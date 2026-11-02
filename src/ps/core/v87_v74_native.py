"""Optional host-architecture C++ helper. Compile once, never inside frame timing."""
from pathlib import Path
import ctypes, hashlib, json, platform, shutil, subprocess, sys, shlex, threading, time, weakref, math
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB=None
_STATUS={'backend':'numpy_analytic_tls','reason':'native_not_loaded','lk_backend':'opencv_python_binding'}

def prepare_native(build=True, required=False,cancel=None):
    global _LIB, _STATUS
    root=Path(__file__).resolve().parent
    from v79_setup import check_cancel,setup_command
    check_cancel(cancel)
    source=root/'v87_v74_native.cpp'
    manifest=json.loads((root/'release_manifest.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if manifest.get('release_id')!=RELEASE_ID or manifest.get('sha256',{}).get(source.name)!=digest:
        raise ValueError('native source/release hash mismatch; upload complete V31 folder')
    if _LIB is not None and _STATUS.get('source_sha256')==digest:return dict(_STATUS,already_loaded=True)
    cv_flags=[]
    cv_version=None
    pkg=shutil.which('pkg-config')
    if sys.platform.startswith('linux') and pkg:
        import cv2
        probe=setup_command([pkg,'--modversion','opencv4'],10,cancel,'V74_DETECTOR_OPENCV_VERSION')
        if probe.returncode==0 and probe.stdout.strip()==cv2.__version__:
            flags=setup_command([pkg,'--cflags','--libs','opencv4'],10,cancel,'V74_DETECTOR_OPENCV_FLAGS')
            if flags.returncode==0:
                cv_flags=shlex.split(flags.stdout);cv_version=probe.stdout.strip()
    variant='lk_'+cv_version if cv_flags else 'base'
    name='v31_native_'+digest[:16]+'_'+platform.machine()+'_'+variant+'.so'
    target=root/name
    try:
        if not sys.platform.startswith('linux'):
            raise RuntimeError('板端 Linux 编译；Windows 无需编译')
        from v80_cache import restore,remember
        cache_flags=['-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread']
        if platform.machine()=='armv7l':cache_flags+=['-mfpu=neon']
        if cv_flags:cache_flags+=['-DP11_OPENCV_LK']+cv_flags
        restore(target,source,'tracker',cache_flags,cancel,source_alias='v31_native.cpp')
        if not target.is_file():
            if not build:raise RuntimeError('native helper 尚未编译')
            compiler=shutil.which('g++') or shutil.which('c++')
            if not compiler:raise RuntimeError('板端没有 g++/c++；可用解析 TLS 回退，未声称达到30FPS')
            temp=target.with_suffix('.building.so')
            command=[compiler,'-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread',str(source),'-o',str(temp)]
            if platform.machine()=='armv7l':command+=['-mfpu=neon']
            if cv_flags:command+=['-DP11_OPENCV_LK']+cv_flags
            result=setup_command(command,180,cancel,'V74_DETECTOR_BUILD')
            if result.returncode!=0:raise RuntimeError(result.stdout[-4000:])
            check_cancel(cancel);temp.replace(target)
        lib=ctypes.CDLL(str(target))
        lib.p11_v31_abi.restype=ctypes.c_int
        if lib.p11_v31_abi()!=3107:raise RuntimeError('native helper ABI mismatch')
        vp=ctypes.c_void_p;ci=ctypes.c_int
        lib.p11_edges.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_edges.restype=ci
        lib.p11_guard.argtypes=[vp,vp,vp,ci,vp];lib.p11_guard.restype=ci
        lib.p11_gray2.argtypes=[vp,ci,ci,ci,vp];lib.p11_gray2.restype=ci
        lib.p11_gray_backend.restype=ci
        lib.p11_gaussian3.argtypes=[vp,ci,ci,ci,vp,vp];lib.p11_gaussian3.restype=ci
        lib.p11_quad_valid.argtypes=[vp,ci,ci,vp];lib.p11_quad_valid.restype=ci
        lib.p11_spatial.argtypes=[vp,ci,vp];lib.p11_spatial.restype=ci
        lib.p11_prepare.argtypes=[vp,ci,ci,vp];lib.p11_prepare.restype=ci
        lib.p11_packet.argtypes=[vp,vp,ci,ci,ci,ci,ci,vp];lib.p11_packet.restype=ci
        lib.p11_signature.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp];lib.p11_signature.restype=ci
        lib.p11_filter_available.restype=ci
        if lib.p11_filter_available():
            lib.p11_lk_filter.argtypes=[vp,vp,vp,vp,vp,vp,ci,vp,vp,ci,ci,vp,vp,vp]
            lib.p11_lk_filter.restype=ci
        lib.p11_plan_geometry.argtypes=[vp,vp,vp,ci,ci,vp,vp,ci,vp,vp]
        lib.p11_plan_geometry.restype=ci
        lib.p11_prepare_control.argtypes=[vp,vp,ci,ci,vp,vp,ci,vp,vp,ci,ci,ci,ci,ci,vp,vp]
        lib.p11_prepare_control.restype=ci
        lib.p11_lk_available.restype=ci
        if lib.p11_lk_available():
            lib.p11_lk_create.restype=vp
            lib.p11_lk_destroy.argtypes=[vp];lib.p11_lk_destroy.restype=None
            lib.p11_lk_anchor.argtypes=[vp,vp,ci,ci];lib.p11_lk_anchor.restype=ci
            lib.p11_lk_track.argtypes=[vp,vp,ci,ci,vp,ci,vp,vp,vp,vp,vp,vp,ci,ci]
            lib.p11_lk_track.restype=ci
            lib.p11_lk_promote.argtypes=[vp];lib.p11_lk_promote.restype=ci
        lib.p11_observe2.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp];lib.p11_observe2.restype=ci
        lib.p11_probe.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp];lib.p11_probe.restype=ci
        lib.p11_wait_io.argtypes=[vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp]
        lib.p11_wait_io.restype=ci
        lib.p11_profile_snapshot.argtypes=[vp,ci];lib.p11_profile_snapshot.restype=ci
        lib.p11_edges_checked.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp];lib.p11_edges_checked.restype=ci
        lib.p11_motion_values.argtypes=[vp,vp,vp,vp,vp,vp];lib.p11_motion_values.restype=ci
        lib.p11_copy_bgr.argtypes=[vp,vp,ci,ci,ci,ci];lib.p11_copy_bgr.restype=ci
        lib.p11_arm_io.argtypes=[vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ci];lib.p11_arm_io.restype=ci
        lib.p11_frame_state.argtypes=[vp,vp,vp];lib.p11_frame_state.restype=ci
        lib.p11_plan_wait.argtypes=[vp,vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp];lib.p11_plan_wait.restype=ci
        lib.p11_profile_os_snapshot.argtypes=[vp,ci];lib.p11_profile_os_snapshot.restype=ci
        lib.p11_edges_motion.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp]
        lib.p11_edges_motion.restype=ci
        lib.p11_frame_create.argtypes=[];lib.p11_frame_create.restype=vp
        lib.p11_frame_destroy.argtypes=[vp];lib.p11_frame_destroy.restype=None
        lib.p11_frame_prepare.argtypes=[vp,vp,vp,ci,ci,ci,ctypes.c_double,ctypes.c_double,ci,ci,vp,vp,vp,vp,ci,ci,vp,vp,ci,vp,vp,ci,ci,ci,ci,vp,vp,vp,vp,vp,vp]
        lib.p11_frame_prepare.restype=ci
        lib.p11_observe_edges.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp,vp]
        lib.p11_observe_edges.restype=ci
        if lib.p11_lk_available():
            lib.p11_lk_checked.argtypes=[vp,vp,ci,ci,vp,ci,vp,ci,ci,ctypes.c_uint32,vp,vp,vp,vp,vp,vp];lib.p11_lk_checked.restype=ci
            lib.p11_lk_checked_motion.argtypes=[vp,vp,ci,ci,vp,ci,vp,ci,ci,ctypes.c_uint32,vp,vp,vp,vp,vp,vp,vp]
            lib.p11_lk_checked_motion.restype=ci
            lib.p11_roi_features.argtypes=[vp,ci,ci,vp,vp,ci,vp,vp];lib.p11_roi_features.restype=ci
        lib.p11_refine64.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_refine64.restype=ci
        lib.p11_yuyv_refine64.argtypes=[vp,ci,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_yuyv_refine64.restype=ci
        lib.p11_preview_canvas_maps.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,ci,ci,vp,vp,vp,vp,vp]
        lib.p11_preview_canvas_maps.restype=ci
        lib.p11_preview_canvas_linear.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,ci,ci,vp,vp,vp,vp,vp,vp]
        lib.p11_preview_canvas_linear.restype=ci
        lib.p11_yuyv_profiles.argtypes=[vp,ci,ci,ci,vp,vp,ci,vp]
        lib.p11_yuyv_profiles.restype=ci
        lib.p11_io_probe.argtypes=[vp,vp,ctypes.c_uint32,ci,vp];lib.p11_io_probe.restype=ci
        lib.p11_owner_batch.argtypes=[vp,vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_double,ci,vp];lib.p11_owner_batch.restype=ci
        lib.p11_owner_complete.argtypes=[vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp]
        lib.p11_owner_complete.restype=ci
        lib.p11_yuyv_gray2.argtypes=[vp,ci,ci,ci,ci,vp];lib.p11_yuyv_gray2.restype=ci
        lib.p11_yuyv_observe2.argtypes=[vp,ci,ci,ci,ci,vp,vp,vp,vp];lib.p11_yuyv_observe2.restype=ci
        lib.p11_yuyv_observe_edges.argtypes=[vp,ci,ci,ci,ci,vp,vp,vp,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp,vp];lib.p11_yuyv_observe_edges.restype=ci
        lib.p11_copy_yuyv.argtypes=[vp,vp,ci,ci,ci,ci];lib.p11_copy_yuyv.restype=ci
        lib.p11_yuyv_bgr.argtypes=[vp,ci,ci,ci,ci,vp];lib.p11_yuyv_bgr.restype=ci
        lib.p11_yuyv_preview.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci]
        lib.p11_yuyv_preview.restype=ci
        lib.p11_yuyv_preview_nearest.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci]
        lib.p11_yuyv_preview_nearest.restype=ci
        lib.p11_bgr_preview_nearest.argtypes=[vp,ci,ci,ci,vp,ci,ci,vp,vp]
        lib.p11_bgr_preview_nearest.restype=ci
        lib.p11_preview_pair_copy.argtypes=[vp,vp,ci,ci,ci,ci,vp,vp,ci,ci,ci,ci,vp]
        lib.p11_preview_pair_copy.restype=ci
        lib.p11_compact_preview.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,vp,ci,ci,vp,vp,vp,vp]
        lib.p11_compact_preview.restype=ci
        lib.p11_coherent_profiles.argtypes=[vp,ci,ci,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp]
        lib.p11_coherent_profiles.restype=ci
        lib.p11_yuyv_exterior.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,ci,
            ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp,vp]
        lib.p11_yuyv_exterior.restype=ci
        lib.p11_locked_yuyv_exterior.argtypes=lib.p11_yuyv_exterior.argtypes+[ctypes.c_double]
        lib.p11_locked_yuyv_exterior.restype=ci
        lib.p11_v67_locked_pair.argtypes=[vp,ci,ci,ci,vp]+[ctypes.c_double]*5+[vp]+[ctypes.c_double]*3+[vp]*5
        lib.p11_v67_locked_pair.restype=ci
        lib.p11_v68_stabilize.argtypes=[vp,ci,ci,ci]+[vp]*6+[ci]+[vp]*4
        lib.p11_v68_stabilize.restype=ci
        lib.p11_locked_coherent_profiles.argtypes=[vp,ci,ci,ctypes.c_double,ctypes.c_double,
            ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp,vp]
        lib.p11_locked_coherent_profiles.restype=ci
        lib.p11_owner_admit.argtypes=[vp,vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_double,vp,vp]
        lib.p11_owner_admit.restype=ci
        lib.p11_preview_snapshot.argtypes=[vp,ci,ci,ci,vp,ci,ci,vp,ci,ci,ci,vp,ci,ci,vp]
        lib.p11_preview_snapshot.restype=ci
        remember(target,source,'tracker',cache_flags)
        _LIB=lib
        _STATUS={'source_sha256':digest,'backend':'cpp_V74_original_detection_kernels','path':str(target),'abi':3107,
                 'preview_snapshot_available':True,'preview_snapshot_signature':'paired_area2_15args',
                 'preview_snapshot_factors':[1,2],
                 'gray_backend':'yuyv_Y_area2_neon' if lib.p11_gray_backend()==2 else 'yuyv_Y_area2_scalar',
                 'geometry_backend':'cpp_projection_q8_and_fixed_guard',
                 'lk_backend':'cpp_cached_pyramids' if lib.p11_lk_available() else 'opencv_python_binding',
                 'lk_pyramid_cache':bool(lib.p11_lk_available()),'lk_pyramid_policy':'lazy_requested_levels',
                  'stable_edge_backend':'cpp_joint_motion_and_current_gray_recheck','locked_pair_backend':'cpp_current_locked64_independent24','packed_exterior_backend':'cpp_direct_YUV_bands_no_full_plane_pack',
                   'coherent_exterior_backend':'cpp_YUV_spatial_signed_peak_lock_TLS','opencv_dev_version':cv_version,
                 'blur_backend':'cpp_fixed_separable_neon' if lib.p11_gray_backend()==2 else 'cpp_fixed_separable_scalar',
                 'tracking_checks_backend':'cpp_ransac_motion_candidate' if lib.p11_filter_available() else 'python_ransac_cpp_geometry',
                 'original_Y_refinement_backend':'cpp_original_Y_64x65' if lib.p11_lk_available() else 'python_original_Y_64x65',
                 'control_backend':'cpp_checked_immutable_packet','appearance_backend':'cpp_gray_signature',
                 'merged_control_backend':'cpp_geometry_guard_tone_packet','preview_backend':'cpp_cached_q8_bilinear_direct_canvas',
                  'owner_completion_backend':'cpp_cached_owner_poll_snapshot',
                 'copy_backend':'cpp_bgr_memcpy','input_copy_backend':'cpp_yuyv_memcpy','owner_control_backend':'cpp_batch_arm_readonly_plan_wait',
                  'wait_backend':'cpp_owner_completion_gil_released','probe_backend':'cpp_aligned_32x32','observation_context':'cpp_edges_gate_motion_workspace','fused_frame_backend':'cpp_current_quad_probe_control'}
    except (RuntimeError,OSError,subprocess.SubprocessError) as exc:
        _LIB=None;_STATUS={'backend':'numpy_analytic_tls','reason':str(exc),
                          'lk_backend':'opencv_python_binding','lk_pyramid_cache':False}
        if required:raise RuntimeError(_STATUS['reason']) from exc
    return dict(_STATUS)

