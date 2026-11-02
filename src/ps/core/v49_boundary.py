"""Current-frame exterior agreement and ephemeral detector receipts; CPU only."""
from pathlib import Path
import hashlib,copy
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def array_key(a):
    return (int(a.ctypes.data),tuple(a.shape),tuple(a.strides),a.dtype.str)

def actual_source64(evidence,source_key):
    return bool(source_key is not None and evidence.get('same_frame_source')
        and evidence.get('profiles_per_edge')==64 and evidence.get('current_source_key')==source_key
        and evidence.get('source_proof_kind') in ('raw_YUV_profiles','source_color_profiles','source_Y_profiles')
        and len(evidence.get('fraction_limits',()))==2 and not evidence.get('deadline_hit'))

def exterior_agreement(first,second,first_e,second_e,scale,source_key=None):
    """Line-normal disagreement avoids amplifying tiny errors at intersections.

    Independent CURRENT source64 proof remains mandatory for wider searches.
    Supports/RMS, polarity, convexity and temporal geometry are checked by caller.
    Both the fit-derived normal allowance and absolute corner cap are bounded.
    """
    from v90_transaction import pair_geometry
    error,line_error,corner_error=pair_geometry(first,second)
    if error is not None:
        return dict(verified=False,reason='invalid_current_quad' if error=='invalid' else 'degenerate_current_edges')
    rms_a=float(max(first_e.get('edge_rms',[1e30]*4)))
    rms_b=float(max(second_e.get('edge_rms',[1e30]*4)))
    support=min(tuple(first_e.get('edge_support',[0.]*4))+tuple(second_e.get('edge_support',[0.]*4)))
    normal_limit=float(np.clip(.30+.5*(rms_a+rms_b)+.125*float(np.min(scale)),.55,.90))
    provenance=actual_source64(second_e,source_key)
    independent=not (actual_source64(first_e,source_key)
        and first_e.get('source_proof_kind')==second_e.get('source_proof_kind')
        and first_e.get('fraction_limits')==second_e.get('fraction_limits'))
    verified=(provenance and independent and first_e.get('valid',False) and second_e.get('valid',False)
        and first_e.get('supported_edges')==4 and second_e.get('supported_edges')==4
        and first_e.get('refined_corners')==4 and second_e.get('refined_corners')==4
        and support>=.80 and max(rms_a,rms_b)<=.65
        and line_error<=normal_limit and corner_error<=1.5)
    return dict(verified=bool(verified),line_normal_difference=line_error,
        normal_limit=normal_limit,corner_difference=corner_error,corner_limit=1.5,
        min_support=float(support),max_rms=max(rms_a,rms_b),units='tracking_pixels',
        proof='same_frame_independent_source64',source64_provenance_verified=bool(provenance),independent_sampling_verified=bool(independent),
        profiles_per_edge=second_e.get('profiles_per_edge'),source_backend=second_e.get('edge_backend'),old_H_not_used=True)

def outer_features(points,quad):
    """Keep real features in a narrow exterior band, not playing screen content."""
    p=np.asarray(points,np.float32).reshape(-1,2);q=np.asarray(quad,np.float32)
    if not len(p):return p
    edge=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(edge,axis=1)
    if np.min(length)<4:return np.empty((0,2),np.float32)
    normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
    center=q.mean(axis=0)
    normal*=np.where(np.sum((center-q)*normal,axis=1)>=0,1.,-1.)[:,None]
    d=np.sum((p[:,None,:]-q[None,:,:])*normal[None,:,:],axis=2)
    # Allow a little exterior/case texture; exclude the deep interior. The width
    # is bounded in observation pixels and scales with the shortest side.
    # Only the rim/exterior carries camera/object motion. Screen pixels must
    # not dominate FB/RANSAC even when the content inside the case is moving.
    width=float(np.clip(.02*float(np.min(length)),1.25,2.0))
    keep=np.isfinite(p).all(axis=1)&(np.min(d,axis=1)>=-3.)&(np.min(d,axis=1)<=width)
    return np.ascontiguousarray(p[keep],np.float32)

def issue_receipt(observation,source_corners,evidence,gate,original_edges,scale):
    # Only synchronous recovery has a caller-owned frame index and source key.
    # Startup/external supplied corners cannot get a reusable receipt.
    if observation is None or 'frame_index' not in observation or 'source_key' not in observation:return None
    return dict(frame_index=int(observation['frame_index']),source_key=observation['source_key'],
        gray_key=array_key(observation['gray']),scale=tuple(float(v) for v in scale),
        source_corners=np.asarray(source_corners,np.float32).tolist(),
        evidence=copy.deepcopy(evidence),gate=copy.deepcopy(gate),
        original_all_four=bool(original_edges.get('refined_corners')==4 and
            len(original_edges.get('edges',[]))==4 and all(e.get('accepted',False) for e in original_edges['edges'])))

def read_receipt(info,image,gray,scale,index,full):
    """A receipt proves only this call's frame/gray/layout/returned four corners.

    Plain CPU metadata; never caches H or owns source/MMAP arrays. A mismatch
    falls back to full current validation rather than accepting a stale receipt.
    """
    r=info.get('_current_boundary_receipt')
    if not isinstance(r,dict):return None
    if (r.get('frame_index')!=index or r.get('source_key')!=array_key(image)
        or r.get('gray_key')!=array_key(gray) or r.get('scale')!=tuple(float(v) for v in scale)
        or not r.get('original_all_four') or not r.get('gate',{}).get('reliable')):return None
    source=np.asarray(r['source_corners'],np.float32);q=np.asarray(full,np.float32)
    if source.shape!=(4,2) or q.shape!=(4,2) or not np.isfinite(source).all() or not np.isfinite(q).all() or np.max(np.abs(source-q))>1e-3:return None
    e=copy.deepcopy(r['evidence'])
    if (not e.get('valid',False) or e.get('supported_edges')!=4 or e.get('refined_corners')!=4
        or min(e.get('edge_support',[0.]*4))<.60 or max(e.get('edge_rms',[1e30]*4))>1.):return None
    candidate=((source+.5)/scale-.5).astype(np.float32)
    g=dict(r['gate'],same_frame_receipt_reused=True,repeated_border_selection_skipped=True)
    return candidate,e,g
