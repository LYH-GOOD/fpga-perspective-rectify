"""ui —— 合并层，含 35 个原始模块。

本文件由 build/merge_layers.py 生成，不要直接编辑。
每个原始模块的边界见下方 "# ===== [NN/MM] 模块名 =====" 分节标记。
"""


from pathlib import Path
import hashlib


from pathlib import Path
from contextvars import copy_context
import errno,fcntl,glob,hashlib,os,select,struct,threading,time
from pathlib import Path
from collections import deque
from dataclasses import dataclass,field
import hashlib,json,threading,time
import cv2,numpy as np
import hashlib,time
import hashlib
import cv2
import hashlib,os,time
import time
import hashlib
import cv2
import numpy as np
from dataclasses import dataclass
import hashlib,time
from collections import OrderedDict
import hashlib,os,threading,time,uuid
import hashlib,json
import cv2,numpy as np
from contextlib import contextmanager
import hashlib,threading,time
import hashlib, time
from collections import deque
import hashlib,threading,time,types
from functools import lru_cache
import math
from contextvars import copy_context
import hashlib,threading,time,types
import hashlib,threading,time,traceback
import hashlib,statistics,threading
from collections import namedtuple
import hashlib,math,threading
import hashlib,threading,time
import hashlib,time,threading
import hashlib,json,math,threading,time
import hashlib,json,time
import hashlib,json


_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ======================================================================
# ===== [01/35] v75_touch =====
# ======================================================================


"""Blocking Linux absolute-touch reader; no graphics/device ownership."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_EVENT=struct.Struct('@llHHi')
_ABS=struct.Struct('iiiiii')
EV_SYN,EV_KEY,EV_ABS=0,1,3
SYN_REPORT,SYN_DROPPED=0,3
ABS_X,ABS_Y,ABS_MT_SLOT=0,1,47
ABS_MT_POSITION_X,ABS_MT_POSITION_Y,ABS_MT_TRACKING_ID=53,54,57
BTN_TOUCH=330


def _read_ioctl(fd,number,size):
    data=bytearray(size)
    fcntl.ioctl(fd,(2<<30)|(size<<16)|(ord('E')<<8)|number,data,True)
    return data


def _has(bits,number):
    return number//8<len(bits) and bool(bits[number//8]&(1<<(number%8)))


def _inspect(fd,path):
    axes=_read_ioctl(fd,0x20+EV_ABS,64)
    keys=_read_ioctl(fd,0x20+EV_KEY,96)
    mt=all(_has(axes,k) for k in (ABS_MT_POSITION_X,ABS_MT_POSITION_Y,ABS_MT_TRACKING_ID))
    single=_has(keys,BTN_TOUCH) and all(_has(axes,k) for k in (ABS_X,ABS_Y))
    if not (mt or single):raise ValueError('Not an absolute touchscreen: '+path)
    xc,yc=(ABS_MT_POSITION_X,ABS_MT_POSITION_Y) if mt else (ABS_X,ABS_Y)
    xa=_ABS.unpack(_read_ioctl(fd,0x40+xc,_ABS.size))
    ya=_ABS.unpack(_read_ioctl(fd,0x40+yc,_ABS.size))
    if xa[2]<=xa[1] or ya[2]<=ya[1]:raise ValueError('Invalid touch axis range: '+path)
    name=bytes(_read_ioctl(fd,0x06,256)).split(b'\0',1)[0].decode(errors='replace')
    return dict(path=path,name=name,multitouch=mt,has_slots=_has(axes,ABS_MT_SLOT),
        x_code=xc,y_code=yc,x_range=(xa[1],xa[2]),y_range=(ya[1],ya[2]))


class TouchInput:
    """Report contacts; opt-in corner moves are bounded and never logged per sample."""
    def __init__(self,device,mode,on_touch,on_error,swap_xy=False,invert_x=False,invert_y=False):
        self.fd=None;self.closed=False;self.error=None;self.on_touch=on_touch;self.on_error=on_error
        self.mode=tuple(mode);self.swap_xy=bool(swap_xy);self.invert_x=bool(invert_x);self.invert_y=bool(invert_y)
        self.wake_r,self.wake_w=os.pipe();self.stop=threading.Event();self.worker=None
        self.context=copy_context();failures=[]
        self.contacts=self.dropped_contacts=self.press_actions=self.move_events=0
        paths=sorted(glob.glob('/dev/input/event*')) if device=='auto' else [str(device)]
        try:
            for path in paths:
                fd=None
                try:
                    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK)
                    detail=_inspect(fd,path)
                    self.fd=fd;self.detail=detail;break
                except (OSError,ValueError) as exc:
                    failures.append(dict(path=path,error=str(exc)))
                    if fd is not None:os.close(fd)
            if self.fd is None:
                raise RuntimeError('No readable absolute USB touchscreen. Set touch_device=/dev/input/eventN; '+str(failures))
            checkpoint('UI_TOUCH_READY',**self.detail,swap_xy=self.swap_xy,invert_x=self.invert_x,
                invert_y=self.invert_y,event_bytes=_EVENT.size,backend='stdlib_ioctl_select',
                activation='return_press; home_and_layout_release',diagnostics='one completed-contact record; immediate accepted press record',
                motion_limit_pixels=32,release_position='last_valid_DOWN_report',UP_coordinates_count_as_motion=False)
            self.worker=threading.Thread(target=self._entry,name='ui_touch',daemon=True);self.worker.start()
        except BaseException:
            self.close();raise
    def _point(self,x,y):
        lo,hi=self.detail['x_range'];u=(x-lo)/(hi-lo)
        lo,hi=self.detail['y_range'];v=(y-lo)/(hi-lo)
        if self.swap_xy:u,v=v,u
        if self.invert_x:u=1.-u
        if self.invert_y:v=1.-v
        return (int(round(max(0.,min(1.,u))*(self.mode[0]-1))),
                int(round(max(0.,min(1.,v))*(self.mode[1]-1))))
    def _entry(self):
        try:self.context.run(self._run)
        except BaseException as exc:
            if not self.stop.is_set():
                self.error=exc
                try:self.on_error(exc)
                except BaseException:pass
    def _run(self):
        pending=b'';x=y=None;slot=0;down=was_down=False;dropped=False
        press=None;peak_motion=0.;pressed_point=None;contact=None;outcome=None
        last_down=None;last_down_raw=None;down_samples=0
        last_move_s=0.;last_move_point=None
        mt=self.detail['multitouch'];has_slots=self.detail['has_slots']
        def activate_press(kernel_s):
            nonlocal press,pressed_point,outcome,last_move_s,last_move_point
            press=self._point(x,y);pressed_point=press
            contact.update(press=press,raw_press=(x,y),kernel_press_s=kernel_s,dispatch_press_s=time.perf_counter())
            t=time.perf_counter()
            outcome=self.on_touch(dict(contact,phase='press',peak_motion=0.)) or {}
            last_move_s=time.perf_counter();last_move_point=press
            contact['press_callback_s']=time.perf_counter()-t
            if outcome.get('accepted'):
                self.press_actions+=1
                checkpoint('UI_TOUCH_PRESS_ACTION',contact_id=contact['contact_id'],press=press,raw_press=(x,y),
                    kernel_event_s=kernel_s,dispatch_at=contact['dispatch_press_s'],
                    callback_s=contact['press_callback_s'],outcome=outcome)
        while not self.stop.is_set():
            readable,_,_=select.select([self.fd,self.wake_r],[],[])
            if self.wake_r in readable:break
            try:data=os.read(self.fd,_EVENT.size*64)
            except BlockingIOError:continue
            if not data:raise OSError(errno.ENODEV,'Touchscreen disconnected')
            pending+=data
            usable=len(pending)//_EVENT.size*_EVENT.size
            for offset in range(0,usable,_EVENT.size):
                seconds,micros,kind,code,value=_EVENT.unpack_from(pending,offset)
                kernel_s=seconds+micros/1e6
                if kind==EV_SYN and code==SYN_DROPPED:
                    self.dropped_contacts+=1
                    checkpoint('UI_TOUCH_DROPPED',contact_id=contact.get('contact_id') if contact else None,
                        reason='SYN_DROPPED_contact_discarded',peak_motion=peak_motion,press=press,
                        press_action_already_sent=bool(outcome and outcome.get('accepted')),
                        dropped_count=self.dropped_contacts,kernel_event_s=kernel_s)
                    self.on_touch(dict(phase='cancel',press=press,reason='SYN_DROPPED',
                        contact_id=contact.get('contact_id') if contact else None))
                    dropped=True;press=None;pressed_point=None;contact=None;outcome=None
                    last_down=last_down_raw=None;down_samples=0
                    was_down=down=False;x=y=None;continue
                if dropped:
                    if kind==EV_SYN and code==SYN_REPORT:dropped=False
                    continue
                if kind==EV_ABS:
                    if code==ABS_MT_SLOT:slot=value;continue
                    if mt and has_slots and slot!=0:continue
                    if code==self.detail['x_code']:x=value
                    elif code==self.detail['y_code']:y=value
                    elif mt and code==ABS_MT_TRACKING_ID:down=value>=0
                elif kind==EV_KEY and code==BTN_TOUCH and (not mt or not has_slots):down=value!=0
                elif kind==EV_SYN and code==SYN_REPORT:
                    if down and not was_down:
                        self.contacts+=1;press=pressed_point=None;peak_motion=0.;outcome=None
                        last_down=last_down_raw=None;down_samples=0
                        contact=dict(contact_id=self.contacts,contact_begin_s=time.perf_counter(),
                            kernel_contact_begin_s=kernel_s,press=None,raw_press=None)
                        if x is not None and y is not None:activate_press(kernel_s)
                    elif down and press is None and x is not None and y is not None:
                        activate_press(kernel_s)
                    # UP reports may contain zero/reset/stale axis values.
                    # They are diagnostic only; never extend a DOWN trajectory.
                    if down and pressed_point is not None and x is not None and y is not None:
                        point=self._point(x,y)
                        peak_motion=max(peak_motion,abs(point[0]-pressed_point[0]),abs(point[1]-pressed_point[1]))
                        last_down=point;last_down_raw=(x,y);down_samples+=1
                        # Only the corner editor opts in. Buttons/albums keep
                        # their original press/release and 32px motion policy.
                        now=time.perf_counter()
                        if (outcome and outcome.get('track_moves') and not outcome.get('consumed')
                                and point!=last_move_point and now-last_move_s>=1./30.):
                            self.on_touch(dict(contact,phase='move',position=point,peak_motion=peak_motion,
                                press_outcome=outcome,kernel_move_s=kernel_s,dispatch_move_s=now))
                            last_move_s=now;last_move_point=point;self.move_events+=1
                    if was_down and not down:
                        up_position=None if x is None or y is None else self._point(x,y)
                        release=last_down
                        up_jump=(None if up_position is None or last_down is None else
                            max(abs(up_position[0]-last_down[0]),abs(up_position[1]-last_down[1])))
                        event=dict(contact or {},phase='release',press=press,release=release,
                            raw_release=None if x is None or y is None else (x,y),peak_motion=peak_motion,
                            last_down=last_down,last_down_raw=last_down_raw,down_samples=down_samples,
                            up_position=up_position,up_jump_pixels=up_jump,UP_coordinate_ignored=True,
                            press_outcome=outcome,kernel_release_s=kernel_s,dispatch_release_s=time.perf_counter())
                        t=time.perf_counter()
                        if outcome and outcome.get('consumed'):
                            decision=dict(outcome,release_reason='contact_consumed_on_press')
                        else:decision=self.on_touch(event) or dict(accepted=False,reason='no_ui_decision')
                        checkpoint('UI_TOUCH_CONTACT',contact_id=event.get('contact_id'),press=press,release=release,
                            raw_press=event.get('raw_press'),raw_release=event['raw_release'],peak_motion=peak_motion,
                            last_down_raw=last_down_raw,down_samples=down_samples,up_position=up_position,
                            up_jump_pixels=up_jump,UP_coordinate_ignored=True,release_source='last_valid_DOWN_report',
                            contact_s=event['dispatch_release_s']-event.get('contact_begin_s',event['dispatch_release_s']),
                            kernel_press_s=event.get('kernel_press_s'),kernel_release_s=kernel_s,
                            dispatch_press_s=event.get('dispatch_press_s'),dispatch_release_s=event['dispatch_release_s'],
                            press_callback_s=event.get('press_callback_s'),release_callback_s=time.perf_counter()-t,
                            event_clock_scope='evdev timestamps retained; not subtracted from perf_counter',outcome=decision)
                        press=None;pressed_point=None;contact=None;outcome=None
                        last_down=last_down_raw=None;down_samples=0
                    was_down=down
            pending=pending[usable:]
    def close(self):
        if self.closed:return
        self.stop.set()
        try:os.write(self.wake_w,b'x')
        except OSError:pass
        if self.worker is not None:
            self.worker.join(2.)
            if self.worker.is_alive():raise RuntimeError('Touch worker did not stop; file descriptors retained')
        if self.worker is not None:checkpoint('UI_TOUCH_SUMMARY',contacts=self.contacts,
            dropped_contacts=self.dropped_contacts,accepted_press_actions=self.press_actions,corner_move_events=self.move_events)
        if self.fd is not None:os.close(self.fd);self.fd=None
        os.close(self.wake_r);os.close(self.wake_w);self.closed=True


# ======================================================================
# ===== [02/35] v75_ui =====
# ======================================================================


"""Static HDMI pages and event-driven UI; the existing owners keep all device access."""
from core import RELEASE_ID as RELEASE_ID; from core import verify_package as verify_package
from core import checkpoint as checkpoint; from core import logged_run as logged_run
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v75_ui=[]

#   ⭐ 2026-10-29：相机输入档位表。**`tracking_max_dim` 必须跟着档位走** ——
#      原生 fused 灰度要求降采样"恰好 2 倍"（`(ow*2,oh*2)==(w,h)`）：
#      640x480 ⇒ 320，800x600 ⇒ 400。设错**不报错**，只是静默退回 Python 慢路径
#      （实测 11 ms → 63 ms），这是切档最容易踩的坑。
CAMERA_PROFILES={
    '480P':dict(width=640,height=480,fps=30,tracking_max_dim=320,label='480P · 640×480'),
    '600P':dict(width=800,height=600,fps=15,tracking_max_dim=400,label='600P · 800×600'),
}
#   P1 的两块 CMA 输入缓冲按**最大档位**分配一次，之后只改有效尺寸，
#   切档时不再申请/释放 DMA 内存（+1.38 MB CMA，赛前确认过够用）。
MAX_INPUT_SHAPE=(600,800)


def camera_profile_for(width,height):
    for name,p in CAMERA_PROFILES.items():
        if (int(width),int(height))==(p['width'],p['height']):return name
    raise ValueError('Unknown camera profile %dx%d'%(width,height))


class UIReturnRequested(Exception):
    """Cooperative return at a safe camera/owner boundary."""


class UIAssets:
    def __init__(self,mode):
        self.mode=tuple(mode);root=Path(__file__).resolve().parent
        spec=json.loads((root/'v75_ui_layout.json').read_text(encoding='utf-8'))
        if self.mode!=tuple(spec['mode']):raise ValueError('UI assets require the retained V74 HDMI1280x720 mode')
        self.home=cv2.imread(str(root/'v75_home.png'),cv2.IMREAD_COLOR)
        self.header=cv2.imread(str(root/'v75_header.png'),cv2.IMREAD_COLOR)
        if self.home is None or self.home.shape!=(self.mode[1],self.mode[0],3):raise ValueError('Invalid UI home asset')
        if self.header is None or self.header.shape!=(72,self.mode[0],3):raise ValueError('Invalid UI header asset')
        self.headers={'compare':self.header}
        badges=cv2.imread(str(root/'v79_status.png'),cv2.IMREAD_COLOR)
        if badges is None or badges.shape!=(160,512,3):raise ValueError('Invalid V79 cached status asset')
        badges.setflags(write=False)
        self.status_badges={state:badges[i*28:(i+1)*28,:320]
            for i,state in enumerate(('SEARCHING','CURRENT','HELD','LOST'))}
        self.acquire_hint=badges[112:160]
        self.clipped_hint=cv2.imread(str(root/'v81_clipped_hint.png'),cv2.IMREAD_COLOR)
        if self.clipped_hint is None or self.clipped_hint.shape!=(48,512,3):raise ValueError('Invalid current-frame placement hint')
        self.clipped_hint.setflags(write=False)
        setup=cv2.imread(str(root/'v79_setup_status.png'),cv2.IMREAD_COLOR)
        if setup is None or setup.shape!=(76,512,3):raise ValueError('Invalid native setup status asset')
        setup.setflags(write=False);self.status_badges['INITIALIZING']=setup[:28,:320]
        self.setup_hint=setup[28:]
        placement=cv2.imread(str(root/'v79_placement_help.png'),cv2.IMREAD_COLOR)
        controls=cv2.imread(str(root/'v79_placement_controls.png'),cv2.IMREAD_COLOR)
        if placement is None or placement.shape!=(172,512,3):raise ValueError('Invalid placement help asset')
        if controls is None or controls.shape!=(216,280,3):raise ValueError('Invalid placement controls asset')
        placement.setflags(write=False);controls.setflags(write=False)
        self.status_badges['PLACEMENT']=placement[:28,:320]
        self.placement_hints={name:placement[28+i*48:76+i*48]
            for i,name in enumerate(('placement','confirmed','preparing'))}
        self.placement_controls={name:controls[i*72:(i+1)*72]
            for i,name in enumerate(('confirm','confirmed','acquiring'))}
        refind=cv2.imread(str(root/'v80_refind.png'),cv2.IMREAD_COLOR)
        if refind is None or refind.shape!=(144,220,3):raise ValueError('Invalid refind button asset')
        refind.setflags(write=False);self.refind_controls={'ready':refind[:72],'preparing':refind[72:]}
        for view in ('rectified','snapshot'):
            image=cv2.imread(str(root/('v77_header_'+view+'.png')),cv2.IMREAD_COLOR)
            if image is None or image.shape!=self.header.shape:raise ValueError('Invalid '+view+' UI header')
            image.setflags(write=False);self.headers[view]=image
        self.snapshot_busy=cv2.imread(str(root/'v79_snapshot_busy.png'),cv2.IMREAD_COLOR)
        if self.snapshot_busy is None or self.snapshot_busy.shape!=self.header.shape:
            raise ValueError('Invalid snapshot busy header')
        self.snapshot_busy.setflags(write=False)
        self.return_patch=cv2.imread(str(root/'v77_return_pressed.png'),cv2.IMREAD_COLOR)
        if self.return_patch is None or self.return_patch.shape!=(72,180,3):raise ValueError('Invalid return feedback asset')
        self.return_patch.setflags(write=False);self.return_home=None
        self.buttons=tuple((entry['view'],tuple(entry['rect'])) for entry in spec['buttons'])
        self.layout_switch=tuple(spec['layout_switch_hit_rect'])
        self.refind=tuple(spec['refind_hit_rect'])
        self.snapshot_recapture=tuple(spec['snapshot_recapture_hit_rect'])
        self.back=tuple(spec['back_hit_rect']);self.home.setflags(write=False);self.header.setflags(write=False)
        self.error_home=None;self.home_pressed=None;self.home_pressed_cache=None;self.home_pressed_key=None
        load_interaction_assets(self,root)
        self.ai=(280,0,100,72);self.manual=(180,0,100,72)
        hints=cv2.imread(str(root/'v97_3_target_hints.png'),cv2.IMREAD_COLOR)
        if hints is None or hints.shape!=(1616,1280,3):raise ValueError('Invalid cached target selection assets')
        hints.setflags(write=False)
        self.target_hints={(view,name):hints[(i*4+j)*40:(i*4+j+1)*40,:640]
            for i,view in enumerate(('compare','rectified')) for j,name in enumerate(('multiple','selecting','selected','miss'))}
        # One existing asset file: keep per-frame package admission's file list.
        for view in ('compare','rectified'):
            self.target_hints[(view,'fallback')]=self.target_hints[(view,'miss')]
            self.target_hints[(view,'not_covered')]=hints[1032:1072,:640]
            self.target_hints[(view,'unconfirmed')]=hints[1072:1112,:640]
            self.target_hints[(view,'current')]=hints[1576:1616,:640]
        progress=hints[320:960];self.switch_busy_header=hints[960:1032]
        self.switch_progress={name:progress[i*128:(i+1)*128] for i,name in enumerate(('prepare','edges','verify','display','miss'))}
        self.switch_progress['fallback']=self.switch_progress['miss']
        self.navigation_progress={name:hints[1112+i*32:1112+(i+1)*32]
            for i,name in enumerate(('prepare','search','verify','display','layout','home','calibration','zoom','album','snapshot','ready'))}
        self.entry_progress={name:hints[1464:1576,i*320:(i+1)*320]
            for i,name in enumerate(('prepare','search','verify','display'))}
        from display import load_assets__v73_ratio_ui as load_assets
        load_assets(self,root)
        load_assets__v119_profile_ui(self,root)
        load_assets__v120_image_settings(self,root)
        load_assets__v123_live_ui(self,root)
        from display import load_assets__v74_hold as load_hold_assets
        load_hold_assets(self,root)
        self.media_assets=MediaAssets(root)
        checkpoint('UI_ASSETS_READY',mode=list(self.mode),resident_bytes=self.home.nbytes+sum(h.nbytes for h in self.headers.values())+self.return_patch.nbytes+self.snapshot_busy.nbytes+setup.nbytes+badges.nbytes+placement.nbytes+controls.nbytes+refind.nbytes+self.clipped_hint.nbytes,
            back_hit_rect=list(self.back),layout_switch_hit_rect=list(self.layout_switch),
            snapshot_recapture_hit_rect=list(self.snapshot_recapture),
            decode_scope='once before sessions',home_redraw='page changes only',header_redraw='per-buffer page changes only',
            ratio_asset_resident_bytes=self.ratio_asset_resident_bytes,ratio_render='inspection events; frozen background cached per buffer')
    @staticmethod
    def inside(point,rect):
        x,y,w,h=rect;return x<=point[0]<x+w and y<=point[1]<y+h
    def home_frame(self,error=False,feedback=False):
        if feedback:
            if self.return_home is None:
                self.return_home=self.home.copy();self.return_home[:72,:180]=self.return_patch
                self.return_home.setflags(write=False)
            return self.return_home
        if not error:
            rect=self.home_pressed
            if rect is None:return self.home
            if rect!=self.home_pressed_key:
                panel=self.home.copy();x,y,w,h=rect
                cv2.rectangle(panel,(x,y),(x+w-1,y+h-1),(230,245,90),3,cv2.LINE_AA)
                panel.setflags(write=False);self.home_pressed_cache=panel;self.home_pressed_key=rect
            return self.home_pressed_cache
        if self.error_home is None:
            self.error_home=self.home.copy()
            cv2.putText(self.error_home,'START FAILED - ADJUST SCENE AND RETRY; SEE run-result.log',
                (60,self.mode[1]-32),cv2.FONT_HERSHEY_SIMPLEX,.48,(210,225,255),1,cv2.LINE_AA)
            self.error_home.setflags(write=False)
        return self.error_home


@dataclass
class _PageRun:
    generation:int
    start_generation:int
    page:str
    cancel:object
    phase:str='preparing'
    placement:object=field(default_factory=threading.Event)
    placement_required:bool=True
    manual:bool=False
    ai:bool=False
    ai_mode_locked:bool=False
    fixed_input:object=None
    target_selection:object=None
    switch_from:object=None
    switch_requested_at:float=0.


class UIState:
    def __init__(self,assets,confirm_placement=False):
        self.assets=assets;self.condition=threading.Condition();self.page='home';self.generation=0
        self.cancel=threading.Event();self.stopping=False;self.error=None;self.display=None
        self.ticket=_PageRun(0,0,'home',self.cancel);self.layout_switches=0
        self.ai_service=None
        self.last_return=-float('inf');self.last_layout=-float('inf');self.debounce_s=.20
        self.last_recapture=-float('inf');self.recapture_requests=0
        self.confirm_placement=confirm_placement;self.last_placement=-float('inf')
        self.last_refind=-float('inf');self.refind_requests=0
        self.tap_contact=None;self.last_tap_target=-float('inf');self.target_request_serial=0;self.ratio=None;self.hold=None
        self.contact_counts=dict(accepted=0,rejected=0,returns=0,layout_switches=0,snapshot_recaptures=0,refind_requests=0)
    def bind(self,display):
        self.display=display;self.ratio=None;self.hold=None;self.profile=None
        if hasattr(display,'_show'):
            from display import RatioUI as RatioUI
            self.ratio=RatioUI(self,display)
            self.profile=ImageSettingsUI(self,display)
            from display import HoldController as HoldController
            self.hold=HoldController(self,display)
    def _home_feedback(self,rect):
        self.assets.home_pressed=rect
        if self.display is not None and self.page=='home':
            # A page-owner redraw request only; no VDMA access in touch thread.
            self.display.request_view('home',self.generation)
    def request(self,page,error=False,return_feedback=False,recapture=False,refind=False,manual=False,restart=False,target_selection=None,ai=None,profile_switch=False):
        if page not in ('home','compare','rectified','snapshot'):raise ValueError('Unknown UI page')
        if ai and page not in ('compare','rectified'):return False
        with self.condition:
            if self.stopping:return False
            if refind and ai is None and not manual:
                ai=self.ticket.ai_mode_locked
            manual=bool(manual or ai)
            self.assets.home_pressed=None
            self.tap_contact=None
            if recapture:
                if page!='snapshot' or self.page!='snapshot' or self.display is None:return False
                if not self.display.snapshot_is_frozen(self.generation):return False
            if refind and (page!=self.page or page not in ('compare','rectified')):return False
            if page==self.page and not error and not recapture and not refind and not manual and not restart:return False
            fixed_input=(self.ticket.fixed_input if manual and page=='snapshot' and self.page=='snapshot'
                and self.display is not None and self.display.snapshot_is_frozen(self.generation) else None)
            previous_ticket=self.ticket
            previous=self.page;layout_only=previous in ('compare','rectified') and page in ('compare','rectified') and not error and not refind and not manual and not restart
            if self.hold is not None:self.hold.end('page_request')
            self.page=page;self.generation+=1;generation=self.generation
            profile_ui=getattr(self,'profile',None)
            if profile_ui is not None:
                if profile_switch:profile_ui.bind_request(generation)
                else:
                    self.pending_profile=None
                    profile_ui.cancel('page_or_session_request')
            if self.ratio is not None:self.ratio.cancel_for_request(layout_only,generation)
            if layout_only:
                # The session token survives; only its display generation changes.
                self.ticket.generation=generation;self.ticket.page=page;self.layout_switches+=1
            else:
                if self.ai_service is not None and hasattr(self.ai_service,'note_transition'):
                    self.ai_service.note_transition('ai' if ai else 'manual_selection' if manual else 'live')
                self.cancel.set();self.cancel=threading.Event()
                self.ticket=_PageRun(generation,generation,page,self.cancel,placement_required=self.confirm_placement,manual=bool(manual),ai=bool(ai),ai_mode_locked=bool(ai),fixed_input=fixed_input,target_selection=target_selection,
                    switch_from=previous_ticket.start_generation,
                    switch_requested_at=time.perf_counter())
                if recapture:
                    self.recapture_requests+=1;self.ticket.placement.set()
                if refind:self.refind_requests+=1
            # Serialize display requests with UI state changes. No device access here.
            if self.display is not None and error and hasattr(self.display,'cancel_ui_feedback'):
                self.display.cancel_ui_feedback()
            if profile_switch and self.display is not None and hasattr(self.display,'cancel_ui_feedback'):
                self.display.cancel_ui_feedback()
            if not profile_switch and self.display is not None and hasattr(self.display,'begin_ui_transition'):
                if target_selection is None and not error:
                    kind=('home' if page=='home' else 'layout' if layout_only else 'ai_calibration' if ai else 'calibration' if manual
                        else 'enter' if previous=='home' and page in ('compare','rectified')
                        else 'snapshot' if page=='snapshot' else 'prepare')
                    self.display.begin_ui_transition(page,generation,kind)
            if self.display is not None:self.display.request_view(page,generation,error=error,
                layout_only=layout_only,return_feedback=return_feedback,preserve_target=target_selection is not None)
            if self.ratio is not None:self.ratio.prepare_header_transition()
            if self.display is not None and target_selection is not None:self.display.set_target_notice('selecting',generation)
            session_generation=self.ticket.start_generation;self.condition.notify_all()
            if page=='home' and self.ai_service is not None:
                from ai import entered_home as entered_home
                entered_home(self)
        checkpoint('UI_MODE_REQUEST',page=page,previous_page=previous,generation=generation,
            session_generation=session_generation,error_banner=bool(error),layout_only=layout_only,
            camera_restarted=False if layout_only or fixed_input is not None or page=='home' else None,
            camera_restart_decision='shared_camera_after_reader_retirement',cooperative_cancel=not layout_only,
            fixed_snapshot_source_reused=fixed_input is not None,
            return_feedback=bool(return_feedback),snapshot_recapture=bool(recapture),explicit_refind=bool(refind),manual_calibration=bool(manual))
        return True
    def queue_target_selection(self,selection):
        """One new intent, immediately; existing live camera/owner keep running."""
        with self.condition:
            if self.stopping or self.page!='compare':return False
            generation=self.generation;self.target_request_serial+=1
            selection=dict(selection,request_id='%s:%s'%(generation,self.target_request_serial),source_generation=generation)
            locked=bool(self.ticket.ai_mode_locked)
            if not self.display.arm_target_switch(generation,None,point=selection['point'],request_id=selection['request_id']):return False
            accepted=self.request(self.page,restart=True,target_selection=selection,ai=locked)
            if not accepted:self.display.target_switch.restore()
            return accepted
    def touch(self,event):
        result=self._touch(event)
        if (self.display is not None and hasattr(self.display,'touch_feedback')
                and not str(result.get('target','')).startswith('settings_')):
            self.display.touch_feedback(event,result,self.generation)
        return result
    def _touch(self,event):
        """Return acts on press. Home/layout controls require a same-page release."""
        with self.condition:
            page=self.page;generation=self.generation;phase=event['phase'];press=event.get('press')
            base=dict(page=page,generation=generation,accepted=False,target=None,consumed=False)
            self.assets.manual=(180,0,100 if page in ('compare','rectified') else 200,72)
            #   ⭐ 2026-10-29：相机输入档位弹窗优先级最高 —— 它打开时盖在画面上，
            #      点哪里都先归它。返回 None 表示不归它管（面板关着且没点按钮）。
            profile=getattr(self,'profile',None)
            if profile is not None:
                prof=profile.touch(event,generation)
                if prof is not None:
                    result=dict(base);result.update(prof)
                    if result.get('accepted'):self.contact_counts['accepted']+=1
                    elif phase!='press':self.contact_counts['rejected']+=1
                    return result
            if self.hold is not None:
                held=self.hold.touch(event,generation)
                if held is not None:
                    if phase=='press' and held.get('accepted'):self.contact_counts['accepted']+=1
                    return dict(base,**held)
            if phase=='cancel':
                self.tap_contact=None
                if self.display is not None:
                    self.display.inspection.cancel_point_contact(event.get('contact_id'))
                    with self.display.condition:self.display.inspection.reading.cancel_locked(event.get('contact_id'))
                self._home_feedback(None)
                return dict(base,reason='contact_cancelled',consumed=True)
            if self.stopping:return dict(base,reason='application_stopping')
            if press is None:return dict(base,reason='missing_press_coordinates')
            if phase=='move':
                origin=event.get('press_outcome') or {}
                if (origin.get('generation')==generation and origin.get('page')==page
                        and origin.get('target')=='inspect_point' and self.display is not None):
                    accepted,reason=self.display.inspection.move_point_contact(event,generation)
                    return dict(base,target='inspect_point',accepted=accepted,reason=reason)
                if (origin.get('generation')==generation and origin.get('page')==page
                        and origin.get('target') in ('inspect_focus','inspect_pan') and self.display is not None):
                    accepted,reason=self.display.inspection.reading.move(event,generation)
                    return dict(base,target=origin['target'],accepted=accepted,reason=reason)
                return dict(base,reason='move_not_requested')
            back=page!='home' and self.assets.inside(press,self.assets.back)
            if self.ratio is not None and self.ratio.pending is not None and not back:
                return dict(base,target='ratio_apply_busy',consumed=True,reason='ratio_apply_in_progress_return_available')
            if not back and self.ratio is not None:
                ratio_result=self.ratio.touch(event,generation)
                if ratio_result is not None:
                    result=dict(base);result.update(ratio_result)
                    if result.get('accepted'):self.contact_counts['accepted']+=1
                    elif phase!='press':self.contact_counts['rejected']+=1
                    return result
            if page!='home' and self.display is not None and self.display.media is not None:
                media=self.display.media.touch(event,generation)
                if media is not None:
                    result=dict(base);result.update(media)
                    if media.get('accepted'):self.contact_counts['accepted']+=1
                    elif phase!='press':self.contact_counts['rejected']+=1
                    return result
            if phase=='press':
                self.tap_contact=None
                if self.display is not None:
                    with self.display.condition:self.display.inspection.reading.cancel_locked()
                if back:
                    now=time.perf_counter()
                    if now-self.last_return<self.debounce_s:
                        self.contact_counts['rejected']+=1
                        return dict(base,target='home',consumed=True,reason='return_debounce')
                    self.last_return=now
                    if self.request('home',return_feedback=True):
                        self.contact_counts['accepted']+=1;self.contact_counts['returns']+=1
                        return dict(base,accepted=True,target='home',consumed=True,reason='return_on_press',request_generation=self.generation)
                target=None
                if page!='home' and self.display is not None:
                    if (page in ('compare','rectified') and self.display.inspection.kind is None
                            and self.assets.inside(press,self.assets.ai)):
                        return dict(base,target='ai_calibration',reason='await_release')
                    # Fixed-image manual calibration remains a page control,
                    # including while a snapshot loupe overlay is displayed.
                    if self.assets.inside(press,self.assets.manual) and self.display.inspection.kind!='calibration':
                        return dict(base,target='manual_calibration',reason='await_release')
                    target=self.display.inspection.target(press,generation)
                    if target=='inspect_point':
                        started,reason,token=self.display.inspection.begin_point_contact(press,generation,event.get('contact_id'))
                        return dict(base,target=target,reason=reason,track_moves=started,inspection_token=token)
                    if target in ('inspect_focus','inspect_pan'):
                        started,reason,token=self.display.inspection.reading.begin(press,generation,event.get('contact_id'))
                        return dict(base,target=target,reason=reason,track_moves=started,inspection_token=token)
                    if target is not None:return dict(base,target=target,reason='await_inspection_release',
                        inspection_token=self.display.inspection.token)
                    if self.assets.inside(press,self.assets.manual):return dict(base,target='manual_calibration',reason='await_release')
                    if self.assets.inside(press,self.assets.zoom):return dict(base,target='reading_zoom',reason='await_release')
                if page=='home':
                    target=next((view for view,rect in self.assets.buttons if self.assets.inside(press,rect)),None)
                    if target is not None:
                        self._home_feedback(next(rect for view,rect in self.assets.buttons if view==target))
                elif page in ('compare','rectified') and self.assets.inside(press,self.assets.refind):
                    if self.ticket.phase=='preparing':
                        self.contact_counts['rejected']+=1
                        return dict(base,target='refind',consumed=True,reason='library_preparing_auto_search_queued')
                    target='refind'
                elif self.ticket.phase!='running' and self.assets.inside(press,self.assets.layout_switch):
                    self.contact_counts['rejected']+=1
                    return dict(base,target='startup_busy',consumed=True,reason='automatic_startup_in_progress')
                elif page in ('compare','rectified') and self.assets.inside(press,self.assets.layout_switch):target='layout_toggle'
                elif page=='snapshot' and self.assets.inside(press,self.assets.snapshot_recapture):
                    if self.display is None or not self.display.snapshot_is_frozen(generation):
                        self.contact_counts['rejected']+=1
                        return dict(base,target='snapshot_recapture',consumed=True,reason='snapshot_still_capturing')
                    target='snapshot_recapture'
                if (target is None and page=='compare' and can_select(self.ticket.manual,self.ticket.ai) and self.ticket.phase=='running'
                        and self.display is not None):
                    selection=self.display.tap_target_source(press,generation)
                    if selection is not None:
                        self.tap_contact=(event.get('contact_id'),selection)
                        return dict(base,target='tap_target',reason='await_target_release')
                return dict(base,target=target,reason='await_release' if target else 'outside_controls')
            origin=event.get('press_outcome') or {}
            if origin.get('generation')!=generation or origin.get('page')!=page:
                result=dict(base,reason='page_changed_during_contact')
            elif origin.get('target')=='inspect_point' and self.display is not None:
                accepted,reason=self.display.inspection.finish_point_contact(event,generation)
                self.contact_counts['accepted' if accepted else 'rejected']+=1
                return dict(base,target='inspect_point',accepted=accepted,reason=reason)
            elif origin.get('target') in ('inspect_focus','inspect_pan') and self.display is not None:
                accepted,reason=self.display.inspection.reading.finish(event,generation)
                self.contact_counts['accepted' if accepted else 'rejected']+=1
                return dict(base,target=origin['target'],accepted=accepted,reason=reason)
            elif event.get('release') is None:result=dict(base,reason='missing_release_coordinates')
            elif event.get('peak_motion',0.)>32:result=dict(base,target=origin.get('target'),reason='drag_over_32px')
            else:
                release=event['release'];target=None;reason='outside_controls'
                origin_target=origin.get('target') or ''
                if origin_target=='tap_target':
                    contact=self.tap_contact;self.tap_contact=None;target=origin_target
                    reason='target_contact_expired'
                    if contact is not None and contact[0]==event.get('contact_id') and time.perf_counter()-contact[1]['pressed_at']<=.75:
                        if (hasattr(self.display,'current_target_tap')
                                and self.display.current_target_tap(contact[1],release,generation)):
                            reason='current_target_release'
                        elif time.perf_counter()-self.last_tap_target<.5:reason='target_debounce' 
                        elif self.display.inspection.kind is None and self.queue_target_selection(contact[1]):
                            self.last_tap_target=time.perf_counter();reason='tap_target_release'
                            checkpoint('UI_TAP_TARGET',point=list(contact[1]['point']),source_sequence=contact[1]['sequence'],
                                source_rect=contact[1]['source_rect'],normalized_point=contact[1]['normalized_point'],
                                selection_request_id=self.ticket.target_selection['request_id'],
                                source_generation=generation,new_generation=self.generation,freeze_before_restart=False,live_preview=True,serialized_owner_restart=True,
                                original_current_proof_required=True,persistent_lock=False)
                elif origin_target.startswith('inspect_'):
                    target=origin_target
                    accepted,reason=self.display.inspection.release(target,press,release,generation,origin.get('inspection_token'))
                    if accepted and target=='inspect_auto':
                        self.request(page,restart=page=='snapshot',refind=page in ('compare','rectified'),ai=False)
                    elif accepted and target=='inspect_manual':
                        self.request(page,manual=True)
                    result=dict(base,target=target,accepted=accepted,reason=reason,request_generation=self.generation if accepted else None)
                    self.contact_counts['accepted' if accepted else 'rejected']+=1
                    return result
                elif origin_target=='ai_calibration':
                    target=origin_target;reason='release_outside_target'
                    if page in ('compare','rectified') and self.assets.inside(release,self.assets.ai):
                        reason='ai_calibration_release' if self.request(page,ai=True) else 'ai_request_ignored'
                elif origin_target=='manual_calibration':
                    target=origin_target;reason='release_outside_target'
                    if self.assets.inside(release,self.assets.manual):
                        reason='manual_calibration_release' if self.request(page,manual=True) else 'manual_request_ignored'
                elif origin_target=='reading_zoom':
                    target=origin_target;reason='release_outside_target'
                    if self.assets.inside(release,self.assets.zoom):
                        reason='reading_zoom_release' if self.display.inspection.request_zoom(generation) else 'reading_requires_current_result'
                elif page=='home':
                    for view,rect in self.assets.buttons:
                        if self.assets.inside(press,rect):
                            target=view;reason='release_outside_target'
                            if self.assets.inside(release,rect):reason='home_release';self.request(view)
                            break
                elif origin.get('target')=='refind':
                    target='refind';reason='release_outside_target'
                    if self.assets.inside(release,self.assets.refind):
                        now=time.perf_counter()
                        if now-self.last_refind<.5:reason='refind_debounce'
                        elif self.ticket.phase=='preparing':reason='library_preparing_auto_search_queued'
                        elif self.request(page,refind=True):
                            self.last_refind=now;reason='refind_release';self.contact_counts['refind_requests']+=1
                            checkpoint('UI_REFIND_REQUEST',previous_generation=generation,new_generation=self.generation,
                                stale_corners_discarded=True,serialized_owner_restart=True,validation_bypassed=False)
                elif self.ticket.phase!='running' and self.assets.inside(press,self.assets.layout_switch):
                    target='startup_busy';reason='startup_already_confirmed_or_acquiring'
                elif page in ('compare','rectified') and self.assets.inside(press,self.assets.layout_switch):
                    target='rectified' if page=='compare' else 'compare';reason='release_outside_target'
                    if self.assets.inside(release,self.assets.layout_switch):
                        now=time.perf_counter()
                        if now-self.last_layout<self.debounce_s:reason='layout_debounce'
                        else:
                            self.last_layout=now;reason='layout_release';self.request(target)
                elif page=='snapshot' and self.assets.inside(press,self.assets.snapshot_recapture):
                    target='snapshot_recapture';reason='release_outside_target'
                    if self.assets.inside(release,self.assets.snapshot_recapture):
                        now=time.perf_counter()
                        if now-self.last_recapture<self.debounce_s:reason='snapshot_recapture_debounce'
                        elif self.request('snapshot',recapture=True):
                            self.last_recapture=now;reason='snapshot_recapture_release'
                        else:reason='snapshot_still_capturing'
                accepted=reason in ('home_release','layout_release','snapshot_recapture_release','refind_release','manual_calibration_release','ai_calibration_release','reading_zoom_release','tap_target_release','current_target_release')
                result=dict(base,target=target,accepted=accepted,reason=reason,
                    request_generation=self.generation if accepted else None)
            self.contact_counts['accepted' if result['accepted'] else 'rejected']+=1
            self.tap_contact=None
            if page=='home' and not result['accepted']:self._home_feedback(None)
            if result['accepted'] and result['reason']=='layout_release':self.contact_counts['layout_switches']+=1
            if result['accepted'] and result['reason']=='snapshot_recapture_release':self.contact_counts['snapshot_recaptures']+=1
            return result
    def input_error(self,exc):
        with self.condition:
            if self.hold is not None:self.hold.end('touch_error')
            self.error=exc;self.stopping=True;self.cancel.set();self.condition.notify_all()
        checkpoint('UI_TOUCH_FAILED',durable=True,exception_type=type(exc).__name__,exception=str(exc))
    def next_session(self,deadline):
        while True:
            hot=getattr(self,'camera_handoff',None)
            if hot is not None:hot.close_unused()
            with self.condition:
                if self.error is not None:raise self.error
                if self.stopping or time.perf_counter()>=deadline:return None
                if self.display is not None and self.display.error is not None:raise self.display.error
                if self.page!='home':return self.page,self.ticket
                left=deadline-time.perf_counter();idle=hot.idle_remaining() if hot is not None else None
                self.condition.wait(min(left,1.,idle) if idle is not None else min(left,1.))
    def wait_fixed_page(self,generation,deadline,context=None):
        while True:
            hot=getattr(self,'camera_handoff',None)
            if hot is not None:hot.close_unused()
            task=None
            with self.condition:
                if self.stopping or self.generation!=generation or self.page!='snapshot':return
                if self.error is not None:raise self.error
                if self.display is not None and self.display.error is not None:raise self.display.error
                remaining=deadline-time.perf_counter()
                if remaining<=0:return
                if context is not None and self.ratio is not None and self.ratio.snapshot_task is not None:
                    task=self.ratio.snapshot_task;self.ratio.snapshot_task=None
                else:self.condition.wait(min(remaining,1.))
            if task is not None:self.ratio.reprocess_snapshot(context,task)
    def finish(self,ticket,error=False):
        with self.condition:
            ticket.fixed_input=None
            if self.ticket is ticket:self.request('home',error=error)
    def stop(self):
        with self.condition:
            profile=getattr(self,'profile',None)
            if profile is not None:profile.cancel('application_stop')
            if self.hold is not None:self.hold.end('application_stop')
            self.stopping=True;self.cancel.set();self.ticket.fixed_input=None;self.condition.notify_all()


@dataclass
class UISession:
    backend:object
    display:object
    ticket:object
    native_setup:object
    hot:object=None
    @property
    def cancel(self):return self.ticket.cancel
    @property
    def generation(self):return self.ticket.generation
    def check(self):
        if self.cancel.is_set():raise UIReturnRequested()
    def set_phase(self,phase):
        self.check()
        if phase not in ('preparing','placement','acquiring','running'):raise ValueError('Unknown startup phase')
        self.ticket.phase=phase
        self.display.set_target_phase({'preparing':'prepare','placement':'prepare','acquiring':'edges','running':'display'}[phase],self.generation)
        checkpoint('UI_SESSION_PHASE',generation=self.generation,phase=phase,
            placement_confirmed=self.ticket.placement.is_set())


from tracking import policy_run as policy_run

@logged_run
@policy_run
def run_ui(device='/dev/video0',touch_device='auto',bitfile='system.bit',max_duration_s=7200.,
           max_frames=0,warmup_frames=5,swap_xy=False,invert_x=False,invert_y=False,
           width=640,height=480,fps=30,output_size=(362,512),hdmi_mode=(1280,720),
           hdmi_max_fps=30.,timeout_s=3.,snapshot_timeout_s=20.,confirm_placement=False,
           capture_dir='/home/xilinx/captures',capture_jpeg_quality=90,**camera_options):
    """Cached home, press-action return, and one processing session for both live layouts."""
    if not 1<=float(max_duration_s)<=7200:raise ValueError('UI duration must be1..7200 seconds')
    if tuple(hdmi_mode)!=(1280,720):raise ValueError('V77 preserves HDMI1280x720')
    #   ⭐ 2026-10-27：允许 800x600（600P）。显示层会把超过面板的源等比缩到面板内
    #      （v64_hdmi_display.HdmiLatest._fit_shape），点选坐标由
    #      v82_interaction 的 _to_source() 按 source_shape 换算回原图。
    if (int(width),int(height)) not in ((640,480),(800,600)):
        raise ValueError('V77 UI camera mode must be 640x480 or 800x600, got %dx%d'%(width,height))
    if isinstance(max_frames,bool) or not isinstance(max_frames,int) or max_frames<0:raise ValueError('Invalid max_frames')
    if isinstance(warmup_frames,bool) or not isinstance(warmup_frames,int) or warmup_frames<0 or (max_frames and max_frames<=warmup_frames):raise ValueError('Invalid warmup_frames')
    if any(k.startswith('_') for k in camera_options):raise ValueError('Private UI session arguments are internal')
    if not 2<=float(snapshot_timeout_s)<=60:raise ValueError('Snapshot capture timeout must be2..60 seconds')
    if not isinstance(confirm_placement,bool):raise ValueError('confirm_placement must be bool')
    if confirm_placement:checkpoint('LEGACY_PLACEMENT_OPTION_IGNORED',automatic_admission=True)
    confirm_placement=False
    root=Path(__file__).resolve().parent;hardware=(root/bitfile).resolve();verify_package(str(hardware))
    cv2.setNumThreads(1)
    from display import P1Backend as P1Backend
    from display import HdmiLatest as HdmiLatest
    from tracking import NativeSetup as NativeSetup
    import display as camera_module
    if camera_module._POISONED:raise RuntimeError('Previous session cleanup unsafe; restart board as run-result.log instructs')
    profile=camera_profile_for(width,height)
    #   档位表是唯一权威：即使 notebook 里 tracking_max_dim 写错，也按档位纠正。
    camera_options['tracking_max_dim']=CAMERA_PROFILES[profile]['tracking_max_dim']
    assets=UIAssets(hdmi_mode);state=UIState(assets,confirm_placement)
    native_setup=NativeSetup()
    hot=CameraHandoff(state);state.camera_handoff=hot
    backend=display=touch=None;failure=None;cleanup=[];interrupted=False;ai_service=None
    sessions=deque(maxlen=4);session_count=0;frames=current=held=lost=0;fixed_captures=0;manual_corrections=0
    began=time.perf_counter();deadline=began+float(max_duration_s)
    try:
        # Validate touch before downloading hardware. Its worker is blocked in select when idle.
        touch=TouchInput(touch_device,hdmi_mode,state.touch,state.input_error,swap_xy,invert_x,invert_y)
        #   ⚠️ 输入 CMA 按**最大档位**分配（`P1Backend.input_shape` 只用于分配，
        #      实际尺寸来自每帧相机图像），这样切档时不用重新申请 DMA 内存。
        backend=P1Backend(str(hardware),MAX_INPUT_SHAPE,output_size,timeout_s)
        #   ⚠️⚠️ `P1Backend.input_shape` 在构造里**只用来分配两块 CMA**（`h*w*4`），
        #      分配完就没有运行期用途；但 `run_camera_hdmi:494` 和 `v76_snapshot:47`
        #      都会拿它和**当前档位**比对：
        #          `if backend.input_shape!=(height,width): raise ValueError('Borrowed UI resources do not match')`
        #      2026-10-29 现场：分配用最大档位后没改回来 ⇒ 切到 480P 后每个会话都抛
        #      `Borrowed UI resources do not match camera options`（25 次），
        #      表现成"闪退到首页之后点不进去"。
        #      ⇒ **分配用容量，比对用有效尺寸**，两个含义分开存。
        backend.capacity_shape=MAX_INPUT_SHAPE
        backend.input_shape=(height,width)
        try:
            display=HdmiLatest(backend.overlay,hdmi_mode,output_size,timeout_s,
                hold_max_age_s=camera_options.get('hold_max_age_s',1.5),
                input_shape=(height,width),max_fps=hdmi_max_fps,ui_assets=assets,
                capture_dir=capture_dir,capture_jpeg_quality=capture_jpeg_quality)
        except BaseException as exc:
            backend.failed=not bool(getattr(exc,'hdmi_shutdown_safe',False));raise
        #   ⚠️ `camera_profile` 必须在 `bind()` **之前**赋值 —— `bind()` 里会创建
        #      `ProfileUI`，它在 `__init__` 就按当前档位初始化按钮文字。
        #      2026-10-29 现场：赋值在 bind 之后 ⇒ 实际跑 800x600，按钮却写"480P"。
        display.sharp_control=backend.sharp_control
        display.light_control=backend.light_control
        state.camera_profile=profile;state.pending_profile=None
        state.bind(display)
        # ---- 相机输入档位：请求 → 结束本会话 → 下次会话用新档位重开（自动重新定位）----
        def request_camera_profile(name):
            """由 `v119_profile_ui.ProfileUI` 调用。只登记请求并结束当前会话，
            真正的换档在会话循环里做（相机必须已经关掉）。"""
            if name not in CAMERA_PROFILES or name==state.camera_profile:return False
            with state.condition:
                if state.stopping or state.page not in ('compare','rectified'):return False
                if state.ticket.phase!='running':return False
                state.pending_profile=name
                accepted=bool(state.request(state.page,refind=True,profile_switch=True))
                if not accepted:state.pending_profile=None
            checkpoint('CAMERA_PROFILE_SWITCH_REQUESTED',from_profile=state.camera_profile,
                to_profile=name,reason='new_input_session; target re-localized automatically')
            return accepted
        state.request_camera_profile=request_camera_profile
        # Preserve an exceptionally early touch that arrived during overlay setup.
        if state.generation:display.request_view(state.page,state.generation)
        checkpoint('UI_READY',durable=True,hdmi_mode=list(hdmi_mode),home_buttons=[b[0] for b in assets.buttons],
            return_location='top_left_press',back_hit_rect=list(assets.back),return_debounce_s=state.debounce_s,
            live_layout_switch='top_right_release',live_layout_reuses_camera_tracker_H=True,
            placement_confirmation=confirm_placement,native_setup_lifetime='whole application; survives home return',
            manual_calibration='explicit frozen four points; separate manual authority',
            reading='event-only frozen2x/4x; processing continues',placement_guidance_enabled=False,
            hdmi_scale=False,backend_reloaded_between_pages=False,
            background='static cached BGR; never decoded in a camera frame',touch=touch.detail)
        # HDMI has already initialized its IO helper; CPU-only tracker work can
        # now warm while home is idle. Returning home never restarts compilation.
        native_setup.start(trigger='home_ready')
        from ai import attach as attach_ai
        ai_service=attach_ai(state,native_setup)
        while True:
            hot.close_unused()
            choice=state.next_session(deadline)
            if choice is None:break
            page,ticket=choice
            if ticket.cancel.is_set():continue
            #   ⭐ 2026-10-29：切档在这里落地 —— 旧会话已经结束、相机已关，
            #      现在换相机尺寸 / 帧率 / tracking_max_dim，并让显示层重建 raw_pool。
            pending=getattr(state,'pending_profile',None)
            if pending and pending!=profile:
                p=CAMERA_PROFILES[pending]
                try:
                    hot.prepare_profile(ticket,camera_key(device,p['width'],p['height'],p['fps'],camera_options.get('color_mode')))
                    display.rescale_input((p['height'],p['width']))
                except BaseException as exc:
                    previous=CAMERA_PROFILES[profile]
                    hot.prepare_profile(ticket,camera_key(device,previous['width'],previous['height'],previous['fps'],camera_options.get('color_mode')))
                    checkpoint('UI_CAMERA_PROFILE_FAILED',requested=pending,active_profile=profile,
                        exception_type=type(exc).__name__,exception=str(exc)[:400],
                        previous_setting_retained=True)
                    with state.condition:state.pending_profile=None
                    if getattr(state,'profile',None) is not None:state.profile.failed('rescale_rejected')
                else:
                    profile=pending;width=p['width'];height=p['height'];fps=p['fps']
                    camera_options['tracking_max_dim']=p['tracking_max_dim']
                    #   有效尺寸跟着档位走（CMA 缓冲仍然是按容量分配的，不重分配）
                    backend.input_shape=(height,width)
                    with state.condition:
                        state.camera_profile=profile;state.pending_profile=None
                    if getattr(state,'profile',None) is not None:state.profile.applied(profile,ticket.generation)
                    checkpoint('UI_CAMERA_PROFILE_APPLIED',active_profile=profile,
                        width=width,height=height,fps=fps,
                        tracking_max_dim=p['tracking_max_dim'],
                        scope='new input session; target re-localized from scratch')
            generation=ticket.start_generation
            if ticket.cancel.is_set():continue
            ai_service.prepare_live(mode='ai' if ticket.ai else 'manual_selection' if ticket.manual else 'live')
            context=UISession(backend,display,ticket,native_setup,hot)
            if backend.active or backend.failed or backend.closed:raise RuntimeError('P1 backend is unsafe to reuse')
            # Old lookahead jobs had their leases drained before the prior session returned.
            # Indices restart at1; never accept an old (index,slot) prefill receipt.
            backend.packed.clear()
            checkpoint('UI_SESSION_BEGIN',generation=generation,view=page,tracking='fresh initial admission')
            ratio_scope=state.ratio.registry.scope('manual' if ticket.manual else 'auto')
            ratio_scope.__enter__()
            state.ratio.header(state.ratio.registry.applied['manual' if ticket.manual else 'auto'][0])
            try:
                if ticket.manual:
                    runner=run_manual
                    if ticket.ai:
                        runner=run_ai
                    result=runner(context,device=device,width=width,height=height,fps=fps,
                        output_size=output_size,max_frames=max_frames,warmup_frames=warmup_frames,
                        deadline=deadline,options=camera_options)
                elif page=='snapshot':
                    from display import capture_one as capture_one
                    result=capture_one(context,device=device,width=width,height=height,fps=fps,
                        output_size=output_size,capture_timeout_s=min(float(snapshot_timeout_s),max(.1,deadline-time.perf_counter())),
                        options=camera_options,app_deadline=deadline)
                else:
                    result=camera_module.run_camera_hdmi.__wrapped__(device=device,bitfile=bitfile,
                        max_frames=max_frames,warmup_frames=warmup_frames,width=width,height=height,fps=fps,
                        output_size=output_size,hdmi_mode=hdmi_mode,hdmi_max_fps=hdmi_max_fps,timeout_s=timeout_s,
                        max_duration_s=max(1.,deadline-time.perf_counter()),_ui_context=context,**camera_options)
                session_count+=1
                frames+=result['frames'];current+=result['current'];held+=result['held'];lost+=result['lost']
                manual_corrections+=result.get('manual_corrections',0)
                # Retain four compact session summaries, not four512-row diagnostic trees.
                summary={k:result[k] for k in ('status','frames','current','held','lost','current_correction_fps',
                    'delivered_fps','hdmi_current_fps','hdmi_submit_fps','formal_elapsed_s','timing','hdmi_timing')}
                summary.update(view=page,view_at_end=ticket.page,generation=generation,
                    final_display_generation=ticket.generation);sessions.append(summary)
                summary['manual_corrections']=result.get('manual_corrections',0)
                summary['manual_fps']=result.get('manual_fps',0.)
                if page=='snapshot':summary['snapshot']=result.get('snapshot')
                checkpoint('UI_SESSION_END',**summary)
                if result.get('user_interrupted'):
                    interrupted=True;break
                if page=='snapshot' and result.get('fixed_frame',False):
                    fixed_captures+=1;state.wait_fixed_page(ticket.generation,deadline,context)
                state.finish(ticket)
            except UIReturnRequested:
                state.finish(ticket)
            except Exception as exc:
                if backend.failed or backend.active or camera_module._POISONED or display.error is not None:raise
                checkpoint('UI_SESSION_START_FAILED',durable=True,generation=generation,
                    exception_type=type(exc).__name__,exception=str(exc),traceback=__import__('traceback').format_exc(),safe_to_retry=True)
                state.finish(ticket,error=True)
            finally:ratio_scope.__exit__(None,None,None)
    except KeyboardInterrupt:
        interrupted=True;checkpoint('UI_USER_STOP',durable=True)
    except BaseException as exc:failure=exc
    finally:
        state.stop()
        try:hot.close()
        except BaseException as exc:
            cleanup.append(('hot_camera',repr(exc)));_RETAINED__v75_ui.append(hot)
            camera_module._POISONED=True
        try:native_setup.close()
        except BaseException as exc:
            cleanup.append(('native_setup',repr(exc)));_RETAINED__v75_ui.append(native_setup)
        if ai_service is not None:
            try:ai_service.close()
            except BaseException as exc:cleanup.append(('ai_service',repr(exc)));_RETAINED__v75_ui.append(ai_service)
        if touch is not None:
            try:touch.close()
            except BaseException as exc:cleanup.append(('touch',repr(exc)))
        # A failed PS/camera cleanup may still refer to overlay/CMA: retain everything.
        unsafe=camera_module._POISONED
        display_stopped=display is None
        if display is not None:
            try:display.close();display_stopped=True
            except BaseException as exc:
                display_stopped=bool(display.shutdown_safe);cleanup.append(('hdmi',repr(exc)))
        if backend is not None and display_stopped and not unsafe:
            try:backend.close()
            except BaseException as exc:cleanup.append(('backend',repr(exc)))
        if unsafe or not display_stopped or (backend is not None and not backend.closed):
            _RETAINED__v75_ui.append((backend,display,state,touch))
            camera_module._POISONED=True
            camera_module._POISON_REASON=list(camera_module._POISON_REASON)+cleanup+[('ui','resources retained')]
        if cleanup:checkpoint('UI_CLEANUP_FAILED',durable=True,errors=cleanup)
    if failure is not None:raise failure
    if cleanup:raise RuntimeError('UI cleanup incomplete: '+str(cleanup))
    return dict(release_id=RELEASE_ID,status='stopped' if interrupted else 'completed',
        sessions=session_count,frames=frames,current=current,held=held,lost=lost,
        fixed_captures=fixed_captures,snapshot_images_saved=0,snapshot_recapture_requests=state.recapture_requests,
        manual_corrections=manual_corrections,automatic_CURRENT_includes_manual=False,
        explicit_refind_requests=state.refind_requests,
        live_layout_switches=state.layout_switches,touch_contacts=dict(state.contact_counts),
        session_summaries=list(sessions),ui_wall_s=time.perf_counter()-began,
        fps_scope='each camera session excludes idle home time; do not divide by UI wall time',
        display=display.snapshot(include_samples=False) if display is not None else None)


# ======================================================================
# ===== [03/35] v82_interaction =====
# ======================================================================


"""Event-only inspection pages and low-rate placement hints; no device IO."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

