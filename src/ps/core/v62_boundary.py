"""Current physical-line lock and single-use startup evidence; CPU metadata only."""
from pathlib import Path
import copy,hashlib
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def peak_radius(scale,evidence,half):
    """A peak corridor in SOURCE pixels, independent of object motion."""
    scale=np.asarray(scale,np.float64)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):
        raise ValueError('Physical peak lock requires positive source scale')
    values=evidence.get('edge_rms',[]) if evidence else []
    noise=max(values)*float(scale.min()) if len(values)==4 and all(np.isfinite(v) and 0<=v<=2 for v in values) else 0.
    return float(min(.70*half,np.clip(1.25+.75*noise,1.25,2.0)))


def layer_continuity(previous,evidence):
    """Check signed sides on strong edges, not the colour of playing content."""
    from v51_target import border_signature
    current=border_signature(evidence)
    if previous is None or current is None:
        return dict(verified=True,measured=False,reason='no_signed_vector_prior')
    a=np.asarray(previous,np.float64);b=np.asarray(current,np.float64)
    if a.shape!=(4,3) or b.shape!=(4,3) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return dict(verified=False,measured=False,reason='invalid_signed_layer_prior')
    weights=np.array([255.,224.,224.]);a=a*weights;b=b*weights
    na=np.linalg.norm(a,axis=1);nb=np.linalg.norm(b,axis=1)
    strong=(na>=16.)&(nb>=16.)
    cosine=np.sum(a*b,axis=1)/np.maximum(na*nb,1e-9)
    failed=strong&(cosine<.25)
    return dict(verified=not bool(failed.any()),measured=bool(strong.any()),
        strong_edges=int(strong.sum()),opposite_edges=int(failed.sum()),
        edge_cosine=cosine.tolist(),minimum_cosine=.25,
        reason='same_signed_physical_side' if not failed.any() else 'parallel_layer_side_changed')


def issue_startup_receipt(image,source_quad,primary,secondary,secondary_quad,scale,agreement,gate):
    """Bind actual primary64 and independent24 to THIS caller-held source array.

    No arrays, image leases or hardware pointers are owned by this record.
    Startup alone consumes it synchronously before the source lease is returned.
    Background proposals must still be sampled on their currently leased frame.
    """
    from v49_boundary import actual_source64,array_key
    key=array_key(image)
    if (not agreement.get('verified') or not gate.get('reliable') or not actual_source64(primary,key)
        or secondary.get('profiles_per_edge')!=24 or not secondary.get('same_frame_source')
        or secondary.get('current_source_key')!=key or secondary.get('deadline_hit')):
        return None
    return dict(source_instance_id=id(image),source_key=array_key(image),
        source_corners=np.asarray(source_quad,np.float32).tolist(),
        scale=tuple(float(v) for v in scale),primary=copy.deepcopy(primary),
        secondary=copy.deepcopy(secondary),secondary_corners=np.asarray(secondary_quad,np.float32).tolist(),
        gate=dict(gate),agreement=dict(agreement),consumed=False,
        kind='same_live_source_primary64_independent24')


def consume_startup_receipt(info,image,source_quad,scale):
    """Recheck geometry/provenance without rerunning any border search."""
    if not isinstance(info,dict):return None
    receipt=info.pop('_initial_boundary_receipt',None)
    if not isinstance(receipt,dict) or receipt.get('consumed'):return None
    receipt['consumed']=True
    from v49_boundary import array_key,actual_source64
    from v62_policy import current_agreement,line_lock
    source=np.asarray(source_quad,np.float32);bound=np.asarray(receipt.get('source_corners'),np.float32)
    scale=np.asarray(scale,np.float64)
    if (receipt.get('kind')!='same_live_source_primary64_independent24'
        or receipt.get('source_instance_id')!=id(image) or receipt.get('source_key')!=array_key(image)
        or receipt.get('scale')!=tuple(float(v) for v in scale)
        or source.shape!=(4,2) or bound.shape!=(4,2) or not np.isfinite(bound).all()
        or np.max(np.abs(source-bound))>1e-3):return None
    primary=receipt.get('primary',{});secondary=receipt.get('secondary',{})
    if (not actual_source64(primary,array_key(image)) or secondary.get('profiles_per_edge')!=24
        or not secondary.get('same_frame_source') or secondary.get('current_source_key')!=array_key(image)
        or secondary.get('deadline_hit')):return None
    q=((source+.5)/scale-.5).astype(np.float32)
    other=np.asarray(receipt.get('secondary_corners'),np.float32)
    agreement=current_agreement(other,q,secondary,primary,scale,array_key(image))
    lock=line_lock(q,other)
    if not agreement.get('verified') or not lock.get('verified') or not receipt.get('gate',{}).get('reliable'):return None
    agreement.update(startup_same_frame_proof_reused=True,repeated_border_search_skipped=True,
        source_instance_bound=True,receipt_single_use=True,line_lock=lock)
    return q,copy.deepcopy(primary),dict(receipt['gate'],same_frame_proof_reused=True),agreement
