"""Failure-only small YUV line hypotheses; no full-color preparation or IO."""
from pathlib import Path
import hashlib,threading
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LOCAL=threading.local()


def line_candidates(image,check):
    from v45_color import _line_candidates
    from v62_exterior import rank_pool
    h,w=image.shape[:2];ow=min(w,160);oh=max(16,round(h*ow/w))
    shape=(oh,ow)
    if getattr(_LOCAL,'shape',None)!=shape:
        _LOCAL.shape=shape;_LOCAL.plane=np.empty(shape,np.uint8)
        _LOCAL.smooth=np.empty(shape,np.uint8);_LOCAL.magnitude=np.empty(shape,np.uint8)
    mag=_LOCAL.magnitude;mag.fill(0)
    if image.ndim==3 and image.shape[2]==2:
        planes=(image[:,:,0],image[:,0::2,1],image[:,1::2,1])
    elif image.ndim==2:planes=(image,)
    else:
        check('v85_small_line_color')
        small=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_LINEAR)
        planes=cv2.split(cv2.cvtColor(small,cv2.COLOR_BGR2YCrCb))
    for plane in planes:
        check('v85_small_line_gradient')
        cv2.resize(plane,(ow,oh),dst=_LOCAL.plane,interpolation=cv2.INTER_LINEAR)
        cv2.GaussianBlur(_LOCAL.plane,(3,3),0,dst=_LOCAL.smooth)
        dx=cv2.convertScaleAbs(cv2.Sobel(_LOCAL.smooth,cv2.CV_16S,1,0,ksize=3),alpha=.35)
        dy=cv2.convertScaleAbs(cv2.Sobel(_LOCAL.smooth,cv2.CV_16S,0,1,ksize=3),alpha=.35)
        np.maximum(mag,cv2.max(dx,dy),out=mag)
    check('v85_small_line_threshold')
    threshold,_=cv2.threshold(mag,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    edges=(mag>=max(8.,threshold*.65)).astype(np.uint8)*255
    proposals=_line_candidates(edges,check)
    # Existing opposite-side geometry rejects arbitrary wood-grain crossings;
    # all proposals still require actual full-source64/independent24 admission.
    pool=[(q,q) for q in proposals[:12]]
    scale=np.array([w/ow,h/oh],np.float64)
    for entry in rank_pool(pool,mag,threshold,check)[:2]:
        yield ((entry['quad']+.5)*scale-.5).astype(np.float32)
