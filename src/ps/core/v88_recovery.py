"""Latest owned-frame recovery using the unchanged V74 admission and native kernels."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v79_acquire import LiveAcquire
from v58_budget import CpuRecoveryBudget,compact_recovery_summary
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class RecoveryCancelled(Exception):pass


class SliceBudget(CpuRecoveryBudget):
    """Cooperative CPU slice; continue full-search candidate ordinal across requests."""
    def __init__(self,worker,milliseconds,candidates,skip=None):
        super().__init__(milliseconds,candidates,wall_max_s=1.2)
        self.worker=worker;self.skip=dict(skip or {});self.visited={};self.log_detail=False
    def check(self,stage,finish_gate=False):
        with self.worker.condition:stopped=self.worker.stop
        if stopped:raise RecoveryCancelled()
        super().check(stage,finish_gate)
    def claim(self,label,coarse):
        position=self.visited.get(label,0)+1;self.visited[label]=position
        if position<=self.skip.get(label,0):
            self.check('v88_candidate_cursor_skip')
            # V74 try_admit catches a candidate ValueError and continues the
            # original stream. No previous evidence or H is accepted here.
            raise ValueError('V88 earlier candidate ordinal already attempted in this scene cycle')
        super().claim(label,coarse)


def detect_slice(worker,frame,observer,hint=None,cursor=None):
    from v31_detection import detect_refined,recovery_detection_scope,recovery_candidate_scope
    worker.last_budget=None
    gray,scale=observer.get(frame.image)
    budget=SliceBudget(worker,worker.budget_ms,1 if hint is not None else 2,None if hint is not None else cursor)
    observation=dict(gray=gray,scale=scale,source_shape=frame.image.shape)
    seeds=() if hint is None else (dict(detector='multicolor_exterior',coarse_corners=np.asarray(hint).tolist()),)
    try:
        with recovery_detection_scope(budget,observation),recovery_candidate_scope(seeds,hint is not None):
            return detect_refined(frame.image,worker.detection_limit,True,prefer_mask=True,
                tracking_limit=worker.tracking_limit),budget
    finally:worker.last_budget=budget


def freshen_source(worker,source,detection):
    """Only old initial video sources get a latest-frame V74 hint reproof.

    Caller keeps ownership of source on failure. A returned replacement is
    separately owned; caller releases the original after successful transfer.
    """
    from v87_v74_tracking import GrayObserver
    if time.perf_counter()-source.ready<=.55:return source,detection,dict(refreshed=False)
    observer=GrayObserver(worker.tracking_limit);candidate=source;current=detection
    original_sequence=int(source.sequence)
    # Initial V74 search stays unrestricted. Only its old result is transported;
    # the strict current source64/independent24 admission is unchanged.
    worker.budget_ms=420.;worker.last_budget=None
    try:
        for _ in range(2):
            latest=worker._take_owned(3.)
            try:current,_=detect_slice(worker,latest,observer,current[0])
            except BaseException:latest.release();raise
            if candidate is not source:candidate.release()
            candidate=latest
            if time.perf_counter()-candidate.ready<=.55:
                return candidate,current,dict(refreshed=True,original_sequence=original_sequence,
                    handoff_sequence=int(candidate.sequence),same_current_V74_admission=True)
        raise ValueError('V88 current handoff still too old; keep live preview and retry')
    except BaseException:
        if candidate is not source:candidate.release()
        raise


class V74Reacquire(LiveAcquire):
    """One replaceable ordinary-RAM snapshot; no camera leases or PL in worker."""
    def __init__(self,detection_limit,tracking_limit,factory=None,quad=None,budget_ms=420.):
        self.hint=None if quad is None else np.asarray(quad,np.float32).copy()
        self.budget_ms=float(budget_ms);self.last_budget=None;self.unpublished=None
        super().__init__(detection_limit,tracking_limit,factory)
    def _run(self):
        from v87_v74_tracking import GrayObserver
        observer=GrayObserver(self.tracking_limit);local_tries=0;cursor={};probe=None;next_log=0.
        while True:
            frame=self._next()
            if frame is None:return
            built=None;started=time.perf_counter();cpu=time.thread_time();phase='local';transferred=False
            try:
                raw=frame.image
                scene=raw[::max(1,raw.shape[0]//12),::max(2,raw.shape[1]//16//2*2),0].astype(np.float32)
                scene-=float(scene.mean())
                changed=probe is not None and (probe.shape!=scene.shape or float(np.median(np.abs(scene-probe)))>12.)
                if changed:cursor={};local_tries=2
                probe=scene
                phase='local' if self.hint is not None and local_tries<2 else 'full_slice'
                if phase=='local':local_tries+=1
                detection,budget=detect_slice(self,frame,observer,self.hint if phase=='local' else None,cursor)
                self.hint=np.asarray(detection[0],np.float32).copy()
                with self.condition:
                    self.candidate=tuple(map(tuple,self.hint.tolist()));self.candidate_ready=float(frame.ready)
                    if self.stop:raise RecoveryCancelled()
                if time.perf_counter()-frame.ready>.55:
                    local_tries=0
                    raise ValueError('V88 recovered source needs latest-frame local continuation')
                built=self.factory(frame,detection) if self.factory else None
                self.unpublished=built
                if time.perf_counter()-frame.ready>.70:
                    local_tries=0
                    raise ValueError('V88 recovery initialization exceeded fresh handoff age')
                report=dict(attempts=self.attempts,rejections=self.rejections,source_sequence=int(frame.sequence),
                    source_age_s=max(0.,time.perf_counter()-frame.ready),owned_source=True,
                    current_revalidated=True,initial_source_verified=True,recovery_phase=phase,
                    v88_local_recovery=phase=='local',candidate_cursor=dict(cursor),
                    admission_policy='unchanged V74 source64 plus independent24',
                    current_frame_validation_before_output='complete_FB_or_V74_current_exterior',
                    elapsed_worker_cpu_s=self.worker_cpu_s+time.thread_time()-cpu)
                with self.condition:
                    if self.stop:raise RecoveryCancelled()
                    self.result=(frame,detection,built,report);self.latest=None;self.stop=True
                    self.unpublished=None;self.condition.notify_all();transferred=True
                return
            except RecoveryCancelled:return
            except (ValueError,cv2.error) as exc:
                self.rejections+=1
                budget=self.last_budget
                if phase=='full_slice':
                    visited={} if budget is None else dict(budget.visited)
                    advanced=any(v>cursor.get(k,0) for k,v in visited.items())
                    progress=dict(cursor)
                    for label,position in visited.items():progress[label]=max(position,progress.get(label,0))
                    cursor=progress if advanced and sum(progress.values())<12 else {}
                    local_tries=0
                if time.perf_counter()>=next_log:
                    checkpoint('V88_RECOVERY_SLICE',phase=phase,reason=str(exc),attempts=self.attempts,
                        rejections=self.rejections,candidate_cursor=cursor,live_preview_continues=True,
                        budget=None if budget is None else compact_recovery_summary(budget.summary()),
                        hard_preemption=False,hardware_access=False)
                    next_log=time.perf_counter()+2.
            finally:
                self.attempts+=1
                if not transferred:
                    # Preserve a frontend on this worker if its close raises;
                    # outer cleanup must retain the worker until retirement.
                    if built is not None:built.close();self.unpublished=None
                    frame.release()
                self.worker_cpu_s+=time.thread_time()-cpu;self.worker_wall_s+=time.perf_counter()-started
    def close(self):
        super().close()
        if self.unpublished is not None:self.unpublished.close();self.unpublished=None
