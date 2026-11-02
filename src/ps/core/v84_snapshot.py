"""One immutable ordinary-RAM still source; no camera or display leases."""
from pathlib import Path
from dataclasses import dataclass
import hashlib,time
import numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
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
        from v79_acquire import OwnedFrame
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
        from v102_ai_selection import select_frame
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
                from v75_ui import UIReturnRequested
                raise UIReturnRequested()
        with display.condition:display.condition.wait(.10)
