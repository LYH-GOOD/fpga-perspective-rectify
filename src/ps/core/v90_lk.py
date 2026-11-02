"""Original complete checked LK transaction with persistent FFI bindings.

The C++ pyramid, forward/backward, filtering and RANSAC implementation is exact
V74. Validation, returned ownership and all acceptance thresholds are retained.
"""
from pathlib import Path
import hashlib,time
import numpy as np
from p11_contract import RELEASE_ID
from v87_v74_native import LKCache
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class LKTransaction(LKCache):
    def __init__(self):
        super().__init__()
        self._addresses={name:int(getattr(self,name).ctypes.data) for name in (
            'anchor_quad','previous_quad','quad','retained','filter_stats','flow_times','motion_info')}
        self._checked_motion=self.lib.p11_lk_checked_motion if self.pointer else None

    def checked(self,gray,points,initial,anchor,previous,generation,levels=3,iterations=20):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if not 4<=len(p)<=100 or (guess is not None and not np.isfinite(guess).all()):raise ValueError('LK prediction/features invalid')
        if isinstance(generation,bool) or not isinstance(generation,(int,np.integer)) or not 0<=int(generation)<0xffffffff:raise ValueError('LK frame generation invalid')
        self.anchor_quad[:]=anchor;self.previous_quad[:]=previous
        self.filter_stats.fill(0.);self.flow_times.fill(0.)
        began=time.perf_counter();cpu=time.thread_time()
        code=self._checked_motion(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],p.ctypes.data,len(p),
            None if guess is None else guess.ctypes.data,int(levels),int(iterations),int(generation),self._addresses['anchor_quad'],
            self._addresses['previous_quad'],self._addresses['quad'],self._addresses['retained'],self._addresses['filter_stats'],self._addresses['flow_times'],self._addresses['motion_info'])
        self.last_checked_timing=dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),native_checked_wall_s=time.perf_counter()-began,
            native_checked_thread_cpu_s=time.thread_time()-cpu,native_checked_code=int(code),
            transaction_backend='cpp_bidirectional_lk_filter',workspace_bindings_reused=True,complete_FB=code==0,
            motion_model={0:'unavailable',1:'similarity_candidate',2:'projective_candidate'}.get(int(self.motion_info[0]),'invalid'),
            motion_good_features=int(self.motion_info[1]),motion_inliers=int(self.motion_info[2]),
            motion_reprojection_rms=float(self.motion_info[3]),current_four_edges_required=True)
        if code<=-100:raise ValueError('native LK rejected frame: '+str(code+100))
        if code:raise ValueError('native LK consistency rejected: '+str(code))
        n=int(self.filter_stats[4])
        detail=dict(lk_backend='cpp_cached_pyramids_checked',features=len(p),good_features=int(self.filter_stats[1]),filter_backend='cpp_bidirectional_lk_filter',
            inliers=n,inlier_fraction=float(self.filter_stats[2]),fb_median=float(self.filter_stats[3]),
            motion_model=self.last_checked_timing['motion_model'],motion_reprojection_rms=float(self.motion_info[3]),
            current_four_edges_required=True)
        return self.quad.copy(),self.retained[:n].copy(),detail,dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),transaction_backend='cpp_bidirectional_lk_filter')
