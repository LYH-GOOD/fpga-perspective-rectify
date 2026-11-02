"""Failure-only current edge proof after a quiet scheduled FB audit.

No hardware calls, native compilation, altered LK gates or stored image/H.
"""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def recover_audit_edges(tracker,image,gray,candidate,evidence,prediction,previous,gate,
                        reason,trigger,lost_at_entry,source_gap):
    """Independent current Y24/Y64 may reanchor; a failed LK is never promoted."""
    if (lost_at_entry or source_gap or tracker.lost or tracker.checks!='auto'
            or tracker.policy!='motion_adaptive' or trigger not in ('adaptive_age','hard_maximum_age')
            or candidate is None or evidence is None or not gate.get('reliable')
            or evidence.get('color_vector_proof') or not evidence.get('valid')
            or evidence.get('supported_edges')!=4 or evidence.get('refined_corners')!=4
            or gate.get('min_support',0.)<.80 or gate.get('max_rms',1e30)>.50
            or gate.get('prediction_correction',1e30)>.75):return None
    elapsed=getattr(tracker,'source_elapsed_s',None)
    timing=tracker.last_lk_timing;flow=timing.get('forward_backward_flow_s')
    code=timing.get('native_checked_code')
    if (elapsed is None or not np.isfinite(elapsed) or not 0<float(elapsed)<=.35
            or flow is None or not np.isfinite(flow) or flow<0
            or (code is not None and code<=-100)):return None
    q=np.asarray(candidate,np.float32);scale=tracker.scale
    if (q.shape!=(4,2) or not np.isfinite(q).all()
            or float(np.max(np.linalg.norm(q-previous,axis=1)))>1.):return None
    from v49_boundary import array_key,actual_source64
    from v62_policy import proof_band,line_lock,declare_current_y24,current_agreement
    from v87_v74_tracking import _valid
    from v31_pixels import require_yuyv,color_mode
    from v91_native import _decode_source64
    # Match the current image/gray/index scope created by this update. The raw
    # camera lease stays owned by the sole PS producer throughout the call.
    scope=(id(image),array_key(image),id(gray),array_key(gray),int(tracker._update_index),tuple(float(v) for v in scale))
    if tracker.current_proofs.scope!=scope or tracker.last_gray is not gray:return None
    lock=line_lock(previous,q)
    if not lock.get('verified') or not _valid(q,gray.shape,previous,tracker.checks):return None
    if image.ndim!=3 or image.shape[2]!=2:return None
    require_yuyv(image)
    work=tracker.post_lk
    if work.kernels is None:return None
    begin=time.perf_counter();cpu=time.thread_time()
    deadline=min(begin+.075,tracker._frame_deadline or begin+.075)
    detail=dict(attempted=True,verified=False,failed_LK_reason=reason,failed_LK_trigger=trigger,
        LK_audit_passed=False,current_source_only=True,proof_cpu_budget_s=.025,
        independent_grids=[[24,.055,.945],[64,.06,.94]],old_H_used=False)
    timing['audit_current_reproof']=detail
    def finish(value=None,why=None):
        detail.update(wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu)
        if why is not None:detail['reason']=why
        if detail['thread_cpu_s']>.025 or time.perf_counter()>deadline:
            detail.update(verified=False,reason='audit_current_reproof_budget_exceeded');return None
        return value
    try:
        # Discard pending source64 from the failed LK geometry. Reuse only its
        # allocated scratch and original pinned native library, never its proof.
        work.clear();tracker._promoted_points=None
        narrow,half=proof_band(scale,evidence)
        local=work.proposed;local[:]=(q+.5)*scale-.5
        h,w=image.shape[:2]
        if (not np.isfinite(local).all() or np.any(local<2) or np.any(local[:,0]>w-3)
                or np.any(local[:,1]>h-3) or not cv2.isContourConvex(local.astype(np.float32))):
            return finish(why='audit_source_quad_not_visible')
        if time.perf_counter()>deadline:return finish(why='audit_reproof_deadline_before_sampling')
        code=work.kernels.p11_yuyv_refine64(image.ctypes.data,w,h,image.strides[0],color_mode(),
            local.ctypes.data,half,work.source.ctypes.data,work.source_stats.ctypes.data)
        if code:return finish(why='audit_original_Y64_kernel_rejected:'+str(code))
        result,raw=_decode_source64(local,half,work.source,work.source_stats)
        edges=raw['edges'];support=[e.get('retained',0)/64. if e.get('accepted') else 0. for e in edges]
        rms=[float(e.get('tls_rms',1e30))/float(scale.min()) for e in edges]
        contrast=np.asarray([e.get('profile_contrast',0.) for e in edges],np.float64)
        valid=(raw.get('refined_corners')==4 and len(edges)==4 and all(e.get('accepted') for e in edges)
            and min(support)>=.60 and all(e.get('coverage',0.)>=.60 for e in edges))
        observed=((result+.5)/scale-.5).astype(np.float32)
        source=dict(valid=bool(valid),refined_corners=4 if valid else 0,supported_edges=sum(s>=.60 for s in support),
            edge_support=support,edge_rms=rms,edge_polarity=np.where(np.abs(contrast)>=8,np.sign(contrast),0).astype(int).tolist(),
            edge_backend='cpp_current_source_Y64',source_proof=raw,same_frame_source=True,
            profiles_per_edge=64,fraction_limits=[.06,.94],current_source_key=array_key(image),source_proof_kind='source_Y_profiles')
        checked=tracker._edge_gate(source,observed,q,3.)
        agreement=current_agreement(q,observed,declare_current_y24(evidence),source,scale,array_key(image),stable_fb=False)
        primary_lock=line_lock(q,observed);previous_lock=line_lock(previous,observed)
        detail.update(validation=checked,agreement=agreement,line_lock=primary_lock,previous_line_lock=previous_lock,
            narrow_radius_tracking=float(narrow),half_window_source=float(half),source64_reused_from_failed_LK=False)
        strict=(checked.get('reliable') and checked['min_support']>=.80 and checked['max_rms']<=.65
            and agreement.get('verified') and primary_lock.get('verified') and previous_lock.get('verified')
            and actual_source64(source,array_key(image)) and _valid(observed,gray.shape,previous,tracker.checks))
        if not strict:return finish(why='audit_current_independent_edges_rejected')
        # Completion is a CURRENT-edge success, not a successful optical-flow
        # audit. Seed real CURRENT points/gray later; do not promote failed flow.
        detail.update(verified=True,force_current_anchor=True,LK_audit_passed=False)
        outcome=finish((observed,source,dict(state='audit_failed_current_edges_twice_verified',
            audit_failure_reproved=True,force_current_anchor=True,first_validation=dict(gate),second_validation=checked,
            source_line_agreement=agreement,audit_current_reproof=detail,old_H_not_used=True)))
        if outcome is not None:
            tracker.last_source_confirmation=dict(agreement,verified=True,final_gate=dict(checked),audit_current_reproof=True)
        return outcome
    except (ValueError,cv2.error) as exc:return finish(why='audit_current_reproof_rejected:'+str(exc))
