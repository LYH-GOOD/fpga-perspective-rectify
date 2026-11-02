"""Owner-only stream handoff for every UI mode; no live-frame hooks."""
from pathlib import Path
from dataclasses import dataclass
import hashlib,threading,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]
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
                from v113_live_preview import bind_preview
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
            from v31_camera import CameraSource
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
            _RETAINED.append(item);raise
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
