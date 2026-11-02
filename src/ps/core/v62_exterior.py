"""Bounded coarse outer-frame hypotheses. CPU RAM only, never an admission."""
from pathlib import Path
import hashlib
import cv2
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def enclosure(parent,child,margin=0.):
    """A larger aligned current quadrilateral may enclose a printed/video inset.

    Containment alone is insufficient: retain three matching side directions
    and bound the area ratio. No expected hue, brightness or portrait is used.
    """
    a=np.asarray(parent,np.float32);b=np.asarray(child,np.float32)
    if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():return False
    aa=abs(cv2.contourArea(a));ab=abs(cv2.contourArea(b))
    if ab<=1 or not 1.12<=aa/ab<=6.:return False
    if any(cv2.pointPolygonTest(a,tuple(float(v) for v in p),True)<-margin for p in b):return False
    da=np.roll(a,-1,axis=0)-a;db=np.roll(b,-1,axis=0)-b
    na=np.linalg.norm(da,axis=1);nb=np.linalg.norm(db,axis=1)
    if min(na.min(),nb.min())<4:return False
    ua=da/na[:,None];ub=db/nb[:,None]
    return any(np.count_nonzero(np.abs(np.sum(ua*np.roll(ub,k,axis=0),axis=1))>=.94)>=3 for k in range(4))

def coarse_support(magnitude,quad,cutoff):
    """Cheap current 20-position perimeter evidence for ranking, not proof."""
    q=np.asarray(quad,np.float64);edge=np.roll(q,-1,axis=0)-q
    length=np.linalg.norm(edge,axis=1)
    if length.min()<4:return np.zeros(4,np.float64)
    normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
    base=q[:,None,:]+np.linspace(.08,.92,20)[None,:,None]*edge[:,None,:]
    xy=base[:,:,None,:]+np.linspace(-1.5,1.5,5)[None,None,:,None]*normal[:,None,None,:]
    h,w=magnitude.shape
    x=np.clip(np.rint(xy[...,0]).astype(np.int32),0,w-1)
    y=np.clip(np.rint(xy[...,1]).astype(np.int32),0,h-1)
    peaks=np.max(magnitude[y,x],axis=2)
    return np.mean(peaks>=max(6.,cutoff*.8),axis=1)

def rank_pool(pool,magnitude,cutoff,check):
    if not pool:return []
    entries=[];h,w=magnitude.shape
    for q,source in pool:
        check('outer_hypothesis_perimeter')
        support=coarse_support(magnitude,q,cutoff)
        area=abs(cv2.contourArea(q))/float(w*h)
        entries.append(dict(quad=q,source=source,support=support,
            score=float(support.min()+.35*support.mean()+.12*np.sqrt(area)),parents=[]))
    for i,e in enumerate(entries):
        for j,p in enumerate(entries):
            if i==j or p['support'].min()<.55:continue
            if enclosure(p['quad'],e['quad'],margin=1.5):e['parents'].append(j)
    # Test plausible enclosures first; tiny insets cannot win merely because
    # playing content has a very sharp gradient. Every result still needs real
    # source-resolution four-edge refinement in the detector.
    order=sorted(range(len(entries)),key=lambda i:(bool(entries[i]['parents']),-entries[i]['score']))
    return [entries[i] for i in order]

def ranked_exterior_candidates(image,check,limit=192):
    """At most 12 coarse hypotheses/pass before any expensive admission.

    Reuses the original Y/U/V downsample and gradient front end. Pooling only
    low-resolution polygons permits containment-aware selection without a
    second full-frame color conversion or source-sized mask.
    """
    h,w=image.shape[:2];ow=min(w,int(limit));oh=max(16,round(h*ow/w))
    if image.ndim==3 and image.shape[2]==2:
        from v31_pixels import require_yuyv
        require_yuyv(image);check('fast_YUV_downsample')
        planes=[cv2.resize(image[:,:,0],(ow,oh),interpolation=cv2.INTER_LINEAR),
                cv2.resize(image[:,0::2,1],(ow,oh),interpolation=cv2.INTER_LINEAR),
                cv2.resize(image[:,1::2,1],(ow,oh),interpolation=cv2.INTER_LINEAR)]
    elif image.ndim==3:
        check('fast_color_downsample')
        small=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)
        planes=list(cv2.split(cv2.cvtColor(small,cv2.COLOR_BGR2YCrCb)))
    else:
        check('fast_Y_downsample')
        planes=[cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)]
    check('fast_YUV_gradients');magnitude=np.zeros((oh,ow),np.uint8)
    for i,plane in enumerate(planes):
        smooth=cv2.GaussianBlur(plane,(3,3),0)
        dx=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,1,0,ksize=3),alpha=.25 if i==0 else .4375)
        dy=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,0,1,ksize=3),alpha=.25 if i==0 else .4375)
        np.maximum(magnitude,cv2.max(dx,dy),out=magnitude)
    threshold,_=cv2.threshold(magnitude,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    kernel=np.ones((3,3),np.uint8);seen=[]
    from v31_detection import _visible_quad
    scale=np.array([w/ow,h/oh],np.float64)
    for cutoff in dict.fromkeys((max(8,int(threshold)),max(6,int(threshold*.65)))):
        check('fast_YUV_closed_edges')
        edges=cv2.morphologyEx((magnitude>=cutoff).astype(np.uint8)*255,cv2.MORPH_CLOSE,kernel)
        check('fast_YUV_contours')
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        pool=[]
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:16]:
            check('fast_YUV_polygon')
            if abs(cv2.contourArea(contour))<.035*ow*oh:continue
            hull=cv2.convexHull(contour);perimeter=cv2.arcLength(hull,True)
            coarse=None
            for eps in (.012,.022,.04,.065):
                polygon=cv2.approxPolyDP(hull,eps*perimeter,True)
                if len(polygon)!=4 or not cv2.isContourConvex(polygon):continue
                try:q=_visible_quad((polygon.reshape(4,2)+.5)*scale-.5,image.shape)
                except ValueError:continue
                coarse=q;break
            if coarse is None:continue
            if any(np.max(np.linalg.norm(coarse-old,axis=1))<3. for old in seen):continue
            if any(np.max(np.linalg.norm(coarse-old[1],axis=1))<3. for old in pool):continue
            low=((coarse+.5)/scale-.5).astype(np.float32)
            pool.append((low,coarse))
            if len(pool)>=12:break
        for entry in rank_pool(pool,magnitude,cutoff,check):
            q=entry['source'];seen.append(q.copy());yield q

def proven_outer_parent(candidate,proven):
    """Reject an inset only when a larger CURRENT source four-edge fit exists."""
    for q in proven:
        if enclosure(q,candidate,margin=2.):
            return dict(enclosed=True,outer_corners=np.asarray(q).tolist(),
                reason='larger_source_primary_outer_blocks_inset',coarse_rank_is_not_proof=True,independent_CURRENT_proof_not_claimed=True)
    return None
