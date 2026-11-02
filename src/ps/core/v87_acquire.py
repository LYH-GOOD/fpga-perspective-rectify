"""V74 stabilization + unrestricted original detector admission, inside a visible CPU worker."""
from pathlib import Path
import hashlib,time,threading
import cv2,numpy as np
from p11_contract import RELEASE_ID
from v79_acquire import LiveAcquire
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class AcquisitionStopped(Exception):pass


class V74Acquire(LiveAcquire):
    """UI/lifetime bridge only. No420ms candidate budget, negative hints or second admission."""
    def __init__(self,detection_limit,tracking_limit,factory=None,quad=None,budget_ms=420.,*,recovery=False,target_selection=None,target_report=None,target_progress=None,phase_report=None):
        self.is_recovery=bool(recovery or quad is not None)
        self.unpublished=None
        self.target_selection=target_selection;self.target_report=target_report
        self.target_progress=target_progress
        self.phase_report=phase_report
        super().__init__(detection_limit,tracking_limit,factory)
    def _take_owned(self,timeout):
        deadline=time.perf_counter()+float(timeout)
        with self.condition:
            while self.latest is None and not self.stop:
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('V74 acquisition: no owned camera snapshot')
                self.condition.wait(min(.1,remaining))
            if self.stop:raise AcquisitionStopped()
            frame=self.latest;self.latest=None;return frame
    def _check_target(self):
        with self.condition:
            if self.stop:raise AcquisitionStopped()
    def _run(self):
        from v31_startup import stabilize_camera,admit_initial_frame
        from v31_detection import detect_refined,detection_cancel_scope
        owner=self
        class CameraProxy:
            @property
            def color_mode(self):
                from v31_pixels import color_mode
                return color_mode()
            def take(self,timeout):return owner._take_owned(timeout)
        proxy=CameraProxy();next_log=0.
        target=TapDetector(self.target_selection,self.detection_limit,self.tracking_limit,self.target_report,self._check_target) if self.target_selection is not None else None
        while True:
            first=selected=None;built=None;began=time.perf_counter();cpu=time.thread_time()
            try:
                # Recovery already has a running exposure stream. Initial entry
                # retains V74's exact12/150/4 stability rule and6s guard.
                if self.phase_report is not None:self.phase_report('STABILIZING')
                if self.is_recovery:first=proxy.take(3.);stability=dict(policy='already_running_camera')
                else:first,stability=stabilize_camera(proxy,12,150,4,6.)
                if self.phase_report is not None:self.phase_report('SEARCHING')
                def preview(frame,attempt):
                    with self.condition:
                        if self.stop:raise AcquisitionStopped()
                seed=first;first=None  # Ownership transfers even when cancelled.
                with detection_cancel_scope(self._check_target):
                    selected,_,detection,admission=admit_initial_frame(proxy,seed,
                        lambda raw,bgr:(target(raw,bgr) if target is not None else detect_refined(raw,self.detection_limit,True,prefer_mask=True,
                            color_reference=bgr,tracking_limit=self.tracking_limit)),
                        attempts=6,timeout_s=12.,save_failed_frame=False,candidate_preview=preview)
                self._check_target()
                if self.phase_report is not None:self.phase_report('CANDIDATE')
                self.attempts+=int(admission.get('attempts',1));self.rejections+=int(admission.get('failed_attempts',0))
                with self.condition:
                    self.candidate=tuple(map(tuple,np.asarray(detection[0]).tolist()));self.candidate_ready=float(selected.ready)
                    stopped=self.stop
                if stopped:raise AcquisitionStopped()
                if self.target_progress is not None:self.target_progress('verify')
                # One overview per accepted acquisition, outside the tracking loop.
                # Existing CURRENT/H/PL admission still runs after this UI hint.
                notice=None
                if self.target_report is not None:
                    if target is None:
                        notice=target_overview(selected.image,detection,self.detection_limit,self.tracking_limit,self._check_target)
                    else:notice='selecting' if target.selected else 'fallback'
                handoff=dict(refreshed=False)
                if self.factory is not None:
                    from v88_recovery import freshen_source
                    replacement,detection,handoff=freshen_source(self,selected,detection)
                    if replacement is not selected:selected.release();selected=replacement
                selection_proof=None
                if target is not None:
                    from v121_selection import map_point,proof
                    point,mapping=map_point(target.selection,selected.image,selected.sequence)
                    if not target.selected or cv2.pointPolygonTest(np.asarray(detection[0],np.float32),point,True)<0.:
                        raise ValueError('当前结果不属于本次点选目标')
                    selection_proof=proof(target.selection,point,selected.sequence,mapping,selection_method='automatic_physical_candidate',current_aligned=False)
                # Original source proof is exactV74. A chronological current FB
                # or V74 ordinary check must still pass before any DMA output.
                built=self.factory(selected,detection) if self.factory else None
                self.unpublished=built
                if self.phase_report is not None:self.phase_report('READY')
                if notice is not None:self.target_report(notice)
                report=dict(attempts=self.attempts,rejections=self.rejections,source_sequence=int(selected.sequence),
                    current_revalidated=bool(handoff['refreshed']),initial_source_verified=True,owned_source=True,
                    admission_policy='V74 stabilize_camera + admit_initial_frame + full detect_refined',
                    elapsed_worker_cpu_s=self.worker_cpu_s+time.thread_time()-cpu,
                    startup_stability=stability,source_age_s=max(0.,time.perf_counter()-selected.ready),
                    handoff=handoff,
                    current_frame_validation_before_output='complete_FB_or_V74_current_exterior')
                if selection_proof is not None:report['target_selection_proof']=selection_proof
                with self.condition:
                    stopped=self.stop
                    if not stopped:
                        self.result=(selected,detection,built,report);self.latest=None;self.stop=True
                        self.unpublished=None;self.condition.notify_all()
                if not stopped:
                    # The result slot now owns the frontend and source snapshot.
                    built=selected=None
                return
            except (AcquisitionStopped,RecoveryCancelled):
                return
            except (ValueError,TimeoutError,cv2.error) as exc:
                self.rejections+=1;self.attempts+=1
                if time.perf_counter()>=next_log:
                    checkpoint('V87_V74_ACQUIRE_RETRY',reason=str(exc),attempts=self.attempts,
                        preview_continues=True,legacy_detector_budgeted=False)
                    next_log=time.perf_counter()+2.
            finally:
                if built is not None:built.close();self.unpublished=None
                if first is not None:first.release()
                if selected is not None:selected.release()
                self.worker_cpu_s+=time.thread_time()-cpu;self.worker_wall_s+=time.perf_counter()-began
    def close(self):
        began=time.perf_counter()
        super().close()
        if self.unpublished is not None:self.unpublished.close();self.unpublished=None
        checkpoint('ACQUIRE_RETIRED',elapsed_s=time.perf_counter()-began,
            cooperative_stage_checks=True,worker_joined=not self.thread.is_alive(),forced_termination=False)


