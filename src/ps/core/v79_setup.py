"""CPU-only native setup behind a live raw view; cancellable child processes."""
from pathlib import Path
from contextvars import copy_context
import hashlib,os,signal,subprocess,tempfile,threading,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class NativeSetupCancelled(Exception):pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise NativeSetupCancelled('Native setup cancelled by session owner')


def _retire_child(child):
    if child.poll() is not None:return
    if os.name=='posix':
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    else:child.terminate()
    try:child.wait(1.)
    except subprocess.TimeoutExpired:
        if os.name=='posix':
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        else:child.kill()
        child.wait(2.)


def setup_command(command,timeout,cancel,stage):
    """No shell, preexec hook, device handles or compiler stdout PIPE deadlock."""
    check_cancel(cancel);begin=time.perf_counter();child=None;next_log=begin+3.
    checkpoint(stage+'_BEGIN',program=Path(command[0]).name,timeout_s=float(timeout),hardware_access=False)
    with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
        try:
            child=subprocess.Popen(command,stdout=output,stderr=errors,start_new_session=os.name=='posix')
            if stage.endswith('BUILD') and hasattr(os,'setpriority'):
                try:os.setpriority(os.PRIO_PROCESS,child.pid,8)
                except (OSError,AttributeError):pass
            while child.poll() is None:
                check_cancel(cancel);now=time.perf_counter()
                if now-begin>=timeout:raise subprocess.TimeoutExpired(command,timeout)
                if now>=next_log:
                    checkpoint(stage+'_PROGRESS',elapsed_s=now-begin,raw_preview_expected=True,hardware_access=False)
                    next_log=now+3.
                if cancel is None:time.sleep(.05)
                elif cancel.wait(.05):check_cancel(cancel)
            check_cancel(cancel)
            output.seek(0,2);output.seek(max(0,output.tell()-8000))
            errors.seek(0,2);errors.seek(max(0,errors.tell()-8000))
            stdout=output.read().decode('utf-8',errors='replace');stderr=errors.read().decode('utf-8',errors='replace')
            checkpoint(stage+'_END',returncode=child.returncode,elapsed_s=time.perf_counter()-begin,
                error_tail=stderr[-2000:] if child.returncode else None)
            return subprocess.CompletedProcess(command,child.returncode,stdout,stderr)
        except BaseException as exc:
            if child is not None:_retire_child(child)
            checkpoint(stage+'_ABORTED',exception_type=type(exc).__name__,exception=str(exc),
                elapsed_s=time.perf_counter()-begin,owned_child_retired=child is None or child.poll() is not None)
            raise


class NativeSetup:
    """Only compiles/loads CPU helpers; never operates camera, MMIO or VDMA."""
    def __init__(self):
        self.cancel=threading.Event();self.done=threading.Event();self.error=None;self.status=None
        self.context=copy_context();self.thread=None
        self.started_at=None;self.finished_at=None;self.trigger=None
    @property
    def elapsed_s(self):
        return 0. if self.started_at is None else max(0.,(self.finished_at or time.perf_counter())-self.started_at)
    def start(self,trigger='raw_preview'):
        check_cancel(self.cancel)
        if self.thread is not None:return
        self.started_at=time.perf_counter();self.trigger=trigger
        self.thread=threading.Thread(target=self._entry,name='p11-native-startup',daemon=True);self.thread.start()
    def _entry(self):
        try:self.context.run(self._run)
        except NativeSetupCancelled:
            checkpoint('NATIVE_SETUP_CANCELLED',owned_subprocess_retirement_requested=True,hardware_access=False)
        except BaseException as exc:
            self.error=exc
            checkpoint('NATIVE_SETUP_FAILED',durable=True,exception_type=type(exc).__name__,exception=str(exc),hardware_access=False)
        finally:self.finished_at=time.perf_counter();self.done.set()
    def _run(self):
        from v31_native import prepare_native
        from v64_io import prepare_io,_BUILD_INFO
        began=time.perf_counter();checkpoint('NATIVE_SETUP_BEGIN',background=True,
            raw_preview_already_submitted=self.trigger=='raw_preview',trigger=self.trigger)
        io_begin=time.perf_counter();library=prepare_io(cancel=self.cancel)
        checkpoint('IO_LOAD_END',abi=6601,path=str(library._name))
        checkpoint('P1_IO_READY',abi=6601,path=str(library._name),setup_s=time.perf_counter()-io_begin,
            neon=bool(library.p11_v66_caps()&1),outside_frame_measurement=True,cpu_only=True,hardware_modified=False)
        checkpoint('PS_PREPARE_READY',plan_abi=int(library.p11_v70_plan_abi()),light_results=True,
            geometry_batch=bool(library.p11_v70_geometry_available()),build=dict(_BUILD_INFO),
            outside_frame_measurement=True)
        self.status=prepare_native(required=False,cancel=self.cancel)
        from v87_v74_native import prepare_native as prepare_V74_detector
        self.status['V74_detector']=prepare_V74_detector(required=False,cancel=self.cancel)
        checkpoint('V87_V74_NATIVE_READY',**self.status['V74_detector'])
        from v84_color import prepare_color_runtime
        self.status['color_setup']=prepare_color_runtime(self.cancel)
        from v91_native import prepare_transactions
        addon=prepare_transactions(cancel=self.cancel)
        self.status['V91_transactions']=dict(available=addon is not None,abi=9101,
            original_four_libraries_unchanged=True,small_addon_only=True)
        checkpoint('NATIVE_SETUP_END',elapsed_s=time.perf_counter()-began,backend=self.status.get('backend'),
            already_loaded=self.status.get('already_loaded',False))
    def result(self):
        if not self.done.is_set():raise RuntimeError('Native setup has not completed')
        if self.error is not None:raise RuntimeError('Native setup failed: '+type(self.error).__name__+': '+str(self.error)) from self.error
        if self.status is None:raise NativeSetupCancelled('Native setup retired before producing a status')
        return dict(self.status)
    def close(self):
        self.cancel.set()
        if self.thread is not None:
            self.thread.join(5.)
            if self.thread.is_alive():raise TimeoutError('Native setup has not retired; CPU worker retained')


