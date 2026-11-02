"""One ordered run-result.log writer; JSON encoding is off the hardware owner."""
from pathlib import Path
from contextlib import redirect_stdout,redirect_stderr,contextmanager
from contextvars import ContextVar
from functools import wraps
from collections import deque
from collections.abc import Mapping
import datetime,hashlib,inspect,json,os,sys,threading,time,traceback,queue
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
RUN_LOG=Path(__file__).resolve().parent/'run-result.log'
_CURRENT=ContextVar('p11_current_run_log',default=None)
_ACTIVE_FILE=ContextVar('p11_active_log_file',default=None)
_BUSY=threading.Lock()
_FRAME_POLICY=ContextVar('p11_frame_log_policy',default=('detailed',30,.120))
_DETAIL_SAMPLE=ContextVar('p11_detail_sample',default=None)

def _stderr_notice(value):
    try:
        stream=sys.__stderr__ or getattr(sys.stderr,'console',sys.stderr)
        stream.write(value);stream.flush()
    except BaseException:pass

def _json_default(value):
    if isinstance(value,Path):return str(value)
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,np.ndarray):return value.tolist()
    if type(value).__module__=='p11_runtime' and hasattr(value,'path'):
        return dict(type=type(value).__name__,bitfile=str(value.path))
    if callable(value):return getattr(value,'__qualname__',repr(value))
    return repr(value)

