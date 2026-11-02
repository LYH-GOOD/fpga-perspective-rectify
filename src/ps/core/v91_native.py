"""Small CPU addon: unchanged native kernels, bound current-frame transactions."""
from pathlib import Path
import ctypes,hashlib,platform,shutil,subprocess,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB=None;_ERROR=None;_LOCK=threading.RLock()


def prepare_transactions(cancel=None,required=False):
    global _LIB,_ERROR
    from v79_setup import setup_command,check_cancel,NativeSetupCancelled
    with _LOCK:
        if _LIB is not None:return _LIB
        if _ERROR is not None:
            if required:raise RuntimeError(_ERROR)
            return None
        try:
            check_cancel(cancel)
            if platform.system()!='Linux':raise RuntimeError('V91 CPU addon requires PYNQ Linux')
            root=Path(__file__).resolve().parent;source=root/'v91_transaction.cpp'
            flags=['-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread']
            if platform.machine()=='armv7l':flags.append('-mfpu=neon')
            digest=hashlib.sha256(source.read_bytes()+platform.machine().encode()+' '.join(flags).encode()).hexdigest()[:20]
            target=root/('v91_transaction_'+digest+'_'+platform.machine()+'.so')
            from v80_cache import restore,remember
            restore(target,source,'transaction',flags,cancel)
            if not target.is_file():
                compiler=shutil.which('g++') or shutil.which('c++')
                if not compiler:raise RuntimeError('No compiler for small V91 CPU addon')
                temporary=target.with_suffix('.building.so')
                try:
                    result=setup_command([compiler]+flags+[str(source),'-o',str(temporary)],90,cancel,'V91_TRANSACTION_BUILD')
                    if result.returncode:raise RuntimeError(result.stderr[-2000:])
                    check_cancel(cancel);temporary.replace(target)
                finally:
                    if temporary.exists():temporary.unlink()
            lib=ctypes.CDLL(str(target));vp=ctypes.c_void_p;ci=ctypes.c_int
            lib.p11_v91_abi.argtypes=[];lib.p11_v91_abi.restype=ci
            if lib.p11_v91_abi()!=9101:raise ValueError('V91 CPU transaction ABI mismatch')
            lib.p11_v91_postlk.argtypes=[vp,vp,vp,ci,ci,ci,vp,ci,ci,ci,ci,vp,ctypes.c_double,vp,vp,vp,vp,vp,vp,vp]
            lib.p11_v91_postlk.restype=ci
            lib.p11_v91_pack_create.argtypes=[vp];lib.p11_v91_pack_create.restype=vp
            lib.p11_v91_pack_destroy.argtypes=[vp];lib.p11_v91_pack_destroy.restype=None
            lib.p11_v91_pack_batch.argtypes=[vp,vp,ci,ci,ci,ci,vp,ci,vp,ctypes.c_size_t,vp]
            lib.p11_v91_pack_batch.restype=ci
            _LIB=lib;remember(target,source,'transaction',flags)
            checkpoint('V91_TRANSACTION_READY',abi=9101,path=str(target),hardware_access=False,
                original_kernels_unchanged=True,opencv_headers_required=False)
            return lib
        except NativeSetupCancelled:raise
        except (OSError,RuntimeError,ValueError,AttributeError,subprocess.SubprocessError) as exc:
            _ERROR=type(exc).__name__+': '+str(exc)
            checkpoint('V91_TRANSACTION_UNAVAILABLE',exception=_ERROR,fallback='unchanged V90 kernels and owner path',hardware_access=False)
            if required:raise
            return None


def _address(function):return int(ctypes.cast(function,ctypes.c_void_p).value)


def _key(array):return (id(array),int(array.ctypes.data),tuple(array.shape),tuple(array.strides),array.dtype.str)


