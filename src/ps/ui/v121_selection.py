"""Event-only target selection. No camera, DMA or inference worker ownership."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def can_select(manual=False,ai=False):
    return not bool(manual) or bool(ai)

def source_point(point,rect,shape):
    x,y,w,h=rect;px,py=map(float,point);sh,sw=shape[:2]
    if w<=0 or h<=0 or not (x<=px<x+w and y<=py<y+h):return None
    return (min(sw-1.,(px-x)*sw/w),min(sh-1.,(py-y)*sh/h))

def _gray(image):
    if image.ndim==2:g=image
    elif image.shape[2]==2:g=image[:,:,0]
    else:g=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    scale=min(1.,320./max(g.shape));size=(max(1,round(g.shape[1]*scale)),max(1,round(g.shape[0]*scale)))
    return cv2.resize(g,size,interpolation=cv2.INTER_AREA),np.array([size[0]/image.shape[1],size[1]/image.shape[0]],np.float32)

def map_point(selection,image,sequence=None):
    """One bounded source-to-current mapping; normalized pixels aren't motion."""
    point=np.asarray(selection['point'],np.float32);old=selection['image']
    if old.shape!=image.shape:raise ValueError('点选后输入尺寸已改变，请重新点选')
    if np.shares_memory(old,image):return tuple(map(float,point)),'same_source'
    a,scale=_gray(old);b,_=_gray(image)
    difference=cv2.absdiff(a,b)
    if float(difference.max())<=10. and float(difference.mean())<=1.5:
        return tuple(map(float,point)),'static_image'
    p=point*scale;h,w=a.shape
    radius=max(40,int(min(h,w)*.28));mask=np.zeros_like(a)
    cv2.rectangle(mask,(max(0,int(p[0])-radius),max(0,int(p[1])-radius)),
        (min(w-1,int(p[0])+radius),min(h-1,int(p[1])+radius)),255,-1)
    features=cv2.goodFeaturesToTrack(a,64,.01,5,mask=mask,blockSize=5)
    if features is None or len(features)<6:raise ValueError('点选目标移动后无法可靠对齐，请重新点选')
    nxt,status,_=cv2.calcOpticalFlowPyrLK(a,b,features,None,winSize=(21,21),maxLevel=3)
    if nxt is None:raise ValueError('点选位置对齐失败')
    back,back_status,_=cv2.calcOpticalFlowPyrLK(b,a,nxt,None,winSize=(21,21),maxLevel=3)
    if back is None:raise ValueError('点选位置反向对齐失败')
    keep=(status.ravel()!=0)&(back_status.ravel()!=0)&(np.linalg.norm(back-features,axis=2).ravel()<=1.5)
    before=features.reshape(-1,2)[keep];after=nxt.reshape(-1,2)[keep]
    if len(before)<6:raise ValueError('点选目标对应点不足')
    matrix,inliers=cv2.estimateAffinePartial2D(before,after,method=cv2.RANSAC,ransacReprojThreshold=2.,maxIters=300)
    if matrix is None or inliers is None or int(inliers.sum())<6:raise ValueError('点选目标运动不一致')
    chosen=before[inliers.ravel()!=0]
    if cv2.pointPolygonTest(cv2.convexHull(chosen),tuple(map(float,p)),True)<-12.:
        raise ValueError('点选位置缺少邻近运动支持')
    moved=(matrix[:,:2]@p+matrix[:,2])/scale
    if not np.isfinite(moved).all() or not (0<=moved[0]<old.shape[1] and 0<=moved[1]<old.shape[0]):
        raise ValueError('点选目标已离开画面')
    return tuple(map(float,moved)),'local_FB_affine'

def proof(selection,point,sequence,method,**detail):
    return dict(request_id=selection['request_id'],single_target=True,source_sequence=int(sequence),
        selected_point=list(map(float,point)),mapping=method,**detail)

def components(binary):
    """Reuse the existing shape gates on each isolated component, never largest again."""
    from v98_ai_geometry import quad_from_mask
    n,labels,stats,_=cv2.connectedComponentsWithStats(np.asarray(binary,np.uint8),8)
    result=[]
    for i in range(1,n):
        if not binary.size*.02<=int(stats[i,cv2.CC_STAT_AREA])<=binary.size*.90:continue
        component=(labels==i)
        q,fit=quad_from_mask(component)
        if q is not None:result.append(dict(label=i,quad=q,fit=float(fit),component=component))
    return result,labels

def select_mask(binary,context=None,source=None):
    """Existing mask only. At most one low-res split and one exterior proof."""
    items,labels=components(binary);point=None if context is None else context['point']
    if not items:return None,0.,dict(reason='no_plane')
    if point is not None:
        sh,sw=context['source_shape'][:2]
        mp=(float(point[0])*binary.shape[1]/sw,float(point[1])*binary.shape[0]/sh)
        px,py=map(int,mp)
        if not (0<=py<binary.shape[0] and 0<=px<binary.shape[1]):return None,0.,dict(reason='point_outside')
        chosen=[it for it in items if labels[py,px]==it['label']]
        if len(chosen)!=1:return None,0.,dict(reason='clicked_component_missing',candidate_count=len(items))
        item=chosen[0]
    elif len(items)>1:
        return None,0.,dict(reason='multiple_targets',candidate_count=len(items))
    else:item=items[0];mp=None
    # Small opening proposes bridge separation only at AI completion, not on
    # tracking frames. Never replace the original component unconditionally.
    opened=cv2.morphologyEx(item['component'].astype(np.uint8),cv2.MORPH_OPEN,np.ones((7,7),np.uint8))
    parts,_=components(opened)
    if len(parts)>1:
        if mp is None:return None,0.,dict(reason='merged_targets',candidate_count=len(parts))
        selected=[it for it in parts if cv2.pointPolygonTest(it['quad'],mp,True)>=0.]
        if len(selected)!=1 or source is None:return None,0.,dict(reason='merged_targets',candidate_count=len(parts))
        part=selected[0];q=part['quad']*np.array([source.shape[1]/binary.shape[1],source.shape[0]/binary.shape[0]],np.float32)
        try:
            from v87_acquire import prove_target
            checked,detail=prove_target(source,q,int(context.get('detection_limit',640)),int(context.get('tracking_limit',320)),source,
                check=context.get('check'))
            checked=np.asarray(checked,np.float32)
            if cv2.pointPolygonTest(checked,tuple(map(float,point)),True)<0:raise ValueError('split excluded tap')
            intersection=cv2.intersectConvexConvex(q,checked)[0]
            union=abs(cv2.contourArea(q))+abs(cv2.contourArea(checked))-intersection
            if intersection/max(1.,union)<.70:raise ValueError('physical proof changed split target')
            # Source pixels, converted back once for the ordinary finish scaler.
            q=checked/np.array([source.shape[1]/binary.shape[1],source.shape[0]/binary.shape[0]],np.float32)
        except (ValueError,cv2.error) as exc:
            return None,0.,dict(reason='merged_edges_unproved',candidate_count=len(parts),detail=str(exc)[:160])
        return q,part['fit'],dict(reason='clicked_split',candidate_count=len(parts),component=part['label'],physical_split_proved=True)
    return item['quad'],item['fit'],dict(reason='clicked_component' if mp is not None else 'single_component',
        candidate_count=len(items),component=item['label'],mask_point=mp,physical_split_proved=False)
