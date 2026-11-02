"""Failure-only current bands: retain fitted lines, repair one side, no IO."""
from pathlib import Path
import hashlib,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LOCAL=threading.local()


def _workspace():
    if not hasattr(_LOCAL,'work'):
        _LOCAL.work=dict(t=np.linspace(.10,.90,64),offset=np.linspace(-1.,1.,65),
            bands=np.zeros((4,64,65,3),np.float32))
    return _LOCAL.work


def _selection(data,half,minimum_contrast=12.,line_lock_radius=None):
    from v31_native import coherent_profiles
    from v41_quad import _coherent_offsets
    # The old ABI accepts four bands. Zero dummy sides have no hypotheses;
    # only the requested side is sampled or fitted during a single-side repair.
    work=_workspace();work['bands'].fill(0);work['bands'][:len(data)]=data
    result=coherent_profiles(work['bands'],half,(.10,.90),minimum_contrast,line_lock_radius=line_lock_radius)
    if result is not None:return result[0][:len(data)].copy()
    values=[]
    for band in data:
        selected=_coherent_offsets(band,work['offset']*half,work['t'],minimum_contrast,
            line_lock_radius=line_lock_radius)
        values.append(np.zeros((64,3),np.float32) if selected is None else
            np.stack((selected[0],selected[1],selected[2]),axis=1))
    return np.asarray(values)


def _sample(image,q,normal,edges,half):
    from v45_color import vector_profiles
    t=_workspace()['t'];offset=_workspace()['offset']*half
    edge=np.roll(q,-1,axis=0)-q
    base=q[edges,None,:]+t[None,:,None]*edge[edges,None,:]
    xy=base[:,:,None,:]+offset[None,None,:,None]*normal[edges,None,None,:]
    values=vector_profiles(image,xy[...,0].reshape(-1,65),xy[...,1].reshape(-1,65))
    return base,values.reshape(len(edges),64,65,3)


def _fit(q,normal,base,selected,index,shape,data=None,half=None):
    from v41_quad import _tls
    h,w=shape[:2];keep=selected[:,2]>.5
    points=base+selected[:,0,None]*normal
    keep&=(points[:,0]>=1)&(points[:,0]<w-1)&(points[:,1]>=1)&(points[:,1]<h-1)
    n=len(selected);needed=int(np.ceil(.60*n))
    report=dict(edge=index,profiles=n,supported=int(keep.sum()),retained=0,coverage=0.,
        accepted=False,tls_rms=1e30,polarity=0,Y_polarity=0,
        contrast_backend='unclipped_YUV_vector_gradient')
    if data is not None and half is not None:
        col=int(np.clip(round(32.+96./half),0,64));near=data[:,col,0]
        report.update(highlight_fraction=float(np.mean(near>=250.)),dark_clip_fraction=float(np.mean(near<=4.)),
            clip_probe_scope='current candidate inward3px; possible clipping, not a glare diagnosis')
    if keep.sum()<needed:return None,report
    line,rms,retained=_tls(points[keep])
    if line is None:return None,report
    tangent=q[(index+1)%4]-q[index]
    along=(retained-q[index])@tangent/max(1e-9,float(tangent@tangent))
    span=float(np.ptp(along));count=len(retained)
    okay=count>=needed and span>=.60 and rms<=1.5
    report.update(retained=count,coverage=span,tls_rms=float(rms),accepted=bool(okay))
    if okay:report['fitted_line_source']=line.tolist()
    return line if okay else None,report