class PostLKWorkspace:
    def __init__(self):
        self.lib=prepare_transactions();self.pending=None;self.detail={}
        from v87_v74_native import _LIB as kernels
        self.kernels=kernels
        self.available=bool(self.lib is not None and kernels is not None and kernels.p11_lk_available())
        self.proposed=np.empty((4,2),np.float64);self.scale=np.empty(2,np.float64)
        self.current=np.empty((4,2),np.float64);self.edges=np.empty(21,np.float64)
        self.polarity=np.empty(4,np.int32)
        self.source=np.empty((4,2),np.float64);self.source_stats=np.empty(27,np.float64);self.meta=np.empty(8,np.float64)
        if self.available:
            self.edge_function=_address(kernels.p11_edges_checked);self.source_function=_address(kernels.p11_yuyv_refine64)

    def clear(self):self.pending=None

    def measure(self,gray,quad,radius,image,scale,index,checks,previous_polarity):
        self.pending=None;self.detail=dict(native_transaction_used=False,source_proof_reused=False)
        if not self.available or checks!='auto' or image is None or image.ndim!=3 or image.shape[2]!=2:return None
        from v31_pixels import require_yuyv,color_mode
        image=require_yuyv(image);g=np.ascontiguousarray(gray,np.uint8)
        if g.ndim!=2:return None
        self.proposed[:]=quad;self.scale[:]=scale
        self.polarity.fill(0)
        for i,value in enumerate(previous_polarity[:4]):self.polarity[i]=int(value)
        begin=time.perf_counter();cpu=time.thread_time()
        code=self.lib.p11_v91_postlk(self.edge_function,self.source_function,
            g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],image.ctypes.data,image.shape[1],image.shape[0],image.strides[0],
            color_mode(),self.proposed.ctypes.data,float(radius),self.scale.ctypes.data,self.polarity.ctypes.data,
            self.current.ctypes.data,self.edges.ctypes.data,self.source.ctypes.data,self.source_stats.ctypes.data,self.meta.ctypes.data)
        if code:raise ValueError('V91 post-LK original kernel rejected input: '+str(code))
        q=self.current.astype(np.float32);stats=self.edges
        evidence=dict(edge_support=stats[:4].tolist(),edge_polarity=stats[4:8].astype(int).tolist(),
            refined_corners=int(stats[16]),supported_edges=int(stats[17]),median_edge_shift=float(np.median(stats[8:12])),
            edge_rms=stats[12:16].tolist(),max_edge_rms=float(max(stats[12:16])),edge_backend='cpp_analytic_tls',
            native_valid=bool(stats[20]),valid=bool(stats[20]),edge_measure_s=float(self.meta[5]))
        self.detail=dict(native_transaction_used=True,transaction_s=time.perf_counter()-begin,
            transaction_thread_cpu_s=time.thread_time()-cpu,current24_native_s=float(self.meta[5]),
            source64_native_s=float(self.meta[6]),source64_thread_cpu_s=float(self.meta[7]),
            independent_source_prepared=bool(self.meta[4]),source_proof_reused=False,
            grids=[[24,.055,.945],[64,.06,.94]],original_native_kernels=True)
        if self.meta[4]:
            self.pending=(_key(image),_key(gray),int(index),q.tobytes(),tuple(float(v) for v in scale))
        return q,evidence

    def take_source(self,image,gray,candidate,scale,index,narrow):
        pending=self.pending;self.pending=None
        if pending is None or image is None:return None
        q=np.asarray(candidate,np.float32);s=np.asarray(scale,np.float64)
        if q.shape!=(4,2) or not np.isfinite(q).all() or s.shape!=(2,):return None
        token=(_key(image),_key(gray),int(index),q.tobytes(),tuple(float(v) for v in s))
        half=min(24.,max(3.,float(narrow)*float(s.max())))
        if token!=pending:
            self.detail['source_reuse_rejected']='current_source_gray_index_quad_or_scale_mismatch';return None
        if half!=float(self.meta[0]) or float(narrow)!=float(self.meta[1]):
            self.detail['source_reuse_rejected']='current_proof_band_mismatch';return None
        local=(q+.5)*s-.5
        h,w=image.shape[:2]
        if (not np.isfinite(local).all() or np.any(local<2) or np.any(local[:,0]>w-3)
                or np.any(local[:,1]>h-3) or not cv2.isContourConvex(local.astype(np.float32))):return None
        result,detail=_decode_source64(local,half,self.source,self.source_stats)
        edges=detail['edges'];accepted=len(edges)==4 and detail.get('refined_corners')==4 and all(e.get('accepted',False) for e in edges)
        support=[e.get('retained',0)/64. if e.get('accepted',False) else 0. for e in edges]
        rms=[float(e.get('tls_rms',1e30))/float(s.min()) for e in edges]
        contrast=np.array([e.get('profile_contrast',0.) for e in edges],np.float64)
        polarity=np.where(np.abs(contrast)>=8,np.sign(contrast),0).astype(int).tolist()
        valid=bool(accepted and min(support)>=.60 and all(e.get('coverage',0.)>=.60 for e in edges))
        origin=np.zeros(2,np.float64)
        observed=((result+origin+.5)/s-.5).astype(np.float32)
        from v49_boundary import array_key
        evidence=dict(valid=valid,refined_corners=4 if valid else 0,supported_edges=sum(v>=.60 for v in support),
            edge_support=support,edge_rms=rms,edge_polarity=polarity,edge_backend='cpp_current_source_Y64',
            method='p1_original_resolution_normal_profiles_TLS',source_proof=detail,tracking_roi_offset=[0.,0.],
            same_frame_source=True,profiles_per_edge=64,current_source_key=array_key(image),
            source_proof_kind='source_Y_profiles',fraction_limits=[.06,.94],
            boundary_fallback_s=time.perf_counter()-float(self.meta[2]),
            boundary_fallback_thread_cpu_s=time.thread_time()-float(self.meta[3]),postlk_native_transaction=True)
        self.detail['source_proof_reused']=True
        return dict(proof=(observed,evidence),begin=float(self.meta[2]),cpu=float(self.meta[3]))


