"""One live camera/PL owner: exact automatic frontend, event-only AI rescue."""
from pathlib import Path
from collections import deque
from contextvars import copy_context
import hashlib,threading,time,types
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v107_policy import OutputMonitor
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class CurrentRate:
    """A tiny completed-output meter; counts current source frames, not refreshes."""
    def __init__(self):self.times=deque();self.last_seq=None;self.lock=threading.Lock()
    def observe(self,row,now):
        if row.get('state') not in ('CURRENT','MANUAL') or row.get('frozen_output'):return
        ready=row.get('capture_ready_at',0.) or 0.
        if ready>0. and not 0.<=now-ready<=.5:return
        seq=row.get('camera_sequence')
        with self.lock:
            if seq is None or self.last_seq is not None and seq<=self.last_seq:return
            self.last_seq=seq;self.times.append(now)
            while self.times and self.times[0]<=now-1.:self.times.popleft()
    def fps(self,now):
        with self.lock:
            while self.times and self.times[0]<=now-1.:self.times.popleft()
            return float(len(self.times))

class HybridFrontend:
    """Producer thread owns frontend mutations; watchdog only requests handoff."""
    def __init__(self,camera,size,options,context,auto_factory,*,recovery=False,target_selection=None,
                 initial_ai=None,clock=time.perf_counter,watchdog=True,acquirer_factory=None,
                 manual_factory=None,aligner=None):
        self.camera=camera;self.size=tuple(size);self.options=dict(options);self.context=context
        self.auto_factory=auto_factory;self.clock=clock;self._raw_required=None
        self.acquirer_factory=acquirer_factory;self.manual_factory=manual_factory;self.aligner=aligner
        self.active=None;self.acquirer=None;self.task=None;self.frozen=None;self.confirm_tracker=None
        self.epoch=0;self.request_id=0;self.phase='AUTO_SEARCH';self.origin='AUTO';self.trigger=''
        self.last_frame_at=clock();self.last_valid_at=None;self.last_capture_count=getattr(camera,'captured',0)
        self.capture_seen_at=clock();self.started=clock();self.observed=0;self.last_observed_seq=None
        self.monitor=OutputMonitor(self.started);self.rate=CurrentRate();self.valid_fps=0.
        self.requested=None;self.closed=False;self.workers_stopped=True;self.lock=threading.Lock();self.stop=threading.Event()
        self.inline_tick=not watchdog;self.awaiting_first_output=False;self.ai_proof_at=None
        self.failures=0;self.next_ai_at=0.;self.scene_base=None;self.scene_previous=None;self.scene_stable=0
        self.scene_check_at=0.;self.early_wake_credit=1;self.initial=dict(hybrid=True,automatic_first=initial_ai is None)
        self.summary_proof=types.SimpleNamespace(snapshot=lambda:dict(scope='hybrid idle',entries=0))
        self.summary_plan=types.SimpleNamespace(batch=types.SimpleNamespace(last_cache={}))
        self.watch=None
        if initial_ai is None:self._new_acquirer(recovery,target_selection)
        else:
            self.monitor.suspend();self.origin='AI';self.phase='AI_TRACK'
            self.active=self._build_manual(initial_ai[0],initial_ai[1]);self.last_valid_at=clock()
        if watchdog:
            ctx=copy_context();self.watch=threading.Thread(target=lambda:ctx.run(self._watch),name='hybrid_watch',daemon=True)
            self.watch.start()
        checkpoint('HYBRID_READY',origin=self.origin,startup_s=3.,window_s=1.,minimum_outputs=4,
            heavy_compute='automatic OR AI; never both',model_per_frame=False)
    @property
    def raw_required(self):return self._raw_required
    @raw_required.setter
    def raw_required(self,value):
        self._raw_required=value
        if self.active is not None:self.active.raw_required=value
    @property
    def proof_cache(self):return self.active.proof_cache if self.active is not None else self.summary_proof
    @property
    def plan_workspace(self):return self.active.plan_workspace if self.active is not None else self.summary_plan
    def _new_acquirer(self,recovery=False,target_selection=None):
        if self.acquirer_factory is not None:
            self.acquirer=self.acquirer_factory(self.auto_factory);return
        from v87_acquire import V74Acquire
        def target_report(notice):
            if not self.context.cancel.is_set():
                self.context.display.set_target_notice(notice,self.context.generation)
        def target_progress(phase):
            if not self.context.cancel.is_set():
                self.context.display.set_target_phase(phase,self.context.generation)
        self.acquirer=V74Acquire(int(self.options.get('detection_max_dim',640)),int(self.options.get('tracking_max_dim',320)),
            self.auto_factory,budget_ms=float(self.options.get('reacquire_budget_ms',420.)),
            recovery=recovery,target_selection=target_selection,target_report=target_report,
            target_progress=target_progress if target_selection is not None else None)
    def _build_manual(self,frame,q):
        if self.manual_factory is not None:return self.manual_factory(frame,q)
        from v82_manual import ManualFrontend
        opts=dict(self.options,_ai_physical_profile=True)
        return ManualFrontend(self.camera,frame,q,self.size,opts,raw_required=self.raw_required)
    def _watch(self):
        while not self.stop.wait(.1):
            if getattr(self.context,'cancel',self.stop).is_set():return
            self.tick()
    def tick(self):
        now=self.clock();count=getattr(self.camera,'captured',self.last_capture_count)
        if count!=self.last_capture_count:self.last_capture_count=count;self.capture_seen_at=now
        capture_ok=(getattr(self.camera,'error',None) is None and
                    now-max(self.capture_seen_at,self.last_frame_at)<=.75)
        self.valid_fps=self.rate.fps(now)
        reason=None
        if self.origin=='AUTO':reason=self.monitor.tick(now,capture_ok=capture_ok)
        elif (self.phase=='AI_TRACK' or self.awaiting_first_output) and capture_ok and self.last_valid_at is not None and now-self.last_valid_at>=3.:
            reason='ai_tracking_lost'
        if reason:
            with self.lock:
                if self.requested is None:
                    self.requested=reason
                    checkpoint('HYBRID_TRIGGER',reason=reason,epoch=self.epoch,
                        effective_fps=self.valid_fps,transition='requested; retire old CPU work before AI')
    def completed(self,row,when):
        """Called only after successful owner completion, independently of log warmup."""
        with self.lock:
            if row.get('hybrid_epoch')!=self.epoch or self.closed:return
            self.rate.observe(row,when)
            if row.get('state')=='CURRENT' and not row.get('frozen_output'):
                self.last_valid_at=when
                if self.awaiting_first_output:
                    self.awaiting_first_output=False;self.phase='AI_TRACK';self.failures=0;self.early_wake_credit=1
                    checkpoint('HYBRID_AI_ACCEPTED',epoch=self.epoch,sequence=row.get('camera_sequence'),
                        confirmation_frames=getattr(self,'confirm_count',0),actual_pixel_output_completed=True)
            if row.get('correction_origin')=='AUTO':self.monitor.observe(row,when)
    def _tag(self,job):
        job.record.update(correction_origin=self.origin,hybrid_phase=self.phase,hybrid_epoch=self.epoch,
            hybrid_valid_fps=self.valid_fps,hybrid_trigger=self.trigger)
        return job
    def _retire_active(self):
        if self.active is not None:
            self.summary_proof=types.SimpleNamespace(snapshot=lambda s=self.active.proof_cache.snapshot():s)
            self.summary_plan=types.SimpleNamespace(batch=types.SimpleNamespace(last_cache=dict(self.active.plan_workspace.batch.last_cache)))
            self.active.close();self.active=None
        if self.acquirer is not None:self.acquirer.close();self.acquirer=None
    def _begin_ai(self,reason):
        self.monitor.suspend();self._retire_active()
        with self.lock:
            self.epoch+=1;self.origin='AI';self.phase='AI_LOADING';self.trigger=reason
            self.rate=CurrentRate();self.valid_fps=0.;self.last_valid_at=None
            self.next_ai_at=self.clock();self.requested=None;self.awaiting_first_output=False
        checkpoint('HYBRID_SWITCH',reason=reason,to='AI',epoch=self.epoch,
            effective_fps=self.valid_fps,source_stream_preserved=True,old_workers_retired=True)
    def _close_confirmation(self):
        if self.confirm_tracker is not None:self.confirm_tracker.close();self.confirm_tracker=None
    def _wait(self,reason,system_error=False):
        self._close_confirmation();self._release_request()
        self.failures+=1;delay=(5.,10.,20.)[min(self.failures-1,2)]
        self.phase='AI_ERROR' if system_error else 'WAIT_TARGET';self.next_ai_at=self.clock()+delay
        self.scene_base=None;self.scene_previous=None;self.scene_stable=0
        checkpoint('HYBRID_WAIT_TARGET',reason=reason,retry_s=delay,failures=self.failures,
            system_error=system_error,correction_output=False)
    def _release_request(self):
        if self.task is not None:
            if not self.task.done.is_set():
                self.task.cancelled.set();service=getattr(self.context.display,'ai_service',None)
                if service is not None:service.cancel(self.task)
            self.task=None
        if self.frozen is not None:self.frozen.release();self.frozen=None
    def _dispatch(self,frame):
        from v79_acquire import OwnedFrame
        from v31_pixels import model_bgr
        service=getattr(self.context.display,'ai_service',None)
        if service is None:self._wait('AI service unavailable',True);return
        # This boundary must finish before the actor is allowed to run inference.
        # No automatic detector/CPU recovery remains active here.
        self.frozen=OwnedFrame(np.array(frame.image,copy=True,order='C'),float(frame.ready),int(frame.sequence),float(frame.timestamp))
        self.frozen.image.setflags(write=False)
        source=np.array(model_bgr(self.frozen.image),copy=True,order='C');source.setflags(write=False)
        self.request_id+=1
        receipt=dict(release_id=RELEASE_ID,generation=int(self.context.generation),token=self.epoch,
            sequence=int(frame.sequence),request_id=self.request_id)
        task=types.SimpleNamespace(source=source,receipt=receipt,done=threading.Event(),cancelled=threading.Event(),
            result=None,progress=None)
        self.task=task;self.task_epoch=self.epoch;self.phase='AI_INFER'
        try:service.submit(task)
        except Exception as exc:self._wait('AI dispatch failed: '+str(exc),True);return
        checkpoint('HYBRID_AI_REQUEST',**receipt,reason=self.trigger,single_inflight=True)
    def _start_confirmation(self,frame,result):
        from v79_acquire import OwnedFrame
        from v100_ai_tracking import align_current
        from v104_physical_tracking import create_tracker
        # align_current takes a lease from this private one-frame source, never
        # from the real camera (only the PS producer consumes that camera).
        owned=OwnedFrame(np.array(frame.image,copy=True,order='C'),float(frame.ready),int(frame.sequence),float(frame.timestamp))
        owned.image.setflags(write=False)
        class OneFrame:
            def __init__(self,f):self.frame=f
            def take(self,timeout):
                if self.frame is None:raise RuntimeError('candidate frame already consumed')
                f=self.frame;self.frame=None;return f
        current=None
        try:
            current,q=(self.aligner or align_current)(self.context,OneFrame(owned),self.frozen,np.asarray(result['quad'],np.float32))
            self.confirm_tracker=create_tracker(current,q,int(self.options.get('tracking_max_dim',320)),authority='ai_confirm')
            self.confirm_count=1;self.confirm_at=self.clock();self.confirm_sequence=int(frame.sequence)
            self.phase='AI_CONFIRM';self._release_request()
            checkpoint('HYBRID_CANDIDATE_CONFIRM',epoch=self.epoch,sequence=int(frame.sequence),required_frames=3,minimum_span_s=.20)
        finally:
            owned.release()
            if current is not None:current.release()
    def _confirm(self,frame):
        if int(frame.sequence)==self.confirm_sequence:return
        tracker=self.confirm_tracker
        # Fallback FB must perform actual bidirectional validation for each
        # confirmation; FIXED/static shortcuts cannot count as fresh evidence.
        if hasattr(tracker,'primary') and getattr(tracker,'edge',None) is None:tracker.primary.first=True
        q,detail=tracker.update(frame)
        if q is None or not detail.get('manual_motion_proved'):
            self._wait('candidate current-frame proof failed');return
        self.confirm_sequence=int(frame.sequence);self.confirm_count+=1
        if self.confirm_count>=3 and self.clock()-self.confirm_at>=.20:
            # Retain ownership before retiring the temporary native tracker;
            # cleanup must own the final frontend even if retirement fails.
            self.active=self._build_manual(frame,q)
            self._close_confirmation();self.phase='AI_CONFIRM';self.awaiting_first_output=True
            self.last_valid_at=self.clock()
        elif self.clock()-self.confirm_at>2.:self._wait('candidate confirmation timed out')
    def _scene_wake(self,frame):
        now=self.clock()
        if now<self.scene_check_at:return False
        self.scene_check_at=now+.5
        image=frame.image
        sample=(image[::8,::8,0] if image.ndim==3 and image.shape[2]==2 else
                cv2.cvtColor(image[::8,::8],cv2.COLOR_BGR2GRAY)).astype(np.float32)
        sample-=np.median(sample)
        if self.scene_base is None:
            self.scene_base=sample;self.scene_previous=sample;return False
        stable=float(np.mean(np.abs(sample-self.scene_previous)))<3.
        changed=float(np.mean(np.abs(sample-self.scene_base)))>10.
        self.scene_previous=sample;self.scene_stable=self.scene_stable+1 if stable else 0
        if changed and self.scene_stable>=2 and self.early_wake_credit:
            self.early_wake_credit-=1;return True
        return False
    def _idle_job(self,index,frame,begin,cpu):
        from v64_camera_hdmi import FrameJob
        raw=np.array(frame.image,copy=True,order='C');raw.setflags(write=False)
        row=dict(index=index,camera_sequence=int(frame.sequence),capture_ready_at=float(frame.ready),
            camera_timestamp=float(frame.timestamp),state='LOST',corners=(),color_mode=int(self.camera.color_mode),
            output_size=self.size,tiles=0,verified_at=0.,ps_prepared_at=self.clock(),
            ps_prepare_s=self.clock()-begin,ps_thread_cpu_s=time.thread_time()-cpu,tracker_s=0.,
            track_reason=self.phase,admission_mode='hybrid_search',source_snapshot_owned=True)
        return self._tag(FrameJob(index,frame,(),self.size,'LOST',(),self.camera.color_mode,raw,row,source_owned=True))
    def prepare(self,index):
        self.context.check()
        if self.inline_tick:self.tick()
        if self.requested is not None:self._begin_ai(self.requested)
        if self.active is not None:
            job=self.active.prepare(index);self.last_frame_at=self.clock()
            proved=bool(job.record.get('manual_motion_proved'))
            static_current=bool(job.record.get('manual_static_hold') and self.ai_proof_at is not None
                and 0.<=self.clock()-self.ai_proof_at<=.20)
            if self.origin=='AI' and job.state=='MANUAL' and (proved or static_current):
                # AI verified current geometry is CURRENT in the common owner,
                # so statistics/HDMI no longer confuse AI with true manual input.
                if proved:self.ai_proof_at=float(job.lease.ready)
                job.state='CURRENT';job.record.update(state='CURRENT',admission_mode='ai',
                    current_evidence='measured' if proved else 'bounded_static_continuity',
                    verified_at=self.ai_proof_at or 0.)
            elif self.origin=='AI' and job.state=='MANUAL':
                # A fixed/static shortcut is visible as held geometry, never
                # evidence of a newly measured current correction.
                fresh=self.ai_proof_at is not None and self.clock()-self.ai_proof_at<=1.5
                job.state='HELD' if fresh else 'LOST'
                job.record.update(state=job.state,admission_mode='ai',hybrid_unproved_hold=True,
                    verified_at=self.ai_proof_at or 0.)
                if not fresh:
                    job.tiles=();job.corners=();job.record.update(corners=(),tiles=0)
                    if job.source_snapshot is None:
                        job.source_snapshot=np.array(job.lease.image,copy=True,order='C')
                        job.source_snapshot.setflags(write=False);job.source_owned=True
            return self._tag(job)
        begin=self.clock();cpu=time.thread_time();frame=self.camera.take(3.)
        try:
            self.last_frame_at=self.clock()
            if int(frame.sequence)!=self.last_observed_seq:
                self.observed+=1;self.last_observed_seq=int(frame.sequence)
            if self.origin=='AUTO':
                ready=self.acquirer.take()
                if ready is not None:
                    selected,det,built,report=ready
                    try:
                        self.active=built;self.active.raw_required=self.raw_required
                        self.acquirer.close();self.acquirer=None
                        self.phase='AUTO_TRACK'
                        checkpoint('HYBRID_AUTO_ACCEPTED',epoch=self.epoch,**report)
                    finally:selected.release()
                else:self.acquirer.offer(frame)
            elif self.phase=='AI_TRACK':pass
            elif self.phase=='AI_CONFIRM':
                try:self._confirm(frame)
                except (ValueError,cv2.error) as exc:self._wait(str(exc))
            elif self.task is not None:
                if self.task.done.is_set():
                    if self.task_epoch!=self.epoch:self._wait('stale AI generation')
                    else:
                        result=self.task.result or {}
                        if result.get('status')=='candidate':
                            try:self._start_confirmation(frame,result)
                            except (ValueError,cv2.error) as exc:self._wait(str(exc))
                        else:self._wait(result.get('error') or 'no_plane',result.get('failure_kind') in ('runtime_error','timeout'))
                else:
                    service=getattr(self.context.display,'ai_service',None)
                    self.phase='AI_LOADING' if getattr(service,'loading',False) else 'AI_INFER'
            elif self.phase in ('WAIT_TARGET','AI_LOADING','AI_ERROR'):
                wake=self._scene_wake(frame) if self.phase=='WAIT_TARGET' else False
                if self.observed>=12 and (self.clock()>=self.next_ai_at or wake):
                    self._dispatch(frame)
            return self._idle_job(index,frame,begin,cpu)
        except BaseException:frame.release();raise
    def close(self):
        if self.closed:return
        self.stop.set()
        if self.watch is not None:
            self.watch.join(1.)
            if self.watch.is_alive():raise RuntimeError('hybrid watchdog still active')
        self.workers_stopped=False
        self.monitor.suspend();self._retire_active();self._close_confirmation();self._release_request()
        self.closed=True;self.workers_stopped=True