def candidate_color_refine(image,quad,half_window,check,deadline=None):
    """One four-side fit, then at most one fresh weak-side sample.

    Three accepted CURRENT line coefficients are retained exactly. The extra
    band widens only the fourth side around the immutable original proposal.
    No source pointer, old frame or historical edge is cached.
    """
    from v49_boundary import array_key
    from v45_color import vector_profiles
    if image.ndim!=3 or image.shape[2] not in (2,3):raise ValueError('Color band source required')
    q=np.asarray(quad,np.float64);begin=time.perf_counter();cpu=time.thread_time()
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('Current color candidate must be cyclic convex')
    edge=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edge,axis=1)
    if min(length)<4:raise ValueError('Degenerate current candidate')
    normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
    normal*=np.where(np.sum((q.mean(axis=0)-q-edge*.5)*normal,axis=1)<0,-1.,1.)[:,None]
    check('v85_current_color_bands')
    bases,bands=_sample(image,q,normal,np.arange(4),float(half_window))
    selection=_selection(bands,float(half_window));lines=[];reports=[]
    for i in range(4):
        check('v85_current_color_fit')
        line,report=_fit(q,normal[i],bases[i],selection[i],i,image.shape,bands[i],float(half_window))
        lines.append(line);reports.append(report)
    repair=dict(attempted=False,retained_current_lines=0)
    good=[i for i,r in enumerate(reports) if r['accepted'] and r['retained']>=52
        and r['coverage']>=.62 and r['tls_rms']<=1.]
    weak=[i for i,r in enumerate(reports) if not r['accepted'] or r['retained']<52]
    if len(good)==3 and len(weak)==1 and (deadline is None or deadline-time.perf_counter()>=.025):
        # Bounded failure-only work. This is a new current measurement, never
        # lowering the final source64 / independent24 admission thresholds.
        check('v85_single_weak_edge_repair');i=weak[0]
        repair_q=q.copy();repair_normal=normal.copy();peak_lock=None
        wider=min(12.,max(8.,1.6*float(half_window)))
        if lines[i] is not None:
            # A fitted but sparse edge is already a physical-line reference.
            # Recenter its band and keep a narrow peak corridor, instead of
            # widening into a neighboring page or printed rectangle.
            old_line=lines[i]
            for corner in (i,(i+1)%4):
                repair_q[corner]-=(old_line[:2]@repair_q[corner]+old_line[2])*old_line[:2]
            repair_normal[i]=old_line[:2]*(1. if old_line[:2]@normal[i]>=0 else -1.)
            wider=min(6.,max(3.,.75*float(half_window)));peak_lock=min(1.5,.70*wider)
        started=time.perf_counter();used=time.thread_time()
        base,band=_sample(image,repair_q,repair_normal,np.array([i]),wider)
        chosen=_selection(band,wider,8.,peak_lock)[0]
        line,report=_fit(q,repair_normal[i],base[0],chosen,i,image.shape,band[0],wider)
        if line is not None and report['tls_rms']>1.:
            line=None;report['accepted']=False
        old=reports[i]
        improved=bool(line is not None and (not old['accepted'] or
            (report['retained']>old['retained'] and report['coverage']>=old['coverage']-.05)))
        repair=dict(attempted=True,edge=i,half_source_pixels=wider,retained_current_lines=3,
            successful=improved,wall_s=time.perf_counter()-started,
            thread_cpu_s=time.thread_time()-used,minimum_contrast=8.,
            physical_peak_lock_source=peak_lock,seed='current_weak_line' if peak_lock is not None else 'original_candidate',
            other_current_line_coefficients_unchanged=True)
        if improved:lines[i]=line;reports[i]=report
    result=q.copy();valid=all(line is not None for line in lines)
    if valid:
        for i in range(4):
            cross=np.cross(lines[i-1],lines[i])
            if abs(cross[2])<.08:valid=False;break
            result[i]=cross[:2]/cross[2]
        h,w=image.shape[:2]
        ratio=abs(cv2.contourArea(result.astype(np.float32)))/max(1.,abs(cv2.contourArea(q.astype(np.float32))))
        valid=bool(valid and np.isfinite(result).all() and cv2.isContourConvex(result.astype(np.float32))
            and .85<=ratio<=1.15 and np.max(np.linalg.norm(result-q,axis=1))<=3*float(half_window)
            and np.all(result>=1) and np.all(result[:,0]<w-1) and np.all(result[:,1]<h-1))
    expired=deadline is not None and time.perf_counter()>=deadline
    valid=bool(valid and not expired);colors=[]
    if valid:
        # Match native YUYV pair centers and fitted-line +/-3px signatures.
        # The independent24 caller receives these actual same-layer sides.
        t=_workspace()['t'];centers=result[:,None,:]+t[None,:,None]*(np.roll(result,-1,axis=0)-result)[:,None,:]
        direction=np.stack((np.roll(result,-1,axis=0)[:,1]-result[:,1],
            result[:,0]-np.roll(result,-1,axis=0)[:,0]),axis=1)
        direction/=np.linalg.norm(direction,axis=1)[:,None]
        direction*=np.where(np.sum((result.mean(axis=0)-result)*direction,axis=1)<0,-1.,1.)[:,None]
        xy=centers[:,:,None,:]+np.array([-3.,3.])[None,None,:,None]*direction[:,None,None,:]
        side=vector_profiles(image,xy[...,0].reshape(256,2),xy[...,1].reshape(256,2)).reshape(4,64,2,3)
        colors=np.concatenate((np.median(side[:,:,0],axis=1),np.median(side[:,:,1],axis=1)),axis=1).tolist()
    expired=deadline is not None and time.perf_counter()>=deadline
    valid=bool(valid and not expired)
    if not valid:result=q.copy()
    evidence=dict(method='coherent_multicolor_gradient_TLS',state='refined' if valid else 'rejected',
        valid=valid,refined_corners=4 if valid else 0,supported_edges=sum(r['accepted'] for r in reports),
        edges=reports,edge_support=[r['retained']/64. if r['accepted'] else 0. for r in reports],
        edge_rms=[r['tls_rms'] for r in reports],edge_polarity=[0]*4,half_window_pixels=float(half_window),
        corner_displacements=np.linalg.norm(result-q,axis=1).tolist(),
        refinement_s=time.perf_counter()-begin,refinement_thread_cpu_s=time.thread_time()-cpu,
        backend='v85_packed_bands_native_consensus_retained_lines',profiles_per_edge=64,
        fraction_limits=[.10,.90],same_frame_source=True,current_source_key=array_key(image),
        source_proof_kind='raw_YUV_profiles' if image.shape[2]==2 else 'source_color_profiles',
        color_vector_proof=True,brightness_polarity_required=False,gradient_consensus_required=True,
        physical_source_corners=result.astype(np.float32).tolist(),border_colors=colors,
        corner_order_preserved=True,deadline_hit=expired,single_edge_repair=repair,
        vector_sample_backend='existing_packed_YUYV_or_color_sampler',full_plane_CSC_used=False)
    return result.astype(np.float32),evidence


