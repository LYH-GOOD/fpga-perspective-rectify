"""display —— 合并层，含 13 个原始模块。

本文件由 build/merge_layers.py 生成，不要直接编辑。
每个原始模块的边界见下方 "# ===== [NN/MM] 模块名 =====" 分节标记。
"""


from pathlib import Path
import hashlib


from pathlib import Path
import ctypes,hashlib,platform,subprocess,threading,time,json
from collections import deque
import numpy as np
from pathlib import Path
import ctypes,hashlib,platform,subprocess,time,shlex,shutil
import numpy as np
import ctypes,hashlib,time
from contextvars import copy_context
import asyncio,hashlib,os,threading,time
import cv2,numpy as np
from dataclasses import dataclass
from collections import OrderedDict
import hashlib,json,os,threading,time,xml.etree.ElementTree as ET,zlib
from collections.abc import Mapping
import hashlib,struct,threading,time,weakref
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import replace
import hashlib,math,threading
import hashlib,os,threading,time
import hashlib,threading,time,xml.etree.ElementTree as ET
import hashlib,json,time,threading
import cv2,numpy as np
import hashlib,time
import hashlib,math,time
import hashlib,time


_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ======================================================================
# ===== [01/13] v31_camera =====
# ======================================================================


"""V4L2 raw capture with generation-checked MMAP leases and latest-frame queue."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v31_camera=[]

def _library__v31_camera():
    if platform.system()!='Linux':raise RuntimeError('Camera capture runs on the PYNQ Linux board')
    root=Path(__file__).resolve().parent;src=root/'v31_camera_native.cpp'
    digest=hashlib.sha256(src.read_bytes()+platform.machine().encode()).hexdigest()[:20]
    target=root/('v31_capture_'+digest+'_'+platform.machine()+'.so')
    from tracking import restore as restore; from tracking import remember as remember
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

def _bind_cpu__v31_camera(name):
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
        self.lib=_library__v31_camera();self.handle=ctypes.c_void_p();self.info=np.zeros(16,np.uint32);message=ctypes.create_string_buffer(512)
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
        _bind_cpu__v31_camera('camera_capture')
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
        from core import checkpoint as checkpoint
        checkpoint('CAMERA_RETIRED_CONSUMER_DRAIN',leases=detail,consumer_threads_retired=sorted(ids),
            active_source_readers=False,force_unmap=False)
        for lease in pending:lease.release()
        return len(pending)
    def close(self):
        if self.closed:return
        self.stop=True
        if self.worker is not None:
            self.worker.join(2.)
            if self.worker.is_alive():_RETAINED__v31_camera.append(self);raise RuntimeError('Capture worker still active; keep MMAP alive')
        with self.condition:latest=self.latest;self.latest=None
        if latest is not None:latest.release()
        with self.condition:
            outstanding=[value.describe() for value in self.leases.values()]
        if outstanding:
            from core import checkpoint as checkpoint
            checkpoint('CAMERA_LEASES_OUTSTANDING',durable=True,leases=outstanding,
                capture_thread_retired=True,force_unmap=False)
            _RETAINED__v31_camera.append(self)
            raise RuntimeError('Camera leases still referenced; drain PS/copy before closing: '+json.dumps(outstanding))
        code=self.lib.p11_camera_close(self.handle)
        if code:_RETAINED__v31_camera.append(self);raise RuntimeError('MMAP close rejected '+str(code))
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
                _RETAINED__v31_camera.append(self);raise RuntimeError('Capture still active; keep MMAP pinned')
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


# ======================================================================
# ===== [02/13] v64_io =====
# ======================================================================


"""Small CPU-only helper; compile on PYNQ, ctypes calls release the GIL."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB=None
_BUILD_INFO={}

def prepare_io(cancel=None):
    global _LIB
    if _LIB is not None:return _LIB
    from tracking import setup_command as setup_command; from tracking import check_cancel as check_cancel
    from core import checkpoint as checkpoint
    check_cancel(cancel)
    if platform.system()!='Linux':raise RuntimeError('V73 runs on PYNQ Linux')
    root=Path(__file__).resolve().parent;src=root/'v64_io.cpp'
    flags=['-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared']
    if platform.machine()=='armv7l':flags.append('-mfpu=neon')
    # CPU-only optional OpenCV H solver. Missing/mismatched headers leave the
    # legacy cv2+mapping+guard path available; no hardware fallback is allowed.
    cv_flags=[];cv_version=None;pkg=shutil.which('pkg-config');reason='pkg_config_unavailable'
    if pkg:
        import cv2
        try:
            probe=setup_command([pkg,'--modversion','opencv4'],10,cancel,'IO_OPENCV_VERSION')
            reason='opencv_development_package_missing_or_version_mismatch'
            if probe.returncode==0 and probe.stdout.strip()==cv2.__version__:
                found=setup_command([pkg,'--cflags','--libs','opencv4'],10,cancel,'IO_OPENCV_FLAGS')
                if found.returncode==0:
                    cv_flags=shlex.split(found.stdout);cv_version=probe.stdout.strip();reason='matching_opencv'
        except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
            reason='opencv_probe_failed:'+type(exc).__name__
    base_flags=list(flags);cache_entry=None
    def load_variant(with_opencv):
        nonlocal cache_entry
        actual_flags=base_flags+(['-DP11_V70_OPENCV'] if with_opencv else [])
        actual_cv=cv_flags if with_opencv else []
        flags_key=actual_flags+actual_cv+([cv_version] if with_opencv else [])
        digest=hashlib.sha256(src.read_bytes()+platform.machine().encode()+' '.join(flags_key).encode()).hexdigest()[:20]
        target=root/('v73_io_'+digest+'_'+platform.machine()+'.so')
        from tracking import restore as restore
        restore(target,src,'io',flags_key,cancel)
        cache_entry=(target,src,'io',flags_key)
        if not target.is_file():
            temp=target.with_suffix('.tmp.so')
            try:
                command=['g++']+actual_flags+[str(src),'-o',str(temp)]+actual_cv
                result=setup_command(command,90,cancel,'IO_BUILD')
                if result.returncode:raise subprocess.CalledProcessError(result.returncode,command,result.stdout,result.stderr)
                check_cancel(cancel);temp.replace(target)
            finally:
                if temp.exists():temp.unlink()
        check_cancel(cancel)
        checkpoint('IO_LOAD_BEGIN',path=str(target),hardware_access=False)
        return ctypes.CDLL(str(target))
    try:lib=load_variant(cv_version is not None)
    except (OSError,subprocess.CalledProcessError) as exc:
        if cv_version is None:raise
        reason='optional_opencv_build_or_load_failed:'+type(exc).__name__
        lib=load_variant(False)
    _BUILD_INFO.update(optional_geometry_reason=reason,opencv_development_version=cv_version,
        geometry_available=bool(lib.p11_v70_geometry_available()),path=str(lib._name))
    vp=ctypes.c_void_p;ci=ctypes.c_int
    lib.p11_v64_abi.argtypes=[];lib.p11_v64_abi.restype=ci
    if lib.p11_v64_abi()!=6601:raise RuntimeError('V70 P1 IO ABI mismatch')
    lib.p11_v64_pack.argtypes=[vp]+[ci]*8+[vp,ctypes.c_size_t]
    #   ⭐ C2：YUYV 原样按行搬（count = src ptr + ss,sw,sh + x0,y0,w,h,ds + dst ptr + bytes）
    lib.p11_v64_copy_rows.argtypes=[vp]+[ci]*8+[vp,ctypes.c_size_t]
    lib.p11_v64_copy_rows.restype=ci
    lib.p11_v64_guard.argtypes=[vp]+[ci]*5+[vp]
    lib.p11_v65_guard_interval.argtypes=[vp]+[ci]*7+[ctypes.c_double,vp]
    lib.p11_v65_guard_interval.restype=ci
    lib.p11_v64_parameters.argtypes=[vp,vp,vp]
    lib.p11_v64_arm.argtypes=[vp]+[ctypes.c_uint32]*4
    lib.p11_v64_poll.argtypes=[vp,vp,ctypes.c_uint32,ctypes.c_double,vp]
    for name in ('pack','guard','parameters','arm','poll'):getattr(lib,'p11_v64_'+name).restype=ci
    lib.p11_v66_caps.argtypes=[];lib.p11_v66_caps.restype=ci
    lib.p11_v66_yuyv_bgr.argtypes=[vp]+[ci]*4+[vp,ci,ctypes.c_size_t]
    lib.p11_v66_bgra_bgr.argtypes=[vp]+[ci]*3+[vp,ci,ctypes.c_size_t]
    lib.p11_v66_mapping.argtypes=[vp,vp,ci,ci,vp,vp]
    for name in ('yuyv_bgr','bgra_bgr','mapping'):getattr(lib,'p11_v66_'+name).restype=ci
    lib.p11_v70_plan_abi.argtypes=[];lib.p11_v70_plan_abi.restype=ci
    if lib.p11_v70_plan_abi()!=7001:raise RuntimeError('V70 CPU plan ABI mismatch')
    lib.p11_v70_geometry_available.argtypes=[];lib.p11_v70_geometry_available.restype=ci
    lib.p11_v70_plan_create.argtypes=[];lib.p11_v70_plan_create.restype=vp
    lib.p11_v70_plan_destroy.argtypes=[vp];lib.p11_v70_plan_destroy.restype=None
    lib.p11_v70_plan_batch.argtypes=[vp,vp]+[ci]*4+[vp,ci,ci,ctypes.c_double]+[vp]*5
    lib.p11_v70_plan_batch.restype=ci
    _LIB=lib
    from tracking import remember as remember
    remember(*cache_entry)
    return lib

def copy_yuyv_rows(image,crop,dst,offset=0):
    #   ⭐ 2026-10-24 C2：只搬 YUYV，不做颜色转换 —— 每行一次 memcpy（C++ 里）。
    #   ⚠️ 不要退回到 numpy 的三维赋值：numpy 对 (h,w,2) 的跨步赋值会退化成
    #      逐 2 字节，实测 51,000 px 要 4.88 ms（比老的整段转换还慢一倍）。
    x,y,w,h=map(int,crop)
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=2 or image.strides[1:]!=(2,1):
        raise ValueError('Raw YUYV layout invalid')
    if dst.dtype!=np.uint8 or not dst.flags.c_contiguous:raise ValueError('Copy workspace must be contiguous uint8')
    n=w*h*2
    if (x&1) or (w&1):raise ValueError('YUYV crop must be even-aligned')
    if offset<0 or offset+n>dst.nbytes:raise ValueError('Copy destination span exceeds workspace')
    code=prepare_io().p11_v64_copy_rows(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],
        x,y,w,h,w*2,int(dst.ctypes.data)+int(offset),int(dst.nbytes)-int(offset))
    if code:raise ValueError('YUYV row copy failed '+str(code))

def pack_yuyv(image,crop,mode,dst):
    x,y,w,h=map(int,crop)
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=2 or image.strides[1:]!=(2,1):raise ValueError('Raw YUYV layout invalid')
    if dst.dtype!=np.uint8 or not dst.flags.c_contiguous:raise ValueError('Pack workspace must be contiguous uint8')
    code=prepare_io().p11_v64_pack(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],x,y,w,h,int(mode),dst.ctypes.data,dst.nbytes)
    if code:raise ValueError('YUYV to BGRX pack failed '+str(code))

def guard(regs,input_size,output_size,*,strategy='fast_safe',cpu_budget_s=.008,block_pixels=128,workspace=None):
    """Only complete sufficient receipts are valid; budget prefixes are rejected."""
    a=np.ascontiguousarray(regs if workspace is None else workspace.mapping[4:],dtype=np.int32)
    if a.shape!=(8,):raise ValueError('P1 requires eight coefficients')
    if strategy not in ('fast_safe','exact_reference'):raise ValueError('Unknown P1 proof strategy')
    lib=prepare_io();begin=time.perf_counter();cpu=time.thread_time()
    if strategy=='exact_reference':
        out=np.zeros(2,np.int32) if workspace is None else workspace.guard_out[:2];out.fill(0)
        code=lib.p11_v64_guard(a.ctypes.data,*map(int,input_size),*map(int,output_size),384,out.ctypes.data)
        return dict(valid=code==0,code=int(code),peak_rows=int(out[0]) if code==0 else None,
            checked_pixels=int(out[1]) if code==0 else None,failure_at=out.tolist() if code else None,
            proof_s=time.perf_counter()-begin,proof_thread_cpu_s=time.thread_time()-cpu,
            method='whole_source_crop_retention_and_operand_bounds' if input_size[1]<=384 else 'native_exact_fixed_point_conservative_lifetime',
            complete_domain_verified=code==0,proof_strategy=strategy,proof_cached=False)
    out=np.zeros(8,np.int32) if workspace is None else workspace.guard_out;out.fill(0)
    #   ⚠️⚠️ 2026-10-25：这个 rows 必须等于 C++ 里 `p11_v65_guard_interval` 的校验值，
    #      否则返回 **-1（参数非法）** ⇒ 证明失败 ⇒ 该帧 HELD/LOST ⇒
    #      "明明找到了却一直重找"。**这个 192 曾经漏改，导致 5% 的帧掉 LOST。**
    from core import LINE_BUF_ROWS as _LBR
    code=lib.p11_v65_guard_interval(a.ctypes.data,*map(int,input_size),*map(int,output_size),int(_LBR),
        int(block_pixels),8192,float(cpu_budget_s),out.ctypes.data)
    return dict(valid=code==0,code=int(code),peak_rows=int(out[0]) if code==0 else None,
        checked_pixels=int(out[1]),interval_blocks=int(out[2]),subdivided_blocks=int(out[3]),
        proof_nodes=int(out[6]),failure_at=[int(out[4]),int(out[5])] if code else None,
        proof_s=time.perf_counter()-begin,proof_thread_cpu_s=time.thread_time()-cpu,
        method='whole_source_crop_retention_and_operand_bounds' if out[7]==0 else 'bounded_fixed_point_interval_lifetime',
        complete_domain_verified=code==0,budget_inconclusive=code==-5,proof_strategy=strategy,
        proof_cached=False,cpu_budget_s=float(cpu_budget_s),interval_block_pixels=int(block_pixels),
        exact_reference_fallback=False)


def poll(dma,regs,expected,seconds=.002,out=None):
    out=np.zeros(4,np.uint32) if out is None else out
    if out.dtype!=np.uint32 or out.shape!=(4,) or not out.flags.c_contiguous:raise ValueError('Invalid owner poll workspace')
    result=prepare_io().p11_v64_poll(dma.ctypes.data,regs.ctypes.data,int(expected),float(seconds),out.ctypes.data)
    return int(result),tuple(map(int,out))

def parameters(regs,packet,out=None):
    words=np.frombuffer(packet,np.uint32)
    if words.shape!=(10,):raise ValueError('P1 parameter packet must be10 words')
    out=np.zeros(2,np.uint32) if out is None else out
    if out.dtype!=np.uint32 or out.shape!=(2,) or not out.flags.c_contiguous:raise ValueError('Invalid parameter workspace')
    code=prepare_io().p11_v64_parameters(regs.ctypes.data,words.ctypes.data,out.ctypes.data)
    if code:raise RuntimeError('P1 parameter readback failed '+str((code,out.tolist())))
    return int(out[1])

def arm(dma,receive,send,nout,nin):
    if not 0<int(receive)<(1<<32) or not 0<int(send)<(1<<32):raise ValueError('P1 DMA address must be32bit CMA')
    if int(receive)%4 or int(send)%4:raise ValueError('P1 non-DRE DMA requires four-byte aligned addresses')
    code=prepare_io().p11_v64_arm(dma.ctypes.data,int(receive),int(send),int(nout),int(nin))
    if code:raise RuntimeError('P1 DMA arm failed '+str(code))


class PlanWorkspace:
    """Single PS planner thread owns these small arrays; tiles copy their packet."""
    def __init__(self):
        self.h=np.empty((3,3),np.float64);self.box=np.empty(4,np.int32)
        self.mapping=np.empty(12,np.int32);self.packet=np.empty(10,np.uint32)
        self.guard_out=np.empty(8,np.int32)
        self.output_corners=np.empty((4,2),np.float32);self.output_size=None
        self.batch=PlanBatchWorkspace(32)
    def close(self):self.batch.close()
    def destination(self,size):
        if self.output_size!=tuple(size):
            w,h=map(int,size);self.output_corners[:]=((0,0),(w-1,0),(w-1,h-1),(0,h-1))
            self.output_size=tuple(size)
        return self.output_corners
    def map_tile(self,h,box,input_size):
        np.copyto(self.h,h);self.box[:]=box
        code=prepare_io().p11_v66_mapping(self.h.ctypes.data,self.box.ctypes.data,
            int(input_size[0]),int(input_size[1]),self.mapping.ctypes.data,self.packet.ctypes.data)
        if code:return None,('invalid_domain','denominator','source_crop_empty','input_or_dma_limit','coefficient_overflow')[min(4,max(0,-int(code)-1))]
        return (tuple(map(int,self.mapping[:4])),tuple(map(int,self.mapping[4:])),self.packet.tobytes()),None


def _bgr_destination(frame,rect,source_shape):
    if frame.dtype!=np.uint8 or frame.ndim!=3 or frame.shape[2]!=3 or not frame.flags.c_contiguous or not frame.flags.writeable:
        raise ValueError('BGR destination must be a writable contiguous backing frame')
    x,y,w,h=map(int,rect)
    if (h,w)!=tuple(source_shape[:2]) or x<0 or y<0 or x+w>frame.shape[1] or y+h>frame.shape[0]:
        raise ValueError('Native BGR rectangle does not match source/frame bounds')
    stride=int(frame.strides[0]);offset=y*stride+x*3;available=frame.nbytes-offset
    if available<(h-1)*stride+w*3:raise ValueError('Native BGR destination span exceeds backing storage')
    return frame.ctypes.data+offset,stride,available


def yuyv_bgr_into(image,mode,frame,rect):
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=2 or image.strides[1:]!=(2,1) or image.strides[0]<image.shape[1]*2:
        raise ValueError('Native YUYV source layout invalid')
    ptr,stride,available=_bgr_destination(frame,rect,image.shape)
    code=prepare_io().p11_v66_yuyv_bgr(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],int(mode),ptr,stride,available)
    if code:raise ValueError('Native YUYV to BGR failed '+str(code))


def bgra_bgr_into(image,frame,rect):
    if image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=4 or image.strides[1:]!=(4,1) or image.strides[0]<image.shape[1]*4:
        raise ValueError('Native BGRX source layout invalid')
    ptr,stride,available=_bgr_destination(frame,rect,image.shape)
    code=prepare_io().p11_v66_bgra_bgr(image.ctypes.data,int(image.strides[0]),image.shape[1],image.shape[0],ptr,stride,available)
    if code:raise ValueError('Native BGRX to BGR failed '+str(code))


# ======================================================================
# ===== [03/13] v71_display =====
# ======================================================================


"""Owner-local bounded CPU display workspaces; no hardware access or frame ownership."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def _library__v71_display():
    lib=prepare_io()
    if getattr(lib,'_v73_display_bound',False):return lib
    vp=ctypes.c_void_p;ci=ctypes.c_int;sz=ctypes.c_size_t
    lib.p11_v71_display_abi.argtypes=[];lib.p11_v71_display_abi.restype=ci
    if lib.p11_v71_display_abi()!=7301:raise RuntimeError('V73 display ABI mismatch; restart kernel with complete new folder')
    lib.p11_v73_display_caps.argtypes=[];lib.p11_v73_display_caps.restype=ci
    lib.p11_v71_display_create.argtypes=[];lib.p11_v71_display_create.restype=vp
    lib.p11_v71_display_destroy.argtypes=[vp];lib.p11_v71_display_destroy.restype=None
    lib.p11_v71_display_scale.argtypes=[vp,vp,sz]+[ci]*5+[vp]+[ci]*3+[sz,vp]
    lib.p11_v71_display_scale.restype=ci
    lib.p11_v71_display_copy.argtypes=[vp,vp,sz,vp,vp,sz,vp];lib.p11_v71_display_copy.restype=ci
    lib._v73_display_bound=True;return lib

class FusedDisplay:
    """Only HDMI owner calls scale/close; paired-copy stats have one producer."""
    def __init__(self):
        self.lib=_library__v71_display();self.contexts=[];self.stats=[np.empty(7,np.float64) for _ in range(2)]
        self.polyphase_backend='native_NEON_5_4_exact_Q3' if self.lib.p11_v73_display_caps()&1 else 'native_scalar_5_4_exact_Q3' 
        try:
            for _ in range(2):
                ptr=self.lib.p11_v71_display_create()
                if not ptr:raise MemoryError('V71 native HDMI workspace allocation failed')
                self.contexts.append(ptr)
        except BaseException:self.close();raise
    def close(self):
        for ptr in self.contexts:self.lib.p11_v71_display_destroy(ptr)
        self.contexts.clear()
    def scale(self,side,image,mode,frame,rect):
        if side not in (0,1) or len(self.contexts)!=2:raise RuntimeError('HDMI workspace closed or invalid side')
        kind=2 if side==0 else 4
        if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=kind
                or not image.flags.c_contiguous):raise ValueError('V71 display source must be contiguous YUYV/BGRX snapshot')
        x,y,w,h=map(int,rect);ptr,stride,available=_bgr_destination(frame,rect,(h,w))
        s=self.stats[side];begin=time.perf_counter();cpu=time.thread_time()
        code=self.lib.p11_v71_display_scale(self.contexts[side],image.ctypes.data,image.nbytes,
            int(image.strides[0]),image.shape[1],image.shape[0],kind,int(mode),ptr,stride,w,h,available,s.ctypes.data)
        if code:raise ValueError('V71 fused display scale failed '+str(code))
        return dict(wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu,
            native_wall_s=float(s[0]),native_thread_cpu_s=float(s[1]),map_build_s=float(s[2]),
            map_rebuilt=bool(s[3]),source_rows=int(s[4]),direct=bool(s[5]),
            source_shape=list(image.shape),destination_rect=list(rect),destination_stride=stride,
            backend=('native_NEON_5_4_nearest_Q3' if int(s[6])==2 else self.polyphase_backend) if s[6] else 'native_convert_then_bilinear_Q11_rows',
            polyphase_5_4_used=bool(s[6]),interpolation='pixel_center_bilinear_Q11_equivalent',source_channels=kind)

def paired_copy(lib,raw,raw_dst,out,out_dst,stats):
    """Producer keeps source lease/CMA output and destination reservation through this call."""
    for image,destination in ((raw,raw_dst),(out,out_dst)):
        if image is None:continue
        if (image.dtype!=np.uint8 or not image.flags.c_contiguous or destination.dtype!=np.uint8
                or not destination.flags.c_contiguous or not destination.flags.writeable
                or image.nbytes>destination.nbytes):raise ValueError('Invalid display paired-copy span')
        a=int(image.ctypes.data);b=int(destination.ctypes.data)
        if a<b+image.nbytes and b<a+image.nbytes:raise ValueError('Display copy source overlaps reserved destination')
    code=lib.p11_v71_display_copy(0 if raw is None else raw.ctypes.data,raw_dst.ctypes.data,
        0 if raw is None else raw.nbytes,0 if out is None else out.ctypes.data,out_dst.ctypes.data,
        0 if out is None else out.nbytes,stats.ctypes.data)
    if code:raise ValueError('V71 display paired copy failed '+str(code))
    return float(stats[0]),float(stats[1])


# ======================================================================
# ===== [04/13] v64_hdmi_display =====
# ======================================================================


"""Same-frame P1 INPUT | RECTIFIED, exact user pair, finite status submission.

