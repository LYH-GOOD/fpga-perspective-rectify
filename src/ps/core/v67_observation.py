"""Small photometric diagnostics; never alters image pixels or proves a quad."""
from pathlib import Path
import hashlib,time
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class IlluminationMotion:
    def __init__(self):
        u,v=np.meshgrid(np.linspace(.15,.85,8),np.linspace(.15,.85,8))
        u=u.ravel();v=v.ravel()
        self.weights=np.stack(((1-u)*(1-v),u*(1-v),u*v,(1-u)*v),axis=1).astype(np.float32)
        self.xy=np.empty((64,2),np.float32);self.previous=None;self.current=None
        self.last_grace_at=-1e9;self.detail={}
    def observe(self,image,quad,enabled=True):
        began=time.perf_counter();cpu=time.thread_time()
        if not enabled:self.previous=None
        self.current=None
        if image.ndim!=3 or image.shape[2]!=2:
            self.detail=dict(available=False,reason='YUYV_required');return self.detail
        q=np.asarray(quad,np.float32)
        np.matmul(self.weights,q,out=self.xy)
        x=np.clip(np.rint(self.xy[:,0]).astype(np.int32),0,image.shape[1]-1)
        y=np.clip(np.rint(self.xy[:,1]).astype(np.int32),0,image.shape[0]-1)
        values=image[y,x,0].astype(np.float32);self.current=values
        mean=float(np.mean(values));clipped=float(np.mean((values<=20)|(values>=235)))
        changed=False;residual=None;gain=1.;delta=0.
        if self.previous is not None:
            p=self.previous;pm=float(np.mean(p));a=p-pm;b=values-mean
            variance=float(np.dot(a,a));gain=float(np.clip(np.dot(a,b)/max(variance,1.),.5,2.)) if variance>=64. else 1.
            residual=float(np.median(np.abs(b-gain*a)));delta=mean-pm
            changed=bool(abs(delta)>=6. and residual<=5. and .7<=gain<=1.4 and clipped<.10)
        self.detail=dict(available=True,sample_count=64,luma_mean=mean,luma_delta=delta,estimated_gain=gain,
            photometric_residual=residual,clipped_fraction=clipped,illumination_change=changed,
            probe_s=time.perf_counter()-began,probe_thread_cpu_s=time.thread_time()-cpu,
            image_pixels_modified=False,geometric_proof_granted=False)
        return self.detail
    def eligible(self,gate,candidate,previous,age,maximum,reason):
        movement=float(np.max(np.linalg.norm(np.asarray(candidate)-previous,axis=1)))
        eligible=bool(self.detail.get('illumination_change') and gate.get('reliable')
            and gate.get('min_support',0.)>=.80 and gate.get('max_rms',1e30)<=.50
            and gate.get('prediction_correction',1e30)<=1.25 and movement<=1.25
            and age<maximum and reason in ('motion_burst','expanded_band_current_motion')
            and time.perf_counter()-self.last_grace_at>=.5)
        self.detail.update(geometry_motion_tracking_pixels=movement,local_reproof_eligible=eligible,
            prior_LK_trigger=reason,hard_FB_age_preserved=True)
        return eligible
    def accepted_grace(self):
        self.last_grace_at=time.perf_counter();self.detail['current_independent_reproof_passed']=True
    def commit(self):
        if self.current is not None:self.previous=self.current.copy()