def stable_weak_edge_grade(first,second,agreement,source_key):
    """One weak side in ONE independent layout, after complete same-target FB."""
    if (not agreement.get('source64_provenance_verified') or not agreement.get('independent_sampling_verified')
        or first.get('profiles_per_edge')!=24 or second.get('profiles_per_edge')!=64):return None
    groups=[]
    for e,n in ((first,24),(second,64)):
        if (not e.get('valid') or e.get('refined_corners')!=4 or e.get('supported_edges')!=4
            or e.get('deadline_hit') or not e.get('same_frame_source') or e.get('current_source_key')!=source_key):return None
        counts=e.get('edge_support',[])
        reports=e.get('edges') or e.get('source_proof',{}).get('edges',[])
        if len(counts)!=4 or not np.isfinite(counts).all():return None
        # The original native tracking-Y counter precedes TLS trimming and
        # does not export retained span. Do not invent that missing report;
        # the caller can obtain one fresh source24 layout against its Y64.
        if len(reports)!=4:return None
        if any(not r.get('accepted') or r.get('profiles')!=n or r.get('coverage',0)<.62
            or abs(float(r.get('retained',0))/n-float(v))>1e-5 for r,v in zip(reports,counts)):return None
        groups.append(np.asarray(counts,np.float64))
    a,b=groups;weak=np.flatnonzero(np.minimum(a,b)<.80)
    if len(weak)!=1:return None
    i=int(weak[0])
    if min(a[i],b[i])<.70 or max(a[i],b[i])<.80:return None
    if (agreement.get('max_rms',1e30)>.65
        or agreement.get('line_normal_difference',1e30)>min(.75,agreement.get('normal_limit',0.))
        or agreement.get('corner_difference',1e30)>1.):return None
    return dict(verified=True,admission_grade='stable_FB_single_weak_edge_070',
        admission_policy='same_target_current_four_edges_complete_FB',weak_edge=i,
        weak_support_floor=.70,other_three_support_floor=.80,independent_weak_side_support=max(a[i],b[i]),
        stable_FB_support_tolerance=True,complete_current_FB_required=True,
        strict_new_candidate_threshold_unchanged=True,all_four_current_fitted_lines_required=True,
        zero_support_edge_allowed=False,original_support_values_preserved=True)