Display owns all VideoFrames. CPU snapshots isolate both MMAP and remap CMA.
Automatic raw snapshots are immutable ordinary RAM, retained in two slots.
This uses P1's24bit BGR configure/binding and direct-to-VDMA composition.
"""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
from ui import footer as hybrid_footer
from ui import valid_continuity as valid_continuity
from ui import LiveUI as LiveUI
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SUPPORTED_MODES=((640,480),(1280,720),(1024,600))
_RETAINED__v64_hdmi_display=[]


def _current_tap_quad(meta,shape,generation,submitted,now):
    """Event-only evidence from the already submitted source; no image reads."""
    if (meta.get('ui_generation')!=generation or meta.get('state')!='CURRENT'
            or meta.get('admission_mode')=='manual' or meta.get('recovery_active')
            or meta.get('epoch') is None):return None
    try:
        ages=(now-float(submitted),now-float(meta['capture_ready_at']),now-float(meta['verified_at']))
        if not all(np.isfinite(age) and 0.<=age<=limit for age,limit in zip(ages,(.25,.35,.35))):return None
        q=np.asarray(meta.get('corners',()),np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q):return None
        h,w=shape[:2]
        if np.any(q<0.) or np.any(q[:,0]>w-1) or np.any(q[:,1]>h-1):return None
        shortest=float(np.min(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)))
        if shortest<24. or abs(cv2.contourArea(q))<576.:return None
        return q,max(12.,.05*shortest),shortest
    except (KeyError,TypeError,ValueError,OverflowError,cv2.error):return None


class PageFeedback:
    """Event-only compositor, removed from the instance after each interaction.

    Only the HDMI owner paints an unsubmitted canvas. No submitted VideoFrame,
    camera image, output lease, timer or background worker is retained here.
    """
    def __init__(self,display):
        self.display=display;self.loading=None;self.point=None;self.revision=0
        self.painted=set();self.entry_regions={};self.handler=self.submit;self.original=None;self.previous=None
        self.live_handler=self.live_frame
    def _attach_locked(self):
        d=self.display
        if d.__dict__.get('_submit') is self.handler:return
        # TargetSwitch temporarily captures _submit while freezing a canvas.
        # Its ownership transaction always has priority over cosmetic events.
        if d.target_switch is not None:return
        self.previous=d.__dict__.get('_submit');self.original=d._submit
        d._submit=self.handler
    def _detach_locked(self):
        d=self.display
        if d.__dict__.get('_feedback_live') is self.live_handler:del d._feedback_live
        if d.__dict__.get('_submit') is self.handler:
            if self.previous is None:del d._submit
            else:d._submit=self.previous
    def _invalidate_locked(self):
        for key in self.painted:self.display.canvas_views.pop(key,None)
        self.painted.clear()
    def _wake_locked(self):
        d=self.display
        if d.ui_view=='home':d.ui_dirty=True
        elif d.inspection.kind is not None:d.inspection.dirty=True
        elif d.ui_view=='snapshot' and d.last_static_packet is not None:d.inspection_restore=True
        d.condition.notify_all()
    def cancel(self):
        with self.display.condition:
            self.loading=self.point=None;self.revision+=1
            self.entry_regions.clear()
            self._invalidate_locked();self._detach_locked()
    def begin(self,view,generation,kind):
        d=self.display
        with d.condition:
            self._invalidate_locked();self.point=None;self.revision+=1
            until=('home' if view=='home' else 'inspection' if kind in ('calibration','zoom','album') else 'output')
            self.entry_regions.clear()
            self.loading=dict(view=view,generation=int(generation),kind=kind,
                stage='prepare' if kind in ('enter','ai_calibration') else kind,until=until)
            if kind=='ai_calibration':d._feedback_live=self.live_handler
            elif d.__dict__.get('_feedback_live') is self.live_handler:del d._feedback_live
            self._attach_locked()
        checkpoint('UI_NAVIGATION_BEGIN',generation=generation,page=view,kind=kind,
            event_driven=True,artificial_delay=False)
    def live_frame(self,meta,has_output):
        # Only present while an explicit AI navigation is unresolved. Called by
        # the owner for the exact canvas about to be submitted, never pixels.
        with self.display.condition:
            load=self.loading
            if load is None or load['kind']!='ai_calibration' or meta.get('ui_generation')!=load['generation']:return
            stage={'AI_LOADING':'prepare','AI_INFER':'search','AI_CONFIRM':'verify'}.get(meta.get('hybrid_phase'))
            if stage is not None and stage!=load['stage']:load['stage']=stage;self.revision+=1
            load['live_settled']=bool(has_output or meta.get('hybrid_phase') in
                ('RECOVERY_COOLDOWN','WAIT_TARGET','EMPTY_WAIT','AI_ERROR'))
    def phase(self,phase,generation):
        stage={'prepare':'prepare','edges':'search','verify':'verify','display':'display'}.get(phase)
        with self.display.condition:
            load=self.loading
            if load is None or load['generation']!=generation or load['until']!='output' or stage is None:return
            if load['kind']=='layout':return
            ranks={'prepare':0,'snapshot':0,'search':1,'verify':2,'display':3}
            if ranks.get(stage,0)<=ranks.get(load['stage'],-1):return
            load['stage']=stage;self.revision+=1
            self._wake_locked()
    def touch(self,event,result,generation):
        d=self.display;phase=event.get('phase');target=result.get('target') or ''
        # RatioUI owns its selection/focus feedback. The generic ring otherwise
        # dirties the frozen panel twice and invalidates its background cache.
        if target.startswith(('ratio_','hold_')):return
        if phase=='press' and target=='media_back' and result.get('accepted'):
            self.begin(d.ui_view,generation,'layout')
            with d.condition:self._wake_locked()
            return
        with d.condition:
            if phase=='press':
                if (result.get('generation')!=generation or not target or result.get('consumed')
                    or target in ('inspect_point','media_background') or d.target_switch is not None):return
                point=event.get('press')
                if point is None:return
                rect=None
                names={'manual_calibration':'manual','reading_zoom':'zoom','refind':'refind',
                    'layout_toggle':'layout_switch','snapshot_recapture':'snapshot_recapture'}
                if target in names:rect=getattr(d.ui_assets,names[target],None)
                self._invalidate_locked();self.point=dict(point=tuple(map(int,point)),rect=rect,generation=generation)
                self.revision+=1;self._attach_locked();self._wake_locked()
                checkpoint('UI_PRESS_FEEDBACK',generation=generation,target=target,event_only=True)
            elif phase in ('release','cancel'):
                self.point=None;self.revision+=1;self._invalidate_locked()
                if phase=='cancel' and self.loading is None:self._detach_locked()
                if self.loading is None:self._detach_locked()
                self._wake_locked()
        if phase!='release' or not result.get('accepted') or d.target_switch is not None:return
        reason=result.get('reason') or ''
        if target=='reading_zoom':kind='zoom'
        elif target.startswith('media_') and target!='media_capture':kind='layout' if target=='media_back' else 'album'
        elif reason.startswith('reading_closed'):kind='layout'
        else:return
        self.begin(d.ui_view,generation,kind)
        with d.condition:self._wake_locked()
    async def submit(self,frame):
        d=self.display
        with d.condition:
            load=None if self.loading is None else dict(self.loading)
            point=None if self.point is None else dict(self.point)
            revision=self.revision;original=self.original
            if load is None and point is None:self._detach_locked()
            key=int(frame.physical_address);token=d.canvas_views.get(key)
            valid=bool(token and len(token)>=2 and token[1]==d.ui_generation)
            if load is not None:
                valid=bool(valid and load['generation']==d.ui_generation)
                if token and token[0]=='target_switch':valid=False
            complete=False
            if load is not None and valid:
                if load['until']=='home':complete=token[0]=='home'
                elif load['until']=='inspection':
                    complete=bool(token[0]=='inspection' and len(token)>=3 and token[2]==d.inspection.token
                        and d.inspection.kind==load['kind'])
                    if load['kind']=='album' and d.media is not None:
                        complete=bool(complete and not d.media.model.get('busy',False))
                else:complete=bool(token[0]==load['view'] and
                    (d.layouts.get(key,(None,None))[1] is not None or load.get('live_settled',False)))
        # All access to frame pixels precedes the official VDMA handoff.
        if valid and (load is not None or point is not None):
            canvas=np.asarray(frame);painted=False
            old_entry=self.entry_regions.get(key)
            if complete and old_entry is not None:
                x,y,w,h=old_entry;right=d.layouts.get(key,(None,None))[1]
                # Erase only placeholder pixels outside the already composed
                # real output. Result geometry may be portrait or landscape.
                if right is not None:
                    rx,ry,rw,rh=right;lo=max(x,rx);hi=min(x+w,rx+rw);top=max(y,ry);bottom=min(y+h,ry+rh)
                    if lo>=hi or top>=bottom:canvas[y:y+h,x:x+w]=0
                    else:
                        canvas[y:top,x:x+w]=0;canvas[bottom:y+h,x:x+w]=0
                        canvas[top:bottom,x:lo]=0;canvas[top:bottom,hi:x+w]=0
                    painted=True
            fixed_status=bool(hasattr(d.ui_assets,'live_ui_parts') and token[0] in ('compare','rectified'))
            if load is not None and load['kind']=='enter' and not complete and token[-1] not in ('live_progress','fixed_live') and not fixed_status:
                # A single cached status tile on an already-owned startup
                # canvas. Phase changes alone advance it; no animation clock.
                x=(canvas.shape[1]//2 if load['view']=='rectified' else canvas.shape[1]*3//4)-160
                y=canvas.shape[0]//2-52
                canvas[y:y+112,x:x+320]=d.ui_assets.entry_progress[load['stage']]
                canvas[74:118]=0  # No second segmented bar or target hint.
                painted=True
                with d.condition:
                    self.entry_regions[key]=(x,y,320,112)
            if load is not None and load['kind']!='enter' and not (complete and load['until']=='output') and not fixed_status:
                stage='ready' if complete else load['stage']
                canvas[74:106]=d.ui_assets.navigation_progress[stage]
                painted=True
                if token[0] in ('compare','rectified') and d.layouts.get(key,(None,None))[1] is None:
                    canvas[106:118,:640]=0  # Old hint text fringes; no image occupies these rows.
            if point is not None and point['generation']==d.ui_generation:
                painted=True
                if point['rect'] is not None:
                    x,y,w,h=point['rect'];cv2.rectangle(canvas,(x+2,y+2),(x+w-3,y+h-3),(90,235,245),2,cv2.LINE_AA)
                else:
                    x,y=point['point'];cv2.circle(canvas,(x,y),16,(90,235,245),2,cv2.LINE_AA)
                    cv2.circle(canvas,(x,y),3,(90,235,245),-1,cv2.LINE_AA)
            canvas=None
            if painted:
                with d.condition:self.painted.add(key)
        result=await original(frame)
        # Metadata only after handoff. Never read frame or its NumPy view here.
        with d.condition:
            if complete and revision==self.revision and self.loading is not None:
                finished=self.loading;self.loading=None;self.revision+=1
                self.entry_regions.clear()
                self._invalidate_locked()
                if self.point is None:self._detach_locked()
                self._wake_locked()  # One event redraw removes the completed strip.
            else:finished=None
        if finished is not None:
            checkpoint('UI_NAVIGATION_PRESENTED',generation=finished['generation'],page=finished['view'],
                kind=finished['kind'],event_only=True,physical_scan_time_measured=False)
        return result


from ui import TargetSwitch as TargetSwitch


def fit_panel_shape(mode, input_shape):
    """把摄像头尺寸等比缩进左边面板；放得下就原样返回（640x480 时不变）。

    ⚠️ 2026-10-28：`native_display_rect()` 只接受"1:1 放得下"的尺寸，
       而 800x600 放不进 640x656 的面板 ⇒ 所有用它算矩形的地方都必须先过这里。
    """
    cw, ch = map(int, mode); h, w = map(int, input_shape)
    pw = min(cw // 2, cw - (cw // 2)); ph = ch - 64
    if w <= pw and h <= ph: return (h, w)
    s = min(float(pw) / max(1, w), float(ph) / max(1, h))
    return (max(2, int(round(h * s)) // 2 * 2), max(2, int(round(w * s)) // 2 * 2))


def native_display_rect(mode,shape,side):
    """Center the complete source image at 1:1; never resize or crop it."""
    if side not in (0,1) or len(mode)!=2 or len(shape)!=2:
        raise ValueError('Invalid native HDMI panel layout')
    canvas_w,canvas_h=map(int,mode);h,w=map(int,shape)
    mid=canvas_w//2;x=0 if side==0 else mid
    width=mid if side==0 else canvas_w-mid;height=canvas_h-64
    if min(w,h,width,height)<1 or w>width or h>height:
        raise ValueError('V74 displays complete images at1:1 without scaling/cropping: '
            +str((w,h))+' does not fit panel '+str((width,height))+'; use1280x720 for default camera/output')
    return x+(width-w)//2,36+(height-h)//2,w,h

def validate_overlay(overlay,manifest):
    required=('remap','axi_dma_0','video/axi_vdma_disp','video/hdmi_out/frontend/vtc_out',
              'video/hdmi_out/frontend/axi_dynclk','video/hdmi_out/pixel_unpack','video/hdmi_out/color_convert')
    missing=[k for k in required if k not in overlay.ip_dict]
    if missing:raise RuntimeError('Specified P1 overlay missing '+str(missing))
    if int(overlay.ip_dict['remap']['phys_addr'])!=0x40000000:raise RuntimeError('P1 remap address mismatch')
    params=overlay.ip_dict['video/axi_vdma_disp']['parameters']
    for key,value in (('C_INCLUDE_MM2S',1),('C_INCLUDE_S2MM',0),('C_M_AXIS_MM2S_TDATA_WIDTH',32),('C_NUM_FSTORES',4)):
        if int(params.get(key,-1))!=value:raise RuntimeError('HDMI VDMA mismatch '+key)
    from pynq import MMIO
    actual=int(MMIO(0x40000000,0x40).read(0x30));expected=int(manifest['remap_version'])
    checkpoint('P1_HARDWARE_IDENTITY',actual_version=actual,expected_version=expected,
        actual_hex='0x%08x'%actual,expected_hex='0x%08x'%expected,matched=actual==expected)
    if actual!=expected:
        raise RuntimeError('P1 VERSION mismatch: actual=0x%08x expected=0x%08x; '
            'use the complete matching bit/HWH/software package'%(actual,expected))

class HdmiLatest:
    manual_status_template='MANUAL %s | M-CORR %.1f | DISP %.1f | %s'
    @staticmethod
    def _fit_shape(mode, input_shape):
        return fit_panel_shape(mode, input_shape)
    def __init__(self,overlay,mode=(1280,720),capacity=(362,512),timeout_s=3.,hold_max_age_s=1.5,
                 input_shape=(480,640),max_fps=30.,ui_assets=None,
                 capture_dir='/home/xilinx/captures',capture_jpeg_quality=90):
        if tuple(mode) not in SUPPORTED_MODES:raise ValueError('HDMI mode640x480/1280x720/1024x600 only')
        if not 1<=float(max_fps)<=30:raise ValueError('HDMI rate1..30 only')
        self.overlay=overlay;self.mode=tuple(mode);self.timeout=float(timeout_s);self.hold_max_age=float(hold_max_age_s)
        #   ⭐ 2026-10-27：允许摄像头分辨率大于面板（例如 800x600）。
        #      `native_display_rect()` 只接受"1:1 放得下"的尺寸，所以这里先算一个
        #      **显示用尺寸**（等比缩到能放下面板），raw 在 `_draw()` 里缩到这个尺寸。
        #      640x480 时两者相同，行为与改动前一模一样。
        self.display_shape=self._fit_shape(self.mode,input_shape)
        native_display_rect(self.mode,self.display_shape,0)
        #   ⭐ 2026-10-28：左预览「缩放 + YUYV→BGR」的备用工作区与取值开关。
        #      首选是 `FusedDisplay`（原生 NEON 5:4 多相），**懒创建**——
        #      启动阶段不能同步编译"正在展示其就绪状态"的那个原生库。
        self._scaled=None;self._fused=None;self._fused_failed=False
        self._preview_nearest=os.environ.get('P11_PREVIEW_NEAREST','1')!='0'
        #   ⭐ 2026-10-31：预览缩放后端三选一，用于 600P（800x600->640x480）A/B。
        #      fused   = NEON 5:4 多相（现状；实测 input_convert 中位 68.4ms / p90 94.6ms）
        #      nearest = 通用最近邻（p11_yuyv_preview_nearest，标量逐像素）
        #      crop    = 不缩放，居中裁 640x480（掉左右各 20% 视野，但走 1:1 快路 ~11ms）
        #      640x480->640x480（480P）不受影响，始终走 1:1。
        self._preview_scale=os.environ.get('P11_PREVIEW_SCALE','fused').strip().lower()
        if self._preview_scale not in ('fused','nearest','crop'):self._preview_scale='fused'
        #   ⭐ 2026-10-29：相机输入档位弹窗的叠加层。由 `v119_profile_ui.ProfileUI.publish()`
        #      写入；None = 不画。只在 `_draw` 末尾贴图，不参与布局。
        self.profile_overlay=None
        native_display_rect(self.mode,(capacity[1],capacity[0]),1)
        self.period=1./float(max_fps);self.max_fps=float(max_fps);self.input_shape=tuple(input_shape)
        self.condition=threading.Condition();self.pending=None;self.active_slot=None;self.copying_slot=None;self.stop=False
        self.ready=False;self.error=None;self.closed=False;self.shutdown_safe=False;self.context=copy_context()
        pixels=int(capacity[0])*int(capacity[1]);h,w=map(int,input_shape)
        self.pool=[np.empty((pixels,4),np.uint8) for _ in range(2)]
        self.raw_pool=[np.empty((h,w,2),np.uint8) for _ in range(2)]
        self.raw_refs=[None,None]  # Only standalone readonly ndarray owners, never camera/CMA views.
        self.output_refs=[None,None]  # Explicit leases to completed, invalidated P1 slots.
        self.slot_packets=[None,None];self.live_preview=None;self.live_packet=None;self.preview_rendered=None;self.live_last_offer_at=0.
        self.layouts={}
        self.submitted=self.offered=self.replaced=self.dropped=self.unique_current=self.panels_submitted=0
        self.cpu_copy_s=0.;self.samples=deque(maxlen=512);self.submit_times=deque(maxlen=120)
        self.latest_meta={};self.epoch=0;self.epoch_stats={}
        self.current_times=deque(maxlen=120);self.copy_stats=np.empty(4,np.float64)
        self.display_lib=_library__v71_display()  # Initialize FFI once before producer/HDMI worker can share it.
        self.last_offer_timing={};self.last_submitted_layout=0
        self.ui_assets=ui_assets;self.ui_view='home' if ui_assets is not None else 'compare'
        self.ui_generation=0;self.ui_dirty=ui_assets is not None;self.ui_error_banner=False
        self.ui_requested_at=time.perf_counter();self.canvas_views={};self.ui_pages_submitted=0;self.ui_discarded=0
        self.ui_return_feedback=False;self.ui_layout_pending=None;self.ui_layout_switches=0;self.ui_feedback_submitted=0
        self.frozen_generation=None;self.snapshot_receipt=None;self.snapshots_frozen=0
        from ui import Inspection as Inspection
        self.inspection=Inspection(self);self.last_static_packet=None;self.inspection_restore=False
        self.tap_source=None;self.target_notice='idle';self.target_switch=None
        self.media=None
        if ui_assets is not None:
            from ui import MediaController as MediaController
            self.media=MediaController(self,capture_dir,capture_jpeg_quality)
        self.worker=threading.Thread(target=self._entry,name='hdmi_owner',daemon=True);self.worker.start()
        deadline=time.perf_counter()+(self.timeout*3 if self.mode==(1024,600) else self.timeout)+2.
        with self.condition:
            while not self.ready and self.error is None:
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('HDMI initialization timed out; worker/overlay retained')
                self.condition.wait(remaining)
            if self.error is not None:
                self.error.hdmi_shutdown_safe=self.shutdown_safe
                raise self.error
    def _entry(self):
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.condition.notify_all()
            if not self.shutdown_safe:_RETAINED__v64_hdmi_display.append(self)
            try:checkpoint('HDMI_FAILED',durable=True,exception_type=type(exc).__name__,exception=str(exc),
                vdmasafe=self.shutdown_safe,vdma_retained=not self.shutdown_safe)
            except BaseException:pass
    def _run(self):
        from pynq.lib.video import VideoMode,PIXEL_BGR
        self.loop=asyncio.new_event_loop();asyncio.set_event_loop(self.loop)
        self.vout=self.overlay.video.hdmi_out
        self.vout._vdma=self.overlay.video.axi_vdma_disp
        self.frontend=self.vout.frontend;self.channel=self.vout._vdma.writechannel
        next_publish=0.;last_meta=None;last_publish=0.
        try:
            checkpoint('HDMI_SETUP_BEGIN',durable=True,mode=list(self.mode),memory_format='BGR24',
                vdma='video/axi_vdma_disp',layout='INPUT | RECTIFIED',settings='P1 explicit binding/configure PIXEL_BGR')
            if self.channel.running:raise RuntimeError('Fresh overlay HDMI channel unexpectedly active')
            if self.mode==(1024,600):
                self.frontend=install_1024_frontend(self.vout,self.overlay,self.timeout)
            self.vout.configure(VideoMode(*self.mode,24),PIXEL_BGR)
            actual=list(self.vout.color_convert.colorspace)
            if self.vout.pixel_unpack.bits_per_pixel!=24:raise RuntimeError('HDMI pixel_unpack24 readback mismatch')
            if len(actual)!=12 or any(abs(float(a)-float(b))>1./256 for a,b in zip(actual,PIXEL_BGR.out_color)):
                raise RuntimeError('HDMI BGR matrix readback mismatch')
            if not callable(getattr(self.channel,'_writeframe_internal',None)):
                raise RuntimeError('Installed PYNQ VDMA lacks reviewed frame submission method')
            self.channel.cacheable_frames=True;self.vout.start()
            with self.condition:self.ready=True;self.condition.notify_all()
            timing=getattr(self.frontend,'detail',{})
            checkpoint('HDMI_READY',durable=True,mode=list(self.mode),refresh_hz=timing.get('refresh_hz',60),memory_format='BGR24',
                timing=timing,nominal_refresh_hz=60,
                layout='INPUT | RECTIFIED',same_frame=True,display_max_fps=self.max_fps,
                pixel_unpack_bits=24,color_matrix=actual,display_software_abi=7301,
                display_frontend_version=79,display_scale_enabled=False,display_crop_enabled=False,
                ui_enabled=self.ui_assets is not None,
                composition_backend='native_direct_color_convert_1to1',submission='finite_status_poll_then_official_frame_ownership',no_jpeg=True)
            while True:
                page_change=None;inspection_payload=None;static_inspect=None
                with self.condition:
                    if self.ui_assets is not None and self.ui_dirty and not self.stop:
                        page_change=(self.ui_view,self.ui_generation,self.ui_error_banner,self.ui_requested_at,self.ui_return_feedback)
                        # request_view already discarded old-generation pending work.
                        # Keep a fresh packet offered after that request.
                        self.ui_dirty=False
                    elif self.ui_assets is not None and not self.stop and self.inspection.dirty:
                        inspection_payload=self.inspection.payload_locked()
                    elif self.ui_assets is not None and not self.stop and self.inspection.kind:
                        self.condition.wait();continue
                    elif (self.ui_assets is not None and not self.stop and self.last_static_packet is not None and
                            (self.inspection.zoom_requested==self.ui_generation or self.inspection_restore
                             or (self.media is not None and self.media.frozen_redraw))):
                        action='zoom' if self.inspection.zoom_requested==self.ui_generation else 'restore'
                        static_inspect=(action,self.last_static_packet)
                        if self.media is not None:self.media.frozen_redraw=False
                        self.inspection_restore=False;self.active_slot=self.last_static_packet[0]
                    elif (self.ui_assets is not None and not self.stop and (self.ui_view=='home' or
                            (self.ui_view=='snapshot' and self.frozen_generation==self.ui_generation))):
                        wait_s=self.media.frozen_wait_locked() if self.media is not None and self.ui_view=='snapshot' else None
                        if wait_s==0.:continue
                        self.condition.wait(wait_s);continue
                    elif not self.stop:
                        now=time.perf_counter()
                        if now<next_publish:self.condition.wait(min(next_publish-now,.10));continue
                        if self.pending is None and not self._preview_due_locked(now):
                            self.condition.wait(min(.10,self.period))
                            if self.ui_dirty or self.inspection.dirty or self.inspection.kind or self.inspection_restore:continue
                    if self.stop and self.ui_assets is not None:self.pending=None;break
                    if self.stop and self.pending is None:break
                    special=page_change is not None or inspection_payload is not None or static_inspect is not None
                    packet=None if special else self.pending
                    if not special:self.pending=None
                    preview_only=False
                    if not special and self.ui_view=='compare' and self.live_preview is not None:
                        if packet is not None:self.live_packet=packet
                        elif self._preview_due_locked(time.perf_counter()):
                            packet=self.live_packet;preview_only=True
                            if packet is None:
                                stamp=time.perf_counter()
                                packet=(None,(),dict(state='WAITING',index=-1,camera_sequence=-1,
                                    verified_at=stamp,capture_ready_at=stamp,epoch=self.epoch,
                                    correction_fps=0.,corners=(),color_mode=0,ui_view=self.ui_view,
                                    ui_generation=self.ui_generation))
                    if packet is not None:self.active_slot=packet[0]
                if page_change is not None:
                    view,generation,error_banner,requested_at,return_feedback=page_change
                    last_meta=None;next_publish=0.
                    if view=='home':
                        if return_feedback:self._show_home(generation,False,requested_at,feedback=True)
                        self._show_home(generation,error_banner,requested_at)
                    else:
                        stamp=time.perf_counter()
                        submitted=self._show(None,None,dict(state='STARTING',index=-1,camera_sequence=-1,
                            verified_at=stamp,capture_ready_at=stamp,epoch=self.epoch,correction_fps=0.,corners=(),
                            color_mode=0,ui_view=view,ui_generation=generation))
                        if submitted:
                            checkpoint('UI_PAGE_PRESENTED',page=view,generation=generation,
                                request_to_submit_s=time.perf_counter()-requested_at,physical_scan_time_measured=False)
                    continue
                if inspection_payload is not None:
                    self._show_inspection(inspection_payload);continue
                if static_inspect is not None:
                    action,(slot,shape,meta)=static_inspect
                    out=self.pool[slot][:shape[0]*shape[1]].reshape(*shape,4)
                    try:
                        if action=='zoom':
                            image=cv2.cvtColor(out,cv2.COLOR_BGRA2BGR)
                            with self.condition:self.inspection.open_zoom_locked(image,meta);self.condition.notify_all()
                        else:self._show(self._raw_snapshot(slot),out,dict(meta,inspection_redraw=True))
                    finally:
                        with self.condition:self.active_slot=None;self.condition.notify_all()
                    continue
                now=time.perf_counter()
                if packet is None:
                    if self._profile_idle(now):
                        next_publish=time.perf_counter()+self.period
                        continue
                    if self.ui_view=='compare' and self.live_preview is not None and self.live_preview.active():continue
                    if last_meta is None or (last_meta.get('state')!='WAITING' and now-last_publish>.5 and now-last_meta.get('verified_at',now)>self.hold_max_age):
                        meta=dict(state='WAITING',index=-1,camera_sequence=-1,verified_at=now,capture_ready_at=now,
                            epoch=self.epoch,correction_fps=0.,corners=(),color_mode=0,
                            ui_view=self.ui_view,ui_generation=self.ui_generation)
                        self._show(None,None,meta);last_meta=meta;last_publish=time.perf_counter()
                        next_publish=last_publish+self.period
                    continue
                slot,out_shape,meta=packet
                raw=None if slot is None or not meta.get('has_raw_snapshot',True) else self._raw_snapshot(slot)
                out=None if not out_shape else self._output_snapshot(slot,out_shape)
                try:
                    raw,meta=self._preview_input(raw,meta,preview_only)
                    if meta.get('display_mode')=='RAW_ONLY':out=None
                    if meta['state'] in ('HELD','MANUAL_HELD') and (
                            (meta.get('continuity_output') and not valid_continuity(meta,now)) or
                            now-meta['verified_at']>self.hold_max_age):
                        out=None;meta=dict(meta,state='LOST',corners=(),verified_at=0.)
                    shown=self._show(raw,out,meta);last_meta=meta;last_publish=time.perf_counter()
                    if shown and meta.get('display_mode')=='RAW_ONLY':
                        with self.condition:self._retire_unpaired_output_locked(packet,raw,meta)
                    next_publish=max(next_publish+self.period,last_publish)
                finally:
                    raw=None;out=None  # Slot ownership keeps source bytes alive.
                    with self.condition:
                        if self.ui_view!='compare' or self.live_preview is None:self.active_slot=None
                        self.condition.notify_all()
        finally:
            # Stop the physical scanout before releasing any frame/cache. Even
            # failed startup may have populated _cache prior to start returning.
            checkpoint('HDMI_STOP_BEGIN',reason='application_exit_or_owner_error',
                page=self.ui_view,generation=self.ui_generation)
            self.channel._mmio.write(0x00,0x00011080);deadline=time.perf_counter()+self.timeout
            while self.channel.running:
                if time.perf_counter()>=deadline:raise TimeoutError('HDMI halt not proved; retain scanout/overlay')
                time.sleep(.001)
            self.channel.stop();self.frontend.stop();self.shutdown_safe=True;self.loop.close()
            checkpoint('HDMI_STOPPED',durable=True,physical_scanout_halted=True,
                buffers_released_after_halt=True)
    def _preview_due_locked(self,now):
        preview=getattr(self,'live_preview',None)
        if preview is None or not preview.active():return False
        state=preview.pairing.snapshot(now)
        if state['display_mode']=='PAIRED':return False
        value=preview.snapshot()
        if value is None:return False
        token=(value[0],value[1],self.ui_generation,state['pair_revision'])
        return token!=self.preview_rendered
    def _preview_input(self,raw,meta,preview_only=False):
        preview=getattr(self,'live_preview',None)
        if preview is None or not preview.active() or meta.get('ui_view')!='compare':return raw,meta
        now=time.perf_counter();state=preview.pairing.snapshot(now)
        paired=(not preview_only and meta.get('display_mode')=='PAIRED'
            and preview.pairing.packet_current(meta,now))
        if paired and not preview.pairing.valid(meta,raw is not None,True,now):
            preview.pairing.invalidate(reason='pair_expired');state=preview.pairing.snapshot(now);paired=False
        if paired:
            # Preserve the immutable raw that produced this actual completed image.
            return raw,dict(meta,**state,input_camera_sequence=meta.get('camera_sequence'),
                input_capture_ready_at=meta.get('capture_ready_at'),preview_only=False)
        value=preview.snapshot()
        if value is None:
            seq=meta.get('camera_sequence',-1);ready=meta.get('capture_ready_at',0.);image=raw;color=meta.get('color_mode',0)
        else:
            seq,ready,image,color,generation=value
            if generation!=meta.get('ui_generation'):
                # A stale preview must not erase the matching producer's raw.
                seq=meta.get('camera_sequence',-1);ready=meta.get('capture_ready_at',0.)
                image=raw;color=meta.get('color_mode',0)
        self.preview_rendered=(seq,ready,self.ui_generation,state['pair_revision'])
        return image,dict(meta,**dict(state,display_mode='RAW_ONLY'),state='LOST',corners=(),candidate_corners=(),
            input_camera_sequence=seq,input_capture_ready_at=ready,color_mode=color,preview_only=True,hybrid_valid_fps=0.)
    def _retire_unpaired_output_locked(self,packet,raw,meta):
        # Executed by HDMI owner after a RAW_ONLY submission, never while reading CMA.
        if self.live_packet is not packet:return
        slot=packet[0]
        if slot is not None:
            reference=self.output_refs[slot];self.output_refs[slot]=None
            if reference is not None:reference.release()
            self.raw_refs[slot]=raw
            saved=dict(meta,has_raw_snapshot=raw is not None)
            self.slot_packets[slot]=((),saved);self.live_packet=(slot,(),saved)
    def begin_ui_transition(self,view,generation,kind):
        with self.condition:
            controller=getattr(self,'page_feedback',None)
            if controller is None:controller=self.page_feedback=PageFeedback(self)
            if self.target_switch is not None:
                controller.cancel();return
            controller.begin(view,generation,kind)
    def cancel_ui_feedback(self):
        controller=getattr(self,'page_feedback',None)
        if controller is not None:controller.cancel()
    def touch_feedback(self,event,result,generation):
        with self.condition:
            controller=getattr(self,'page_feedback',None)
            if controller is None:controller=self.page_feedback=PageFeedback(self)
            controller.touch(event,result,generation)
    def arm_target_switch(self,generation,on_frozen,point=None,request_id=None):
        with self.condition:
            if (self.stop or self.error is not None or generation!=self.ui_generation or self.ui_view!='compare'
                    or self.inspection.kind is not None
                    or (self.media is not None and self.media.active)):return False
            if self.target_switch is not None:self.target_switch.restore()
            switch=TargetSwitch(self,on_frozen,point,request_id=request_id);self.target_switch=switch
            self._show=switch.handler;self.tap_source=None
        checkpoint('UI_TARGET_SWITCH_ARMED',generation=generation,event_only=True,request_id=request_id,live_preview=True)
        return True
    def set_target_phase(self,phase,generation):
        controller=getattr(self,'page_feedback',None)
        if controller is not None:controller.phase(phase,generation)
        with self.condition:
            switch=self.target_switch
            if switch is not None and switch.active and generation==switch.generation==self.ui_generation:
                switch.set_phase_locked(phase)
    def request_view(self,view,generation,error=False,layout_only=False,return_feedback=False,preserve_target=False):
        if self.ui_assets is None:raise RuntimeError('UI assets not configured')
        if view not in ('home','compare','rectified','snapshot'):raise ValueError('Unknown display view')
        with self.condition:
            if self.stop:return
            if int(generation)<self.ui_generation:return
            switch=self.target_switch
            if switch is not None:
                if not (preserve_target and not error and view in ('compare','rectified') and switch.retarget_locked(generation)):
                    switch.restore()
            previous=self.ui_view;previous_generation=self.ui_generation
            if layout_only and (previous not in ('compare','rectified') or view not in ('compare','rectified')):
                raise ValueError('Layout-only command requires two live views')
            self.ui_view=view;self.ui_generation=int(generation);self.ui_error_banner=bool(error)
            preview=getattr(self,'live_preview',None)
            if (layout_only or preserve_target) and preview is not None:
                # Explicit compare/result-only layout changes reuse this camera.
                # A manual/new session still requires a fresh binding.
                with preview.lock:
                    if preview.generation==previous_generation:
                        preview.generation=int(generation)
                        if preview.latest is not None:
                            seq,ready,raw,color,_=preview.latest
                            preview.latest=(seq,ready,raw,color,int(generation))
            self.live_packet=None;self.preview_rendered=None
            self.ui_requested_at=time.perf_counter();self.ui_return_feedback=bool(return_feedback)
            self.frozen_generation=None;self.snapshot_receipt=None
            self.last_static_packet=None;self.inspection_restore=False;self.inspection.clear_locked()
            self.tap_source=None
            if not layout_only:self.target_notice='idle'
            if self.media is not None:self.media.page_changed_locked()
            if layout_only:
                # Keep scanout until a complete new-layout frame can be submitted.
                # A startup page command already queued still uses the new view.
                self.ui_layout_switches+=1
                self.ui_layout_pending=(int(generation),view,self.ui_requested_at)
                if self.pending is not None:
                    slot,shape,meta=self.pending
                    if view=='compare' and not meta.get('has_raw_snapshot',True):
                        self.ui_discarded+=1;self.pending=None
                    else:
                        meta=dict(meta,ui_view=view,ui_generation=int(generation))
                        self.pending=(slot,shape,meta)
            else:
                self.ui_dirty=True;self.ui_layout_pending=None
                if self.pending is not None:self.ui_discarded+=1;self.pending=None
            self.condition.notify_all()
    def set_target_notice(self,notice,generation):
        controller=getattr(self,'page_feedback',None)
        if controller is not None and notice in ('idle','multiple','selecting'):controller.phase('verify',generation)
        with self.condition:
            if self.stop or generation!=self.ui_generation or self.ui_view not in ('compare','rectified'):return False
            switch=self.target_switch
            if switch is not None and generation==switch.generation and notice in ('miss','fallback'):
                switch.set_phase_locked('fallback')
            if notice not in ('idle','multiple','selecting','selected','miss','fallback','not_covered','unconfirmed','current'):raise ValueError('Invalid target notice')
            if notice!=self.target_notice:
                self.target_notice=notice;self.canvas_views.clear();self.condition.notify_all()
        checkpoint('UI_TARGET_NOTICE',notice=notice,generation=generation,
            scope='tap_event' if notice=='current' else 'acquisition_only',per_frame_detection=False)
        return True
    def tap_target_source(self,point,generation):
        # Called on a UI event: ordinary readonly RAM only, never MMAP/CMA/VDMA.
        with self.condition:
            value=self.tap_source
            if (self.stop or generation!=self.ui_generation or self.ui_view!='compare'
                    or self.inspection.kind is not None or self.media is not None and self.media.active or value is None):return None
            raw,meta,rect,submitted=value
            if (meta.get('ui_generation')!=generation or time.perf_counter()-submitted>.75
                    or time.perf_counter()-meta.get('capture_ready_at',0.)>1.2
                    or rect is None):return None
            from ui import source_point as source_point; from ui import can_select as can_select
            if not can_select(meta.get('admission_mode')=='manual',meta.get('correction_origin')=='AI'):return None
            if type(raw) is not np.ndarray or not raw.flags.owndata or raw.flags.writeable or not raw.flags.c_contiguous:return None
            mapped=source_point(point,rect,raw.shape)
            if mapped is None:return None
            return dict(image=raw,point=mapped,normalized_point=(mapped[0]/raw.shape[1],mapped[1]/raw.shape[0]),ready=float(meta['capture_ready_at']),
                sequence=int(meta.get('camera_sequence',-1)),submitted_at=submitted,pressed_at=time.perf_counter(),
                current_target_meta=meta,source_rect=rect)
    def current_target_tap(self,selection,release,generation):
        """A clean tap may keep a fresh current quad; uncertainty always falls through.

        Both endpoints must lie well inside both the press and latest submitted
        quads. This is displayed-target geometry, not semantic book recognition.
        This method is called only by touch release, never by the frame loop.
        """
        with self.condition:
            if (self.stop or self.error is not None or self.target_switch is not None
                    or self.target_notice in ('selecting','miss','fallback','not_covered','unconfirmed')):return False
            original=selection.get('current_target_meta')
            if original is None:return False
            if not (original.get('target_selection_proof') or {}).get('single_target'):return False
            latest=self.tap_target_source(release,generation)
            if latest is None:return False
            meta=latest['current_target_meta'];now=time.perf_counter()
            if (meta.get('target_selection_proof') or {}).get('request_id')!=original['target_selection_proof'].get('request_id'):return False
            if (original.get('epoch')!=meta.get('epoch')
                    or selection.get('source_rect')!=latest['source_rect']
                    or selection['image'].shape!=latest['image'].shape):return False
            first=_current_tap_quad(original,selection['image'].shape,generation,
                selection['submitted_at'],selection['pressed_at'])
            last=_current_tap_quad(meta,latest['image'].shape,generation,latest['submitted_at'],now)
            if first is None or last is None:return False
            q0,margin0,edge0=first;q1,margin1,edge1=last
            if float(np.max(np.linalg.norm(q1-q0,axis=1)))>max(12.,.08*min(edge0,edge1)):return False
            points=(tuple(map(float,selection['point'])),tuple(map(float,latest['point'])))
            distances=[float(cv2.pointPolygonTest(q,p,True)) for q in (q0,q1) for p in points]
            if min(distances[:2])<margin0 or min(distances[2:])<margin1:return False
            if not self.set_target_notice('current',generation):return False
            checkpoint('UI_TAP_CURRENT_TARGET',generation=generation,point=list(points[0]),
                source_sequence=selection['sequence'],latest_sequence=latest['sequence'],
                minimum_inside_distance=min(distances),boundary_margin=max(margin0,margin1),
                target_restarted=False,camera_reopened=False,tracker_reinitialized=False,
                semantic_identity_proven=False,event_only=True)
            return True
    def snapshot_is_frozen(self,generation):
        # Touch reads only this receipt. It never calls camera/DMA/VDMA code.
        with self.condition:
            return bool(not self.stop and self.error is None and self.ui_view=='snapshot'
                and self.ui_generation==generation and self.frozen_generation==generation
                and self.snapshot_receipt is not None)
    def wait_snapshot(self,generation,index,sequence,cancel=None,timeout_s=None):
        deadline=time.perf_counter()+(self.timeout+2. if timeout_s is None else float(timeout_s))
        with self.condition:
            while True:
                if (cancel is not None and cancel.is_set()) or generation!=self.ui_generation:return None
                if self.error is not None:raise self.error
                if self.stop:raise RuntimeError('HDMI stopped before snapshot confirmation')
                receipt=self.snapshot_receipt
                if receipt is not None and (receipt['generation'],receipt['index'],receipt['camera_sequence'])==(generation,index,sequence):
                    return dict(receipt)
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('Single-frame HDMI submission was not confirmed')
                self.condition.wait(min(remaining,.2))
    def _acquire_canvas(self,page=None,generation=None):
        # Frame ownership has one release path: drop our Python reference.
        # In older PYNQ, explicitly freebuffer() on a cached frame returns its
        # pointer, then its __del__ may unmap that same cached pointer again.
        # Submitted frames remain referenced by the VDMA driver's _frames.
        frame=self.channel.newframe();canvas=np.asarray(frame)
        if page is not None:
            detail=dict(page=page,generation=generation,physical_address=int(frame.physical_address),
                virtual_address=int(canvas.ctypes.data),bytes=int(canvas.nbytes),
                cache_entries=len(getattr(getattr(self.channel,'_cache',None),'_cache',())),
                release_policy='reference_only_no_explicit_cached_frame_free')
            try:
                if canvas.shape!=(self.mode[1],self.mode[0],3) or canvas.dtype!=np.uint8:
                    raise RuntimeError('HDMI canvas layout mismatch')
                if not canvas.flags.c_contiguous or not canvas.flags.writeable or getattr(frame,'freed',False):
                    raise RuntimeError('HDMI canvas is not live writable memory')
                slots=getattr(self.channel,'_frames',())
                if any(slots[i] is not None and int(slots[i].physical_address)==detail['physical_address'] for i in range(len(slots))):
                    raise RuntimeError('HDMI newframe aliases a VDMA-owned frame')
                # Page transitions only: diagnose a stale mapping before a CPU
                # store can terminate the kernel. This is not a per-frame scan.
                cursor=detail['virtual_address'];end=cursor+detail['bytes']
                for line in Path('/proc/self/maps').read_text().splitlines():
                    fields=line.split(None,2);lo,hi=(int(v,16) for v in fields[0].split('-'))
                    if lo<=cursor<hi:
                        if not fields[1].startswith('rw'):break
                        cursor=min(end,hi)
                        if cursor==end:break
                if cursor!=end:raise RuntimeError('HDMI canvas mapping is incomplete; stop before writing')
                detail['mapping_read_write_verified']=True
                checkpoint('HDMI_CANVAS_ACQUIRED',**detail)
            except BaseException as exc:
                checkpoint('HDMI_CANVAS_REJECTED',durable=True,**detail,exception=str(exc))
                canvas=None;frame=None
                raise
        return frame,canvas
    def _show_home(self,generation,error_banner,requested_at,feedback=False):
        if generation!=self.ui_generation:return
        frame,canvas=self._acquire_canvas('home',generation)
        try:
            canvas[:]=self.ui_assets.home_frame(error_banner,feedback=feedback)
            key=int(frame.physical_address)
            self.canvas_views[key]=('home',generation);self.layouts[key]=(None,None)
            if generation!=self.ui_generation:return
            self.loop.run_until_complete(self._submit(frame))
            if feedback:self.ui_feedback_submitted+=1
            else:self.ui_pages_submitted+=1
            checkpoint('UI_RETURN_FEEDBACK_PRESENTED' if feedback else 'UI_PAGE_PRESENTED',page='home',generation=generation,
                request_to_submit_s=time.perf_counter()-requested_at,static=True,physical_scan_time_measured=False)
        finally:
            # No explicit freebuffer: a stale frame is recycled once by its
            # destructor; a submitted frame stays owned by channel._frames.
            canvas=None;frame=None
    def _status(self):
        mmio=self.channel._mmio
        return dict(control=int(mmio.read(0)),status=int(mmio.read(4)),park=int(mmio.read(0x28)),
            vsize=int(mmio.read(0x50)),hsize=int(mmio.read(0x54)),stride=int(mmio.read(0x58)),
            desired_frame=int(self.channel.desiredframe),pixel_bits=int(self.vout.pixel_unpack.bits_per_pixel))
    async def _submit(self,frame):
        # Same ownership/flush/schedule path as PYNQ writeframe, with a finite
        # readable-status wait instead of depending on an IRQ future's loop.
        mmio=self.channel._mmio;deadline=time.perf_counter()+self.timeout;polls=0
        while True:
            status=int(mmio.read(4))
            if status&0x70:raise RuntimeError('HDMI VDMA error '+str(self._status()))
            if status&1:raise RuntimeError('HDMI VDMA stopped before submission '+str(self._status()))
            if status&0x1000:break
            if time.perf_counter()>=deadline:
                detail=self._status();checkpoint('HDMI_SUBMIT_TIMEOUT',durable=True,registers=detail,polls=polls)
                raise TimeoutError('HDMI frame-ready timeout '+str(detail))
            polls+=1;await asyncio.sleep(.001)
        mmio.write(4,0x1000)
        self.channel._writeframe_internal(frame)
        return polls
    def _show_inspection(self,payload):
        from ui import render_inspection as render_inspection
        began=time.perf_counter();cpu=time.thread_time()
        generation=payload['generation']
        if generation!=self.ui_generation:return False
        frame,canvas=self._acquire_canvas('inspection_'+payload['kind'],generation)
        try:
            if payload['kind']=='ratio':
                key=int(frame.physical_address)
                payload=dict(payload,ratio_background_cached=self.canvas_views.get(key)==('inspection',generation,payload['token']))
            if payload['kind']=='zoom':
                key=int(frame.physical_address);previous=self.inspection.reading.canvases.get(key)
                cached=(self.canvas_views.get(key)==('inspection',generation,payload['token'])
                    and previous is not None and previous[0]==payload['token'])
                payload=dict(payload,reading_background_cached=cached,reading_previous_roi=previous[1] if cached else None)
            reading_roi=render_inspection(canvas,payload,self.ui_assets)
            with self.condition:
                current=(generation==self.ui_generation and self.inspection.token==payload['token'] and self.inspection.kind==payload['kind'])
            if not current:return False
            key=int(frame.physical_address);self.canvas_views[key]=('inspection',generation,payload['token'])
            if payload['kind']=='zoom':
                with self.condition:
                    if self.inspection.token==payload['token']:
                        cache=self.inspection.reading.canvases;cache[key]=(payload['token'],reading_roi)
                        if len(cache)>16:self.inspection.reading.canvases={key:cache[key]}
            self.layouts[key]=(None,None)
            composed=time.perf_counter();composed_cpu=time.thread_time()
            self.loop.run_until_complete(self._submit(frame));submitted=time.perf_counter()
            if payload['kind']=='album' and self.media is not None:
                with self.condition:self.media.presented_locked(payload)
            checkpoint('UI_INSPECTION_PRESENTED',generation=generation,kind=payload['kind'],
                points=len(payload['points']),event_only=True,physical_scan_time_measured=False,
                compose_s=composed-began,compose_thread_cpu_s=composed_cpu-cpu,vdma_submit_s=submitted-composed)
            return True
        finally:canvas=None;frame=None
    def _geometry_overlay(self,raw,meta,now):
        empty=dict(quad=(),kind='NONE',reason='raw_only',source_sequence=None,age_ms=None)
        if raw is None or meta.get('ui_view')=='rectified' or meta.get('display_mode')=='RAW_ONLY':return empty
        sequence=meta.get('input_camera_sequence',meta.get('camera_sequence',-1))
        ready=meta.get('input_capture_ready_at',meta.get('capture_ready_at',0.))
        continuity=bool(meta.get('continuity_output')) and valid_continuity(meta,now)
        if (sequence==meta.get('camera_sequence') and (meta.get('state') in ('CURRENT','MANUAL') or continuity)
                and not meta.get('frozen_output') and now-float(ready)<=.5
                and len(meta.get('corners',()))==4):
            empty.update(quad=meta['corners'],kind='CONTINUITY' if continuity else 'CURRENT',
                reason='current_frame_continuity' if continuity else 'completed_pair',source_sequence=sequence,
                age_ms=max(0.,now-float(meta['verified_at']))*1000. if continuity else 0.)
        return empty
    def _live_diagnostic(self,reason,meta,left,right,probe,physical_address=None):
        signature=(meta.get('ui_view','compare'),meta.get('ui_generation'),meta.get('hybrid_epoch'),
            left is not None,right is not None)
        key=(reason,signature)
        if key==getattr(self,'_live_diagnostic_key',None):return
        self._live_diagnostic_key=key;self._live_diagnostic_signature=signature
        now=time.perf_counter()
        if now-getattr(self,'_live_diagnostic_at',-1e9)<.25 and reason!='empty_canvas_suppressed':
            self._live_diagnostic_suppressed=getattr(self,'_live_diagnostic_suppressed',0)+1;return
        suppressed=getattr(self,'_live_diagnostic_suppressed',0)
        self._live_diagnostic_at=now;self._live_diagnostic_suppressed=0
        checkpoint('DISPLAY_LIVE_EVENT',reason=reason,index=meta.get('index'),state=meta.get('state'),
            ui_generation=meta.get('ui_generation'),hybrid_epoch=meta.get('hybrid_epoch'),
            hybrid_phase=meta.get('hybrid_phase'),camera_sequence=meta.get('camera_sequence'),
            input_camera_sequence=meta.get('input_camera_sequence',meta.get('camera_sequence')),
            left_present=left is not None,right_present=right is not None,
            preview_only=bool(meta.get('preview_only')),continuity_output=bool(meta.get('continuity_output')),
            continuity_from_owner_wait=bool(meta.get('continuity_from_owner_wait')),
            capture_ready_at=meta.get('capture_ready_at'),input_capture_ready_at=meta.get('input_capture_ready_at'),
            physical_address=physical_address,pixel_probe_bgr=probe,submitted=reason=='canvas_submitted',
            suppressed_transitions=suppressed,physical_scan_time_measured=False)
    def _profile_state(self,now):
        view=getattr(self,'profile_overlay',None)
        if view is not None and view.get('busy'):
            controller=getattr(self,'profile_controller',None)
            if controller is not None and controller.expire(now):view=self.profile_overlay
        return view

    def _profile_idle(self,now):
        """Owner-only UI during STREAMOFF. Never replay or copy camera pixels."""
        view=self._profile_state(now)
        failed=bool(view and view.get('phase')=='failed')
        if (not view or (not view.get('busy') and not failed) or view.get('generation')!=self.ui_generation
                or self.ui_view not in ('compare','rectified') or self.ui_assets is None
                or now<getattr(self,'_profile_next_redraw',0.)):return False
        if failed and getattr(self,'_profile_failure_presented',None)==view['serial']:return False
        # Normal queued output/current preview always gets priority. Snapshot
        # metadata under the condition, but NEVER submit while holding it.
        with self.condition:
            if self.stop or self.pending is not None or self.ui_dirty or self.inspection.kind:return False
            preview=getattr(self,'live_preview',None)
            page=self.ui_view;generation=self.ui_generation
        value=preview.snapshot() if preview is not None else None
        if value is not None and value[4]==generation and 0.<=now-value[1]<=.5:
            return False
        frame,canvas=self._acquire_canvas()
        try:
            canvas[:]=(32,28,24) # explicit neutral switching UI, not a blank live canvas
            canvas[:72]=self.ui_assets.headers[page]
            from ui import render_overlay__v120_image_settings as render_overlay
            render_overlay(canvas,dict(view,timeout_notice=True) if failed else view,self.ui_assets)
            key=int(frame.physical_address)
            self.canvas_views[key]=(page,generation,'profile_wait',view['serial'])
            self.layouts[key]=(None,None)
            with self.condition:
                if generation!=self.ui_generation or self.stop or self.pending is not None:return False
            self.loop.run_until_complete(self._submit(frame))
            self._profile_next_redraw=now+.1
            if failed:self._profile_failure_presented=view['serial']
            if getattr(self,'_profile_wait_logged',None)!=view['serial']:
                self._profile_wait_logged=view['serial']
                checkpoint('CAMERA_PROFILE_WAIT_PRESENTED',generation=generation,
                    request_serial=view['serial'],target=view['target'],max_ui_hz=10,
                    camera_frame_replayed=False,physical_scan_time_measured=False)
            return True
        finally:canvas=None;frame=None

    def _show(self,raw,out,meta):
        view=meta.get('ui_view','compare');generation=int(meta.get('ui_generation',0))
        if self.ui_assets is not None and generation!=self.ui_generation:return False
        profile_view=getattr(self,'profile_overlay',None);profile_controller=None
        if profile_view is not None and profile_view.get('busy'):
            profile_view=self._profile_state(time.perf_counter())
            profile_controller=getattr(self,'profile_controller',None) if profile_view.get('busy') else None
        paused=False
        preview_only=bool(meta.get('preview_only'))
        if meta.get('display_mode')=='RAW_ONLY':out=None
        result_valid=(out is not None and (meta.get('state') in ('CURRENT','MANUAL') or valid_continuity(meta,time.perf_counter()))
            and not meta.get('frozen_output') and time.perf_counter()-float(meta.get('capture_ready_at',0.))<=.5)
        if view in ('compare','rectified') and not result_valid:
            out=None;meta=dict(meta,corners=(),hybrid_valid_fps=0.)
        if view in ('compare','rectified') and raw is None and out is None:
            preview=getattr(self,'live_preview',None)
            value=preview.snapshot() if preview is not None else None
            if value is not None and value[4]==generation and -.02<=time.perf_counter()-value[1]<=.5:
                sequence,ready,raw,color,_=value
                meta=dict(meta,input_camera_sequence=sequence,input_capture_ready_at=ready,color_mode=color,
                    preview_only=True,display_mode='RAW_ONLY',corners=(),candidate_corners=())
            elif getattr(self,'_live_pixels_seen',False) or meta.get('state') not in ('STARTING','INITIALIZING'):
                self._live_diagnostic('empty_canvas_suppressed',meta,None,None,None)
                return False
        same_frame=(raw is not None and out is not None and
            meta.get('input_camera_sequence',meta.get('camera_sequence'))==meta.get('camera_sequence'))
        if not same_frame:meta=dict(meta,corners=(),candidate_corners=())
        display_mode=meta.get('display_mode') or ('PAIRED' if same_frame else 'RAW_ONLY' if out is None else 'RECTIFIED')
        overlay=self._geometry_overlay(raw,meta,time.perf_counter()) if out is not None else dict(
            quad=(),kind='NONE',reason='no_valid_pixels',source_sequence=None,age_ms=None)
        began=time.perf_counter();cpu=time.thread_time()
        if profile_controller is not None and (raw is not None or result_valid):
            profile_view=profile_controller.frame_view(profile_view,generation,
                raw.shape if raw is not None else self.input_shape,
                meta.get('input_capture_ready_at',meta.get('capture_ready_at')),
                meta.get('input_camera_sequence',meta.get('camera_sequence')),began)
        frame,canvas=self._acquire_canvas(view if meta['state']=='STARTING' else None,generation)
        acquired=time.perf_counter();acquired_cpu=time.thread_time()
        try:
            h,w=self.mode[1],self.mode[0];mid=w//2
            # Before acquisition (and after complete loss), show live input
            # even on the result-only page so placement remains visible.
            single=view=='rectified' and out is not None
            if single:raw=None
            left=native_display_rect(self.mode,self._fit_shape(self.mode,raw.shape[:2]),0) if raw is not None else None
            live_wait=out is None and view in ('compare','rectified')
            if out is not None and single:
                oh,ow=out.shape[:2]
                if ow>w or oh>h-64:raise ValueError('Rectified native image exceeds HDMI canvas')
                right=((w-ow)//2,36+(h-64-oh)//2,ow,oh)
            else:right=native_display_rect(self.mode,out.shape[:2],1) if out is not None else None
            fixed_status=bool(self.ui_assets is not None and hasattr(self.ui_assets,'live_ui_parts') and view in ('compare','rectified'))
            live_ui=None
            if fixed_status:
                live_ui=getattr(self,'live_status',None)
                if live_ui is None:self.live_status=live_ui=LiveUI()
                # Keep native output dimensions. Only move a tall portrait down
                # past the fixed information strip; bottom controls begin640.
                if right is not None:
                    rx,ry,rw,rh=right;right=(rx,max(124,ry),rw,rh)
            key=int(frame.physical_address);old=self.layouts.get(key)
            page_token=(view,generation,out is not None) if view=='snapshot' else (
                view,generation,self.target_notice,'fixed_live')
            if profile_view is not None and (profile_view.get('busy') or profile_view.get('open')):
                # The settings rectangle does not move while dragging. A new
                # numeric candidate must not clear the whole HDMI canvas.
                token=('settings_open' if profile_view.get('open') and not profile_view.get('busy')
                       and 'settings_tab' in profile_view else profile_view['revision'])
                page_token=(view,generation,self.target_notice,token,'fixed_live')
            startup_phase=meta.get('ui_startup_phase');startup_action=None
            if startup_phase in ('preparing','placement'):
                startup_action=('confirmed' if meta.get('placement_confirmed') or not meta.get('placement_required') else 'confirm')
            elif startup_phase=='acquiring':startup_action='acquiring'
            if startup_action is not None:page_token=page_token+(startup_action,)
            page_changed=self.canvas_views.get(key)!=page_token
            if old is None or page_changed:canvas.fill(0)
            else:
                for prior,new in zip(old,(left,right)):
                    if prior is not None and prior!=new:
                        x,y,rw,rh=prior;canvas[y:y+rh,x:x+rw].fill(0)
            # Repaint text backgrounds (including antialias fringes), and only
            # changed image regions, rather than clearing720p every submission.
            ui_began=time.perf_counter();ui_header_restore_s=0.
            if self.ui_assets is None:canvas[:36].fill(0)
            else:
                if page_changed:
                    canvas[:72]=(self.ui_assets.snapshot_busy if view=='snapshot' and out is None
                        else self.ui_assets.headers[view])
                    if startup_action is not None:
                        canvas[:72,1000:1280]=self.ui_assets.placement_controls[startup_action]
                    if view in ('compare','rectified'):
                        canvas[:72,380:580]=self.ui_assets.refind_controls[
                            'preparing' if startup_phase=='preparing' else 'ready']
                        if self.target_notice!='idle' and not fixed_status:
                            canvas[78:118,:640]=self.ui_assets.target_hints[(view,self.target_notice)]
                    ui_header_restore_s=time.perf_counter()-ui_began
                # Cached top-left return pixels are not touched on warm buffers.
                label_end=1000 if view in ('compare','rectified','snapshot') else w
                # V82 cached touch controls occupy the header; dynamic labels
                # stay in the existing footer and never overwrite hit targets.
                self.canvas_views[key]=page_token
                if len(self.canvas_views)>16:self.canvas_views={key:page_token}
            if self.ui_assets is None:self.canvas_views[key]=page_token
            if not fixed_status:canvas[h-28:].fill(0)
            clear_end=time.perf_counter();clear_cpu=time.thread_time()
            raw_backend='none';input_convert_s=0.;output_convert_s=0.;scale_s=0.
            left_detail={};right_detail={};left_panel_s=right_panel_s=0.;left_cpu_s=right_cpu_s=0.
            corner_draw_s=0.;corner_draw_cpu_s=0.
            if raw is not None:
                x,y,rw,rh=left;t=time.perf_counter();tc=time.thread_time()
                # Startup must not synchronously compile the library whose
                # readiness it is trying to show. Only INITIALIZING can use
                # this temporary path; normal display remains unchanged.
                startup_fallback=False
                if meta['state']=='INITIALIZING':
                    startup_fallback=_LIB is None
                if startup_fallback:
                    if meta['color_mode']==0:
                        cv2.cvtColor(raw,cv2.COLOR_YUV2BGR_YUY2,dst=canvas[y:y+rh,x:x+rw])
                    else:
                        from core import model_bgr as model_bgr
                        canvas[y:y+rh,x:x+rw]=model_bgr(raw)
                else:
                    #   ⭐ 2026-10-28：源图比面板大（800x600 放进 640x480 槽）时，
                    #      **在画的时候缩**。
                    #      ① 优先 `FusedDisplay.scale()`：800x600→640x480 恰好是 5:4，
                    #         命中原生 **NEON 5:4 多相**分支，直接写进 canvas。
                    #         实测左预览 **94 → 39.8 ms**，显示 7 → 14 fps。
                    #      ② 退回通用 YUYV 预览缩放（标量双线性/最近邻，实测 92~94 ms）。
                    #      ③ 再退回居中裁剪（颜色仍正确，只是视野变小）。
                    scaled_detail=None
                    if raw.shape[:2]!=(rh,rw):
                        #   ⭐ 2026-10-31：后端由 P11_PREVIEW_SCALE 选（fused/nearest/crop）。
                        #      crop 直接跳到最后那条居中裁剪，不碰多相也不碰最近邻。
                        if self._preview_scale=='fused':
                            if self._fused is None and not self._fused_failed:
                                try:
                                    self._fused=FusedDisplay()
                                except BaseException:
                                    self._fused=None;self._fused_failed=True
                            if self._fused is not None:
                                try:
                                    scaled_detail=self._fused.scale(0,raw,int(meta['color_mode']),canvas,left)
                                except BaseException:
                                    scaled_detail=None
                        if scaled_detail is not None:
                            raw_backend=scaled_detail['backend']
                        elif self._preview_scale=='crop':
                            ih,iw=raw.shape[:2];y0=max(0,(ih-rh)//2);x0=max(0,(iw-rw)//2)
                            yuyv_bgr_into(np.ascontiguousarray(raw[y0:y0+rh,x0:x0+rw]),
                                meta['color_mode'],canvas,left)
                            raw_backend='crop_center_fallback'
                        else:
                            from tracking import yuyv_preview_into__v31_native as yuyv_preview_into
                            if self._scaled is None or self._scaled.shape[:2]!=(rh,rw):
                                self._scaled=np.empty((rh,rw,3),np.uint8)
                            if yuyv_preview_into(raw,int(meta['color_mode']),self._scaled,
                                    fast=self._preview_nearest):
                                canvas[y:y+rh,x:x+rw]=self._scaled
                                raw_backend=('native_YUYV_to_BGR_scaled_nearest' if self._preview_nearest
                                    else 'native_YUYV_to_BGR_scaled')
                            else:
                                ih,iw=raw.shape[:2];y0=max(0,(ih-rh)//2);x0=max(0,(iw-rw)//2)
                                yuyv_bgr_into(np.ascontiguousarray(raw[y0:y0+rh,x0:x0+rw]),
                                    meta['color_mode'],canvas,left)
                                raw_backend='crop_center_fallback'
                    else:
                        yuyv_bgr_into(raw,meta['color_mode'],canvas,left)
                        raw_backend='native_YUYV_to_BGR_1to1'
                input_convert_s=time.perf_counter()-t
                if startup_fallback:
                    raw_backend='startup_OpenCV_or_model_CSC';scaled_detail=None
                left_detail=dict(direct=True,resize_used=False,crop_used=False,backend=raw_backend,
                    source_shape=list(raw.shape),destination_rect=list(left),
                    polyphase_5_4_used=bool(scaled_detail and scaled_detail.get('polyphase_5_4_used')),
                    scale_native_s=(scaled_detail or {}).get('native_wall_s',0.),
                    scale_backend_all=(scaled_detail or {}).get('backend'))
                left_panel_s=time.perf_counter()-t;left_cpu_s=time.thread_time()-tc
                t=time.perf_counter();tc=time.thread_time()
                corners=overlay['quad']
                #   ⚠️ 2026-10-28（现场：绿框位置/大小都不对，还拖出黄绿长条）：
                #      四角是【源图坐标】（800x600），而左画面是【缩放后】的 640x480。
                #      直接 `points+=矩形原点` 按 1:1 画 ⇒ 框比实际大 1.25 倍、溢出到右半边。
                #      640x480 时系数恒为 1，行为与改动前完全一致。
                _sx,_sy=rw/float(raw.shape[1]),rh/float(raw.shape[0])
                if len(corners)==4:
                    points=np.asarray(corners,np.float32)
                    if (rw,rh)!=tuple(raw.shape[1::-1]):
                        points=np.stack([points[:,0]*_sx,points[:,1]*_sy],axis=1)
                    points=points+np.array([x,y],np.float32)
                    color=((0,210,255) if overlay['kind']=='REFERENCE' else
                        (255,200,70) if meta['state'] in ('MANUAL','MANUAL_HELD') else (0,240,0))
                    # A single colored outline preserves HELD status without
                    # dozens of Python/NumPy/cv2.line calls on each frame.
                    cv2.polylines(canvas,[np.rint(points).astype(np.int32)],True,color,2,cv2.LINE_AA)
                candidate=meta.get('candidate_corners',())
                if (not corners and len(candidate)==4 and
                        0<=time.perf_counter()-meta.get('candidate_ready_at',0.)<=.9):
                    cq=np.asarray(candidate,np.float32)
                    if (rw,rh)!=tuple(raw.shape[1::-1]):
                        cq=np.stack([cq[:,0]*_sx,cq[:,1]*_sy],axis=1)
                    points=np.rint(cq+np.array([x,y],np.float32)).astype(np.int32)
                    cv2.polylines(canvas,[points],True,(70,70,255),2,cv2.LINE_AA)
                corner_draw_s=time.perf_counter()-t;corner_draw_cpu_s=time.thread_time()-tc
            if out is not None:
                x,y,rw,rh=right;t=time.perf_counter();tc=time.thread_time()
                bgra_bgr_into(out,canvas,right)
                output_convert_s=time.perf_counter()-t
                right_detail=dict(direct=True,resize_used=False,crop_used=False,backend='native_BGRX_to_BGR_1to1',
                    source_shape=list(out.shape),destination_rect=list(right),polyphase_5_4_used=False)
                right_panel_s=time.perf_counter()-t;right_cpu_s=time.thread_time()-tc
            if live_wait and self.ui_assets is not None and view in ('compare','rectified') and not fixed_status:
                # Small cached status in the right region; no page/progress overlay.
                canvas[78:106,800:1120]=self.ui_assets.status_badges['SEARCHING']
            elif self.ui_assets is not None and view in ('compare','rectified') and not fixed_status:
                canvas[78:106,800:1120].fill(0)
            self.layouts[key]=(left,right)
            if len(self.layouts)>16:self.layouts={key:(left,right)}
            now=time.perf_counter()
            while self.submit_times and self.submit_times[0]<now-2.:self.submit_times.popleft()
            times=list(self.submit_times)
            rate=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.
            with self.condition:
                while self.current_times and self.current_times[0]<now-2.:self.current_times.popleft()
                # Fixed2s includes CURRENT only; decays during lost/held updates.
                current_rate=len(self.current_times)/2.
            age=max(0.,now-meta.get('capture_ready_at',now))*1000
            verified=float(meta.get('verified_at',0.));h_age=max(0.,now-verified)*1000 if verified>0 else None
            label_x=184 if self.ui_assets is not None else 8
            if not single and self.ui_assets is None:
                label=('ORIGINAL seq=%d' if view=='snapshot' else 'INPUT seq=%d')%meta.get('camera_sequence',-1)
                cv2.putText(canvas,label,(label_x,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
            heading=('SNAPSHOT '+('READY' if out is not None else 'CAPTURING')) if view=='snapshot' else 'RECTIFIED '+meta['state']
            if self.ui_assets is None:cv2.putText(canvas,heading,(label_x if single else mid+8,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
            status='CORR %.1f | DISP %.1f | CUR %.1f | CAP %.0fms | H %s'%(meta.get('correction_fps',0.),rate,current_rate,age,
                ('%.0fms'%h_age) if h_age is not None and meta['state'] in ('CURRENT','HELD') else '--')
            if meta.get('v86_motion_authority'):
                status=status.replace('CUR ', 'TRACK ')
            if view=='snapshot':
                status=('SINGLE FRAME | seq=%d | RECAPTURE OR RETURN'%meta.get('camera_sequence',-1)
                    if out is not None else 'SINGLE FRAME | WAITING FOR VERIFIED CORNERS')
            if meta.get('admission_mode')=='manual':
                status=self.manual_status_template%(meta.get('manual_tracking',''),
                    meta.get('manual_fps',0.),rate,('MOTION WATCH / AUTO RESUME' if meta.get('manual_fixed_watch') else 'RECALIBRATE AFTER MOVING')
                    if meta.get('manual_tracking')=='FIXED' else 'FULL FB TRACK / FINITE HOLD')
                if meta.get('manual_tracking')=='SNAPSHOT':status='MANUAL SINGLE FRAME | RECAPTURE, RECALIBRATE OR RETURN'
            if meta['state']=='INITIALIZING':
                status='SETUP %.0fs | AUTO LOCATE WHEN READY | RAW VIEW ACTIVE'%meta.get('native_setup_elapsed_s',0.)
            elif meta['state']=='PLACEMENT':status='READY | AUTOMATIC CURRENT-FRAME LOCALIZATION'
            status_x=8
            hybrid=hybrid_footer(meta,out is not None,rate) if 'correction_origin' in meta and not fixed_status else None
            if hybrid is not None:status=hybrid[1]
            if self.ui_assets is not None and not fixed_status:
                if hybrid is not None:canvas[h-28:,:320]=hybrid[0]
                else:
                    state=meta['state'] if meta['state'] in self.ui_assets.status_badges else 'SEARCHING'
                    if state=='MANUAL' and meta.get('manual_tracking')=='FIXED':state='MANUAL_FIXED'
                    canvas[h-28:,:320]=self.ui_assets.status_badges[state]
                status_x=326
            if fixed_status:
                live_ui.paint(canvas,self.ui_assets,meta,out is not None,self,now,key,force=page_changed)
            else:cv2.putText(canvas,status,(status_x,h-9),cv2.FONT_HERSHEY_SIMPLEX,.40,(255,255,255),1,cv2.LINE_AA)
            if self.ui_assets is not None and generation!=self.ui_generation:
                return False
            if self.ui_assets is not None and out is not None and not paused and self.inspection.zoom_requested==int(meta.get('ui_generation',-1)):
                from ui import render_inspection as render_inspection
                x,y,rw,rh=right
                with self.condition:
                    self.inspection.open_zoom_locked(canvas[y:y+rh,x:x+rw],meta)
                    payload=self.inspection.payload_locked()
                if payload is not None:
                    render_inspection(canvas,payload,self.ui_assets)
                    self.canvas_views[key]=('inspection',payload['generation'],payload['token']);self.layouts[key]=(None,None)
            if self.media is not None:
                if not preview_only:self.media.capture_from_output(out,meta)
                if self.inspection.kind is None:self.media.render_live(canvas,key,page_changed)
                with self.condition:
                    if self.media.active:return False
            feedback=getattr(self,'_feedback_live',None)
            if feedback is not None:feedback(meta,out is not None)
            # Probe only on a display-mode/epoch transition, never scan/copy an
            # image. Pixel reads must precede official VDMA ownership transfer.
            probe=None
            signature=(view,generation,meta.get('hybrid_epoch'),left is not None,right is not None)
            if signature!=getattr(self,'_live_diagnostic_signature',None):
                probe=[]
                for rect in (left,right):
                    if rect is None:probe.append(None);continue
                    x,y,rw,rh=rect
                    probe.append([canvas[y+rh//2,x+rw//2].tolist(),canvas[y+rh//3,x+rw//3].tolist()])
            #   相机输入档位弹窗：画在最终提交前，盖在左右两幅画面之上。
            #   ⚠️⚠️ 变量名**不能叫 `overlay`** —— 本方法后面还要用同名变量引用
            #      `v114_geometry_overlay` 的四角叠加字典（`overlay['kind']` / `['quad']`）。
            #      2026-10-29 现场就是这里把 `overlay` 覆盖成档位视图 ⇒
            #      `KeyError: 'kind'`，主界面一点"校正"整场崩。
            #   ⚠️ 可见性看**当前页面**，不看 `profile_overlay['visible']` ——
            #      那个标志只在 `publish()` 时刷新，而 `publish()` 只在开/关面板时调，
            #      上板实测：进实时页后它还是构造时的 home 值 ⇒ 按钮一次没画出来。
            if profile_view is not None and view in ('compare','rectified'):
                try:
                    from ui import render_overlay__v120_image_settings as render_overlay
                    render_overlay(canvas,profile_view,self.ui_assets)
                except BaseException as exc:
                    self.profile_overlay=None
                    checkpoint('CAMERA_PROFILE_RENDER_FAILED',error=str(exc)[:400])
            composed=time.perf_counter();composed_cpu=time.thread_time();polls=self.loop.run_until_complete(self._submit(frame));end=time.perf_counter()
            if live_ui is not None:live_ui.rate.observe(meta,end,result_valid and out is not None)
            if profile_controller is not None and profile_view.get('complete'):
                profile_controller.submitted(profile_view,generation,
                    meta.get('input_capture_ready_at',meta.get('capture_ready_at')),
                    meta.get('input_camera_sequence',meta.get('camera_sequence')))
            if result_valid and out is not None:
                settings=getattr(self,'profile_controller',None)
                if settings is not None and hasattr(settings,'sharp_submitted'):settings.sharp_submitted(meta)
            if raw is not None or out is not None:self._live_pixels_seen=True
            if probe is not None:self._live_diagnostic('canvas_submitted',meta,left,right,probe,physical_address=key)
            if meta.get('inspection_redraw'):return True
            sample=dict(index=meta['index'],camera_sequence=meta.get('camera_sequence'),state=meta['state'],epoch=meta['epoch'],
                compose_s=composed-began,compose_thread_cpu_s=composed_cpu-cpu,
                frame_acquire_s=acquired-began,frame_acquire_thread_cpu_s=acquired_cpu-cpu,
                clear_layout_s=clear_end-acquired,clear_layout_thread_cpu_s=clear_cpu-acquired_cpu,
                left_panel_s=left_panel_s,left_panel_thread_cpu_s=left_cpu_s,
                right_panel_s=right_panel_s,right_panel_thread_cpu_s=right_cpu_s,
                panel_native_details=dict(left=left_detail,right=right_detail),corner_draw_s=corner_draw_s,corner_draw_thread_cpu_s=corner_draw_cpu_s,
                held_outline_backend='single_polylines',
                other_compose_s=max(0.,composed-clear_end-left_panel_s-right_panel_s-corner_draw_s),
                current_display_fps_2s=current_rate,display_rate_window_s=2.,
                output_display_fps_3s=live_ui.rate.fps(end) if live_ui is not None else None,
                display_backend='native_direct_color_convert_1to1',display_frontend_version=79,
                capture_age_ms=age,H_age_ms=h_age,
                ui_view=view,ui_generation=generation,ui_header_restore_s=ui_header_restore_s,
                display_scale_enabled=False,display_crop_enabled=False,native_substage_times_available=False,
                input_convert_s=input_convert_s,output_convert_s=output_convert_s,scale_s=scale_s,
                split_conversion_times_available=True,
                conversion_timing_scope='direct conversion wrappers; no resampling; native-only substage timers unavailable',
                vdma_submit_thread_cpu_s=time.thread_time()-composed_cpu,
                vdmasubmit_polls=polls,vdma_submit_s=end-composed,submitted_at=end,display_thread_cpu_s=time.thread_time()-cpu,
                capture_to_submit_s=end-meta.get('capture_ready_at',end),same_frame=same_frame,input_backend=raw_backend,
                input_camera_sequence=meta.get('input_camera_sequence',meta.get('camera_sequence')),
                input_capture_ready_at=meta.get('input_capture_ready_at',meta.get('capture_ready_at')),
                input_capture_age_ms=max(0.,end-meta.get('input_capture_ready_at',meta.get('capture_ready_at',end)))*1000.,
                result_camera_sequence=meta.get('camera_sequence') if out is not None else None,
                preview_only=preview_only,
                overlay_drawn=bool(raw is not None and len(overlay['quad'])==4),
                overlay_kind=overlay['kind'],overlay_reason=overlay['reason'],
                overlay_source_sequence=overlay['source_sequence'],overlay_age_ms=overlay['age_ms'],
                overlay_epoch=overlay.get('epoch'),
                display_mode=display_mode,pair_reason=meta.get('pair_reason'),
                paired_sequence=meta.get('camera_sequence') if display_mode=='PAIRED' and out is not None else None,
                pair_timeout_ms=meta.get('pair_timeout_ms'),pair_stall_ms=meta.get('pair_stall_ms'),
                pair_interarrival_ms=meta.get('pair_interarrival_ms'),pair_entry_regression_ms=meta.get('pair_entry_regression_ms'),
                continuity_output=bool(out is not None and meta.get('continuity_output')),
                continuity_age_s=max(0.,end-float(meta.get('verified_at',end))) if meta.get('continuity_output') else None,
                ai_mode_locked=meta.get('ai_mode_locked'),ai_target_acquired=meta.get('ai_target_acquired'),
                display_hold=paused,
                layout_generation=int(meta.get('layout_generation',0)),orientation=meta.get('orientation'))
            generation=sample['layout_generation']
            if out is not None and generation>self.last_submitted_layout:
                if meta.get('switch_requested_at') is not None:sample['direction_to_submit_s']=end-meta['switch_requested_at']
                self.last_submitted_layout=generation
            snapshot_receipt=None;layout_receipt=None
            with self.condition:
                self.submitted+=int(out is not None and not preview_only);self.panels_submitted+=int(raw is not None and not paused)
                self.unique_current+=int(out is not None and meta['state']=='CURRENT' and not preview_only)
                if raw is not None or out is not None:self.submit_times.append(end)
                if out is not None and not preview_only and meta['state']=='CURRENT' and meta['epoch']==self.epoch:self.current_times.append(end)
                self.samples.append(sample)
                preview=getattr(self,'live_preview',None)
                if display_mode=='RAW_ONLY' and raw is not None and preview is not None and preview.active():
                    preview.pairing.raw_displayed(meta.get('input_capture_ready_at',meta.get('capture_ready_at',end)))
                # Retain a reference to the already owned source; no pixel copy.
                self.tap_source=(raw,dict(meta,camera_sequence=meta.get('input_camera_sequence',meta.get('camera_sequence')),
                    capture_ready_at=meta.get('input_capture_ready_at',meta.get('capture_ready_at'))),left,end)
                stats=self.epoch_stats.setdefault(meta['epoch'],dict(submitted=0,current=0,panels=0,replaced=0,dropped=0))
                stats['submitted']+=int(out is not None and not preview_only);stats['current']+=int(out is not None and meta['state']=='CURRENT' and not preview_only)
                stats['panels']+=int(raw is not None and not paused)
                if paused:stats['display_hold_submissions']=stats.get('display_hold_submissions',0)+1
                if raw is not None or out is not None:stats['last_submitted_at']=end
                command=self.ui_layout_pending
                if (command is not None and meta['state']!='STARTING' and
                        (command[0],command[1])==(int(meta.get('ui_generation',0)),view)):
                    layout_receipt=dict(page=view,generation=command[0],layout_only=True,
                        request_to_submit_s=end-command[2],camera_restarted=False,tracker_reinitialized=False,
                        same_frame=True,index=meta['index'],camera_sequence=meta.get('camera_sequence'),
                        physical_scan_time_measured=False)
                    self.ui_layout_pending=None
                if (view=='snapshot' and raw is not None and out is not None and meta['state'] in ('CURRENT','MANUAL') and
                        int(meta.get('ui_generation',0))==self.ui_generation):
                    self.frozen_generation=self.ui_generation;self.snapshots_frozen+=1
                    snapshot_receipt=dict(generation=self.ui_generation,index=int(meta['index']),
                        camera_sequence=int(meta['camera_sequence']),submitted_at=end,
                        capture_to_submit_s=end-meta.get('capture_ready_at',end),
                        paired_input=True,input_shape=list(raw.shape[:2]),layout='original_left_rectified_right',
                        output_shape=list(out.shape[:2]),vdma_submission_confirmed=True,
                        physical_panel_scan_measured=False)
                    self.snapshot_receipt=snapshot_receipt;self.condition.notify_all()
                    self.last_static_packet=(self.active_slot,out.shape[:2],dict(meta))
            if snapshot_receipt is not None:checkpoint('SNAPSHOT_HDMI_FROZEN',**snapshot_receipt)
            if layout_receipt is not None:checkpoint('UI_PAGE_PRESENTED',**layout_receipt)
            if meta['index']>=0 and (meta['index']%60==0 or end-began>.12):checkpoint('HDMI_FRAME_DETAIL',**sample)
            return True
        finally:
            canvas=None;frame=None
    def begin_measurement(self):
        with self.condition:
            self.epoch+=1;self.current_times.clear();self.submit_times.clear();self.last_submitted_layout=0
            self.epoch_stats[self.epoch]=dict(submitted=0,current=0,panels=0,replaced=0,dropped=0)
            if len(self.epoch_stats)>64:self.epoch_stats.pop(next(iter(self.epoch_stats)))
        return self.epoch
    def _raw_snapshot(self,slot):
        # Caller pins active_slot under the display condition. Producer only
        # replaces an inactive slot; the strong reference spans composition.
        value=self.raw_refs[slot]
        return self.raw_pool[slot] if value is None else value
    def _output_snapshot(self,slot,shape):
        reference=self.output_refs[slot]
        return (self.pool[slot][:shape[0]*shape[1]].reshape(*shape,4)
                if reference is None else reference.array)
    def needs_raw_source(self):
        with self.condition:
            if self.media is not None and self.media.active:return False
            return self.ui_view!='rectified' or self.inspection.kind is not None
    def offer(self,out,meta,raw=None,*,raw_owned=False,output_reference=None):
        begin=time.perf_counter();cpu=time.thread_time();lock_wait=0.;raw_s=0.;out_s=0.
        preview=getattr(self,'live_preview',None)
        if preview is not None and 'hybrid_epoch' not in meta:preview.observe_geometry(meta)
        # Display receives only fields it uses, not the nested tracker/plan tree.
        selected={k:meta.get(k) for k in ('index','camera_sequence','state','corners','color_mode',
            'verified_at','capture_ready_at','correction_fps','layout_generation','orientation',
            'ui_startup_phase','placement_required','placement_confirmed','native_setup_elapsed_s','track_reason',
            'switch_requested_at','switch_decided_at','ui_generation','candidate_corners','candidate_ready_at',
            'min_edge_support','admission_mode','manual_tracking','manual_fps','recovery_active',
            'correction_origin','hybrid_phase','hybrid_epoch','frozen_output','hybrid_valid_fps','hybrid_trigger','tracking_engine','corner_source','target_cycle_state',
            'recovery_round','recovery_from_ai','recovery_retry_after_s',
            'continuity_output','continuity_deadline','continuity_age_s','continuity_epoch',
            'ai_mode_locked','ai_target_acquired','manual_reference_v17','sharp_receipt','light_receipt',
            'target_selection_proof','target_selection_failed') if k in meta}
        if (self.ui_view in ('compare','rectified') and
                ((selected.get('state') not in ('CURRENT','MANUAL') and not valid_continuity(selected,time.perf_counter()))
                    or selected.get('frozen_output'))):
            out=None;selected.update(state='LOST',corners=(),hybrid_valid_fps=0.)
        with self.condition:
            lock_wait+=time.perf_counter()-begin
            if self.error is not None:raise self.error
            if self.stop:raise RuntimeError('HDMI already stopped')
            if self.inspection.kind is not None:
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=time.perf_counter()-begin,display_raw_copy_s=0.,display_output_copy_s=0.,inspection_display_paused=True)
                return 0.
            view=self.ui_view;generation=self.ui_generation
            if self.ui_assets is not None and (view=='home' or selected.get('ui_generation')!=generation):
                self.ui_discarded+=1
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=lock_wait,display_raw_copy_s=0.,display_output_copy_s=0.,ui_offer_discarded=True)
                return 0.
            selected.update(ui_view=view,ui_generation=generation)
            preview=getattr(self,'live_preview',None)
            if (preview is not None and preview.active() and
                    preview.pairing.rejects(selected,raw is not None,out is not None,time.perf_counter())):
                self.ui_discarded+=1;self.last_offer_timing=dict(stale_or_duplicate_pair_discarded=True)
                return 0.
            if view=='snapshot' and self.frozen_generation==generation:
                raise RuntimeError('Single-frame page is already frozen; return before recapture')
            if self.copying_slot is not None:raise RuntimeError('HDMI paired snapshots require one producer')
            self.offered+=1;selected['epoch']=self.epoch
            if self.pending is not None:
                old=self.pending;self.pending=None;self.replaced+=1
                self.epoch_stats.setdefault(old[2]['epoch'],dict(submitted=0,current=0,panels=0,replaced=0,dropped=0))['replaced']+=1
            slot=next((i for i in range(2) if i!=self.active_slot),None)
            if slot is None:
                self.dropped+=1
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=lock_wait,display_raw_copy_s=0.,display_output_copy_s=0.)
                return 0.
            self.copying_slot=slot
            previous_output=self.output_refs[slot];self.output_refs[slot]=None
            if previous_output is not None:previous_output.release()
        borrowed_output=None
        try:
            # This reserved slot is absent from pending and cannot be selected
            # by the display worker. Expensive copies occur outside its lock.
            if raw is not None and (raw.shape!=self.raw_pool[slot].shape or raw.dtype!=np.uint8):raise ValueError('HDMI raw snapshot shape mismatch')
            if raw_owned and raw is not None and (type(raw) is not np.ndarray or not raw.flags.owndata or
                    raw.flags.writeable or not raw.flags.c_contiguous):
                raise ValueError('Owned HDMI raw snapshot must be standalone readonly ordinary-RAM ndarray')
            shape=()
            if out is not None:
                if raw is None and view!='rectified':
                    # A live layout switch may race one already prepared frame.
                    # Drop it; the next prepare observes the new raw requirement.
                    self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                        display_offer_lock_wait_s=lock_wait,display_raw_copy_s=0.,display_output_copy_s=0.,
                        ui_offer_discarded=True,raw_required_after_layout_switch=True)
                    return time.perf_counter()-begin
                if out.ndim!=3 or out.shape[2]!=4 or out.size>self.pool[slot].size:raise ValueError('HDMI output snapshot capacity mismatch')
                shape=out.shape[:2]
            copy_raw=None if view=='rectified' and out is not None else raw
            selected['has_raw_snapshot']=copy_raw is not None
            owned_raw=copy_raw if raw_owned else None
            # Frozen snapshots retain their ordinary-RAM copy for later zoom or
            # manual recalibration. Live output instead retains a completed CMA
            # slot until conversion into an independently owned HDMI canvas.
            if out is not None and output_reference is not None and view!='snapshot':
                borrowed_output=output_reference.retain(out)
            raw_to_copy=None if raw_owned else copy_raw
            out_to_copy=None if borrowed_output is not None else out
            if raw_to_copy is None and out_to_copy is None:
                self.copy_stats.fill(0.);raw_s=out_s=0.
            else:
                raw_s,out_s=paired_copy(self.display_lib,raw_to_copy,self.raw_pool[slot],
                    out_to_copy,self.pool[slot],self.copy_stats)
            selected['raw_snapshot_handoff']='owned_readonly_reference' if owned_raw is not None else 'no_raw' if copy_raw is None else 'copied_snapshot'
            if out is None and selected['state'] not in ('SEARCHING','LOST','STARTING','INITIALIZING','PLACEMENT'):selected['state']='WAITING'
            t=time.perf_counter()
            with self.condition:
                lock_wait+=time.perf_counter()-t
                if self.error is not None:raise self.error
                if self.stop:raise RuntimeError('HDMI stopped during snapshot copy')
                if self.inspection.kind is not None:
                    self.ui_discarded+=1
                    self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                        display_offer_lock_wait_s=lock_wait,display_raw_copy_s=raw_s,display_output_copy_s=out_s,
                        inspection_display_paused=True)
                    return time.perf_counter()-begin
                if self.ui_assets is not None and generation!=self.ui_generation:
                    self.ui_discarded+=1
                    self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                        display_offer_lock_wait_s=lock_wait,display_raw_copy_s=raw_s,display_output_copy_s=out_s,ui_offer_discarded=True)
                    return time.perf_counter()-begin
                preview=getattr(self,'live_preview',None)
                if preview is not None and preview.active():
                    mode=preview.pairing.observe(selected,copy_raw is not None,out is not None,time.perf_counter())
                    if mode=='DROP':
                        self.ui_discarded+=1
                        self.last_offer_timing=dict(stale_or_duplicate_pair_discarded=True)
                        return time.perf_counter()-begin
                    selected.update(preview.pairing.snapshot(time.perf_counter()))
                self.raw_refs[slot]=owned_raw
                self.output_refs[slot]=borrowed_output;borrowed_output=None
                self.slot_packets[slot]=(shape,selected)
                self.pending=(slot if copy_raw is not None or out is not None else None,shape,selected);self.latest_meta=selected
                self.live_last_offer_at=time.perf_counter()
                self.copying_slot=None;self.condition.notify_all()
                elapsed=time.perf_counter()-begin;self.cpu_copy_s+=elapsed
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=lock_wait,display_raw_copy_s=raw_s,display_output_copy_s=out_s,
                    display_raw_reference_handoff=owned_raw is not None,
                    display_output_reference_handoff=self.output_refs[slot] is not None,
                    display_pair_copy_native_s=float(self.copy_stats[2]),display_pair_copy_native_thread_cpu_s=float(self.copy_stats[3]))
                return elapsed
        finally:
            if borrowed_output is not None:borrowed_output.release()
            # Success already relinquished the reservation in the publish lock.
            # Only an interrupted copy needs another lock acquisition.
            if self.copying_slot==slot:
                with self.condition:
                    if self.copying_slot==slot:self.copying_slot=None;self.condition.notify_all()
    def snapshot(self,include_samples=True):
        with self.condition:
            last=self.samples[-1] if self.samples else {}
            right_frozen=bool(last.get('right_frozen') and last.get('ui_generation')==self.ui_generation and self.ui_view in ('compare','rectified'))
            result=dict(offered=self.offered,submitted=self.submitted,current_submitted=self.unique_current,
                split_panels_submitted=self.panels_submitted,replaced_pending=self.replaced,dropped=self.dropped,
                snapshot_copy_s=self.cpu_copy_s,epoch=self.epoch,epoch_stats={str(k):dict(v) for k,v in self.epoch_stats.items()},
                refresh_hz=getattr(getattr(self,'frontend',None),'detail',{}).get('refresh_hz',60),
                nominal_refresh_hz=60,display_max_fps=self.max_fps,mode=list(self.mode),memory_format='BGR24',same_frame=bool(last.get('same_frame',False)),
                transition_display_hold=bool(last.get('display_hold',False)),
                right_view_frozen=right_frozen,right_frozen_canvas_submitted=sum(v.get('right_frozen_canvas_submitted',0) for v in self.epoch_stats.values()),
                shutdown_safe=self.shutdown_safe,error=None if self.error is None else repr(self.error),
                fps_scope='unique correction and unique input panel submissions, not physical panel measurement',
                display_software_abi=7301,display_frontend_version=77,
                ui_enabled=self.ui_assets is not None,ui_view=self.ui_view,ui_generation=self.ui_generation,
                snapshot_frozen=self.ui_view=='snapshot' and self.frozen_generation==self.ui_generation,
                snapshots_frozen=self.snapshots_frozen,
                ui_home_submissions=self.ui_pages_submitted,ui_discarded_offers=self.ui_discarded,
                ui_layout_switches=self.ui_layout_switches,ui_return_feedback_submissions=self.ui_feedback_submitted,
                inspection_openings=self.inspection.opened,inspection_event_redraws=self.inspection.redraws,
                composition_backend='native_direct_color_convert_1to1',display_scale_enabled=False,display_crop_enabled=False,
                raw_snapshot_handoff='automatic immutable ordinary-RAM references; rectified live skips unused source',raw_reference_slots=2,
                output_snapshot_handoff='completed leased CMA slots for live; owned RAM copy for frozen stills',
                completed_output_slots=3,
                current_display_fps_2s=sum(t>=time.perf_counter()-2. for t in self.current_times)/2.,
                current_display_rate_scope='CURRENT-only submissions / fixed2s, warmup cleared; footer excludes submission being composed')
            preview=getattr(self,'live_preview',None)
            if preview is not None:
                result['live_preview']=dict(fallback_copies=preview.fallback_copies,
                    fallback_bytes=preview.fallback_bytes,prepared_publications=preview.prepared_publications,
                    fallback_max_fps=1./(preview.period*2),queue_capacity=1,
                    camera_consumer_added=False,hdmi_writer_added=False)
            result['input_camera_sequence']=last.get('input_camera_sequence')
            result['result_camera_sequence']=last.get('result_camera_sequence')
            if self.media is not None:result['photos']=self.media.statistics_locked()
            if include_samples:result['samples']=list(self.samples)
            return result
    def rescale_input(self, input_shape):
        """换相机档位：重算面板显示尺寸并**整体换掉** `raw_pool`。

        ⚠️ 只在两次会话之间调用（相机已关、旧会话已排空）。
        新池**先建好再原子替换引用**，显示线程下一帧自然用新池；
           旧池在显示线程丢引用后由 GC 回收，不会出现"写到已释放缓冲"。
        返回 True 表示尺寸真的变了。
        """
        h, w = (int(v) for v in input_shape)
        if (h, w) == tuple(self.input_shape):
            return False
        pool = [np.empty((h, w, 2), np.uint8) for _ in range(2)]
        shape = self._fit_shape(self.mode, (h, w))
        native_display_rect(self.mode, shape, 0)   # 放不下就在这里抛，先于替换
        with self.condition:
            self.input_shape = (h, w)
            self.display_shape = shape
            self.raw_pool = pool
            self._scaled = None                    # 旧缩放工作区尺寸已失效
            self.canvas_views.clear()
            self.layouts.clear()
        checkpoint('HDMI_INPUT_RESCALED', input_shape=[h, w],
                   display_shape=list(shape), raw_pool_rebuilt=True)
        return True

    def close(self):
        self.cancel_ui_feedback()
        if self.closed:return
        with self.condition:
            if self.target_switch is not None:self.target_switch.restore()
            self.stop=True;self.condition.notify_all()
        self.worker.join(self.timeout*2+3)
        if self.worker.is_alive():_RETAINED__v64_hdmi_display.append(self);raise RuntimeError('HDMI owner active; keep buffers/overlay')
        if self.media is not None:self.media.close()
        if self._fused is not None:self._fused.close();self._fused=None
        controller=getattr(self,'profile_controller',None)
        if controller is not None:controller.cancel('display_close')
        self.profile_controller=None;self.profile_overlay=None
        self.live_packet=None;self.preview_rendered=None;self.slot_packets[:]=[None,None]
        self.raw_refs[:]=[None,None]
        for reference in self.output_refs:
            if reference is not None:reference.release()
        self.output_refs[:]=[None,None]
        self.closed=True
        if self.error is not None:raise self.error
        if not self.shutdown_safe:raise RuntimeError('HDMI shutdown not proved')


# ======================================================================
# ===== [05/13] v64_p1_backend =====
# ======================================================================


"""P1 immutable combined overlay, conservative plan and a single remap owner.

