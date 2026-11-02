"""Immediate recovery, with no change to steady automatic/manual tracking.

The producer alone creates/retires CPU frontends or sends AI requests. A
watchdog only flags deadlines. True manual entry never uses this controller.
"""
from pathlib import Path
from collections import deque
import hashlib,threading,time,traceback
import cv2
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v110_unified import HybridFrontend as UnifiedFrontend,CurrentRate
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class AIBudget:
    """Failed/unstable requests count; only the owner's stable request refunds."""
    def __init__(self,maximum=3,window=60.):
        self.maximum=maximum;self.window=window;self.times=deque();self.tickets=deque();self.lock=threading.Lock()
    def _due(self,now):
        while self.times and self.times[0]<=now-self.window:self.times.popleft();self.tickets.popleft()
        return self.times[0]+self.window if len(self.times)>=self.maximum else now
    def due(self,now):
        with self.lock:return self._due(now)
    def reserve(self,now,ticket=None):
        with self.lock:
            if self._due(now)>now:return False
            if ticket is not None and any(t is ticket for t in self.tickets):raise ValueError('AI budget ticket already reserved')
            self.times.append(now);self.tickets.append(ticket);return True
    def refund(self,ticket,now):
        if ticket is None:return False
        with self.lock:
            self._due(now)
            for i,owner in enumerate(self.tickets):
                if owner is ticket:
                    del self.times[i];del self.tickets[i];return True
            return False
_AUTOMATIC_AI_BUDGET=AIBudget()