def line_quantization_grade(first,second,agreement,scale,source_key):
    """At most two 1/32-source-pixel interpolation steps, with strong evidence.

    This never reduces support or accepts a missing line. Absolute .75tracking
    line lock and tighter corner/RMS checks still bound the physical layer.
    """
    if (not agreement.get('source64_provenance_verified') or not agreement.get('independent_sampling_verified')
        or agreement.get('min_support',0)<.80 or agreement.get('max_rms',1e30)>.35
        or agreement.get('corner_difference',1e30)>1.
        or first.get('profiles_per_edge')!=24 or second.get('profiles_per_edge')!=64):return None
    for e,n in ((first,24),(second,64)):
        if (not e.get('valid') or e.get('refined_corners')!=4 or e.get('supported_edges')!=4
            or not e.get('same_frame_source') or e.get('current_source_key')!=source_key
            or e.get('deadline_hit')):return None
        reports=e.get('edges') or e.get('source_proof',{}).get('edges',[])
        if not reports and n==24 and e.get('edge_backend') in (
            'cpp_analytic_tls','cpp_edges_gate_motion_context','numpy_analytic_tls'):
            if min(e.get('edge_support',[0]*4))<.80:return None
        elif len(reports)!=4 or any(not r.get('accepted') or r.get('profiles')!=n
            or r.get('coverage',0)<.62 for r in reports):return None
    step=.0625/float(np.min(scale));old=agreement.get('normal_limit',0.)
    limit=min(.75,old+step);error=agreement.get('line_normal_difference',1e30)
    if not old<error<=limit:return None
    return dict(verified=True,admission_grade='current_line_interpolation_quantization',
        admission_policy='strong_current_independent_edges_quantized_line',
        original_normal_limit=old,normal_limit=limit,quantization_allowance_source_pixels=.0625,
        strict_new_candidate_support=.80,all_four_current_fitted_lines_required=True,
        zero_support_edge_allowed=False,old_H_not_used=True)


