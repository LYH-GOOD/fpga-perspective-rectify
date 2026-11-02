"""Regularized local surface from long dark-line centres, no grid-spacing prior."""
from pathlib import Path
import hashlib,time
from functools import lru_cache
import cv2
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
NX,NY=7,5


@lru_cache(maxsize=4)
def _knots(n):
    knots=np.r_[np.zeros(4),np.linspace(0,1,n-2)[1:-1],np.ones(4)]
    knots.setflags(write=False)
    return knots


def basis(z,n):
    """Open uniform cubic B-spline basis with polynomial end continuation.

    Continuation matters: hardware nodes can lie past the last active pixel.
    Clamping the function there creates derivative discontinuities.
    """
    z=np.asarray(z,float)
    knots=_knots(n)
    b=((z[...,None]>=knots[:-1])&(z[...,None]<knots[1:])).astype(float)
    b[...,3]=np.where(z<0,1.,b[...,3])
    b[...,n-1]=np.where(z>=1,1.,b[...,n-1])
    for degree in (1,2,3):
        size=len(knots)-degree-1
        out=np.zeros(z.shape+(size,))
        for i in range(size):
            left=knots[i+degree]-knots[i]
            right=knots[i+degree+1]-knots[i+1]
            if left:out[...,i]+=(z-knots[i])/left*b[...,i]
            if right:out[...,i]+=(knots[i+degree+1]-z)/right*b[...,i+1]
        b=out
    return b


def design(x,y):
    x,y=np.broadcast_arrays(np.asarray(x,float),np.asarray(y,float))
    bx=basis(x,NX)*((x*(1-x))[...,None]);by=basis(y,NY)
    return (by[..., :,None]*bx[...,None,:]).reshape(x.shape+(NX*NY,))


@lru_cache(maxsize=24)
def _grid_basis(x_axis,y_axis):
    x=np.asarray(x_axis,float);y=np.asarray(y_axis,float)
    bx=basis(x,NX)*(x*(1-x))[:,None];by=basis(y,NY)
    bx.setflags(write=False);by.setflags(write=False)
    return bx,by


_PENALTY=np.vstack([.20*np.kron(np.eye(NY),np.diff(np.eye(NX),n=2,axis=0)),
                    .20*np.kron(np.diff(np.eye(NY),n=2,axis=0),np.eye(NX)),
                    .01*np.eye(NX*NY)])
_PENALTY.setflags(write=False)


def evaluate_grid(coeff,x_axis,y_axis):
    """Return (len(y_axis), len(x_axis)) samples of the SAME cubic surface."""
    x_axis=np.asarray(x_axis,float);y_axis=np.asarray(y_axis,float)
    if not np.any(coeff):return np.zeros((y_axis.size,x_axis.size),float)
    if max(x_axis.size,y_axis.size)<=128:
        bx,by=_grid_basis(tuple(x_axis),tuple(y_axis))
    else:
        bx=basis(x_axis,NX)*(x_axis*(1-x_axis))[:,None]
        by=basis(y_axis,NY)
    return cv2.gemm(cv2.gemm(np.ascontiguousarray(by),np.ascontiguousarray(coeff,dtype=np.float64),1.,None,0.),
                    np.ascontiguousarray(bx.T),1.,None,0.)


def evaluate(coeff,x,y):
    x,y=np.broadcast_arrays(np.asarray(x,float),np.asarray(y,float))
    if not np.any(coeff):return np.zeros(x.shape,float)
    if x.ndim==2:
        if np.array_equal(x,np.broadcast_to(x[:1,:],x.shape)) and np.array_equal(y,np.broadcast_to(y[:,:1],y.shape)):
            return evaluate_grid(coeff,x[0,:],y[:,0])
        if np.array_equal(x,np.broadcast_to(x[:,:1],x.shape)) and np.array_equal(y,np.broadcast_to(y[:1,:],y.shape)):
            return evaluate_grid(coeff,x[:,0],y[0,:]).T
    bx=basis(x,NX);by=basis(y,NY)
    # Avoid a dense (...,35) tensor for preview/full-map points.
    result=np.zeros(x.shape,float)
    for j in range(NY):
        row=np.zeros(x.shape,float)
        for i in range(NX):row+=coeff[j,i]*bx[...,i]
        result+=row*by[...,j]
    return result*x*(1-x)


