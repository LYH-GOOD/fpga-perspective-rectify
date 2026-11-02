"""Cached live source/FPS/progress. Only the HDMI owner paints these pixels.

No runtime fonts, image analysis, devices, timers or additional scanout writer.
The FPS receipt is recorded only after a successful new corrected submission.
"""
from pathlib import Path
from collections import deque
import hashlib,json
import cv2,numpy as np
from p11_contract import RELEASE_ID

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
INFO=(0,72,1280,52)
SOURCE=(20,72,202,52)
PROGRESS=(248,72,694,52)
FPS=(980,72,288,52)

def load_assets(assets,root):
    root=Path(root)
    spec=json.loads((root/'v123_live_ui.json').read_text(encoding='utf-8'))
    atlas=cv2.imdecode(np.frombuffer((root/'v123_live_ui.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if atlas is None or list(atlas.shape)!=spec['shape']:raise ValueError('Invalid live UI atlas')
    parts={}
    for name,(x,y,w,h) in spec['parts'].items():
        if min(x,y)<0 or min(w,h)<=0 or x+w>atlas.shape[1] or y+h>atlas.shape[0]:
            raise ValueError('Invalid live UI tile '+name)
        part=atlas[y:y+h,x:x+w];part.flags.writeable=False;parts[name]=part
    atlas.flags.writeable=False
    assets.live_ui_parts=parts
    assets.live_ui_spec=spec

class OutputRate:
    """Unique corrected frame receipts / fixed3s, including true manual.

    Existing CURRENT-only diagnostics retain their old definitions.
    """
    def __init__(self):
        self.times=deque();self.generation=None;self.last_sequence=None
    def observe(self,meta,when,valid):
        generation=meta.get('ui_generation')
        if generation!=self.generation:
            self.times.clear();self.last_sequence=None;self.generation=generation
        if not valid or meta.get('preview_only') or meta.get('inspection_redraw') or meta.get('frozen_output'):return False
        sequence=meta.get('camera_sequence')
        if sequence is None or sequence<0 or self.last_sequence is not None and sequence<=self.last_sequence:return False
        self.last_sequence=sequence;self.times.append(when)
        self.fps(when)
        return True
    def fps(self,now):
        while self.times and self.times[0]<=now-3.:self.times.popleft()
        return len(self.times)/3.

def source_key(meta,has_output):
    origin=meta.get('correction_origin')
    if origin not in ('AUTO','AI','MANUAL'):
        origin='MANUAL' if meta.get('manual_tracking') or meta.get('admission_mode')=='manual' else 'AUTO'
    if has_output:return origin
    if meta.get('hybrid_phase')=='EMPTY_WAIT':return 'EMPTY'
    return origin+'_SEARCH'

def progress_key(display,meta,has_output):
    """Metadata snapshot only; no pixels or frontend mutation."""
    with display.condition:
        switch=getattr(display,'target_switch',None)
        if switch is not None and switch.active and switch.generation==meta.get('ui_generation'):
            proof=meta.get('target_selection_proof') or {}
            if meta.get('target_selection_failed')==switch.request_id:return 'failed'
            if (has_output and meta.get('state')=='CURRENT' and proof.get('request_id')==switch.request_id
                    and proof.get('single_target') is True and proof.get('current_aligned') is True):return 'display'
            phase=meta.get('hybrid_phase','')
            if phase=='AI_CONFIRM':return 'verify'
            if phase in ('AI_LOADING','AI_INFER'):return 'ai'
            return {'prepare':'prepare','edges':'auto','verify':'verify','display':'verify',
                    'miss':'ai','fallback':'ai'}.get(switch.phase,'prepare')
        controller=getattr(display,'page_feedback',None)
        load=getattr(controller,'loading',None)
        if load is not None and load.get('generation')==meta.get('ui_generation') and load.get('until')=='output':
            if has_output:return 'blank'
            phase=meta.get('hybrid_phase','')
            if phase=='AI_CONFIRM':return 'verify'
            if phase in ('AI_LOADING','AI_INFER'):return 'ai'
            return {'prepare':'prepare','search':'auto','verify':'verify','display':'verify',
                    'layout':'prepare','snapshot':'prepare'}.get(load.get('stage'),'blank')
        notice=getattr(display,'target_notice','idle')
    return {'unconfirmed':'failed','not_covered':'failed','multiple':'multiple','current':'current'}.get(notice,'blank')

class LiveUI:
    def __init__(self):
        self.rate=OutputRate();self.tokens={};self.number=None;self.number_at=-float('inf');self.number_patch=None
    def _number(self,parts,has_output,now):
        if has_output and self.rate.last_sequence is not None:
            if self.number not in (None,'--') and now-self.number_at<.1:return self.number,self.number_patch
            value='%.1f'%self.rate.fps(now)
        else:value='--'
        self.number_at=now
        if value!=self.number:
            patch=parts['fps_base'].copy();x=278
            for char in reversed(value):
                tile=parts['digit_'+char];x-=tile.shape[1]
                patch[:,x:x+tile.shape[1]]=tile
            patch.flags.writeable=False
            self.number_patch=patch;self.number=value
        return self.number,self.number_patch
    def paint(self,canvas,assets,meta,has_output,display,now,address,force=False):
        parts=assets.live_ui_parts
        if self.rate.generation!=meta.get('ui_generation'):
            self.rate.observe(meta,now,False)
            self.number=None;self.number_at=-float('inf')
        source=source_key(meta,has_output);progress=progress_key(display,meta,has_output)
        number,patch=self._number(parts,has_output,now)
        token=(meta.get('ui_generation'),source,progress,number)
        previous=self.tokens.get(address)
        if force or previous is None or previous[0]!=token[0]:
            canvas[72:124]=parts['info_base']
            previous=None
        if previous is None or previous[1]!=source:canvas[72:124,20:222]=parts['source_'+source]
        if previous is None or previous[2]!=progress:canvas[72:124,248:942]=parts['progress_'+progress]
        if previous is None or previous[3]!=number:canvas[72:124,980:1268]=patch
        self.tokens[address]=token
        if len(self.tokens)>32:self.tokens={address:token}
        return self.rate.fps(now)
