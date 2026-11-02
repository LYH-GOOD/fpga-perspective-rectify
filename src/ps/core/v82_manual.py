"""Explicit manual authority, bounded FB motion and unchanged P1 owner/planner."""
from pathlib import Path
from collections import deque
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint,frame_record
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]


from v105_manual_tracking import PersistentManualTracker as ManualTracker


class ManualFrontend:
    def __init__(self,camera,first,q,size,options,raw_required=None):
        from v64_io import PlanWorkspace
        from v64_p1_backend import ProofCache
        from v73_ratio import make_orientation as DualOrientation
        self.camera=camera;self.size=tuple(size);self.hold_s=min(1.5,float(options.get('hold_max_age_s',1.5)))
        self.options=dict(options);self.recovery=None;self.automatic=None;self.next_offer=0.
        self.workers_stopped=True;self.closed=False
        self.proof_cache=ProofCache(128);self.plan_workspace=PlanWorkspace();self.plan_states={}
        self.plan_strategy=options.get('plan_strategy','fast_safe');self.proof_cpu_budget_s=float(options.get('proof_cpu_budget_ms',12.))/1000.
        self.orientation=DualOrientation(options.get('output_orientation','auto_two'),size,2)
        self.raw_required=raw_required
        self.tracker=None;self.last_verified=None;self.manual_retired=False;self.manual_failed=False
        self.manual_failure_reason=None;self.manual_hint=None
        self.manual_streak=0
        self.manual_fail_streak=max(1,int(options.get('manual_fail_streak',3)))
        self.reference_tracking=bool(options.get('_manual_reference_v17',False));self.continuity_blocked=False
        try:
            if self.reference_tracking:
                from v117_manual_reference import PersistentReferenceTracker
                self.tracker=PersistentReferenceTracker(first,q,int(options.get('tracking_max_dim',320)))
            elif options.get('_ai_physical_profile',False):
                from v104_physical_tracking import create_tracker
                self.tracker=create_tracker(first,q,int(options.get('tracking_max_dim',320)))
            else:self.tracker=ManualTracker(first,q,int(options.get('tracking_max_dim',320)))
        except BaseException:self.close();raise
        from v73_ratio import register_manual_frontend
        register_manual_frontend(self)
    def plan(self,q,shape,size):
        from v64_camera_hdmi import Frontend
        return Frontend.plan(self,q,shape,size)
    def prepare(self,index):
        from v64_camera_hdmi import FrameJob
        capture=time.perf_counter();frame=self.camera.take(3.);begin=time.perf_counter();cpu=time.thread_time()
        try:
            q,track=self.tracker.update(frame)
            plan={};failure=None
            if q is not None:
                proposal=self.orientation.propose(q,frame.image.shape,index,timestamp=float(frame.ready),
                    confidence=1.,strong_verified=bool(track.get('manual_motion_proved')))
                q=proposal.quad;size=tuple(proposal.size or self.size)
                try:tiles,plan=self.plan(q,frame.image.shape,size)
                except ValueError as exc:failure=str(exc)
                else:
                    orient=self.orientation.commit(proposal)
                    self.last_verified=dict(tiles=tiles,size=size,corners=tuple(map(tuple,q.tolist())),verified_at=float(frame.ready),
                        layout_generation=orient.get('layout_generation',0),orientation=orient.get('orientation'))
            valid=q is not None and failure is None;last=self.last_verified
            if valid:self.manual_streak=0
            else:self.manual_streak+=1
            age=max(0.,time.perf_counter()-last['verified_at']) if last else float('inf')
            state='MANUAL' if valid else 'MANUAL_HELD' if last and age<=self.hold_s else 'LOST'
            used=last if state!='LOST' else dict(tiles=(),size=self.size,corners=(),verified_at=0.)
            candidate=();candidate_ready=0.
            raw_begin=time.perf_counter()
            need_raw=state=='LOST' or self.raw_required is None or self.raw_required()
            from v113_live_preview import source_snapshot
            raw=source_snapshot(self.camera,frame) if need_raw else None
            if raw is not None:raw.setflags(write=False)
            raw_s=time.perf_counter()-raw_begin
            row=dict(index=index,camera_sequence=int(frame.sequence),capture_ready_at=float(frame.ready),
                camera_timestamp=float(frame.timestamp),verified_at=used['verified_at'],state=state,corners=used['corners'],
                color_mode=int(self.camera.color_mode),output_size=used['size'],tiles=len(used['tiles']),
                admission_mode='manual',automatic_edge_proof=False,
                manual_tracking=self.tracker.kind,
                manual_tracker_baseline='physical_native_v5' if getattr(self.tracker,'physical',False) else 'V87_exact_persistent',manual_tracker_retired=self.manual_retired,
                source_snapshot_s=raw_s,source_snapshot_owned=raw is not None,source_snapshot_skipped=raw is None,
                recovery_active=self.recovery is not None,candidate_corners=candidate,candidate_ready_at=candidate_ready,
                manual_motion_proved=bool(track.get('manual_motion_proved')),track_reason=track.get('reason') or failure,
                manual_static_hold=bool(track.get('static_hold',False)),
                manual_fail_streak=self.manual_streak,
                tracker_s=track['tracker_s'],tracker_thread_cpu_s=track['tracker_thread_cpu_s'],
                ps_prepare_s=time.perf_counter()-begin,ps_thread_cpu_s=time.thread_time()-cpu,
                ps_prepared_at=time.perf_counter(),capture_wait_s=begin-capture,held_age_s=age,
                layout_generation=used.get('layout_generation',0),orientation=used.get('orientation'),
                proof_s=plan.get('proof_s',0.),proof_thread_cpu_s=plan.get('proof_thread_cpu_s',0.))
            if index==1 or index%60==0:row.update(manual_track_detail=track,plan_detail=plan)
            if self.reference_tracking:
                from v116_continuity import mark_continuity,continuity_cancelled
                row.update(manual_reference_v17=True,hybrid_epoch=0,target_cycle_state='PRESENT',manual_tracker_baseline='manual_reference17')
                if valid:self.continuity_blocked=False
                elif continuity_cancelled(row):self.continuity_blocked=True
                mark_continuity(row,bool(used['tiles']) and not self.continuity_blocked,time.perf_counter())
            return FrameJob(index,frame,used['tiles'],used['size'],state,used['corners'],self.camera.color_mode,raw,row,
                source_owned=raw is not None)
        except BaseException:frame.release();raise
    def close(self):
        if self.closed:return
        self.workers_stopped=True
        if self.recovery is not None:
            try:self.recovery.close();self.recovery=None
            except BaseException:
                self.workers_stopped=False;raise
        errors=[]
        for name,item in [('automatic',self.automatic),('manual_tracker',self.tracker),('plan_workspace',self.plan_workspace)]:
            if item is not None:
                try:item.close()
                except BaseException as exc:
                    errors.append((name,repr(exc)))
                    if name=='automatic':self.workers_stopped=False
        if errors:raise RuntimeError('Manual frontend cleanup incomplete: '+str(errors))
        self.closed=True


