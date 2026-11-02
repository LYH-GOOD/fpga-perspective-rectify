"""Live acquisition: owned CPU snapshots, current hint proof, no device access."""
from pathlib import Path
from dataclasses import dataclass
from contextvars import copy_context
import hashlib,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass
class OwnedFrame:
    image:object
    ready:float
    sequence:int
    timestamp:float
    flags:int=0
    released:bool=False
    def release(self):self.released=True  # Ordinary RAM; never a V4L2 lease.


class LiveAcquire:
    """One bounded worker, one replaceable snapshot, no MMAP or PL pointers.

    Detection failure keeps the page alive. The worker's old quad is only a
    proposal: a later snapshot must pass strict current admission before use.
    """
    def __init__(self,detection_limit,tracking_limit,factory=None):
        self.detection_limit=detection_limit;self.tracking_limit=tracking_limit;self.factory=factory
        self.condition=threading.Condition();self.latest=None;self.result=None
        self.stop=False;self.error=None;self.candidate=();self.candidate_ready=0.;self.context=copy_context()
        self.attempts=0;self.rejections=0;self.worker_cpu_s=0.;self.worker_wall_s=0.
        from v83_recovery import CandidateRetry
        self.candidate_retry=CandidateRetry()
        self.thread=threading.Thread(target=self._entry,name='p11-initial-acquisition',daemon=True)
        self.thread.start()
    def offer(self,frame):
        with self.condition:
            if self.error is not None:raise RuntimeError('Initial acquisition worker failed') from self.error
            if self.stop or self.result is not None:return
            # Latest-slot replacement is bounded to two ordinary snapshots
            # (one in use, one waiting); no camera buffer crosses threads.
            self.latest=OwnedFrame(np.array(frame.image,copy=True,order='C'),float(frame.ready),
                int(frame.sequence),float(frame.timestamp),int(frame.flags))
            self.condition.notify_all()
    def take(self):
        with self.condition:
            if self.error is not None:raise RuntimeError('Initial acquisition worker failed') from self.error
            value=self.result;self.result=None
            return value
    def _next(self,after=-1.):
        with self.condition:
            while not self.stop and (self.latest is None or self.latest.ready<=after):self.condition.wait(.1)
            if self.stop:return None
            item=self.latest;self.latest=None
            return item
    def _detect(self,frame,observer,seed=None):
        from v31_detection import detect_refined,recovery_detection_scope,recovery_candidate_scope
        from v58_budget import CpuRecoveryBudget
        from v83_recovery import candidate_retry_scope
        gray,scale=observer.get(frame.image)
        # Full search and strict hint proof have separate CPU slices; never
        # pass a stale source receipt or let search exhaust current admission.
        budget=CpuRecoveryBudget(420. if seed is None else 220.,4 if seed is None else 1,
            wall_max_s=1. if seed is None else .65)
        budget.log_detail=False
        seeds=() if seed is None else (dict(detector='live_multicolor_exterior',coarse_corners=np.asarray(seed).tolist()),)
        observation=dict(gray=gray,scale=scale,source_shape=frame.image.shape)
        if seed is None:self.candidate_retry.begin(frame.image)
        # Strict current revalidation of a successful proposal is never skipped
        # by a negative hint from a different source frame.
        success=False;started=time.perf_counter()
        try:
            with recovery_detection_scope(budget,observation),recovery_candidate_scope(seeds,seed is not None),candidate_retry_scope(self.candidate_retry if seed is None else None):
                result=detect_refined(frame.image,self.detection_limit,True,prefer_mask=True,
                    tracking_limit=self.tracking_limit)
            success=True;return result
        finally:
            if seed is None:self.candidate_retry.completed(success,time.perf_counter()-started)
    def _entry(self):
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.condition.notify_all()
    def _run(self):
        from v31_tracking import GrayObserver
        observer=GrayObserver(self.tracking_limit);pending=None;pending_ready=0.;hint_misses=0;next_log=0.
        while True:
            frame=self._next()
            if frame is None:return
            begin=time.perf_counter();cpu=time.thread_time();built=None
            try:
                self.attempts+=1
                if pending is not None and 0<=frame.ready-pending_ready<=.9 and hint_misses<2:
                    current=frame;hint_misses+=1
                    quad,info=self._detect(current,observer,pending)
                else:
                    quad,info=self._detect(frame,observer)
                    pending=np.asarray(quad,np.float32).copy();pending_ready=frame.ready;hint_misses=0
                    with self.condition:
                        self.candidate=tuple(map(tuple,pending.tolist()));self.candidate_ready=frame.ready
                    current=self._next(frame.ready)
                    if current is None:return
                    quad,info=self._detect(current,observer,pending)
                if time.perf_counter()-current.ready>.40:
                    raise ValueError('Strict current candidate completed too late; request a fresh snapshot')
                detection=(quad,info)
                built=self.factory(current,detection) if self.factory else None
                if time.perf_counter()-current.ready>.75:
                    raise ValueError('Initialization exceeded current source age; retry without publishing old H')
                report=dict(attempts=self.attempts,rejections=self.rejections,
                    source_sequence=current.sequence,current_revalidated=True,
                    elapsed_worker_cpu_s=self.worker_cpu_s+time.thread_time()-cpu,
                    startup_gate_removed=True,owned_source=True)
                with self.condition:
                    cancelled=self.stop
                    if not cancelled:
                        self.result=(current,detection,built,report);self.latest=None;self.stop=True
                        self.condition.notify_all()
                if cancelled and built is not None:built.close()
                return
            except (ValueError,cv2.error) as exc:
                if built is not None:built.close()
                self.rejections+=1
                now=time.perf_counter()
                if now>=next_log:
                    checkpoint('LIVE_ACQUIRE_RETRY',attempts=self.attempts,rejections=self.rejections,
                        reason=str(exc),preview_continues=True,hardware_access=False)
                    next_log=now+2.
            finally:
                self.worker_cpu_s+=time.thread_time()-cpu;self.worker_wall_s+=time.perf_counter()-begin
    def close(self):
        with self.condition:
            self.stop=True;self.latest=None;self.condition.notify_all()
        self.thread.join(5.)
        if self.thread.is_alive():raise TimeoutError('Initial CPU call is still retiring; keep owned workspace pinned')
        with self.condition:unused=self.result;self.result=None
        if unused is not None and unused[2] is not None:unused[2].close()


