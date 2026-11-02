"""CPU-only PS workspaces and lazy current-frame diagnostic materialization."""
from pathlib import Path
from collections.abc import Mapping
import hashlib,struct,threading,time,weakref
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class EdgeEvidence(Mapping):
    """Immutable 168-byte native evidence snapshot; fields decoded on demand."""
    _keys=('valid','edge_support','edge_polarity','refined_corners','supported_edges',
        'median_edge_shift','edge_rms','max_edge_rms','edge_backend')
    def __init__(self,stats,max_rms):
        self.raw=stats.tobytes();self.max_rms=float(max_rms);self.values={}
    def __len__(self):return len(self._keys)
    def __iter__(self):return iter(self._keys)
    def __getitem__(self,name):
        if name in self.values:return self.values[name]
        if name=='edge_support':value=struct.unpack_from('=4d',self.raw,0)
        elif name=='edge_rms':value=struct.unpack_from('=4d',self.raw,12*8)
        elif name=='edge_polarity':value=tuple(map(int,struct.unpack_from('=4d',self.raw,4*8)))
        elif name=='valid':value=bool(struct.unpack_from('=d',self.raw,20*8)[0])
        elif name=='refined_corners':value=int(struct.unpack_from('=d',self.raw,16*8)[0])
        elif name=='supported_edges':value=int(struct.unpack_from('=d',self.raw,17*8)[0])
        elif name=='median_edge_shift':
            shifts=sorted(struct.unpack_from('=4d',self.raw,8*8));value=(shifts[1]+shifts[2])*.5
        elif name=='max_edge_rms':value=self.max_rms
        elif name=='edge_backend':value='cpp_edges_gate_motion_context'
        else:raise KeyError(name)
        self.values[name]=value;return value


def decode_light_edges(work):
    began=time.perf_counter();cpu=time.thread_time()
    np.copyto(work.result32,work.result,casting='unsafe')
    g=work.gate
    gate=dict(reliable=bool(g[0]),min_support=float(g[1]),max_rms=float(g[2]),
        prediction_correction=float(g[3]),polarity_flips=int(g[4]),radius=float(g[5]))
    evidence=EdgeEvidence(work.stats,g[2])
    result=(work.result32,evidence,gate,tuple(map(float,work.motion)) if gate['reliable'] else None)
    prior=work.decode_timing
    work.decode_timing=(prior[0]+time.perf_counter()-began,prior[1]+time.thread_time()-cpu)
    return result


def observe_yuyv_bound(work,image,scratch,rows,out,drift,radius,mode,library):
    """Reuse pointers to private, already-validated workspaces only.

    The caller retains all original layout/alias checks. The leased camera
    pointer is obtained afresh on every call and is never retained here.
    """
    cache=getattr(work,'_light_bindings',None)
    if cache is None:cache={};work._light_bindings=cache
    key=(id(library),id(scratch),id(rows),id(out),id(drift))
    binding=cache.get(key)
    if binding is None:
        if len(cache)>=6:cache.clear()
        references=(scratch,rows,out,work.predicted,work.previous,work.anchor,drift,work.polarity,
            work.result,work.stats,work.motion,work.gate,work.times)
        pointers=tuple(a.ctypes.data for a in references)
        binding=(library,library.p11_yuyv_observe_edges,references,pointers[:8],pointers[8:])
        cache[key]=binding
    return binding[1](image.ctypes.data,image.shape[1],image.shape[0],image.strides[0],int(mode),
        *binding[3],float(radius),*binding[4])


def materialize_tracking(track):
    """Called immediately by the same PS prepare, before the next update."""
    factory=track.pop('_diagnostics',None)
    def owned(value):
        if isinstance(value,Mapping):return {k:owned(v) for k,v in value.items()}
        if isinstance(value,list):return [owned(v) for v in value]
        if isinstance(value,tuple):return tuple(owned(v) for v in value)
        if isinstance(value,np.ndarray):
            result=value.copy();result.flags.writeable=False;return result
        return value
    return owned(factory() if factory is not None else track)


def evidence_snapshot(evidence):
    """A native immutable evidence snapshot already owns its bytes."""
    return evidence if isinstance(evidence,EdgeEvidence) else dict(evidence)