def _peaks(values,gap):
    values=np.asarray(values,float)
    candidates=np.flatnonzero((values>=np.roll(values,1))&(values>=np.roll(values,-1))&
                             (values>max(4,.25*values.max())))
    chosen=[]
    for i in sorted(candidates,key=lambda i:values[i],reverse=True):
        if all(abs(int(i)-j)>=gap for j in chosen):chosen.append(int(i))
    return sorted(chosen)


def line_surface(gray,ink=None,solver='qr',tracking_backend='batch'):
    """Track subpixel line centres; fit a shared smooth local displacement.

    A whole family of genuinely curved artwork is ambiguous: caller must use
    document/lines mode only where straight-line evidence is appropriate.
    """
    started=time.perf_counter()
    h,w=gray.shape
    if solver not in ('qr','svd'):raise ValueError('surface_solver须为qr/svd')
    if tracking_backend not in ('batch','legacy'):raise ValueError('surface_tracking须为batch/legacy')
    batch_count=0
    threshold_s=morphology_s=profile_prepare_s=profile_stats_s=crossing_s=track_filter_s=0.
    def inactive(reason,n=0,**evidence):
        defaults=dict(tracking_backend=tracking_backend,profile_batches=batch_count,tracking_s=time.perf_counter()-started,fit_s=0.,solves=0,
                      threshold_s=threshold_s,morphology_s=morphology_s,
                      profile_prepare_s=profile_prepare_s,profile_statistics_s=profile_stats_s,
                      crossing_s=crossing_s,track_filter_s=track_filter_s)
        defaults.update(evidence)
        return np.zeros((65,65),np.float32),dict(state='inactive',accepted=0,candidates=n,
                       reason=reason,**defaults),np.zeros((NY,NX))
    if min(h,w)<48:return inactive('preview_too_small')
    t=time.perf_counter()
    if ink is None:
        ink=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,9)
    elif ink.shape!=gray.shape or ink.dtype!=np.uint8:
        raise ValueError('shared threshold shape/dtype mismatch')
    threshold_s=time.perf_counter()-t;t=time.perf_counter()
    horizontal=cv2.morphologyEx(ink,cv2.MORPH_OPEN,np.ones((1,max(9,w//35)),np.uint8))
    seeds=_peaks((horizontal>0).sum(axis=1),max(6,h//70))
    morphology_s=time.perf_counter()-t
    if len(seeds)<5:
        return inactive('fewer_than_five_seed_candidates',len(seeds),tracking_s=time.perf_counter()-started,
                        fit_s=0.,solves=0,threshold_s=threshold_s,morphology_s=morphology_s)
    xs=np.linspace(.04*(w-1),.96*(w-1),41)
    tracks=[];half=max(2,w//90)
    bounds=[(max(0,int(x)-half),min(w,int(x)+half+1)) for x in xs]
    equal_width=len({b-a for a,b in bounds})==1
    windows=[]
    for seed in seeds:
        neighbours=[abs(seed-other) for other in seeds if other!=seed]
        radius=int(max(3,min(h*.03,(min(neighbours) if neighbours else h*.06)*.43)))
        windows.append((max(0,seed-radius),min(h,seed+radius+1),radius))
    # Median of the SAME source strip is independent of which line is tracked.
    # Compute each needed row once, even when neighbouring search windows overlap.
    t=time.perf_counter();needed=np.zeros(h,bool)
    for lo,hi,_ in windows:needed[lo:hi]=True
    needed_rows=np.flatnonzero(needed);source=gray[needed_rows]
    if equal_width and tracking_backend=='batch':
        strips=np.stack([source[:,a:b] for a,b in bounds])
        median_index=strips.shape[2]//2
        # Strip widths here are odd (2*half+1); uint8 selection is the exact median.
        strips.partition(median_index,axis=2)
        all_profiles=strips[:,:,median_index].astype(float)
    elif equal_width:
        all_profiles=np.median(np.stack([source[:,a:b] for a,b in bounds]),axis=2).astype(float)
    else:
        all_profiles=np.stack([np.median(source[:,a:b],axis=1) for a,b in bounds]).astype(float)
    profiles_by_row=np.zeros((len(xs),h),float)
    profiles_by_row[:,needed_rows]=all_profiles
    profile_prepare_s=time.perf_counter()-t
    if tracking_backend=='batch':
        batch_hits,batch_stats,batch_count=_batch_crossings(profiles_by_row,windows,xs)
        profile_stats_s+=batch_stats['statistics_s'];crossing_s+=batch_stats['crossing_s']
    for window_index,(lo,hi,radius) in enumerate(windows):
        if tracking_backend=='batch':
            hits=batch_hits[window_index]
        else:
            profiles=profiles_by_row[:,lo:hi];t=time.perf_counter()
            backgrounds=np.percentile(profiles,80,axis=1)
            minima=np.argmin(profiles,axis=1)
            profile_stats_s+=time.perf_counter()-t;t=time.perf_counter()
            # Exact contiguous half-depth component around each minimum. Batch all
            # profiles; no per-pixel/profile while loops, same strict '< level' rule.
            depth=backgrounds-profiles[np.arange(len(xs)),minima]
            levels=backgrounds-depth*.5
            axis=np.arange(profiles.shape[1])[None,:]
            below=profiles<levels[:,None]
            left=np.max(np.where((axis<minima[:,None])&~below,axis,-1),axis=1)+1
            right=np.min(np.where((axis>minima[:,None])&~below,axis,profiles.shape[1]),axis=1)-1
            good=(depth>=18)&(minima>0)&(minima<profiles.shape[1]-1)
            good&=(left>0)&(right<profiles.shape[1]-1)&(right-left+1<=max(7,radius))
            k=np.flatnonzero(good);l=left[k];r=right[k]
            edge_l=l-1+(profiles[k,l-1]-levels[k])/np.maximum(profiles[k,l-1]-profiles[k,l],1e-6)
            edge_r=r+(levels[k]-profiles[k,r])/np.maximum(profiles[k,r+1]-profiles[k,r],1e-6)
            hits=np.column_stack([xs[k],lo+(edge_l+edge_r)/2])
            crossing_s+=time.perf_counter()-t
        if len(hits)<30:continue
        t=time.perf_counter()
        xy=np.asarray(hits);z=xy[:,0]/(w-1)
        # Polynomial only rejects mis-tracked samples; actual samples feed the
        # spline, so the final local model is not limited to cubic tracks.
        c=np.polyfit(z,xy[:,1],3);errors=xy[:,1]-np.polyval(c,z)
        keep=abs(errors)<1.8
        if keep.sum()<30:
            track_filter_s+=time.perf_counter()-t
            continue
        xy=xy[keep];z=z[keep]
        c=np.polyfit(z,xy[:,1],3);ends=np.polyval(c,[0.,1.])
        chord=ends[0]+(ends[1]-ends[0])*z;delta=xy[:,1]-chord
        if np.max(abs(delta))>max(4,h*.04):
            track_filter_s+=time.perf_counter()-t
            continue
        level=float(np.median(chord))
        if 2<level<h-3:tracks.append((level,z,chord/(h-1),delta))
        track_filter_s+=time.perf_counter()-t
    tracks.sort(key=lambda p:p[0]);unique=[]
    for track in tracks:
        if not unique or track[0]-unique[-1][0]>2:unique.append(track)
    tracks=unique;n=len(tracks)
    if n<5:return inactive('fewer_than_five_supported_curves',n)
    coverage=(tracks[-1][0]-tracks[0][0])/(h-1)
    if coverage<.45:return inactive('insufficient_coverage',n,coverage=float(coverage))
    tracking_s=time.perf_counter()-started
    fit_started=time.perf_counter()
    target=np.concatenate([t[3] for t in tracks])
    baseline=float(np.sqrt(np.mean(target**2)))
    if baseline<.15:
        return inactive('curvature_below_preview_resolution',n,
            model='regularized_cubic_bspline_5x7',coverage=float(coverage),
            uncorrected_curve_rms=baseline,validation_folds=0,measured_points=len(target),
            tracking_s=tracking_s,fit_s=time.perf_counter()-fit_started,solves=0)
    A=design(np.concatenate([t[1] for t in tracks]),np.concatenate([t[2] for t in tracks]))
    ids=np.concatenate([np.full(len(t[1]),i) for i,t in enumerate(tracks)])
    # Second differences suppress spurious waves while allowing local curvature.
    penalty=_PENALTY
    solve_seconds=0.;qr_fallbacks=0;solve_count=0
    def product(a,b):
        return _native_matvec(a,b) if tracking_backend=='batch' else a@b
    def solve(a,b,weights=None):
        nonlocal solve_seconds,qr_fallbacks,solve_count
        solve_count+=1;t=time.perf_counter()
        weights=np.ones(len(b)) if weights is None else weights
        root=np.sqrt(weights)
        augmented=np.ascontiguousarray(np.vstack([a*root[:,None],penalty]),dtype=np.float64)
        rhs=np.ascontiguousarray(np.r_[b*root,np.zeros(len(penalty))],dtype=np.float64)
        coeff=None
        if solver=='qr':
            # Solve the augmented least-squares system directly: no normal
            # equations, no squared condition number, same regularized objective.
            try:
                ok,value=cv2.solve(augmented,rhs[:,None],flags=cv2.DECOMP_QR)
                if ok and value is not None:
                    trial=value.reshape(-1)
                    if trial.size==NX*NY and np.all(np.isfinite(trial)):
                        residual=product(augmented,trial)-rhs
                        gradient=product(augmented.T,residual)
                        # Backward stationarity guard; retain SVD as fallback.
                        scale=max(1.,np.linalg.norm(augmented,1)*np.linalg.norm(augmented,np.inf)*
                                  np.linalg.norm(trial,np.inf)+np.linalg.norm(product(augmented.T,rhs),np.inf))
                        if np.linalg.norm(gradient,np.inf)<=1e-9*scale:coeff=trial
            except cv2.error:
                pass
            if coeff is None:qr_fallbacks+=1
        if coeff is None:
            coeff=np.linalg.lstsq(augmented,rhs,rcond=None)[0]
        solve_seconds+=time.perf_counter()-t
        return coeff
    coefficients=solve(A,target)
    for _ in range(2):
        error=product(A,coefficients)-target
        coefficients=solve(A,target,np.minimum(1.,.6/np.maximum(abs(error),1e-6)))
    # Three interleaved folds hold out whole curves. A fixed number of solves
    # replaces one solve for every line, bounding work on densely ruled pages.
    held=np.zeros_like(target)
    for fold in range(3):
        train=ids%3!=fold;c=solve(A[train],target[train])
        held[~train]=product(A[~train],c)-target[~train]
    baseline=float(np.sqrt(np.mean(target**2)))
    rms=float(np.sqrt(np.mean((product(A,coefficients)-target)**2)))
    cv=float(np.sqrt(np.mean(held**2)))
    info=dict(model='regularized_cubic_bspline_5x7',coverage=float(coverage),fit_rms=rms,
              held_out_rms=cv,uncorrected_curve_rms=baseline,validation_folds=3,solves=solve_count,
              solver='opencv_qr_with_svd_fallback' if solver=='qr' else 'svd_lstsq',
              tracking_backend=tracking_backend,profile_batches=batch_count,
              matrix_backend='opencv_gemm' if tracking_backend=='batch' else 'numpy',
              qr_fallbacks=qr_fallbacks,solve_s=solve_seconds,
              threshold_s=threshold_s,morphology_s=morphology_s,
              profile_prepare_s=profile_prepare_s,profile_statistics_s=profile_stats_s,
              crossing_s=crossing_s,track_filter_s=track_filter_s,
              measured_points=int(len(target)),tracking_s=tracking_s,
              fit_s=time.perf_counter()-fit_started)
    if baseline<.15:return inactive('curvature_below_preview_resolution',n,**info)
    if cv>min(.85,.85*baseline) or rms>.75:
        return inactive('curves_do_not_support_local_surface',n,**info)
    coefficients=coefficients.reshape(NY,NX)
    # Displacement/Jacobian guards need a small geometry grid, not full-resolution
    # images. Coefficients remain authoritative at PL node evaluation time.
    yy,xx=np.meshgrid(np.linspace(0,1,65),np.linspace(0,1,65),indexing='ij')
    field=evaluate(coefficients,xx,yy).astype(np.float32)
    if np.max(abs(field))>max(4,h*.04):return inactive('extrapolation_too_large',n,**info)
    return field,dict(state='active',accepted=n,candidates=n,
                     max_preview_displacement=float(np.max(abs(field))),**info),coefficients


def _native_matvec(matrix,vector):
    """Float64 products without dispatching small problems to threaded BLAS."""
    matrix=np.ascontiguousarray(matrix,dtype=np.float64)
    vector=np.ascontiguousarray(vector,dtype=np.float64).reshape(-1,1)
    return cv2.gemm(matrix,vector,1.,None,0.).reshape(-1)


def _batch_crossings(profiles_by_row,windows,xs):
    """Same 80% quantile and contiguous half-depth rule, grouped by length.

    Grouping retains each window's exact samples. There is no padded quantile,
    changed threshold, grid-spacing prior or reduction of held-out curves.
    """
    groups={};hits=[None]*len(windows);statistics_s=crossing_s=0.
    for i,(lo,hi,radius) in enumerate(windows):
        groups.setdefault(hi-lo,[]).append(i)
    count=len(xs)
    for length,indices in groups.items():
        profiles=np.stack([profiles_by_row[:,windows[i][0]:windows[i][1]] for i in indices])
        t=time.perf_counter()
        backgrounds=np.percentile(profiles,80,axis=2)
        minima=np.argmin(profiles,axis=2)
        statistics_s+=time.perf_counter()-t;t=time.perf_counter()
        rows=np.arange(count)[None,:]
        batches=np.arange(len(indices))[:,None]
        depth=backgrounds-profiles[batches,rows,minima]
        levels=backgrounds-depth*.5
        axis=np.arange(length)[None,None,:]
        below=profiles<levels[:,:,None]
        left=np.max(np.where((axis<minima[:,:,None])&~below,axis,-1),axis=2)+1
        right=np.min(np.where((axis>minima[:,:,None])&~below,axis,length),axis=2)-1
        radius=np.array([windows[i][2] for i in indices])[:,None]
        good=(depth>=18)&(minima>0)&(minima<length-1)
        good&=(left>0)&(right<length-1)&(right-left+1<=np.maximum(7,radius))
        batch_index,k=np.nonzero(good);l=left[batch_index,k];r=right[batch_index,k]
        q=profiles[batch_index,k];level=levels[batch_index,k]
        sample=np.arange(len(k))
        edge_l=l-1+(q[sample,l-1]-level)/np.maximum(q[sample,l-1]-q[sample,l],1e-6)
        edge_r=r+(level-q[sample,r])/np.maximum(q[sample,r+1]-q[sample,r],1e-6)
        centre=(edge_l+edge_r)/2
        for local,i in enumerate(indices):
            selected=batch_index==local
            hits[i]=np.column_stack([xs[k[selected]],windows[i][0]+centre[selected]])
        crossing_s+=time.perf_counter()-t
    return hits,dict(statistics_s=statistics_s,crossing_s=crossing_s),len(groups)