def native_status():return dict(_STATUS)

def gaussian3(gray, workspace):
    if _LIB is None:return None
    g=np.ascontiguousarray(gray,np.uint8);h,w=g.shape
    if workspace.dtype!=np.uint16 or workspace.size<3*w or not workspace.flags.c_contiguous:
        raise ValueError('Gaussian workspace layout invalid')
    out=np.empty_like(g)
    code=_LIB.p11_gaussian3(g.ctypes.data,w,h,g.strides[0],workspace.ctypes.data,out.ctypes.data)
    if code:raise ValueError('native Gaussian rejected: '+str(code))
    return out

def quad_valid(quad, shape, reference=None):
    if _LIB is None:return None
    q=np.ascontiguousarray(quad,np.float64).reshape(4,2)
    ref=None if reference is None else np.ascontiguousarray(reference,np.float64).reshape(4,2)
    code=_LIB.p11_quad_valid(q.ctypes.data,int(shape[1]),int(shape[0]),None if ref is None else ref.ctypes.data)
    if code<0:raise ValueError('native quad check rejected: '+str(code))
    return bool(code)

def spatial_support(points,quad):
    if _LIB is None:return None
    p=np.ascontiguousarray(points,np.float32).reshape(-1,2)
    if len(p)<4:return False
    if len(p)>100:raise ValueError('native boundary feature count exceeds100')
    q=np.ascontiguousarray(quad,np.float64).reshape(4,2)
    code=_LIB.p11_spatial(p.ctypes.data,len(p),q.ctypes.data)
    if code<0:raise ValueError('native spatial check rejected: '+str(code))
    return bool(code)