def _destroy_plan(library,pointer):library.p11_v70_plan_destroy(pointer)


class PlanBatchWorkspace:
    """One sequential PS producer; no frame pixels, MMIO or device handles."""
    def __init__(self,capacity=32):
        self.capacity=int(capacity)
        if not 1<=self.capacity<=32:raise ValueError('P1 batch capacity1..32')
        self.quad=np.empty((4,2),np.float32);self.boxes=np.empty((self.capacity,4),np.int32)
        self.h=np.empty((3,3),np.float64);self.mapping=np.empty((self.capacity,12),np.int32)
        self.packet=np.empty((self.capacity,10),np.uint32);self.proof=np.empty((self.capacity,12),np.int32)
        self.times=np.empty(16+4*self.capacity,np.float64)
        self.lock=threading.Lock();self.library=None;self.context=None;self.finalizer=None;self.available=None
        self.last_cache=dict(entries=0,hits=0,misses=0,calls=0,capacity=128)
        self.last_status=dict(available=False,reason='not_requested')
    def _context(self):
        from v64_io import prepare_io
        lib=prepare_io()
        if self.library is not lib:
            if self.finalizer is not None:self.finalizer()
            self.context=None;self.finalizer=None;self.library=lib
            self.available=bool(lib.p11_v70_geometry_available())
        if not self.available:
            self.last_status=dict(available=False,reason='matching_opencv_development_package_unavailable');return None
        if self.context is None:
            pointer=lib.p11_v70_plan_create()
            if not pointer:raise MemoryError('P1 CPU plan context allocation failed')
            self.context=pointer;self.finalizer=weakref.finalize(self,_destroy_plan,lib,pointer)
        return lib
    def run(self,q,input_size,size,boxes,budget):
        if not self.lock.acquire(False):raise RuntimeError('P1 CPU plan workspace already active')
        try:
            lib=self._context()
            if lib is None:return None
            if not 1<=len(boxes)<=self.capacity:raise ValueError('P1 batch box count invalid')
            q=np.asarray(q,np.float32)
            if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('P1 batch current quad invalid')
            self.quad[:]=q;self.boxes[:len(boxes)]=boxes
            began=time.perf_counter();cpu=time.thread_time()
            code=lib.p11_v70_plan_batch(self.context,self.quad.ctypes.data,int(input_size[0]),int(input_size[1]),
                int(size[0]),int(size[1]),self.boxes.ctypes.data,len(boxes),self.capacity,float(budget),
                self.h.ctypes.data,self.mapping.ctypes.data,self.packet.ctypes.data,self.proof.ctypes.data,self.times.ctypes.data)
            elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
            if code:
                self.last_status=dict(available=True,code=int(code),reason='native_geometry_rejected',wall_s=elapsed,thread_cpu_s=used)
                # Invalid geometry is rejected by the existing legacy path too;
                # it does not authorize any old packet or incomplete receipt.
                return None
            t=self.times
            self.last_cache=dict(entries=int(t[10]),hits=int(t[12]),misses=int(t[13]),calls=int(t[14]),capacity=128)
            self.last_status=dict(available=True,code=0,wall_s=elapsed,thread_cpu_s=used,
                native_wall_s=float(t[6]),native_thread_cpu_s=float(t[7]),
                h_s=float(t[0]),h_thread_cpu_s=float(t[1]),mapping_s=float(t[2]),mapping_thread_cpu_s=float(t[3]),
                proof_s=float(t[4]),proof_thread_cpu_s=float(t[5]),
                proof_cache_hits=int(t[8]),proof_cache_misses=int(t[9]),native_calls=1)
            return self.h,self.mapping[:len(boxes)],self.packet[:len(boxes)],self.proof[:len(boxes)],dict(self.last_status)
        finally:self.lock.release()
    def close(self):
        if not self.lock.acquire(False):raise RuntimeError('P1 CPU plan active; retain context until producer stops')
        try:
            if self.finalizer is not None:self.finalizer()
            self.context=None;self.finalizer=None;self.library=None;self.available=None
        finally:self.lock.release()
