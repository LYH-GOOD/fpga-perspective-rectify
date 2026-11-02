"""Manual selection keeps authority; failures never start scene-wide detection."""
import time
from pathlib import Path
import hashlib
import cv2
import numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v92_manual_v87 import ManualTracker
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class PersistentManualTracker:
    @property
    def physical(self):return self.edge is not None
    def __init__(self,frame,quad,limit=320,authority='manual'):
        from v105_native import prepare_edges
        prepare_edges()  # Selection only; never compile on a failed live frame.
        self.primary=ManualTracker(frame,quad,limit,authority);self.edge=None;self.failures=0
        self.next_retry=0.;self.limit=limit;self.authority=authority;self.closed=False
        if self.primary.fixed:
            from v104_physical_tracking import PhysicalTracker
            try:self.edge=PhysicalTracker.from_observation(self.primary.gray,self.primary.scale,self.primary.q,
                    self.primary.previous_ready,limit,authority)
            except (ValueError,cv2.error):pass
            if self.edge is not None:self.primary.close()
    def __getattr__(self,name):return getattr(self.edge or self.primary,name)
    def update(self,frame,radius=4.):
        if self.edge is not None:return self.edge.update(frame,radius=radius)
        begin=time.perf_counter();cpu=time.thread_time();stamp=float(frame.ready)
        if self.failures>=3 and stamp<self.next_retry:
            return None,dict(manual_tracking='MANUAL_SEARCH',manual_motion_proved=False,
                reason='same_target_retry_pending',tracker_s=time.perf_counter()-begin,tracker_thread_cpu_s=time.thread_time()-cpu)
        # Revalidate the same feature anchor after a gap. Static shortcuts must
        # not renew an expired/failed anchor; all original FB/RANSAC gates run.
        if self.failures:self.primary.first=True
        q,detail=self.primary.update(frame)
        if q is not None:
            if self.failures:checkpoint('MANUAL_SAME_TARGET_RECOVERED',method='original_FB',automatic_switch=False)
            self.failures=0;return q,detail
        self.failures+=1
        if self.failures>=3:
            self.next_retry=stamp+.25
            from v104_physical_tracking import PhysicalTracker
            try:
                candidate=PhysicalTracker.from_observation(self.primary.gray,self.primary.scale,self.primary.q,
                    self.primary.previous_ready,self.limit,self.authority)
            except (ValueError,cv2.error):candidate=None
            if candidate is not None:
                self.edge=candidate;self.edge.failures=1;self.primary.close()
                checkpoint('MANUAL_TARGET_RECOVERY_BEGIN',method='same_boundary',automatic_switch=False)
                q,detail=self.edge.update(frame)
            elif self.failures in (3,7) or self.failures%20==0:
                checkpoint('MANUAL_TARGET_RETRY',reason=detail.get('reason'),automatic_switch=False,
                    retry_max_hz=4,old_coordinates_not_renewed=True)
        detail['tracker_s']=time.perf_counter()-begin;detail['tracker_thread_cpu_s']=time.thread_time()-cpu
        return q,detail
    def close(self):
        if self.closed:return
        self.closed=True
        if self.edge is not None:self.edge.close()
        else:self.primary.close()
