"""Small CPU-only helper; compile on PYNQ, ctypes calls release the GIL."""
from pathlib import Path
import ctypes,hashlib,platform,subprocess,time,shlex,shutil
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB=None
_BUILD_INFO={}

def prepare_io(cancel=None):
    global _LIB
    if _LIB is not None:return _LIB
    from v79_setup import setup_command,check_cancel
    from run_logging import checkpoint
    check_cancel(cancel)
    if platform.system()!='Linux':raise RuntimeError('V73 runs on PYNQ Linux')
    root=Path(__file__).resolve().parent;src=root/'v64_io.cpp'
    flags=['-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared']
    if platform.machine()=='armv7l':flags.append('-mfpu=neon')
    # CPU-only optional OpenCV H solver. Missing/mismatched headers leave the
    # legacy cv2+mapping+guard path available; no hardware fallback is allowed.
    cv_flags=[];cv_version=None;pkg=shutil.which('pkg-config');reason='pkg_config_unavailable'
    if pkg:
        import cv2
        try:
            probe=setup_command([pkg,'--modversion','opencv4'],10,cancel,'IO_OPENCV_VERSION')
            reason='opencv_development_package_missing_or_version_mismatch'
            if probe.returncode==0 and probe.stdout.strip()==cv2.__version__:
                found=setup_command([pkg,'--cflags','--libs','opencv4'],10,cancel,'IO_OPENCV_FLAGS')
                if found.returncode==0:
                    cv_flags=shlex.split(found.stdout);cv_version=probe.stdout.strip();reason='matching_opencv'
        except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
            reason='opencv_probe_failed:'+type(exc).__name__
    base_flags=list(flags);cache_entry=None
    def load_variant(with_opencv):
        nonlocal cache_entry
        actual_flags=base_flags+(['-DP11_V70_OPENCV'] if with_opencv else [])
        actual_cv=cv_flags if with_opencv else []
        flags_key=actual_flags+actual_cv+([cv_version] if with_opencv else [])
        digest=hashlib.sha256(src.read_bytes()+platform.machine().encode()+' '.join(flags_key).encode()).hexdigest()[:20]
        target=root/('v73_io_'+digest+'_'+platform.machine()+'.so')
        from v80_cache import restore
        restore(target,src,'io',flags_key,cancel)
        cache_entry=(target,src,'io',flags_key)
        if not target.is_file():
            temp=target.with_suffix('.tmp.so')
            try:
                command=['g++']+actual_flags+[str(src),'-o',str(temp)]+actual_cv
                result=setup_command(command,90,cancel,'IO_BUILD')
                if result.returncode:raise subprocess.CalledProcessError(result.returncode,command,result.stdout,result.stderr)
                check_cancel(cancel);temp.replace(target)
            finally:
                if temp.exists():temp.unlink()
        check_cancel(cancel)
        checkpoint('IO_LOAD_BEGIN',path=str(target),hardware_access=False)
        return ctypes.CDLL(str(target))
    try:lib=load_variant(cv_version is not None)
    except (OSError,subprocess.CalledProcessError) as exc:
        if cv_version is None:raise
        reason='optional_opencv_build_or_load_failed:'+type(exc).__name__
        lib=load_variant(False)
    _BUILD_INFO.update(optional_geometry_reason=reason,opencv_development_version=cv_version,
        geometry_available=bool(lib.p11_v70_geometry_available()),path=str(lib._name))
    vp=ctypes.c_void_p;ci=ctypes.c_int
    lib.p11_v64_abi.argtypes=[];lib.p11_v64_abi.restype=ci
    if lib.p11_v64_abi()!=6601:raise RuntimeError('V70 P1 IO ABI mismatch')
    lib.p11_v64_pack.argtypes=[vp]+[ci]*8+[vp,ctypes.c_size_t]
    #   ⭐ C2：YUYV 原样按行搬（count = src ptr + ss,sw,sh + x0,y0,w,h,ds + dst ptr + bytes）
    lib.p11_v64_copy_rows.argtypes=[vp]+[ci]*8+[vp,ctypes.c_size_t]
    lib.p11_v64_copy_rows.restype=ci
    lib.p11_v64_guard.argtypes=[vp]+[ci]*5+[vp]
    lib.p11_v65_guard_interval.argtypes=[vp]+[ci]*7+[ctypes.c_double,vp]
    lib.p11_v65_guard_interval.restype=ci
    lib.p11_v64_parameters.argtypes=[vp,vp,vp]
    lib.p11_v64_arm.argtypes=[vp]+[ctypes.c_uint32]*4
    lib.p11_v64_poll.argtypes=[vp,vp,ctypes.c_uint32,ctypes.c_double,vp]
    for name in ('pack','guard','parameters','arm','poll'):getattr(lib,'p11_v64_'+name).restype=ci
    lib.p11_v66_caps.argtypes=[];lib.p11_v66_caps.restype=ci
    lib.p11_v66_yuyv_bgr.argtypes=[vp]+[ci]*4+[vp,ci,ctypes.c_size_t]
    lib.p11_v66_bgra_bgr.argtypes=[vp]+[ci]*3+[vp,ci,ctypes.c_size_t]
    lib.p11_v66_mapping.argtypes=[vp,vp,ci,ci,vp,vp]
    for name in ('yuyv_bgr','bgra_bgr','mapping'):getattr(lib,'p11_v66_'+name).restype=ci
    lib.p11_v70_plan_abi.argtypes=[];lib.p11_v70_plan_abi.restype=ci
    if lib.p11_v70_plan_abi()!=7001:raise RuntimeError('V70 CPU plan ABI mismatch')
    lib.p11_v70_geometry_available.argtypes=[];lib.p11_v70_geometry_available.restype=ci
    lib.p11_v70_plan_create.argtypes=[];lib.p11_v70_plan_create.restype=vp
    lib.p11_v70_plan_destroy.argtypes=[vp];lib.p11_v70_plan_destroy.restype=None
    lib.p11_v70_plan_batch.argtypes=[vp,vp]+[ci]*4+[vp,ci,ci,ctypes.c_double]+[vp]*5
    lib.p11_v70_plan_batch.restype=ci
    _LIB=lib
    from v80_cache import remember
    remember(*cache_entry)
    return lib

