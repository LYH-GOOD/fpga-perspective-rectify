"""Bounded color exterior proposals / raw chroma observations; no device access.

YUYV U/V coordinates use pair centers. No fixed hue, white foreground or RGB
clipping is used to prove an exterior. Every proposal still needs four lines.
"""
from pathlib import Path
import hashlib,itertools,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def vector_profiles(image,x,y):
    """Return [Y, 1.75 U, 1.75 V] differences without CSC clipping."""
    mx=np.ascontiguousarray(x,np.float32);my=np.ascontiguousarray(y,np.float32)
    if image.ndim==2:
        return cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)[...,None].astype(np.float32)
    if image.shape[2]==2:
        from v31_pixels import require_yuyv
        require_yuyv(image)
        from v87_v74_native import packed_vector_profiles
        direct=packed_vector_profiles(image,mx,my)
        if direct is not None:return direct
        h,w=image.shape[:2];pairs=image.reshape(h,w//2,4)
        ux=np.ascontiguousarray((mx-.5)*.5,np.float32)
        yv=cv2.remap(image[:,:,0],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        u=cv2.remap(pairs[:,:,1],ux,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
        v=cv2.remap(pairs[:,:,3],ux,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
        return np.stack((yv,1.75*u,1.75*v),axis=-1)
    bgr=cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    yv=.114*bgr[:,:,0]+.587*bgr[:,:,1]+.299*bgr[:,:,2]
    return np.stack((yv,1.75*.564*(bgr[:,:,0]-yv),1.75*.713*(bgr[:,:,2]-yv)),axis=-1)


def chroma_gray(image,shape,channel,out):
    """Only an optional LK scalar observation; source lease stays owned by caller."""
    from v31_pixels import require_yuyv
    require_yuyv(image)
    if channel not in ('U','V') or out.dtype!=np.uint8 or out.shape!=tuple(shape):
        raise ValueError('Invalid chroma LK workspace')
    h,w=image.shape[:2];pairs=image.reshape(h,w//2,4)
    plane=pairs[:,:,1 if channel=='U' else 3]
    cv2.resize(plane,(shape[1],shape[0]),dst=out,interpolation=cv2.INTER_LINEAR)
    # OpenCV supports in-place GaussianBlur; one small scalar plane, no RGB frame.
    cv2.GaussianBlur(out,(3,3),0,dst=out)
    return out


def _candidate(q,shape):
    from v8_geometry import order_corners
    h,w=shape;q=order_corners(q)
    if np.any(q<2) or np.any(q[:,0]>w-3) or np.any(q[:,1]>h-3):return None
    area=abs(cv2.contourArea(q));edges=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edges,axis=1)
    if area<.035*w*h or min(length)<max(8.,.04*min(h,w)):return None
    sine=np.abs(np.cross(edges,np.roll(edges,1,axis=0)))/(length*np.roll(length,1))
    if min(sine)<.20:return None
    return q


def _mask_candidates(lab,checkpoint):
    """Contrast to a robust frame border, including mixed ink + white cover."""
    h,w=lab.shape[:2];band=max(3,min(h,w)//25)
    border=np.concatenate((lab[:band].reshape(-1,3),lab[-band:].reshape(-1,3),
                           lab[band:-band,:band].reshape(-1,3),lab[band:-band,-band:].reshape(-1,3)))
    center=np.median(border,axis=0);spread=np.maximum(8.,np.median(np.abs(border-center),axis=0)*1.4826)
    weight=np.clip(12./spread,.35,1.5);weight[0]*=.65
    delta=(lab.astype(np.float32)-center)*weight
    distance=np.clip(np.sqrt(np.sum(delta*delta,axis=2)),0,255).astype(np.uint8)
    checkpoint('color_border_distance')
    otsu,_=cv2.threshold(distance,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    masks=[]
    for threshold in (max(12.,otsu),max(10.,otsu*.65)):
        mask=(distance>threshold).astype(np.uint8)*255
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((7,7),np.uint8))
        masks.append(mask)
    candidates=[]
    for mask in masks:
        checkpoint('color_mask_contours')
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:8]:
            hull=cv2.convexHull(contour);area=abs(cv2.contourArea(hull))
            if area<.035*w*h:continue
            # Hull can bridge ink/color breaks; this is never a final admission.
            for eps in (.012,.022,.04,.065):
                poly=cv2.approxPolyDP(hull,eps*cv2.arcLength(hull,True),True)
                if len(poly)!=4:continue
                try:q=_candidate(poly,(h,w))
                except ValueError:continue
                if q is not None and abs(cv2.contourArea(q))/area>=.82:candidates.append(q);break
    return candidates


def _line_candidates(edges,checkpoint):
    """Combine bounded opposite line pairs when an exterior contour is broken."""
    h,w=edges.shape;checkpoint('color_hough_segments')
    segments=cv2.HoughLinesP(edges,1,np.pi/180.,max(18,min(h,w)//10),
                            minLineLength=max(16,min(h,w)//6),maxLineGap=max(6,min(h,w)//14))
    checkpoint('color_hough_segments_done')
    if segments is None:return []
    lines=[]
    raw=segments.reshape(-1,4).astype(np.float64)
    order=np.argsort(np.linalg.norm(raw[:,2:]-raw[:,:2],axis=1))[::-1][:64]
    for i in order:
        a,b=raw[i,:2],raw[i,2:];d=b-a;length=float(np.linalg.norm(d))
        normal=np.array([-d[1],d[0]])/length;rho=float(normal@a)
        if rho<0:normal=-normal;rho=-rho
        if any(abs(float(normal@n))>.992 and abs(rho-(r if normal@n>0 else -r))<3. for n,r,_,_ in lines):continue
        lines.append((normal,rho,length,np.stack((a,b))))
        if len(lines)==24:break
    if len(lines)<4:return []
    # Opposite sides may converge; no right-angle or fixed aspect assumption.
    pairs=[]
    for a,b in itertools.combinations(range(len(lines)),2):
        n1,r1,l1,_=lines[a];n2,r2,l2,_=lines[b];dot=float(n1@n2)
        if abs(dot)<.75:continue
        if abs(r1-(r2 if dot>0 else -r2))<max(10.,.06*min(h,w)):continue
        pairs.append((a,b,l1+l2))
    pairs=sorted(pairs,key=lambda p:p[2],reverse=True)[:48]
    candidates=[]
    for first,second in itertools.combinations(pairs,2):
        if len({first[0],first[1],second[0],second[1]})!=4:continue
        if abs(float(lines[first[0]][0]@lines[second[0]][0]))>.85:continue
        checkpoint('color_line_quad')
        a,b=first[:2];c,d=second[:2];corners=[]
        for i,j in ((a,c),(a,d),(b,d),(b,c)):
            n1,r1=lines[i][:2];n2,r2=lines[j][:2];den=n1[0]*n2[1]-n1[1]*n2[0]
            if abs(den)<.20:break
            corners.append([(r1*n2[1]-n1[1]*r2)/den,(n1[0]*r2-r1*n2[0])/den])
        if len(corners)!=4:continue
        try:q=_candidate(np.asarray(corners,np.float32),(h,w))
        except ValueError:continue
        if q is None:continue
        # Every proposed side must have an actual segment spanning its interior.
        good=True
        for i in (a,b,c,d):
            normal,rho,_,segment=lines[i];distance=np.abs(q@normal-rho)
            ids=np.argsort(distance)[:2];p1,p2=q[ids];vector=p2-p1;length=float(np.linalg.norm(vector))
            t=(segment-p1)@vector/max(1e-9,length*length)
            overlap=max(0.,min(1.,float(max(t)))-max(0.,float(min(t))))
            if overlap<.40:good=False;break
        if good and not any(np.max(np.linalg.norm(q-old,axis=1))<3. for old in candidates):candidates.append(q)
        if len(candidates)>=32:break
    return candidates


def rectangle_proposals(color,source_shape,checkpoint=lambda stage:None,max_candidates=12,include_lines=True):
    """Candidate union only; closed gradients, border contrast and long line pairs."""
    from v8_geometry import order_corners
    begin=time.perf_counter();h,w=color.shape[:2];H,W=source_shape[:2]
    if color.dtype!=np.uint8 or color.ndim!=3 or color.shape[2]!=3:raise ValueError('Expected small BGR proposal image')
    checkpoint('multicolor_gradient_prepare')
    smooth=cv2.GaussianBlur(color,(3,3),0);lab=cv2.cvtColor(smooth,cv2.COLOR_BGR2LAB)
    channels=(lab[:,:,0],lab[:,:,1],lab[:,:,2]);union=np.zeros((h,w),np.uint8)
    for plane in channels:
        checkpoint('multicolor_channel_edges');union|=cv2.Canny(plane,12,40)
    candidates=_mask_candidates(lab,checkpoint)
    # Closed contours and convex hulls are proposals, not 75% filled-color masks.
    for kernel in (3,5):
        checkpoint('multicolor_contours')
        edges=cv2.morphologyEx(union,cv2.MORPH_CLOSE,np.ones((kernel,kernel),np.uint8))
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:20]:
            hull=cv2.convexHull(contour);area=abs(cv2.contourArea(hull))
            if area<.035*w*h:continue
            for epsilon in (.012,.025,.045,.065):
                poly=cv2.approxPolyDP(hull,epsilon*cv2.arcLength(hull,True),True)
                if len(poly)!=4:continue
                try:q=_candidate(poly,(h,w))
                except ValueError:continue
                if q is not None and abs(cv2.contourArea(q))/area>.85:candidates.append(q);break
    if include_lines:candidates.extend(_line_candidates(union,checkpoint))
    unique=[]
    for q in sorted(candidates,key=lambda q:abs(cv2.contourArea(q)),reverse=True):
        q=(q+.5)*[W/w,H/h]-.5
        if not any(np.max(np.linalg.norm(q-old,axis=1))<4. for old in unique):unique.append(q.astype(np.float32))
        if len(unique)>=max_candidates:break
    return unique


def iter_recovery_rectangles(color,source_shape,checkpoint,allow_lines,max_candidates=8):
    """Yield cheap proposals for immediate admission BEFORE bounded line fallback.

    Only budgeted recovery uses this scheduler. Startup and final source64/current24
    validation keep their existing path. Coarse lines never constitute a proof.
    """
    seen=[]
    for q in rectangle_proposals(color,source_shape,checkpoint,max_candidates,include_lines=False):
        seen.append(q);yield q
    if len(seen)>=max_candidates or not allow_lines():return
    checkpoint('bounded_color_line_prepare')
    h,w=color.shape[:2];scale=min(1.,160./max(h,w))
    small=cv2.resize(color,(max(2,round(w*scale)),max(2,round(h*scale))),interpolation=cv2.INTER_LINEAR) if scale<1. else color
    lab=cv2.cvtColor(cv2.GaussianBlur(small,(3,3),0),cv2.COLOR_BGR2LAB)
    union=np.zeros(small.shape[:2],np.uint8)
    for k in range(3):
        checkpoint('bounded_color_line_channel');union|=cv2.Canny(lab[:,:,k],12,40)
    # Recheck immediately before the non-preemptible OpenCV call.
    if not allow_lines():return
    H,W=source_shape[:2];lh,lw=union.shape
    for local in _line_candidates(union,checkpoint):
        q=((local+.5)*[W/lw,H/lh]-.5).astype(np.float32)
        if any(np.max(np.linalg.norm(q-old,axis=1))<4. for old in seen):continue
        seen.append(q);yield q
        if len(seen)>=max_candidates:return