Original V31 spatial light/surface tables remain unused. A separate pointwise
PWL light stage is controlled once per frame by the existing owner.
"""
from core import RELEASE_ID as RELEASE_ID; from core import verify_package as verify_package; from core import EXACT_PAIR_SHA256 as EXACT_PAIR_SHA256
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v64_p1_backend=[]
_OWNER_SESSION=None

@dataclass(frozen=True)
class Tile:
    box:tuple
    crop:tuple
    regs:tuple
    proof:dict
    packet:bytes

def encode(h):
    h=np.asarray(h,np.float64);h=h/h[2,2]
    values=h.reshape(-1)[:8].copy()
    values[[0,1,3,4,6,7]]*=2048.
    values=np.rint(values*65536.)
    if not np.isfinite(values).all() or (np.abs(values)>2147483647).any():raise ValueError('P1 coefficient overflow')
    return tuple(map(int,values))

class ProofCache:
    """Bounded receipts keyed by the ACTUAL encoded hardware mapping/domain."""
    def __init__(self,capacity=128):
        self.capacity=int(capacity);self.items=OrderedDict();self.hits=0;self.misses=0
    def get(self,key):
        receipt=self.items.get(key)
        if receipt is None:self.misses+=1;return None
        self.items.move_to_end(key);self.hits+=1
        return dict(receipt,proof_cached=True,proof_s=0.,proof_thread_cpu_s=0.,
            receipt_coordinate_samples=receipt.get('checked_pixels'),checked_pixels=0,
            interval_blocks=0,subdivided_blocks=0,proof_nodes=0)
    def put(self,key,receipt):
        # Budget prefixes are not complete receipts, even when sampled values
        # looked safe. Conservative negative decisions may be repeated safely.
        if receipt.get('budget_inconclusive') or receipt.get('code')==-5:return
        self.items[key]=dict(receipt);self.items.move_to_end(key)
        while len(self.items)>self.capacity:self.items.popitem(last=False)
    def snapshot(self):return dict(entries=len(self.items),hits=self.hits,misses=self.misses,capacity=self.capacity)


def _partition_boxes(boxes,size,max_tiles=32):
    """Coverage is exact: bounded rectangles, disjoint interiors, full area."""
    ow,oh=map(int,size);boxes=tuple(tuple(map(int,b)) for b in boxes)
    if not boxes or len(boxes)>max_tiles:raise ValueError('Invalid P1 partition count')
    area=0
    for i,b in enumerate(boxes):
        if len(b)!=4:raise ValueError('P1 partition rectangle requires four bounds')
        x0,y0,x1,y1=b
        if not(0<=x0<x1<=ow and 0<=y0<y1<=oh and x1-x0>=2 and y1-y0>=2):raise ValueError('P1 partition rectangle out of bounds')
        area+=(x1-x0)*(y1-y0)
        for c in boxes[:i]:
            if max(x0,c[0])<min(x1,c[2]) and max(y0,c[1])<min(y1,c[3]):raise ValueError('P1 partition rectangles overlap')
    if area!=ow*oh:raise ValueError('P1 partition does not cover output')
    return boxes


def _merge_pairs(boxes):
    result=[]
    for i,a in enumerate(boxes):
        for j in range(i+1,len(boxes)):
            b=boxes[j]
            if a[0]==b[0] and a[2]==b[2] and (a[3]==b[1] or b[3]==a[1]):
                result.append((i,j,(a[0],min(a[1],b[1]),a[2],max(a[3],b[3]))))
            elif a[1]==b[1] and a[3]==b[3] and (a[2]==b[0] or b[2]==a[0]):
                result.append((i,j,(min(a[0],b[0]),a[1],max(a[2],b[2]),a[3])))
    return result


def _legacy_make_plan(q,shape,size,max_tiles=32,*,proof_cache=None,strategy='fast_safe',proof_cpu_budget_s=.012,
              partition_boxes=None,merge_probe=False,merge_cursor=0,workspace=None,_h_current=None,_proof_prior_cpu_s=0.):
    """Reuse leaf geometry only; every current H/crop/packet has a fresh proof.

    Bounded low-frequency merging can reduce tile count without retrying the
    expensive full-output proof on each moving corner measurement.
    """
    if strategy not in ('fast_safe','exact_reference'):raise ValueError('Unknown P1 plan strategy')
    if not .002<=float(proof_cpu_budget_s)<=.03:raise ValueError('Proof CPU budget must be2..30ms')
    ih,iw=map(int,shape[:2]);ow,oh=map(int,size)
    q=np.asarray(q,np.float32)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Invalid current quad')
    if not 2<=ow<=4095 or not 2<=oh<=4095:raise ValueError('P1 output dimensions invalid')
    ws=workspace if workspace is not None else PlanWorkspace()
    h=(cv2.getPerspectiveTransform(ws.destination(size),q).astype(np.float64) if _h_current is None
        else np.asarray(_h_current,np.float64).copy())
    if not np.isfinite(h).all() or abs(h[2,2])<1e-12:raise ValueError('Invalid P1 homography')
    h/=h[2,2];tiles=[];failures=[];proof_s=0.;proof_cpu_s=0.;visited=0
    proof_cache_hits=0;proof_budget_splits=0;proof_samples=0;interval_blocks=0
    mapping_s=0.;mapping_cpu_s=0.;merge_attempts=0;merge_accepted=0
    reused=partition_boxes is not None and strategy=='fast_safe'
    boxes=_partition_boxes(partition_boxes,size,max_tiles) if reused else ((0,0,ow,oh),)
    def candidate(box,probe=False):
        nonlocal proof_s,proof_cpu_s,visited,proof_cache_hits,proof_budget_splits,proof_samples,interval_blocks,mapping_s,mapping_cpu_s
        t=time.perf_counter();c=time.thread_time();mapping,reason=ws.map_tile(h,box,(iw,ih))
        mapping_s+=time.perf_counter()-t;mapping_cpu_s+=time.thread_time()-c
        if mapping is None:return None,reason
        crop,regs,packet=mapping;cx,cy,cw,ch=crop;tw,th=box[2]-box[0],box[3]-box[1]
        key=(6601,0x10007,int(__import__('core').LINE_BUF_ROWS),strategy,regs,cw,ch,tw,th)
        proof=proof_cache.get(key) if proof_cache is not None else None
        if proof is not None:proof_cache_hits+=1
        else:
            remaining=float(proof_cpu_budget_s)-proof_cpu_s-float(_proof_prior_cpu_s)
            #   ⚠️ 2026-10-25：这个门槛原来是 192（旧 ROWS）。硬件现在是 384，
            #      用 192 会把「其实装得下」的 tile 也判成"预算不够"→ 多余地切块/放弃。
            if strategy=='fast_safe' and ch>int(__import__('core').LINE_BUF_ROWS) and remaining<.0005:
                proof_budget_splits+=1;visited+=1
                return None,dict(code=-5,reason='bounded_plan_proof_CPU_budget_exhausted',safe_fallback='split_to_whole_source_crop_retention')
            proof=guard(regs,(cw,ch),(tw,th),strategy=strategy,
                cpu_budget_s=max(.0005,min(.001 if probe else .008,remaining)),block_pixels=128,workspace=ws)
            if proof_cache is not None:proof_cache.put(key,proof)
        proof_s+=proof['proof_s'];proof_cpu_s+=proof.get('proof_thread_cpu_s',0.);visited+=1
        proof_samples+=int(proof.get('checked_pixels') or 0);interval_blocks+=int(proof.get('interval_blocks') or 0)
        proof_budget_splits+=int(proof.get('budget_inconclusive',False))
        if not proof['valid']:return None,proof
        return Tile(tuple(box),crop,regs,proof,packet),None
    def split(box,depth=0):
        tile,reason=candidate(box)
        if tile is not None:tiles.append(tile);return
        if len(tiles)>=max_tiles or depth>=12:raise ValueError('P1 tile proof budget exceeded: '+str(reason))
        x0,y0,x1,y1=box;w,hh=x1-x0,y1-y0
        if min(w,hh)<4:raise ValueError('P1 cannot prove this raster direction: '+str(reason))
        # Keep the established split decision: smaller worst source y span.
        choices=[]
        for axis in ('x','y'):
            mid=(x0+x1)//2 if axis=='x' else (y0+y1)//2
            children=[(x0,y0,mid,y1),(mid,y0,x1,y1)] if axis=='x' else [(x0,y0,x1,mid),(x0,mid,x1,y1)]
            spans=[]
            for b in children:
                xy=np.array([[b[0],b[1]],[b[2]-1,b[1]],[b[2]-1,b[3]-1],[b[0],b[3]-1]],np.float64)
                d=xy@h[2,:2]+h[2,2];yy=(xy@h[1,:2]+h[1,2])/d;spans.append(float(np.ptp(yy)))
            choices.append((max(spans),axis,children))
        _,axis,children=min(choices,key=lambda v:v[0]);failures.append(dict(box=box,axis=axis,reason=reason))
        for b in children:split(b,depth+1)
    merged=None;excluded=()
    if reused and merge_probe and len(boxes)>1:
        pairs=_merge_pairs(boxes)
        if pairs:
            i,j,merged_box=pairs[int(merge_cursor)%len(pairs)];merge_attempts=1
            merged,merge_reason=candidate(merged_box,probe=True)
            if merged is not None:excluded=(i,j);merge_accepted=1
    for i,box in enumerate(boxes):
        if i not in excluded:split(box)
    if merged is not None:tiles.append(merged)
    tiles.sort(key=lambda tile:(tile.box[1],tile.box[0]))
    _partition_boxes((tile.box for tile in tiles),size,max_tiles)
    return tuple(tiles),dict(tile_count=len(tiles),proof_s=proof_s,proof_thread_cpu_s=proof_cpu_s,
        proof_attempts=visited,split_events=failures,proof_cache_hits=proof_cache_hits,
        proof_cache=proof_cache.snapshot() if proof_cache is not None else None,
        proof_budget_splits=proof_budget_splits,proof_coordinate_samples=proof_samples,
        interval_blocks=interval_blocks,proof_strategy=strategy,proof_cpu_budget_s=float(proof_cpu_budget_s),
        planner='reused_partition_fresh_native_mapping_and_proof',full_pixel_scan_enabled=strategy=='exact_reference',
        partition_reused=reused,partition_input_tiles=len(boxes),partition_boxes=[t.box for t in tiles],
        merge_probe_attempts=merge_attempts,merge_probe_accepted=merge_accepted,merge_probe_cpu_budget_s=.001,
        mapping_native_s=mapping_s,mapping_native_thread_cpu_s=mapping_cpu_s,
        proof_methods=[t.proof['method'] for t in tiles],h_out2in=h.tolist(),
        mapping='planar_p1_fixed_q16',input_bytes=sum(t.crop[2]*t.crop[3]*4 for t in tiles))


def make_plan(q,shape,size,max_tiles=32,*,proof_cache=None,strategy='fast_safe',proof_cpu_budget_s=.012,
              partition_boxes=None,merge_probe=False,merge_cursor=0,workspace=None):
    """Batch ordinary geometry, retaining the exact legacy split/merge fallback.

    Row certificates always describe actual encoded packets. Native cache keys
    contain all ten words and fixed ABI/version/192-row context, never rounded H.
    """
    args=dict(proof_cache=proof_cache,strategy=strategy,proof_cpu_budget_s=proof_cpu_budget_s,
        partition_boxes=partition_boxes,merge_probe=merge_probe,merge_cursor=merge_cursor,workspace=workspace)
    if strategy!='fast_safe' or merge_probe:
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args)
        detail.update(native_geometry_used=False,native_geometry_fallback='reference_or_merge_probe',native_geometry_calls=0)
        return tiles,detail
    if not .002<=float(proof_cpu_budget_s)<=.03:raise ValueError('Proof CPU budget must be2..30ms')
    ih,iw=map(int,shape[:2]);ow,oh=map(int,size);q=np.asarray(q,np.float32)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Invalid current quad')
    if not 2<=ow<=4095 or not 2<=oh<=4095:raise ValueError('P1 output dimensions invalid')
    ws=workspace if workspace is not None else PlanWorkspace();args['workspace']=ws
    boxes=_partition_boxes(partition_boxes,size,max_tiles) if partition_boxes is not None else ((0,0,ow,oh),)
    if len(boxes)>ws.batch.capacity:
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args)
        detail.update(native_geometry_used=False,native_geometry_fallback='batch_capacity',native_geometry_calls=0)
        return tiles,detail
    batch=ws.batch.run(q,(iw,ih),size,boxes,proof_cpu_budget_s)
    if batch is None:
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args)
        status=ws.batch.last_status
        detail.update(native_geometry_used=False,native_geometry_fallback=status.get('reason'),
            native_geometry_s=status.get('wall_s',0.),native_geometry_thread_cpu_s=status.get('thread_cpu_s',0.),
            native_geometry_calls=int(status.get('available',False)))
        return tiles,detail
    h,mapping,packets,results,status=batch
    start=time.perf_counter();used=time.thread_time();tiles=[];proofs=[];failures=[]
    for i,box in enumerate(boxes):
        meta=results[i];mapping_code=int(meta[0])
        if mapping_code:
            failures.append(dict(box=box,mapping_code=mapping_code));continue
        m=mapping[i];crop=tuple(map(int,m[:4]));regs=tuple(map(int,m[4:]));code=int(meta[1]);cached=bool(meta[2])
        t=ws.batch.times[16+i*4:20+i*4]
        proof=dict(valid=code==0,code=code,peak_rows=int(meta[3]) if code==0 else None,
            checked_pixels=int(meta[4]),interval_blocks=int(meta[5]),subdivided_blocks=int(meta[6]),
            failure_at=[int(meta[7]),int(meta[8])] if code else None,proof_nodes=int(meta[9]),
            method='whole_source_crop_retention_and_operand_bounds' if meta[10]==0 else 'bounded_fixed_point_interval_lifetime',
            proof_s=float(t[2]),proof_thread_cpu_s=float(t[3]),complete_domain_verified=code==0,
            budget_inconclusive=code==-5,proof_strategy=strategy,proof_cached=cached,
            cpu_budget_s=float(proof_cpu_budget_s),interval_block_pixels=128,exact_reference_fallback=False,
            proof_cache_backend='native_exact_ten_word_LRU',receipt_coordinate_samples=int(meta[11]) if cached else None)
        key=(6601,0x10007,int(__import__('core').LINE_BUF_ROWS),strategy,regs,crop[2],crop[3],box[2]-box[0],box[3]-box[1])
        proofs.append((key,proof))
        if proof['valid']:
            # Small immutable payload only. No mutable native workspace view is
            # published to the MMIO owner or asynchronous display.
            tiles.append(Tile(tuple(box),crop,regs,proof,packets[i].tobytes()))
        else:failures.append(dict(box=box,proof=proof))
    decode_s=time.perf_counter()-start;decode_cpu=time.thread_time()-used
    common=dict(native_geometry_used=True,native_geometry_s=status['wall_s'],
        native_geometry_thread_cpu_s=status['thread_cpu_s'],native_geometry_calls=1,
        h_native_s=status['h_s'],h_native_thread_cpu_s=status['h_thread_cpu_s'],
        geometry_result_decode_s=decode_s,geometry_result_decode_thread_cpu_s=decode_cpu,
        native_plan_cache=dict(ws.batch.last_cache),native_initial_proof_s=status['proof_s'],
        native_initial_proof_thread_cpu_s=status['proof_thread_cpu_s'])
    if failures:
        # Seed only complete actual-domain receipts. Failed CPU prefixes are
        # deliberately not cacheable. Legacy split decisions remain unchanged.
        if proof_cache is not None:
            for key,proof in proofs:proof_cache.put(key,proof)
        tiles,detail=_legacy_make_plan(q,shape,size,max_tiles,**args,_h_current=h,
            _proof_prior_cpu_s=status['proof_thread_cpu_s'])
        detail.update(common,native_geometry_fallback='existing_split_after_unproved_batch',
            native_batch_failures=failures,native_H_reused=True)
        # The old stage totals include all computation performed by this call.
        detail['proof_s']+=status['proof_s'];detail['proof_thread_cpu_s']+=status['proof_thread_cpu_s']
        detail['mapping_native_s']+=status['mapping_s'];detail['mapping_native_thread_cpu_s']+=status['mapping_thread_cpu_s']
        detail['proof_attempts']+=len(boxes);detail['proof_cache_hits']+=status['proof_cache_hits']
        detail['proof_coordinate_samples']+=sum(p['checked_pixels'] for _,p in proofs)
        detail['interval_blocks']+=sum(p['interval_blocks'] for _,p in proofs)
        detail['proof_budget_splits']+=sum(p['budget_inconclusive'] for _,p in proofs)
        return tiles,detail
    tiles.sort(key=lambda tile:(tile.box[1],tile.box[0]));_partition_boxes((t.box for t in tiles),size,max_tiles)
    detail=dict(tile_count=len(tiles),proof_s=status['proof_s'],proof_thread_cpu_s=status['proof_thread_cpu_s'],
        proof_attempts=len(boxes),split_events=[],proof_cache_hits=status['proof_cache_hits'],
        proof_cache=proof_cache.snapshot() if proof_cache is not None else None,
        proof_budget_splits=0,proof_coordinate_samples=sum(p['checked_pixels'] for _,p in proofs),
        interval_blocks=sum(p['interval_blocks'] for _,p in proofs),proof_strategy=strategy,proof_cpu_budget_s=float(proof_cpu_budget_s),
        planner='native_current_H_mapping_packet_and_rowproof',full_pixel_scan_enabled=False,
        partition_reused=partition_boxes is not None,partition_input_tiles=len(boxes),partition_boxes=[t.box for t in tiles],
        merge_probe_attempts=0,merge_probe_accepted=0,merge_probe_cpu_budget_s=.001,
        mapping_native_s=status['mapping_s'],mapping_native_thread_cpu_s=status['mapping_thread_cpu_s'],
        proof_methods=[t.proof['method'] for t in tiles],h_out2in=h.tolist(),mapping='planar_p1_fixed_q16',
        input_bytes=sum(t.crop[2]*t.crop[3]*4 for t in tiles),native_geometry_fallback=None)
    detail.update(common);return tuple(tiles),detail

def inspect_pair(bitfile):
    path=Path(bitfile).resolve();verify_package(str(path))
    info=json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf-8-sig'))
    if info.get('format')!='p1-light-pair-v1' or info.get('remap_version')!=0x00010005:raise ValueError('Specified PL sharp pair receipt mismatch')
    for p,stem in ((path,'bit'),(path.with_suffix('.hwh'),'hwh')):
        data=p.read_bytes()
        if (hashlib.sha256(data).hexdigest()!=EXACT_PAIR_SHA256[p.name] or
            info[stem+'_sha256']!=EXACT_PAIR_SHA256[p.name] or
            '%08x'%(zlib.crc32(data)&0xffffffff)!=info[stem+'_crc32']):raise ValueError('Specified P1 hardware pair mismatch')
    if info.get('input_contract')!=dict(format='BGRX32',bytes_per_pixel=4,PL_YUYV=False,color_conversion='existing_native_CPU'):
        raise ValueError('Selected remap1.5 requires BGRX32 native CPU input contract')
    tree=ET.parse(path.with_suffix('.hwh'));mods={m.get('FULLNAME'):m for m in tree.findall('.//MODULE')}
    remap=mods.get('/remap')
    if remap is None:raise ValueError('Missing P1 remap metadata')
    params={p.get('NAME'):p.get('VALUE') for p in remap.findall('./PARAMETERS/PARAMETER')}
    #   ⚠️ 2026-10-25：行缓存改成 MAX_W=512 / ROWS=384（用宽度换深度）。
    #      hwh 里的参数必须和这里一致 —— 不一致说明装错了 bit。
    #   ⚠️ 硬件参数从 p11_contract 取（别再写字面量 —— 已经漏过两次）。
    from core import LINE_BUF_W as LINE_BUF_W; from core import LINE_BUF_ROWS as LINE_BUF_ROWS
    for key,val in (('DW',32),('MAX_W',int(LINE_BUF_W)),('NCH',3),('PIX_W',24),('ROWS',int(LINE_BUF_ROWS)),('NORM_SCALE',2048)):
        if int(params.get(key,-1))!=val:raise ValueError('P1 parameter mismatch '+key)
    dma=mods.get('/axi_dma_0')
    if dma is None:raise ValueError('Missing remap DMA metadata')
    dp={p.get('NAME'):p.get('VALUE') for p in dma.findall('./PARAMETERS/PARAMETER')}
    if int(dp.get('C_INCLUDE_SG',-1))!=0 or int(dp.get('C_SG_LENGTH_WIDTH',-1))!=23:raise ValueError('P1 simple DMA/length metadata mismatch')
    ps=next((m for m in mods.values() if m.get('INSTANCE')=='ps7'),None)
    if ps is None:raise ValueError('Missing PS clock metadata')
    p={x.get('NAME'):x.get('VALUE') for x in ps.findall('./PARAMETERS/PARAMETER')}
    if p.get('PCW_FCLK0_PERIPHERAL_CLKSRC')!='IO PLL':raise ValueError('Unexpected P1 FCLK0 source')
    hz=float(p['PCW_IO_IO_PLL_FREQMHZ'])*1e6/(int(p['PCW_FCLK0_PERIPHERAL_DIVISOR0'])*int(p['PCW_FCLK0_PERIPHERAL_DIVISOR1']))
    if abs(hz-float(p['PCW_CLK0_FREQ']))>1000:raise ValueError('P1 HWH clock tree mismatch')
    display=mods.get('/video/axi_vdma_disp')
    if display is None:raise ValueError('Specified P1 HDMI VDMA hierarchy missing')
    vp={x.get('NAME'):x.get('VALUE') for x in display.findall('./PARAMETERS/PARAMETER')}
    for key,val in (('C_INCLUDE_MM2S',1),('C_INCLUDE_S2MM',0),('C_M_AXIS_MM2S_TDATA_WIDTH',32),('C_NUM_FSTORES',4)):
        if int(vp.get(key,-1))!=val:raise ValueError('Specified P1 HDMI VDMA mismatch '+key)
    for ip in ('/video/hdmi_out/pixel_unpack','/video/hdmi_out/color_convert','/video/hdmi_out/frontend/vtc_out','/video/hdmi_out/frontend/axi_dynclk'):
        if ip not in mods:raise ValueError('Specified P1 HDMI pipeline missing '+ip)
    from ui import inspect_sharp_metadata as inspect_sharp_metadata
    inspect_sharp_metadata(mods)
    from ui import inspect_light_metadata as inspect_light_metadata
    inspect_light_metadata(mods)
    checkpoint('P1_PAIR_ADMITTED',source_pair='PWL light27 matched bit + HWH',
        bitfile=str(path),sha256=dict(EXACT_PAIR_SHA256),hdmi_vdma='video/axi_vdma_disp',fclk0_hz=hz,
        hardware_substitution_allowed=False,hardware_modified=True,bit_rebuilt=True)
    return path,info,hz

class P1Backend:
    def __init__(self,bitfile='system.bit',input_shape=(480,640),output_size=(362,512),timeout_s=3.):
        global _OWNER_SESSION
        if _OWNER_SESSION is not None:raise RuntimeError('Previous P1 session must be closed before download')
        path,manifest,hz=inspect_pair(bitfile)
        from pynq import Overlay,MMIO,allocate,Clocks
        # Register official drivers before constructing the overlay hierarchy.
        import pynq.lib.video,pynq.lib.dma
        self.overlay=Overlay(str(path),ignore_version=True);self.path=path;self.manifest=manifest
        validate_overlay(self.overlay,manifest)
        if abs(float(Clocks.fclk0_mhz)*1e6-hz)>5000:raise RuntimeError('Actual FCLK0 differs from selected P1 HWH')
        self.mmio=MMIO(0x40000000,0x40)
        dma_info=self.overlay.ip_dict['axi_dma_0']
        # Do not instantiate overlay.axi_dma_0: its PYNQ channel constructor
        # starts the channels immediately. This adapter exclusively owns MMIO.
        self.dma=MMIO(int(dma_info['phys_addr']),int(dma_info['addr_range']))
        self.owner=threading.get_ident();self.timeout_s=float(timeout_s);self.active=False;self.failed=False;self.closed=False
        self.ticket=0;self.buffers=[];self.packed={};self.input_shape=tuple(input_shape)
        self.output_slots=None;self.completed_output=None
        self.input_packer=None;self.active_input_slot=None
        #   ⭐ C2：None = 还没决定；True/False = PL 侧做 YUV→RGB / PS 侧做
        self.input_yuyv=None;self.pl_color_mode=0;self.last_release_s=0.
        self.output_capacity=int(output_size[0])*int(output_size[1]);self.dma_snapshot=np.zeros(4,np.uint32)
        self.parameter_snapshot=np.zeros(2,np.uint32)
        _OWNER_SESSION=self
        try:
            for _ in range(2):self.buffers.append(allocate(shape=(int(input_shape[0])*int(input_shape[1])*4,),dtype=np.uint8))
            self.tile_buffer=allocate(shape=(self.output_capacity*4,),dtype=np.uint8);self.buffers.append(self.tile_buffer)
            from tracking import OutputSlots as OutputSlots
            self.output_slots=OutputSlots(allocate,self.output_capacity)
            self._start_fresh()
            from ui import SharpControl as SharpControl; from ui import SharpDriver as SharpDriver
            self.sharp_control=SharpControl(path.parent)
            self.sharp=SharpDriver(self.overlay,MMIO,self.sharp_control)
            from ui import LightControl as LightControl; from ui import LightDriver as LightDriver
            self.light_control=LightControl(path.parent)
            self.light=LightDriver(self.overlay,MMIO,self.light_control)
        except BaseException:
            self.close();raise
        checkpoint('P1_BACKEND_READY',durable=True,version=int(self.mmio.read(0x30)),fclk0_hz=hz,
            rows=int(__import__('core').LINE_BUF_ROWS),max_width=int(__import__('core').LINE_BUF_W),input_format='YUYV_or_BGRX',internal_line_format='RGB565',
            cma_bytes=sum(b.nbytes for b in self.buffers)+sum(b.nbytes for b in self.output_slots.buffers),ack='ten_register_readback_plus_software_ticket',
            board_hardware_tested=manifest.get('board_hardware_tested',False))
    def _assert_owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('P1 device access must stay on owner thread')
        if self.failed or self.closed:raise RuntimeError('P1 session failed/closed; restart board after active DMA error')
    def _start_fresh(self):
        d=self.dma;tx,rx=d.read(4),d.read(0x34)
        if not(tx&1 and rx&1) or (tx|rx)&0x70:raise RuntimeError('Fresh overlay DMA is not halted/clean')
        d.write(0,4);end=time.perf_counter()+self.timeout_s
        while d.read(0)&4:
            if time.perf_counter()>end:raise TimeoutError('Fresh P1 DMA reset timed out')
            time.sleep(.0002)
        d.write(0x30,1);d.write(0,1)
        while (d.read(4)|d.read(0x34))&1:
            if time.perf_counter()>end:raise TimeoutError('Fresh P1 DMA start timed out')
            time.sleep(.0002)
        # This adapter owns the simple DMA directly; PYNQ transfer/wait is never called.
        self.dma_array=d.array
    def _configure(self,tile,size):
        before=parameters(self.mmio.array,tile.packet,self.parameter_snapshot)
        self.ticket+=1;return self.ticket,before
    def _input_format(self):
        # This exact supplied pair is remap1.5. Its CTRL is write-only and
        # has no YUYV/colour mode latch. Use the existing native BGRX32 packer;
        # never probe unsupported format bits or reinterpret raw YUYV as RGB.
        if self.input_yuyv is None:
            from core import color_mode as color_mode
            self.input_yuyv=False;self.pl_color_mode=int(color_mode())&3
            checkpoint('P1_INPUT_FORMAT',durable=True,yuyv=False,color_mode=self.pl_color_mode,
                requested=os.environ.get('P11_YUYV_INPUT','1')!='0',
                reason='paired_remap_1p5_BGRX32_only',input_format='BGRX32',bytes_per_pixel=4,
                color_conversion='existing_native_CPU',board_FPS_verified=False)
        return self.input_yuyv
    def _copy_input_batch(self,job,slot):
        #   ⭐ C2：只做 strided memcpy，**不做 YUV→RGB**（那步挪进 PL 了）。
        #   目的地是 CMA（可缓存），源是相机 mmap 的 YUYV 行；crop 的 left/width
        #   都已按偶数对齐（v8_geometry.make_tile 保证），所以每行 4 字节对齐。
        #   ⚠️ 一次 numpy 赋值 = 一次 C 层 strided copy，没有 Python 逐像素循环。
        from tracking import PackedInput as PackedInput
        from core import require_yuyv as require_yuyv
        dest=self.buffers[slot];image=require_yuyv(job.lease.image)
        #   ⚠️ 与写进 PL 的 color_mode 必须一致，否则 PL 用错系数 ⇒ 颜色偏但不报错
        if int(job.color_mode)!=int(self.pl_color_mode):
            raise RuntimeError('YUYV color_mode %d != PL %d'%(int(job.color_mode),int(self.pl_color_mode)))
        offsets=[];offset=0;begin=time.perf_counter();native=0.
        for tile in job.tiles:
            x,y,w,h=map(int,tile.crop)
            if (x&1) or (w&1):raise RuntimeError('YUYV crop must be even-aligned: %r'%((x,w),))
            n=w*h*2
            if offset+n>dest.nbytes:return None
            #   ⚠️ 必须用 C++ 的每行 memcpy（ctypes）。
            #      numpy 三维赋值在**桌面 x86 上并不慢**（122 KB 0.003 ms），
            #      所以早先"numpy 退化成逐 2 字节"的解释是【错的】，已撤。
            #      板上真正贵的是 ctypes 调用的 GIL/调度抖动（见 C1）。
            t=time.perf_counter();copy_yuyv_rows(image,(x,y,w,h),dest,offset);native+=time.perf_counter()-t
            offsets.append(offset);offset+=n
        return PackedInput(job,offsets,dict(input_pack_batch=True,input_pack_yuyv=True,input_bpp=2,
            input_pack_tiles=len(job.tiles),input_pack_bytes=offset,
            input_pack_converted_pixels=offset//2,input_pack_kernel_calls=len(job.tiles),
            input_pack_native_s=native,input_pack_wrapper_s=time.perf_counter()-begin-native,
            input_pack_pl_copy=True))
    def _pack_input_batch(self,job,slot):
        self._assert_owner()
        if slot not in (0,1) or (self.active and slot==self.active_input_slot):
            raise RuntimeError('Cannot pack an active P1 input buffer')
        if self._input_format():
            batch=self._copy_input_batch(job,slot)
            if batch is None:raise RuntimeError('YUYV input copy rejected a tile')
            job.release_source()
            return batch
        if self.input_packer is None:
            from tracking import InputPackWorkspace as InputPackWorkspace
            self.input_packer=InputPackWorkspace()
        batch=self.input_packer.pack(job,self.buffers[slot])
        if batch is not None:job.release_source()  # All crops now own independent CMA bytes.
        return batch
    def prefill(self,job,slot):
        """Only the owner copies into idle CMA; never change current DMA buffer."""
        self._assert_owner()
        if job is None or job.state=='LOST' or not job.tiles:return 0.
        key=(job.index,slot)
        if key in self.packed:return 0.
        begin=time.perf_counter();batch=self._pack_input_batch(job,slot)
        if batch is not None:
            self.packed[key]=batch
            return time.perf_counter()-begin
        pack_yuyv(job.lease.image,job.tiles[0].crop,job.color_mode,self.buffers[slot])
        # DMA sees a CMA copy; no camera MMAP address is programmed.
        self.packed[key]=job.tiles[0]
        # A multi-tile job still needs its leased source for subsequent crops.
        if len(job.tiles)==1:job.release_source()
        return time.perf_counter()-begin
    def execute(self,job,lookahead=None):
        self._assert_owner()
        if job.state=='LOST':raise ValueError('LOST frame cannot be submitted')
        ow,oh=job.size
        if ow*oh>self.output_capacity:raise ValueError('Output exceeds persistent capacity')
        if not job.tiles:raise ValueError('Current P1 frame has no proved tiles')
        # Whole-width strips have contiguous output rows. RX addresses must be
        # four-byte aligned: the immutable DMA has no data-realignment engine.
        row_end=0;direct_rows=True
        for tile in job.tiles:
            x0,y0,x1,y1=tile.box
            if x0!=0 or x1!=ow or y0!=row_end or y1<=y0 or y1>oh:direct_rows=False;break
            row_end=y1
        direct_rows=direct_rows and row_end==oh
        _t0=time.perf_counter()          # ⭐ 诊断：release/acquire 原先落在 owner_s 之外
        if self.completed_output is not None:self.completed_output.release();self.completed_output=None
        self.completed_output=self.output_slots.acquire(ow,oh)
        _out_reset_s=time.perf_counter()-_t0
        result=self.completed_output.array
        receive_buffer=self.output_slots.buffers[self.completed_output.index] if direct_rows else self.tile_buffer
        timing=dict(control_s=0.,input_copy_s=0.,cache_sync_s=0.,dma_wait_s=0.,tile_assembly_s=0.,
            owner_release_s=0.,owner_prep_s=0.,owner_sharp_prep_s=0.,owner_arm_s=0.,owner_sharp_done_s=0.,
            lookahead_service_s=0.,lookahead_prefills=0,tiles=len(job.tiles),
            direct_row_receive=bool(direct_rows),receive_layout='full_width_row_offsets' if direct_rows else 'tile_then_host_assembly',
            tile_assembly_bytes=0,output_cache_batches=0,output_slot=self.completed_output.index,
            completed_output_reference=True,owner_out_reset_s=_out_reset_s,
            prev_release_source_s=float(getattr(self,'last_release_s',0.)),
            #   ⭐ 2026-10-25：查 tile 数到底被什么卡住 —— 是行缓存的 ROWS 还是别的。
            #      peak_rows = 该 tile 需要的最大源行跨度（证明里算出来的），
            #      ROWS=192 是硬件上限，两者一比就知道"加深行缓存能不能少切块"。
            tile_boxes=[list(map(int,t.box)) for t in job.tiles],
            tile_crops=[list(map(int,t.crop)) for t in job.tiles],
            tile_peak_rows=int(max((t.proof.get('peak_rows') or 0) for t in job.tiles)),
            tile_crop_w=int(max(int(t.crop[2]) for t in job.tiles)),
            tile_crop_h=int(max(int(t.crop[3]) for t in job.tiles)))
        began=time.perf_counter();cpu=time.thread_time();slot=job.index%2
        try:
            timing['sharp_receipt']=self.sharp.begin_frame(job.tiles)
            if hasattr(self,'light'):timing['light_receipt']=self.light.begin_frame(job.tiles)
            from tracking import PackedInput as PackedInput
            #   ⚠️ 2026-10-31：预取深度改 2 后命中率从 14% 升到 ~92%，LOST 帧不会走 execute，
            #      它的预取条目就永远没人 pop ⇒ 字典会无限长。这里顺手清掉过期的（正常 ≤2 项）。
            if self.packed:
                for stale in [k for k in self.packed if k[0]<job.index]:self.packed.pop(stale,None)
            packed_first=self.packed.pop((job.index,slot),None)
            batch=packed_first if isinstance(packed_first,PackedInput) else None
            if batch is not None and not batch.matches(job):raise RuntimeError('Stale P1 input batch does not belong to this frame')
            pack_begin=time.perf_counter()
            if packed_first is None:batch=self._pack_input_batch(job,slot)
            timing['input_copy_s']+=time.perf_counter()-pack_begin
            timing.update(input_pack_batch=batch is not None,input_pack_prefilled=isinstance(packed_first,PackedInput))
            if batch is not None:timing.update(batch.detail)
            #   ⭐ 2026-10-24 诊断：owner_s 里有 13.4 ms 说不清（run 83），先把它拆成
            #      前置 / 循环 / 收尾 三段，循环内部再用已有的子计时往下减。
            #      ⚠️ 纯计时，不改任何行为。
            timing['owner_setup_s']=time.perf_counter()-began
            loop_begin=time.perf_counter()
            for number,tile in enumerate(job.tiles):
                t=time.perf_counter();packed=packed_first if number==0 else None
                if batch is None and packed is not tile:pack_yuyv(job.lease.image,tile.crop,job.color_mode,self.buffers[slot])
                timing['input_copy_s']+=time.perf_counter()-t
                t=time.perf_counter()
                if len(job.tiles)==1:job.release_source()
                timing['owner_release_s']+=time.perf_counter()-t
                if self.active:raise RuntimeError('Cannot reconfigure active remap')
                t=time.perf_counter();ticket,before=self._configure(tile,job.size);timing['control_s']+=time.perf_counter()-t
                t_prep=time.perf_counter()
                #   ⚠️ n_in 的 bpp 必须跟着【实际送进 DMA 的格式】走：
                #      BGRX32=4、YUYV=2。写错会让 DMA 多搬/少搬一半的字节，
                #      现象是"图错位但核不报错"，很难查。
                #   ⚠️ 行缓存 MAX_W=640（2026-10-25 由 1024 降下来换 ROWS=320）。
                #      crop 宽度超 640 会让行缓存地址**静默回绕**（错图但不报错），
                #      所以在这里硬挡一道 —— 规划器那边改漏了也炸得出来。
                from core import LINE_BUF_W as _LBW
                if int(tile.crop[2])>_LBW:
                    raise RuntimeError('P1 crop width %d exceeds line buffer MAX_W=%d'%(int(tile.crop[2]),_LBW))
                n_in=tile.crop[2]*tile.crop[3]*(4 if batch is None else int(batch.bpp))
                tw,th=tile.box[2]-tile.box[0],tile.box[3]-tile.box[1];n_out=tw*th*4
                if not tile.proof.get('valid') or not tile.proof.get('complete_domain_verified') or n_in>=(1<<23) or n_out>=(1<<23):raise RuntimeError('Unproved P1 tile')
                receive_offset=tile.box[1]*ow*4 if direct_rows else 0
                if receive_offset<0 or receive_offset+n_out>receive_buffer.nbytes or receive_offset%4:
                    raise RuntimeError('P1 receive span exceeds aligned CMA capacity')
                receive_address=int(receive_buffer.physical_address)+receive_offset
                if receive_address+n_out>(1<<32):raise RuntimeError('P1 receive span exceeds 32-bit address space')
                input_offset=0 if batch is None else int(batch.offsets[number])
                if input_offset<0 or input_offset%4 or input_offset+n_in>self.buffers[slot].nbytes:
                    raise RuntimeError('P1 input batch span exceeds aligned CMA capacity')
                input_address=int(self.buffers[slot].physical_address)+input_offset
                if input_address+n_in>(1<<32):raise RuntimeError('P1 input span exceeds 32-bit address space')
                timing['owner_prep_s']+=time.perf_counter()-t_prep
                t=time.perf_counter()
                if batch is None or number==0:self.buffers[slot].flush()
                # The CPU never touches output storage between strip transfers.
                # Flush once before the first strip, invalidate after the last.
                if not direct_rows or number==0:receive_buffer.flush()
                timing['cache_sync_s']+=time.perf_counter()-t
                expected=(before+1)&65535
                # Set active before the first physical submission; failure pins all CMA.
                self.active=True
                self.active_input_slot=slot
                d=self.dma
                t=time.perf_counter();self.sharp.prepare_tile(tile);timing['owner_sharp_prep_s']+=time.perf_counter()-t
                t=time.perf_counter();arm(self.dma_array,receive_address,input_address,n_out,n_in);timing['owner_arm_s']+=time.perf_counter()-t
                t=time.perf_counter();deadline=t+self.timeout_s;prefilled=False;stop_requested=False
                while True:
                    try:rc,snapshot=poll(self.dma_array,self.mmio.array,expected,.002,self.dma_snapshot)
                    except KeyboardInterrupt:
                        # Drain the current physical transfer before allowing a
                        # normal user stop to release CMA or change the overlay.
                        stop_requested=True;continue
                    if rc<0:raise RuntimeError('P1 DMA error '+str(snapshot))
                    if rc==1:break
                    if time.perf_counter()>=deadline:raise TimeoutError('P1 DMA/frame timeout '+str(snapshot))
                    # Completion gets checked before any next-frame CPU prefill.
                    if not stop_requested and not prefilled and number==len(job.tiles)-1 and lookahead is not None:
                        next_job=lookahead()
                        if next_job is not None and next_job.index==job.index+1:
                            spent=self.prefill(next_job,1-slot);timing['lookahead_service_s']+=spent
                            timing['lookahead_prefills']+=int(spent>0);prefilled=True
                timing['dma_wait_s']+=time.perf_counter()-t-timing['lookahead_service_s']
                t=time.perf_counter()
                if int(d.read(0x58))!=n_out:raise RuntimeError('P1 receive byte count differs from this tile')
                self.sharp.completed_tile()
                timing['owner_sharp_done_s']+=time.perf_counter()-t
                self.active=False
                self.active_input_slot=None
                t=time.perf_counter()
                if not direct_rows or number==len(job.tiles)-1:
                    receive_buffer.invalidate();timing['output_cache_batches']+=1
                timing['cache_sync_s']+=time.perf_counter()-t
                t=time.perf_counter();x0,y0,x1,y1=tile.box
                if direct_rows:
                    # This completed slot is immutable until both the P1 owner
                    # and HDMI reader release their explicit references.
                    pass
                else:
                    np.copyto(result[y0:y1,x0:x1],self.tile_buffer[:n_out].reshape(th,tw,4))
                    timing['tile_assembly_bytes']+=n_out
                timing['tile_assembly_s']+=time.perf_counter()-t
                timing['ticket']=ticket;timing['frame_count']=expected;timing['parameter_readbacks']=10*len(job.tiles)
                timing['parameter_readback_verified']=True
                if stop_requested:timing['stop_requested']=True
            if hasattr(self,'light'):self.light.completed_frame()
            timing['owner_loop_s']=time.perf_counter()-loop_begin
            timing['owner_tail_s']=time.perf_counter()-began-timing['owner_setup_s']-timing['owner_loop_s']
            #   循环内部「已计时项」之和 —— 与 owner_loop_s 的差就是没被覆盖的部分
            timing['owner_loop_accounted_s']=(timing['input_copy_s']+timing['control_s']+
                timing['cache_sync_s']+timing['dma_wait_s']+timing['tile_assembly_s']+
                timing['owner_release_s']+timing['owner_prep_s']+timing['owner_sharp_prep_s']+
                timing['owner_arm_s']+timing['owner_sharp_done_s'])
            timing.update(owner_s=time.perf_counter()-began,owner_thread_cpu_s=time.thread_time()-cpu)
            return result,timing
        except BaseException as exc:
            self.failed=True
            if self not in _RETAINED__v64_p1_backend:_RETAINED__v64_p1_backend.append(self)
            checkpoint('P1_OWNER_FAILED',durable=True,active=self.active,error=repr(exc),ticket=self.ticket,
                dma_state=[int(self.dma.read(o)) for o in (4,0x34)],frame_count=int(self.mmio.read(0x34)),buffers_retained=True)
            raise
        finally:
            #   ⭐ 诊断：归还相机 buffer 可能才是"看不见的等待" —— 计时并挂到实例上，
            #      下一帧的 timing 里会带出来（一帧延迟，统计用没问题）。
            _t_rel=time.perf_counter()
            job.release_source()
            self.last_release_s=time.perf_counter()-_t_rel
    def output_reference(self,image):
        # Only completed output may cross to HDMI; no DMA ownership transfers.
        self._assert_owner()
        if image is None:return None
        if self.active or self.completed_output is None:raise RuntimeError('Output not completed')
        return self.completed_output
    def close(self):
        global _OWNER_SESSION
        if self.closed:return
        if self.active or self.failed:
            if self not in _RETAINED__v64_p1_backend:_RETAINED__v64_p1_backend.append(self)
            raise RuntimeError('Failed/active P1 DMA: CMA and overlay retained; reboot board')
        self._assert_owner()
        # Even an idle DMA must be halted before its overlay may be replaced.
        self.dma.write(0,0);self.dma.write(0x30,0);deadline=time.perf_counter()+self.timeout_s
        while not(self.dma.read(4)&1 and self.dma.read(0x34)&1):
            if time.perf_counter()>=deadline:
                self.failed=True;_RETAINED__v64_p1_backend.append(self)
                raise TimeoutError('P1 DMA did not halt; CMA/overlay retained')
            time.sleep(.0002)
        if hasattr(self,'light'):self.light.close()
        elif hasattr(self,'light_control'):self.light_control.close()
        if hasattr(self,'sharp'):self.sharp.close()
        elif hasattr(self,'sharp_control'):self.sharp_control.close()
        if self.completed_output is not None:self.completed_output.release();self.completed_output=None
        if self.output_slots is not None:
            try:self.output_slots.close()
            except BaseException:
                self.failed=True
                if self not in _RETAINED__v64_p1_backend:_RETAINED__v64_p1_backend.append(self)
                raise
        if self.input_packer is not None:self.input_packer.close();self.input_packer=None
        for buf in self.buffers:buf.freebuffer()
        self.buffers.clear();self.packed.clear();self.closed=True
        if _OWNER_SESSION is self:_OWNER_SESSION=None


# ======================================================================
# ===== [06/13] v70_ps =====
# ======================================================================


"""CPU-only PS workspaces and lazy current-frame diagnostic materialization."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class EdgeEvidence(Mapping):
    """Immutable 168-byte native evidence snapshot; fields decoded on demand."""
    _keys=('valid','edge_support','edge_polarity','refined_corners','supported_edges',
        'median_edge_shift','edge_rms','max_edge_rms','edge_backend')
    def __init__(self,stats,max_rms):
        self.raw=stats.tobytes();self.max_rms=float(max_rms);self.values={}
    def __len__(self):return len(self._keys)
    def __iter__(self):return iter(self._keys)
    def __getitem__(self,name):
        if name in self.values:return self.values[name]
        if name=='edge_support':value=struct.unpack_from('=4d',self.raw,0)
        elif name=='edge_rms':value=struct.unpack_from('=4d',self.raw,12*8)
        elif name=='edge_polarity':value=tuple(map(int,struct.unpack_from('=4d',self.raw,4*8)))
        elif name=='valid':value=bool(struct.unpack_from('=d',self.raw,20*8)[0])
        elif name=='refined_corners':value=int(struct.unpack_from('=d',self.raw,16*8)[0])
        elif name=='supported_edges':value=int(struct.unpack_from('=d',self.raw,17*8)[0])
        elif name=='median_edge_shift':
            shifts=sorted(struct.unpack_from('=4d',self.raw,8*8));value=(shifts[1]+shifts[2])*.5
        elif name=='max_edge_rms':value=self.max_rms
        elif name=='edge_backend':value='cpp_edges_gate_motion_context'
        else:raise KeyError(name)
        self.values[name]=value;return value