def copy_yuyv_rows(image,crop,dst,offset=0):
    #   ⭐ 2026-10-24 C2：只搬 YUYV，不做颜色转换 —— 每行一次 memcpy（C++ 里）。
    #   ⚠️ 不要退回到 numpy 的三维赋值：numpy 对 (h,w,2) 的跨步赋值会退化成
    #      逐 2 字节，实测 51,000 px 要 4.88 ms（比老的整段转换还慢一倍）。
    x,y,w,h=map(int,crop)
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=2 or image.strides[1:]!=(2,1):
        raise ValueError('Raw YUYV layout invalid')
    if dst.dtype!=np.uint8 or not dst.flags.c_contiguous:raise ValueError('Copy workspace must be contiguous uint8')
    n=w*h*2
    if (x&1) or (w&1):raise ValueError('YUYV crop must be even-aligned')
    if offset<0 or offset+n>dst.nbytes:raise ValueError('Copy destination span exceeds workspace')
    code=prepare_io().p11_v64_copy_rows(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],
        x,y,w,h,w*2,int(dst.ctypes.data)+int(offset),int(dst.nbytes)-int(offset))
    if code:raise ValueError('YUYV row copy failed '+str(code))

def pack_yuyv(image,crop,mode,dst):
    x,y,w,h=map(int,crop)
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=2 or image.strides[1:]!=(2,1):raise ValueError('Raw YUYV layout invalid')
    if dst.dtype!=np.uint8 or not dst.flags.c_contiguous:raise ValueError('Pack workspace must be contiguous uint8')
    code=prepare_io().p11_v64_pack(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],x,y,w,h,int(mode),dst.ctypes.data,dst.nbytes)
    if code:raise ValueError('YUYV to BGRX pack failed '+str(code))