def filter_lk(points,forward,backward,status,reverse,error,anchor,previous,shape):
    if _LIB is None or not _LIB.p11_filter_available():return None
    p=np.ascontiguousarray(points,np.float32).reshape(-1,2);n=len(p)
    if not 4<=n<=100:raise ValueError('native LK filter feature count invalid')
    f=np.ascontiguousarray(forward,np.float32).reshape(n,2)
    b=np.ascontiguousarray(backward,np.float32).reshape(n,2)
    s=np.ascontiguousarray(status,np.uint8).reshape(n)
    sb=np.ascontiguousarray(reverse,np.uint8).reshape(n)
    e=np.ascontiguousarray(error,np.float32).reshape(n)
    a=np.ascontiguousarray(anchor,np.float64).reshape(4,2)
    old=np.ascontiguousarray(previous,np.float64).reshape(4,2)
    q=np.empty((4,2),np.float32);retained=np.empty((n,2),np.float32);stats=np.empty(5,np.float64)
    code=_LIB.p11_lk_filter(p.ctypes.data,f.ctypes.data,b.ctypes.data,s.ctypes.data,sb.ctypes.data,
        e.ctypes.data,n,a.ctypes.data,old.ctypes.data,shape[1],shape[0],q.ctypes.data,
        retained.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native LK consistency rejected: '+str(code))
    return q,retained[:int(stats[4])].copy(),dict(features=n,good_features=int(stats[1]),
        inlier_fraction=float(stats[2]),fb_median=float(stats[3]),filter_backend='cpp_ransac_geometry')

def prepare_regs(H,w,h):
    if _LIB is None:return None
    mat=np.ascontiguousarray(H,np.float64)
    if mat.shape!=(3,3):raise ValueError('H shape invalid')
    regs=np.empty(8,np.int32)
    code=_LIB.p11_prepare(mat.ctypes.data,int(w),int(h),regs.ctypes.data)
    if code:raise ValueError('native fixed H corner preflight rejected: '+str(code))
    return tuple(int(x) for x in regs)

def encode_packet(field,regs,wi,hi,wo,ho,flags):
    if _LIB is None:return None
    f=np.asarray(field)
    if f.shape!=(21,21,4) or f.dtype!=np.int32:raise ValueError('control field must be int32 21x21x4')
    f=np.ascontiguousarray(f)
    r=np.ascontiguousarray(regs,np.int32);out=np.empty(1776,dtype='<u4')
    code=_LIB.p11_packet(f.ctypes.data,r.ctypes.data,wi,hi,wo,ho,flags,out.ctypes.data)
    if code:raise ValueError('native control field/range rejected: '+str(code))
    return out.tobytes()

def gray_signature(gray,H,kernel):
    if _LIB is None:return None
    g=np.ascontiguousarray(gray,np.uint8);mat=np.ascontiguousarray(H,np.float64)
    k=np.ascontiguousarray(kernel,np.float32).reshape(9)
    if g.ndim!=2 or mat.shape!=(3,3):raise ValueError('signature layout invalid')
    structure=np.empty((128,96),np.float32);background=np.empty((8,8),np.float32)
    stats=np.empty(2,np.float64)
    code=_LIB.p11_signature(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],mat.ctypes.data,
        k.ctypes.data,structure.ctypes.data,background.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native appearance signature rejected: '+str(code))
    return dict(structure=structure,background=background,mean=float(stats[0]),std=float(stats[1]),
                backend='cpp_gray_signature')

def gray_area2(image, out):
    """Return False for unsupported layouts/sizes; never silently copy full BGR."""
    if _LIB is None:return False
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3 or
        image.strides[2]!=1 or image.strides[1]!=3):return False
    h,w=image.shape[:2]
    if w%2 or h%2 or min(w,h)<4 or max(w,h)>8192:return False
    if image.strides[0]<w*3:return False
    if out.shape!=(h//2,w//2) or out.dtype!=np.uint8 or not out.flags.c_contiguous:
        raise ValueError('gray observation destination layout invalid')
    code=_LIB.p11_gray2(image.ctypes.data,w,h,image.strides[0],out.ctypes.data)
    if code:raise ValueError('native gray observation rejected: '+str(code))
    return True

def merged_geometry(H, regs, nodes, nx, ny, uv, samples):
    """Return None for Python fallback; native failures remain hard rejections."""
    if _LIB is None:return None
    if len(regs)!=8 or any(int(x)!=x or not -(1<<31)<=int(x)<(1<<31) for x in regs):
        raise ValueError('native geometry registers outside signed32')
    mat=np.ascontiguousarray(H,np.float64)
    r=np.ascontiguousarray(regs,np.int32)
    if mat.shape!=(3,3) or r.shape!=(8,) or not np.isfinite(mat).all():
        raise ValueError('native geometry H/register shape invalid')
    nodes=np.ascontiguousarray(nodes,np.float64)
    uv=np.ascontiguousarray(uv,np.int32);samples=np.ascontiguousarray(samples,np.float64)
    if (nodes.shape!=(ny*nx,2) or uv.ndim!=2 or uv.shape[1]!=2 or
        samples.shape!=uv.shape or not 1<=len(uv)<=20000 or
        not (np.isfinite(nodes).all() and np.isfinite(samples).all())):
        raise ValueError('native geometry cached sample layout invalid')
    field=np.empty((21,21,4),np.int32);residual=np.empty(1,np.float64)
    code=_LIB.p11_plan_geometry(mat.ctypes.data,r.ctypes.data,nodes.ctypes.data,nx,ny,
        uv.ctypes.data,samples.ctypes.data,len(uv),field.ctypes.data,residual.ctypes.data)
    if code:raise ValueError('native geometry range/quantization rejected; no image DMA: '+str(code))
    return field,float(residual[0])

class LKCache:
    """Own both padded pyramids/derivatives; reuse forward/backward then promote."""
    def __init__(self):
        self.lib=_LIB
        self.forward=np.empty((100,1,2),np.float32);self.backward=np.empty_like(self.forward)
        self.status=np.empty(100,np.uint8);self.reverse=np.empty(100,np.uint8);self.errors=np.empty(100,np.float32)
        self.quad=np.empty((4,2),np.float32);self.retained=np.empty((100,2),np.float32)
        self.anchor_quad=np.empty((4,2),np.float64);self.previous_quad=np.empty_like(self.anchor_quad)
        self.filter_stats=np.empty(5,np.float64);self.flow_times=np.empty(2,np.float64)
        self.last_checked_timing={};self.motion_info=np.empty(4,np.float64)
        self.roi_quad=np.empty((4,2),np.float32);self.roi_stats=np.empty(3,np.int32)
        self.pointer=self.lib.p11_lk_create() if self.lib and self.lib.p11_lk_available() else None
        if self.lib and self.lib.p11_lk_available() and not self.pointer:
            raise MemoryError('native LK context allocation failed')
    def anchor(self,gray):
        if not self.pointer:return
        g=np.ascontiguousarray(gray,np.uint8)
        code=self.lib.p11_lk_anchor(self.pointer,g.ctypes.data,g.shape[1],g.shape[0])
        if code:raise ValueError('native LK anchor rejected: '+str(code))
    def track(self,gray,points,initial=None,levels=3,iterations=20):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if guess is not None and not np.isfinite(guess).all():raise ValueError('LK prediction not finite')
        if not 4<=len(p)<=100:raise ValueError('LK feature count outside4..100')
        f=self.forward[:len(p)];b=self.backward[:len(p)];s=self.status[:len(p)];sb=self.reverse[:len(p)]
        error=self.errors[:len(p)]
        code=self.lib.p11_lk_track(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],
            p.ctypes.data,len(p),f.ctypes.data,b.ctypes.data,s.ctypes.data,sb.ctypes.data,error.ctypes.data,
            None if guess is None else guess.ctypes.data,int(levels),int(iterations))
        if code:raise ValueError('native LK rejected frame: '+str(code))
        return f,s,error,b,sb
    def checked(self,gray,points,initial,anchor,previous,generation,levels=3,iterations=20):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if not 4<=len(p)<=100 or (guess is not None and not np.isfinite(guess).all()):raise ValueError('LK prediction/features invalid')
        if isinstance(generation,bool) or not isinstance(generation,(int,np.integer)) or not 0<=int(generation)<0xffffffff:raise ValueError('LK frame generation invalid')
        self.anchor_quad[:]=anchor;self.previous_quad[:]=previous
        self.filter_stats.fill(0.);self.flow_times.fill(0.)
        began=time.perf_counter();cpu=time.thread_time()
        code=self.lib.p11_lk_checked_motion(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],p.ctypes.data,len(p),
            None if guess is None else guess.ctypes.data,int(levels),int(iterations),int(generation),self.anchor_quad.ctypes.data,
            self.previous_quad.ctypes.data,self.quad.ctypes.data,self.retained.ctypes.data,self.filter_stats.ctypes.data,self.flow_times.ctypes.data,self.motion_info.ctypes.data)
        self.last_checked_timing=dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),native_checked_wall_s=time.perf_counter()-began,
            native_checked_thread_cpu_s=time.thread_time()-cpu,native_checked_code=int(code),
            transaction_backend='cpp_bidirectional_lk_filter',
            motion_model={0:'unavailable',1:'similarity_candidate',2:'projective_candidate'}.get(int(self.motion_info[0]),'invalid'),
            motion_good_features=int(self.motion_info[1]),motion_inliers=int(self.motion_info[2]),
            motion_reprojection_rms=float(self.motion_info[3]),current_four_edges_required=True)
        if code<=-100:raise ValueError('native LK rejected frame: '+str(code+100))
        if code:raise ValueError('native LK consistency rejected: '+str(code))
        n=int(self.filter_stats[4])
        detail=dict(lk_backend='cpp_cached_pyramids_checked',features=len(p),good_features=int(self.filter_stats[1]),filter_backend='cpp_bidirectional_lk_filter',
            inliers=n,inlier_fraction=float(self.filter_stats[2]),fb_median=float(self.filter_stats[3]),
            motion_model=self.last_checked_timing['motion_model'],motion_reprojection_rms=float(self.motion_info[3]),
            current_four_edges_required=True)
        return self.quad.copy(),self.retained[:n].copy(),detail,dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),transaction_backend='cpp_bidirectional_lk_filter')
    def roi_features(self,gray,quad,retained=None):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);points=np.empty((0,2),np.float32) if retained is None else np.ascontiguousarray(retained,np.float32).reshape(-1,2)
        if len(points)>100:raise ValueError('ROI retained features exceed100')
        self.roi_quad[:]=quad
        code=self.lib.p11_roi_features(g.ctypes.data,g.shape[1],g.shape[0],self.roi_quad.ctypes.data,
            points.ctypes.data,len(points),self.retained.ctypes.data,self.roi_stats.ctypes.data)
        if code:raise ValueError('Native corner ROI rejected: '+str(code))
        return self.retained[:int(self.roi_stats[0])].copy(),dict(action='native_outer_corner_roi',regions=int(self.roi_stats[1]),
            added=int(self.roi_stats[2]),features=int(self.roi_stats[0]),workspace_reused=True)
    def promote(self):
        if self.pointer:
            code=self.lib.p11_lk_promote(self.pointer)
            if code:raise ValueError('native LK promotion failed: '+str(code))
    def close(self):
        if self.pointer:
            self.lib.p11_lk_destroy(self.pointer);self.pointer=None
    def __del__(self):
        try:self.close()
        except Exception:pass

def measure_edges(gray, quad, radius, checked=False):
    if _LIB is None:return None
    g=np.ascontiguousarray(gray,dtype=np.uint8)
    if g.ndim!=2:raise ValueError('native edges require grayscale')
    q=np.ascontiguousarray(quad,dtype=np.float64).reshape(4,2)
    result=np.empty((4,2),np.float64);stats=np.empty(21,np.float64)
    function=_LIB.p11_edges_checked if checked else _LIB.p11_edges
    code=function(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],q.ctypes.data,
                       float(radius),result.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native edge helper rejected input: '+str(code))
    return result.astype(np.float32),dict(edge_support=stats[:4].tolist(),
        edge_polarity=stats[4:8].astype(int).tolist(),refined_corners=int(stats[16]),
        supported_edges=int(stats[17]),median_edge_shift=float(np.median(stats[8:12])),
        edge_rms=stats[12:16].tolist(),max_edge_rms=float(max(stats[12:16])),
        edge_backend='cpp_analytic_tls',native_valid=bool(stats[20]) if checked else None)

def fixed_coordinates(regs,u,v,field):
    if len(regs)!=8 or any(int(r)!=r or not -(1<<31)<=int(r)<(1<<31) for r in regs):
        raise ValueError('H寄存器超出signed32，禁止截断后误加载')
    if _LIB is None:
        from pl_fields import coordinates
        x,y,_=coordinates(regs,u,v,field)
        return x/65536.,y/65536.
    u,v=np.broadcast_arrays(u,v)
    uv=np.ascontiguousarray(np.column_stack([u.ravel(),v.ravel()]),np.int32)
    r=np.ascontiguousarray(regs,np.int32);f=np.ascontiguousarray(field,np.int32)
    out=np.empty((len(uv),2),np.float64)
    if r.shape!=(8,) or f.shape!=(21,21,4):raise ValueError('native guard shape mismatch')
    code=_LIB.p11_guard(r.ctypes.data,f.ctypes.data,uv.ctypes.data,len(uv),out.ctypes.data)
    if code:raise ValueError('定点几何采样范围不安全，未启动图像DMA: '+str(code))
    return out[:,0].reshape(u.shape),out[:,1].reshape(u.shape)


def prepare_control(H,nodes,nx,ny,uv,samples,gain,offset,wi,hi,wo,ho,flags=15):
    """One native call; same fixed arithmetic and 0.65-source-pixel guard."""
    if _LIB is None:return None
    mat=np.ascontiguousarray(H,np.float64)
    nodes=np.ascontiguousarray(nodes,np.float64)
    uv=np.ascontiguousarray(uv,np.int32)
    samples=np.ascontiguousarray(samples,np.float64)
    gain=np.ascontiguousarray(gain,np.int32);offset=np.ascontiguousarray(offset,np.int32)
    if (mat.shape!=(3,3) or nodes.shape!=(nx*ny,2) or uv.ndim!=2 or uv.shape[1]!=2
        or samples.shape!=uv.shape or gain.shape!=(21,21) or offset.shape!=(21,21)
        or not 1<=len(uv)<=20000 or not 1<=nx<=21 or not 1<=ny<=21
        or not all(np.isfinite(a).all() for a in (mat,nodes,samples))):
        raise ValueError('merged control geometry layout invalid')
    if any(isinstance(n,bool) or int(n)!=n or not 2<=int(n)<=1280 for n in (wi,hi,wo,ho)):
        raise ValueError('merged control dimensions outside2..1280')
    out=np.empty(1776,dtype='<u4');residual=np.empty(1,np.float64)
    code=_LIB.p11_prepare_control(mat.ctypes.data,nodes.ctypes.data,nx,ny,uv.ctypes.data,
        samples.ctypes.data,len(uv),gain.ctypes.data,offset.ctypes.data,wi,hi,wo,ho,flags,
        out.ctypes.data,residual.ctypes.data)
    if code:raise ValueError('native merged control rejected; no image DMA: '+str(code))
    return out.tobytes(),float(residual[0])


def probe_signature(gray,H):
    if _LIB is None:return None
    g=np.ascontiguousarray(gray,np.uint8);mat=np.ascontiguousarray(H,np.float64)
    if g.ndim!=2 or mat.shape!=(3,3):raise ValueError('Probe layout invalid')
    structure=np.empty((32,32),np.float32);background=np.empty((8,8),np.float32)
    stats=np.empty(2,np.float64)
    code=_LIB.p11_probe(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],mat.ctypes.data,
        structure.ctypes.data,background.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('Aligned probe rejected: '+str(code))
    return dict(structure=structure,background=background,mean=float(stats[0]),std=float(stats[1]),
        backend='cpp_aligned_32x32')


