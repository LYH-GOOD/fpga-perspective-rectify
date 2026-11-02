"""Owner-local bounded CPU display workspaces; no hardware access or frame ownership."""
from pathlib import Path
import ctypes,hashlib,time
import numpy as np
from p11_contract import RELEASE_ID
from v64_io import prepare_io,_bgr_destination
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def _library():
    lib=prepare_io()
    if getattr(lib,'_v73_display_bound',False):return lib
    vp=ctypes.c_void_p;ci=ctypes.c_int;sz=ctypes.c_size_t
    lib.p11_v71_display_abi.argtypes=[];lib.p11_v71_display_abi.restype=ci
    if lib.p11_v71_display_abi()!=7301:raise RuntimeError('V73 display ABI mismatch; restart kernel with complete new folder')
    lib.p11_v73_display_caps.argtypes=[];lib.p11_v73_display_caps.restype=ci
    lib.p11_v71_display_create.argtypes=[];lib.p11_v71_display_create.restype=vp
    lib.p11_v71_display_destroy.argtypes=[vp];lib.p11_v71_display_destroy.restype=None
    lib.p11_v71_display_scale.argtypes=[vp,vp,sz]+[ci]*5+[vp]+[ci]*3+[sz,vp]
    lib.p11_v71_display_scale.restype=ci
    lib.p11_v71_display_copy.argtypes=[vp,vp,sz,vp,vp,sz,vp];lib.p11_v71_display_copy.restype=ci
    lib._v73_display_bound=True;return lib

class FusedDisplay:
    """Only HDMI owner calls scale/close; paired-copy stats have one producer."""
    def __init__(self):
        self.lib=_library();self.contexts=[];self.stats=[np.empty(7,np.float64) for _ in range(2)]
        self.polyphase_backend='native_NEON_5_4_exact_Q3' if self.lib.p11_v73_display_caps()&1 else 'native_scalar_5_4_exact_Q3' 
        try:
            for _ in range(2):
                ptr=self.lib.p11_v71_display_create()
                if not ptr:raise MemoryError('V71 native HDMI workspace allocation failed')
                self.contexts.append(ptr)
        except BaseException:self.close();raise
    def close(self):
        for ptr in self.contexts:self.lib.p11_v71_display_destroy(ptr)
        self.contexts.clear()
    def scale(self,side,image,mode,frame,rect):
        if side not in (0,1) or len(self.contexts)!=2:raise RuntimeError('HDMI workspace closed or invalid side')
        kind=2 if side==0 else 4
        if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=kind
                or not image.flags.c_contiguous):raise ValueError('V71 display source must be contiguous YUYV/BGRX snapshot')
        x,y,w,h=map(int,rect);ptr,stride,available=_bgr_destination(frame,rect,(h,w))
        s=self.stats[side];begin=time.perf_counter();cpu=time.thread_time()
        code=self.lib.p11_v71_display_scale(self.contexts[side],image.ctypes.data,image.nbytes,
            int(image.strides[0]),image.shape[1],image.shape[0],kind,int(mode),ptr,stride,w,h,available,s.ctypes.data)
        if code:raise ValueError('V71 fused display scale failed '+str(code))
        return dict(wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu,
            native_wall_s=float(s[0]),native_thread_cpu_s=float(s[1]),map_build_s=float(s[2]),
            map_rebuilt=bool(s[3]),source_rows=int(s[4]),direct=bool(s[5]),
            source_shape=list(image.shape),destination_rect=list(rect),destination_stride=stride,
            backend=('native_NEON_5_4_nearest_Q3' if int(s[6])==2 else self.polyphase_backend) if s[6] else 'native_convert_then_bilinear_Q11_rows',
            polyphase_5_4_used=bool(s[6]),interpolation='pixel_center_bilinear_Q11_equivalent',source_channels=kind)

def paired_copy(lib,raw,raw_dst,out,out_dst,stats):
    """Producer keeps source lease/CMA output and destination reservation through this call."""
    for image,destination in ((raw,raw_dst),(out,out_dst)):
        if image is None:continue
        if (image.dtype!=np.uint8 or not image.flags.c_contiguous or destination.dtype!=np.uint8
                or not destination.flags.c_contiguous or not destination.flags.writeable
                or image.nbytes>destination.nbytes):raise ValueError('Invalid display paired-copy span')
        a=int(image.ctypes.data);b=int(destination.ctypes.data)
        if a<b+image.nbytes and b<a+image.nbytes:raise ValueError('Display copy source overlaps reserved destination')
    code=lib.p11_v71_display_copy(0 if raw is None else raw.ctypes.data,raw_dst.ctypes.data,
        0 if raw is None else raw.nbytes,0 if out is None else out.ctypes.data,out_dst.ctypes.data,
        0 if out is None else out.nbytes,stats.ctypes.data)
    if code:raise ValueError('V71 display paired copy failed '+str(code))
    return float(stats[0]),float(stats[1])