def guard(regs,input_size,output_size,*,strategy='fast_safe',cpu_budget_s=.008,block_pixels=128,workspace=None):
    """Only complete sufficient receipts are valid; budget prefixes are rejected."""
    a=np.ascontiguousarray(regs if workspace is None else workspace.mapping[4:],dtype=np.int32)
    if a.shape!=(8,):raise ValueError('P1 requires eight coefficients')
    if strategy not in ('fast_safe','exact_reference'):raise ValueError('Unknown P1 proof strategy')
    lib=prepare_io();begin=time.perf_counter();cpu=time.thread_time()
    if strategy=='exact_reference':
        out=np.zeros(2,np.int32) if workspace is None else workspace.guard_out[:2];out.fill(0)
        code=lib.p11_v64_guard(a.ctypes.data,*map(int,input_size),*map(int,output_size),384,out.ctypes.data)
        return dict(valid=code==0,code=int(code),peak_rows=int(out[0]) if code==0 else None,
            checked_pixels=int(out[1]) if code==0 else None,failure_at=out.tolist() if code else None,
            proof_s=time.perf_counter()-begin,proof_thread_cpu_s=time.thread_time()-cpu,
            method='whole_source_crop_retention_and_operand_bounds' if input_size[1]<=384 else 'native_exact_fixed_point_conservative_lifetime',
            complete_domain_verified=code==0,proof_strategy=strategy,proof_cached=False)
    out=np.zeros(8,np.int32) if workspace is None else workspace.guard_out;out.fill(0)
    #   ⚠️⚠️ 2026-10-25：这个 rows 必须等于 C++ 里 `p11_v65_guard_interval` 的校验值，
    #      否则返回 **-1（参数非法）** ⇒ 证明失败 ⇒ 该帧 HELD/LOST ⇒
    #      "明明找到了却一直重找"。**这个 192 曾经漏改，导致 5% 的帧掉 LOST。**
    from p11_contract import LINE_BUF_ROWS as _LBR
    code=lib.p11_v65_guard_interval(a.ctypes.data,*map(int,input_size),*map(int,output_size),int(_LBR),
        int(block_pixels),8192,float(cpu_budget_s),out.ctypes.data)
    return dict(valid=code==0,code=int(code),peak_rows=int(out[0]) if code==0 else None,
        checked_pixels=int(out[1]),interval_blocks=int(out[2]),subdivided_blocks=int(out[3]),
        proof_nodes=int(out[6]),failure_at=[int(out[4]),int(out[5])] if code else None,
        proof_s=time.perf_counter()-begin,proof_thread_cpu_s=time.thread_time()-cpu,
        method='whole_source_crop_retention_and_operand_bounds' if out[7]==0 else 'bounded_fixed_point_interval_lifetime',
        complete_domain_verified=code==0,budget_inconclusive=code==-5,proof_strategy=strategy,
        proof_cached=False,cpu_budget_s=float(cpu_budget_s),interval_block_pixels=int(block_pixels),
        exact_reference_fallback=False)


def poll(dma,regs,expected,seconds=.002,out=None):
    out=np.zeros(4,np.uint32) if out is None else out
    if out.dtype!=np.uint32 or out.shape!=(4,) or not out.flags.c_contiguous:raise ValueError('Invalid owner poll workspace')
    result=prepare_io().p11_v64_poll(dma.ctypes.data,regs.ctypes.data,int(expected),float(seconds),out.ctypes.data)
    return int(result),tuple(map(int,out))

