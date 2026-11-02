"""V4L2 raw capture with generation-checked MMAP leases and latest-frame queue."""
from pathlib import Path
import ctypes,hashlib,platform,subprocess,threading,time,json
from collections import deque
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]

def _library():
    if platform.system()!='Linux':raise RuntimeError('Camera capture runs on the PYNQ Linux board')
    root=Path(__file__).resolve().parent;src=root/'v31_camera_native.cpp'
    digest=hashlib.sha256(src.read_bytes()+platform.machine().encode()).hexdigest()[:20]
    target=root/('v31_capture_'+digest+'_'+platform.machine()+'.so')
    from v80_cache import restore,remember
    flags=['-O3','-std=c++11','-fPIC','-shared','-pthread']
    restore(target,src,'capture',flags)
    if not target.is_file():
        temp=target.with_suffix('.tmp.so')
        subprocess.run(['g++','-O3','-std=c++11','-fPIC','-shared','-pthread',str(src),'-o',str(temp)],check=True,capture_output=True,text=True)
        temp.replace(target)
    lib=ctypes.CDLL(str(target));vp=ctypes.c_void_p;ci=ctypes.c_int
    lib.p11_camera_abi.restype=ci
    if lib.p11_camera_abi()!=3102:raise RuntimeError('Camera helper ABI mismatch')
    lib.p11_camera_open.argtypes=[ctypes.c_char_p,ci,ci,ci,ctypes.POINTER(vp),vp,vp,ci];lib.p11_camera_open.restype=ci
    lib.p11_camera_next.argtypes=[vp,ci,ctypes.POINTER(vp),vp];lib.p11_camera_next.restype=ci
    lib.p11_camera_release.argtypes=[vp,ctypes.c_uint32,ctypes.c_uint64];lib.p11_camera_release.restype=ci
    lib.p11_camera_controls.argtypes=[vp,ci,vp];lib.p11_camera_controls.restype=ci
    lib.p11_camera_close.argtypes=[vp];lib.p11_camera_close.restype=ci
    lib.p11_camera_reconfigure_abi.restype=ci
    if lib.p11_camera_reconfigure_abi()!=1:raise RuntimeError('Camera reconfigure helper mismatch')
    lib.p11_camera_reconfigure.argtypes=[vp,ci,ci,ci,vp,vp,ci];lib.p11_camera_reconfigure.restype=ci
    remember(target,src,'capture',flags)
    return lib

def _mode(info,override):
    cs,enc,quant=int(info[6]),int(info[7]),int(info[8]);defaulted=[]
    if override is not None:
        if isinstance(override,bool) or override not in (0,1,2,3):raise ValueError('color_mode must be None or 0..3')
        return int(override),dict(override=True,colorspace=cs,ycbcr_encoding=enc,quantization=quant)
    if enc==0:
        if cs in (0,1,2,5,6,7,8):enc=1
        elif cs==3:enc=2
        else:raise ValueError('Unsupported camera colorspace; choose explicit verified color_mode')
        defaulted.append('YUV matrix derived from colorspace/SD default')
    if enc not in (1,2):raise ValueError('PL supports BT601/BT709; camera returned another YCbCr matrix')
    if quant==0:quant=1 if cs==7 else 2;defaulted.append('V4L2 default YUV quantization')
    if quant not in (1,2):raise ValueError('Unsupported quantization')
    return (2 if enc==2 else 0)+(1 if quant==1 else 0),dict(override=False,colorspace=cs,ycbcr_encoding=enc,quantization=quant,defaulted=defaulted)

