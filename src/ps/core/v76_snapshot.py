"""One admitted camera frame, one complete P1 correction, then static HDMI."""
from pathlib import Path
import hashlib,time
import numpy as np
from p11_contract import RELEASE_ID,verify_package
from run_logging import checkpoint
from v31_camera import CameraSource
from v31_pixels import set_color_mode
from v79_acquire import pump_acquisition
from v87_acquire import V74Acquire as LiveAcquire
from v79_setup import wait_native_with_preview,wait_for_placement
from v31_detection import detect_refined
from v31_native import prepare_native
from v73_ratio import make_orientation as DualOrientation
from v64_camera_hdmi import FrameJob
from v64_io import PlanWorkspace,prepare_io
from v64_p1_backend import make_plan,ProofCache
from v75_ui import UIReturnRequested

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]


class _CancelableCamera:
    def __init__(self,camera,check):self.camera=camera;self.check=check
    def __getattr__(self,name):return getattr(self.camera,name)
    def take(self,timeout=3.):
        until=time.perf_counter()+float(timeout)
        while True:
            self.check()
            remaining=until-time.perf_counter()
            if remaining<=0:raise TimeoutError('No valid single-frame input before deadline')
            try:frame=self.camera.take(min(remaining,.2))
            except TimeoutError:continue
            try:self.check()
            except BaseException:frame.release();raise
            return frame


