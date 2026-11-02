"""Two layouts with time-bounded evidence and transactional H commit."""
from pathlib import Path
from dataclasses import dataclass
import hashlib,time
import numpy as np
from p11_contract import RELEASE_ID
from v8_geometry import aspect_ratio
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

@dataclass(frozen=True)
class OrientationProposal:
    quad:object
    size:object
    detail:dict
    state:dict
    base_revision:int

class DualOrientation:
    __slots__=('__dict__','_draft')
    def __init__(self,mode,size,confirm_frames=2):
        if mode not in ('fixed','auto_two'):raise ValueError('output_orientation must be fixed/auto_two')
        if isinstance(confirm_frames,bool) or not isinstance(confirm_frames,int) or not 2<=confirm_frames<=8:
            raise ValueError('orientation_confirm_frames must be2..8')
        if mode=='auto_two':
            if size is None or len(size)!=2:raise ValueError('auto_two requires output_size=(short,long)')
            if any(isinstance(v,bool) or not isinstance(v,(int,np.integer)) for v in size):raise ValueError('Dual output dimensions must be integers')
            a,b=sorted(map(int,size))
            if not 16<=a<b<=1280:raise ValueError('Dual output requires16<=short<long<=1280')
            self.sizes={'portrait':(a,b),'landscape':(b,a)}
        else:self.sizes={}
        self.mode=mode;self.confirm_frames=confirm_frames;self.orientation=None
        self.long_family=1;self.shift=0;self.generation=0;self.metric={}
        self.pending=None;self.count=0;self.pending_at=0.;self.last_vote_at=0.
        self.flip_count=0;self.flip_at=0.;self.last_switch_at=-1e9
        self.evidence_window_s=.5;self.cooldown_s=.2;self.revision=0

    def lost(self,timestamp=None):
        # HELD/LOST are not votes. Expire by elapsed time, not processed index.
        now=time.perf_counter() if timestamp is None else float(timestamp)
        if now-self.last_vote_at>self.evidence_window_s:self.pending=None;self.count=0
        if now-self.flip_at>self.evidence_window_s:self.flip_count=0

    def propose(self,q,image_shape,index,new_target=False,confidence=1.,timestamp=None,strong_verified=False):
        draft=getattr(self,'_draft',None)
        if draft is None:
            draft=object.__new__(DualOrientation);self._draft=draft
        draft.__dict__.clear();draft.__dict__.update(self.__dict__)
        quad,size,detail=draft._observe(q,image_shape,index,new_target,confidence,timestamp,strong_verified)
        return OrientationProposal(quad,size,detail,dict(draft.__dict__),self.revision)

    def commit(self,proposal):
        if proposal.base_revision!=self.revision:raise ValueError('Stale orientation proposal')
        self.__dict__.update(proposal.state);self.revision+=1
        return dict(proposal.detail,orientation_committed=True,layout_generation=self.generation)

    def observe(self,q,image_shape,index,new_target=False,confidence=1.,**kwargs):
        p=self.propose(q,image_shape,index,new_target,confidence,**kwargs)
        return p.quad,p.size,self.commit(p)

    def _observe(self,q,image_shape,index,new_target,confidence,timestamp,strong_verified):
        began=time.perf_counter();now=began if timestamp is None else float(timestamp)
        q=np.asarray(q,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Orientation requires finite current four corners')
        if self.mode=='fixed':return q,None,dict(policy='fixed',changed=False,layout_generation=0,orientation_s=time.perf_counter()-began)
        first=self.orientation is None;old=self.orientation;old_shift=self.shift
        reinitialized=False;family=self.long_family
        if first or new_target:
            ratio,metric=aspect_ratio(q,image_shape)
            # Ambiguous aspect never vetoes orientation. Do not rename an
            # established physical edge family on a near-equal estimate.
            if first or ratio<.85 or ratio>1.15:family=0 if ratio>1 else 1
            self.metric=metric
            if new_target:self.pending=None;self.count=0;self.flip_count=0
        edge=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edge,axis=1)
        if np.min(length)<4:raise ValueError('Degenerate orientation edges')
        unit=edge/length[:,None];ids=(family,family+2)
        axis_ratio=float(sum(abs(unit[i,0]) for i in ids))/max(float(sum(abs(unit[i,1]) for i in ids)),1e-6)
        angle=float(np.degrees(np.arctan2(1.,axis_ratio)))
        desired='landscape' if axis_ratio>1.15 else 'portrait' if axis_ratio<1/1.15 else None
        changed=False;reorder=False;decision='retain_in_angle_deadband';switch_requested_at=None
        if first:
            self.orientation=desired or ('landscape' if axis_ratio>1 else 'portrait')
            self.long_family=family;reorder=True;decision='initial_current_layout'
        else:
            self.lost(now)
            target=desired or self.orientation;family_changed=family!=self.long_family
            proposal=(target,family)
            if confidence<.75:decision='weak_current_direction_no_vote'
            elif target==self.orientation and not family_changed:
                self.pending=None;self.count=0;decision='current_layout_confirmed'
            else:
                if self.pending!=proposal or now-self.last_vote_at>self.evidence_window_s:
                    self.pending=proposal;self.count=1;self.pending_at=now
                else:self.count+=1
                self.last_vote_at=now
                strong=bool(strong_verified and confidence>=.90 and desired is not None
                    and (axis_ratio>=1.7 or axis_ratio<=1/1.7))
                enough=strong or self.count>=self.confirm_frames
                if enough and (strong or now-self.last_switch_at>=self.cooldown_s):
                    switch_requested_at=self.pending_at
                    self.orientation=target;self.long_family=family
                    changed=target!=old;reinitialized=family_changed;reorder=changed or family_changed
                    self.pending=None;self.count=0;self.last_switch_at=now
                    decision='strong_current_proof_fast_switch' if strong else 'time_window_votes_confirmed'
                else:decision='pending_current_direction'
        # Half-turn geometry is independent of semantic text/video direction.
        if not first and not reorder:
            top=float((q[self.shift,1]+q[(self.shift+1)%4,1])*.5)
            bottom=float((q[(self.shift+2)%4,1]+q[(self.shift+3)%4,1])*.5)
            if top-bottom>.10*float(np.min(length)) and confidence>=.75:
                if now-self.flip_at>self.evidence_window_s:self.flip_count=0
                self.flip_count+=1;self.flip_at=now
                strong_flip=bool(strong_verified and confidence>=.90 and top-bottom>.35*float(np.min(length)))
                if (strong_flip or self.flip_count>=self.confirm_frames) and (strong_flip or now-self.last_switch_at>=self.cooldown_s):
                    reorder=True;self.flip_count=0;self.last_switch_at=now
                    decision='current_half_turn_reorder';switch_requested_at=now
            else:self.flip_count=0
        if first or reorder:
            top_family=self.long_family if self.orientation=='landscape' else 1-self.long_family
            self.shift=min((top_family,top_family+2),key=lambda i:float((q[i,1]+q[(i+1)%4,1])*.5))
            self.generation+=1
        result=np.ascontiguousarray(np.roll(q,-self.shift,axis=0),np.float32)
        detail=dict(policy='auto_two_time_window',orientation=self.orientation,changed=changed,
            mapping_reoriented=bool(not first and self.shift!=old_shift),reinitialized=reinitialized,
            target_change_proposed=bool(new_target),output_size=list(self.sizes[self.orientation]),
            output_corner_shift=self.shift,layout_generation=self.generation,long_edge_family=self.long_family,
            long_axis_ratio=axis_ratio,long_axis_angle_degrees=angle,square_switch_veto=False,
            pending_orientation=None if self.pending is None else self.pending[0],confirmation_count=self.count,
            required_confirmations=self.confirm_frames,evidence_window_s=self.evidence_window_s,
            minimum_switch_interval_s=self.cooldown_s,decision=decision,orientation_committed=False,
            switch_requested_at=switch_requested_at,switch_decided_at=now if reorder and not first else None,
            aspect_method=self.metric.get('method'),aspect_confidence=self.metric.get('confidence'),
            orientation_s=time.perf_counter()-began,semantic_text_orientation=False)
        return result,self.sizes[self.orientation],detail
