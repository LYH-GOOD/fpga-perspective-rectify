"""Latest-only ordinary-RAM preview; capture remains the sole MMAP owner.

Prepared frames publish their existing immutable snapshot. Capture only makes
a fallback snapshot when that producer has stopped supplying fresh previews.
No camera.take(), HDMI submission, CMA lease or unbounded queue lives here.
"""
from pathlib import Path
import hashlib,threading,time
import numpy as np
from v115_pair_display import PairDisplayState
from p11_contract import RELEASE_ID
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