def _select(context,camera,deadline):
    if getattr(context.ticket,'ai',False):
        from v102_ai_selection import select_live
        return select_live(context,camera,deadline)
    from v79_acquire import OwnedFrame
    display=context.display;raw=None;transfer=getattr(context,'camera_transfer',None);warming=not bool(transfer and transfer.stabilized);warm_begin=time.perf_counter();observed=0
    while True:
        context.check()
        if time.perf_counter()>=deadline:raise TimeoutError('Manual calibration session ended')
        try:frame=camera.take(.15)
        except TimeoutError:continue
        try:
            if transfer is not None and float(frame.ready)<transfer.ready_after:continue
            observed+=1
            if warming and observed<12 and time.perf_counter()-warm_begin<.6:continue
            warming=False
            raw=np.array(frame.image,copy=True,order='C');raw.setflags(write=False)
            frozen=OwnedFrame(raw,float(frame.ready),int(frame.sequence),float(frame.timestamp),int(frame.flags))
        finally:frame.release()
        # Manual editing owns this still; do not add capture-side copies to its
        # subsequent healthy tracking path, especially rectified-only mode.
        camera.live_preview=None
        if not display.inspection.begin_calibration(raw,camera.color_mode,context.generation,frozen.sequence):context.check()
        while True:
            context.check()
            if time.perf_counter()>=deadline:raise TimeoutError('Manual calibration session ended')
            if display.error is not None:raise display.error
            action=display.inspection.take_action(context.generation)
            if action is not None:
                if action[0]=='refresh':break
                if action[0]=='auto':
                    from v75_ui import UIReturnRequested
                    raise UIReturnRequested()
                if action[0]=='confirm':
                    camera._p11_stream_stabilized=True
                    return frozen,action[1]
            with display.condition:display.condition.wait(.10)


