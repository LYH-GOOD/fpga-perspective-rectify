"""ai —— 合并层，含 8 个原始模块。

本文件由 build/merge_layers.py 生成，不要直接编辑。
每个原始模块的边界见下方 "# ===== [NN/MM] 模块名 =====" 分节标记。
"""


from pathlib import Path
import hashlib


from pathlib import Path
import hashlib
import cv2
import numpy as np
from pathlib import Path
import hashlib,json,struct,socket
from contextvars import copy_context
import hashlib,json,os,platform,queue,secrets,select,socket,subprocess,sys,tempfile,threading,time
import hashlib,json,os,platform,struct,sys,time
import hashlib,json,os,sys,threading,time,types
import argparse,hashlib,json,os,platform,struct,sys,time


_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ======================================================================
# ===== [01/08] v98_ai_geometry =====
# ======================================================================


"""Pure NumPy/OpenCV mask-to-quadrilateral helpers; no training framework."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

POSTPROCESS_VERSION="mask_quad_huber_lines_v2"

def ordered(points):
    q=np.asarray(points,np.float32).reshape(4,2)
    q=q[np.argsort(np.arctan2(q[:,1]-q[:,1].mean(),q[:,0]-q[:,0].mean()))]
    q=np.roll(q,-np.argmin(q.sum(axis=1)),axis=0)
    if cv2.contourArea(q,oriented=True)<0: q=q[[0,3,2,1]]
    return q

def quad_from_mask(binary):
    count,labels,stats,_=cv2.connectedComponentsWithStats(binary.astype(np.uint8),8)
    if count<=1: return None,0.
    index=1+np.argmax(stats[1:,cv2.CC_STAT_AREA])
    component=(labels==index).astype(np.uint8)
    if component.sum()<binary.size*.02 or component.sum()>binary.size*.90: return None,0.
    contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    hull=cv2.convexHull(max(contours,key=cv2.contourArea))
    best=None;score=0.
    for eps in [.008,.012,.018,.025,.035,.05,.065,.08]:
        approx=cv2.approxPolyDP(hull,eps*cv2.arcLength(hull,True),True)
        if len(approx)!=4 or not cv2.isContourConvex(approx): continue
        q=ordered(approx)
        filled=np.zeros_like(component)
        cv2.fillPoly(filled,[np.rint(q).astype(np.int32)],1)
        iou=float(np.sum((filled>0)&(component>0))/max(1,np.sum((filled>0)|(component>0))))
        if iou>score: score=iou;best=q
    if score<.7: return None,score
    refined,fit=_refine_lines(binary,best)
    if refined is not None and fit>=score-.015: return refined,fit
    return best,score


def _refine_lines(binary,q):
    count,labels,stats,_=cv2.connectedComponentsWithStats(binary.astype(np.uint8),8)
    if count<=1:return None,0.
    component=(labels==(1+np.argmax(stats[1:,cv2.CC_STAT_AREA]))).astype(np.uint8)
    contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    points=max(contours,key=cv2.contourArea).reshape(-1,2).astype(np.float32)
    lines=[]
    for i in range(4):
        a=q[i];direction=q[(i+1)%4]-a
        length=float(np.linalg.norm(direction));unit=direction/length
        relative=points-a
        t=relative@unit/length
        distance=np.abs(relative[:,0]*unit[1]-relative[:,1]*unit[0])
        chosen=points[(t>.18)&(t<.82)&(distance<max(2.5,length*.06))]
        if len(chosen)<12:return None,0.
        vx,vy,x,y=cv2.fitLine(chosen,cv2.DIST_HUBER,0,.01,.01).reshape(4)
        lines.append((np.array([x,y]),np.array([vx,vy])))
    corners=[]
    for i in range(4):
        previous,dp=lines[(i-1)%4];current,dc=lines[i]
        matrix=np.column_stack((dp,-dc))
        if abs(np.linalg.det(matrix))<.1:return None,0.
        offset=np.linalg.solve(matrix,current-previous)[0]
        corners.append(previous+offset*dp)
    result=ordered(corners)
    h,w=binary.shape
    if not np.isfinite(result).all() or not cv2.isContourConvex(result):return None,0.
    if (result<0).any() or (result[:,0]>w-1).any() or (result[:,1]>h-1).any():return None,0.
    movement=np.mean(np.linalg.norm(result-q,axis=1))
    if movement>min(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1))*.15:return None,0.
    filled=np.zeros_like(component)
    cv2.fillPoly(filled,[np.rint(result).astype(np.int32)],1)
    iou=float(np.sum((filled>0)&(component>0))/max(1,np.sum((filled>0)|(component>0))))
    return result,iou



# ======================================================================
# ===== [02/08] v99_ai_protocol =====
# ======================================================================


"""Bounded length-framed local IPC. EOF means disconnect, never end of a frame."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_HEADER=16384
FRAME_BYTES=480*640*3


