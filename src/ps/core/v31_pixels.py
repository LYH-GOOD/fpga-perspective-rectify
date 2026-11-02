"""Explicit packed YUYV contract; no implicit BGR or MJPEG admission."""
from pathlib import Path
import hashlib
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_MODE=0
_LUT=np.array([(min(219,max(0,x-16))*255+109)//219 for x in range(256)],np.uint8)
def set_color_mode(mode):
    global _MODE
    if isinstance(mode,bool) or mode not in (0,1,2,3):raise ValueError('YUYV CSC mode must be 0..3')
    _MODE=int(mode)
def color_mode():return _MODE
def require_yuyv(image):
    if (not isinstance(image,np.ndarray) or image.dtype!=np.uint8 or image.ndim!=3
        or image.shape[2]!=2 or image.shape[1]%2 or image.strides[1:]!=(2,1)
        or image.strides[0]<image.shape[1]*2):raise ValueError('Expected even-width uint8 HxWx2 packed YUYV')
    return image
def luminance(image):
    require_yuyv(image); y=image[:,:,0]
    return y if _MODE&1 else _LUT[y]
def gray_half(image,out):
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or out.shape!=(h//2,w//2):raise ValueError('Y area2 layout')
    y=image[:,:,0].astype(np.uint16)
    value=((y[0::2,0::2]+y[0::2,1::2]+y[1::2,0::2]+y[1::2,1::2]+2)>>2).astype(np.uint8)
    out[:]=value if _MODE&1 else _LUT[value]
    return out
def model_bgr(image):
    """Only startup/reacquisition/model refresh. Ordinary tracking uses Y."""
    if image.shape[2]==3:return image
    require_yuyv(image)
    from v31_native import yuyv_model_bgr
    native=yuyv_model_bgr(image,_MODE)
    if native is not None:return native
    h,w=image.shape[:2];pairs=image.reshape(h,w//2,4) if image.flags.c_contiguous else np.ascontiguousarray(image).reshape(h,w//2,4)
    y=image[:,:,0].astype(np.int32)
    u=np.repeat(pairs[:,:,1].astype(np.int32)-128,2,axis=1)
    v=np.repeat(pairs[:,:,3].astype(np.int32)-128,2,axis=1)
    coeff=((298,409,100,208,516),(256,359,88,183,454),(298,459,55,136,541),(256,403,48,120,475))[_MODE]
    c=y if _MODE&1 else np.maximum(y-16,0);cy,rv,gu,gv,bu=coeff
    rgb=(cy*c+bu*u,cy*c-gu*u-gv*v,cy*c+rv*v)
    return np.stack([np.clip((a+128)>>8,0,255).astype(np.uint8) for a in rgb],axis=2)
def copy_input(source,destination):
    require_yuyv(source);require_yuyv(destination)
    if source.shape!=destination.shape:raise ValueError('YUYV copy shape mismatch')
    from v31_native import copy_yuyv_native
    if copy_yuyv_native(source,destination):return 'cpp_yuyv_memcpy'
    np.copyto(destination,source);return 'numpy_yuyv_copy'
