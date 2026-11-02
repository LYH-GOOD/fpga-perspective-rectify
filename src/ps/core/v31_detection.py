"""Multicolor rectangles: Y-first or sampled color bands verify all four exterior edges.

First/reacquisition use small color proposals. Normal frames use raw Y first;
weak Y proof may sample bounded raw chroma bands from the same leased frame.
Hue-independent exterior gradients precede white components; never partially refined H.
"""
from pathlib import Path
import hashlib,time
from contextlib import contextmanager
from contextvars import ContextVar
import numpy as np
import cv2
from p11_contract import RELEASE_ID
from p1_paper_quad import find_paper_quad
from v10_quad import refine_edges
from v8_geometry import order_corners
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class QuadDetectionError(ValueError):
    def __init__(self,message,diagnostics):
        super().__init__(message);self.diagnostics=dict(diagnostics)

class _DetectionStop(RuntimeError):
    """Internal cooperative stop; candidate rejection must not swallow it."""

_RECOVERY_BUDGET=ContextVar('p11_recovery_detection_budget',default=None)
_ACQUIRE_CANCEL=ContextVar('p11_acquire_cooperative_cancel',default=None)
_RECOVERY_OBSERVATION=ContextVar('p11_current_Y_observation',default=None)
_RECOVERY_OFFSET=ContextVar('p11_recovery_view_offset',default=(0,0))
_RECOVERY_SEEDS=ContextVar('p11_recent_coarse_candidate_slice',default=None)

class RecoveryBudget:
    def __init__(self,milliseconds,max_candidates,begin=None,begin_cpu=None):
        now=time.perf_counter();cpu=time.thread_time()
        self.begin=now if begin is None else float(begin)
        self.begin_cpu=cpu if begin_cpu is None else float(begin_cpu)
        self.pre_detection_s=max(0.,now-self.begin)
        self.deadline=self.begin+milliseconds/1000.
        self.stage_begin=self.begin;self.stage_cpu=self.begin_cpu;self.stages={}
        self.milliseconds=float(milliseconds);self.max_candidates=int(max_candidates)
        self.candidates=0;self.last_stage='begin';self.stopped=None;self.proposals=[];self.rejections=[];self.admission_active=False
        self.completed_gate_after_deadline=0
    def _stages(self,now,cpu):
        result={k:dict(v) for k,v in self.stages.items()}
        row=result.setdefault(self.last_stage,dict(wall_s=0.,thread_cpu_s=0.,calls=0))
        row['wall_s']+=now-self.stage_begin;row['thread_cpu_s']+=cpu-self.stage_cpu;row['calls']+=1
        return result
    def check(self,stage,finish_gate=False):
        now=time.perf_counter();cpu=time.thread_time()
        # Mutate one interval; copying all nested stage dictionaries at every
        # polygon/profile checkpoint costs time and adds short-lived objects.
        row=self.stages.setdefault(self.last_stage,dict(wall_s=0.,thread_cpu_s=0.,calls=0))
        row['wall_s']+=now-self.stage_begin;row['thread_cpu_s']+=cpu-self.stage_cpu;row['calls']+=1
        self.stage_begin=now;self.stage_cpu=cpu;self.last_stage=stage
        if finish_gate:
            if not self.admission_active:raise RuntimeError('Final gate without an admitted candidate')
            self.completed_gate_after_deadline+=int(now>=self.deadline)
            return  # Finish only the already-refined candidate's safety gate.
        if stage!='candidate_admission' and not self.admission_active and self.candidates>=self.max_candidates:
            self.stopped='candidate_limit'
            raise _DetectionStop('恢复检测达到候选上限')
        if time.perf_counter()>=self.deadline:
            self.stopped='cooperative_deadline'
            raise _DetectionStop('恢复检测达到协作时间预算')
    def claim(self,label,coarse):
        self.check('candidate_admission')
        if self.candidates>=self.max_candidates:
            self.stopped='candidate_limit'
            raise _DetectionStop('恢复检测达到候选上限')
        self.candidates+=1
        self.proposals.append(dict(detector=label,coarse_corners=np.asarray(coarse).tolist()))
    def summary(self):
        now=time.perf_counter();cpu=time.thread_time();elapsed=now-self.begin
        return dict(budget_ms=self.milliseconds,max_candidates=self.max_candidates,
            candidates=self.candidates,elapsed_s=elapsed,thread_cpu_s=cpu-self.begin_cpu,
            pre_detection_s=max(0.,self.begin-getattr(self,'tracker_begin',self.begin)),whole_tracker_budget=False,
            detector_elapsed_s=elapsed,total_tracker_budget_ms=getattr(self,'tracker_budget_ms',None),
            total_tracker_elapsed_s=now-getattr(self,'tracker_begin',self.begin),
            wall_minus_thread_cpu_s=max(0.,elapsed-cpu+self.begin_cpu),stages=self._stages(now,cpu),
            stage_scope="exclusive checkpoint intervals, including CV calls and host wrapper; no double addition",
            overshoot_s=max(0.,elapsed-self.milliseconds/1000.),
            stop_reason=self.stopped,last_stage=self.last_stage,candidate_proposals=list(self.proposals),rejected_candidates=list(self.rejections),
            completed_gate_after_deadline=self.completed_gate_after_deadline,
            deadline_kind='cooperative_between_CV_operations; a running call and final safety gate are not preempted')