from v88_recovery import V74Reacquire,RecoveryCancelled


def target_quads(image):
    """Search-time coarse rectangles only; never evidence, H, or PL authority."""
    from v31_detection import _contour_proposals,_color_proposals,_small_color
    raw=image.ndim==3 and image.shape[2]==2
    gray=image[:,:,0] if raw else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    proposals=list(_contour_proposals(gray,320))
    if image.ndim==3:proposals.extend(_color_proposals(_small_color(image,192),image.shape))
    result=[]
    for quad in sorted(proposals,key=lambda q:abs(cv2.contourArea(q)),reverse=True):
        q=np.asarray(quad,np.float32)
        area=abs(cv2.contourArea(q))
        # The same outline and its interior print must not count as two books.
        if any(cv2.intersectConvexConvex(q,old)[0]>=.85*area for old in result):continue
        result.append(q)
        if len(result)==8:break
    return result


def prove_target(image,quad,limit,tracking_limit,color_reference=None,check=None,*,luma_first=False):
    """A coarse tap hint enters the existing full-source64/independent24 gate."""
    from v31_detection import detect_refined,recovery_detection_scope,recovery_candidate_scope
    from v58_budget import CpuRecoveryBudget
    class TargetBudget(CpuRecoveryBudget):
        def check(self,stage,finish_gate=False):
            if check is not None:check()
            super().check(stage,finish_gate)
    budget=TargetBudget(1200.,1,wall_max_s=2.);budget.log_detail=False
    seeds=(dict(detector='tap_current_Y' if luma_first else 'tap_multicolor_exterior',coarse_corners=np.asarray(quad).tolist()),)
    with recovery_detection_scope(budget),recovery_candidate_scope(seeds,True):
        return detect_refined(image,limit,True,prefer_mask=True,color_reference=color_reference,tracking_limit=tracking_limit)


def target_overview(image,detection,limit,tracking_limit,check=None):
    """Hint only when a second independent rectangle passes original admission."""
    from v31_detection import QuadDetectionError
    chosen=np.asarray(detection[0],np.float32);area=abs(cv2.contourArea(chosen))
    checked=0
    for q in target_quads(image):
        if check is not None:check()
        if cv2.intersectConvexConvex(chosen,q)[0]>.20*min(area,abs(cv2.contourArea(q))):continue
        checked+=1
        try:other,_=prove_target(image,q,limit,tracking_limit,check=check)
        except (QuadDetectionError,ValueError,cv2.error):
            if checked>=3:break
            continue
        if cv2.intersectConvexConvex(chosen,other)[0]<=.20*min(area,abs(cv2.contourArea(other))):return 'multiple'
        if checked>=3:break
    return 'idle'


class TargetSliceExpired(Exception):pass


