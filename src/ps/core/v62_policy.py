"""V61 bounded current-edge policies; owns no frame leases or device IO."""
from pathlib import Path
import hashlib,time
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class LKWorkBudgetExceeded(ValueError):
    """A completed failed FB attempt cannot retry within its compute window."""

class LKPhaseBudget:
    """Budget whole attempts, never half of a forward/backward transaction."""
    def __init__(self,cpu_s=.12,wall_s=.40):
        self.begin=time.perf_counter();self.cpu=time.thread_time()
        self.cpu_s=float(cpu_s);self.wall_s=float(wall_s)
        self.deadline=self.begin+self.wall_s
    def retry_allowed(self):
        return time.thread_time()-self.cpu<self.cpu_s and time.perf_counter()<self.deadline
    def summary(self):
        wall=time.perf_counter()-self.begin;cpu=time.thread_time()-self.cpu
        return dict(budget_basis='thread_CPU_with_separate_wall_guard',cpu_budget_s=self.cpu_s,
            wall_guard_s=self.wall_s,wall_s=wall,thread_cpu_s=cpu,
            wall_minus_thread_cpu_s=max(0.,wall-cpu),cpu_budget_hit=cpu>=self.cpu_s,
            wall_guard_hit=wall>=self.wall_s,cpu_overshoot_s=max(0.,cpu-self.cpu_s),
            wall_overshoot_s=max(0.,wall-self.wall_s),complete_FB_attempt_reserved=True,
            old_prepare_wall_deadline_used=False,scope='cooperative; complete checks never split')

def proof_band(scale,evidence=None):
    """A source-pixel proof band independent of the motion search radius."""
    scale=np.asarray(scale,np.float64)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):
        raise ValueError('Current proof requires positive finite 2D scale')
    rms=[] if evidence is None else evidence.get('edge_rms',[])
    noise=max(rms)*float(np.min(scale)) if len(rms)==4 and all(np.isfinite(v) and 0<=v<=2. for v in rms) else 0.
    # Current fit noise widens only the sampling band, never the line lock.
    half=float(np.clip(max(3.,1.5*float(np.min(scale)))+1.25*noise,3.,6.))
    return half/float(np.max(scale)),half

def sample_locked_color(image,scale,quad,profiles,deadline,boundary_prior=None,half_source=None,offset=(0,0),lock_physical=True,lock_evidence=None):
    """Use existing packed native sampling without another gray edge search.

    Sampling width and the caller's geometric tolerance are separate. Source
    provenance/line fits are real, supplied by the existing refine_boundary.
    No source arrays or pointers escape this synchronous CPU transaction.
    """
    from v31_detection import _visible_quad
    from v41_quad import refine_boundary
    begin=time.perf_counter();cpu=time.thread_time()
    scale=np.asarray(scale,np.float64);_,default_half=proof_band(scale)
    half=default_half if half_source is None else float(half_source)
    if not np.isfinite(half) or not 2.5<=half<=24.:raise ValueError('Current sample half-window must be2.5..24 source pixels')
    origin=np.asarray(offset,np.float64)
    if origin.shape!=(2,) or not np.isfinite(origin).all():raise ValueError('Current sample offset invalid')
    q=np.asarray(quad,np.float32)
    local=_visible_quad((q+.5)*scale-.5-origin,image.shape,preserve_order=True)
    from v62_boundary import peak_radius
    peak=peak_radius(scale,lock_evidence or {},half) if lock_physical else None
    candidate,evidence=refine_boundary(image,local,half,profiles=profiles,
        max_rms=float(scale.min()),minimum_contrast=8.,
        fraction_limits=(.12,.88) if profiles==24 else (.10,.90),
        deadline=deadline,boundary_prior=boundary_prior,line_lock_radius=peak)
    observed=((candidate+origin+.5)/scale-.5).astype(np.float32)
    evidence=dict(evidence,edge_rms=[float(v)/float(scale.min()) for v in evidence['edge_rms']],
        edge_backend='locked_current_YUV'+str(profiles),tracking_roi_offset=origin.tolist(),
        boundary_fallback_s=time.perf_counter()-begin,
        boundary_fallback_thread_cpu_s=time.thread_time()-cpu,
        direct_locked_band=True,repeated_gray_edge_search=False)
    return observed,evidence

def line_lock(reference,candidate):
    """Check both quads' lines, not just potentially sensitive intersections."""
    from v90_transaction import pair_geometry
    error,normal,corner=pair_geometry(reference,candidate)
    if error is not None:
        return dict(verified=False,reason='invalid_line_lock' if error=='invalid' else 'degenerate_line_lock')
    return dict(verified=bool(normal<=.75 and corner<=1.5),line_normal_difference=normal,
        normal_limit=.75,corner_difference=corner,corner_limit=1.5,units='tracking_pixels',
        lock='one_current_primary_edge_reference',old_H_not_used=True)

