"""Bounded mixed-cover candidates. Coarse ranking is never source-edge admission."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _gradient(planes,check):
    mag=np.zeros(planes[0].shape,np.uint8)
    for plane in planes:
        check('v86_coarse_gradient')
        smooth=cv2.GaussianBlur(plane,(3,3),0)
        dx=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,1,0),alpha=.35)
        dy=cv2.convertScaleAbs(cv2.Sobel(smooth,cv2.CV_16S,0,1),alpha=.35)
        np.maximum(mag,cv2.max(dx,dy),out=mag)
    return mag


def _shared_sides(parent,child):
    """A book band shares actual side lines, unlike a separate surrounding mat."""
    p=np.asarray(parent,np.float64);c=np.asarray(child,np.float64)
    e=np.roll(p,-1,axis=0)-p;n=np.stack((-e[:,1],e[:,0]),axis=1)
    n/=np.maximum(np.linalg.norm(n,axis=1)[:,None],1e-9)
    mids=.5*(c+np.roll(c,-1,axis=0));ce=np.roll(c,-1,axis=0)-c
    cn=np.stack((-ce[:,1],ce[:,0]),axis=1);cn/=np.maximum(np.linalg.norm(cn,axis=1)[:,None],1e-9)
    return sum(any(abs(float(n[j]@cn[i]))>.97 and
        abs(float((mids[i]-p[j])@n[j]))<=2. for j in range(4)) for i in range(4))


def _perimeter(mag,q,cutoff):
    # Four longitudinal sections: interrupted ink/glare does not need a closed mask.
    from v62_exterior import coarse_support
    support=coarse_support(mag,q,cutoff)
    return support


def ranked_candidates(image,check,limit=192):
    from v31_detection import _visible_quad
    from v62_exterior import enclosure
    from v86_policy import policy
    settings=policy();h,w=image.shape[:2];ow=min(w,int(limit));oh=max(16,round(h*ow/w))
    check('v86_candidate_downsample')
    if image.ndim==3 and image.shape[2]==2:
        planes=[cv2.resize(a,(ow,oh),interpolation=cv2.INTER_LINEAR) for a in
            (image[:,:,0],image[:,0::2,1],image[:,1::2,1])]
    elif image.ndim==3:
        small=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)
        planes=list(cv2.split(cv2.cvtColor(small,cv2.COLOR_BGR2YCrCb)))
    else:planes=[cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)]
    scale=np.array([w/ow,h/oh]);raw_mag=_gradient(planes,check)
    threshold,_=cv2.threshold(raw_mag,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    pool=[];kernel=np.ones((3,3),np.uint8)
    def add(low,kind):
        try:q=_visible_quad((np.asarray(low)+.5)*scale-.5,image.shape)
        except ValueError:return
        q=((q+.5)/scale-.5).astype(np.float32)
        if any(np.max(np.linalg.norm(q-e['q'],axis=1))<1.5 for e in pool):return
        if len(pool)<20:pool.append(dict(q=q,kind=kind))
    def contours(mag,cutoff,kind,capacity=12):
        check('v86_coarse_contours')
        edge=cv2.morphologyEx((mag>=cutoff).astype(np.uint8)*255,cv2.MORPH_CLOSE,kernel)
        cs,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(cs,key=cv2.contourArea,reverse=True)[:14]:
            if len(pool)>=capacity:return
            check('v86_coarse_polygon')
            if abs(cv2.contourArea(c))<.035*ow*oh:continue
            hull=cv2.convexHull(c);length=cv2.arcLength(hull,True)
            for eps in (.012,.022,.04,.065):
                p=cv2.approxPolyDP(hull,eps*length,True)
                if len(p)==4 and cv2.isContourConvex(p):add(p.reshape(4,2),kind);break
    for cutoff in dict.fromkeys((max(8.,threshold),max(6.,threshold*.65))):contours(raw_mag,cutoff,'raw_YUV')
    def rank_entries():
        for e in pool:
            check('v86_full_cover_rank')
            support=_perimeter(raw_mag,e['q'],threshold);e['support']=support
            area=abs(cv2.contourArea(e['q']))/(ow*oh)
            e['score']=float(support.min()+.35*support.mean()+.08*np.sqrt(area))
        for child in pool:
            for parent in pool:
                if parent is child:continue
                ratio=abs(cv2.contourArea(parent['q']))/max(1.,abs(cv2.contourArea(child['q'])))
                if not 1.12<=ratio<=2.8 or min(parent['support'])<.35:continue
                if enclosure(parent['q'],child['q'],margin=1.) and _shared_sides(parent['q'],child['q'])>=3:
                    # Coarse evidence may change order, never remove an unproved child.
                    child['score']-=.12;parent['score']+=.25
        return sorted(pool,key=lambda e:e['score'],reverse=True)
    yielded=[]
    # Yield cheap contours BEFORE starting Hough/contrast work. A caller can
    # accept candidate0 immediately and never resume this generator's fallback.
    for e in rank_entries()[:4]:
        yielded.append(e['q'].copy())
        yield ((e['q']+.5)*scale-.5).astype(np.float32)
    from v31_detection import _RECOVERY_BUDGET
    budget=_RECOVERY_BUDGET.get();permit=getattr(budget,'can_start_stage',None)
    lines_allowed=permit is None or permit('v86_pooled_segments',.10,.16,admission_cpu_s=.12,admission_wall_s=.18)
    if lines_allowed:
        from v45_color import _line_candidates
        class LineWorkStop(Exception):pass
        began=time.perf_counter();cpu=time.thread_time();combinations=0
        def bounded_check(stage):
            nonlocal combinations
            check(stage)
            if stage=='color_line_quad':combinations+=1
            if combinations>64 or time.thread_time()-cpu>.10 or time.perf_counter()-began>.16:
                raise LineWorkStop()
        try:lines=_line_candidates((raw_mag>=max(6.,threshold*.65)).astype(np.uint8)*255,bounded_check)
        except LineWorkStop:lines=[]
        for q in lines[:6]:add(q,'raw_segments')
    contrast_allowed=permit is None or permit('v86_small_contrast',.015,.030,admission_cpu_s=.12,admission_wall_s=.18)
    if settings['detection_contrast_fallback'] and contrast_allowed and not any(
            _perimeter(raw_mag,e['q'],threshold).min()>=.65 for e in pool):
        check('v86_failure_only_small_contrast')
        enhanced=cv2.createCLAHE(clipLimit=1.6,tileGridSize=(4,4)).apply(planes[0])
        em=_gradient([enhanced]+planes[1:],check)
        t,_=cv2.threshold(em,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
        contours(em,max(6.,t*.65),'small_contrast_proposal_only',20)
    count=0
    for e in rank_entries():
        if any(np.max(np.linalg.norm(e['q']-old,axis=1))<1.5 for old in yielded):continue
        yield ((e['q']+.5)*scale-.5).astype(np.float32)
        count+=1
        if count>=2:return