def decode_light_edges(work):
    began=time.perf_counter();cpu=time.thread_time()
    np.copyto(work.result32,work.result,casting='unsafe')
    g=work.gate
    gate=dict(reliable=bool(g[0]),min_support=float(g[1]),max_rms=float(g[2]),
        prediction_correction=float(g[3]),polarity_flips=int(g[4]),radius=float(g[5]))
    evidence=EdgeEvidence(work.stats,g[2])
    result=(work.result32,evidence,gate,tuple(map(float,work.motion)) if gate['reliable'] else None)
    prior=work.decode_timing
    work.decode_timing=(prior[0]+time.perf_counter()-began,prior[1]+time.thread_time()-cpu)
    return result


def observe_yuyv_bound(work,image,scratch,rows,out,drift,radius,mode,library):
    """Reuse pointers to private, already-validated workspaces only.

    The caller retains all original layout/alias checks. The leased camera
    pointer is obtained afresh on every call and is never retained here.
    """
    cache=getattr(work,'_light_bindings',None)
    if cache is None:cache={};work._light_bindings=cache
    key=(id(library),id(scratch),id(rows),id(out),id(drift))
    binding=cache.get(key)
    if binding is None:
        if len(cache)>=6:cache.clear()
        references=(scratch,rows,out,work.predicted,work.previous,work.anchor,drift,work.polarity,
            work.result,work.stats,work.motion,work.gate,work.times)
        pointers=tuple(a.ctypes.data for a in references)
        binding=(library,library.p11_yuyv_observe_edges,references,pointers[:8],pointers[8:])
        cache[key]=binding
    return binding[1](image.ctypes.data,image.shape[1],image.shape[0],image.strides[0],int(mode),
        *binding[3],float(radius),*binding[4])


