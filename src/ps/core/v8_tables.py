"""Small-array Gaussian/CLAHE LUT construction and conservative row schedule."""
import hashlib
from pathlib import Path
import cv2
import numpy as np
from p11_contract import RELEASE_ID
from pl_fields import validate_field,interpolate
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def tile_shift(width,height):
    return max(5,(max(width,height)-1).bit_length()-3)

def _range_grid(wo,ho,field):
    starts=np.arange(0,wo,64,dtype=np.int64)
    u=np.stack([starts,np.minimum(starts+63,wo-1)],axis=-1)[None,:,:]
    v=np.arange(ho,dtype=np.int64)[:,None,None]
    local=interpolate(field[:,:,:2],u,v)/256.
    return u,v,local.min(axis=2),local.max(axis=2)


def mapping_ranges(regs,wo,ho,field=None,*,_grid=None):
    from pl_fields import identity_field
    field=identity_field() if field is None else validate_field(field)
    if len(regs)!=8 or any(not -(1<<31)<=int(r)<(1<<31) for r in regs):
        raise ValueError('H 参数超出int32')
    a,b,c,d,e,f,g,h=map(int,regs)
    u,v,shift_low,shift_high=_range_grid(wo,ho,field) if _grid is None else _grid
    den=g*u*32+h*v*32+(1<<32)
    nums=[a*u*32+b*v*32+(c<<16),d*u*32+e*v*32+(f<<16)]
    if np.any((den>>16)<16384) or np.any((den>>16)>=(1<<31)):
        raise ValueError('H分母不安全，未启动DMA')
    ranges=[]
    for axis,num in enumerate(nums):
        if np.any((num>>16)<-(1<<31)) or np.any((num>>16)>=(1<<31)):
            raise ValueError('H被除数不安全')
        ratios=num/den
        dmin=np.min(den,axis=-1)/65536.
        # Truncation of N,D before division + final signed Q16 truncation.
        guard=(1+np.max(np.abs(ratios),axis=-1))/(dmin-1)+1/65536.+1e-7
        low=np.min(ratios,axis=-1)-guard+shift_low[...,axis]
        high=np.max(ratios,axis=-1)+guard+shift_high[...,axis]
        if np.any(low<=-32768) or np.any(high>=32767):raise ValueError('校正坐标越界')
        ranges.append((low.min(axis=1),high.max(axis=1)))
    return ranges

class WindowOverflow(ValueError):
    def __init__(self,message,split_axis):
        super().__init__(message)
        self.split_axis=split_axis


def schedule_from_ranges(ranges,hi,rows):
    lo,high=ranges[1]
    lowrows=np.clip(np.floor(lo),0,hi-2).astype(np.int64)
    highrows=np.clip(np.floor(high),0,hi-2).astype(np.int64)+1
    floor=np.minimum.accumulate(lowrows[::-1])[::-1]
    span=highrows-floor+1
    if np.any(span>rows):
        k=int(np.argmax(span))
        # Width helps when ONE row spans too many source rows. Height helps
        # when later output rows force much earlier source data to remain live.
        axis='x' if highrows[k]-lowrows[k]+1>rows else 'y'
        raise WindowOverflow(f'含局部校正的保守窗口第{k}行需要{span[k]}行，容量{rows}；未启动DMA。',axis)
    return ((highrows.astype(np.uint32)<<16)|floor.astype(np.uint32)),int(span.max())


def safe_schedule(regs,wo,ho,hi,rows=128,field=None):
    return schedule_from_ranges(mapping_ranges(regs,wo,ho,field),hi,rows)


