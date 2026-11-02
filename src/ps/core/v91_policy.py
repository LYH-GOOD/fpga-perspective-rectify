"""Optional plan-probe backoff only; never suppress a current hardware proof."""
from pathlib import Path
import hashlib
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class MergeProbeBackoff:
    def __init__(self):
        self.failures=0;self.next_at=0.;self.reference=None;self.topology=None;self.delay=1.;self.deferred=0

    def ready(self,now,quad,boxes,stable):
        if not boxes or len(boxes)<=1:return False
        topology=tuple(tuple(b) for b in boxes);q=np.asarray(quad,np.float32)
        moved=self.reference is not None and float(np.max(np.linalg.norm(q-self.reference,axis=1)))>4.
        if topology!=self.topology or moved:
            # A changing target must not reset a failed probe into a new
            # immediate probe on every small-motion frame. Re-evaluate after
            # one second of this geometry; the first topology may probe now.
            self.next_at=now+1. if self.reference is not None else 0.
            self.failures=0;self.delay=1.;self.topology=topology;self.reference=q.copy()
        if not stable:return False
        if now<self.next_at:self.deferred+=1;return False
        return True

    def observe(self,now,quad,boxes,requested,detail):
        if not requested:return
        attempted=bool(detail.get('merge_probe_attempts'));accepted=bool(detail.get('merge_probe_accepted'))
        if attempted:
            self.failures=0 if accepted else min(3,self.failures+1)
            self.delay=1. if accepted else float(min(8,2**self.failures))
        else:self.delay=8.  # No valid adjacent pair: do not enter legacy every frame.
        self.next_at=now+self.delay;self.reference=np.asarray(quad,np.float32).copy()
        self.topology=tuple(tuple(b) for b in boxes)

    def summary(self):
        return dict(merge_probe_failure_streak=self.failures,merge_probe_retry_s=self.delay,
            merge_probe_deferred_frames=self.deferred,merge_probe_backoff_only=True,
            current_packet_and_rowproof_skipped=False)
