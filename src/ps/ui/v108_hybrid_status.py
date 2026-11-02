"""Cached hybrid footer, independent of camera, model, and frame ownership.

The atlas is decoded once at module import. Runtime selection only returns a
read-only 320x28 view and formats the existing English rate label. Chinese
glyphs, fonts, Pillow and filesystem reads never enter the live frame path.
"""
from pathlib import Path
from functools import lru_cache
import hashlib
import math
import cv2
import numpy as np
from p11_contract import RELEASE_ID

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ORIGINS=('AUTO','AI','MANUAL')
PHASES=('AUTO_SEARCH','AUTO_TRACK','AI_LOADING','AI_INFER','AI_CONFIRM',
        'AI_TRACK','WAIT_TARGET','EMPTY_WAIT','AI_ERROR','MANUAL_TRACK','MANUAL_FIXED','MANUAL_SNAPSHOT',
        'AUTO_RECOVER','AI_REJECT_RECOVER','RECOVERY_COOLDOWN','DISPLAY_HOLD')
QUALIFIERS=('NORMAL','HELD','LOST')
TILE_WIDTH=320
TILE_HEIGHT=28
_PHASE_SET=frozenset(PHASES)
_CURRENT_STATES=frozenset(('CURRENT','MANUAL'))
_HELD_STATES=frozenset(('HELD','MANUAL_HELD'))
_PHASE_HINTS={
    'AUTO_SEARCH':'SEARCH CURRENT FRAME',
    'AUTO_TRACK':'AUTO TRACK',
    'AI_LOADING':'AI LOADING / WAIT',
    'AI_INFER':'AI ONE-SHOT INFERENCE',
    'AI_CONFIRM':'AI CURRENT-FRAME VERIFY',
    'AI_TRACK':'AI CORRECTION',
    'WAIT_TARGET':'WAIT TARGET',
    'EMPTY_WAIT':'EMPTY / NEXT TARGET AUTO FIRST',
    'AI_ERROR':'AI FAILED / WAIT',
    'MANUAL_TRACK':'MANUAL SELECT / TRACK',
    'MANUAL_FIXED':'MANUAL FIXED / RESELECT IF MOVED',
    'MANUAL_SNAPSHOT':'MANUAL STILL / RECAPTURE',
    'AUTO_RECOVER':'AUTO RESEARCH / RECOVERY',
    'AI_REJECT_RECOVER':'ALIGN FAILED / AUTO RECOVERY',
    'RECOVERY_COOLDOWN':'RECOVERY COOLDOWN',
    'DISPLAY_HOLD':'PAUSED VIEW / PREPARING NEW FRAME',
}


def _load_badges():
    image=cv2.imdecode(np.frombuffer((Path(__file__).resolve().parent/
        'v108_hybrid_status.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    keys=tuple((origin,phase,qualifier) for origin in ORIGINS
        for phase in PHASES for qualifier in QUALIFIERS)
    if image is None or image.shape!=(len(keys)*TILE_HEIGHT,TILE_WIDTH,3):
        raise ValueError('Invalid cached hybrid status atlas')
    image.setflags(write=False)
    return {key:image[i*TILE_HEIGHT:(i+1)*TILE_HEIGHT] for i,key in enumerate(keys)}


_BADGES=_load_badges()

def _rate(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>=0. else 0.
    except (TypeError,ValueError,OverflowError):return 0.


@lru_cache(maxsize=len(_BADGES))
def _descriptor(origin,phase,qualifier):
    return _BADGES[(origin,phase,qualifier)],_PHASE_HINTS[phase]


def footer(meta,has_output,display_rate):
    """Return (cached badge, label), or None for an untagged legacy offer.

    correction_origin describes the current correction authority, while
    hybrid_phase describes the running operation. Neither implies a valid
    current output: the existing state and output presence remain decisive.
    hybrid_valid_fps is supplied by completed unique valid corrections; it is
    separate from the HDMI owner's submission rate. No rate is inferred from
    AI model calls, source labels, or a nominal camera/HDMI configuration.
    """
    origin=meta.get('correction_origin')
    if origin not in ORIGINS:return None
    state=meta.get('state','SEARCHING')
    phase=meta.get('hybrid_phase')
    if phase=='AUTO_RECOVER' and meta.get('recovery_from_ai'):phase='AI_REJECT_RECOVER'
    if origin=='AI' and has_output and meta.get('manual_tracking')=='FIXED':phase='MANUAL_FIXED'
    if phase not in _PHASE_SET:
        if origin=='MANUAL':
            mode=meta.get('manual_tracking')
            phase=('MANUAL_SNAPSHOT' if mode=='SNAPSHOT' else 'MANUAL_FIXED'
                if mode=='FIXED' else 'MANUAL_TRACK') if has_output else 'WAIT_TARGET'
        else:
            phase=('AI_TRACK' if origin=='AI' else 'AUTO_TRACK') if has_output else 'WAIT_TARGET'
            if origin=='AUTO' and state in ('INITIALIZING','PLACEMENT','SEARCHING','STARTING'):
                phase='AUTO_SEARCH'
    if not has_output and phase in ('AUTO_TRACK','AI_TRACK','MANUAL_TRACK','MANUAL_FIXED','MANUAL_SNAPSHOT'):
        phase='WAIT_TARGET'
    if phase=='DISPLAY_HOLD':qualifier='HELD'
    elif state=='LOST' or (state in _HELD_STATES and not has_output):
        qualifier='LOST'
    elif state in _HELD_STATES:qualifier='NORMAL' if meta.get('continuity_output') and has_output else 'HELD'
    else:qualifier='NORMAL'
    badge,hint=_descriptor(origin,phase,qualifier)
    output_state=('CURRENT' if state in _CURRENT_STATES else 'HELD'
        if state in _HELD_STATES else 'NONE') if has_output and state!='LOST' else 'NONE'
    if has_output and phase=='MANUAL_SNAPSHOT':output_state='STILL'
    if has_output and phase=='MANUAL_FIXED':output_state='FIXED'
    if phase=='DISPLAY_HOLD':output_state='PAUSED'
    valid_rate=meta.get('hybrid_valid_fps',meta.get('manual_fps',0.)
        if origin=='MANUAL' else meta.get('correction_fps',0.))
    label='CORR(valid) %.1f | DISP %.1f | OUT %s | %s'%(
        0. if phase=='DISPLAY_HOLD' else _rate(valid_rate),_rate(display_rate),output_state,hint)
    if output_state in ('FIXED','STILL'):label=label.replace('CORR(valid)','CORR(output)',1)
    if phase=='RECOVERY_COOLDOWN':label+=' | RETRY %.1fs'%_rate(meta.get('recovery_retry_after_s',0.))
    if has_output and meta.get('continuity_output'):label+=' | LIVE CONTINUITY <=1s'
    if meta.get('ai_mode_locked'):label+=' | AI LOCK'
    return badge,label