def tables_from_histogram(counts,width,height,shift,profile='photo',strength=.7,clip_limit=2.0):
    if profile not in ('document','photo'):raise ValueError('profile 为 document/photo')
    if not np.isfinite(strength) or not 0<=strength<=1:raise ValueError('strength 为0..1')
    if not np.isfinite(clip_limit) or not 1<=clip_limit<=8:raise ValueError('clip_limit 为1..8')
    hist=np.asarray(counts,dtype=np.uint32).reshape(8,8,64)
    pitch=1<<shift;nx=(width+pitch-1)//pitch;ny=(height+pitch-1)//pitch
    totals=hist.astype(np.uint64).sum(axis=2)
    expected=np.zeros((8,8),np.uint64)
    for y in range(ny):
        for x in range(nx):expected[y,x]=min(pitch,height-y*pitch)*min(pitch,width-x*pitch)
    if not np.array_equal(totals,expected):raise ValueError('PL分块直方图像素数不符，不进行第二遍')
    # Quantile background for documents; broad scene illumination for photographs.
    active=hist[:ny,:nx].astype(np.float64)
    sums=active.sum(axis=2)
    centers=np.arange(64)*4+1.5
    if profile=='document':
        bg=(np.argmax(np.cumsum(active,axis=2)>=sums[:,:,None]*.90,axis=2)*4+3).astype(np.float32)
    else:bg=((active*centers).sum(axis=2)/sums).astype(np.float32)
    smooth=cv2.GaussianBlur(bg,(5,5),0,borderType=cv2.BORDER_REPLICATE)
    target=float(np.median(smooth))
    normalized_gain=np.clip(target/np.maximum(smooth,24),.65,1.6)
    light_strength=strength if profile=='document' else strength*.4
    gains=1+light_strength*(normalized_gain-1)
    lut=np.empty((8,8,256),np.uint8)
    levels=np.arange(256,dtype=float)
    for y in range(ny):
        for x in range(nx):
            # Build the local CDF in the normalized luminance domain.
            mapped=np.clip(np.floor(centers*gains[y,x]/4),0,63).astype(int)
            rebinned=np.bincount(mapped,weights=active[y,x],minlength=64)
            cap=clip_limit*sums[y,x]/64.
            clipped=np.minimum(rebinned,cap)
            clipped+=(sums[y,x]-clipped.sum())/64.
            cdf=np.cumsum(clipped)/sums[y,x]*255.
            normal=np.clip(levels*gains[y,x],0,255)
            contrast=np.interp(normal,centers,cdf,left=0,right=255)
            amount=strength if profile=='document' else strength*.5
            result=(1-amount)*normal+amount*contrast
            # Constant/near-constant tiles contain no reliable local contrast.
            if np.count_nonzero(active[y,x])<=1:result=normal
            lut[y,x]=np.clip(np.rint(result),0,255).astype(np.uint8)
    for y in range(8):
        for x in range(8):
            if y>=ny or x>=nx:lut[y,x]=lut[min(y,ny-1),min(x,nx-1)]
    return lut,dict(profile=profile,strength=strength,clip_limit=clip_limit,tiles=[nx,ny],pitch=pitch,
                   background=smooth.tolist(),gains=gains.tolist(),histogram_pixels=int(totals.sum()))

def pack_tables(lut):
    q=np.asarray(lut,dtype=np.uint8).reshape(-1,4).astype(np.uint32)
    return q[:,0]|(q[:,1]<<8)|(q[:,2]<<16)|(q[:,3]<<24)

def apply_tables(rgb,lut,shift):
    h,w=rgb.shape[:2];pitch=1<<shift;nx=(w+pitch-1)//pitch;ny=(h+pitch-1)//pitch
    def positions(p,n):
        relative=np.maximum(p-pitch//2,0)
        base=relative>>shift;frac=(relative&(pitch-1))<<(8-shift)
        if n<=1:return np.zeros_like(base),np.zeros_like(frac)
        end=base>=n-1
        return np.where(end,n-2,base),np.where(end,256,frac)
    xx,fx=positions(np.arange(w)[None,:],nx);yy,fy=positions(np.arange(h)[:,None],ny)
    q=rgb.astype(np.int32);Y=(q[:,:,2]*77+q[:,:,1]*150+q[:,:,0]*29+128)>>8
    a=lut[yy,xx,Y].astype(np.int64);b=lut[yy,xx+1,Y].astype(np.int64)
    c=lut[yy+1,xx,Y].astype(np.int64);d=lut[yy+1,xx+1,Y].astype(np.int64)
    new=(((a*(256-fx)+b*fx)*(256-fy)+(c*(256-fx)+d*fx)*fy+32768)>>16)
    return np.clip(q+(new-Y)[:,:,None],0,255).astype(np.uint8)
