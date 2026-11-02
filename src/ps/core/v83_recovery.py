"""Failure-only bounded proposal scheduling; never stores H or a proof receipt."""
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib,time
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ACTIVE=ContextVar('p11_v83_candidate_retry',default=None)


def scene_probe(image):
    h,w=image.shape[:2];sy=max(1,h//12);sx=max(2,(w//16)//2*2)
    y=image[::sy,::sx] if image.ndim==2 else image[::sy,::sx,0]
    if image.ndim==3 and image.shape[2]==2:
        u=image[::sy,::sx,1];v=image[::sy,1::sx,1]
        cols=min(y.shape[1],u.shape[1],v.shape[1])
        return np.stack((y[:,:cols],u[:,:cols],v[:,:cols])).astype(np.float32)
    return np.asarray(y,np.float32)[None].copy()


def scene_changed(a,b):
    if a is None or b is None or a.shape!=b.shape:return True
    d=np.abs(a-b)
    # Include local changes, not only a frame-wide median dominated by the desk.
    return bool(float(np.mean(d))>7. or float(np.percentile(d,95))>24.)


def failure_class(detail):
    if not isinstance(detail,dict):return 'unclassified'
    reason=str(detail.get('reason',''))
    if 'budget' in reason or 'deadline' in reason:return 'compute_budget'
    agreement=detail.get('agreement') or detail.get('source_line_agreement') or {}
    if 'budget' in str(agreement.get('reason','')) or agreement.get('deadline_hit'):return 'compute_budget'
    e=detail.get('edge_refinement') or detail.get('edge_evidence') or {}
    reports=e.get('edges',())
    if any(not x.get('accepted') and x.get('highlight_fraction',0.)>.25 for x in reports):
        return 'possible_highlight_edge_loss'
    if 'clipped' in reason:return 'clipped_geometry'
    if 'all_four_original' in reason:
        failed=[r for r in reports if not r.get('accepted')]
        if any(r.get('supported',0)==0 for r in failed):return 'no_current_edge_samples_in_search_band'
        if any(r.get('retained',0)>0 and r.get('coverage',0)<.60 for r in failed):return 'insufficient_current_edge_span'
        if any(r.get('supported',0)>0 and r.get('retained',0)==0 for r in failed):return 'incoherent_current_candidate_band'
        if any(0<r.get('retained',0)<.60*r.get('profiles',64) for r in failed):return 'weak_spatial_support'
        return 'current_source_line_fit_rejected'
    if agreement.get('min_support',1.)==0:return 'missing_independent_edge'
    if (agreement.get('line_normal_difference',0.)>agreement.get('normal_limit',float('inf'))
            or 'layer' in reason or 'left_locked' in str(agreement.get('reason',''))):return 'neighbour_line_disagreement'
    if agreement.get('min_support',1.)<.8:return 'weak_spatial_support'
    return 'unproved_current_exterior'


class CandidateRetry:
    """Bounded negative hints, <=1.2s; scene/motion can invalidate immediately.

    These records can only suppress repeated computation. They never accept a
    candidate, renew a hold timer or bypass current independent edge sampling.
    """
    def __init__(self):
        self.probe=None;self.entries=[];self.failures=0;self.skipped=0;self.resets=0;self.classes={}
        self.batch=[];self.batch_started=0.;self.batch_skipped=0;self.cycle_wall_s=.25
        self.expired_rechecks=0
    def begin(self,image):
        self.batch=[];self.batch_started=time.perf_counter()
        probe=scene_probe(image)
        if scene_changed(probe,self.probe):
            self.entries.clear();self.failures=0;self.probe=probe;self.resets+=1
        return probe
    def _entry(self,quad):
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return None
        center=q.mean(axis=0)
        for entry in reversed(self.entries):
            delta=center-entry['center']
            if float(delta@delta)>36.:continue
            d=entry['cycles']-q
            if float(np.min(np.max(np.sum(d*d,axis=2),axis=1)))<=16.:return entry
        return None
    def allow(self,quad):
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return True
        for old in self.batch:
            d=old-q
            if float(np.min(np.max(np.sum(d*d,axis=2),axis=1)))<=4.:
                self.batch_skipped+=1;return False
        self.batch.append(np.stack([np.roll(v,k,axis=0) for v in (q,q[::-1]) for k in range(4)]))
        if len(self.batch)>32:self.batch.pop(0)
        entry=self._entry(quad)
        allowed=entry is None or time.perf_counter()>=entry['until']
        if not allowed:self.skipped+=1
        elif entry is not None:self.expired_rechecks+=1
        return allowed
    def reject(self,quad,detail):
        kind=failure_class(detail);self.classes[kind]=self.classes.get(kind,0)+1
        # A compute deadline is not evidence that this boundary is wrong.
        if kind=='compute_budget':return
        entry=self._entry(quad);count=1 if entry is None else entry['count']+1
        # A fixed150ms hint expired before the next ~0.8-1s search reached
        # admission. Cover one observed cycle, then force fresh remeasurement.
        elapsed=max(0.,time.perf_counter()-self.batch_started)
        delay=min(1.20,max(.35,self.cycle_wall_s+.20,elapsed+.20)*(1.+.20*min(count-1,2)))
        q=np.asarray(quad,np.float32).copy()
        value=dict(quad=q,center=q.mean(axis=0),cycles=np.stack([np.roll(v,k,axis=0) for v in (q,q[::-1]) for k in range(4)]),
            count=count,kind=kind,until=time.perf_counter()+delay)
        if entry is not None:self.entries=[x for x in self.entries if x is not entry]
        self.entries.append(value)
        if len(self.entries)>24:self.entries.pop(0)
    def completed(self,valid,wall_s=None):
        elapsed=max(0.,time.perf_counter()-self.batch_started) if wall_s is None else max(0.,float(wall_s))
        self.cycle_wall_s=.5*self.cycle_wall_s+.5*min(1.,elapsed)
        self.failures=0 if valid else min(4,self.failures+1)
        if valid:self.entries.clear()
    def delay(self):return .10 if not self.failures else min(.60,.15*2**min(self.failures-1,2))
    def summary(self):
        return dict(negative_hints=len(self.entries),repeated_candidates_skipped=self.skipped,
            same_batch_candidates_skipped=self.batch_skipped,expired_candidate_rechecks=self.expired_rechecks,
            scene_resets=self.resets,failure_classes=dict(self.classes),maximum_negative_hint_s=1.20,
            observed_cycle_wall_s=self.cycle_wall_s,cached_current_proof=False,old_H_lifetime_changed=False)


@contextmanager
def candidate_retry_scope(policy):
    token=_ACTIVE.set(policy)
    try:yield
    finally:_ACTIVE.reset(token)


def active_retry():return _ACTIVE.get()