def connect_address(address):
    if address.startswith('tcp:'):
        host,port=address[4:].rsplit(':',1)
        if host!='127.0.0.1':raise ValueError('AI TCP fallback is loopback only')
        connection=socket.socket(socket.AF_INET,socket.SOCK_STREAM);target=(host,int(port))
    else:
        connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);target=address
    try:
        connection.settimeout(10.);connection.connect(target);connection.settimeout(None)
        return connection
    except BaseException:connection.close();raise


def recv_exact(sock,count):
    result=bytearray(count);view=memoryview(result);offset=0
    while offset<count:
        used=sock.recv_into(view[offset:],count-offset)
        if not used:raise EOFError('AI connection closed during a message')
        offset+=used
    return bytes(result)


def send_message(sock,metadata,payload=b''):
    if len(payload)>FRAME_BYTES:raise ValueError('AI payload too large')
    value=dict(metadata,payload_bytes=len(payload))
    header=json.dumps(value,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(header)>MAX_HEADER:raise ValueError('AI header too large')
    sock.sendall(struct.pack('!I',len(header))+header)
    if payload:sock.sendall(payload)


def recv_message(sock):
    length=struct.unpack('!I',recv_exact(sock,4))[0]
    if not 1<=length<=MAX_HEADER:raise ValueError('Invalid AI header size')
    value=json.loads(recv_exact(sock,length))
    if not isinstance(value,dict):raise ValueError('AI metadata must be an object')
    count=value.pop('payload_bytes',0)
    if type(count) is not int or not 0<=count<=FRAME_BYTES:raise ValueError('Invalid AI payload size')
    return value,recv_exact(sock,count) if count else b''


# ======================================================================
# ===== [03/08] v99_ai_service =====
# ======================================================================


"""Application-owned resident CPU service. Only home/session/request events call it."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
INIT_TIMEOUT_S=60.
REQUEST_TIMEOUT_S=10.
MIN_AVAILABLE_KIB=64*1024
MAX_WORKER_PSS_KIB=128*1024


class Aborted(Exception):pass


def memory_info__v99_ai_service():
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
        self.baseline_memory=memory_info__v99_ai_service();self.reserve_cma_kib=int(os.environ.get('P11_AI_CMA_RESERVE_KIB',str(cma_reserve_kib)))
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
        value=memory_info__v99_ai_service();worker=self.worker_info.get('memory',{})
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
            memory=memory_info__v99_ai_service(),idle_protocol='blocking receive; passive OpenMP')

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
            self.baseline_memory=memory_info__v99_ai_service()
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
            from ui import prepare as prepare; from ui import finish as finish
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


# ======================================================================
# ===== [04/08] v98_ai_request =====
# ======================================================================


"""Resident request facade, imported only by an explicit AI selection."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ======================================================================
# ===== [05/08] v98_ai_worker =====
# ======================================================================


"""CPU-only AI child. Stage traces go to stderr; the response is one stdout JSON."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT__v98_ai_worker=Path(__file__).resolve().parent
START=time.perf_counter()


def trace(stage,**detail):
    value=dict(stage=stage,elapsed_ms=(time.perf_counter()-START)*1000.,**detail)
    print('P11_AI_STAGE '+json.dumps(value,allow_nan=False),file=sys.stderr,flush=True)


class NoPlaneFound(ValueError):pass


def validate_manifest():
    trace('check_assets')
    manifest=json.loads((ROOT__v98_ai_worker/'v98_ai_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('release_id')!=RELEASE_ID or manifest.get('format')!=1:
        raise ValueError('AI manifest version mismatch')
    if (platform.machine()!='armv7l' or struct.calcsize('P')!=4 or sys.version_info[:2]!=(3,10)):
        raise RuntimeError('AI runtime requires the tested ARMv7 Python 3.10 board')
    for name,digest in manifest['sha256'].items():
        path=(ROOT__v98_ai_worker/name).resolve()
        if not path.is_relative_to(ROOT__v98_ai_worker) or not name.startswith('ai/'):
            raise ValueError('Unsafe AI asset path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('AI asset integrity mismatch: '+name)
    trace('assets_ready',files=len(manifest['sha256']))
    return manifest


def infer(header,data,manifest):
    sys.path.insert(0,str(ROOT__v98_ai_worker/'ai'/'runtime'))
    trace('import_numpy')
    import numpy as np
    trace('import_cv2')
    import cv2
    trace('import_ncnn')
    import ncnn
    trace('import_geometry')
    cv2.setNumThreads(1)
    bgr=np.frombuffer(data,np.uint8).reshape(header['shape'])
    prep=manifest['preprocessing'];width=prep['width'];height=prep['height']
    trace('preprocess')
    rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
    small=cv2.resize(rgb,(width,height),interpolation=cv2.INTER_AREA)
    mean=np.array(prep['mean'],np.float32).reshape(1,1,3)
    std=np.array(prep['std'],np.float32).reshape(1,1,3)
    x=np.ascontiguousarray(((small.astype(np.float32)/255.-mean)/std).transpose(2,0,1))
    threads=header.get('threads',1)
    if type(threads) is not int or threads not in (1,2):raise ValueError('Invalid AI thread count')
    net=ncnn.Net();net.opt.use_vulkan_compute=False;net.opt.num_threads=threads
    net.opt.use_fp16_packed=False;net.opt.use_fp16_storage=False;net.opt.use_fp16_arithmetic=False
    net.opt.use_bf16_storage=False;net.opt.use_winograd_convolution=False
    try:
        trace('load_parameters')
        if net.load_param(str(ROOT__v98_ai_worker/'ai'/'plane.ncnn.param'))!=0:raise RuntimeError('AI parameter load failed')
        trace('load_weights')
        if net.load_model(str(ROOT__v98_ai_worker/'ai'/'plane.ncnn.bin'))!=0:raise RuntimeError('AI weights load failed')
        trace('inference',threads=threads)
        with net.create_extractor() as ex:
            if ex.input('in0',ncnn.Mat(x).clone())!=0:raise RuntimeError('AI input failed')
            rc,value=ex.extract('out0')
            if rc!=0:raise RuntimeError('AI output failed')
            logits=np.asarray(value).copy().reshape(height,width)
        if not np.isfinite(logits).all():raise ValueError('Non-finite AI output')
        trace('fit_corners')
        quad,fit=quad_from_mask(logits>0)
        if quad is None:raise NoPlaneFound('No usable plane found in this frame')
        quad=quad*np.array([bgr.shape[1]/width,bgr.shape[0]/height],np.float32)
        return dict(status='candidate',quad=quad.tolist(),mask_fit_iou=float(fit),
            postprocess=POSTPROCESS_VERSION,model_sha256=manifest['sha256']['ai/plane.ncnn.bin'])
    finally:net.clear()


def main__v98_ai_worker():
    started=time.perf_counter();stream=sys.stdin.buffer
    trace('read_input',interpreter=sys.executable,machine=platform.machine())
    line=stream.readline(4097)
    if len(line)>4096 or not line.endswith(b'\n'):raise ValueError('Invalid AI header')
    header=json.loads(line)
    if (header.get('release_id')!=RELEASE_ID or header.get('shape')!=[480,640,3]
            or header.get('dtype')!='uint8'):raise ValueError('Invalid AI source format')
    receipt={key:header[key] for key in ('release_id','generation','token','sequence','request_id')}
    data=stream.read(480*640*3)
    if len(data)!=480*640*3 or stream.read(1):raise ValueError('Invalid AI source size')
    digest=hashlib.sha256(data).hexdigest()
    if digest!=header.get('source_sha256'):raise ValueError('AI source hash mismatch')
    memory={}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key,value=line.split(':',1)
            if key in ('MemAvailable','SwapFree','SwapTotal'):memory[key]=value.strip()
    except (OSError,ValueError):pass
    trace('input_ready',bytes=len(data),memory=memory)
    try:value=infer(header,data,validate_manifest())
    except NoPlaneFound as exc:value=dict(status='failed',failure_kind='no_plane',error=str(exc))
    except Exception as exc:value=dict(status='failed',failure_kind='runtime_error',error=str(exc)[:1000])
    trace('result_ready',status=value['status'],failure_kind=value.get('failure_kind'))
    value.update(receipt,source_sha256=digest,worker_ms=(time.perf_counter()-started)*1000.)
    print(json.dumps(value,allow_nan=False),flush=True)


if __name__=='__main__':main__v98_ai_worker()


# ======================================================================
# ===== [06/08] v99_ai_selftest =====
# ======================================================================


"""Recorded-image CPU self-test of the actual resident worker and four-corner handoff."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT__v99_ai_selftest=Path(__file__).resolve().parent


def process_seconds(pid):
    try:
        fields=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()
        return (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    except (OSError,ValueError,AttributeError):
        if os.name!='nt':return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return None
        try:
            values=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in values]):return None
            return sum(((x.dwHighDateTime<<32)|x.dwLowDateTime) for x in values[2:])/1e7
        finally:kernel.CloseHandle(handle)
    except (OSError,AttributeError):return None


