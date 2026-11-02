"""Finite ordinary-RAM display pause; never geometry, DMA or valid FPS proof."""
from pathlib import Path
import hashlib
import numpy as np
from p11_contract import RELEASE_ID
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