def stable_current(evidence,gate,candidate,previous,age,max_gap,scheduled=False,lost=False):
    """Fresh strong Y uses the original normal path; maximum FB age remains."""
    shift=float(np.max(np.linalg.norm(np.asarray(candidate)-previous,axis=1)))
    supports=evidence.get('edge_support',[0.]*4);rms=evidence.get('edge_rms',[1e30]*4)
    okay=(not lost and not scheduled and 0<=age<max_gap and gate.get('reliable',False)
        and evidence.get('valid',False) and evidence.get('supported_edges')==4
        and evidence.get('refined_corners')==4 and not evidence.get('color_vector_proof',False)
        and len(supports)==4 and len(rms)==4 and min(supports)>=.75 and max(rms)<=.50
        and gate.get('polarity_flips',1)==0 and gate.get('prediction_correction',1e30)<=1.
        and shift<=1.5)
    return dict(eligible=bool(okay),policy='V58_normal_current_Y_four_edges',corner_shift=shift,
        max_shift=1.5,min_support=.75,max_rms=.50,anchor_age=int(age),max_anchor_age=int(max_gap),
        current_four_edges_required=True,scheduled_FB_not_skipped=True,reacquisition=False)

def stable_fb_context(detail,travel,correction,lost,elapsed,processing_gap=False):
    """Bounded same-target tolerance only AFTER complete current FB/four-edge fit.

    A proven latest-slot processing skip may use up to .75s elapsed, with tighter
    motion/FB/inlier bounds. A genuine/stale/invalid capture gap is not eligible.
    New-target admission and LOST remain strict; current independent proof stays.
    """
    if lost or elapsed is None or not np.isfinite(elapsed) or not np.isfinite(travel):return False
    common=(0<float(elapsed)<=.75 and travel<=6. and correction<=2.5
        and detail.get('good_features',0)>=4 and detail.get('inlier_fraction',0.)>=.85
        and detail.get('fb_median',1e30)<.7)
    if not common:return False
    if float(elapsed)<=.35:return True
    return bool(processing_gap and travel<=3. and correction<=1.5
        and detail.get('good_features',0)>=6 and detail.get('inlier_fraction',0.)>=.90
        and detail.get('fb_median',1e30)<.35)


def declare_current_y24(evidence):
    # These helpers really sample 24 positions .055..945; this is NOT source64.
    if evidence.get('profiles_per_edge') is None and evidence.get('edge_backend') in (
            'cpp_analytic_tls','cpp_edges_gate_motion_context','numpy_analytic_tls'):
        return dict(evidence,profiles_per_edge=24,fraction_limits=[.055,.945],
            sampling_metadata='fixed_current_tracking_Y24_grid')
    return evidence

def stable_rms_limit(scale):
    scale=np.asarray(scale,np.float64)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):raise ValueError('Current RMS scale invalid')
    # Source-pixel precision floor: 1.5 source pixels, <=.85 observation pixels.
    return float(np.clip(1.5/float(np.min(scale)),.65,.85))

def detector_source64(image,scale,edges,derived_gray=None):
    """Bind the already executed original64 fit to its current detector input.

    This adapter is called synchronously immediately after the original
    refinement. It rejects unknown grids/backends and never accepts an old
    receipt. P1 native and Python profiles really use .06..94 and64 positions.
    Vector evidence must carry the key of this input or its same-call derived Y.
    """
    from v49_boundary import array_key
    reports=edges.get('edges',[]);key=array_key(image)
    p1=edges.get('method')=='p1_pyramid_subpixel_profiles_tls'
    if p1:
        if len(reports)!=4 or any(r.get('profiles')!=64 for r in reports):
            raise ValueError('Original P1 source64 grid missing')
        kind='source_Y_profiles';fractions=[.06,.94]
    else:
        keys=[key]
        if derived_gray is not None:keys.append(array_key(derived_gray))
        if (not edges.get('same_frame_source') or edges.get('profiles_per_edge')!=64
                or edges.get('current_source_key') not in keys or edges.get('deadline_hit')
                or edges.get('source_proof_kind') not in ('raw_YUV_profiles','source_color_profiles','source_Y_profiles')):
            raise ValueError('Original source64 provenance missing')
        kind=edges['source_proof_kind'];fractions=edges.get('fraction_limits',[])
        if len(fractions)!=2:raise ValueError('Original source64 sampling limits missing')
    if len(reports)!=4 or edges.get('refined_corners')!=4 or any(not r.get('accepted') for r in reports):
        raise ValueError('Original source64 does not contain four fitted lines')
    supports=[float(r.get('retained',0))/64. for r in reports]
    rms=[float(r.get('tls_rms',1e30))/float(np.min(scale)) for r in reports]
    polarities=edges.get('edge_polarity')
    if polarities is None:
        polarities=[int(np.sign(r.get('profile_contrast',0.))) if abs(r.get('profile_contrast',0.))>=8 else 0 for r in reports]
    valid=bool(min(supports)>=.60 and all(r.get('coverage',0.)>=.60 for r in reports))
    return dict(edges,valid=valid,supported_edges=sum(v>=.60 for v in supports),
        refined_corners=4 if valid else 0,edge_support=supports,edge_rms=rms,edge_polarity=polarities,
        profiles_per_edge=64,fraction_limits=list(fractions),same_frame_source=True,
        current_source_key=key,source_proof_kind=kind,edge_backend='detector_original_source64',
        evidence_adapter='synchronous_original_fit_grid_and_source_key_checked',deadline_hit=False)