def run_selftest(output=None,service_factory=None,idle_s=1.,event_sink=None):
    import numpy as np,cv2
    import ui as interaction
    events=[]
    def emit(stage,**fields):
        events.append(dict(stage=stage,**fields))
        if event_sink is not None:event_sink(stage,**fields)
    config=json.loads((ROOT__v99_ai_selftest/'v99_ai_selftest.json').read_text(encoding='utf-8'))
    if config['release_id']!=RELEASE_ID:raise ValueError('Self-test version mismatch')
    for item in config['cases']:
        if hashlib.sha256((ROOT__v99_ai_selftest/item['image']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Self-test image mismatch')
    report=dict(status='running',release_id=RELEASE_ID,scope='recorded BGR CPU resident IPC and original corner handoff',
        camera_accessed=False,pl_accessed=False,hdmi_accessed=False,physical_fps_measured=False,cases=[])
    output=Path(output or ROOT__v99_ai_selftest/'ai_selftest_result.json')
    service=(service_factory or Service)(event_sink=emit,preload=True);old_log=interaction.checkpoint;interaction.checkpoint=emit
    try:
        service.enter_home()
        if not service.wait_ready(65.) and service.state!='on_demand':raise RuntimeError('AI initialization failed: '+str(service.last_error))
        report['initial_worker']=dict(service.worker_info);report['parent_memory_before_live']=memory_info__v99_ai_service()
        service.prepare_live()
        if service.process is None:
            report['resident_released_for_memory']=True  # explicit calls remain available
        first_pid=None
        for index,item in enumerate(config['cases']):
            image=cv2.imdecode(np.frombuffer((ROOT__v99_ai_selftest/item['image']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape!=(480,640,3):raise ValueError('Invalid self-test image')
            image.setflags(write=False)
            display=types.SimpleNamespace(condition=threading.Condition(),ui_generation=7,stop=False,
                pending=None,canvas_views={},layouts={},ai_service=service)
            editor=interaction.Inspection(display);display.inspection=editor
            editor.kind='calibration';editor.generation=7;editor.source=image;editor.source_rect=interaction.SOURCE_RECT
            editor.meta=dict(sequence=100+index,source_shape=(480,640));editor.notice='select'
            assert editor.queue_ai(7,ai_only=True);assert editor.take_action(7)==('ai',None)
            task=Request(editor,7);started=time.perf_counter()
            try:
                if not task.done.wait(75.):raise TimeoutError('Self-test request did not finish')
                task.poll()
            finally:task.close()
            action=editor.take_action(7)
            if action is None or action[0]!='confirm':raise RuntimeError('Self-test AI failed: '+str(task.result))
            expected=np.array(item['quad'],np.float32)
            error=float(np.max(np.linalg.norm(action[1]-expected,axis=1)))
            if error>2.5:raise ValueError('Self-test corner drift %.3fpx exceeds 2.5px'%error)
            pid=task.result.get('pid');first_pid=pid if first_pid is None else first_pid
            report['cases'].append(dict(id=item['id'],quad=action[1].tolist(),max_corner_drift_px=error,
                elapsed_ms=(time.perf_counter()-started)*1000.,worker_ms=task.result.get('worker_ms'),
                pid=pid,automatic_original_handoff=True,memory=task.result.get('memory')))
            emit('AI_SELFTEST_CASE_PASSED',id=item['id'],max_corner_drift_px=error,pid=pid)
        report['same_worker_for_all_cases']=len({x['pid'] for x in report['cases']})==1
        if service.process is not None:
            pid=service.process.pid;before=process_seconds(pid);began=time.monotonic();time.sleep(idle_s)
            after=process_seconds(pid);elapsed=time.monotonic()-began
            cpu=(after-before)/elapsed*100. if before is not None and after is not None else None
            report['idle']=dict(seconds=elapsed,worker_cpu_percent_one_core=cpu,state=service.state,
                measured=cpu is not None,idle_cpu_check_passed=cpu is not None and cpu<=2.)
        report['parent_imported_ncnn']='ncnn' in sys.modules
        report['worker_opencv_imported']=service.worker_info.get('opencv_imported')
        report['resident_admitted']=service.process is not None
        report['status']='passed';emit('AI_SELFTEST_PASSED',cases=len(report['cases']),idle=report.get('idle'))
    except Exception as exc:
        report.update(status='failed',error=str(exc),last_stage=service.last_stage)
        emit('AI_SELFTEST_FAILED',error=str(exc),last_stage=service.last_stage)
    finally:
        try:service.close()
        finally:interaction.checkpoint=old_log
        report['manager_retired']=not service.thread.is_alive()
        report['child_retired']=service.last_process is None or service.last_process.poll() is not None
        report['events']=events
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    def show(stage,**fields):
        print(json.dumps(dict(stage=stage,**fields),ensure_ascii=False),flush=True)
    result=run_selftest(event_sink=show)
    print('%d/%d corner checks passed'%(len(result['cases']),len(result['cases'])) if result['status']=='passed' else 'Self-test failed: '+result.get('error','unknown'),flush=True)
    sys.exit(0 if result['status']=='passed' else 1)


# ======================================================================
# ===== [07/08] v99_ai_ui =====
# ======================================================================


"""Event-only home status and application-owned service attachment."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def attach(state,native_setup):
    import cv2,numpy as np
    assets=state.assets;root=Path(__file__).resolve().parent
    image=cv2.imdecode(np.frombuffer((root/'v99_ai_home_status.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    names=('waiting_native','loading','ready','on_demand','error','off')
    if image is None or image.shape!=(288,340,3):raise ValueError('Invalid resident AI home status asset')
    base=assets.home
    def changed(status):
        with state.condition:
            state.ai_status=status
            if state.page!='home' or state.stopping:return
            index=names.index(status) if status in names else names.index('loading')
            home=base.copy();home[20:68,900:1240]=image[index*48:(index+1)*48]
            home.setflags(write=False);assets.home=home
            assets.return_home=None;assets.error_home=None;assets.home_pressed_cache=None;assets.home_pressed_key=None
            display=state.display
            if display is not None:
                with display.condition:
                    display.ui_dirty=True;display.condition.notify_all()
    state.ai_status_changed=changed
    canvas_kib=((int(assets.mode[0])*int(assets.mode[1])*3+4095)//4096)*4
    service=Service(native_gate=native_setup.done,status_callback=changed,cma_reserve_kib=canvas_kib+4)
    state.ai_service=service
    if state.display is not None:state.display.ai_service=service
    changed('waiting_native');service.enter_home()
    return service


def entered_home(state):
    service=getattr(state,'ai_service',None)
    if service is None:return
    state.ai_status_changed(service.state);service.enter_home()


# ======================================================================
# ===== [08/08] v99_ai_worker =====
# ======================================================================


"""Lean resident inference only: no OpenCV, geometry, camera or FPGA imports."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT__v99_ai_worker=Path(__file__).resolve().parent
PREPROCESS_VERSION='rgb-area-imagenet-chw-f32-v1'


def memory_info__v99_ai_worker():
    result={}
    for name,fields in [('/proc/self/status',('VmRSS','VmHWM','VmSwap','Threads')),
        ('/proc/self/smaps_rollup',('Pss',)),('/proc/meminfo',('MemAvailable','CmaFree','CmaTotal','SwapFree'))]:
        try:
            for line in Path(name).read_text().splitlines():
                if ':' not in line:continue
                key,value=line.split(':',1)
                if key in fields:result[key]=int(value.split()[0])
        except (OSError,ValueError):pass
    return result


def validate_assets():
    manifest=json.loads((ROOT__v99_ai_worker/'v98_ai_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('release_id')!=RELEASE_ID or manifest.get('format')!=1:raise ValueError('AI manifest version mismatch')
    if platform.machine()!='armv7l' or struct.calcsize('P')!=4 or sys.version_info[:2]!=(3,10):
        raise RuntimeError('AI runtime requires the tested ARMv7 Python 3.10 board')
    for name,digest in manifest['sha256'].items():
        path=(ROOT__v99_ai_worker/name).resolve()
        if not name.startswith('ai/') or not path.is_relative_to(ROOT__v99_ai_worker):raise ValueError('Unsafe AI resource path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('AI asset integrity mismatch: '+name)
    return manifest


class Model:
    def __init__(self,stage):
        stage('check_assets');self.manifest=validate_assets()
        sys.path.insert(0,str(ROOT__v99_ai_worker/'ai/runtime'))
        stage('import_numpy');import numpy as np
        stage('import_ncnn');import ncnn
        self.np=np;self.ncnn=ncnn
        self.width=self.manifest['preprocessing']['width'];self.height=self.manifest['preprocessing']['height']
        self.threads=int(os.environ.get('P11_AI_THREADS','1'))
        if self.threads not in (1,2):raise ValueError('P11_AI_THREADS must be 1 or 2')
        self.net=ncnn.Net();self.net.opt.use_vulkan_compute=False;self.net.opt.num_threads=self.threads
        self.net.opt.use_fp16_packed=False;self.net.opt.use_fp16_storage=False;self.net.opt.use_fp16_arithmetic=False
        self.net.opt.use_bf16_storage=False;self.net.opt.use_winograd_convolution=False
        try:
            stage('load_parameters')
            if self.net.load_param(str(ROOT__v99_ai_worker/'ai/plane.ncnn.param'))!=0:raise RuntimeError('AI parameter load failed')
            stage('load_weights')
            if self.net.load_model(str(ROOT__v99_ai_worker/'ai/plane.ncnn.bin'))!=0:raise RuntimeError('AI weights load failed')
            stage('warmup');self.forward(np.zeros((3,self.height,self.width),np.float32))
        except BaseException:self.net.clear();raise

    def forward(self,x):
        with self.net.create_extractor() as ex:
            if ex.input('in0',self.ncnn.Mat(x).clone())!=0:raise RuntimeError('AI input failed')
            code,value=ex.extract('out0')
            if code!=0:raise RuntimeError('AI output failed')
            return self.np.asarray(value).copy().reshape(self.height,self.width)

    def infer(self,header,payload,stage):
        np=self.np
        #   ⚠️ 2026-10-28：`source_shape` 原来写死 [480,640,3]。
        #      换成 800x600 摄像头后父进程送来 [600,800,3] ⇒ 这里抛
        #      "Invalid AI tensor format"，**AI 通路整条失效**（现场 9 次全失败）。
        #      模型张量本来就是 resize 到 (3,h,w)，源图多大都不影响，
        #      所以只校验"是 3 通道、尺寸合理"，不校验具体分辨率。
        _src=header.get('source_shape') or []
        if (header.get('release_id')!=RELEASE_ID or header.get('shape')!=[3,self.height,self.width]
            or (len(_src)!=3 or _src[2]!=3 or not (16<=int(_src[0])<=2160) or not (16<=int(_src[1])<=3840))
            or header.get('dtype')!='float32-le'
            or header.get('preprocessing')!=PREPROCESS_VERSION or len(payload)!=3*self.height*self.width*4):
            raise ValueError('Invalid AI tensor format')
        if hashlib.sha256(payload).hexdigest()!=header.get('tensor_sha256'):raise ValueError('AI tensor hash mismatch')
        x=np.frombuffer(payload,dtype='<f4').reshape(3,self.height,self.width)
        if not np.isfinite(x).all():raise ValueError('Non-finite AI input')
        stage('inference');logits=self.forward(x)
        if not np.isfinite(logits).all():raise ValueError('Non-finite AI output')
        mask=np.ascontiguousarray(logits>0,np.uint8).tobytes()
        return dict(status='mask',shape=[self.height,self.width],dtype='uint8',
            mask_sha256=hashlib.sha256(mask).hexdigest(),model_sha256=self.manifest['sha256']['ai/plane.ncnn.bin']),mask

    def close(self):self.net.clear()


def serve(connection,nonce):
    start=time.perf_counter();model=None
    def stage(name):send_message(connection,dict(type='stage',stage=name,elapsed_ms=(time.perf_counter()-start)*1000.))
    send_message(connection,dict(type='hello',release_id=RELEASE_ID,nonce=nonce,pid=os.getpid(),
        interpreter=sys.executable,machine=platform.machine(),python=list(sys.version_info[:3])))
    try:
        model=Model(stage)
        send_message(connection,dict(type='ready',release_id=RELEASE_ID,pid=os.getpid(),memory=memory_info__v99_ai_worker(),
            model_sha256=model.manifest['sha256']['ai/plane.ncnn.bin'],initialization_ms=(time.perf_counter()-start)*1000.,
            ncnn_version=model.ncnn.__version__,numpy_version=model.np.__version__,threads=model.threads,
            opencv_imported='cv2' in sys.modules,preprocessing=PREPROCESS_VERSION))
        while True:
            connection.settimeout(None)
            header,payload=recv_message(connection)
            if header.get('type')=='stop':return
            if header.get('type')!='infer':raise ValueError('Unknown AI command')
            start=time.perf_counter()
            receipt={k:header[k] for k in ('release_id','generation','token','sequence','request_id',
                'source_sha256','tensor_sha256','preprocessing')}
            try:result,mask=model.infer(header,payload,stage)
            except Exception as exc:result=dict(status='failed',failure_kind='runtime_error',error=str(exc)[:1000]);mask=b''
            payload=b''
            result.update(receipt,type='result',worker_ms=(time.perf_counter()-start)*1000.,memory=memory_info__v99_ai_worker(),pid=os.getpid())
            send_message(connection,result,mask);mask=b'';result=None;header=None
    except EOFError:return
    except Exception as exc:
        try:send_message(connection,dict(type='error',error=str(exc)[:1200],failure_kind='runtime_error'))
        except OSError:pass
    finally:
        if model is not None:model.close()


def main__v99_ai_worker():
    p=argparse.ArgumentParser();p.add_argument('--socket',required=True);p.add_argument('--nonce',required=True)
    args=p.parse_args()
    with connect_address(args.socket) as connection:serve(connection,args.nonce)


if __name__=='__main__':main__v99_ai_worker()