def materialize_tracking(track):
    """Called immediately by the same PS prepare, before the next update."""
    factory=track.pop('_diagnostics',None)
    def owned(value):
        if isinstance(value,Mapping):return {k:owned(v) for k,v in value.items()}
        if isinstance(value,list):return [owned(v) for v in value]
        if isinstance(value,tuple):return tuple(owned(v) for v in value)
        if isinstance(value,np.ndarray):
            result=value.copy();result.flags.writeable=False;return result
        return value
    return owned(factory() if factory is not None else track)


def evidence_snapshot(evidence):
    """A native immutable evidence snapshot already owns its bytes."""
    return evidence if isinstance(evidence,EdgeEvidence) else dict(evidence)


def _destroy_plan(library,pointer):library.p11_v70_plan_destroy(pointer)


class PlanBatchWorkspace:
    """One sequential PS producer; no frame pixels, MMIO or device handles."""
    def __init__(self,capacity=32):
        self.capacity=int(capacity)
        if not 1<=self.capacity<=32:raise ValueError('P1 batch capacity1..32')
        self.quad=np.empty((4,2),np.float32);self.boxes=np.empty((self.capacity,4),np.int32)
        self.h=np.empty((3,3),np.float64);self.mapping=np.empty((self.capacity,12),np.int32)
        self.packet=np.empty((self.capacity,10),np.uint32);self.proof=np.empty((self.capacity,12),np.int32)
        self.times=np.empty(16+4*self.capacity,np.float64)
        self.lock=threading.Lock();self.library=None;self.context=None;self.finalizer=None;self.available=None
        self.last_cache=dict(entries=0,hits=0,misses=0,calls=0,capacity=128)
        self.last_status=dict(available=False,reason='not_requested')
    def _context(self):
        lib=prepare_io()
        if self.library is not lib:
            if self.finalizer is not None:self.finalizer()
            self.context=None;self.finalizer=None;self.library=lib
            self.available=bool(lib.p11_v70_geometry_available())
        if not self.available:
            self.last_status=dict(available=False,reason='matching_opencv_development_package_unavailable');return None
        if self.context is None:
            pointer=lib.p11_v70_plan_create()
            if not pointer:raise MemoryError('P1 CPU plan context allocation failed')
            self.context=pointer;self.finalizer=weakref.finalize(self,_destroy_plan,lib,pointer)
        return lib
    def run(self,q,input_size,size,boxes,budget):
        if not self.lock.acquire(False):raise RuntimeError('P1 CPU plan workspace already active')
        try:
            lib=self._context()
            if lib is None:return None
            if not 1<=len(boxes)<=self.capacity:raise ValueError('P1 batch box count invalid')
            q=np.asarray(q,np.float32)
            if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('P1 batch current quad invalid')
            self.quad[:]=q;self.boxes[:len(boxes)]=boxes
            began=time.perf_counter();cpu=time.thread_time()
            code=lib.p11_v70_plan_batch(self.context,self.quad.ctypes.data,int(input_size[0]),int(input_size[1]),
                int(size[0]),int(size[1]),self.boxes.ctypes.data,len(boxes),self.capacity,float(budget),
                self.h.ctypes.data,self.mapping.ctypes.data,self.packet.ctypes.data,self.proof.ctypes.data,self.times.ctypes.data)
            elapsed=time.perf_counter()-began;used=time.thread_time()-cpu
            if code:
                self.last_status=dict(available=True,code=int(code),reason='native_geometry_rejected',wall_s=elapsed,thread_cpu_s=used)
                # Invalid geometry is rejected by the existing legacy path too;
                # it does not authorize any old packet or incomplete receipt.
                return None
            t=self.times
            self.last_cache=dict(entries=int(t[10]),hits=int(t[12]),misses=int(t[13]),calls=int(t[14]),capacity=128)
            self.last_status=dict(available=True,code=0,wall_s=elapsed,thread_cpu_s=used,
                native_wall_s=float(t[6]),native_thread_cpu_s=float(t[7]),
                h_s=float(t[0]),h_thread_cpu_s=float(t[1]),mapping_s=float(t[2]),mapping_thread_cpu_s=float(t[3]),
                proof_s=float(t[4]),proof_thread_cpu_s=float(t[5]),
                proof_cache_hits=int(t[8]),proof_cache_misses=int(t[9]),native_calls=1)
            return self.h,self.mapping[:len(boxes)],self.packet[:len(boxes)],self.proof[:len(boxes)],dict(self.last_status)
        finally:self.lock.release()
    def close(self):
        if not self.lock.acquire(False):raise RuntimeError('P1 CPU plan active; retain context until producer stops')
        try:
            if self.finalizer is not None:self.finalizer()
            self.context=None;self.finalizer=None;self.library=None;self.available=None
        finally:self.lock.release()


# ======================================================================
# ===== [07/13] v73_ratio =====
# ======================================================================


"""Event-activated output geometry; the untouched default orientation stays native."""
from core import RELEASE_ID as RELEASE_ID
from geometry import DualOrientation as OriginalOrientation
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

SHIFT=1<<20
PRESETS=('original','1:1','3:4','4:3','16:9')
_CONTEXT=ContextVar('p11_v73_ratio_profile',default=None)
_BINDINGS={}
class RatioPlanRejected(RuntimeError):pass

def normalize(value):
    if value=='original':return value
    try:
        first,second=str(value).split(':');w=float(first);h=float(second)
    except (TypeError,ValueError):raise ValueError('invalid_ratio')
    if not all(math.isfinite(v) and .1<=v<=9999 for v in (w,h)) or not .5<=w/h<=2:
        raise ValueError('ratio_range')
    return '%g:%g'%(w,h)

def dimensions(value):
    value=normalize(value)
    fixed={'1:1':(430,430),'3:4':(372,496),'4:3':(496,372),'16:9':(560,315)}
    if value=='original':return None
    if value in fixed:return fixed[value]
    w,h=map(float,value.split(':'));ratio=w/h
    height=min(512.,math.sqrt(185344./ratio))
    return int(height*ratio)//2*2,int(height)//2*2

class RatioRegistry:
    def __init__(self):
        self.lock=threading.RLock();self.serial=0;self.entries=[]
        self.desired={'auto':('original',0),'manual':('original',0)}
        self.applied=dict(self.desired)
        self.sizes={'auto':None,'manual':None}
        self.fronts={};self.pending_modes={'auto':False,'manual':False};self.on_reject=None
    @contextmanager
    def scope(self,mode):
        if mode not in self.desired:raise ValueError('Unknown ratio profile')
        with self.lock:
            for item,_ in self.entries:_BINDINGS.pop(item,None)
            self.entries=[]
        token=_CONTEXT.set((self,mode))
        try:yield
        finally:
            _CONTEXT.reset(token)
            with self.lock:
                for mode in self.desired:self._retire_fronts(mode)
                for item,_ in self.entries:_BINDINGS.pop(item,None)
                self.entries=[];self.fronts={}
    def register(self,item,mode):
        with self.lock:
            self.entries.append((item,mode))
            if len(self.entries)>64:del self.entries[:-64]
            if self.desired[mode][0]!='original':self._activate(item,mode)
        return item
    def _activate(self,item,mode):
        _BINDINGS[item]=(self,mode)
        item.__class__=RatioOrientation
    def attach_manual_frontend(self,front,mode):
        with self.lock:
            self.fronts[front.orientation]=dict(front=front,mode=mode,prepare=front.prepare,plan=front.plan,
                had_prepare='prepare' in front.__dict__,had_plan='plan' in front.__dict__)
            if self.pending_modes[mode]:self._install_front(self.fronts[front.orientation])
    def _install_front(self,entry):
        if 'wrapped_prepare' in entry:return
        front=entry['front'];mode=entry['mode'];base_prepare=entry['prepare'];base_plan=entry['plan']
        def plan(q,shape,size):
            try:return base_plan(q,shape,size)
            except ValueError as exc:
                with self.lock:
                    value,revision=self.desired[mode];enabled=self.pending_modes[mode];target=self.sizes[mode]
                matching=tuple(size)==target if target is not None else tuple(size) in (tuple(front.size),tuple(front.size)[::-1])
                if not enabled or not matching:raise
                if self.on_reject is not None:self.on_reject(mode,revision,str(exc))
                else:self.rollback(mode)
                raise RatioPlanRejected(str(exc)) from exc
        def prepare(index):
            try:return base_prepare(index)
            except RatioPlanRejected:
                # ManualTracker advances by source sequence/time, not job index.
                # The original outer exception path already released the rejected
                # lease. Retry once using the restored destination on a new frame.
                return base_prepare(index)
        entry.update(wrapped_prepare=prepare,wrapped_plan=plan);front.prepare=prepare;front.plan=plan
    def _retire_fronts(self,mode):
        for entry in self.fronts.values():
            if entry['mode']!=mode or 'wrapped_prepare' not in entry:continue
            front=entry['front']
            for name in ('prepare','plan'):
                if getattr(front,name)==entry['wrapped_'+name]:
                    if entry['had_'+name]:setattr(front,name,entry[name])
                    else:front.__dict__.pop(name,None)
                entry.pop('wrapped_'+name,None)
    def request(self,mode,value):
        value=normalize(value)
        with self.lock:
            self.serial+=1;self.desired[mode]=(value,self.serial)
            self.pending_modes[mode]=True
            self.sizes[mode]=dimensions(value)
            for item,profile in self.entries:
                if profile==mode:self._activate(item,mode)
            for entry in self.fronts.values():
                if entry['mode']==mode:self._install_front(entry)
            return self.serial
    def finish(self,mode,revision):
        with self.lock:
            if self.desired[mode][1]!=revision:return False
            self.applied[mode]=self.desired[mode]
            self.pending_modes[mode]=False;self._retire_fronts(mode)
            if self.applied[mode][0]=='original':self._restore(mode)
            return True
    def rollback(self,mode):
        with self.lock:
            self.desired[mode]=self.applied[mode]
            self.pending_modes[mode]=False;self._retire_fronts(mode)
            self.sizes[mode]=dimensions(self.desired[mode][0])
            if self.desired[mode][0]=='original':self._restore(mode)
    def _restore(self,mode):
        for item,profile in self.entries:
            if profile==mode:
                item.__class__=OriginalOrientation
                _BINDINGS.pop(item,None)

class RatioOrientation(OriginalOrientation):
    __slots__=()
    def propose(self,*args,**kwargs):
        # A touch may restore the original class while an old bound call runs.
        binding=_BINDINGS.get(self)
        if binding is None:return OriginalOrientation.propose(self,*args,**kwargs)
        registry,mode=binding
        with registry.lock:
            value,revision=registry.desired[mode];size=registry.sizes[mode]
        proposal=OriginalOrientation.propose(self,*args,**kwargs)
        size=size or proposal.size
        return replace(proposal,size=size,detail=dict(proposal.detail,
            output_size=list(size) if size is not None else None,
            output_ratio=value,output_ratio_revision=revision if value!='original' else 0,output_ratio_profile=mode))
    def commit(self,proposal):
        result=OriginalOrientation.commit(self,proposal)
        revision=proposal.detail.get('output_ratio_revision')
        if revision is not None:
            generation=int(result.get('layout_generation',0))
            if not 0<=generation<SHIFT:raise ValueError('orientation_generation_overflow')
            result['layout_generation']=int(revision)*SHIFT+generation
        return result

def make_orientation(*args,**kwargs):
    item=OriginalOrientation(*args,**kwargs);binding=_CONTEXT.get()
    return item if binding is None else binding[0].register(item,binding[1])

def register_manual_frontend(front):
    binding=_CONTEXT.get()
    if binding is not None:binding[0].attach_manual_frontend(front,binding[1])

def revision_of(meta):return int(meta.get('layout_generation',0))//SHIFT


# ======================================================================
# ===== [08/13] v64_camera_hdmi =====
# ======================================================================


"""V74 automatic edges/conditional complete FB, immutable P1 and asynchronous HDMI."""
from core import RELEASE_ID as RELEASE_ID; from core import verify_package as verify_package
from tracking import LiveAcquire as LiveAcquire; from tracking import pump_acquisition as pump_acquisition
from tracking import NativeSetup as NativeSetup; from tracking import wait_native_with_preview as wait_native_with_preview; from tracking import wait_for_placement as wait_for_placement
from core import set_color_mode as set_color_mode
from tracking import detect_refined as detect_refined
from tracking import PaperTracker__v87_v74_tracking as PaperTracker; from tracking import skip_dead_research as skip_dead_research
from tracking import prepare_native__v31_native as prepare_native
from core import GcBudget as GcBudget
from ui import UIReturnRequested as UIReturnRequested
from core import logged_run as logged_run; from core import checkpoint as checkpoint; from core import frame_record as frame_record; from core import frame_log_scope as frame_log_scope
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v64_camera_hdmi=[]
_POISONED=False
_POISON_REASON=[]

@dataclass
class FrameJob:
    index:int
    lease:object
    tiles:tuple
    size:tuple
    state:str
    corners:tuple
    color_mode:int
    source_snapshot:object
    record:dict
    source_owned:bool=False
    def claim_source(self,owner):
        claim=getattr(self.lease,'claim',None)
        if claim is not None:
            claim(owner,self.index)
            self.record.update(source_buffer_index=self.lease.index,source_generation=self.lease.generation,source_last_owner=owner)
    def release_source(self):
        if self.lease is not None:self.lease.release()

