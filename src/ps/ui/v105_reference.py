"""Vectorized fallback for the CPU edge kernel; same evidence requirements."""
import cv2,numpy as np
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ALONG=np.linspace(.10,.90,24,dtype=np.float32)
T=2*ALONG-1
def measure_python(gray,q,radius,reference=None):
    q=np.asarray(q,np.float32);edge=np.roll(q,-1,axis=0)-q
    length=np.linalg.norm(edge,axis=1)
    if np.any(length<24):raise ValueError('physical_side_too_short')
    normal=np.stack((edge[:,1],-edge[:,0]),axis=1)/length[:,None]
    base=q[:,None,:]+ALONG[None,:,None]*edge[:,None,:]
    offsets=np.arange(-radius,radius+.25,.5,dtype=np.float32)
    grid=base[:,:,None,:]+offsets[None,None,:,None]*normal[:,None,None,:]
    coords=np.concatenate([(grid+s*normal[:,None,None,:]).reshape(96,-1,2) for s in (1,-1,-2)])
    values=cv2.remap(gray,coords[...,0],coords[...,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    outer,inner,body=np.split(values,3);mag=np.abs(outer-inner)
    error=0 if reference is None else np.abs(body-np.asarray(reference).reshape(96,1))
    h,w=gray.shape
    valid=(coords[...,0]>=0)&(coords[...,0]<w-1)&(coords[...,1]>=0)&(coords[...,1]<h-1)
    valid=np.logical_and.reduce(np.split(valid,3)) & (error<=40)
    peak=(mag>=np.roll(mag,1,axis=1))&(mag>=np.roll(mag,-1,axis=1))&(mag>=8)
    peak[:,[0,-1]]=False
    cap=np.clip(1.05*np.max(np.where(np.abs(offsets)[None,:]<=2,mag,0),axis=1),16,80)
    scores=np.where(valid&peak,np.minimum(mag,cap[:,None])-.8*np.abs(offsets)[None,:]-.65*error,-1e9)
    idx=scores.argmax(1);rows=np.arange(96);lo=np.maximum(0,idx-1);hi=np.minimum(len(offsets)-1,idx+1)
    mid=mag[rows,idx];den=mag[rows,lo]-2*mid+mag[rows,hi]
    refine=.25*(mag[rows,lo]-mag[rows,hi])/np.where(np.abs(den)>.01,den,-1.)
    shift=(offsets[idx]+np.clip(refine,-.4,.4)).reshape(4,24)
    good=((mid>=8)&(np.abs(offsets[idx])<radius-.1)&valid[rows,idx]&peak[rows,idx]).reshape(4,24)
    for i in range(3):
        n=good.sum(1);s=(good*T).sum(1);ss=(good*T*T).sum(1)
        v=(good*shift).sum(1);sv=(good*shift*T).sum(1);den=n*ss-s*s
        if np.any(den<1):raise ValueError('physical_edge_distribution_insufficient')
        tilt=(n*sv-s*v)/den;intercept=(v-tilt*s)/n
        residual=shift-intercept[:,None]-tilt[:,None]*T
        if i<2:good=good & (np.abs(residual)<=1)
    count=good.sum(1);rms=np.sqrt((good*residual*residual).sum(1)/np.maximum(count,1))
    span=np.max(np.where(good,T,-10),axis=1)-np.min(np.where(good,T,10),axis=1)
    if np.any(count<15) or np.any(span<1.1) or np.any(rms>.7):raise ValueError('physical_four_edges_not_proved')
    a=q+normal*(intercept-tilt)[:,None];b=q+edge+normal*(intercept+tilt)[:,None]
    v=b-a;line=np.stack((v[:,1],-v[:,0]),axis=1);c=-(line*a).sum(1)
    prev=np.roll(line,1,axis=0);pc=np.roll(c,1);det=prev[:,0]*line[:,1]-prev[:,1]*line[:,0]
    if np.any(np.abs(det)<length*np.roll(length,1)*.1):raise ValueError('physical_corner_intersection_invalid')
    result=np.stack(((prev[:,1]*c-pc*line[:,1])/det,(pc*line[:,0]-prev[:,0]*c)/det),axis=1).astype(np.float32)
    pos=(base+(intercept[:,None]+tilt[:,None]*T-2)[:,:,None]*normal[:,None,:]).astype(np.float32)
    measured=cv2.remap(gray,pos[...,0],pos[...,1],cv2.INTER_LINEAR).astype(np.float32).reshape(96)
    return result,dict(support=(count/24).tolist(),edge_rms=rms.tolist(),sample_count=96,body=measured,edge_backend='numpy105')