MANUAL_RECT=(180,0,200,72)
REFIND_RECT=(380,0,200,72)
ZOOM_RECT=(580,0,180,72)
SOURCE_RECT=(24,148,640,480)
CALIB_CONTROLS={'undo':(716,366,244,64),'refresh':(980,366,244,64),
    'confirm':(716,446,244,72),'auto':(980,446,244,72)}
AI_CONTROLS={'refresh':(716,366,244,64),'retry':(980,366,244,64),
    'manual':(716,446,244,64),'auto':(980,446,244,64)}
AI_STAGES=('queued','loading','ready','busy','parent_preprocess','parent_fit_corners',
    'inference','check_assets','import_numpy','import_ncnn','load_parameters','load_weights','warmup')
ZOOM_CONTROLS={'zoom_scale':(716,560,244,64),'zoom_close':(980,560,244,64)}
CALIB_LOUPE=(716,148,240,192)
CORNER_HIT_RADIUS=28
CALIB_CONTROLS.update({name:(716+i*128,630,112,56)
    for i,name in enumerate(('left','up','down','right'))})


def inside__v82_interaction(point,rect):
    x,y,w,h=rect
    return point is not None and x<=point[0]<x+w and y<=point[1]<y+h


def selected_quad(points,shape):
    """Explicit user selection still requires a visible convex geometric quad."""
    if len(points)!=4:raise ValueError('Select all four corners first')
    q=np.asarray(points,np.float32).reshape(4,2)
    if not np.isfinite(q).all():raise ValueError('Invalid manual coordinates')
    hull=cv2.convexHull(q).reshape(-1,2)
    if len(hull)!=4:raise ValueError('Four distinct exterior corners are required')
    from geometry import order_corners as order_corners
    from tracking import _visible_quad as _visible_quad
    return _visible_quad(order_corners(hull),shape,preserve_order=True)