@contextmanager
def recovery_detection_scope(budget,observation=None):
    token=_RECOVERY_BUDGET.set(budget);obs_token=_RECOVERY_OBSERVATION.set(observation)
    offset_token=_RECOVERY_OFFSET.set((0,0))
    try:yield
    finally:
        _RECOVERY_OFFSET.reset(offset_token);_RECOVERY_OBSERVATION.reset(obs_token);_RECOVERY_BUDGET.reset(token)

@contextmanager
def recovery_candidate_scope(seeds=(),seed_only=False):
    # Coarse coordinates only. No source image, H or safety receipt is reused.
    value=dict(seeds=tuple(seeds),seed_only=bool(seed_only)) if seeds or seed_only else None
    token=_RECOVERY_SEEDS.set(value)
    try:yield
    finally:_RECOVERY_SEEDS.reset(token)

@contextmanager
def recovery_view_scope(offset):
    token=_RECOVERY_OFFSET.set(tuple(offset))
    try:yield
    finally:_RECOVERY_OFFSET.reset(token)

@contextmanager
def detection_cancel_scope(check):
    # Scoped to the acquisition worker, without changing its detector schedule,
    # thresholds or the already-existing recovery-budget checks.
    token=_ACQUIRE_CANCEL.set(check)
    try:yield
    finally:_ACQUIRE_CANCEL.reset(token)

def _budget_check(stage,finish_gate=False):
    cancel=_ACQUIRE_CANCEL.get()
    if cancel is not None:cancel()
    budget=_RECOVERY_BUDGET.get()
    if budget is not None:budget.check(stage,finish_gate=finish_gate)

