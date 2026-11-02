"""Automatic-first admission; AI supplies a seed to the exact manual frontend.

One producer owns all tracker mutations. The watchdog requests transitions;
it never reads image pixels, closes a frontend or launches model inference.
"""
from pathlib import Path
from collections import deque
from contextvars import copy_context
import hashlib,threading,time,types
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v107_policy import OutputMonitor
from v109_target_cycle import TargetCycle
from v116_continuity import mark_continuity,continuity_cancelled
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class CurrentRate:
    def __init__(self):self.times=deque();self.last_seq=None;self.lock=threading.Lock()
    def observe(self,row,now):
        if row.get('state') not in ('CURRENT','MANUAL') or row.get('frozen_output'):return False
        ready=row.get('capture_ready_at',0.) or 0.
        if ready>0. and not 0.<=now-ready<=.5:return False
        seq=row.get('camera_sequence')
        with self.lock:
            if seq is None or self.last_seq is not None and seq<=self.last_seq:return False
            self.last_seq=seq;self.times.append(now)
            while self.times and self.times[0]<=now-1.:self.times.popleft()
            return True
    def fps(self,now):
        with self.lock:
            while self.times and self.times[0]<=now-1.:self.times.popleft()
            return float(len(self.times))

class HybridFrontend:
    def __init__(self,camera,size,options,context,auto_factory,*,recovery=False,target_selection=None,
                 initial_ai=None,clock=time.perf_counter,watchdog=True,acquirer_factory=None,
                 manual_factory=None,aligner=None,cycle_factory=None):
        self.camera=camera;self.size=tuple(size);self.options=dict(options);self.context=context
        self.auto_factory=auto_factory;self.clock=clock;self.acquirer_factory=acquirer_factory
        self.manual_factory=manual_factory;self.aligner=aligner;self._raw_required=None
        self.target_selection=target_selection;self.selection_proof=None;self.selection_failed=None;self.selection_wait_absent=False
        self.active=None;self.acquirer=None;self.task=None;self.frozen=None
        self._continuity_blocked=False
        self.origin='AUTO';self.engine='NONE';self.phase='AUTO_SEARCH';self.trigger=''
        self.started=clock();self.search_at=None;self.candidate_at=None;self.active_started=None
        self.auto_stage='STABILIZING';self.active_index=0;self.epoch=0;self.request_id=0
        self.observed=0;self.last_observed_seq=None;self.ai_attempted=False;self.awaiting_first_output=False
        self.rate=CurrentRate();self.monitor=OutputMonitor(self.started);self.valid_fps=0.;self.low_since=None
        self.requested=None;self.transitioning=False;self.lock=threading.Lock();self.stop=threading.Event();self.watch_wake=threading.Event()
        self.closed=False;self.workers_stopped=True;self.watch=None;self.inline_tick=not watchdog
        self.last_frame_at=clock();self.last_capture_count=getattr(camera,'captured',0);self.capture_seen_at=clock()
        self.cycle=(cycle_factory or TargetCycle)()
        self.initial=dict(hybrid=True,automatic_first=initial_ai is None,ai_tracking='exact manual same-target strategy')
        self.summary_proof=types.SimpleNamespace(snapshot=lambda:dict(scope='unified idle',entries=0))
        self.summary_plan=types.SimpleNamespace(batch=types.SimpleNamespace(last_cache={}))
        if initial_ai is None:self._new_acquirer(recovery,target_selection)
        else:
            self.origin='AI';self.ai_attempted=True;self.monitor.suspend()
            self._install_manual(initial_ai[0],initial_ai[1])
        if watchdog:
            ctx=copy_context();self.watch=threading.Thread(target=lambda:ctx.run(self._watch),name='unified_watch',daemon=True)
            self.watch.start()
        checkpoint('UNIFIED_READY',origin=self.origin,startup_search_s=getattr(self,'AUTO_SEARCH_S',1.5),startup_total_cap_s=getattr(self,'AUTO_TOTAL_CAP_S',2.8),candidate_grace_s=getattr(self,'AUTO_CANDIDATE_EXTRA_S',1.3),startup_presearch_guard_s=8.,
            low_rate_window_s=1.,minimum_outputs=4,low_rate_persistence_s=1.,
            ai_seed_only=True,periodic_ai_recovery=False,new_target_after_absence='AUTO first in recovery controller',
            tracking='exact same ManualFrontend/PersistentManualTracker/options as manual selection')
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
    def _new_acquirer(self,recovery,target_selection):
        if self.acquirer_factory is not None:self.acquirer=self.acquirer_factory(self.auto_factory);return
        from v87_acquire import V74Acquire
        def report(notice):
            if not self.context.cancel.is_set():self.context.display.set_target_notice(notice,self.context.generation)
        def progress(phase):
            if not self.context.cancel.is_set():self.context.display.set_target_phase(phase,self.context.generation)
        self.acquirer=V74Acquire(int(self.options.get('detection_max_dim',640)),int(self.options.get('tracking_max_dim',320)),
            self.auto_factory,budget_ms=float(self.options.get('reacquire_budget_ms',420.)),recovery=recovery,
            target_selection=target_selection,target_report=report,target_progress=progress if target_selection is not None else None,
            phase_report=self._acquire_phase)
    def _acquire_phase(self,phase):
        with self.lock:
            self.auto_stage=phase;now=self.clock()
            if phase=='SEARCHING' and self.search_at is None:self.search_at=now
            if phase=='CANDIDATE' and self.candidate_at is None:self.candidate_at=now
        checkpoint('UNIFIED_AUTO_PHASE',phase=phase,search_at=self.search_at,candidate_at=self.candidate_at)
    def _watch(self):
        while not self.stop.is_set():
            self.watch_wake.wait(.1);self.watch_wake.clear()
            if self.stop.is_set() or self.context.cancel.is_set():return
            self.tick()
    def tick(self):
        now=self.clock();count=getattr(self.camera,'captured',self.last_capture_count)
        if count!=self.last_capture_count:self.last_capture_count=count;self.capture_seen_at=now
        healthy=getattr(self.camera,'error',None) is None and now-max(self.capture_seen_at,self.last_frame_at)<=.75
        with self.lock:
            self.valid_fps=self.rate.fps(now)
            if not healthy or self.closed or self.transitioning or self.origin!='AUTO':return
            reason=None
            if self.acquirer is not None:
                if now-self.started>=8.:reason='startup_no_output'
                elif self.search_at is not None and now-self.search_at>=3.:
                    candidate=self.candidate_at is not None and now-self.candidate_at<2.
                    inflight=self.candidate_at is None and now-self.search_at<4.5
                    if not candidate and not inflight:reason='startup_no_output'
            elif self.active is not None and self.engine=='AUTO_V74':
                first=self.monitor.first_valid
                if first is None:
                    if now-self.active_started>=3.:reason='startup_no_output'
                elif now-first>=1.:
                    if self.valid_fps<4.:
                        if self.low_since is None:self.low_since=now
                        if now-self.low_since>=1.:reason='low_fps'
                    else:self.low_since=None
            if reason is not None and self.requested is None:
                self.requested=reason;checkpoint('UNIFIED_TRIGGER',reason=reason,epoch=self.epoch,effective_fps=self.valid_fps)
    def completed(self,row,when):
        with self.lock:
            if self.closed or self.transitioning or row.get('hybrid_epoch')!=self.epoch:return
            fresh=self.rate.observe(row,when)
            if not fresh:return
            if self.engine=='AUTO_V74':
                self.monitor.observe(row,when)
                if self.requested in ('startup_no_output','low_fps') and (self.requested!='low_fps' or self.rate.fps(when)>=4.):
                    self.requested=None;self.low_since=None
                    checkpoint('UNIFIED_SWITCH_CANCELLED',reason='fresh automatic output completed',epoch=self.epoch)
            if self.awaiting_first_output:
                self.awaiting_first_output=False;self.phase='AI_TRACK'
                checkpoint('UNIFIED_AI_ACCEPTED',epoch=self.epoch,sequence=row.get('camera_sequence'),
                    tracking_engine='MANUAL_SAME_TARGET',actual_pixel_output_completed=True)
    def _tag(self,job):
        job.record.update(correction_origin=self.origin,corner_source=self.origin,tracking_engine=self.engine,
            hybrid_phase=self.phase,hybrid_epoch=self.epoch,hybrid_valid_fps=self.valid_fps,hybrid_trigger=self.trigger,
            target_cycle_state=self.cycle.state)
        if self.selection_proof is not None:job.record['target_selection_proof']=self.selection_proof
        if self.selection_failed is not None:job.record['target_selection_failed']=self.selection_failed
        if job.state=='CURRENT':self._continuity_blocked=False
        elif continuity_cancelled(job.record):self._continuity_blocked=True
        mark_continuity(job.record,bool(job.tiles) and not self._continuity_blocked,self.clock())
        return job
    def _take_auto_result(self):
        if self.origin!='AUTO' or self.acquirer is None:return False
        ready=self.acquirer.take()
        if ready is None:return False
        selected,det,built,report=ready
        try:
            selection_proof=report.get('target_selection_proof')
            if self.target_selection is not None and (not selection_proof or
                    selection_proof.get('request_id')!=self.target_selection['request_id'] or not selection_proof.get('single_target')):
                built.close();self.acquirer.close();self.acquirer=None
                self._begin_ai('selection_auto_unconfirmed');return False
            self.active=built;self.active.raw_required=self.raw_required
            self.acquirer.close();self.acquirer=None
            self.cycle.lock(selected.image,det[0] if det is not None else np.asarray(built.initial['corners']))
            if self.target_selection is not None:
                self.selection_proof=dict(selection_proof,current_aligned=True);self.target_selection=None
            with self.lock:
                self.phase='AUTO_TRACK';self.engine='AUTO_V74';self.active_index=0;self.active_started=self.clock()
                self.monitor.reset(self.active_started);self.requested=None;self.low_since=None
            checkpoint('UNIFIED_AUTO_ACCEPTED',epoch=self.epoch,**report)
        finally:selected.release()
        return True
    def _retire_active(self):
        if self.active is not None:
            self.summary_proof=types.SimpleNamespace(snapshot=lambda s=self.active.proof_cache.snapshot():s)
            self.summary_plan=types.SimpleNamespace(batch=types.SimpleNamespace(last_cache=dict(self.active.plan_workspace.batch.last_cache)))
            self.active.close();self.active=None
        if self.acquirer is not None:self.acquirer.close();self.acquirer=None
        self.engine='NONE'
    def _release_request(self):
        if self.task is not None:
            if not self.task.done.is_set():
                service=getattr(self.context.display,'ai_service',None)
                if service is not None:service.cancel(self.task)
                self.task.cancelled.set()
            self.task=None
        if self.frozen is not None:self.frozen.release();self.frozen=None
    def _transition(self,reason,empty=False):
        with self.lock:self.transitioning=True
        self.monitor.suspend();self._retire_active();self._release_request()
        with self.lock:
            self.epoch+=1;self.requested=None;self.low_since=None;self.rate=CurrentRate();self.valid_fps=0.
            self.awaiting_first_output=False;self.trigger=reason
            if empty:self.phase='EMPTY_WAIT'
            else:self.origin='AI';self.phase='AI_LOADING'
            self.transitioning=False
        checkpoint('UNIFIED_EMPTY_WAIT' if empty else 'UNIFIED_AI_BEGIN',reason=reason,epoch=self.epoch,old_workers_retired=True)
    def _begin_ai(self,reason):
        if self.ai_attempted:
            self.requested=None;return
        self._transition(reason)
    def _wait(self,reason,system_error=False):
        self._release_request();self.phase='AI_ERROR' if system_error else 'WAIT_TARGET'
        checkpoint('UNIFIED_WAIT_TARGET',reason=reason,system_error=system_error,
            retry_policy='confirmed absence then stable return, or explicit reselect',periodic_retry=False)
    def _selection_failure(self,reason,ambiguous=False):
        selection=self.target_selection;self.selection_failed=None if selection is None else selection['request_id']
        self.target_selection=None;self.selection_proof=None;self.selection_wait_absent=True
        self._release_request();self.phase='WAIT_TARGET';self.requested=None
        notice='multiple' if ambiguous else 'unconfirmed'
        setter=getattr(self.context.display,'set_target_notice',None)
        if setter is not None:setter(notice,self.context.generation)
        checkpoint('TARGET_SELECTION_FAILED',request_id=self.selection_failed,reason=str(reason),
            automatic_retry_same_click=False,live_preview=True,waiting_for='new tap or confirmed absence/return')
    def _dispatch(self,frame):
        if self.ai_attempted:return
        self.ai_attempted=True
        from v79_acquire import OwnedFrame
        from v31_pixels import model_bgr
        service=getattr(self.context.display,'ai_service',None)
        if service is None:self._wait('AI service unavailable',True);return
        selection_context=None
        if self.target_selection is not None:
            from v121_selection import map_point
            try:point,mapping=map_point(self.target_selection,frame.image,frame.sequence)
            except (ValueError,cv2.error) as exc:self._wait(str(exc));return
            selection_context=dict(request_id=self.target_selection['request_id'],point=point,mapping=mapping,
                source_shape=list(frame.image.shape),detection_limit=int(self.options.get('detection_max_dim',640)),
                tracking_limit=int(self.options.get('tracking_max_dim',320)),check=self.context.check)
        self.frozen=OwnedFrame(np.array(frame.image,copy=True,order='C'),float(frame.ready),int(frame.sequence),float(frame.timestamp))
        self.frozen.image.setflags(write=False)
        source=np.array(model_bgr(self.frozen.image),copy=True,order='C');source.setflags(write=False)
        self.request_id+=1
        receipt=dict(release_id=RELEASE_ID,generation=int(self.context.generation),token=self.epoch,
            sequence=int(frame.sequence),request_id=self.request_id)
        self.task=types.SimpleNamespace(source=source,receipt=receipt,done=threading.Event(),cancelled=threading.Event(),result=None,progress=None)
        self.task.selection_context=selection_context
        self.task_epoch=self.epoch;self.phase='AI_INFER'
        try:service.submit(self.task)
        except Exception as exc:self._wait(str(exc),True);return
        checkpoint('UNIFIED_AI_REQUEST',**receipt,reason=self.trigger,one_attempt_per_target_cycle=True)
    def _install_manual(self,frame,q):
        # Exactly the public manual default: no AI physical-first option,
        # extra .2s static deadline or AI-specific same-target recovery branch.
        if self.manual_factory is not None:built=self.manual_factory(frame,q)
        else:
            from v82_manual import ManualFrontend
            opts={k:v for k,v in self.options.items() if k!='_ai_physical_profile'}
            built=ManualFrontend(self.camera,frame,q,self.size,opts,raw_required=self.raw_required)
        self.active=built;self.active.raw_required=self.raw_required;self.active_index=0
        self.camera._p11_stream_stabilized=True
        self.engine='MANUAL_SAME_TARGET';self.phase='AI_CONFIRM';self.awaiting_first_output=True
        self.cycle.lock(frame.image,q)
        checkpoint('UNIFIED_MANUAL_SEEDED',epoch=self.epoch,tracking_engine=self.engine,manual_defaults_preserved=True,
            periodic_ai_recovery=False,sequence=int(frame.sequence))
    def _start_manual(self,frame,result):
        from v79_acquire import OwnedFrame
        from v100_ai_tracking import align_current
        owned=OwnedFrame(np.array(frame.image,copy=True,order='C'),float(frame.ready),int(frame.sequence),float(frame.timestamp))
        owned.image.setflags(write=False)
        class OneFrame:
            def __init__(self,f):self.frame=f
            def take(self,timeout):
                if self.frame is None:raise RuntimeError('candidate frame already consumed')
                f=self.frame;self.frame=None;return f
        current=None
        try:
            selection_proof=result.get('target_selection_proof')
            if self.target_selection is not None and (not selection_proof or
                    selection_proof.get('request_id')!=self.target_selection['request_id'] or not selection_proof.get('single_target')):
                raise ValueError('AI结果不属于本次点选的单本目标')
            current,q=(self.aligner or align_current)(self.context,OneFrame(owned),self.frozen,np.asarray(result['quad'],np.float32))
            self._install_manual(current,q)
            if self.target_selection is not None:
                self.selection_proof=dict(selection_proof,current_aligned=True);self.target_selection=None
            self._release_request()
        finally:
            owned.release()
            if current is not None:current.release()
    def _presence(self,frame):
        event=self.cycle.observe(frame.image,int(frame.sequence),self.clock())
        if event=='ABSENT':
            self.requested='target_absent';checkpoint('UNIFIED_TARGET_ABSENT',epoch=self.epoch,confirmed=True)
        elif event=='RETURNED':
            self.ai_attempted=False;self.requested='target_returned'
            checkpoint('UNIFIED_TARGET_RETURNED',epoch=self.epoch,next_admission='AI first')
        return event
    def _idle_job(self,index,frame,begin,cpu):
        from v64_camera_hdmi import FrameJob
        from v113_live_preview import source_snapshot
        raw=source_snapshot(self.camera,frame)
        row=dict(index=index,camera_sequence=int(frame.sequence),capture_ready_at=float(frame.ready),camera_timestamp=float(frame.timestamp),
            state='LOST',corners=(),color_mode=int(self.camera.color_mode),output_size=self.size,tiles=0,verified_at=0.,
            ps_prepared_at=self.clock(),ps_prepare_s=self.clock()-begin,ps_thread_cpu_s=time.thread_time()-cpu,tracker_s=0.,
            track_reason=self.phase,admission_mode='unified_search',source_snapshot_owned=True)
        return self._tag(FrameJob(index,frame,(),self.size,'LOST',(),self.camera.color_mode,raw,row,source_owned=True))
    def prepare(self,index):
        self.context.check();self._take_auto_result()
        if self.inline_tick:self.tick()
        reason=self.requested
        if reason is not None:
            if reason=='target_absent':self._transition(reason,empty=True)
            elif reason=='target_returned':self._transition(reason)
            elif not self._take_auto_result():
                with self.lock:
                    if reason=='low_fps' and self.rate.fps(self.clock())>=4.:self.requested=None;self.low_since=None;reason=None
                if reason is not None:self._begin_ai(reason)
        if self.active is not None:
            self.active_index+=1;job=self.active.prepare(self.active_index);self.last_frame_at=self.clock()
            job.index=index;job.record.update(index=index,tracking_index=self.active_index)
            original=job.state
            if self.engine=='MANUAL_SAME_TARGET':
                job.record['manual_source_state']=original
                if original=='MANUAL':job.state='CURRENT';job.record['state']='CURRENT'
                elif original=='MANUAL_HELD':job.state='HELD';job.record['state']='HELD'
            measured=(original=='CURRENT' and self.engine=='AUTO_V74' or
                original=='MANUAL' and bool(job.record.get('manual_motion_proved')))
            if measured:self.cycle.tracking_good()
            else:
                probe_started=time.perf_counter();probe_cpu=time.thread_time();event=self._presence(job.lease)
                elapsed=time.perf_counter()-probe_started
                job.record.update(presence_check_s=elapsed,ps_prepare_s=job.record.get('ps_prepare_s',0.)+elapsed,
                    ps_thread_cpu_s=job.record.get('ps_thread_cpu_s',0.)+time.thread_time()-probe_cpu)
            if not measured and event=='ABSENT':
                # Retire the frontend on the next producer iteration; never
                # publish old tiles on the frame that confirms an empty scene.
                job.state='LOST';job.tiles=();job.corners=();job.record.update(state='LOST',tiles=0,corners=())
                if job.source_snapshot is None:
                    from v113_live_preview import source_snapshot
                    job.source_snapshot=source_snapshot(self.camera,job.lease);job.source_owned=True
            return self._tag(job)
        begin=self.clock();cpu=time.thread_time();frame=self.camera.take(3.)
        try:
            self.last_frame_at=self.clock()
            if int(frame.sequence)!=self.last_observed_seq:self.observed+=1;self.last_observed_seq=int(frame.sequence)
            if self.acquirer is not None:
                if not self._take_auto_result():self.acquirer.offer(frame)
            elif self.task is not None:
                if self.task.done.is_set():
                    result=self.task.result or {}
                    if self.task_epoch!=self.epoch:self._wait('stale AI generation')
                    elif result.get('status')=='candidate':
                        try:self._start_manual(frame,result)
                        except (ValueError,cv2.error) as exc:self._wait(str(exc))
                    elif result.get('failure_kind')=='ambiguous_target':self._selection_failure(result.get('error') or 'multiple targets',True)
                    else:self._wait(result.get('error') or 'no_plane',result.get('failure_kind') in ('runtime_error','timeout'))
                else:self.phase='AI_LOADING' if getattr(self.context.display.ai_service,'loading',False) else 'AI_INFER'
            elif self.phase=='AI_LOADING' and not self.ai_attempted:
                if self.observed>=12:self._dispatch(frame)
            elif self.phase in ('WAIT_TARGET','AI_ERROR','EMPTY_WAIT'):self._presence(frame)
            return self._idle_job(index,frame,begin,cpu)
        except BaseException:frame.release();raise
    def close(self):
        if self.closed:return
        self.stop.set();self.watch_wake.set()
        if self.watch is not None:
            self.watch.join(1.)
            if self.watch.is_alive():raise RuntimeError('unified watchdog still active')
        self.workers_stopped=False;self.monitor.suspend();self._retire_active();self._release_request()
        self.closed=True;self.workers_stopped=True
