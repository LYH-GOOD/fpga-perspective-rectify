"""Reuse motion masks and existing CPU checks; no device access or new native ABI."""
from pathlib import Path
import hashlib
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class MotionWorkspace:
    def __init__(self):
        self.delta=np.empty((100,2),np.float32);self.square=np.empty_like(self.delta)
        self.fb=np.empty(100,np.float32);self.good=np.empty(100,np.bool_)
        self.finite=np.empty((100,2),np.bool_);self.flag=np.empty(100,np.bool_)
    def filter(self,p,forward,back,status,reverse):
        n=len(p);fb=self.fb[:n];good=self.good[:n];flag=self.flag[:n]
        delta=self.delta[:n];square=self.square[:n];finite=self.finite[:n]
        np.subtract(back.reshape(-1,2),p.reshape(-1,2),out=delta)
        np.multiply(delta,delta,out=square);np.add(square[:,0],square[:,1],out=fb);np.sqrt(fb,out=fb)
        np.less(fb,.8,out=good);np.isfinite(fb,out=flag);np.logical_and(good,flag,out=good)
        np.isfinite(forward.reshape(-1,2),out=finite)
        np.logical_and(finite[:,0],finite[:,1],out=flag);np.logical_and(good,flag,out=good)
        np.not_equal(status.ravel(),0,out=flag);np.logical_and(good,flag,out=good)
        np.not_equal(reverse.ravel(),0,out=flag);np.logical_and(good,flag,out=good)
        return fb,good


def distributed(points,source_quad,scale):
    if points is None or len(points)<8:return False
    # Match legacy input rounding before hull area and nearest-side checks.
    small=np.asarray((source_quad+.5)/scale-.5,np.float32)
    from v31_native import spatial_support
    result=spatial_support(points,small)
    if result is not None:return bool(result)
    from v31_tracking import _spatial_support
    return bool(_spatial_support(points,small,'legacy'))


def valid_quad(quad,shape,previous):
    from v31_native import quad_valid
    quad=np.asarray(quad,np.float32);previous=np.asarray(previous,np.float32)
    result=quad_valid(quad,shape,previous)
    if result is not None:return bool(result)
    from v31_tracking import _valid
    return bool(_valid(quad,shape,previous,'legacy'))