def repair_independent24(image,scale,primary,source,observed,current,half,deadline,offset=(0,0)):
    """Fresh single-side CURRENT sample for a marginal strict admission.

    The other three lines come from the actual current24 fit. No cached old
    frame or primary64 point is counted in this shifted independent24 grid.
    """
    from v49_boundary import array_key,actual_source64
    from v62_boundary import peak_radius
    from v41_quad import _coherent_offsets
    from v45_color import vector_profiles
    key=array_key(image);scale=np.asarray(scale,np.float64)
    if (not actual_source64(source,key) or not source.get('valid')
        or min(source.get('edge_support',[0.]*4))<.80
        or not current.get('valid') or current.get('profiles_per_edge')!=24
        or current.get('current_source_key')!=key or current.get('deadline_hit')
        or current.get('weak24_repair_attempted')):return None
    support=np.asarray(current.get('edge_support',[]),np.float64)
    if support.shape!=(4,) or not np.isfinite(support).all():return None
    weak=np.flatnonzero(support<.80)
    if len(weak)!=1 or min(support)<.70:return None
    if len(current.get('edges',[]))!=4 or max(current.get('edge_rms',[1e30]*4))>.65:return None
    if deadline is not None and deadline-time.perf_counter()<.030:return None
    begin=time.perf_counter();cpu=time.thread_time();i=int(weak[0])
    origin=np.asarray(offset,np.float64)
    q=(np.asarray(primary,np.float64)+.5)*scale-.5-origin
    old=np.asarray(current.get('physical_source_corners'),np.float64)
    if q.shape!=(4,2) or old.shape!=(4,2) or not np.isfinite(old).all():return None
    edge=q[(i+1)%4]-q[i];normal=np.array([-edge[1],edge[0]])/max(1e-9,np.linalg.norm(edge))
    if normal@(q.mean(axis=0)-(q[i]+q[(i+1)%4])*.5)<0:normal=-normal
    t=np.linspace(.135,.865,24);offset=np.linspace(-half,half,65)
    base=q[i]+t[:,None]*edge;xy=base[:,None,:]+offset[None,:,None]*normal
    data=vector_profiles(image,xy[...,0],xy[...,1])
    sides=base[:,None,:]+np.array([-3.,3.])[None,:,None]*normal
    side=vector_profiles(image,sides[...,0],sides[...,1]);prior=side[:,1]-side[:,0]
    selected=_coherent_offsets(data,offset,t,8.,prior,peak_radius(scale,source,half))
    if selected is None:return None
    fit=np.stack((selected[0],selected[1],selected[2]),axis=1)
    line,report=_fit(q,normal,base,fit,i,image.shape,data,half)
    if line is None or report['retained']<20 or report['coverage']<.62:return None
    lines=[]
    for k in range(4):
        v=np.cross(np.r_[old[k],1.],np.r_[old[(k+1)%4],1.]);v/=max(1e-9,np.linalg.norm(v[:2]));lines.append(v)
    lines[i]=line;result=old.copy()
    for k in range(4):
        cross=np.cross(lines[k-1],lines[k])
        if abs(cross[2])<.08:return None
        result[k]=cross[:2]/cross[2]
    h,w=image.shape[:2]
    if (not np.isfinite(result).all() or not cv2.isContourConvex(result.astype(np.float32))
        or np.any(result<1) or np.any(result[:,0]>=w-1) or np.any(result[:,1]>=h-1)
        or np.max(np.linalg.norm(result-old,axis=1))>2.
        or time.thread_time()-cpu>.040 or (deadline is not None and time.perf_counter()>=deadline)):return None
    evidence=dict(current);reports=[dict(r) for r in current['edges']];reports[i]=report
    supports=list(current['edge_support']);supports[i]=report['retained']/24.
    rms=list(current['edge_rms']);rms[i]=report['tls_rms']/float(np.min(scale))
    layout=[list(current.get('fraction_limits',[.12,.88])) for _ in range(4)];layout[i]=[.135,.865]
    evidence.update(edges=reports,edge_support=supports,edge_rms=rms,
        physical_source_corners=result.astype(np.float32).tolist(),fraction_limits_per_edge=layout,
        weak24_repair_attempted=True,weak24_repair=dict(edge=i,wall_s=time.perf_counter()-begin,
            thread_cpu_s=time.thread_time()-cpu,grid=[24,.135,.865],
            retained_other_current_lines=3,old_frame_used=False,primary_points_relabelled=False))
    return ((result+origin+.5)/scale-.5).astype(np.float32),evidence


def compact_evidence(evidence):
    """Own only scalar/list proof fields used by same-frame consumers."""
    import copy
    fields=('method','valid','state','refined_corners','supported_edges','edges','edge_support','edge_rms',
        'edge_polarity','edge_backend','profiles_per_edge','fraction_limits','same_frame_source',
        'current_source_key','source_proof_kind','physical_source_corners','color_vector_proof',
        'deadline_hit','border_colors','corner_order_preserved','half_window_pixels',
        'gradient_consensus_required','brightness_polarity_required','boundary_prior_used',
        'physical_peak_lock','peak_lock_radius_source','signed_peak_lock','signed_reference',
        'fraction_limits_per_edge','weak24_repair_attempted','weak24_repair','sampling_metadata')
    result={k:copy.deepcopy(evidence[k]) for k in fields if k in evidence}
    if 'source_proof' in evidence:
        source=evidence['source_proof'];result['source_proof']={k:copy.deepcopy(source[k])
            for k in ('method','edges','refined_corners','backend') if k in source}
    return result
