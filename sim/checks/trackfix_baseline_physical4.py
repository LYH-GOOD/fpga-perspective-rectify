"""Batched 4x24 physical boundary probes; one remap, no video/LK/model loop."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v92_manual_v87 import ManualTracker
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ALONG=np.linspace(.10,.90,24,dtype=np.float32)
_T=2.*_ALONG-1.


def measure(gray,q,radius=4.):
    """Signed dark-body / lighter-exterior edges, all four sides in one batch."""
    q=np.asarray(q,np.float32);edge=np.roll(q,-1,axis=0)-q
    length=np.linalg.norm(edge,axis=1)
    if np.any(length<24):raise ValueError('physical_side_too_short')
    normals=np.stack((edge[:,1],-edge[:,0]),axis=1)/length[:,None]
    base=q[:,None,:]+_ALONG[None,:,None]*edge[:,None,:]
    offsets=np.arange(-radius,radius+.25,.5,dtype=np.float32)
    grid=base[:,:,None,:]+offsets[None,None,:,None]*normals[:,None,None,:]
    outer=grid+normals[:,None,None,:];inner=grid-normals[:,None,None,:]
    h,w=gray.shape
    valid=(np.minimum(outer[...,0],inner[...,0])>=1)&(np.maximum(outer[...,0],inner[...,0])<=w-2)&(np.minimum(outer[...,1],inner[...,1])>=1)&(np.maximum(outer[...,1],inner[...,1])<=h-2)
    coords=np.concatenate((outer.reshape(-1,len(offsets),2),inner.reshape(-1,len(offsets),2)),axis=0)
    values=cv2.remap(gray,coords[...,0],coords[...,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    contrast=(values[:96]-values[96:]).reshape(4,24,-1)
    score=np.where(valid,contrast-.65*np.abs(offsets)[None,None,:],-1000.)
    idx=np.argmax(score,axis=2);selected=np.take_along_axis(contrast,idx[...,None],axis=2)[...,0]
    shift=offsets[idx].copy();lo=np.maximum(0,idx-1);hi=np.minimum(len(offsets)-1,idx+1)
    ym=np.take_along_axis(contrast,lo[...,None],axis=2)[...,0];yp=np.take_along_axis(contrast,hi[...,None],axis=2)[...,0]
    denom=ym-2*selected+yp
    shift+=.5*np.clip(.5*(ym-yp)/np.where(np.abs(denom)>.01,denom,-1.),-.8,.8)
    good=(selected>=12.)&(idx>0)&(idx<len(offsets)-1)
    weight=good.astype(np.float32)
    def fit(weight):
        count=weight.sum(1);s=(weight*_T).sum(1);ss=(weight*_T*_T).sum(1)
        y=(weight*shift).sum(1);sy=(weight*shift*_T).sum(1)
        den=count*ss-s*s
        if np.any(den<1.):raise ValueError('physical_edge_distribution_insufficient')
        tilt=(count*sy-s*y)/den;intercept=(y-tilt*s)/np.maximum(count,1.)
        return intercept,tilt
    for _ in range(2):
        intercept,tilt=fit(weight);residual=shift-intercept[:,None]-tilt[:,None]*_T
        weight=good*(np.abs(residual)<=1.0)
    intercept,tilt=fit(weight);count=weight.sum(1)
    residual=shift-intercept[:,None]-tilt[:,None]*_T
    rms=np.sqrt((weight*residual*residual).sum(1)/np.maximum(count,1.))
    span=np.max(np.where(weight>0,_T,-10),axis=1)-np.min(np.where(weight>0,_T,10),axis=1)
    if np.any(count<15) or np.any(span<1.1) or np.any(rms>.7):raise ValueError('physical_four_edges_not_proved')
    a=q+normals*(intercept-tilt)[:,None];b=q+edge+normals*(intercept+tilt)[:,None]
    v=b-a;line=np.stack((v[:,1],-v[:,0]),axis=1);c=-(line*a).sum(1)
    prev=np.roll(line,1,axis=0);pc=np.roll(c,1);det=prev[:,0]*line[:,1]-prev[:,1]*line[:,0]
    if np.any(np.abs(det)<length*np.roll(length,1)*.10):raise ValueError('physical_corner_intersection_invalid')
    result=np.stack(((prev[:,1]*c-pc*line[:,1])/det,(pc*line[:,0]-prev[:,0]*c)/det),axis=1).astype(np.float32)
    from v31_tracking import _valid
    if not _valid(result,gray.shape,q,'legacy'):raise ValueError('physical_quad_invalid')
    return result,dict(support=(count/24.).tolist(),edge_rms=rms.tolist(),sample_count=96,remap_calls=1)


class PhysicalTracker:
    """Finite local evidence, fast batched profiles and physical-corner smoothing."""
    physical=True
    def __init__(self,frame,quad,limit=320,authority='ai_physical',entry_radius=8.):
        from v31_tracking import GrayObserver
        self.observer=GrayObserver(limit);self.q=np.asarray(quad,np.float32).copy();self.closed=False
        try:
            self.gray,self.scale=self.observer.get(frame.image)
            self.previous_ready=float(frame.ready);self.kind='PHYSICAL_EDGE_FAST';self.fixed=False;self.points=None;self.failures=0
            small=(self.q+.5)/self.scale-.5
            found,detail=measure(self.gray,small,entry_radius);self.raw_q=(found+.5)*self.scale-.5
            self.q=self.raw_q.copy();self.velocity=np.zeros((4,2),np.float32)
        except BaseException:self.close();raise
        checkpoint('AI_PHYSICAL_TRACKER_READY',authority=authority,source_sha256=_SOURCE_SHA256,
            feature_region='four signed physical-body boundary strips; no interior video',
            per_frame_model=False,per_frame_lk=False,profile_samples=96,remap_calls=1,edge_detail=detail)

    def update(self,frame,radius=4.):
        began=time.perf_counter();cpu=time.thread_time()
        try:
            if not 0<=float(frame.ready)-self.previous_ready<=8.:raise ValueError('physical_capture_gap')
            self.previous_ready=float(frame.ready)
            gray,scale=self.observer.get(frame.image)
            if not np.array_equal(scale,self.scale):raise ValueError('physical_source_layout_changed')
            prediction=self.raw_q+np.clip(self.velocity,-6.,6.)
            found,edges=measure(gray,(prediction+.5)/scale-.5,radius)
            measured=(found+.5)*scale-.5
            delta=float(np.max(np.linalg.norm(measured-self.raw_q,axis=1)))
            if delta>32.:raise ValueError('physical_motion_outside_local_window')
            shift=float(np.max(np.linalg.norm(measured-self.q,axis=1)))
            candidate=self.q.copy() if shift<=.65 else measured if shift>=3. else self.q+.8*(measured-self.q)
            from v82_interaction import selected_quad
            selected_quad(candidate,frame.image.shape)
            self.velocity=.4*self.velocity+.6*(measured-self.raw_q)
            self.raw_q=measured;self.q=np.asarray(candidate,np.float32);self.previous_ready=float(frame.ready);self.failures=0
            detail=dict(manual_motion_proved=True,current_outer_edge_evidence=True,physical_corner_shift=shift,physical_static_deadband=shift<=.65,physical_edges=edges)
            result=self.q.copy()
        except (ValueError,cv2.error) as exc:
            self.failures+=1;self.velocity.fill(0.);result=None
            detail=dict(manual_motion_proved=False,current_outer_edge_evidence=False,reason=str(exc))
            if self.failures in (1,3) or self.failures%60==0:checkpoint('AI_PHYSICAL_EDGE_REJECTED',reason=str(exc),consecutive=self.failures,old_coordinates_not_renewed=True)
        detail.update(manual_tracking=self.kind,physical_body=True,video_features=False,tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu)
        return result,detail

    def close(self):
        if getattr(self,'closed',True):return
        self.closed=True;transaction=getattr(self.observer,'transaction',None);close=getattr(transaction,'close',None)
        if callable(close):close()
        self.observer=None;self.gray=None


def create_tracker(frame,quad,limit=320,authority='ai'):
    """Physical profile needs all four signed edges; other planes use baseline."""
    try:return PhysicalTracker(frame,quad,limit,authority)
    except (ValueError,cv2.error):return ManualTracker(frame,quad,limit,authority)