class FrameLease:
    def __init__(self,source,pointer,meta):
        self.source=source;self.meta=tuple(int(x) for x in meta);self.released=False
        h,w,stride=source.height,source.width,source.stride
        needed=(h-1)*stride+w*2
        self.backing=(ctypes.c_uint8*needed).from_address(int(pointer))
        self.image=np.ndarray((h,w,2),np.uint8,buffer=self.backing,strides=(stride,2,1));self.image.setflags(write=False)
        self.index,self.generation,self.sequence=self.meta[:3]
        self.owner='capture_latest';self.owner_thread=threading.get_ident();self.job_index=None
        self.release_started=False;self.native_returned=False;self.retired=False
        self.ready=self.meta[6]*1e-9;self.timestamp=self.meta[5]*1e-9;self.flags=self.meta[4]
    def release(self):
        if self.released:
            if not self.retired:self.source._retire(self)
            return
        self.release_started=True
        code=self.source.lib.p11_camera_release(self.source.handle,self.index,self.generation)
        if code:raise RuntimeError('Camera QBUF failed '+str(code))
        self.native_returned=True;self.released=True;self.source._retire(self)
    def claim(self,owner,job_index=None):
        with self.source.condition:
            self.owner=str(owner);self.owner_thread=threading.get_ident();self.job_index=job_index
    def describe(self):
        return dict(buffer_index=self.index,generation=self.generation,sequence=self.sequence,
            owner=self.owner,owner_thread=self.owner_thread,job_index=self.job_index,
            release_started=self.release_started,native_returned=self.native_returned,released=self.released,retired=self.retired)
    def __enter__(self):return self
    def __exit__(self,*args):self.release()

def _bind_cpu(name):
    """P11_CPU_AFFINITY=1 时把当前线程绑到 CPU1（主线程在 notebook 里绑 CPU0）。

    2026-10-24：实测输入打包的 ctypes 调用 p50=5.68ms、p90=12.7ms，而原生只 2.38ms；
    25% 的帧超过 10ms ⇒ 不是 GIL（prepare 负载翻倍差值不变），是 OS 抢占。
    双核三线程，把两个后台线程绑到 CPU1、主线程独占 CPU0，减少互相抢占。
    """
    import os as _os
    if _os.environ.get('P11_CPU_AFFINITY') != '1':
        return
    try:
        _os.sched_setaffinity(0, {1})
    except Exception:
        pass