def pump_acquisition(worker,camera,display,check,generation,deadline=None,context=None,*,already_running=False,ready_after=None):
    from v79_setup import startup_meta
    began=time.perf_counter();next_offer=0.;observed=0;first_ready=None
    checkpoint('LIVE_ACQUIRE_BEGIN',preview_continues=True,strict_current_admission=True,
        exposure_stability_blocks_display=False,queue_capacity=1,hardware_access=False,
        already_running_stream=already_running,source_ready_after=ready_after)
    while True:
        check()
        if deadline is not None and time.perf_counter()>=deadline:
            raise TimeoutError('Live acquisition session deadline reached')
        ready=worker.take()
        if ready is not None:
            checkpoint('LIVE_ACQUIRE_ACCEPTED',**ready[3],preview_frames=observed,
                elapsed_s=time.perf_counter()-began)
            return ready
        try:frame=camera.take(.10)
        except TimeoutError:continue
        try:
            if ready_after is not None and float(frame.ready)<ready_after:continue
            observed+=1
            if first_ready is None:first_ready=float(frame.ready)
            now=time.perf_counter()
            if now>=next_offer:
                with worker.condition:candidate=worker.candidate;candidate_ready=worker.candidate_ready
                display.offer(None,dict(index=-2,camera_sequence=int(frame.sequence),state='SEARCHING',
                    corners=(),candidate_corners=candidate,candidate_ready_at=candidate_ready,
                    color_mode=int(camera.color_mode),verified_at=0.,
                    capture_ready_at=float(frame.ready),correction_fps=0.,ui_generation=generation(),
                    **startup_meta(context,'acquiring')),frame.image)
                # Startup does not add more than eight full preview copies/s.
                next_offer=now+.125
            # Let automatic exposure begin settling while the RAW view is
            # already visible. No brightness-stability timeout can hide it.
            if already_running or observed>=12 and float(frame.ready)-first_ready>=.35:worker.offer(frame)
        finally:frame.release()