class Frontend:
    """One chronological CPU worker; current four-corner proof renews TTL."""
    def __init__(self,camera,first,detection,size,tracking_limit,detection_limit,hold_s,
                 lk_min_gap,lk_max_gap,orientation_mode='auto_two',reacquire_budget_ms=420.,
                 plan_strategy='fast_safe',proof_cpu_budget_ms=12.):
        self.camera=camera;self.size=tuple(size);self.hold_s=hold_s
        self.raw_required=None
        self.orientation=make_orientation(orientation_mode,size,2);self.last_verified=None
        self.proof_cache=ProofCache(128);self.plan_strategy=plan_strategy
        self.plan_workspace=PlanWorkspace();self.plan_states={}
        self.proof_cpu_budget_s=float(proof_cpu_budget_ms)/1000.
        self.last_detail_at=0.;self.last_detail_signature=None
        self.tracker=PaperTracker(interval=3,limit=tracking_limit,detection_limit=detection_limit,
            feature_policy='quality',tracking_checks='auto',tracking_policy='motion_adaptive',
            lk_min_gap=lk_min_gap,lk_max_gap=lk_max_gap)
        self.tracker.light_results=True
        self.tracker.observer.transaction.light_results=True
        self.tracker.edge_workspace.light_results=True
        try:
            self.tracker.continuity_hold=True
            self.tracker.configure_recovery(120.,2,4,float(reacquire_budget_ms),4)
            self.tracker.configure_async_recovery(True,.90)
            self.tracker.initialize(first.image,detection[0],index=0,initial_detection=detection[1])
            self.last_sequence=int(first.sequence);self.last_ready=float(first.ready)
            self.anchor_sequence=int(first.sequence);self.anchor_index=self.tracker.anchor_index
            self.last_camera_counters=self._capture_counters()
            # Each job owns one immutable ordinary-RAM source. The two-slot
            # display may retain it after camera/CMA release without recopying.
            # No mutable rotating source slot is lent to the display thread.
            proposal=self.orientation.propose(self.tracker.corners(),first.image.shape,0,timestamp=float(first.ready))
            q=proposal.quad;actual=tuple(proposal.size or self.size);tiles,plan=self.plan(q,first.image.shape,actual)
            orient=self.orientation.commit(proposal)
            self.last_verified=dict(tiles=tiles,size=actual,corners=tuple(map(tuple,q.tolist())),verified_at=float(first.ready),
                layout_generation=orient.get('layout_generation',0),orientation=orient.get('orientation'),
                switch_requested_at=None,switch_decided_at=None)
            self.initial=dict(corners=self.last_verified['corners'],orientation=orient,plan=plan,
                sequence=int(first.sequence),physical_verified_at=float(first.ready))
        except BaseException:
            self.close();raise
    def plan(self,q,shape,size):
        signature=(tuple(shape[:2]),tuple(size),self.plan_strategy)
        entry=self.plan_states.get(signature)
        if entry is None:
            entry=dict(boxes=None,last_q=None,probe_at=0.,cursor=0,key=None,cached=None)
            from tracking import MergeProbeBackoff as MergeProbeBackoff
            entry['merge_backoff']=MergeProbeBackoff()
            self.plan_states[signature]=entry
            if len(self.plan_states)>2:self.plan_states.pop(next(iter(self.plan_states)))
        key=np.asarray(q,np.float32).tobytes()
        if key==entry['key']:
            return entry['cached'][0],dict(entry['cached'][1],plan_cached=True,proof_s=0.,proof_thread_cpu_s=0.,
                proof_coordinate_samples=0,interval_blocks=0,proof_cache_hits=0,proof_attempts=0,proof_budget_splits=0,
                mapping_native_s=0.,mapping_native_thread_cpu_s=0.,merge_probe_attempts=0,merge_probe_accepted=0,
                native_geometry_s=0.,native_geometry_thread_cpu_s=0.,native_geometry_calls=0,
                native_geometry_used=False,native_geometry_fallback=None,native_plan_cached=True,
                h_native_s=0.,h_native_thread_cpu_s=0.,geometry_result_decode_s=0.,geometry_result_decode_thread_cpu_s=0.)
        now=time.perf_counter()
        stable=entry['last_q'] is not None and float(np.max(np.linalg.norm(np.asarray(q)-entry['last_q'],axis=1)))<=3.
        probe=entry['merge_backoff'].ready(now,q,entry['boxes'],stable)
        if probe:entry['probe_at']=now
        tiles,detail=make_plan(q,shape,size,proof_cache=self.proof_cache,strategy=self.plan_strategy,
            proof_cpu_budget_s=self.proof_cpu_budget_s,partition_boxes=entry['boxes'],
            merge_probe=probe,merge_cursor=entry['cursor'],workspace=self.plan_workspace)
        if detail.get('merge_probe_attempts'):entry['cursor']+=1
        entry['merge_backoff'].observe(time.perf_counter(),q,tuple(tile.box for tile in tiles),probe,detail)
        detail.update(entry['merge_backoff'].summary())
        entry.update(boxes=tuple(tile.box for tile in tiles),last_q=np.asarray(q,np.float32).copy(),key=key,cached=(tiles,detail))
        return tiles,dict(detail,plan_cached=False,layout_partition_entries=len(self.plan_states))
    def _capture_counters(self):
        # No MMAP pointer escapes; these counters belong to the capture thread.
        with self.camera.condition:
            if self.camera.error is not None:raise RuntimeError('Camera capture worker failed') from self.camera.error
            return (self.camera.captured,self.camera.dropped,self.camera.invalid,self.camera.sequence_gaps)
    def prepare(self,index):
        capture_begin=time.perf_counter();lease=self.camera.take(3.)
        began=time.perf_counter();cpu=time.thread_time()
        try:
            self.tracker.source_step=max(1,(int(lease.sequence)-self.last_sequence)&0xffffffff)
            self.tracker.source_elapsed_s=max(1e-6,float(lease.ready)-self.last_ready)
            counters=self._capture_counters()
            deltas=tuple(max(0,a-b) for a,b in zip(counters,self.last_camera_counters))
            self.last_camera_counters=counters
            frame_age=max(0.,began-float(lease.ready));gap=self.tracker.source_elapsed_s
            # A selected-frame gap is not a USB outage. Continued capture and
            # observed latest-slot drops identify processing skips, not a guess
            # from sequence alone. Stale, invalid, missing or very old inputs
            # keep the strict reanchor route; hard capture-age LK remains.
            processing_skips=bool(self.tracker.source_step>=3 and deltas[0]>=3 and deltas[1]>=1
                and deltas[2]==0 and deltas[3]==0 and frame_age<=.20 and gap<=.75)
            self.tracker.source_processing_gap=processing_skips
            self.tracker.source_force_reacquire=bool(frame_age>.20 or gap>.75 or(gap>.35 and not processing_skips))
            gap_kind=('processing_latest_skips' if processing_skips else
                'capture_or_stale_gap' if self.tracker.source_force_reacquire else 'normal_selected_interval')
            captured_age=(int(lease.sequence)-self.anchor_sequence)&0xffffffff
            processed_age=max(0,index-self.tracker.anchor_index)
            self.tracker.source_age_extra=max(0,captured_age-processed_age)
            self.tracker.source_ready_at=float(lease.ready);self.tracker.source_sequence=int(lease.sequence)
            self.last_sequence=int(lease.sequence);self.last_ready=float(lease.ready)
            tracker_begin=time.perf_counter();track=self.tracker.update(lease.image,index)
            if self.tracker.anchor_index!=self.anchor_index:
                self.anchor_index=self.tracker.anchor_index;self.anchor_sequence=int(lease.sequence)
            tracker_s=time.perf_counter()-tracker_begin;plan_s=0.;plan={};failure=None;orientation_s=0.;orientation_cpu_s=0.
            if track.get('valid',False):
                q=np.asarray(track['corners'],np.float32)
                to=time.perf_counter();co=time.thread_time()
                lk=track.get('lk_timing') or {};proof=track.get('current_source_proof') or {}
                full_current=bool(proof.get('verified') and
                    (track.get('mode')=='lk_measured' and 'forward_backward_flow_s' in lk
                     or track.get('mode') in ('full_redetect','current_edge_reacquire')))
                proposal=self.orientation.propose(q,lease.image.shape,index,
                    new_target=bool(track.get('target_changed',False)),confidence=float(track.get('confidence',0.)),
                    timestamp=float(lease.ready),strong_verified=full_current)
                q=proposal.quad;orient=proposal.detail
                if track.get('target_changed',False):self.plan_states.clear()
                actual=tuple(proposal.size or self.size);t=time.perf_counter()
                orientation_s=t-to;orientation_cpu_s=time.thread_time()-co
                try:tiles,plan=self.plan(q,lease.image.shape,actual)
                except ValueError as exc:failure=str(exc)
                else:
                    tc=time.perf_counter();cc=time.thread_time()
                    orient=self.orientation.commit(proposal)
                    if self.last_verified and self.last_verified.get('layout_generation')==orient.get('layout_generation'):
                        orient=dict(orient,switch_requested_at=self.last_verified.get('switch_requested_at'),switch_decided_at=self.last_verified.get('switch_decided_at'))
                    self.last_verified=dict(tiles=tiles,size=actual,corners=tuple(map(tuple,q.tolist())),verified_at=float(lease.ready),
                        layout_generation=orient.get('layout_generation',0),orientation=orient.get('orientation'),
                        switch_requested_at=orient.get('switch_requested_at'),switch_decided_at=orient.get('switch_decided_at'))
                    orientation_s+=time.perf_counter()-tc;orientation_cpu_s+=time.thread_time()-cc
                plan_s=time.perf_counter()-t
            else:
                self.orientation.lost(float(lease.ready));orient={}
            current=bool(track.get('valid',False) and failure is None)
            previous=self.last_verified;age=max(0.,time.perf_counter()-previous['verified_at']) if previous else float('inf')
            state='CURRENT' if current else 'HELD' if previous and age<=self.hold_s else 'LOST'
            used=previous if state!='LOST' else dict(tiles=(),size=previous['size'] if previous else self.size,corners=(),verified_at=0.,
                layout_generation=previous.get('layout_generation',0) if previous else 0,orientation=previous.get('orientation') if previous else None)
            snapshot_begin=time.perf_counter()
            raw_required=state=='LOST' or self.raw_required is None or self.raw_required()
            from ui import source_snapshot as owned_snapshot
            source_snapshot=owned_snapshot(self.camera,lease) if raw_required else None
            if source_snapshot is not None:source_snapshot.flags.writeable=False
            snapshot_s=time.perf_counter()-snapshot_begin
            metadata_begin=time.perf_counter();metadata_cpu=time.thread_time()
            record=dict(index=index,camera_sequence=int(lease.sequence),capture_ready_at=float(lease.ready),
                camera_timestamp=float(lease.timestamp),verified_at=float(used['verified_at']),state=state,
                color_mode=int(self.camera.color_mode),source_snapshot_s=snapshot_s,
                source_capture_gap_s=float(self.tracker.source_elapsed_s),source_step=int(self.tracker.source_step),
                source_gap_reacquire=bool(self.tracker.source_force_reacquire),captured_anchor_age=int(captured_age),
                source_gap_kind=gap_kind,source_processing_skips=processing_skips,source_age_at_prepare_s=frame_age,
                capture_observed_delta=deltas[0],latest_drop_delta=deltas[1],invalid_capture_delta=deltas[2],driver_sequence_gap_delta=deltas[3],
                capture_wait_s=began-capture_begin,ps_prepare_s=time.perf_counter()-began,ps_prepared_at=time.perf_counter(),
                ps_thread_cpu_s=time.thread_time()-cpu,tracker_s=tracker_s,plan_update_s=plan_s,
                corners=used['corners'],output_size=used['size'],tiles=len(used['tiles']),held_age_s=age,
                confidence=float(track.get('confidence',0.)),mode=track.get('mode'),plan_failure=failure,
                layout_generation=used.get('layout_generation',0),orientation=used.get('orientation'),
                direction_proposed=orient.get('pending_orientation'),direction_decision=orient.get('decision'),
                direction_angle_degrees=orient.get('long_axis_angle_degrees'),direction_confirmations=orient.get('confirmation_count'),
                direction_committed=bool(current and orient.get('orientation_committed')),
                direction_switch=bool(current and (orient.get('changed') or orient.get('mapping_reoriented'))),
                switch_requested_at=used.get('switch_requested_at'),switch_decided_at=used.get('switch_decided_at'))
            source_proof=track.get('current_source_proof',{})
            stability=getattr(self.tracker,'stability_detail',{})
            photo=getattr(self.tracker.photometric,'detail',{})
            controls=self.camera.control_detail
            lk=track.get('lk_timing',{});edge=track.get('edge_gate',{})
            fastpath=track.get('v49_fastpath',{})
            quick=track.get('quick_current_candidate',{})
            proof_workspace=track.get('current_proof_workspace',{})
            record.update(proof_s=plan.get('proof_s',0.),proof_thread_cpu_s=plan.get('proof_thread_cpu_s',0.),
                proof_coordinate_samples=plan.get('proof_coordinate_samples',0),interval_blocks=plan.get('interval_blocks',0),
                proof_attempts=plan.get('proof_attempts',0),proof_cache_hits=plan.get('proof_cache_hits',0),
                proof_budget_splits=plan.get('proof_budget_splits',0),plan_cached=bool(plan.get('plan_cached',False)),
                plan_strategy=self.plan_strategy,proof_methods=plan.get('proof_methods',()),
                partition_reused=bool(plan.get('partition_reused',False)),
                merge_probe_attempts=plan.get('merge_probe_attempts',0),merge_probe_accepted=plan.get('merge_probe_accepted',0),
                mapping_native_s=plan.get('mapping_native_s',0.),mapping_native_thread_cpu_s=plan.get('mapping_native_thread_cpu_s',0.),
                track_reason=track.get('reason'),lk_trigger=track.get('lk_trigger'),
                # ⭐ 2026-10-18 合并 V1.1 优化：把开关状态写进每一帧
                skip_research=bool(skip_dead_research()),
                edge_rescue=track.get('edge_rescue'),   # 重搜前后 gate 指标（A/B 用）
                static_hold=track.get('static_hold'),   # ⭐ 静态保持：motion/held_s/frames
                hold_motion=getattr(self.tracker,'_hold_motion',None),   # 每帧帧差（诊断为什么没保持）
                hold_changed=getattr(self.tracker,'_hold_changed',None),
                hold_smooth=getattr(self.tracker,'_hold_smooth',None),
                hold_floor=getattr(self.tracker,'_hold_floor_m',None),
                hold_count=getattr(self.tracker,'_hold_count',None),
                hold_active=bool(getattr(self.tracker,'_hold_active',False)),
                feature_count=track.get('feature_count'),min_edge_support=edge.get('min_support'),max_edge_rms=edge.get('max_rms'),
                stable_FB_context=lk.get('stable_FB_context'),current_source_proof_verified=source_proof.get('verified'),
                current_source_proof_reason=source_proof.get('reason'),
                current_source_support=source_proof.get('min_support'),current_source_rms=source_proof.get('max_rms'),
                current_source_normal_difference=source_proof.get('line_normal_difference'),
                luma_mean=photo.get('luma_mean'),luma_delta=photo.get('luma_delta'),
                luma_clipped_fraction=photo.get('clipped_fraction'),photometric_residual=photo.get('photometric_residual'),
                illumination_change=bool(photo.get('illumination_change')),
                illumination_local_reproof=bool(photo.get('current_independent_reproof_passed')),
                illumination_probe_s=photo.get('probe_s',0.),
                camera_exposure_absolute=controls.get('exposure_absolute'),camera_gain=controls.get('gain'),
                camera_exposure_auto_priority=controls.get('exposure_auto_priority'),camera_controls_queried_at=controls.get('queried_at'),
                paired_current_proof=bool(source_proof.get('current_proof_timing',{}).get('paired_native_transaction')),
                physical_layer_suspect=bool(stability.get('physical_layer_suspect')),
                corner_filter_applied=bool(stability.get('filtered')),corner_filter_shift=stability.get('filter_shift',0.),
                edge_stability_s=stability.get('wall_s',0.),edge_stability_thread_cpu_s=stability.get('thread_cpu_s',0.),
                local_edge_lock_attempted=bool(stability.get('local_lock_attempted')),
                local_edge_lock_verified=bool(stability.get('local_lock_verified')),
                local_edge_lock_s=stability.get('local_lock_wall_s',0.),local_edge_lock_thread_cpu_s=stability.get('local_lock_thread_cpu_s',0.),
                calm_FB_burst_exit=bool(lk.get('calm_burst_exit',{}).get('verified')),
                localization_baseline='V74_complete_automatic',
                automatic_path='V74_current_edges_conditional_complete_FB',
                complete_FB=bool('forward_backward_flow_s' in lk),
                source_snapshot_owned=source_snapshot is not None,source_snapshot_skipped=source_snapshot is None,
                lk_transaction_geometry=getattr(self.tracker,'_v90_geometry_stats',None),
                postlk_native_transaction=dict(self.tracker.post_lk.detail) if track.get('mode')=='lk_measured' else None,
                merge_probe_failure_streak=plan.get('merge_probe_failure_streak'),
                merge_probe_retry_s=plan.get('merge_probe_retry_s'),
                v49_fastpath_route=fastpath.get('route'),same_frame_receipt_reused=bool(fastpath.get('same_frame_receipt_reused')),
                current_proof_reuse_hits=int(proof_workspace.get('hits',0)),
                current_proof_store_count=int(proof_workspace.get('stored',0)),
                quick_current_candidate_attempted=bool(quick.get('attempted')),
                quick_current_candidate_verified=bool(quick.get('verified')),
                quick_current_candidate_s=quick.get('wall_s',0.),
                quick_current_candidate_thread_cpu_s=quick.get('thread_cpu_s',0.),
                quick_current_candidate_reason=quick.get('reason'),
                ps_light_results=bool(self.tracker.light_results),
                observation_wrapper_s=track.get('gray_s',0.),
                observation_native_s=self.tracker.observer.detail.get('native_transaction_s',0.) if track.get('gray_s',0.)>0 else 0.,
                result_decode_s=sum(w.decode_timing[0] for w in (self.tracker.observer.transaction,self.tracker.edge_workspace)),
                result_decode_thread_cpu_s=sum(w.decode_timing[1] for w in (self.tracker.observer.transaction,self.tracker.edge_workspace)),
                source_corners_s=track.get('source_corners_s',0.),post_observation_s=track.get('post_observation_s',0.),
                # ⭐ 2026-10-28 计时：把 tracker_s 拆成 静止门控/观测前/LK/帧尾 四段。
                pre_obs_s=track.get('pre_obs_s',0.),static_hold_s=track.get('static_hold_s',0.),
                lk_s=track.get('lk_s',0.),post_lk_tail_s=track.get('tail_s',0.),
                # ⭐ 2026-10-28：锚点重取点的总耗时，与其中【搜索】部分；外加生效的间隔。
                feature_s=track.get('feature_s',0.),feature_roi_s=track.get('feature_roi_s',0.),
                roi_search_gap=int(track.get('roi_search_gap',0) or 0),
                orientation_prepare_s=orientation_s,orientation_thread_cpu_s=orientation_cpu_s,
                native_geometry_used=bool(plan.get('native_geometry_used',False)),
                native_geometry_fallback=plan.get('native_geometry_fallback'),
                native_geometry_calls=int(plan.get('native_geometry_calls',0)),
                native_geometry_s=plan.get('native_geometry_s',0.),native_geometry_thread_cpu_s=plan.get('native_geometry_thread_cpu_s',0.),
                h_native_s=plan.get('h_native_s',0.),h_native_thread_cpu_s=plan.get('h_native_thread_cpu_s',0.),
                geometry_result_decode_s=plan.get('geometry_result_decode_s',0.),
                geometry_result_decode_thread_cpu_s=plan.get('geometry_result_decode_thread_cpu_s',0.))
            # Keep every timing/quad/state. A recurring slow/recovery condition
            # does not serialize the same large proof tree on every frame.
            now=time.perf_counter();signature=(state,track.get('mode'),track.get('reason'))
            changed=signature!=self.last_detail_signature
            detailed=index==1 or index%60==0 or((changed or tracker_s>.12) and now-self.last_detail_at>=2.)
            record['diagnostic_detail']=bool(detailed)
            if detailed:
                record.update(tracker_detail=materialize_tracking(track),plan_detail=plan,orientation_detail=orient)
                self.last_detail_at=now;self.last_detail_signature=signature
            # Include the per-frame summary/detail selection in preparation,
            # not as an unreported gap before publishing the ready job.
            record['metadata_build_s']=time.perf_counter()-metadata_begin
            record['metadata_thread_cpu_s']=time.thread_time()-metadata_cpu
            record['ps_prepare_s']=time.perf_counter()-began
            record['ps_thread_cpu_s']=time.thread_time()-cpu
            record['ps_prepared_at']=time.perf_counter()
            seal=time.perf_counter()
            job=FrameJob(index,lease,used['tiles'],used['size'],state,used['corners'],self.camera.color_mode,source_snapshot,record,source_owned=source_snapshot is not None)
            record['job_seal_s']=time.perf_counter()-seal
            record['ps_prepare_total_s']=time.perf_counter()-began
            record['ps_prepare_total_thread_cpu_s']=time.thread_time()-cpu
            return job
        except BaseException:lease.release();raise
    def close(self):
        # Stop recovery before releasing LK/workspaces read by that CPU worker.
        worker=getattr(self.tracker,'recovery_worker',None)
        if worker is not None:worker.close()
        self.tracker.lk_cache.close()
        for name in ('edge_workspace','workspace'):
            obj=getattr(self.tracker,name,None)
            if obj is not None and hasattr(obj,'close'):obj.close()
        transaction=getattr(self.tracker.observer,'transaction',None)
        if transaction is not None and hasattr(transaction,'close'):transaction.close()
        self.plan_workspace.close()

def _bind_cpu__v64_camera_hdmi(name):
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


class PrepareQueue:
    """At most one queued job. Stop always disposes captured frame leases."""
    def __init__(self,frontend,count,warmup):
        self.frontend=frontend;self.count=count;self.allowed=warmup;self.taken=0
        #   ⭐ 2026-10-31：预取深度。原来的单槽（depth=1）让 PS 只能在 owner `take(N)`
        #      之后才开始准备 N+1，而预取点在第 N 帧 DMA 等待的开头（约 10ms 进帧），
        #      PS 需要 23.5ms ⇒ 预取命中率只有 14%，input_copy 5.34ms 一直压在关键路径上。
        #      depth=2 让 PS 能提前两帧，预取点在 N 帧时 N+1 早已就绪。
        #      P11_PREPARE_AHEAD=1 可退回原行为。相机有 6 个 V4L2 buffer，同时最多持 3 个 lease。
        #   ⚠️ 2026-10-31 实测：depth=2 确实把 input_copy 5.34→1.54ms、service 36.7→33.7ms，
        #      但 ps_prepare 墙钟从 23.6 涨到 29.7ms，和显示线程抢同一个 GIL ⇒
        #      并排(PAIRED) compose 39.4→45.2ms、显示 17→15fps。用户看到的是并排，净效果更差。
        #      所以**默认回 1**；开关保留，等显示侧不再是瓶颈再启用。
        try:self.depth=max(1,min(3,int(os.environ.get('P11_PREPARE_AHEAD','1'))))
        except ValueError:self.depth=1
        self.slots=[]                       # 已准备待取走，按 index 升序
        self.stop=False;self.error=None;self.finished=False;self.condition=threading.Condition();self.handoff=None
        self.context=copy_context();self.credit_wait_s=0.;self.publish_wait_s=0.
        self.worker=threading.Thread(target=self._entry,name='ps_prepare',daemon=True);self.worker.start()
    def _entry(self):
        _bind_cpu__v64_camera_hdmi('ps_prepare')
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.finished=True;self.condition.notify_all()
    def _run(self):
        for index in range(1,self.count+1):
            with self.condition:
                begin=time.perf_counter()
                while not self.stop and (index>self.allowed or index>self.taken+self.depth):self.condition.wait()
                self.credit_wait_s+=time.perf_counter()-begin
                if self.stop:break
            item=self.frontend.prepare(index)
            with self.condition:
                begin=time.perf_counter()
                while not self.stop and len(self.slots)>=self.depth:self.condition.wait()
                self.publish_wait_s+=time.perf_counter()-begin
                if self.stop:item.release_source();break
                item.claim_source('prepared_queue');self.slots.append(item);self.condition.notify_all()
        with self.condition:self.finished=True;self.condition.notify_all()
    def allow_measured(self):
        with self.condition:self.allowed=self.count;self.condition.notify_all()
    def take(self,index,cancel=None):
        idle=getattr(self,'idle_callback',None)
        while True:
            with self.condition:
                if self.slots:
                    item=self.slots[0]
                    if item.index!=index:raise RuntimeError('Frame preparation order changed')
                    self.handoff=item;item.claim_source('owner_execute')
                    self.slots.pop(0);self.taken=index;self.condition.notify_all();return item
                if cancel is not None and cancel.is_set():raise UIReturnRequested()
                if self.error is not None:raise self.error
                if self.finished or self.stop:raise RuntimeError('PS preparation ended early')
                self.condition.wait(.04 if idle is not None else .2)
                if self.slots:continue
                if self.error is not None or self.finished or self.stop or cancel is not None and cancel.is_set():continue
            if idle is not None:idle()
    def peek(self):
        with self.condition:
            return self.slots[0] if (self.slots and not self.stop and self.error is None) else None
    def close(self):
        with self.condition:
            self.stop=True;pending=list(self.slots);self.slots=[];self.condition.notify_all()
        errors=[]
        for item in pending:
            try:item.release_source()
            except BaseException as exc:errors.append(('queued_source',repr(exc)))
        self.worker.join(10.)
        if self.worker.is_alive():_RETAINED__v64_camera_hdmi.append(self);raise RuntimeError('PS worker active; keep camera/contexts')
        if self.handoff is not None:
            try:self.handoff.release_source();self.handoff=None
            except BaseException as exc:errors.append(('owner_handoff_source',repr(exc)))
        if errors:raise RuntimeError('Prepare source cleanup failed '+str(errors))

def _summary(rows,key):
    values=[float(r[key]) for r in rows if key in r and np.isfinite(r[key])]
    return dict(median_ms=float(np.median(values))*1000,p95_ms=float(np.percentile(values,95))*1000,p99_ms=float(np.percentile(values,99))*1000,
        max_ms=max(values)*1000,count=len(values)) if values else None

from tracking import policy_run as policy_run; from tracking import policy as policy

@logged_run
@policy_run
def run_camera_hdmi(device='/dev/video0',bitfile='system.bit',max_frames=190,warmup_frames=5,
                    width=640,height=480,fps=30,output_size=(362,512),hdmi_mode=(1280,720),
                    max_duration_s=300.,tracking_max_dim=320,detection_max_dim=640,
                    hold_max_age_s=1.5,lk_min_gap=6,lk_max_gap=30,output_orientation='auto_two',
                    opencv_threads=1,timeout_s=3.,color_mode=None,progress_every=60,
                    startup_timeout_s=6.,startup_detect_attempts=6,gc_policy='bounded',hdmi_max_fps=30.,reacquire_budget_ms=420.,
                    plan_strategy='fast_safe',proof_cpu_budget_ms=12.,book_rescue=True,book_rescue_cpu_ms=70.,_ui_context=None,auto_tracking_mode='strict',tracking_audit_s=1.,
                    outer_candidate_competition=False,recovery_local_first=False,detection_contrast_fallback=False,hybrid_auto_ai=True):
    """max_frames=0 means live until duration/interrupt; all diagnostics in one log.

    Flat homography only: P1 has no local B-spline/light-field accelerator.
    Current/HELD/LOST counts are separate. A held H never renews its own TTL.
    """
    global _POISONED,_POISON_REASON
    borrowed=_ui_context is not None
    def check_ui():
        if borrowed:_ui_context.check()
    check_ui()
    if _POISONED:raise RuntimeError('Previous cleanup left resources active: '+str(_POISON_REASON)+
        '. Restart the PYNQ board and inspect the earlier V64_PRIMARY_FAILURE/HDMI_CLEANUP_FAILED in run-result.log')
    if isinstance(max_frames,bool) or not isinstance(max_frames,int) or max_frames<0:raise ValueError('max_frames must be nonnegative int')
    if not isinstance(warmup_frames,int) or warmup_frames<0 or (max_frames and max_frames<=warmup_frames):raise ValueError('Invalid warmup/frame count')
    if not .1<=float(hold_max_age_s)<=1.5:raise ValueError('Hold TTL must be0.1..1.5s')
    if not 1<=float(max_duration_s)<=7200:raise ValueError('Duration must be1..7200s')
    if int(width)%2 or width<2 or height<2 or width>1024:raise ValueError('P1 camera width must be even and<=1024')
    if not 16<=min(output_size) or max(output_size)>1024:raise ValueError('Output dimensions16..1024')
    if int(opencv_threads)!=1:raise ValueError('V68 requires one OpenCV thread')
    if not 1<=float(hdmi_max_fps)<=30:raise ValueError('HDMI max FPS must be1..30')
    if not 120<=float(reacquire_budget_ms)<=500:raise ValueError('Recovery CPU budget must be120..500ms')
    if plan_strategy not in ('fast_safe','exact_reference'):raise ValueError('Unknown plan strategy')
    if not 2<=float(proof_cpu_budget_ms)<=30:raise ValueError('Proof CPU budget must be2..30ms')
    if not isinstance(book_rescue,bool):raise ValueError('book_rescue must be bool')
    if isinstance(book_rescue_cpu_ms,bool) or not np.isfinite(book_rescue_cpu_ms) or not 30<=float(book_rescue_cpu_ms)<=120:
        raise ValueError('book_rescue_cpu_ms must be30..120')
    # Reject an undersized canvas before loading the overlay or starting DMA.
    #   ⭐ 2026-10-27：摄像头分辨率可以大于面板（如 800x600），显示前会等比缩小，
    #      所以这里校验的是【缩小后】的尺寸，而不是原始摄像头尺寸。
    native_display_rect(hdmi_mode,HdmiLatest._fit_shape(hdmi_mode,(height,width)),0)
    native_display_rect(hdmi_mode,(output_size[1],output_size[0]),1)
    if output_orientation=='auto_two':native_display_rect(hdmi_mode,(output_size[0],output_size[1]),1)
    setup=time.perf_counter();root=Path(__file__).resolve().parent;hardware=(root/bitfile).resolve()
    checkpoint('CAMERA_FUNCTION_ENTER',borrowed_UI=borrowed,raw_before_native_setup=True)
    checkpoint('CAMERA_PACKAGE_CHECK_BEGIN')
    verify_package(str(hardware))
    checkpoint('CAMERA_PACKAGE_CHECK_END')
    # run_ui configured OpenCV before its display/touch threads started.
    # Borrowed sessions must not reconfigure that global policy mid-display.
    if not borrowed:cv2.setNumThreads(1)
    elif cv2.getNumThreads()!=1:raise ValueError('UI OpenCV thread policy changed; restart the application')
    checkpoint('ACTIVE_PATH',v86_policy=policy(),tracking='V89 complete V74 automatic current four-edge measurement + conditional full bidirectional LK',
        hardware='only user E:/P1/board/system.bit + system.hwh',mapping='P1 planar RGB565',
        local_surface_enabled=False,light_correction_enabled=False,display='P1 BGR24 same-frame split',
        native_ready_scope='compiled CPU capabilities; unused V31 packet/tone/preview helpers are not active PL features',
        io_native_abi=6601,plan_strategy=plan_strategy,proof_cpu_budget_ms=float(proof_cpu_budget_ms),
        gap_policy='capture counters + freshness + current full FB/four edges; no selected-gap-only loss',
        display_max_fps=float(hdmi_max_fps),orientation_policy='two layouts/current proof commit/500ms evidence',
        illumination_policy='V69 ordinary path; no added illumination probe or pixel enhancement',
         edge_policy='V74 candidates/refinement/independent admission and original PaperTracker; manual core only after explicit calibration',
         recovery_policy='V74 current-edge local recovery + original asynchronous detector; finite hold<=1.5s',
         display_snapshot_policy='automatic: one immutable ordinary-RAM raw copy; corrected CMA still copied to reserved slot',
         display_software_abi=7301,display_frontend_version=79,
         display_composition='1280x720 source-size direct color conversion; no resize or crop')
    camera=backend=display=frontend=preparer=budget=first=acquirer=native_setup=job=None
    owns_native_setup=not borrowed
    hot=getattr(_ui_context,'hot',None) if borrowed else None
    transfer=None;camera_preserved=False
    from ui import camera_key as camera_key
    stream_key=camera_key(device,width,height,fps,color_mode)
    rows=deque(maxlen=512);total=delivered=current=held=lost=0;formal_begin=formal_end=None
    speed_counts=dict(v86_motion_frames=0,v86_edge_verified_frames=0,partition_reused=0,merge_attempts=0,merge_accepted=0,direct_row_frames=0,assembled_frames=0,assembly_bytes=0,lookahead_prefills=0,
        v85_line_quantization_frames=0,v85_single_weak_edge_frames=0,v85_independent_side_remeasured_frames=0,
        v49_current_Y_frames=0,v49_current_color_frames=0,same_frame_receipt_frames=0,current_proof_reuse_hits=0,current_observation_reuse_hits=0,current_primary64_reuse_hits=0,current_FB_proof_reuse_hits=0,
        quick_current_candidate_attempts=0,quick_current_candidate_successes=0,
        native_geometry_frames=0,native_geometry_fallback_frames=0,native_geometry_calls=0,light_result_frames=0)
    current_times=deque(maxlen=120);initial=None;stability=None;run_error=None;cleanup=[];display_summary={};camera_end={}
    count=max_frames or 2147483647;interrupted=False;user_interrupted=False;returned_home=False;epoch=None;stage='pair_overlay'
    session_deadline=time.perf_counter()+float(max_duration_s)
    with frame_log_scope('compact',60,120.):
        try:
            if borrowed:
                backend=_ui_context.backend;display=_ui_context.display;backend._assert_owner()
                if (backend.path!=hardware or backend.input_shape!=(height,width) or display.mode!=tuple(hdmi_mode)
                        or int(output_size[0])*int(output_size[1])>backend.output_capacity):
                    raise ValueError('Borrowed UI resources do not match camera options')
            else:
                backend=P1Backend(str(hardware),(height,width),output_size,timeout_s)
                stage='hdmi_pipeline_start'
                try:display=HdmiLatest(backend.overlay,hdmi_mode,output_size,timeout_s,hold_max_age_s,
                    input_shape=(height,width),max_fps=hdmi_max_fps)
                except BaseException as exc:
                    # A constructor timeout can leave its display owner in driver
                    # start(). Keep the shared overlay pinned instead of reloading it.
                    backend.failed=not bool(getattr(exc,'hdmi_shutdown_safe',False));raise
            check_ui()
            stage='camera_open'
            transfer=hot.claim(_ui_context,stream_key) if hot is not None else None
            if transfer is not None:camera=transfer.camera;budget=transfer.budget
            else:
                checkpoint('CAMERA_OPEN_BEGIN',device=device,width=width,height=height,fps=fps)
                camera=CameraSource(device,width,height,fps,color_mode)
            set_color_mode(camera.color_mode)
            if borrowed:
                from ui import bind_preview as bind_preview
                bind_preview(camera,display,_ui_context.generation)
            check_ui()
            checkpoint('CAMERA_READY',durable=True,**camera.metadata(),no_jpeg_decoder=True)
            stage='visible_native_setup'
            native_setup=_ui_context.native_setup if borrowed else NativeSetup()
            if transfer is not None:
                check_ui();status=native_setup.result()
            else:
                status=wait_native_with_preview(native_setup,camera,display,check_ui,
                    lambda:_ui_context.generation if borrowed else 0,deadline=session_deadline,context=_ui_context)
            if owns_native_setup:native_setup.close();native_setup=None
            checkpoint('NATIVE_READY',**status)
            check_ui()
            stage='placement_confirmation'
            if transfer is None:
                wait_for_placement(camera,display,check_ui,lambda:_ui_context.generation if borrowed else 0,
                    deadline=session_deadline,context=_ui_context)
            if borrowed:_ui_context.set_phase('acquiring')
            stage='live_acquisition'
            def build_frontend(frame,detection):
                from tracking import create_frontend as create_frontend
                return create_frontend(camera,frame,detection,output_size,tracking_max_dim,detection_max_dim,
                    hold_max_age_s,lk_min_gap,lk_max_gap,output_orientation,reacquire_budget_ms,
                    plan_strategy,proof_cpu_budget_ms,book_rescue,book_rescue_cpu_ms)
            from tracking import V74Acquire as LocalAcquire
            hybrid_enabled=bool(hybrid_auto_ai and borrowed and getattr(display,'ai_service',None) is not None)
            if hybrid_enabled:
                from ui import HybridFrontend__v111_recovery as HybridFrontend
                hybrid_options=dict(tracking_max_dim=tracking_max_dim,detection_max_dim=detection_max_dim,
                    hold_max_age_s=hold_max_age_s,output_orientation=output_orientation,
                    reacquire_budget_ms=reacquire_budget_ms,plan_strategy=plan_strategy,
                    proof_cpu_budget_ms=proof_cpu_budget_ms,book_rescue=book_rescue,book_rescue_cpu_ms=book_rescue_cpu_ms)
                frontend=HybridFrontend(camera,output_size,hybrid_options,_ui_context,build_frontend,
                    recovery=transfer is not None and transfer.stabilized,target_selection=_ui_context.ticket.target_selection)
                _ui_context.ticket.target_selection=None
                stability=dict(policy='V74 exact automatic gate; AI distinct-frame plus current-source proof',
                    camera_reused=transfer is not None,hybrid=True)
                initial=dict(frontend.initial)
            else:
                target_selection=_ui_context.ticket.target_selection if borrowed else None
                def target_report(notice):
                    if borrowed and not _ui_context.cancel.is_set():display.set_target_notice(notice,_ui_context.generation)
                def target_progress(phase):
                    if borrowed and not _ui_context.cancel.is_set():display.set_target_phase(phase,_ui_context.generation)
                acquirer=LocalAcquire(detection_max_dim,tracking_max_dim,build_frontend,budget_ms=reacquire_budget_ms,
                    recovery=transfer is not None and transfer.stabilized,target_selection=target_selection,target_report=target_report if borrowed else None,
                    target_progress=target_progress if target_selection is not None else None)
                target_selection=None
                if borrowed:_ui_context.ticket.target_selection=None
                acquisition_check=transfer.acquisition_check(check_ui) if transfer is not None else check_ui
                first,detection,frontend,admission=pump_acquisition(acquirer,camera,display,acquisition_check,
                    lambda:_ui_context.generation if borrowed else 0,
                    deadline=session_deadline,context=_ui_context,already_running=transfer is not None and transfer.stabilized,
                    ready_after=transfer.ready_after if transfer is not None else None)
                acquirer.close();acquirer=None
                stability=dict(policy='already_running_camera_then_original_admission' if transfer is not None else 'V74_12_150_4_stabilization_then_original_admission',
                    strict_brightness_gate=transfer is None,live_preview_during_acquisition=True,
                    camera_reused=transfer is not None,full_current_target_admission=True)
                initial=dict(frontend.initial,admission=admission);first.release();first=None
            check_ui()
            if budget is None:budget=GcBudget(gc_policy,240,30.);budget.__enter__()
            stage='producer_start'
            frontend.raw_required=display.needs_raw_source
            if borrowed:_ui_context.set_phase('running')
            preparer=PrepareQueue(frontend,count,warmup_frames)
            continuity=None
            if borrowed:
                from ui import OwnerContinuity as OwnerContinuity
                continuity=OwnerContinuity(frontend,backend,display,_ui_context)
                preparer.idle_callback=continuity.pump
            checkpoint('HDMI_SEQUENCE_READY',durable=True,release_id=RELEASE_ID,initial=initial,
                camera_reused=transfer is not None,initial_stabilization_repeated=transfer is None,
                full_current_target_admission=True,GC_window_reused=transfer is not None,
                setup_s=time.perf_counter()-setup,output_size=list(output_size),hdmi_mode=list(hdmi_mode),
                localization='V89 full V74 automatic detector/PaperTracker; current edges first, conditional complete FB; no automatic manual-motion entry',remap='P1 planar RGB565',
                book_rescue_policy='disabled: exact V74 localization strategy',
                book_rescue_cpu_ms=float(book_rescue_cpu_ms),
                queue_capacity=preparer.depth,max_prepare_ahead=preparer.depth)
            stage='frame_loop'
            # ⭐ 2026-10-18 静态输出冻结：静止保持帧不再跑 P1 remap/DMA，
            #   直接把上一帧已完成的校正图再提交一次（输入仍在变，但 H 不变）。
            freeze_output=False  # Live12 always remaps fresh pixels; no cached-output freeze.
            #   ⭐ 2026-10-25：逐帧日志降频。
            #      实测（run 86，LOG_WRITER_SUMMARY）：`_owned_payload()` 的**深拷贝**
            #      在主线程上花了 snapshot_s=13.69 s / 3122 帧 = **4.4 ms/帧**，
            #      占墙钟 10%。日志本身 24 MB / 3122 帧 = 7.7 KB/帧。
            #      ⇒ P11_LOG_EVERY=N：每 N 帧才写一条 V64_FRAME（默认 1 = 全记）。
            #      ⚠️ 只影响【落盘的逐帧记录】；内存里的 `rows` 仍然是每帧全收，
            #         所以 RUN_COMPLETED 的 timing 汇总**不受影响**。
            try:log_every=max(1,int(os.environ.get('P11_LOG_EVERY','1')))
            except ValueError:log_every=1
            last_output=None;last_output_sig=None;last_output_index=0
            for index in range(1,count+1):
                if borrowed and _ui_context.cancel.is_set():raise UIReturnRequested()
                if index==warmup_frames+1:
                    formal_begin=time.perf_counter();epoch=display.begin_measurement();preparer.allow_measured()
                if time.perf_counter()>=session_deadline:break
                try:
                    wait_begin=time.perf_counter();job=preparer.take(index,_ui_context.cancel if borrowed else None);taken=time.perf_counter()
                    row=dict(job.record,preparation_wait_s=taken-wait_begin,
                        parameter_queue_s=max(0.,taken-job.record['ps_prepared_at']))
                    if borrowed and _ui_context.cancel.is_set():raise UIReturnRequested()
                    if job.state=='LOST':
                        image=None;owner=dict(owner_s=0.,owner_thread_cpu_s=0.,tiles=0)
                        last_output=None;last_output_sig=None
                    else:
                        output_sig=(tuple(job.size),tuple(tuple(float(v) for v in c) for c in (job.record.get('corners') or ())))
                        if (freeze_output and job.record.get('mode')=='static_hold' and last_output is not None
                                and not backend.active and output_sig==last_output_sig):
                            image=last_output
                            owner=dict(owner_s=0.,owner_thread_cpu_s=0.,tiles=0,frozen_output=True,
                                frozen_frames=int(index-last_output_index))
                        else:
                            image,owner=backend.execute(job,preparer.peek)
                            last_output=image;last_output_sig=output_sig;last_output_index=index
                    ready=time.perf_counter();row.update(owner,output_ready_at=ready,
                        capture_to_output_s=ready-job.record['capture_ready_at'])
                    #   ⭐ 2026-10-31 诊断：service_s 除 take/owner/offer 之外还有 ~12ms 归不了因，
                    #      而 ps_prepare 的墙钟里只有一半是 CPU（疑似等 GIL）。纯计时，不改行为。
                    _t_a=time.perf_counter()
                    if job.lease.flags&0xe000==0x2000 and 0<=job.lease.timestamp<=ready:
                        row['driver_to_output_s']=ready-job.lease.timestamp
                    if hybrid_enabled:
                        if row.get('hybrid_epoch')!=frontend.epoch:
                            job.state='HELD' if image is not None else 'LOST';row['state']=job.state
                            row['continuity_output']=False
                        frontend.completed(row,ready)
                        row['hybrid_valid_fps']=frontend.rate.fps(ready)
                        if row.get('hybrid_epoch')==frontend.epoch:row['hybrid_phase']=frontend.phase
                    _t_b=time.perf_counter()
                    measured=index>warmup_frames
                    if measured:
                        total+=1;delivered+=int(job.state!='LOST');current+=int(job.state=='CURRENT')
                        held+=int(job.state=='HELD');lost+=int(job.state=='LOST')
                        speed_counts['v86_motion_frames']+=int(job.state=='CURRENT' and row.get('complete_FB',False))
                        speed_counts['v86_edge_verified_frames']+=int(job.state=='CURRENT' and bool(row.get('current_source_proof_verified',False)))
                        speed_counts['partition_reused']+=int(row.get('partition_reused',False))
                        speed_counts['merge_attempts']+=int(row.get('merge_probe_attempts',0))
                        speed_counts['merge_accepted']+=int(row.get('merge_probe_accepted',0))
                        speed_counts['direct_row_frames']+=int(owner.get('direct_row_receive',False))
                        speed_counts['assembled_frames']+=int(job.state!='LOST' and not owner.get('direct_row_receive',False))
                        speed_counts['assembly_bytes']+=int(owner.get('tile_assembly_bytes',0))
                        speed_counts['lookahead_prefills']+=int(owner.get('lookahead_prefills',0))
                        speed_counts['v85_line_quantization_frames']+=int(job.state=='CURRENT' and row.get('v85_line_quantization',False))
                        speed_counts['v85_single_weak_edge_frames']+=int(job.state=='CURRENT' and row.get('v85_single_weak_edge',False))
                        speed_counts['v85_independent_side_remeasured_frames']+=int(job.state=='CURRENT' and row.get('v85_independent_side_remeasured',False))
                        speed_counts['v49_current_Y_frames']+=int(job.state=='CURRENT' and row.get('v49_fastpath_route')=='current_Y_edges')
                        speed_counts['v49_current_color_frames']+=int(job.state=='CURRENT' and row.get('v49_fastpath_route')=='current_color_edges')
                        speed_counts['same_frame_receipt_frames']+=int(row.get('same_frame_receipt_reused',False))
                        speed_counts['current_proof_reuse_hits']+=int(row.get('current_proof_reuse_hits',0))
                        for reuse_key in ('current_observation_reuse_hits','current_primary64_reuse_hits','current_FB_proof_reuse_hits'):
                            speed_counts[reuse_key]+=int(row.get(reuse_key,0))
                        speed_counts['quick_current_candidate_attempts']+=int(row.get('quick_current_candidate_attempted',False))
                        speed_counts['quick_current_candidate_successes']+=int(job.state=='CURRENT' and row.get('quick_current_candidate_verified',False))
                        speed_counts['native_geometry_frames']+=int(row.get('native_geometry_used',False))
                        speed_counts['native_geometry_fallback_frames']+=int(bool(row.get('native_geometry_fallback')))
                        speed_counts['native_geometry_calls']+=int(row.get('native_geometry_calls',0))
                        speed_counts['light_result_frames']+=int(row.get('ps_light_results',False))
                        if job.state=='CURRENT':current_times.append(ready)
                    while current_times and current_times[0]<ready-2.:current_times.popleft()
                    corr=(len(current_times)-1)/(current_times[-1]-current_times[0]) if len(current_times)>1 and current_times[-1]>current_times[0] else 0.
                    row['correction_fps']=corr
                    if borrowed:row['ui_generation']=_ui_context.generation
                    #   ⭐ 2026-10-24 诊断：offer() 只报了内部子项，外面套一个总计时，
                    #      这样 service_s 才能拆成 take / owner / offer / release_source。
                    _t_c=time.perf_counter()
                    _t_offer=time.perf_counter()
                    row['display_snapshot_s']=display.offer(image,row,job.source_snapshot,raw_owned=job.source_owned,
                        output_reference=backend.output_reference(image))
                    row['display_offer_total_s']=time.perf_counter()-_t_offer
                    _t_d=time.perf_counter()
                    row.update(display.last_offer_timing)
                    if continuity is not None:continuity.remember(job,row)
                    _t_e=time.perf_counter()
                    if row.get('direction_switch') and row.get('switch_requested_at') is not None:
                        row['direction_to_output_s']=ready-row['switch_requested_at']
                    row['service_s']=time.perf_counter()-wait_begin
                    #   诊断分解（纯计时）：把 service_s 拆成
                    #   take前开销 / hybrid记账 / 计数器 / offer / offer后收尾。
                    row['svc_pre_s']=max(0.,ready-taken-float(owner.get('owner_s',0.)))
                    row['svc_hybrid_s']=max(0.,_t_b-_t_a)
                    row['svc_counters_s']=max(0.,_t_c-_t_b)
                    row['svc_offer_tail_s']=max(0.,_t_e-_t_d)
                    if measured:
                        rows.append(row);budget.check(index)
                        if log_every<=1 or index%log_every==0:
                            frame_record('V64_FRAME',**row)
                        if progress_every and total%progress_every==0:checkpoint('HDMI_PROGRESS',frames=total,current=current,held=held,lost=lost,
                            current_fps=current/max(1e-9,ready-formal_begin),correction_fps_recent=corr)
                    if owner.get('stop_requested',False):interrupted=True;user_interrupted=True;break
                finally:
                    if job is not None:job.release_source();job=None
            formal_end=time.perf_counter()
        except UIReturnRequested:
            interrupted=True;returned_home=True;formal_end=time.perf_counter()
            checkpoint('UI_CAMERA_RETURN',frames=total,hardware_abort=False)
        except KeyboardInterrupt:
            interrupted=True;user_interrupted=True;formal_end=time.perf_counter();checkpoint('HDMI_USER_STOP',durable=True,frames=total)
        except BaseException as exc:
            run_error=exc;formal_end=time.perf_counter()
            try:checkpoint('V64_PRIMARY_FAILURE',durable=True,failure_stage=stage,exception_type=type(exc).__name__,
                exception=str(exc),traceback=__import__('traceback').format_exc(),frames=total,remap_active=bool(backend and backend.active),
                remap_failed=bool(backend and backend.failed),hardware_source='E:/P1/board/system.bit + system.hwh')
            except BaseException:pass
        finally:
            if formal_begin is not None:
                checkpoint('HDMI_PRE_CLEANUP_SUMMARY',frames=total,current=current,held=held,lost=lost,
                    formal_elapsed_s=max(0.,(formal_end or time.perf_counter())-formal_begin),
                    display=display.snapshot(include_samples=False) if display else None)
            # Stop producer first: no native LK context or camera mapping may be
            # closed while CPU prepare/recovery still references it.
            preparer_stopped=True
            if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='prepare_stop_begin',frames=total)
            if native_setup is not None and owns_native_setup:
                try:native_setup.close()
                except BaseException as exc:cleanup.append(('native_setup',repr(exc)));preparer_stopped=False
            if acquirer is not None:
                try:acquirer.close()
                except BaseException as exc:cleanup.append(('initial_acquisition',repr(exc)));preparer_stopped=False
            if preparer is not None:
                try:preparer.close()
                except BaseException as exc:cleanup.append(('prepare',repr(exc)));preparer_stopped=False
            if job is not None and preparer_stopped:
                try:job.release_source();job=None
                except BaseException as exc:cleanup.append(('owner_source',repr(exc)))
            if first is not None:
                try:first.release()
                except BaseException as exc:cleanup.append(('first_lease',repr(exc)))
            if preparer_stopped and frontend is not None:
                if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='frontend_close_begin',frames=total)
                try:frontend.close()
                except BaseException as exc:cleanup.append(('frontend',repr(exc)));preparer_stopped=False
            if preparer_stopped and camera is not None:
                if backend is None or not backend.active:
                    try:camera.retire_consumers((preparer.worker,) if preparer is not None else (),current_owner_retired=True)
                    except BaseException as exc:cleanup.append(('consumer_drain',repr(exc)))
                camera_end=camera.metadata()
                try:
                    if hot is not None and _ui_context.cancel.is_set() and not user_interrupted and run_error is None and not cleanup:
                        camera_preserved=hot.offer(_ui_context,camera,stream_key,budget,
                            readers_retired=preparer_stopped,backend_idle=backend is not None and not backend.active and not backend.failed,
                            admitted=stability is not None and frontend is not None)
                    if not camera_preserved:
                        if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='camera_close_begin',frames=total)
                        camera.close()
                except BaseException as exc:cleanup.append(('camera',repr(exc)))
            if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='camera_cleanup_end',frames=total,errors=list(cleanup),capture_kept_running=camera_preserved)
            display_stopped=True
            if display is not None and not borrowed:
                try:display.close()
                except BaseException as exc:
                    display_stopped=bool(display.shutdown_safe)
                    if display_stopped:
                        if run_error is None:run_error=exc
                        checkpoint('HDMI_FAILED_BUT_HALTED',durable=True,exception=repr(exc),hardware_stopped=True)
                    else:cleanup.append(('hdmi',repr(exc)))
                display_summary=display.snapshot()
            elif display is not None:display_summary=display.snapshot(include_samples=False)
            if display_stopped and backend is not None and not borrowed:
                try:backend.close()
                except BaseException as exc:cleanup.append(('backend',repr(exc)))
            if budget is not None and not camera_preserved:budget.__exit__(None,None,None)
            if cleanup:
                _POISONED=True;_POISON_REASON=list(cleanup)
                _RETAINED__v64_camera_hdmi.append((native_setup,acquirer,preparer,frontend,camera,display,backend))
                checkpoint('HDMI_CLEANUP_FAILED',durable=True,errors=cleanup,resources_retained=True)
        if run_error is not None:raise run_error
        if cleanup:raise RuntimeError('Cleanup safety check failed '+str(cleanup))
        elapsed=max(0.,(formal_end or time.perf_counter())-formal_begin) if formal_begin is not None else 0.
        ds=display_summary.get('epoch_stats',{}).get(str(epoch),{})
        samples=[s for s in display_summary.get('samples',[]) if s['epoch']==epoch]
        timings={} if borrowed and interrupted else {key:_summary(list(rows),key) for key in ('ps_prepare_s','ps_thread_cpu_s','ps_prepare_total_s','ps_prepare_total_thread_cpu_s','tracker_s','plan_update_s',
            'observation_wrapper_s','observation_native_s','result_decode_s','result_decode_thread_cpu_s','source_corners_s','post_observation_s',
            'pre_obs_s','static_hold_s','lk_s','post_lk_tail_s','feature_s','feature_roi_s',
            'orientation_prepare_s','orientation_thread_cpu_s','native_geometry_s','native_geometry_thread_cpu_s','h_native_s','h_native_thread_cpu_s',
            'geometry_result_decode_s','geometry_result_decode_thread_cpu_s','metadata_build_s','metadata_thread_cpu_s','job_seal_s','proof_s','proof_thread_cpu_s','mapping_native_s','mapping_native_thread_cpu_s','illumination_probe_s','edge_stability_s','edge_stability_thread_cpu_s','local_edge_lock_s','local_edge_lock_thread_cpu_s','quick_current_candidate_s','quick_current_candidate_thread_cpu_s','source_snapshot_s',
            'preparation_wait_s','parameter_queue_s','owner_s','owner_thread_cpu_s','control_s','input_copy_s',
            'cache_sync_s','dma_wait_s','tile_assembly_s','lookahead_service_s','display_snapshot_s','display_snapshot_thread_cpu_s','display_offer_lock_wait_s','display_raw_copy_s','display_output_copy_s','display_pair_copy_native_s','display_pair_copy_native_thread_cpu_s','direction_to_output_s','capture_to_output_s','driver_to_output_s',
            'svc_pre_s','svc_hybrid_s','svc_counters_s','svc_offer_tail_s',
            'owner_release_s','owner_prep_s','owner_sharp_prep_s','owner_arm_s','owner_sharp_done_s','owner_loop_s','owner_loop_accounted_s')}
        display_elapsed=max(0.,max(formal_end or 0.,ds.get('last_submitted_at',0.))-formal_begin) if formal_begin is not None else 0.
        metrics_frontend=(getattr(frontend,'delegate',None) or frontend) if frontend is not None else None
        result=dict(release_id=RELEASE_ID,status='stopped' if interrupted else 'completed',frames=total,
            user_interrupted=user_interrupted,returned_home=returned_home,
            delivered=delivered,current=current,held=held,lost=lost,formal_elapsed_s=elapsed,
            current_correction_fps=current/elapsed if elapsed else 0.,
            current_metric_scope='fresh current corners: complete FB motion OR strict exterior; HELD excluded',
            motion_tracked_frames=speed_counts['v86_motion_frames'],edge_verified_frames=speed_counts['v86_edge_verified_frames'],
            motion_correction_fps=speed_counts['v86_motion_frames']/elapsed if elapsed else 0.,
            independent_edge_verified_fps=speed_counts['v86_edge_verified_frames']/elapsed if elapsed else 0.,
            delivered_fps=delivered/elapsed if elapsed else 0.,held_fps=held/elapsed if elapsed else 0.,
            hdmi_submitted=ds.get('submitted',0),hdmi_current_submitted=ds.get('current',0),
            hdmi_panels_submitted=ds.get('panels',0),
            hdmi_panel_fps=ds.get('panels',0)/display_elapsed if display_elapsed else 0.,
            hdmi_submit_fps=ds.get('submitted',0)/display_elapsed if display_elapsed else 0.,
            hdmi_current_fps=ds.get('current',0)/display_elapsed if display_elapsed else 0.,
            formal_display_elapsed_s=display_elapsed,
            speed_counts=speed_counts,timing=timings,hdmi_timing={} if borrowed and interrupted else {k:_summary(samples,k) for k in ('compose_s','compose_thread_cpu_s','frame_acquire_s','frame_acquire_thread_cpu_s','clear_layout_s','clear_layout_thread_cpu_s','ui_header_restore_s','left_panel_s','left_panel_thread_cpu_s','right_panel_s','right_panel_thread_cpu_s','left_native_s','left_native_thread_cpu_s','right_native_s','right_native_thread_cpu_s','corner_draw_s','other_compose_s','input_convert_s','output_convert_s','scale_s','vdma_submit_s','vdma_submit_thread_cpu_s','direction_to_submit_s','capture_to_submit_s')},
            summary_window='last512 correction rows/last512 display submissions; totals cover all formal frames',
            camera=camera_end,camera_reused=transfer is not None,camera_preserved_for_next_target=camera_preserved,
            display=display_summary,gc=budget.summary() if budget else None,initial=initial,
            stability=stability,hardware_manifest=backend.manifest if backend else None,
            localization_baseline='V74 complete localization including original native kernels; current complete FB motion with safe reentry',
            plan_strategy=plan_strategy,proof_cpu_budget_ms=float(proof_cpu_budget_ms),proof_cache=metrics_frontend.proof_cache.snapshot() if metrics_frontend else None,native_plan_cache=dict(metrics_frontend.plan_workspace.batch.last_cache) if metrics_frontend else None,mapping='P1 planar',photometric='camera passthrough to RGB565 bilinear',
            pipeline='chronological PS producer / single remap owner / same-frame split latest HDMI owner',
            total_call_before_logging_s=time.perf_counter()-setup,rows=list(rows))
        checkpoint('HDMI_FINAL_SUMMARY',durable=True,frames=total,current=current,held=held,lost=lost,
            current_fps=result['current_correction_fps'],delivered_fps=result['delivered_fps'],
            hdmi_current_fps=result['hdmi_current_fps'],hdmi_submit_fps=result['hdmi_submit_fps'],hdmi_panel_fps=result['hdmi_panel_fps'],speed_counts=speed_counts,timing=timings,hdmi_timing=result['hdmi_timing'])
        return result


