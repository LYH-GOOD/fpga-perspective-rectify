"""Application-owned resident CPU service. Only home/session/request events call it."""
from pathlib import Path
from contextvars import copy_context
import hashlib,json,os,platform,queue,secrets,select,socket,subprocess,sys,tempfile,threading,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v99_ai_protocol import send_message,recv_message
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
INIT_TIMEOUT_S=60.
REQUEST_TIMEOUT_S=10.
MIN_AVAILABLE_KIB=64*1024
MAX_WORKER_PSS_KIB=128*1024


class Aborted(Exception):pass


def memory_info():
    value={}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key,data=line.split(':',1)
            if key in ('MemAvailable','CmaFree','CmaTotal','SwapFree'):value[key]=int(data.split()[0])
    except (OSError,ValueError):pass
    return value


def _ram_file(label):
    if hasattr(os,'memfd_create'):
        return os.fdopen(os.memfd_create('p11-ai-'+label,os.MFD_CLOEXEC),'w+b',buffering=0)
    return tempfile.TemporaryFile('w+b',dir='/dev/shm' if Path('/dev/shm').is_dir() else None)


def _python():
    tested=Path('/usr/bin/python3')
    return str(tested) if platform.machine()=='armv7l' and tested.is_file() else sys.executable


class Service:
    def __init__(self,native_gate=None,status_callback=None,event_sink=None,root=None,preload=None,cma_reserve_kib=0):
        self.root=Path(root or Path(__file__).resolve().parent).resolve()
        self.native_gate=native_gate;self.callback=status_callback;self.emit=event_sink or checkpoint
        self.preload=(os.environ.get('P11_AI_PRELOAD','1')!='0') if preload is None else bool(preload)
        self.condition=threading.Condition();self.commands=queue.Queue();self.abort=threading.Event()
        self.load_done=threading.Event();self.load_done.set();self.closed=False;self.home=False
        self.state='off';self.loading=False;self.active=None;self.process=None;self.connection=None
        self.logs=();self.ipc_dir=None;self.last_process=None;self.last_error=None;self.last_stage=None
        self.worker_info={};self.context=copy_context();self.home_attempted=False;self.transition_hint=None
        self.baseline_memory=memory_info();self.reserve_cma_kib=int(os.environ.get('P11_AI_CMA_RESERVE_KIB',str(cma_reserve_kib)))
        if self.reserve_cma_kib<0:raise ValueError('CMA reserve must be nonnegative')
        self.thread=threading.Thread(target=lambda:self.context.run(self._run),name='p11-ai-manager',daemon=False)
        self.thread.start()

    def _status(self,state):
        with self.condition:
            changed=state!=self.state;self.state=state;self.condition.notify_all()
        if changed and self.callback is not None:
            try:self.callback(state)
            except Exception as exc:self.emit('AI_STATUS_CALLBACK_FAILED',error=str(exc))

    def enter_home(self):
        with self.condition:
            if self.closed:return
            self.home=True
        self.commands.put(('home',None))

    def wait_ready(self,timeout=INIT_TIMEOUT_S+2.):
        deadline=time.monotonic()+timeout
        with self.condition:
            while self.state!='ready' or self.loading:
                if self.closed or self.state in ('error','on_demand'):return False
                left=deadline-time.monotonic()
                if left<=0:return False
                self.condition.wait(left)
        return True


    def _admitted(self):
        value=memory_info();worker=self.worker_info.get('memory',{})
        # Ordinary RAM/PSS are independent of CMA. A zero reserve declares that
        # the CPU-only worker needs no contiguous allocation. Log CMA deltas; the
        # original DMA allocators still enforce their real allocation demands.
        # Operators can supply a measured pending-allocation reserve explicitly.
        passed=(value.get('MemAvailable',MIN_AVAILABLE_KIB)>=MIN_AVAILABLE_KIB
            and worker.get('VmSwap',0)==0 and worker.get('Pss',0)<=MAX_WORKER_PSS_KIB
            and (not self.reserve_cma_kib or value.get('CmaFree',0)>=self.reserve_cma_kib))
        self.emit('AI_MEMORY_ADMISSION',passed=passed,memory=value,worker=worker,
            baseline_before_ai=self.baseline_memory,min_available_kib=MIN_AVAILABLE_KIB,
            max_worker_pss_kib=MAX_WORKER_PSS_KIB,pending_cma_reserve_kib=self.reserve_cma_kib,
            cma_delta_kib=value.get('CmaFree',0)-self.baseline_memory.get('CmaFree',0),
            scope='home/session/request boundary only; no per-frame monitoring')
        return passed


    def prepare_live(self,mode='live'):
        """Actor barrier: the old compute is stopped before any live producer."""
        with self.condition:
            if self.closed:raise RuntimeError('AI service is closed')
            self.home=False;self.transition_hint=None
            draining=self.active is not None and getattr(self.active,'discard_result',False)
        if draining and mode in ('ai','manual_selection'):
            self.emit('AI_LIVE_BOUNDARY',state=self.state,resident=self.process is not None,
                background_inference=True,selection_only=mode,normal_tracking_allowed=False,
                discard_remaining_s=max(0.,getattr(self.active,'drain_deadline',0.)-time.monotonic()))
            return
        with self.condition:
            finish_warmup=self.loading and self.active is None and self.last_stage=='warmup'
        if finish_warmup:
            began=time.monotonic()
            self.emit('AI_LIVE_WARMUP_WAIT_BEGIN',maximum_s=2.,before_live_producer=True)
            try:finished=self.load_done.wait(2.)
            except BaseException:self._interrupt();raise
            self.emit('AI_LIVE_WARMUP_WAIT_END',elapsed_s=time.monotonic()-began,finished=finished,
                ready=self.state=='ready' and not self.loading,before_live_producer=True)
        with self.condition:
            if self.closed:raise RuntimeError('AI service is closed')
            interrupt=self.loading or self.active is not None
        if interrupt:self._interrupt()
        ack=threading.Event();self.commands.put(('live',ack))
        if not ack.wait(5.):raise RuntimeError('AI lifecycle barrier did not finish before live start')
        with self.condition:
            if self.loading or self.active is not None:raise RuntimeError('AI compute has not retired')
        self.emit('AI_LIVE_BOUNDARY',state=self.state,resident=self.process is not None,background_inference=False,
            memory=memory_info(),idle_protocol='blocking receive; passive OpenMP')

    def _interrupt(self):
        # shutdown wakes a blocking receive; only the actor closes/reaps handles.
        with self.condition:
            self.abort.set();connection=self.connection
        if connection is not None:
            try:connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass

    def submit(self,task):
        with self.condition:
            if self.closed:raise RuntimeError('AI service is closed')
        self.commands.put(('infer',task))


    def note_transition(self,mode):
        with self.condition:self.transition_hint=mode

    def ready_for_request(self):
        with self.condition:return not self.closed and not self.loading and self.active is None

    def _cancelled(self,task):
        if task is None or not task.cancelled.is_set():return False
        return not (getattr(task,'discard_result',False) and time.monotonic()<getattr(task,'drain_deadline',0.))

    def cancel(self,task):
        with self.condition:
            hint=getattr(self,'transition_hint',None);self.transition_hint=None
            active=self.active is task
            soft=bool(active and hint in ('ai','manual_selection') and self.process is not None
                and not self.loading and self.last_stage in ('inference','parent_fit_corners'))
            if soft:
                task.discard_result=True
                task.drain_deadline=min(time.monotonic()+2.,getattr(task,'request_deadline',time.monotonic()+2.))
            task.cancelled.set()
            if not active:task.done.set()
        if soft:
            self.emit('AI_REQUEST_DISCARD_BEGIN',generation=task.receipt.get('generation'),
                token=task.receipt.get('token'),maximum_s=2.,next_mode=hint,old_result_invalid=True)
        elif active:
            self._interrupt()
            if not task.done.wait(5.):raise RuntimeError('AI request did not retire before correction resumed')

    def _discard_received(self,task,result):
        if not getattr(task,'discard_result',False):return False
        if self.abort.is_set() or self._cancelled(task):raise Aborted()
        task.result=None;result.pop('_mask_payload',None)
        self.worker_info.update(memory=result.get('memory',{}));self._status('ready')
        self.emit('AI_REQUEST_DISCARD_END',generation=task.receipt.get('generation'),
            token=task.receipt.get('token'),worker_reused=True,old_result_applied=False)
        if not self.preload or not self._admitted():self._retire();self._status('on_demand')
        return True

    def _retire(self):
        with self.condition:
            connection=self.connection;process=self.process;logs=self.logs;directory=self.ipc_dir
            self.connection=None;self.process=None;self.logs=();self.ipc_dir=None
        if connection is not None:
            try:connection.shutdown(socket.SHUT_RDWR)
            except OSError:pass

            connection.close()
        if process is not None:
            if process.poll() is None:
                try:process.terminate()
                except ProcessLookupError:pass
                try:process.wait(.75)
                except subprocess.TimeoutExpired:process.kill();process.wait(1.5)
            if process.poll() is None:raise RuntimeError('AI child could not be reaped')
        for stream in logs:
            try:stream.close()
            except OSError:pass
        if directory is not None:
            # This directory contains only the service socket; no recursive deletion.
            path=Path(directory).resolve()
            if not path.name.startswith('p11ai_'):raise RuntimeError('Unexpected IPC directory')
            try:(path/'s').unlink(missing_ok=True);path.rmdir()
            except OSError:pass

    def _diagnostics(self):
        with self.condition:process=self.process;logs=self.logs
        value=dict(last_stage=self.last_stage,exit_code=process.poll() if process is not None else None)
        if len(logs)>1:
            try:
                stream=logs[1];size=os.fstat(stream.fileno()).st_size
                if hasattr(os,'pread'):data=os.pread(stream.fileno(),2048,max(0,size-2048))
                elif process is not None and process.poll() is not None:
                    stream.seek(max(0,size-2048));data=stream.read(2048)
                else:data=b''
                value['stderr_tail']=data.decode('utf-8','replace')
            except (OSError,ValueError):pass
        return value

    def _receive(self,deadline,task=None):
        if self.abort.is_set() or self._cancelled(task):raise Aborted()
        left=deadline-time.monotonic()
        if left<=0:raise TimeoutError('AI operation timed out; last_stage='+str(self.last_stage))
        with self.condition:connection=self.connection
        if connection is None:raise Aborted()
        try:
            connection.settimeout(.1)
            service=self
            class Reader:
                def recv_into(self,buffer,count):
                    while True:
                        if service.abort.is_set() or service.closed or service._cancelled(task):raise Aborted()
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise TimeoutError('AI operation timed out; last_stage='+str(service.last_stage))
                        readable,_,_=select.select([connection],[],[],min(.05,remaining))
                        if readable:return connection.recv_into(buffer,count)
            message,payload=recv_message(Reader())
        except (OSError,EOFError) as exc:
            if self.abort.is_set() or self.closed or self._cancelled(task):raise Aborted() from exc
            if isinstance(exc,socket.timeout):raise TimeoutError('AI operation timed out; last_stage='+str(self.last_stage)) from exc
            raise
        if self.abort.is_set() or self.closed or self._cancelled(task):raise Aborted()
        if payload:
            if message.get('type')!='result' or message.get('status')!='mask':raise ValueError('Unexpected AI payload')
            message['_mask_payload']=payload
        if message.get('type')=='stage':
            self.last_stage=message.get('stage')
            if task is not None:task.progress=dict(message)
            self.emit('AI_WORKER_PROGRESS',worker_stage=self.last_stage,elapsed_ms=message.get('elapsed_ms'))
        return message

    def _initialize(self,for_home=False,task=None):
        with self.condition:
            if self.closed or (for_home and not self.home) or (task is not None and task.cancelled.is_set()):raise Aborted()
            if self.process is not None and self.process.poll() is None and self.state=='ready':return
            self.abort.clear();self.loading=True;self.load_done.clear()
            self.baseline_memory=memory_info()
        self._status('loading');self.last_stage='python_startup';self.last_error=None
        listener=None;success=False
        try:
            self._retire()
            directory=Path(tempfile.mkdtemp(prefix='p11ai_')).resolve()
            if hasattr(socket,'AF_UNIX'):
                address=str(directory/'s')
                if len(os.fsencode(address))>=100:raise RuntimeError('AI IPC path is too long')
                listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);listener.bind(address)
            else:
                listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM);listener.bind(('127.0.0.1',0))
                address='tcp:127.0.0.1:'+str(listener.getsockname()[1])
            listener.listen(1);listener.settimeout(.10)
            nonce=secrets.token_hex(16)
            env=dict(os.environ,OMP_NUM_THREADS='1',OMP_WAIT_POLICY='PASSIVE',OPENBLAS_NUM_THREADS='1',
                MKL_NUM_THREADS='1',KMP_BLOCKTIME='0',PYTHONDONTWRITEBYTECODE='1')
            output=_ram_file('stdout');errors=_ram_file('stderr')
            with self.condition:
                self.ipc_dir=directory;self.logs=(output,errors)
                if self.abort.is_set() or self.closed or (for_home and not self.home):raise Aborted()
                self.process=subprocess.Popen([_python(),'-u','-B',str(self.root/'v99_ai_worker.py'),
                    '--socket',address,'--nonce',nonce],cwd=str(self.root),env=env,stdout=output,stderr=errors)
                self.last_process=self.process
            self.emit('AI_INIT_BEGIN',pid=self.process.pid,interpreter=_python(),timeout_s=INIT_TIMEOUT_S)
            deadline=time.monotonic()+INIT_TIMEOUT_S
            while True:
                if self.abort.is_set() or self.closed or (task is not None and task.cancelled.is_set()):raise Aborted()
                if time.monotonic()>=deadline:raise TimeoutError('AI initialization timed out at python_startup')
                with self.condition:process=self.process
                if process is None:raise Aborted()
                if process.poll() is not None:raise RuntimeError('AI interpreter exited before connection: '+str(process.returncode))
                try:connection,_=listener.accept();break
                except socket.timeout:continue  # startup only, never resident idle
            with self.condition:self.connection=connection
            listener.close();listener=None
            hello=self._receive(deadline,task)
            if (hello.get('type')!='hello' or hello.get('nonce')!=nonce or hello.get('release_id')!=RELEASE_ID):
                raise ValueError('AI handshake mismatch')
            self.emit('AI_WORKER_HELLO',**{k:v for k,v in hello.items() if k not in ('type','nonce')})
            while True:
                message=self._receive(deadline,task)
                if message.get('type')=='stage':continue
                if message.get('type')=='error':raise RuntimeError(message.get('error','AI initialization failed'))
                if message.get('type')!='ready' or message.get('release_id')!=RELEASE_ID:raise ValueError('AI READY mismatch')
                self.worker_info=message;break
            if self.abort.is_set():raise Aborted()
            self._status('ready');success=True
            self.emit('AI_READY',**{k:v for k,v in self.worker_info.items() if k!='type'})
        finally:
            if listener is not None:listener.close()
            if not success:self._retire()
            with self.condition:self.loading=False;self.load_done.set();self.condition.notify_all()


    def _infer(self,task):
        with self.condition:
            if task.cancelled.is_set():task.done.set();return
            self.active=task
        try:
            self._initialize(task=task)
            if task.cancelled.is_set():raise Aborted()
            from v100_ai_image import prepare,finish
            self._status('busy');self.last_stage='parent_preprocess';started=time.perf_counter()
            header,data=prepare(task.source,task.receipt)
            preprocess_ms=(time.perf_counter()-started)*1000.
            if self.abort.is_set() or task.cancelled.is_set():raise Aborted()
            deadline=time.monotonic()+REQUEST_TIMEOUT_S;task.request_deadline=deadline
            with self.condition:connection=self.connection
            if connection is None:raise Aborted()
            connection.settimeout(REQUEST_TIMEOUT_S);send_message(connection,header,data);data=b''
            while True:
                result=self._receive(deadline,task)
                if result.get('type')=='stage':continue
                if result.get('type')=='error':raise RuntimeError(result.get('error','AI worker failed'))
                if result.get('type')!='result':raise ValueError('Unexpected AI result')
                break
            if any(result.get(k)!=v for k,v in task.receipt.items()):raise ValueError('AI frame receipt mismatch')
            if result.get('model_sha256')!=self.worker_info.get('model_sha256') and result.get('status')=='mask':
                raise ValueError('AI model receipt mismatch')
            if self._discard_received(task,result):return
            self.last_stage='parent_fit_corners';fit_start=time.perf_counter()
            selection_context=getattr(task,'selection_context',None)
            if selection_context is None:result=finish(result,result.pop('_mask_payload',b''),header)
            else:result=finish(result,result.pop('_mask_payload',b''),header,selection_context,task.source)
            if self._discard_received(task,result):return
            if self.abort.is_set() or task.cancelled.is_set():raise Aborted()
            result.update(request_ms=(time.perf_counter()-started)*1000.,parent_preprocess_ms=preprocess_ms,
                parent_fit_ms=(time.perf_counter()-fit_start)*1000.)
            task.result=result;self.worker_info.update(memory=result.get('memory',{}))
            self._status('ready')
            if not self.preload or not self._admitted():self._retire();self._status('on_demand')
            self.emit('AI_WORKER_RESULT',**{k:v for k,v in result.items() if k not in ('type','quad')})
        except Aborted:
            self._retire();self._status('on_demand')
        except Exception as exc:
            if self.abort.is_set() or task.cancelled.is_set() or self.closed:
                self._retire();self._status('on_demand')
            else:
                self.last_error=str(exc);kind='timeout' if isinstance(exc,(TimeoutError,socket.timeout)) else 'runtime_error'
                diagnostic=self._diagnostics()
                task.result=dict(task.receipt,status='failed',failure_kind=kind,error=str(exc),diagnostics=diagnostic,last_stage=self.last_stage)
                self.emit('AI_SERVICE_ERROR',error=str(exc),failure_kind=kind,**diagnostic)
                self._retire();self._status('error')
        finally:
            with self.condition:self.active=None;task.done.set();self.condition.notify_all()


    def _run(self):
        try:
            # Commands must still be serviced while native compilation is busy.
            # Home preload is deferred by UI readiness events, not by blocking
            # this actor ahead of cancellation/live/stop barriers.
            while True:
                command,task=self.commands.get()
                if command=='stop':return
                if command=='live':
                    try:
                        if self.process is not None and (self.abort.is_set() or not self.preload or not self._admitted()):
                            self._retire();self._status('on_demand')
                    finally:task.set()
                    task=None;continue
                if command=='home':
                    with self.condition:allowed=self.home and not self.closed
                    if not allowed:continue
                    if not self.preload or self.home_attempted:self._status('ready' if self.process is not None else 'on_demand');continue
                    if self.native_gate is not None and not self.native_gate.is_set():
                        self._status('waiting_native')
                        # Native startup only; no polling when live or resident.
                        while not self.native_gate.wait(.1):
                            if self.closed or not self.home:break
                        if self.closed:return
                        if not self.home:continue
                    self.home_attempted=True
                    try:
                        self._initialize(for_home=True)
                        if not self._admitted():self._retire();self._status('on_demand')
                    except Aborted:self._status('on_demand')
                    except Exception as exc:
                        if self.abort.is_set() or self.closed or not self.home:
                            self._retire();self._status('on_demand')
                        else:
                            self.last_error=str(exc);diagnostic=self._diagnostics();self._retire();self._status('error')
                            self.emit('AI_INIT_FAILED',error=str(exc),**diagnostic)
                elif command=='infer':
                    self._infer(task);task=None
        finally:self._retire()


    def close(self):
        with self.condition:
            if self.closed:return
            self.closed=True;self.home=False;active=self.active
            if active is not None:active.cancelled.set()
        self._interrupt();self.commands.put(('stop',None));self.thread.join(5.)
        if self.thread.is_alive():raise RuntimeError('AI manager did not retire')


class Request:
    def __init__(self,inspection,generation):
        self.inspection=inspection;self.receipt,self.source=inspection.ai_input(generation)
        self.service=getattr(inspection.display,'ai_service',None)
        if self.service is None:raise RuntimeError('Resident AI service is not attached; restart the new package')
        self.done=threading.Event();self.cancelled=threading.Event();self.result=None;self.progress=None;self.taken=False
        self.service.submit(self)

    def poll(self):
        if not self.done.is_set() or self.taken:return False
        self.taken=True
        if not self.cancelled.is_set() and self.result is not None:
            self.inspection.apply_ai_result(self.receipt,self.source,self.result)
        return True

    def close(self):
        if not self.done.is_set():self.service.cancel(self)


def start_request(inspection,generation):return Request(inspection,generation)