class Inspection:
    """One immutable ordinary-RAM source; HDMI owner alone renders/submits it.

    Every method uses the display condition. No touch handler reads pooled video
    pixels or owns a camera/VDMA lease. Requests have a page generation and token.
    """
    def __init__(self,display):
        self.display=display;self.kind=None;self.generation=-1;self.token=0
        self.source=None;self.source_rect=None;self.points=();self.action=None
        self.dirty=False;self.zoom_requested=None;self.scale=2;self.focus=None
        self.notice='';self.meta={};self.opened=0;self.redraws=0
        self.selected=None;self.edit_history=[];self.edit_contact=None
        from display import ReadingPan as ReadingPan
        self.reading=ReadingPan(self)
    def clear_locked(self):
        self.kind=None;self.source=None;self.source_rect=None;self.points=()
        self.action=None;self.dirty=False;self.zoom_requested=None;self.focus=None;self.meta={}
        self.selected=None;self.edit_history=[];self.edit_contact=None
        self.token+=1;self.reading.clear_locked()
    #   ⭐ 2026-10-27：坐标换算。源图（800x600）在屏幕上是被等比缩小显示的
    #      （v64_hdmi_display.HdmiLatest._fit_shape），所以：
    #        屏幕点 → 源图点：先减矩形原点，再乘 (源宽/矩形宽)
    #      640x480 时缩放系数恒为 1，行为与改动前完全一致。
    def _source_size(self):
        sh=self.meta.get('source_shape') if isinstance(self.meta,dict) else None
        if not sh or len(sh)!=2 or not self.source_rect:return self.source_rect[2],self.source_rect[3]
        return int(sh[1]),int(sh[0])
    #   ⚠️ 必须与 `v64_hdmi_display.preview_scale_enabled()` **完全一致**：
    #      True = 等比缩放（乘系数）；False = 居中裁剪（加偏移）。
    #   ⭐ 2026-10-28：显示改成【绘制时用原生缩放】（见 `v64_hdmi_display._draw`），
    #      所以这里**恒为等比缩放**，不再依赖 OpenCV 的 BGR→YUYV 编码常量。
    _SCALE_PREVIEW = True

    def _source_offset(self):
        if self._SCALE_PREVIEW:
            return 0, 0
        sw, sh = self._source_size()
        _, _, w, h = self.source_rect
        return max(0, (sw - int(w)) // 2), max(0, (sh - int(h)) // 2)

    def _source_scale(self):
        if not self._SCALE_PREVIEW:
            return 1., 1.
        sw, sh = self._source_size()
        _, _, w, h = self.source_rect
        return (float(sw) / max(1, w), float(sh) / max(1, h))

    def _to_source(self, point):
        x, y = self.source_rect[0], self.source_rect[1]
        ox, oy = self._source_offset()
        sx, sy = self._source_scale()
        return (float(point[0] - x) + ox) * sx, (float(point[1] - y) + oy) * sy
    def _clamp_source(self,x,y):
        sw,sh=self._source_size()
        return (float(np.clip(x,0,sw-1)),float(np.clip(y,0,sh-1)))
    def begin_calibration(self,raw,color_mode,generation,sequence):
        # Caller owns the frozen raw source until confirmation/retirement.
        from display import yuyv_bgr_into as yuyv_bgr_into
        h,w=raw.shape[:2];image=np.empty((h,w,3),np.uint8)
        yuyv_bgr_into(raw,color_mode,image,(0,0,w,h))
        image.setflags(write=False)
        with self.display.condition:
            if generation!=self.display.ui_generation or self.display.stop:return False
            self.clear_locked();self.kind='calibration';self.generation=generation
            self.source=image;self.source_rect=SOURCE_RECT;self.points=();self.notice='select'
            self.meta=dict(sequence=int(sequence),source_shape=tuple(raw.shape[:2]))
            self.dirty=True;self.opened+=1;self.display.pending=None;self.display.condition.notify_all()
        checkpoint('MANUAL_CALIBRATION_FROZEN',generation=generation,sequence=int(sequence),
            source_shape=list(raw.shape[:2]),source_rect=list(SOURCE_RECT),coordinate_mapping='native 1to1; frozen source',hardware_access=False)
        return True
    def request_zoom(self,generation):
        with self.display.condition:
            if generation!=self.display.ui_generation or self.display.stop or self.kind:return False
            if self.display.latest_meta.get('ui_generation')!=generation:return False
            if self.display.ui_view=='snapshot' and self.display.frozen_generation!=generation:return False
            if self.display.latest_meta.get('state') not in ('CURRENT','HELD','MANUAL','MANUAL_HELD'):
                return False
            self.zoom_requested=generation;self.display.condition.notify_all();return True
    def open_zoom_locked(self,image,meta):
        generation=int(meta.get('ui_generation',-1))
        if self.zoom_requested!=generation or generation!=self.display.ui_generation:return False
        if self.display.pending is not None:
            self.display.pending=None;self.display.ui_discarded+=1
        self.clear_locked();self.kind='zoom';self.generation=generation
        self.source=np.array(image,copy=True,order='C');self.source.setflags(write=False)
        h,w=self.source.shape[:2]
        #   ⚠️ 2026-10-31：600P 时 w=800 会让 x=24+(640-800)//2=-56，负索引切片变空 ⇒
        #      再赋值就 ValueError。夹到非负；640x480 档 x=24、y=134，与改动前相同。
        self.source_rect=(max(0,24+(640-w)//2),max(0,100+(548-h)//2),w,h)
        self.focus=(w//2,h//2);self.scale=2;self.meta=dict(sequence=meta.get('camera_sequence'),source_shape=(h,w),page=self.display.ui_view)
        self.dirty=True;self.opened+=1
        checkpoint('READING_FREEZE_READY',generation=generation,sequence=meta.get('camera_sequence'),
            source_shape=[h,w],fixed_source=True,processing_continues=True,ordinary_RAM_bytes=self.source.nbytes)
        return True
    def target(self,point,generation):
        with self.display.condition:
            if self.kind is None or generation!=self.generation:return None
            if self.kind=='calibration':
                if self.meta.get('ai_only'):
                    for name,rect in AI_CONTROLS.items():
                        if inside__v82_interaction(point,rect):return 'inspect_'+name
                    return 'inspect_background'
                if inside__v82_interaction(point,self.source_rect):return 'inspect_point'
                for name,rect in CALIB_CONTROLS.items():
                    if inside__v82_interaction(point,rect):return 'inspect_'+name
            elif self.kind=='zoom':
                target=self.reading.target_locked(point)
                if target is not None:return target
                for name,rect in ZOOM_CONTROLS.items():
                    if inside__v82_interaction(point,rect):return 'inspect_'+name
            return 'inspect_background'
    def _point_notice_locked(self):
        self.notice='select'
        if len(self.points)==4:
            try:selected_quad(self.points,self.meta['source_shape'])
            except ValueError:self.notice='invalid'
            else:self.notice='ready'
    def _edit_redraw_locked(self):
        self._point_notice_locked();self.dirty=True;self.display.condition.notify_all()
    def _remember_locked(self,points,selected):
        self.edit_history.append((points,selected))
        if len(self.edit_history)>64:del self.edit_history[0]
    def begin_point_contact(self,point,generation,contact_id):
        """Stage an edit on frozen RAM; a matching release alone commits it."""
        with self.display.condition:
            if (self.kind!='calibration' or generation!=self.generation or self.notice in ('busy','ai_busy')
                    or contact_id is None or not inside__v82_interaction(point,self.source_rect)):
                return False,'corner_edit_unavailable',self.token
            if self.edit_contact is not None:return False,'corner_contact_busy',self.token
            x,y,w,h=self.source_rect;p=self._to_source(point)
            distances=[np.hypot(p[0]-a,p[1]-b) for a,b in self.points]
            index=int(np.argmin(distances)) if distances and min(distances)<=CORNER_HIT_RADIUS else None
            before=self.points;old_selected=self.selected
            if index is None:
                if len(before)>=4:return False,'touch_existing_corner_to_adjust',self.token
                index=len(before);offset=(0.,0.);self.points=before+(p,)
            else:offset=(before[index][0]-p[0],before[index][1]-p[1])
            self.edit_contact=dict(contact_id=contact_id,token=self.token,generation=generation,
                index=index,before=before,selected=old_selected,offset=offset)
            self.selected=index;self.focus=self.points[index];self._edit_redraw_locked()
            return True,'corner_contact_started',self.token
    def _matching_contact_locked(self,event,generation):
        edit=self.edit_contact;origin=event.get('press_outcome') or {}
        return bool(edit is not None and self.kind=='calibration' and self.generation==generation
            and edit['generation']==generation and edit['token']==self.token
            and origin.get('inspection_token')==self.token and event.get('contact_id')==edit['contact_id'])
    def _update_contact_locked(self,point):
        edit=self.edit_contact
        bx,by=self._to_source(point)
        p=self._clamp_source(bx+edit['offset'][0],by+edit['offset'][1])
        points=list(self.points);points[edit['index']]=p;self.points=tuple(points)
        self.focus=p;self._edit_redraw_locked()
    def move_point_contact(self,event,generation):
        with self.display.condition:
            if not self._matching_contact_locked(event,generation):return False,'corner_contact_changed'
            point=event.get('position')
            if point is None:return False,'missing_move_coordinates'
            self._update_contact_locked(point)
            return True,'corner_drag_preview'
    def cancel_point_contact(self,contact_id=None):
        with self.display.condition:
            edit=self.edit_contact
            if edit is None or (contact_id is not None and contact_id!=edit['contact_id']):return False
            self.points=edit['before'];self.selected=edit['selected'];self.edit_contact=None
            self.focus=self.points[self.selected] if self.selected is not None else None
            self._edit_redraw_locked();return True
    def finish_point_contact(self,event,generation):
        with self.display.condition:
            if not self._matching_contact_locked(event,generation):return False,'corner_contact_changed'
            if event.get('release') is None:
                self.cancel_point_contact(event.get('contact_id'));return False,'missing_release_coordinates'
            edit=self.edit_contact
            self._update_contact_locked(event['release'])
            p=self.points[edit['index']]
            if any(i!=edit['index'] and np.hypot(p[0]-q[0],p[1]-q[1])<10 for i,q in enumerate(self.points)):
                self.cancel_point_contact(event.get('contact_id'));return False,'corners_too_close'
            changed=self.points!=edit['before']
            if changed:self._remember_locked(edit['before'],edit['selected'])
            self.edit_contact=None;self._edit_redraw_locked()
            checkpoint('MANUAL_CORNER_EDIT',generation=generation,sequence=self.meta['sequence'],
                corner=edit['index']+1,point=p,changed=changed,points=len(self.points),
                operation='place' if len(edit['before'])<len(self.points) else 'drag',
                frozen_source=True,hardware_access=False)
            return True,'corner_edit_committed' if changed else 'corner_selected'
    def release(self,target,press,release,generation,token=None):
        with self.display.condition:
            if generation!=self.generation or self.kind is None or token!=self.token:return False,'inspection_changed'
            if self.target(release,generation)!=target:return False,'release_outside_target'
            if self.kind=='calibration' and self.notice=='busy':return False,'calibration_busy'
            if self.kind=='calibration' and self.notice=='ai_busy' and target not in ('inspect_refresh','inspect_auto','inspect_manual'):
                return False,'ai_request_busy'
            if self.kind=='calibration' and self.edit_contact is not None:return False,'finish_corner_drag_first'
            if target=='inspect_point':return False,'point_requires_matching_contact'
            elif target=='inspect_undo':
                if not self.edit_history:return False,'no_corner_edit_to_undo'
                self.points,self.selected=self.edit_history.pop()
                self.focus=self.points[self.selected] if self.selected is not None else None
                self._point_notice_locked()
                checkpoint('MANUAL_CORNER_UNDO',generation=generation,points=len(self.points),frozen_source=True)
            elif target in ('inspect_left','inspect_up','inspect_down','inspect_right'):
                if self.selected is None:return False,'select_corner_before_nudge'
                delta={'inspect_left':(-1,0),'inspect_up':(0,-1),'inspect_down':(0,1),'inspect_right':(1,0)}[target]
                before=self.points;old_selected=self.selected;p=before[self.selected]
                q=self._clamp_source(p[0]+delta[0],p[1]+delta[1])
                if q==p:return False,'corner_at_source_boundary'
                if any(i!=self.selected and np.hypot(q[0]-v[0],q[1]-v[1])<10 for i,v in enumerate(before)):
                    return False,'corners_too_close'
                self._remember_locked(before,old_selected)
                points=list(before);points[self.selected]=q;self.points=tuple(points);self.focus=q
                self._point_notice_locked()
            elif target=='inspect_retry':
                if not self.meta.get('ai_only'):return False,'not_ai_page'
                return self.queue_ai(generation,ai_only=True),'ai_retry_queued'
            elif target=='inspect_manual':
                if not self.meta.get('ai_only'):return False,'not_ai_page'
                self.action=('manual',None);self.notice='busy'
                checkpoint('AI_MANUAL_FALLBACK_REQUESTED',generation=generation,explicit_user=True)
            elif target=='inspect_refresh':self.action=('refresh',None);self.notice='busy'
            elif target=='inspect_confirm':
                try:q=selected_quad(self.points,self.meta['source_shape'])
                except ValueError:self.notice='invalid';self.dirty=True;self.display.condition.notify_all();return False,'manual_quad_invalid'
                self.action=('confirm',q.copy());self.notice='busy'
                checkpoint('MANUAL_CORNERS_CONFIRMED',generation=generation,sequence=self.meta['sequence'],
                    corners=q.tolist(),authority='explicit user four points',automatic_edge_proof=False,hardware_proof_still_required=True)
            elif target=='inspect_auto':self.action=('auto',None);self.notice='busy'
            elif target=='inspect_focus':
                fx,fy=self._to_source(release)
                fx,fy=self._clamp_source(fx,fy)
                self.focus=(int(fx),int(fy))
            elif target=='inspect_zoom_scale':
                self.reading.cancel_locked();self.scale=4 if self.scale==2 else 2
            elif target=='inspect_zoom_close':
                self.clear_locked();self.display.canvas_views.clear();self.display.layouts.clear()
                self.display.inspection_restore=bool(self.display.ui_view=='snapshot' and self.display.last_static_packet is not None)
                self.display.condition.notify_all();return True,'reading_closed_resume_latest'
            else:return False,'outside_controls'
            self.dirty=True;self.display.condition.notify_all();return True,target
    def begin_ai(self,raw,color_mode,generation,sequence):
        if not self.begin_calibration(raw,color_mode,generation,sequence):return False
        return self.queue_ai(generation,ai_only=True)
    def ai_progress(self,generation,stage):
        with self.display.condition:
            if (self.generation!=generation or self.notice!='ai_busy'
                    or self.display.ui_generation!=generation or self.display.stop):return
            if self.meta.get('ai_stage')==stage:return
            self.meta['ai_stage']=stage;self.dirty=True;self.display.condition.notify_all()
    def ai_alignment_failed(self,generation,error):
        with self.display.condition:
            if (self.generation!=generation or self.display.ui_generation!=generation
                    or self.display.stop or not self.meta.get('ai_only')):return
            self.notice='ai_alignment_failed';self.action=None;self.dirty=True
            self.display.condition.notify_all()
            checkpoint('AI_ALIGNMENT_REJECTED',generation=generation,error=str(error)[:1200],
                retry_available=True,manual_fallback='explicit_user_only')
    def queue_ai(self,generation,ai_only=False):
        with self.display.condition:
            if (self.kind!='calibration' or self.generation!=generation
                    or self.display.ui_generation!=generation or self.display.stop
                    or self.source is None or self.notice in ('busy','ai_busy')):return False
            self.meta['ai_request_id']=int(self.meta.get('ai_request_id',0))+1
            self.meta['ai_only']=bool(ai_only)
            self.meta['ai_stage']='queued'
            self.action=('ai',None);self.notice='ai_busy';self.dirty=True
            self.display.condition.notify_all();return True
    def ai_input(self,generation):
        with self.display.condition:
            if (self.kind!='calibration' or self.generation!=generation
                    or self.display.ui_generation!=generation or self.display.stop
                    or self.notice!='ai_busy' or self.source is None):
                raise ValueError('AI selection is no longer current')
            receipt=dict(release_id=RELEASE_ID,generation=generation,token=self.token,
                sequence=self.meta['sequence'],request_id=self.meta['ai_request_id'])
            return receipt,self.source
    def ai_failed(self,generation,error,failure_kind='runtime_error',diagnostics=None):
        with self.display.condition:
            if self.kind=='calibration' and self.generation==generation and self.notice=='ai_busy':
                self.notice=('ai_timeout' if failure_kind=='timeout' else 'ai_failed'
                    if failure_kind in ('no_plane','invalid_geometry') else 'ai_runtime_failed')
                self.dirty=True;self.display.condition.notify_all()
                checkpoint('AI_CORNERS_FAILED',generation=generation,error=str(error)[:1200],
                    failure_kind=failure_kind,diagnostics=diagnostics or [],manual_available=True)
    def apply_ai_result(self,receipt,source,result):
        with self.display.condition:
            expected=dict(release_id=RELEASE_ID,generation=self.generation,token=self.token,
                sequence=self.meta.get('sequence'),request_id=self.meta.get('ai_request_id'))
            if (self.kind!='calibration' or self.display.ui_generation!=self.generation
                    or self.display.stop or self.source is not source or self.notice!='ai_busy'
                    or self.action is not None or receipt!=expected
                    or any(result.get(k)!=v for k,v in expected.items())):
                return False
            if result.get('status')!='candidate':
                self.ai_failed(self.generation,result.get('error','AI did not complete'),
                    result.get('failure_kind','runtime_error'),result.get('diagnostics'));return False
            try:
                q=selected_quad(result['quad'],self.meta['source_shape'])
            except (ValueError,TypeError,KeyError) as exc:
                self.ai_failed(self.generation,exc,'invalid_geometry');return False
            self._remember_locked(self.points,self.selected)
            self.points=tuple(map(tuple,q.tolist()));self.selected=None;self.focus=None
            self.action=('confirm',q.copy());self.notice='busy'
            self.dirty=True;self.display.condition.notify_all()
            checkpoint('AI_CORNERS_CANDIDATE',generation=self.generation,sequence=self.meta['sequence'],
                corners=q.tolist(),request_id=receipt['request_id'],request_ms=result.get('request_ms'),
                worker_ms=result.get('worker_ms'),mask_fit_iou=result.get('mask_fit_iou'),
                authority='explicit AI click; AI seed to shared correction backend',
                model_sha256=result.get('model_sha256'),hardware_access=False)
            return True
    def take_action(self,generation):
        with self.display.condition:
            if generation!=self.generation:return None
            result=self.action;self.action=None;return result
    def end_calibration(self,generation):
        with self.display.condition:
            if self.generation==generation:
                self.clear_locked();self.display.canvas_views.clear();self.display.layouts.clear();self.display.condition.notify_all()
    def payload_locked(self):
        if not self.kind or not self.dirty:return None
        self.dirty=False;self.redraws+=1
        return dict(kind=self.kind,generation=self.generation,token=self.token,source=self.source,
            source_rect=self.source_rect,points=self.points,notice=self.notice,focus=self.focus,
            scale=self.scale,meta=dict(self.meta),selected=self.selected,dragging=self.edit_contact is not None)


def _ai_editor_assets(assets):
    # Decoded once on the explicitly requested AI page, never on a live frame.
    if hasattr(assets,'ai_header'):return
    root=Path(__file__).resolve().parent
    def read(name,shape):
        value=cv2.imdecode(np.frombuffer((root/name).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if value is None or value.shape!=shape:raise ValueError('Invalid AI UI asset '+name)
        return value
    assets.ai_header=read('v98_ai_header.png',(72,1280,3))
    assets.ai_help=read('v98_ai_help.png',(232,544,3))
    buttons=read('v102_ai_controls.png',(128,488,3))
    assets.ai_buttons={name:buttons[(i//2)*64:(i//2+1)*64,(i%2)*244:(i%2+1)*244]
        for i,name in enumerate(AI_CONTROLS)}
    assets.ai_retry_disabled=cv2.convertScaleAbs(assets.ai_buttons['retry'],alpha=.4)
    stages=read('v102_ai_stages.png',(len(AI_STAGES)*48,512,3))
    assets.ai_stage_patches={name:stages[i*48:(i+1)*48] for i,name in enumerate(AI_STAGES)}
    atlas=read('v98_ai_notices.png',(384,512,3))
    for i,name in enumerate(('ai_busy','ai_ready','ai_failed','ai_timeout','ai_runtime_failed','ai_alignment_failed')):
        assets.calibration_notices[name]=atlas[i*64:(i+1)*64]


def _render_ai(canvas,payload,assets):
    _ai_editor_assets(assets);canvas.fill(0);canvas[:72]=assets.ai_header
    x,y,w,h=payload['source_rect'];canvas[y:y+h,x:x+w]=payload['source']
    canvas[108:340,704:1248]=assets.ai_help
    for name,(a,b,c,d) in AI_CONTROLS.items():
        canvas[b:b+d,a:a+c]=(assets.ai_retry_disabled if name=='retry'
            and payload['notice'] in ('ai_busy','busy') else assets.ai_buttons[name])
    notice=assets.calibration_notices.get(payload['notice'],assets.calibration_notices['ai_ready'])
    canvas[540:604,716:1228]=notice
    stage=payload['meta'].get('ai_stage','queued')
    # Chinese stage text is cached with the UI assets; no font work on board.
    patch=assets.ai_stage_patches.get(stage,assets.ai_stage_patches['busy'])
    if payload['notice']=='ai_busy':canvas[620:668,716:1228]=patch
    cv2.putText(canvas,'AI | SOURCE seq=%s'%payload['meta']['sequence'],(32,112),
        cv2.FONT_HERSHEY_SIMPLEX,.65,(230,230,230),1,cv2.LINE_AA)


def render_inspection(canvas,payload,assets):
    """Called only by the existing HDMI owner; expensive work is event-only."""
    if payload['kind']=='ratio':
        from display import render_ratio as render_ratio
        return render_ratio(canvas,payload,assets)
    if payload['kind']=='album':
        return render_album(canvas,payload,assets)
    if payload['kind']=='zoom':
        from display import render_reading as render_reading
        return render_reading(canvas,payload,assets)
    if payload['kind']=='calibration' and payload['meta'].get('ai_only'):
        return _render_ai(canvas,payload,assets)
    canvas.fill(0)
    canvas[:72]=(assets.headers['snapshot'] if payload['kind']=='zoom' and payload['meta'].get('page')=='snapshot' else assets.ratio_reading_header if payload['kind']=='zoom' else assets.inspect_header)
    image=payload['source'];x,y,w,h=payload['source_rect']
    #   ⚠️ 2026-10-31：600P 的源图是 800x600，而 SOURCE_RECT 固定 640x480，
    #      直接赋值会 ValueError: could not broadcast (600,800,3) into (480,640,3)。
    #      640x480 档位两者相等，走原路径，行为不变。
    #      坐标换算不在这里做 —— `_source_scale()` 已按 (源/矩形) 处理好触摸点。
    if image.shape[:2]!=(h,w):
        canvas[y:y+h,x:x+w]=cv2.resize(image,(w,h),interpolation=cv2.INTER_NEAREST)
    else:
        canvas[y:y+h,x:x+w]=image
    if payload['kind']=='calibration':
        canvas[108:340,704:1248]=assets.calibration_help
        points=payload['points']
        selected=payload.get('selected')
        if selected is not None and selected<len(points):
            fx,fy=points[selected];oh,ow=image.shape[:2];lx,ly,lw,lh=CALIB_LOUPE
            span_w=min(ow,lw//4);span_h=min(oh,lh//4)
            sx=int(np.clip(round(fx)-span_w//2,0,ow-span_w));sy=int(np.clip(round(fy)-span_h//2,0,oh-span_h))
            cv2.resize(image[sy:sy+span_h,sx:sx+span_w],(lw,lh),dst=canvas[ly:ly+lh,lx:lx+lw],interpolation=cv2.INTER_NEAREST)
            px=lx+int(round((fx-sx+.5)*lw/span_w-.5));py=ly+int(round((fy-sy+.5)*lh/span_h-.5))
            cv2.line(canvas,(max(lx,px-13),py),(min(lx+lw-1,px+13),py),(0,230,255),1,cv2.LINE_AA)
            cv2.line(canvas,(px,max(ly,py-13)),(px,min(ly+lh-1,py+13)),(0,230,255),1,cv2.LINE_AA)
            cv2.rectangle(canvas,(lx-1,ly-1),(lx+lw,ly+lh),(80,230,255),1)
            cv2.putText(canvas,'P%d (%d, %d)'%(selected+1,round(fx),round(fy)),(980,328),cv2.FONT_HERSHEY_SIMPLEX,.48,(100,235,245),1,cv2.LINE_AA)
        if len(points)==4:
            try:q=selected_quad(points,payload['meta']['source_shape'])
            except ValueError:q=None
            if q is not None:cv2.polylines(canvas,[np.rint(q+[x,y]).astype(np.int32)],True,(80,230,255),2,cv2.LINE_AA)
        for i,p in enumerate(points):
            v=tuple(np.rint(np.asarray(p)+[x,y]).astype(int));cv2.circle(canvas,v,7,(30,230,255),2,cv2.LINE_AA)
            if i==selected:cv2.circle(canvas,v,14,(70,245,255),2,cv2.LINE_AA)
            cv2.putText(canvas,str(i+1),(v[0]+10,v[1]-8),cv2.FONT_HERSHEY_SIMPLEX,.65,(30,230,255),2,cv2.LINE_AA)
        for name,rect in CALIB_CONTROLS.items():
            a,b,c,d=rect;canvas[b:b+d,a:a+c]=assets.inspection_buttons[name]
        notice=payload['notice'];message=assets.calibration_notices.get(notice,assets.calibration_notices['select'])
        canvas[542:606,716:1228]=message
        cv2.putText(canvas,'POINTS %d / 4 | SOURCE seq=%s'%(len(points),payload['meta']['sequence']),
            (32,112),cv2.FONT_HERSHEY_SIMPLEX,.65,(230,230,230),1,cv2.LINE_AA)


# ======================================================================
# ===== [04/35] v82_assets =====
# ======================================================================


"""Decode V82 interaction labels once; no runtime fonts, web, or UI renderer."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def load_interaction_assets(assets,root):
    def read(name,shape):
        image=cv2.imread(str(root/name),cv2.IMREAD_COLOR)
        if image is None or image.shape!=shape:raise ValueError('Invalid V82 UI asset '+name)
        image.setflags(write=False);return image
    assets.manual=MANUAL_RECT;assets.zoom=ZOOM_RECT;assets.refind=REFIND_RECT
    for view in ('compare','rectified','snapshot'):
        assets.headers[view]=read('v82_header_'+view+'.png',(72,1280,3))
    assets.header=assets.headers['compare']
    assets.snapshot_busy=read('v82_header_busy.png',(72,1280,3))
    refind=read('v82_refind.png',(144,200,3));assets.refind_controls={'ready':refind[:72],'preparing':refind[72:]}
    assets.inspect_header=read('v82_header_inspect.png',(72,1280,3))
    assets.calibration_help=read('v82_calibration_help.png',(232,544,3))
    assets.reading_help=read('v82_reading_help.png',(48,512,3))
    assets.inspection_buttons={}
    for name,h in (('undo',64),('refresh',64),('confirm',72),('auto',72),('zoom_scale',64),('zoom_close',64)):
        assets.inspection_buttons[name]=read('v82_button_'+name+'.png',(h,244,3))
    for name in ('left','up','down','right'):
        assets.inspection_buttons[name]=read('v97_1_button_'+name+'.png',(56,112,3))
    notices=read('v82_calibration_notices.png',(256,512,3))
    assets.calibration_notices={name:notices[i*64:(i+1)*64] for i,name in enumerate(('select','ready','invalid','busy'))}
    manual=read('v82_manual_badges.png',(84,320,3))
    assets.status_badges.update({name:manual[i*28:(i+1)*28] for i,name in enumerate(('MANUAL','MANUAL_HELD','MANUAL_FIXED'))})


# ======================================================================
# ===== [05/35] v92_manual_v87 =====
# ======================================================================


"""Exact V87 manual FB tracker. Failure policy lives in the current controller."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

#   ⭐ 2026-10-26：手动模式的【静止门控】。
#   动机（run-result(18) 实测）：手动跟踪帧 `capture→output` **114.9 ms**，其中
#   `tracker_s` **66.8 ms**（双向金字塔 LK 3 层×20 迭代 + RANSAC 300 次），
#   而 PL 的 `dma_wait` 只有 9.8 ms ⇒ 慢 100% 在 PS 跟踪，且**纸完全不动也照跑**。
#   自动模式早有等价机制（`v87_v74_tracking._static_hold`），这里按同样口径补一份。
#
#   ⚠️ **为什么"跳过"也必须刷新锚点**：`update()` 开头有
#        if not self.first and not 0<elapsed<=.75: raise ValueError('expired_anchor')
#      跳过时若不更新 `previous_ready` / `self.gray`，超过 0.75 s 后恢复会直接失败。
#   ⚠️ **为什么要设最长保持时间**：门控可能判错（如光照突变但画面没动），
#      超过 `MAX_S` 强制做一次真实跟踪，作为兜底。
#   ⚠️ 开关：`P11_MANUAL_STATIC_HOLD=0` 可完全关闭，回到改动前行为。
#
#   ===== rev2（2026-10-26，run-result(92) 实测推翻 rev1）=====
#   rev1 用**固定阈值 4.0(进) / 8.0(出)** 直接照抄自动模式的数字 —— 这是错的。
#   自动模式那 4.0/8.0 是【乘了自适应噪声底】之后的**下限**：
#        limit = max(enter, enter_gain * floor)
#   而 rev1 少了 floor 这一层 ⇒ 退出阈值 = 实测噪声底(0.55) 的 **14.5 倍**，永远够不着。
#
#   实测后果：1219/1297 帧被判"静止"，真实跟踪只剩 **每 912 ms 一次**
#   （68 帧 / 74.9 s），而被跳过的帧上纸的角点位移 **100% 是 0** ——
#   也就是"帧率上去了，动态跟随变成 0.9 秒一跳一格"。用户反馈正是这句。
#
#   rev2 三项修正：
#     ① **自适应噪声底**（快降 0.20 / 慢升 0.01），阈值 = max(下限, 系数 × 底)；
#     ② 进入用 **3 帧中值**（要求持续静止），退出用**原始值**（一动就退）；
#     ③ `MAX_S` 0.8 → **0.2 s**，并且到点只强制一帧真实跟踪、**不清保持态**
#        （否则每次都要再攒 `MIN_FRAMES` 帧，实际跳过率砍半）。
#
#   ⚠️ **`MAX_S` 才是真正兜住滞后量的那一条**，阈值只是尽量少误判。原因：
#      纸只占画面 ~19%，手慢慢动 1~3 px/帧 时全幅帧差只有 0.8~1.5，
#      和静止噪声底 0.55 只差 1.5~2.7 倍 —— 任何全幅统计量都分不开。
#      所以：**纸停了 ⇒ 跳过（快）；纸在动 ⇒ 由 MAX_S 限住滞后 ≤0.2 s**。
#      实测分离度：静止 0.54~0.59，明显移动 2.1~2.9。
#
#   标定依据（run-result(92)，`hold_diff` 全部实测值）：0.54 0.55 0.56 0.57 0.59
#   0.76 0.79 0.83 0.84 1.16 1.20 1.44 2.09 2.33 2.90
_HOLD_ON = os.environ.get('P11_MANUAL_STATIC_HOLD', '1') != '0'
#   ⚠️ `_HOLD_ENTER` / `_HOLD_EXIT` 是【下限】，实际阈值 = max(下限, 系数 × 噪声底)
_HOLD_ENTER = float(os.environ.get('P11_MANUAL_HOLD_ENTER', '0.9'))
_HOLD_EXIT = float(os.environ.get('P11_MANUAL_HOLD_EXIT', '1.6'))
_HOLD_ENTER_GAIN = float(os.environ.get('P11_MANUAL_HOLD_ENTER_GAIN', '1.5'))
_HOLD_EXIT_GAIN = float(os.environ.get('P11_MANUAL_HOLD_EXIT_GAIN', '2.2'))
_HOLD_CHANGE = float(os.environ.get('P11_MANUAL_HOLD_CHANGE', '0.02'))
_HOLD_EXIT_CHANGE = float(os.environ.get('P11_MANUAL_HOLD_EXIT_CHANGE', '0.04'))
_HOLD_MIN_FRAMES = max(1, int(float(os.environ.get('P11_MANUAL_HOLD_MIN_FRAMES', '2'))))
_HOLD_SMOOTH = max(1, int(float(os.environ.get('P11_MANUAL_HOLD_SMOOTH', '3'))))
_HOLD_MAX_S = float(os.environ.get('P11_MANUAL_HOLD_MAX_S', '0.2'))
#   ⭐ 见 `_reseed_points`：单帧位移超过这个值就不救（防止从病态点集外推单应）
_RESEED_MAX_MOVE = float(os.environ.get('P11_MANUAL_RESEED_MAX_MOVE', '12'))
#   ⭐ 2026-10-26（run 95）：会话死因从 `spatial_support` 换成了 `inliers_failed`（2/2）。
#      采样到的成功帧 `inlier_fraction` 全是 **1.0**、`rms` 只有 0.03~0.15 ——
#      余量很大，说明失败的那一帧是"少数点被误匹配"把比例拉了下来，而不是真的跟丢。
#      ⇒ 把 RANSAC 阈值和内点率门槛各松一档（**其余六道关一道没动**：
#      FB 一致性 / rms≤0.75 / `_valid` / 位移≤64 / `selected_quad` / `_distributed`）。
#   ⚠️ 这是**在没看到失败帧数据时的保守放宽**，不是诊断结论 ——
#      下次上板看 `MANUAL_TRACK_FAIL` 里的 `inlier_count / feature_count` 才能定。
_RANSAC_PX = float(os.environ.get('P11_MANUAL_RANSAC_PX', '1.8'))
_INLIER_MIN = float(os.environ.get('P11_MANUAL_INLIER_MIN', '0.75'))


class ManualTracker:
    """Only manual mode: actual outer-band features, complete FB and RANSAC.

    Manual selection authorizes the initial boundary, not an automatic four-edge
    receipt. With too little real texture the UI explicitly says FIXED; no fake
    optical-flow points or silent fallback from a failed moving track is used.
    """
    def __init__(self,frame,quad,limit=320,authority='manual'):
        from tracking import GrayObserver__v31_tracking as GrayObserver
        self.observer=GrayObserver(limit);self.q=np.asarray(quad,np.float32).copy()
        self.lk_cache=None;self._mask=None;self._inside=None
        try:
            from tracking import LKCache__v31_native as LKCache
            self.lk_cache=LKCache()
            self.gray,self.scale=self.observer.get(frame.image);self.observer.pin(self.gray)
            self.lk_cache.anchor(self.gray)
            self.previous_ready=float(frame.ready);self.first=True;self.last_seed=0.;self.last_failure=None
            #   ⭐ 静止门控状态（见文件头说明）
            self._hold_sample=None;self._hold_tmp=None;self._hold_hist=[]
            self._hold_since=0.;self._hold_active=False;self._hold_count=0
            self._hold_floor_m=_HOLD_ENTER;self._hold_floor_c=_HOLD_CHANGE
            self._hold_last_full=time.perf_counter()
            self.last_hold_diff=0.;self.last_hold_changed=0.;self.hold_frames=0
            self.points=self._features(self.gray,self.q);self.fixed=not self._distributed(self.points,self.q)
        except BaseException:
            self.close();raise
        self.kind='FIXED' if self.fixed else 'FB_TRACK'
        #   ⭐ `source_sha256`：这一版的源码指纹。**上板日志里对不上的时候，
        #      第一件事就是看它** —— run 94/95 的 `RELEASE_ID` 一模一样，
        #      根本分不出跑的是哪一版 PS 代码（2026-10-26 吃过这个亏）。
        checkpoint('MANUAL_TRACKER_READY' if authority=='manual' else 'V86_MOTION_TRACKER_READY',
            authority=authority,feature_count=0 if self.points is None else len(self.points),
            tracking=self.kind,feature_region='inside outer boundary band; no central playback area',
            fixed_means='explicit static coordinates; moving requires manual recalibration',automatic_edge_proof=False,
            source_sha256=_SOURCE_SHA256,
            ransac_px=_RANSAC_PX,inlier_min=_INLIER_MIN,reseed_max_move=_RESEED_MAX_MOVE,
            hold_max_s=_HOLD_MAX_S)
    def _features(self,gray,source_q):
        """在外环带找角点；带内纹理不够时【逐级放宽】，最后一档才允许纸内。

        ⚠️ 2026-10-26（run 93）：原来只调一次 `goodFeaturesToTrack(32,.012,5.)` 就定生死，
           某一场只找到 **7 个点**，而 `_distributed` 要求 ≥8 ⇒ 直接判 `FIXED`
           ⇒ **2021 帧（48%）完全不动**，用户反馈"还是没有动态跟随"。
           现在逐级放宽（宽带 / 低质量门限 / 大 blockSize / 多角点），
           只要纸上有纹理就一定能拿到 ≥8 个点；真的全无纹理才退回 FIXED。
        """
        q=(source_q+.5)/self.scale-.5;h,w=gray.shape
        if self._mask is None or self._mask.shape!=(h,w):
            self._mask=np.empty((h,w),np.uint8);self._inside=np.empty_like(self._mask)
        mask=self._mask;inside=self._inside;mask.fill(0);inside.fill(0)
        qi=np.rint(q).astype(np.int32);cv2.fillConvexPoly(inside,qi,255)
        best=None
        #   ⚠️ 收工条件不是"≥8 就够"：只找到 8 个但挤在一个角上时 `_distributed` 仍然不过，
        #      结果还是 FIXED。所以要求 **≥12 且空间分布合格**（12 个点对 8 参数单应余量够）。
        #   ⚠️ 每个档位的 `corners` 都封顶 32 —— 点越多 LK 越慢，
        #      而 `tracker_s` 已经 87 ms，不能为了鲁棒把每帧成本再推上去。
        for band,quality,dist,block,corners in ((12,.012,5.,3,32),(20,.006,4.,5,32),(28,.003,4.,7,32)):
            mask.fill(0)
            cv2.polylines(mask,[qi],True,255,band)
            cv2.bitwise_and(mask,inside,dst=mask)
            p=cv2.goodFeaturesToTrack(gray,corners,quality,dist,mask=mask,blockSize=block)
            if p is None:continue
            p=np.ascontiguousarray(p,np.float32)
            if best is None or len(p)>len(best):best=p
            if len(p)>=12 and self._distributed(p,source_q):return p
        #   最后一档：把纸的包围盒四等分，每格各找几个 —— 不再限于外环带。
        #   ⚠️ 分格是为了**保证空间分布**：整张纸一次找点时 `goodFeaturesToTrack`
        #      会挑最强的若干个，很容易全挤在一角，`_distributed` 照样不过 ⇒ 还是 FIXED。
        x0,y0=qi.min(axis=0);x1,y1=qi.max(axis=0)
        cells=[]
        for gy in range(2):
            for gx in range(2):
                a=(int(x0+gx*(x1-x0)//2),int(y0+gy*(y1-y0)//2))
                b=(int(x0+(gx+1)*(x1-x0)//2),int(y0+(gy+1)*(y1-y0)//2))
                mask.fill(0)
                cv2.rectangle(mask,a,b,255,-1)
                cv2.bitwise_and(mask,inside,dst=mask)
                pp=cv2.goodFeaturesToTrack(gray,8,.004,3.,mask=mask,blockSize=5)
                if pp is not None:cells.append(np.ascontiguousarray(pp,np.float32))
        if cells:
            p=np.concatenate(cells,axis=0)
            if best is None or len(p)>len(best):best=p
            if len(p)>=8 and self._distributed(p,source_q):return p
        return best
    def _distributed(self,points,q):
        if points is None or len(points)<8:return False
        from tracking import _spatial_support__v31_tracking as _spatial_support
        return bool(_spatial_support(points,(q+.5)/self.scale-.5,'legacy'))
    #   ⭐ 2026-10-26（run 94）：跟踪【成功】但幸存点分布不合格时，**就地在当前帧、
    #      绕新四边形重新取一次点**，而不是整帧作废。
    #
    #   为什么这样是安全的：走到这一步时，四边形已经过了 FB 一致性(中位<0.35px)、
    #   RANSAC 内点率(>=0.85)、重投影 RMS(<=0.75px)、`_valid`、单帧位移(<=64px)、
    #   `selected_quad` 六道关。`_distributed` 卡的是**下一帧的跟踪基座**，
    #   不是这一帧的四边形对不对。
    #
    #   ⚠️ 但 `_distributed` 原本还兼一个作用：**防止 LK 整体滑到背景上**。所以这里
    #      限定 `move<=_RESEED_MAX_MOVE` 才救 —— 单帧位移很大同时又挤成一团，
    #      正是"从病态点集里外推单应"最危险的组合，那种情况照旧作废。
    #   ⚠️ 返回 None 表示本帧应当作废（调用方 raise `manual_motion_spatial_support_failed`）。
    def _reseed_points(self,points,q,gray,move):
        if self._distributed(points,q):return points,False
        if move>_RESEED_MAX_MOVE:return None,False
        seeds=self._features(gray,q)
        if seeds is None or len(seeds)<8 or not self._distributed(seeds,q):return None,False
        return np.ascontiguousarray(seeds,np.float32),True
    #   ⭐ 静止门控：80×80 采样 + 自适应噪声底 + 滞回 + 最长保持时间。
    #      口径与自动模式 `v87_v74_tracking._static_hold` 一致（rev2，见文件头）。
    #      返回 True = 本帧可以跳过跟踪；False = 必须做一次真实跟踪。
    def _still(self,gray,now):
        if not _HOLD_ON or self.fixed:return False
        h,w=gray.shape
        if h<80 or w<80:return False
        sample=gray[::max(1,h//80),::max(1,w//80)][:80,:80]
        prev=self._hold_sample
        if prev is None or prev.shape!=sample.shape:
            self._hold_sample=np.empty(sample.shape,np.int16)
            np.copyto(self._hold_sample,sample,casting='unsafe')
            self._hold_tmp=np.empty(sample.shape,np.int16)
            self._hold_hist=[];self._hold_count=0;self._hold_active=False
            self._hold_since=now;self._hold_last_full=now
            return False
        tmp=np.subtract(sample,prev,out=self._hold_tmp,casting='unsafe')
        np.abs(tmp,out=tmp)
        motion=float(tmp.mean())
        changed=float(np.count_nonzero(tmp>8))/float(tmp.size)
        np.copyto(prev,sample,casting='unsafe')
        self.last_hold_diff=motion;self.last_hold_changed=changed
        #   自适应噪声底：低于底时快速跟随（0.20），高于底时极慢上升（0.01）
        fm=self._hold_floor_m;fc=self._hold_floor_c
        fm+=(.20 if motion<fm else .01)*(motion-fm)
        fc+=(.20 if changed<fc else .01)*(changed-fc)
        self._hold_floor_m=fm;self._hold_floor_c=fc
        hist=self._hold_hist;hist.append((motion,changed))
        if len(hist)>_HOLD_SMOOTH:hist.pop(0)
        sm=sorted(v[0] for v in hist)[len(hist)//2]
        sc=sorted(v[1] for v in hist)[len(hist)//2]
        #   进入用【平滑值】（要求持续静止）；退出用【原始值】（一动就退）
        if self._hold_active:
            exit_m=max(_HOLD_EXIT,_HOLD_EXIT_GAIN*fm)
            exit_c=max(_HOLD_EXIT_CHANGE,_HOLD_EXIT_GAIN*fc)
            blocked=motion>exit_m or changed>exit_c
        else:
            limit_m=max(_HOLD_ENTER,_HOLD_ENTER_GAIN*fm)
            limit_c=max(_HOLD_CHANGE,_HOLD_ENTER_GAIN*fc)
            blocked=sm>limit_m or sc>limit_c
        if blocked:
            self._hold_active=False;self._hold_count=0
            return False
        if not self._hold_active:
            self._hold_count+=1
            if self._hold_count<_HOLD_MIN_FRAMES:return False
            self._hold_active=True;self._hold_since=now;self.hold_frames=0
        #   到点强制做一次真实跟踪（防慢速漂移），但【不清保持态】——
        #   下一帧仍按"已在保持"判定，不必重新攒 MIN_FRAMES 帧。
        if now-self._hold_last_full>=_HOLD_MAX_S:return False
        self.hold_frames+=1
        return True
    def update(self,frame):
        began=time.perf_counter();cpu=time.thread_time()
        if self.fixed:return self.q.copy(),dict(manual_tracking='FIXED',manual_motion_proved=False,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu)
        detail=dict(manual_tracking='FB_TRACK',manual_motion_proved=False)
        try:
            elapsed=float(frame.ready)-self.previous_ready
            if not self.first and not 0<elapsed<=.75:raise ValueError('manual_capture_gap_or_expired_anchor')
            gray,scale=self.observer.get(frame.image)
            if not np.array_equal(scale,self.scale):raise ValueError('manual_source_layout_changed')
            #   ⭐ 静止门控：画面没动 ⇒ 复用上一帧四角，跳过 LK + RANSAC。
            #   ⚠️ 必须同时刷新 gray / pin / previous_ready / first —— 否则
            #      下一次真实跟踪会撞 .75 s 的 expired_anchor 守卫。
            if not self.first and self._still(gray,time.perf_counter()):
                self.gray=gray;self.observer.pin(gray)
                self.previous_ready=float(frame.ready);self.first=False
                detail.update(static_hold=True,hold_frames=self.hold_frames,
                    hold_diff=self.last_hold_diff,hold_changed=self.last_hold_changed,
                    hold_floor_m=self._hold_floor_m,hold_floor_c=self._hold_floor_c,
                    hold_max_s=_HOLD_MAX_S,
                    feature_count=0 if self.points is None else len(self.points))
                detail.update(tracker_s=time.perf_counter()-began,
                    tracker_thread_cpu_s=time.thread_time()-cpu)
                return self.q.copy(),detail
            p=self.points
            if not self._distributed(p,self.q):raise ValueError('manual_outer_features_insufficient')
            flow=time.perf_counter();args=dict(winSize=(21,21),maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02))
            native=self.lk_cache.track(gray,p,levels=3,iterations=20,generation=int(frame.sequence)&0xffffffff)
            if native is None:f,s,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,p,None,**args)
            else:f,s,error,back,sb=native
            if f is None or s is None:raise ValueError('manual_forward_flow_failed')
            if native is None:back,sb,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,f,None,**args)
            if back is None or sb is None:raise ValueError('manual_backward_flow_failed')
            fb=np.linalg.norm(back.reshape(-1,2)-p.reshape(-1,2),axis=1)
            good=(s.ravel()!=0)&(sb.ravel()!=0)&np.isfinite(f).all(axis=(1,2))&np.isfinite(fb)&(fb<.8)
            detail.update(forward_backward_flow_s=time.perf_counter()-flow,feature_count=len(p),good_features=int(good.sum()),
                lk_backend='native_cached_bidirectional_pyramids' if native is not None else 'opencv_bidirectional')
            if good.sum()<8 or float(np.median(fb[good]))>.35:raise ValueError('manual_FB_consistency_failed')
            a=p.reshape(-1,2)[good];b=f.reshape(-1,2)[good]
            transform,inliers=cv2.findHomography(a,b,cv2.RANSAC,_RANSAC_PX,maxIters=300,confidence=.995)
            if transform is None or inliers is None or not np.isfinite(transform).all():raise ValueError('manual_motion_model_failed')
            keep=inliers.ravel()!=0;fraction=float(np.mean(keep))
            detail.update(inlier_fraction=fraction,inlier_count=int(keep.sum()),model_points=len(p))
            if keep.sum()<8 or fraction<_INLIER_MIN:raise ValueError('manual_motion_inliers_failed')
            projected=cv2.perspectiveTransform(a[keep].reshape(-1,1,2),transform).reshape(-1,2)
            rms=float(np.sqrt(np.mean(np.sum((projected-b[keep])**2,axis=1))))
            if rms>.75:raise ValueError('manual_reprojection_error')
            small=(self.q+.5)/self.scale-.5
            next_q=cv2.perspectiveTransform(small.reshape(-1,1,2),transform).reshape(-1,2)
            from tracking import _valid__v31_tracking as _valid
            if not _valid(next_q,gray.shape,small,'legacy'):raise ValueError('manual_current_quad_invalid')
            move=float(np.max(np.linalg.norm(next_q-small,axis=1)))
            if move>64:raise ValueError('manual_motion_too_large')
            q=(next_q+.5)*self.scale-.5
            # Validate intersections without reordering physical corner identity.
            selected_quad(q,frame.image.shape)
            next_points,reseeded=self._reseed_points(
                np.ascontiguousarray(b[keep].reshape(-1,1,2),np.float32),q,gray,move)
            if next_points is None:raise ValueError('manual_motion_spatial_support_failed')
            if reseeded:detail.update(point_reseed_at='motion',point_reseed_px=move)
            if native is not None:self.lk_cache.promote()
            self.q=q.astype(np.float32);self.points=next_points
            self.gray=gray;self.observer.pin(gray);self.previous_ready=float(frame.ready);self.first=False
            # Low-rate top-up only after a successful complete flow transaction.
            if len(next_points)<16 and time.perf_counter()-self.last_seed>=1.:
                self.last_seed=time.perf_counter();seeds=self._features(gray,self.q)
                if self._distributed(seeds,self.q):self.points=seeds
            detail.update(manual_motion_proved=True,fb_median=float(np.median(fb[good])),
                inlier_fraction=fraction,reprojection_rms=rms,features_retained=len(self.points))
            self.last_failure=None;result=self.q.copy()
        except (ValueError,cv2.error) as exc:
            detail.update(reason=str(exc));self.last_failure=str(exc);result=None
            #   ⭐ 失败帧的数据只在这里才拿得到（`manual_track_detail` 是每 60 帧才记一条）。
            #      没有这几项，"为什么死"就只能靠猜 —— 2026-10-26 已经猜错过一次。
            try:
                checkpoint('MANUAL_TRACK_FAIL',reason=str(exc),
                    feature_count=detail.get('feature_count'),good_features=detail.get('good_features'),
                    inlier_fraction=detail.get('inlier_fraction'),inlier_count=detail.get('inlier_count'),
                    model_points=detail.get('model_points'),
                    reprojection_rms=detail.get('reprojection_rms'),fb_median=detail.get('fb_median'),
                    hold_active=self._hold_active,hold_frames=self.hold_frames,
                    source_sha256=_SOURCE_SHA256,tracker_s=time.perf_counter()-began)
            except Exception:pass
        #   ⭐ 真实跟踪做完（不管成败）⇒ 记一次"完整测量"，MAX_S 从这里重新计时
        self._hold_last_full=time.perf_counter()
        detail.update(tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu)
        return result,detail
    def close(self):
        # ObservationWorkspace owns NumPy work arrays, no native close handle.
        # Retire the caller's worker before dropping these pinned references.
        observer=self.observer
        if self.lk_cache is not None:self.lk_cache.close()
        if observer is None:return
        transaction=getattr(observer,'transaction',None)
        close=getattr(transaction,'close',None)
        if callable(close):close()
        self.observer=None;self.gray=None;self.points=None



# ======================================================================
# ===== [06/35] v105_manual_tracking =====
# ======================================================================


"""Manual selection keeps authority; failures never start scene-wide detection."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class PersistentManualTracker:
    @property
    def physical(self):return self.edge is not None
    def __init__(self,frame,quad,limit=320,authority='manual'):
        from tracking import prepare_edges as prepare_edges
        prepare_edges()  # Selection only; never compile on a failed live frame.
        self.primary=ManualTracker(frame,quad,limit,authority);self.edge=None;self.failures=0
        self.next_retry=0.;self.limit=limit;self.authority=authority;self.closed=False
        if self.primary.fixed:
            try:self.edge=PhysicalTracker.from_observation(self.primary.gray,self.primary.scale,self.primary.q,
                    self.primary.previous_ready,limit,authority)
            except (ValueError,cv2.error):pass
            if self.edge is not None:self.primary.close()
    def __getattr__(self,name):return getattr(self.edge or self.primary,name)
    def update(self,frame,radius=4.):
        if self.edge is not None:return self.edge.update(frame,radius=radius)
        begin=time.perf_counter();cpu=time.thread_time();stamp=float(frame.ready)
        if self.failures>=3 and stamp<self.next_retry:
            return None,dict(manual_tracking='MANUAL_SEARCH',manual_motion_proved=False,
                reason='same_target_retry_pending',tracker_s=time.perf_counter()-begin,tracker_thread_cpu_s=time.thread_time()-cpu)
        # Revalidate the same feature anchor after a gap. Static shortcuts must
        # not renew an expired/failed anchor; all original FB/RANSAC gates run.
        if self.failures:self.primary.first=True
        q,detail=self.primary.update(frame)
        if q is not None:
            if self.failures:checkpoint('MANUAL_SAME_TARGET_RECOVERED',method='original_FB',automatic_switch=False)
            self.failures=0;return q,detail
        self.failures+=1
        if self.failures>=3:
            self.next_retry=stamp+.25
            try:
                candidate=PhysicalTracker.from_observation(self.primary.gray,self.primary.scale,self.primary.q,
                    self.primary.previous_ready,self.limit,self.authority)
            except (ValueError,cv2.error):candidate=None
            if candidate is not None:
                self.edge=candidate;self.edge.failures=1;self.primary.close()
                checkpoint('MANUAL_TARGET_RECOVERY_BEGIN',method='same_boundary',automatic_switch=False)
                q,detail=self.edge.update(frame)
            elif self.failures in (3,7) or self.failures%20==0:
                checkpoint('MANUAL_TARGET_RETRY',reason=detail.get('reason'),automatic_switch=False,
                    retry_max_hz=4,old_coordinates_not_renewed=True)
        detail['tracker_s']=time.perf_counter()-begin;detail['tracker_thread_cpu_s']=time.thread_time()-cpu
        return q,detail
    def close(self):
        if self.closed:return
        self.closed=True
        if self.edge is not None:self.edge.close()
        else:self.primary.close()


# ======================================================================
# ===== [07/35] v82_manual =====
# ======================================================================


"""Explicit manual authority, bounded FB motion and unchanged P1 owner/planner."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint; from core import frame_record as frame_record
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v82_manual=[]




class ManualFrontend:
    def __init__(self,camera,first,q,size,options,raw_required=None):
        from display import PlanWorkspace as PlanWorkspace
        from display import ProofCache as ProofCache
        from display import make_orientation as DualOrientation
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
                self.tracker=PersistentReferenceTracker(first,q,int(options.get('tracking_max_dim',320)))
            elif options.get('_ai_physical_profile',False):
                self.tracker=create_tracker(first,q,int(options.get('tracking_max_dim',320)))
            else:self.tracker=PersistentManualTracker(first,q,int(options.get('tracking_max_dim',320)))
        except BaseException:self.close();raise
        from display import register_manual_frontend as register_manual_frontend
        register_manual_frontend(self)
    def plan(self,q,shape,size):
        from display import Frontend as Frontend
        return Frontend.plan(self,q,shape,size)
    def prepare(self,index):
        from display import FrameJob as FrameJob
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
        return select_live(context,camera,deadline)
    from tracking import OwnedFrame as OwnedFrame
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
                    raise UIReturnRequested()
                if action[0]=='confirm':
                    camera._p11_stream_stabilized=True
                    return frozen,action[1]
            with display.condition:display.condition.wait(.10)


def run_manual(context,device='/dev/video0',width=640,height=480,fps=30,
               output_size=(362,512),max_frames=0,warmup_frames=5,deadline=None,options=None):
    """New serialized UI session; original device and display owners are reused."""
    from display import CameraSource as CameraSource
    from core import set_color_mode as set_color_mode
    from display import PrepareQueue as PrepareQueue; from display import FrameJob as FrameJob
    from display import make_orientation as DualOrientation
    from display import PlanWorkspace as PlanWorkspace
    from display import make_plan as make_plan; from display import ProofCache as ProofCache
    options=dict(options or {});backend=context.backend;display=context.display;backend._assert_owner()
    options['_ai_physical_profile']=bool(getattr(context.ticket,'ai',False))
    deadline=float('inf') if deadline is None else float(deadline)
    camera=front=queue=first=workspace=job=budget=None;failure=None;cleanup=[];fixed=False
    n=manual=current=held=lost=manual_tracked=manual_fixed=0;began=None;ended=None;rows=deque(maxlen=512);times=deque(maxlen=120);current_times=deque(maxlen=120)
    snapshot=context.ticket.page=='snapshot';stopped=False;epoch=None
    completed_rate=CurrentRate__v110_unified();is_ai=bool(getattr(context.ticket,'ai',False))
    try:
        context.check();retained=context.ticket.fixed_input if snapshot else None
        if retained is not None:
            color_mode=int(retained.color_mode);set_color_mode(color_mode)
            checkpoint('MANUAL_SESSION_BEGIN',generation=context.generation,snapshot=True,
                camera=None,fixed_source_reused=True,camera_opened=False,
                automatic_edge_proof=False,hardware_checks_preserved=True)
            first,q=select_fixed(context,retained,deadline)
        if first is None:
            transfer=claim(context,device,width,height,fps,options.get('color_mode'))
            if transfer is not None:finish_previous_budget(transfer)
            camera=transfer.camera if transfer is not None else CameraSource(device,width,height,fps,options.get('color_mode'))
            context.camera_transfer=transfer
            if transfer is not None:
                checkpoint('MANUAL_CAMERA_REUSED',generation=context.generation,camera_reopened=False,
                    stream_reconfigured=transfer.reconfigured,initial_stabilization_repeated=not transfer.stabilized)
            color_mode=int(camera.color_mode);set_color_mode(color_mode)
            if is_ai and not snapshot:
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
            remember_fixed_source(context,first.image,first,color_mode)
            job=FrameJob(1,first,tuple(tiles),size,'MANUAL',row['corners'],color_mode,first.image,row)
            image,owner=backend.execute(job);context.check();display.offer(image,row,first.image);job.release_source()
            receipt=display.wait_snapshot(context.generation,1,first.sequence,context.cancel)
            if receipt is None:context.check();raise RuntimeError('Manual snapshot submission not confirmed')
            fixed=True;n=manual=1;rows.append(dict(row,**owner));ended=time.perf_counter()
        else:
            if is_ai:
                from tracking import create_frontend as create_frontend
                def automatic_factory(frame,detection):
                    return create_frontend(camera,frame,detection,output_size,int(options.get('tracking_max_dim',320)),
                        int(options.get('detection_max_dim',640)),float(options.get('hold_max_age_s',1.5)),
                        6,30,options.get('output_orientation','auto_two'),float(options.get('reacquire_budget_ms',420.)),
                        options.get('plan_strategy','fast_safe'),float(options.get('proof_cpu_budget_ms',12.)),False,70.)
                front=HybridFrontend__v111_recovery(camera,output_size,options,context,automatic_factory,ai_first=True,
                    target_selection=context.ticket.target_selection)
                context.ticket.target_selection=None
                front.raw_required=display.needs_raw_source
            else:
                bind_preview(camera,display,context.generation)
                front=ManualFrontend(camera,first,q,output_size,dict(options,_manual_reference_v17=True),raw_required=display.needs_raw_source)
            if first is not None:first.release();first=None
            from core import GcBudget as GcBudget
            budget=GcBudget(options.get('gc_policy','bounded'),240,30.);budget.__enter__()
            queue=PrepareQueue(front,max_frames or 2147483647,0);queue.allow_measured()
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
                            preserved=hot.offer(context,camera,camera_key(device,width,height,fps,options.get('color_mode')),budget,
                                readers_retired=producer_stopped,backend_idle=not backend.active and not backend.failed,
                                admitted=first is not None or n>0)
                        if preserved:budget=None
                        else:camera.close();camera_closed=True
                    except BaseException as exc:cleanup.append(('manual_camera',repr(exc)))
        if cleanup:
            import display as camera_module
            camera_module._POISONED=True;camera_module._POISON_REASON=list(camera_module._POISON_REASON)+cleanup
            _RETAINED__v82_manual.append((queue,front,workspace,camera,first,job,backend,display))
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


# ======================================================================
# ===== [08/35] v84_snapshot =====
# ======================================================================


"""One immutable ordinary-RAM still source; no camera or display leases."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass(frozen=True)
class FixedInput:
    image:object
    ready:float
    sequence:int
    timestamp:float
    flags:int
    color_mode:int
    def frame(self):
        from tracking import OwnedFrame as OwnedFrame
        return OwnedFrame(self.image,self.ready,self.sequence,self.timestamp,self.flags)


def remember_fixed_source(context,raw,frame,color_mode):
    """Only the serialized snapshot producer calls this before offering its result."""
    if context.ticket.page!='snapshot':raise ValueError('Fixed source is only valid on the still-image page')
    if (raw.dtype!=np.uint8 or raw.shape!=(480,640,2) or not raw.flags.c_contiguous or not raw.flags.owndata):
        raise ValueError('Fixed calibration source must be owned640x480YUYV')
    # Both callers supply a prior ordinary-RAM copy, never MMAP/CMA memory.
    # Keep it immutable without copying every video frame or reading a pool
    # from the touch thread. A new ticket inherits this object by reference.
    raw.setflags(write=False)
    source=FixedInput(raw,float(frame.ready),int(frame.sequence),float(frame.timestamp),
        int(frame.flags),int(color_mode))
    context.ticket.fixed_input=source
    checkpoint('SNAPSHOT_SOURCE_RETAINED',generation=context.generation,sequence=source.sequence,
        ordinary_RAM_bytes=raw.nbytes,scope='one still image until recapture/home',hardware_access=False)
    return source


def select_fixed(context,source,deadline):
    """Same-image four-point selection; explicit refresh requests new capture."""
    if getattr(context.ticket,'ai',False):
        frozen=source.frame();selected=None
        try:
            selected,quad=select_frame(context,source.image,source.color_mode,frozen,deadline)
            return selected,quad
        finally:
            if selected is not frozen:frozen.release()
    display=context.display;context.check()
    if not display.inspection.begin_calibration(source.image,source.color_mode,context.generation,source.sequence):
        context.check();raise RuntimeError('Fixed calibration page was not accepted')
    checkpoint('MANUAL_FIXED_SOURCE_BEGIN',generation=context.generation,sequence=source.sequence,
        same_captured_image=True,camera_opened=False)
    while True:
        context.check()
        if time.perf_counter()>=deadline:raise TimeoutError('Manual still calibration deadline')
        if display.error is not None:raise display.error
        action=display.inspection.take_action(context.generation)
        if action is not None:
            if action[0]=='confirm':return source.frame(),action[1]
            if action[0]=='refresh':
                checkpoint('MANUAL_FIXED_RECAPTURE_REQUEST',generation=context.generation)
                return None,None
            if action[0]=='auto':
                raise UIReturnRequested()
        with display.condition:display.condition.wait(.10)


# ======================================================================
# ===== [09/35] v97_album =====
# ======================================================================


"""Event-only SD captures and touch album. The HDMI owner alone reads video pixels.

The IO worker receives owned ordinary RAM, never camera/CMA/VideoFrame references.
No directory access, image copy, encoding or decode occurs on an idle live frame.
"""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

CAPTURE_RECT=(1000,640,120,56)
ALBUM_RECT=(1132,640,120,56)
BACK_RECT=(0,0,216,72)
PHOTO_RECT=(32,96,1216,520)
TILES=tuple((40+c*408,100+r*260,384,240) for r in range(2) for c in range(3))
FOOTER=tuple((32+i*200,632,184,64) for i in range(6))
BUTTON_NAMES=('previous','next','grid','zoom','delete','clear','confirm','cancel')
NOTICE_NAMES=('idle','waiting','saving','saved','error','unavailable','busy','empty','loading','deleted','confirm','select')


def inside__v97_album(point,rect):
    x,y,w,h=rect
    return point is not None and x<=point[0]<x+w and y<=point[1]<y+h


def event(stage,**detail):
    # A completed SD task can outlive application logging during a slow shutdown.
    try:checkpoint(stage,**detail)
    except BaseException:pass


class MediaAssets:
    def __init__(self,root):
        def read(name,shape):
            value=cv2.imread(str(root/name),cv2.IMREAD_COLOR)
            if value is None or value.shape!=shape:raise ValueError('Invalid album asset '+name)
            value.setflags(write=False)
            return value
        self.bar=read('v97_media_bar.png',(56,252,3))
        self.header=read('v97_album_header.png',(72,1280,3))
        buttons=read('v97_album_buttons.png',(len(BUTTON_NAMES)*64,184,3))
        self.buttons={name:buttons[i*64:(i+1)*64] for i,name in enumerate(BUTTON_NAMES)}
        notices=read('v97_media_notices.png',(len(NOTICE_NAMES)*32,244,3))
        self.notices={name:notices[i*32:(i+1)*32] for i,name in enumerate(NOTICE_NAMES)}


class MediaController:
    def __init__(self,display,directory='/home/xilinx/captures',quality=90):
        folder=Path(directory).expanduser()
        if not folder.is_absolute():raise ValueError('capture_dir must be absolute')
        if not 70<=int(quality)<=95:raise ValueError('capture_jpeg_quality must be 70..95')
        self.display=display;self.folder=folder;self.quality=int(quality)
        self.assets=display.ui_assets.media_assets
        self.worker=None;self.context=copy_context();self.closed=False
        self.capture_request=None;self.save_job=None;self.delete_job=None;self.load_job=None
        self.saving=False;self.notice='idle';self.notice_until=0.;self.frozen_redraw=False
        self.live_tokens={};self.revision=0;self.presented_revision=-1;self.model={};self.files=();self.selected=set()
        self.mode='grid';self.page=0;self.photo_name=None;self.zoom=1;self.focus=None
        self.confirm_names=();self.return_mode='grid';self.thumb_cache=OrderedDict()
        self.opened_at=None;self.album_seconds=0.;self.saved=0;self.deleted=0;self.failures=0

    @property
    def active(self):
        return self.display.inspection.kind=='album'

    def _start_locked(self):
        if self.worker is None:
            worker=threading.Thread(target=lambda:self.context.run(self._run),name='photo_sd_io',daemon=True)
            self.worker=worker
            try:worker.start()
            except BaseException:self.worker=None;raise

    def _notice_locked(self,name,seconds=2.):
        self.notice=name;self.notice_until=time.perf_counter()+seconds
        self.frozen_redraw=True;self.display.condition.notify_all()

    def _discard_pending_locked(self):
        d=self.display
        if d.pending is not None:d.pending=None;d.ui_discarded+=1
        # Active/copying slots retain their original ownership until their caller finishes.
        for i,reference in enumerate(d.output_refs):
            if i not in (d.active_slot,d.copying_slot) and reference is not None:
                d.output_refs[i]=None;reference.release()

    def _model_locked(self,model):
        model=dict(model,revision=self.revision);self.model=model
        self.display.inspection.meta={'album':model}
        self.display.inspection.dirty=True
        self.display.condition.notify_all()

    def _schedule_locked(self,rescan=False):
        self.revision+=1
        ins=self.display.inspection
        self.load_job=dict(kind='load',revision=self.revision,token=ins.token,
            generation=ins.generation,mode=self.mode,page=self.page,photo=self.photo_name,
            zoom=self.zoom,focus=self.focus,files=tuple(self.files),rescan=rescan,
            selected=tuple(self.selected))
        self._model_locked(dict(self.model,mode=self.mode,busy=True,notice='loading',selected=tuple(self.selected)))
        try:self._start_locked()
        except Exception as exc:
            self.load_job=None
            self._model_locked(dict(self.model,busy=False,notice='error'))
            event('PHOTO_WORKER_START_FAILED',exception=repr(exc),realtime_pipeline_continues=True)
        self.display.condition.notify_all()

    def _open_locked(self,generation):
        d=self.display
        if d.inspection.kind:return False,'inspection_busy'
        if d.ui_view=='snapshot' and d.frozen_generation!=generation:return False,'snapshot_still_capturing'
        if self.capture_request is not None:
            self.capture_request=None;self.saving=False;self._notice_locked('unavailable')
        self._discard_pending_locked()
        ins=d.inspection;ins.clear_locked();ins.kind='album';ins.generation=generation;ins.opened+=1
        self.mode='grid';self.page=0;self.selected.clear();self.confirm_names=();self.model={}
        self.opened_at=time.perf_counter();self._schedule_locked(rescan=True)
        event('ALBUM_OPEN',generation=generation,directory=str(self.folder),tracking_continues=True,hardware_access=False)
        return True,'album_opened'

    def _close_locked(self):
        d=self.display
        if self.opened_at is not None:self.album_seconds+=time.perf_counter()-self.opened_at
        self.opened_at=None;self.revision+=1;self.load_job=None;self.model={};self.files=()
        self.selected.clear();self.confirm_names=()
        d.inspection.clear_locked();self._discard_pending_locked()
        d.canvas_views.clear();d.layouts.clear();self.live_tokens.clear()
        d.current_times.clear();d.submit_times.clear()
        d.inspection_restore=bool(d.ui_view=='snapshot' and d.last_static_packet is not None)
        d.condition.notify_all()
        event('ALBUM_CLOSE',generation=d.ui_generation,resume_latest=True,camera_restart=False,album_seconds=self.album_seconds)

    def page_changed_locked(self):
        # request_view may clear the Inspection before this hook is called.
        if self.opened_at is not None:self.album_seconds+=time.perf_counter()-self.opened_at
        self.opened_at=None;self.revision+=1;self.load_job=None;self.model={};self.files=()
        self.selected.clear();self.confirm_names=();self.live_tokens.clear();self.frozen_redraw=False
        if self.capture_request is not None:self.capture_request=None;self.saving=False

    def touch(self,touch,generation):
        """Called under UIState's lock; image data and SD access never enter this handler."""
        d=self.display
        with d.condition:
            if self.closed or d.stop or generation!=d.ui_generation:return None
            if d.inspection.kind and not self.active:return None
            phase=touch['phase'];press=touch.get('press');origin=touch.get('press_outcome') or {}
            if phase=='cancel':return dict(target='media_background',accepted=False,consumed=True,reason='media_contact_cancelled') if self.active else None
            if self.active:
                target=self._target_locked(press)
                if phase=='press':
                    if target=='media_back':
                        self._close_locked()
                        return dict(target=target,accepted=True,consumed=True,reason='album_return_on_press')
                    return dict(target=target,accepted=False,consumed=False,reason='await_album_release',media_revision=self.revision)
            else:
                target='media_capture' if inside__v97_album(press,CAPTURE_RECT) else 'media_open' if inside__v97_album(press,ALBUM_RECT) else None
                if phase=='press':
                    return None if target is None else dict(target=target,accepted=False,consumed=False,reason='await_media_release')
                if not str(origin.get('target','')).startswith('media_'):return None
            target=origin.get('target') or target
            result=dict(target=target,accepted=False,consumed=True,reason='media_release_rejected')
            release=touch.get('release')
            if (origin.get('generation')!=generation or origin.get('page')!=d.ui_view or release is None
                    or touch.get('peak_motion',0.)>32):return result
            if self.active:
                if origin.get('media_revision')!=self.revision or self._target_locked(release)!=target:return result
                accepted,reason=self._activate_locked(target,release)
            elif target=='media_capture' and inside__v97_album(release,CAPTURE_RECT):
                if self.saving:accepted,reason=False,'capture_busy';self._notice_locked('busy')
                elif d.latest_meta.get('state') not in ('CURRENT','MANUAL'):
                    accepted,reason=False,'capture_requires_current_result';self._notice_locked('unavailable')
                else:
                    self.saving=True;self.capture_request=(generation,time.perf_counter()+2.)
                    self._notice_locked('waiting');accepted,reason=True,'capture_requested'
            elif target=='media_open' and inside__v97_album(release,ALBUM_RECT):accepted,reason=self._open_locked(generation)
            else:accepted,reason=False,'media_release_outside'
            return dict(result,accepted=accepted,reason=reason,request_generation=generation if accepted else None)

    def _target_locked(self,point):
        if inside__v97_album(point,BACK_RECT):return 'media_back'
        if self.model.get('busy') or self.presented_revision!=self.revision:return 'media_background'
        if self.mode=='confirm':
            return 'media_confirm' if inside__v97_album(point,FOOTER[3]) else 'media_cancel' if inside__v97_album(point,FOOTER[4]) else 'media_background'
        names=('previous','next','grid','zoom','delete','clear')
        for name,rect in zip(names,FOOTER):
            if inside__v97_album(point,rect):return 'media_'+name
        if self.mode=='grid':
            for i,rect in enumerate(TILES[:len(self.model.get('items',()))]):
                if inside__v97_album(point,rect):
                    x,y,w,h=rect
                    return 'media_select_'+str(i) if inside__v97_album(point,(x+w-64,y+h-58,64,58)) else 'media_photo_'+str(i)
        elif self.mode=='photo' and inside__v97_album(point,PHOTO_RECT):return 'media_focus'
        return 'media_background'

    def _activate_locked(self,target,point):
        if target.startswith(('media_select_','media_photo_')):
            i=int(target.rsplit('_',1)[1]);name=self.model['items'][i]['name']
            if target.startswith('media_select_'):
                if name in self.selected:self.selected.remove(name)
                else:self.selected.add(name)
                self.revision+=1;self._model_locked(dict(self.model,selected=tuple(self.selected)))
            else:
                self.mode='photo';self.photo_name=name;self.zoom=1;self.focus=None;self._schedule_locked()
        elif target in ('media_previous','media_next'):
            step=-1 if target=='media_previous' else 1
            if self.mode=='grid':self.page=max(0,min(max(0,(len(self.files)-1)//6),self.page+step))
            elif self.files:
                index=self.files.index(self.photo_name) if self.photo_name in self.files else 0
                self.photo_name=self.files[max(0,min(len(self.files)-1,index+step))];self.zoom=1;self.focus=None
            self._schedule_locked()
        elif target=='media_grid':self.mode='grid';self._schedule_locked(rescan=True)
        elif target=='media_zoom':
            if self.mode=='photo':self.zoom={1:2,2:4,4:1}[self.zoom];self._schedule_locked()
            elif len(self.selected)==1:
                self.mode='photo';self.photo_name=next(iter(self.selected));self.zoom=1;self.focus=None;self._schedule_locked()
            else:self._model_locked(dict(self.model,notice='select'));return False,'select_one_photo_to_view'
        elif target=='media_focus' and self.mode=='photo':
            mapping=self.model.get('mapping')
            if mapping:
                sx,sy,scale,x,y,w,h=mapping
                if inside__v97_album(point,(x,y,w,h)):
                    self.focus=(sx+(point[0]-x)/scale,sy+(point[1]-y)/scale)
                    if self.zoom==1:self.zoom=2
                    self._schedule_locked()
        elif target=='media_clear':
            self.selected.clear();self.revision+=1;self._model_locked(dict(self.model,selected=()))
        elif target=='media_delete':
            names=tuple(self.selected) if self.mode=='grid' else (self.photo_name,) if self.photo_name else ()
            if not names:
                self._model_locked(dict(self.model,notice='select'))
                return False,'select_photos_before_delete'
            self.confirm_names=names;self.return_mode=self.mode;self.mode='confirm';self.revision+=1
            self._model_locked(dict(self.model,mode='confirm',delete_count=len(names),notice='confirm'))
        elif target=='media_cancel':self.mode=self.return_mode;self.confirm_names=();self._schedule_locked()
        elif target=='media_confirm':
            if self.delete_job is not None:return False,'delete_busy'
            self.revision+=1
            self.delete_job=dict(kind='delete',names=self.confirm_names,revision=self.revision)
            self.mode='grid';self._model_locked(dict(self.model,mode='grid',busy=True,notice='loading'))
            try:self._start_locked()
            except Exception as exc:
                self.delete_job=None;self._model_locked(dict(self.model,busy=False,notice='error'))
                event('PHOTO_WORKER_START_FAILED',exception=repr(exc),realtime_pipeline_continues=True)
                return False,'delete_worker_unavailable'
            self.display.condition.notify_all()
        else:return False,'album_outside_controls'
        return True,target

    def capture_from_output(self,out,meta):
        """Only HDMI owner calls this while active_slot pins the completed output."""
        if self.capture_request is None:return
        d=self.display
        with d.condition:
            request=self.capture_request
            if request is None:return
            generation,deadline=request
            if (generation!=meta.get('ui_generation') or d.ui_generation!=generation
                    or time.perf_counter()>deadline or out is None or meta.get('state') not in ('CURRENT','MANUAL')):
                self.capture_request=None;self.saving=False;self._notice_locked('unavailable');return
            self.capture_request=None
        began=time.perf_counter()
        try:
            if out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=4 or out.nbytes>4*1280*720:
                raise ValueError('Invalid completed capture layout')
            image=np.array(out,copy=True,order='C');image.setflags(write=False)
            copied=dict(index=int(meta.get('index',-1)),camera_sequence=int(meta.get('camera_sequence',-1)),
                capture_ready_at=float(meta.get('capture_ready_at',0.)),state=meta.get('state'),
                width=int(image.shape[1]),height=int(image.shape[0]),requested_generation=generation)
            with d.condition:
                if self.closed:self.saving=False;return
                self.save_job=(image,copied);self._notice_locked('saving',30.);self._start_locked();d.condition.notify_all()
            event('PHOTO_CAPTURE_COPIED',**copied,copy_s=time.perf_counter()-began,ordinary_RAM_bytes=image.nbytes,hardware_reference_retained=False)
        except BaseException as exc:
            with d.condition:self.save_job=None;self.saving=False;self.failures+=1;self._notice_locked('error')
            event('PHOTO_CAPTURE_FAILED',exception=repr(exc),realtime_pipeline_continues=True)

    def render_live(self,canvas,address,page_changed):
        # Cached patches are installed once per VideoFrame/status, never rebuilt.
        notice=self.notice if time.perf_counter()<self.notice_until else 'idle'
        token=(self.display.ui_generation,notice)
        if not page_changed and self.live_tokens.get(address)==token:return
        canvas[640:696,1000:1252]=self.assets.bar
        canvas[652:684,744:988]=self.assets.notices[notice]
        self.live_tokens[address]=token
        if len(self.live_tokens)>16:self.live_tokens={address:token}

    def presented_locked(self,payload):
        model=payload['meta'].get('album',{})
        if self.active and model.get('revision')==self.revision:
            self.presented_revision=self.revision
        event('ALBUM_PRESENTED',generation=payload['generation'],revision=model.get('revision'),
            mode=model.get('mode'),count=model.get('total',0),not_live_HDMI_FPS=True)

    def frozen_wait_locked(self):
        if self.notice=='idle':return None
        remaining=self.notice_until-time.perf_counter()
        if remaining>0:return remaining
        self.notice='idle';self.frozen_redraw=True
        return 0.

    @staticmethod
    def _name_ok(name):
        return isinstance(name,str) and Path(name).name==name and name.startswith('capture_') and name.endswith('.jpg')

    def _path(self,name):
        if not self._name_ok(name):raise ValueError('Invalid captured photo name')
        root=self.folder.resolve();path=(root/name).resolve()
        if path.parent!=root:raise ValueError('Photo is outside capture directory')
        return path

    def _thumb_path(self,name):
        if not self._name_ok(name):raise ValueError('Invalid thumbnail name')
        root=self.folder.resolve();directory=root/'.thumbs'
        if directory.is_symlink():raise ValueError('Thumbnail directory cannot be a symlink')
        path=(directory/name).resolve()
        if path.parent!=directory or directory.parent!=root:raise ValueError('Thumbnail is outside capture directory')
        return path

    def _scan(self):
        if not self.folder.exists():return ()
        # A bounded gallery of the most recent captures; scanning only happens on events.
        import heapq
        with os.scandir(self.folder) as entries:
            return tuple(heapq.nlargest(2000,(e.name for e in entries if self._name_ok(e.name) and e.is_file(follow_symlinks=False))))

    @staticmethod
    def _atomic(path,data):
        temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()

    def _save(self,job):
        image,meta=job;began=time.perf_counter()
        self.folder.mkdir(parents=True,exist_ok=True)
        # Strip the unused X channel on the low-priority IO thread.
        bgr=cv2.cvtColor(image,cv2.COLOR_BGRA2BGR)
        okay,encoded=cv2.imencode('.jpg',bgr,[cv2.IMWRITE_JPEG_QUALITY,self.quality])
        if not okay:raise OSError('JPEG encoder failed')
        stamp=time.strftime('%Y%m%d_%H%M%S')
        name='capture_%s_%s_f%06d_%s.jpg'%(stamp,str(time.time_ns())[-9:],meta['camera_sequence'],uuid.uuid4().hex[:8])
        path=self._path(name);self._atomic(path,encoded.tobytes())
        # Thumbnail failure must not turn an already saved full photo into a failure.
        try:
            thumb=self._fit(bgr,344,184)[0]
            okay,small=cv2.imencode('.jpg',thumb,[cv2.IMWRITE_JPEG_QUALITY,80])
            if okay:
                thumb_path=self._thumb_path(name);thumb_path.parent.mkdir(exist_ok=True)
                self._atomic(thumb_path,small.tobytes())
        except Exception as exc:event('PHOTO_THUMBNAIL_DEFERRED',file=name,exception=repr(exc))
        event('PHOTO_SAVED',file=str(path),bytes=int(encoded.size),elapsed_s=time.perf_counter()-began,**meta)
        with self.display.condition:
            self.saved+=1;self.saving=False
            if not self.closed:
                self._notice_locked('saved')
                if self.active and self.mode=='grid':self._schedule_locked(rescan=True)

    @staticmethod
    def _fit(image,width,height,enlarge=False,zoom=1,focus=None):
        h,w=image.shape[:2];factor=min(width/w,height/h)
        if not enlarge:factor=min(1.,factor)
        factor*=zoom
        cw=min(w,max(1,int(width/factor)));ch=min(h,max(1,int(height/factor)))
        cx,cy=(w/2,h/2) if focus is None else focus
        sx=int(np.clip(cx-cw/2,0,w-cw));sy=int(np.clip(cy-ch/2,0,h-ch))
        dw=min(width,max(1,int(round(cw*factor))));dh=min(height,max(1,int(round(ch*factor))))
        x=(width-dw)//2;y=(height-dh)//2
        result=np.zeros((height,width,3),np.uint8)
        cv2.resize(image[sy:sy+ch,sx:sx+cw],(dw,dh),dst=result[y:y+dh,x:x+dw],interpolation=cv2.INTER_LINEAR)
        result.setflags(write=False)
        return result,(sx,sy,factor,x,y,dw,dh)

    def _read(self,path):
        if path.stat().st_size>16*1024*1024:raise ValueError('Captured photo exceeds gallery limit')
        image=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if image is None or image.shape[0]*image.shape[1]>1280*720:raise ValueError('Invalid captured photo dimensions')
        return image

    def _thumb(self,name):
        value=self.thumb_cache.get(name)
        if value is not None:self.thumb_cache.move_to_end(name);return value
        try:
            path=self._thumb_path(name)
            image=self._read(path) if path.is_file() else self._read(self._path(name))
        except Exception:return None
        value=self._fit(image,344,184)[0];self.thumb_cache[name]=value
        while len(self.thumb_cache)>8:self.thumb_cache.popitem(last=False)
        return value

    def _load(self,job):
        names=self._scan() if job['rescan'] else job['files']
        mode=job['mode'];page=max(0,min(job['page'],max(0,(len(names)-1)//6)))
        model=dict(mode=mode,busy=False,files=names,page=page,total=len(names),selected=job['selected'],notice='empty' if not names else 'idle')
        if mode=='photo' and job['photo'] in names:
            name=job['photo'];image=self._read(self._path(name))
            fitted,mapping=self._fit(image,PHOTO_RECT[2],PHOTO_RECT[3],zoom=job['zoom'],focus=job['focus'])
            sx,sy,factor,x,y,w,h=mapping
            model.update(photo=name,image=fitted,zoom=job['zoom'],position=names.index(name)+1,
                mapping=(sx,sy,factor,x+PHOTO_RECT[0],y+PHOTO_RECT[1],w,h))
        else:
            model['mode']='grid';model['items']=tuple(dict(name=n,image=self._thumb(n)) for n in names[page*6:page*6+6])
        d=self.display
        with d.condition:
            if (not self.closed and self.active and job['revision']==self.revision
                    and job['generation']==d.ui_generation and job['token']==d.inspection.token):
                if time.perf_counter()<self.notice_until and self.notice in ('error','deleted','saved'):
                    model['notice']=self.notice
                self.files=names;self.page=page;self.mode=model['mode'];self._model_locked(model)

    def _delete(self,job):
        removed=0;errors=[]
        for name in job['names']:
            try:
                path=self._path(name)
                if path.exists():path.unlink();removed+=1
                thumb=self._thumb_path(name)
                if thumb.exists() and not thumb.is_symlink():thumb.unlink()
                self.thumb_cache.pop(name,None)
            except Exception as exc:errors.append((name,repr(exc)))
        event('PHOTO_DELETE_COMPLETED',confirmed=True,requested=len(job['names']),deleted=removed,errors=errors)
        with self.display.condition:
            self.deleted+=removed;self.selected.clear();self.confirm_names=()
            if not self.closed:
                self._notice_locked('error' if errors else 'deleted')
                if self.active:self.mode='grid';self.page=0;self._schedule_locked(rescan=True)

    def _run(self):
        try:
            # Linux nice applies to this worker's native thread only.
            if hasattr(os,'setpriority') and hasattr(threading,'get_native_id'):
                try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),10)
                except OSError:pass
            while True:
                with self.display.condition:
                    while not self.closed and self.save_job is None and self.delete_job is None and self.load_job is None:
                        self.display.condition.wait()
                    if self.save_job is not None:kind='save';job=self.save_job;self.save_job=None
                    elif self.delete_job is not None:kind='delete';job=self.delete_job;self.delete_job=None
                    elif self.closed:return
                    else:kind='load';job=self.load_job;self.load_job=None
                try:
                    if kind=='save':self._save(job)
                    elif kind=='delete':self._delete(job)
                    else:self._load(job)
                except BaseException as exc:
                    event('PHOTO_IO_FAILED',operation=kind,exception=repr(exc),hardware_reference_retained=False)
                    with self.display.condition:
                        self.failures+=1
                        if kind=='save':self.saving=False
                        if not self.closed:
                            self._notice_locked('error')
                            if self.active:self._model_locked(dict(self.model,busy=False,notice='error'))
                finally:job=None
        finally:event('PHOTO_IO_STOPPED',hardware_references=False)

    def statistics_locked(self):
        seconds=self.album_seconds+(time.perf_counter()-self.opened_at if self.opened_at is not None else 0.)
        return dict(directory=str(self.folder),saved=self.saved,deleted=self.deleted,failures=self.failures,
            album_active=self.active,album_seconds=seconds,capture_busy=self.saving,
            worker_started=self.worker is not None,encoding_on_live_thread=False)

    def close(self):
        with self.display.condition:
            self.closed=True;self.capture_request=None;self.load_job=None;self.display.condition.notify_all()
        worker=self.worker
        if worker is not None:
            worker.join(.5)
            if worker.is_alive():event('PHOTO_IO_FINISHING',owned_RAM_only=True,hardware_resources_retained=False)


def render_album(canvas,payload,assets):
    """Event-only composition. All file reads/decodes/resizes happened on the IO worker."""
    album=payload['meta'].get('album',{});media=assets.media_assets
    canvas[:]=(14,12,10);canvas[:72]=media.header
    mode=album.get('mode','grid');selected=set(album.get('selected',()))
    if mode=='photo' and album.get('image') is not None:
        x,y,w,h=PHOTO_RECT;canvas[y:y+h,x:x+w]=album['image']
        title='%d / %d | %dx | %s'%(album.get('position',0),album.get('total',0),album.get('zoom',1),album.get('photo',''))
    else:
        items=album.get('items',())
        for rect,item in zip(TILES,items):
            x,y,w,h=rect;cv2.rectangle(canvas,(x,y),(x+w-1,y+h-1),(45,42,38),-1)
            image=item.get('image')
            if image is not None:canvas[y+10:y+194,x+20:x+364]=image
            cv2.putText(canvas,item['name'][:41],(x+12,y+220),cv2.FONT_HERSHEY_SIMPLEX,.36,(225,225,225),1,cv2.LINE_AA)
            checked=item['name'] in selected
            color=(235,205,60) if checked else (125,115,105)
            cv2.rectangle(canvas,(x+w-48,y+h-44),(x+w-18,y+h-14),color,2)
            if checked:cv2.line(canvas,(x+w-43,y+h-29),(x+w-34,y+h-20),color,3);cv2.line(canvas,(x+w-34,y+h-20),(x+w-22,y+h-37),color,3)
        title='SD CARD | %d photos | page %d | selected %d'%(album.get('total',0),album.get('page',0)+1,len(selected))
    if mode!='confirm':
        for name,rect in zip(('previous','next','grid','zoom','delete','clear'),FOOTER):
            x,y,w,h=rect;canvas[y:y+h,x:x+w]=media.buttons[name]
    cv2.putText(canvas,title[:88],(390,46),cv2.FONT_HERSHEY_SIMPLEX,.42,(235,235,235),1,cv2.LINE_AA)
    notice=album.get('notice','idle')
    if notice!='idle':canvas[20:52,1012:1256]=media.notices.get(notice,media.notices['error'])
    if mode=='confirm':
        cv2.rectangle(canvas,(344,230),(936,454),(28,25,22),-1)
        cv2.rectangle(canvas,(344,230),(936,454),(105,95,85),2)
        canvas[278:310,518:762]=media.notices['confirm']
        cv2.putText(canvas,'%d PHOTO(S)'%album.get('delete_count',0),(518,370),cv2.FONT_HERSHEY_SIMPLEX,.8,(235,235,235),1,cv2.LINE_AA)
        for name,rect in (('confirm',FOOTER[3]),('cancel',FOOTER[4])):
            x,y,w,h=rect;canvas[y:y+h,x:x+w]=media.buttons[name]


# ======================================================================
# ===== [10/35] v100_ai_image =====
# ======================================================================


"""Click-only preprocessing/postprocessing; ncnn stays outside the UI process."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT=Path(__file__).resolve().parent
PREPROCESS_VERSION='rgb-area-imagenet-chw-f32-v1'


def prepare(source,receipt):
    #   ⭐ 2026-10-27：原来写死 640x480。换 800x600 摄像头时这里会直接抛，
    #      整个 AI 通路失效。模型输入本来就是 resize 到 256x192，
    #      所以这里只校验【类型/通道/只读】，尺寸交给 resize。
    if (source.dtype!=np.uint8 or source.ndim!=3 or source.shape[2]!=3
            or source.flags.writeable or min(source.shape[:2])<8):
        raise ValueError('AI requires an immutable HxWx3 uint8 BGR snapshot')
    manifest=json.loads((ROOT/'v98_ai_manifest.json').read_text(encoding='utf-8'))
    p=manifest['preprocessing'];w,h=p['width'],p['height']
    rgb=cv2.cvtColor(source,cv2.COLOR_BGR2RGB)
    small=cv2.resize(rgb,(w,h),interpolation=cv2.INTER_AREA)
    mean=np.asarray(p['mean'],np.float32).reshape(1,1,3)
    std=np.asarray(p['std'],np.float32).reshape(1,1,3)
    x=np.ascontiguousarray(((small.astype(np.float32)/255.-mean)/std).transpose(2,0,1),dtype='<f4')
    data=x.tobytes()
    header=dict(receipt,type='infer',shape=[3,h,w],dtype='float32-le',
        preprocessing=PREPROCESS_VERSION,source_shape=list(source.shape),
        source_sha256=hashlib.sha256(source.tobytes()).hexdigest(),tensor_sha256=hashlib.sha256(data).hexdigest())
    return header,data


def finish(result,payload,header,selection_context=None,source=None):
    from ai import quad_from_mask as quad_from_mask
    if any(result.get(k)!=header[k] for k in ('source_sha256','tensor_sha256','preprocessing')):
        raise ValueError('AI image/tensor receipt mismatch')
    if result.get('status')!='mask':
        if payload:raise ValueError('Unexpected image payload for failed inference')
        return result
    if (result.get('shape')!=[192,256] or result.get('dtype')!='uint8'
            or len(payload)!=192*256 or hashlib.sha256(payload).hexdigest()!=result.get('mask_sha256')):
        raise ValueError('AI mask format/hash mismatch')
    mask=np.frombuffer(payload,np.uint8).reshape(192,256)
    if not np.isin(mask,(0,1)).all():raise ValueError('AI mask must be binary')
    quad,fit,selection_detail=select_mask(mask!=0,selection_context,source)
    if quad is None:
        ambiguous=selection_detail.get('reason') in ('multiple_targets','merged_targets','merged_edges_unproved')
        return dict(result,status='failed',failure_kind='ambiguous_target' if ambiguous else 'no_plane',
            error='目标未分清，请点书中心或拉开两本书' if ambiguous else ('点击位置未找到完整目标，请重新点选' if selection_context is not None else '未找到完整目标'),selection_detail=selection_detail)
    #   ⭐ 同样不能写死 640x480：从 header 里的真实源尺寸换算回像素坐标。
    sh=header.get('source_shape') or [480,640,3]
    quad*=np.array([float(sh[1])/256.,float(sh[0])/192.],np.float32)
    answer=dict(result,status='candidate',quad=quad.tolist(),mask_fit_iou=float(fit),selection_detail=selection_detail)
    if selection_context is not None:
        answer['target_selection_proof']=proof(selection_context,selection_context['point'],header['sequence'],
            selection_context.get('mapping','mapped'),selection_method=selection_detail['reason'],component=selection_detail.get('component'),
            candidate_count=selection_detail.get('candidate_count',1),current_aligned=False)
    return answer


# ======================================================================
# ===== [11/35] v100_ai_tracking =====
# ======================================================================


"""One-time corner handoff and cached source label; no per-frame AI hooks."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def unchanged(a,b):
    # Full observed gray image, not a few sample pixels. Restrictive thresholds
    # deliberately fall back to complete FB on camera noise/exposure changes.
    if a.shape!=b.shape:return False
    diff=cv2.absdiff(a,b)
    return float(cv2.norm(diff,cv2.NORM_INF))<=1. and float(cv2.mean(diff)[0])<=.15


def align_current(context,camera,frozen,quad):
    """Never seed a moving live tracker directly from the old inference frame."""
    from tracking import OwnedFrame as OwnedFrame
    verifier=None;current=None
    try:
        context.check();lease=camera.take(3.)
        try:
            image=np.array(lease.image,copy=True,order='C');image.setflags(write=False)
            current=OwnedFrame(image,float(lease.ready),int(lease.sequence),float(lease.timestamp),int(lease.flags))
        finally:lease.release()
        context.check()
        primary_failure=None
        try:
            verifier=PersistentManualTracker(frozen,quad,320,authority='ai_bridge')
            if getattr(verifier,'physical',False):
                q,detail=verifier.update(current,radius=12.)
                if q is None:raise ValueError(str(detail.get('reason')))
                method='manual_default_physical_fallback'
            else:
                gray,scale=verifier.observer.get(current.image)
                if np.array_equal(scale,verifier.scale) and unchanged(verifier.gray,gray):
                    q=np.asarray(quad,np.float32).copy();method='strict_gray_static'
                elif verifier.fixed:raise ValueError('current alignment needs texture or static continuity')
                else:
                    q,detail=verifier.update(current)
                    if q is None:raise ValueError(str(detail.get('reason')))
                    method='original_complete_FB_RANSAC'
        except (ValueError,cv2.error) as exc:
            primary_failure=str(exc)
            if verifier is not None:verifier.close();verifier=None
            # One bounded physical-body fallback at admission only; all old
            # exterior gates remain. Never grant CURRENT to an old AI quad.
            try:
                verifier=PhysicalTracker(frozen,quad,320,authority='ai_bridge_physical_fallback')
                q,detail=verifier.update(current,radius=12.)
                if q is None:raise ValueError(str(detail.get('reason')))
                method='manual_then_physical_four_edges'
            except (ValueError,cv2.error) as fallback:
                raise ValueError('AI current-frame alignment failed: manual='+primary_failure+'; physical='+str(fallback)) from fallback
        context.check()
        checkpoint('AI_CURRENT_FRAME_ALIGNED',generation=context.generation,source_sequence=frozen.sequence,
            current_sequence=current.sequence,source_age_s=max(0.,current.ready-frozen.ready),method=method,
            current_anchor=True,non_physical_FB_thresholds_preserved=True,
            physical_four_edge_evidence=getattr(verifier,'physical',False),primary_failure=primary_failure,
            admission_strategy='manual first, one bounded physical fallback')
        return current,q
    except BaseException:
        if current is not None:current.release()
        raise
    finally:
        if verifier is not None:verifier.close()


@contextmanager
def badges(display):
    assets=getattr(display,'ui_assets',None)
    if assets is None:yield;return
    image=cv2.imdecode(np.frombuffer((Path(__file__).resolve().parent/'v100_ai_badges.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.shape!=(84,320,3):raise ValueError('Invalid AI status badges')
    image.setflags(write=False)
    names=('MANUAL','MANUAL_HELD','MANUAL_FIXED');old={n:assets.status_badges[n] for n in names}
    previous_template=display.manual_status_template
    try:
        for i,n in enumerate(names):assets.status_badges[n]=image[i*28:(i+1)*28]
        display.manual_status_template='AI ASSIST %s | CORR %.1f | DISP %.1f | %s'
        yield
    finally:
        assets.status_badges.update(old);display.manual_status_template=previous_template


def run_ai(context,**kwargs):
    checkpoint('AI_CORRECTION_SESSION_BEGIN',generation=context.generation,corner_source='ai',
        tracking='AI physical-body seed then batched physical edges; other planes retain FB',automatic_pipeline='shared correction backend',
        ai_flow_revision='20261027-9-recovery',inference_required=True,background_inference=False)
    with badges(context.display):return run_manual(context,**kwargs)


# ======================================================================
# ===== [12/35] v75_hotswitch =====
# ======================================================================


"""Owner-only stream handoff for every UI mode; no live-frame hooks."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v75_hotswitch=[]
IDLE_TTL_S=3.

def camera_key(device,width,height,fps,color_mode):
    return (str(device),int(width),int(height),float(fps),None if color_mode is None else int(color_mode))

@dataclass
class StreamTransfer:
    camera:object
    budget:object
    key:tuple
    ticket:object
    parked_at:float
    ready_after:float=0.
    next_budget_check:float=0.
    stabilized:bool=True
    idle:bool=False
    expires_at:float=0.
    reconfigured:bool=False
    def acquisition_check(self,check):
        def guarded():
            check();now=time.perf_counter()
            if self.budget is not None and self.budget.paused and now>=self.next_budget_check:
                self.budget.check(0);self.next_budget_check=now+.5
        return guarded

class CameraHandoff:
    """Only the existing UI/P1 owner can transfer a fully retired reader set."""
    def __init__(self,state,clock=None,camera_factory=None):
        self.state=state;self.owner=threading.get_ident();self.pending=None;self.closed=False
        self.clock=clock or time.perf_counter;self.camera_factory=camera_factory
    def _owner(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Camera handoff requires the existing UI owner')
    def _current_locked(self,ticket):
        return bool(not self.closed and not self.state.stopping and self.state.ticket is ticket
            and self.state.page==ticket.page and not ticket.cancel.is_set()
            and ticket.page in ('home','compare','rectified','snapshot'))
    def _requested_locked(self,old_ticket,next_ticket):
        return bool(next_ticket is not old_ticket and self._current_locked(next_ticket)
            and next_ticket.switch_from==old_ticket.start_generation)
    @staticmethod
    def _healthy(camera,key):
        if (camera.closed or camera.stop or camera.error is not None or camera.worker is None
                or not camera.worker.is_alive() or (camera.width,camera.height)!=(key[1],key[2])):return False
        if abs(float(camera.actual_fps)-key[3])>max(.5,key[3]*.03):return False
        if key[4] is not None and int(camera.color_mode)!=key[4]:return False
        with camera.condition:
            return not any(not v.released and v.owner!='capture_latest' for v in camera.leases.values())
    @staticmethod
    def _finish_budget(item):
        if item.budget is not None:
            budget=item.budget;item.budget=None;budget.__exit__(None,None,None)
    def offer(self,context,camera,key,budget,*,readers_retired,backend_idle,admitted,idle=False):
        self._owner()
        if not readers_retired or not backend_idle:return False
        with self.state.condition:
            ticket=self.state.ticket
            valid=self._requested_locked(context.ticket,ticket)
            valid=valid or (idle and ticket is context.ticket and self._current_locked(ticket) and ticket.page=='snapshot')
            if self.pending is not None or not valid or not self._healthy(camera,key):return False
            now=self.clock();is_idle=bool(idle or ticket.page=='home')
            item=StreamTransfer(camera,budget,key,ticket,now,stabilized=bool(admitted and getattr(camera,'_p11_stream_stabilized',admitted)),
                idle=is_idle,expires_at=now+IDLE_TTL_S if is_idle else 0.)
            camera.live_preview=None
            self.pending=item
        display=getattr(context,'display',None)
        if not is_idle and display is not None:
            try:
                bind_preview(camera,display,ticket.generation)
            except BaseException:
                self.pending=None;raise
        if is_idle:self._finish_budget(item)
        checkpoint('HOT_SWITCH_CAMERA_PARKED',source_generation=context.ticket.start_generation,
            target_generation=ticket.start_generation,capture_kept_running=True,readers_retired=True,
            old_consumer_leases=0,GC_window_preserved=item.budget is not None,stabilized=item.stabilized,
            idle=is_idle,idle_ttl_s=IDLE_TTL_S if is_idle else None)
        return True
    def _eligible(self,item,ticket):
        with self.state.condition:
            return bool(self._current_locked(ticket) and (item.ticket is ticket or item.idle)
                and (not item.expires_at or self.clock()<item.expires_at)
                and self._healthy(item.camera,item.key))
    def _configure(self,item,key):
        if item.key==key:return True
        if item.key[0]!=key[0] or item.key[4]!=key[4]:return False
        began=self.clock()
        checkpoint('CAMERA_STREAM_RECONFIGURE_BEGIN',from_key=item.key,to_key=key)
        item.camera.reconfigure(key[1],key[2],key[3],key[4])
        item.key=key;item.stabilized=False;item.reconfigured=True
        checkpoint('CAMERA_STREAM_RECONFIGURE_END',elapsed_s=self.clock()-began,
            camera_reopened=False,stream_reconfigured=True,initial_stabilization_repeated=True)
        return self._healthy(item.camera,key)
    def claim(self,context,key):
        self._owner();item=self.pending
        if item is None:return None
        valid=self._eligible(item,context.ticket)
        if valid:
            try:valid=self._configure(item,key)
            except Exception as exc:
                checkpoint('CAMERA_STREAM_RECONFIGURE_FALLBACK',error=str(exc),full_reopen_required=True)
                valid=False
        if not valid:
            self.close_pending('ticket_or_stream_changed')
            checkpoint('HOT_SWITCH_COLD_FALLBACK',generation=context.ticket.start_generation,
                reason='ticket_or_stream_changed',full_startup_required=True)
            return None
        self.pending=None;item.ticket=context.ticket;item.idle=False;item.expires_at=0.
        item.ready_after=max(float(context.ticket.switch_requested_at),self.clock())
        checkpoint('HOT_SWITCH_CAMERA_REUSED',generation=context.ticket.start_generation,
            camera_reopened=False,stream_reconfigured=item.reconfigured,
            initial_stabilization_repeated=not item.stabilized,ready_after=item.ready_after,
            transfer_s=self.clock()-item.parked_at,request_to_claim_s=self.clock()-context.ticket.switch_requested_at,
            full_current_target_admission_required=True,GC_window_reset=False)
        return item
    def prepare_profile(self,ticket,key):
        """Complete device negotiation before committing backend/display/UI shape."""
        self._owner();item=self.pending
        if item is not None and self._eligible(item,ticket):
            try:
                if self._configure(item,key):return item
            except Exception as exc:
                checkpoint('CAMERA_STREAM_RECONFIGURE_FALLBACK',error=str(exc),full_reopen_required=True)
        if self.pending is not None:self.close_pending('profile_full_open')
        factory=self.camera_factory
        if factory is None:
            from display import CameraSource as CameraSource
            factory=CameraSource
        camera=factory(*key)
        item=StreamTransfer(camera,None,key,ticket,self.clock(),stabilized=False)
        self.pending=item
        checkpoint('CAMERA_PROFILE_DEVICE_READY',key=key,camera_reopened=True,stream_reconfigured=False)
        return item
    def close_pending(self,reason):
        self._owner();item=self.pending;self.pending=None
        if item is None:return
        try:item.camera.close()
        except BaseException:
            _RETAINED__v75_hotswitch.append(item);raise
        finally:self._finish_budget(item)
        checkpoint('HOT_SWITCH_IDLE_CAMERA_CLOSED',generation=item.ticket.start_generation,reason=reason)
    def idle_remaining(self):
        item=self.pending
        return max(0.,item.expires_at-self.clock()) if item is not None and item.idle else None
    def close_unused(self):
        self._owner();item=self.pending
        if item is None:return
        with self.state.condition:
            valid=not self.closed and not self.state.stopping
            if item.idle:valid=valid and self.clock()<item.expires_at
            else:valid=valid and self._current_locked(item.ticket)
        if not valid:self.close_pending('idle_expired_or_pending_cancelled')
    def close(self):
        self._owner();self.closed=True;self.close_pending('application_exit')


# ======================================================================
# ===== [13/35] v101_ai_camera =====
# ======================================================================


"""AI-click camera transitions only. No worker, polling, frame or device hooks."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED__v101_ai_camera=[]


def claim(context,device,width,height,fps,color_mode):
    broker=getattr(context,'hot',None)
    if broker is None:return None
    return broker.claim(context,camera_key(device,width,height,fps,color_mode))


def finish_previous_budget(transfer):
    # The old live epoch ends before click-only Python/model work. The original
    # run_manual starts its normal new budget after the corner handoff.
    budget=transfer.budget
    if budget is not None:
        try:budget.__exit__(None,None,None)
        except BaseException:
            _RETAINED__v101_ai_camera.append(budget);raise
        transfer.budget=None


def park(context,camera,device,width,height,fps,color_mode,budget,*,readers_retired,backend_idle,admitted):
    broker=getattr(context,'hot',None)
    if broker is None or not context.cancel.is_set():return False
    # Broker rechecks identity, source generation, cancellation, parameters,
    # capture health and every CPU lease under its original owner/locks.
    return broker.offer(context,camera,camera_key(device,width,height,fps,color_mode),budget,
        readers_retired=readers_retired,backend_idle=backend_idle,admitted=admitted)


# ======================================================================
# ===== [14/35] v102_ai_selection =====
# ======================================================================


"""Explicit AI-page selection; requests never run in the normal video loop."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _check(context, deadline):
    context.check()
    if time.perf_counter() >= deadline:
        raise TimeoutError('AI selection session ended')
    if context.display.error is not None:
        raise context.display.error


def select_frame(context, raw, color_mode, frozen, deadline, camera=None,auto_recapture=False):
    """Return a verified seed, or (None,None) for an explicit new capture.

    Own and retire every Request before source replacement, handoff or return.
    Request/Inspection retain generation, token, sequence and source checks.
    A failed inference stays on the AI page. Manual is a separate user request.
    """
    from ai import start_request as start_request
    display = context.display
    inspection = display.inspection
    task = None
    started = None
    try:
        _check(context, deadline)
        if not inspection.begin_ai(raw, color_mode, context.generation, frozen.sequence):
            _check(context, deadline)
            raise RuntimeError('AI page was not accepted')
        checkpoint('AI_SELECTION_BEGIN', generation=context.generation,
                   sequence=frozen.sequence, source='frozen_current_camera_frame',
                   fixed_source=camera is None, manual_fallback='explicit_user_only')
        while True:
            _check(context, deadline)
            if task is not None:
                task.poll()
                inspection.ai_progress(context.generation,
                    'candidate' if task.done.is_set() else
                    str((task.progress or {}).get('stage') or task.service.state))
            action = inspection.take_action(context.generation)
            if action is not None:
                name, value = action
                if name == 'ai':
                    if task is not None:
                        task.close()
                        task = None
                    started = time.perf_counter()
                    try:
                        task = start_request(inspection, context.generation)
                        checkpoint('AI_REQUEST_DISPATCHED', generation=context.generation,
                                   sequence=frozen.sequence, request_id=task.receipt['request_id'],
                                   initial_service_state=task.service.state)
                    except Exception as exc:
                        inspection.ai_failed(context.generation, str(exc), 'runtime_error')
                elif name == 'refresh':
                    return None, None
                elif name in ('auto', 'manual'):
                    # UI dispatch creates the requested next ticket; never
                    # switch to a manual seed inside an AI-labelled session.
                    raise UIReturnRequested()
                elif name == 'confirm':
                    if task is not None:
                        task.close()
                        task = None
                    _check(context, deadline)
                    if camera is not None:
                        while not context.native_setup.done.is_set():
                            _check(context, deadline)
                            context.native_setup.done.wait(.10)
                        context.native_setup.result()
                        try:
                            current, quad = align_current(context, camera, frozen, value)
                        except (ValueError, TimeoutError) as exc:
                            _check(context, deadline)
                            if auto_recapture:
                                checkpoint('AI_AUTOMATIC_RECAPTURE',generation=context.generation,
                                    reason=str(exc),policy='bounded fresh-source retry, at most two per entry')
                                return None,None
                            inspection.ai_alignment_failed(context.generation, str(exc))
                            continue
                        frozen.release()
                    else:
                        current, quad = frozen, value
                    checkpoint('AI_SEED_ACCEPTED', generation=context.generation,
                               sequence=current.sequence, corner_source='ai',
                               total_click_request_ms=(time.perf_counter()-started)*1000.
                                   if started is not None else None,
                               includes_cold_start=True, current_alignment=camera is not None,
                               hardware_proof_still_required=True)
                    return current, quad
            with display.condition:
                display.condition.wait(.10)
    finally:
        if task is not None:
            task.close()


def select_live(context, camera, deadline):
    from tracking import OwnedFrame as OwnedFrame
    warming = True
    warm_begin = time.perf_counter()
    observed = 0
    previous_sequence=None
    recaptures=0
    while True:
        _check(context, deadline)
        try:
            frame = camera.take(.15)
        except TimeoutError:
            continue
        try:
            sequence=int(frame.sequence)
            if sequence!=previous_sequence:observed+=1;previous_sequence=sequence
            # A slow FIRST delivery must not bypass all startup observations.
            if warming and observed<12:continue
            if warming:checkpoint('AI_CAPTURE_SETTLED',generation=context.generation,
                distinct_frames=observed,selected_sequence=sequence,elapsed_s=time.perf_counter()-warm_begin,
                policy='minimum distinct frames; video content is not a global stillness test')
            warming = False
            raw = np.array(frame.image, copy=True, order='C')
            raw.setflags(write=False)
            frozen = OwnedFrame(raw, float(frame.ready), int(frame.sequence),
                                float(frame.timestamp), int(frame.flags))
        finally:
            frame.release()
        selected = None
        try:
            selected, quad = select_frame(context, raw, camera.color_mode,
                                          frozen, deadline, camera,auto_recapture=recaptures<2)
            if selected is not None:
                return selected, quad
            recaptures+=1
        finally:
            if selected is not frozen:
                frozen.release()


# ======================================================================
# ===== [15/35] v105_reference =====
# ======================================================================


"""Vectorized fallback for the CPU edge kernel; same evidence requirements."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ALONG=np.linspace(.10,.90,24,dtype=np.float32)
T=2*ALONG-1
def measure_python(gray,q,radius,reference=None):
    q=np.asarray(q,np.float32);edge=np.roll(q,-1,axis=0)-q
    length=np.linalg.norm(edge,axis=1)
    if np.any(length<24):raise ValueError('physical_side_too_short')
    normal=np.stack((edge[:,1],-edge[:,0]),axis=1)/length[:,None]
    base=q[:,None,:]+ALONG[None,:,None]*edge[:,None,:]
    offsets=np.arange(-radius,radius+.25,.5,dtype=np.float32)
    grid=base[:,:,None,:]+offsets[None,None,:,None]*normal[:,None,None,:]
    coords=np.concatenate([(grid+s*normal[:,None,None,:]).reshape(96,-1,2) for s in (1,-1,-2)])
    values=cv2.remap(gray,coords[...,0],coords[...,1],cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    outer,inner,body=np.split(values,3);mag=np.abs(outer-inner)
    error=0 if reference is None else np.abs(body-np.asarray(reference).reshape(96,1))
    h,w=gray.shape
    valid=(coords[...,0]>=0)&(coords[...,0]<w-1)&(coords[...,1]>=0)&(coords[...,1]<h-1)
    valid=np.logical_and.reduce(np.split(valid,3)) & (error<=40)
    peak=(mag>=np.roll(mag,1,axis=1))&(mag>=np.roll(mag,-1,axis=1))&(mag>=8)
    peak[:,[0,-1]]=False
    cap=np.clip(1.05*np.max(np.where(np.abs(offsets)[None,:]<=2,mag,0),axis=1),16,80)
    scores=np.where(valid&peak,np.minimum(mag,cap[:,None])-.8*np.abs(offsets)[None,:]-.65*error,-1e9)
    idx=scores.argmax(1);rows=np.arange(96);lo=np.maximum(0,idx-1);hi=np.minimum(len(offsets)-1,idx+1)
    mid=mag[rows,idx];den=mag[rows,lo]-2*mid+mag[rows,hi]
    refine=.25*(mag[rows,lo]-mag[rows,hi])/np.where(np.abs(den)>.01,den,-1.)
    shift=(offsets[idx]+np.clip(refine,-.4,.4)).reshape(4,24)
    good=((mid>=8)&(np.abs(offsets[idx])<radius-.1)&valid[rows,idx]&peak[rows,idx]).reshape(4,24)
    for i in range(3):
        n=good.sum(1);s=(good*T).sum(1);ss=(good*T*T).sum(1)
        v=(good*shift).sum(1);sv=(good*shift*T).sum(1);den=n*ss-s*s
        if np.any(den<1):raise ValueError('physical_edge_distribution_insufficient')
        tilt=(n*sv-s*v)/den;intercept=(v-tilt*s)/n
        residual=shift-intercept[:,None]-tilt[:,None]*T
        if i<2:good=good & (np.abs(residual)<=1)
    count=good.sum(1);rms=np.sqrt((good*residual*residual).sum(1)/np.maximum(count,1))
    span=np.max(np.where(good,T,-10),axis=1)-np.min(np.where(good,T,10),axis=1)
    if np.any(count<15) or np.any(span<1.1) or np.any(rms>.7):raise ValueError('physical_four_edges_not_proved')
    a=q+normal*(intercept-tilt)[:,None];b=q+edge+normal*(intercept+tilt)[:,None]
    v=b-a;line=np.stack((v[:,1],-v[:,0]),axis=1);c=-(line*a).sum(1)
    prev=np.roll(line,1,axis=0);pc=np.roll(c,1);det=prev[:,0]*line[:,1]-prev[:,1]*line[:,0]
    if np.any(np.abs(det)<length*np.roll(length,1)*.1):raise ValueError('physical_corner_intersection_invalid')
    result=np.stack(((prev[:,1]*c-pc*line[:,1])/det,(pc*line[:,0]-prev[:,0]*c)/det),axis=1).astype(np.float32)
    pos=(base+(intercept[:,None]+tilt[:,None]*T-2)[:,:,None]*normal[:,None,:]).astype(np.float32)
    measured=cv2.remap(gray,pos[...,0],pos[...,1],cv2.INTER_LINEAR).astype(np.float32).reshape(96)
    return result,dict(support=(count/24).tolist(),edge_rms=rms.tolist(),sample_count=96,body=measured,edge_backend='numpy105')


# ======================================================================
# ===== [16/35] v104_physical_tracking =====
# ======================================================================


"""Physical boundary tracking with two-sided contrast and bounded recovery."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
from tracking import EdgeWorkspace as EdgeWorkspace
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def measure(gray,q,radius=4.,reference=None,workspace=None):
    workspace=workspace or EdgeWorkspace()
    result,detail=(workspace.measure(gray,q,radius,reference) if workspace.lib is not None
                   else measure_python(gray,q,radius,reference))
    from tracking import _valid__v31_tracking as _valid
    if not _valid(result,gray.shape,q,'legacy'):raise ValueError('physical_quad_invalid')
    return result,detail

class PhysicalTracker:
    physical=True
    def __init__(self,frame,quad,limit=320,authority='ai_physical',entry_radius=8.):
        from tracking import GrayObserver__v31_tracking as GrayObserver
        self.observer=GrayObserver(limit);self.closed=False
        try:
            gray,scale=self.observer.get(frame.image)
            self._initialize(gray,scale,quad,float(frame.ready),authority,entry_radius)
        except BaseException:self.close();raise
    @classmethod
    def from_observation(cls,gray,scale,quad,ready,limit=320,authority='manual'):
        from tracking import GrayObserver__v31_tracking as GrayObserver
        obj=cls.__new__(cls);obj.observer=GrayObserver(limit);obj.closed=False
        try:obj._initialize(gray,scale,quad,ready,authority,3.)
        except BaseException:obj.close();raise
        return obj
    def _initialize(self,gray,scale,quad,ready,authority,radius):
        self.workspace=EdgeWorkspace();self.scale=np.asarray(scale).copy();self.previous_ready=ready
        self.authority=authority
        self.kind='PHYSICAL_EDGE_FAST';self.fixed=False;self.points=None;self.failures=0
        self.next_search=0.;self.search_stage=0;self.pending=None
        self.q=np.asarray(quad,np.float32).copy()
        seed=(self.q+.5)/self.scale-.5
        try:found,detail=measure(gray,seed,radius,workspace=self.workspace)
        except ValueError:
            # Only on ambiguous entry: compare the inside of the selected body
            # to candidate edges. An inner-screen edge often has reversed sign
            # but also a different inside appearance. Keep all four proof gates.
            edge=np.roll(seed,-1,axis=0)-seed;length=np.linalg.norm(edge,axis=1)
            if np.any(length<24):raise
            normal=np.stack((edge[:,1],-edge[:,0]),axis=1)/length[:,None]
            along=np.linspace(.10,.90,24,dtype=np.float32)
            base=seed[:,None,:]+along[None,:,None]*edge[:,None,:]
            points=base[:,:,None,:]-np.array([1.,2.,3.],np.float32)[None,None,:,None]*normal[:,None,None,:]
            points=points.reshape(96,3,2).astype(np.float32)
            inside=cv2.remap(gray,points[...,0],points[...,1],cv2.INTER_LINEAR)
            reference=np.median(inside,axis=1).astype(np.float32)
            try:found,detail=measure(gray,seed,radius,reference,self.workspace)
            except ValueError:
                # A slightly inset seed can straddle screen text and bezel.
                # One bounded outward hypothesis only at entry; no scene scan.
                expanded=seed.mean(0)+(seed-seed.mean(0))*1.04
                found,detail=measure(gray,expanded,radius,workspace=self.workspace)
                if np.max(np.linalg.norm((found-seed)*self.scale,axis=1))>20:
                    raise ValueError('physical_entry_displacement_too_large')
                detail['entry_outward_hypothesis']=True
            detail['entry_body_disambiguation']=True
        self.reference=detail.pop('body');self.raw_q=(found+.5)*self.scale-.5
        self.q=self.raw_q.copy();self.velocity=np.zeros((4,2),np.float32)
        checkpoint('AI_PHYSICAL_TRACKER_READY',authority=authority,source_sha256=_SOURCE_SHA256,
            feature_region='physical boundary with measured inner appearance; either exterior polarity',
            per_frame_model=False,per_frame_lk=False,profile_samples=96,edge_detail=detail,
            recovery_max_hz=5,automatic_scene_switch=False)
    def update(self,frame,radius=4.):
        began=time.perf_counter();cpu=time.thread_time();stamp=float(frame.ready)
        recovering=self.failures>0;result=None;detail={}
        try:
            if recovering and stamp<self.next_search:
                detail=dict(manual_motion_proved=False,reason='physical_retry_pending')
                return None,self._detail(detail,began,cpu)
            gray,scale=self.observer.get(frame.image)
            if not np.array_equal(scale,self.scale):raise ValueError('physical_source_layout_changed')
            gap=stamp-self.previous_ready
            if gap<0:raise ValueError('physical_capture_gap')
            if gap>.75 and not recovering and self.authority!='ai_bridge':
                recovering=True;self.failures=1
            self.previous_ready=stamp
            prediction=self.raw_q+np.clip(self.velocity,-6.,6.)
            if recovering:
                prediction=self.pending if self.pending is not None else self.raw_q
                radius=4. if self.pending is not None else (8.,16.,32.,40.)[min(self.search_stage,3)]
                self.search_stage+=int(self.pending is None);self.next_search=stamp+.2
            found,edges=measure(gray,(prediction+.5)/scale-.5,radius,self.reference,self.workspace)
            body=edges.pop('body');measured=(found+.5)*scale-.5
            oldarea=abs(cv2.contourArea(self.raw_q.astype(np.float32)))
            ratio=abs(cv2.contourArea(measured.astype(np.float32)))/max(oldarea,1.)
            oldlen=np.linalg.norm(np.roll(self.raw_q,-1,axis=0)-self.raw_q,axis=1)
            newlen=np.linalg.norm(np.roll(measured,-1,axis=0)-measured,axis=1)
            if not .82<ratio<1.22 or np.any(newlen/oldlen<.86) or np.any(newlen/oldlen>1.18):
                raise ValueError('physical_target_shape_changed')
            delta=float(np.max(np.linalg.norm(measured-self.raw_q,axis=1)))
            if delta>(110. if recovering else 32.):raise ValueError('physical_motion_outside_window')
            if recovering and self.pending is None:
                self.pending=measured.copy();self.next_search=stamp
                detail=dict(manual_motion_proved=False,reason='physical_recovery_confirmation',search_radius=radius)
                return None,self._detail(detail,began,cpu)
            if recovering and np.max(np.linalg.norm(measured-self.pending,axis=1))>16:
                raise ValueError('physical_recovery_unstable')
            shift=float(np.max(np.linalg.norm(measured-self.q,axis=1)))
            candidate=self.q.copy() if shift<=.65 else measured if shift>=3. else self.q+.8*(measured-self.q)
            selected_quad(candidate,frame.image.shape)
            self.velocity=np.zeros((4,2),np.float32) if recovering else .4*self.velocity+.6*(measured-self.raw_q)
            self.raw_q=measured;self.q=np.asarray(candidate,np.float32);self.failures=0
            self.pending=None;self.search_stage=0;self.next_search=0.
            # Very slow bounded update follows exposure; the original body cannot
            # be replaced by an unrelated high-contrast screen edge in one frame.
            self.reference+=.02*np.clip(body-self.reference,-8.,8.)
            if recovering:checkpoint('PHYSICAL_SAME_TARGET_RECOVERED',automatic_switch=False,source_shift=delta)
            detail=dict(manual_motion_proved=True,current_outer_edge_evidence=True,physical_corner_shift=shift,
                physical_static_deadband=shift<=.65,physical_edges=edges,recovered_same_target=recovering)
            result=self.q.copy()
        except (ValueError,cv2.error) as exc:
            self.failures+=1;self.pending=None;self.velocity.fill(0.)
            detail=dict(manual_motion_proved=False,current_outer_edge_evidence=False,reason=str(exc))
            if self.failures in (1,3) or self.failures%20==0:
                checkpoint('AI_PHYSICAL_EDGE_REJECTED',reason=str(exc),consecutive=self.failures,
                    old_coordinates_not_renewed=True,recovery_radius=(8,16,32,40)[min(self.search_stage,3)])
        return result,self._detail(detail,began,cpu)
    def _detail(self,detail,began,cpu):
        detail.update(manual_tracking=self.kind,physical_body=True,video_features=False,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu)
        return detail
    def close(self):
        if getattr(self,'closed',True):return
        self.closed=True;transaction=getattr(self.observer,'transaction',None);close=getattr(transaction,'close',None)
        if callable(close):close()
        self.observer=None

def create_tracker(frame,quad,limit=320,authority='ai'):
    try:return PhysicalTracker(frame,quad,limit,authority)
    except (ValueError,cv2.error) as exc:
        checkpoint('AI_TRACKER_FALLBACK',reason=str(exc),tracker='FB_TRACK',automatic_switch=False)
        return PersistentManualTracker(frame,quad,limit,authority)


# ======================================================================
# ===== [17/35] v107_hybrid =====
# ======================================================================


"""One live camera/PL owner: exact automatic frontend, event-only AI rescue."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
from tracking import OutputMonitor as OutputMonitor
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class CurrentRate__v107_hybrid:
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

class HybridFrontend__v107_hybrid:
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
        self.monitor=OutputMonitor(self.started);self.rate=CurrentRate__v107_hybrid();self.valid_fps=0.
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
        from tracking import V74Acquire as V74Acquire
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
            self.rate=CurrentRate__v107_hybrid();self.valid_fps=0.;self.last_valid_at=None
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
        from tracking import OwnedFrame as OwnedFrame
        from core import model_bgr as model_bgr
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
        from tracking import OwnedFrame as OwnedFrame
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
        from display import FrameJob as FrameJob
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


# ======================================================================
# ===== [18/35] v108_hybrid_status =====
# ======================================================================


"""Cached hybrid footer, independent of camera, model, and frame ownership.

The atlas is decoded once at module import. Runtime selection only returns a
read-only 320x28 view and formats the existing English rate label. Chinese
glyphs, fonts, Pillow and filesystem reads never enter the live frame path.
"""
from core import RELEASE_ID as RELEASE_ID

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ORIGINS=('AUTO','AI','MANUAL')
PHASES=('AUTO_SEARCH','AUTO_TRACK','AI_LOADING','AI_INFER','AI_CONFIRM',
        'AI_TRACK','WAIT_TARGET','EMPTY_WAIT','AI_ERROR','MANUAL_TRACK','MANUAL_FIXED','MANUAL_SNAPSHOT',
        'AUTO_RECOVER','AI_REJECT_RECOVER','RECOVERY_COOLDOWN','DISPLAY_HOLD')
QUALIFIERS=('NORMAL','HELD','LOST')
TILE_WIDTH=320
TILE_HEIGHT=28
_PHASE_SET=frozenset(PHASES)
_CURRENT_STATES=frozenset(('CURRENT','MANUAL'))
_HELD_STATES=frozenset(('HELD','MANUAL_HELD'))
_PHASE_HINTS={
    'AUTO_SEARCH':'SEARCH CURRENT FRAME',
    'AUTO_TRACK':'AUTO TRACK',
    'AI_LOADING':'AI LOADING / WAIT',
    'AI_INFER':'AI ONE-SHOT INFERENCE',
    'AI_CONFIRM':'AI CURRENT-FRAME VERIFY',
    'AI_TRACK':'AI CORRECTION',
    'WAIT_TARGET':'WAIT TARGET',
    'EMPTY_WAIT':'EMPTY / NEXT TARGET AUTO FIRST',
    'AI_ERROR':'AI FAILED / WAIT',
    'MANUAL_TRACK':'MANUAL SELECT / TRACK',
    'MANUAL_FIXED':'MANUAL FIXED / RESELECT IF MOVED',
    'MANUAL_SNAPSHOT':'MANUAL STILL / RECAPTURE',
    'AUTO_RECOVER':'AUTO RESEARCH / RECOVERY',
    'AI_REJECT_RECOVER':'ALIGN FAILED / AUTO RECOVERY',
    'RECOVERY_COOLDOWN':'RECOVERY COOLDOWN',
    'DISPLAY_HOLD':'PAUSED VIEW / PREPARING NEW FRAME',
}


def _load_badges():
    image=cv2.imdecode(np.frombuffer((Path(__file__).resolve().parent/
        'v108_hybrid_status.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    keys=tuple((origin,phase,qualifier) for origin in ORIGINS
        for phase in PHASES for qualifier in QUALIFIERS)
    if image is None or image.shape!=(len(keys)*TILE_HEIGHT,TILE_WIDTH,3):
        raise ValueError('Invalid cached hybrid status atlas')
    image.setflags(write=False)
    return {key:image[i*TILE_HEIGHT:(i+1)*TILE_HEIGHT] for i,key in enumerate(keys)}


_BADGES=_load_badges()

def _rate(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>=0. else 0.
    except (TypeError,ValueError,OverflowError):return 0.


@lru_cache(maxsize=len(_BADGES))
def _descriptor(origin,phase,qualifier):
    return _BADGES[(origin,phase,qualifier)],_PHASE_HINTS[phase]


def footer(meta,has_output,display_rate):
    """Return (cached badge, label), or None for an untagged legacy offer.

    correction_origin describes the current correction authority, while
    hybrid_phase describes the running operation. Neither implies a valid
    current output: the existing state and output presence remain decisive.
    hybrid_valid_fps is supplied by completed unique valid corrections; it is
    separate from the HDMI owner's submission rate. No rate is inferred from
    AI model calls, source labels, or a nominal camera/HDMI configuration.
    """
    origin=meta.get('correction_origin')
    if origin not in ORIGINS:return None
    state=meta.get('state','SEARCHING')
    phase=meta.get('hybrid_phase')
    if phase=='AUTO_RECOVER' and meta.get('recovery_from_ai'):phase='AI_REJECT_RECOVER'
    if origin=='AI' and has_output and meta.get('manual_tracking')=='FIXED':phase='MANUAL_FIXED'
    if phase not in _PHASE_SET:
        if origin=='MANUAL':
            mode=meta.get('manual_tracking')
            phase=('MANUAL_SNAPSHOT' if mode=='SNAPSHOT' else 'MANUAL_FIXED'
                if mode=='FIXED' else 'MANUAL_TRACK') if has_output else 'WAIT_TARGET'
        else:
            phase=('AI_TRACK' if origin=='AI' else 'AUTO_TRACK') if has_output else 'WAIT_TARGET'
            if origin=='AUTO' and state in ('INITIALIZING','PLACEMENT','SEARCHING','STARTING'):
                phase='AUTO_SEARCH'
    if not has_output and phase in ('AUTO_TRACK','AI_TRACK','MANUAL_TRACK','MANUAL_FIXED','MANUAL_SNAPSHOT'):
        phase='WAIT_TARGET'
    if phase=='DISPLAY_HOLD':qualifier='HELD'
    elif state=='LOST' or (state in _HELD_STATES and not has_output):
        qualifier='LOST'
    elif state in _HELD_STATES:qualifier='NORMAL' if meta.get('continuity_output') and has_output else 'HELD'
    else:qualifier='NORMAL'
    badge,hint=_descriptor(origin,phase,qualifier)
    output_state=('CURRENT' if state in _CURRENT_STATES else 'HELD'
        if state in _HELD_STATES else 'NONE') if has_output and state!='LOST' else 'NONE'
    if has_output and phase=='MANUAL_SNAPSHOT':output_state='STILL'
    if has_output and phase=='MANUAL_FIXED':output_state='FIXED'
    if phase=='DISPLAY_HOLD':output_state='PAUSED'
    valid_rate=meta.get('hybrid_valid_fps',meta.get('manual_fps',0.)
        if origin=='MANUAL' else meta.get('correction_fps',0.))
    label='CORR(valid) %.1f | DISP %.1f | OUT %s | %s'%(
        0. if phase=='DISPLAY_HOLD' else _rate(valid_rate),_rate(display_rate),output_state,hint)
    if output_state in ('FIXED','STILL'):label=label.replace('CORR(valid)','CORR(output)',1)
    if phase=='RECOVERY_COOLDOWN':label+=' | RETRY %.1fs'%_rate(meta.get('recovery_retry_after_s',0.))
    if has_output and meta.get('continuity_output'):label+=' | LIVE CONTINUITY <=1s'
    if meta.get('ai_mode_locked'):label+=' | AI LOCK'
    return badge,label


# ======================================================================
# ===== [19/35] v109_target_cycle =====
# ======================================================================


"""Conservative target departure/return latch; small probes only when needed.

This proposes new admission, never corners or a CURRENT output receipt.
Tracking loss alone cannot establish absence. Stable empty evidence must be
observed before a separate stable reappearance can start another search epoch.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class TargetCycle:
    def __init__(self,interval=.5):
        self.interval=float(interval);self.next_at=0.;self.state='UNKNOWN'
        self.reference=None;self.quad=None;self.empty=None;self.pending=None
        self.negative_since=None;self.negative_count=0;self.positive_since=None;self.positive_count=0
        self.last_sequence=None;self.probes=0
        self.candidate_box=None;self.candidate_count=0;self.candidate_since=None
        self.candidate_version=0;self.candidate_anchor=None;self.present_at=None
    @staticmethod
    def small(image):
        step=max(1,round(max(image.shape[:2])/160))
        view=image[::step,::step]
        return np.ascontiguousarray(view[:,:,0] if view.shape[2]==2 else cv2.cvtColor(view,cv2.COLOR_BGR2GRAY))
    def lock(self,image,quad):
        self.reference=self.small(image)
        self.quad=np.asarray(quad,np.float32)*np.array([self.reference.shape[1]/image.shape[1],self.reference.shape[0]/image.shape[0]],np.float32)
        self.state='PRESENT';self.pending=None;self.negative_count=self.positive_count=0
        self.negative_since=self.positive_since=None
        self.reset_candidate(new_target=True)
    def reset_candidate(self,new_target=False):
        # Box, count and start time form one observation history. Never retain
        # an old box with a cleared clock across a missing contour or new lock.
        self.candidate_box=None;self.candidate_count=0;self.candidate_since=None;self.present_at=None
        if new_target:self.candidate_anchor=None
    def tracking_good(self):
        # Measured tracking is stronger evidence than a missing coarse contour.
        if self.state!='ABSENT':self.state='PRESENT'
        self.negative_count=0;self.negative_since=None
    @staticmethod
    def _quads(small):
        smooth=cv2.GaussianBlur(small,(3,3),0)
        low=max(8,min(24,int(float(np.std(smooth))*.35)))
        edge=cv2.Canny(smooth,low,low*3)
        contours,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        h,w=small.shape;found=[]
        for c in contours:
            area=abs(cv2.contourArea(c))
            if not .018*h*w<=area<=.90*h*w:continue
            p=cv2.approxPolyDP(c,.028*cv2.arcLength(c,True),True)
            if len(p)!=4 or not cv2.isContourConvex(p):continue
            q=p.reshape(4,2).astype(np.float32)
            if np.any(q[:,0]<=1) or np.any(q[:,1]<=1) or np.any(q[:,0]>=w-2) or np.any(q[:,1]>=h-2):continue
            lengths=np.linalg.norm(q-np.roll(q,1,axis=0),axis=1)
            if lengths.min()<8 or lengths.max()/lengths.min()>4.5:continue
            found.append((area,q))
        return [q for _,q in sorted(found,key=lambda pair:pair[0],reverse=True)[:8]]
    @staticmethod
    def _difference(a,b):
        delta=a.astype(np.float32)-b.astype(np.float32)
        delta-=np.median(delta)
        return np.abs(delta)
    def _empty_evidence(self,small):
        if self.empty is not None and self.empty.shape==small.shape:
            d=self._difference(small,self.empty)
            if float(d.mean())<5. and float(np.mean(d>15))<.08:return True
        if self.reference is not None and self.reference.shape==small.shape:
            q=self.quad;center=q.mean(0)
            core=np.zeros(small.shape,np.uint8);ring=np.zeros_like(core);inside=np.zeros_like(core)
            cv2.fillConvexPoly(core,np.rint(center+(q-center)*.60).astype(np.int32),1)
            cv2.fillConvexPoly(ring,np.rint(center+(q-center)*1.16).astype(np.int32),1)
            cv2.fillConvexPoly(inside,np.rint(center+(q-center)*.90).astype(np.int32),1)
            ring[inside!=0]=0;c=small[core!=0];r=small[ring!=0]
            if c.size<20 or r.size<20:return False
            d=self._difference(small,self.reference)[core!=0]
            disappeared=float(d.mean())>5. and float(np.mean(d>10.))>.15
            resembles_background=abs(float(np.median(c))-float(np.median(r)))<18. and abs(float(np.std(c))-float(np.std(r)))<16.
            return disappeared and resembles_background
        # Startup/failed-AI waiting has no known object boundary. Require a
        # broadly uniform background, not merely failure to find a rectangle.
        h,w=small.shape;med=[];spread=[]
        for y in range(3):
            for x in range(3):
                cell=small[y*h//3:(y+1)*h//3,x*w//3:(x+1)*w//3]
                med.append(float(np.median(cell)));spread.append(float(np.std(cell)))
        med.sort();spread.sort()
        return med[-2]-med[1]<24. and spread[-2]-spread[1]<16.
    def _foreground(self,small):
        if self.empty is None or self.empty.shape!=small.shape:return None
        mask=(self._difference(small,self.empty)>12.).astype(np.uint8)
        changed=float(mask.mean())
        if not .01<changed<.65:return None
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours,key=cv2.contourArea,reverse=True)[:3]:
            x,y,w,h=cv2.boundingRect(c)
            if w>=10 and h>=10 and w*h>=.025*small.size and cv2.contourArea(c)>.012*small.size:
                return np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],np.float32)
        return None
    def _candidate_signal(self,q,now):
        if q is None:self.reset_candidate();return
        box=np.r_[q.min(0),q.max(0)]
        stable=(self.candidate_since is not None and self.candidate_box is not None
            and float(np.max(np.abs(box-self.candidate_box)))<=8.)
        if stable:self.candidate_count+=1
        else:self.candidate_count=1;self.candidate_since=now;self.present_at=None
        self.candidate_box=box
        if self.candidate_count>=3 and self.candidate_since is not None and now-self.candidate_since>=1.:
            self.present_at=now
            if self.candidate_anchor is None or float(np.max(np.abs(box-self.candidate_anchor)))>8.:
                self.candidate_anchor=box.copy();self.candidate_version+=1
    def observe(self,image,sequence,now):
        if now<self.next_at or sequence==self.last_sequence:return None
        self.next_at=now+self.interval;self.last_sequence=sequence;self.probes+=1
        small=self.small(image);quads=self._quads(small)
        proposal=quads[0] if quads else self._foreground(small) if self.state=='ABSENT' else None
        self._candidate_signal(proposal,now)
        if self.state=='ABSENT':
            q=proposal
            changed=self.empty is not None and float(self._difference(small,self.empty).mean())>3.
            if q is None or not changed:
                self.pending=None;self.positive_count=0;self.positive_since=None;return None
            box=np.r_[q.min(0),q.max(0)]
            stable=(self.positive_since is not None and self.pending is not None
                and float(np.max(np.abs(box-self.pending)))<=8.)
            if not stable:self.positive_count=1;self.positive_since=now
            else:self.positive_count+=1
            self.pending=box
            if self.positive_count>=3 and self.positive_since is not None and now-self.positive_since>=1.:
                self.state='PRESENT';self.reference=None;self.quad=None;self.pending=None
                self.negative_count=0;self.negative_since=None
                return 'RETURNED'
            return None
        if quads or not self._empty_evidence(small):
            self.negative_count=0;self.negative_since=None;return None
        if self.negative_since is None:self.negative_since=now
        self.negative_count+=1
        if self.negative_count>=4 and now-self.negative_since>=1.5:
            self.state='ABSENT';self.empty=small.copy();self.pending=None
            self.positive_count=0;self.positive_since=None
            return 'ABSENT'
        return None


# ======================================================================
# ===== [20/35] v116_continuity =====
# ======================================================================


"""Bounded geometry reuse on fresh pixels; no image storage or tracking work."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

MAX_CONTINUITY_S=1.
HARD_STOP_REASONS=frozenset(('manual_motion_too_large',
    'candidate_touches_image_border_or_is_clipped','跟踪四角越界或形变异常'))


def continuity_cancelled(row):
    """Reuse existing definite loss reports; no new motion/colour threshold."""
    return row.get('target_cycle_state')=='ABSENT' or row.get('track_reason') in HARD_STOP_REASONS


def valid_continuity(row,now):
    """Only producer-labelled held jobs can supply a live continuity pair."""
    if not row.get('continuity_output') or not (row.get('state')=='HELD' or
            row.get('state')=='MANUAL_HELD' and row.get('manual_reference_v17')):return False
    verified=float(row.get('verified_at',0.));ready=float(row.get('capture_ready_at',0.))
    return (not row.get('frozen_output') and not continuity_cancelled(row) and
        len(row.get('corners',()))==4 and row.get('continuity_epoch')==row.get('hybrid_epoch') and
        verified>0. and 0.<=now-verified<=MAX_CONTINUITY_S and
        now<=float(row.get('continuity_deadline',0.)) and -.02<=now-ready<=.5 and
        verified<=ready+.02)


def mark_continuity(row,has_tiles,now):
    """Metadata only; held frames never advance the verified geometry clock."""
    row['continuity_output']=False
    if not (row.get('state')=='HELD' or row.get('state')=='MANUAL_HELD' and row.get('manual_reference_v17')) or not has_tiles:return False
    verified=float(row.get('verified_at',0.))
    row.update(continuity_output=True,continuity_deadline=verified+MAX_CONTINUITY_S,
        continuity_age_s=max(0.,now-verified),continuity_epoch=row.get('hybrid_epoch'))
    row['continuity_output']=valid_continuity(row,now)
    return row['continuity_output']


# ======================================================================
# ===== [21/35] v110_unified =====
# ======================================================================


"""Automatic-first admission; AI supplies a seed to the exact manual frontend.

One producer owns all tracker mutations. The watchdog requests transitions;
it never reads image pixels, closes a frontend or launches model inference.
"""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
from tracking import OutputMonitor as OutputMonitor
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class CurrentRate__v110_unified:
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

class HybridFrontend__v110_unified:
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
        self.rate=CurrentRate__v110_unified();self.monitor=OutputMonitor(self.started);self.valid_fps=0.;self.low_since=None
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
        from tracking import V74Acquire as V74Acquire
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
            self.epoch+=1;self.requested=None;self.low_since=None;self.rate=CurrentRate__v110_unified();self.valid_fps=0.
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
        from tracking import OwnedFrame as OwnedFrame
        from core import model_bgr as model_bgr
        service=getattr(self.context.display,'ai_service',None)
        if service is None:self._wait('AI service unavailable',True);return
        selection_context=None
        if self.target_selection is not None:
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
            opts={k:v for k,v in self.options.items() if k!='_ai_physical_profile'}
            built=ManualFrontend(self.camera,frame,q,self.size,opts,raw_required=self.raw_required)
        self.active=built;self.active.raw_required=self.raw_required;self.active_index=0
        self.camera._p11_stream_stabilized=True
        self.engine='MANUAL_SAME_TARGET';self.phase='AI_CONFIRM';self.awaiting_first_output=True
        self.cycle.lock(frame.image,q)
        checkpoint('UNIFIED_MANUAL_SEEDED',epoch=self.epoch,tracking_engine=self.engine,manual_defaults_preserved=True,
            periodic_ai_recovery=False,sequence=int(frame.sequence))
    def _start_manual(self,frame,result):
        from tracking import OwnedFrame as OwnedFrame
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
        from display import FrameJob as FrameJob
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


# ======================================================================
# ===== [22/35] v111_recovery =====
# ======================================================================


"""Immediate recovery, with no change to steady automatic/manual tracking.

The producer alone creates/retires CPU frontends or sends AI requests. A
watchdog only flags deadlines. True manual entry never uses this controller.
"""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class AIBudget:
    """Failed/unstable requests count; only the owner's stable request refunds."""
    def __init__(self,maximum=3,window=60.):
        self.maximum=maximum;self.window=window;self.times=deque();self.tickets=deque();self.lock=threading.Lock()
    def _due(self,now):
        while self.times and self.times[0]<=now-self.window:self.times.popleft();self.tickets.popleft()
        return self.times[0]+self.window if len(self.times)>=self.maximum else now
    def due(self,now):
        with self.lock:return self._due(now)
    def reserve(self,now,ticket=None):
        with self.lock:
            if self._due(now)>now:return False
            if ticket is not None and any(t is ticket for t in self.tickets):raise ValueError('AI budget ticket already reserved')
            self.times.append(now);self.tickets.append(ticket);return True
    def refund(self,ticket,now):
        if ticket is None:return False
        with self.lock:
            self._due(now)
            for i,owner in enumerate(self.tickets):
                if owner is ticket:
                    del self.times[i];del self.tickets[i];return True
            return False
_AUTOMATIC_AI_BUDGET=AIBudget()

class HybridFrontend__v111_recovery(HybridFrontend__v110_unified):
    AUTO_SEARCH_S=1.5
    AUTO_CANDIDATE_EXTRA_S=1.3
    AUTO_TOTAL_CAP_S=2.8
    LOSS_S=1.2
    def __init__(self,*args,budget=None,ai_first=False,**kwargs):
        self.ai_budget=budget if budget is not None else _AUTOMATIC_AI_BUDGET
        self.ai_budget_ticket=None;self.ai_budget_epoch=None
        self.recovery_mode=False;self.recovery_round=0
        self.auto_budget_waiting=False;self.ai_wait_due=None;self.ai_wait_candidate_version=None
        self.last_effective_at=None;self.stable_since=None;self.last_failure='';self.recovery_from_ai=False
        self.search_epoch_started=None
        self._skip_initial_auto=bool(ai_first);self.explicit_first_request=bool(ai_first)
        self.ai_mode_locked=bool(ai_first);self.ai_target_acquired=False
        super().__init__(*args,**kwargs)
        self._sync_ai_mode()
        checkpoint('RECOVERY_READY',loss_s=self.LOSS_S,auto_search_s=self.AUTO_SEARCH_S,
            auto_candidate_extra_s=self.AUTO_CANDIDATE_EXTRA_S,auto_total_cap_s=self.AUTO_TOTAL_CAP_S,
            fixed_recovery_cooldown=False,automatic_ai_per_minute=3,
            budget_refund='only own AI request after existing3s stable>=4 output proof',
            true_empty_return='AUTO first after acquired-target loss; bounded AI fallback',
            ai_mode_locked=self.ai_mode_locked,ai_lock_release='acquired target lost')
    def _sync_ai_mode(self):
        ticket=getattr(self.context,'ticket',None)
        if ticket is not None:ticket.ai_mode_locked=self.ai_mode_locked
    def _release_ai_mode(self,reason):
        if not self.ai_mode_locked:return
        self.ai_mode_locked=False;self.ai_target_acquired=False;self._sync_ai_mode()
        checkpoint('AI_MODE_LOCK_RELEASED',reason=reason,epoch=self.epoch,next_admission='AUTO first')
    def _new_acquirer(self,recovery,target_selection):
        if self._skip_initial_auto:
            self._skip_initial_auto=False;self.origin='AI';self.phase='AI_LOADING';self.monitor.suspend()
            self.initial['automatic_first']=False
            return
        super()._new_acquirer(recovery,target_selection)
    def _acquire_phase(self,phase):
        if phase=='SEARCHING' and getattr(self,'camera',None) is not None:self.camera._p11_stream_stabilized=True
        with self.lock:
            now=self.clock();previous=self.auto_stage;self.auto_stage=phase
            if phase=='SEARCHING':
                if self.search_at is None:self.search_at=now
                self.candidate_at=None
            elif phase=='CANDIDATE' and previous!='CANDIDATE':self.candidate_at=now
        checkpoint('UNIFIED_AUTO_PHASE',phase=phase,search_at=self.search_at,candidate_at=self.candidate_at,
            search_s=self.AUTO_SEARCH_S,candidate_extra_s=self.AUTO_CANDIDATE_EXTRA_S,total_cap_s=self.AUTO_TOTAL_CAP_S)
        wake=getattr(self,'watch_wake',None)
        if wake is not None:wake.set()
    def _auto_search_expired(self,now):
        start=self.search_at
        if start is None:
            # Warm recovery already has a live camera. Cold exposure/stability
            # still uses its existing separate startup guard.
            if not self.recovery_mode:return False
            start=self.search_epoch_started
            if start is None:return False
        if now<start+self.AUTO_SEARCH_S:return False
        candidate=(self.auto_stage in ('CANDIDATE','READY') and self.candidate_at is not None
            and self.candidate_at<=start+self.AUTO_SEARCH_S)
        return not candidate or now>=start+self.AUTO_TOTAL_CAP_S
    def _move(self,reason,phase,origin):
        self.selection_proof=None;self.selection_failed=None
        if reason in ('target_absent','target_returned','recover_tracking_lost'):
            self.target_selection=None;self.selection_wait_absent=False
        with self.lock:
            self.transitioning=True
            # Losing/changing the target never refunds a failed/unstable attempt.
            self.ai_budget_ticket=None;self.ai_budget_epoch=None
        preview=getattr(self.camera,'live_preview',None)
        if preview is not None:preview.reset_geometry(self.epoch+1,reason)
        self.monitor.suspend();self._retire_active();self._release_request()
        with self.lock:
            self.epoch+=1;self.requested=None;self.low_since=None;self.rate=CurrentRate__v110_unified();self.valid_fps=0.
            self.awaiting_first_output=False;self.trigger=reason;self.phase=phase;self.origin=origin
            self.last_effective_at=None;self.active_started=None;self.stable_since=None
            self.auto_budget_waiting=False;self.ai_wait_due=None;self.ai_wait_candidate_version=None;self.transitioning=False
        checkpoint('RECOVERY_TRANSITION',reason=reason,phase=phase,origin=origin,epoch=self.epoch,
            recovery_round=self.recovery_round,old_workers_retired=True,camera_reopened=False)
    def _transition(self,reason,empty=False):
        # Called by the retained producer boundary for confirmed absence/return.
        if empty:
            if self.ai_target_acquired:self._release_ai_mode(reason)
            self.recovery_mode=False;self._move(reason,'EMPTY_WAIT',self.origin)
            checkpoint('UNIFIED_EMPTY_WAIT',reason=reason,epoch=self.epoch)
        else:
            self.recovery_round=0
            self.ai_attempted=False;self.recovery_from_ai=False
            if self.ai_mode_locked:self._begin_ai(reason)
            else:self._start_auto(reason)
    def _presence(self,frame):
        # Auxiliary low-rate scene probes must not tear down a valid tracker.
        # Scope the guard to numerical/probe failures; camera/DMA/ownership
        # failures remain fatal and follow the original safe cleanup path.
        try:event=self.cycle.observe(frame.image,int(frame.sequence),self.clock())
        except (TypeError,ValueError,ArithmeticError,cv2.error) as exc:
            if not hasattr(self.cycle,'reset_candidate'):raise
            self.cycle.reset_candidate()
            self.cycle.pending=None;self.cycle.positive_count=self.cycle.negative_count=0
            self.cycle.positive_since=self.cycle.negative_since=None
            checkpoint('RECOVERY_PROBE_RESET',exception_type=type(exc).__name__,exception=str(exc),
                traceback=traceback.format_exc(),epoch=self.epoch,tracking_preserved=True)
            return None
        if self.selection_wait_absent:
            if event!='ABSENT':return None
            self.selection_wait_absent=False
        if event=='ABSENT':
            self.requested='target_absent';checkpoint('UNIFIED_TARGET_ABSENT',epoch=self.epoch,confirmed=True)
        elif event=='RETURNED':
            self.ai_attempted=False;self.requested='target_returned'
            checkpoint('UNIFIED_TARGET_RETURNED',epoch=self.epoch,next_admission='AI locked' if self.ai_mode_locked else 'AUTO first')
        return event
    def _start_auto(self,reason):
        if self.ai_mode_locked:
            self._await_ai(reason);return
        # No round-limit pause. Keep an existing live search worker, especially
        # while an AI quota is unavailable; never rebuild it on every tick.
        if self.acquirer is not None:
            self.requested=None;return
        self.recovery_round+=1;self.recovery_mode=True
        self._move(reason,'AUTO_RECOVER','AUTO')
        self.started=self.clock();self.search_epoch_started=self.started
        self.search_at=None;self.candidate_at=None;self.auto_stage='SEARCHING'
        # A live capture stream already exists: do not repeat exposure startup.
        self._new_acquirer(True,None)
        checkpoint('RECOVERY_AUTO_BEGIN',reason=reason,epoch=self.epoch,recovery_round=self.recovery_round,
            search_s=self.AUTO_SEARCH_S,candidate_extra_s=self.AUTO_CANDIDATE_EXTRA_S,
            total_cap_s=self.AUTO_TOTAL_CAP_S,already_running_stream=True)
    def _await_ai(self,reason):
        """AI-only entry waits for new evidence or its actual quota deadline.

        There is no fixed recovery timer and no request on every camera frame.
        The existing coarse probe stays at its original low rate.
        """
        if self.target_selection is not None:
            self._selection_failure(reason);return
        self.recovery_mode=False;self._move(reason,'WAIT_TARGET','AI')
        now=self.clock();due=self.ai_budget.due(now)
        self.ai_wait_due=due if due>now else None
        self.ai_wait_candidate_version=getattr(self.cycle,'candidate_version',0)
        self.ai_attempted=True
        checkpoint('RECOVERY_AI_EVIDENCE_WAIT',reason=reason,epoch=self.epoch,
            quota_due=self.ai_wait_due,fixed_recovery_cooldown=False,live_preview=True)
    def _wait_auto_budget(self):
        if self.target_selection is not None:
            self._selection_failure('AI请求名额暂不可用，请稍后重新点选');return
        if self.ai_mode_locked:
            self._await_ai('ai_budget_exhausted');return
        if self.acquirer is None:self._start_auto('ai_budget_exhausted')
        self.auto_budget_waiting=True;self.recovery_mode=True;self.requested=None
        checkpoint('RECOVERY_AUTO_CONTINUES',reason='ai_budget_exhausted',epoch=self.epoch,
            quota_due=self.ai_budget.due(self.clock()),worker_retained=True,fixed_recovery_cooldown=False)
    def _selection_failure(self,reason,ambiguous=False):
        # A terminal selection must also retire its searcher. Otherwise its
        # expired clock immediately restarts with the selected point discarded.
        with self.lock:self.transitioning=True
        try:
            self.monitor.suspend();self._retire_active()
            self.recovery_mode=False;self.auto_budget_waiting=False
            self.ai_wait_due=None;self.ai_wait_candidate_version=None
            super()._selection_failure(reason,ambiguous)
        finally:
            with self.lock:self.transitioning=False
    def _begin_ai(self,reason):
        if reason=='recover_tracking_lost' and self.ai_mode_locked:
            if self.ai_target_acquired:self._release_ai_mode(reason)
            else:
                self._await_ai(reason);return
        if not self.ai_mode_locked and reason=='recover_tracking_lost':
            self.recovery_from_ai=False;self._start_auto(reason);return
        # Retry permission belongs to the recovery phase, not to an ABSENT-only
        # latch. Explicit user AI clicks remain separate from this auto budget.
        if self.ai_budget.due(self.clock())>self.clock():
            self._wait_auto_budget();return
        self.recovery_mode=False;self.ai_attempted=False
        self._move(reason,'AI_LOADING','AI')
        checkpoint('UNIFIED_AI_BEGIN',reason=reason,epoch=self.epoch)
    def _dispatch(self,frame):
        if self.ai_attempted:return
        service=getattr(self.context.display,'ai_service',None)
        if service is not None and hasattr(service,'ready_for_request') and not service.ready_for_request():return
        if self.explicit_first_request:
            self.explicit_first_request=False;super()._dispatch(frame);return
        ticket=object()
        if not self.ai_budget.reserve(self.clock(),ticket):self._wait_auto_budget();return
        self.ai_budget_ticket=ticket;self.ai_budget_epoch=self.epoch
        super()._dispatch(frame)
    def _wait(self,reason,system_error=False):
        if self.target_selection is not None:
            self._selection_failure(reason);return
        # Found-but-rejected and no-plane both have a bounded recovery route;
        # neither is represented as waiting for an already PRESENT target.
        self.last_failure=str(reason);self.recovery_from_ai=True
        self._release_request()
        checkpoint('RECOVERY_AI_REJECTED',reason=reason,system_error=system_error,
            target_cycle_state=self.cycle.state,next_action='AI waits for fresh evidence or quota' if self.ai_mode_locked else 'immediate automatic recovery')
        self._start_auto('ai_rejected: '+str(reason))
    def _install_manual(self,frame,q):
        # Do not let the watchdog inspect a half-installed tracker using the
        # previous target's clock. Completion still waits for actual pixels.
        with self.lock:self.transitioning=True
        try:
            super()._install_manual(frame,q)
            with self.lock:
                self.active_started=self.last_effective_at=self.clock();self.stable_since=None
                self.requested=None;self.low_since=None;self.recovery_mode=False;self.recovery_from_ai=False
        finally:
            with self.lock:self.transitioning=False
    def _take_auto_result(self):
        # Explicit absence/return outranks an old worker result. A completed
        # result still wins over a timer-only timeout as in unified8.
        if self.requested in ('target_absent','target_returned'):return False
        if self.origin!='AUTO' or self.acquirer is None:return False
        with self.lock:self.transitioning=True
        try:
            accepted=super()._take_auto_result()
            if accepted:
                with self.lock:
                    self.active_started=self.last_effective_at=self.clock();self.stable_since=None
                    self.requested=None;self.recovery_mode=False;self.recovery_from_ai=False;self.auto_budget_waiting=False
            return accepted
        finally:
            with self.lock:self.transitioning=False
    def tick(self):
        now=self.clock();count=getattr(self.camera,'captured',self.last_capture_count)
        if count!=self.last_capture_count:self.last_capture_count=count;self.capture_seen_at=now
        healthy=getattr(self.camera,'error',None) is None and now-max(self.capture_seen_at,self.last_frame_at)<=.75
        with self.lock:
            self.valid_fps=self.rate.fps(now)
            if not healthy or self.closed or self.transitioning:return
            reason=None
            if self.acquirer is not None:
                if self.auto_budget_waiting:
                    # The same searcher can succeed during the quota wait.
                    # Once quota returns, finish any freshly discovered candidate
                    # before handing the still-unsolved search to AI.
                    fresh_candidate=(self.auto_stage in ('CANDIDATE','READY') and self.candidate_at is not None
                        and now<self.candidate_at+self.AUTO_CANDIDATE_EXTRA_S)
                    if self.ai_budget.due(now)<=now and not fresh_candidate:reason='ai_budget_available'
                elif self.recovery_mode:
                    if self._auto_search_expired(now):reason='recovery_auto_timeout'
                elif self.search_at is None and now-self.started>=8.:reason='startup_no_output'
                elif self._auto_search_expired(now):reason='startup_no_output'
            elif self.active is not None:
                last=self.last_effective_at if self.last_effective_at is not None else self.active_started
                if last is not None and now>=last+self.LOSS_S:reason='recover_tracking_lost'
                elif self.engine=='AUTO_V74' and self.monitor.first_valid is not None and now-self.monitor.first_valid>=1.:
                    if 0.<self.valid_fps<4.:
                        if self.low_since is None:self.low_since=now
                        if now-self.low_since>=1.:reason='low_fps'
                    else:self.low_since=None
            if reason is not None and self.requested is None:
                self.requested=reason;checkpoint('RECOVERY_TRIGGER',reason=reason,epoch=self.epoch,effective_fps=self.valid_fps)
    def completed(self,row,when):
        before=self.rate.last_seq;super().completed(row,when)
        with self.lock:
            if self.closed or self.transitioning or row.get('hybrid_epoch')!=self.epoch or self.rate.last_seq==before:return
            if self.ai_mode_locked and self.origin=='AI' and self.engine=='MANUAL_SAME_TARGET' and not self.ai_target_acquired:
                self.ai_target_acquired=True
                checkpoint('AI_MODE_TARGET_ACQUIRED',epoch=self.epoch,sequence=row.get('camera_sequence'),
                    actual_pixel_output_completed=True,release_on='confirmed absence or1.2s output loss')
            previous=self.last_effective_at;self.last_effective_at=when
            if self.requested=='recover_tracking_lost':
                self.requested=None;checkpoint('RECOVERY_CANCELLED',reason='fresh output before handoff',epoch=self.epoch)
            pending_refund=(self.ai_budget_ticket is not None and self.ai_budget_epoch==self.epoch
                and self.origin=='AI' and self.engine=='MANUAL_SAME_TARGET')
            if not (self.recovery_round or pending_refund):return
            if self.stable_since is None or previous is None or when-previous>.5:self.stable_since=when
            if when-self.stable_since>=3. and self.rate.fps(when)>=4.:
                refunded=False
                if pending_refund:
                    refunded=self.ai_budget.refund(self.ai_budget_ticket,when)
                    self.ai_budget_ticket=None;self.ai_budget_epoch=None
                    checkpoint('AI_BUDGET_STABLE_REFUND',epoch=self.epoch,sequence=row.get('camera_sequence'),
                        stable_s=when-self.stable_since,refunded=refunded,failed_requests_preserved=True)
                if self.recovery_round:
                    checkpoint('RECOVERY_STABLE',epoch=self.epoch,stable_s=when-self.stable_since,
                        failed_ai_budget_preserved=True,own_stable_AI_request_refunded=refunded)
                self.recovery_round=0
    def _tag(self,job):
        job=super()._tag(job)
        job.record.update(ai_mode_locked=self.ai_mode_locked,ai_target_acquired=self.ai_target_acquired)
        if self.recovery_round or self.recovery_from_ai:
            job.record.update(recovery_round=self.recovery_round,recovery_from_ai=self.recovery_from_ai)
        # Geometry becomes available before P1 DMA/HDMI pixels complete.
        preview=getattr(self.camera,'live_preview',None)
        if preview is not None:preview.observe_geometry(job.record)
        return job
    def _idle_job(self,index,frame,begin,cpu):
        # Existing tiny-image probe is reused only during recovery/wait. No new
        # image work is introduced in healthy measured tracking frames.
        if self.recovery_mode:self._presence(frame)
        if (self.ai_mode_locked and self.phase=='WAIT_TARGET' and not self.selection_wait_absent
                and self.requested is None and self.ai_wait_candidate_version is not None):
            now=self.clock();due=self.ai_budget.due(now)
            changed=(getattr(self.cycle,'candidate_version',0)!=self.ai_wait_candidate_version
                and getattr(self.cycle,'present_at',None) is not None and now-self.cycle.present_at<=1.)
            quota_returned=self.ai_wait_due is not None and now>=self.ai_wait_due
            if due<=now and (changed or quota_returned):
                self.requested='ai_fresh_evidence' if changed else 'ai_budget_available'
                self.ai_wait_candidate_version=None;self.ai_wait_due=None
                checkpoint('RECOVERY_AI_READY',reason=self.requested,epoch=self.epoch,fixed_recovery_cooldown=False)
        return super()._idle_job(index,frame,begin,cpu)


# ======================================================================
# ===== [23/35] v112_display_hold =====
# ======================================================================


"""Finite ordinary-RAM display pause; never geometry, DMA or valid FPS proof."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class DisplayHold:
    def __init__(self,seconds=8.):
        self.seconds=float(seconds);self.revision=0;self.attempted=False
        self.payload=None;self.deadline=None;self.rendered=None;self.latest_epoch=-1;self.phase=None;self.capturing=False
    @staticmethod
    def valid(meta,has_output,now):
        ready=meta.get('capture_ready_at')
        return (has_output and meta.get('state')=='CURRENT' and not meta.get('frozen_output')
            and meta.get('correction_origin') in ('AUTO','AI')
            and meta.get('hybrid_phase') in ('AUTO_TRACK','AI_TRACK')
            and ready is not None and 0.<=now-float(ready)<=.5)
    def reset(self):
        self.revision+=1;self.attempted=False;self.payload=None;self.deadline=None
        self.rendered=None;self.latest_epoch=-1;self.phase=None;self.capturing=False
    def stop(self):
        self.revision+=1;self.attempted=True;self.payload=None;self.deadline=None;self.rendered=None;self.capturing=False
    def note(self,meta):
        epoch=meta.get('hybrid_epoch')
        if epoch is not None:self.latest_epoch=max(self.latest_epoch,int(epoch))
        if meta.get('hybrid_phase') is not None:self.phase=meta['hybrid_phase']
    @staticmethod
    def snapshot(raw,out,meta):
        # A temporary completed-output lease is held by the caller only until
        # this ordinary-RAM copy finishes. No CMA/VideoFrame survives here.
        output=np.array(out,dtype=np.uint8,copy=True,order='C');output.setflags(write=False)
        if raw is not None and not (type(raw) is np.ndarray and raw.flags.owndata
                and raw.flags.c_contiguous and not raw.flags.writeable):
            raw=np.array(raw,dtype=np.uint8,copy=True,order='C');raw.setflags(write=False)
        return dict(raw=raw,out=output,meta=dict(meta))


# ======================================================================
# ===== [24/35] v115_pair_display =====
# ======================================================================


"""Metadata-only completed-pair clock. Never blocks capture or owns pixels."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class PairDisplayState:
    def __init__(self):
        self.lock=threading.Lock();self.mode='RAW_ONLY';self.reason='startup';self.revision=0;self.epoch=-1
        self.last_key=None;self.last_pair_at=None;self.last_capture=None;self.last_raw_capture=None
        self.intervals=deque(maxlen=8);self.timeout=.18;self.last_interval=None;self.entry_regression_ms=0.
        self.last_verified=None
    @staticmethod
    def valid(row,has_raw,has_out,now):
        return (has_raw and has_out and (row.get('state') in ('CURRENT','MANUAL') or valid_continuity(row,now)) and
            not row.get('frozen_output') and row.get('target_cycle_state')!='ABSENT' and
            len(row.get('corners',()))==4 and -.02<=now-float(row.get('capture_ready_at',0.))<=.5)
    def _expire(self,now):
        # The short adaptive timer reports late production. It is not a new
        # target-loss decision. Owner continuity supplies new completed pixels;
        # never keep stale input beyond the existing 0.5s freshness bound.
        if self.mode=='PAIRED' and self.last_capture is not None and (
                now-self.last_capture>.5 or self.last_verified is not None and now-self.last_verified>1.):
            self.mode='RAW_ONLY';self.reason='pair_input_expired';self.revision+=1
    def invalidate(self,epoch=None,reason='target_transition'):
        with self.lock:
            if epoch is not None and int(epoch)<self.epoch:return
            if epoch is not None and int(epoch)>self.epoch:
                self.epoch=int(epoch);self.intervals.clear();self.last_interval=None;self.timeout=.18
            self.mode='RAW_ONLY';self.reason=str(reason);self.revision+=1
    def observe(self,row,has_raw,has_out,now):
        """Called only for a complete accepted offer, before pending publication."""
        epoch=int(row.get('hybrid_epoch',0));ready=float(row.get('capture_ready_at',0.))
        key=(epoch,int(row.get('camera_sequence',-1)),ready)
        valid=self.valid(row,has_raw,has_out,now)
        with self.lock:
            self._expire(now)
            if epoch<self.epoch:return 'DROP'
            if epoch==self.epoch and self.last_capture is not None and ready<self.last_capture:return 'DROP'
            if epoch>self.epoch:
                self.epoch=epoch;self.intervals.clear();self.last_interval=None;self.timeout=.18
                self.mode='RAW_ONLY';self.last_capture=None
            if not valid:
                self.mode='RAW_ONLY';self.reason='invalid_result';self.revision+=1
                return 'RAW_ONLY'
            if key==self.last_key or (self.last_capture is not None and ready<self.last_capture):return 'DROP'
            gap=None if self.last_pair_at is None else now-self.last_pair_at
            if self.mode=='PAIRED' and gap is not None and .005<=gap<=.5:
                self.intervals.append(gap);self.timeout=min(.25,max(.15,2.*statistics.median(self.intervals)))
            self.last_interval=gap
            entering=self.mode!='PAIRED'
            self.entry_regression_ms=(max(0.,self.last_raw_capture-ready)*1000.
                if entering and self.last_raw_capture is not None else 0.)
            self.last_key=key;self.last_capture=ready;self.last_pair_at=float(now)
            self.last_verified=float(row.get('verified_at',ready))
            self.mode='PAIRED';self.reason='current_frame_continuity' if row.get('continuity_output') else 'new_completed_pair';self.revision+=1
            return 'PAIRED'
    def rejects(self,row,has_raw,has_out,now):
        epoch=int(row.get('hybrid_epoch',0));ready=float(row.get('capture_ready_at',0.))
        key=(epoch,int(row.get('camera_sequence',-1)),ready)
        with self.lock:
            return epoch<self.epoch or (epoch==self.epoch and self.last_capture is not None and ready<self.last_capture) or (self.valid(row,has_raw,has_out,now) and
                (key==self.last_key or (epoch==self.epoch and self.last_capture is not None and ready<self.last_capture)))
    def packet_current(self,row,now):
        with self.lock:
            self._expire(now)
            return self.mode=='PAIRED' and int(row.get('hybrid_epoch',0))>=self.epoch
    def raw_displayed(self,ready):
        with self.lock:self.last_raw_capture=float(ready)
    def snapshot(self,now):
        with self.lock:
            self._expire(now)
            return dict(display_mode=self.mode,pair_reason=self.reason,pair_revision=self.revision,
                pair_timeout_ms=self.timeout*1000.,pair_stall_ms=None if self.last_pair_at is None else max(0.,now-self.last_pair_at)*1000.,
                pair_interarrival_ms=None if self.last_interval is None else self.last_interval*1000.,
                pair_producer_stalled=bool(self.last_pair_at is not None and now-self.last_pair_at>=self.timeout),
                pair_entry_regression_ms=self.entry_regression_ms)


# ======================================================================
# ===== [25/35] v113_live_preview =====
# ======================================================================


"""Latest-only ordinary-RAM preview; capture remains the sole MMAP owner.

Prepared frames publish their existing immutable snapshot. Capture only makes
a fallback snapshot when that producer has stopped supplying fresh previews.
No camera.take(), HDMI submission, CMA lease or unbounded queue lives here.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class LivePreview:
    def __init__(self,display,generation,color_mode,clock=time.perf_counter):
        self.display=display;self.generation=int(generation);self.color_mode=int(color_mode);self.clock=clock
        self.lock=threading.Lock();self.latest=None;self.published_at=clock()
        self.fallback_copies=0;self.prepared_publications=0;self.fallback_bytes=0
        self.period=max(1./30.,float(getattr(display,'period',1./30.)))
        self.pairing=PairDisplayState()
    def active(self):
        d=self.display
        return (not d.stop and d.ui_generation==self.generation and d.ui_view=='compare'
                and getattr(d,'live_preview',None) is self)
    def capture(self,lease):
        if not self.active():return
        now=self.clock()
        with self.lock:
            # Healthy prepare/offer already owns the one source snapshot.
            if now-self.published_at<self.period*2:return
        raw=np.array(lease.image,dtype=np.uint8,copy=True,order='C');raw.setflags(write=False)
        lease.preview_snapshot=raw
        self.publish(lease,raw,fallback=True)
    def publish(self,lease,raw,fallback=False):
        if not self.active():return
        ready=float(lease.ready);sequence=int(lease.sequence)
        with self.lock:
            if self.latest is not None and ready<self.latest[1]:return
            self.latest=(sequence,ready,raw,self.color_mode,self.generation)
            self.published_at=self.clock()
            if fallback:self.fallback_copies+=1;self.fallback_bytes+=raw.nbytes
            else:self.prepared_publications+=1
        # Normal prepare is followed by the existing completed-output offer.
        # Only fallback needs its own wake, so preview cannot steal its period.
        if fallback:
            with self.display.condition:self.display.condition.notify_all()
    def snapshot(self):
        with self.lock:return self.latest
    def observe_geometry(self,row):
        # Prepared geometry alone cannot replace a completed display pair.
        # Keep the controller hook compatible without image/geometry work.
        return
    def reset_geometry(self,epoch,reason):
        self.pairing.invalidate(epoch,reason)
        if self.active():
            with self.display.condition:self.display.condition.notify_all()

def source_snapshot(camera,lease):
    """Reuse capture fallback for this exact lease, otherwise the normal copy."""
    raw=getattr(lease,'preview_snapshot',None)
    if raw is None:
        raw=np.array(lease.image,dtype=np.uint8,copy=True,order='C');raw.setflags(write=False)
    preview=getattr(camera,'live_preview',None)
    if preview is not None:preview.publish(lease,raw)
    return raw

def bind_preview(camera,display,generation):
    old=getattr(camera,'live_preview',None)
    if old is not None and old is getattr(display,'live_preview',None) and old.color_mode==camera.color_mode:
        # Hot reuse of the SAME camera keeps its immutable latest raw. Only
        # geometry belongs to the new session; a different camera never inherits it.
        preview=old
        with preview.lock:
            preview.generation=int(generation);preview.pairing=PairDisplayState()
            if preview.latest is not None:
                seq,ready,raw,color,_=preview.latest;preview.latest=(seq,ready,raw,color,int(generation))
    else:preview=LivePreview(display,generation,camera.color_mode)
    with display.condition:
        display.live_preview=preview;display.live_packet=None;display.preview_rendered=None;display.live_last_offer_at=0.
    camera.live_preview=preview
    return preview


# ======================================================================
# ===== [26/35] v114_geometry_overlay =====
# ======================================================================


"""Small geometry-only display channel; never grants correction authority."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
Observation=namedtuple('Observation','sequence ready quad epoch stable')

class GeometryOverlay:
    def __init__(self,reference_s=.15,failure_s=.12,max_wall_s=.5):
        self.reference_s=float(reference_s);self.failure_s=float(failure_s);self.max_wall_s=float(max_wall_s)
        self.lock=threading.Lock();self.epoch=-1;self.revision=0;self.history=()
        self.attempt=None;self.failed_at=None;self.hard_reason=None
    def reset(self,epoch=None,reason='transition'):
        with self.lock:
            if epoch is not None and int(epoch)<self.epoch:return
            if epoch is not None:self.epoch=int(epoch)
            self.history=();self.attempt=None;self.failed_at=None;self.hard_reason=str(reason);self.revision+=1
    def observe(self,row,now):
        epoch=int(row.get('hybrid_epoch',0));seq=int(row.get('camera_sequence',-1));ready=float(row.get('capture_ready_at',0.))
        state=row.get('state');reason=str(row.get('track_reason') or '')
        phase=row.get('hybrid_phase');q=row.get('corners')
        if q is None:q=()
        valid=state in ('CURRENT','MANUAL') and not row.get('frozen_output') and len(q)==4
        if valid:
            try:
                q=tuple((float(p[0]),float(p[1])) for p in q)
                valid=all(math.isfinite(v) for p in q for v in p)
            except (TypeError,ValueError,IndexError,OverflowError):valid=False
        hard=(row.get('target_cycle_state')=='ABSENT' or
            phase in ('EMPTY_WAIT','AUTO_RECOVER','RECOVERY_COOLDOWN','WAIT_TARGET','AI_ERROR','AI_LOADING','AI_INFER') or
            any(text in reason.lower() for text in ('motion_too_large','fb_consistency','large_motion')))
        with self.lock:
            if epoch<self.epoch:return False
            if epoch>self.epoch:
                self.epoch=epoch;self.history=();self.attempt=None;self.failed_at=None;self.hard_reason=None
            if self.attempt is not None and ready<self.attempt[1]:return False
            attempt=(seq,ready,state)
            if attempt==self.attempt:return False
            self.attempt=attempt;self.revision+=1
            if valid and not hard:
                previous=self.history[-1] if self.history else None
                stable=bool(row.get('manual_static_hold'))
                if previous is not None and 0.<ready-previous.ready<=.3:
                    # Reuse existing tracked corners; no pixel analysis/optical flow.
                    distance=max(math.hypot(a[0]-b[0],a[1]-b[1]) for a,b in zip(q,previous.quad))
                    stable=distance<=8. and distance/(ready-previous.ready)<=180.
                obs=Observation(seq,ready,q,epoch,stable)
                self.history=(self.history+(obs,))[-2:];self.failed_at=None;self.hard_reason=None
            else:
                if self.failed_at is None:self.failed_at=float(now)
                if hard:self.history=();self.hard_reason=reason or phase or 'target_absent'
            return True
    def select(self,sequence,ready,now):
        sequence=int(sequence);ready=float(ready);now=float(now)
        with self.lock:
            history=self.history;failed_at=self.failed_at;hard=self.hard_reason;revision=self.revision
            epoch=self.epoch
        empty=dict(quad=(),kind='NONE',reason='geometry_not_ready',source_sequence=None,age_ms=None,
            epoch=epoch,revision=revision)
        candidates=[p for p in history if p.ready<=ready+.000001]
        if not candidates:
            if hard:empty['reason']='target_or_motion_reset'
            return empty
        obs=candidates[-1];skew=max(0.,ready-obs.ready);wall=max(0.,now-obs.ready)
        empty.update(source_sequence=obs.sequence,age_ms=skew*1000.)
        if wall>self.max_wall_s:empty['reason']='geometry_expired';return empty
        if failed_at is not None and now-failed_at>self.failure_s:
            empty['reason']='tracking_loss_expired';return empty
        exact=sequence==obs.sequence and abs(ready-obs.ready)<=.002
        if exact and failed_at is None:
            empty.update(quad=obs.quad,kind='CURRENT',reason='prepared_geometry');return empty
        if skew>self.reference_s:empty['reason']='raw_geometry_skew';return empty
        if not obs.stable:empty['reason']='motion_unconfirmed';return empty
        empty.update(quad=obs.quad,kind='REFERENCE',reason='brief_tracking_gap' if failed_at is not None else 'newer_live_raw')
        return empty


# ======================================================================
# ===== [27/35] v117_manual_reference =====
# ======================================================================


"""True-manual-only reference motion; one existing native FB transaction."""
from core import checkpoint as checkpoint
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_CANON=np.float32([[0,0],[63,0],[63,63],[0,63]])
_RING=np.ones((64,64),bool);_RING[4:-4,4:-4]=False

def similarity(a,b):
    x=a-a.mean(0);y=b-b.mean(0);den=float(np.sum(x*x))
    if den<1.e-6:return None,float('inf')
    c=float(np.sum(x*y))/den;s=float(np.sum(x[:,0]*y[:,1]-x[:,1]*y[:,0]))/den
    M=np.array([[c,-s],[s,c]],np.float64);t=b.mean(0)-M@a.mean(0)
    H=np.eye(3);H[:2,:2]=M;H[:2,2]=t
    error=float(np.sqrt(np.mean(np.sum((a@M.T+t-b)**2,axis=1))))
    return H,error

class ReferenceTracker(ManualTracker):
    def __init__(self,frame,quad,limit=320,authority='manual'):
        self.boundary_points=False
        super().__init__(frame,quad,limit,authority)
        self.reference_q=(self.q+.5)/self.scale-.5
        self.reference_points=None if self.points is None else self.points.copy()
        self.reference_epoch=0;self.last_model='initial';self.next_audit=float(frame.ready)+1.
        self.reference_template=self._template(self.gray,self.reference_q)
        self.reference_vector=self.reference_template[_RING].astype(np.float32)
        self.reference_vector-=self.reference_vector.mean()
        self.reference_norm=float(np.linalg.norm(self.reference_vector))
        self.audit_count=0;self.audit_failed=0;self.last_audit=None
        self._roi_indices=None;self._refresh_roi(self.gray.shape)
        checkpoint('MANUAL_REFERENCE_READY',source_sha256=_SOURCE_SHA256,working_points=0 if self.points is None else len(self.points),
            maximum_points=32,one_fb=True,reference_shape=[64,64],audit_period_s=1.,manual_only=True)
    @staticmethod
    def _template(gray,q):
        H=cv2.getPerspectiveTransform(np.asarray(q,np.float32),_CANON)
        return cv2.warpPerspective(gray,H,(64,64),flags=cv2.INTER_LINEAR)
    def _features(self,gray,q):
        self.boundary_points=False
        p=super()._features(gray,q)
        if p is None:return p
        pts=p.reshape(-1,2);small=np.asarray((np.asarray(q)+.5)/self.scale-.5,np.float32)
        distance=np.array([cv2.pointPolygonTest(small,tuple(map(float,x)),True) for x in pts])
        boundary=p[(distance>=-1.)&(distance<=3.)]
        area=max(1.,abs(cv2.contourArea(small)))
        if len(boundary)>=4 and abs(cv2.contourArea(cv2.convexHull(boundary)))>=.35*area:
            p=boundary;self.boundary_points=True
        if len(p)<=24:return p
        pts=p.reshape(-1,2)
        chosen=[]
        # Keep boundary coverage, then greedily retain separated existing points.
        for corner in small:
            order=np.argsort(np.sum((pts-corner)**2,axis=1))
            chosen.append(next(int(i) for i in order if int(i) not in chosen))
        distance=np.min(np.sum((pts[:,None]-pts[chosen][None])**2,axis=2),axis=1)
        while len(chosen)<24:
            distance[chosen]=-1.;i=int(np.argmax(distance));chosen.append(i)
            distance=np.minimum(distance,np.sum((pts-pts[i])**2,axis=1))
        selected=np.ascontiguousarray(pts[chosen].reshape(-1,1,2),np.float32)
        return selected if self._distributed(selected,q) else p
    def _distributed(self,points,q):
        if self.boundary_points and points is not None and len(points)>=4:
            small=np.asarray((np.asarray(q)+.5)/self.scale-.5,np.float32)
            return abs(cv2.contourArea(cv2.convexHull(points)))>=.35*max(1.,abs(cv2.contourArea(small)))
        return super()._distributed(points,q)
    def _reseed_points(self,points,q,gray,move):
        if self._distributed(points,q):return points,False
        return super()._reseed_points(points,q,gray,move)
    def _refresh_roi(self,shape):
        h,w=shape
        if self.points is None or not len(self.points):self._roi_indices=None;return
        centers=np.rint(self.points.reshape(-1,2)).astype(np.int32);yy,xx=np.mgrid[-3:4,-3:4]
        xs=np.clip(centers[:,0,None]+xx.reshape(1,-1),0,w-1).reshape(-1)
        ys=np.clip(centers[:,1,None]+yy.reshape(1,-1),0,h-1).reshape(-1)
        # Same6400-sample budget, centred on actual target features rather than
        # flat background/cover pixels. Index work happens only after real flow.
        self._roi_indices=(np.resize(ys,6400).reshape(80,80),np.resize(xs,6400).reshape(80,80))
    def _still(self,gray,now):
        return False if self._roi_indices is None else super()._still(gray[self._roi_indices],now)
    def _audit(self,gray,q,stamp):
        current=self._template(gray,q)[_RING].astype(np.float32);current-=current.mean()
        norm=float(np.linalg.norm(current));count=len(current)
        self.audit_count+=1;self.next_audit=stamp+1.
        if min(norm,self.reference_norm)<3.*np.sqrt(count):
            self.last_audit=dict(state='insufficient_texture',ncc=None);return True
        ncc=float(np.dot(current,self.reference_vector)/(norm*self.reference_norm))
        self.last_audit=dict(state='matched' if ncc>=.15 else 'mismatch',ncc=ncc)
        if ncc<.15:self.audit_failed+=1;return False
        return True
    def update(self,frame):
        begin=time.perf_counter();cpu=time.thread_time()
        if self.fixed:return super().update(frame)
        detail=dict(manual_tracking='FB_TRACK',manual_motion_proved=False,manual_reference17=True)
        try:
            stamp=float(frame.ready);elapsed=stamp-self.previous_ready
            if not self.first and not 0.<elapsed<=.75:raise ValueError('manual_capture_gap_or_expired_anchor')
            gray,scale=self.observer.get(frame.image)
            if not np.array_equal(scale,self.scale):raise ValueError('manual_source_layout_changed')
            if not self.first and self._still(gray,time.perf_counter()):
                # The point coordinates and native pyramid stay at the last
                # actual flow image. Capture/static samples have their own clock.
                detail.update(static_hold=True,hold_frames=self.hold_frames,reference_epoch=self.reference_epoch,
                    feature_count=len(self.points),manual_motion_model=self.last_model)
                return self.q.copy(),dict(detail,tracker_s=time.perf_counter()-begin,tracker_thread_cpu_s=time.thread_time()-cpu)
            p=self.points
            if not self._distributed(p,self.q):raise ValueError('manual_outer_features_insufficient')
            flow=time.perf_counter();native=self.lk_cache.track(gray,p,levels=3,iterations=20,generation=int(frame.sequence)&0xffffffff)
            if native is None:
                args=dict(winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02))
                f,s,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,p,None,**args)
                if f is None or s is None:raise ValueError('manual_forward_flow_failed')
                back,sb,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,f,None,**args)
            else:f,s,error,back,sb=native
            if f is None or back is None or s is None or sb is None:raise ValueError('manual_backward_flow_failed')
            fb=np.linalg.norm(back.reshape(-1,2)-p.reshape(-1,2),axis=1)
            good=(s.ravel()!=0)&(sb.ravel()!=0)&np.isfinite(f).all(axis=(1,2))&np.isfinite(fb)&(fb<.8)
            detail.update(forward_backward_flow_s=time.perf_counter()-flow,feature_count=len(p),good_features=int(good.sum()),
                lk_backend='native_cached_bidirectional_pyramids' if native is not None else 'opencv_bidirectional')
            minimum=4 if self.boundary_points else 8
            if good.sum()<minimum or float(np.median(fb[good]))>.35:raise ValueError('manual_FB_consistency_failed')
            a=self.reference_points.reshape(-1,2)[good];b=f.reshape(-1,2)[good]
            simple,simple_rms=similarity(a,b);model='similarity_reference'
            if simple is not None and simple_rms<=.20:
                H=simple;keep=np.ones(len(a),bool);fraction=1.;rms=simple_rms
            else:
                H,inliers=cv2.findHomography(a,b,cv2.RANSAC,_RANSAC_PX,maxIters=300,confidence=.995)
                if H is None or inliers is None or not np.isfinite(H).all():raise ValueError('manual_motion_model_failed')
                keep=inliers.ravel()!=0;fraction=float(np.mean(keep));model='projective_reference'
                if keep.sum()<minimum or fraction<_INLIER_MIN:raise ValueError('manual_motion_inliers_failed')
                projected=cv2.perspectiveTransform(a[keep].reshape(-1,1,2),H).reshape(-1,2)
                rms=float(np.sqrt(np.mean(np.sum((projected-b[keep])**2,axis=1))))
                if rms>.75:raise ValueError('manual_reprojection_error')
            next_q=cv2.perspectiveTransform(self.reference_q.reshape(-1,1,2),H).reshape(-1,2)
            small=(self.q+.5)/self.scale-.5
            from tracking import _valid__v31_tracking as _valid
            if not _valid(next_q,gray.shape,small,'legacy'):raise ValueError('manual_current_quad_invalid')
            move=float(np.max(np.linalg.norm(next_q-small,axis=1)))
            if move>64:raise ValueError('manual_motion_too_large')
            q=(next_q+.5)*self.scale-.5
            selected_quad(q,frame.image.shape)
            retained=np.ascontiguousarray(b[keep].reshape(-1,1,2),np.float32)
            next_points,reseeded=self._reseed_points(retained,q,gray,move)
            if next_points is None:raise ValueError('manual_motion_spatial_support_failed')
            top_up=not self.boundary_points and len(next_points)<16 and time.perf_counter()-self.last_seed>=1.
            if reseeded or top_up or stamp>=self.next_audit:
                if not self._audit(gray,next_q,stamp):raise ValueError('manual_reference_mismatch')
            if top_up:
                seeds=self._features(gray,q)
                if self._distributed(seeds,q):next_points=seeds;reseeded=True
                self.last_seed=time.perf_counter()
            if native is not None:self.lk_cache.promote()
            self.q=q.astype(np.float32);self.points=next_points
            if reseeded:
                self.reference_q=next_q.copy();self.reference_points=next_points.copy();self.reference_epoch+=1
            else:self.reference_points=np.ascontiguousarray(self.reference_points[good][keep],np.float32)
            self.gray=gray;self.observer.pin(gray);self.previous_ready=stamp;self.first=False
            self._refresh_roi(gray.shape)
            self._hold_last_full=time.perf_counter();self.last_model=model;self.last_failure=None
            detail.update(manual_motion_proved=True,manual_motion_model=model,reference_epoch=self.reference_epoch,
                reference_audits=self.audit_count,reference_audit=self.last_audit,reference_reseeded=reseeded,
                inlier_fraction=fraction,inlier_count=int(keep.sum()),fb_median=float(np.median(fb[good])),
                reprojection_rms=rms,similarity_rms=simple_rms,features_retained=len(next_points))
            result=self.q.copy()
        except (ValueError,cv2.error) as exc:
            self.last_failure=str(exc);detail['reason']=str(exc);result=None
            checkpoint('MANUAL_REFERENCE_FAIL',reason=str(exc),feature_count=detail.get('feature_count'),
                good_features=detail.get('good_features'),reference_epoch=self.reference_epoch)
        detail.update(tracker_s=time.perf_counter()-begin,tracker_thread_cpu_s=time.thread_time()-cpu)
        return result,detail

class PersistentReferenceTracker(PersistentManualTracker):
    def __init__(self,frame,quad,limit=320,authority='manual'):
        from tracking import prepare_edges as prepare_edges
        prepare_edges()
        self.primary=ReferenceTracker(frame,quad,limit,authority);self.edge=None;self.failures=0
        self.next_retry=0.;self.limit=limit;self.authority=authority;self.closed=False
        if self.primary.fixed:
            try:self.edge=PhysicalTracker.from_observation(self.primary.gray,self.primary.scale,self.primary.q,self.primary.previous_ready,limit,authority)
            except (ValueError,cv2.error):pass
            if self.edge is not None:self.primary.close()


# ======================================================================
# ===== [28/35] v118_display_continuity =====
# ======================================================================


"""Original owner remaps fresh preview pixels while prepare is late; no tracker/copy."""
from core import checkpoint as checkpoint
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class OwnerContinuity:
    def __init__(self,frontend,backend,display,context,clock=time.perf_counter):
        self.front=frontend;self.backend=backend;self.display=display;self.context=context;self.clock=clock
        self.plan=None;self.row=None;self.last_output=0.;self.last_sequence=-1;self.frames=0;self.active=False
        self.owner_thread=threading.get_ident()
    def _end(self,reason):
        if self.active:
            checkpoint('DISPLAY_CONTINUITY_END',reason=reason,frames=self.frames,
                verified_at=self.row.get('verified_at') if self.row else None)
            self.active=False;self.frames=0
    def remember(self,job,row):
        self.last_output=float(row['output_ready_at']) if 'output_ready_at' in row else self.clock()
        self.last_sequence=max(self.last_sequence,int(row.get('camera_sequence',-1)))
        if row.get('state') in ('CURRENT','MANUAL') and getattr(job,'tiles',()):
            self._end('reliable_output_resumed');self.plan=(job.tiles,job.size,job.corners,job.color_mode);self.row=row
        elif row.get('continuity_output'):
            self._end('prepared_continuity_resumed')
        elif not row.get('continuity_output'):
            self._end('geometry_unavailable');self.plan=self.row=None
    def _allowed(self,now):
        d=self.display;f=self.front;r=self.row
        return bool(r and self.plan and not getattr(d,'stop',False) and not getattr(d,'error',None)
            and not getattr(self.backend,'active',False) and not getattr(self.backend,'failed',False)
            and d.ui_view=='compare' and d.ui_generation==self.context.generation
            and not self.context.cancel.is_set() and not getattr(f,'transitioning',False)
            and not getattr(f,'manual_retired',False)
            and not getattr(f,'_continuity_blocked',False) and not getattr(f,'continuity_blocked',False)
            and getattr(getattr(f,'cycle',None),'state',None)!='ABSENT'
            and getattr(f,'epoch',r.get('hybrid_epoch',0))==r.get('hybrid_epoch',0)
            and 0.<=now-float(r.get('verified_at',0.))<1.)
    def pump(self):
        now=self.clock()
        preview=getattr(self.display,'live_preview',None)
        delay=(max(.05,float(getattr(self.display,'period',1./30.))) if self.active else
            max(.15,float(preview.pairing.timeout)) if preview is not None else .18)
        if now-self.last_output<delay:return False
        if not self._allowed(now):self._end('continuity_expired_or_invalidated');return False
        if preview is None or not preview.active():return False
        value=preview.snapshot()
        if value is None:return False
        sequence,ready,raw,color,generation=value
        if generation!=self.context.generation or sequence<=self.last_sequence or not -.02<=now-ready<=.5:return False
        if threading.get_ident()!=self.owner_thread:raise RuntimeError('Continuity requires the existing PL owner')
        from display import FrameJob as FrameJob
        from tracking import OwnedFrame as OwnedFrame
        tiles,size,corners,mode=self.plan;r=self.row
        row={k:r[k] for k in ('correction_origin','corner_source','tracking_engine','hybrid_phase','hybrid_epoch',
            'layout_generation','orientation','target_cycle_state','manual_reference_v17','ai_mode_locked','ai_target_acquired') if k in r}
        row.update(index=-int(sequence)-1,state='HELD',camera_sequence=int(sequence),capture_ready_at=float(ready),
            verified_at=float(r['verified_at']),corners=corners,color_mode=color,output_size=size,
            ps_prepared_at=now,continuity_from_owner_wait=True,track_reason='prepare_wait_current_frame_continuity',
            frozen_output=False,ui_generation=generation,correction_fps=0.,hybrid_valid_fps=0.)
        if not mark_continuity(row,bool(tiles),now):return False
        job=FrameJob(row['index'],OwnedFrame(raw,ready,sequence,ready),tiles,size,'HELD',corners,color,raw,row,source_owned=True)
        try:
            # Exceptional waits may follow prefill; an input slot overwrite
            # must invalidate its cached batch before the next ordinary job.
            packed=getattr(self.backend,'packed',None)
            if packed:packed.clear()
            image,timing=self.backend.execute(job)
            if timing.get('stop_requested'):raise KeyboardInterrupt()
            end=self.clock();row.update(timing,output_ready_at=end,capture_to_output_s=end-ready)
            self.last_output=end;self.last_sequence=sequence
            if not self._allowed(end):self._end('invalidated_during_remap');return False
            self.display.offer(image,row,raw,raw_owned=True,output_reference=self.backend.output_reference(image))
            if not self.active:
                self.active=True;self.frames=0
                checkpoint('DISPLAY_CONTINUITY_BEGIN',camera_sequence=sequence,hybrid_epoch=row.get('hybrid_epoch'),
                    verified_at=row['verified_at'],deadline=row['verified_at']+1.,fresh_pixels=True,
                    owner_thread=self.owner_thread,no_tracking=True)
            self.frames+=1;return True
        finally:job.release_source()


# ======================================================================
# ===== [29/35] v119_profile_ui =====
# ======================================================================


"""相机输入档位（480P / 600P）：左下角按钮 + 弹出面板 + 选档。

⚠️ 分工说明（2026-10-29）
    - 本模块只管 **UI 状态机 + 绘制 + 热区**，不做任何设备操作。
    - 真正的「切档」是一次**输入会话切换**（关相机 → 改模式 → 重开 → 新代次），
      需要相机/backend/display 三方协调，接口预留在 `request_camera_profile()`：
      接不上时只写一条 `CAMERA_PROFILE_SWITCH_UNAVAILABLE` checkpoint 并关面板，
      **绝不假装切换成功**。
    - 素材由 `build/make_ui_profile_assets.py` 生成（PIL + 系统中文字体）——
      OpenCV 的 putText 不支持中文，所以中文必须预渲染成 PNG。

坐标系：1280×720，与 `v75_ui_layout.json` 一致。
"""

from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# ---- 布局（绝对坐标）------------------------------------------------------
BAR = (20, 640, 300, 56)          # Keep clear of native512px output ending636.
PANEL = (20, 128, 448, 488)       # Leave the fixed source/FPS strip visible.
CLOSE__v119_profile_ui = (404, 140, 48, 48)
OPT_480 = (36, 256, 416, 84)
OPT_600 = (36, 352, 416, 84)
APPLY = (36, 528, 416, 64)
HINT = (340, 656, 240, 24)
#   切换中的居中卡片（420x140）与它里面的空进度条轨道
BUSY_CARD = (430, 290, 420, 140)
BUSY_TRACK = (470, 352, 340, 16)
# 21版日志切档2.22~2.92秒。沿用附件的1秒快速推进与后续缓进，
# 这只是等待提示；只有新档位画面提交成功才画满。
BUSY_FAST_S = 1.0
BUSY_CAP = 0.95
BUSY_CREEP_PER_S = 0.03

def progress_at(view, now):
    """Visual wait indicator, not a hardware percentage. Pure metadata only."""
    if view.get('complete'):return 1.
    elapsed=max(0.,now-float(view.get('started',now)))
    return min(.99,BUSY_CAP*elapsed/BUSY_FAST_S if elapsed<BUSY_FAST_S
               else BUSY_CAP+BUSY_CREEP_PER_S*(elapsed-BUSY_FAST_S))

PROFILES = ('480P', '600P')

# 素材尺寸断言：素材被改动时立刻报错，而不是画歪
SHAPES = {
    'v119_bar_480p.png': (56, 300, 3), 'v119_bar_600p.png': (56, 300, 3),
    'v119_panel_480p.png': (528, 448, 3), 'v119_panel_600p.png': (528, 448, 3),
    'v119_opt_480p_active.png': (84, 416, 3), 'v119_opt_480p_cand.png': (84, 416, 3),
    'v119_opt_600p_active.png': (84, 416, 3), 'v119_opt_600p_cand.png': (84, 416, 3),
    'v119_apply_480p.png': (64, 416, 3), 'v119_apply_600p.png': (64, 416, 3),
    'v119_apply_busy.png': (64, 416, 3),
    'v119_hint_reloc.png': (30, 420, 3), 'v119_hint_keep.png': (26, 420, 3),
    'v119_hint_apply.png': (24, 240, 3),
    'v119_busy_480p.png': (140, 420, 3), 'v119_busy_600p.png': (140, 420, 3),
    'v119_wait_480p.png': (140,420,3),'v119_wait_600p.png': (140,420,3),
    'v119_frame_timeout.png': (140,420,3),
}


def inside__v119_profile_ui(point, rect):
    return (point is not None and rect[0] <= point[0] < rect[0] + rect[2]
            and rect[1] <= point[1] < rect[1] + rect[3])


def load_assets__v119_profile_ui(assets, root):
    """一次性解码到 assets.profile_parts；运行时不再读盘。"""
    import cv2
    root = Path(root)
    parts = {}
    for name, shape in SHAPES.items():
        image = cv2.imread(str(root / name), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Missing camera profile UI asset ' + name)
        if image.shape != shape:
            raise ValueError('Invalid camera profile asset %s: %s != %s' % (name, image.shape, shape))
        image.setflags(write=False)
        parts[name] = image
    assets.profile_parts = parts
    assets.profile_asset_bytes = sum(p.nbytes for p in parts.values())


def _put(canvas, image, x, y):
    h, w = image.shape[:2]
    if y < 0 or x < 0 or y + h > canvas.shape[0] or x + w > canvas.shape[1]:
        return False
    canvas[y:y + h, x:x + w] = image
    return True


def render_overlay__v119_profile_ui(canvas, view, assets):
    """只由 HDMI owner 调用。view 由 `ProfileUI.publish()` 产出。

    ⚠️ **不在这里判断"是否可见"** —— 可见性由调用方按**当前页面**决定
       （`_show` 里 `view in ('compare','rectified')`）。
       2026-10-29 上板：`publish()` 只在构造时调过一次，那时还在 home，
       `visible=False` 之后再没人刷新 ⇒ **按钮一次都没画出来**。
    """
    if not view:
        return
    parts = assets.profile_parts
    active = view['active']
    _put(canvas, parts['v119_bar_%s.png' % active.lower()], BAR[0], BAR[1])
    if view.get('timeout_notice'):
        _put(canvas,parts['v119_frame_timeout.png'],BUSY_CARD[0],BUSY_CARD[1]);return
    if view.get('busy'):
        #   切换中：居中卡片 + 按【已用时间】推进的进度条。
        # 正常随帧推进，停流期间由现有owner最多10Hz绘制切档UI。
        target = view.get('target') or active
        phase='wait' if view.get('phase')=='waiting_frame' else 'busy'
        _put(canvas, parts['v119_%s_%s.png' % (phase,target.lower())], BUSY_CARD[0], BUSY_CARD[1])
        frac = progress_at(view, time.perf_counter())
        tx, ty, tw, th = BUSY_TRACK
        filled = int(tw * max(0., min(1., frac)))
        if filled > 0:
            canvas[ty + 2:ty + th - 2, tx:tx + filled] = (210, 224, 78)   # ACCENT 的 BGR
        return
    if not view.get('open'):
        return
    x, y, w, h = PANEL
    _put(canvas, parts['v119_panel_%s.png' % active.lower()], x, y)
    for name in PROFILES:
        rect = OPT_480 if name == '480P' else OPT_600
        state = 'active' if name == active else 'cand'
        _put(canvas, parts['v119_opt_%s_%s.png' % (name.lower(), state)], rect[0], rect[1])
    _put(canvas, parts['v119_hint_reloc.png'], x + 16, y + 302)
    _put(canvas, parts['v119_hint_keep.png'], x + 16, y + 340)
    other = '600P' if active == '480P' else '480P'
    label = 'busy' if view.get('busy') else other.lower()
    _put(canvas, parts['v119_apply_%s.png' % label], APPLY[0], APPLY[1])
    _put(canvas, parts['v119_hint_apply.png'], HINT[0], HINT[1])


class ProfileUI:
    """事件驱动：没有常驻循环；只在状态变化时把 view 推给显示层。"""

    def __init__(self, state, display):
        self.state = state
        self.display = display
        self.active = getattr(state, 'camera_profile', None) or '480P'
        self.open = False
        self.busy = False
        self.contact = None
        #   进度条时钟：`apply()` 记起点，`view()` 按已用时间算进度，`applied/failed` 清零。
        self.switch_started = None
        self.switch_target = None
        self.lock=threading.RLock();self.revision=0;self.serial=0
        self.generation=None;self.ready_after=None;self.first_frame_deadline=None
        self.phase='idle';self.completed=False
        display.profile_controller=self
        #   ⚠️ 不需要"吞掉抬起"的机制：按下 `consumed=True` 时 `v75_touch` 根本
        #      不派发抬起（见 `v75_touch.py:170`）。留一个跨接触的标志反而会把
        #      **下一次**触摸的抬起吃掉。
        self.publish()

    # ---- 状态 → 显示 ------------------------------------------------------
    def view(self):
        # Published snapshots never mutate. The renderer advances time only
        # while busy; healthy frames reuse this dictionary without allocation.
        with self.lock:
            return dict(open=self.open,active=self.active,busy=self.busy,target=self.switch_target,
                started=self.switch_started,phase=self.phase,generation=self.generation,
                revision=self.revision,serial=self.serial,complete=self.completed)

    def publish(self):
        self.display.profile_overlay = self.view()

    def request_redraw(self):
        d = self.display
        try:
            d.request_view(d.ui_view, d.ui_generation)
        except Exception:
            pass

    # ---- 面板开关 --------------------------------------------------------
    def show(self):
        with self.lock:
            if self.busy:return
            self.open = True; self.busy = False;self.phase='idle'
            self.switch_target=None;self.switch_started=None;self.revision+=1;self.publish()
        self.request_redraw()
        checkpoint('CAMERA_PROFILE_PANEL_OPEN', active_profile=self.active,
                   available=list(PROFILES), event_only=True)

    def hide(self, reason='user'):
        with self.lock:
            if not self.open:return
            self.open = False; self.busy = False; self.contact = None;self.revision+=1;self.publish()
        self.request_redraw()
        checkpoint('CAMERA_PROFILE_PANEL_CLOSED', active_profile=self.active, reason=reason)

    # ---- 触摸 ------------------------------------------------------------
    def touch(self, event, generation):
        """返回 dict 交给 `v75_ui` 合并；返回 None 表示不归我管。"""
        if self.state.page not in ('compare', 'rectified'):
            return None
        if self.busy:
            # Keep the existing top-left Return available while changing format.
            if inside__v119_profile_ui(event.get('press'),(0,0,180,72)):return None
            return dict(target='camera_profile', consumed=True, reason='camera_profile_busy')
        phase = event.get('phase'); press = event.get('press')
        if self.open:
            if phase == 'cancel':
                self.hide('contact_cancelled')
                return dict(target='camera_profile', consumed=True, reason='camera_profile_cancelled')
            if press is None:
                return None
            target = self._target(press)
            if phase == 'press':
                self.contact = target
                #   ⚠️⚠️ **`consumed` 决定"抬起会不会派发"** —— 见 `v75_touch.py:170`：
                #      `if outcome and outcome.get('consumed'): decision=dict(outcome,...)`
                #      ⇒ 按下时 `consumed=True` 的话，**抬起根本不会回调 on_touch**。
                #      2026-10-29 现场："点了应用没反应"就是这个 —— 应用按钮的按下
                #      返回了 `consumed=True`，`apply()` 一次都没执行。
                #      ⇒ **按下即生效的（关面板/选档）用 True；要等抬起的（应用）必须 False。**
                if target == 'close':
                    self.hide('close_press')
                    return dict(target='camera_profile_close', accepted=True, consumed=True)
                if target in ('opt_480P', 'opt_600P'):
                    return dict(target='camera_profile_' + target, accepted=True, consumed=True,
                                reason='profile_option_press')
                if target == 'apply':
                    #   必须 False：抬起事件要回来才执行 apply()
                    return dict(target='camera_profile_apply', consumed=False, reason='await_release')
                return dict(target='camera_profile_panel', consumed=True, reason='panel_background_press')
            origin = event.get('press_outcome') or {}
            accept = bool(target and origin.get('generation') == generation
                          and origin.get('target') == 'camera_profile_' + str(target)
                          and self._target(event.get('release')) == target
                          and event.get('peak_motion', 0) <= 32)
            if accept and target == 'apply':
                self.apply()
            return dict(target='camera_profile_' + str(target or 'panel'), accepted=accept, consumed=True,
                        reason='camera_profile_apply' if accept and target == 'apply' else 'camera_profile_release')
        # 面板关着：只有按钮能打开
        if phase == 'press':
            if inside__v119_profile_ui(press, BAR):
                self.contact = 'bar'
                return dict(target='camera_profile_open', reason='await_release')
            return None
        origin = event.get('press_outcome') or {}
        if origin.get('generation') == generation and origin.get('target') == 'camera_profile_open':
            if inside__v119_profile_ui(event.get('release'), BAR) and event.get('peak_motion', 0) <= 32:
                self.show(); return dict(target='camera_profile_open', accepted=True, consumed=True,
                                         reason='camera_profile_opened')
            return dict(target='camera_profile_open', consumed=True, reason='camera_profile_open_rejected')
        return None

    def _target(self, point):
        if inside__v119_profile_ui(point, CLOSE__v119_profile_ui):
            return 'close'
        if inside__v119_profile_ui(point, OPT_480):
            return 'opt_480P'
        if inside__v119_profile_ui(point, OPT_600):
            return 'opt_600P'
        if inside__v119_profile_ui(point, APPLY):
            return 'apply'
        return None

    # ---- 应用 ------------------------------------------------------------
    def apply(self):
        """请求切档。**这里绝不改 `active`** —— 只有后端换好之后 `applied()` 才改。"""
        with self.lock:
            if self.busy:return False
            other = '600P' if self.active == '480P' else '480P'
        handler = getattr(self.state, 'request_camera_profile', None)
        if handler is None:
            checkpoint('CAMERA_PROFILE_SWITCH_UNAVAILABLE', requested=other,
                       active_profile=self.active, reason='backend_not_wired',
                       previous_setting_retained=True)
            self.hide('backend_not_wired')
            return False
        # Publish before requesting the new session: the UI owner may begin
        # device preparation immediately after request() wakes it.
        with self.lock:
            self.serial+=1;self.revision+=1;self.open=False;self.busy=True
            self.switch_target=other;self.switch_started=time.perf_counter()
            self.phase='switching';self.generation=None;self.ready_after=None
            self.first_frame_deadline=None;self.completed=False;self.publish()
        if not bool(handler(other)):
            checkpoint('CAMERA_PROFILE_SWITCH_REJECTED', requested=other,
                       active_profile=self.active, reason='request_not_accepted',
                       previous_setting_retained=True)
            self.cancel('rejected')
            return False
        # 请求已受理；设备生效后继续等待实际新画面提交。
        self.request_redraw()
        return True

    def bind_request(self,generation):
        with self.lock:
            if not self.busy:return
            self.generation=int(generation);self.publish()

    def applied(self, name, generation=None):
        """设备参数已经生效；进度仍等待新画面，不碰相机。"""
        if name not in PROFILES:
            raise ValueError('Unknown camera profile ' + str(name))
        with self.lock:
            self.active=name
            if not self.busy or generation!=self.generation:
                self.publish();return False
            self.phase='waiting_frame';self.ready_after=time.perf_counter()
            self.first_frame_deadline=self.ready_after+float(getattr(self.display,'timeout',3.))
            self.publish()
        self.request_redraw()
        checkpoint('CAMERA_PROFILE_APPLIED',active_profile=name,generation=generation,
                   completion='waiting_for_new_profile_frame_submission')
        return True

    def frame_view(self,view,generation,shape,ready,sequence,now):
        """Candidate for THIS canvas; completion is committed only after submit."""
        if not view or not view.get('busy'):return view
        expected=(480,640) if view['target']=='480P' else (600,800)
        with self.lock:
            valid=(self.busy and view['serial']==self.serial and generation==self.generation
                and self.phase=='waiting_frame' and tuple(shape[:2])==expected
                and ready is not None and self.ready_after is not None
                and self.ready_after<=ready<=now+.02 and now-ready<=.5 and sequence is not None and sequence>=0)
        return dict(view,complete=True) if valid else view

    def submitted(self,view,generation,ready,sequence):
        if not view or not view.get('complete'):return False
        with self.lock:
            if not self.busy or view['serial']!=self.serial or generation!=self.generation:return False
            self.busy=False;self.phase='idle';self.completed=False;self.revision+=1
            self.switch_target=None;self.switch_started=None;self.first_frame_deadline=None
            self.publish()
        checkpoint('CAMERA_PROFILE_FIRST_FRAME_SUBMITTED',active_profile=self.active,generation=generation,
            request_serial=view['serial'],camera_sequence=sequence,capture_ready_at=ready,
            physical_scan_time_measured=False)
        return True

    def expire(self,now):
        with self.lock:
            expired=self.busy and self.first_frame_deadline is not None and now>=self.first_frame_deadline
            if expired:
                self.busy=False;self.phase='failed';self.first_frame_deadline=None
                self.revision+=1;self.publish()
        if expired:
            checkpoint('CAMERA_PROFILE_SWITCH_FAILED',active_profile=self.active,
                reason='new_profile_first_frame_timeout',device_configuration_retained=True)
        return expired

    def cancel(self,reason='page_left'):
        with self.lock:
            changed=self.busy or self.open
            self.busy=False;self.open=False;self.contact=None;self.phase='idle'
            self.generation=None;self.switch_target=None;self.switch_started=None
            self.ready_after=None;self.first_frame_deadline=None;self.completed=False
            if changed:self.revision+=1
            self.publish()
        if changed:checkpoint('CAMERA_PROFILE_CANCELLED',active_profile=self.active,reason=reason)

    def failed(self, reason='switch_failed'):
        """换档失败：保留旧档位，退出等待态。"""
        self.cancel(reason);self.request_redraw()
        checkpoint('CAMERA_PROFILE_SWITCH_FAILED', active_profile=self.active,
                   reason=reason, previous_setting_retained=True)


# ======================================================================
# ===== [30/35] v120_sharp =====
# ======================================================================


"""PL stream sharpening. UI publishes a request; the existing P1 owner applies it.

No CPU pixel filter, camera/overlay restart, new frame buffer or polling thread.
The supplied kernel is packet-local; multi-tile frames use explicit bypass.
"""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_WIDTH=512
BYPASS_VERSION=0x53420001

def quantize(level):
    if isinstance(level,bool):raise ValueError('Invalid sharpness')
    value=float(level)
    if not math.isfinite(value) or not 0.<=value<=4.:raise ValueError('Sharpness must be 0..4')
    return int(math.floor(value*10.+.5))

class SharpControl:
    """Atomic immutable requests; completed-output acknowledgement is separate."""
    def __init__(self,folder=None):
        self.path=None if folder is None else Path(folder)/'p11_sharp_settings.json'
        level=0
        if self.path is not None and self.path.is_file():
            try:
                value=json.loads(self.path.read_text(encoding='utf-8'))
                if value.get('format')!='p11-sharp-settings-v1':raise ValueError('Unknown settings format')
                level=quantize(value['level'])
            except (ValueError,KeyError,TypeError,OSError) as exc:
                checkpoint('SHARP_SETTINGS_LOAD_FAILED',error=str(exc)[:200],default_level=0.)
        self.requested=(0,level);self.lock=threading.Lock();self.last_submitted=None
        self.frame_request=self.requested;self.frame_request_at=-float('inf')
        self.save_lock=threading.Lock();self.saved_serial=-1;self.save_request=None;self.writers=[]
    def request(self,tenths):
        if isinstance(tenths,bool) or int(tenths)!=tenths or not 0<=tenths<=40:raise ValueError('Invalid sharpness tenths')
        with self.lock:
            if self.requested[1]==int(tenths):return self.requested
            self.requested=(self.requested[0]+1,int(tenths));request=self.requested
        return request
    def for_frame(self):
        # The existing P1 owner calls once before the frame's first packet.
        # Healthy frames avoid clocks/locks. A drag only replaces one tuple;
        # no intermediate values queue up and no timer/worker touches MMIO.
        if self.requested is self.frame_request:return self.frame_request
        now=time.perf_counter()
        changed=False
        # Only this existing frame owner writes frame_request/frame_request_at.
        # Read the immutable UI tuple atomically; never wait for a save lock.
        if now-self.frame_request_at>=.1:
            self.frame_request=self.requested;self.frame_request_at=now;changed=True
        request=self.frame_request
        if changed:
            checkpoint('SHARP_SETTING_REQUESTED',serial=request[0],level=request[1]/10.,pixel_processing='PL_only',
                camera_restarted=False,applied_on='frame_boundary',latest_only=True,min_interval_s=.1)
        return request
    def finish(self):
        """Gesture finished: persist the final setting, even without a target."""
        with self.lock:
            serial,tenths=self.requested
            if self.path is None or serial<=0 or serial<=self.saved_serial:return
            self.saved_serial=serial;self.save_request=(serial,tenths)
        worker=threading.Thread(target=self._save,args=(serial,tenths),name='p11-sharp-save',daemon=True)
        self.writers=[w for w in self.writers if w.is_alive()];self.writers.append(worker);worker.start()
    def submitted(self,receipt):
        """Called only AFTER this actual rectified frame was submitted to HDMI."""
        if receipt is None or receipt is self.last_submitted:return False
        # An older, genuinely displayed frame remains the actual value while
        # the newest request waits for the next allowed frame boundary.
        if self.last_submitted is not None and receipt['serial']<self.last_submitted['serial']:return False
        if receipt['serial']>self.requested[0]:return False
        self.last_submitted=receipt
        checkpoint('SHARP_FRAME_SUBMITTED',**receipt,physical_scan_time_measured=False)
        return True
    def _save(self,serial,tenths):
        try:
            with self.save_lock:
                if (serial,tenths)!=self.save_request:return
                tmp=self.path.with_suffix('.tmp')
                tmp.write_text(json.dumps(dict(format='p11-sharp-settings-v1',level=tenths/10.),ensure_ascii=False)+'\n',encoding='utf-8')
                with self.lock:
                    if (serial,tenths)!=self.save_request:return
                    tmp.replace(self.path)
        except OSError as exc:checkpoint('SHARP_SETTINGS_SAVE_FAILED',serial=serial,error=str(exc)[:200])
    def close(self):
        for w in self.writers:w.join(1.)

def inspect_sharp_metadata(modules):
    """Use paired XML metadata, never source-comment absolute addresses."""
    expected={'/axis_sharp_0':('xilinx.com:hls:axis_sharp:1.0','C_S_AXI_CONTROL_BASEADDR',0x40030000),
              '/axis_bypass_0':('xilinx.com:module_ref:axis_bypass_bd:1.0','C_BASEADDR',0x40001000)}
    for path,(vlnv,param,address) in expected.items():
        node=modules.get(path)
        if node is None or node.get('VLNV')!=vlnv:raise ValueError('Missing or incorrect sharp IP '+path)
        params={x.get('NAME'):x.get('VALUE') for x in node.findall('./PARAMETERS/PARAMETER')}
        if int(params.get(param,'-1'),0)!=address:raise ValueError('Sharp IP address mismatch '+path)
    def bus(path,name):
        if path not in modules:return None
        node=modules[path].find('./BUSINTERFACES/BUSINTERFACE[@NAME="'+name+'"]')
        return None if node is None else node.get('BUSNAME')
    links=[('/axis_light_0','M_AXIS','/axis_data_fifo_0','S_AXIS'),
           ('/axis_data_fifo_0','M_AXIS','/axis_bypass_0','S_AXIS'),
           ('/axis_bypass_0','SH_AXIS','/axis_sharp_0','s_axis'),
           ('/axis_sharp_0','m_axis','/axis_bypass_0','FS_AXIS'),
           ('/axis_bypass_0','M_AXIS','/axi_dma_0','S_AXIS_S2MM')]
    if '/axis_data_fifo_0' not in modules:raise ValueError('Missing sharp stream FIFO')
    for a,ap,b,bp in links:
        if bus(a,ap) is None or bus(a,ap)!=bus(b,bp):raise ValueError('Sharp stream topology mismatch '+a+'/'+ap)

class SharpDriver:
    def __init__(self,overlay,mmio_factory,control):
        self.control=control;self.frame_receipt=None;self.receipt_key=None
        self.shape=None;self.amount=None;self.route=None;self.in_flight=False;self.check_route=False
        ips=overlay.ip_dict
        def mm(name):
            spec=ips[name];return mmio_factory(int(spec['phys_addr']),int(spec['addr_range']))
        self.core=mm('axis_sharp_0');self.gate=mm('axis_bypass_0')
        if int(self.gate.read(0x04))!=BYPASS_VERSION:raise RuntimeError('Incorrect PL sharp bypass version')
        self.gate.write(0x00,0);self.route=0
        checkpoint('SHARP_BACKEND_READY',kernel='axis_sharp_0',bypass='axis_bypass_0',max_output_width=MAX_WIDTH,
            default_level=control.requested[1]/10.,multi_tile='explicit_hardware_bypass',CPU_fallback=False)
    def begin_frame(self,tiles):
        if self.in_flight:raise RuntimeError('Previous sharp packet has not completed')
        serial,tenths=self.control.for_frame()
        reason='disabled' if tenths==0 else 'multi_tile_bypass' if len(tiles)!=1 else 'PL'
        if reason=='PL':
            x0,y0,x1,y1=tiles[0].box
            if not 0<x1-x0<=MAX_WIDTH or not 0<y1-y0<=65535:reason='output_shape_bypass'
        enabled=reason=='PL';key=(serial,tenths,enabled,reason)
        if key!=self.receipt_key:
            self.receipt_key=key
            self.frame_receipt=dict(serial=serial,tenths=tenths,requested_level=tenths/10.,
                effective_level=tenths/10. if enabled else 0.,enabled=enabled,reason=reason)
            checkpoint('SHARP_ROUTE_SELECTED',**self.frame_receipt)
        return self.frame_receipt
    def prepare_tile(self,tile):
        if self.in_flight:raise RuntimeError('Cannot change an active sharp packet')
        receipt=self.frame_receipt
        if receipt is None:raise RuntimeError('Sharp frame configuration missing')
        route=int(receipt['enabled'])
        if route:
            x0,y0,x1,y1=tile.box;shape=(x1-x0,y1-y0)
            if shape!=self.shape:
                self.core.write(0x10,shape[0]);self.core.write(0x18,shape[1]);self.shape=shape
            a8=(receipt['tenths']*256+5)//10
            if a8!=self.amount:self.core.write(0x20,a8);self.amount=a8
            self.core.write(0x28,1);self.core.write(0x00,1)
            self.in_flight=True
        if route!=self.route:
            self.gate.write(0x00,route);self.route=route;self.check_route=True
    def completed_tile(self):
        # The existing DMA owner calls this only after S2MM completion. Do not
        # sleep or poll: the packet and its output bytes have already drained.
        if self.in_flight:
            status=int(self.core.read(0x00))
            if not(status&6):raise RuntimeError('PL sharp did not finish after DMA completion')
            self.in_flight=False
        if self.check_route:
            if int(self.gate.read(0x14))!=self.route:raise RuntimeError('PL sharp route acknowledgement mismatch')
            self.check_route=False
    def close(self):
        if self.in_flight:raise RuntimeError('Cannot close an active PL sharp packet')
        self.gate.write(0x00,0);self.route=0;self.control.close()


# ======================================================================
# ===== [31/35] v122_light =====
# ======================================================================


"""Zero-image-buffer PL PWL light controls; MMIO belongs to the P1 owner."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
VERSION=0x4c540001

class LightControl(SharpControl):
    def __init__(self,folder=None):
        super().__init__(None)
        self.path=None if folder is None else Path(folder)/'p11_light_settings.json'
        value=0
        if self.path is not None and self.path.is_file():
            try:
                saved=json.loads(self.path.read_text(encoding='utf-8'))
                value=saved['percent']
                if saved.get('format')!='p11-light-settings-v1' or isinstance(value,bool) or int(value)!=value or not 0<=value<=100:
                    raise ValueError('Incorrect light settings')
            except (ValueError,KeyError,TypeError,OSError) as exc:
                value=0;checkpoint('LIGHT_SETTINGS_LOAD_FAILED',error=str(exc)[:200])
        self.requested=(0,int(value));self.frame_request=self.requested
    def request(self,percent):
        if isinstance(percent,bool) or int(percent)!=percent or not 0<=percent<=100:raise ValueError('Light percent must be0..100')
        with self.lock:
            if self.requested[1]!=int(percent):self.requested=(self.requested[0]+1,int(percent))
            return self.requested
    def for_frame(self):
        if self.requested is self.frame_request:return self.frame_request
        now=time.perf_counter()
        if now-self.frame_request_at>=.1:
            self.frame_request=self.requested;self.frame_request_at=now
            checkpoint('LIGHT_SETTING_REQUESTED',serial=self.frame_request[0],percent=self.frame_request[1],
                applied_on='frame_boundary',latest_only=True,min_interval_s=.1)
        return self.frame_request
    def submitted(self,receipt):
        if receipt is None or receipt is self.last_submitted:return False
        if self.last_submitted is not None and receipt['serial']<self.last_submitted['serial']:return False
        if receipt['serial']>self.requested[0]:return False
        self.last_submitted=receipt;checkpoint('LIGHT_FRAME_SUBMITTED',**receipt,physical_scan_time_measured=False);return True
    def _save(self,serial,percent):
        try:
            with self.save_lock:
                if (serial,percent)!=self.save_request:return
                tmp=self.path.with_suffix('.tmp')
                tmp.write_text(json.dumps(dict(format='p11-light-settings-v1',percent=percent))+'\n',encoding='utf-8')
                with self.lock:
                    if (serial,percent)==self.save_request:tmp.replace(self.path)
        except OSError as exc:checkpoint('LIGHT_SETTINGS_SAVE_FAILED',error=str(exc)[:200])

class LightDriver:
    def __init__(self,overlay,mmio_factory,control):
        self.control=control
        ip=overlay.ip_dict['axis_light_0']
        if int(ip['phys_addr'])!=0x40002000 or int(ip['addr_range'])<64:raise RuntimeError('PL light address mismatch')
        self.mmio=mmio_factory(int(ip['phys_addr']),int(ip['addr_range']))
        if int(self.mmio.read(4))!=VERSION:raise RuntimeError('PL light version mismatch')
        self.mmio.write(0,0);self.q8=0;self.key=None;self.receipt=None;self.changed=False
        checkpoint('LIGHT_BACKEND_READY',version=VERSION,pixel_processing='PL_PWL',image_buffer=False,
            requested_percent=control.requested[1],CPU_pixel_fallback=False)
    def begin_frame(self,tiles):
        request=self.control.for_frame()
        if self.key is None and self.control.frame_request_at==-float('inf'):
            self.control.frame_request_at=time.perf_counter()
        if request is not self.key:
            self.key=request;serial,percent=request;q8=(percent*256+50)//100
            if q8!=self.q8:
                self.mmio.write(0,q8)
                if int(self.mmio.read(0))!=q8:raise RuntimeError('PL light setting readback mismatch')
                self.q8=q8;self.changed=True
            self.receipt=dict(serial=serial,percent=percent,q8=q8,enabled=percent>0)
        return self.receipt
    def completed_frame(self):
        if self.changed:
            if int(self.mmio.read(8))!=self.q8:raise RuntimeError('PL light active parameter mismatch')
            self.changed=False
    def close(self):
        self.control.close();self.mmio.write(0,0)

def inspect_light_metadata(modules):
    node=modules.get('/axis_light_0')
    if node is None or node.get('VLNV')!='xilinx.com:module_ref:axis_light27:1.0':raise ValueError('Missing PL light IP')
    params={p.get('NAME'):p.get('VALUE') for p in node.findall('./PARAMETERS/PARAMETER')}
    if int(params.get('C_BASEADDR','-1'),0)!=0x40002000:raise ValueError('PL light address mismatch')
    for name in ('aclk','aresetn'):
        a=node.find('./PORTS/PORT[@NAME="'+name+'"]');b=modules['/remap'].find('./PORTS/PORT[@NAME="'+name+'"]')
        if a is None or b is None or a.get('SIGNAME')!=b.get('SIGNAME'):raise ValueError('PL light clock/reset mismatch')
    def bus(path,name):
        n=modules[path].find('./BUSINTERFACES/BUSINTERFACE[@NAME="'+name+'"]')
        return None if n is None else n.get('BUSNAME')
    for a,ap,b,bp in [('/remap','m_axis','/axis_light_0','S_AXIS'),('/axis_light_0','M_AXIS','/axis_data_fifo_0','S_AXIS')]:
        if bus(a,ap) is None or bus(a,ap)!=bus(b,bp):raise ValueError('PL light stream topology mismatch')


# ======================================================================
# ===== [32/35] v120_image_settings =====
# ======================================================================


"""Left settings panel. Profile22's switch/first-frame lifecycle is inherited."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CLOSE__v120_image_settings=(404,140,48,48)
TABS={'resolution':(36,192,128,48),'sharp':(180,192,128,48),'light':(324,192,128,48)}
LIGHT_PRESETS=(0,20,40,60,80,100)
PROFILE_OPTIONS={'480P':(36,256,416,84),'600P':(36,352,416,84)}
PRESETS=(0,10,15,20,30,40)
SLIDER=(36,454,416,64)
SLIDER_START=60;SLIDER_END=428

def load_assets__v120_image_settings(assets,root):
    import cv2
    root=Path(root);spec=json.loads((root/'v120_settings_atlas.json').read_text(encoding='utf-8'))
    atlas=cv2.imread(str(root/'v120_settings_atlas.png'),cv2.IMREAD_COLOR)
    if atlas is None or list(atlas.shape)!=spec['shape']:raise ValueError('Incorrect settings atlas')
    assets.settings_parts={}
    for name,(x,y,w,h) in spec['parts'].items():
        if min(x,y)<0 or min(w,h)<=0 or x+w>atlas.shape[1] or y+h>atlas.shape[0]:raise ValueError('Settings atlas rectangle invalid')
        part=atlas[y:y+h,x:x+w];part.flags.writeable=False;assets.settings_parts[name]=part
    assets.settings_atlas=atlas
    assets.settings_footers={}

def render_overlay__v120_image_settings(canvas,view,assets):
    if not view or 'settings_tab' not in view:return render_overlay__v119_profile_ui(canvas,view,assets)
    parts=assets.settings_parts
    if view.get('busy') or view.get('timeout_notice'):render_overlay__v119_profile_ui(canvas,view,assets)
    _put(canvas,parts['bar_'+view['active']],BAR[0],BAR[1])
    # Compose this tiny status patch only when its VALUE changes. Healthy
    # frames do one cached copy, without rebuilding text or UI pixel arrays.
    key=(view['sharp_requested'],view['light_requested']);footer=assets.settings_footers.get(key)
    if footer is None:
        import numpy as np
        footer=np.empty((32,254,3),np.uint8);footer[:]=(18,13,8)
        _put(footer,parts['footer_label'],0,0)
        _put(footer,parts['footer_number_'+str(key[0])],52,0)
        _put(footer,parts['light_footer_label'],134,0)
        _put(footer,parts['light_number_'+str(key[1])],186,0)
        footer.flags.writeable=False
        if len(assets.settings_footers)>=8:assets.settings_footers.clear()
        assets.settings_footers[key]=footer
    _put(canvas,footer,340,652)
    if not view.get('open') or view.get('busy') or view.get('timeout_notice'):return
    tab=view['settings_tab'];_put(canvas,parts['panel_'+tab],PANEL[0],PANEL[1])
    if tab=='resolution':
        for name,rect in PROFILE_OPTIONS.items():
            selected=name==view['profile_candidate']
            _put(canvas,parts['option_'+name+('_on' if selected else '_off')],rect[0],rect[1])
        _put(canvas,parts['profile_apply_'+('same' if view['profile_candidate']==view['active'] else view['profile_candidate'])],APPLY[0],528)
        return
    effect='light' if tab=='light' else 'sharp';number='light_number_' if tab=='light' else 'number_'
    presets=LIGHT_PRESETS if tab=='light' else PRESETS;maximum=100 if tab=='light' else 40
    actual=view[effect+'_actual'];candidate=view[effect+'_candidate']
    _put(canvas,parts[number+str(actual)],104,246)
    _put(canvas,parts[number+str(candidate)],324,246)
    for i,val in enumerate(presets):
        _put(canvas,parts[('light_preset_' if tab=='light' else 'preset_')+str(val)+('_on' if val==candidate else '_off')],36+(i%3)*144,288+(i//3)*64)
    _put(canvas,parts[number+str(candidate)],384,414)
    import cv2
    canvas[474:483,60:429]=(107,89,62)
    x=SLIDER_START+int((SLIDER_END-SLIDER_START)*candidate/maximum+.5)
    if x>SLIDER_START:canvas[474:483,SLIDER_START:x]=(235,219,85)
    cv2.circle(canvas,(x,478),16,(235,219,85),-1)
    cv2.circle(canvas,(x,478),16,(245,237,229),2)

class ImageSettingsUI(ProfileUI):
    def __init__(self,state,display):
        self.sharp=getattr(display,'sharp_control',None) or SharpControl()
        self.light=getattr(display,'light_control',None) or LightControl()
        self.light_candidate=self.light.requested[1]
        self.tab='resolution';self.profile_candidate=getattr(state,'camera_profile',None) or '480P'
        self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.drag=None
        super().__init__(state,display)
    def view(self):
        with self.lock:
            v=super().view();request=self.sharp.requested;receipt=self.sharp.last_submitted
            current=receipt is not None and receipt['serial']==request[0] and receipt['tenths']==request[1]
            status=('off' if request[1]==0 else 'waiting') if not current else (
                'PL' if receipt['enabled'] else 'multi' if receipt['reason']=='multi_tile_bypass' else
                'shape' if receipt['reason']=='output_shape_bypass' else 'off')
            v.update(settings_tab=self.tab,profile_candidate=self.profile_candidate,sharp_candidate=self.sharp_candidate,
                sharp_requested=request[1],sharp_actual=receipt['tenths'] if receipt is not None and receipt['enabled'] else 0,
                sharp_status=status)
            light_receipt=self.light.last_submitted
            v.update(light_candidate=self.light_candidate,light_requested=self.light.requested[1],
                light_actual=light_receipt['percent'] if light_receipt is not None else 0)
            return v
    def show(self):
        with self.lock:
            self.profile_candidate=self.active;self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.drag=None
        super().show()
    def hide(self,reason='user'):
        with self.lock:self.drag=None;self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.profile_candidate=self.active
        super().hide(reason)
    def cancel(self,reason='page_left'):
        with self.lock:self.drag=None;self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.profile_candidate=self.active
        super().cancel(reason)
    def _target(self,point):
        if inside__v119_profile_ui(point,CLOSE__v120_image_settings):return 'close'
        for tab,rect in TABS.items():
            if inside__v119_profile_ui(point,rect):return 'tab_'+tab
        if self.tab=='resolution' and inside__v119_profile_ui(point,(36,528,416,64)):return 'apply'
        if self.tab=='resolution':
            for name,rect in PROFILE_OPTIONS.items():
                if inside__v119_profile_ui(point,rect):return 'profile_'+name
        else:
            for i,val in enumerate(LIGHT_PRESETS if self.tab=='light' else PRESETS):
                if inside__v119_profile_ui(point,(36+(i%3)*144,288+(i//3)*64,128,56)):return 'preset_'+str(val)
            if inside__v119_profile_ui(point,SLIDER):return 'slider'
        return None
    def _slider(self,point):
        if point is None:return
        maximum=100 if self.tab=='light' else 40
        value=max(0,min(maximum,int((point[0]-SLIDER_START)*maximum/(SLIDER_END-SLIDER_START)+.5)))
        if self.tab=='light':self.light_candidate=value;self.light.request(value)
        else:self.sharp_candidate=value;self.sharp.request(value)
        self.revision+=1;self.publish()
        # Live HDMI frames render the small dirty UI; never submit a new full
        # frame or reconfigure a camera for each move event.
    def touch(self,event,generation):
        if self.state.page not in ('compare','rectified'):return None
        if self.busy:return super().touch(event,generation)
        phase=event.get('phase');press=event.get('press');origin=event.get('press_outcome') or {}
        with self.lock:
            if phase=='cancel':
                if self.drag is not None or self.open:
                    self.hide('contact_cancelled');return dict(target='settings_cancel',consumed=True)
                return None
            if self.drag is not None:
                valid=(self.drag==(generation,event.get('contact_id')) and origin.get('target')=='settings_slider'
                    and origin.get('generation')==generation and origin.get('page')==self.state.page)
                if not valid:self.drag=None;return dict(target='settings_slider',consumed=True,reason='stale_drag')
                if phase in ('move','release'):
                    self._slider(event.get('position') if phase=='move' else event.get('release'))
                    if phase=='release':self.drag=None;(self.light if self.tab=='light' else self.sharp).finish()
                    return dict(target='settings_slider',consumed=phase=='release',track_moves=True,accepted=True)
                return dict(target='settings_slider',track_moves=True,consumed=False)
            if not self.open:return super().touch(event,generation)
            # Return remains accessible; state.request() performs cancellation.
            if inside__v119_profile_ui(press,(0,0,180,72)):return None
            if phase=='press':
                target=self._target(press)
                if target=='close' or not inside__v119_profile_ui(press,PANEL):
                    self.hide('close' if target=='close' else 'outside')
                    return dict(target='settings_close',consumed=True,accepted=True)
                if target=='slider':
                    self.drag=(generation,event.get('contact_id'));self._slider(press)
                    return dict(target='settings_slider',consumed=False,track_moves=True,accepted=True)
                if target is None:return dict(target='settings_panel',consumed=True)
                return dict(target='settings_'+target,consumed=False,reason='await_release')
            target=self._target(press)
            valid=(phase=='release' and target is not None and origin.get('target')=='settings_'+target
                and origin.get('generation')==generation and origin.get('page')==self.state.page
                and self._target(event.get('release'))==target and event.get('peak_motion',0)<=32)
            if not valid:return dict(target='settings_release',consumed=True,accepted=False)
            if target.startswith('tab_'):self.tab=target[4:]
            elif target.startswith('profile_'):self.profile_candidate=target[8:]
            elif target.startswith('preset_'):
                value=int(target[7:])
                if self.tab=='light':self.light_candidate=value;self.light.request(value);self.light.finish()
                else:self.sharp_candidate=value;self.sharp.request(value);self.sharp.finish()
            elif target=='apply':return dict(target='settings_apply',consumed=True,accepted=self.apply())
            self.revision+=1;self.publish()
            return dict(target='settings_'+target,consumed=True,accepted=True)
    def apply(self):
        with self.lock:
            if self.busy:return False
            if self.tab!='resolution':
                return False
            if self.profile_candidate==self.active:return False
        return super().apply()
    def sharp_submitted(self,meta):
        sharp_receipt=meta.get('sharp_receipt');light_receipt=meta.get('light_receipt')
        changed=sharp_receipt is not None and self.sharp.submitted(sharp_receipt)
        changed=(light_receipt is not None and self.light.submitted(light_receipt)) or changed
        if changed:
            with self.lock:self.revision+=1;self.publish()


# ======================================================================
# ===== [33/35] v121_selection =====
# ======================================================================


"""Event-only target selection. No camera, DMA or inference worker ownership."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def can_select(manual=False,ai=False):
    return not bool(manual) or bool(ai)

def source_point(point,rect,shape):
    x,y,w,h=rect;px,py=map(float,point);sh,sw=shape[:2]
    if w<=0 or h<=0 or not (x<=px<x+w and y<=py<y+h):return None
    return (min(sw-1.,(px-x)*sw/w),min(sh-1.,(py-y)*sh/h))

def _gray(image):
    if image.ndim==2:g=image
    elif image.shape[2]==2:g=image[:,:,0]
    else:g=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    scale=min(1.,320./max(g.shape));size=(max(1,round(g.shape[1]*scale)),max(1,round(g.shape[0]*scale)))
    return cv2.resize(g,size,interpolation=cv2.INTER_AREA),np.array([size[0]/image.shape[1],size[1]/image.shape[0]],np.float32)

def map_point(selection,image,sequence=None):
    """One bounded source-to-current mapping; normalized pixels aren't motion."""
    point=np.asarray(selection['point'],np.float32);old=selection['image']
    if old.shape!=image.shape:raise ValueError('点选后输入尺寸已改变，请重新点选')
    if np.shares_memory(old,image):return tuple(map(float,point)),'same_source'
    a,scale=_gray(old);b,_=_gray(image)
    difference=cv2.absdiff(a,b)
    if float(difference.max())<=10. and float(difference.mean())<=1.5:
        return tuple(map(float,point)),'static_image'
    p=point*scale;h,w=a.shape
    radius=max(40,int(min(h,w)*.28));mask=np.zeros_like(a)
    cv2.rectangle(mask,(max(0,int(p[0])-radius),max(0,int(p[1])-radius)),
        (min(w-1,int(p[0])+radius),min(h-1,int(p[1])+radius)),255,-1)
    features=cv2.goodFeaturesToTrack(a,64,.01,5,mask=mask,blockSize=5)
    if features is None or len(features)<6:raise ValueError('点选目标移动后无法可靠对齐，请重新点选')
    nxt,status,_=cv2.calcOpticalFlowPyrLK(a,b,features,None,winSize=(21,21),maxLevel=3)
    if nxt is None:raise ValueError('点选位置对齐失败')
    back,back_status,_=cv2.calcOpticalFlowPyrLK(b,a,nxt,None,winSize=(21,21),maxLevel=3)
    if back is None:raise ValueError('点选位置反向对齐失败')
    keep=(status.ravel()!=0)&(back_status.ravel()!=0)&(np.linalg.norm(back-features,axis=2).ravel()<=1.5)
    before=features.reshape(-1,2)[keep];after=nxt.reshape(-1,2)[keep]
    if len(before)<6:raise ValueError('点选目标对应点不足')
    matrix,inliers=cv2.estimateAffinePartial2D(before,after,method=cv2.RANSAC,ransacReprojThreshold=2.,maxIters=300)
    if matrix is None or inliers is None or int(inliers.sum())<6:raise ValueError('点选目标运动不一致')
    chosen=before[inliers.ravel()!=0]
    if cv2.pointPolygonTest(cv2.convexHull(chosen),tuple(map(float,p)),True)<-12.:
        raise ValueError('点选位置缺少邻近运动支持')
    moved=(matrix[:,:2]@p+matrix[:,2])/scale
    if not np.isfinite(moved).all() or not (0<=moved[0]<old.shape[1] and 0<=moved[1]<old.shape[0]):
        raise ValueError('点选目标已离开画面')
    return tuple(map(float,moved)),'local_FB_affine'

def proof(selection,point,sequence,method,**detail):
    return dict(request_id=selection['request_id'],single_target=True,source_sequence=int(sequence),
        selected_point=list(map(float,point)),mapping=method,**detail)

def components(binary):
    """Reuse the existing shape gates on each isolated component, never largest again."""
    from ai import quad_from_mask as quad_from_mask
    n,labels,stats,_=cv2.connectedComponentsWithStats(np.asarray(binary,np.uint8),8)
    result=[]
    for i in range(1,n):
        if not binary.size*.02<=int(stats[i,cv2.CC_STAT_AREA])<=binary.size*.90:continue
        component=(labels==i)
        q,fit=quad_from_mask(component)
        if q is not None:result.append(dict(label=i,quad=q,fit=float(fit),component=component))
    return result,labels

def select_mask(binary,context=None,source=None):
    """Existing mask only. At most one low-res split and one exterior proof."""
    items,labels=components(binary);point=None if context is None else context['point']
    if not items:return None,0.,dict(reason='no_plane')
    if point is not None:
        sh,sw=context['source_shape'][:2]
        mp=(float(point[0])*binary.shape[1]/sw,float(point[1])*binary.shape[0]/sh)
        px,py=map(int,mp)
        if not (0<=py<binary.shape[0] and 0<=px<binary.shape[1]):return None,0.,dict(reason='point_outside')
        chosen=[it for it in items if labels[py,px]==it['label']]
        if len(chosen)!=1:return None,0.,dict(reason='clicked_component_missing',candidate_count=len(items))
        item=chosen[0]
    elif len(items)>1:
        return None,0.,dict(reason='multiple_targets',candidate_count=len(items))
    else:item=items[0];mp=None
    # Small opening proposes bridge separation only at AI completion, not on
    # tracking frames. Never replace the original component unconditionally.
    opened=cv2.morphologyEx(item['component'].astype(np.uint8),cv2.MORPH_OPEN,np.ones((7,7),np.uint8))
    parts,_=components(opened)
    if len(parts)>1:
        if mp is None:return None,0.,dict(reason='merged_targets',candidate_count=len(parts))
        selected=[it for it in parts if cv2.pointPolygonTest(it['quad'],mp,True)>=0.]
        if len(selected)!=1 or source is None:return None,0.,dict(reason='merged_targets',candidate_count=len(parts))
        part=selected[0];q=part['quad']*np.array([source.shape[1]/binary.shape[1],source.shape[0]/binary.shape[0]],np.float32)
        try:
            from tracking import prove_target as prove_target
            checked,detail=prove_target(source,q,int(context.get('detection_limit',640)),int(context.get('tracking_limit',320)),source,
                check=context.get('check'))
            checked=np.asarray(checked,np.float32)
            if cv2.pointPolygonTest(checked,tuple(map(float,point)),True)<0:raise ValueError('split excluded tap')
            intersection=cv2.intersectConvexConvex(q,checked)[0]
            union=abs(cv2.contourArea(q))+abs(cv2.contourArea(checked))-intersection
            if intersection/max(1.,union)<.70:raise ValueError('physical proof changed split target')
            # Source pixels, converted back once for the ordinary finish scaler.
            q=checked/np.array([source.shape[1]/binary.shape[1],source.shape[0]/binary.shape[0]],np.float32)
        except (ValueError,cv2.error) as exc:
            return None,0.,dict(reason='merged_edges_unproved',candidate_count=len(parts),detail=str(exc)[:160])
        return q,part['fit'],dict(reason='clicked_split',candidate_count=len(parts),component=part['label'],physical_split_proved=True)
    return item['quad'],item['fit'],dict(reason='clicked_component' if mp is not None else 'single_component',
        candidate_count=len(items),component=item['label'],mask_point=mp,physical_split_proved=False)


# ======================================================================
# ===== [34/35] v121_target_switch =====
# ======================================================================


"""One event transaction over live scanout; no frozen canvas or device calls."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class TargetSwitch:
    def __init__(self,display,on_frozen=None,point=None,request_id=None):
        self.display=display;self.generation=display.ui_generation;self.point=point;self.request_id=request_id
        self.previous=display.__dict__.get('_show');self.original=display._show
        self.phase='prepare';self.used_fallback=False;self.active=True;self.frozen=None
        self.started=time.perf_counter();self.handler=self.show
    def restore(self):
        d=self.display
        with d.condition:
            self.active=False
            if getattr(d,'target_switch',None) is self:
                d.target_switch=None
                if d.__dict__.get('_show') is self.handler:
                    if self.previous is None:del d._show
                    else:d._show=self.previous
    def retarget_locked(self,generation):
        if not self.active:return False
        self.generation=int(generation);return True
    def set_phase_locked(self,phase):
        self.phase=phase;self.used_fallback|=phase in ('miss','fallback')
    def show(self,raw,out,meta):
        if not self.active or int(meta.get('ui_generation',-1))!=self.generation:return False
        d=self.display;proof=meta.get('target_selection_proof') or {}
        selected=(out is not None and meta.get('state')=='CURRENT' and proof.get('request_id')==self.request_id
            and proof.get('single_target') is True and proof.get('current_aligned') is True)
        failed=meta.get('target_selection_failed')==self.request_id
        if selected:
            self.phase='display';d.set_target_notice('selected',self.generation)
        elif failed:d.set_target_notice('unconfirmed',self.generation)
        # The existing owner composes and submits every fresh raw/output frame.
        # Never acquire/copy/replay a complete old HDMI canvas here.
        shown=self.original(raw,out,meta)
        if shown and (selected or failed):
            checkpoint('UI_TARGET_SWITCH_PRESENTED',generation=self.generation,request_id=self.request_id,
                result='selected_single_target' if selected else 'selection_failed',selection_proof=proof or None,
                semantic_identity_proven=False,request_to_submit_s=time.perf_counter()-self.started,
                physical_scan_time_measured=False,live_preview=True,frozen_frame_released=False,event_only=True)
            self.restore()
        return shown
    def render(self):return False


# ======================================================================
# ===== [35/35] v123_live_ui =====
# ======================================================================


"""Cached live source/FPS/progress. Only the HDMI owner paints these pixels.

No runtime fonts, image analysis, devices, timers or additional scanout writer.
The FPS receipt is recorded only after a successful new corrected submission.
"""
from core import RELEASE_ID as RELEASE_ID

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
INFO=(0,72,1280,52)
SOURCE=(20,72,202,52)
PROGRESS=(248,72,694,52)
FPS=(980,72,288,52)

def load_assets__v123_live_ui(assets,root):
    root=Path(root)
    spec=json.loads((root/'v123_live_ui.json').read_text(encoding='utf-8'))
    atlas=cv2.imdecode(np.frombuffer((root/'v123_live_ui.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if atlas is None or list(atlas.shape)!=spec['shape']:raise ValueError('Invalid live UI atlas')
    parts={}
    for name,(x,y,w,h) in spec['parts'].items():
        if min(x,y)<0 or min(w,h)<=0 or x+w>atlas.shape[1] or y+h>atlas.shape[0]:
            raise ValueError('Invalid live UI tile '+name)
        part=atlas[y:y+h,x:x+w];part.flags.writeable=False;parts[name]=part
    atlas.flags.writeable=False
    assets.live_ui_parts=parts
    assets.live_ui_spec=spec

class OutputRate:
    """Unique corrected frame receipts / fixed3s, including true manual.

    Existing CURRENT-only diagnostics retain their old definitions.
    """
    def __init__(self):
        self.times=deque();self.generation=None;self.last_sequence=None
    def observe(self,meta,when,valid):
        generation=meta.get('ui_generation')
        if generation!=self.generation:
            self.times.clear();self.last_sequence=None;self.generation=generation
        if not valid or meta.get('preview_only') or meta.get('inspection_redraw') or meta.get('frozen_output'):return False
        sequence=meta.get('camera_sequence')
        if sequence is None or sequence<0 or self.last_sequence is not None and sequence<=self.last_sequence:return False
        self.last_sequence=sequence;self.times.append(when)
        self.fps(when)
        return True
    def fps(self,now):
        while self.times and self.times[0]<=now-3.:self.times.popleft()
        return len(self.times)/3.

def source_key(meta,has_output):
    origin=meta.get('correction_origin')
    if origin not in ('AUTO','AI','MANUAL'):
        origin='MANUAL' if meta.get('manual_tracking') or meta.get('admission_mode')=='manual' else 'AUTO'
    if has_output:return origin
    if meta.get('hybrid_phase')=='EMPTY_WAIT':return 'EMPTY'
    return origin+'_SEARCH'

def progress_key(display,meta,has_output):
    """Metadata snapshot only; no pixels or frontend mutation."""
    with display.condition:
        switch=getattr(display,'target_switch',None)
        if switch is not None and switch.active and switch.generation==meta.get('ui_generation'):
            proof=meta.get('target_selection_proof') or {}
            if meta.get('target_selection_failed')==switch.request_id:return 'failed'
            if (has_output and meta.get('state')=='CURRENT' and proof.get('request_id')==switch.request_id
                    and proof.get('single_target') is True and proof.get('current_aligned') is True):return 'display'
            phase=meta.get('hybrid_phase','')
            if phase=='AI_CONFIRM':return 'verify'
            if phase in ('AI_LOADING','AI_INFER'):return 'ai'
            return {'prepare':'prepare','edges':'auto','verify':'verify','display':'verify',
                    'miss':'ai','fallback':'ai'}.get(switch.phase,'prepare')
        controller=getattr(display,'page_feedback',None)
        load=getattr(controller,'loading',None)
        if load is not None and load.get('generation')==meta.get('ui_generation') and load.get('until')=='output':
            if has_output:return 'blank'
            phase=meta.get('hybrid_phase','')
            if phase=='AI_CONFIRM':return 'verify'
            if phase in ('AI_LOADING','AI_INFER'):return 'ai'
            return {'prepare':'prepare','search':'auto','verify':'verify','display':'verify',
                    'layout':'prepare','snapshot':'prepare'}.get(load.get('stage'),'blank')
        notice=getattr(display,'target_notice','idle')
    return {'unconfirmed':'failed','not_covered':'failed','multiple':'multiple','current':'current'}.get(notice,'blank')

class LiveUI:
    def __init__(self):
        self.rate=OutputRate();self.tokens={};self.number=None;self.number_at=-float('inf');self.number_patch=None
    def _number(self,parts,has_output,now):
        if has_output and self.rate.last_sequence is not None:
            if self.number not in (None,'--') and now-self.number_at<.1:return self.number,self.number_patch
            value='%.1f'%self.rate.fps(now)
        else:value='--'
        self.number_at=now
        if value!=self.number:
            patch=parts['fps_base'].copy();x=278
            for char in reversed(value):
                tile=parts['digit_'+char];x-=tile.shape[1]
                patch[:,x:x+tile.shape[1]]=tile
            patch.flags.writeable=False
            self.number_patch=patch;self.number=value
        return self.number,self.number_patch
    def paint(self,canvas,assets,meta,has_output,display,now,address,force=False):
        parts=assets.live_ui_parts
        if self.rate.generation!=meta.get('ui_generation'):
            self.rate.observe(meta,now,False)
            self.number=None;self.number_at=-float('inf')
        source=source_key(meta,has_output);progress=progress_key(display,meta,has_output)
        number,patch=self._number(parts,has_output,now)
        token=(meta.get('ui_generation'),source,progress,number)
        previous=self.tokens.get(address)
        if force or previous is None or previous[0]!=token[0]:
            canvas[72:124]=parts['info_base']
            previous=None
        if previous is None or previous[1]!=source:canvas[72:124,20:222]=parts['source_'+source]
        if previous is None or previous[2]!=progress:canvas[72:124,248:942]=parts['progress_'+progress]
        if previous is None or previous[3]!=number:canvas[72:124,980:1268]=patch
        self.tokens[address]=token
        if len(self.tokens)>32:self.tokens={address:token}
        return self.rate.fps(now)
