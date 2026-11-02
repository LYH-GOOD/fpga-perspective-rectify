"""Bounded multicolor rectangle proposals and coherent exterior profiles.

No target hue, brightness polarity, grid, focal length or fixed aspect ratio.
Proposals are never trusted without four same-frame measured exterior lines.
YUYV color fallback converts sampled normal bands, not a full RGB frame.
"""
from pathlib import Path
import hashlib,time
import cv2
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def sample_profiles(image,x,y):
    """Sample BGR/gray or paired YUYV with explicit CSC/color-range contract."""
    mx=np.ascontiguousarray(x,np.float32);my=np.ascontiguousarray(y,np.float32)
    if image.ndim==2:
        return cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)[...,None].astype(np.float32)
    if image.shape[2]==3:
        return cv2.remap(image,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    from v31_pixels import require_yuyv,color_mode
    require_yuyv(image);h,w=image.shape[:2];pairs=image.reshape(h,w//2,4)
    # Chroma belongs to a Y0/Y1 pair centered at x=.5,2.5,... . Do not resize
    # the interleaved U/V byte plane as though each byte were the same channel.
    uvx=np.ascontiguousarray((mx-.5)*.5,np.float32)
    Y=cv2.remap(image[:,:,0],mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    U=cv2.remap(pairs[:,:,1],uvx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
    V=cv2.remap(pairs[:,:,3],uvx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE).astype(np.float32)-128.
    mode=color_mode();cy,rv,gu,gv,bu=((298,409,100,208,516),(256,359,88,183,454),
                                  (298,459,55,136,541),(256,403,48,120,475))[mode]
    C=Y if mode&1 else np.maximum(Y-16.,0.)
    return np.clip(np.stack((cy*C+bu*U,cy*C-gu*U-gv*V,cy*C+rv*V),axis=-1)/256.,0,255)


def _tls(points):
    """Analytic 2D TLS; residual trim cannot accept an unsupported second edge."""
    selected=np.asarray(points,np.float64)
    for _ in range(3):
        center=selected.mean(axis=0);d=selected-center
        xx=float(np.sum(d[:,0]**2));yy=float(np.sum(d[:,1]**2));xy=float(np.sum(d[:,0]*d[:,1]))
        if np.hypot(xx-yy,2*xy)<=1e-10*(xx+yy+1):return None,None,None
        angle=.5*np.arctan2(2*xy,xx-yy);normal=np.array([-np.sin(angle),np.cos(angle)])
        residual=np.abs(d@normal);threshold=min(1.25,max(.55,2.5*float(np.median(residual))))
        keep=residual<=threshold
        if keep.all() or int(keep.sum())<12:break
        selected=selected[keep]
    center=selected.mean(axis=0);d=selected-center
    angle=.5*np.arctan2(2*float(np.sum(d[:,0]*d[:,1])),float(np.sum(d[:,0]**2)-np.sum(d[:,1]**2)))
    normal=np.array([-np.sin(angle),np.cos(angle)])
    return np.r_[normal,-normal@center],float(np.sqrt(np.mean((d@normal)**2))),selected


def _coherent_offsets(samples,offsets,t,minimum_contrast,boundary_prior=None,line_lock_radius=None):
    """Three peak hypotheses/profile; bounded joint line consensus, not nearest crossing."""
    sm=samples.copy();sm[:,1:-1]=(samples[:,:-2]+2*samples[:,1:-1]+samples[:,2:])*.25
    gradient=np.zeros(samples.shape[:2],np.float32)
    # A wider difference measures a real contrast across blur, not one noisy sample.
    gradient[:,4:-4]=np.max(np.abs(sm[:,8:]-sm[:,:-8]),axis=2)
    noise=np.median(np.max(np.abs(samples[:,1:]-samples[:,:-1]),axis=2),axis=1)
    threshold=np.maximum(float(minimum_contrast),4*noise)
    positions=np.zeros((len(t),3),np.float32);strengths=np.zeros_like(positions)
    work=gradient/(1+.35*np.abs(offsets)[None,:]/max(1.,float(abs(offsets[-1]))))
    if line_lock_radius is not None:work[:,np.abs(offsets)>line_lock_radius]=0.
    affinity=np.zeros_like(positions);signed=boundary_prior is not None and samples.shape[2]==3 and np.linalg.norm(boundary_prior)>=16.
    row=np.arange(len(t))
    for k in range(3):
        col=np.argmax(work,axis=1)
        left=gradient[row,np.maximum(col-1,0)];mid=gradient[row,col];right=gradient[row,np.minimum(col+1,len(offsets)-1)]
        den=left-2*mid+right
        alpha=np.where(np.abs(den)>1e-5,np.clip(.5*(left-right)/np.where(np.abs(den)>1e-5,den,1.),-.5,.5),0.)
        positions[:,k]=offsets[col]+alpha*(offsets[1]-offsets[0])
        strengths[:,k]=mid
        if signed:
            vector=sm[row,np.minimum(col+4,len(offsets)-1)]-sm[row,np.maximum(col-4,0)]
            affinity[:,k]=(vector@boundary_prior)/np.maximum(np.linalg.norm(vector,axis=1)*np.linalg.norm(boundary_prior),1e-9)
        for shift in range(-4,5):work[row,np.clip(col+shift,0,len(offsets)-1)]=0
    eligible=(strengths>=threshold[:,None])&(np.abs(positions)<abs(offsets[-1])*.9)
    if line_lock_radius is not None:
        eligible&=np.abs(positions)<=line_lock_radius
        if signed:eligible&=affinity>=.25
    # P1 batches normal-profile geometry; batch the bounded hypothesis grid too.
    # Same ordered anchor pairs/three peaks, eligibility and endpoint constraints.
    anchors=np.linspace(0,len(t)-1,8).astype(int)
    ai,bi,ki,kj=np.indices((8,8,3,3))
    ia,ib=anchors[ai.ravel()],anchors[bi.ravel()]
    ka,kb=ki.ravel(),kj.ravel();dt=t[ib]-t[ia]
    good=(dt>=.4)&eligible[ia,ka]&eligible[ib,kb]
    if not good.any():return None
    ia,ib,ka,kb=ia[good],ib[good],ka[good],kb[good]
    slope=(positions[ib,kb]-positions[ia,ka])/(t[ib]-t[ia])
    intercept=positions[ia,ka]-slope*t[ia]
    endpoint_limit=abs(offsets[-1]) if line_lock_radius is None else line_lock_radius
    good=np.maximum(np.abs(intercept+slope*t[0]),np.abs(intercept+slope*t[-1]))<=endpoint_limit
    if not good.any():return None
    models=np.stack((intercept[good],slope[good]),axis=1).astype(np.float32)
    predicted=models[:,0,None,None]+models[:,1,None,None]*t[None,:,None]
    distance=np.where(eligible[None,:,:],np.abs(positions[None,:,:]-predicted),np.inf)
    peak=np.argmin(distance,axis=2);res=np.take_along_axis(distance,peak[:,:,None],axis=2)[:,:,0]
    inlier=res<=.85
    g=np.take_along_axis(np.broadcast_to(strengths,(len(models),)+strengths.shape),peak[:,:,None],axis=2)[:,:,0]
    score=inlier.sum(axis=1)+.08*np.sum(np.minimum(g,64)*inlier,axis=1)/64.-.08*np.abs(models[:,0]+models[:,1]*.5)
    best=int(np.argmax(score));chosen=peak[best];keep=inlier[best]
    return positions[row,chosen],strengths[row,chosen],keep


def refine_boundary(image,quad,half_window=6.,profiles=64,min_support=.60,max_rms=1.5,
                    minimum_contrast=12.,fraction_limits=(.10,.90),deadline=None,boundary_prior=None,line_lock_radius=None):
    """Independent 4xN exterior gradient bands; all four lines must be accepted."""
    from v8_geometry import order_corners
    begin=time.perf_counter();cpu=time.thread_time();h,w=image.shape[:2]
    if profiles not in (24,64) or not 2.5<=half_window<=24:raise ValueError('Invalid bounded exterior profile layout')
    if line_lock_radius is not None and (not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window):raise ValueError('Physical peak corridor invalid')
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Physical boundary side prior invalid')
    q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('Exterior profiles require cyclic convex current corners')
    from v87_v74_native import fused_yuyv_exterior
    native=fused_yuyv_exterior(image,q,half_window,profiles,min_support,max_rms,minimum_contrast,fraction_limits,deadline,boundary_prior,line_lock_radius)
    if native is not None:return native
    center=q.mean(axis=0)
    t=np.linspace(*fraction_limits,profiles);offsets=np.linspace(-half_window,half_window,65)
    bases=[];normals=[];coords=[]
    for i in range(4):
        a,b=q[i],q[(i+1)%4];edge=b-a;normal=np.array([-edge[1],edge[0]])/max(1e-9,np.linalg.norm(edge))
        if np.dot(center-(a+b)*.5,normal)<0:normal=-normal
        base=a+t[:,None]*edge;bases.append(base);normals.append(normal)
        coords.append(base[:,None,:]+offsets[None,:,None]*normal)
    from v45_color import vector_profiles
    xy=np.asarray(coords);bands=vector_profiles(image,xy[...,0].reshape(4*profiles,65),xy[...,1].reshape(4*profiles,65))
    bands=bands.reshape(4,profiles,65,-1);lines=[];reports=[];polarities=[];supports=[];rms_values=[]
    from v87_v74_native import coherent_profiles,native_status
    consensus=coherent_profiles(bands,half_window,fraction_limits,minimum_contrast,boundary_prior,line_lock_radius)
    consensus_detail={} if consensus is None else consensus[1]
    for i in range(4):
        data=bands[i]
        if consensus is None:selection=_coherent_offsets(data,offsets,t,minimum_contrast,None if prior is None else prior[i],line_lock_radius)
        else:
            selected=consensus[0][i]
            selection=(selected[:,0],selected[:,1],selected[:,2]>.5)
        luminance=data[:,:,0]
        contrast=float(np.median(np.median(luminance[:,-8:],axis=1)-np.median(luminance[:,:8],axis=1)))
        raw_polarity=int(np.sign(contrast)) if abs(contrast)>=8 else 0
        # Mixed-color exterior may reverse Y polarity along one real line.
        # A vector proof has four spatial lines, not a common brightness sign.
        polarities.append(raw_polarity if data.shape[2]==1 else 0)
        report=dict(edge=i,profiles=profiles,supported=0,retained=0,coverage=0.,accepted=False,
                    polarity=polarities[-1],Y_polarity=raw_polarity,contrast_backend='Y_gradient' if data.shape[2]==1 else 'unclipped_YUV_vector_gradient')
        line=None;rms=1e30;retained=0
        if selection is not None:
            shifts,strength,keep=selection
            points=bases[i]+shifts[:,None]*normals[i]
            keep&=(points[:,0]>=1)&(points[:,0]<w-1)&(points[:,1]>=1)&(points[:,1]<h-1)
            report['supported']=int(keep.sum())
            if int(keep.sum())>=int(np.ceil(profiles*min_support)):
                line,rms,selected=_tls(points[keep])
                if line is not None:
                    retained=len(selected)
                    tangent=(q[(i+1)%4]-q[i]);length=float(np.linalg.norm(tangent))
                    along=(selected-q[i])@tangent/max(1e-9,length*length)
                    coverage=float(np.ptp(along));report.update(retained=retained,coverage=coverage,tls_rms=rms)
                    report['accepted']=bool(retained>=int(np.ceil(profiles*min_support)) and coverage>=.60 and rms<=max_rms)
                    if not report['accepted']:line=None
        lines.append(line);reports.append(report);supports.append(retained/float(profiles) if line is not None else 0.)
        rms_values.append(float(rms))
    result=q.copy();refined=0
    for i in range(4):
        if lines[i-1] is None or lines[i] is None:continue
        cross=np.cross(lines[i-1],lines[i])
        if abs(cross[2])<.08:continue
        p=cross[:2]/cross[2]
        if np.isfinite(p).all() and np.linalg.norm(p-q[i])<=3*half_window and np.all(p>=1) and p[0]<w-1 and p[1]<h-1:
            result[i]=p;refined+=1
    valid=refined==4 and all(r['accepted'] for r in reports)
    if valid:
        try:
            ordered=result.astype(np.float32);ratio=abs(cv2.contourArea(ordered))/max(1.,abs(cv2.contourArea(q.astype(np.float32))))
            valid=cv2.isContourConvex(ordered) and .85<=ratio<=1.15 and np.max(np.linalg.norm(ordered-q,axis=1))<=3*half_window
            if valid:result=ordered
        except (ValueError,cv2.error):valid=False
    deadline_hit=deadline is not None and time.perf_counter()>=deadline
    if deadline_hit:valid=False
    if not valid:result=q;refined=0
    evidence=dict(method='coherent_multicolor_gradient_TLS',state='refined' if valid else 'rejected',
        valid=bool(valid),supported_edges=sum(s>=min_support for s in supports),refined_corners=refined,
        edges=reports,edge_support=supports,edge_rms=rms_values,edge_polarity=polarities,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(result-q,axis=1).tolist(),
        refinement_s=time.perf_counter()-begin,refinement_thread_cpu_s=time.thread_time()-cpu,
        backend='bounded_coherent_gradient_profiles',profiles_per_edge=profiles,fraction_limits=list(fraction_limits),
        vector_sample_backend=(native_status().get('packed_exterior_backend','opencv_remap_scalar_planes')
            if image.ndim==3 and image.shape[2]==2 and max(image.shape[:2])<=1280 else 'opencv_remap_scalar_planes'),
        consensus_backend=consensus_detail.get('backend','numpy_three_peak_consensus'),
        consensus_native_wall_s=consensus_detail.get('native_wall_s',0.),
        consensus_native_thread_cpu_s=consensus_detail.get('native_thread_cpu_s',0.),
        same_frame_color_bands_only=bool(image.ndim==3 and image.shape[2]==2),gradient_consensus_required=True,
        color_vector_proof=bool(image.ndim==3),brightness_polarity_required=image.ndim==2,
        same_frame_source=True,current_source_key=__import__('v49_boundary').array_key(image),
        source_proof_kind='raw_YUV_profiles' if image.ndim==3 and image.shape[2]==2 else 'source_color_profiles' if image.ndim==3 else 'source_Y_profiles',
        deadline_hit=deadline_hit,corner_order_preserved=True,boundary_prior_used=prior is not None and line_lock_radius is not None,
        physical_peak_lock=line_lock_radius is not None,peak_lock_radius_source=line_lock_radius,
        signed_peak_lock=bool(line_lock_radius is not None and prior is not None))
    return np.asarray(result,np.float32),evidence


def original_y_boundary(image,scale,quad,offset=(0,0),radius=3.,source_gray=None):
    """P1 native original-Y64 proof of a CURRENT tracking-space proposal.

    Independent source-resolution profiles; never relabel previous-frame points.
    RMS is conservatively rescaled; supports use retained, not pre-trim points.
    This supplies evidence only. The caller still applies its polarity/motion gate.
    """
    from v87_v74_native import refine_original_y64
    from v31_pixels import luminance
    from v8_geometry import order_corners
    begin=time.perf_counter();cpu=time.thread_time()
    scale=np.asarray(scale,np.float64);origin=np.asarray(offset,np.float64)
    q=np.asarray(quad,np.float32).reshape(4,2)
    if scale.shape!=(2,) or np.any(scale<=0) or not np.isfinite(scale).all():raise ValueError('Source proof scale invalid')
    local=(q+.5)*scale-.5-origin
    h,w=image.shape[:2]
    if (not np.isfinite(local).all() or np.any(local<2) or np.any(local[:,0]>w-3)
            or np.any(local[:,1]>h-3) or not cv2.isContourConvex(local.astype(np.float32))):return None
    half=min(24.,max(3.,float(radius)*float(scale.max())))
    raw=image.ndim==3 and image.shape[2]==2
    y=source_gray;proof=None
    if raw and y is None:
        from v87_v74_native import refine_original_yuyv64
        proof=refine_original_yuyv64(image,local,half)
    if proof is None:
        if y is None:y=luminance(image) if raw else image if image.ndim==2 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        if y.shape!=(h,w) or y.dtype!=np.uint8:raise ValueError('Source proof gray layout mismatch')
        proof=refine_original_y64(y,local,half)
    if proof is None:return None
    result,detail=proof;edges=detail.get('edges',[])
    accepted=len(edges)==4 and detail.get('refined_corners')==4 and all(e.get('accepted',False) for e in edges)
    support=[e.get('retained',0)/64. if e.get('accepted',False) else 0. for e in edges]
    rms=[float(e.get('tls_rms',1e30))/float(scale.min()) for e in edges]
    observed=((result+origin+.5)/scale-.5).astype(np.float32)
    # Preserve inward/outward contrast signs without assuming white foreground.
    # Sample source-Y endpoints at the fitted exterior, not an older frame.
    ordered=np.asarray(result,np.float64);D=np.roll(ordered,-1,axis=0)-ordered
    length=np.linalg.norm(D,axis=1);normal=np.stack((-D[:,1],D[:,0]),axis=1)/np.maximum(length[:,None],1e-9)
    normal*=np.where(np.sum((ordered.mean(axis=0)-ordered-D*.5)*normal,axis=1)<0,-1.,1.)[:,None]
    fractions=np.linspace(.06,.94,64);base=ordered[:,None,:]+fractions[None,:,None]*D[:,None,:]
    ends=base[:,:,None,:]+np.array([-half,half])[None,None,:,None]*normal[:,None,None,:]
    if y is None:
        # Packed native proof reports normalized source-profile polarity itself.
        contrast=np.array([e.get('profile_contrast',0.) for e in edges],np.float64)
    else:
        bands=sample_profiles(y,ends[...,0].reshape(256,2),ends[...,1].reshape(256,2)).reshape(4,64,2)
        contrast=np.median(bands[:,:,1]-bands[:,:,0],axis=1)
    polarity=np.where(np.abs(contrast)>=8,np.sign(contrast),0).astype(int).tolist()
    valid=bool(accepted and min(support)>=.60 and all(e.get('coverage',0.)>=.60 for e in edges))
    evidence=dict(valid=valid,refined_corners=4 if valid else 0,supported_edges=sum(s>=.60 for s in support),
        edge_support=support,edge_rms=rms,edge_polarity=polarity,edge_backend='cpp_current_source_Y64',
        method='p1_original_resolution_normal_profiles_TLS',source_proof=detail,
        tracking_roi_offset=origin.tolist(),same_frame_source=True,profiles_per_edge=64,
        current_source_key=__import__('v49_boundary').array_key(image),source_proof_kind='source_Y_profiles',fraction_limits=[.06,.94],
        boundary_fallback_s=time.perf_counter()-begin,boundary_fallback_thread_cpu_s=time.thread_time()-cpu)
    return observed,evidence


def rectangle_proposals(color,source_shape,checkpoint=lambda stage:None,max_candidates=12,include_lines=True):
    from v45_color import rectangle_proposals as proposals
    return proposals(color,source_shape,checkpoint,max_candidates,include_lines)