def capture_one(context,device='/dev/video0',width=640,height=480,fps=30,
                output_size=(362,512),capture_timeout_s=20.,options=None,app_deadline=None):
    """Called by the existing device owner, without a second logger or overlay."""
    options=dict(options or {});backend=context.backend;display=context.display
    backend._assert_owner();context.check();verify_package(str(backend.path))
    if backend.active or backend.failed or backend.closed:raise RuntimeError('Snapshot backend is unsafe')
    if (backend.input_shape!=(height,width) or display.ui_view!='snapshot' or
            display.ui_generation!=context.generation):
        context.check();raise ValueError('Single-frame UI/input context mismatch')
    strategy=options.get('plan_strategy','fast_safe');proof_ms=float(options.get('proof_cpu_budget_ms',12.))
    if strategy not in ('fast_safe','exact_reference') or not 2<=proof_ms<=30:
        raise ValueError('Invalid single-frame hardware proof settings')
    if int(options.get('opencv_threads',1))!=1:raise ValueError('Single-frame mode requires one OpenCV thread')
    startup_s=float(options.get('startup_timeout_s',6.))
    attempts=options.get('startup_detect_attempts',6)
    began=time.perf_counter();deadline=float('inf') if app_deadline is None else float(app_deadline)
    def check():
        context.check()
        if time.perf_counter()>=deadline:raise TimeoutError('Single-frame capture deadline exceeded')
    check()
    checkpoint('SNAPSHOT_BEGIN',generation=context.generation,persistent_image_save=False,
        correction_policy='one admitted source image; complete proved tiles',capture_timeout_s=float(capture_timeout_s))
    camera=first=workspace=job=image=raw=acquirer=native_setup=None;failure=None;cleanup=[];receipt=None
    transfer=None;camera_preserved=False;camera_end={};camera_closed=False;owner={};stage='native_setup';completed=False
    try:
        stage='camera_open'
        from v75_hotswitch import camera_key
        hot=getattr(context,'hot',None)
        transfer=hot.claim(context,camera_key(device,width,height,fps,options.get('color_mode'))) if hot is not None else None
        if transfer is not None:
            from v101_ai_camera import finish_previous_budget
            finish_previous_budget(transfer);camera=transfer.camera
        else:
            checkpoint('CAMERA_OPEN_BEGIN',device=device,width=width,height=height,fps=fps,single_frame=True)
            camera=CameraSource(device,width,height,fps,options.get('color_mode'))
        set_color_mode(camera.color_mode);check()
        checkpoint('CAMERA_READY',durable=True,**camera.metadata(),no_jpeg_decoder=True,single_frame=True)
        stage='visible_native_setup'
        native_setup=context.native_setup
        status=wait_native_with_preview(native_setup,camera,display,check,lambda:context.generation,
            deadline=deadline,context=context)
        checkpoint('NATIVE_READY',**status);check()
        stage='placement_confirmation'
        wait_for_placement(camera,display,check,lambda:context.generation,deadline=deadline,context=context)
        context.set_phase('acquiring')
        # Compile/load time does not consume the single-image selection budget.
        deadline=min(deadline,time.perf_counter()+float(capture_timeout_s))
        stage='live_acquisition'
        def acquire_phase(phase):
            if phase=='SEARCHING':camera._p11_stream_stabilized=True
        acquirer=LiveAcquire(options.get('detection_max_dim',640),options.get('tracking_max_dim',320),recovery=bool(transfer and transfer.stabilized),phase_report=acquire_phase)
        first,detection,_,admission=pump_acquisition(acquirer,camera,display,check,
            lambda:context.generation,deadline=deadline,context=context,already_running=bool(transfer and transfer.stabilized),ready_after=transfer.ready_after if transfer else None)
        acquirer.close();acquirer=None
        stability=dict(policy='V74_12_150_4_stabilization_then_original_admission',
            live_preview_during_acquisition=True,startup_stability=admission.get('startup_stability'))
        check()
        # Keep the admitted candidate and its exact leased image together.
        # No video tracker/recovery producer is started for a still image.
        stage='current_plan'
        orientation=DualOrientation(options.get('output_orientation','auto_two'),output_size,2)
        proposal=orientation.propose(detection[0],first.image.shape,0,timestamp=float(first.ready))
        q=proposal.quad;size=tuple(proposal.size or output_size)
        if size[0]*size[1]>backend.output_capacity:raise ValueError('Snapshot output exceeds persistent capacity')
        workspace=PlanWorkspace()
        tiles,plan=make_plan(q,first.image.shape,size,proof_cache=ProofCache(128),strategy=strategy,
            proof_cpu_budget_s=proof_ms/1000.,workspace=workspace)
        orient=orientation.commit(proposal);check()
        # execute may return a single-tile MMAP lease immediately after packing.
        # Preserve provenance first, so display never reads a requeued camera buffer.
        raw=np.empty(first.image.shape,np.uint8);np.copyto(raw,first.image)
        row=dict(index=1,camera_sequence=int(first.sequence),state='CURRENT',
            corners=tuple(map(tuple,q.tolist())),color_mode=int(camera.color_mode),
            capture_ready_at=float(first.ready),verified_at=float(first.ready),correction_fps=0.,
            layout_generation=orient.get('layout_generation',0),orientation=orient.get('orientation'),
            ui_generation=context.generation)
        job=FrameJob(1,first,tuple(tiles),size,'CURRENT',row['corners'],camera.color_mode,raw,row)
        epoch=display.begin_measurement();hardware_began=time.perf_counter();check()
        stage='hardware_correction'
        image,owner=backend.execute(job)
        row.update(owner,output_ready_at=time.perf_counter())
        if owner.get('stop_requested',False):raise KeyboardInterrupt()
        check();stage='display_submission';context.set_phase('running')
        from v84_snapshot import remember_fixed_source
        remember_fixed_source(context,raw,first,camera.color_mode)
        display.offer(image,row,raw)
        job.release_source()
        receipt=display.wait_snapshot(context.generation,1,row['camera_sequence'],context.cancel)
        if receipt is None:
            context.check();raise RuntimeError('Single-frame page changed before submission')
        if not receipt.get('paired_input',False):raise RuntimeError('Single-frame output lacks its matching original panel')
        completed=True
        timings=dict(setup_and_selection_s=hardware_began-began,owner_s=owner.get('owner_s',0.),
            owner_thread_cpu_s=owner.get('owner_thread_cpu_s',0.),capture_to_submit_s=receipt['capture_to_submit_s'])
        snapshot=dict(camera_sequence=row['camera_sequence'],output_size=list(size),corners=row['corners'],
            receipt=receipt,orientation=orient,admission=admission,stability=stability,
            tiles=len(tiles),complete_images=1,plan=plan)
    except UIReturnRequested as exc:
        failure=exc
        checkpoint('SNAPSHOT_CANCELLED',phase=stage,hardware_abort=False)
    except BaseException as exc:
        failure=exc
        checkpoint('SNAPSHOT_FAILED',durable=True,phase=stage,exception_type=type(exc).__name__,
            exception=str(exc),remap_active=backend.active,remap_failed=backend.failed)
    finally:
        checkpoint('SNAPSHOT_CLEANUP',phase='camera_stop_begin',completed=completed)
        # Application owner keeps CPU setup alive across page returns/recaptures.
        if acquirer is not None:
            try:acquirer.close()
            except BaseException as exc:cleanup.append(('initial_acquisition',repr(exc)))
        if first is not None:
            try:first.release()
            except BaseException as exc:cleanup.append(('source_lease',repr(exc)))
        if workspace is not None:
            try:workspace.close()
            except BaseException as exc:cleanup.append(('plan_workspace',repr(exc)))
        if camera is not None:
            try:camera_end=camera.metadata()
            except BaseException as exc:cleanup.append(('camera_metadata',repr(exc)))
            try:
                if not cleanup and not backend.active:camera.retire_consumers(current_owner_retired=True)
                hot=getattr(context,'hot',None)
                if hot is not None and failure is None and not cleanup:
                    from v75_hotswitch import camera_key
                    camera_preserved=hot.offer(context,camera,camera_key(device,width,height,fps,options.get('color_mode')),None,
                        readers_retired=acquirer is None,backend_idle=not backend.active and not backend.failed,admitted=completed,idle=completed)
                if not camera_preserved:camera.close();camera_closed=True
            except BaseException as exc:cleanup.append(('camera',repr(exc)))
        image=None;raw=None;job=None
        checkpoint('SNAPSHOT_CLEANUP',phase='camera_stop_end',camera_closed=camera_closed,errors=list(cleanup))
        if cleanup:
            import v64_camera_hdmi as camera_module
            camera_module._POISONED=True
            camera_module._POISON_REASON=list(camera_module._POISON_REASON)+cleanup
            _RETAINED.append((native_setup,acquirer,camera,first,workspace,backend,display))
    if failure is not None:raise failure
    if cleanup:raise RuntimeError('Single-frame cleanup incomplete: '+str(cleanup))
    if not completed or not (camera_closed or camera_preserved):raise RuntimeError('Single-frame result is not ready to hold')
    checkpoint('SNAPSHOT_READY',durable=True,generation=context.generation,sequence=snapshot['camera_sequence'],
        output_size=snapshot['output_size'],camera_closed=camera_closed,camera_preserved=camera_preserved,images_saved=0,complete_images=1,
        layout='original_left_rectified_right',same_captured_frame=True,
        held_until='top-left return or application exit',submission=receipt)
    # No pixels, MMAP views or CMA views escape into session history.
    return dict(release_id=RELEASE_ID,status='captured',fixed_frame=True,user_interrupted=False,
        frames=1,current=1,held=0,lost=0,delivered=1,formal_elapsed_s=time.perf_counter()-began,
        current_correction_fps=0.,delivered_fps=0.,hdmi_current_fps=0.,hdmi_submit_fps=0.,
        timing=timings,hdmi_timing={},snapshot=snapshot,camera=camera_end,images_saved=0,
        fps_scope='single still; FPS not applicable; physical scan repeats are not deliveries')
