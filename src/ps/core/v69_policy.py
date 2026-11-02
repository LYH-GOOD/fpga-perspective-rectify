"""V49 ordinary-path support: current-frame CPU proof reuse, no device access."""
from pathlib import Path
import copy,hashlib
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class CurrentProofWorkspace:
    """At most four completed requests, scoped to one source/gray/index.

    Owns small corners and CPU evidence only. No camera arrays, leases, native
    pointers, H or hardware proof are retained. Failed proofs are never cached.
    """
    def __init__(self):
        self.scope=None;self.entries=[];self.hits=0;self.stores=0

    def clear(self):
        self.scope=None;self.entries.clear();self.hits=self.stores=0

    def begin(self,image,gray,index,scale):
        from v49_boundary import array_key
        self.clear()
        self.scope=(id(image),array_key(image),id(gray),array_key(gray),int(index),
            tuple(float(v) for v in scale))

    def token(self,image,gray,index,scale,candidate,reference,radius,new_candidate,gray_reliable,stable_fb):
        from v49_boundary import array_key
        scope=(id(image),array_key(image),id(gray),array_key(gray),int(index),
            tuple(float(v) for v in scale))
        if scope!=self.scope:return None
        a=np.asarray(candidate,np.float32);b=np.asarray(reference,np.float32)
        if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():return None
        return (a.tobytes(),b.tobytes(),float(radius),bool(new_candidate),bool(gray_reliable),bool(stable_fb))

    def get(self,token):
        if token is None:return None
        for key,quad,evidence,gate,agreement in self.entries:
            if key==token:
                self.hits+=1
                return quad.copy(),copy.deepcopy(evidence),dict(gate),copy.deepcopy(agreement)
        return None

    def remember(self,token,quad,evidence,gate,agreement):
        from v49_boundary import actual_source64
        if (token is None or self.scope is None or not gate.get('reliable')
                or not agreement.get('verified') or not actual_source64(evidence,self.scope[1])
                or not agreement.get('source64_provenance_verified')
                or not agreement.get('independent_sampling_verified')):return
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return
        self.entries=[item for item in self.entries if item[0]!=token]
        self.entries.append((token,q.copy(),copy.deepcopy(evidence),dict(gate),copy.deepcopy(agreement)))
        if len(self.entries)>4:self.entries.pop(0)
        self.stores+=1

    def summary(self):
        return dict(hits=self.hits,stored=self.stores,entries=len(self.entries),capacity=4,
            same_live_source_only=True,failed_proofs_retained=False,hardware_proof_reused=False)


def issue_current_receipt(observation,image,source_quad,primary,secondary,secondary_quad,scale,agreement,gate):
    """Only a synchronous, full-source detection may publish this receipt.

    ROI/donor/background observations receive no reusable current receipt.
    Primary returned corners remain the physical boundary reference.
    """
    from v49_boundary import array_key
    from v62_boundary import issue_startup_receipt
    if (not isinstance(observation,dict) or 'frame_index' not in observation
            or observation.get('source_key')!=array_key(image)):return None
    gray=observation.get('gray')
    if gray is None:return None
    proof=issue_startup_receipt(image,source_quad,primary,secondary,secondary_quad,scale,agreement,gate)
    if proof is None:return None
    return dict(kind='v69_same_frame_primary64_independent24',
        frame_index=int(observation['frame_index']),gray_instance_id=id(gray),gray_key=array_key(gray),proof=proof)


def read_current_receipt(info,image,gray,scale,index,full):
    """Recheck bound metadata; the caller removes it after final admission.

    Two same-call readers (ROI/full return and final tracker admission) can
    inspect it while the exact source is leased. No sampling is repeated.
    """
    from v49_boundary import array_key
    from v62_boundary import consume_startup_receipt
    if not isinstance(info,dict):return None
    receipt=info.get('_current_boundary_receipt')
    if (not isinstance(receipt,dict) or receipt.get('kind')!='v69_same_frame_primary64_independent24'
            or receipt.get('frame_index')!=index or receipt.get('gray_instance_id')!=id(gray)
            or receipt.get('gray_key')!=array_key(gray)):return None
    result=consume_startup_receipt({'_initial_boundary_receipt':copy.deepcopy(receipt.get('proof'))},image,full,scale)
    if result is None:return None
    quad,evidence,gate,agreement=result
    agreement=dict(agreement,startup_same_frame_proof_reused=False,
        current_same_frame_proof_reused=True,receipt_single_use=False,
        receipt_scope='synchronous current frame; removed after final tracker admission')
    return quad,evidence,dict(gate,same_frame_receipt_reused=True,
        repeated_border_selection_skipped=True,current_source_agreement=agreement)


def ordinary_policy(evidence,gate,age,max_gap,scheduled=False,lost=False):
    """The V49 normal four-edge gate; scheduling still owns complete FB LK."""
    eligible=(not lost and not scheduled and 0<=age<max_gap and gate.get('reliable',False)
        and evidence.get('valid',False) and evidence.get('supported_edges')==4
        and evidence.get('refined_corners')==4 and not evidence.get('color_vector_proof',False))
    return dict(eligible=bool(eligible),policy='V49_current_Y_four_edges',
        current_four_edges_required=True,scheduled_FB_not_skipped=True,
        anchor_age=int(age),max_anchor_age=int(max_gap),reacquisition=bool(lost))
