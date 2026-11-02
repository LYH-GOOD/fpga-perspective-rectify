"""Small-image geometry estimation; original-resolution PL tile plans.

No camera metadata is assumed. Automatic metric aspect is conditional on a
centered square-pixel pinhole camera and a flat rectangular target.
"""
from pathlib import Path
import hashlib,time
import cv2
import numpy as np
from p11_contract import RELEASE_ID,cache_profile
from find_homography import homography_to_regs,compute_H_out2in
from pl_fields import identity_field,validate_field,interpolate,coordinates
from v8_tables import mapping_ranges,schedule_from_ranges,_range_grid
from v8_plan import _seal_checked,require_yuyv_shape
from v8_surface import line_surface as _line_field,evaluate as _bend_eval,NY,NX
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_IMAGE_CACHE={}

def read_image(path,source_max_dim=4096,source_max_pixels=8_000_000):
    """Inspect header first, select bounded JPEG IDCT decoding, then orient once.
    Original coordinates refer to the EXIF-oriented original, as in the old imread.
    """
    from PIL import Image as PILImage
    if source_max_dim is not None and (isinstance(source_max_dim,bool) or not isinstance(source_max_dim,int) or source_max_dim<32):
        raise ValueError('source_max_dim为None或>=32的整数')
    if isinstance(source_max_pixels,bool) or not isinstance(source_max_pixels,int) or not 100_000<=source_max_pixels<=24_000_000:
        raise ValueError('source_max_pixels须为10万..2400万；默认800万')
    p=Path(path).expanduser().resolve();st=p.stat()
    key=(str(p),st.st_size,st.st_mtime_ns,source_max_dim,source_max_pixels)
    if key in _IMAGE_CACHE:
        image,info=_IMAGE_CACHE[key]
        return image,True,dict(info)
    with PILImage.open(str(p)) as header:
        rw,rh=header.size;fmt=header.format
        try:orientation=int(header.getexif().get(274,1))
        except (ValueError,TypeError,AttributeError):orientation=1
    if min(rw,rh)<2:raise ValueError('图像宽高至少为2')
    if orientation not in range(1,9):orientation=1
    ow,oh=(rh,rw) if orientation in (5,6,7,8) else (rw,rh)
    divisor=1
    if fmt=='JPEG':
        for d in (1,2,4,8):
            divisor=d;dw,dh=(rw+d-1)//d,(rh+d-1)//d
            if dw*dh<=source_max_pixels and (source_max_dim is None or max(dw,dh)<=source_max_dim):break
        if ((rw+divisor-1)//divisor)*((rh+divisor-1)//divisor)>source_max_pixels:
            raise ValueError('JPEG缩小解码至1/8后仍超内存预算，请在电脑缩小后上传；尚未解码像素')
    elif rw*rh>source_max_pixels:
        raise ValueError('大尺寸非JPEG不能保证低内存解码，请在电脑转为JPEG或缩小后上传；尚未解码像素')
    flags={1:cv2.IMREAD_COLOR,2:cv2.IMREAD_REDUCED_COLOR_2,4:cv2.IMREAD_REDUCED_COLOR_4,8:cv2.IMREAD_REDUCED_COLOR_8}
    _IMAGE_CACHE.clear()  # Release the previous working image BEFORE allocating another.
    image=cv2.imread(str(p),flags[divisor]|cv2.IMREAD_IGNORE_ORIENTATION)
    if image is None or min(image.shape[:2])<2:raise ValueError('无法读取有效彩色图片')
    if image.shape[0]*image.shape[1]>source_max_pixels:
        raise ValueError('解码器返回尺寸超过预算，停止处理')
    if orientation==2:image=cv2.flip(image,1)
    elif orientation==3:image=cv2.rotate(image,cv2.ROTATE_180)
    elif orientation==4:image=cv2.flip(image,0)
    elif orientation==5:image=cv2.transpose(image)
    elif orientation==6:image=cv2.rotate(image,cv2.ROTATE_90_CLOCKWISE)
    elif orientation==7:image=cv2.flip(cv2.transpose(image),-1)
    elif orientation==8:image=cv2.rotate(image,cv2.ROTATE_90_COUNTERCLOCKWISE)
    h,w=image.shape[:2]
    if source_max_dim is not None and max(h,w)>source_max_dim:
        scale=source_max_dim/max(h,w)
        image=cv2.resize(image,(max(2,round(w*scale)),max(2,round(h*scale))),interpolation=cv2.INTER_AREA)
    h,w=image.shape[:2]
    info=dict(original_shape=[oh,ow,3],encoded_shape=[rh,rw,3],working_shape=[h,w,3],
              jpeg_decode_divisor=divisor,exif_orientation=orientation,
              original_to_working_scale=[w/ow,h/oh],source_max_dim=source_max_dim,
              source_max_pixels=source_max_pixels,reduced=(w!=ow or h!=oh))
    _IMAGE_CACHE[key]=(image,info)
    return image,False,dict(info)


def resize_view(image,limit=640):
    h,w=image.shape[:2];s=min(1.,limit/max(h,w))
    # Coarse proposals only; original-resolution edge refinement follows.
    return cv2.resize(image,(max(2,round(w*s)),max(2,round(h*s))),interpolation=cv2.INTER_LINEAR) if s<1 else image

def order_corners(points):
    q=np.asarray(points,np.float32).reshape(4,2)
    center=q.mean(axis=0)
    q=q[np.argsort(np.arctan2(q[:,1]-center[1],q[:,0]-center[0]))]
    q=np.roll(q,-int(np.argmin(q.sum(axis=1))),axis=0)
    if np.cross(q[1]-q[0],q[2]-q[1])<0:q=q[[0,3,2,1]]
    if not cv2.isContourConvex(q) or abs(cv2.contourArea(q))<16:raise ValueError('四角退化或非凸')
    return q

def detect_quad(image,limit=640):
    view=resize_view(image,limit);h,w=view.shape[:2]
    gray=view if view.ndim==2 else cv2.cvtColor(view,cv2.COLOR_BGR2GRAY)
    blur=cv2.GaussianBlur(gray,(5,5),0);candidates=[]
    # Both thresholds on the SMALL image: the outer paper can be weaker than its black frame.
    for low,high in ((50,150),(15,50)):
        edge=cv2.dilate(cv2.Canny(blur,low,high),np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours,key=cv2.contourArea,reverse=True)[:16]:
            area=cv2.contourArea(c)
            if area<.05*w*h:continue
            p=cv2.approxPolyDP(c,.018*cv2.arcLength(c,True),True)
            if len(p)!=4 or not cv2.isContourConvex(p):continue
            q=order_corners(p)
            if np.any(q[:,0]<2) or np.any(q[:,1]<2) or np.any(q[:,0]>w-3) or np.any(q[:,1]>h-3):continue
            candidates.append((area,q))
    if not candidates:raise ValueError('缩略图未找到外框；可提高detection_max_dim或给manual_points（原图坐标）')
    area,q=max(candidates,key=lambda item:item[0])
    H,W=image.shape[:2]
    q=(q+.5)*[W/w,H/h]-.5
    return q.astype(np.float32),dict(view_shape=[h,w],candidates=len(candidates),area_ratio=area/(w*h))

def project(H,x,y):
    d=H[2,0]*x+H[2,1]*y+H[2,2]
    if np.any(d<=1e-7):raise ValueError('映射分母非正或接近零')
    return (H[0,0]*x+H[0,1]*y+H[0,2])/d,(H[1,0]*x+H[1,1]*y+H[1,2])/d

def _aspect_once(q,image_shape):
    h,w=image_shape[:2]
    G=cv2.getPerspectiveTransform(np.array([[0,0],[1,0],[1,1],[0,1]],np.float32),q.astype(np.float32)).astype(float)
    A=np.array([[1,0,-(w-1)/2],[0,1,-(h-1)/2],[0,0,1.]])@G
    denom=A[2,0]*A[2,1]
    if abs(denom)<1e-9:raise ValueError('焦距估计退化')
    f2=-np.dot(A[:2,0],A[:2,1])/denom
    if not np.isfinite(f2) or f2<=0:raise ValueError('无有效实数焦距')
    f=np.sqrt(f2)
    if not .2*max(w,h)<f<8*max(w,h):raise ValueError('估计焦距不可信')
    a=A[:,0]*[1/f,1/f,1];b=A[:,1]*[1/f,1/f,1]
    r=np.linalg.norm(a)/np.linalg.norm(b)
    if not .1<r<10:raise ValueError('估计比例不可信')
    return float(r),float(f)

def aspect_ratio(q,image_shape,known_ratio=None):
    if known_ratio is not None:
        if not np.isfinite(known_ratio) or not .05<float(known_ratio)<20:raise ValueError('aspect_ratio须为0.05..20')
        return float(known_ratio),dict(method='user_ratio',confidence='user_supplied')
    tl,tr,br,bl=q
    fallback=(np.linalg.norm(tr-tl)+np.linalg.norm(br-bl))/(np.linalg.norm(bl-tl)+np.linalg.norm(br-tr))
    try:
        r,f=_aspect_once(q,image_shape);samples=[]
        # Deterministic sensitivity check, not a confidence interval or calibration.
        eps=max(image_shape[:2])/640.
        for i in range(4):
            for axis in range(2):
                for sign in (-1,1):
                    perturbed=q.copy();perturbed[i,axis]+=sign*eps
                    samples.append(_aspect_once(perturbed,image_shape)[0])
        spread=float(max(abs(np.asarray(samples)/r-1)))
        if spread>.10:raise ValueError('角点扰动导致比例不稳定')
        return r,dict(method='rectangle_self_calibration',confidence='conditional',focal_pixels=f,
                      aspect_sensitivity=spread,assumptions='原图中心主点、方形像素、平面矩形；弯曲纸面可能不满足')
    except (ValueError,cv2.error) as e:
        return float(fallback),dict(method='projected_edge_fallback',confidence='low',reason=str(e),
                                   warning='没有足够信息恢复真实比例；当前保留投影估计，不强制A4或正方格')

def build_model(image,quad,ratio=None,output_size=None,max_dim=None,dewarp='auto',preview_dim=640,preview_backend='opencv',surface_solver='qr',surface_tracking='batch',preserve_corner_order=False):
    started=time.perf_counter()
    if preview_backend not in ('opencv','numpy'):raise ValueError('geometry_preview_backend须为opencv/numpy')
    if surface_solver not in ('qr','svd'):raise ValueError('surface_solver须为qr/svd')
    if surface_tracking not in ('batch','legacy'):raise ValueError('surface_tracking须为batch/legacy')
    if dewarp not in ('auto','off','lines'):raise ValueError('dewarp为auto/lines/off')
    q=np.asarray(quad,np.float32).reshape(4,2).copy() if preserve_corner_order else order_corners(quad)
    if not np.isfinite(q).all() or not cv2.isContourConvex(q) or cv2.contourArea(q,oriented=True)<=16:raise ValueError('ordered output corners must be finite convex clockwise image coordinates')
    r,metric=aspect_ratio(q,image.shape,ratio)
    aspect_s=time.perf_counter()-started;t=time.perf_counter()
    tl,tr,br,bl=q
    ew=max(np.linalg.norm(tr-tl),np.linalg.norm(br-bl));eh=max(np.linalg.norm(bl-tl),np.linalg.norm(br-tr))
    if output_size is None:
        wo=max(ew,eh*r);ho=wo/r
        scale=1 if max_dim is None else min(1,float(max_dim)/max(wo,ho))
        wo,ho=max(16,round(wo*scale)),max(16,round(ho*scale))
    else:
        wo,ho=map(int,output_size)
        if tuple(output_size)!=(wo,ho):raise ValueError('output_size应为整数(宽,高)')
        metric=dict(method='explicit_output_size',confidence='user_supplied')
    if min(wo,ho)<16 or wo*ho>12_000_000 or max(wo,ho)>16384:raise ValueError('输出须>=16、<=1200万像素、单边<=16384；请设置max_dim')
    H=compute_H_out2in(q,wo,ho).astype(float)
    h_s=time.perf_counter()-t;t=time.perf_counter()
    scale=min(1,preview_dim/max(wo,ho));pw=max(16,round(wo*scale));ph=max(16,round(ho*scale))
    preview=None;preview_coordinates_s=preview_remap_s=0.
    if dewarp!='off':
        if preview_backend=='opencv':
            # Preview endpoints are EXACTLY the former linspace endpoints:
            # pixel (0,0)->(0,0), (pw-1,ph-1)->(wo-1,ho-1).
            # Only this small observation preview changes raster implementation.
            # H and the authoritative nonlinear model/PL numeric ABI are intact.
            denominator=H[2,0]*np.array([0.,wo-1,wo-1,0.])+H[2,1]*np.array([0.,0.,ho-1,ho-1])+H[2,2]
            if (not np.all(np.isfinite(H)) or not np.all(np.isfinite(denominator)) or
                    np.min(abs(denominator))<1e-6 or denominator.min()<=0<=denominator.max()):
                raise ValueError('几何预览H分母不安全')
            transform=H@np.diag([(wo-1)/(pw-1),(ho-1)/(ph-1),1.])
            preview_coordinates_s=time.perf_counter()-t;t=time.perf_counter()
            preview=cv2.warpPerspective(image,transform,(pw,ph),
                flags=cv2.INTER_LINEAR|cv2.WARP_INVERSE_MAP,borderMode=cv2.BORDER_REPLICATE)
            preview_remap_s=time.perf_counter()-t
        else:
            u,v=np.meshgrid(np.linspace(0,wo-1,pw),np.linspace(0,ho-1,ph));x,y=project(H,u,v)
            preview_coordinates_s=time.perf_counter()-t;t=time.perf_counter()
            preview=cv2.remap(image,x.astype(np.float32),y.astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
            preview_remap_s=time.perf_counter()-t
    perspective_preview_s=time.perf_counter()-started
    horizontal_s=vertical_s=gray_s=threshold_s=transpose_s=0.
    dx=np.zeros((ph,pw),np.float32);dy=dx.copy();details={'state':'off','strength':0.}
    cx=np.zeros((NY,NX));cy=np.zeros((NY,NX))
    if dewarp!='off':
        t=time.perf_counter();gray=cv2.cvtColor(preview,cv2.COLOR_BGR2GRAY)
        gray_s=time.perf_counter()-t;t=time.perf_counter()
        ink=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,9)
        threshold_s=time.perf_counter()-t
        t=time.perf_counter();dy,details['horizontal'],cy=_line_field(gray,ink=ink,solver=surface_solver,tracking_backend=surface_tracking)
        horizontal_s=time.perf_counter()-t
        t=time.perf_counter()
        vertical_gray=np.ascontiguousarray(gray.T);vertical_ink=np.ascontiguousarray(ink.T)
        transpose_s=time.perf_counter()-t;t=time.perf_counter()
        vertical,details['vertical'],cx=_line_field(vertical_gray,ink=vertical_ink,solver=surface_solver,tracking_backend=surface_tracking);dx=vertical.T
        vertical_s=time.perf_counter()-t
        # Validate no folds on the composed displacement grid; reduce strength if necessary.
        strength=1. if (np.any(cx) or np.any(cy)) else 0.
        dxx=np.gradient(dx,(pw-1)/64,axis=1);dxy=np.gradient(dx,(ph-1)/64,axis=0)
        dyx=np.gradient(dy,(pw-1)/64,axis=1);dyy=np.gradient(dy,(ph-1)/64,axis=0)
        for _ in range(5):
            if np.min((1+dxx*strength)*(1+dyy*strength)-dxy*dyx*strength**2)>.35:break
            strength*=.5
        else:strength=0.
        cx*=strength;cy*=strength;details['strength']=strength
        details['state']='active' if strength else 'inactive'
    # Analytic smooth field is authoritative; 33x33 maps are saved for inspection.
    # Evaluate beyond page bounds smoothly for the last partial hardware cell.
    cx*=(wo-1)/(pw-1);cy*=(ho-1)/(ph-1)
    uu,vv=np.meshgrid(np.linspace(0,1,33),np.linspace(0,1,33))
    mx=_bend_eval(cx,vv,uu);my=_bend_eval(cy,uu,vv)
    return dict(H=H,width=wo,height=ho,mesh_x=mx,mesh_y=my,bend_x=cx,bend_y=cy,
                quad=q,metric=metric,dewarp=details,preview=preview,
                geometry_timing=dict(perspective_preview_s=perspective_preview_s,
                    aspect_s=aspect_s,h_and_size_s=h_s,preview_coordinates_s=preview_coordinates_s,
                    preview_remap_s=preview_remap_s,preview_backend=preview_backend,
                    preview_skipped=dewarp=='off',preview_shape=[ph,pw],surface_solver=surface_solver,surface_tracking=surface_tracking,
                    gray_s=gray_s,threshold_s=threshold_s,
                    horizontal_s=horizontal_s,vertical_s=vertical_s,transpose_s=transpose_s,
                    guards_and_export_s=time.perf_counter()-started-perspective_preview_s-horizontal_s-vertical_s-gray_s-threshold_s-transpose_s))

def map_points(model,u,v):
    u,v=np.broadcast_arrays(np.asarray(u,float),np.asarray(v,float))
    gx=u/(model['width']-1);gy=v/(model['height']-1)
    cache=model.get('_motion_bend_cache')
    if cache is not None and u.size<=16384:
        # Only the paper-coordinate bend is cached. H is applied afresh on
        # every call. Exact coordinate/coefficient bytes prevent stale fields
        # after re-estimation or the planner's perspective-only fallback.
        key=(model['width'],model['height'],u.shape,u.tobytes(),v.tobytes(),
             model['bend_x'].tobytes(),model['bend_y'].tobytes())
        warped=cache.get(key)
        if warped is None:
            warped=(u+_bend_eval(model['bend_x'],gy,gx),v+_bend_eval(model['bend_y'],gx,gy))
            cache[key]=warped
            while (len(cache)>8 or sum(len(k[3])+len(k[4])+x.nbytes+y.nbytes
                                      for k,(x,y) in cache.items())>2*1024*1024):
                cache.popitem(last=False)
        else:
            cache.move_to_end(key)
        return project(model['H'],*warped)
    return project(model['H'],u+_bend_eval(model['bend_x'],gy,gx),
                   v+_bend_eval(model['bend_y'],gx,gy))


class TileGeometryError(ValueError):
    pass


class GeometryPlanFallback(ValueError):
    pass

def coordinate_bounds(regs,wo,ho,field):
    return [(float(low.min()),float(high.max())) for low,high in mapping_ranges(regs,wo,ho,field)]


def make_tile(model,box,image_shape,validator):
    require_yuyv_shape(image_shape)
    x0,y0,x1,y1=map(int,box);wo,ho=x1-x0,y1-y0
    if min(wo,ho)<2:raise ValueError('分块宽高不足2')
    if max(wo,ho)>1280:raise ValueError('输出分块超过硬件1280上限')
    # Shift ONE global H. Refitting H to four warped corners for each tiny tile
    # used to create unstable extrapolation at its final partial 64px cell.
    H=model['H']@np.array([[1.,0,x0],[0,1.,y0],[0,0,1.]])
    if H[2,2]<=1e-7:raise ValueError('分块基准H分母不安全')
    H=H/H[2,2]
    # Control nodes cover the active hardware cells, including the last partial cell.
    nx=(wo-1+63)//64+1;ny=(ho-1+63)//64+1
    u,v=np.meshgrid(np.arange(nx)*64.,np.arange(ny)*64.)
    xx,yy=map_points(model,u+x0,v+y0);bx,by=project(H,u,v)
    delta=np.rint(np.stack([xx-bx,yy-by],-1)*256).astype(np.int64)
    if np.any(abs(delta)>32768):raise TileGeometryError('局部位移超界')
    field=identity_field();field[:ny,:nx,:2]=delta.astype(np.int32)
    field[ny:,:,:2]=field[ny-1:ny,:,:2];field[:,nx:,:2]=field[:,nx-1:nx,:2]
    # Reject inaccurate geometry BEFORE building the expensive row schedules.
    # This is a sampling guard, not a mathematical bound on every output pixel.
    tu,tv=np.meshgrid(np.unique(np.r_[0,np.arange(16,wo,16),wo-1]),np.unique(np.r_[0,np.arange(16,ho,16),ho-1]))
    tx,ty=map_points(model,tu+x0,tv+y0);ax,ay=project(H,tu,tv)
    local=interpolate(field,tu,tv)
    residual=float(np.max(np.hypot(ax+local[...,0]/256-tx,ay+local[...,1]/256-ty)))
    if residual>.65:raise TileGeometryError('控制网格近似误差超过0.65源像素')
    grid=_range_grid(wo,ho,field)
    regs=homography_to_regs(H)
    bounds=[(float(low.min()),float(high.max())) for low,high in mapping_ranges(regs,wo,ho,field,_grid=grid)]
    ih,iw=image_shape[:2]
    left=max(0,min(iw-2,int(np.floor(bounds[0][0]))-2));right=min(iw,max(left+2,int(np.ceil(bounds[0][1]))+3))
    top=max(0,min(ih-2,int(np.floor(bounds[1][0]))-2));bottom=min(ih,max(top+2,int(np.ceil(bounds[1][1]))+3))
    if len(image_shape)==3 and image_shape[2]==2:
        left&=~1;right=min(iw,(right+1)&~1)
    wi,hi=right-left,bottom-top
    if wi>512 or hi>1280:raise ValueError('源区域宽度超出512输入限制（行缓存 MAX_W=512）')
    # Translate homography output to cropped source coordinates, preserving h33=1.
    H=np.array([[1,0,-left],[0,1,-top],[0,0,1.]])@H
    regs=homography_to_regs(H);field=validate_field(field)
    qx,qy,_=coordinates(regs,tu,tv,field)
    residual=float(np.max(np.hypot(qx/65536.+left-tx,qy/65536.+top-ty)))
    if residual>.65:raise TileGeometryError('定点映射采样误差超过0.65源像素')
    padded,rows=cache_profile(wi)
    candidate=dict(box=list(box),crop=[left,top,right,bottom],regs=regs,field=field,
        descriptors=np.empty(0,np.uint32),input_shape=(hi,wi,image_shape[2]),width=wo,height=ho,
        capacity_rows=rows,approximation_error=residual,planning_backend='pl_exact_suffix_rows',
        border_flags=int(left==0)|(int(top==0)<<1)|(int(right==iw)<<2)|(int(bottom==ih)<<3))
    if validator is None:raise RuntimeError('v9必须由PL规划器确认候选，不能用未验证行表')
    info=validator(candidate)
    candidate.update(peak_rows=info['peak_rows'],pl_preflight=info)
    return _seal_checked(candidate,candidate['input_shape'])


def _plan_tiles_v11(model,image_shape,tile_size=1280,max_tiles=512,planner='adaptive',validator=None):
    """Hints select candidates only; every leaf passes make_tile's full guards.

    Small sampled maps NEVER supply DMA row descriptors or certify cache safety.
    A bounded hint budget avoids turning heuristic search into another bottleneck.
    """
    reasons={};attempts=[];fallback=None;hints={}
    counters=dict(full_validation_attempts=0,predictive_splits=0,hint_evaluations=0,
                  hint_s=0.,full_validation_s=0.)
    if planner not in ('adaptive','legacy'):raise ValueError('planner=adaptive/legacy')
    if not 64<=tile_size<=1280:raise ValueError('tile_size须为64..1280')

    def hint(box):
        if box in hints:return hints[box]
        if counters['hint_evaluations']>=128:return None
        t=time.perf_counter();counters['hint_evaluations']+=1
        try:
            x0,y0,x1,y1=box
            u,v=np.meshgrid(np.linspace(x0,x1-1,9),np.linspace(y0,y1-1,17))
            xx,yy=map_points(model,u,v)
            if not np.all(np.isfinite(xx)) or not np.all(np.isfinite(yy)):return None
            ih,iw=image_shape[:2]
            left=max(0,min(iw-2,int(np.floor(xx.min()))-3));right=min(iw,max(left+2,int(np.ceil(xx.max()))+4))
            top=max(0,min(ih-2,int(np.floor(yy.min()))-3));bottom=min(ih,max(top+2,int(np.ceil(yy.max()))+4))
            if len(image_shape)==3 and image_shape[2]==2:
                left&=~1;right=min(iw,(right+1)&~1)
            wi,hi=right-left,bottom-top
            #   ⚠️ 2026-10-25：行缓存是**固定** ROWS=384（不是按宽度分档的老模型）
            rows=384
            low=np.clip(np.floor(yy.min(axis=1)),0,ih-2)
            high=np.clip(np.floor(yy.max(axis=1)),0,ih-2)+1
            future=np.minimum.accumulate(low[::-1])[::-1]
            peak=float(np.max(high-future+1))+4
            single=float(np.max(high-low+1))+4
            axis='x' if single>rows else 'y'
            if wi>512 or hi>1280:
                # Candidate scoring below can change this preliminary axis.
                axis='x' if wi>=hi else 'y'
            result=dict(width=wi,height=hi,rows=rows,peak=peak,axis=axis,
                        overload=max(wi/512.,hi/1280.,peak/rows),traffic=wi*hi,
                        obvious=(wi>520 or hi>1296 or peak>rows*1.18+8))
            hints[box]=result
            return result
        except (ValueError,OverflowError,FloatingPointError):return None
        finally:counters['hint_s']+=time.perf_counter()-t

    def children(box,axis,cut):
        x0,y0,x1,y1=box
        if axis=='x':return (x0,y0,cut,y1),(cut,y0,x1,y1)
        return (x0,y0,x1,cut),(x0,cut,x1,y1)

    def choose_split(box,preferred,depth):
        x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
        if (preferred=='x' and w<4) or (preferred=='y' and h<4):preferred='y' if preferred=='x' else 'x'
        start,size=(x0,w) if preferred=='x' else (y0,h)
        selected=(preferred,start+size//2)
        if planner=='legacy' or depth>=5 or counters['hint_evaluations']>=116:return selected
        best=None
        # Six cuts at most. Include an estimated cache-width transition when useful.
        parent=hint(box)
        for axis in (preferred,'y' if preferred=='x' else 'x'):
            start,size=(x0,w) if axis=='x' else (y0,h)
            if size<128:continue
            fractions=[.375,.5,.625]
            if axis=='x' and parent is not None:
                boundary=640 if parent['width']>640 else 320
                f=(boundary-12)/max(parent['width'],1)
                if .25<f<.75:fractions=[.5,f,1-f]
            for fraction in fractions:
                cut=start+int(round(size*fraction))
                if min(cut-start,start+size-cut)<64:continue
                a,b=children(box,axis,cut);ha,hb=hint(a),hint(b)
                if ha is None or hb is None:continue
                # Failed children dominate the cost; then prefer lower estimated
                # overflow, less duplicated source traffic and balanced partitions.
                overloads=[ha['overload'],hb['overload']]
                score=(sum(o>1 for o in overloads),sum(max(0,o-1) for o in overloads),
                       (ha['traffic']+hb['traffic'])/(w*h)+.05*abs(fraction-.5))
                if best is None or score<best:best=score;selected=(axis,cut)
        return selected

    def plan_once():
        plans=[]
        def split(box,depth=0):
            x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
            prediction=hint(box) if planner=='adaptive' and depth<3 and min(w,h)>=128 else None
            predict_split=(prediction is not None and prediction['obvious'] and counters['predictive_splits']<8)
            if predict_split:
                counters['predictive_splits']+=1
                error=None;reason='采样预测超限，提前选择子块（未作为安全证明）';preferred=prediction['axis']
            else:
                t=time.perf_counter();counters['full_validation_attempts']+=1
                try:tile=make_tile(model,box,image_shape,validator)
                except (ValueError,cv2.error) as e:
                    error=e;reason=str(e);preferred=getattr(e,'split_axis','x' if w>=h else 'y')
                else:
                    plans.append(tile)
                    if len(plans)>max_tiles:raise ValueError('分块数超过上限，请设置较小max_dim')
                    return
                finally:counters['full_validation_s']+=time.perf_counter()-t
            reasons[reason]=reasons.get(reason,0)+1
            if isinstance(error,TileGeometryError) and min(w,h)<=128:
                raise GeometryPlanFallback(reason+'；停止把局部曲率误差细分成微小块') from error
            if depth>=14 or max(w,h)<4:raise ValueError('无法安全分块: '+reason) from error
            axis,cut=choose_split(box,preferred,depth)
            attempts.append(dict(box=list(box),reason=reason,depth=depth,split_axis=axis,
                                 split_coordinate=cut,predictive=bool(predict_split)))
            a,b=children(box,axis,cut)
            split(a,depth+1);split(b,depth+1)
        xs=np.linspace(0,model['width'],int(np.ceil(model['width']/tile_size))+1).astype(int)
        ys=np.linspace(0,model['height'],int(np.ceil(model['height']/tile_size))+1).astype(int)
        for ya,yb in zip(ys[:-1],ys[1:]):
            for xa,xb in zip(xs[:-1],xs[1:]):split((int(xa),int(ya),int(xb),int(yb)))
        return plans
    try:plans=plan_once()
    except GeometryPlanFallback as e:
        if not (np.any(model['bend_x']) or np.any(model['bend_y'])):raise
        fallback=str(e);hints.clear()
        model['bend_x']=np.zeros((NY,NX));model['bend_y']=np.zeros((NY,NX))
        model['mesh_x']=np.zeros((33,33));model['mesh_y']=np.zeros((33,33))
        model['dewarp'].update(state='perspective_fallback',strength=0.,fallback_reason=fallback)
        plans=plan_once()
    model['plan_stats']=dict(initial_tile_size=tile_size,tile_count=len(plans),planner=planner,
                            min_tile_width=min(p['width'] for p in plans),min_tile_height=min(p['height'] for p in plans),
                            split_reason_counts=reasons,split_events=attempts,geometry_fallback=fallback,
                            geometry_guard_sample_step=16,geometry_guard_threshold=.65,
                            hint_budget=128,**counters)
    return plans


def plan_tiles(model,image_shape,tile_size=1280,max_tiles=512,planner='adaptive',validator=None):
    # Lazy import avoids the geometry/planner dependency cycle.
    if planner in ('legacy','adaptive_v11'):
        plans=_plan_tiles_v11(model,image_shape,tile_size,max_tiles,
                             'legacy' if planner=='legacy' else 'adaptive',validator)
        model['plan_stats'].update(planner=planner,search_backend='v11_direct_hints')
        return plans
    if planner!='adaptive':raise ValueError('planner=adaptive/adaptive_v11/legacy')
    from v14_planner import plan_tiles_fast
    return plan_tiles_fast(model,image_shape,tile_size,max_tiles,validator)