def tap_candidates(image,point,check=None):
    """Retain different hypotheses for the clicked object, not only white blobs.

    These are proposals only. A frozen source never grants a CURRENT receipt.
    Keep near-outline variants until strict current admission has tried them.
    """
    from v48_candidates import exterior_candidates
    from v31_detection import _contour_proposals,_color_proposals,_small_color
    def guard(stage=None):
        if check is not None:check()
    candidates=[]
    def add(q):
        q=np.asarray(q,np.float32)
        if cv2.pointPolygonTest(q,point,True)<2.:return None
        if any(np.max(np.linalg.norm(q-old,axis=1))<2. for old in candidates):return None
        candidates.append(q);return q
    for q in exterior_candidates(image,guard,192):
        guard();q=add(q)
        if q is not None:yield q
        if len(candidates)>=12:return
    gray=image[:,:,0] if image.ndim==3 and image.shape[2]==2 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    for q in _contour_proposals(gray,320,incremental=True):
        guard();q=add(q)
        if q is not None:yield q
        if len(candidates)>=12:return
    if image.ndim==3:
        for q in _color_proposals(_small_color(image,192),image.shape):
            guard();q=add(q)
            if q is not None:yield q
            if len(candidates)>=12:return


class TapDetector:
    """Bounded CURRENT retries for one tap, without an old-frame proof veto."""
    def __init__(self,selection,limit,tracking_limit,report=None,check=None):
        self.selection=selection;self.limit=limit;self.tracking_limit=tracking_limit
        self.report=report;self.check=check;self.seed=None;self.selected=False
        self.calls=0;self.cursor=0;self.finished=False
    def __call__(self,image,bgr):
        from v31_detection import detect_refined
        from v31_detection import QuadDetectionError
        if self.finished:
            raise QuadDetectionError('本次点选自动搜索已结束，等待原策略转AI',dict(selection_only=True))
        self.calls+=1;self.selected=False
        from v121_selection import map_point
        try:point,mapping=map_point(self.selection,image)
        except (ValueError,cv2.error) as exc:
            raise QuadDetectionError(str(exc),dict(selection_only=True)) from exc
        began=time.perf_counter();cpu=time.thread_time();failures=[];candidates=[]
        def check():
            if self.check is not None:self.check()
            if time.thread_time()-cpu>.60 or time.perf_counter()-began>1.2:raise TargetSliceExpired()
        def proposals():
            if self.seed is not None:yield self.seed
            for source in (image,):
                for q in tap_candidates(source,point,check):
                    if any(np.max(np.linalg.norm(q-old,axis=1))<2. for old in candidates):continue
                    candidates.append(q);yield q
        def try_candidate(q):
            for luma_first in (False,True):
                check()
                try:result=prove_target(image,q,self.limit,self.tracking_limit,bgr,check=check,luma_first=luma_first)
                except (QuadDetectionError,ValueError,cv2.error) as exc:
                    failures.append(dict(strategy='Y' if luma_first else 'YUV',reason=str(exc)));continue
                if cv2.pointPolygonTest(np.asarray(result[0],np.float32),point,True)<-2.:
                    failures.append(dict(reason='proved_rectangle_does_not_contain_clicked_point'));continue
                proposed_area=abs(cv2.contourArea(np.asarray(q,np.float32)));proved=np.asarray(result[0],np.float32)
                proved_area=abs(cv2.contourArea(proved));intersection=cv2.intersectConvexConvex(np.asarray(q,np.float32),proved)[0]
                if intersection/max(1.,proposed_area+proved_area-intersection)<.70:
                    failures.append(dict(reason='proved_rectangle_changed_target_candidate'));continue
                self.seed=np.asarray(result[0],np.float32).copy();self.selected=True
                checkpoint('TAP_TARGET_CURRENT_ACCEPTED',attempt=self.calls,current_frame_only=True,
                    luma_first=luma_first,candidate_count=len(candidates))
                return result
            self.cursor+=1
            return None
        try:
            # Admit immediately as proposals arrive; never collect a whole
            # multi-family pool before the first target can reach its gate.
            attempted=0
            for position,q in enumerate(proposals()):
                if position<self.cursor:continue
                if attempted>=4:break
                attempted+=1
                result=try_candidate(q)
                if result is not None:return result
            if not attempted:
                self.cursor=0
                # A new snapshot gets another chance even if its candidate
                # count shrank below the previous frame's search cursor.
                for q in candidates[:4]:
                    result=try_candidate(q)
                    if result is not None:return result
        except TargetSliceExpired:failures.append(dict(reason='target_slice_exhausted_retry_latest_frame'))
        if (candidates or failures) and self.calls<3:
            checkpoint('TAP_TARGET_RETRY',attempt=self.calls,latest_frame_required=True,candidate_count=len(candidates),failures=failures[-6:])
            raise QuadDetectionError('点选候选未通过当前四边验证，换最新画面重试',dict(attempt=self.calls,failures=failures[-6:]))
        self.finished=True
        if self.report is not None:self.report('fallback')
        checkpoint('TAP_TARGET_FALLBACK',search_route_only=True,final_target_result_pending=True,attempts=self.calls,candidate_count=len(candidates),failures=failures[-6:])
        raise QuadDetectionError('点选自动未找到，保留本次目标意图等待AI',dict(selection_only=True,attempts=self.calls))
