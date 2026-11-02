"""Bounded ownership and exact geometry reuse; no device operations here."""
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import hashlib,threading
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class OutputReference:
    """One explicit reference to a completed, cache-synchronized output slot."""
    def __init__(self,pool,index,array):
        self.pool=pool;self.index=index;self.array=array;self.released=False

    def retain(self,out):
        with self.pool.lock:
            if self.released or self.pool.closed:raise RuntimeError('Output reference retired')
            if (out.shape!=self.array.shape or out.dtype!=self.array.dtype or
                    out.strides!=self.array.strides or out.ctypes.data!=self.array.ctypes.data):
                raise ValueError('Output reference does not own this completed frame')
            self.pool.counts[self.index]+=1
            return OutputReference(self.pool,self.index,self.array)

    def release(self):
        with self.pool.lock:
            if not self.released:
                self.pool.counts[self.index]-=1;self.released=True
                if self.pool.counts[self.index]<0:raise RuntimeError('Output reference underflow')

    def __del__(self):
        # Interrupted publication must not strand a reference whose temporary
        # owner never reached the normal explicit-release path.
        try:self.release()
        except BaseException:pass


class OutputSlots:
    """Three slots: one DMA writer, one HDMI reader and one pending output.

    Allocation/free remain on the P1 owner. HDMI may only retain/release a
    completed slot. No physical buffer can be reused while a reader holds it.
    """
    def __init__(self,allocate,capacity):
        self.lock=threading.RLock();self.counts=[];self.buffers=[];self.closed=False
        try:
            for _ in range(3):
                self.buffers.append(allocate(shape=(int(capacity)*4,),dtype=np.uint8));self.counts.append(0)
        except BaseException:
            for buffer in self.buffers:buffer.freebuffer()
            self.buffers.clear();raise

    def acquire(self,width,height):
        with self.lock:
            if self.closed:raise RuntimeError('Output pool closed')
            index=next((i for i,n in enumerate(self.counts) if n==0),None)
            if index is None:raise RuntimeError('All output slots retained; ownership invariant broken')
            buffer=self.buffers[index]
            if width*height*4>buffer.nbytes:raise ValueError('Output pool capacity exceeded')
            self.counts[index]=1
            return OutputReference(self,index,buffer[:width*height*4].reshape(height,width,4))

    def close(self):
        with self.lock:
            if self.closed:return
            if any(self.counts):raise RuntimeError('HDMI still references output slots: '+str(self.counts))
            for buffer in self.buffers:buffer.freebuffer()
            self.buffers.clear();self.closed=True


_GEOMETRY=ContextVar('p11_v90_exact_geometry_transaction',default=None)


def geometry_transaction(function):
    """Memoize geometry only during one synchronous call, including nested calls."""
    @wraps(function)
    def run(*args,**kwargs):
        if _GEOMETRY.get() is not None:return function(*args,**kwargs)
        workspace=dict(entries={},calls=0,hits=0)
        token=_GEOMETRY.set(workspace)
        try:return function(*args,**kwargs)
        finally:
            if args:
                args[0]._v90_geometry_stats=dict(calls=workspace['calls'],hits=workspace['hits'],
                    entries=len(workspace['entries']),scope='one synchronous transaction; geometry only',
                    frame_index=getattr(args[0],'_update_index',None),function=function.__name__,
                    sampling_reused=False,FB_checks_skipped=False)
            _GEOMETRY.reset(token)
    return run


def pair_geometry(first,second):
    """Exact original float64 line/corner arithmetic; never a proof receipt."""
    a=np.asarray(first,np.float64);b=np.asarray(second,np.float64)
    if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return 'invalid',None,None
    workspace=_GEOMETRY.get();key=None
    if workspace is not None:
        workspace['calls']+=1;key=tuple(sorted((a.tobytes(),b.tobytes())))
        cached=workspace['entries'].get(key)
        if cached is not None:
            workspace['hits']+=1;return cached
    values=[]
    for p,q in ((a,b),(b,a)):
        edges=np.roll(p,-1,axis=0)-p;length=np.linalg.norm(edges,axis=1)
        if np.min(length)<4:return 'degenerate',None,None
        normal=np.stack((-edges[:,1],edges[:,0]),axis=1)/length[:,None]
        points=q[:,None,:]+np.array([.15,.5,.85])[None,:,None]*(np.roll(q,-1,axis=0)-q)[:,None,:]
        values.append(float(np.max(np.abs(np.sum((points-p[:,None,:])*normal[:,None,:],axis=2)))))
    result=(None,max(values),float(np.max(np.linalg.norm(a-b,axis=1))))
    if workspace is not None and len(workspace['entries'])<64:workspace['entries'][key]=result
    return result


class CandidateAttempts:
    """Same-frame exact duplicate suppression; no approximate/negative cache.

    The detector's existing <2px rejection remains. This additionally recognizes
    identical proposals from different families/start vertices/winding. New
    source frames always start empty and receive all current strict proofs.
    """
    def __init__(self):self.seen=set();self.repeats=0;self.unique=0

    def repeated(self,quad,strategy):
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return False
        variants=[]
        for packed in (q.tobytes(),q[::-1].tobytes()):
            variants.extend(packed[8*i:]+packed[:8*i] for i in range(4))
        # Color-first and Y-first are different transactions even if their
        # geometry is identical; neither may suppress the other.
        key=(bool(strategy),min(variants))
        if key in self.seen:self.repeats+=1;return True
        if len(self.seen)<256:self.seen.add(key)
        self.unique+=1;return False

