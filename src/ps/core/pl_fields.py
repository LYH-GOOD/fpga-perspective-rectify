"""Shared Q8 field and exact integer reference arithmetic (no PYNQ import)."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from p11_contract import RELEASE_ID, cache_profile
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
N=21
PITCH=64

def identity_field():
    field=np.zeros((N,N,4),dtype=np.int32)
    field[:,:,2]=256
    return field

def validate_field(field):
    a=np.asarray(field)
    if a.shape!=(N,N,4) or a.dtype!=np.int32:
        raise ValueError('field 必须为 int32 [21,21,4]，Q8 dx/dy/gain/offset')
    if np.any(np.abs(a[:,:,:2].astype(np.int64))>128*256):
        raise ValueError('局部位移超过 +/-128 源像素，请降低尺寸/形变')
    if np.any(a[:,:,2]<128) or np.any(a[:,:,2]>768) or np.any(np.abs(a[:,:,3].astype(np.int64))>192*256):
        raise ValueError('gain 必须为0.5..3.0，offset 为 +/-192 (HW ABI 9)')
    return a

def interpolate(field,u,v):
    u,v=np.broadcast_arrays(np.asarray(u,dtype=np.int64),np.asarray(v,dtype=np.int64))
    x,y=u//64,v//64
    fx,fy=(u%64)[...,None],(v%64)[...,None]
    a=field[y,x].astype(np.int64);b=field[y,x+1].astype(np.int64)
    c=field[y+1,x].astype(np.int64);d=field[y+1,x+1].astype(np.int64)
    return (((a*(64-fx)+b*fx)*(64-fy)+(c*(64-fx)+d*fx)*fy)>>12)

def coordinates(regs,u,v,field):
    a,b,c,d,e,f,g,h=map(int,regs)
    u,v=np.broadcast_arrays(np.asarray(u,dtype=np.int64),np.asarray(v,dtype=np.int64))
    denominator=(g*u*32+h*v*32+(1<<32))>>16
    nx=(a*u*32+b*v*32+(c<<16))>>16
    ny=(d*u*32+e*v*32+(f<<16))>>16
    if np.any(denominator<16384) or np.any(denominator>=(1<<31)) or any(np.any(t<-(1<<31)) or np.any(t>=(1<<31)) for t in (nx,ny)):
        raise ValueError('H 超出 v4 除法器安全范围；未启动 DMA')
    def divide(t):
        t=t<<16
        return np.where(t<0,-(np.abs(t)//denominator),t//denominator)
    x,y=divide(nx),divide(ny)
    local=interpolate(field,u,v)
    x=x+(local[...,0]<<8);y=y+(local[...,1]<<8)
    if any(np.any(t<-(1<<31)) or np.any(t>=(1<<31)) for t in (x,y)):
        raise ValueError('局部校正坐标超出 Q16.16')
    return x,y,local

def schedule(regs,w_out,h_out,h_in,rows,field):
    validate_field(field)
    lows=[]; highs=[]
    u=np.arange(w_out,dtype=np.int64)
    for v in range(h_out):
        _,y,_=coordinates(regs,u,v,field)
        y0=np.clip(y>>16,0,h_in-2)
        lows.append(int(y0.min()));highs.append(int(y0.max())+1)
    floor=np.minimum.accumulate(np.asarray(lows)[::-1])[::-1]
    high=np.asarray(highs)
    span=high-floor+1
    if np.any(span>rows):
        row=int(np.argmax(span))
        raise ValueError(f'含局部位移的未来行窗口在第{row}行需要{span[row]}行，容量{rows}；未启动DMA。降低max_dim。')
    return ((high.astype(np.uint32)<<16)|floor.astype(np.uint32)),int(span.max())

def tone(rgb,local,shoulder=True):
    gain=local[...,2,None];offset=local[...,3,None]
    maximum=rgb.max(axis=-1).astype(np.int64)
    weights=np.array([255,253,251,249,247,245,243,241],dtype=np.int64)
    s=np.where(maximum<224,256,weights[np.clip((maximum-224)//4,0,7)]) if shoulder else np.full(maximum.shape,256)
    return np.clip(((rgb.astype(np.int64)*gain+offset)*s[...,None]+32768)>>16,0,255).astype(np.uint8)

def reference(image,regs,w_out,h_out,field,shoulder=True):
    h,w=image.shape[:2];out=np.empty((h_out,w_out,3),np.uint8)
    u=np.arange(w_out,dtype=np.int64)
    for v in range(h_out):
        x,y,local=coordinates(regs,u,v,field)
        xi,yi=x>>16,y>>16
        fx=np.where(x<0,0,np.where(xi>=w-1,65535,x&65535)).astype(np.uint64)[:,None]
        fy=np.where(y<0,0,np.where(yi>=h-1,65535,y&65535)).astype(np.uint64)[:,None]
        x0,y0=np.clip(xi,0,w-2),np.clip(yi,0,h-2)
        p00=image[y0,x0].astype(np.uint64);p10=image[y0,x0+1].astype(np.uint64)
        p01=image[y0+1,x0].astype(np.uint64);p11=image[y0+1,x0+1].astype(np.uint64)
        top=(65536-fx)*p00+fx*p10
        bottom=(65536-fx)*p01+fx*p11
        rgb=(((65536-fy)*top+fy*bottom+(1<<31))>>32).astype(np.uint8)
        out[v]=tone(rgb,local,shoulder)
    return out

def project(H,x,y):
    den=H[2,0]*x+H[2,1]*y+H[2,2]
    if np.any(np.abs(den)<1e-6):
        raise ValueError('校正场 H 分母接近零')
    return (H[0,0]*x+H[0,1]*y+H[0,2])/den,(H[1,0]*x+H[1,1]*y+H[1,2])/den

def load_calibration(path,image_shape):
    if path is None:return None
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    K=np.asarray(data['camera_matrix'],float)
    D=np.asarray(data['dist_coeffs'],float).reshape(-1)
    size=np.asarray(data['image_size'],float)
    if K.shape!=(3,3) or D.size!=5 or size.shape!=(2,) or np.any(size<=0) or not np.all(np.isfinite(K)) or not np.all(np.isfinite(D)) or not np.all(np.isfinite(size)) or K[0,0]<=0 or K[1,1]<=0:
        raise ValueError('需要有限的3x3 K、5系数[k1,k2,p1,p2,k3]、image_size=[宽,高]')
    if abs(K[0,1])>1e-8 or not np.allclose(K[2],[0,0,1]) or abs(K[1,0])>1e-8:
        raise ValueError('此版本仅支持零 skew 的 OpenCV 标准针孔相机模型')
    h,w=image_shape[:2]
    sx,sy=w/size[0],h/size[1]
    if abs(sx/sy-1)>0.01:
        raise ValueError('照片与标定图宽高比不符；不可用于不同裁剪/旋转的相机图像')
    K=K.copy();K[0,0]*=sx;K[1,1]*=sy
    K[0,2]=(K[0,2]+0.5)*sx-0.5;K[1,2]=(K[1,2]+0.5)*sy-0.5
    return K,D

def distort(K,D,x,y):
    xn=(x-K[0,2])/K[0,0];yn=(y-K[1,2])/K[1,1]
    k1,k2,p1,p2,k3=D
    r=xn*xn+yn*yn;rad=1+k1*r+k2*r*r+k3*r*r*r
    return K[0,0]*(xn*rad+2*p1*xn*yn+p2*(r+2*xn*xn))+K[0,2],K[1,1]*(yn*rad+p1*(r+2*yn*yn)+2*p2*xn*yn)+K[1,2]

def edge_bend(image,H,w_out,h_out):
    """Conservative outer-boundary estimator, not a grid/interior line detector."""
    edges=cv2.Canny(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),50,150)
    t=np.linspace(0,1,65)
    h,w=image.shape[:2];radius=max(2,min(12,round(min(h,w)*0.018)))
    fits=[];reports=[]
    for name,uu,vv in [('top',t*(w_out-1),np.zeros_like(t)),('bottom',t*(w_out-1),np.full_like(t,h_out-1)),('left',np.zeros_like(t),t*(h_out-1)),('right',np.full_like(t,w_out-1),t*(h_out-1))]:
        x,y=project(H,uu,vv)
        tangent=np.array([x[-1]-x[0],y[-1]-y[0]])
        normal=np.array([-tangent[1],tangent[0]])/max(1e-9,np.linalg.norm(tangent))
        chosen=[];tt=[]
        for j in range(3,62):
            offsets=np.arange(-radius,radius+1)
            xx=np.rint(x[j]+normal[0]*offsets).astype(int)
            yy=np.rint(y[j]+normal[1]*offsets).astype(int)
            inside=(xx>=0)&(xx<w)&(yy>=0)&(yy<h)
            hit=offsets[inside & (edges[np.clip(yy,0,h-1),np.clip(xx,0,w-1)]>0)]
            if len(hit):
                chosen.append(float(hit[np.argmin(np.abs(hit))]));tt.append(t[j])
        accepted=False;amplitude=0.;rms=None
        if len(tt)>=42:
            tt=np.asarray(tt);chosen=np.asarray(chosen)
            basis=4*tt*(1-tt)
            amplitude=float(np.dot(basis,chosen)/np.dot(basis,basis))
            residual=chosen-amplitude*basis
            rms=float(np.sqrt(np.mean(residual**2)))
            accepted=(rms<0.85 and 0.7<abs(amplitude)<radius*0.7 and np.mean(np.abs(residual)<1.25)>0.8)
        fits.append((normal,amplitude if accepted else 0.))
        reports.append(dict(edge=name,samples=len(tt),accepted=bool(accepted),amplitude_px=amplitude,rms_px=rms))
    def delta(u,v):
        s=np.clip(u/max(1,w_out-1),0,1);t0=np.clip(v/max(1,h_out-1),0,1)
        shape=np.broadcast(s,t0).shape;d=np.zeros(shape+(2,),float)
        for idx,weight,curve in [(0,1-t0,4*s*(1-s)),(1,t0,4*s*(1-s)),(2,1-s,4*t0*(1-t0)),(3,s,4*t0*(1-t0))]:
            normal,amp=fits[idx];d+= (weight*curve*amp)[...,None]*normal
        return d
    return delta,reports



def control_field(template_path,output_points,source_points,output_path='local_field.npz'):
    """Build a general smooth displacement field from explicit correspondences.
    Output points: desired pixel positions in the rectified output.
    Source points: matching observed positions in the PL INPUT (saved input PNG).
    These are correspondences, not automatically guessed straightness constraints.
    Four corners are fixed to the template mapping; do not repeat corner anchors.
    """
    with np.load(template_path,allow_pickle=False) as data:
        field=validate_field(data['field']).copy();regs=data['regs'].copy()
        input_shape=data['input_shape'].copy();output_shape=data['output_shape'].copy()
    ho,wo=map(int,output_shape);hi,wi=map(int,input_shape)
    target=np.asarray(output_points,float);source=np.asarray(source_points,float)
    if target.ndim!=2 or target.shape[1]!=2 or target.shape!=source.shape or len(target)<1 or len(target)>64:
        raise ValueError('需要1..64对二维对应点')
    if not np.all(np.isfinite(target)) or not np.all(np.isfinite(source)) or np.any(target<0) or np.any(target>[wo-1,ho-1]) or np.any(source<0) or np.any(source>[wi-1,hi-1]):
        raise ValueError('控制点超出输入/输出坐标范围')
    if not np.allclose(target,np.rint(target)):raise ValueError('输出控制点使用整数像素坐标')
    anchors=np.array([[0,0],[wo-1,0],[wo-1,ho-1],[0,ho-1]],float)
    xy=np.vstack([anchors,target]);scaled=xy/[max(1,wo-1),max(1,ho-1)]
    dist=np.linalg.norm(scaled[:,None,:]-scaled[None,:,:],axis=2)
    if np.any((dist+np.eye(len(xy)))<1e-4):raise ValueError('控制点重复或与固定四角过近')
    px,py,_=coordinates(regs,target[:,0],target[:,1],field)
    delta=np.vstack([np.zeros((4,2)),source-np.column_stack([px,py])/65536])
    def kernel(r):return r*r*np.log(np.maximum(r,1e-12))
    K=kernel(dist);P=np.column_stack([np.ones(len(xy)),scaled])
    system=np.block([[K+np.eye(len(xy))*1e-7,P],[P.T,np.zeros((3,3))]])
    coefficients=np.linalg.solve(system,np.vstack([delta,np.zeros((3,2))]))
    u,v=np.meshgrid(np.arange(N)*64.,np.arange(N)*64.)
    uv=np.column_stack([np.minimum(u.ravel(),wo-1)/(wo-1),np.minimum(v.ravel(),ho-1)/(ho-1)])
    basis=np.column_stack([kernel(np.linalg.norm(uv[:,None,:]-scaled[None,:,:],axis=2)),np.ones(len(uv)),uv])
    change=(basis@coefficients).reshape(N,N,2)
    if not np.all(np.isfinite(change)) or np.max(np.abs(change))>128:raise ValueError('控制点形成过大/不稳定位移')
    field[:,:,:2]+=np.rint(change*256).astype(np.int32)
    validate_field(field)
    # Re-evaluate true integer row lifetimes before writing a usable field.
    schedule(regs,wo,ho,hi,cache_profile(wi)[1],field)
    np.savez(output_path,field=field,regs=regs,input_shape=input_shape,output_shape=output_shape)
    return str(output_path)
