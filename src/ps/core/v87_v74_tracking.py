"""Per-frame paper edges first; confidence-triggered predicted sparse LK.

Coordinates returned to the caller are original BGR pixel coordinates. No PL
access occurs here. A failed reacquisition returns valid=False, never stale H.
"""
from pathlib import Path
import hashlib
import os
import time
import cv2
import numpy as np
from v90_transaction import geometry_transaction
from p11_contract import RELEASE_ID
from v31_pixels import luminance,model_bgr,gray_half

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# ⭐⭐ 2026-10-18（把 V1.1 的优化合并进 V94）：
#   gate 失守后那次 `_boundary` 「重搜」的开关。
#   【默认 False = 行为与原 V94 完全一致】；notebook 里设 P11_SKIP_RESEARCH=1 才跳过。
#
# 证据（V1.1 上做的 A/B，跑的是本 tracker 的同一段代码）：
#   - edge_confidence 帧 tracker 170.0 → 121.9 ms（−28%）
#   - tracker p90 −18%、service p90 −15%、中位持平、confidence 完全相同
#   - V89-M 上板复验：干净场景 156.9 → 126.0 ms（−20%）
#   ⚠️ V94 换了 V90/V91 原生事务，绝对毫秒会变，但这段 `current_boundary` 调用本身没变。
#
# ⚠️ 用环境变量而不是改常量：改 .py 会让 sha256 与 release_manifest.json 不一致
#    ⇒ verify_package 直接抛错，还得 Kernel->Restart（_SOURCE_SHA256 是 import 时算的）。
# ⚠️ 在【调用时】读 ⇒ 改完下一次跟踪就生效，不用重启内核。
SKIP_DEAD_RESEARCH = False


def skip_dead_research():
    """A/B 开关：环境变量 P11_SKIP_RESEARCH=1 就跳过那次 _boundary 重搜。"""
    return os.environ.get('P11_SKIP_RESEARCH') == '1'


# ⭐⭐ 2026-10-18 静态保持（static hold）：
#   静止超过 min_frames 帧后，跳过 observer/边测量/门限，直接复用上一帧四角；
#   一旦帧差超过退出阈值、或距上次完整测量超过 max_hold_s，立即走原完整路径。
#   默认 False（行为与 V94-M 完全一致）；notebook 里设 P11_STATIC_HOLD=1 才开。
#   预算（V94-M 实测，静态 edge_measured 帧）：service 46.3 ms，其中 tracker 23.0 ms。
STATIC_HOLD = False


def static_hold_enabled():
    return os.environ.get('P11_STATIC_HOLD') == '1'


def _hold_float(name,default):
    try:return float(os.environ.get(name,default))
    except (TypeError,ValueError):return float(default)


def static_hold_settings():
    """静态保持参数。阈值会乘上自适应噪声底，见 _static_hold。"""
    return dict(enabled=static_hold_enabled(),continuity=os.environ.get('P11_STATIC_EDGE_CONTINUITY','1')!='0',
        enter=_hold_float('P11_HOLD_ENTER',4.),exit=_hold_float('P11_HOLD_EXIT',8.),
        enter_frac=_hold_float('P11_HOLD_CHANGE',.03),exit_frac=_hold_float('P11_HOLD_EXIT_CHANGE',.08),
        max_s=_hold_float('P11_HOLD_MAX_S',.8),min_frames=max(1,int(_hold_float('P11_HOLD_MIN_FRAMES',3))),
        enter_gain=_hold_float('P11_HOLD_ENTER_GAIN',1.5),exit_gain=_hold_float('P11_HOLD_EXIT_GAIN',2.2),
        smooth=max(1,int(_hold_float('P11_HOLD_SMOOTH',3))))


class LKExteriorMismatch(ValueError):
    """FB/motion fit succeeded, but the CURRENT exterior did not verify it."""

class GrayObserver:
    """Reuse three gray slots; pinned anchor and last observation stay intact."""
    def __init__(self, limit, backend='auto', gaussian_backend='auto'):
        if backend not in ('auto','legacy'):raise ValueError('gray_backend须为auto/legacy')
        if gaussian_backend not in ('auto','legacy'):raise ValueError('gaussian_backend须为auto/legacy')
        self.limit,self.backend=limit,backend
        self.gaussian_backend=gaussian_backend
        self.blur_workspace=None
        self.scratch=None
        self.detail={};self.pool=[];self.pinned=None;self.last=None;self.merged_edges=None;self.merged_error=None
        self.timing=np.empty(2,np.float64)
        self._layout=None;self._scale=None;self._geometry=None
        from v87_v74_native import ObservationWorkspace
        self.transaction=ObservationWorkspace()
    def pin(self,gray):self.pinned=gray
    def output(self,shape):
        if not self.pool or self.pool[0].shape!=shape:self.pool=[np.empty(shape,np.uint8) for _ in range(3)]
        return next(a for a in self.pool if a is not self.pinned and a is not self.last)

    def get(self,image,edge_context=None):
        began=time.perf_counter();cpu=time.thread_time();h,w=image.shape[:2];self.merged_edges=None;self.merged_error=None
        self.transaction.decode_timing=(0.,0.)
        layout=(h,w,self.limit)
        if layout!=self._layout:
            scale=min(1.,self.limit/max(h,w));ow,oh=round(w*scale),round(h*scale)
            self._scale=np.frombuffer(np.array([w/ow,h/oh],np.float64).tobytes(),np.float64)
            self._geometry=(scale,ow,oh);self._layout=layout
        scale,ow,oh=self._geometry
        #   ⚠️ 2026-10-28：原生 fused 灰度要求降采样**恰好 2 倍**（见下面几处
        #      `(ow*2,oh*2)==(w,h)`）。480P 要 320、600P 要 400 ——
        #      切档方案里若只改相机宽高而不改 `tracking_max_dim`，
        #      会**静默**退回 Python 慢路径（实测 11 ms → 63 ms）。
        #      这里打一次性 checkpoint，让"切档后变慢"能一眼看出来。
        if not (ow*2,oh*2)==(w,h) and not getattr(self,'_slow_warned',False):
            self._slow_warned=True
            try:
                from run_logging import checkpoint as _ck
                _ck('GRAY_OBSERVER_SLOW_PATH',warning='原生 fused 要求恰好 2 倍降采样',
                    image_shape=[h,w],limit=self.limit,gray_shape=[oh,ow],
                    fix='tracking_max_dim 必须等于 长边/2（640x480⇒320，800x600⇒400）')
            except Exception:pass
        if self.backend=='auto' and self.gaussian_backend=='auto' and (ow*2,oh*2)==(w,h):
            from v87_v74_native import fused_observation2
            if self.scratch is None or self.scratch.shape!=(oh,ow):self.scratch=np.empty((oh,ow),np.uint8)
            if self.blur_workspace is None or self.blur_workspace.size<3*ow:self.blur_workspace=np.empty(3*ow,np.uint16)
            out=self.output((oh,ow));fused_result=None
            if edge_context is not None:
                merged=self.transaction.observe(image,self.scratch,self.blur_workspace,out,*edge_context)
                if merged is not None:
                    self.merged_edges,detail=merged;self.merged_error=detail.get('edge_error');fused_result=(out,detail)
            if fused_result is None:fused_result=fused_observation2(image,self.scratch,self.blur_workspace,out,self.timing)
            if fused_result is not None:
                observation,detail=fused_result;elapsed=time.perf_counter()-began
                self.detail=dict(detail,backend='cpp_fused_area2_gaussian3',blur_backend='cpp_fixed_gaussian3',
                    shape=[oh,ow],gray_s=elapsed,
                    native_return_overhead_s=max(0.,elapsed-detail.get('native_transaction_s',detail['resize_gray_s']+detail['blur_s'])))
                self.detail['observation_transaction_s']=elapsed;self.detail['output_pool_reused']=True
                self.last=observation
                self.detail['thread_cpu_s']=time.thread_time()-cpu
                return observation,self._scale
        backend='opencv_area_then_gray';fused=False
        from v87_v74_native import gray_area2,native_status
        if self.backend=='auto' and (ow*2,oh*2)==(w,h):
            if self.scratch is None or self.scratch.shape!=(oh,ow):
                self.scratch=np.empty((oh,ow),np.uint8)
            fused=gray_area2(image,self.scratch)
            if fused:gray=self.scratch;backend=native_status().get('gray_backend','fused_area2')
        if not fused:
            if image.shape[2]==2:
                if (ow*2,oh*2)==(w,h):
                    if self.scratch is None or self.scratch.shape!=(oh,ow):self.scratch=np.empty((oh,ow),np.uint8)
                    gray=gray_half(image,self.scratch)
                else:
                    y=luminance(image);gray=cv2.resize(y,(ow,oh),interpolation=cv2.INTER_AREA) if scale<1 else y
                backend='direct_Y_normalized'
            else:
                view=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_AREA) if scale<1 else image
                gray=cv2.cvtColor(view,cv2.COLOR_BGR2GRAY)
        resize_s=time.perf_counter()-began;t=time.perf_counter()
        # Fresh blurred allocation is deliberate: anchor_gray must survive
        # intermediate frames and the native pyramid promotion.
        observation=None;blur_backend='opencv_gaussian3'
        if self.gaussian_backend=='auto':
            from v87_v74_native import gaussian3
            if self.blur_workspace is None or self.blur_workspace.size<3*ow:
                self.blur_workspace=np.empty(3*ow,np.uint16)
            observation=gaussian3(gray,self.blur_workspace)
            if observation is not None:blur_backend=native_status().get('blur_backend','cpp_gaussian3')
        if observation is None:observation=cv2.GaussianBlur(gray,(3,3),.6)
        self.detail=dict(backend=backend,blur_backend=blur_backend,shape=[oh,ow],resize_gray_s=resize_s,
                         blur_s=time.perf_counter()-t,gray_s=time.perf_counter()-began)
        self.last=observation
        self.detail['thread_cpu_s']=time.thread_time()-cpu
        return observation,self._scale

def _gray(image,limit):
    return GrayObserver(limit,'legacy').get(image)


def _valid(q, shape, reference=None, checks='auto'):
    if checks=='auto':
        from v87_v74_native import quad_valid
        result=quad_valid(q,shape,reference)
        if result is not None:return result
    q = np.asarray(q, np.float32).reshape(4, 2)
    h, w = shape[:2]
    if not np.isfinite(q).all() or not cv2.isContourConvex(q):
        return False
    if np.cross(q[1]-q[0], q[2]-q[1]) <= 0:
        return False
    area = abs(cv2.contourArea(q))
    if area < .035*w*h or np.any(q < 0) or np.any(q[:, 0] > w-1) or np.any(q[:, 1] > h-1):
        return False
    if reference is not None:
        old = abs(cv2.contourArea(np.asarray(reference, np.float32)))
        if not .55 < area/max(old, 1.) < 1.8:
            return False
    return True