def _small_color(image,work_width):
    h,w=image.shape[:2];width=min(w,max(16,int(work_width)))
    if image.ndim==3 and image.shape[2]==2:
        from v31_pixels import require_yuyv,model_bgr
        require_yuyv(image);width=max(2,(width//2)*2)
        height=max(2,int(round(h*width/float(w))))
        pairs=image.reshape(h,w//2,4)
        reduced=cv2.resize(pairs,(width//2,height),interpolation=cv2.INTER_LINEAR) if width<w else pairs
        return model_bgr(np.ascontiguousarray(reduced).reshape(reduced.shape[0],width,2))
    height=max(2,int(round(h*width/float(w))))
    return cv2.resize(image,(width,height),interpolation=cv2.INTER_LINEAR) if width<w else image

def _visible_quad(quad,shape,preserve_order=False):
    # Coarse polygons need sorting. A measured/tracked cyclic order is a
    # physical corner correspondence and must survive rotation/refinement.
    q=np.ascontiguousarray(quad,np.float32) if preserve_order else order_corners(quad)
    if q.shape!=(4,2):raise ValueError('candidate_four_corner_shape_invalid')
    h,w=shape[:2]
    if (not np.isfinite(q).all() or np.any(q<2) or np.any(q[:,0]>w-3) or np.any(q[:,1]>h-3)):
        raise ValueError('candidate_touches_image_border_or_is_clipped')
    if not cv2.isContourConvex(q) or abs(cv2.contourArea(q))<.035*w*h:
        raise ValueError('candidate_not_convex_or_area_too_small')
    edges=np.roll(q,-1,axis=0)-q;lengths=np.linalg.norm(edges,axis=1)
    if lengths.min()<max(12.,.04*min(h,w)) or lengths.min()/lengths.max()<.10:
        raise ValueError('candidate_collapsed_short_edge')
    sine=np.abs(np.cross(edges,np.roll(edges,1,axis=0)))/(lengths*np.roll(lengths,1))
    if np.min(sine)<.15:raise ValueError('candidate_nearly_collinear_corner')
    return q

def exterior_gate(evidence,candidate,proposal,radius,require_light=False):
    """Independent four-edge gate; not relative to a potentially bad old anchor."""
    support=evidence.get('edge_support',[0.]*4);rms=evidence.get('edge_rms',[1e30]*4)
    correction=float(np.max(np.linalg.norm(np.asarray(candidate)-proposal,axis=1)))
    positive=sum(p>0 for p in evidence.get('edge_polarity',[]))
    valid=(evidence.get('valid',False) and evidence.get('supported_edges',0)==4
           and evidence.get('refined_corners',0)==4 and min(support)>=.60
           and max(rms)<=1. and correction<=radius*.65
           and (not require_light or positive>=3))
    return dict(reliable=bool(valid),min_support=float(min(support)),max_rms=float(max(rms)),
                prediction_correction=correction,positive_edges=positive,radius=radius,
                supported_edges=evidence.get('supported_edges',0),refined_corners=evidence.get('refined_corners',0))

def _contour_proposals(gray,limit,incremental=False):
    proposals=_iter_contour_proposals(gray,limit)
    if incremental:return proposals
    return sorted(list(proposals),key=lambda q:abs(cv2.contourArea(q)),reverse=True)[:12]

def _iter_contour_proposals(gray,limit):
    h,w=gray.shape;scale=min(1.,float(limit)/max(h,w));ow,oh=round(w*scale),round(h*scale)
    view=cv2.resize(gray,(ow,oh),interpolation=cv2.INTER_LINEAR) if scale<1 else gray
    blur=cv2.GaussianBlur(view,(5,5),0);candidates=[]
    for low,high in ((15,50),(50,150)):
        _budget_check("Y_contours")
        edges=cv2.dilate(cv2.Canny(blur,low,high),np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours,key=cv2.contourArea,reverse=True)[:20]:
            _budget_check("Y_contour_polygon")
            if abs(cv2.contourArea(c))<.035*ow*oh:continue
            for epsilon in (.012,.022,.04):
                polygon=cv2.approxPolyDP(c,epsilon*cv2.arcLength(c,True),True)
                if len(polygon)!=4 or not cv2.isContourConvex(polygon):continue
                try:q=_visible_quad((order_corners(polygon)+.5)*[w/ow,h/oh]-.5,gray.shape)
                except ValueError:continue
                if not any(np.max(np.linalg.norm(q-old,axis=1))<4. for old in candidates):
                    candidates.append(q);yield q
                break
    return

def _color_proposals(color,source_shape):
    """Adaptive whiteness components, including less neutral white balance.

    Reject border-connected distractors separately rather than assuming the
    largest component is the paper. These are proposals, not accepted corners.
    """
    h,w=color.shape[:2];H,W=source_shape[:2]
    white=np.min(color,axis=2).astype(np.uint8)
    threshold,_=cv2.threshold(white,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    _budget_check('color_statistics')
    saturation=cv2.cvtColor(color,cv2.COLOR_BGR2HSV)[:,:,1]
    bright=white>threshold
    if not bright.any():return []
    # 256-bin integer percentile avoids a float image and selection workspace.
    mask=bright.astype(np.uint8)*255
    hist=cv2.calcHist([saturation],[0],mask,[256],[0,256]).ravel().astype(np.int64)
    cumulative=hist.cumsum();rank=.8*(int(cumulative[-1])-1)
    lo=int(np.searchsorted(cumulative,int(np.floor(rank))+1))
    hi=int(np.searchsorted(cumulative,int(np.ceil(rank))+1))
    percentile=lo+(hi-lo)*(rank-np.floor(rank))
    adaptive=float(np.clip(percentile/255.+.04,.12,.55))
    candidates=[]
    for cutoff in dict.fromkeys((adaptive,min(.55,adaptive+.12))):
        _budget_check("color_components")
        mask=(bright&(saturation<=cutoff*255.)).astype(np.uint8)*255
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
        for label in sorted(range(1,count),key=lambda k:stats[k,cv2.CC_STAT_AREA],reverse=True)[:8]:
            _budget_check("color_polygon")
            x,y,cw,ch,area=stats[label]
            if area<.035*w*h or x<2 or y<2 or x+cw>w-2 or y+ch>h-2:continue
            contours,_=cv2.findContours((labels==label).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            if not contours:continue
            contour=cv2.convexHull(max(contours,key=cv2.contourArea))
            for epsilon in (.012,.022,.04,.065):
                polygon=cv2.approxPolyDP(contour,epsilon*cv2.arcLength(contour,True),True)
                if len(polygon)!=4:continue
                try:q=_visible_quad((order_corners(polygon)+.5)*[W/w,H/h]-.5,source_shape)
                except ValueError:continue
                if not any(np.max(np.linalg.norm(q-old,axis=1))<3 for old in candidates):candidates.append(q)
                break
    return sorted(candidates,key=lambda q:abs(cv2.contourArea(q)),reverse=True)[:8]

def detect_refined(image,limit=640,refine=True,prefer_mask=True,color_reference=None,tracking_limit=320):
    budget=_RECOVERY_BUDGET.get()
    try:return _detect_refined(image,limit,refine,prefer_mask,color_reference,tracking_limit)
    except _DetectionStop as exc:
        detail=dict(reason=str(exc),recovery_budget=budget.summary(),input_shape=list(image.shape))
        from run_logging import checkpoint
        if getattr(budget,'log_detail',True):checkpoint('RECOVERY_DETECTION_STOPPED',**detail)
        else:
            from v58_budget import compact_recovery_summary
            checkpoint('RECOVERY_DETECTION_STOPPED',reason=str(exc),recovery_budget=compact_recovery_summary(detail['recovery_budget']),input_shape=detail['input_shape'])
        raise QuadDetectionError(str(exc),detail) from exc

def current_boundary(image,gray,scale,quad,offset=(0,0),measured=None,evidence=None,checks='auto',allow_color=True,radius=3.,fast_only=False,deadline=None,expected_polarity=None,color_profiles=24,prefer_color=False,prefer_vector=False,source_validated=False,boundary_prior=None):
    """Current exterior: Y fast path or one bounded fused raw-color transaction.

    prefer_color is a request for an actual independent source64 proof; an
    expired call cannot return ordinary small-Y evidence as that proof.
    prefer_vector keeps color recovery continuous without full-frame CSC.
    """
    from v87_v74_tracking import edge_measure
    from v41_quad import refine_boundary,original_y_boundary
    from v49_boundary import array_key
    begin=time.perf_counter();cpu=time.thread_time()
    scale=np.asarray(scale,np.float64);origin=np.asarray(offset,np.float64);q=np.asarray(quad,np.float32)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):raise ValueError('Boundary scale invalid')
    required64=bool(prefer_color);profiles=64 if required64 else color_profiles
    key=array_key(image)
    def validate(e,c):
        gate=exterior_gate(e,c,q,radius)
        flips=0 if expected_polarity is None or e.get('color_vector_proof') else sum(a*b<0 for a,b in zip(expected_polarity,e.get('edge_polarity',[])))
        actual64=(e.get('same_frame_source') and e.get('profiles_per_edge')==64
            and e.get('current_source_key')==key and e.get('source_proof_kind') in ('raw_YUV_profiles','source_color_profiles','source_Y_profiles'))
        gate.update(polarity_flips=flips,actual_source64=bool(actual64),
            reliable=bool(gate['reliable'] and flips<2 and (not required64 or actual64)))
        return gate
    def detail(e,backend):
        e=dict(e);e.update(edge_backend=backend,initial_Y_gate=initial_gate,
            boundary_fallback_s=time.perf_counter()-begin,boundary_fallback_thread_cpu_s=time.thread_time()-cpu)
        return e
    def available():return deadline is None or time.perf_counter()<deadline
    if measured is None or evidence is None:measured,evidence=edge_measure(gray,q,radius,checks)
    evidence=dict(evidence,current_source_key=key);gate=validate(evidence,measured);initial_gate=dict(gate)
    # V49: a reliable current Y fit finishes the ordinary transaction.
    # A historical colour-family hint does not force new colour sampling.
    if gate['reliable'] and not required64:return measured,evidence,gate
    color_attempted=False
    def vector():
        local=_visible_quad((q+.5)*scale-.5-origin,image.shape,preserve_order=True)
        candidate,e=refine_boundary(image,local,max(2.5,min(24.,radius*float(scale.max()))),profiles=profiles,
            max_rms=float(scale.min()),minimum_contrast=8.,fraction_limits=(.12,.88) if profiles==24 else (.10,.90),deadline=deadline,boundary_prior=boundary_prior)
        observed=((candidate+origin+.5)/scale-.5).astype(np.float32)
        e['edge_rms']=[float(v)/float(scale.min()) for v in e['edge_rms']]
        e.update(tracking_roi_offset=origin.tolist(),direct_Y_primary=True,fast_path_chroma_allowed=True)
        e=detail(e,'sampled_current_YUV'+str(profiles));return observed,e,validate(e,observed)
    color_available=allow_color and image.ndim==3 and image.shape[2] in (2,3)
    if color_available and (prefer_vector or source_validated) and available():
        measured,evidence,gate=vector();color_attempted=True
        if gate['reliable']:return measured,evidence,gate
        # A current vector proof uses one definition; another Y crossing is
        # not a substitute when this physical boundary failed or timed out.
        evidence=dict(evidence,valid=False,vector_family_rejected=True)
        return measured,evidence,validate(evidence,measured)
    # An accepted original candidate already has its source64 proof. Do not
    # repeat that proof during its independent current24 safety gate.
    if not source_validated and available():
        proof=original_y_boundary(image,scale,q,offset,radius)
        if proof is not None:
            candidate,e=proof;g=validate(e,candidate)
            if g['reliable']:return candidate,detail(e,'cpp_current_source_Y64'),g
            if required64:measured,evidence,gate=candidate,e,g
    if color_available and not color_attempted and available():
        measured,evidence,gate=vector()
        if gate['reliable']:return measured,evidence,gate
    if required64:
        # Clearing validity is essential: callers also recompute _edge_gate.
        failed=detail(evidence,'source64_required_not_verified')
        failed.update(valid=False,refined_corners=0,supported_edges=0,source64_missing_or_rejected=True)
        return measured,failed,validate(failed,measured)
    if fast_only or source_validated or not available():
        return measured,detail(evidence,evidence.get('edge_backend','current_Y_or_YUV_fast')),gate
    robust,e=refine_boundary(gray,q,radius,profiles=24,max_rms=1.,minimum_contrast=8.,fraction_limits=(.10,.90),deadline=deadline)
    e.update(current_source_key=key)
    return robust,detail(e,'coherent_current_Y24'),validate(e,robust)


def _detect_refined(image,limit,refine,prefer_mask,color_reference,tracking_limit):
    began=time.perf_counter();raw=image.ndim==3 and image.shape[2]==2
    budget=_RECOVERY_BUDGET.get();_budget_check('source_Y_prepare')
    h,w=image.shape[:2];gray=None
    def source_gray():
        nonlocal gray
        if gray is None:
            _budget_check('lazy_source_Y_fallback')
            from v31_pixels import luminance
            gray=luminance(image) if raw else image if image.ndim==2 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        return gray
    observation=dict(input_shape=list(image.shape),gray_source='direct_Y' if raw else 'BGR_or_gray',
        color_assist_used=False,color_assist_requested=bool(prefer_mask),detection_limit=limit,
        coarse_interpolation='INTER_LINEAR',target_policy='multicolor_planar_rectangle',
        fixed_hue_required=False,positive_edges_required=False)
    mask_detail={};failures=[];proposals=[];color=None
    search_limit=min(limit,320) if budget is not None else limit
    work_width=max(16,min(256,round(search_limit*w/max(h,w))))
    from v41_quad import rectangle_proposals,refine_boundary
    color_input=color_reference if color_reference is not None else image
    def prepare_color():
        nonlocal color
        if color is None:
            _budget_check('color_proposal_prepare')
            src=cv2.cvtColor(color_input,cv2.COLOR_GRAY2BGR) if color_input.ndim==2 else color_input
            color=_small_color(src,work_width)
            observation.update(color_work_shape=list(color.shape),color_assist_used=True)
        return color
    # V48: no eager Lab collection before a candidate can reach admission.
    observation['proposal_schedule']='bounded_YUV_outer_enclosure_pool_then_Y_then_bounded_Lab'
    mask_detail['proposal_method']='YUV_gradient_stream_with_original_four_edge_proof' 
    mask_s=time.perf_counter()-began
    from v87_v74_tracking import GrayObserver
    _budget_check('tracking_observation')
    reused=_RECOVERY_OBSERVATION.get() if budget is not None else None
    offset=np.asarray(_RECOVERY_OFFSET.get(),np.float32)
    if reused is None:
        observer=GrayObserver(tracking_limit)
        tracked_gray,tracking_scale=observer.get(image if image.ndim==3 else cv2.cvtColor(image,cv2.COLOR_GRAY2BGR))
        offset[:]=0.;observation['tracking_observation_reused']=False
    else:
        tracked_gray=reused['gray'];tracking_scale=reused['scale']
        if (tracked_gray.ndim!=2 or tracked_gray.dtype!=np.uint8 or np.shape(tracking_scale)!=(2,)
            or not np.isfinite(tracking_scale).all() or np.any(tracking_scale<=0) or np.any(offset<0)
            or offset[0]+w>reused['source_shape'][1] or offset[1]+h>reused['source_shape'][0]):
            raise ValueError('Current Y recovery observation/ROI layout mismatch')
        observation.update(tracking_observation_reused=True,tracking_source_shape=list(reused['source_shape']),tracking_roi_offset=offset.tolist())
    attempted=[];proven_outer=[]
    from v90_transaction import CandidateAttempts
    duplicate_attempts=CandidateAttempts() if budget is not None else None
    def admit(label,coarse):
        from v62_exterior import proven_outer_parent
        parent=proven_outer_parent(coarse,proven_outer)
        if parent is not None:
            failures.append(dict(detector=label,reason='internal_rectangle_has_current_proven_outer',boundary_selection=parent))
            return None
        if budget is not None:budget.claim(label,coarse)
        q=_visible_quad(coarse,image.shape);attempted.append(q.copy())
        half=min(24.,max(6.,.008*max(h,w),2.5*max(h/192.,w/256.)))
        def accepted(e):return (e.get('refined_corners')==4 and len(e.get('edges',[]))==4
            and all(x.get('accepted',False) and x.get('supported',0)>=38 for x in e['edges']))
        result=q;edges={};original=None;attempts=[]
        color_first=prefer_mask and ('multicolor' in label)
        color_attempted=False
        def color_refine():
            _budget_check('original_YUV_band_refinement')
            # Prefer raw YUYV vectors when available: no RGB clipping of a red edge.
            source=image if raw else color_reference if color_reference is not None else image
            if source.shape[:2]!=image.shape[:2]:raise ValueError('Color reference belongs to a different source layout')
            return refine_boundary(source,q,half,deadline=None if budget is None else budget.deadline)
        if color_first and image.ndim==3:
            result,edges=color_refine();color_attempted=True
            attempts.append(dict(backend='coherent_original_YUV64',refinement_s=edges['refinement_s'],refined_corners=edges['refined_corners']))
        if not accepted(edges):
            _budget_check('original_Y_edge_refinement')
            from v87_v74_native import refine_original_y64,refine_original_yuyv64
            native=refine_original_yuyv64(image,q,half) if raw else refine_original_y64(source_gray(),q,half)
            if native is None:
                c=time.thread_time();result,edges=refine_edges(source_gray(),q,half_window=half)
                edges.update(backend='python_original_Y_64x65',refinement_thread_cpu_s=time.thread_time()-c)
            else:result,edges=native
            original=edges
            attempts.append(dict(backend=edges.get('backend'),refinement_s=edges.get('refinement_s',0.),refined_corners=edges.get('refined_corners',0)))
        if not accepted(edges) and prefer_mask and image.ndim==3 and not color_attempted:
            result,edges=color_refine();color_attempted=True
            attempts.append(dict(backend='coherent_original_YUV64',refinement_s=edges['refinement_s'],refined_corners=edges['refined_corners']))
        if not accepted(edges):
            _budget_check('original_Y_coherent_refinement')
            result,edges=refine_boundary(source_gray(),q,half)
            attempts.append(dict(backend='coherent_original_Y64',refinement_s=edges['refinement_s'],refined_corners=edges['refined_corners']))
        edges.update(refinement_attempts=attempts,refinement_attempt_wall_s=sum(a['refinement_s'] for a in attempts),
            original_Y_attempt=original if original is not None and not accepted(original) else None)
        if not accepted(edges):
            failures.append(dict(detector=label,reason='all_four_original_edges_required',corners=q.tolist(),edge_refinement=edges));return None
        result=_visible_quad(result,image.shape,preserve_order=True)
        _budget_check('current_four_edge_gate',finish_gate=budget is not None)
        from v62_policy import proof_band,line_lock,sample_locked_color,detector_source64,current_agreement,declare_current_y24
        from v49_boundary import array_key
        from v51_target import border_signature
        measured=(result+offset+.5)/tracking_scale-.5
        original=detector_source64(image,tracking_scale,edges,derived_gray=gray)
        if original['valid'] and min(original['edge_support'])>=.80 and max(original['edge_rms'])<=.65:
            proven_outer.append(result.copy())
        narrow,half_proof=proof_band(tracking_scale,original)
        # Independent CURRENT24 samples remain on the already selected source
        # primary line. They cannot restart a broad Y/colour crossing search.
        checked,evidence=sample_locked_color(image,tracking_scale,measured,24,
            None if budget is None else budget.deadline,border_signature(edges),
            half_source=half_proof,offset=offset,lock_evidence=original)
        gate=exterior_gate(evidence,checked,measured,3.);lock=line_lock(measured,checked)
        current=declare_current_y24(evidence)
        agreement=current_agreement(checked,measured,current,original,tracking_scale,array_key(image))
        if current.get('profiles_per_edge')!=24:agreement.update(verified=False,reason='detector_independent24_grid_required')
        if not gate['reliable'] or not lock['verified'] or not agreement['verified']:
            failures.append(dict(detector=label,reason='current_observation_left_original_source_line',corners=q.tolist(),
                original_refined_corners=result.tolist(),gate=gate,line_lock=lock,agreement=agreement,edge_evidence=evidence));return None
        source=result+offset
        if reused is not None:_visible_quad(source,reused['source_shape'],preserve_order=True)
        # A receipt for the secondary intersections would falsely bind their
        # evidence to different returned corners. Revalidate in the caller.
        from v69_policy import issue_current_receipt
        receipt=(issue_current_receipt(reused,image,source,original,current,checked,
            tracking_scale,agreement,gate) if not np.any(offset) else None)
        from v62_boundary import issue_startup_receipt
        startup_receipt=(issue_startup_receipt(image,result,original,current,checked,
            tracking_scale,agreement,gate) if not np.any(offset) else None)
        evidence=dict(original,original_source_line_retained=True,current_line_lock=lock,
            current_independent24_agreement=agreement)
        return result,dict(observation,_current_boundary_receipt=receipt,_initial_boundary_receipt=startup_receipt,detector=label,edge_refinement=edges,tracking_validation=gate,
            tracking_edge_evidence=evidence,boundary_selection=dict(policy='source_primary_outer_lines',
                original_source_corners=result.tolist(),independent_current_corners=checked.tolist(),
                line_lock=lock,source64_independent24=agreement,proof_half_source_pixels=half_proof,
                proven_outer_hypotheses=len(proven_outer)),mask_s=mask_s,mask_diagnostics=mask_detail,rejected_candidates=failures,
            area_ratio=float(abs(cv2.contourArea(result))/(w*h)),detection_s=time.perf_counter()-began,
            recovery_budget=None if budget is None else budget.summary())
    def try_admit(label,q):
        if duplicate_attempts is not None and duplicate_attempts.repeated(q,prefer_mask and 'multicolor' in label):
            budget.candidate_duplicate_skips=duplicate_attempts.repeats
            observation['candidate_duplicate_skips']=duplicate_attempts.repeats
            return None
        if any(np.max(np.linalg.norm(np.asarray(q)-old,axis=1))<2. for old in attempted):return None
        before=len(failures)
        if budget is not None:budget.admission_active=True
        try:result=admit(label,q)
        except (ValueError,cv2.error) as exc:failures.append(dict(detector=label,reason=str(exc)));result=None
        finally:
            if budget is not None:budget.admission_active=False
        if budget is not None and result is None:budget.rejections.extend(failures[before:])
        return result
    try:
        saved=_RECOVERY_SEEDS.get()
        if saved is not None:
            observation['proposal_schedule']='recent_coarse_hint_current_source_reproof'
            observation['recent_candidate_slice']=True
            for seed in saved['seeds']:
                _budget_check('recent_candidate_current_admission')
                coarse=np.asarray(seed.get('coarse_corners'),np.float32)
                if coarse.shape!=(4,2) or not np.isfinite(coarse).all():continue
                result=try_admit('v67_recent_'+str(seed.get('detector','multicolor_exterior')),coarse)
                if result is not None:return result
            if saved['seed_only']:
                if budget is not None:budget.stopped='recent_candidate_slice_miss'
                raise _DetectionStop('候选复用片段未通过当前四边准入；后续请求继续或扩大搜索')
        if budget is not None:
            current=None if reused is None else reused.get('verified_edge_proposal')
            if current is not None:
                local=np.asarray(current,np.float32)-offset
                try:local=_visible_quad(local,image.shape)
                except ValueError:local=None
                if local is not None:
                    result=try_admit('current_exterior_original_verified',local)
                    if result is not None:return result
        if prefer_mask:
            from v48_candidates import exterior_candidates
            # Keep at least one admission for a different proposal family.
            # Previously a pair of rejected nested color contours exhausted
            # the ordinary two-candidate budget before Y had any opportunity.
            color_limit=None if budget is None else max(1,budget.max_candidates//2)
            observation['color_candidate_limit']=color_limit
            for q in exterior_candidates(image,_budget_check,192):
                if budget is not None and budget.candidates>=color_limit:break
                result=try_admit('stream_multicolor_exterior',q)
                if result is not None:return result
        if budget is not None:
            _budget_check('next_current_Y_search')
            small=tracked_gray
            y_limit=budget.max_candidates  # consume the remaining Y admissions; heavy fallback requires spare budget
            observation['Y_admission_limit_before_color']=y_limit
            for proposal in (_contour_proposals(small,min(240,search_limit),incremental=True) if budget.candidates<y_limit else ()):
                q=(proposal+.5)*tracking_scale-.5-offset
                try:q=_visible_quad(q,image.shape)
                except ValueError:continue
                result=try_admit('current_Y_contour_verified',q)
                if result is not None:return result
                if budget.candidates>=y_limit:break
            if prefer_mask:
                from v45_color import iter_recovery_rectangles
                permit=getattr(budget,'can_start_stage',None)
                cheap_ok=permit('Lab_contour',.025,.04) if permit is not None else budget.deadline-time.perf_counter()>=.16
                if cheap_ok:
                    allow_lines=lambda:permit('Hough160',.10,.14) if permit is not None else budget.deadline-time.perf_counter()>=.26
                    observation.update(color_fallback_used=True,color_proposal_schedule='immediate_contour_admission_then_budgeted_Hough160')
                    # Generator yields into the unchanged strict admit function.
                    # A successful cheap contour returns before Hough is called.
                    for q in iter_recovery_rectangles(prepare_color(),image.shape,_budget_check,allow_lines,max_candidates=8):
                        result=try_admit('multicolor_gradient_rectangle',q)
                        if result is not None:return result
                else:observation['heavy_color_fallback_deferred']='insufficient_compute_or_wall_for_search_plus_admission'
        for label,q in proposals:
            result=try_admit(label,q)
            if result is not None:return result
        if prefer_mask and budget is None:
            # Full startup may use heavier Lab/line fallback only after streams.
            for q in rectangle_proposals(prepare_color(),image.shape,_budget_check,max_candidates=12,include_lines=True):
                result=try_admit('multicolor_line_fallback',q)
                if result is not None:return result
        # White paper remains a fallback, not a universal definition of a target.
        if prefer_mask and color is not None and budget is None:
            _budget_check('legacy_paper_fallback')
            proposal=find_paper_quad(color,work_width=color.shape[1],camera_color=True,diagnostics=mask_detail)
            if proposal is not None:
                q=(np.asarray(proposal,np.float32)+.5)*[w/color.shape[1],h/color.shape[0]]-.5
                result=try_admit('p1_camera_white_fallback',q)
                if result is not None:return result
            for q in _color_proposals(color,image.shape):
                result=try_admit('adaptive_white_fallback',q)
                if result is not None:return result
        coarse_limit=min(search_limit,max(160,round(max(h,w)/3.)))
        for contour_limit in dict.fromkeys((coarse_limit,search_limit)):
            for proposal in _contour_proposals(tracked_gray,contour_limit):
                q=(proposal+.5)*tracking_scale-.5-offset
                result=try_admit('Y_contour_verified',q)
                if result is not None:return result
    except (ValueError,cv2.error) as exc:failures.append(dict(detector='candidate_validation',reason=str(exc)))
    from run_logging import checkpoint
    detail=dict(observation,mask_s=mask_s,mask_diagnostics=mask_detail,rejected_candidates=failures,
        contour_or_refinement_reason='no_candidate_with_four_verified_exterior_edges',detection_s=time.perf_counter()-began,
        recovery_budget=None if budget is None else budget.summary())
    if budget is None or getattr(budget,'log_detail',True):checkpoint('DOCUMENT_DETECTION_FAILED',**detail)
    else:
        from v58_budget import compact_recovery_summary
        checkpoint('DOCUMENT_DETECTION_FAILED',reason=detail['contour_or_refinement_reason'],recovery_budget=compact_recovery_summary(detail['recovery_budget']))
    raise QuadDetectionError('未找到四条可信矩形外边缘；不提交错误 H。请查看候选与四边诊断。',detail)