def _decode_source64(q,half,out,stats):
    """Original V74 refine64 returned-corner guards and edge metadata."""
    if not np.isfinite(out).all() or not np.isfinite(stats).all():raise ValueError('native original-Y64 returned invalid geometry')
    count=int(stats[24]);edges=[]
    for i in range(4):
        n=int(stats[i*6]);info=dict(edge=i,profiles=64,supported=n,accepted=bool(stats[i*6+4]),profile_contrast=float(stats[i*6+5]))
        if n>=20:info.update(tls_rms=float(stats[i*6+1]),retained=int(stats[i*6+2]),coverage=float(stats[i*6+3]))
        edges.append(info)
    try:
        candidate=out.astype(np.float32)
        if not cv2.isContourConvex(candidate):raise ValueError('native64 refined convexity invalid')
        area_ratio=abs(cv2.contourArea(candidate))/abs(cv2.contourArea(q.astype(np.float32)))
        if not .85<=area_ratio<=1.15 or np.max(np.linalg.norm(candidate-q,axis=1))>3*half:
            raise ValueError('native64 refined area/order/displacement invalid')
    except (ValueError,cv2.error):candidate=q.astype(np.float32);count=0
    return candidate,dict(method='p1_pyramid_subpixel_profiles_tls',backend='cpp_packed_Y_64x65_Q5',
        state='refined' if count else 'coarse_retained',refined_corners=count,edges=edges,half_window_pixels=float(half),
        corner_displacements=np.linalg.norm(candidate-q,axis=1).tolist(),
        refinement_s=float(stats[25]),refinement_thread_cpu_s=float(stats[26]),
        native_wall_s=float(stats[25]),native_thread_cpu_s=float(stats[26]),workspace_reused=True,
        interpolation='opencv_uint8_linear_replicate',tls_solver='analytic_2x2_principal_axis',original_profile_gates_preserved=True)


