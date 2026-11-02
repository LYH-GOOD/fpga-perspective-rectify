"""Bounded CPU target/corner continuity; no cached H, image leases or device IO."""
from pathlib import Path
import hashlib
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def align_current(candidate,evidence,reference):
    """Match cyclic numbering only; never move/smooth the measured corners."""
    q=np.asarray(candidate,np.float32);r=np.asarray(reference,np.float32)
    distances=[float(np.max(np.linalg.norm(np.roll(q,-i,axis=0)-r,axis=1))) for i in range(4)]
    shift=int(np.argmin(distances));e=dict(evidence)
    if shift:
        for name in ('edge_support','edge_rms','edge_polarity','border_colors','corner_displacements'):
            if name in e and len(e[name])==4:e[name]=list(e[name][shift:])+list(e[name][:shift])
        if len(e.get('edges',()))==4:
            reports=e['edges'][shift:]+e['edges'][:shift]
            e['edges']=[dict(item,edge=i) for i,item in enumerate(reports)]
    e['corner_correspondence_shift']=shift
    return np.ascontiguousarray(np.roll(q,-shift,axis=0),np.float32),e

def border_signature(evidence):
    colors=np.asarray(evidence.get('border_colors',()),np.float32)
    if colors.shape!=(4,6) or not np.isfinite(colors).all() or not evidence.get('valid'):return None
    # Difference across the physical exterior is less sensitive to a uniform
    # exposure/color cast than the absolute cover or playing screen content.
    delta=colors[:,3:]-colors[:,:3]
    return np.clip(delta/np.array([255.,224.,224.],np.float32),-1.5,1.5)

def target_relation(previous,candidate,evidence,signature):
    current=border_signature(evidence)
    diagonal=max(8.,float(np.linalg.norm(np.asarray(previous)[2]-np.asarray(previous)[0])))
    travel=float(np.max(np.linalg.norm(np.asarray(candidate)-previous,axis=1)))/diagonal
    difference=None if current is None or signature is None else float(np.mean(np.abs(current-signature)))
    same=difference is not None and difference<=.15 and travel<=.20
    changed=difference is not None and difference>.25
    label='same_target' if same else 'new_target' if changed else 'unproven_reacquisition'
    return dict(state=label,same_target=bool(same),target_changed=not same,
        boundary_signature_difference=difference,normalized_corner_travel=travel,
        semantic_identity_proven=False),current
