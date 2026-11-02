"""Lazy CPU edge addon: compile once at selection/startup, never per frame."""
from pathlib import Path
import ctypes, hashlib, os, platform, shutil, subprocess, threading
import numpy as np
from run_logging import checkpoint
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB=None
_ERROR=None
_LOCK=threading.Lock()

def prepare_edges():
    global _LIB,_ERROR
    with _LOCK:
        if _LIB is not None:return _LIB
        if _ERROR is not None:return None
        try:
            source=Path(__file__).with_name('v105_edges.cpp')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()[:20]
            suffix='.dll' if platform.system()=='Windows' else '.so'
            target=source.with_name('v105_edges_'+digest+'_'+platform.machine()+suffix)
            if not target.exists():
                compiler=os.environ.get('P11_EDGE_CXX') or shutil.which('g++') or shutil.which('c++')
                if not compiler:raise RuntimeError('C++ compiler unavailable')
                cmd=[compiler]+(['c++'] if Path(compiler).stem=='zig' else [])+['-O3','-std=c++11','-ffp-contract=off','-shared']
                if Path(compiler).stem=='zig':cmd+=['-fno-exceptions','-fno-rtti','-nostdlib++']
                if suffix=='.so':cmd+=['-fPIC']
                if platform.machine()=='armv7l':cmd+=['-mfpu=neon']
                temporary=target.with_name(target.stem+'.building'+suffix)
                try:
                    result=subprocess.run(cmd+[str(source),'-o',str(temporary)],capture_output=True,text=True,timeout=300 if os.name=='nt' else 90,
                        **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
                    if result.returncode:raise RuntimeError(result.stderr[-1600:])
                    temporary.replace(target)
                finally:
                    if temporary.exists():temporary.unlink()
            lib=ctypes.CDLL(str(target));ptr=ctypes.c_void_p;integer=ctypes.c_int
            lib.p11_edges_abi.argtypes=[];lib.p11_edges_abi.restype=integer
            if lib.p11_edges_abi()!=10501:raise RuntimeError('edge ABI mismatch')
            lib.p11_edges.argtypes=[ptr,integer,integer,integer,ptr,ctypes.c_float,ptr,ptr,ptr,ptr]
            lib.p11_edges.restype=integer
            _LIB=lib;checkpoint('PHYSICAL_NATIVE_READY',abi=10501,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),path=str(target))
            return lib
        except (OSError,RuntimeError,subprocess.SubprocessError) as exc:
            _ERROR=str(exc);checkpoint('PHYSICAL_NATIVE_UNAVAILABLE',reason=_ERROR,fallback='vectorized CPU edge implementation')
            return None

class EdgeWorkspace:
    def __init__(self):
        self.lib=prepare_edges();self.body=np.empty(96,np.float32);self.q=np.empty((4,2),np.float32)
        self.stats=np.empty(12,np.float32)
    def measure(self,gray,q,radius,reference):
        gray=np.ascontiguousarray(gray,np.uint8);q=np.ascontiguousarray(q,np.float32)
        ref=None if reference is None else np.ascontiguousarray(reference,np.float32)
        if gray.ndim!=2 or q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Invalid edge input')
        if ref is not None and (ref.size!=96 or not np.isfinite(ref).all()):raise ValueError('Invalid edge reference')
        result=self.lib.p11_edges(gray.ctypes.data,gray.shape[1],gray.shape[0],gray.strides[0],q.ctypes.data,
            radius,None if ref is None else ref.ctypes.data,self.body.ctypes.data,self.q.ctypes.data,self.stats.ctypes.data)
        if result:raise ValueError('physical_edge_proof_failed:'+str(result))
        return self.q.copy(),dict(support=self.stats[:4].tolist(),edge_rms=self.stats[4:8].tolist(),
            sample_count=96,edge_backend='native105',body=self.body.copy())
