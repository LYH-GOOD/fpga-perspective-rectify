"""Private CPU workspace: joint edge motion and bounded, remeasured jitter filter."""
from pathlib import Path
import hashlib,time
import numpy as np
import v31_native as native
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class StableEdgeWorkspace:
    def __init__(self):
        self.quads=np.empty((3,4,2),np.float64)
        self.support=np.empty(4,np.float64);self.rms=np.empty(4,np.float64)
        self.polarity=np.empty(4,np.int32);self.out=np.empty((4,2),np.float64)
        self.checked=np.empty((4,2),np.float64);self.edges=np.empty(21,np.float64)
        self.stats=np.empty(26,np.float64)
    def measure(self,gray,previous,prediction,candidate,evidence,allow_filter=True):
        if native._LIB is None:return None
        began=time.perf_counter();cpu=time.thread_time()
        g=np.ascontiguousarray(gray,np.uint8)
        if g.ndim!=2:raise ValueError('Stable edges require current gray plane')
        for i,q in enumerate((previous,prediction,candidate)):
            if np.shape(q)!=(4,2):raise ValueError('Stable edge quad layout invalid')
            self.quads[i]=q
        supports=evidence.get('edge_support',());rms=evidence.get('edge_rms',());polarity=evidence.get('edge_polarity',())
        if len(supports)!=4 or len(rms)!=4 or len(polarity)!=4:return None
        self.support[:]=supports;self.rms[:]=rms;self.polarity[:]=polarity
        code=native._LIB.p11_v68_stabilize(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            self.quads[0].ctypes.data,self.quads[1].ctypes.data,self.quads[2].ctypes.data,
            self.support.ctypes.data,self.rms.ctypes.data,self.polarity.ctypes.data,int(bool(allow_filter)),
            self.out.ctypes.data,self.checked.ctypes.data,self.edges.ctypes.data,self.stats.ctypes.data)
        if code:raise ValueError('Stable current-edge helper rejected input '+str(code))
        if not np.isfinite(self.out).all() or not np.isfinite(self.stats).all():raise ValueError('Stable edge result invalid')
        s=self.stats
        detail=dict(backend='cpp_joint_line_motion_current_recheck',physical_layer_suspect=bool(s[0]),
            filtered=bool(s[1]),raw_motion=float(s[2]),prediction_correction=float(s[3]),
            joint_motion_residual=float(s[4]),largest_edge_offset=float(s[5]),second_edge_offset=float(s[6]),
            noise_pixels=float(s[7]),filter_alpha=float(s[8]),filter_shift=float(s[9]) if s[1] else 0.,
            proposed_filter_shift=float(s[9]),
            current_fit_line_error=float(s[10]),remeasured_line_error=float(s[11]),
            native_wall_s=float(s[12]),native_thread_cpu_s=float(s[13]),current_remeasured=bool(s[14]),
            strong_current_edges=bool(s[15]),signed_edge_offsets=s[16:20].tolist(),
            real_motion_filter_bypassed=bool(s[20]),current_quad_valid=bool(s[21]),filter_proposed=bool(s[22]),
            remeasure_support=float(s[23]),remeasure_rms=float(s[24]),filtered_quad_valid=bool(s[25]),
            wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu,
            independent_source_proof_granted=False,old_H_not_used=True)
        updated=evidence
        if detail['filtered']:
            e=self.edges
            updated=dict(evidence,valid=bool(e[20]),supported_edges=int(e[17]),refined_corners=int(e[16]),
                edge_support=[min(float(e[i]),float(self.support[i])) for i in range(4)],
                edge_rms=[max(float(e[12+i]),float(self.rms[i])) for i in range(4)],
                edge_polarity=[int(e[4+i]) for i in range(4)],
                edge_backend='cpp_current_Y24_filtered_quad_recheck',filtered_current_line_recheck=True,
                filter_max_shift_tracking_pixels=.25,current_recheck_radius=1.75)
        result=self.out.astype(np.float32)
        detail.update(wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu)
        return result,updated,detail