def current_agreement(first,second,first_e,second_e,scale,source_key,stable_fb=False):
    """Strict new-target proof; bounded noise tolerance after complete current FB.

    No tolerance for LOST/new admission. Both independently measured current
    fits must still contain all four physical lines and actual source64 data.
    """
    from v49_boundary import exterior_agreement
    result=exterior_agreement(first,second,first_e,second_e,scale,source_key=source_key)
    limit=stable_rms_limit(scale)
    result.update(admission_policy='strict_current_reacquisition',stable_FB_support_tolerance=False,
        strict_new_candidate_support=.80,strict_new_candidate_rms=.65,stable_FB_rms_limit=limit,admission_grade='new_or_current_strict')
    if result.get('verified') or not stable_fb:return result
    a=first_e.get('edge_support',[0.]*4);b=second_e.get('edge_support',[0.]*4)
    eligible=(first_e.get('profiles_per_edge')==24 and len(a)==4 and len(b)==4
        and min(a)>=.75 and min(b)>=.75 and result.get('source64_provenance_verified',False)
        and result.get('independent_sampling_verified',False) and first_e.get('valid',False)
        and second_e.get('valid',False) and first_e.get('supported_edges')==4
        and second_e.get('supported_edges')==4 and first_e.get('refined_corners')==4
        and second_e.get('refined_corners')==4 and result.get('max_rms',1e30)<=limit
        and result.get('line_normal_difference',1e30)<=min(.75,result.get('normal_limit',0.))
        and result.get('corner_difference',1e30)<=1.)
    result.update(verified=bool(eligible),stable_FB_support_tolerance=bool(eligible),
        complete_current_FB_required=True,strict_new_candidate_threshold_unchanged=True,
        admission_policy='stable_current_FB_independent_edges' if eligible else 'strict_current_reacquisition',
        admission_grade='stable_FB_bounded_noise' if eligible else 'weak_current_hold_and_remeasure_required')
    return result

def search_gate(evidence,candidate,proposal,radius):
    """Bound a coarse/transported search separately from CURRENT proof agreement.

    Corner intersection sensitivity must not be treated as disagreement between
    the independent source64 and24 fits. Bounded line drift, area and corners
    still restrict this proposal-to-primary search; strict admission follows.
    """
    from v31_detection import exterior_gate
    import cv2
    a=np.asarray(proposal,np.float32);b=np.asarray(candidate,np.float32)
    if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return dict(reliable=False,reason='invalid_search_quad')
    g=exterior_gate(evidence,b,a,radius)
    d=line_lock(a,b)
    area=abs(cv2.contourArea(a));ratio=abs(cv2.contourArea(b))/max(area,1.)
    normal_limit=min(6.,.95*float(radius));corner_limit=min(9.,1.30*float(radius))
    valid=(evidence.get('valid',False) and evidence.get('supported_edges')==4
        and evidence.get('refined_corners')==4 and g['min_support']>=.60 and g['max_rms']<=1.
        and cv2.isContourConvex(b) and .80<=ratio<=1.25
        and d.get('line_normal_difference',1e30)<=normal_limit
        and g['prediction_correction']<=corner_limit)
    return dict(g,reliable=bool(valid),gate_kind='bounded_search_before_strict_current_proof',
        line_normal_difference=d.get('line_normal_difference'),normal_limit=normal_limit,
        corner_limit=corner_limit,area_ratio=ratio,independent_proof_not_granted=True)



def sample_locked_pair(image,scale,quad,deadline,evidence,half,cpu_budget_s=.12):
    """Optional native fusion for an already trusted same-target locked line."""
    from v31_detection import _visible_quad
    from v87_v74_native import fused_locked_pair
    from v62_boundary import peak_radius
    from v51_target import border_signature
    scale=np.asarray(scale,np.float64);q=np.asarray(quad,np.float32)
    local=_visible_quad((q+.5)*scale-.5,image.shape,preserve_order=True)
    result=fused_locked_pair(image,local,half,peak_radius(scale,evidence,half),float(scale.min()),
        deadline,border_signature(evidence),cpu_budget_s)
    if result is None:return None
    primary,secondary,detail=result;converted=[]
    for observed,source in (primary,secondary):
        observed=((observed+.5)/scale-.5).astype(np.float32)
        source=dict(source,edge_rms=[float(v)/float(scale.min()) for v in source['edge_rms']],
            edge_backend='locked_current_YUV'+str(source['profiles_per_edge']),tracking_roi_offset=[0.,0.],
            direct_locked_band=True,repeated_gray_edge_search=False,paired_native_transaction=True)
        converted.append((observed,source))
    return converted[0],converted[1],detail