def wait_io(pl_array,dma_array,before,kind,timeout,out=None):
    """None means unsupported layout: caller retains Python polling. Never copy MMIO."""
    if _LIB is None:return None
    for array,minimum in ((pl_array,0x3c),(dma_array,0x38)):
        if (not isinstance(array,np.ndarray) or array.dtype!=np.dtype('uint32')
            or not array.flags.c_contiguous or array.nbytes<minimum or array.ctypes.data%4):return None
    if np.isfinite(timeout) and float(timeout)>3600:return None
    if int(kind) not in (0,1) or not np.isfinite(timeout) or not 0<float(timeout)<=3600:
        raise ValueError('Native wait arguments invalid')
    result=np.empty(4,np.uint32) if out is None else out
    if result.shape!=(4,) or result.dtype!=np.uint32 or not result.flags.c_contiguous or not result.flags.writeable:raise ValueError('Wait output workspace invalid')
    code=_LIB.p11_wait_io(pl_array.ctypes.data,dma_array.ctypes.data,int(before)&0xffffffff,
        int(kind),float(timeout),result.ctypes.data)
    if code<0:raise ValueError('Native wait rejected: '+str(code))
    return int(code),dict(pl_status=int(result[0]),pl_error=int(result[1]),tx=int(result[2]),rx=int(result[3]))


