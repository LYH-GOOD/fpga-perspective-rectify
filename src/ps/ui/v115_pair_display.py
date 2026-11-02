"""Metadata-only completed-pair clock. Never blocks capture or owns pixels."""
from pathlib import Path
from collections import deque
import hashlib,statistics,threading
from p11_contract import RELEASE_ID
from v116_continuity import valid_continuity
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