class HybridFrontend(UnifiedFrontend):
    AUTO_SEARCH_S=1.5
    AUTO_CANDIDATE_EXTRA_S=1.3
    AUTO_TOTAL_CAP_S=2.8
    LOSS_S=1.2
    def __init__(self,*args,budget=None,ai_first=False,**kwargs):
        self.ai_budget=budget if budget is not None else _AUTOMATIC_AI_BUDGET
        self.ai_budget_ticket=None;self.ai_budget_epoch=None
        self.recovery_mode=False;self.recovery_round=0
        self.auto_budget_waiting=False;self.ai_wait_due=None;self.ai_wait_candidate_version=None
        self.last_effective_at=None;self.stable_since=None;self.last_failure='';self.recovery_from_ai=False
        self.search_epoch_started=None
        self._skip_initial_auto=bool(ai_first);self.explicit_first_request=bool(ai_first)
        self.ai_mode_locked=bool(ai_first);self.ai_target_acquired=False
        super().__init__(*args,**kwargs)
        self._sync_ai_mode()
        checkpoint('RECOVERY_READY',loss_s=self.LOSS_S,auto_search_s=self.AUTO_SEARCH_S,
            auto_candidate_extra_s=self.AUTO_CANDIDATE_EXTRA_S,auto_total_cap_s=self.AUTO_TOTAL_CAP_S,
            fixed_recovery_cooldown=False,automatic_ai_per_minute=3,
            budget_refund='only own AI request after existing3s stable>=4 output proof',
            true_empty_return='AUTO first after acquired-target loss; bounded AI fallback',
            ai_mode_locked=self.ai_mode_locked,ai_lock_release='acquired target lost')
    def _sync_ai_mode(self):
        ticket=getattr(self.context,'ticket',None)
        if ticket is not None:ticket.ai_mode_locked=self.ai_mode_locked
    def _release_ai_mode(self,reason):
        if not self.ai_mode_locked:return
        self.ai_mode_locked=False;self.ai_target_acquired=False;self._sync_ai_mode()
        checkpoint('AI_MODE_LOCK_RELEASED',reason=reason,epoch=self.epoch,next_admission='AUTO first')
    def _new_acquirer(self,recovery,target_selection):
        if self._skip_initial_auto:
            self._skip_initial_auto=False;self.origin='AI';self.phase='AI_LOADING';self.monitor.suspend()
            self.initial['automatic_first']=False
            return
        super()._new_acquirer(recovery,target_selection)
    def _acquire_phase(self,phase):
        if phase=='SEARCHING' and getattr(self,'camera',None) is not None:self.camera._p11_stream_stabilized=True
        with self.lock:
            now=self.clock();previous=self.auto_stage;self.auto_stage=phase
            if phase=='SEARCHING':
                if self.search_at is None:self.search_at=now
                self.candidate_at=None
            elif phase=='CANDIDATE' and previous!='CANDIDATE':self.candidate_at=now
        checkpoint('UNIFIED_AUTO_PHASE',phase=phase,search_at=self.search_at,candidate_at=self.candidate_at,
            search_s=self.AUTO_SEARCH_S,candidate_extra_s=self.AUTO_CANDIDATE_EXTRA_S,total_cap_s=self.AUTO_TOTAL_CAP_S)
        wake=getattr(self,'watch_wake',None)
        if wake is not None:wake.set()
    def _auto_search_expired(self,now):
        start=self.search_at
        if start is None:
            # Warm recovery already has a live camera. Cold exposure/stability
            # still uses its existing separate startup guard.
            if not self.recovery_mode:return False
            start=self.search_epoch_started
            if start is None:return False
        if now<start+self.AUTO_SEARCH_S:return False
        candidate=(self.auto_stage in ('CANDIDATE','READY') and self.candidate_at is not None
            and self.candidate_at<=start+self.AUTO_SEARCH_S)
        return not candidate or now>=start+self.AUTO_TOTAL_CAP_S
    def _move(self,reason,phase,origin):
        self.selection_proof=None;self.selection_failed=None
        if reason in ('target_absent','target_returned','recover_tracking_lost'):
            self.target_selection=None;self.selection_wait_absent=False
        with self.lock:
            self.transitioning=True
            # Losing/changing the target never refunds a failed/unstable attempt.
            self.ai_budget_ticket=None;self.ai_budget_epoch=None
        preview=getattr(self.camera,'live_preview',None)
        if preview is not None:preview.reset_geometry(self.epoch+1,reason)
        self.monitor.suspend();self._retire_active();self._release_request()
        with self.lock:
            self.epoch+=1;self.requested=None;self.low_since=None;self.rate=CurrentRate();self.valid_fps=0.
            self.awaiting_first_output=False;self.trigger=reason;self.phase=phase;self.origin=origin
            self.last_effective_at=None;self.active_started=None;self.stable_since=None
            self.auto_budget_waiting=False;self.ai_wait_due=None;self.ai_wait_candidate_version=None;self.transitioning=False
        checkpoint('RECOVERY_TRANSITION',reason=reason,phase=phase,origin=origin,epoch=self.epoch,
            recovery_round=self.recovery_round,old_workers_retired=True,camera_reopened=False)
    def _transition(self,reason,empty=False):
        # Called by the retained producer boundary for confirmed absence/return.
        if empty:
            if self.ai_target_acquired:self._release_ai_mode(reason)
            self.recovery_mode=False;self._move(reason,'EMPTY_WAIT',self.origin)
            checkpoint('UNIFIED_EMPTY_WAIT',reason=reason,epoch=self.epoch)
        else:
            self.recovery_round=0
            self.ai_attempted=False;self.recovery_from_ai=False
            if self.ai_mode_locked:self._begin_ai(reason)
            else:self._start_auto(reason)
    def _presence(self,frame):
        # Auxiliary low-rate scene probes must not tear down a valid tracker.
        # Scope the guard to numerical/probe failures; camera/DMA/ownership
        # failures remain fatal and follow the original safe cleanup path.
        try:event=self.cycle.observe(frame.image,int(frame.sequence),self.clock())
        except (TypeError,ValueError,ArithmeticError,cv2.error) as exc:
            if not hasattr(self.cycle,'reset_candidate'):raise
            self.cycle.reset_candidate()
            self.cycle.pending=None;self.cycle.positive_count=self.cycle.negative_count=0
            self.cycle.positive_since=self.cycle.negative_since=None
            checkpoint('RECOVERY_PROBE_RESET',exception_type=type(exc).__name__,exception=str(exc),
                traceback=traceback.format_exc(),epoch=self.epoch,tracking_preserved=True)
            return None
        if self.selection_wait_absent:
            if event!='ABSENT':return None
            self.selection_wait_absent=False
        if event=='ABSENT':
            self.requested='target_absent';checkpoint('UNIFIED_TARGET_ABSENT',epoch=self.epoch,confirmed=True)
        elif event=='RETURNED':
            self.ai_attempted=False;self.requested='target_returned'
            checkpoint('UNIFIED_TARGET_RETURNED',epoch=self.epoch,next_admission='AI locked' if self.ai_mode_locked else 'AUTO first')
        return event
    def _start_auto(self,reason):
        if self.ai_mode_locked:
            self._await_ai(reason);return
        # No round-limit pause. Keep an existing live search worker, especially
        # while an AI quota is unavailable; never rebuild it on every tick.
        if self.acquirer is not None:
            self.requested=None;return
        self.recovery_round+=1;self.recovery_mode=True
        self._move(reason,'AUTO_RECOVER','AUTO')
        self.started=self.clock();self.search_epoch_started=self.started
        self.search_at=None;self.candidate_at=None;self.auto_stage='SEARCHING'
        # A live capture stream already exists: do not repeat exposure startup.
        self._new_acquirer(True,None)
        checkpoint('RECOVERY_AUTO_BEGIN',reason=reason,epoch=self.epoch,recovery_round=self.recovery_round,
            search_s=self.AUTO_SEARCH_S,candidate_extra_s=self.AUTO_CANDIDATE_EXTRA_S,
            total_cap_s=self.AUTO_TOTAL_CAP_S,already_running_stream=True)
    def _await_ai(self,reason):
        """AI-only entry waits for new evidence or its actual quota deadline.

        There is no fixed recovery timer and no request on every camera frame.
        The existing coarse probe stays at its original low rate.
        """
        if self.target_selection is not None:
            self._selection_failure(reason);return
        self.recovery_mode=False;self._move(reason,'WAIT_TARGET','AI')
        now=self.clock();due=self.ai_budget.due(now)
        self.ai_wait_due=due if due>now else None
        self.ai_wait_candidate_version=getattr(self.cycle,'candidate_version',0)
        self.ai_attempted=True
        checkpoint('RECOVERY_AI_EVIDENCE_WAIT',reason=reason,epoch=self.epoch,
            quota_due=self.ai_wait_due,fixed_recovery_cooldown=False,live_preview=True)
    def _wait_auto_budget(self):
        if self.target_selection is not None:
            self._selection_failure('AI请求名额暂不可用，请稍后重新点选');return
        if self.ai_mode_locked:
            self._await_ai('ai_budget_exhausted');return
        if self.acquirer is None:self._start_auto('ai_budget_exhausted')
        self.auto_budget_waiting=True;self.recovery_mode=True;self.requested=None
        checkpoint('RECOVERY_AUTO_CONTINUES',reason='ai_budget_exhausted',epoch=self.epoch,
            quota_due=self.ai_budget.due(self.clock()),worker_retained=True,fixed_recovery_cooldown=False)
    def _selection_failure(self,reason,ambiguous=False):
        # A terminal selection must also retire its searcher. Otherwise its
        # expired clock immediately restarts with the selected point discarded.
        with self.lock:self.transitioning=True
        try:
            self.monitor.suspend();self._retire_active()
            self.recovery_mode=False;self.auto_budget_waiting=False
            self.ai_wait_due=None;self.ai_wait_candidate_version=None
            super()._selection_failure(reason,ambiguous)
        finally:
            with self.lock:self.transitioning=False
    def _begin_ai(self,reason):
        if reason=='recover_tracking_lost' and self.ai_mode_locked:
            if self.ai_target_acquired:self._release_ai_mode(reason)
            else:
                self._await_ai(reason);return
        if not self.ai_mode_locked and reason=='recover_tracking_lost':
            self.recovery_from_ai=False;self._start_auto(reason);return
        # Retry permission belongs to the recovery phase, not to an ABSENT-only
        # latch. Explicit user AI clicks remain separate from this auto budget.
        if self.ai_budget.due(self.clock())>self.clock():
            self._wait_auto_budget();return
        self.recovery_mode=False;self.ai_attempted=False
        self._move(reason,'AI_LOADING','AI')
        checkpoint('UNIFIED_AI_BEGIN',reason=reason,epoch=self.epoch)
    def _dispatch(self,frame):
        if self.ai_attempted:return
        service=getattr(self.context.display,'ai_service',None)
        if service is not None and hasattr(service,'ready_for_request') and not service.ready_for_request():return
        if self.explicit_first_request:
            self.explicit_first_request=False;super()._dispatch(frame);return
        ticket=object()
        if not self.ai_budget.reserve(self.clock(),ticket):self._wait_auto_budget();return
        self.ai_budget_ticket=ticket;self.ai_budget_epoch=self.epoch
        super()._dispatch(frame)
    def _wait(self,reason,system_error=False):
        if self.target_selection is not None:
            self._selection_failure(reason);return
        # Found-but-rejected and no-plane both have a bounded recovery route;
        # neither is represented as waiting for an already PRESENT target.
        self.last_failure=str(reason);self.recovery_from_ai=True
        self._release_request()
        checkpoint('RECOVERY_AI_REJECTED',reason=reason,system_error=system_error,
            target_cycle_state=self.cycle.state,next_action='AI waits for fresh evidence or quota' if self.ai_mode_locked else 'immediate automatic recovery')
        self._start_auto('ai_rejected: '+str(reason))
    def _install_manual(self,frame,q):
        # Do not let the watchdog inspect a half-installed tracker using the
        # previous target's clock. Completion still waits for actual pixels.
        with self.lock:self.transitioning=True
        try:
            super()._install_manual(frame,q)
            with self.lock:
                self.active_started=self.last_effective_at=self.clock();self.stable_since=None
                self.requested=None;self.low_since=None;self.recovery_mode=False;self.recovery_from_ai=False
        finally:
            with self.lock:self.transitioning=False
    def _take_auto_result(self):
        # Explicit absence/return outranks an old worker result. A completed
        # result still wins over a timer-only timeout as in unified8.
        if self.requested in ('target_absent','target_returned'):return False
        if self.origin!='AUTO' or self.acquirer is None:return False
        with self.lock:self.transitioning=True
        try:
            accepted=super()._take_auto_result()
            if accepted:
                with self.lock:
                    self.active_started=self.last_effective_at=self.clock();self.stable_since=None
                    self.requested=None;self.recovery_mode=False;self.recovery_from_ai=False;self.auto_budget_waiting=False
            return accepted
        finally:
            with self.lock:self.transitioning=False
    def tick(self):
        now=self.clock();count=getattr(self.camera,'captured',self.last_capture_count)
        if count!=self.last_capture_count:self.last_capture_count=count;self.capture_seen_at=now
        healthy=getattr(self.camera,'error',None) is None and now-max(self.capture_seen_at,self.last_frame_at)<=.75
        with self.lock:
            self.valid_fps=self.rate.fps(now)
            if not healthy or self.closed or self.transitioning:return
            reason=None
            if self.acquirer is not None:
                if self.auto_budget_waiting:
                    # The same searcher can succeed during the quota wait.
                    # Once quota returns, finish any freshly discovered candidate
                    # before handing the still-unsolved search to AI.
                    fresh_candidate=(self.auto_stage in ('CANDIDATE','READY') and self.candidate_at is not None
                        and now<self.candidate_at+self.AUTO_CANDIDATE_EXTRA_S)
                    if self.ai_budget.due(now)<=now and not fresh_candidate:reason='ai_budget_available'
                elif self.recovery_mode:
                    if self._auto_search_expired(now):reason='recovery_auto_timeout'
                elif self.search_at is None and now-self.started>=8.:reason='startup_no_output'
                elif self._auto_search_expired(now):reason='startup_no_output'
            elif self.active is not None:
                last=self.last_effective_at if self.last_effective_at is not None else self.active_started
                if last is not None and now>=last+self.LOSS_S:reason='recover_tracking_lost'
                elif self.engine=='AUTO_V74' and self.monitor.first_valid is not None and now-self.monitor.first_valid>=1.:
                    if 0.<self.valid_fps<4.:
                        if self.low_since is None:self.low_since=now
                        if now-self.low_since>=1.:reason='low_fps'
                    else:self.low_since=None
            if reason is not None and self.requested is None:
                self.requested=reason;checkpoint('RECOVERY_TRIGGER',reason=reason,epoch=self.epoch,effective_fps=self.valid_fps)
    def completed(self,row,when):
        before=self.rate.last_seq;super().completed(row,when)
        with self.lock:
            if self.closed or self.transitioning or row.get('hybrid_epoch')!=self.epoch or self.rate.last_seq==before:return
            if self.ai_mode_locked and self.origin=='AI' and self.engine=='MANUAL_SAME_TARGET' and not self.ai_target_acquired:
                self.ai_target_acquired=True
                checkpoint('AI_MODE_TARGET_ACQUIRED',epoch=self.epoch,sequence=row.get('camera_sequence'),
                    actual_pixel_output_completed=True,release_on='confirmed absence or1.2s output loss')
            previous=self.last_effective_at;self.last_effective_at=when
            if self.requested=='recover_tracking_lost':
                self.requested=None;checkpoint('RECOVERY_CANCELLED',reason='fresh output before handoff',epoch=self.epoch)
            pending_refund=(self.ai_budget_ticket is not None and self.ai_budget_epoch==self.epoch
                and self.origin=='AI' and self.engine=='MANUAL_SAME_TARGET')
            if not (self.recovery_round or pending_refund):return
            if self.stable_since is None or previous is None or when-previous>.5:self.stable_since=when
            if when-self.stable_since>=3. and self.rate.fps(when)>=4.:
                refunded=False
                if pending_refund:
                    refunded=self.ai_budget.refund(self.ai_budget_ticket,when)
                    self.ai_budget_ticket=None;self.ai_budget_epoch=None
                    checkpoint('AI_BUDGET_STABLE_REFUND',epoch=self.epoch,sequence=row.get('camera_sequence'),
                        stable_s=when-self.stable_since,refunded=refunded,failed_requests_preserved=True)
                if self.recovery_round:
                    checkpoint('RECOVERY_STABLE',epoch=self.epoch,stable_s=when-self.stable_since,
                        failed_ai_budget_preserved=True,own_stable_AI_request_refunded=refunded)
                self.recovery_round=0
    def _tag(self,job):
        job=super()._tag(job)
        job.record.update(ai_mode_locked=self.ai_mode_locked,ai_target_acquired=self.ai_target_acquired)
        if self.recovery_round or self.recovery_from_ai:
            job.record.update(recovery_round=self.recovery_round,recovery_from_ai=self.recovery_from_ai)
        # Geometry becomes available before P1 DMA/HDMI pixels complete.
        preview=getattr(self.camera,'live_preview',None)
        if preview is not None:preview.observe_geometry(job.record)
        return job
    def _idle_job(self,index,frame,begin,cpu):
        # Existing tiny-image probe is reused only during recovery/wait. No new
        # image work is introduced in healthy measured tracking frames.
        if self.recovery_mode:self._presence(frame)
        if (self.ai_mode_locked and self.phase=='WAIT_TARGET' and not self.selection_wait_absent
                and self.requested is None and self.ai_wait_candidate_version is not None):
            now=self.clock();due=self.ai_budget.due(now)
            changed=(getattr(self.cycle,'candidate_version',0)!=self.ai_wait_candidate_version
                and getattr(self.cycle,'present_at',None) is not None and now-self.cycle.present_at<=1.)
            quota_returned=self.ai_wait_due is not None and now>=self.ai_wait_due
            if due<=now and (changed or quota_returned):
                self.requested='ai_fresh_evidence' if changed else 'ai_budget_available'
                self.ai_wait_candidate_version=None;self.ai_wait_due=None
                checkpoint('RECOVERY_AI_READY',reason=self.requested,epoch=self.epoch,fixed_recovery_cooldown=False)
        return super()._idle_job(index,frame,begin,cpu)