def run_manual(context,device='/dev/video0',width=640,height=480,fps=30,
               output_size=(362,512),max_frames=0,warmup_frames=5,deadline=None,options=None):
    """New serialized UI session; original device and display owners are reused."""
    from v31_camera import CameraSource
    from v31_pixels import set_color_mode
    from v75_ui import UIReturnRequested
    from v64_camera_hdmi import PrepareQueue,FrameJob
    from v73_ratio import make_orientation as DualOrientation
    from v64_io import PlanWorkspace
    from v64_p1_backend import make_plan,ProofCache
    options=dict(options or {});backend=context.backend;display=context.display;backend._assert_owner()
    options['_ai_physical_profile']=bool(getattr(context.ticket,'ai',False))
    deadline=float('inf') if deadline is None else float(deadline)
    camera=front=queue=first=workspace=job=budget=None;failure=None;cleanup=[];fixed=False
    n=manual=current=held=lost=manual_tracked=manual_fixed=0;began=None;ended=None;rows=deque(maxlen=512);times=deque(maxlen=120);current_times=deque(maxlen=120)
    snapshot=context.ticket.page=='snapshot';stopped=False;epoch=None
    from v110_unified import CurrentRate
    completed_rate=CurrentRate();is_ai=bool(getattr(context.ticket,'ai',False))
    try:
        context.check();retained=context.ticket.fixed_input if snapshot else None
        if retained is not None:
            from v84_snapshot import select_fixed
            color_mode=int(retained.color_mode);set_color_mode(color_mode)
            checkpoint('MANUAL_SESSION_BEGIN',generation=context.generation,snapshot=True,
                camera=None,fixed_source_reused=True,camera_opened=False,
                automatic_edge_proof=False,hardware_checks_preserved=True)
            first,q=select_fixed(context,retained,deadline)
        if first is None:
            from v101_ai_camera import claim,finish_previous_budget
            transfer=claim(context,device,width,height,fps,options.get('color_mode'))
            if transfer is not None:finish_previous_budget(transfer)
            camera=transfer.camera if transfer is not None else CameraSource(device,width,height,fps,options.get('color_mode'))
            context.camera_transfer=transfer
            if transfer is not None:
                checkpoint('MANUAL_CAMERA_REUSED',generation=context.generation,camera_reopened=False,
                    stream_reconfigured=transfer.reconfigured,initial_stabilization_repeated=not transfer.stabilized)
            color_mode=int(camera.color_mode);set_color_mode(color_mode)
            if is_ai and not snapshot:
                from v113_live_preview import bind_preview
                bind_preview(camera,display,context.generation)
            checkpoint('MANUAL_CAMERA_REOPENED' if retained is not None else 'MANUAL_SESSION_BEGIN',generation=context.generation,snapshot=snapshot,
                camera=camera.metadata(),fixed_source_reused=False,camera_opened=transfer is None,
                ai_camera_reused=transfer is not None,
                automatic_edge_proof=False,hardware_checks_preserved=True)
            if is_ai and not snapshot:
                first=q=None
                checkpoint('RECOVERY_EXPLICIT_AI_ENTRY',generation=context.generation,
                    same_live_controller=True,blocking_selector_bypassed=True)
            else:first,q=_select(context,camera,deadline)
        # Setup is shared with the app. Keep the frozen selection visible and
        # never consume a second camera lease while waiting for CPU readiness.
        while not context.native_setup.done.is_set():
            context.check()
            if time.perf_counter()>=deadline:raise TimeoutError('Manual native setup deadline')
            context.native_setup.done.wait(.10)
        context.native_setup.result();context.check()
        if not is_ai:
            service=getattr(display,'ai_service',None)
            if service is not None:service.prepare_live()
        display.inspection.end_calibration(context.generation);context.set_phase('running')
        epoch=display.begin_measurement();began=time.perf_counter()
        if snapshot:
            orientation=DualOrientation(options.get('output_orientation','auto_two'),output_size,2)
            proposal=orientation.propose(q,first.image.shape,0,timestamp=float(first.ready));q=proposal.quad
            size=tuple(proposal.size or output_size);workspace=PlanWorkspace()
            tiles,plan=make_plan(q,first.image.shape,size,proof_cache=ProofCache(128),
                strategy=options.get('plan_strategy','fast_safe'),proof_cpu_budget_s=float(options.get('proof_cpu_budget_ms',12.))/1000.,workspace=workspace)
            orient=orientation.commit(proposal)
            row=dict(index=1,camera_sequence=first.sequence,capture_ready_at=first.ready,verified_at=first.ready,
                state='MANUAL',corners=tuple(map(tuple,q.tolist())),color_mode=color_mode,
                admission_mode='manual',manual_tracking='SNAPSHOT',manual_fps=0.,correction_fps=0.,
                correction_origin='AI' if is_ai else 'MANUAL',hybrid_valid_fps=0.,
                ui_generation=context.generation,layout_generation=orient.get('layout_generation',0),orientation=orient.get('orientation'))
            from v84_snapshot import remember_fixed_source
            remember_fixed_source(context,first.image,first,color_mode)
            job=FrameJob(1,first,tuple(tiles),size,'MANUAL',row['corners'],color_mode,first.image,row)
            image,owner=backend.execute(job);context.check();display.offer(image,row,first.image);job.release_source()
            receipt=display.wait_snapshot(context.generation,1,first.sequence,context.cancel)
            if receipt is None:context.check();raise RuntimeError('Manual snapshot submission not confirmed')
            fixed=True;n=manual=1;rows.append(dict(row,**owner));ended=time.perf_counter()
        else:
            if is_ai:
                from v111_recovery import HybridFrontend
                from v86_tracking import create_frontend
                def automatic_factory(frame,detection):
                    return create_frontend(camera,frame,detection,output_size,int(options.get('tracking_max_dim',320)),
                        int(options.get('detection_max_dim',640)),float(options.get('hold_max_age_s',1.5)),
                        6,30,options.get('output_orientation','auto_two'),float(options.get('reacquire_budget_ms',420.)),
                        options.get('plan_strategy','fast_safe'),float(options.get('proof_cpu_budget_ms',12.)),False,70.)
                front=HybridFrontend(camera,output_size,options,context,automatic_factory,ai_first=True,
                    target_selection=context.ticket.target_selection)
                context.ticket.target_selection=None
                front.raw_required=display.needs_raw_source
            else:
                from v113_live_preview import bind_preview
                bind_preview(camera,display,context.generation)
                front=ManualFrontend(camera,first,q,output_size,dict(options,_manual_reference_v17=True),raw_required=display.needs_raw_source)
            if first is not None:first.release();first=None
            from v31_gc_budget import GcBudget
            budget=GcBudget(options.get('gc_policy','bounded'),240,30.);budget.__enter__()
            queue=PrepareQueue(front,max_frames or 2147483647,0);queue.allow_measured()
            from v118_display_continuity import OwnerContinuity
            continuity=OwnerContinuity(front,backend,display,context)
            queue.idle_callback=continuity.pump
            for index in range(1,(max_frames or 2147483647)+1):
                context.check()
                if time.perf_counter()>=deadline:break
                job=queue.take(index,context.cancel);row=dict(job.record)
                try:
                    context.check()
                    if job.state=='LOST':image=None;owner=dict(owner_s=0.)
                    else:image,owner=backend.execute(job,queue.peek)
                    now=time.perf_counter()
                    if is_ai and row.get('hybrid_epoch')!=front.epoch:
                        job.state='HELD' if image is not None else 'LOST';row['state']=job.state
                        row['continuity_output']=False
                    n+=1;manual+=int(job.state=='MANUAL');current+=int(job.state=='CURRENT')
                    held+=int(job.state in ('MANUAL_HELD','HELD'));lost+=int(job.state=='LOST')
                    if job.state=='MANUAL':
                        if row.get('manual_motion_proved'):manual_tracked+=1;times.append(now)
                        elif row.get('manual_tracking')=='FIXED':manual_fixed+=1
                    if job.state=='CURRENT':current_times.append(now)
                    while times and times[0]<now-2.:times.popleft()
                    while current_times and current_times[0]<now-2.:current_times.popleft()
                    row.update(owner,ui_generation=context.generation,manual_fps=len(times)/2.,correction_fps=len(current_times)/2.,
                        capture_to_output_s=now-job.record['capture_ready_at'],output_ready_at=now)
                    if is_ai:
                        front.completed(row,now);row['hybrid_valid_fps']=front.rate.fps(now)
                        if row.get('hybrid_epoch')==front.epoch:row['hybrid_phase']=front.phase
                    else:
                        completed_rate.observe(row,now)
                        row.update(correction_origin='MANUAL',hybrid_valid_fps=completed_rate.fps(now))
                    display.offer(image,row,job.source_snapshot,raw_owned=job.source_owned,
                        output_reference=backend.output_reference(image));row.update(display.last_offer_timing)
                    continuity.remember(job,row)
                    rows.append(row);budget.check(index)
                    frame_record('V64_FRAME' if row.get('recovered_from_manual') else 'MANUAL_FRAME',**row)
                    if owner.get('stop_requested'):stopped=True;break
                finally:job.release_source();job=None
            ended=time.perf_counter()
    except UIReturnRequested:stopped=True;ended=time.perf_counter()
    except BaseException as exc:failure=exc;ended=time.perf_counter()
    finally:
        producer_stopped=True;camera_closed=camera is None
        if queue is not None:
            try:queue.close()
            except BaseException as exc:cleanup.append(('manual_prepare',repr(exc)));producer_stopped=False
        if job is not None:
            try:job.release_source()
            except BaseException as exc:cleanup.append(('manual_job',repr(exc)))
        if first is not None:first.release()
        if producer_stopped:
            for name,item in [('manual_frontend',front),('manual_workspace',workspace)]:
                if item is not None:
                    try:item.close()
                    except BaseException as exc:cleanup.append((name,repr(exc)))
            # A failed worker join must keep camera/native storage pinned.
            if front is None or front.workers_stopped:
                if camera is not None:
                    try:
                        if not backend.active:camera.retire_consumers((queue.worker,) if queue is not None else (),current_owner_retired=True)
                        preserved=False
                        hot=getattr(context,'hot',None)
                        if hot is not None and stopped and failure is None and not cleanup:
                            from v75_hotswitch import camera_key
                            preserved=hot.offer(context,camera,camera_key(device,width,height,fps,options.get('color_mode')),budget,
                                readers_retired=producer_stopped,backend_idle=not backend.active and not backend.failed,
                                admitted=first is not None or n>0)
                        if preserved:budget=None
                        else:camera.close();camera_closed=True
                    except BaseException as exc:cleanup.append(('manual_camera',repr(exc)))
        if cleanup:
            import v64_camera_hdmi as camera_module
            camera_module._POISONED=True;camera_module._POISON_REASON=list(camera_module._POISON_REASON)+cleanup
            _RETAINED.append((queue,front,workspace,camera,first,job,backend,display))
        if budget is not None:budget.__exit__(None,None,None)
        checkpoint('MANUAL_SESSION_END',generation=context.generation,manual_corrections=manual,
            automatic_current=current,held=held,lost=lost,camera_closed=camera_closed,camera_opened=camera is not None,errors=cleanup)
    if failure is not None:raise failure
    if cleanup:raise RuntimeError('Manual cleanup incomplete: '+str(cleanup))
    elapsed=max(0.,(ended or time.perf_counter())-began) if began is not None else 0.
    display_summary=display.snapshot(include_samples=False)
    ds=display_summary.get('epoch_stats',{}).get(str(epoch),{})
    display_elapsed=max(0.,max(ended or 0.,ds.get('last_submitted_at',0.))-began) if began is not None else 0.
    return dict(release_id=RELEASE_ID,status='captured' if fixed else 'stopped' if stopped else 'completed',
        frames=n,current=current,held=held,lost=lost,delivered=current+manual+held,manual_corrections=manual,
        manual_fps=manual_tracked/elapsed if elapsed and not fixed else 0.,fixed_frame=fixed,user_interrupted=False,
        manual_tracked_corrections=manual_tracked,manual_fixed_corrections=manual_fixed,
        current_correction_fps=current/elapsed if elapsed and not fixed else 0.,delivered_fps=(current+manual+held)/elapsed if elapsed and not fixed else 0.,
        hdmi_current_fps=ds.get('current',0)/display_elapsed if display_elapsed and not fixed else 0.,
        hdmi_submit_fps=ds.get('submitted',0)/display_elapsed if display_elapsed and not fixed else 0.,
        hdmi_current_submitted=ds.get('current',0),hdmi_submitted=ds.get('submitted',0),
        formal_elapsed_s=elapsed,formal_display_elapsed_s=display_elapsed,display=display_summary,timing={},hdmi_timing={},
        admission_mode=('ai_snapshot' if fixed else 'ai_seed_manual_with_auto_recovery') if is_ai else 'manual_locked',automatic_edge_proof=False,rows=list(rows))