# ======================================================================
# ===== [09/13] v70_hdmi_timing =====
# ======================================================================


"""P1 software-only 1024x600 CVT frontend; existing bit/hwh stay immutable.

Register conventions: Xilinx XVtc_ConvTiming2Signal/SetGenerator (origin=1,
progressive, vertical sync -1), Digilent/PYNQ DisplayClkFindReg. No private
CPython object memory or global PYNQ mode-table patch is used.
"""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# Manual page6: hdmi_cvt1024 600 60 6 0 0 0. CVT request expanded to
# 15:9, progressive, no margins/reduced blanking; nominal60Hz (59.8503Hz).
# These derived register parameters are not a verbatim vendor porch table.
TIMING=dict(width=1024,height=600,pixel_clock_hz=49000000,
    h_front=40,h_sync=104,h_back=144,v_front=3,v_sync=7,v_back=14,
    h_positive=True,v_positive=True,h_total=1312,v_total=624,
    source='manual_page6_CVT_1024_600_60_aspect6_no_margins_progressive_no_RB')
# REF_CLK_I=FCLK2=100MHz. VCO=100*49/5=980MHz; 5x=980/4=245MHz;
# existing BUFR /5 yields49MHz. clk0L,clkFBL,clkFBH_clk0H,divclk,lockL,filter.
# The two lookup words use fbmult49 in upstream PYNQ video_display.h.
CLOCK_WORDS=(0x00000082,0x00800619,0x00000000,0x00002083,0xCFAFA401,0x00A300FF)
SOURCE_SELECT=0x03F7EF00
_BASE='video/hdmi_out/frontend/'


class Cvt1024Frontend:
    """Only the existing HDMI owner may configure this output frontend."""
    def __init__(self,vout,overlay,timeout_s=3.):
        from pynq import MMIO,Clocks
        self.owner=threading.get_ident();self.timeout=float(timeout_s)
        self.original=vout._hdmi;self._mode=None;self.running=False
        if not hasattr(self.original,'_display'):raise RuntimeError('1024x600 requires PYNQ-Z2 DVI frontend')
        if int(self.original._display.state())!=0:raise RuntimeError('HDMI frontend already running before custom timing')
        modules=ET.parse(Path(overlay.bitfile_name).with_suffix('.hwh')).findall('.//MODULE')
        dyn=next((m for m in modules if m.get('FULLNAME')=='/'+_BASE+'axi_dynclk'),None)
        vtc=next((m for m in modules if m.get('FULLNAME')=='/'+_BASE+'vtc_out'),None)
        if dyn is None or vtc is None:raise RuntimeError('Specified P1 timing metadata missing')
        ref=dyn.find("./PORTS/PORT[@NAME='REF_CLK_I']")
        if ref is None or ref.get('SIGNAME')!='ps7_FCLK_CLK2' or int(ref.get('CLKFREQUENCY','0'))!=100000000:
            raise RuntimeError('1024x600 fixed clock receipt requires specified100MHz FCLK2 reference')
        if abs(float(Clocks.fclk2_mhz)-100.)>.01:raise RuntimeError('Actual FCLK2 differs from100MHz HDMI clock reference')
        pars={p.get('NAME'):p.get('VALUE') for p in vtc.findall('./PARAMETERS/PARAMETER')}
        if pars.get('C_HAS_AXI4_LITE')!='1' or pars.get('C_GENERATE_EN')!='1' or pars.get('C_INTERLACE_EN')!='0':
            raise RuntimeError('Specified P1 progressive programmable VTC contract differs')
        self.clock=MMIO(int(overlay.ip_dict[_BASE+'axi_dynclk']['phys_addr']),0x20)
        self.vtc=MMIO(int(overlay.ip_dict[_BASE+'vtc_out']['phys_addr']),0x100)
        self.original.stop()
        self.vtc.write(0,int(self.vtc.read(0))&~4)
        if self.vtc.read(0)&4:raise RuntimeError('VTC generator could not stop before custom timing')
        self.detail=dict(TIMING,refresh_hz=49000000./(1312*624),reference_clock_hz=100000000,
            serial_clock_hz=245000000,clock_words=list(CLOCK_WORDS),clock_source='FCLK2',
            hardware_modified=False,vtc_version=int(self.vtc.read(0x10)),physical_display_validated=False)
    def _owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('HDMI timing access must stay on HDMI owner')
    def _wait_clock(self,running):
        deadline=time.perf_counter()+self.timeout
        while bool(self.clock.read(4)&1)!=bool(running):
            if time.perf_counter()>=deadline:raise TimeoutError('HDMI dynamic clock did not '+('lock' if running else 'stop'))
            time.sleep(.001)
    @property
    def mode(self):return self._mode
    @mode.setter
    def mode(self,value):
        self._owner()
        if (int(value.width),int(value.height),int(value.bits_per_pixel))!=(1024,600,24):
            raise ValueError('Custom frontend requires1024x600 BGR24')
        if abs(float(value.fps)-60.)>.01:raise ValueError('Custom CVT frontend uses nominal60Hz')
        if self.running:self.stop()
        self._mode=value
    def start(self):
        self._owner()
        if self.running:return
        if self._mode is None:raise RuntimeError('Set HDMI mode before start')
        # Reprogram only with the generator disabled and before VDMA starts.
        if self.vtc.read(0)&4:raise RuntimeError('VTC enabled during timing reconfiguration')
        self.clock.write(0,0);self._wait_clock(False)
        for offset,value in zip(range(8,32,4),CLOCK_WORDS):self.clock.write(offset,value)
        clock_read=tuple(int(self.clock.read(offset)) for offset in range(8,32,4))
        if clock_read!=CLOCK_WORDS:raise RuntimeError('HDMI clock parameter readback mismatch')
        self.clock.write(0,1);self._wait_clock(True)
        p=TIMING;w,h=p['width'],p['height'];hs=w+p['h_front'];he=hs+p['h_sync']
        vs=h+p['v_front']-1;ve=vs+p['v_sync'];ht=p['h_total'];vt=p['v_total']
        # XVtc origin=1: full totals, vertical sync start/end minus one;
        # VBlank horizontal offset=HActive, VSync horizontal offset=HSyncStart.
        registers={0x60:(h<<16)|w,0x6C:0x7F,0x70:ht,0x74:(vt<<16)|vt,
            0x78:(he<<16)|hs,0x7C:(w<<16)|w,0x80:(ve<<16)|vs,
            0x84:(hs<<16)|hs,0x88:(w<<16)|w,0x8C:(ve<<16)|vs,0x90:(hs<<16)|hs}
        self.vtc.write(0,SOURCE_SELECT|2)
        self.vtc.write(0x68,int(self.vtc.read(0x68))&~0x140) # progressive, chroma parity0; preserve RGB format
        for offset,value in registers.items():self.vtc.write(offset,value)
        readback={offset:int(self.vtc.read(offset)) for offset in registers}
        # Field1/chroma/field-ID hardware is optional in this progressive P1
        # core. Write the official mirror registers but prove active fields;
        # do not require unused/omitted field1 registers to echo their value.
        masks={0x60:0x3FFF3FFF,0x6C:0x1F,0x70:0x3FFF,0x74:0x3FFF,
            0x78:0x3FFF3FFF,0x7C:0x3FFF3FFF,0x80:0x3FFF3FFF,0x84:0x3FFF3FFF}
        if any((readback[k]&mask)!=(registers[k]&mask) for k,mask in masks.items()):
            raise RuntimeError('1024x600 active VTC timing readback mismatch')
        if self.vtc.read(0x68)&0x40:raise RuntimeError('VTC progressive encoding readback failed')
        self.vtc.write(0,SOURCE_SELECT|7)
        if not self.vtc.read(0)&4:raise RuntimeError('VTC generator enable readback failed')
        self.running=True
        checkpoint('HDMI_CUSTOM_TIMING_READY',durable=True,**self.detail,
            vtc_control=int(self.vtc.read(0)),vtc_registers={hex(k):v for k,v in readback.items()},
            vtc_active_readback_masks={hex(k):v for k,v in masks.items()},
            clock_locked=bool(self.clock.read(4)&1),timing_source='vendor CVT request expanded in PS; board confirmation pending')
    def stop(self):
        self._owner()
        self.vtc.write(0,int(self.vtc.read(0))&~4)
        if self.vtc.read(0)&4:raise RuntimeError('HDMI VTC generator disable not proved')
        self.running=False


def install_1024_frontend(vout,overlay,timeout_s):
    """Replace only this VideoOut instance's mode frontend, keeping official VDMA."""
    if not hasattr(vout,'_hdmi'):raise RuntimeError('Installed PYNQ VideoOut frontend interface differs')
    frontend=Cvt1024Frontend(vout,overlay,timeout_s)
    vout._hdmi=frontend
    return frontend


# ======================================================================
# ===== [10/13] v73_ratio_ui =====
# ======================================================================


"""Right-hand settings, ordinary-RAM event snapshots, no resident draw loop."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

PANEL=(820,72,460,648)
ENTRY=(768,0,224,72)
def inside__v73_ratio_ui(p,r):return p is not None and r[0]<=p[0]<r[0]+r[2] and r[1]<=p[1]<r[1]+r[3]
def load_assets__v73_ratio_ui(assets,root):
    root=Path(root)
    def read(name):
        image=cv2.imread(str(root/name),cv2.IMREAD_COLOR)
        if image is None:raise ValueError('Missing ratio UI asset '+name)
        image.setflags(write=False);return image
    assets.ratio_panel=read('v73_ratio_panel.png');atlas=read('v73_ratio_atlas.png')
    if assets.ratio_panel.shape!=(648,460,3) or atlas.shape!=(1024,1024,3):raise ValueError('Invalid ratio assets')
    spec=json.loads((root/'v73_ratio_assets.json').read_text(encoding='utf-8'))
    assets.ratio_parts={name:atlas[y:y+h,x:x+w] for name,(x,y,w,h) in spec.items()}
    assets.ratio_original_headers=dict(assets.headers);assets.ratio_header_cache={}
    assets.ratio_reading_header=read('v73_reading_header.png')
    assets.ratio_asset_resident_bytes=assets.ratio_panel.nbytes+atlas.nbytes+assets.ratio_reading_header.nbytes

def ratio_header(assets,value):
    key=value if value in PRESETS or value=='busy' else 'custom'
    cache=assets.ratio_header_cache
    if key not in cache:
        headers={}
        for view,original in assets.ratio_original_headers.items():
            image=original.copy();image[3:69,768:992]=assets.ratio_parts['header_'+key]
            image.setflags(write=False);headers[view]=image
        cache[key]=headers
    return cache[key]

def render_ratio(canvas,payload,assets):
    if not payload.get('ratio_background_cached'):canvas[:]=payload['source']
    x,y,w,h=PANEL;canvas[y:y+h,x:x+w]=assets.ratio_panel
    model=payload['meta'];parts=assets.ratio_parts
    def put(name,px,py):
        image=parts[name];hh,ww=image.shape[:2];canvas[y+py:y+py+hh,x+px:x+px+ww]=image
    def number(text,px,py):
        for char in str(text)[:16]:
            image=parts.get('glyph_'+char)
            if image is not None:
                canvas[y+py:y+py+28,x+px:x+px+16]=image;px+=16
    put('mode_'+model['mode'],26,78)
    keyboard=model.get('field') is not None
    put('done' if keyboard else 'reset',306,27)
    if keyboard:
        keys='123456789.0';keys=list(keys)+['del']
        for i,key in enumerate(keys):put('key_'+key,26+(i%3)*140,208+(i//3)*60)
    else:
        for i,key in enumerate(list(PRESETS)+['custom']):put('preset_'+key+('_selected' if model['draft']==key else ''),26+(i%3)*140,133+(i//3)*96)
    if model['draft']=='custom':
        fy=132 if keyboard else 330
        put('width',26,fy+10);put('height',172,fy+10)
        for key,fx in [('width',56),('height',202)]:
            canvas[y+fy:y+fy+49,x+fx:x+fx+97]=(35,28,17)
            cv2.rectangle(canvas,(x+fx,y+fy),(x+fx+96,y+fy+48),(132,115,85),1)
            if model.get('field')==key:cv2.rectangle(canvas,(x+fx,y+fy),(x+fx+96,y+fy+48),(220,205,123),2)
            number(model[key],fx+5,fy+9)
        put('invalid' if model.get('error')=='invalid' else 'hint',26,464 if keyboard else 396)
    if model.get('error')=='failed':put('failed',26,480)
    put('current',26,520)
    current=model['current']
    if current=='original':
        put('current_original',88,520)
    else:number(current,88,520)
    try:normalize(model['width']+':'+model['height'] if model['draft']=='custom' else model['draft']);valid=True
    except ValueError:valid=False
    put('cancel',26,565);put('apply' if valid else 'apply_disabled',166,565)

class RatioUI:
    def __init__(self,state,display):
        self.state=state;self.display=display;self.registry=RatioRegistry()
        self.registry.on_reject=self.manual_mapping_rejected
        self.pending=None;self.snapshot_task=None;self.open_requested=False
        self.base_show=display._show;self.model=None;self.captured=None
        self.previous_offer=None
    def mode(self):return 'manual' if self.state.ticket.manual else 'auto'
    def manual_mapping_rejected(self,mode,revision,reason):
        pending=self.pending
        if pending is not None and (pending['mode'],pending['revision'])==(mode,revision):self.fail('manual_mapping_proof_rejected')
        else:self.registry.rollback(mode)
    def prepare_header_transition(self):
        d=self.display
        if self.state.page!='home' and self.pending is None and not self.open_requested and d.target_switch is None:
            d._show=self.first_result_show
    def first_result_show(self,raw,out,meta):
        d=self.display
        if out is not None and int(meta.get('ui_generation',-1))==d.ui_generation:
            with d.condition:d.canvas_views.clear()
            shown=self.base_show(raw,out,meta)
            if shown and d._show==self.first_result_show:d._show=self.base_show
            return shown
        return self.base_show(raw,out,meta)
    def header(self,value):
        self.state.assets.headers=ratio_header(self.state.assets,value)
        with self.display.condition:self.display.canvas_views.clear()
    def cancel_for_request(self,layout_only,generation):
        if self.pending is not None:
            if layout_only:self.pending['generation']=generation
            else:self.fail('page_changed',reopen=False)
        self.open_requested=False;self.snapshot_task=None
        if self.display._show in (self.capture_show,self.first_result_show):self.display._show=self.base_show
    def open(self,generation,error=None):
        d=self.display
        with d.condition:
            if generation!=d.ui_generation or d.inspection.kind or d.target_switch is not None or self.pending is not None:return False
            latest=getattr(d,'latest_meta',{})
            if latest.get('state') not in ('CURRENT','HELD','MANUAL','MANUAL_HELD') or latest.get('ui_generation')!=generation:return False
            mode=self.mode();current=self.registry.applied[mode][0]
            draft=current if current in PRESETS else 'custom'
            width,height=('3','4') if current in PRESETS else current.split(':')
            self.model=dict(mode=mode,current=current,draft=draft,width=width,height=height,field=None,error=error)
            self.open_requested=generation;d._show=self.capture_show
            if d.ui_view=='snapshot':d.inspection_restore=True
            d.condition.notify_all()
        return True
    def capture_show(self,raw,out,meta):
        d=self.display
        if int(meta.get('ui_generation',-1))!=self.open_requested or out is None:return self.base_show(raw,out,meta)
        value,revision=self.registry.applied[self.model['mode']]
        actual_revision=revision_of(meta)
        if actual_revision!=revision and not (value=='original' and actual_revision==0):return False
        previous=d._submit;captured=None
        async def submit(frame):
            nonlocal captured
            # All reads precede the official handoff; exactly one event copy.
            captured=np.array(frame,dtype=np.uint8,copy=True,order='C')
            result=await previous(frame)
            return result
        d._submit=submit
        try:shown=self.base_show(raw,out,meta)
        finally:
            if d._submit is submit:d._submit=previous
        with d.condition:
            if shown and captured is not None and self.open_requested==d.ui_generation:
                captured.setflags(write=False);ins=d.inspection;ins.clear_locked()
                self.captured=captured
                ins.kind='ratio';ins.generation=d.ui_generation;ins.source=captured;ins.source_rect=(0,0,1280,720)
                ins.meta=dict(self.model);ins.dirty=True;ins.opened+=1;d.pending=None
                self.open_requested=False;d._show=self.base_show;d.condition.notify_all()
        return shown
    def controls(self):
        m=self.model;result={'cancel':(846,637,128,56),'apply':(986,637,128,56),'reset':(1126,99,128,56)}
        if m.get('field') is not None:
            for i,key in enumerate(list('123456789.0')+['del']):result['key_'+key]=(846+(i%3)*140,280+(i//3)*60,126,52)
        else:
            for i,key in enumerate(list(PRESETS)+['custom']):result['preset_'+key]=(846+(i%3)*140,205+(i//3)*96,126,82)
        if m['draft']=='custom':
            fy=204 if m.get('field') is not None else 402
            result.update(width=(876,fy,96,48),height=(1022,fy,96,48))
        return result
    def target(self,p):return next((key for key,r in self.controls().items() if inside__v73_ratio_ui(p,r)),None)
    def touch(self,event,generation):
        d=self.display
        if d.inspection.kind!='ratio':
            if d.inspection.kind is not None:return None
            if not inside__v73_ratio_ui(event.get('press'),ENTRY):return None
            if self.state.page=='home' or self.state.ticket.phase!='running':return None
            if event['phase']=='press':return dict(target='ratio_open',reason='await_release')
            origin=event.get('press_outcome') or {}
            accepted=bool(origin.get('target')=='ratio_open' and origin.get('generation')==generation and inside__v73_ratio_ui(event.get('release'),ENTRY) and event.get('peak_motion',0)<=32 and self.open(generation))
            return dict(target='ratio_open',accepted=accepted,consumed=True,reason='ratio_opened' if accepted else 'ratio_unavailable')
        if event['phase']=='cancel':return dict(consumed=True,reason='ratio_contact_cancelled')
        key=self.target(event.get('press'))
        # Reversible draft edits respond to the initial contact; noisy later
        # DOWN coordinates cannot discard an intended light tap. A draft never
        # changes the live mapping. Apply/reset still require a valid release.
        if event['phase']=='press' and key and (key.startswith(('preset_','key_')) or
                key in ('width','height','cancel') or key=='reset' and self.model.get('field') is not None):
            self.action(key)
            return dict(target='ratio_'+key,accepted=True,consumed=True,
                reason='ratio_cancel_press' if key=='cancel' else 'ratio_draft_press')
        if event['phase']=='press':return dict(target='ratio_'+(key or 'background'),consumed=False,reason='await_release')
        origin=event.get('press_outcome') or {}
        accepted=bool(key and origin.get('generation')==generation and origin.get('target')=='ratio_'+key and self.target(event.get('release'))==key and event.get('peak_motion',0)<=32)
        if accepted:self.action(key)
        return dict(target='ratio_'+(key or 'background'),accepted=accepted,consumed=True,reason='ratio_control' if accepted else 'ratio_contact_rejected')
    def redraw(self):
        with self.display.condition:
            if self.display.inspection.kind=='ratio':
                self.display.inspection.meta=dict(self.model);self.display.inspection.dirty=True;self.display.condition.notify_all()
    def close_panel(self):
        d=self.display
        with d.condition:
            d.inspection.clear_locked();d.canvas_views.clear();d.layouts.clear()
            d.inspection_restore=bool(d.ui_view=='snapshot' and d.last_static_packet is not None)
            d.condition.notify_all()
        if self.pending is None:self.captured=None
    def action(self,key):
        m=self.model
        if key=='cancel':self.close_panel();return
        if key=='reset' and m.get('field') is not None:m['field']=None
        elif key=='reset':self.apply('original');return
        elif key=='apply':
            try:value=normalize(m['width']+':'+m['height'] if m['draft']=='custom' else m['draft'])
            except ValueError:m['error']='invalid'
            else:self.apply(value);return
        elif key.startswith('preset_'):m['draft']=key[7:];m['field']=None;m['error']=None
        elif key in ('width','height'):m['field']=key;m['replace_next']=True
        elif key.startswith('key_') and m.get('field') is not None:
            field=m['field'];char=key[4:];text=m[field]
            if char=='del':text=text[:-1]
            else:
                if m.pop('replace_next',False):text=''
                if len(text)<6 and (char!='.' or '.' not in text):text+=char
            m[field]=text;m['error']=None
        self.redraw()
    def apply(self,value):
        with self.display.condition:
            if self.pending is not None:return
            mode=self.mode()
            if value==self.registry.applied[mode][0]:self.close_panel();return
            revision=self.registry.request(mode,value)
            self.pending=dict(mode=mode,value=value,revision=revision,generation=self.display.ui_generation,began=time.perf_counter(),shown=False)
            self.previous_offer=self.display.offer;self.display.offer=self.pending_offer
            self.display._show=self.pending_show
            self.close_panel();self.header('busy')
            checkpoint('OUTPUT_RATIO_REQUEST',profile=mode,value=value,revision=revision,event_only=True)
        if self.state.page=='snapshot':
            with self.state.condition:self.snapshot_task=dict(self.pending);self.state.condition.notify_all()
    def restore_offer(self):
        if self.display.offer==self.pending_offer:self.display.offer=self.previous_offer
    def pending_offer(self,out,meta,raw=None,**kwargs):
        with self.display.condition:pending=self.pending;previous=self.previous_offer
        if pending is not None and int(meta.get('ui_generation',-1))==pending['generation']:
            expected=0 if pending['value']=='original' else pending['revision']
            if out is not None and revision_of(meta)==expected and meta.get('state') in ('CURRENT','MANUAL'):
                pending['candidate_ready']=True
            elif meta.get('plan_failure') and not pending.get('candidate_ready'):
                self.fail('mapping_proof_rejected')
        return previous(out,meta,raw,**kwargs)
    def fail(self,reason,reopen=True):
        pending=self.pending
        if pending is None:return
        self.registry.rollback(pending['mode']);self.pending=None;self.snapshot_task=None
        self.restore_offer()
        self.display._show=self.base_show;self.header(self.registry.applied[pending['mode']][0])
        checkpoint('OUTPUT_RATIO_REJECTED',revision=pending['revision'],reason=reason,previous_setting_retained=True)
        if reopen:self.open(self.display.ui_generation,error='failed')
    def pending_show(self,raw,out,meta):
        with self.display.condition:p=self.pending
        if p is None:return self.base_show(raw,out,meta)
        expected_revision=0 if p['value']=='original' else p['revision']
        matching=(int(meta.get('ui_generation',-1))==p['generation'] and out is not None and revision_of(meta)==expected_revision and meta.get('state') in ('CURRENT','MANUAL'))
        if not matching:
            if time.perf_counter()-p['began']>6.:self.fail('no_verified_new_output');return False
            if not p['shown'] and self.captured is not None and p['generation']==self.display.ui_generation:
                d=self.display;frame,canvas=d._acquire_canvas('ratio_pending',p['generation'])
                canvas[:]=self.captured;canvas[:72]=d.ui_assets.headers[d.ui_view]
                key=int(frame.physical_address);d.canvas_views[key]=('ratio_pending',p['generation']);d.layouts[key]=(None,None)
                d.loop.run_until_complete(d._submit(frame));p['shown']=True
                return True
            return False
        expected=dimensions(p['value'])
        actual=tuple(out.shape[1::-1])
        if actual!=(expected or actual) or p['value']=='original' and actual not in ((362,512),(512,362)):
            self.fail('output_size_mismatch');return False
        self.header(p['value'])
        try:shown=self.base_show(raw,out,meta)
        except BaseException:
            self.fail('submission_failed',reopen=False);raise
        if shown and matching and self.pending is p:
            with self.display.condition:
                if self.pending is not p:return shown
                if not self.registry.finish(p['mode'],p['revision']):
                    self.fail('setting_revision_changed',reopen=False);return shown
                self.pending=None;self.display._show=self.base_show
                self.restore_offer()
                if p['value']=='original':self.display.last_submitted_layout=int(meta.get('layout_generation',0))%SHIFT
                self.captured=None
            checkpoint('OUTPUT_RATIO_APPLIED',profile=p['mode'],value=p['value'],revision=p['revision'],native_size=list(out.shape[1::-1]),complete_submission=True)
        return shown
    def reprocess_snapshot(self,context,task):
        """Serviced only by the existing P1/app owner, while the still page waits."""
        context.check();d=self.display;fixed=context.ticket.fixed_input
        if fixed is None or task['generation']!=context.generation:
            self.fail('fixed_source_unavailable');return
        with d.condition:previous=dict(d.latest_meta)
        if previous.get('camera_sequence')!=fixed.sequence or len(previous.get('corners',()))!=4:
            self.fail('fixed_source_pair_mismatch');return
        workspace=None;job=None
        try:
            context.backend._assert_owner()
            orientation=make_orientation('auto_two',(362,512),2)
            proposal=orientation.propose(previous['corners'],fixed.image.shape,0,timestamp=float(fixed.ready))
            size=tuple(proposal.size or (362,512));workspace=PlanWorkspace()
            tiles,detail=make_plan(proposal.quad,fixed.image.shape,size,proof_cache=ProofCache(128),workspace=workspace)
            orient=orientation.commit(proposal);row=dict(previous)
            row.update(index=int(previous.get('index',1))+1,state='MANUAL' if self.mode()=='manual' else 'CURRENT',
                corners=tuple(map(tuple,proposal.quad.tolist())),output_size=size,tiles=len(tiles),
                layout_generation=orient['layout_generation'],orientation=orient.get('orientation'),
                capture_ready_at=fixed.ready,color_mode=fixed.color_mode,ui_generation=context.generation)
            job=FrameJob(row['index'],fixed.frame(),tuple(tiles),size,row['state'],row['corners'],fixed.color_mode,fixed.image,row,source_owned=True)
            context.check();image,owner=context.backend.execute(job);context.check()
            with d.condition:
                d.frozen_generation=None;d.snapshot_receipt=None
            row.update(owner)
            d.offer(image,row,fixed.image,raw_owned=True,output_reference=context.backend.output_reference(image))
            receipt=d.wait_snapshot(context.generation,row['index'],fixed.sequence,context.cancel)
            if receipt is None:context.check();raise RuntimeError('Ratio snapshot was not submitted')
            checkpoint('SNAPSHOT_RATIO_REMAP',generation=context.generation,revision=task['revision'],
                source_sequence=fixed.sequence,camera_opened=False,redetection=False,hardware_proof_preserved=True)
        except ValueError as exc:self.fail(str(exc))
        finally:
            if job is not None:job.release_source()
            if workspace is not None:workspace.close()


# ======================================================================
# ===== [11/13] v74_hold =====
# ======================================================================


"""Event-owned right-view hold. Only the existing HDMI owner touches pixels."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
from ui import CAPTURE_RECT as CAPTURE_RECT; from ui import ALBUM_RECT as ALBUM_RECT
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class HoldUnavailable(RuntimeError):pass