def fused_observation2(image,scratch,workspace,out=None,timing=None):
    if _LIB is None:return None
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3
        or image.strides[1:]!=(3,1) or image.strides[0]<image.shape[1]*3):return None
    h,w=image.shape[:2]
    if w%2 or h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (scratch.shape!=(h//2,w//2) or scratch.dtype!=np.uint8 or not scratch.flags.c_contiguous
        or workspace.dtype!=np.uint16 or workspace.size<3*(w//2) or not workspace.flags.c_contiguous):
        raise ValueError('Fused observation workspace invalid')
    if out is None:out=np.empty_like(scratch)
    if timing is None:timing=np.empty(2,np.float64)
    if out.shape!=scratch.shape or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable or np.shares_memory(out,scratch):
        raise ValueError('Observation output aliases scratch or has invalid layout')
    code=_LIB.p11_observe2(image.ctypes.data,w,h,image.strides[0],scratch.ctypes.data,
        workspace.ctypes.data,out.ctypes.data,timing.ctypes.data)
    if code:raise ValueError('Fused observation rejected: '+str(code))
    return out,dict(resize_gray_s=float(timing[0]),blur_s=float(timing[1]))

def profile_snapshot(raw=False,out=None):
    if _LIB is None:return None if raw else {}
    f=_LIB.p11_profile_snapshot
    if out is None:out=np.empty(90,np.float64)
    if (not isinstance(out,np.ndarray) or out.dtype!=np.float64 or out.shape!=(90,)
            or not out.flags.c_contiguous or not out.flags.writeable):
        raise ValueError('Native profile output workspace invalid')
    if f(out.ctypes.data,len(out)):raise RuntimeError('Native profile layout rejected')
    if raw:return out
    names=['p11_lk_anchor', 'p11_lk_track', 'p11_lk_promote', 'p11_gray2', 'p11_gaussian3', 'p11_quad_valid', 'p11_spatial', 'p11_lk_filter', 'p11_edges', 'p11_guard', 'p11_plan_geometry', 'p11_prepare', 'p11_packet', 'p11_signature', 'p11_prepare_control', 'p11_probe', 'p11_wait_io', 'p11_observe2', 'p11_edges_motion', 'p11_copy_bgr', 'p11_arm_io', 'p11_plan_wait', 'p11_frame_state', 'p11_motion_values', 'outer_calls', 'p11_observe_edges', 'p11_lk_checked', 'p11_roi_features', 'p11_owner_batch', 'p11_owner_complete']
    return {name:dict(wall_s=float(out[i*3]),thread_cpu_s=float(out[i*3+1]),calls=int(out[i*3+2])) for i,name in enumerate(names)}


def _mmio_layout(array,minimum):
    return (isinstance(array,np.ndarray) and array.dtype==np.dtype('uint32')
        and array.flags.c_contiguous and array.nbytes>=minimum and array.ctypes.data%4==0)

def copy_bgr_native(source,destination):
    if _LIB is None:return False
    h,w=source.shape[:2]
    code=_LIB.p11_copy_bgr(source.ctypes.data,destination.ctypes.data,w,h,
                          source.strides[0],destination.strides[0])
    if code:raise ValueError('Native BGR copy rejected: '+str(code))
    return True

def arm_io(pl,dma,src,dst,send,receive,sequence=None):
    if _LIB is None or not _mmio_layout(pl,12) or not _mmio_layout(dma,0x5c):return False
    values=(src,dst,send,receive,0 if sequence is None else sequence)
    if any(isinstance(n,bool) or int(n)!=n or not 0<=int(n)<=0xffffffff for n in values):
        raise ValueError('Native arm uint32 argument invalid')
    code=_LIB.p11_arm_io(pl.ctypes.data,dma.ctypes.data,*map(int,values),int(sequence is not None))
    if code:raise RuntimeError('Native owner arm rejected: '+str(code))
    return True

def frame_state(pl,dma):
    if _LIB is None or not _mmio_layout(pl,0xcc) or not _mmio_layout(dma,0x5c):return None
    out=np.empty(12,np.uint32)
    if _LIB.p11_frame_state(pl.ctypes.data,dma.ctypes.data,out.ctypes.data):
        raise RuntimeError('Native frame state rejected')
    return tuple(map(int,out))

def plan_wait(planner,pixel,dma,sequence,kind,timeout):
    if (_LIB is None or not _mmio_layout(planner,0x74) or not _mmio_layout(pixel,0xe0)
        or not _mmio_layout(dma,0x38)):return None
    if (isinstance(sequence,bool) or not 0<int(sequence)<=0xffffffff or kind not in (0,1)
        or not np.isfinite(timeout) or not 0<float(timeout)<=3600):
        raise ValueError('Native plan wait argument invalid')
    out=np.zeros(4,np.uint32)
    code=_LIB.p11_plan_wait(planner.ctypes.data,pixel.ctypes.data,dma.ctypes.data,
                           int(sequence),int(kind),float(timeout),out.ctypes.data)
    if code<0:raise RuntimeError('Native plan wait rejected')
    return int(code),tuple(map(int,out))


def motion_values(candidate,prediction,previous,anchor,drift):
    if _LIB is None:return None
    points=[np.ascontiguousarray(q,np.float32).reshape(4,2) for q in (candidate,prediction,previous,anchor)]
    if drift.shape!=(4,2) or drift.dtype!=np.float32 or not drift.flags.c_contiguous:
        raise ValueError('Motion drift workspace invalid')
    out=np.empty(5,np.float64)
    code=_LIB.p11_motion_values(*(q.ctypes.data for q in points),drift.ctypes.data,out.ctypes.data)
    if code:raise ValueError('Native motion reduction rejected: '+str(code))
    return tuple(map(float,out))


class EdgeMotionWorkspace:
    """Private chronological PS context; buffers reused across frames."""
    def __init__(self):
        self.predicted=np.empty((4,2),np.float64)
        self.previous=np.empty((4,2),np.float32);self.anchor=np.empty((4,2),np.float32)
        self.polarity=np.empty(4,np.int32)
        self.result=np.empty((4,2),np.float64);self.stats=np.empty(21,np.float64)
        self.result32=np.empty((4,2),np.float32);self.light_results=False;self.decode_timing=(0.,0.)
        self.motion=np.empty(5,np.float64);self.gate=np.empty(6,np.float64)
    def measure(self,gray,prediction,previous,anchor,drift,polarity,radius=5.):
        if _LIB is None:return None
        g=np.ascontiguousarray(gray,np.uint8)
        if g.ndim!=2 or drift.dtype!=np.float32 or drift.shape!=(4,2) or not drift.flags.c_contiguous:
            raise ValueError('Observation context layout invalid')
        self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
        code=_LIB.p11_edges_motion(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,
            drift.ctypes.data,self.polarity.ctypes.data,float(radius),self.result.ctypes.data,
            self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data)
        if code:raise ValueError('Native observation context rejected: '+str(code))
        return self.decode()
    def decode(self):
        if self.light_results:
            from v70_ps import decode_light_edges
            return decode_light_edges(self)
        stats=self.stats;shifts=sorted(float(v) for v in stats[8:12])
        evidence=dict(valid=bool(stats[20]),edge_support=stats[:4].tolist(),
            edge_polarity=stats[4:8].astype(int).tolist(),refined_corners=int(stats[16]),
            supported_edges=int(stats[17]),median_edge_shift=(shifts[1]+shifts[2])*.5,
            edge_rms=stats[12:16].tolist(),max_edge_rms=float(self.gate[2]),
            edge_backend='cpp_edges_gate_motion_context')
        gate=dict(reliable=bool(self.gate[0]),min_support=float(self.gate[1]),
            max_rms=float(self.gate[2]),prediction_correction=float(self.gate[3]),
            polarity_flips=int(self.gate[4]),radius=float(self.gate[5]))
        return self.result.astype(np.float32),evidence,gate,tuple(map(float,self.motion)) if gate['reliable'] else None


def profile_os_snapshot(out=None):
    if _LIB is None:return None
    values=np.empty((30,4),np.float64) if out is None else out
    if (not isinstance(values,np.ndarray) or values.dtype!=np.float64 or values.shape!=(30,4)
            or not values.flags.c_contiguous or not values.flags.writeable):
        raise ValueError('Native OS profile output workspace invalid')
    code=_LIB.p11_profile_os_snapshot(values.ctypes.data,values.size)
    if code:raise RuntimeError('Native OS profile layout mismatch')
    return values


class FusedPrepareLayoutError(ValueError):
    """A Python/native memory contract error; distinct from a scene rejection."""


def _frame_int(value,low,high,name):
    if (isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer))
            or not low<=int(value)<=high):
        raise FusedPrepareLayoutError('Fused '+name+' must be integer in '+str((low,high)))
    return int(value)


def _readonly_array(value,dtype,shape,name):
    try:array=np.ascontiguousarray(value,dtype)
    except (TypeError,ValueError) as exc:
        raise FusedPrepareLayoutError('Fused '+name+' conversion invalid') from exc
    if array.shape!=shape:
        raise FusedPrepareLayoutError('Fused '+name+' shape invalid: '+str(array.shape))
    # Bytes-backed snapshots cannot be mutated by their original owner. A
    # readonly typed cache supplied by the chronological producer needs no copy.
    if array.flags.writeable:array=np.frombuffer(array.tobytes(),dtype).reshape(shape)
    return array


def _destroy_frame_context(library,pointer):
    # The finalizer's arguments keep the owning CDLL alive independently of
    # module-global _LIB; closing a later session cannot unload this callback.
    library.p11_frame_destroy(pointer)


class FramePrepareWorkspace:
    """One chronological producer owns input, output and native guard scratch.

    scale is exactly [source_width / gray_width, source_height / gray_height].
    C++ consumes separate sx/sy doubles; scalar scale is deliberately rejected.
    Only immutable reference/control identities qualify for validation caching.
    Current q, scale and H are rewritten for every frame. Returned observations,
    H and control bytes own their memory and never alias this scratch workspace.
    """
    def __init__(self):
        self.quad=np.empty((4,2),np.float64);self.scale=np.empty(2,np.float64)
        self.H=np.empty((3,3),np.float64);self.shape=np.empty(4,np.float64)
        self.structure=np.empty((32,32),np.float32);self.background=np.empty((8,8),np.float32)
        self.info=np.empty(11,np.float64);self.packet=np.empty(1776,dtype='<u4')
        self._quad_pointer=self.quad.ctypes.data
        self._output_pointers=tuple(a.ctypes.data for a in
            (self.H,self.shape,self.structure,self.background,self.info,self.packet))
        self.references=None;self.reference_arrays=None;self.reference_pointers=None
        self.control_arrays=None;self.control_inputs=None;self.control_layout=None;self.control_pointers=None
        self._owner=None;self._context=None;self._context_library=None;self._context_finalizer=None

    def close(self):
        if self._context_finalizer is not None:self._context_finalizer()
        self._context=None;self._context_library=None;self._context_finalizer=None

    def _native_context(self):
        if self._context_library is not _LIB:
            self.close();pointer=_LIB.p11_frame_create()
            if not pointer:raise RuntimeError('Native frame workspace allocation failed')
            self._context=pointer;self._context_library=_LIB
            # Retain this specific CDLL, not the later module-global _LIB.
            self._context_finalizer=weakref.finalize(self,_destroy_frame_context,_LIB,pointer)
        return self._context

    def prepare(self,q,gray,scale,wo,ho,refs,control=None):
        if _LIB is None:return None
        began=time.perf_counter();owner=threading.get_ident()
        if self._owner is None:self._owner=owner
        elif owner!=self._owner:raise FusedPrepareLayoutError('Fused workspace requires one chronological producer thread')
        try:qa=np.asarray(q);sa=np.asarray(scale);g=np.asarray(gray)
        except (TypeError,ValueError) as exc:
            raise FusedPrepareLayoutError('Fused frame input conversion invalid') from exc
        if qa.shape!=(4,2) or qa.dtype.kind not in 'fiu' or sa.shape!=(2,) or sa.dtype.kind not in 'fiu':
            raise FusedPrepareLayoutError('Fused quad must be4x2; scale must be finite positive [sx, sy]')
        if (g.dtype!=np.uint8 or g.ndim!=2 or min(g.shape)<2 or max(g.shape)>1280
                or g.strides[1]!=1 or not g.shape[1]<=g.strides[0]<=0x7fffffff):
            raise FusedPrepareLayoutError('Fused grayscale byte/stride contract invalid')
        np.copyto(self.quad,qa,casting='unsafe');np.copyto(self.scale,sa,casting='unsafe')
        sx=float(self.scale[0]);sy=float(self.scale[1])
        if not math.isfinite(sx) or not math.isfinite(sy) or sx<=0 or sy<=0:
            raise FusedPrepareLayoutError('Fused scale must contain finite positive sx and sy')
        # Current q values are checked by p11_quad_h before probing or control
        # encoding. A scene/quad rejection must not disable later valid frames.
        wo=_frame_int(wo,2,1280,'output width');ho=_frame_int(ho,2,1280,'output height')
        try:key=tuple(refs)
        except TypeError as exc:raise FusedPrepareLayoutError('Fused references tuple invalid') from exc
        if len(key)!=3:raise FusedPrepareLayoutError('Probe references require structure/background/shape')
        reference_hit=(self.references is not None and all(a is b for a,b in zip(key,self.references)))
        if not reference_hit:
            self.reference_arrays=tuple(_readonly_array(a,dtype,shape,name)
                for a,dtype,shape,name in zip(key,(np.float32,np.float32,np.float64),
                    ((32,32),(8,8),(4,)),('structure reference','background reference','shape reference')))
            self.reference_pointers=tuple(a.ctypes.data for a in self.reference_arrays)
            self.references=key if all(isinstance(a,np.ndarray) and not a.flags.writeable for a in key) else None
        rs,rb,rshape=self.reference_pointers
        control_hit=False
        if control is None:
            nx=ny=count=wi=hi=flags=0;pointers=(0,0,0,0,0)
        else:
            if not isinstance(control,(tuple,list)) or len(control)!=10:
                raise FusedPrepareLayoutError('Fused control tuple requires10 fields')
            nodes,nx,ny,uv,samples,gain,offset,wi,hi,flags=control
            nx=_frame_int(nx,2,21,'node columns');ny=_frame_int(ny,2,21,'node rows')
            wi=_frame_int(wi,2,1280,'input width');hi=_frame_int(hi,2,1280,'input height')
            flags=_frame_int(flags,0,15,'border flags')
            arrays=(nodes,uv,samples,gain,offset);layout=(nx,ny,wi,hi,flags)
            control_hit=(self.control_inputs is not None and layout==self.control_layout
                and all(a is b for a,b in zip(arrays,self.control_inputs)))
            if not control_hit:
                expected_dtypes=(np.float64,np.int32,np.float64,np.int32,np.int32)
                if (any(not isinstance(a,np.ndarray) or a.dtype!=dtype or not a.flags.c_contiguous
                        for a,dtype in zip(arrays,expected_dtypes))
                    or nodes.shape!=(nx*ny,2) or uv.ndim!=2 or uv.shape[1]!=2
                    or samples.shape!=uv.shape or gain.shape!=(21,21) or offset.shape!=(21,21)
                    or not 1<=len(uv)<=20000):
                    raise FusedPrepareLayoutError('Fused control pointer/dtype/layout invalid before native access')
                self.control_arrays=tuple(_readonly_array(a,dtype,a.shape,'control input')
                    for a,dtype in zip(arrays,expected_dtypes))
                self.control_pointers=tuple(a.ctypes.data for a in self.control_arrays)
                self.control_layout=layout
                self.control_inputs=arrays if all(not a.flags.writeable for a in arrays) else None
            pointers=self.control_pointers;count=len(self.control_arrays[1])
        context=self._native_context();native_begin=time.perf_counter()
        code=_LIB.p11_frame_prepare(context,self._quad_pointer,g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            sx,sy,wo,ho,rs,rb,rshape,pointers[0],nx,ny,pointers[1],pointers[2],count,
            pointers[3],pointers[4],wi,hi,flags,int(control is not None),*self._output_pointers)
        if code in (-1,-5,-7):
            raise FusedPrepareLayoutError('Native frame pointer/reference/owner contract rejected: '+str(code))
        if code:raise ValueError('Current quad/probe rejected before image DMA: '+str(code))
        publish_begin=time.perf_counter()
        observations=tuple(a.copy() for a in (self.structure,self.background,self.shape))
        for a in observations:a.setflags(write=False)
        probe=dict(structure=observations[0],background=observations[1],shape=observations[2],
            mean=float(self.info[0]),std=float(self.info[1]),backend='cpp_current_quad_probe_control')
        changes=tuple(float(x) for x in self.info[2:5])
        status=int(self.info[6]);wire=self.packet.tobytes() if control is not None and status==0 else None
        H=self.H.copy();finished=time.perf_counter()
        return dict(H=H,probe=probe,changes=changes,wire=wire,residual=float(self.info[5]),control_code=status,
            h_native_s=float(self.info[7]),probe_native_s=float(self.info[8]),control_native_s=float(self.info[9]),
            native_transaction_s=float(self.info[10]),wrapper_prepare_s=native_begin-began,
            wrapper_publish_s=finished-publish_begin,wrapper_total_s=finished-began,
            reference_cache_hit=reference_hit,control_cache_hit=control_hit)


class ObservationWorkspace(EdgeMotionWorkspace):
    """Own bounded gray/filter/corner buffers; no pointer escapes the call."""
    def __init__(self):
        super().__init__();self.times=np.empty(4,np.float64)
    def observe(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius=5.):
        if _LIB is None:return None
        h,w=image.shape[:2]
        if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3 or image.strides[1:]!=(3,1)
            or image.strides[0]<w*3 or min(w,h)<4 or max(w,h)>1280 or w%2 or h%2):return None
        if (out.shape!=(h//2,w//2) or scratch.shape!=out.shape or out.dtype!=np.uint8 or scratch.dtype!=np.uint8
            or rows.dtype!=np.uint16 or rows.size<3*(w//2) or drift.dtype!=np.float32 or drift.shape!=(4,2)
            or any(not a.flags.c_contiguous or not a.flags.writeable for a in (scratch,rows,out,drift))
            or np.shares_memory(out,scratch)):
            raise ValueError('Merged observation workspace invalid before native access')
        self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
        code=_LIB.p11_observe_edges(image.ctypes.data,w,h,image.strides[0],scratch.ctypes.data,rows.ctypes.data,out.ctypes.data,
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,drift.ctypes.data,self.polarity.ctypes.data,
            float(radius),self.result.ctypes.data,self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data,self.times.ctypes.data)
        if code and code>-200:raise ValueError('Merged observation rejected: '+str(code))
        return (self.decode() if code==0 else None),dict(edge_error=(code+200 if code else None),resize_gray_s=float(self.times[0]),blur_s=float(self.times[1]),edge_gate_motion_s=float(self.times[2]),
            native_transaction_s=float(self.times[3]),transaction_backend='cpp_gray_gaussian_edges_confidence_motion')

class OwnerBatch:
    """Cached admitted mappings/output scratch; only the creating owner may call."""
    def __init__(self,planner,pixel,dma):
        import threading
        self.lib=_LIB;self.owner=threading.get_ident();self.arrays=(planner,pixel,dma)
        self.available=bool(self.lib)
        for a,minimum in zip(self.arrays,(0xc4,0xe4,0x5c)):
            self.available=self.available and isinstance(a,np.ndarray) and a.dtype==np.uint32 and a.flags.c_contiguous and a.nbytes>=minimum and a.ctypes.data%4==0
        self.pointers=tuple(a.ctypes.data for a in self.arrays) if self.available else ()
        self.state=np.empty(20,np.uint32)
    def call(self,operation=0,sequence=0,src=0,dst=0,timeout=1.):
        import threading
        if threading.get_ident()!=self.owner:raise RuntimeError('Native device transaction must stay on owner')
        if not self.available:return None
        if not 0<float(timeout)<=(30 if operation==3 else 1) or not np.isfinite(timeout):raise ValueError('Owner batch deadline invalid')
        code=self.lib.p11_owner_batch(*self.pointers,int(src),int(dst),int(sequence),float(timeout),int(operation),self.state.ctypes.data)
        if code<0:raise ValueError('Native device transaction layout rejected: '+str(code))
        return int(code),self.state
    def admit(self,sequence,input_size,output_size,capacity,timeout=1.):
        if threading.get_ident()!=self.owner:raise RuntimeError('Native device transaction must stay on owner')
        if not self.available:return None
        if not hasattr(self,'admit_times'):self.admit_times=np.empty(2,np.float64)
        code=self.lib.p11_owner_admit(*self.pointers,int(sequence),int(input_size),int(output_size),int(capacity),float(timeout),self.state.ctypes.data,self.admit_times.ctypes.data)
        if code<0:raise ValueError('Native owner admission layout rejected '+str(code))
        return int(code),self.state,self.admit_times


def preview_snapshot_available():
    # The loader admits ABI3107 and binds the unchanged 15-argument export.
    # A future ABI needs explicit admission here; do not assume ABI>=3106.
    return bool(_LIB is not None and _STATUS.get('abi')==3107
        and _STATUS.get('preview_snapshot_available',False)
        and _STATUS.get('preview_snapshot_signature')=='paired_area2_15args')


def preview_snapshot(raw,raw_out,bgr,bgr_out,times):
    if not preview_snapshot_available():return False
    from v31_pixels import require_yuyv
    require_yuyv(raw)
    for value,channels in ((raw_out,2),(bgr,3),(bgr_out,3)):
        if value.dtype!=np.uint8 or value.ndim!=3 or value.shape[2]!=channels or value.strides[-1]!=1 or value.strides[-2]!=channels:
            raise ValueError('Preview snapshot layout invalid')
    if (not raw_out.flags.c_contiguous or not bgr_out.flags.c_contiguous
            or not raw_out.flags.writeable or not bgr_out.flags.writeable
            or times.shape!=(2,) or times.dtype!=np.float64
            or not times.flags.c_contiguous or not times.flags.writeable):
        raise ValueError('Preview snapshot workspace invalid')
    code=_LIB.p11_preview_snapshot(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],raw_out.ctypes.data,raw_out.shape[1],raw_out.shape[0],
        bgr.ctypes.data,bgr.shape[1],bgr.shape[0],bgr.strides[0],bgr_out.ctypes.data,bgr_out.shape[1],bgr_out.shape[0],times.ctypes.data)
    if code:raise ValueError('Preview snapshot rejected '+str(code))
    return True

def completion_probe(pl_array,dma_array,before,kind,out):
    if _LIB is None:return None
    if out.dtype!=np.uint32 or out.shape!=(4,) or not out.flags.c_contiguous:raise ValueError('Completion probe scratch invalid')
    code=_LIB.p11_io_probe(pl_array.ctypes.data,dma_array.ctypes.data,int(before)&0xffffffff,int(kind),out.ctypes.data)
    if code<0:raise ValueError('Native completion probe rejected: '+str(code))
    return int(code),dict(pl_status=int(out[0]),pl_error=int(out[1]),tx=int(out[2]),rx=int(out[3]))


def copy_entry():
    """Admitted CPU memcpy only; no device mapping is supplied to the worker."""
    return _LIB.p11_copy_bgr if _LIB is not None else None


class OwnerCompletion:
    """Persistent mapping pointers, result scratch and function bindings."""
    def __init__(self,pl,dma):
        self.owner=threading.get_ident();self.arrays=(pl,dma)
        self.available=bool(_LIB) and _mmio_layout(pl,0xcc) and _mmio_layout(dma,0x5c)
        self.state=np.zeros(12,np.uint32);self.completed=None
        self.before=0;self.kind=1
        self.stats=dict(probe_calls=0,wait_calls=0,native_wait_s=0.,snapshots=0)
        if self.available:
            self.pointers=(int(pl.ctypes.data),int(dma.ctypes.data))
            self.output=int(self.state.ctypes.data)
            self.function=_LIB.p11_owner_complete;self.state_function=_LIB.p11_frame_state
    def begin(self,before,kind):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached completion owner')
        if kind not in (0,1):raise ValueError('Completion kind invalid')
        self.before=int(before)&0xffffffff;self.kind=kind;self.completed=None
    def poll(self,timeout=0.):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached completion owner')
        if not self.available:return None
        began=time.perf_counter()
        code=self.function(*self.pointers,self.before,self.kind,float(timeout),self.output)
        self.stats['native_wait_s']+=time.perf_counter()-began
        self.stats['wait_calls' if timeout else 'probe_calls']+=1
        if code<0:raise ValueError('Cached owner completion rejected: '+str(code))
        if code==0:self.completed=(self.before,self.kind)
        return int(code)
    def snapshot(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached snapshot owner')
        if not self.available:return None
        self.completed=None;code=self.state_function(*self.pointers,self.output)
        if code:raise ValueError('Cached owner snapshot rejected: '+str(code))
        self.stats['snapshots']+=1;return self.state
    def completed_state(self,before,kind=1):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong completion-state owner')
        return self.state if self.completed==(int(before)&0xffffffff,kind) else None
    def error_state(self):
        return dict(pl_status=int(self.state[0]),pl_error=int(self.state[1]),
                    tx=int(self.state[2]),rx=int(self.state[3]))





# Raw YUYV dispatch, keeping the existing BGR helper only for setup previews.
_bgr_gray_area2=gray_area2
_bgr_fused_observation2=fused_observation2
_bgr_observe=ObservationWorkspace.observe
_bgr_copy_entry=copy_entry

def gray_area2(image,out):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_gray_area2(image,out)
    if _LIB is None:return False
    from v31_pixels import require_yuyv,color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return False
    if out.shape!=(h//2,w//2) or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable:raise ValueError('Y output workspace')
    code=_LIB.p11_yuyv_gray2(image.ctypes.data,w,h,image.strides[0],color_mode(),out.ctypes.data)
    if code:raise ValueError('Y observer rejected '+str(code))
    return True

def fused_observation2(image,scratch,workspace,out=None,timing=None):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_fused_observation2(image,scratch,workspace,out,timing)
    if _LIB is None:return None
    from v31_pixels import require_yuyv,color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (scratch.shape!=(h//2,w//2) or scratch.dtype!=np.uint8 or not scratch.flags.c_contiguous or not scratch.flags.writeable
        or workspace.dtype!=np.uint16 or workspace.size<3*(w//2) or not workspace.flags.c_contiguous or not workspace.flags.writeable):raise ValueError('Y Gaussian workspace')
    if out is None:out=np.empty_like(scratch)
    if timing is None:timing=np.empty(2,np.float64)
    if (out.shape!=scratch.shape or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable
        or np.shares_memory(out,scratch) or timing.dtype!=np.float64 or timing.shape!=(2,) or not timing.flags.c_contiguous):raise ValueError('Y output alias/layout')
    code=_LIB.p11_yuyv_observe2(image.ctypes.data,w,h,image.strides[0],color_mode(),scratch.ctypes.data,workspace.ctypes.data,out.ctypes.data,timing.ctypes.data)
    if code:raise ValueError('Y fused observer rejected '+str(code))
    return out,dict(resize_gray_s=float(timing[0]),blur_s=float(timing[1]),input_format='YUYV',ps_luminance='direct_Y_normalized')

def _y_observe(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius=5.):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_observe(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius)
    if _LIB is None:return None
    from v31_pixels import require_yuyv,color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (out.shape!=(h//2,w//2) or scratch.shape!=out.shape or out.dtype!=np.uint8 or scratch.dtype!=np.uint8
        or rows.dtype!=np.uint16 or rows.size<3*(w//2) or drift.dtype!=np.float32 or drift.shape!=(4,2)
        or any(not a.flags.c_contiguous or not a.flags.writeable for a in (scratch,rows,out,drift)) or np.shares_memory(out,scratch)):raise ValueError('Y edge workspace')
    self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
    if self.light_results:
        from v70_ps import observe_yuyv_bound
        code=observe_yuyv_bound(self,image,scratch,rows,out,drift,radius,color_mode(),_LIB)
    else:
        code=_LIB.p11_yuyv_observe_edges(image.ctypes.data,w,h,image.strides[0],color_mode(),scratch.ctypes.data,rows.ctypes.data,out.ctypes.data,
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,drift.ctypes.data,self.polarity.ctypes.data,
            float(radius),self.result.ctypes.data,self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data,self.times.ctypes.data)
    if code and code>-200:raise ValueError('Y edge observer rejected '+str(code))
    return (self.decode() if code==0 else None),dict(edge_error=(code+200 if code else None),resize_gray_s=float(self.times[0]),blur_s=float(self.times[1]),
        edge_gate_motion_s=float(self.times[2]),native_transaction_s=float(self.times[3]),transaction_backend='cpp_Y_gaussian_edges_confidence_motion',input_format='YUYV')
ObservationWorkspace.observe=_y_observe

def copy_yuyv_native(source,destination):
    if _LIB is None:return False
    from v31_pixels import require_yuyv
    require_yuyv(source);require_yuyv(destination)
    if source.shape!=destination.shape or not destination.flags.writeable or np.shares_memory(source,destination):raise ValueError('YUYV copy destination/alias')
    code=_LIB.p11_copy_yuyv(source.ctypes.data,destination.ctypes.data,source.shape[1],source.shape[0],source.strides[0],destination.strides[0])
    if code:raise ValueError('YUYV copy rejected '+str(code))
    return True

def copy_entry(bpp=3):
    return (_LIB.p11_copy_yuyv if bpp==2 else _bgr_copy_entry()) if _LIB is not None else None

def yuyv_model_bgr(image,mode):
    if _LIB is None:return None
    from v31_pixels import require_yuyv
    require_yuyv(image);h,w=image.shape[:2];out=np.empty((h,w,3),np.uint8)
    code=_LIB.p11_yuyv_bgr(image.ctypes.data,w,h,image.strides[0],int(mode),out.ctypes.data)
    if code:raise ValueError('Model CSC rejected '+str(code))
    return out

def yuyv_preview_into(image,mode,out,fast=False):
    if _LIB is None:return False
    from v31_pixels import require_yuyv
    require_yuyv(image)
    if (out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=3 or not out.flags.c_contiguous
            or min(out.shape[:2])<1 or max(out.shape[:2])>640):raise ValueError('Preview workspace layout invalid')
    h,w=image.shape[:2];ho,wo=out.shape[:2]
    entry=_LIB.p11_yuyv_preview_nearest if fast else _LIB.p11_yuyv_preview
    code=entry(image.ctypes.data,w,h,image.strides[0],int(mode),out.ctypes.data,wo,ho)
    if code:raise ValueError('Preview resize/CSC rejected '+str(code))
    return True


def bgr_preview_into(image,out,xmap,ymap):
    """Nearest preview only. All buffers belong to the ordinary-RAM UI worker."""
    if _LIB is None:return False
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3
            or image.strides[2]!=1 or image.strides[1]!=3
            or out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=3 or not out.flags.c_contiguous):
        raise ValueError('BGR preview workspace layout invalid')
    h,w=image.shape[:2];ho,wo=out.shape[:2]
    if any(a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (xmap,ymap)):
        raise ValueError('BGR preview index map invalid')
    if xmap.size!=wo or ymap.size!=ho:raise ValueError('BGR preview index map size mismatch')
    code=_LIB.p11_bgr_preview_nearest(image.ctypes.data,w,h,image.strides[0],
        out.ctypes.data,wo,ho,xmap.ctypes.data,ymap.ctypes.data)
    if code:raise ValueError('BGR preview resize rejected '+str(code))
    return True


def preview_pair_copy(raw,raw_out,bgr,bgr_out,times):
    """One GIL-released row-copy call. Caller pins camera/output until it returns."""
    if _LIB is None:return False
    from v31_pixels import require_yuyv
    require_yuyv(raw)
    if (raw_out.dtype!=np.uint8 or raw.shape!=raw_out.shape or not raw_out.flags.c_contiguous
        or bgr.dtype!=np.uint8 or bgr.ndim!=3 or bgr.shape[2]!=3 or bgr.strides[1:]!=(3,1)
        or bgr_out.dtype!=np.uint8 or bgr.shape!=bgr_out.shape or not bgr_out.flags.c_contiguous
        or times.dtype!=np.float64 or times.shape!=(2,) or not times.flags.c_contiguous):
        raise ValueError('Paired preview copy workspace mismatch')
    rh,rw=raw.shape[:2];bh,bw=bgr.shape[:2]
    code=_LIB.p11_preview_pair_copy(raw.ctypes.data,raw_out.ctypes.data,rw,rh,raw.strides[0],raw_out.strides[0],
        bgr.ctypes.data,bgr_out.ctypes.data,bw,bh,bgr.strides[0],bgr_out.strides[0],times.ctypes.data)
    if code:raise ValueError('Paired preview copy rejected '+str(code))
    return True

class CompactPreview:
    """Pinned packet/workspace arguments; used only by the single UI worker."""
    def __init__(self,raw,output,work):
        self.available=_LIB is not None and work.compact
        self.times=np.zeros(3,np.float64);self.refs=(raw,output,work)
        if not self.available:return
        from v31_pixels import require_yuyv
        require_yuyv(raw)
        arrays=(output,work.left,work.canvas)
        if work.right is not None:arrays=arrays+(work.right,)
        if any(a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=3 or not a.flags.c_contiguous for a in arrays):
            raise ValueError('Compact preview workspace must be contiguous BGR')
        hi,wi=raw.shape[:2];bh,bw=output.shape[:2];height,lw=work.left.shape[:2]
        rw=work.canvas.shape[1]-lw
        if work.canvas.shape!=(height,lw+rw,3):raise ValueError('Compact preview canvas shape mismatch')
        if work.right is None:
            if output.shape!=(height,rw,3):raise ValueError('Compact preview native right shape mismatch')
            xs=ys=right=0
        else:
            if work.right.shape!=(height,rw,3):raise ValueError('Compact preview right shape mismatch')
            if any(a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (work.xmap,work.ymap)):
                raise ValueError('Compact preview index map layout mismatch')
            if work.xmap.size!=rw or work.ymap.size!=height:raise ValueError('Compact preview map sizes mismatch')
            xs,ys,right=work.xmap.ctypes.data,work.ymap.ctypes.data,work.right.ctypes.data
        self.entry=_LIB.p11_compact_preview
        self.args=(raw.ctypes.data,wi,hi,raw.strides[0],0,output.ctypes.data,bw,bh,output.strides[0],
            work.left.ctypes.data,lw,right,rw,height,xs,ys,work.canvas.ctypes.data,self.times.ctypes.data)
    def run(self,mode):
        if not self.available:return False
        args=self.args
        code=self.entry(*args[:4],int(mode),*args[5:])
        if code:raise ValueError('Compact preview transaction rejected '+str(code))
        return True


_REFINE64=threading.local()
def refine_original_y64(gray,quad,half_window,packed_mode=None):
    """P1 64x65 original-Y profiles + robust TLS in one native transaction."""
    if _LIB is None or not _LIB.p11_lk_available():return None
    from v8_geometry import order_corners
    import cv2
    start=time.perf_counter();cpu=time.thread_time()
    if packed_mode is None:
        if not isinstance(gray,np.ndarray) or gray.dtype!=np.uint8 or gray.ndim!=2:
            raise ValueError('native64 requires original uint8 Y plane')
        g=np.ascontiguousarray(gray)
    else:
        from v31_pixels import require_yuyv
        g=require_yuyv(gray)
        if packed_mode not in (0,1,2,3):raise ValueError('native64 YUYV color range invalid')
    q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('native64 requires ordered convex current corners')
    if not np.isfinite(half_window) or not 3<=half_window<=48:raise ValueError('native64 half_window must be3..48')
    if not hasattr(_REFINE64,'buffers'):
        _REFINE64.buffers=(np.empty((4,2),np.float64),np.empty(27,np.float64))
    out,stats=_REFINE64.buffers
    args=(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0])
    tail=(q.ctypes.data,float(half_window),out.ctypes.data,stats.ctypes.data)
    code=(_LIB.p11_refine64(*args,*tail) if packed_mode is None else
          _LIB.p11_yuyv_refine64(*args,int(packed_mode),*tail))
    if code==-9:return None
    if code:raise ValueError('native original-Y64 rejected input: '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(stats).all():
        raise ValueError('native original-Y64 returned invalid geometry')
    count=int(stats[24]);edges=[]
    for i in range(4):
        n=int(stats[i*6]);info=dict(edge=i,profiles=64,supported=n,accepted=bool(stats[i*6+4]),profile_contrast=float(stats[i*6+5]))
        if n>=20:info.update(tls_rms=float(stats[i*6+1]),retained=int(stats[i*6+2]),coverage=float(stats[i*6+3]))
        edges.append(info)
    try:
        candidate=out.astype(np.float32)
        if not cv2.isContourConvex(candidate):raise ValueError('native64 refined convexity invalid')
        area_ratio=abs(cv2.contourArea(candidate))/abs(cv2.contourArea(q.astype(np.float32)))
        if not .85<=area_ratio<=1.15 or np.max(np.linalg.norm(candidate-q,axis=1))>3*half_window:
            raise ValueError('native64 refined area/order/displacement invalid')
    except (ValueError,cv2.error):
        candidate=q.astype(np.float32);count=0
    return candidate,dict(method='p1_pyramid_subpixel_profiles_tls',backend='cpp_packed_Y_64x65_Q5' if packed_mode is not None else 'cpp_original_Y_64x65',
        state='refined' if count else 'coarse_retained',refined_corners=count,edges=edges,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(candidate-q,axis=1).tolist(),
        refinement_s=time.perf_counter()-start,refinement_thread_cpu_s=time.thread_time()-cpu,
        native_wall_s=float(stats[25]),native_thread_cpu_s=float(stats[26]),
        workspace_reused=True,interpolation='opencv_uint8_linear_replicate',
        tls_solver='analytic_2x2_principal_axis',original_profile_gates_preserved=True)


def refine_original_yuyv64(image,quad,half_window):
    from v31_pixels import color_mode
    return refine_original_y64(image,quad,half_window,packed_mode=color_mode())

_COHERENT=__import__('threading').local()

def coherent_profiles(bands,half_window,fraction_limits,minimum_contrast,boundary_prior=None,line_lock_radius=None):
    """One ctypes transaction for all four current Y/color exterior bands; no device access."""
    if _LIB is None:return None
    data=np.ascontiguousarray(bands,np.float32)
    if data.ndim!=4 or data.shape[0]!=4 or data.shape[1] not in (24,64) or data.shape[2]!=65 or data.shape[3] not in (1,3):
        raise ValueError('Coherent exterior band layout invalid')
    shape=(4,data.shape[1],3)
    if not hasattr(_COHERENT,'out') or _COHERENT.out.shape!=shape:
        _COHERENT.out=np.empty(shape,np.float32);_COHERENT.times=np.empty(2,np.float64)
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Current consensus side prior invalid')
    if line_lock_radius is not None:
        if not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window:raise ValueError('Current consensus peak lock invalid')
        code=_LIB.p11_locked_coherent_profiles(data.ctypes.data,data.shape[1],data.shape[3],float(half_window),
            float(fraction_limits[0]),float(fraction_limits[1]),float(minimum_contrast),float(line_lock_radius),
            0 if prior is None else prior.ctypes.data,_COHERENT.out.ctypes.data,_COHERENT.times.ctypes.data)
    else:
        code=_LIB.p11_coherent_profiles(data.ctypes.data,data.shape[1],data.shape[3],float(half_window),
            float(fraction_limits[0]),float(fraction_limits[1]),float(minimum_contrast),_COHERENT.out.ctypes.data,_COHERENT.times.ctypes.data)
    if code:raise ValueError('Native exterior consensus rejected bands: '+str(code))
    return _COHERENT.out,dict(backend='cpp_four_edge_three_peak_consensus',
        native_wall_s=float(_COHERENT.times[0]),native_thread_cpu_s=float(_COHERENT.times[1]),workspace_reused=True)

def preview_canvas_into(raw,output,work,mode,times,interpolation='nearest'):
    """Borrow source arrays ONLY for this call; destination is owned UI RAM.

    V48 UI worker calls this with owned ordinary-RAM snapshots. Direct borrowed
    use also remains valid only within the call; no source pointer is retained.
    """
    if _LIB is None:return False
    from v31_pixels import require_yuyv
    require_yuyv(raw)
    if (not work.compact or work.right is None or output.dtype!=np.uint8 or output.ndim!=3
        or output.shape[2]!=3 or output.strides[1:]!=(3,1)):
        raise ValueError('Preview borrowed source layout')
    if any(a.dtype!=np.uint8 or not a.flags.c_contiguous or not a.flags.writeable
           for a in (work.left,work.right,work.canvas)):
        raise ValueError('Preview packet workspace')
    if times.shape!=(3,) or times.dtype!=np.float64 or not times.flags.c_contiguous:raise ValueError('Preview timing workspace')
    hi,wi=raw.shape[:2];bh,bw=output.shape[:2];height,lw=work.left.shape[:2];rw=work.right.shape[1]
    if output.strides[0]<3*bw or not 2<=min(hi,wi,bh,bw,height,lw,rw) or max(hi,wi,bh,bw)>1280 or not 0<=int(mode)<=3:
        raise ValueError('Preview dimensions/row stride/mode invalid')
    if not times.flags.writeable:raise ValueError('Preview timing destination is read-only')
    if work.canvas.shape!=(height,lw+rw,3) or work.right.shape[0]!=height:raise ValueError('Preview canvas shape')
    if interpolation=='linear':
        axes=getattr(work,'linear_maps',None)
        if axes is None or len(axes)!=5:raise ValueError('Missing cached linear preview maps')
        sizes=(lw,height,lw,rw,height)
        for axis,size in zip(axes,sizes):
            if (axis.dtype!=np.int32 or axis.shape!=(size,3) or not axis.flags.c_contiguous
                or axis.flags.writeable):raise ValueError('Linear preview map layout')
        if work.linear_layout!=(hi,wi,bh,bw,height,lw,rw):raise ValueError('Linear preview source layout changed')
        code=_LIB.p11_preview_canvas_linear(raw.ctypes.data,wi,hi,raw.strides[0],int(mode),
            output.ctypes.data,bw,bh,output.strides[0],work.canvas.ctypes.data,lw,rw,height,
            *(axis.ctypes.data for axis in axes),times.ctypes.data)
        if code:raise ValueError('Bilinear preview canvas transaction rejected '+str(code))
        return True
    if interpolation!='nearest':raise ValueError('Unknown preview interpolation')
    if any(a is None or a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (work.xmap,work.ymap)):
        raise ValueError('Preview map workspace layout')
    if work.xmap.size!=rw or work.ymap.size!=height or np.any(work.xmap<0) or np.any(work.xmap>=bw) or np.any(work.ymap<0) or np.any(work.ymap>=bh):
        raise ValueError('Preview map bounds')
    if not times.flags.writeable:raise ValueError('Preview timing destination is read-only')
    if work.canvas.shape!=(height,lw+rw,3) or work.right.shape[0]!=height:raise ValueError('Preview canvas shape')
    layout=(hi,wi,height,lw)
    if getattr(work,'left_layout',None)!=layout:
        work.left_xmap=(np.arange(lw,dtype=np.int32)*wi//lw)
        work.left_ymap=(np.arange(height,dtype=np.int32)*hi//height)
        work.left_xmap.flags.writeable=False;work.left_ymap.flags.writeable=False;work.left_layout=layout
    code=_LIB.p11_preview_canvas_maps(raw.ctypes.data,wi,hi,raw.strides[0],int(mode),
        output.ctypes.data,bw,bh,output.strides[0],work.canvas.ctypes.data,lw,rw,height,
        work.left_xmap.ctypes.data,work.left_ymap.ctypes.data,work.xmap.ctypes.data,work.ymap.ctypes.data,
        times.ctypes.data)
    if code:raise ValueError('Preview canvas transaction rejected '+str(code))
    return True

def packed_vector_profiles(image,x,y):
    """Borrow packed source only until return; sample bounded Y/U/V bands."""
    if _LIB is None:return None
    from v31_pixels import require_yuyv
    require_yuyv(image)
    if max(image.shape[:2])>1280:return None
    mx=np.ascontiguousarray(x,np.float32);my=np.ascontiguousarray(y,np.float32)
    if mx.shape!=my.shape or not 1<=mx.size<=4*64*65:
        raise ValueError('Packed exterior profile coordinate layout invalid')
    output=np.empty((*mx.shape,3),np.float32);h,w=image.shape[:2]
    code=_LIB.p11_yuyv_profiles(image.ctypes.data,w,h,image.strides[0],mx.ctypes.data,
        my.ctypes.data,mx.size,output.ctypes.data)
    if code:raise ValueError('Packed exterior sampler rejected '+str(code))
    return output


_EXTERIOR=threading.local()
def fused_yuyv_exterior(image,quad,half_window,profiles=64,min_support=.60,max_rms=1.5,
                        minimum_contrast=12.,fraction_limits=(.10,.90),deadline=None,boundary_prior=None,line_lock_radius=None):
    """Current borrowed YUYV bands, consensus, robust TLS and corners in one call.

    CPU-only thread-local scratch. Output arrays are copied, no source pointer
    escapes the transaction. Expired work returns rejected evidence, not fallback.
    """
    if _LIB is None or image.ndim!=3 or image.shape[2]!=2 or max(image.shape[:2])>1280:return None
    from v31_pixels import require_yuyv
    from v49_boundary import array_key
    import cv2
    raw=require_yuyv(image);q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('Fused current exterior requires cyclic convex corners')
    if not hasattr(_EXTERIOR,'buffers'):
        _EXTERIOR.buffers=(np.empty((4,2),np.float64),np.empty(80,np.float64))
    out,s=_EXTERIOR.buffers;begin=time.perf_counter();cpu=time.thread_time()
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Boundary side prior invalid')
    if line_lock_radius is not None and (not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window):raise ValueError('Fused current physical lock invalid')
    function=_LIB.p11_yuyv_exterior if line_lock_radius is None else _LIB.p11_locked_yuyv_exterior
    args=() if line_lock_radius is None else (float(line_lock_radius),)
    code=function(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],q.ctypes.data,
        float(half_window),int(profiles),float(fraction_limits[0]),float(fraction_limits[1]),
        float(minimum_contrast),float(min_support),float(max_rms),0. if deadline is None else float(deadline),
        0 if prior is None else prior.ctypes.data,out.ctypes.data,s.ctypes.data,*args)
    if code not in (0,1):raise ValueError('Fused current YUV exterior rejected input: '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(s).all():raise ValueError('Invalid native exterior result')
    return _decode_yuyv_exterior(raw,q,out,s,half_window,profiles,fraction_limits,boundary_prior,line_lock_radius,
        time.perf_counter()-begin,time.thread_time()-cpu)


def _decode_yuyv_exterior(raw,q,out,s,half_window,profiles,fraction_limits,boundary_prior,line_lock_radius,wall_s,cpu_s):
    from v49_boundary import array_key
    edges=[];support=[];rms=[];colors=[]
    for i in range(4):
        z=s[i*13:(i+1)*13];accepted=bool(z[4])
        edges.append(dict(edge=i,profiles=profiles,supported=int(z[0]),retained=int(z[1]),
            coverage=float(z[2]),tls_rms=float(z[3]),accepted=accepted,polarity=0,Y_polarity=int(z[12]),
            contrast_backend='unclipped_YUV_vector_gradient'))
        support.append(float(z[1])/profiles if accepted else 0.);rms.append(float(z[3]))
        colors.append(z[6:12].tolist())
    evidence=dict(method='coherent_multicolor_gradient_TLS',state='refined' if s[53] else 'rejected',
        valid=bool(s[53]),refined_corners=int(s[52]),supported_edges=sum(e['accepted'] for e in edges),
        edges=edges,edge_support=support,edge_rms=rms,edge_polarity=[0]*4,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(out-q,axis=1).tolist(),
        refinement_s=float(wall_s),refinement_thread_cpu_s=float(cpu_s),
        backend='cpp_fused_current_YUV_exterior',profiles_per_edge=int(profiles),fraction_limits=list(fraction_limits),
        vector_sample_backend='cpp_direct_YUV_bands_no_full_plane_pack',consensus_backend='cpp_four_edge_three_peak_consensus',
        native_wall_s=float(s[54]),native_thread_cpu_s=float(s[55]),sampling_s=float(s[56]),sampling_thread_cpu_s=float(s[57]),
        consensus_native_wall_s=float(s[58]),consensus_native_thread_cpu_s=float(s[59]),fit_s=float(s[60]),fit_thread_cpu_s=float(s[61]),
        deadline_hit=bool(s[62]),workspace_reused=True,same_frame_color_bands_only=True,
        color_vector_proof=True,brightness_polarity_required=False,same_frame_source=True,
        current_source_key=array_key(raw),source_proof_kind='raw_YUV_profiles',border_colors=colors,
        gradient_consensus_required=True,area_ratio=float(s[63]),corner_order_preserved=True,
        boundary_prior_used=boundary_prior is not None,border_color_sampling='fitted_line_sides_3px',
        physical_peak_lock=line_lock_radius is not None,peak_lock_radius_source=line_lock_radius,
        signed_peak_lock=bool(line_lock_radius is not None and boundary_prior is not None))
    return out.astype(np.float32),evidence



def fused_locked_pair(image,quad,half_window,primary_lock,scale_min,deadline=None,boundary_prior=None,cpu_budget_s=.12):
    """Two independent current-color sample layouts; all geometric gates remain outside."""
    if _LIB is None or image.ndim!=3 or image.shape[2]!=2:return None
    from v31_pixels import require_yuyv
    raw=require_yuyv(image);q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Native pair quad layout invalid')
    if not hasattr(_EXTERIOR,'pair'):
        _EXTERIOR.pair=(np.empty((2,4,2),np.float64),np.empty((2,80),np.float64),np.empty(4,np.float64))
    out,stats,timing=_EXTERIOR.pair
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Native pair prior invalid')
    began=time.perf_counter();cpu=time.thread_time()
    code=_LIB.p11_v67_locked_pair(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],q.ctypes.data,
        float(half_window),8.,.60,float(scale_min),0. if deadline is None else float(deadline),
        0 if prior is None else prior.ctypes.data,float(primary_lock),float(scale_min),float(cpu_budget_s),
        out[0].ctypes.data,stats[0].ctypes.data,out[1].ctypes.data,stats[1].ctypes.data,timing.ctypes.data)
    if code not in (0,1,2,3):raise ValueError('Native pair input rejected '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(stats).all():raise ValueError('Native pair output invalid')
    first=_decode_yuyv_exterior(raw,q,out[0],stats[0],half_window,64,(.10,.90),boundary_prior,primary_lock,stats[0,54],stats[0,55])
    secondary_lock=min(.70*half_window,float(np.clip(1.25+.75*max(stats[0,i*13+3] for i in range(4)),1.25,2.)))
    # The core derives the secondary signed prior from the current primary.
    second=_decode_yuyv_exterior(raw,q,out[1],stats[1],half_window,24,(.12,.88),True if stats[0,53] else None,secondary_lock,stats[1,54],stats[1,55])
    detail=dict(backend='cpp_current_locked64_independent24',code=int(code),complete=code==0,
        pair_wall_s=time.perf_counter()-began,pair_thread_cpu_s=time.thread_time()-cpu,
        native_pair_wall_s=float(timing[0]),native_pair_thread_cpu_s=float(timing[1]),
        independent_grids=[[64,.10,.90],[24,.12,.88]],same_locked_line=True,geometric_proof_granted=False)
    return first,second,detail
