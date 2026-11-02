"""Small geometry-only display channel; never grants correction authority."""
from pathlib import Path
from collections import namedtuple
import hashlib,math,threading
from p11_contract import RELEASE_ID
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
