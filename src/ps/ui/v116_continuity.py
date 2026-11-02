"""Bounded geometry reuse on fresh pixels; no image storage or tracking work."""
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

MAX_CONTINUITY_S=1.
HARD_STOP_REASONS=frozenset(('manual_motion_too_large',
    'candidate_touches_image_border_or_is_clipped','跟踪四角越界或形变异常'))


def continuity_cancelled(row):
    """Reuse existing definite loss reports; no new motion/colour threshold."""
    return row.get('target_cycle_state')=='ABSENT' or row.get('track_reason') in HARD_STOP_REASONS


def valid_continuity(row,now):
    """Only producer-labelled held jobs can supply a live continuity pair."""
    if not row.get('continuity_output') or not (row.get('state')=='HELD' or
            row.get('state')=='MANUAL_HELD' and row.get('manual_reference_v17')):return False
    verified=float(row.get('verified_at',0.));ready=float(row.get('capture_ready_at',0.))
    return (not row.get('frozen_output') and not continuity_cancelled(row) and
        len(row.get('corners',()))==4 and row.get('continuity_epoch')==row.get('hybrid_epoch') and
        verified>0. and 0.<=now-verified<=MAX_CONTINUITY_S and
        now<=float(row.get('continuity_deadline',0.)) and -.02<=now-ready<=.5 and
        verified<=ready+.02)


def mark_continuity(row,has_tiles,now):
    """Metadata only; held frames never advance the verified geometry clock."""
    row['continuity_output']=False
    if not (row.get('state')=='HELD' or row.get('state')=='MANUAL_HELD' and row.get('manual_reference_v17')) or not has_tiles:return False
    verified=float(row.get('verified_at',0.))
    row.update(continuity_output=True,continuity_deadline=verified+MAX_CONTINUITY_S,
        continuity_age_s=max(0.,now-verified),continuity_epoch=row.get('hybrid_epoch'))
    row['continuity_output']=valid_continuity(row,now)
    return row['continuity_output']