def startup_meta(context,phase,worker=None):
    ticket=context.ticket if context is not None else None
    return dict(ui_startup_phase=phase,placement_required=bool(ticket is not None and ticket.placement_required),
        placement_confirmed=bool(ticket is not None and ticket.placement.is_set()),
        native_setup_elapsed_s=worker.elapsed_s if worker is not None else 0.)


def wait_native_with_preview(worker,camera,display,check,generation,deadline=None,context=None):
    """Single producer; release camera leases after display owns its raw copy."""
    began=time.perf_counter();last_frame=began;next_offer=0.;offered=0;started=worker.thread is not None
    if context is not None:context.set_phase('preparing')
    if started:checkpoint('NATIVE_SETUP_REUSED',done=worker.done.is_set(),elapsed_s=worker.elapsed_s,hardware_access=False)
    with display.condition:initial_panels=display.panels_submitted
    while True:
        check();now=time.perf_counter()
        if deadline is not None and now>=deadline:raise TimeoutError('Native startup reached session deadline')
        if display.error is not None:raise display.error
        if started and worker.done.is_set():return worker.result()
        if not started:
            with display.condition:
                submitted=display.panels_submitted>initial_panels and display.ui_generation==generation()
            if submitted:
                checkpoint('RAW_PREVIEW_FIRST_SUBMITTED',elapsed_s=now-began,preview_offers=offered,
                    generation=generation(),physical_panel_scan_measured=False)
                worker.start();started=True
            elif now-began>3. and offered:
                raise TimeoutError('Raw camera frames were offered but HDMI submission was not confirmed')
        try:frame=camera.take(.1)
        except TimeoutError:
            if time.perf_counter()-last_frame>3.:raise TimeoutError('No valid camera frame during visible native startup')
            continue
        try:
            now=time.perf_counter();last_frame=now
            if now>=next_offer:
                display.offer(None,dict(index=-2,camera_sequence=int(frame.sequence),state='INITIALIZING',corners=(),
                    color_mode=int(camera.color_mode),verified_at=0.,capture_ready_at=float(frame.ready),
                    correction_fps=0.,ui_generation=generation(),**startup_meta(context,'preparing',worker)),frame.image)
                offered+=1;next_offer=now+.125
        finally:frame.release()


def wait_for_placement(camera,display,check,generation,deadline=None,context=None):
    """Legacy call name retained; automatic current-frame admission never waits for touch."""
    check()
    if context is not None:context.set_phase('acquiring')
    checkpoint('AUTOMATIC_ADMISSION_BEGIN',generation=generation(),confirmation_required=False,
        skipped_validation=False,strict_current_admission=True)
