"""Cold CV preparation outside acquisition; bounded reusable color work images."""
from pathlib import Path
import hashlib,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_READY=threading.Event();_LOCK=threading.Lock();_LOCAL=threading.local();_DETAIL={}


def prepare_color_runtime(cancel=None):
    """One small Lab call initializes CV tables before any recovery budget starts."""
    from v79_setup import check_cancel
    if _READY.is_set():return dict(_DETAIL,already_ready=True)
    with _LOCK:
        if _READY.is_set():return dict(_DETAIL,already_ready=True)
        check_cancel(cancel);began=time.perf_counter();cpu=time.thread_time()
        checkpoint('CV_COLOR_WARMUP_BEGIN',hardware_access=False,scope='CPU setup; outside frame measurement')
        # Exercise the actual uchar conversion with a small varied image.
        image=np.arange(8*8*3,dtype=np.uint8).reshape(8,8,3)
        blurred=cv2.GaussianBlur(image,(3,3),0)
        cv2.cvtColor(blurred,cv2.COLOR_BGR2LAB)
        check_cancel(cancel)
        _DETAIL.update(wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu,
            work_shape=[8,8,3],backend='opencv_uint8_Lab_initialized',hardware_access=False)
        _READY.set();checkpoint('CV_COLOR_WARMUP_END',**_DETAIL)
        return dict(_DETAIL,already_ready=False)


def color_runtime_ready():return _READY.is_set()


def small_lab(color,check,max_dim=192):
    """No lazy Lab initialization in a timed recovery. Source proof remains full resolution."""
    if not _READY.is_set():
        # Public direct detection without NativeSetup can use earlier Y/YUV
        # paths; never start an uninitialized heavyweight call in its budget.
        raise ValueError('Color runtime not prepared; defer Lab proposal stage')
    if color.dtype!=np.uint8 or color.ndim!=3 or color.shape[2]!=3:raise ValueError('Expected BGR color proposal image')
    check('multicolor_work_resize_begin')
    h,w=color.shape[:2];scale=min(1.,float(max_dim)/max(h,w))
    shape=(max(2,round(h*scale)),max(2,round(w*scale)),3)
    if getattr(_LOCAL,'shape',None)!=shape:
        _LOCAL.shape=shape;_LOCAL.work=np.empty(shape,np.uint8)
        _LOCAL.smooth=np.empty(shape,np.uint8);_LOCAL.lab=np.empty(shape,np.uint8)
    if shape[:2]!=color.shape[:2]:
        cv2.resize(color,(shape[1],shape[0]),dst=_LOCAL.work,interpolation=cv2.INTER_LINEAR)
        source=_LOCAL.work
    else:source=color
    check('multicolor_work_resize_end')
    check('multicolor_gaussian_begin');cv2.GaussianBlur(source,(3,3),0,dst=_LOCAL.smooth)
    check('multicolor_gaussian_end')
    check('multicolor_Lab_begin');cv2.cvtColor(_LOCAL.smooth,cv2.COLOR_BGR2LAB,dst=_LOCAL.lab)
    check('multicolor_Lab_end')
    return _LOCAL.lab