def _owned_payload(value):
    """Detach small record metadata before queuing; never retain mutable DMA views."""
    if value is None or isinstance(value,(str,int,float,bool)):return value
    if isinstance(value,Mapping):return {k:_owned_payload(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return tuple(_owned_payload(v) for v in value)
    if isinstance(value,np.ndarray):return value.tolist()
    return _json_default(value)

class _Writer:
    def __init__(self):
        self.queue=queue.Queue(maxsize=64);self.error=None;self.closed=False
        self.io_events=deque(maxlen=512);self.io_events_dropped=0
        self.stats_lock=threading.Lock()
        self.stats=dict(records=0,bytes=0,serialize_s=0.,serialize_cpu_s=0.,serialize_max_s=0.,
            snapshot_s=0.,snapshot_cpu_s=0.,snapshot_max_s=0.,
            enqueue_s=0.,enqueue_cpu_s=0.,enqueue_max_s=0.,queue_max=0,
            write_s=0.,write_cpu_s=0.,write_max_s=0.,flush_s=0.,flush_cpu_s=0.,flush_max_s=0.,
            fsync_s=0.,fsync_cpu_s=0.,fsync_max_s=0.,sync_count=0,barrier_wait_s=0.,
            serialize_scope='writer_thread',producer_scope='metadata_snapshot_and_bounded_enqueue')
        self.worker=threading.Thread(target=self._run,name='run_log_writer',daemon=True)
        self.worker.start()

    def _put(self,item):
        began=time.perf_counter();cpu=time.thread_time()
        while True:
            if self.error:raise RuntimeError('日志写入线程失败') from self.error
            if self.closed:raise RuntimeError('日志队列已关闭')
            try:self.queue.put(item,timeout=.1);break
            except queue.Full:
                if not self.worker.is_alive():raise RuntimeError('日志线程已退出')
        elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
        with self.stats_lock:
            self.stats['enqueue_s']+=elapsed;self.stats['enqueue_cpu_s']+=used
            self.stats['enqueue_max_s']=max(self.stats['enqueue_max_s'],elapsed)
            self.stats['queue_max']=max(self.stats['queue_max'],self.queue.qsize())

    def record(self,payload):
        began=time.perf_counter();cpu=time.thread_time()
        owned=_owned_payload(payload)
        elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
        with self.stats_lock:
            self.stats['snapshot_s']+=elapsed;self.stats['snapshot_cpu_s']+=used
            self.stats['snapshot_max_s']=max(self.stats['snapshot_max_s'],elapsed)
        self._put(('record',owned,None))

    def snapshot(self):
        with self.stats_lock:return dict(self.stats)

    def write(self,value):
        if value:self._put(('write',str(value),None))
        return len(value)

    def flush(self):
        if self.error:raise RuntimeError('日志文件错误') from self.error

    def barrier(self,durable=False):
        done=threading.Event();began=time.perf_counter()
        self._put(('sync' if durable else 'flush','',done))
        while not done.wait(.1):
            if self.error or not self.worker.is_alive():raise RuntimeError('日志同步失败') from self.error
            if time.perf_counter()-began>30:raise TimeoutError('日志同步超过30秒')
        with self.stats_lock:self.stats['barrier_wait_s']+=time.perf_counter()-began
        if self.error:raise RuntimeError('日志同步失败') from self.error

    def _io_event(self,kind,begin,cpu,always=False):
        end=time.perf_counter();used=time.thread_time()-cpu;wall=end-begin
        if always or wall>=.002:
            if len(self.io_events)==self.io_events.maxlen:self.io_events_dropped+=1
            self.io_events.append(dict(operation=kind,begin=begin,end=end,wall_s=wall,
                thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,wall-used),thread_id=threading.get_ident()))

    def _run(self):
        try:
            with RUN_LOG.open('a',encoding='utf-8',buffering=65536) as file:
                dirty=False;last=time.monotonic()
                def flush(durable=False):
                    began=time.perf_counter();cpu=time.thread_time();file.flush()
                    elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                    self._io_event('flush',began,cpu)
                    with self.stats_lock:
                        self.stats['flush_cpu_s']+=used;self.stats['flush_s']+=elapsed
                        self.stats['flush_max_s']=max(self.stats['flush_max_s'],elapsed)
                    if durable:
                        began=time.perf_counter();cpu=time.thread_time();os.fsync(file.fileno())
                        elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                        self._io_event('fsync',began,cpu,True)
                        with self.stats_lock:
                            self.stats['fsync_cpu_s']+=used;self.stats['fsync_s']+=elapsed
                            self.stats['fsync_max_s']=max(self.stats['fsync_max_s'],elapsed)
                            self.stats['sync_count']+=1
                while True:
                    try:kind,value,event=self.queue.get(timeout=.05)
                    except queue.Empty:
                        if dirty and time.monotonic()-last>=.5:flush();dirty=False;last=time.monotonic()
                        continue
                    try:
                        if kind in ('record','write'):
                            if kind=='record':
                                began=time.perf_counter();cpu=time.thread_time()
                                value=json.dumps(value,ensure_ascii=False,default=_json_default)+'\n'
                                elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                                with self.stats_lock:
                                    self.stats['serialize_s']+=elapsed;self.stats['serialize_cpu_s']+=used
                                    self.stats['serialize_max_s']=max(self.stats['serialize_max_s'],elapsed)
                            began=time.perf_counter();cpu=time.thread_time();file.write(value)
                            elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
                            self._io_event('write',began,cpu)
                            with self.stats_lock:
                                self.stats['records']+=1;self.stats['bytes']+=len(value.encode('utf-8'))
                                self.stats['write_s']+=elapsed;self.stats['write_cpu_s']+=used
                                self.stats['write_max_s']=max(self.stats['write_max_s'],elapsed)
                            dirty=True
                        else:flush(kind in ('sync','stop'));dirty=False;last=time.monotonic()
                        if kind=='stop':return
                        if dirty and time.monotonic()-last>=.5:flush();dirty=False;last=time.monotonic()
                    except BaseException as exc:self.error=exc;raise
                    finally:
                        if event:event.set()
                        self.queue.task_done()
        except BaseException as exc:self.error=exc

    def close(self):
        if self.closed:return
        if self.error:
            self.worker.join(1);self.closed=True
            raise RuntimeError('日志写入已经失败') from self.error
        done=threading.Event();self._put(('stop','',done));self.worker.join(30);self.closed=True
        if self.worker.is_alive():raise TimeoutError('日志线程未停止')
        if self.error:raise RuntimeError('日志关闭失败') from self.error

_CONSOLE_ENABLED=ContextVar('p11_console_enabled',default=False)

class _Tee:
    def __init__(self,console,file):self.console,self.file=console,file
    def write(self,value):
        self.file.write(value)
        return self.console.write(value) if _CONSOLE_ENABLED.get() else len(value)
    def flush(self):
        self.file.flush()
        if _CONSOLE_ENABLED.get():self.console.flush()
    def __getattr__(self,name):return getattr(self.console,name)

def current_log_metadata():return dict(_CURRENT.get() or {})
def log_metrics():
    active=_ACTIVE_FILE.get();return active.snapshot() if active else {}
def flush_log(durable=False):
    active=_ACTIVE_FILE.get()
    if active:active.barrier(durable)

@contextmanager
def frame_log_scope(mode='compact',detail_every=30,slow_ms=120.):
    if mode not in ('compact','detailed'):raise ValueError('log_mode须为compact/detailed')
    if isinstance(detail_every,bool) or not isinstance(detail_every,int) or detail_every<1:
        raise ValueError('log_detail_every须为正整数')
    if not np.isfinite(slow_ms) or slow_ms<=0:raise ValueError('log_slow_ms须为有限正数')
    token=_FRAME_POLICY.set((mode,detail_every,float(slow_ms)/1000.))
    sample_token=_DETAIL_SAMPLE.set(dict(lock=threading.Lock(),seen={},decisions={}))
    try:yield
    finally:
        _DETAIL_SAMPLE.reset(sample_token);_FRAME_POLICY.reset(token)

def _recovery_deferred(tracking):
    return (tracking.get('mode')=='lost_skip' and not tracking.get('valid',True)
            and tracking.get('recovery_attempt',{}).get('state')=='bounded_backoff')

def diagnostic_detail(index,wall=0.,tracking=None):
    """Keep first occurrence and periodic full detail, not every failed frame.

    Basic current corners/state/timings are always logged. Native/device errors
    using durable checkpoints bypass this sampler. A bounded shared ledger
    makes prepare/owner/retention choose the same detail for a frame.
    """
    mode,every,slow=_FRAME_POLICY.get();tracking=tracking or {}
    if mode=='detailed' or index==1 or index%every==0:return True
    state=_DETAIL_SAMPLE.get()
    if state is None:return False
    recovery=tracking.get('recovery_attempt',{})
    key=(tracking.get('mode'),tracking.get('tracking_state'),tracking.get('lk_trigger'),
        recovery.get('state'),recovery.get('last_stage'),wall>=slow)
    with state['lock']:
        cache_key=(index,key)
        if cache_key in state['decisions']:return state['decisions'][cache_key]
        previous=state['seen'].get(key);chosen=previous is None or index-previous>=max(every,60)
        if chosen:
            state['seen'][key]=index
            while len(state['seen'])>32:state['seen'].pop(next(iter(state['seen'])))
        state['decisions'][cache_key]=chosen
        while len(state['decisions'])>16:state['decisions'].pop(next(iter(state['decisions'])))
        return chosen

def native_os_sample(index):
    mode,every,_=_FRAME_POLICY.get()
    return mode=='detailed' or index==1 or index%every==0

def _scalars(value):
    return {k:v for k,v in value.items() if v is None or isinstance(v,(str,int,float,bool))}

def _compact_diagnostic(value):
    result=_scalars(value)
    result['native']={k:_scalars(v) for k,v in value.get('native',{}).items()}
    if 'os_thread_events' in value:result['os_thread_events']=_scalars(value['os_thread_events'])
    return result

_NORMAL_PHASES=frozenset(('FRAME_SOURCE_WAIT','FRAME_PS_BEGIN','FRAME_PS_READY','FRAME_BEGIN',
    'planner upload begin','planner exact scan done','planner import begin','planner import done'))

def frame_phase_enabled(stage):
    """Check before constructing a suppressed success-phase payload.

    Frame outcomes, current corners/timings and all error checkpoints remain
    recorded. This does not alter durable handling or throughput boundaries.
    """
    return _FRAME_POLICY.get()[0]=='detailed' or stage not in _NORMAL_PHASES


def _compact_stage_timings(value):
    # Keep every stage's wall, CPU and call count; derived wait can be rebuilt.
    # Full sampled/error rows retain the original nested diagnostic structure.
    keep=('wall_s','thread_cpu_s','calls')
    result={k:value[k] for k in ('wall_s','thread_cpu_s','exclusive_stages','accounting_residual_s') if k in value}
    result['stages']={name:{k:timing[k] for k in keep if k in timing}
        for name,timing in value.get('stages',{}).items()}
    return result

def _compact_record(stage,data):
    mode,every,slow=_FRAME_POLICY.get()
    if mode=='detailed':return data
    if stage in _NORMAL_PHASES:
        # Ordinary successful planning is queued, never serialized to console.
        return {k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
    if stage=='GC_FRAME_BATCH':
        result=dict(data);result['events']=tuple(e for e in data.get('events',()) if e['wall_s']>=.002)
        return result
    if stage=='CAMERA_FRAME':
        tracking=data.get('tracking',{});index=data.get('index',0)
        if diagnostic_detail(index,max(data.get('ps_prepare_s',0.),data.get('owner_s',0.)),tracking):
            return dict(data,log_detail=True)
        result={k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
        result.update(log_detail=False,corners_used=data.get('corners_used',tracking.get('corners')),
            output_orientation=data.get('output_orientation',{}),
            tracking={k:tracking[k] for k in ('valid','mode','corners','confidence','lk_trigger','feature_count',
                'tracker_s','tracker_thread_cpu_s','lk_channel','gray_s','feature_update_s','lk_age_frames','gap_anchor_retained','reason','trigger','edge_gate',
                'tracking_state','recovery_confirmations','target_changed','color_boundary_continuity') if k in tracking},
            refresh={k:v for k,v in data.get('refresh',{}).items() if v is None or isinstance(v,(str,int,float,bool))})
        result['tracking']['recovery_attempt']=_scalars(tracking.get('recovery_attempt',{}))
        result['tracking']['same_target_recovery']=tracking.get('same_target_recovery')
        result['tracking']['current_proof_budget_ms']=tracking.get('current_proof_budget_ms')
        lk_budget=tracking.get('lk_timing',{}).get('entry_budget')
        if lk_budget:result['tracking']['lk_entry_budget']=_scalars(lk_budget)
        stable=tracking.get('stable_tracking_policy',{})
        if stable:result['tracking']['stable_tracking_policy']=_scalars(stable)
        proof=tracking.get('current_source_proof',{})
        if proof:
            result['tracking']['current_source_proof_summary']={k:proof[k] for k in
                ('verified','reason','admission_policy','admission_grade','source64_provenance_verified',
                 'independent_sampling_verified','stable_FB_support_tolerance','boundary_definition',
                 'min_support','max_rms','line_normal_difference','normal_limit',
                 'corner_difference','corner_limit','stable_FB_rms_limit',
                 'strict_new_candidate_support','strict_new_candidate_rms') if k in proof}
            timing=proof.get('current_proof_timing',{})
            result['tracking']['current_source_proof_summary']['timing']=_scalars(timing)
            result['tracking']['current_source_proof_summary']['physical_layer_continuity']=_scalars(timing.get('physical_layer_continuity',{}))
        result['tracking']['local_recovery']=_scalars(tracking.get('edge_recovery',{}))
        edge=tracking.get('edge_evidence',{})
        result['tracking']['physical_peak_lock']=edge.get('physical_peak_lock')
        result['tracking']['peak_lock_radius_source']=edge.get('peak_lock_radius_source')
        result['tracking']['signed_peak_lock']=edge.get('signed_peak_lock')
        gate=tracking.get('edge_gate',{})
        result['tracking'].update(min_edge_support=gate.get('min_support'),max_edge_rms=gate.get('max_rms'),
            feature_action=tracking.get('feature_detail',{}).get('action'),
            gap_anchor_action=tracking.get('edge_recovery',{}).get('anchor_action'),
            gap_anchor_guard_s=tracking.get('edge_recovery',{}).get('anchor_guard_s'),
            lk_max_gap=tracking.get('lk_max_gap'),
            edge_backend=tracking.get('edge_evidence',{}).get('edge_backend'),
            boundary_fallback_s=tracking.get('edge_evidence',{}).get('boundary_fallback_s',0.),
            boundary_fallback_thread_cpu_s=tracking.get('edge_evidence',{}).get('boundary_fallback_thread_cpu_s',0.))
        # All per-stage wall/CPU samples remain available for comparable summaries.
        for key in ('owner_stages','prepare_stages'):
            if key in data:result[key]=_compact_stage_timings(data[key])
        for key in ('owner_diagnostics','prepare_diagnostics'):
            if key in data:result[key]=_compact_diagnostic(data[key])
        result['parallel_plan']={k:(data.get('parallel_plan') or {}).get(k) for k in
            ('sequence','peak_rows','capacity_rows','receiver_acknowledged','imported_fields','imported_rows')}
        return result
    if stage=='DOCUMENT_DETECTION_FAILED' and mode=='compact':
        # The enclosing CAMERA_FRAME samples the full diagnostic tree. This
        # low-level repeated event carries an explicit rejection summary.
        result=_scalars(data);result.update(diagnostic_detail_deferred_to_camera_frame=True,
            candidate_rejection_count=len(data.get('rejected_candidates',()) or ()))
        return result
    if stage not in ('FRAME_DONE','FRAME_SKIPPED'):return data
    tracking=data.get('tracking',{});index=data.get('index',0)
    if (diagnostic_detail(index,data.get('bgr_latency_s',0.),tracking)
        or data.get('refresh',{}).get('surface_updated') or data.get('refresh',{}).get('light_updated')):
        return dict(data,log_detail=True)
    # One complete timing row, scalar state and current measured corners. Native
    # aggregates survive; result retention separately uses the same sampling policy.
    result={k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
    result.update(log_detail=False,corners_used=data.get('corners_used'),
        tracking=dict(mode=tracking.get('mode'),valid=tracking.get('valid'),
            confidence=tracking.get('confidence'),lk_trigger=tracking.get('lk_trigger'),
            feature_count=tracking.get('feature_count'),feature_seed_count=tracking.get('feature_seed_count'),
            min_edge_support=tracking.get('edge_gate',{}).get('min_support'),
            max_edge_rms=tracking.get('edge_gate',{}).get('max_rms')),
        refresh={k:v for k,v in data.get('refresh',{}).items() if k in ('surface_updated','light_updated','full_observation','appearance_backend')},
        parallel_plan={k:(data.get('parallel_plan') or {}).get(k) for k in
            ('sequence','peak_rows','capacity_rows','scan_cycles','hardware_overlap_cycles',
             'receiver_acknowledged','imported_fields','imported_rows','early_control_published_at',
             'early_control_submit_delay_s','submitted_at','completed_at')})
    return result

def frame_record(stage,durable=False,**data):
    active=_ACTIVE_FILE.get()
    if active is None:raise RuntimeError('frame_record needs an active logged_run')
    selected=data if durable else _compact_record(stage,data)
    if selected is None:return
    active.record(dict(time=datetime.datetime.now().astimezone().isoformat(),stage=stage,**selected))
    if durable:active.barrier(True)

_ORDINARY_PLANNING=frozenset(('planner upload begin','planner exact scan done','planner import begin',
    'planner import done','plan candidate begin','plan candidate ready'))
_CONSOLE_MILESTONES=frozenset(('RUN_BEGIN','RUN_COMPLETED','RUN_FAILED','CAMERA_PROGRESS','CAMERA_SUMMARY',
    'NATIVE_READY','CAMERA_READY','CAMERA_SEQUENCE_READY','LIVE_PREVIEW_READY','CAMERA_FIRST_FRAME_VERIFY'))

def _console_payload(stage,data):
    if stage=='CAMERA_SUMMARY':
        return {k:data[k] for k in ('release_id','frames','delivered','lost','live_delivered_fps',
            'ps_prepare','owner','raw_ready_latency','driver_input_latency','preview','run_log_path','status') if k in data}
    if stage=='CAMERA_PROGRESS':
        camera=data.get('camera',{})
        return dict(index=data.get('index'),total=data.get('total'),delivered=data.get('delivered'),
            capture_frames=camera.get('capture_frames'),queue_drops=camera.get('latest_queue_drops'))
    if stage in ('NATIVE_READY','CAMERA_READY','CAMERA_SEQUENCE_READY','LIVE_PREVIEW_READY','RUN_BEGIN'):
        return {k:v for k,v in data.items() if v is None or isinstance(v,(str,int,float,bool))}
    return data

def checkpoint(stage,durable=False,**data):
    #   ⭐ 2026-10-29：**PC 侧主机测试必须能关掉写盘**。
    #      `RUN_LOG` 是【模块所在目录】的 `run-result.log`，不是 CWD ——
    #      所以只要 import 了本包的 run_logging，单测就会把事件写进
    #      **随包发布的那个 run-result.log**，然后被打进 zip 传到板上。
    #      现场就出过：板上日志开头 11 条 `CAMERA_PROFILE_*` 全是 PC 单测的，
    #      差点被当成"板子跑了新功能"。
    #      ⇒ 单测跑 `P11_TEST_NO_LOG=1`，checkpoint 直接变 no-op。
    if os.environ.get('P11_TEST_NO_LOG')=='1':return
    # ACK/row proofs are retained in file records. Only normal successful plan
    # events lose their fsync; startup checkpoints and errors remain durable.
    if stage in _ORDINARY_PLANNING:durable=False
    active=_ACTIVE_FILE.get()
    if active:frame_record(stage,durable=durable,**data)
    else:
        writer=_Writer()
        try:
            writer.record(dict(time=datetime.datetime.now().astimezone().isoformat(),stage=stage,**data))
            writer.barrier(durable)
        finally:writer.close()
    if not _CONSOLE_ENABLED.get():return
    error=any(word in stage.lower() for word in ('fail','error','timeout','lost'))
    if stage in _ORDINARY_PLANNING:return
    if _FRAME_POLICY.get()[0]=='compact' and stage not in _CONSOLE_MILESTONES and not error:return
    stream=sys.stdout.console if isinstance(sys.stdout,_Tee) else sys.stdout
    payload=_console_payload(stage,data) if _FRAME_POLICY.get()[0]=='compact' or stage in _CONSOLE_MILESTONES else data
    stream.write(stage+' '+json.dumps(payload,ensure_ascii=False,default=_json_default)+'\n');stream.flush()

def gc_summary(events):
    return dict(count=len(events),wall_s=sum(e['wall_s'] for e in events),
        thread_cpu_s=sum(e.get('thread_cpu_s',0.) for e in events),
        max_s=max((e['wall_s'] for e in events),default=0.),
        first_number=events[0]['number'] if events else None,last_number=events[-1]['number'] if events else None)

def log_gc_batch(stage,after,**metadata):
    """One incremental record, never one queue entry per GC event."""
    from v31_diagnostics import gc_records,gc_retention
    events=gc_records(after)
    if events:frame_record(stage,summary=gc_summary(events),events=events,retention=gc_retention(after),**metadata)
    return events[-1]['number'] if events else after

def _log_metadata_target(result):
    """Attach run details to a result dict or the metadata in (image, dict)."""
    if isinstance(result,dict):return result
    if isinstance(result,tuple) and len(result)==2 and isinstance(result[1],dict):
        return result[1]
    return None


def logged_run(function):
    signature=inspect.signature(function)
    @wraps(function)
    def wrapped(*args,**kwargs):
        if not _BUSY.acquire(blocking=False):raise RuntimeError('同一内核已有PL任务运行')
        token=file_token=None;writer=None;began=time.perf_counter()
        from v31_diagnostics import enable_gc,disable_gc,gc_records,gc_cursor,gc_retention
        result=None;result_metadata=None
        try:
            from v31_crash import install_crash_capture
            crash_info=install_crash_capture()
            gc_before=gc_cursor();enable_gc()
            bound=signature.bind_partial(*args,**kwargs);bound.apply_defaults()
            run_id=f'{os.getpid()}_{time.time_ns()}'
            metadata=dict(run_id=run_id,run_log_path=str(RUN_LOG),run_log_dir=str(RUN_LOG.parent),
                working_directory=str(Path.cwd()),gc_begin_number=gc_before)
            token=_CURRENT.set(metadata);writer=_Writer();file_token=_ACTIVE_FILE.set(writer)
            with redirect_stdout(_Tee(sys.stdout,writer)),redirect_stderr(_Tee(sys.stderr,writer)):
                checkpoint('RUN_BEGIN',durable=True,release_id=RELEASE_ID,run_id=run_id,parameters=dict(bound.arguments))
                checkpoint('CRASH_CAPTURE_READY',durable=True,**crash_info)
                try:
                    result=function(*args,**kwargs)
                    result_metadata=_log_metadata_target(result)
                except BaseException as exc:
                    try:
                        events=gc_records(gc_before)
                        frame_record('GC_FAILURE_BATCH',summary=gc_summary(events),events=events,retention=gc_retention(gc_before))
                        checkpoint('RUN_FAILED',durable=True,run_id=run_id,exception_type=type(exc).__name__,
                            exception=str(exc),logging=writer.snapshot(),gc_summary=gc_summary(events))
                        writer.write(traceback.format_exc());writer.barrier(True)
                    except BaseException as log_error:_stderr_notice('日志失败，保留原始异常：'+repr(log_error)+'\n')
                    raise
                events=gc_records(gc_before)
                frame_record('GC_RUN_SUMMARY',summary=gc_summary(events),retention=gc_retention(gc_before))
                writer.barrier(False)
                checkpoint('LOG_WRITER_SUMMARY',scope='through_summary_barrier_before_final_close',
                    metrics=writer.snapshot(),gc_events=len(events),slow_io_events=list(writer.io_events),
                    slow_io_events_dropped=writer.io_events_dropped)
                if result_metadata is not None:
                    result_metadata.update(metadata,logging=writer.snapshot(),gc_events=events,
                        log_io_events=list(writer.io_events))
                checkpoint('RUN_COMPLETED',durable=True,run_id=run_id,elapsed_wall_s=time.perf_counter()-began,
                    status=result_metadata.get('status','completed') if result_metadata is not None else 'completed')
                if result_metadata is not None:result_metadata['call_wall_s']=time.perf_counter()-began
                return result
        finally:
            try:
                original_error=sys.exc_info()[0] is not None
                if writer:
                    try:writer.close()
                    except BaseException as close_error:
                        if not original_error:raise
                        _stderr_notice('日志关闭失败，保留原始异常：'+repr(close_error)+'\n')
                if result_metadata is not None:
                    try:
                        result_metadata['call_wall_s']=time.perf_counter()-began
                        if writer is not None:
                            result_metadata['logging']=writer.snapshot()
                            result_metadata['log_io_events']=list(writer.io_events)
                    except BaseException as metadata_error:
                        if not original_error:raise
                        _stderr_notice('日志元数据收尾失败，保留原始异常：'+repr(metadata_error)+'\n')
            finally:
                disable_gc()
                if file_token is not None:_ACTIVE_FILE.reset(file_token)
                if token is not None:_CURRENT.reset(token)
                _BUSY.release()
    return wrapped


def retained_camera_row(data):
    return _compact_record('CAMERA_FRAME',data)


def retained_frame_row(data,policy='sampled'):
    """Keep every timing/id/corner; retain full trees only for sampled/errors."""
    if policy=='all':return data
    if policy!='sampled':raise ValueError('retain_details须为sampled/all')
    out=_compact_record('FRAME_DONE' if data['delivered'] else 'FRAME_SKIPPED',data)
    if out.get('log_detail'):return out
    # Summary counters need these small records, not a repeated native/GC tree.
    tracking=dict(out['tracking']);original=data.get('tracking',{})
    tracking['trigger']=original.get('trigger')
    tracking['gray_detail']={k:v for k,v in original.get('gray_detail',{}).items() if k in ('backend','blur_backend','transaction_backend','output_pool_reused','edge_error')}
    tracking['feature_detail']={k:v for k,v in original.get('feature_detail',{}).items() if k=='action'}
    out['tracking']=tracking
    detail=data.get('plan_detail',{}) or {}
    out['plan_detail']={k:int(detail.get(k) or 0) for k in ('tone_cache_hits','tone_cache_misses')}
    out['plan_detail'].update({k:detail[k] for k in ('geometry_backend','control_encode_backend') if k in detail})
    return out

@contextmanager
def console_output_scope(enabled=False):
    token=_CONSOLE_ENABLED.set(bool(enabled))
    try:yield
    finally:_CONSOLE_ENABLED.reset(token)

@contextmanager
def file_only_output():
    """Notebook setup/helper output to the same file; no device work is hidden."""
    writer=_Writer();token=_ACTIVE_FILE.set(writer)
    try:
        with console_output_scope(False),redirect_stdout(_Tee(sys.stdout,writer)),redirect_stderr(_Tee(sys.stderr,writer)):
            try:yield
            except BaseException:
                writer.write(traceback.format_exc());writer.barrier(True);raise
    finally:
        _ACTIVE_FILE.reset(token);writer.close()
