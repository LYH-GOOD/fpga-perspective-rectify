"""One event transaction over live scanout; no frozen canvas or device calls."""
from pathlib import Path
import hashlib,time
from p11_contract import RELEASE_ID
from run_logging import checkpoint
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