class CameraSource:
    def __init__(self,device='/dev/video0',width=640,height=480,fps=30,color_mode=None):
        self.lib=_library();self.handle=ctypes.c_void_p();self.info=np.zeros(16,np.uint32);message=ctypes.create_string_buffer(512)
        code=self.lib.p11_camera_open(str(device).encode(),int(width),int(height),int(fps),ctypes.byref(self.handle),self.info.ctypes.data,message,512)
        if code:raise RuntimeError(message.value.decode(errors='replace') or 'Camera open failed '+str(code))
        self.width,self.height,self.stride=map(int,self.info[:3]);self.closed=False;self.condition=threading.Condition()
        self.stop=False;self.error=None;self.latest=None;self.live_preview=None;self.leases={};self.captured=self.dropped=self.invalid=self.sequence_gaps=0;self.last_sequence=None
        self.stream_epoch=0;self._p11_stream_stabilized=False;self.worker=None;self.control_detail={};self.control_query_s=0.;self.control_next_at=0.
        self.capture_intervals=deque(maxlen=120);self.capture_clock=None;self.capture_previous=None
        try:
            self.control_workspace=np.zeros(12,np.int32);self._controls(True)
            self.color_mode,self.color_detail=_mode(self.info,color_mode)
            self.actual_fps=float(self.info[5])/max(1,int(self.info[4]))
            if abs(self.actual_fps-fps)>max(.5,fps*.03):raise ValueError('Camera negotiated '+str(self.actual_fps)+' FPS, requested '+str(fps))
            self.worker=threading.Thread(target=self._capture,name='camera_capture',daemon=True);self.worker.start()
        except BaseException:
            self.lib.p11_camera_close(self.handle);self.handle=None;self.closed=True;raise
    def _controls(self,fixed_rate=False):
        began=time.perf_counter()
        code=self.lib.p11_camera_controls(self.handle,int(bool(fixed_rate)),self.control_workspace.ctypes.data)
        a=self.control_workspace
        names=('exposure_auto','exposure_absolute','exposure_auto_priority','gain','autogain','white_balance_temperature','auto_white_balance')
        detail={name:int(a[2+i]) if int(a[0])&(1<<i) else None for i,name in enumerate(names)}
        detail.update(fixed_rate_requested=bool(fixed_rate),priority_disable_attempted=bool(int(a[1])&1),
            priority_disable_verified=bool(int(a[1])&2),control_errno=int(a[9]),query_code=int(code),
            queried_at=time.perf_counter(),exposure_unit_us=100,exposure_or_white_balance_manually_set=False)
        elapsed=time.perf_counter()-began
        with self.condition:
            self.control_detail=detail;self.control_query_s+=elapsed;self.control_next_at=time.perf_counter()+2.
    def _retire(self,lease):
        with self.condition:
            self.leases.pop((lease.index,lease.generation),None);lease.retired=True;self.condition.notify_all()
    def _capture(self):
        _bind_cpu('camera_capture')
        pointer=ctypes.c_void_p();meta=np.zeros(12,np.uint64)
        try:
            while not self.stop:
                code=self.lib.p11_camera_next(self.handle,250,ctypes.byref(pointer),meta.ctypes.data)
                if code<0:raise RuntimeError('Camera capture failed '+str(code))
                if code==0:continue
                if code==2:
                    with self.condition:self.invalid+=1
                    continue
                lease=FrameLease(self,pointer.value,meta)
                if time.perf_counter()>=self.control_next_at:self._controls(False)
                clock='driver_monotonic' if lease.flags&0xe000==0x2000 and 0<=lease.timestamp<=lease.ready else 'DQBUF_ready'
                stamp=lease.timestamp if clock=='driver_monotonic' else lease.ready
                with self.condition:
                    if clock==self.capture_clock and self.capture_previous is not None and stamp>self.capture_previous:
                        self.capture_intervals.append(stamp-self.capture_previous)
                    elif clock!=self.capture_clock:self.capture_intervals.clear()
                    self.capture_clock=clock;self.capture_previous=stamp
                    if self.last_sequence is not None:self.sequence_gaps+=max(0,((lease.sequence-self.last_sequence)&0xffffffff)-1)
                    self.last_sequence=lease.sequence;self.captured+=1;self.leases[(lease.index,lease.generation)]=lease
                    old=self.latest;self.latest=None
                # Copy only while capture owns the MMAP lease, before consumer publication.
                preview=self.live_preview
                try:
                    if preview is not None:preview.capture(lease)
                except BaseException:
                    lease.release()
                    if old is not None:old.release()
                    raise
                with self.condition:self.latest=lease;self.condition.notify_all()
                if old is not None:old.release();self.dropped+=1
        except BaseException as exc:
            with self.condition:self.error=exc;self.condition.notify_all()
    def take(self,timeout=3.):
        deadline=time.perf_counter()+timeout
        with self.condition:
            while self.latest is None:
                if self.error is not None:raise self.error
                if self.closed:raise RuntimeError('Camera is closed')
                remain=deadline-time.perf_counter()
                if remain<=0:raise TimeoutError('No valid YUYV camera frame')
                self.condition.wait(remain)
            value=self.latest
            value.claim('consumer:'+threading.current_thread().name)
            self.latest=None;return value
    def take_after(self,ready_after,timeout=3.):
        """Drop an already queued setup frame; wait for capture after handoff."""
        deadline=time.perf_counter()+float(timeout)
        while True:
            remaining=deadline-time.perf_counter()
            if remaining<=0:raise TimeoutError('No fresh YUYV frame after startup handoff')
            lease=self.take(remaining)
            if lease.ready>=ready_after:return lease
            lease.release()
    def metadata(self):
        with self.condition:
            intervals=tuple(self.capture_intervals);controls=dict(self.control_detail);query_s=self.control_query_s;clock=self.capture_clock
        observed=1./float(np.median(intervals)) if intervals else None
        return dict(capture_native_abi=3102,stream_epoch=getattr(self,'stream_epoch',0),device_format='YUYV',shape=[self.height,self.width,2],bytesperline=self.stride,
            frame_bytes=self.width*self.height*2,actual_fps=self.actual_fps,color_mode=self.color_mode,
            colorimetry=self.color_detail,mmap_buffers=int(self.info[13]),capture_frames=self.captured,
            latest_queue_drops=self.dropped,invalid_frames=self.invalid,driver_sequence_gaps=self.sequence_gaps,
            controls=controls,control_query_s=query_s,control_query_interval_s=2.,observed_capture_fps=observed,
            capture_interval_clock=clock,capture_interval_samples=len(intervals),actual_fps_scope='negotiated stream parameter; observed_capture_fps uses recent timestamp intervals')
    def retire_consumers(self,retired_workers=(),current_owner_retired=False):
        """Explicit coordinator drain AFTER all CPU readers/owner calls retire.

        Only known consumer threads are eligible. close() itself still rejects
        outstanding leases; this never guesses that an active reader is done.
        """
        if not current_owner_retired:raise RuntimeError('Owner retirement must precede consumer drain')
        ids={threading.get_ident()}
        for worker in retired_workers:
            if worker.is_alive():raise RuntimeError('Cannot drain an active consumer thread')
            if worker.ident is not None:ids.add(worker.ident)
        with self.condition:
            pending=[lease for lease in self.leases.values() if lease.owner_thread in ids
                and (lease.owner.startswith('consumer:') or lease.owner in ('prepared_queue','owner_execute'))]
            detail=[lease.describe() for lease in pending]
        if not pending:return 0
        from run_logging import checkpoint
        checkpoint('CAMERA_RETIRED_CONSUMER_DRAIN',leases=detail,consumer_threads_retired=sorted(ids),
            active_source_readers=False,force_unmap=False)
        for lease in pending:lease.release()
        return len(pending)
    def close(self):
        if self.closed:return
        self.stop=True
        if self.worker is not None:
            self.worker.join(2.)
            if self.worker.is_alive():_RETAINED.append(self);raise RuntimeError('Capture worker still active; keep MMAP alive')
        with self.condition:latest=self.latest;self.latest=None
        if latest is not None:latest.release()
        with self.condition:
            outstanding=[value.describe() for value in self.leases.values()]
        if outstanding:
            from run_logging import checkpoint
            checkpoint('CAMERA_LEASES_OUTSTANDING',durable=True,leases=outstanding,
                capture_thread_retired=True,force_unmap=False)
            _RETAINED.append(self)
            raise RuntimeError('Camera leases still referenced; drain PS/copy before closing: '+json.dumps(outstanding))
        code=self.lib.p11_camera_close(self.handle)
        if code:_RETAINED.append(self);raise RuntimeError('MMAP close rejected '+str(code))
        self.handle=None;self.closed=True
    def reconfigure(self,width,height,fps,color_mode=None):
        """Owner boundary after all consumers retire; keep fd, replace MMAP stream."""
        if self.closed or self.stop or self.error is not None:raise RuntimeError('Camera is not healthy for reconfiguration')
        width,height,fps=int(width),int(height),int(fps)
        if width<2 or height<2 or width>1280 or height>1280 or width&1 or not 1<=fps<=60:raise ValueError('Invalid camera stream parameters')
        with self.condition:
            if any(not v.released and v.owner!='capture_latest' for v in self.leases.values()):
                raise RuntimeError('Retire all consumers before stream reconfiguration')
            self.stop=True;self.live_preview=None
        if self.worker is not None:
            self.worker.join(2.)
            if self.worker.is_alive():
                _RETAINED.append(self);raise RuntimeError('Capture still active; keep MMAP pinned')
        with self.condition:latest=self.latest;self.latest=None
        if latest is not None:latest.release()
        with self.condition:
            if self.leases:raise RuntimeError('Camera leases still referenced before reconfiguration')
        info=np.zeros(16,np.uint32);message=ctypes.create_string_buffer(512)
        code=self.lib.p11_camera_reconfigure(self.handle,width,height,fps,info.ctypes.data,message,512)
        if code:
            self.error=RuntimeError('Camera reconfigure failed '+str(code)+': '+message.value.decode('utf-8','replace'))
            raise self.error
        self.info=info;self.width,self.height,self.stride=map(int,info[:3])
        self.actual_fps=float(info[5])/max(1,int(info[4]))
        if abs(self.actual_fps-fps)>max(.5,fps*.03):
            self.error=ValueError('Camera reconfigure FPS mismatch');raise self.error
        self.color_mode,self.color_detail=_mode(info,color_mode)
        self.stream_epoch=getattr(self,'stream_epoch',0)+1
        self._p11_stream_stabilized=False
        self.captured=self.dropped=self.invalid=self.sequence_gaps=0;self.last_sequence=None
        self.capture_intervals.clear();self.capture_clock=None;self.capture_previous=None
        self._controls(True);self.stop=False
        self.worker=threading.Thread(target=self._capture,name='camera_capture',daemon=True);self.worker.start()
        return self.metadata()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