def _edge_python(gray, quad, radius=5., checks='auto'):
    """Sample 24 short normal profiles per OUTER paper edge, then intersect TLS lines."""
    q = np.asarray(quad, np.float64).reshape(4, 2)
    offsets = np.linspace(-radius, radius, 25)
    fractions = np.linspace(.055, .945, 24)
    center = q.mean(axis=0)
    lines, supports, shifts, polarity, rms_values = [], [], [], [], []
    for i in range(4):
        a, b = q[i], q[(i+1) % 4]
        edge = b-a
        normal = np.array([-edge[1], edge[0]]) / max(np.linalg.norm(edge), 1e-6)
        if np.dot(center-(a+b)*.5, normal) < 0:
            normal = -normal
        base = a + fractions[:, None]*edge
        xy = base[:, None, :] + offsets[None, :, None]*normal
        p = cv2.remap(gray, xy[..., 0].astype(np.float32), xy[..., 1].astype(np.float32),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        outer, inner = np.median(p[:, :4], axis=1), np.median(p[:, -4:], axis=1)
        contrast = inner-outer
        signed = (p-(outer+inner)[:, None]*.5)*np.where(contrast >= 0, 1., -1.)[:, None]
        crossing = (signed[:, :-1] <= 0) & (signed[:, 1:] > 0)
        scores = np.where(crossing, np.abs((offsets[:-1]+offsets[1:])*.5), np.inf)
        col = np.argmin(scores, axis=1)
        row = np.arange(len(base))
        before, after = signed[row, col], signed[row, col+1]
        alpha = np.clip(-before/np.maximum(after-before, 1e-6), 0., 1.)
        shift = offsets[col] + alpha*(offsets[col+1]-offsets[col])
        good = (np.abs(contrast) >= 8) & crossing.any(axis=1) & (np.abs(shift) < radius*.85)
        line = None
        rms = 1e30
        support = float(good.mean())
        if good.sum() >= 10 and np.ptp(fractions[good]) >= .55:
            points = base[good]+shift[good, None]*normal
            for _ in range(2):
                mean = points.mean(axis=0)
                n = _tls_normal(points-mean)
                residual = np.abs((points-mean)@n)
                keep = residual <= max(.6, 2.5*float(np.median(residual)))
                if keep.all() or keep.sum() < 8:
                    break
                points = points[keep]
            mean = points.mean(axis=0)
            n = _tls_normal(points-mean)
            rms = float(np.sqrt(np.mean(((points-mean)@n)**2)))
            if rms <= 1.25:
                line = np.r_[n, -n@mean]
        lines.append(line)
        rms_values.append(rms)
        supports.append(support if line is not None else 0.)
        shifts.append(float(np.median(np.abs(shift[good]))) if good.any() else radius)
        median_contrast = float(np.median(contrast))
        polarity.append(int(np.sign(median_contrast)) if abs(median_contrast) >= 8 else 0)
    corrected = q.copy()
    refined = 0
    for i in range(4):
        if lines[i-1] is None or lines[i] is None:
            continue
        cross = np.cross(lines[i-1], lines[i])
        if abs(cross[2]) > .06:
            point = cross[:2]/cross[2]
            if np.linalg.norm(point-q[i]) < radius*2.8:
                corrected[i] = point
                refined += 1
    supported_edges = sum(s >= .42 for s in supports)
    valid = supported_edges >= 3 and refined >= 2 and _valid(corrected, gray.shape, q, checks)
    return corrected.astype(np.float32), dict(valid=bool(valid), supported_edges=supported_edges,
        edge_support=supports, edge_polarity=polarity, refined_corners=refined,
        median_edge_shift=float(np.median(shifts)),edge_rms=rms_values,max_edge_rms=max(rms_values))



def _tls_normal(centered):
    xx=float(np.sum(centered[:,0]**2));yy=float(np.sum(centered[:,1]**2))
    xy=float(np.sum(centered[:,0]*centered[:,1]))
    if np.hypot(xx-yy,2*xy)<=1e-10*(xx+yy+1):
        raise ValueError('TLS edge samples degenerate')
    theta=.5*np.arctan2(2*xy,xx-yy)
    return np.array([-np.sin(theta),np.cos(theta)])

def edge_measure(gray,quad,radius=5.,checks='auto'):
    began=time.perf_counter()
    from v87_v74_native import measure_edges
    native=measure_edges(gray,quad,radius,checked=checks=='auto')
    if native is None:
        q,evidence=_edge_python(gray,quad,radius,checks)
        evidence['edge_backend']='numpy_analytic_tls'
    else:
        q,evidence=native
        evidence['valid']=(evidence['native_valid'] if checks=='auto' else
            evidence['supported_edges']>=3 and evidence['refined_corners']>=2 and _valid(q,gray.shape,quad,checks))
    evidence['edge_measure_s']=time.perf_counter()-began
    return q,evidence

def _spatial_support(points,quad,checks='auto'):
    if checks=='auto':
        from v87_v74_native import spatial_support
        result=spatial_support(points,quad)
        if result is not None:return result
    p=np.asarray(points,np.float32).reshape(-1,2)
    if len(p)<4:return False
    area=abs(cv2.contourArea(np.asarray(quad,np.float32)))
    if abs(cv2.contourArea(cv2.convexHull(p)))<.25*max(area,1):return False
    # Require points near three different border segments, not one grid line.
    q=np.asarray(quad,np.float32);edge=np.roll(q,-1,axis=0)-q
    d=p[:,None,:]-q[None,:,:]
    t=np.clip(np.sum(d*edge[None,:,:],axis=2)/np.maximum(np.sum(edge*edge,axis=1),1e-6),0,1)
    distance=np.linalg.norm(d-t[:,:,None]*edge[None,:,:],axis=2)
    near=np.argmin(distance,axis=1)
    return len(np.unique(near))>=3 or len(p)==4  # four widely spaced tracked paper corners

class PaperTracker:
    def __init__(self, interval=3, limit=320, detection_limit=640, detector=None,
                 gray_backend='auto',feature_policy='quality',gaussian_backend='auto',tracking_checks='auto',
                 tracking_policy='motion_adaptive',lk_max_gap=30,lk_min_gap=6):
        if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 10:
            raise ValueError('track_interval 须为 1..10 的整数')
        if not 160 <= limit <= 640:
            raise ValueError('tracking_max_dim 须为 160..640')
        if tracking_policy not in ('motion_adaptive','edge_first','periodic'):raise ValueError('tracking_policy须为motion_adaptive/edge_first/periodic')
        if isinstance(lk_max_gap,bool) or not isinstance(lk_max_gap,int) or not 3<=lk_max_gap<=60:
            raise ValueError('lk_max_gap须为3..60')
        if isinstance(lk_min_gap,bool) or not isinstance(lk_min_gap,int) or not 3<=lk_min_gap<=lk_max_gap:raise ValueError('lk_min_gap须为3..lk_max_gap')
        self.lk_min_gap=lk_min_gap
        self.motion_ema=self.correction_ema=self.drift_budget=0.
        self.accumulated_drift=np.zeros((4,2),np.float32)
        self.policy,self.lk_max_gap=tracking_policy,lk_max_gap
        self.interval, self.limit, self.detection_limit = interval, limit, detection_limit
        self.detector = detector
        self.velocity = np.zeros((4, 2), np.float32)
        self.started = False
        self.last_index = self.anchor_index = 0
        self.lost = False
        self.seed_index=0
        self.seed_count=0
        self._promoted_points=None
        from v90_lk import LKTransaction
        self.lk_cache=LKTransaction()
        from v91_native import PostLKWorkspace
        self.post_lk=PostLKWorkspace()
        self.last_lk_timing={}
        if feature_policy not in ('quality','legacy'):raise ValueError('feature_policy须为quality/legacy')
        if tracking_checks not in ('auto','legacy'):raise ValueError('tracking_checks须为auto/legacy')
        self.checks=tracking_checks
        self.feature_policy=feature_policy
        self.observer=GrayObserver(limit,gray_backend,gaussian_backend)
        self.last_gray=None
        self.light_results=False
        self.last_feature_detail={}
        from v87_v74_native import EdgeMotionWorkspace
        self.edge_workspace=EdgeMotionWorkspace()
        self._current_motion_values=None
        self.edge_recovery_count=0
        # ⭐ 静态保持状态
        self._hold_ref=None;self._hold_count=0;self._hold_active=False;self._hold_since=0.
        self._hold_last_full=0.;self._hold_gate={};self._hold_confidence=0.;self._hold_frames=0
        self._hold_motion=0.;self._hold_changed=0.
        self._hold_tmp=None;self._hold_hist=[];self._hold_floor_m=4.;self._hold_floor_c=.03
        self._hold_smooth=(0.,0.);self._hold_cfg=None
        self._still_q=None;self._still_samples=None;self._still_calm=False;self._still_radius=3.
        self._still_edge_motion=0.;self._still_release='initial'
        self._roi_failures=0;self._roi_retry_lk=0;self._roi_lk_checks=0
        # ⭐ 2026-10-28：重取点【成功】后的最小间隔（单位：LK 帧）。
        #    实测 native 四角 ROI 18~25 ms、边缘条 30~33 ms，占动态帧约 13 ms；
        #    而原来成功后 `delay=1` ⇒ 下一帧立刻又搜。P11_ROI_SEARCH_GAP=1 回到旧行为。
        try:self._roi_search_gap=max(1,min(8,int(os.environ.get('P11_ROI_SEARCH_GAP','3'))))
        except ValueError:self._roi_search_gap=3
        self._roi_last_q=None;self._roi_mask=None;self._roi_inside=None
        self._gap_anchor_reuses=0
        self._burst_until=-1;self._frame_deadline=None;self._update_index=0
        self.anchor_gray=None;self.lk_channel='Y';self._flow_gray=None;self._flow_cache=None;self._chroma_pool=[]
        self._channel_audit_index=-100;self._channel_evidence={};self._edge_radius=3.
        self.state='UNINITIALIZED';self._total_deadline=None;self._reserved_detection_ms=0.
        self._lk_initial=np.empty((100,1,2),np.float32)
        self._lk_anchor_quad=np.empty((4,2),np.float32)
        self._lk_prediction_quad=np.empty((4,2),np.float32)
        self.recovery_budget_ms=None;self.recovery_max_candidates=2;self.recovery_backoff_max_frames=4
        self.reacquire_budget_ms=240.;self.reacquire_max_candidates=4
        self._recovery_failures=0;self._recovery_next_index=0;self._recovery_attempts=0
        self._recovery_next_at=0.;self._continuity_proof_next_at=0.;self.continuity_hold=False
        self.recovery_retry_min_s=.20;self.recovery_retry_max_s=.60
        self.recovery_stats=dict(attempts=0,deferred=0,successes=0,budget_stops=0,elapsed_s=0.,overshoot_s=0.)
        self.recovery_snapshots=[]
        self._vector_boundary=False;self._target_signature=None;self._recovery_confirmations=3
        self.recovery_worker=None;self.recovery_result_max_age_s=.90
        from v67_observation import IlluminationMotion
        self.photometric=IlluminationMotion()
        from v68_stability import StableEdgeWorkspace
        self.stability=StableEdgeWorkspace();self.stability_detail={}
        self._stability_drift_start=np.zeros((4,2),np.float32)
        self._last_measured_motion=0.;self._edge_lock_next_at=0.;self._edge_lock_failures=0
        from v69_policy import CurrentProofWorkspace
        self.current_proofs=CurrentProofWorkspace()
        self.fastpath_detail={};self.quick_recovery_detail={};self._quick_recovery_attempted=False

    def configure_async_recovery(self,enabled=True,result_max_age_s=.90):
        if not isinstance(enabled,bool) or isinstance(result_max_age_s,bool) or not np.isfinite(result_max_age_s) or not .1<=result_max_age_s<=1.:
            raise ValueError('async_recovery bool; recovery_result_max_age_s .1..1 seconds')
        self.recovery_result_max_age_s=float(result_max_age_s)
        if enabled and self.recovery_worker is None:
            from v58_recovery import RecoveryWorker
            self.recovery_worker=RecoveryWorker(self.detection_limit,self.limit)

    def _async_wait(self,image,index,began,cpu,reason,result=None,observation=None,request_background=True):
        self.lost=True;self.state='LOST';self.velocity[:]=0;self.last_index=index
        age=max(0.,time.perf_counter()-getattr(self,'_last_physical_at',began))
        local_first=(age<.20 and not self._quick_recovery_attempted and getattr(self,'_local_attempts',0)<2
            and self._last_measured_motion<=4. and not getattr(self,'source_force_reacquire',False))
        request_background=bool(request_background and not local_first)
        requested=self.recovery_worker.request(image,index,
            getattr(self,'source_ready_at',began),getattr(self,'source_sequence',None),
            self.reacquire_budget_ms,self.reacquire_max_candidates) if request_background else False
        detail=dict(state='async_detection_in_progress',requested=requested,
            result=None if result is None else {k:result.get(k) for k in
                ('valid','index','sequence','ready','completed_at','worker_s','worker_cpu_s','reason')},
            worker=self.recovery_worker.snapshot(),hardware_access=False,
            ordinary_frame_heavy_recovery_skipped=True,current_candidate_required_before_new_H=True,
            background_deferred_for_local_first=not request_background,
            local_attempts=int(getattr(self,'_local_attempts',0)),local_first_grace_s=.20,
            large_motion_skips_local=self._last_measured_motion>4.)
        record=dict(valid=False,mode='lost_skip',reason=reason,trigger=reason,index=index,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu,
            gray_s=0.,gray_detail=dict(state='not_measured_while_background_busy'),
            feature_update_s=0.,feature_detail=dict(action='async_wait',roi_s=0.),lk_timing={},
            tracking_policy=self.policy,lk_channel=self.lk_channel,lk_trigger='async_recovery',
            tracking_state=self.state,edge_gate={},edge_evidence={},detection=None,
            final_admission_gate=dict(reliable=False),recovery_attempt=detail,edge_stability=dict(self.stability_detail),
            v49_fastpath=dict(self.fastpath_detail),quick_current_candidate=dict(self.quick_recovery_detail),
            current_proof_workspace=self.current_proofs.summary())
        if observation is not None:record.update(observation)
        return record

    def _admit_async_candidate(self,image,gray,scale,result,index):
        # Background coordinates are a proposal ONLY. All admitted edges come
        # from the currently leased input. The worker's receipt is never reused.
        from v31_detection import current_boundary,exterior_gate
        from v49_boundary import exterior_agreement,array_key,actual_source64
        age=max(0.,time.perf_counter()-result['ready'])
        if age>self.recovery_result_max_age_s:raise ValueError('Background candidate too old')
        proposal=((np.asarray(result['quad'],np.float32)+.5)/scale-.5).astype(np.float32)
        transport=dict(used=False,backend='bounded_candidate_corner_forward_backward_LK')
        donor=result.get('source_gray');donor_scale=result.get('source_scale')
        if donor is not None and donor.shape==gray.shape and np.allclose(donor_scale,scale,rtol=0,atol=1e-6):
            t=time.perf_counter();cpu=time.thread_time()
            points=proposal.reshape(4,1,2)
            criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02)
            moved,status,error=cv2.calcOpticalFlowPyrLK(donor,gray,points,None,
                winSize=(21,21),maxLevel=2,criteria=criteria)
            if moved is not None and status is not None and np.all(status):
                back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,donor,moved,None,
                    winSize=(21,21),maxLevel=2,criteria=criteria)
                fb=float(np.max(np.linalg.norm(back.reshape(4,2)-proposal,axis=1))) if back is not None else float('inf')
                transported=moved.reshape(4,2)
                if (back_status is not None and np.all(back_status) and np.isfinite(transported).all()
                        and fb<=1. and error is not None and np.max(error)<=30.
                        and _valid(transported,gray.shape,proposal,self.checks)):
                    proposal=transported.astype(np.float32);transport.update(used=True,fb_max=fb)
                else:transport.update(reason='candidate_flow_rejected',fb_max=fb)
            else:transport['reason']='candidate_flow_unavailable'
            transport.update(wall_s=time.perf_counter()-t,thread_cpu_s=time.thread_time()-cpu)
        if not _valid(proposal,gray.shape,checks=self.checks):raise ValueError('Background candidate geometry invalid')
        reference=proposal.copy()
        measured,small_evidence=edge_measure(gray,reference,6.,self.checks)
        gray_gate=exterior_gate(small_evidence,measured,reference,6.)
        gray_trusted=(gray_gate.get('reliable') and gray_gate.get('min_support',0.)>=.80
            and gray_gate.get('max_rms',1e30)<=.65 and gray_gate.get('prediction_correction',1e30)<=.75)
        seed=measured if gray_trusted else reference
        primary,evidence,second_gate,agreement=self._source_confirmation(
            image,gray,seed,small_evidence,new_candidate=True,radius=6.,
            reference=reference,gray_reliable=bool(gray_trusted))
        transport.update(original_candidate_preserved=True,gray_seed_used=bool(gray_trusted),
            gray_gate=gray_gate,source_reference=reference.tolist())
        from v62_policy import search_gate
        first=search_gate(evidence,primary,proposal,6.)
        verified=(first.get('reliable') and second_gate.get('reliable') and agreement.get('verified')
            and _valid(primary,gray.shape,checks=self.checks))
        if not verified:
            from run_logging import checkpoint
            checkpoint('ASYNC_CANDIDATE_CURRENT_REJECTED',current_index=index,
                background_index=result['index'],candidate_age_s=age,
                first_gate=first,independent_gate=second_gate,agreement=agreement,
                candidate_transport=transport,hardware_access=False)
            raise ValueError('Background proposal failed current independent exterior proof: '+str(agreement.get('reason','four_edge_disagreement')))
        return primary,evidence,dict(state='async_candidate_current_frame_verified',
            background_index=result['index'],background_sequence=result['sequence'],candidate_age_s=age,
            current_index=index,candidate_transport=transport,first_validation=first,second_validation=second_gate,
            source_line_agreement=agreement,old_H_not_used=True,stale_receipt_used=False)

    def _local_due(self):
        now=time.perf_counter();age=now-getattr(self,'_last_physical_at',0.)
        # At most two local attempts per actual validation failure episode.
        # Expiring output hold does not reset or extend this search budget.
        return bool(0<=age<=1.5 and now>=getattr(self,'_local_next_at',0.)
            and getattr(self,'_local_attempts',0)<2 and self._last_measured_motion<=4.
            and not getattr(self,'source_force_reacquire',False))

    def _quick_current_candidate(self,image,gray,scale,index):
        """One current-Y contour candidate per loss episode, strict admission.

        Proposal generation and original64/independent24 share one CPU/wall
        budget. A miss does not fall through to a full foreground search.
        """
        if self._quick_recovery_attempted:return None
        self._quick_recovery_attempted=True
        from v31_detection import _contour_proposals,recovery_detection_scope,recovery_candidate_scope,_DetectionStop
        from v58_budget import CpuRecoveryBudget,compact_recovery_summary
        from v69_policy import read_current_receipt
        from v49_boundary import array_key
        began=time.perf_counter();cpu=time.thread_time()
        budget=CpuRecoveryBudget(120.,1,wall_max_s=.30)
        observation=dict(gray=gray,scale=scale,source_shape=image.shape,frame_index=index,source_key=array_key(image))
        detail=dict(attempted=True,verified=False,proposal_source='current_tracking_Y_contour',
            maximum_candidates=1,maximum_attempts_per_loss_episode=1,hardware_access=False,
            old_H_not_used=True,full_foreground_search=False)
        self.quick_recovery_detail=detail
        try:
            with recovery_detection_scope(budget,observation):
                budget.check('v69_current_Y_proposal')
                proposal=next(iter(_contour_proposals(gray,min(240,self.detection_limit),incremental=True)),None)
                if proposal is None:
                    detail['reason']='no_current_Y_contour_candidate';return None
                if not _valid(np.asarray(proposal,np.float32),gray.shape,checks=self.checks):
                    detail['reason']='current_Y_candidate_geometry_invalid';return None
                budget.check('v69_immediate_candidate_admission')
                coarse=(np.asarray(proposal,np.float32)+.5)*scale-.5
                seed=dict(detector='v69_current_Y_contour',coarse_corners=coarse.tolist())
                with recovery_candidate_scope((seed,),True):full,detection=self._detect(image)
            receipt=read_current_receipt(detection,image,gray,scale,index,full)
            detection.pop('_current_boundary_receipt',None)
            if receipt is None:
                detail['reason']='current_candidate_receipt_not_bound';return None
            candidate,evidence,gate=receipt
            if not gate.get('reliable') or not _valid(candidate,gray.shape,checks=self.checks):
                detail['reason']='current_candidate_final_geometry_invalid';return None
            agreement=gate.get('current_source_agreement',{})
            if not agreement.get('verified'):
                detail['reason']='current_candidate_independent_proof_missing';return None
            self.last_source_confirmation=dict(agreement,final_gate=dict(gate))
            detail.update(verified=True,reason='current_candidate_immediately_admitted',
                same_frame_receipt_reused=True,original_corners_preserved=True)
            return candidate,evidence,dict(state='v69_current_candidate_verified',
                first_validation=gate,source_line_agreement=agreement,quick_current_candidate=detail,
                current_index=index,old_H_not_used=True,stale_receipt_used=False)
        except (ValueError,cv2.error,_DetectionStop) as exc:
            detail.update(reason=str(exc),exception_type=type(exc).__name__);return None
        finally:
            detail.update(wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu,
                budget=compact_recovery_summary(budget.summary()))

    def _local_exterior(self,image,gray,scale,prediction,index):
        """Current source lines only; bounded local proposal before full search.

        Strict new/current independent proof stays mandatory after LOST. This
        routine neither promotes old LK data nor renews any hold timestamp.
        """
        if not self._local_due():return None
        from v62_policy import sample_locked_color,search_gate
        now=time.perf_counter();cpu=time.thread_time()
        if not getattr(self,'_local_attempts',0):self._local_batch_at=now
        self._local_attempts=getattr(self,'_local_attempts',0)+1;self._local_next_at=now+.20
        deadline=now+.22
        if self._frame_deadline is not None:deadline=min(deadline,self._frame_deadline)
        age=max(0.,now-getattr(self,'_last_physical_at',now))
        radius=max(3.,min(12.,max(self._edge_radius,3.+2.*age)))
        try:
            primary,e=sample_locked_color(image,scale,prediction,64,deadline,self._target_signature,
                half_source=min(24.,radius*float(np.max(scale))),lock_physical=False)
            first=search_gate(e,primary,prediction,radius)
            if not first.get('reliable'):return None
            from v62_boundary import layer_continuity
            continuity=layer_continuity(self._target_signature,e)
            if not continuity['verified']:return None
            remaining_cpu=.16-(time.thread_time()-cpu)
            if remaining_cpu<=0 or time.perf_counter()>=deadline:return None
            observed,current,gate,agreement=self._source_confirmation(image,gray,primary,e,
                new_candidate=True,radius=radius,reference=prediction,gray_reliable=False,proof_deadline=deadline,proof_cpu_s=remaining_cpu)
            if (time.perf_counter()>deadline or time.thread_time()-cpu>.16
                or not gate.get('reliable') or not agreement.get('verified')
                or not _valid(observed,gray.shape,self.q,self.checks)):return None
            return observed,current,dict(state='local_current_source_exterior_reacquired',
                first_validation=first,second_validation=gate,source_line_agreement=agreement,
                local_attempt=self._local_attempts,local_wall_s=time.perf_counter()-now,
                local_thread_cpu_s=time.thread_time()-cpu,old_H_not_used=True,
                global_detection_skipped=True,hold_timer_renewed=False,physical_layer_continuity=continuity)
        except (ValueError,cv2.error):return None

    def configure_recovery(self,budget_ms=120.,max_candidates=2,backoff_max_frames=4,reacquire_budget_ms=240.,reacquire_max_candidates=4):
        if isinstance(reacquire_budget_ms,bool) or not np.isfinite(reacquire_budget_ms) or not budget_ms<=reacquire_budget_ms<=500:
            raise ValueError('reacquire_budget_ms must be recovery_budget_ms..500')
        if isinstance(budget_ms,bool) or not np.isfinite(budget_ms) or not 40<=budget_ms<=500:
            raise ValueError('recovery_budget_ms must be 40..500')
        for name,value,low,high in (('recovery_max_candidates',max_candidates,1,8),
                ('recovery_backoff_max_frames',backoff_max_frames,1,8),
                ('reacquire_max_candidates',reacquire_max_candidates,max_candidates,8)):
            if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
                raise ValueError(name+' outside bounded integer range')
        self.recovery_budget_ms=float(budget_ms);self.recovery_max_candidates=max_candidates
        self.recovery_backoff_max_frames=backoff_max_frames
        self.reacquire_budget_ms=float(reacquire_budget_ms);self.reacquire_max_candidates=reacquire_max_candidates

    def _remember_recovery_failure(self,gray,index,prediction,detail):
        # Four owned small-Y snapshots only. Encoding/saving is after formal timing.
        # Retain first + most recent three instead of growing with a long outage.
        if self._recovery_failures>1 and self._recovery_failures%4:return
        item=dict(index=int(index),gray=gray.copy(),corners=prediction.copy(),detail=dict(detail))
        if len(self.recovery_snapshots)>=4:self.recovery_snapshots.pop(1)
        self.recovery_snapshots.append(item)

    def _detect(self, image):
        if self.detector is not None:
            return self.detector(image)
        from v31_detection import detect_refined
        return detect_refined(image, self.detection_limit, True)

    def _roi_features(self,gray,q,retained=None,variant=0):
        if variant:return self._edge_strip_features(gray,q,retained,variant)
        if self.checks=='auto':
            began=time.perf_counter();native=self.lk_cache.roi_features(gray,q,retained)
            if native is not None:
                points,detail=native
                from v49_boundary import outer_features
                before=len(points);points=outer_features(points,q)
                self.last_feature_detail=dict(detail,roi_s=time.perf_counter()-began,
                    outer_band_filter=True,interior_features_removed=before-len(points),features=len(points),
                    added=max(0,len(points)-(0 if retained is None else len(retained))))
                return points
        """Small OUTER-paper corner patches; exclude interior repeating grid.

        Actual GFTT points only. If a textureless sheet gives no usable four
        regions, the existing full boundary seed remains the fallback.
        """
        began=time.perf_counter();h,w=gray.shape
        points=[] if retained is None else list(np.asarray(retained,np.float32).reshape(-1,2))
        before=len(points);regions=0
        for corner in q:
            if sum(float(np.linalg.norm(p-corner))<18 for p in points)>=2:
                continue
            x,y=corner;x0=max(0,int(x)-20);y0=max(0,int(y)-20)
            x1=min(w,int(x)+21);y1=min(h,int(y)+21)
            if min(x1-x0,y1-y0)<7:continue
            qi=np.rint(q-[x0,y0]).astype(np.int32)
            mask=np.zeros((y1-y0,x1-x0),np.uint8)
            cv2.polylines(mask,[qi],True,255,4)
            inside=np.zeros_like(mask);cv2.fillConvexPoly(inside,qi,255)
            mask=cv2.bitwise_and(mask,inside)
            if len(points)>=100:break
            found=cv2.goodFeaturesToTrack(gray[y0:y1,x0:x1],maxCorners=6,
                    qualityLevel=.012,minDistance=5,mask=mask,blockSize=5)
            regions+=1
            if found is None:continue
            for point in found.reshape(-1,2)[:4]+[x0,y0]:
                if len(points)>=100:break
                if not points or min(float(np.linalg.norm(p-point)) for p in points)>4:
                    points.append(point.astype(np.float32))
        out=np.asarray(points,np.float32).reshape(-1,2)
        self.last_feature_detail=dict(action='outer_corner_roi',regions=regions,
            added=len(out)-before,features=len(out),roi_s=time.perf_counter()-began)
        from v49_boundary import outer_features
        out=outer_features(out,q);self.last_feature_detail.update(features=len(out),added=max(0,len(out)-before))
        return out


    def _edge_strip_features(self,gray,q,retained,variant):
        """Alternate bounded outer-edge strips after corner patches add nothing."""
        began=time.perf_counter();cpu=time.thread_time();h,w=gray.shape
        if self._roi_mask is None or self._roi_mask.shape!=gray.shape:
            self._roi_mask=np.zeros_like(gray);self._roi_inside=np.zeros_like(gray)
        self._roi_mask.fill(0);self._roi_inside.fill(0)
        qi=np.rint(q).astype(np.int32);cv2.fillConvexPoly(self._roi_inside,qi,255)
        edges=(variant%2,(variant%2)+2)
        for edge in edges:
            a,b=q[edge],q[(edge+1)%4]
            cv2.line(self._roi_mask,tuple(np.rint(a+.12*(b-a)).astype(int)),
                tuple(np.rint(a+.88*(b-a)).astype(int)),255,4)
        cv2.bitwise_and(self._roi_mask,self._roi_inside,dst=self._roi_mask)
        points=[] if retained is None else list(np.asarray(retained,np.float32).reshape(-1,2))
        before=len(points)
        # Two bounded patches; no whole-image feature search, no invented points.
        for edge in edges:
            a,b=q[edge],q[(edge+1)%4]
            x0=max(0,int(min(a[0],b[0]))-5);x1=min(w,int(max(a[0],b[0]))+6)
            y0=max(0,int(min(a[1],b[1]))-5);y1=min(h,int(max(a[1],b[1]))+6)
            if min(x1-x0,y1-y0)<7:continue
            found=cv2.goodFeaturesToTrack(gray[y0:y1,x0:x1],maxCorners=4,qualityLevel=.012,
                minDistance=5,mask=self._roi_mask[y0:y1,x0:x1],blockSize=5)
            if found is None:continue
            for point in found.reshape(-1,2)+[x0,y0]:
                if len(points)>=100:break
                if not points or min(float(np.linalg.norm(p-point)) for p in points)>4:
                    points.append(point.astype(np.float32))
        out=np.asarray(points,np.float32).reshape(-1,2)
        self.last_feature_detail=dict(action='alternate_outer_edge_strips',regions=2,
            variant=variant,added=len(out)-before,features=len(out),workspace_reused=True,
            roi_s=time.perf_counter()-began,roi_thread_cpu_s=time.thread_time()-cpu)
        from v49_boundary import outer_features
        out=outer_features(out,q);self.last_feature_detail.update(features=len(out),added=max(0,len(out)-before))
        return out

    def _quality_replenish(self,gray,points,q,quality,evidence):
        from v49_boundary import outer_features
        points=outer_features(points,q)
        self._roi_lk_checks+=1
        supported=_spatial_support(points,q,self.checks)
        reliable=(quality and supported and len(points)>=4 and
            min(evidence.get('edge_support',[0.]*4))>=.8 and max(evidence.get('edge_rms',[1e30]*4))<=.65)
        if reliable and len(points)>=12:
            self.last_feature_detail=dict(action='promote_validated_inliers',features=len(points),roi_s=0.)
            return points
        if reliable and self._roi_lk_checks<self._roi_retry_lk:
            self.last_feature_detail=dict(action='bounded_roi_backoff',features=len(points),added=0,
                roi_s=0.,failures=self._roi_failures,next_retry_lk=self._roi_retry_lk,
                current_lk=self._roi_lk_checks,maximum_skipped_lk_checks=7,
                retained_fb_and_four_edge_checks=True)
            return points
        before=len(points);variant=self._roi_failures%3 if self._roi_failures else 0
        out=self._roi_features(gray,q,points,variant)
        self._roi_last_q=q.copy()
        self._roi_failures=(min(8,self._roi_failures+1) if len(out)<=before else 0)
        # Low-yield refill backs off only while motion, FB inliers, spatial
        # support AND all four measured edges remain trustworthy.
        delay=min(8,1<<min(3,self._roi_failures)) if reliable else 1
        self._roi_retry_lk=self._roi_lk_checks+delay
        # ⭐ 2026-10-28：这次真加了点（`len(out)>before`）且跟踪本来就可靠 ⇒
        #    按 `_roi_search_gap` 隔几帧再搜，而不是下一帧立刻重搜。
        #    只在"可靠但点数仍<12"这种纹理偏少的场景生效，`reliable=False` 的
        #    快速重试路径（delay=1）完全不动。
        if reliable and len(out)>before:
            self._roi_retry_lk=max(self._roi_retry_lk,self._roi_lk_checks+self._roi_search_gap)
        self.last_feature_detail.update(failures=self._roi_failures,next_retry_lk=self._roi_retry_lk,
            current_lk=self._roi_lk_checks,variant=variant,quality_override=not reliable)
        return out

    def _channel_quality(self,plane,q,points):
        # Four short outside/inside bands in the SMALL scalar plane; no full CSC.
        d=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(d,axis=1)
        normal=np.stack((-d[:,1],d[:,0]),axis=1)/np.maximum(length[:,None],1e-6)
        normal*=np.where(np.sum((q.mean(axis=0)-q-d*.5)*normal,axis=1)<0,-1.,1.)[:,None]
        base=q[:,None,:]+np.linspace(.1,.9,12)[None,:,None]*d[:,None,:]
        xy=base[:,:,None,:]+np.array([-3.,3.])[None,None,:,None]*normal[:,None,None,:]
        value=cv2.remap(plane,xy[...,0].reshape(48,2).astype(np.float32),
            xy[...,1].reshape(48,2).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        per_edge=np.median(np.abs(value[:,1].astype(np.float32)-value[:,0]).reshape(4,12),axis=1)
        spatial=_spatial_support(points,q,self.checks)
        # A channel must cover the exterior spatially, not only yield many ink points.
        score=(min(len(points),40)/40.)*float(np.mean(np.minimum(per_edge,48.)))*float(spatial)
        return dict(score=score,spatial=bool(spatial),features=len(points),edge_contrast=per_edge.tolist())

    def _seed(self, gray, q, index, source_image=None, same_target=False):
        self._gap_anchor_reuses=0
        self._roi_failures=0;self._roi_retry_lk=0;self._roi_lk_checks=0;self._roi_last_q=None
        def features(plane):
            points=self._roi_features(plane,q) if self.feature_policy=='quality' else np.empty((0,2),np.float32)
            if not _spatial_support(points,q,self.checks):
                points=self._full_features(plane,q)
                self.last_feature_detail.update(action='full_boundary_fallback',features=len(points))
            return points
        raw=source_image is not None and source_image.ndim==3 and source_image.shape[2]==2
        flow_gray=self._flow_observation(source_image,gray) if raw and self.lk_channel!='Y' else gray
        points=features(flow_gray);quality=self._channel_quality(flow_gray,q,points)
        audit=raw and (not quality['spatial'] or (not same_target and index-self._channel_audit_index>=12))
        chosen=self.lk_channel if raw else 'Y';scores={chosen:quality};feature_detail=dict(self.last_feature_detail)
        if audit:
            current=chosen;best_score=quality['score'];self._channel_audit_index=index
            # Fixed channel per NEW anchor; forward/backward LK never mixes channels.
            for channel in ('Y','U','V'):
                if channel==current:continue
                plane=gray if channel=='Y' else self._chroma_observation(source_image,gray.shape,channel)
                found=features(plane);check=self._channel_quality(plane,q,found);scores[channel]=check
                if check['spatial'] and (not quality['spatial'] or check['score']>best_score*1.2+2.):
                    chosen,flow_gray,points=channel,plane,found
                    quality=check;best_score=check['score'];feature_detail=dict(self.last_feature_detail)
        self.lk_channel=chosen;self._flow_gray=flow_gray;self._flow_cache=None
        self._channel_evidence=dict(selected=chosen,audited=audit,scores=scores,channel_fixed_until_new_anchor=True,
            same_target_channel_retained=bool(same_target and not audit))
        self.last_feature_detail=dict(feature_detail,channel_selection=self._channel_evidence)
        self.anchor_gray=flow_gray;self.observer.pin(gray)
        self.anchor_q=q.copy();self.anchor_points=points.astype(np.float32).reshape(-1,1,2)
        self.anchor_index=index;self.seed_index=index;self.seed_count+=1;self.lk_cache.anchor(flow_gray)

    def _chroma_observation(self,image,shape,channel):
        from v45_color import chroma_gray
        if not self._chroma_pool or self._chroma_pool[0].shape!=tuple(shape):
            self._chroma_pool=[np.empty(shape,np.uint8) for _ in range(3)]
        plane=next(p for p in self._chroma_pool if p is not self.anchor_gray and p is not self._flow_gray)
        chroma_gray(image,shape,channel,plane);self._flow_gray=plane
        return plane

    def _flow_observation(self,image,gray):
        if self.lk_channel=='Y' or image is None:return gray
        if self._flow_cache is not None and self._flow_cache[0]==self._update_index:
            return self._flow_cache[1]
        plane=self._chroma_observation(image,gray.shape,self.lk_channel)
        self._flow_cache=(self._update_index,plane)
        return plane

    def _full_features(self,gray,q):
        mask = np.zeros_like(gray)
        qi = np.rint(q).astype(np.int32)
        cv2.polylines(mask, [qi], True, 255, 4)
        inside = np.zeros_like(gray)
        cv2.fillConvexPoly(inside, qi, 255)
        mask = cv2.bitwise_and(mask, inside)
        points = cv2.goodFeaturesToTrack(gray, maxCorners=96, qualityLevel=.012,
                                        minDistance=5, mask=mask, blockSize=5)
        points = np.empty((0, 2), np.float32) if points is None else points.reshape(-1, 2)
        for corner in (q if self.feature_policy=='legacy' else ()):
            if not len(points) or np.min(np.linalg.norm(points-corner, axis=1)) > 2:
                points = np.vstack((points, corner))
        from v49_boundary import outer_features
        return outer_features(points,q)

    def initialize(self, image, quad=None, index=1, initial_evidence=None, initial_detection=None):
        if quad is None:
            quad, detection = self._detect(image)
        else:
            detection = initial_detection if isinstance(initial_detection,dict) else {'state': 'supplied_first_frame_detection'}
        if initial_evidence is None:initial_evidence=detection.get('tracking_edge_evidence',{})
        # A hint selects the CURRENT verifier. Only a single-use receipt bound
        # to this still-leased source permits same-frame proof reuse.
        self._vector_boundary=bool(initial_evidence.get('color_vector_proof'))
        gray, scale = self.observer.get(image)
        self.last_gray=gray
        self._update_index=index;self.current_proofs.begin(image,gray,index,scale)
        q = (np.asarray(quad, np.float32)+.5)/scale-.5
        if not _valid(q, gray.shape,checks=self.checks):
            raise ValueError('首帧纸张四角无效或已超出画面')
        self.shape, self.scale = image.shape, scale
        self.q = q.astype(np.float32)
        from v62_boundary import consume_startup_receipt
        from v31_detection import exterior_gate
        receipt=consume_startup_receipt(detection,image,quad,scale)
        if receipt is not None:
            primary,source,source_gate,agreement=receipt
        else:
            # External/mismatched corners receive a fresh proof. Never reuse an
            # old source receipt or let unreliable small Y shift this original.
            checked,evidence=edge_measure(gray,self.q,3.,checks=self.checks)
            initial_gate=exterior_gate(evidence,checked,self.q,3.)
            original=self.q.copy()
            gray_trusted=bool(initial_gate.get('reliable') and initial_gate.get('min_support',0.)>=.80
                and initial_gate.get('max_rms',1e30)<=.65 and initial_gate.get('prediction_correction',1e30)<=.75)
            primary,source,source_gate,agreement=self._source_confirmation(image,gray,
                checked if gray_trusted else original,evidence,new_candidate=True,radius=3.,
                reference=original,gray_reliable=gray_trusted)
        if not source_gate.get('reliable') or not agreement.get('verified') or not _valid(primary,gray.shape,checks=self.checks):
            from run_logging import checkpoint
            checkpoint('INITIAL_CURRENT_LINE_PROOF_FAILED',gate=source_gate,agreement=agreement,
                source_corners=np.asarray(quad).tolist(),hardware_access=False)
            raise ValueError('首帧物理外框未通过当前源图独立四边证明: '+str(agreement.get('reason','four_edge_disagreement')))
        checked,evidence,initial_gate=primary,source,source_gate
        detection.update(initial_source_line_agreement=agreement,original_primary_preserved=True)
        self.q=checked.astype(np.float32)
        self.edge_polarity = evidence['edge_polarity']
        self._vector_boundary=bool(evidence.get('color_vector_proof'))
        from v51_target import border_signature
        self._target_signature=border_signature(evidence)
        detection=dict(detection,initial_edge_gate=initial_gate)
        self.velocity[:] = 0
        self._lk_budget_deferrals=0
        self._seed(gray, self.q, index, image)
        self.last_index = index
        self.started, self.lost = True, False
        self.state='TRACKING'
        self._last_physical_at=time.perf_counter();self._local_next_at=0.;self._local_attempts=0
        return self.corners(), detection

    def write_corners(self,out):
        if out.shape!=(4,2) or out.dtype!=np.float32:raise ValueError('Corner workspace must be4x2 float32')
        np.add(self.q,.5,out=out);np.multiply(out,self.scale,out=out);np.subtract(out,.5,out=out)
        return out

    def corners(self):
        return self.write_corners(np.empty((4,2),np.float32))

    def _lk(self, gray, prediction=None, fast=False, source_image=None):
        attempts=list(self.last_lk_timing.get('attempts',()))
        began=time.perf_counter();cpu=time.thread_time();failure=None
        self.lk_cache.last_checked_timing={}
        self.post_lk.clear();self.post_lk.detail={}
        try:return self._lk_impl(gray,prediction,fast,source_image)
        except BaseException as exc:
            failure=str(exc);raise
        finally:
            detail=dict(self.last_lk_timing,**self.lk_cache.last_checked_timing)
            detail['postlk_native_transaction']=dict(self.post_lk.detail)
            self.post_lk.clear()
            detail.pop('attempts',None)
            detail.update(search='fast' if fast else 'full',accepted=failure is None,
                reason=failure,wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu)
            attempts.append(detail)
            self.last_lk_timing=dict(detail,attempts=attempts,attempt_count=len(attempts),
                total_attempt_wall_s=sum(v['wall_s'] for v in attempts),
                total_attempt_thread_cpu_s=sum(v['thread_cpu_s'] for v in attempts))

    @geometry_transaction
    def _lk_impl(self, gray, prediction=None, fast=False, source_image=None):
        began=time.perf_counter()
        self.last_lk_timing={}
        flow_gray=self._flow_observation(source_image,gray)
        p = self.anchor_points
        if len(p)<4:raise ValueError('外边框有效特征少于4个')
        params = dict(winSize=(21, 21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, .02))
        initial=None
        if prediction is not None:
            self._lk_anchor_quad[:]=self.anchor_q;self._lk_prediction_quad[:]=prediction
            motion=cv2.getPerspectiveTransform(self._lk_anchor_quad,self._lk_prediction_quad)
            initial=self._lk_initial[:len(p)]
            cv2.perspectiveTransform(p,motion,dst=initial)
        if fast:params.update(maxLevel=2,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,12,.02))
        checked=self.lk_cache.checked(flow_gray,p,initial,self.anchor_q,self.q,self.last_index,params['maxLevel'],params['criteria'][1]) if self.checks=='auto' else None
        native=None if checked is not None else self.lk_cache.track(flow_gray,p,initial=initial,levels=params['maxLevel'],iterations=params['criteria'][1])
        if checked is not None:
            q,retained,filter_detail,times=checked;self.last_lk_timing.update(times)
            fit_began=time.perf_counter()
        else:
            if native is None:
                forward, status, error = cv2.calcOpticalFlowPyrLK(self.anchor_gray, flow_gray, p, initial,
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW if initial is not None else 0, **params)
            else:
                forward,status,error,backward,status_b=native
            if forward is None:
                raise ValueError('LK 没有返回特征')
            if native is None:
                backward, status_b, _ = cv2.calcOpticalFlowPyrLK(flow_gray, self.anchor_gray, forward, p.copy(),
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **params)
            if backward is None:
                raise ValueError('LK 反向跟踪失败')
            self.last_lk_timing['forward_backward_flow_s']=time.perf_counter()-began
            fit_began=time.perf_counter()
            from v87_v74_native import filter_lk
            filtered=filter_lk(p,forward,backward,status,status_b,error,self.anchor_q,self.q,gray.shape) if self.checks=='auto' else None
            if filtered is not None:
                q,retained,filter_detail=filtered
            else:
                fb = np.linalg.norm(backward.reshape(-1, 2)-p.reshape(-1, 2), axis=1)
                good = status.ravel().astype(bool) & status_b.ravel().astype(bool)
                good &= (fb < 1.4) & (error.ravel() < 30)
                if good.sum() < 4:
                    raise ValueError('外边框有效特征少于4个')
                a=p.reshape(-1,2)[good];z=forward.reshape(-1,2)[good]
                motion_model='projective_candidate'
                if len(a)<8:
                    affine,inliers=cv2.estimateAffinePartial2D(a,z,method=cv2.RANSAC,
                        ransacReprojThreshold=1.6,maxIters=1000,confidence=.99,refineIters=10)
                    H=None if affine is None else np.vstack((affine,[0.,0.,1.]))
                    motion_model='similarity_candidate'
                else:
                    H,inliers=cv2.findHomography(a,z,cv2.RANSAC,1.6,maxIters=1000,confidence=.99)
                    if H is not None and inliers is not None and inliers.sum()<8:
                        affine,inliers=cv2.estimateAffinePartial2D(a,z,method=cv2.RANSAC,
                            ransacReprojThreshold=1.6,maxIters=1000,confidence=.99,refineIters=10)
                        H=None if affine is None else np.vstack((affine,[0.,0.,1.]))
                        motion_model='similarity_candidate'
                if H is None or not np.isfinite(H).all() or inliers is None:
                    raise ValueError('边框特征不能确定运动映射')
                retained=forward.reshape(-1,2)[good][inliers.ravel().astype(bool)]
                original=p.reshape(-1,2)[good][inliers.ravel().astype(bool)]
                if not _spatial_support(original,self.anchor_q,self.checks):
                    raise ValueError("边缘特征分布退化，不能只凭RANSAC内点率")
                fraction = float(inliers.mean())
                if inliers.sum() < 4 or fraction < .65:
                    raise ValueError('边框特征几何一致性不足')
                q = cv2.perspectiveTransform(self.anchor_q.reshape(1, 4, 2), H).reshape(4, 2)
                if not _valid(q, gray.shape, self.q,self.checks):
                    raise ValueError('跟踪四角越界或形变异常')
                filter_detail=dict(features=len(p),good_features=int(good.sum()),
                    inlier_fraction=fraction,fb_median=float(np.median(fb[good])),filter_backend='opencv_python_ransac',motion_model=motion_model,
                    current_four_edges_required=True)
        if checked is None:self.last_lk_timing['fb_filter_ransac_s']=time.perf_counter()-fit_began
        self.last_lk_timing['motion_fit']=dict(filter_detail)
        travel=float(np.max(np.linalg.norm(q-self.q,axis=1)))
        shortest=float(np.min(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)))
        cap=max(3.,min(7.5,.06*shortest,24./float(np.max(self.scale))))
        radius=float(np.clip(max(3.,self._edge_radius)+.10*travel,3.,cap))
        unlocked_radius=radius
        static_reference=bool(self._still_calm and self._still_q is not None)
        if static_reference:
            # LK remains complete. Its raw motion model can release the lock
            # before CURRENT edge selection, independently of output smoothing.
            lock_motion=float(np.max(np.linalg.norm(q-self._still_q,axis=1)))
            if lock_motion>1.:
                self._release_static_edges('current_FB_motion')
            else:
                q=self._still_q.copy();radius=self._still_radius
        # ⭐ 2026-10-28 计时：post_lk 一次 native 事务（24网格+64网格）的完整墙钟，
        #    与它自己报的 `transaction_s` 对比即可看出 Python 侧的包装开销。
        postlk_t=time.perf_counter()
        fused=self.post_lk.measure(gray,q,radius,source_image,self.scale,self._update_index,self.checks,self.edge_polarity)
        self.last_lk_timing['postlk_measure_s']=time.perf_counter()-postlk_t
        measured,evidence=edge_measure(gray,q,radius,self.checks) if fused is None else fused
        from v62_policy import search_gate,sample_locked_color
        from v51_target import border_signature
        def current_search(e,c):
            g=search_gate(e,c,q,radius)
            flips=0 if e.get('color_vector_proof') else sum(a*b<0 for a,b in zip(self.edge_polarity,e.get('edge_polarity',[])))
            return dict(g,reliable=bool(g['reliable'] and flips==0),polarity_flips=flips)
        lk_gate=current_search(evidence,measured)
        if source_image is not None and not lk_gate['reliable']:
            measured,evidence=sample_locked_color(source_image,self.scale,q,64,self._frame_deadline,
                self._target_signature,half_source=min(24.,max(3.,radius*float(np.max(self.scale)))),
                lock_physical=bool(self._still_calm))
            lk_gate=current_search(evidence,measured)
        lock_required=bool(unlocked_radius>3. or lk_gate.get('prediction_correction',0.)>1.5 or evidence.get('color_vector_proof'))
        if lk_gate['reliable'] and lock_required:
            # Wider first search cannot justify itself. Independently spaced
            # source Y64 (or YUV64) must agree with all four refined edges.
            from v62_policy import stable_fb_context
            stable_fb=stable_fb_context(filter_detail,travel,lk_gate['prediction_correction'],
                self.lost,getattr(self,'source_elapsed_s',None),
                processing_gap=bool(getattr(self,'source_processing_gap',False)))
            second,independent,strict_gate,agreement=self._source_confirmation(source_image,gray,measured,evidence,
                radius=radius,reference=q,gray_reliable=lk_gate['reliable'],stable_fb=stable_fb)
            self.last_lk_timing['stable_FB_context']=stable_fb
            verified=(strict_gate is not None and strict_gate['reliable'] and agreement['verified']
                and _valid(second,gray.shape,self.q,self.checks))
            self.last_lk_timing['source_line_agreement']=agreement
            self.last_lk_timing['independent_source_gate']=strict_gate
            lk_gate['independent_source_verified']=bool(verified)
            if verified:measured,evidence=second,independent
            else:lk_gate['reliable']=False
        self.last_lk_timing['motion_adaptive_exterior_radius']=radius
        self.last_lk_timing['search_proof_separated']=True
        if not lk_gate['reliable']:
            self.last_lk_timing['failed_exterior_gate']=dict(lk_gate)
            self.last_lk_timing['failed_LK_corners']=q.tolist()
            self.last_lk_timing.update(failure_class='current_exterior_mismatch',
                redundant_full_retry_skipped=True)
            raise LKExteriorMismatch('LK 四角未通过四条纸张外边缘检查')
        self.last_lk_timing['current_four_edge_gate']=dict(lk_gate)
        self._promoted_points=np.ascontiguousarray(retained,dtype=np.float32)
        return measured, dict(evidence, **filter_detail)

    def _boundary(self,*args,**kwargs):
        from v31_detection import current_boundary
        kwargs.setdefault('prefer_vector',self._vector_boundary)
        kwargs.setdefault('boundary_prior',self._target_signature)
        candidate,evidence,gate=current_boundary(*args,**kwargs)
        if gate.get('reliable') and evidence.get('color_vector_proof'):self._vector_boundary=True
        return candidate,evidence,gate

    @geometry_transaction
    def _source_confirmation(self,image,gray,candidate,evidence,new_candidate=False,radius=3.,
            reference=None,gray_reliable=None,stable_fb=False,proof_deadline=None,proof_cpu_s=None):
        """Wide candidate search is separate from a narrow current-line proof.

        Normal tracking locks the measured CURRENT line. New admission may
        search from its immutable proposal, then locks its current source64
        line. Independent 24/64 samples never receive the motion search band.
        """
        from v49_boundary import actual_source64,array_key
        from v41_quad import original_y_boundary
        from v31_detection import current_boundary,exterior_gate
        from v51_target import border_signature
        from v62_policy import proof_band,line_lock,current_agreement,declare_current_y24,sample_locked_color,search_gate
        narrow,half=proof_band(self.scale,evidence)
        entry_s=time.perf_counter()
        prepared=(self.post_lk.take_source(image,gray,candidate,self.scale,self._update_index,narrow)
            if not new_candidate and gray_reliable is not False and proof_deadline is None and proof_cpu_s is None else None)
        decode_s=time.perf_counter()-entry_s
        begin=time.perf_counter() if prepared is None else prepared['begin']
        cpu=time.thread_time() if prepared is None else prepared['cpu'];deadline=begin+.40
        cpu_limit=.18 if new_candidate else .12
        if proof_deadline is not None:deadline=min(deadline,float(proof_deadline))
        if proof_cpu_s is not None:cpu_limit=min(cpu_limit,max(0.,float(proof_cpu_s)))
        wall_limit=max(0.,deadline-begin)
        proof_gate_radius=3.  # Keep geometry allowance independent of sample width.
        details=dict(budget_basis='proof_thread_CPU_and_separate_wall_guard',
            cpu_budget_s=cpu_limit,wall_guard_s=wall_limit,prior_frame_deadline_not_reused=proof_deadline is None,
            search_radius_tracking=float(radius),proof_radius_tracking=narrow,
            proof_half_source_pixels=half,proof_gate_radius=proof_gate_radius,
            motion_search_band_reused_for_proof=False,
            strict_new_candidate=bool(new_candidate),same_target_FB=bool(stable_fb and not new_candidate),
            postlk_native_source_prepared=prepared is not None,repeated_source_sampling_skipped=prepared is not None,
            # ⭐ 2026-10-28 计时：take_source 解码（复用 post_lk 缓冲）本身的耗时。
            decode_s=decode_s)
        memo_token=None
        def available():return time.perf_counter()<deadline and time.thread_time()-cpu<cpu_limit
        def gate(e,q,p,r):
            return exterior_gate(e,q,p,r) if new_candidate else self._edge_gate(e,q,p,r)
        def done(q,e,g,a):
            if memo_token is not None and g.get('reliable') and a.get('verified'):
                self.current_proofs.remember(memo_token,q,e,g,a)
            details.update(wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu,
                wall_guard_hit=time.perf_counter()>=deadline,cpu_budget_hit=time.thread_time()-cpu>=cpu_limit,
                scope='cooperative between calls; native calls cannot be preempted')
            a=dict(a,current_proof_timing=dict(details),old_H_not_used=True)
            self.last_source_confirmation=dict(a,final_gate=dict(g))
            return q,e,g,a
        failed=dict(reliable=False)
        if image is None:return done(candidate,dict(valid=False),failed,dict(verified=False,reason='no_current_source'))
        key=array_key(image);candidate=np.asarray(candidate,np.float32).copy()
        reference=np.asarray(candidate if reference is None else reference,np.float32).copy()
        if gray_reliable is None:
            gray_reliable=bool(gate(evidence,candidate,reference,radius).get('reliable'))
        memo_token=self.current_proofs.token(image,gray,self._update_index,self.scale,candidate,reference,
            radius,new_candidate,gray_reliable,stable_fb)
        reused_result=self.current_proofs.get(memo_token)
        if reused_result is not None:
            q,e,g,a=reused_result
            a=dict(a,current_same_frame_proof_reused=True,repeated_border_search_skipped=True,
                current_proof_timing=dict(metadata_receipt_reuse=True,wall_s=time.perf_counter()-begin,
                    thread_cpu_s=time.thread_time()-cpu,native_sampling_repeated=False))
            self.last_source_confirmation=dict(a,final_gate=dict(g))
            return q,e,g,a
        details.update(original_reference_preserved=True,reference_corners=reference.tolist(),
            gray_reliable=bool(gray_reliable),color_seed='original_reference' if new_candidate else 'current_locked_line')
        # Strong CURRENT Y and independently spaced source-Y64 share a narrow
        # normal neighborhood. A historical color hint cannot override this.
        if gray_reliable and evidence.get('valid') and not evidence.get('color_vector_proof') and (available() or prepared is not None):
            # Finish the original gates for already completed CURRENT source64;
            # no new search may use the completed-call budget exception.
            proof=original_y_boundary(image,self.scale,candidate,radius=narrow) if prepared is None else prepared['proof']
            if proof is not None:
                yq,ye=proof;yg=gate(ye,yq,candidate,proof_gate_radius);lock=line_lock(candidate,yq)
                first=declare_current_y24(evidence)
                ya=current_agreement(candidate,yq,first,ye,self.scale,key,
                    stable_fb=stable_fb and not new_candidate)
                details['Y_attempt']=dict(gate=yg,agreement=ya,line_lock=lock)
                details['y_gate_wall_s']=time.perf_counter()-begin
                if yg.get('reliable') and ya.get('verified') and lock.get('verified'):
                    ya.update(boundary_definition='locked_current_Y24_independent_source_Y64',
                        current_source64_reused=prepared is not None,line_lock=lock)
                    return done(yq,ye,yg,ya)
        if not available():
            return done(candidate,evidence,failed,dict(verified=False,reason='current_proof_budget_exhausted',deadline_hit=True))
        # For new candidates only, obtain a broad current source64 primary from
        # the untouched transported proposal. Unreliable gray cannot move it.
        search=reference if new_candidate else candidate
        reused=bool(actual_source64(evidence,key) and evidence.get('color_vector_proof'))
        primary,source=candidate,evidence;paired_secondary=None;pair_detail={}
        pair_trusted=bool(not new_candidate and stable_fb and gray_reliable and evidence.get('valid')
            and not evidence.get('color_vector_proof') and min(evidence.get('edge_support',[0.]*4))>=.80
            and max(evidence.get('edge_rms',[1e30]*4))<=.65
            and gate(evidence,candidate,reference,radius).get('prediction_correction',1e30)<=.75)
        if pair_trusted and not reused:
            from v62_policy import sample_locked_pair
            paired=sample_locked_pair(image,self.scale,candidate,deadline,evidence,half,
                max(.0005,cpu_limit-(time.thread_time()-cpu)))
            if paired is not None:
                (primary,source),paired_secondary,pair_detail=paired
                details['paired_native_transaction']=pair_detail
        if not reused:
            if paired_secondary is not None:
                first=gate(source,primary,candidate,proof_gate_radius)
            elif new_candidate:
                primary,source=sample_locked_color(image,self.scale,search,64,deadline,
                    half_source=min(24.,max(3.,float(radius)*float(np.max(self.scale)))),lock_physical=False)
                first=search_gate(source,primary,search,radius)
            else:
                primary,source=sample_locked_color(image,self.scale,search,64,deadline,border_signature(evidence),half_source=half,lock_evidence=evidence)
                first=gate(source,primary,search,proof_gate_radius)
            details['color_primary_gate']=first
            provenance=actual_source64(source,key)
            if not first.get('reliable') or not provenance:
                return done(primary,source,failed,dict(verified=False,
                    reason='current_raw_source64_shift_or_quality_rejected' if provenance else 'current_raw_source64_not_completed',
                    deadline_hit=source.get('deadline_hit',False),source64_provenance_verified=bool(provenance),rejected_gate=dict(first)))
        if not new_candidate and source.get('color_vector_proof'):
            from v62_boundary import layer_continuity
            continuity=layer_continuity(self._target_signature,source)
            details['physical_layer_continuity']=continuity
            if not continuity['verified']:
                return done(primary,source,failed,dict(verified=False,reason='current_signed_physical_layer_changed'))
        # Stable tracking fixes BOTH sample layouts around one current measured
        # line. New admission fixes them around its just-measured source64 line.
        if new_candidate:
            narrow,half=proof_band(self.scale,source)
            details.update(proof_radius_tracking=narrow,proof_half_source_pixels=half)
            if reused:
                first=search_gate(source,primary,reference,radius)
                details['color_primary_gate']=first
                if not first.get('reliable'):
                    return done(primary,source,failed,dict(verified=False,reason='reused_primary_search_bounds_rejected'))
        # A weak/broad tracking-Y line is a search proposal. A fresh strong
        # source64 line can establish the narrow reference after bounded
        # same-target checks, rather than proving a different old-Y layer.
        gray_search_gate=gate(evidence,candidate,reference,radius)
        gray_trusted=bool(gray_reliable and evidence.get('valid') and not evidence.get('color_vector_proof') and
            gray_search_gate.get('prediction_correction',1e30)<=.75 and
            min(evidence.get('edge_support',[0.]*4))>=.80 and
            max(evidence.get('edge_rms',[1e30]*4))<=.65)
        raw_lock=line_lock(candidate,primary)
        raw_rebase=bool(not new_candidate and not gray_trusted and actual_source64(source,key)
            and source.get('valid') and source.get('supported_edges')==4
            and min(source.get('edge_support',[0.]*4))>=.80
            and max(source.get('edge_rms',[1e30]*4))<=.65
            and raw_lock.get('line_normal_difference',1e30)<=1.25
            and raw_lock.get('corner_difference',1e30)<=2.)
        details['fresh_source64_reference']=dict(used=raw_rebase,raw_shift=raw_lock,
            old_tracking_Y_is_proposal_only=raw_rebase,independent24_still_required=True)
        locked=np.asarray(primary if new_candidate or raw_rebase else candidate,np.float32).copy()
        primary_lock=line_lock(locked,primary)
        if not primary_lock.get('verified'):
            return done(primary,source,failed,dict(verified=False,reason='source64_left_locked_current_line',line_lock=primary_lock))
        # A completed native pair may finish its existing safety gates after
        # the compute checkpoint; it must not start another sampling call.
        complete_pair=bool(paired_secondary is not None and pair_detail.get('complete'))
        if not available() and not complete_pair:
            return done(primary,source,failed,dict(verified=False,reason='independent_proof_budget_exhausted',deadline_hit=True))
        if paired_secondary is not None and np.array_equal(locked,candidate):
            observed,current=paired_secondary
        else:observed,current=sample_locked_color(image,self.scale,locked,24,deadline,border_signature(source),half_source=half,lock_evidence=source)
        checked=gate(current,observed,locked,proof_gate_radius)
        secondary_lock=line_lock(locked,observed)
        agreement=current_agreement(observed,primary,current,source,self.scale,key,
            stable_fb=stable_fb and not new_candidate)
        agreement.update(verified=bool(agreement.get('verified') and primary_lock.get('verified') and secondary_lock.get('verified')),
            current_source64_reused=reused,boundary_definition='locked_current_source64_and_independent24',
            normal_half_window_source_pixels=half,secondary_radius_tracking=narrow,
            primary_line_lock=primary_lock,secondary_line_lock=secondary_lock,
            independent_deadline_hit=current.get('deadline_hit',False),
            current_primary_prior_used=border_signature(source) is not None)
        if not secondary_lock.get('verified'):agreement['reason']='independent24_left_locked_current_line'
        return done(primary,source,checked,agreement)

    def _edge_gate(self,evidence,candidate,prediction,radius):
        supports=evidence.get('edge_support',[0.]*4)
        rms=evidence.get('edge_rms',[1e30]*4)
        correction=float(np.max(np.linalg.norm(candidate-prediction,axis=1)))
        raw_flips=sum(a*b<0 for a,b in zip(self.edge_polarity,evidence.get('edge_polarity',[])))
        # Weak Y can reverse sign on a chromatic exterior. Its raw sign is
        # diagnostic only after the coherent current YUV proof passes all
        # four support/RMS/geometry gates; ordinary Y keeps its polarity gate.
        flips=0 if evidence.get('color_vector_proof') else raw_flips
        reliable=(evidence.get('valid',False) and evidence.get('supported_edges',0)==4
            and evidence.get('refined_corners',0)==4 and min(supports)>=.60
            and max(rms)<=1.0 and correction<=radius*.65 and flips==0)
        return dict(reliable=bool(reliable),min_support=float(min(supports)),max_rms=float(max(rms)),
            prediction_correction=correction,polarity_flips=flips,raw_Y_polarity_flips=raw_flips,radius=radius)

    def _stabilize_current_edges(self,image,gray,candidate,evidence,gate,prediction,previous):
        """Current profiles decide every output; joint geometry only selects work."""
        result=self.stability.measure(gray,previous,prediction,candidate,evidence,
            allow_filter=not evidence.get('color_vector_proof',False))
        if result is None:return candidate,evidence,gate,False
        filtered,updated,detail=result;self.stability_detail=detail
        self._last_measured_motion=detail['raw_motion']
        if detail['physical_layer_suspect']:
            now=time.perf_counter();detail['local_lock_attempted']=False
            if now>=self._edge_lock_next_at:
                detail['local_lock_attempted']=True;cpu=time.thread_time()
                # One narrow CURRENT Y measurement around the physical prediction.
                tight,tight_e=edge_measure(gray,prediction,1.75,self.checks)
                tight_g=self._edge_gate(tight_e,tight,prediction,1.75)
                from v62_policy import line_lock
                lock=line_lock(prediction,tight)
                strong=(tight_g.get('reliable') and tight_g['min_support']>=.80
                    and tight_g['max_rms']<=.65 and lock.get('verified'))
                if strong:
                    q,e,g,a=self._source_confirmation(image,gray,tight,tight_e,reference=prediction,
                        gray_reliable=True,radius=1.75,proof_deadline=min(now+.18,self._frame_deadline or now+.18),
                        proof_cpu_s=max(0.,.08-(time.thread_time()-cpu)))
                    strong=bool(g.get('reliable') and a.get('verified') and line_lock(prediction,q).get('verified'))
                    if strong:
                        detail.update(local_lock_verified=True,local_lock_wall_s=time.perf_counter()-now,
                            local_lock_thread_cpu_s=time.thread_time()-cpu,current_source_proof_reused=False)
                        self._edge_lock_failures=0;self._edge_lock_next_at=0.
                        self._current_motion_values=None;self.accumulated_drift[:]=self._stability_drift_start
                        return q,e,g,True
                self._edge_lock_failures=min(3,self._edge_lock_failures+1)
                self._edge_lock_next_at=now+min(.6,.15*(2**(self._edge_lock_failures-1)))
                detail.update(local_lock_verified=False,local_lock_wall_s=time.perf_counter()-now,
                    local_lock_thread_cpu_s=time.thread_time()-cpu,next_local_lock_at=self._edge_lock_next_at)
            # Do not authorize an isolated layer jump by four-corner geometry alone.
            return candidate,evidence,dict(gate,reliable=False,physical_layer_ambiguous=True),False
        if detail['filtered']:
            checked=self._edge_gate(updated,filtered,prediction,self._edge_radius)
            if checked.get('reliable'):
                self._current_motion_values=None;self.accumulated_drift[:]=self._stability_drift_start
                return filtered,updated,checked,False
            detail.update(filtered=False,filter_rejected_by_original_gate=True)
        return candidate,evidence,gate,False

    def _exit_verified_calm_burst(self,mode,candidate,previous,prediction,index):
        """Exit only after complete CURRENT FB plus independent same-edge proof."""
        if mode!='lk_measured' or self.anchor_index!=index:return
        timing=self.last_lk_timing;proof=timing.get('source_line_agreement',{})
        gate=timing.get('current_four_edge_gate',{})
        motion=float(np.max(np.linalg.norm(candidate-previous,axis=1)))
        correction=float(np.max(np.linalg.norm(candidate-prediction,axis=1)))
        normalized=motion/max(1.,float(getattr(self,'source_step',1.)))
        okay=('forward_backward_flow_s' in timing and timing.get('stable_FB_context',False)
            and proof.get('verified') and gate.get('reliable') and gate.get('min_support',0.)>=.80
            and gate.get('max_rms',1e30)<=.65 and motion<=1.25 and normalized<=.45 and correction<=.75
            and len(self.anchor_points)>=4)
        timing['calm_burst_exit']=dict(verified=bool(okay),motion_pixels=motion,
            motion_per_capture_frame=normalized,prediction_correction=correction,
            complete_FB_and_independent_edges_required=True)
        if okay:
            self._burst_until=index-1
            self.motion_ema=min(self.motion_ema,normalized);self.correction_ema=min(self.correction_ema,correction)
            self.accumulated_drift.fill(0.);self.drift_budget=0.
            self._edge_lock_failures=0;self._edge_lock_next_at=0.

    def _motion_schedule(self,gate,candidate,prediction,previous,age):
        from v87_v74_native import motion_values
        values=self._current_motion_values;self._current_motion_values=None
        if values is None:
            values=motion_values(candidate,prediction,previous,self.anchor_q,self.accumulated_drift) if self.checks=='auto' else None
        if values is None:
            motion=float(np.max(np.linalg.norm(candidate-previous,axis=1)))
            self.accumulated_drift+=(candidate-prediction)
            drift=float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))
            diagonal=float(np.linalg.norm(previous[2]-previous[0]))
            travel=float(np.max(np.linalg.norm(candidate-self.anchor_q,axis=1)))
        else:motion,_,drift,diagonal,travel=values
        source_step=max(1.,float(getattr(self,'source_step',1.)))
        normalized=motion/source_step
        elapsed=getattr(self,'source_elapsed_s',None)
        self.motion_ema=.8*self.motion_ema+.2*normalized
        self._last_measured_motion=float(motion)
        self.correction_ema=.8*self.correction_ema+.2*gate['prediction_correction']
        self.drift_budget+=max(0.,gate['prediction_correction']-.75*gate['max_rms'])
        quality=max(.25,min(1.,gate['min_support']))
        target=max(self.lk_min_gap,min(self.lk_max_gap,round(self.lk_max_gap*quality/(1.+.45*self.motion_ema+.7*self.correction_ema))))
        urgent=(motion>4. or normalized>2. or gate['prediction_correction']>1.5
                or gate['min_support']<.75 or gate['max_rms']>.75)
        if urgent:self._burst_until=self._update_index+3
        # Confidence/motion can override the quiet-scene minimum. FB is never
        # skipped; a successful check promotes current points/pyramids together.
        burst=self._update_index<=self._burst_until
        reason=('hard_maximum_age' if age>=self.lk_max_gap else
                'motion_burst' if burst and age>=1 else
                'accumulated_drift' if age>=self.lk_min_gap and (drift>2. or self.drift_budget>6.) else
                'anchor_displacement' if age>=self.lk_min_gap and travel>max(16.,max(1.,diagonal)*.18) else
                'adaptive_age' if age>=target else None)
        return reason,dict(target_gap=target,hard_max_gap=self.lk_max_gap,min_gap=self.lk_min_gap,
            motion_pixels=motion,motion_per_capture_frame=normalized,source_step=source_step,
            source_elapsed_s=elapsed,processing_gap=bool(getattr(self,'source_processing_gap',False)),motion_ema=self.motion_ema,correction_ema=self.correction_ema,
            burst_active=burst,burst_until_processed_frame=self._burst_until,
            accumulated_drift_pixels=drift,accumulated_excess_residual=self.drift_budget,
            anchor_travel_pixels=travel,min_support=gate['min_support'],prediction_correction=gate['prediction_correction'])

    def _lk_current(self,gray,prediction,image):
        from v62_policy import LKPhaseBudget,LKWorkBudgetExceeded
        budget=LKPhaseBudget();prior_deadline=self._frame_deadline
        self._frame_deadline=budget.deadline
        displacement=float(np.max(np.linalg.norm(prediction-self.anchor_q,axis=1)))
        deep=(displacement>12. or float(getattr(self,'source_step',1.))>=6.)
        started=time.perf_counter()
        try:
            try:
                candidate,evidence=self._lk(gray,prediction,fast=not deep,source_image=image)
                self.last_lk_timing.update(search_policy='direct_full_large_motion' if deep else 'predicted_fast',
                    predicted_anchor_displacement=displacement)
                return candidate,evidence
            except LKExteriorMismatch:
                self._promoted_points=None
                raise  # Repeating the same motion solve cannot prove another edge.
            except (ValueError,cv2.error) as exc:
                self._promoted_points=None
                if deep:raise
                if not budget.retry_allowed():
                    raise LKWorkBudgetExceeded('Complete fast FB attempt finished; full retry deferred by CPU/wall guard') from exc
                spent=time.perf_counter()-started
                candidate,evidence=self._lk(gray,prediction,fast=False,source_image=image)
                self.last_lk_timing.update(search_policy='full_after_fast',fast_attempt_s=spent,
                    predicted_anchor_displacement=displacement)
                return candidate,evidence
        finally:
            self.last_lk_timing['entry_budget']=budget.summary()
            self._frame_deadline=prior_deadline

    def _strict_current_reanchor(self,image,gray,prediction,candidate,evidence):
        radius=self._edge_radius
        gate=self._edge_gate(evidence,candidate,prediction,radius)
        if not gate['reliable']:
            from v31_detection import current_boundary
            candidate,evidence,_=self._boundary(image,gray,self.scale,prediction,
                measured=candidate,evidence=evidence,checks=self.checks,radius=radius,fast_only=True,deadline=self._frame_deadline,
                expected_polarity=self.edge_polarity,color_profiles=64,prefer_color=True,prefer_vector=True)
            gate=self._edge_gate(evidence,candidate,prediction,radius)
        strict=lambda g:g['reliable'] and g['min_support']>=.80 and g['max_rms']<=.65
        if not strict(gate) or gate['prediction_correction']>1.:return None
        second,independent,checked,agreement=self._source_confirmation(image,gray,candidate,evidence)
        if not strict(checked) or not agreement['verified']:return None
        if not _valid(second,gray.shape,self.q,self.checks):return None
        return second,independent,dict(state='current_four_edges_twice_verified',
            first_validation=gate,second_validation=checked,source_line_agreement=agreement,old_H_not_used=True)

    def _recover_current_edges(self,gray,candidate,evidence,prediction,previous,gate,reason):
        # Only a correspondence-shortage failure may use stricter independently
        # measured CURRENT outer edges. Other LK/geometry failures fully redetect.
        shortage=('少于4' in reason or 'consistency rejected: -2' in reason)
        if (not shortage or candidate is None or not gate.get('reliable')
            or self.edge_recovery_count>=2 or gate['min_support']<.80
            or gate['max_rms']>.65 or gate['prediction_correction']>1.0):return None
        measured,checked=edge_measure(gray,candidate,3.,self.checks)
        independent=self._edge_gate(checked,measured,candidate,3.)
        if (not independent['reliable'] or independent['min_support']<.80
            or independent['max_rms']>.65 or independent['prediction_correction']>.6
            or not _valid(measured,gray.shape,previous,self.checks)):return None
        return measured,checked,dict(state='current_outer_edges_verified',lk_shortage=reason,
            validation=independent,consecutive_recoveries=self.edge_recovery_count+1)

    def _detect_nearby(self,image,prediction,scale,bounded=False,force_full=False):
        # Alternate ROI-first and full-view attempts after repeated failure.
        # Both share ONE candidate/time budget; a spent ROI budget is not reset.
        # A failed current exterior is evidence that the old ROI is unsafe.
        # Search the existing whole small Y, then refine its NEW candidate.
        full_first=force_full or (bounded and (self.lost or self._recovery_attempts%2==0))
        route='current_exterior_mismatch_global_Y' if force_full else ('lost_or_alternate_global_Y' if full_first else 'verified_prediction_ROI')
        raw_yuyv=image.ndim==3 and image.shape[2]==2
        # A full detector is kept as final fallback. ROI candidates must also
        # match the previous current-frame geometry and measured exterior edges.
        q=((prediction+.5)*scale-.5).astype(np.float32);h,w=image.shape[:2]
        pad=max(24.,float(max(scale))*12.)
        lo=np.maximum(0,np.floor(q.min(axis=0)-pad)).astype(int)
        hi=np.minimum([w,h],np.ceil(q.max(axis=0)+pad)).astype(int)
        x0,y0=map(int,lo);x1,y1=map(int,hi)
        if raw_yuyv:
            # A local YUYV view must start on Y0/U and contain complete pairs.
            x0=(x0//2)*2;x1=min(w,((x1+1)//2)*2)
        if not full_first and (x1-x0)*(y1-y0)<.80*w*h and min(x1-x0,y1-y0)>=32:
            began=time.perf_counter()
            try:
                from v31_detection import recovery_view_scope
                with recovery_view_scope((x0,y0)):local,info=self._detect(image[y0:y1,x0:x1])
                full=np.asarray(local,np.float32)+[x0,y0]
                observed=((full+.5)/scale-.5).astype(np.float32)
                if not _valid(observed,self.last_gray.shape,self.q,self.checks):raise ValueError('ROI detection geometry mismatch')
                from v69_policy import read_current_receipt as read_receipt
                receipt=read_receipt(info,image,self.last_gray,scale,self._update_index,full)
                if receipt is None:
                    measured,e=edge_measure(self.last_gray,observed,3.,self.checks)
                    g=self._edge_gate(e,measured,observed,3.)
                    if not g['reliable']:
                        from v31_detection import current_boundary
                        measured,e,_=self._boundary(image,self.last_gray,scale,observed,measured=measured,evidence=e,checks=self.checks)
                        g=self._edge_gate(e,measured,observed,3.)
                    if not g['reliable']:raise ValueError('ROI detection does not match current exterior')
                return full,dict(info,roi=[x0,y0,x1,y1],recovery_backend='p1_predicted_roi',recovery_route=route,stale_prediction_ROI_skipped=False,roi_detection_s=time.perf_counter()-began)
            except (ValueError,cv2.error,TypeError):
                if bounded:
                    from v31_detection import _budget_check
                    from v31_detection import _DetectionStop,QuadDetectionError,_RECOVERY_BUDGET
                    try:_budget_check('ROI_to_full_fallback')
                    except _DetectionStop as exc:
                        raise QuadDetectionError(str(exc),_RECOVERY_BUDGET.get().summary()) from exc
        full,info=self._detect(image)
        return full,dict(info,recovery_backend='p1_full_frame',recovery_route=route,
            stale_prediction_ROI_skipped=bool(force_full))

    def _search_radius(self,previous,step,source_gap):
        speed=max(float(np.max(np.linalg.norm(self.velocity,axis=1))),self.motion_ema)
        drift=float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))
        uncertainty=.25*speed*max(0.,step-1.)+.15*drift+.5*self.correction_ema+(1. if source_gap else 0.)
        shortest=float(np.min(np.linalg.norm(np.roll(previous,-1,axis=0)-previous,axis=1)))
        cap=max(3.,min(6.,.06*shortest))
        return float(np.clip(3.+uncertainty,3.,cap)),dict(radius_cap=cap,prediction_uncertainty=uncertainty,
            source_step=step,speed_per_capture_frame=speed,all_four_edges_required=True)

    def _release_static_edges(self,reason):
        self._still_q=None;self._still_samples=None;self._still_calm=False
        self._still_radius=3.
        self._still_release=reason

    def _pin_static_edges(self,sample_shape):
        # Only once on entry. These are indices into the ALREADY computed
        # 60x80 difference, not another image read or detector invocation.
        q=self.corners();fractions=np.linspace(.08,.92,24)[:,None]
        points=[]
        for a,b in zip(q,np.roll(q,-1,axis=0)):
            edge=b-a;normal=np.array([-edge[1],edge[0]])/max(1.,float(np.linalg.norm(edge)))
            base=a+fractions*edge
            for offset in (-8.,0.,8.):points.append(base+offset*normal)
        xy=np.rint(np.concatenate(points)/8.).astype(np.intp)
        h,w=sample_shape;xy[:,0]=np.clip(xy[:,0],0,w-1);xy[:,1]=np.clip(xy[:,1],0,h-1)
        self._still_samples=np.unique(xy[:,1]*w+xy[:,0])
        self._still_q=self.q.copy();self._still_release=None
        # Keep the original band for already stable/soft covers. Narrow only
        # after actual low-motion corrections indicate a neighboring edge.
        correction=max(self.correction_ema,float(self._hold_gate.get('prediction_correction',0.)))
        self._still_radius=2. if correction>.75 else 3.

    def _static_hold(self, image, index, began, cpu, lost_at_entry):
        """⭐ 静止保持：60x80 Y 采样（预分配）+ 3 帧中值 + 自适应噪声底。

        rev4：固定阈值在高噪声场景会永远进不去（`hold_changed` 中位 5.6% > 3%），
        且 120x160 采样每帧约 9 ms。这里改成 60x80 + 预分配 + 噪声自适应。
        """
        self._still_calm=False
        # Numeric options are session configuration (Notebook sets them before
        # construction). Cache their parsing to pay for the small local cue.
        # The two on/off switches remain live for A/B and normal disablement.
        cfg=self._hold_cfg
        if cfg is None:cfg=self._hold_cfg=static_hold_settings()
        continuity=os.environ.get('P11_STATIC_EDGE_CONTINUITY','1')!='0'
        if not static_hold_enabled() or image is None or image.ndim!=3 or image.shape[2]!=2:
            self._release_static_edges('disabled_or_layout')
            return None
        sample=image[::8,::8,0]
        ref=self._hold_ref
        if ref is None or ref.shape!=sample.shape:
            self._release_static_edges('new_sample_layout')
            ref=self._hold_ref=np.empty(sample.shape,np.int16)
            np.copyto(ref,sample,casting='unsafe')
            self._hold_hist=[];self._hold_count=0;self._hold_active=False
            self._hold_last_full=time.perf_counter()
            return None
        tmp=self._hold_tmp
        if tmp is None or tmp.shape!=sample.shape:
            tmp=self._hold_tmp=np.empty(sample.shape,np.int16)
        np.subtract(ref,sample,out=tmp,casting='unsafe')
        np.abs(tmp,out=tmp)
        motion=float(tmp.mean())
        changed=float(np.count_nonzero(tmp>8))/float(tmp.size)
        self._hold_motion=motion;self._hold_changed=changed
        # 自适应噪声底：低于底时快速跟随，高于底时极慢上升
        fm=self._hold_floor_m;fc=self._hold_floor_c
        fm+=(.20 if motion<fm else .01)*(motion-fm)
        fc+=(.20 if changed<fc else .01)*(changed-fc)
        self._hold_floor_m=fm;self._hold_floor_c=fc
        hist=self._hold_hist;hist.append((motion,changed))
        if len(hist)>cfg['smooth']:hist.pop(0)
        sm=sorted(v[0] for v in hist)[len(hist)//2]
        sc=sorted(v[1] for v in hist)[len(hist)//2]
        self._hold_smooth=(sm,sc)
        now=time.perf_counter()
        # ⚠️ 进入用【平滑值】（要求持续静止）；退出用【原始值】（一有大变化立刻退出）。
        # 上限防止自适应把阈值放得太松（噪声大到无法区分慢动作时宁可少保持）。
        if self._hold_active:
            exit_m=min(12.,max(cfg['exit'],cfg['exit_gain']*fm))
            exit_c=min(.18,max(cfg['exit_frac'],cfg['exit_gain']*fc))
            blocked=motion>exit_m or changed>exit_c
        else:
            limit_m=min(10.,max(cfg['enter'],cfg['enter_gain']*fm))
            limit_c=min(.15,max(cfg['enter_frac'],cfg['enter_gain']*fc))
            blocked=sm>limit_m or sc>limit_c
        # A small book can move without changing the whole-view mean much.
        # Compare boundary-near cells to the SAME fixed raw reference; slow
        # movement accumulates across holds and periodic complete checks.
        local_blocked=False
        if not continuity and self._still_q is not None:self._release_static_edges('continuity_disabled')
        if continuity and self._still_samples is not None:
            near=tmp.ravel()[self._still_samples]
            self._still_edge_motion=float(near.sum())/float(near.size)
            # Uniform exposure/noise should keep the original global decision;
            # only excess change concentrated at the book border wakes early.
            local_blocked=(self._still_edge_motion>max(6.,min(8.,1.5*fm))
                and self._still_edge_motion>1.5*motion)
        if (lost_at_entry or self.state!='TRACKING' or blocked or local_blocked
                or getattr(self,'source_force_reacquire',False)):
            self._release_static_edges('lost_or_gap' if lost_at_entry or getattr(self,'source_force_reacquire',False)
                else 'raw_motion' if blocked or local_blocked else 'not_tracking')
            np.copyto(ref,sample,casting='unsafe')
            self._hold_count=0;self._hold_active=False;self._hold_last_full=now
            return None
        self._still_calm=self._still_q is not None
        self._hold_count+=1
        if not self._hold_active:
            if self._hold_count<cfg['min_frames']:
                self._hold_last_full=now
                return None
            self._hold_active=True;self._hold_since=now;self._hold_frames=0
            if continuity and self._still_q is None:self._pin_static_edges(sample.shape)
        self._still_calm=self._still_q is not None
        if now-self._hold_last_full>cfg['max_s']:
            # 到点强制完整测量一次（防慢速漂移）
            self._hold_active=False;self._hold_count=0;self._hold_last_full=now
            return None
        self._hold_frames+=1
        self.velocity[:]=0
        self.last_index=index;self.state='TRACKING';self.lost=False
        self.fastpath_detail=dict(policy='static_hold',route='static_hold',
            ordinary_stability_probe=False,ordinary_illumination_probe=False,same_frame_receipt_reused=False)
        corners=self.corners();corners.flags.writeable=False
        return dict(valid=True,mode='static_hold',corners=corners,
            confidence=float(self._hold_confidence),index=index,scheduled=False,
            lk_trigger=None,edge_rescue=None,trigger='static_hold',
            feature_count=len(self.anchor_points),target_changed=False,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu,
            tracking_state='TRACKING',edge_gate=dict(self._hold_gate),lk_timing={},
            current_source_proof=dict(self.last_source_confirmation),
            v49_fastpath=dict(self.fastpath_detail),
            quick_current_candidate=dict(attempted=False,verified=False),
            current_proof_workspace=self.current_proofs.summary(),
            source_corners_s=0.,post_observation_s=0.,gray_s=0.,
            static_hold=dict(motion=motion,changed=changed,smooth_motion=sm,smooth_changed=sc,
                floor_m=fm,floor_c=fc,held_s=now-self._hold_since,frames=self._hold_frames,
                max_hold_s=cfg['max_s'],edge_motion=self._still_edge_motion,
                fixed_raw_reference=True,static_edge_reference=self._still_calm))

    def update(self, image, index):
        self.last_source_confirmation={}  # Per-current-frame diagnostic only.
        self.edge_workspace.decode_timing=(0.,0.)
        self.observer.transaction.decode_timing=(0.,0.)
        self.current_proofs.clear()
        self.fastpath_detail=dict(policy='V49_ordinary_current_edges',route='pending',
            ordinary_stability_probe=False,ordinary_illumination_probe=False,same_frame_receipt_reused=False)
        self.quick_recovery_detail=dict(attempted=False,verified=False)
        self.photometric.detail=dict(available=False,reason='V49_ordinary_path_no_illumination_probe',frame_index=index)
        self.stability_detail=dict(available=False,reason='V49_ordinary_path_no_extra_stability_remeasurement',frame_index=index)
        began=time.perf_counter();begin_cpu=time.thread_time();self._update_index=index;self._flow_cache=None
        budget_ms=(None if self.recovery_budget_ms is None else
            self.reacquire_budget_ms if (self.lost or getattr(self,'source_force_reacquire',False)) else self.recovery_budget_ms)
        lost_at_entry=self.lost
        retry_deferred=bool(lost_at_entry and getattr(self,'continuity_hold',False) and began<self._recovery_next_at)
        if retry_deferred:self._recovery_next_index=max(self._recovery_next_index,index+1)
        self._total_deadline=None if budget_ms is None else began+budget_ms/1000.
        # Current proof has priority. Global search gets the remaining budget;
        # an exhausted update rejects this frame and retries on the next one.
        # Reserving 60ms first starved FB LK's independent 64/24 proof.
        self._reserved_detection_ms=0. if budget_ms is None or lost_at_entry or self.recovery_worker is not None else min(15.,budget_ms*.125)
        self._frame_deadline=(None if budget_ms is None else
            began+.40 if self.recovery_worker is not None else
            self._total_deadline if lost_at_entry else began+(budget_ms-self._reserved_detection_ms)/1000.)
        if not self.started or image.shape!=self.shape or index<=self.last_index:
            raise ValueError('连续帧尺寸或顺序改变')
        async_result=None
        if lost_at_entry and self.recovery_worker is not None:
            async_result=self.recovery_worker.take()
            current_proposal=bool(async_result is not None and async_result.get('valid')
                and time.perf_counter()-async_result['ready']<=self.recovery_result_max_age_s)
            if not current_proposal:
                if self._quick_recovery_attempted and not self._local_due():
                    return self._async_wait(image,index,began,begin_cpu,'Awaiting current admitted background candidate',async_result)
                async_result=None
        previous=self.q.copy();dt=max(1.,float(getattr(self,"source_step",index-self.last_index)))
        source_gap=bool(getattr(self,'source_force_reacquire',False))
        # Do not extrapolate a stale velocity across a long USB capture gap.
        prediction=previous.copy() if source_gap else self.q+self.velocity*dt
        self._edge_radius,search_detail=self._search_radius(previous,dt,source_gap)
        self._stability_drift_start[:]=self.accumulated_drift
        # ⭐ 2026-10-28 计时：静止门控也在 `tg` 之前，`post_observation_s` 把这段
        #    算成了"观测之后"，导致 800x600 有 ~18.5 ms 无法归因。单独打点。
        hold_begin=time.perf_counter()
        held=self._static_hold(image,index,began,begin_cpu,lost_at_entry)
        hold_s=time.perf_counter()-hold_begin
        if held is not None:return held
        if self._still_calm:
            # Fix the physical search reference, NOT the output coordinates.
            # The existing measurement still supplies this frame's corners.
            prediction=self._still_q.copy();self._edge_radius=min(self._edge_radius,self._still_radius)
        context=(prediction,previous,self.anchor_q,self.accumulated_drift,self.edge_polarity,self._edge_radius) if not lost_at_entry and self.checks=='auto' and self.policy=='motion_adaptive' else None
        tg=time.perf_counter();gray,scale=self.observer.get(image,context)
        self.last_gray=gray;gray_s=time.perf_counter()-tg
        self.current_proofs.begin(image,gray,index,scale)
        self._promoted_points=None;self.last_lk_timing={}
        age=index-self.anchor_index+int(getattr(self,"source_age_extra",0))
        scheduled=(age>=(self.interval if self.policy=='periodic' else self.lk_max_gap)
            or bool(self._lk_budget_deferrals))
        # previous/dt/prediction were computed before this same-frame observation.
        evidence,reason,detection={},None,None
        mode,reseed='edge_measured',False;gate={};lk_trigger=None;motion_schedule={};adaptive_reason=None
        stable_detail=dict(eligible=False,policy='strict_current_reacquisition')
        self._current_motion_values=None
        self._rescue_detail=None        # ⭐ 2026-10-18 埋点：每帧先清，防串味
        measured_edge_candidate=None;measured_edge_evidence=None;recovery_detail={};gap_anchor_retained=False;recovery_attempt_detail={}
        from v62_policy import LKWorkBudgetExceeded
        from v69_policy import ordinary_policy
        try:
            if lost_at_entry and async_result is not None:
                candidate,evidence,recovery_detail=self._admit_async_candidate(image,gray,scale,async_result,index)
                gate=recovery_detail['first_validation'];mode,reseed='current_edge_reacquire',True
                self.edge_polarity=list(evidence['edge_polarity'])
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
            elif lost_at_entry and self.recovery_worker is not None:
                quick_due=not self._quick_recovery_attempted
                local=(self._quick_current_candidate(image,gray,scale,index) if quick_due else
                    self._local_exterior(image,gray,scale,prediction,index))
                if local is None:
                    return self._async_wait(image,index,began,begin_cpu,'Local current exterior unproved; await background candidate',
                        observation=dict(gray_s=gray_s,gray_detail=dict(self.observer.detail),
                            current_source_proof=dict(self.last_source_confirmation)))
                candidate,evidence,recovery_detail=local
                gate=recovery_detail['first_validation'];mode,reseed='current_edge_reacquire',True
                self.edge_polarity=list(evidence['edge_polarity'])
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
            elif lost_at_entry:
                self.state='LOST' 
                candidate,evidence=edge_measure(gray,prediction,3.,self.checks)
                gate=self._edge_gate(evidence,candidate,prediction,3.)
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
                # Leave most of the total budget for global detection if the
                # current exterior cannot be proved near its last location.
                current_deadline=self._frame_deadline
                self._frame_deadline=min(current_deadline,time.perf_counter()+.055) if current_deadline is not None else None
                proof_allowed=(not retry_deferred or (gate['reliable'] and
                    time.perf_counter()>=self._continuity_proof_next_at))
                if proof_allowed and getattr(self,'continuity_hold',False):
                    self._continuity_proof_next_at=time.perf_counter()+.10
                try:proof=(self._strict_current_reanchor(image,gray,prediction,candidate,evidence)
                    if proof_allowed else None)
                finally:self._frame_deadline=current_deadline
                if proof is not None:
                    candidate,evidence,recovery_detail=proof
                    mode,reseed='current_edge_reacquire',True
                    recovery_detail.update(state='LOST_current_source64_reacquired',old_LK_skipped=True)
                elif index<self._recovery_next_index:
                    raise ValueError('LOST: current exterior not proved; global retry deferred')
                else:raise ValueError('LOST: prioritize current global detection; old LK skipped')
            if self.observer.merged_error is not None:raise ValueError('Native edge observation rejected: '+str(self.observer.merged_error))
            if mode=='current_edge_reacquire':pass
            elif source_gap:
                was_lost=self.lost
                if self.observer.merged_edges is not None:
                    candidate,evidence,gate,self._current_motion_values=self.observer.merged_edges
                else:candidate,evidence=edge_measure(gray,prediction,self._edge_radius,self.checks)
                proof=self._strict_current_reanchor(image,gray,prediction,candidate,evidence)
                if proof is None:
                    candidate,evidence=self._lk_current(gray,prediction,image)
                    mode,reseed='lk_measured',True;lk_trigger='lost_or_capture_gap'
                else:
                    candidate,evidence,recovery_detail=proof
                    gate=self._edge_gate(evidence,candidate,candidate,3.)
                    measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
                    anchor_supported=_spatial_support(self.anchor_points,self.anchor_q,self.checks)
                    travel=float(np.max(np.linalg.norm(candidate-self.anchor_q,axis=1)))
                    can_retain=(not was_lost and self.policy=='motion_adaptive' and anchor_supported
                        and age<self.lk_max_gap and travel<=1. and self._gap_anchor_reuses<3
                        and float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))<2.
                        and self.drift_budget<6.)
                    if scheduled and (anchor_supported or self._lk_budget_deferrals):
                        candidate,evidence=self._lk_current(gray,candidate,image)
                        mode,reseed='lk_measured',True;lk_trigger='gap_maximum_anchor_age'
                    elif can_retain:
                        mode,reseed='gap_edge_reanchor',False
                        gap_anchor_retained=True;self._gap_anchor_reuses+=1
                        recovery_detail.update(anchor_action='retain_original_gray_points_pyramid',anchor_age=age)
                    else:
                        # Re-seeding is allowed only from two current measured
                        # exterior proofs. It is not a synthetic LK observation.
                        mode,reseed='gap_edge_reanchor',True
                        recovery_detail['anchor_action']='seed_current_twice_verified_edges'
                    recovery_detail.update(source_gap=source_gap,was_lost=was_lost,source_step=dt)
            elif self.policy=='periodic'  and (self.lost or scheduled):
                candidate,evidence=self._lk(gray,source_image=image);mode,reseed='lk_measured',True;lk_trigger='periodic'
            else:
                # Even at maximum LK age, measure the CURRENT outer boundary first.
                radius=self._edge_radius
                fused=self.observer.merged_edges
                if fused is None:
                    fused=self.edge_workspace.measure(gray,prediction,previous,self.anchor_q,
                        self.accumulated_drift,self.edge_polarity,radius) if self.checks=='auto' and self.policy=='motion_adaptive' else None
                if fused is None:
                    candidate,evidence=edge_measure(gray,prediction,radius,checks=self.checks)
                    gate=self._edge_gate(evidence,candidate,prediction,radius)
                else:candidate,evidence,gate,self._current_motion_values=fused
                if not gate['reliable'] and not (SKIP_DEAD_RESEARCH or skip_dead_research()):
                    # ⭐ 埋点：记重搜【前】的 gate 指标（只读，不改行为）
                    _pre_sup=float(gate.get('min_support',0.));_pre_rms=float(gate.get('max_rms',0.))
                    _pre_corr=float(gate.get('prediction_correction',0.));_pre_flip=int(gate.get('polarity_flips',0) or 0)
                    _pre_edges=int(evidence.get('supported_edges',0) or 0);_pre_corners=int(evidence.get('refined_corners',0) or 0)
                    _pre_valid=bool(evidence.get('valid',False))
                    from v31_detection import current_boundary
                    candidate,evidence,_=self._boundary(image,gray,scale,prediction,measured=candidate,evidence=evidence,
                        checks=self.checks,radius=radius,fast_only=True,deadline=self._frame_deadline,
                        expected_polarity=self.edge_polarity,color_profiles=24,
                        prefer_color=False,prefer_vector=False)
                    gate=self._edge_gate(evidence,candidate,prediction,radius)
                    self._current_motion_values=None
                    # ⭐ 重搜【后】再记一次 —— 量的是【改善了多少】
                    _post_sup=float(gate.get('min_support',0.));_post_rms=float(gate.get('max_rms',0.))
                    _post_corr=float(gate.get('prediction_correction',0.));_post_flip=int(gate.get('polarity_flips',0) or 0)
                    _post_edges=int(evidence.get('supported_edges',0) or 0);_post_corners=int(evidence.get('refined_corners',0) or 0)
                    _post_valid=bool(evidence.get('valid',False))
                    self._rescue_detail=dict(
                        pre_support=_pre_sup,post_support=_post_sup,
                        pre_rms=_pre_rms,post_rms=_post_rms,
                        support_gain=_post_sup-_pre_sup,
                        post_meets_support=bool(_post_sup>=.60),
                        post_meets_rms=bool(_post_rms<=1.0),
                        pre_valid=_pre_valid,post_valid=_post_valid,
                        pre_edges=_pre_edges,post_edges=_post_edges,
                        pre_corners=_pre_corners,post_corners=_post_corners,
                        pre_correction=_pre_corr,post_correction=_post_corr,
                        pre_flips=_pre_flip,post_flips=_post_flip,
                        recovered=bool(gate.get('reliable')))
                if (SKIP_DEAD_RESEARCH or skip_dead_research()) and not gate['reliable']:
                    # ⚠️ 跳过重搜时仍保留原分支的这次重置 —— 让 A/B 只差"_boundary 本身"
                    self._current_motion_values=None
                from v70_ps import evidence_snapshot
                measured_edge_candidate=candidate.copy();measured_edge_evidence=evidence_snapshot(evidence)
                self.fastpath_detail['route']='current_color_edges' if evidence.get('color_vector_proof') else 'current_Y_edges'
                if self.policy=='motion_adaptive' and gate['reliable']:
                    if self._still_calm and gate['prediction_correction']>.75:self._still_radius=2.
                    # A replaced measurement recomputes drift once from its saved
                    # pre-observation value, rather than counting both searches.
                    if self._current_motion_values is None:self.accumulated_drift[:]=self._stability_drift_start
                    adaptive_reason,motion_schedule=self._motion_schedule(gate,candidate,prediction,previous,age)
                    if radius>3.25 and gate['prediction_correction']>1.:
                        adaptive_reason='expanded_band_current_motion';motion_schedule['wide_band_FB_required']=True
                    if self._lk_budget_deferrals:
                        adaptive_reason='pending_complete_current_FB'
                        motion_schedule['deferred_FB_required']=True
                    scheduled=adaptive_reason is not None
                need_lk=self.lost or not gate['reliable'] or scheduled
                if self.policy=='periodic':
                    need_lk=self.lost or not gate['reliable'];mode='prediction_edge_corrected'
                if need_lk:
                    lk_trigger=('lost' if self.lost else (adaptive_reason or 'maximum_gap') if scheduled and gate['reliable']
                                else 'edge_confidence')
                    candidate,evidence=self._lk_current(gray,candidate if gate['reliable'] else prediction,image)
                    mode,reseed='lk_measured',True
            if mode=='edge_measured':
                stable_detail=ordinary_policy(evidence,self._edge_gate(evidence,candidate,prediction,self._edge_radius),
                    age,self.lk_max_gap,scheduled=scheduled,lost=lost_at_entry)
            if self._edge_radius>3.25 and mode=='edge_measured':
                # V49 expanded ordinary searches require actual source four
                # edges before H, while LK/new admission keep independent proof.
                from v41_quad import original_y_boundary
                proof=original_y_boundary(image,scale,candidate,radius=3.)
                precise,precise_e=(candidate,dict(valid=False)) if proof is None else proof
                pg=self._edge_gate(precise_e,precise,candidate,3.) if proof is not None else dict(reliable=False)
                if not pg['reliable']:
                    precise,precise_e,_=self._boundary(image,gray,scale,candidate,
                        measured=precise,evidence=precise_e,checks=self.checks,radius=3.,fast_only=True,
                        deadline=self._frame_deadline,expected_polarity=self.edge_polarity,
                        color_profiles=64,prefer_color=True)
                    pg=self._edge_gate(precise_e,precise,candidate,3.)
                if not pg['reliable']:
                    raise LKExteriorMismatch('V49 expanded band failed current source-resolution four-edge proof')
                candidate,evidence=precise,precise_e
                gate=pg
                self.fastpath_detail['expanded_source_four_edges']=True
            flips=0 if evidence.get('color_vector_proof') else sum(a*b<0 for a,b in zip(self.edge_polarity,evidence.get('edge_polarity',[])))
            if flips>=2:raise ValueError('边界极性改变，拒绝内部网格边界')
            fresh_admission=(mode=='current_edge_reacquire' and
                (async_result is not None or self.quick_recovery_detail.get('verified',False)))
            reference=None if fresh_admission else previous
            if not _valid(candidate,gray.shape,reference,self.checks):raise ValueError('本帧四角不合法')
        except (ValueError,cv2.error) as exc:
            reason=str(exc)
            if isinstance(exc,LKWorkBudgetExceeded) and not lost_at_entry and getattr(self,'_lk_budget_deferrals',0)<2:
                # Do not call a time deferral a target replacement. No current
                # admission or anchor promotion occurs. Next frame still owes FB;
                # the pipeline may use ONLY its pre-existing finite HELD policy.
                self._promoted_points=None;self.last_index=index
                self._lk_budget_deferrals=getattr(self,'_lk_budget_deferrals',0)+1
                return dict(valid=False,mode='budget_deferred',reason=reason,index=index,
                    tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-begin_cpu,
                    gray_s=gray_s,gray_detail=dict(self.observer.detail),feature_update_s=0.,
                    feature_detail=dict(action='retain_real_anchor_pending_FB',roi_s=0.),
                    lk_timing=dict(self.last_lk_timing),lk_trigger=lk_trigger,
                    tracking_state=self.state,edge_gate=dict(gate),edge_evidence=dict(evidence),
                    final_admission_gate=dict(reliable=False),current_source_proof=dict(self.last_source_confirmation),
                    recovery_attempt=dict(state='compute_budget_deferred',physical_loss_proven=False,
                        current_output_verified=False,hold_timer_renewed=False,FB_required_next_frame=True,
                        consecutive_deferrals=self._lk_budget_deferrals,maximum_consecutive_deferrals=2))
            if isinstance(exc,LKWorkBudgetExceeded):
                self.last_lk_timing.update(budget_deferral_limit_reached=True,
                    recovery_reason='bounded_compute_retries_exhausted; request new current anchor',physical_loss_proven=False)
            try:
                from v94_audit import recover_audit_edges
                recovered=recover_audit_edges(self,image,gray,measured_edge_candidate,measured_edge_evidence,
                    prediction,previous,gate,reason,lk_trigger,lost_at_entry,source_gap)
                if recovered is None:
                    recovered=self._recover_current_edges(gray,measured_edge_candidate,measured_edge_evidence,
                        prediction,previous,gate,reason)
                if recovered is not None:
                    candidate,evidence,edge_recovery=recovered
                    recovery_detail=dict(recovery_detail,**edge_recovery,source_gap=source_gap,
                        anchor_action="seed_current_verified_frame_after_LK_shortage")
                    mode='audit_edge_reanchor' if edge_recovery.get('audit_failure_reproved') else 'measured_edge_recovery'
                    reseed=True
                    if mode=='measured_edge_recovery':self.edge_recovery_count+=1
                else:
                    if self.recovery_worker is not None:
                        return self._async_wait(image,index,began,begin_cpu,reason,async_result,
                            dict(gray_s=gray_s,gray_detail=dict(self.observer.detail),edge_gate=dict(gate),
                                 edge_evidence=dict(evidence),lk_timing=dict(self.last_lk_timing),lk_trigger=lk_trigger,
                                 current_source_proof=dict(self.last_source_confirmation)),request_background=not self._local_due())
                    if self.recovery_budget_ms is not None:
                        if self.lost and index<self._recovery_next_index:
                            recovery_attempt_detail=dict(state='bounded_backoff',next_index=self._recovery_next_index,
                                maximum_processed_frame_gap=self.recovery_backoff_max_frames,
                                current_edge_observation_attempted=True,current_edge_candidate_available=measured_edge_candidate is not None,invalid_frame_skipped=True)
                            self.recovery_stats['deferred']+=1
                            raise ValueError('Recovery retry deferred; no stale H submitted')
                        from v31_detection import RecoveryBudget,recovery_detection_scope
                        from v49_boundary import array_key
                        reacquire=self.lost or source_gap
                        stage_begin=time.perf_counter();stage_cpu=time.thread_time()
                        remaining_ms=max(0.,(self._total_deadline-stage_begin)*1000.)
                        budget=RecoveryBudget(remaining_ms,
                            self.reacquire_max_candidates if reacquire else self.recovery_max_candidates,
                            begin=stage_begin,begin_cpu=stage_cpu)
                        budget.tracker_begin=began;budget.tracker_budget_ms=budget_ms
                        self._frame_deadline=self._total_deadline
                        self.state='REACQUIRING'
                        self._recovery_attempts+=1;self.recovery_stats['attempts']+=1
                        # This merely prioritizes a current candidate, without
                        # waiving LK or original-Y/final independent admission.
                        strong=(measured_edge_candidate is not None and gate.get('reliable')
                            and gate['min_support']>=.80 and gate['max_rms']<=.65
                            and gate['prediction_correction']<=1.)
                        proposal=((measured_edge_candidate+.5)*scale-.5) if strong else None
                        try:
                            with recovery_detection_scope(budget,dict(gray=gray,scale=scale,source_shape=image.shape,
                                    verified_edge_proposal=proposal,frame_index=index,
                                    source_key=array_key(image))):
                                global_current=(lost_at_entry or isinstance(exc,LKExteriorMismatch) or not gate.get('reliable',False))
                                full,detection=self._detect_nearby(image,measured_edge_candidate if strong else prediction,scale,bounded=True,force_full=global_current)
                        finally:
                            recovery_attempt_detail=dict(budget.summary(),budget_class="reacquisition" if reacquire else "ordinary",
                                 current_Y_reused=True,current_exterior_proposal_used=bool(strong),
                                 whole_tracker_budget=False,total_tracker_budget_ms=budget_ms,
                                 pre_detection_s=stage_begin-began,detector_phase_budget_ms=remaining_ms,
                                 detector_first_on_LOST=lost_at_entry,old_LK_skipped=lost_at_entry,
                                 reserved_detection_ms=self._reserved_detection_ms,
                                 total_tracker_elapsed_s=time.perf_counter()-began,
                                 global_current_Y_first=bool(lost_at_entry or isinstance(exc,LKExteriorMismatch) or not gate.get('reliable',False)),
                                 trigger_class='LKExteriorMismatch' if isinstance(exc,LKExteriorMismatch) else 'current_geometry_or_flow')
                            self.recovery_stats['elapsed_s']+=recovery_attempt_detail['elapsed_s']
                            self.recovery_stats['overshoot_s']+=recovery_attempt_detail['overshoot_s']
                            self.recovery_stats['budget_stops']+=int(budget.stopped is not None)
                    else:full,detection=self._detect_nearby(image,prediction,scale)
                    candidate=((np.asarray(full)+.5)/scale-.5).astype(np.float32)
                    if not _valid(candidate,gray.shape,checks=self.checks):raise ValueError('重检四角异常')
                    from v69_policy import read_current_receipt as read_receipt
                    receipt=read_receipt(detection,image,gray,scale,index,full)
                    detection.pop('_current_boundary_receipt',None)
                    if receipt is not None:
                        measured,reacquired,reacquisition_gate=receipt
                        self.last_source_confirmation=dict(reacquisition_gate.get('current_source_agreement',{}),
                            final_gate=dict(reacquisition_gate))
                    else:
                        measured,reacquired=edge_measure(gray,candidate,3.,self.checks)
                        from v31_detection import exterior_gate
                        reacquisition_gate=exterior_gate(reacquired,measured,candidate,3.)
                        if not reacquisition_gate['reliable']:
                            from v31_detection import current_boundary
                            measured,reacquired,reacquisition_gate=self._boundary(image,gray,scale,candidate,measured=measured,evidence=reacquired,checks=self.checks)
                    recovery_detail=dict(recovery_detail,state='full_redetection_validation',validation=reacquisition_gate,
                        edge_evidence=reacquired,corners=candidate.tolist())
                    if not reacquisition_gate['reliable'] or not _valid(measured,gray.shape,checks=self.checks):
                        raise ValueError('重检未通过四条外边缘验证: '+str(reacquisition_gate))
                    # Use the measured intersections, not the coarse proposal.
                    # Strong full-frame detection establishes its own polarity;
                    # ordinary tracking still rejects polarity flips and uses FB LK.
                    candidate=measured
                    self.edge_polarity=reacquired['edge_polarity']
                    mode,reseed='full_redetect',True;evidence=reacquired
                    self.edge_recovery_count=0
            except (ValueError,cv2.error) as failure:
                self.lost=True;self.state='LOST';self.velocity[:]=0;self.last_index=index
                if self.recovery_budget_ms is not None and recovery_attempt_detail.get('state')!='bounded_backoff':
                    self._recovery_failures+=1
                    gap=min(self.recovery_backoff_max_frames,1<<min(3,max(0,self._recovery_failures-1)))
                    self._recovery_next_index=index+gap
                    if getattr(self,'continuity_hold',False):
                        retry_s=min(self.recovery_retry_max_s,self.recovery_retry_min_s*(2**min(2,self._recovery_failures-1)))
                        self._recovery_next_at=time.perf_counter()+retry_s
                        recovery_attempt_detail.update(next_retry_at=self._recovery_next_at,retry_backoff_s=retry_s)
                    recovery_attempt_detail.update(failure_count=self._recovery_failures,next_index=self._recovery_next_index,
                        current_edge_observation_attempted=True,current_edge_candidate_available=measured_edge_candidate is not None,invalid_frame_skipped=True)
                    self._remember_recovery_failure(gray,index,prediction,recovery_attempt_detail)
                return dict(valid=False,mode='lost_skip',reason=str(failure),trigger=reason,
                    tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-begin_cpu,index=index,gray_s=gray_s,
                    gray_detail=dict(self.observer.detail),feature_update_s=0.,
                    feature_detail=dict(action='lost_skip',roi_s=0.),lk_timing=dict(self.last_lk_timing),
                    edge_rescue=getattr(self,"_rescue_detail",None),   # ⭐ 防未初始化
                    tracking_policy=self.policy,lk_channel=self.lk_channel,lk_trigger=lk_trigger,edge_gate=gate,
                    tracking_state=self.state,prediction_gate=dict(gate),final_admission_gate=dict(reliable=False),
                    lk_current_gate=self.last_lk_timing.get('current_four_edge_gate'),search_band=search_detail,
                    edge_evidence=evidence,detection=detection,reacquisition=recovery_detail,
                    detector_failure=getattr(failure,'diagnostics',None),source_gap=source_gap,
                    recovery_attempt=recovery_attempt_detail)
        self._lk_budget_deferrals=0
        self.photometric.commit()
        from v51_target import align_current,border_signature,target_relation
        identity=dict(state='tracked_current_target',target_changed=False,same_target=True)
        if mode in ('full_redetect','current_edge_reacquire'):
            candidate,evidence=align_current(candidate,evidence,previous)
            self.edge_polarity=list(evidence['edge_polarity'])
            identity,signature=target_relation(previous,candidate,evidence,self._target_signature)
            self._recovery_confirmations=1
            if signature is not None:self._target_signature=signature.copy()
        else:
            self._recovery_confirmations=min(3,self._recovery_confirmations+1)
            signature=border_signature(evidence)
            if signature is not None:self._target_signature=signature.copy()
        if evidence.get('color_vector_proof'):self._vector_boundary=True
        elif identity.get('target_changed'):self._vector_boundary=False
        # Smooth corner velocity only. The newly measured corners themselves
        # are used for H; averaging H coefficients would create geometric lag.
        if self._recovery_failures:
            self.recovery_stats['successes']+=1
        self._recovery_failures=0;self._recovery_next_index=0;self._recovery_attempts=0
        self._recovery_next_at=0.;self._continuity_proof_next_at=0.
        change = (candidate-previous)/max(dt, 1)
        if mode=='lk_measured':self.edge_recovery_count=0
        self.velocity = (self.velocity*.25+change*.75).astype(np.float32)
        if mode in ('full_redetect','gap_edge_reanchor','current_edge_reacquire','audit_edge_reanchor'):
            self.velocity[:] = 0
            self._promoted_points=None
            self._last_measured_motion=0.;self._edge_lock_failures=0;self._edge_lock_next_at=0.
        same_recovery=bool(mode in ('full_redetect','current_edge_reacquire','gap_edge_reanchor','audit_edge_reanchor') and identity.get('same_target'))
        if mode in ('full_redetect','current_edge_reacquire'):
            if not identity.get('same_target'):
                self.lk_channel='Y';self._flow_cache=None;self._channel_audit_index=-100
            self.motion_ema=self.correction_ema=0.
            self._burst_until=-1
        if self._still_calm and self._still_q is not None:
            from v62_policy import line_lock
            if not line_lock(self._still_q,candidate).get('verified'):
                self._release_static_edges('current_edges_left_reference')
        np.copyto(self.q,candidate,casting='unsafe')
        self.last_index, self.lost = index, False
        self.state='TRACKING' if self._recovery_confirmations>=3 else 'RECOVERING'
        feature_s=0.;feature_reused=False
        self.last_feature_detail=dict(action='gap_original_anchor_retained' if gap_anchor_retained else 'unchanged_between_lk',
            roi_s=0.,gap_anchor_retained=gap_anchor_retained,consecutive_gap_anchor_reuses=self._gap_anchor_reuses)
        if reseed:
            ts=time.perf_counter()
            anchor_travel=float(np.max(np.linalg.norm(self.q-self.anchor_q,axis=1)))
            retain_original=(same_recovery and not recovery_detail.get('force_current_anchor',False) and self.policy=='motion_adaptive'
                and _spatial_support(self.anchor_points,self.anchor_q,self.checks)
                and age<self.lk_max_gap and anchor_travel<=min(6.,.04*float(np.min(np.linalg.norm(np.roll(self.q,-1,axis=0)-self.q,axis=1))))
                and self._gap_anchor_reuses<3)
            if retain_original:
                self._gap_anchor_reuses+=1;gap_anchor_retained=True;feature_reused=True
                self.observer.pin(self.anchor_gray if self.lk_channel=='Y' else self.last_gray)
                self.last_feature_detail=dict(action='same_target_original_verified_anchor_retained',roi_s=0.,
                    channel_audit_skipped=True,anchor_age=age,anchor_travel=anchor_travel,
                    forward_backward_due_by=self.anchor_index+self.lk_max_gap,
                    points_synthesized=False,pyramid_promoted=False)
            else:
                self._gap_anchor_reuses=0
            points=self._promoted_points
            if (not retain_original and self.feature_policy=='quality' and mode not in ('full_redetect','measured_edge_recovery','gap_edge_reanchor','current_edge_reacquire','audit_edge_reanchor') and points is not None):
                # Maintain measured points while their distribution and LK
                # quality remain good; no unconditional 45-frame rebuild.
                quality=(evidence.get('inlier_fraction',0.)>=.85 and
                         evidence.get('fb_median',float('inf'))<.7 and
                         _spatial_support(points,self.q,self.checks))
                points=self._quality_replenish(self._flow_observation(image,gray),points,self.q,quality,evidence)
            if retain_original:pass
            elif (mode not in ('full_redetect','measured_edge_recovery','gap_edge_reanchor','current_edge_reacquire','audit_edge_reanchor') and points is not None and
                _spatial_support(points,self.q,self.checks) and
                (self.feature_policy=='quality' or index-self.seed_index<45)):
                self.anchor_gray=self._flow_observation(image,gray);self.observer.pin(gray)
                self.anchor_q=self.q.copy()
                self.anchor_points=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
                self.anchor_index=index
                self.lk_cache.promote()
                feature_reused=True
            else:
                self._seed(gray,self.q,index,image,same_target=same_recovery)
            self.accumulated_drift[:]=0;self.drift_budget=0.
            feature_s=time.perf_counter()-ts
            # ⭐ 2026-10-28 计时：其中【重取点搜索】占多少（promote 快路径为 0）。
            feature_roi_s=float(self.last_feature_detail.get('roi_s') or 0.)
        else:feature_roi_s=0.
        verified_now=time.perf_counter();source_ready=getattr(self,'source_ready_at',verified_now)
        self._exit_verified_calm_burst(mode,candidate,previous,prediction,index)
        self._last_physical_at=float(source_ready) if np.isfinite(source_ready) and 0<=source_ready<=verified_now else verified_now
        self._local_attempts=0;self._local_next_at=0.
        self._quick_recovery_attempted=False
        self.fastpath_detail.update(route=mode if mode!='edge_measured' else self.fastpath_detail['route'],
            same_frame_receipt_reused=bool(gate.get('same_frame_receipt_reused') or self.last_source_confirmation.get('current_same_frame_proof_reused')))
        if static_hold_enabled():
            self._hold_gate=dict(gate);self._hold_confidence=float(np.mean(evidence.get('edge_support',[1.])))
        tc=time.perf_counter();source_corners=self.corners();source_corners.flags.writeable=False
        source_corners_s=time.perf_counter()-tc
        confidence=float(np.mean(evidence.get('edge_support',[1.])))
        tracker_elapsed=time.perf_counter()-began;tracker_cpu=time.thread_time()-begin_cpu
        post_observation_s=max(0.,tracker_elapsed-(tg-began)-gray_s)
        # ⭐ 2026-10-28 计时：把 post_observation 再拆成 LK / 其余。
        #    `lk_s` 取 LK 自己记的 total_attempt_wall_s（含证据门），
        #    `tail_s` = 观测结束到帧尾中 LK 之外的部分（重播点、corners 等）。
        lk_s=float(self.last_lk_timing.get('total_attempt_wall_s') or 0.)
        pre_obs_s=max(0.,(tg-began)-hold_s)
        tail_s=max(0.,post_observation_s-lk_s-feature_s)
        def diagnostics():
            if self._update_index!=index:raise RuntimeError('Expired tracking diagnostic view; materialize before next frame')
            tm=time.perf_counter();cm=time.thread_time()
            result=dict(valid=True, mode=mode, corners=source_corners.tolist(),
                        confidence=confidence,
                        edge_evidence=evidence, detection=detection, trigger=reason,
                        corner_shift_pixels=float(np.max(np.linalg.norm((self.q-previous)*scale, axis=1))),
                        tracker_s=tracker_elapsed,tracker_thread_cpu_s=tracker_cpu, index=index, scheduled=scheduled,
                        lk_trigger=lk_trigger,tracking_policy=self.policy,lk_channel=self.lk_channel,edge_gate=gate,
                        tracking_state=self.state,prediction_gate=dict(gate),
                        final_admission_gate=self._edge_gate(evidence,self.q,self.q,3.),
                        lk_current_gate=self.last_lk_timing.get('current_four_edge_gate'),search_band=search_detail,
                        channel_selection=dict(self._channel_evidence),
                        lk_age_frames=age,lk_max_gap=self.lk_max_gap,motion_schedule=motion_schedule,
                        gray_s=gray_s, feature_update_s=feature_s, feature_reused=feature_reused,
                        gap_anchor_retained=gap_anchor_retained,
                        gray_detail=dict(self.observer.detail),feature_detail=dict(self.last_feature_detail),
                        feature_seed_count=self.seed_count,feature_count=len(self.anchor_points),
                        edge_recovery=recovery_detail,lk_timing=dict(self.last_lk_timing),recovery_attempt=recovery_attempt_detail,
                        target_identity=identity,target_changed=identity.get('target_changed',False),
                        recovery_confirmations=self._recovery_confirmations,color_boundary_continuity=self._vector_boundary,
                        current_proof_budget_ms=budget_ms-self._reserved_detection_ms if budget_ms is not None else None,
                        same_target_recovery=same_recovery,
                        current_source_proof=dict(self.last_source_confirmation),photometric=dict(self.photometric.detail),
                        edge_stability=dict(self.stability_detail),
                        static_edges=dict(active=self._still_calm,release=self._still_release,
                            edge_motion=self._still_edge_motion,current_measurement_retained=True),
                        stable_tracking_policy=stable_detail,localization_baseline='V49_ordinary_V68_strict_new_admission',
                        v49_fastpath=dict(self.fastpath_detail),quick_current_candidate=dict(self.quick_recovery_detail),
                        current_proof_workspace=self.current_proofs.summary(),
                        current_proof_budget_scope='independent LK CPU/wall; narrow current-line proof; strict new admission')
            result['tracking_metadata_build_s']=time.perf_counter()-tm
            result['tracking_metadata_thread_cpu_s']=time.thread_time()-cm
            result['source_corners_s']=source_corners_s
            result.update(pre_obs_s=pre_obs_s,static_hold_s=hold_s,lk_s=lk_s,tail_s=tail_s,
                feature_s=feature_s,feature_roi_s=feature_roi_s,roi_search_gap=self._roi_search_gap)
            return result
        if not self.light_results:return diagnostics()
        # Only the current PS caller may consume _diagnostics; it never enters
        # FrameJob or the log queue. The tiny corners snapshot owns its bytes.
        return dict(valid=True,mode=mode,corners=source_corners,confidence=confidence,
            index=index,scheduled=scheduled,lk_trigger=lk_trigger,edge_rescue=getattr(self,"_rescue_detail",None),trigger=reason,
            feature_count=len(self.anchor_points),target_changed=identity.get('target_changed',False),
            tracker_s=tracker_elapsed,tracker_thread_cpu_s=tracker_cpu,tracking_state=self.state,
            edge_gate=gate,lk_timing=self.last_lk_timing,current_source_proof=self.last_source_confirmation,
            v49_fastpath=self.fastpath_detail,quick_current_candidate=self.quick_recovery_detail,
            current_proof_workspace=self.current_proofs.summary(),source_corners_s=source_corners_s,
            static_edges=dict(active=self._still_calm,release=self._still_release,
                edge_motion=self._still_edge_motion,current_measurement_retained=True),
            post_observation_s=post_observation_s,gray_s=gray_s,
            pre_obs_s=pre_obs_s,static_hold_s=hold_s,lk_s=lk_s,tail_s=tail_s,
            feature_s=feature_s,feature_roi_s=feature_roi_s,roi_search_gap=self._roi_search_gap,
            _diagnostics=diagnostics)
