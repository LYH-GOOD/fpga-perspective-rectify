"""Failure-only current exterior grades and retry routing; CPU metadata only."""
from pathlib import Path
import hashlib,math,time
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def flow_failure_class(timing,reason):
    fit=timing.get('motion_fit') or {}
    complete=('forward_backward_flow_s' in timing and fit.get('good_features',0)>=4
        and fit.get('inlier_fraction',0.)>=.85 and fit.get('fb_median',1e30)<.7)
    if not complete:return 'motion_unproved'
    if 'candidate_touches_image_border_or_is_clipped' in str(reason):return 'current_geometry_clipped'
    if (timing.get('failure_class')=='current_exterior_mismatch'
        or 'four' in str(reason) or '四' in str(reason) or 'source64' in str(reason)):
        return 'current_exterior_unproved'
    return 'motion_unproved'


def _reports(evidence,n):
    reports=evidence.get('edges',());supports=evidence.get('edge_support',())
    if len(reports)!=4 or len(supports)!=4:return None
    if (not evidence.get('valid') or evidence.get('supported_edges')!=4
        or evidence.get('refined_corners')!=4 or evidence.get('profiles_per_edge')!=n
        or evidence.get('deadline_hit') or not evidence.get('color_vector_proof')):return None
    counts=[];coverage=[]
    for report,support in zip(reports,supports):
        retained=report.get('retained',0);span=report.get('coverage',0.)
        if (report.get('profiles')!=n or not report.get('accepted')
            or not 0<retained<=n or not math.isfinite(float(support))
            or abs(float(support)-retained/n)>1e-5 or not math.isfinite(float(span)) or span<.62):return None
        counts.append(int(retained));coverage.append(float(span))
    return counts,coverage


def joint_color_grade(first,second,agreement,source_key,stable_fb=False):
    """Two actual current sample grids; no missing edge or old-H substitution.

    A tight joint-sample grade can resolve discretization differences at new
    admission. A single weaker primary side additionally requires complete
    same-target FB plus very strong independent24 and tighter line agreement.
    """
    if (not agreement.get('source64_provenance_verified') or not agreement.get('independent_sampling_verified')
        or first.get('current_source_key')!=source_key or not first.get('same_frame_source')):return None
    a=_reports(first,24);b=_reports(second,64)
    if a is None or b is None:return None
    n24,n64=a[0],b[0]
    rms=agreement.get('max_rms',1e30);normal=agreement.get('line_normal_difference',1e30)
    corner=agreement.get('corner_difference',1e30);limit=agreement.get('normal_limit',0.)
    quantized=(min(n64)>=51 and min(n24)>=21 and rms<=.50
        and normal<=min(.75,limit) and corner<=1.)
    tight=rms<=.35 and normal<=min(.50,limit) and corner<=.80
    # >=21/24 and >=48/64, with >=71/88 paired retained samples on EVERY
    # physical side. Both grids retain broad spatial coverage and fitted lines.
    joint=tight and all(x>=21 and y>=48 and x+y>=71 for x,y in zip(n24,n64))
    stable=(stable_fb and min(n24)>=21 and sum(n24)>=91
        and min(n64)>=40 and sum(n64)>=212
        and sum(y<48 for y in n64)<=1 and sum(y>=55 for y in n64)>=3
        and agreement.get('max_rms',1e30)<=.30
        and agreement.get('line_normal_difference',1e30)<=.40
        and agreement.get('corner_difference',1e30)<=.65)
    if not quantized and not joint and not stable:return None
    return dict(verified=True,admission_grade='current_color_count_quantization' if quantized else
        'joint_current_color_samples' if joint else 'stable_FB_single_sparse_color_edge',
        admission_policy='current_source64_and_independent24_spatial_evidence',
        joint_sample_grade=True,stable_FB_support_tolerance=bool(stable and not joint and not quantized),
        per_edge_retained24=n24,per_edge_retained64=n64,
        per_edge_joint_support=[(x+y)/88. for x,y in zip(n24,n64)],
        minimum_coverage=min(a[1]+b[1]),complete_current_FB_required=bool(stable and not joint and not quantized),
        all_four_current_fitted_lines_required=True,zero_support_edge_allowed=False,
        original_support_values_preserved=True,global_threshold_unchanged=True)


def low_contrast_retry(image,quad,half,failed,deadline=None):
    """One small-band retry only after three well-fitted source color sides.

    Harmonize original color contrast12 with the existing tracking contrast8;
    never whiten the image, expand the candidate or accept a missing fourth edge.
    """
    reports=failed.get('edges',())
    if (not failed.get('color_vector_proof') or failed.get('deadline_hit') or len(reports)!=4
        or sum(bool(r.get('accepted')) and r.get('retained',0)>=48
            and r.get('coverage',0.)>=.62 and r.get('tls_rms',1e30)<=1. for r in reports)<3):return None
    began=time.perf_counter();cpu=time.thread_time()
    end=min(began+.10,float(deadline)) if deadline is not None else began+.10
    if end-began<.025:return None
    from v41_quad import refine_boundary
    result,evidence=refine_boundary(image,quad,min(8.,float(half)),profiles=64,
        max_rms=1.,minimum_contrast=8.,deadline=end)
    detail=dict(attempted=True,minimum_contrast=8.,previous_minimum_contrast=12.,
        half_source_pixels=min(8.,float(half)),wall_s=time.perf_counter()-began,
        thread_cpu_s=time.thread_time()-cpu,wall_guard_s=end-began,
        source_shape=list(image.shape),four_edges_still_required=True,
        full_image_enhancement=False,full_image_copy=False)
    evidence=dict(evidence,low_contrast_band_retry=detail)
    return result,evidence,detail