def load_assets__v74_hold(assets,root):
    value=cv2.imread(str(Path(root)/'v74_hold_badge.png'),cv2.IMREAD_COLOR)
    if value is None or value.shape!=(56,248,3):raise ValueError('Invalid hold badge')
    value.setflags(write=False);assets.hold_badge=value[:28];assets.hold_badge_small=value[28:,:48]

def inside__v74_hold(point,rect):
    return point is not None and rect is not None and rect[0]<=point[0]<rect[0]+rect[2] and rect[1]<=point[1]<rect[1]+rect[3]

class HoldController:
    def __init__(self,state,display):
        self.state=state;self.display=display;self.base_show=display._show
        self.handler=self.show;self.active=None;self.serial=0
        self.cleanup=None;self.clean_handler=self.acquire_clean;self.last_acquire=display._acquire_canvas
    def stop_cleanup_locked(self):
        d=self.display;record=self.cleanup
        if record is not None:
            if d._acquire_canvas==self.clean_handler:d._acquire_canvas=record['base']
            self.last_acquire=record['base'];self.cleanup=None
    def acquire_clean(self,*args,**kwargs):
        record=self.cleanup
        if record is None:return self.last_acquire(*args,**kwargs)
        frame,canvas=record['base'](*args,**kwargs);d=self.display
        with d.condition:
            if self.cleanup is record:
                key=int(frame.physical_address);patch=record['patches'].pop(key,None)
                if patch is not None:
                    rect,pixels,normal_token,hold_token=patch
                    if d.canvas_views.get(key)==hold_token:
                        x,y,w,h=rect;canvas[y:y+h,x:x+w]=pixels
                        d.canvas_views[key]=normal_token
                record['calls']+=1
                if not record['patches'] or record['calls']>=record['limit']:self.stop_cleanup_locked()
        return frame,canvas
    def current(self,session):
        d=self.display
        with d.condition:
            return self.active is session and session['generation']==d.ui_generation and session['view']==d.ui_view and not d.stop
    def begin(self,event,generation):
        d=self.display;s=self.state
        with d.condition:
            point=event.get('press')
            if point is None or point[1]<72 or inside__v74_hold(point,CAPTURE_RECT) or inside__v74_hold(point,ALBUM_RECT):return False
            if (self.active is not None or s.stopping or s.page not in ('compare','rectified') or
                    s.ticket.phase!='running' or d.ui_view!=s.page or generation!=d.ui_generation or
                    d.stop or d.error is not None or d.inspection.kind is not None or
                    d.inspection.zoom_requested is not None or d.target_switch is not None or d._show!=self.base_show):return False
            ratio=s.ratio;media=d.media
            if ratio is not None and (ratio.pending is not None or ratio.open_requested):return False
            if media is not None and (media.active or getattr(media,'capture_request',None) is not None):return False
            if not d.samples:return False
            sample=d.samples[-1]
            if sample.get('ui_generation')!=generation or sample.get('ui_view')!=s.page or sample.get('state') not in ('CURRENT','HELD','MANUAL','MANUAL_HELD'):return False
            details=sample.get('panel_native_details',{}).get('right',{})
            rect=details.get('destination_rect');shape=details.get('source_shape')
            if not rect or not shape or not inside__v74_hold(point,rect):return False
            self.stop_cleanup_locked()
            self.serial+=1
            session=dict(serial=self.serial,generation=generation,view=s.page,contact_id=event.get('contact_id'),
                press_rect=tuple(rect),press_index=sample.get('index'),press_sequence=sample.get('camera_sequence'),
                began=time.perf_counter(),image=None,source_index=None,source_sequence=None,source_kind=None,
                submitted=0,source_frames=0,cache_copies=0,visible=False,patches={})
            self.active=session;d._show=self.handler;d.current_times.clear()
            s.tap_contact=None
            checkpoint('UI_RIGHT_HOLD_BEGIN',generation=generation,view=s.page,contact_id=session['contact_id'],
                rect=list(rect),press_index=session['press_index'],event_only=True,left_remains_live=s.page=='compare')
        return True
    def end(self,reason):
        d=self.display
        with d.condition:
            if reason in ('page_request','touch_error','application_stop','view_changed'):self.stop_cleanup_locked()
            session=self.active
            if session is None:return
            self.active=None
            if d._show==self.handler:d._show=self.base_show
            if reason not in ('page_request','touch_error','application_stop','view_changed','display_error') and session['patches']:
                self.stop_cleanup_locked();base=d._acquire_canvas;self.last_acquire=base
                self.cleanup=dict(base=base,patches=dict(session['patches']),calls=0,limit=max(12,len(session['patches'])*4+4))
                d._acquire_canvas=self.clean_handler
            d.current_times.clear();d.condition.notify_all()
        checkpoint('UI_RIGHT_HOLD_END',generation=session['generation'],view=session['view'],reason=reason,
            duration_s=time.perf_counter()-session['began'],source_frames=session['source_frames'],
            frozen_canvas_submissions=session['submitted'],right_cache_copies=session['cache_copies'],
            source_kind=session['source_kind'],live_handler_restored=d._show==self.base_show)
    def touch(self,event,generation):
        phase=event['phase'];session=self.active
        if session is not None and phase=='press' and event.get('contact_id')!=session['contact_id']:
            self.end('new_contact');session=None
        if session is not None:
            if phase=='cancel' or phase=='release' and event.get('contact_id')==session['contact_id']:
                self.end('touch_cancelled' if phase=='cancel' else 'released')
                return dict(target='hold_view',accepted=True,consumed=True,reason='right_hold_released')
            return dict(target='hold_view',accepted=False,consumed=False,reason='right_hold_contact_owned')
        if phase=='press' and self.begin(event,generation):
            # The parser must deliver release even when the finger leaves the image.
            return dict(target='hold_view',accepted=True,consumed=False,reason='right_hold_started')
        return None
    def show(self,raw,out,meta):
        session=self.active
        if session is None:return self.base_show(raw,out,meta)
        if not self.current(session):
            self.end('view_changed');return self.base_show(raw,out,meta)
        if int(meta.get('ui_generation',-1))!=session['generation'] or meta.get('ui_view',session['view'])!=session['view']:return False
        session['source_frames']+=1
        if session['view']=='rectified' and session['visible']:return False
        was_visible=session['visible']
        try:
            if session['image'] is None and out is not None and meta.get('state') in ('CURRENT','HELD','MANUAL','MANUAL_HELD'):
                # This source is pinned by the existing display slot for this call.
                # The extra image is ordinary RAM and keeps no camera/P1/CMA lease.
                h,w=out.shape[:2];image=np.empty((h,w,3),np.uint8)
                bgra_bgr_into(out,image,(0,0,w,h));image.setflags(write=False)
                session.update(image=image,source_index=meta.get('index'),source_sequence=meta.get('camera_sequence'),source_kind='completed_output')
            if not self.current(session):return False
            shown=render_frozen(self.display,raw,out,meta,self,session)
            if shown and not was_visible:
                checkpoint('UI_RIGHT_HOLD_PRESENTED',generation=session['generation'],view=session['view'],
                    frozen_source_index=session['source_index'],frozen_source_sequence=session['source_sequence'],
                    source_kind=session['source_kind'],left_live=session['view']=='compare',new_correction_counted=False)
            return shown
        except HoldUnavailable:
            # Claim this contact through UP, but keep live input responsive.
            with self.display.condition:
                if self.display._show==self.handler:self.display._show=self.base_show
            checkpoint('UI_RIGHT_HOLD_UNAVAILABLE',generation=session['generation'],reason='no_owned_complete_result',contact_remains_owned=True)
            return self.base_show(raw,out,meta)
        except BaseException:
            self.end('display_error');raise

# BEGIN EVENT-ONLY FROZEN RENDERER
def render_frozen(self,raw,live_out,meta,controller,session):
    out=session['image']
    view=meta.get('ui_view','compare');generation=int(meta.get('ui_generation',0))
    if self.ui_assets is not None and generation!=self.ui_generation:return False
    began=time.perf_counter();cpu=time.thread_time()
    frame,canvas=self._acquire_canvas(view if meta['state']=='STARTING' else None,generation)
    acquired=time.perf_counter();acquired_cpu=time.thread_time()
    try:
        h,w=self.mode[1],self.mode[0];mid=w//2
        # Before acquisition (and after complete loss), show live input
        # even on the result-only page so placement remains visible.
        single=view=='rectified' and out is not None
        if single:raw=None
        left=native_display_rect(self.mode,fit_panel_shape(self.mode,raw.shape[:2]),0) if raw is not None else None
        if out is not None and single:
            oh,ow=out.shape[:2]
            if ow>w or oh>h-64:raise ValueError('Rectified native image exceeds HDMI canvas')
            right=((w-ow)//2,36+(h-64-oh)//2,ow,oh)
        else:right=native_display_rect(self.mode,out.shape[:2],1) if out is not None else None
        key=int(frame.physical_address);old=self.layouts.get(key)
        if out is None:
            # No new output: a recycled, now-owned canvas may contain a complete
            # prior right image. All reads precede any clear or device handoff.
            prior=None if old is None else old[1]
            token=self.canvas_views.get(key)
            if prior!=session['press_rect'] or not token or len(token)!=3 or token[:2]!=(view,generation):raise HoldUnavailable()
            px,py,pw,ph=prior
            out=np.array(canvas[py:py+ph,px:px+pw],dtype=np.uint8,copy=True,order='C')
            out.setflags(write=False);session.update(image=out,source_kind='owned_complete_canvas')
            single=view=='rectified';left=None if single else left;right=prior
            if single:raw=None
        page_token=(view,generation,'right_hold',session['serial'],self.target_notice)
        startup_phase=meta.get('ui_startup_phase');startup_action=None
        if startup_phase in ('preparing','placement'):
            startup_action=('confirmed' if meta.get('placement_confirmed') or not meta.get('placement_required') else 'confirm')
        elif startup_phase=='acquiring':startup_action='acquiring'
        if startup_action is not None:page_token=page_token+(startup_action,)
        prior_token=self.canvas_views.get(key);normal_token=(view,generation,self.target_notice)
        page_changed=self.ui_assets is not None and prior_token not in (page_token,normal_token)
        first_hold_buffer=prior_token!=page_token
        if old is None or page_changed:canvas.fill(0)
        else:
            for prior,new in zip(old,(left,right)):
                if prior is not None and prior!=new:
                    x,y,rw,rh=prior;canvas[y:y+rh,x:x+rw].fill(0)
        # Repaint text backgrounds (including antialias fringes), and only
        # changed image regions, rather than clearing720p every submission.
        ui_began=time.perf_counter();ui_header_restore_s=0.
        if self.ui_assets is None:canvas[:36].fill(0)
        else:
            if page_changed:
                canvas[:72]=(self.ui_assets.snapshot_busy if view=='snapshot' and out is None
                    else self.ui_assets.ratio_original_headers[view] if out is None else self.ui_assets.headers[view])
                if startup_action is not None:
                    canvas[:72,1000:1280]=self.ui_assets.placement_controls[startup_action]
                if view in ('compare','rectified'):
                    canvas[:72,380:580]=self.ui_assets.refind_controls[
                        'preparing' if startup_phase=='preparing' else 'ready']
                    if self.target_notice!='idle':
                        canvas[78:118,:640]=self.ui_assets.target_hints[(view,self.target_notice)]
                ui_header_restore_s=time.perf_counter()-ui_began
            # Cached top-left return pixels are not touched on warm buffers.
            label_end=1000 if view in ('compare','rectified','snapshot') else w
            # V82 cached touch controls occupy the header; dynamic labels
            # stay in the existing footer and never overwrite hit targets.
            self.canvas_views[key]=page_token
            if len(self.canvas_views)>16:self.canvas_views={key:page_token}
        canvas[h-28:].fill(0)
        clear_end=time.perf_counter();clear_cpu=time.thread_time()
        raw_backend='none';input_convert_s=0.;output_convert_s=0.;scale_s=0.
        left_detail={};right_detail={};left_panel_s=right_panel_s=0.;left_cpu_s=right_cpu_s=0.
        corner_draw_s=0.;corner_draw_cpu_s=0.
        if raw is not None:
            x,y,rw,rh=left;t=time.perf_counter();tc=time.thread_time()
            # Startup must not synchronously compile the library whose
            # readiness it is trying to show. Only INITIALIZING can use
            # this temporary path; normal display remains unchanged.
            startup_fallback=False
            if meta['state']=='INITIALIZING':
                startup_fallback=_LIB is None
            if startup_fallback:
                if meta['color_mode']==0:
                    cv2.cvtColor(raw,cv2.COLOR_YUV2BGR_YUY2,dst=canvas[y:y+rh,x:x+rw])
                else:
                    from core import model_bgr as model_bgr
                    canvas[y:y+rh,x:x+rw]=model_bgr(raw)
            else:
                #   ⚠️ 2026-10-28：`left` 是 `fit_panel_shape()` 算出来的显示尺寸
                #      （800x600 源图 ⇒ 640x480 槽），而 `yuyv_bgr_into()` 要求
                #      **矩形尺寸必须等于源图尺寸**，否则抛
                #      `Native BGR rectangle does not match source/frame bounds`。
                #      ⇒ 800x600 下按"右图冻结/查看"手势会**直接崩**。这里补缩放分支。
                done=False
                if raw.shape[:2]!=(rh,rw):
                    fused=getattr(self,'_fused',None)
                    if fused is None and not getattr(self,'_fused_failed',False):
                        try:
                            fused=FusedDisplay();self._fused=fused
                        except BaseException:
                            self._fused_failed=True;fused=None
                    if fused is not None:
                        try:fused.scale(0,raw,int(meta['color_mode']),canvas,left);done=True
                        except BaseException:done=False
                    if not done:
                        from tracking import yuyv_preview_into__v31_native as yuyv_preview_into
                        if self._scaled is None or self._scaled.shape[:2]!=(rh,rw):
                            self._scaled=np.empty((rh,rw,3),np.uint8)
                        if yuyv_preview_into(raw,int(meta['color_mode']),self._scaled,
                                fast=bool(getattr(self,'_preview_nearest',True))):
                            canvas[y:y+rh,x:x+rw]=self._scaled;done=True
                        else:
                            ih,iw=raw.shape[:2];y0=max(0,(ih-rh)//2);x0=max(0,(iw-rw)//2)
                            yuyv_bgr_into(np.ascontiguousarray(raw[y0:y0+rh,x0:x0+rw]),
                                meta['color_mode'],canvas,left)
                if not done:yuyv_bgr_into(raw,meta['color_mode'],canvas,left)
            input_convert_s=time.perf_counter()-t
            raw_backend='startup_OpenCV_or_model_CSC' if startup_fallback else 'native_YUYV_to_BGR_scaled_or_1to1'
            left_detail=dict(direct=True,resize_used=False,crop_used=False,backend=raw_backend,
                source_shape=list(raw.shape),destination_rect=list(left),polyphase_5_4_used=False)
            left_panel_s=time.perf_counter()-t;left_cpu_s=time.thread_time()-tc
            t=time.perf_counter();tc=time.thread_time()
            corners=meta.get('corners',())
            #   ⚠️ 2026-10-28：四角是【源图坐标】，左画面是【缩放后】的 ⇒ 先缩放再加偏移。
            _sx,_sy=rw/float(raw.shape[1]),rh/float(raw.shape[0])
            _scaled_pts=(rw,rh)!=tuple(raw.shape[1::-1])
            if len(corners)==4:
                points=np.asarray(corners,np.float32).copy()
                if _scaled_pts:points=np.stack([points[:,0]*_sx,points[:,1]*_sy],axis=1)
                points+=np.array([x,y],np.float32)
                color=(0,240,0) if meta['state']=='CURRENT' else (255,200,70) if meta['state']=='MANUAL' else (0,210,255)
                # A single colored outline preserves HELD status without
                # dozens of Python/NumPy/cv2.line calls on each frame.
                cv2.polylines(canvas,[np.rint(points).astype(np.int32)],True,color,2,cv2.LINE_AA)
            candidate=meta.get('candidate_corners',())
            if (not corners and len(candidate)==4 and
                    0<=time.perf_counter()-meta.get('candidate_ready_at',0.)<=.9):
                cq=np.asarray(candidate,np.float32)
                if _scaled_pts:cq=np.stack([cq[:,0]*_sx,cq[:,1]*_sy],axis=1)
                points=np.rint(cq+np.array([x,y],np.float32)).astype(np.int32)
                cv2.polylines(canvas,[points],True,(70,70,255),2,cv2.LINE_AA)
            corner_draw_s=time.perf_counter()-t;corner_draw_cpu_s=time.thread_time()-tc
        if out is not None:
            x,y,rw,rh=right;t=time.perf_counter();tc=time.thread_time()
            if first_hold_buffer or page_changed or old is None or old[1]!=right:
                canvas[y:y+rh,x:x+rw]=out
                badge=self.ui_assets.hold_badge if rw>=248 else self.ui_assets.hold_badge_small
                bh,bw=badge.shape[:2]
                if rw>=bw and y-bh-4>=72:
                    bx=x+(rw-bw)//2;by=y-bh-4
                    underlay=np.array(canvas[by:by+bh,bx:bx+bw],copy=True,order='C');underlay.setflags(write=False)
                    session['patches'][key]=((bx,by,bw,bh),underlay,normal_token,page_token)
                    canvas[by:by+bh,bx:bx+bw]=badge
                session['cache_copies']+=1
            output_convert_s=0.
            right_detail=dict(direct=True,resize_used=False,crop_used=False,backend='ordinary_RAM_frozen_BGR',
                source_shape=list(out.shape),destination_rect=list(right),right_frozen=True)
            right_panel_s=time.perf_counter()-t;right_cpu_s=time.thread_time()-tc
        self.layouts[key]=(left,right)
        if len(self.layouts)>16:self.layouts={key:(left,right)}
        now=time.perf_counter()
        while self.submit_times and self.submit_times[0]<now-2.:self.submit_times.popleft()
        times=list(self.submit_times)
        rate=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.
        with self.condition:
            while self.current_times and self.current_times[0]<now-2.:self.current_times.popleft()
            # Fixed2s includes CURRENT only; decays during lost/held updates.
            current_rate=len(self.current_times)/2.
        age=max(0.,now-meta.get('capture_ready_at',now))*1000
        verified=float(meta.get('verified_at',0.));h_age=max(0.,now-verified)*1000 if verified>0 else None
        label_x=184 if self.ui_assets is not None else 8
        if not single and self.ui_assets is None:
            label=('ORIGINAL seq=%d' if view=='snapshot' else 'INPUT seq=%d')%meta.get('camera_sequence',-1)
            cv2.putText(canvas,label,(label_x,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
        heading=('SNAPSHOT '+('READY' if out is not None else 'CAPTURING')) if view=='snapshot' else 'RECTIFIED '+meta['state']
        if self.ui_assets is None:cv2.putText(canvas,heading,(label_x if single else mid+8,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
        status='CORR %.1f | DISP %.1f | CUR %.1f | CAP %.0fms | H %s'%(meta.get('correction_fps',0.),rate,current_rate,age,
            ('%.0fms'%h_age) if h_age is not None and meta['state'] in ('CURRENT','HELD') else '--')
        if meta.get('v86_motion_authority'):
            status=status.replace('CUR ', 'TRACK ')
        if view=='snapshot':
            status=('SINGLE FRAME | seq=%d | RECAPTURE OR RETURN'%meta.get('camera_sequence',-1)
                if out is not None else 'SINGLE FRAME | WAITING FOR VERIFIED CORNERS')
        if meta.get('admission_mode')=='manual':
            status='MANUAL %s | M-CORR %.1f | DISP %.1f | %s'%(meta.get('manual_tracking',''),
                meta.get('manual_fps',0.),rate,('MOTION WATCH / AUTO RESUME' if meta.get('manual_fixed_watch') else 'RECALIBRATE AFTER MOVING')
                if meta.get('manual_tracking')=='FIXED' else 'FULL FB TRACK / FINITE HOLD')
            if meta.get('manual_tracking')=='SNAPSHOT':status='MANUAL SINGLE FRAME | RECAPTURE, RECALIBRATE OR RETURN'
        if meta['state']=='INITIALIZING':
            status='SETUP %.0fs | AUTO LOCATE WHEN READY | RAW VIEW ACTIVE'%meta.get('native_setup_elapsed_s',0.)
        elif meta['state']=='PLACEMENT':status='READY | AUTOMATIC CURRENT-FRAME LOCALIZATION'
        status=('INPUT LIVE | RECTIFIED FROZEN | RELEASE TO RESUME' if not single else 'RECTIFIED FROZEN | RELEASE TO RESUME')
        status_x=8
        if self.ui_assets is not None:
            state=meta['state'] if meta['state'] in self.ui_assets.status_badges else 'SEARCHING'
            if state=='MANUAL' and meta.get('manual_tracking')=='FIXED':state='MANUAL_FIXED'
            canvas[h-28:,:320]=self.ui_assets.status_badges[state];status_x=326
        cv2.putText(canvas,status,(status_x,h-9),cv2.FONT_HERSHEY_SIMPLEX,.40,(255,255,255),1,cv2.LINE_AA)
        if self.ui_assets is not None and generation!=self.ui_generation:
            return False
        if self.media is not None:
            if self.inspection.kind is None:self.media.render_live(canvas,key,page_changed)
            with self.condition:
                if self.media.active:return False
        if not controller.current(session):return False
        composed=time.perf_counter();composed_cpu=time.thread_time();polls=self.loop.run_until_complete(self._submit(frame));end=time.perf_counter()
        if meta.get('inspection_redraw'):return True
        sample=dict(index=meta['index'],camera_sequence=meta.get('camera_sequence'),state='DISPLAY_FROZEN',source_state=meta['state'],epoch=meta['epoch'],
            compose_s=composed-began,compose_thread_cpu_s=composed_cpu-cpu,
            frame_acquire_s=acquired-began,frame_acquire_thread_cpu_s=acquired_cpu-cpu,
            clear_layout_s=clear_end-acquired,clear_layout_thread_cpu_s=clear_cpu-acquired_cpu,
            left_panel_s=left_panel_s,left_panel_thread_cpu_s=left_cpu_s,
            right_panel_s=right_panel_s,right_panel_thread_cpu_s=right_cpu_s,
            panel_native_details=dict(left=left_detail,right=right_detail),corner_draw_s=corner_draw_s,corner_draw_thread_cpu_s=corner_draw_cpu_s,
            held_outline_backend='single_polylines',
            other_compose_s=max(0.,composed-clear_end-left_panel_s-right_panel_s-corner_draw_s),
            current_display_fps_2s=current_rate,display_rate_window_s=2.,
            display_backend='native_direct_color_convert_1to1',display_frontend_version=79,
            capture_age_ms=age,H_age_ms=h_age,
            ui_view=view,ui_generation=generation,ui_header_restore_s=ui_header_restore_s,
            display_scale_enabled=False,display_crop_enabled=False,native_substage_times_available=False,
            input_convert_s=input_convert_s,output_convert_s=output_convert_s,scale_s=scale_s,
            split_conversion_times_available=True,
            conversion_timing_scope='direct conversion wrappers; no resampling; native-only substage timers unavailable',
            vdma_submit_thread_cpu_s=time.thread_time()-composed_cpu,
            vdmasubmit_polls=polls,vdma_submit_s=end-composed,submitted_at=end,display_thread_cpu_s=time.thread_time()-cpu,
            capture_to_submit_s=end-meta.get('capture_ready_at',end),same_frame=False,input_backend=raw_backend,
            right_frozen=True,left_live=raw is not None,frozen_source_index=session['source_index'],frozen_source_sequence=session['source_sequence'],frozen_source_kind=session['source_kind'],
            layout_generation=int(meta.get('layout_generation',0)),orientation=meta.get('orientation'))
        snapshot_receipt=None;layout_receipt=None
        with self.condition:
            self.panels_submitted+=int(raw is not None);session['submitted']+=1;session['visible']=True
            # A frozen right image is never a new correction submission.
            if raw is not None or out is not None:self.submit_times.append(end)
            self.samples.append(sample)
            # Retain a reference to the already owned source; no pixel copy.
            self.tap_source=(raw,meta,left,end)
            stats=self.epoch_stats.setdefault(meta['epoch'],dict(submitted=0,current=0,panels=0,replaced=0,dropped=0))
            stats['right_frozen_canvas_submitted']=stats.get('right_frozen_canvas_submitted',0)+1
            stats['panels']+=int(raw is not None)
            if raw is not None or out is not None:stats['last_submitted_at']=end
            command=self.ui_layout_pending
            if (command is not None and meta['state']!='STARTING' and
                    (command[0],command[1])==(int(meta.get('ui_generation',0)),view)):
                layout_receipt=dict(page=view,generation=command[0],layout_only=True,
                    request_to_submit_s=end-command[2],camera_restarted=False,tracker_reinitialized=False,
                    same_frame=False,index=meta['index'],camera_sequence=meta.get('camera_sequence'),
                    physical_scan_time_measured=False)
                self.ui_layout_pending=None
        if snapshot_receipt is not None:checkpoint('SNAPSHOT_HDMI_FROZEN',**snapshot_receipt)
        if layout_receipt is not None:checkpoint('UI_PAGE_PRESENTED',**layout_receipt)
        if meta['index']>=0 and (meta['index']%60==0 or end-began>.12):checkpoint('HDMI_FRAME_DETAIL',**sample)
        return True
    finally:
        canvas=None;frame=None


# ======================================================================
# ===== [12/13] v741_reading =====
# ======================================================================


"""Reading-only geometry, contact ownership and owner-side event rendering."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def geometry(image,focus,factor):
    h,w=image.shape[:2];span=max(16,min(w,h,392//factor))
    sx=max(0,min(w-span,int(round(focus[0]))-span//2))
    sy=max(0,min(h-span,int(round(focus[1]))-span//2))
    side=min(392,span*factor)
    return (sx,sy,span),(716+(512-side)//2,148+(392-side)//2,side,side)


def inside__v741_reading(point,rect):
    if point is None or len(point)!=2 or not all(math.isfinite(v) for v in point):return False
    x,y,w,h=rect;return x<=point[0]<x+w and y<=point[1]<y+h


class ReadingPan:
    def __init__(self,inspection):
        self.inspection=inspection;self.contact=None;self.canvases={}
    def clear_locked(self):
        self.contact=None;self.canvases.clear()
    def cancel_locked(self,contact_id=None):
        if self.contact is None or contact_id is not None and self.contact['id']!=contact_id:return False
        self.contact=None;return True
    def target_locked(self,point):
        i=self.inspection
        if inside__v741_reading(point,i.source_rect):return 'inspect_focus'
        _,rect=geometry(i.source,i.focus,i.scale)
        if inside__v741_reading(point,rect):return 'inspect_pan'
        return None
    def begin(self,point,generation,contact_id):
        i=self.inspection
        with i.display.condition:
            if i.kind!='zoom' or generation!=i.generation or i.display.stop or contact_id is None:
                return False,'reading_unavailable',i.token
            target=self.target_locked(point)
            if target is None:return False,'outside_reading_image',i.token
            roi,_=geometry(i.source,i.focus,i.scale)
            self.contact=dict(id=contact_id,token=i.token,generation=generation,target=target,
                press=tuple(point),roi=roi,scale=i.scale,began=time.perf_counter())
            return True,'reading_contact_started',i.token
    def matching_locked(self,event,generation):
        i=self.inspection;c=self.contact;origin=event.get('press_outcome') or {}
        return bool(c is not None and i.kind=='zoom' and i.generation==generation
            and c['generation']==generation and c['token']==i.token
            and origin.get('inspection_token')==i.token and origin.get('target')==c['target']
            and event.get('contact_id')==c['id'])
    def update_locked(self,point):
        if point is None or len(point)!=2 or not all(math.isfinite(v) for v in point):return False
        i=self.inspection;c=self.contact;sx,sy,span=c['roi'];h,w=i.source.shape[:2]
        if c['target']=='inspect_focus':
            #   ⭐ 2026-10-27：源图可能被等比缩小显示（如 800x600 缩到 640x480），
            #      屏幕点要先换算成源图坐标再取 ROI。
            px,py=i._to_source(point)
            sx=int(round(px))-span//2;sy=int(round(py))-span//2
        else:
            # Move paper with the finger; map screen delta through the actual scale.
            sx=int(round(sx-(point[0]-c['press'][0])/c['scale']))
            sy=int(round(sy-(point[1]-c['press'][1])/c['scale']))
        focus=(max(0,min(w-span,sx))+span//2,max(0,min(h-span,sy))+span//2)
        if focus!=i.focus:
            i.focus=focus;i.dirty=True;i.display.condition.notify_all()
        return True
    def move(self,event,generation):
        i=self.inspection
        with i.display.condition:
            if not self.matching_locked(event,generation):return False,'reading_contact_changed'
            ok=self.update_locked(event.get('position'))
            return ok,'reading_pan_preview' if ok else 'missing_move_coordinates'
    def finish(self,event,generation):
        i=self.inspection
        with i.display.condition:
            if not self.matching_locked(event,generation):return False,'reading_contact_changed'
            c=self.contact;ok=self.update_locked(event.get('release'));self.contact=None
            if not ok:return False,'missing_release_coordinates'
            checkpoint('READING_PAN_FINISHED',generation=generation,sequence=i.meta.get('sequence'),
                region='overview' if c['target']=='inspect_focus' else 'loupe',scale=i.scale,
                focus=i.focus,contact_s=time.perf_counter()-c['began'],frozen_source=True,event_only=True)
            return True,'reading_pan_finished'


def restore_outline(canvas,image,source_rect,roi):
    """Erase only the previous outline's strips on the re-owned canvas."""
    x,y,w,h=source_rect;sx,sy,span=roi;left=x+sx;top=y+sy;right=left+span;bottom=top+span
    pad=4
    for ax,ay,bx,by in ((left-pad,top-pad,right+pad,top+pad),
                        (left-pad,bottom-pad,right+pad,bottom+pad),
                        (left-pad,top-pad,left+pad,bottom+pad),
                        (right-pad,top-pad,right+pad,bottom+pad)):
        ax=max(0,ax);ay=max(0,ay);bx=min(canvas.shape[1],bx);by=min(canvas.shape[0],by)
        canvas[ay:by,ax:bx]=0
        ix=max(x,ax);iy=max(y,ay);ex=min(x+w,bx);ey=min(y+h,by)
        if ix<ex and iy<ey:canvas[iy:ey,ix:ex]=image[iy-y:ey-y,ix-x:ex-x]


def render_reading(canvas,payload,assets):
    image=payload['source'];x,y,w,h=payload['source_rect']
    cached=payload.get('reading_background_cached',False)
    if not cached:
        canvas.fill(0)
        canvas[:72]=assets.headers['snapshot'] if payload['meta'].get('page')=='snapshot' else assets.ratio_reading_header
        canvas[y:y+h,x:x+w]=image;canvas[92:140,716:1228]=assets.reading_help
        from ui import ZOOM_CONTROLS as ZOOM_CONTROLS
        for name,(a,b,c,d) in ZOOM_CONTROLS.items():canvas[b:b+d,a:a+c]=assets.inspection_buttons[name]
    else:
        restore_outline(canvas,image,payload['source_rect'],payload['reading_previous_roi'])
        canvas[73:100,24:664]=0
    roi,rect=geometry(image,payload['focus'],payload['scale'])
    sx,sy,span=roi;dx,dy,side,_=rect
    # Only these event-driven patches change. No video input or new full-frame copy.
    canvas[148:540,716:1228]=0
    cv2.resize(image[sy:sy+span,sx:sx+span],(side,side),dst=canvas[dy:dy+side,dx:dx+side],interpolation=cv2.INTER_LINEAR)
    cv2.rectangle(canvas,(x+sx,y+sy),(x+sx+span-1,y+sy+span-1),(20,230,255),2,cv2.LINE_AA)
    cv2.putText(canvas,'%dx | FROZEN seq=%s'%(payload['scale'],payload['meta']['sequence']),
        (32,92),cv2.FONT_HERSHEY_SIMPLEX,.65,(230,230,230),1,cv2.LINE_AA)
    return roi


# ======================================================================
# ===== [13/13] v76_snapshot =====
# ======================================================================


"""One admitted camera frame, one complete P1 correction, then static HDMI."""
from core import RELEASE_ID as RELEASE_ID; from core import verify_package as verify_package
from core import checkpoint as checkpoint
from core import set_color_mode as set_color_mode
from tracking import pump_acquisition as pump_acquisition
from tracking import V74Acquire as LiveAcquire
from tracking import wait_native_with_preview as wait_native_with_preview; from tracking import wait_for_placement as wait_for_placement
from tracking import detect_refined as detect_refined
from tracking import prepare_native__v31_native as prepare_native
from ui import UIReturnRequested as UIReturnRequested

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v76_snapshot=[]


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
    global _POISONED, _POISON_REASON
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
        from ui import camera_key as camera_key
        hot=getattr(context,'hot',None)
        transfer=hot.claim(context,camera_key(device,width,height,fps,options.get('color_mode'))) if hot is not None else None
        if transfer is not None:
            from ui import finish_previous_budget as finish_previous_budget
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
        orientation=make_orientation(options.get('output_orientation','auto_two'),output_size,2)
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
        from ui import remember_fixed_source as remember_fixed_source
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
                    from ui import camera_key as camera_key
                    camera_preserved=hot.offer(context,camera,camera_key(device,width,height,fps,options.get('color_mode')),None,
                        readers_retired=acquirer is None,backend_idle=not backend.active and not backend.failed,admitted=completed,idle=completed)
                if not camera_preserved:camera.close();camera_closed=True
            except BaseException as exc:cleanup.append(('camera',repr(exc)))
        image=None;raw=None;job=None
        checkpoint('SNAPSHOT_CLEANUP',phase='camera_stop_end',camera_closed=camera_closed,errors=list(cleanup))
        if cleanup:
            _POISONED=True
            _POISON_REASON=list(_POISON_REASON)+cleanup
            _RETAINED__v76_snapshot.append((native_setup,acquirer,camera,first,workspace,backend,display))
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