def parameters(regs,packet,out=None):
    words=np.frombuffer(packet,np.uint32)
    if words.shape!=(10,):raise ValueError('P1 parameter packet must be10 words')
    out=np.zeros(2,np.uint32) if out is None else out
    if out.dtype!=np.uint32 or out.shape!=(2,) or not out.flags.c_contiguous:raise ValueError('Invalid parameter workspace')
    code=prepare_io().p11_v64_parameters(regs.ctypes.data,words.ctypes.data,out.ctypes.data)
    if code:raise RuntimeError('P1 parameter readback failed '+str((code,out.tolist())))
    return int(out[1])

def arm(dma,receive,send,nout,nin):
    if not 0<int(receive)<(1<<32) or not 0<int(send)<(1<<32):raise ValueError('P1 DMA address must be32bit CMA')
    if int(receive)%4 or int(send)%4:raise ValueError('P1 non-DRE DMA requires four-byte aligned addresses')
    code=prepare_io().p11_v64_arm(dma.ctypes.data,int(receive),int(send),int(nout),int(nin))
    if code:raise RuntimeError('P1 DMA arm failed '+str(code))


class PlanWorkspace:
    """Single PS planner thread owns these small arrays; tiles copy their packet."""
    def __init__(self):
        self.h=np.empty((3,3),np.float64);self.box=np.empty(4,np.int32)
        self.mapping=np.empty(12,np.int32);self.packet=np.empty(10,np.uint32)
        self.guard_out=np.empty(8,np.int32)
        self.output_corners=np.empty((4,2),np.float32);self.output_size=None
        from v70_ps import PlanBatchWorkspace
        self.batch=PlanBatchWorkspace(32)
    def close(self):self.batch.close()
    def destination(self,size):
        if self.output_size!=tuple(size):
            w,h=map(int,size);self.output_corners[:]=((0,0),(w-1,0),(w-1,h-1),(0,h-1))
            self.output_size=tuple(size)
        return self.output_corners
    def map_tile(self,h,box,input_size):
        np.copyto(self.h,h);self.box[:]=box
        code=prepare_io().p11_v66_mapping(self.h.ctypes.data,self.box.ctypes.data,
            int(input_size[0]),int(input_size[1]),self.mapping.ctypes.data,self.packet.ctypes.data)
        if code:return None,('invalid_domain','denominator','source_crop_empty','input_or_dma_limit','coefficient_overflow')[min(4,max(0,-int(code)-1))]
        return (tuple(map(int,self.mapping[:4])),tuple(map(int,self.mapping[4:])),self.packet.tobytes()),None


def _bgr_destination(frame,rect,source_shape):
    if frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3 or not frame.flags.c_contiguous or not frame.flags.writeable:
        raise ValueError('BGR destination must be a writable contiguous backing frame')
    x,y,w,h=map(int,rect)
    if (h,w)!=tuple(source_shape[:2]) or x<0 or y<0 or x+w>frame.shape[1] or y+h>frame.shape[0]:
        raise ValueError('Native BGR rectangle does not match source/frame bounds')
    stride=int(frame.strides[0]);offset=y*stride+x*3;available=frame.nbytes-offset
    if available<(h-1)*stride+w*3:raise ValueError('Native BGR destination span exceeds backing storage')
    return frame.ctypes.data+offset,stride,available


def yuyv_bgr_into(image,mode,frame,rect):
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=2 or image.strides[1:]!=(2,1) or image.strides[0]<image.shape[1]*2:
        raise ValueError('Native YUYV source layout invalid')
    ptr,stride,available=_bgr_destination(frame,rect,image.shape)
    code=prepare_io().p11_v66_yuyv_bgr(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],int(mode),ptr,stride,available)
    if code:raise ValueError('Native YUYV to BGR failed '+str(code))


def bgra_bgr_into(image,frame,rect):
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=4 or image.strides[1:]!=(4,1) or image.strides[0]<image.shape[1]*4:
        raise ValueError('Native BGRX source layout invalid')
    ptr,stride,available=_bgr_destination(frame,rect,image.shape)
    code=prepare_io().p11_v66_bgra_bgr(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],ptr,stride,available)
    if code:raise ValueError('Native BGRX to BGR failed '+str(code))
