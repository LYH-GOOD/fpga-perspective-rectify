"""Blocking Linux absolute-touch reader; no graphics/device ownership."""
from pathlib import Path
from contextvars import copy_context
import errno,fcntl,glob,hashlib,os,select,struct,threading,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
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