class PackedInput:
    def __init__(self,job,offsets,detail):
        self.token=(id(job),job.index,int(job.color_mode),tuple(id(t) for t in job.tiles))
        self.offsets=tuple(offsets);self.detail=dict(detail)
        #   ⭐ C2：DMA 每个像素搬几个字节。4 = 老路径（PS 打好 BGRX32）；
        #      2 = PL 侧转换（PS 只搬 YUYV）。execute() 用它算 n_in。
        self.bpp=int(detail.get('input_bpp',4))

    def matches(self,job):return self.token==(id(job),job.index,int(job.color_mode),tuple(id(t) for t in job.tiles))


class InputPackWorkspace:
    def __init__(self):
        self.owner=threading.get_ident();self.lib=prepare_transactions();self.pointer=None
        self.descriptors=np.empty((32,5),np.int32);self.stats=np.empty(10,np.float64)
        from v64_io import prepare_io
        self.kernel=prepare_io()
        if self.lib is not None:
            self.pointer=self.lib.p11_v91_pack_create(_address(self.kernel.p11_v64_pack))
            if not self.pointer:raise MemoryError('V91 input packing workspace allocation failed')

    def pack(self,job,destination):
        #   ⭐ 2026-10-24 仪表：把 pack() 拆成 4 段，定位 input_copy_s 里那 4.7ms 的非原生开销。
        _t0=time.perf_counter()
        if threading.get_ident()!=self.owner:raise RuntimeError('Input packing must remain on P1 owner')
        if self.pointer is None or not 2<=len(job.tiles)<=32:return None
        offset=0;offsets=[]
        for i,tile in enumerate(job.tiles):
            x,y,w,h=map(int,tile.crop)
            if min(w,h)<2 or offset+w*h*4>destination.nbytes:return None
            self.descriptors[i]=(x,y,w,h,offset);offsets.append(offset);offset+=w*h*4
        _t1=time.perf_counter()
        from v31_pixels import require_yuyv
        image=require_yuyv(job.lease.image)
        if destination.dtype!=np.uint8 or not destination.flags.c_contiguous or not destination.flags.writeable:
            raise ValueError('V91 input destination must be writable contiguous uint8 CMA')
        _t2=time.perf_counter()
        code=self.lib.p11_v91_pack_batch(self.pointer,image.ctypes.data,image.strides[0],image.shape[1],image.shape[0],
            int(job.color_mode),self.descriptors.ctypes.data,len(job.tiles),destination.ctypes.data,destination.nbytes,self.stats.ctypes.data)
        _t3=time.perf_counter()
        if code:raise ValueError('V91 input batch rejected: '+str(code))
        detail=dict(input_pack_batch=True,input_pack_tiles=len(job.tiles),input_pack_bytes=offset,
            input_pack_kernel_calls=int(self.stats[0]),input_pack_converted_pixels=int(self.stats[1]),
            input_pack_requested_pixels=int(self.stats[2]),input_pack_native_s=float(self.stats[4]),
            input_pack_thread_cpu_s=float(self.stats[5]),input_pack_workspace_bytes=int(self.stats[6]),
            input_pack_original_color_kernel=True,input_pack_row_reuse=bool(self.stats[8]),
            input_pack_overlap_area=int(self.stats[9]),
            input_pack_desc_s=_t1-_t0,input_pack_prep_s=_t2-_t1,input_pack_call_s=_t3-_t2)
        out=PackedInput(job,offsets,detail)
        out.detail['input_pack_total_s']=time.perf_counter()-_t0
        return out

    def close(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Packing workspace close must stay on owner')
        if self.pointer:self.lib.p11_v91_pack_destroy(self.pointer);self.pointer=None
