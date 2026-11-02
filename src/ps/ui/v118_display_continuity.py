"""Original owner remaps fresh preview pixels while prepare is late; no tracker/copy."""
from pathlib import Path
import hashlib,threading,time
from run_logging import checkpoint
from p11_contract import RELEASE_ID
from v116_continuity import mark_continuity
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
        from v64_camera_hdmi import FrameJob
        from v79_acquire import OwnedFrame
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
