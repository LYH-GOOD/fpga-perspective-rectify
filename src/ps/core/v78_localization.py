"""Failure-only, bounded cover-texture proposals. No H admission or device IO."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class BookRescue:
    """Failure-only cover motion. Cache coordinates, never source image history."""
    def __init__(self,enabled=True,cpu_ms=70.):
        self.configure(enabled,cpu_ms)
        self.anchor_ready=None;self.next_at=0.;self.failures=0;self.frame_index=None
        self.mask=None;self.detail={};self.begin=self.cpu=0.;self.deadline=0.
        self.output=np.empty((32,2),np.float32);self.stats=np.empty(8,np.int32)
        self.cache=None;self.pending=None;self.cache_uses=0
    def configure(self,enabled,cpu_ms):
        if not isinstance(enabled,bool):raise ValueError('book_rescue must be bool')
        if isinstance(cpu_ms,bool) or not np.isfinite(cpu_ms) or not 30<=float(cpu_ms)<=120:
            raise ValueError('book_rescue_cpu_ms must be30..120')
        self.enabled=enabled;self.proof_cpu_s=float(cpu_ms)/1000.
        self.selection_cpu_s=min(.008,self.proof_cpu_s*.15);self.flow_cpu_s=.040
        self.cpu_s=self.selection_cpu_s+self.flow_cpu_s+self.proof_cpu_s
    def mark_anchor(self,ready,quad=None,channel=None):
        self.anchor_ready=float(ready);self.cache=None;self.cache_uses=0
        pending=self.pending;self.pending=None
        if pending is not None and quad is not None and channel==pending['channel']:
            shift=float(np.max(np.linalg.norm(np.asarray(quad)-pending['quad'],axis=1)))
            if shift<=1.5 and 0<=float(ready)-pending['ready']<=.35:
                self.cache=dict(pending,anchor_ready=float(ready));self.cache_uses=int(pending.get('uses',0))
    def available(self):
        return time.perf_counter()<self.deadline and time.thread_time()-self.cpu<self.cpu_s
    def normal_success(self):self.failures=0
    def prepare(self,anchor,current,quad,prediction,rim,index,ready,lost,flow_channel):
        """At most16 corner-zone cover points plus up to16 real rim points.

        The central region is excluded. Screen-like dark rims and duplicate local
        patterns are rejected conservatively; these are guards, not semantics.
        """
        if not self.enabled:return None
        now=time.perf_counter()
        if self.frame_index==index or now<self.next_at:return None
        self.frame_index=index;self.begin=now;self.cpu=time.thread_time();self.deadline=now+.30
        self.detail=dict(attempted=True,verified=False,index=int(index),policy='current_first_failure_only_cover_proposal',
            cpu_budget_s=self.cpu_s,proof_cpu_budget_s=self.proof_cpu_s,
            selection_cpu_budget_s=self.selection_cpu_s,flow_reserved_cpu_s=self.flow_cpu_s,
            wall_guard_s=.30,flow_channel=flow_channel,
            center_excluded=True,full_FB_required=True,current_four_edges_required=True,
            old_H_can_renew_from_texture=False,semantic_book_identity_proven=False)
        age=float('inf') if self.anchor_ready is None else float(ready)-self.anchor_ready
        self.detail['anchor_age_s']=age
        if lost or not 0<=age<=1.5:
            self.detail['reason']='no_recent_verified_anchor';return None
        if anchor is None or anchor.shape!=current.shape or anchor.dtype!=np.uint8:
            self.detail['reason']='anchor_plane_unavailable';return None
        q=np.asarray(quad,np.float32);p=np.asarray(prediction,np.float32)
        if q.shape!=(4,2) or p.shape!=(4,2) or not np.isfinite(q).all() or not np.isfinite(p).all():
            self.detail['reason']='invalid_cover_proposal';return None
        edge=np.roll(p,-1,axis=0)-p;length=np.linalg.norm(edge,axis=1)
        if min(length)<24:
            self.detail['reason']='cover_too_small';return None
        normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
        normal*=np.where(np.sum((p.mean(axis=0)-p)*normal,axis=1)>=0,1.,-1.)[:,None]
        xy=p[:,None,None,:]+np.linspace(.12,.88,8)[None,:,None,None]*edge[:,None,None,:]+np.array([2.,4.])[None,None,:,None]*normal[:,None,None,:]
        x=np.clip(np.rint(xy[...,0]).astype(np.int32),0,current.shape[1]-1)
        y=np.clip(np.rint(xy[...,1]).astype(np.int32),0,current.shape[0]-1)
        rim_luma=np.median(current[y,x],axis=(1,2))
        self.detail['current_inner_rim_luma']=rim_luma.tolist()
        if np.sum(rim_luma<75.)>=3:
            self.detail['reason']='dark_rim_screen_guard';return None
        cache=self.cache
        if (cache is not None and cache['anchor_ready']==self.anchor_ready and cache['channel']==flow_channel
                and 0<=float(ready)-cache['origin_ready']<=.75 and self.cache_uses<3):
            self.cache_uses+=1
            self.detail.update(selection_backend='verified_auxiliary_coordinates',selection_reused=True,
                cache_use=self.cache_uses,selection_s=time.perf_counter()-self.begin,
                selection_thread_cpu_s=time.thread_time()-self.cpu)
            return cache['points'],cache['rim_count']
        from v31_native import _LIB
        if _LIB is None or not _LIB.p11_lk_available():
            self.detail['reason']='native_cover_selector_unavailable';return None
        from v49_boundary import outer_features
        original=np.ascontiguousarray(outer_features(rim,q),np.float32).reshape(-1,2)
        if len(original)<3:
            self.detail['reason']='fewer_than_three_real_rim_anchors';return None
        anchor=np.ascontiguousarray(anchor,np.uint8);q=np.ascontiguousarray(q,np.float32)
        self.stats.fill(0)
        code=_LIB.p11_cover_features(anchor.ctypes.data,anchor.shape[1],anchor.shape[0],q.ctypes.data,
            original.ctypes.data,len(original),self.output.ctypes.data,self.stats.ctypes.data,self.selection_cpu_s)
        if code:raise ValueError('Native cover selector rejected '+str(code))
        n,rim_count,cover_count,regions,repeated,clipped,timeout,candidates=map(int,self.stats)
        self.detail.update(rim_features=rim_count,cover_features=cover_count,cover_regions=regions,
            selection_backend='cpp_corner_tensor_spatial_quota_patch_dedup',selection_reused=False,
            duplicate_patterns_rejected=repeated,low_contrast_or_clipped_rejected=clipped,
            selection_budget_hit=bool(timeout),selection_candidates=candidates,
            selection_s=time.perf_counter()-self.begin,selection_thread_cpu_s=time.thread_time()-self.cpu)
        if cover_count<8 or regions<3 or not self.available():
            self.detail['reason']='insufficient_distributed_cover_texture' if not timeout else 'selection_budget'
            return None
        return self.output[:n].reshape(-1,1,2),rim_count
    def remember_flow(self,points,forward,backward,status,reverse,error,rim_count,anchor_quad,quad,ready,channel):
        a=np.asarray(points).reshape(-1,2);z=np.asarray(forward).reshape(-1,2)
        b=np.asarray(backward).reshape(-1,2)
        H=cv2.getPerspectiveTransform(np.asarray(anchor_quad,np.float32),np.asarray(quad,np.float32))
        mapped=cv2.perspectiveTransform(a.reshape(1,-1,2),H)[0]
        good=(np.asarray(status).ravel().astype(bool)&np.asarray(reverse).ravel().astype(bool)
            &np.isfinite(z).all(axis=1)&np.isfinite(b).all(axis=1)&np.isfinite(mapped).all(axis=1)
            &(np.linalg.norm(b-a,axis=1)<.7)&(np.asarray(error).ravel()<25.)
            &(np.linalg.norm(mapped-z,axis=1)<=1.25))
        nr=int(good[:rim_count].sum());nc=int(good[rim_count:].sum())
        if nr>=3 and nc>=8:
            self.pending=dict(points=np.ascontiguousarray(z[good],np.float32).reshape(-1,1,2),rim_count=nr,
                quad=np.asarray(quad,np.float32).copy(),ready=float(ready),channel=channel,
                origin_ready=(self.cache['origin_ready'] if self.detail.get('selection_reused') else self.anchor_ready),
                uses=self.cache_uses if self.detail.get('selection_reused') else 0)
    def finish(self,success,reason=None):
        now=time.perf_counter();used=time.thread_time()-self.cpu
        self.failures=0 if success else min(3,self.failures+1)
        if not success:self.pending=None
        self.next_at=now+(.25 if success else min(1.,.25*(2**(self.failures-1))))
        self.detail.update(verified=bool(success),wall_s=now-self.begin,thread_cpu_s=used,
            cpu_budget_hit=used>=self.cpu_s,wall_guard_hit=now>=self.deadline,
            cpu_overshoot_s=max(0.,used-self.cpu_s),next_attempt_at=self.next_at,
            scope='cooperative checkpoints; a complete native FB/proof call cannot be preempted')
        if reason is not None:self.detail['reason']=str(reason)
        return dict(self.detail)


def verify_rim_flow(points,forward,backward,status,reverse,error,rim_count,anchor_quad,moved_quad):
    """Cover motion must agree with >=3 widely distributed real exterior tracks."""
    a=np.asarray(points,np.float32).reshape(-1,2)[:rim_count]
    z=np.asarray(forward,np.float32).reshape(-1,2)[:rim_count]
    b=np.asarray(backward,np.float32).reshape(-1,2)[:rim_count]
    error=np.asarray(error).reshape(-1)[:rim_count]
    good=np.asarray(status).ravel()[:rim_count].astype(bool)&np.asarray(reverse).ravel()[:rim_count].astype(bool)
    good&=np.isfinite(z).all(axis=1)&np.isfinite(b).all(axis=1)&np.isfinite(error)
    good&=(np.linalg.norm(b-a,axis=1)<.7)&(error<25.)
    H=cv2.getPerspectiveTransform(np.asarray(anchor_quad,np.float32),np.asarray(moved_quad,np.float32))
    predicted=cv2.perspectiveTransform(a.reshape(1,-1,2),H)[0]
    good&=np.isfinite(predicted).all(axis=1)&(np.linalg.norm(predicted-z,axis=1)<=1.25)
    kept=a[good];area=abs(cv2.contourArea(np.asarray(anchor_quad,np.float32)))
    coverage=abs(cv2.contourArea(cv2.convexHull(kept))) / max(area,1.) if len(kept)>=3 else 0.
    verified=bool(len(kept)>=3 and coverage>=.15)
    return dict(verified=verified,rim_good_features=int(good.sum()),rim_total=rim_count,
        rim_hull_fraction=coverage,min_rim_features=3,min_rim_hull_fraction=.15,
        max_rim_reprojection=1.25,complete_rim_forward_backward_required=True)
