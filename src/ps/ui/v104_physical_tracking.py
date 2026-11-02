"""Physical boundary tracking with two-sided contrast and bounded recovery."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v105_native import EdgeWorkspace
from v105_reference import measure_python
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def measure(gray,q,radius=4.,reference=None,workspace=None):
    workspace=workspace or EdgeWorkspace()
    result,detail=(workspace.measure(gray,q,radius,reference) if workspace.lib is not None
                   else measure_python(gray,q,radius,reference))
    from v31_tracking import _valid
    if not _valid(result,gray.shape,q,'legacy'):raise ValueError('physical_quad_invalid')
    return result,detail

class PhysicalTracker:
    physical=True
    def __init__(self,frame,quad,limit=320,authority='ai_physical',entry_radius=8.):
        from v31_tracking import GrayObserver
        self.observer=GrayObserver(limit);self.closed=False
        try:
            gray,scale=self.observer.get(frame.image)
            self._initialize(gray,scale,quad,float(frame.ready),authority,entry_radius)
        except BaseException:self.close();raise
    @classmethod
    def from_observation(cls,gray,scale,quad,ready,limit=320,authority='manual'):
        from v31_tracking import GrayObserver
        obj=cls.__new__(cls);obj.observer=GrayObserver(limit);obj.closed=False
        try:obj._initialize(gray,scale,quad,ready,authority,3.)
        except BaseException:obj.close();raise
        return obj
    def _initialize(self,gray,scale,quad,ready,authority,radius):
        self.workspace=EdgeWorkspace();self.scale=np.asarray(scale).copy();self.previous_ready=ready
        self.authority=authority
        self.kind='PHYSICAL_EDGE_FAST';self.fixed=False;self.points=None;self.failures=0
        self.next_search=0.;self.search_stage=0;self.pending=None
        self.q=np.asarray(quad,np.float32).copy()
        seed=(self.q+.5)/self.scale-.5
        try:found,detail=measure(gray,seed,radius,workspace=self.workspace)
        except ValueError:
            # Only on ambiguous entry: compare the inside of the selected body
            # to candidate edges. An inner-screen edge often has reversed sign
            # but also a different inside appearance. Keep all four proof gates.
            edge=np.roll(seed,-1,axis=0)-seed;length=np.linalg.norm(edge,axis=1)
            if np.any(length<24):raise
            normal=np.stack((edge[:,1],-edge[:,0]),axis=1)/length[:,None]
            along=np.linspace(.10,.90,24,dtype=np.float32)
            base=seed[:,None,:]+along[None,:,None]*edge[:,None,:]
            points=base[:,:,None,:]-np.array([1.,2.,3.],np.float32)[None,None,:,None]*normal[:,None,None,:]
            points=points.reshape(96,3,2).astype(np.float32)
            inside=cv2.remap(gray,points[...,0],points[...,1],cv2.INTER_LINEAR)
            reference=np.median(inside,axis=1).astype(np.float32)
            try:found,detail=measure(gray,seed,radius,reference,self.workspace)
            except ValueError:
                # A slightly inset seed can straddle screen text and bezel.
                # One bounded outward hypothesis only at entry; no scene scan.
                expanded=seed.mean(0)+(seed-seed.mean(0))*1.04
                found,detail=measure(gray,expanded,radius,workspace=self.workspace)
                if np.max(np.linalg.norm((found-seed)*self.scale,axis=1))>20:
                    raise ValueError('physical_entry_displacement_too_large')
                detail['entry_outward_hypothesis']=True
            detail['entry_body_disambiguation']=True
        self.reference=detail.pop('body');self.raw_q=(found+.5)*self.scale-.5
        self.q=self.raw_q.copy();self.velocity=np.zeros((4,2),np.float32)
        checkpoint('AI_PHYSICAL_TRACKER_READY',authority=authority,source_sha256=_SOURCE_SHA256,
            feature_region='physical boundary with measured inner appearance; either exterior polarity',
            per_frame_model=False,per_frame_lk=False,profile_samples=96,edge_detail=detail,
            recovery_max_hz=5,automatic_scene_switch=False)
    def update(self,frame,radius=4.):
        began=time.perf_counter();cpu=time.thread_time();stamp=float(frame.ready)
        recovering=self.failures>0;result=None;detail={}
        try:
            if recovering and stamp<self.next_search:
                detail=dict(manual_motion_proved=False,reason='physical_retry_pending')
                return None,self._detail(detail,began,cpu)
            gray,scale=self.observer.get(frame.image)
            if not np.array_equal(scale,self.scale):raise ValueError('physical_source_layout_changed')
            gap=stamp-self.previous_ready
            if gap<0:raise ValueError('physical_capture_gap')
            if gap>.75 and not recovering and self.authority!='ai_bridge':
                recovering=True;self.failures=1
            self.previous_ready=stamp
            prediction=self.raw_q+np.clip(self.velocity,-6.,6.)
            if recovering:
                prediction=self.pending if self.pending is not None else self.raw_q
                radius=4. if self.pending is not None else (8.,16.,32.,40.)[min(self.search_stage,3)]
                self.search_stage+=int(self.pending is None);self.next_search=stamp+.2
            found,edges=measure(gray,(prediction+.5)/scale-.5,radius,self.reference,self.workspace)
            body=edges.pop('body');measured=(found+.5)*scale-.5
            oldarea=abs(cv2.contourArea(self.raw_q.astype(np.float32)))
            ratio=abs(cv2.contourArea(measured.astype(np.float32)))/max(oldarea,1.)
            oldlen=np.linalg.norm(np.roll(self.raw_q,-1,axis=0)-self.raw_q,axis=1)
            newlen=np.linalg.norm(np.roll(measured,-1,axis=0)-measured,axis=1)
            if not .82<ratio<1.22 or np.any(newlen/oldlen<.86) or np.any(newlen/oldlen>1.18):
                raise ValueError('physical_target_shape_changed')
            delta=float(np.max(np.linalg.norm(measured-self.raw_q,axis=1)))
            if delta>(110. if recovering else 32.):raise ValueError('physical_motion_outside_window')
            if recovering and self.pending is None:
                self.pending=measured.copy();self.next_search=stamp
                detail=dict(manual_motion_proved=False,reason='physical_recovery_confirmation',search_radius=radius)
                return None,self._detail(detail,began,cpu)
            if recovering and np.max(np.linalg.norm(measured-self.pending,axis=1))>16:
                raise ValueError('physical_recovery_unstable')
            shift=float(np.max(np.linalg.norm(measured-self.q,axis=1)))
            candidate=self.q.copy() if shift<=.65 else measured if shift>=3. else self.q+.8*(measured-self.q)
            from v82_interaction import selected_quad
            selected_quad(candidate,frame.image.shape)
            self.velocity=np.zeros((4,2),np.float32) if recovering else .4*self.velocity+.6*(measured-self.raw_q)
            self.raw_q=measured;self.q=np.asarray(candidate,np.float32);self.failures=0
            self.pending=None;self.search_stage=0;self.next_search=0.
            # Very slow bounded update follows exposure; the original body cannot
            # be replaced by an unrelated high-contrast screen edge in one frame.
            self.reference+=.02*np.clip(body-self.reference,-8.,8.)
            if recovering:checkpoint('PHYSICAL_SAME_TARGET_RECOVERED',automatic_switch=False,source_shift=delta)
            detail=dict(manual_motion_proved=True,current_outer_edge_evidence=True,physical_corner_shift=shift,
                physical_static_deadband=shift<=.65,physical_edges=edges,recovered_same_target=recovering)
            result=self.q.copy()
        except (ValueError,cv2.error) as exc:
            self.failures+=1;self.pending=None;self.velocity.fill(0.)
            detail=dict(manual_motion_proved=False,current_outer_edge_evidence=False,reason=str(exc))
            if self.failures in (1,3) or self.failures%20==0:
                checkpoint('AI_PHYSICAL_EDGE_REJECTED',reason=str(exc),consecutive=self.failures,
                    old_coordinates_not_renewed=True,recovery_radius=(8,16,32,40)[min(self.search_stage,3)])
        return result,self._detail(detail,began,cpu)
    def _detail(self,detail,began,cpu):
        detail.update(manual_tracking=self.kind,physical_body=True,video_features=False,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu)
        return detail
    def close(self):
        if getattr(self,'closed',True):return
        self.closed=True;transaction=getattr(self.observer,'transaction',None);close=getattr(transaction,'close',None)
        if callable(close):close()
        self.observer=None

def create_tracker(frame,quad,limit=320,authority='ai'):
    try:return PhysicalTracker(frame,quad,limit,authority)
    except (ValueError,cv2.error) as exc:
        from v105_manual_tracking import PersistentManualTracker
        checkpoint('AI_TRACKER_FALLBACK',reason=str(exc),tracker='FB_TRACK',automatic_switch=False)
        return PersistentManualTracker(frame,quad,limit,authority)
