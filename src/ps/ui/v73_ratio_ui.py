"""Right-hand settings, ordinary-RAM event snapshots, no resident draw loop."""
from pathlib import Path
import hashlib,json,time,threading
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v73_ratio import RatioRegistry,PRESETS,SHIFT,normalize,dimensions,revision_of
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

PANEL=(820,72,460,648)
ENTRY=(768,0,224,72)
def inside(p,r):return p is not None and r[0]<=p[0]<r[0]+r[2] and r[1]<=p[1]<r[1]+r[3]
def load_assets(assets,root):
    root=Path(root)
    def read(name):
        image=cv2.imread(str(root/name),cv2.IMREAD_COLOR)
        if image is None:raise ValueError('Missing ratio UI asset '+name)
        image.setflags(write=False);return image
    assets.ratio_panel=read('v73_ratio_panel.png');atlas=read('v73_ratio_atlas.png')
    if assets.ratio_panel.shape!=(648,460,3) or atlas.shape!=(1024,1024,3):raise ValueError('Invalid ratio assets')
    spec=json.loads((root/'v73_ratio_assets.json').read_text(encoding='utf-8'))
    assets.ratio_parts={name:atlas[y:y+h,x:x+w] for name,(x,y,w,h) in spec.items()}
    assets.ratio_original_headers=dict(assets.headers);assets.ratio_header_cache={}
    assets.ratio_reading_header=read('v73_reading_header.png')
    assets.ratio_asset_resident_bytes=assets.ratio_panel.nbytes+atlas.nbytes+assets.ratio_reading_header.nbytes

def ratio_header(assets,value):
    key=value if value in PRESETS or value=='busy' else 'custom'
    cache=assets.ratio_header_cache
    if key not in cache:
        headers={}
        for view,original in assets.ratio_original_headers.items():
            image=original.copy();image[3:69,768:992]=assets.ratio_parts['header_'+key]
            image.setflags(write=False);headers[view]=image
        cache[key]=headers
    return cache[key]

def render_ratio(canvas,payload,assets):
    if not payload.get('ratio_background_cached'):canvas[:]=payload['source']
    x,y,w,h=PANEL;canvas[y:y+h,x:x+w]=assets.ratio_panel
    model=payload['meta'];parts=assets.ratio_parts
    def put(name,px,py):
        image=parts[name];hh,ww=image.shape[:2];canvas[y+py:y+py+hh,x+px:x+px+ww]=image
    def number(text,px,py):
        for char in str(text)[:16]:
            image=parts.get('glyph_'+char)
            if image is not None:
                canvas[y+py:y+py+28,x+px:x+px+16]=image;px+=16
    put('mode_'+model['mode'],26,78)
    keyboard=model.get('field') is not None
    put('done' if keyboard else 'reset',306,27)
    if keyboard:
        keys='123456789.0';keys=list(keys)+['del']
        for i,key in enumerate(keys):put('key_'+key,26+(i%3)*140,208+(i//3)*60)
    else:
        for i,key in enumerate(list(PRESETS)+['custom']):put('preset_'+key+('_selected' if model['draft']==key else ''),26+(i%3)*140,133+(i//3)*96)
    if model['draft']=='custom':
        fy=132 if keyboard else 330
        put('width',26,fy+10);put('height',172,fy+10)
        for key,fx in [('width',56),('height',202)]:
            canvas[y+fy:y+fy+49,x+fx:x+fx+97]=(35,28,17)
            cv2.rectangle(canvas,(x+fx,y+fy),(x+fx+96,y+fy+48),(132,115,85),1)
            if model.get('field')==key:cv2.rectangle(canvas,(x+fx,y+fy),(x+fx+96,y+fy+48),(220,205,123),2)
            number(model[key],fx+5,fy+9)
        put('invalid' if model.get('error')=='invalid' else 'hint',26,464 if keyboard else 396)
    if model.get('error')=='failed':put('failed',26,480)
    put('current',26,520)
    current=model['current']
    if current=='original':
        put('current_original',88,520)
    else:number(current,88,520)
    try:normalize(model['width']+':'+model['height'] if model['draft']=='custom' else model['draft']);valid=True
    except ValueError:valid=False
    put('cancel',26,565);put('apply' if valid else 'apply_disabled',166,565)

class RatioUI:
    def __init__(self,state,display):
        self.state=state;self.display=display;self.registry=RatioRegistry()
        self.registry.on_reject=self.manual_mapping_rejected
        self.pending=None;self.snapshot_task=None;self.open_requested=False
        self.base_show=display._show;self.model=None;self.captured=None
        self.previous_offer=None
    def mode(self):return 'manual' if self.state.ticket.manual else 'auto'
    def manual_mapping_rejected(self,mode,revision,reason):
        pending=self.pending
        if pending is not None and (pending['mode'],pending['revision'])==(mode,revision):self.fail('manual_mapping_proof_rejected')
        else:self.registry.rollback(mode)
    def prepare_header_transition(self):
        d=self.display
        if self.state.page!='home' and self.pending is None and not self.open_requested and d.target_switch is None:
            d._show=self.first_result_show
    def first_result_show(self,raw,out,meta):
        d=self.display
        if out is not None and int(meta.get('ui_generation',-1))==d.ui_generation:
            with d.condition:d.canvas_views.clear()
            shown=self.base_show(raw,out,meta)
            if shown and d._show==self.first_result_show:d._show=self.base_show
            return shown
        return self.base_show(raw,out,meta)
    def header(self,value):
        self.state.assets.headers=ratio_header(self.state.assets,value)
        with self.display.condition:self.display.canvas_views.clear()
    def cancel_for_request(self,layout_only,generation):
        if self.pending is not None:
            if layout_only:self.pending['generation']=generation
            else:self.fail('page_changed',reopen=False)
        self.open_requested=False;self.snapshot_task=None
        if self.display._show in (self.capture_show,self.first_result_show):self.display._show=self.base_show
    def open(self,generation,error=None):
        d=self.display
        with d.condition:
            if generation!=d.ui_generation or d.inspection.kind or d.target_switch is not None or self.pending is not None:return False
            latest=getattr(d,'latest_meta',{})
            if latest.get('state') not in ('CURRENT','HELD','MANUAL','MANUAL_HELD') or latest.get('ui_generation')!=generation:return False
            mode=self.mode();current=self.registry.applied[mode][0]
            draft=current if current in PRESETS else 'custom'
            width,height=('3','4') if current in PRESETS else current.split(':')
            self.model=dict(mode=mode,current=current,draft=draft,width=width,height=height,field=None,error=error)
            self.open_requested=generation;d._show=self.capture_show
            if d.ui_view=='snapshot':d.inspection_restore=True
            d.condition.notify_all()
        return True
    def capture_show(self,raw,out,meta):
        d=self.display
        if int(meta.get('ui_generation',-1))!=self.open_requested or out is None:return self.base_show(raw,out,meta)
        value,revision=self.registry.applied[self.model['mode']]
        actual_revision=revision_of(meta)
        if actual_revision!=revision and not (value=='original' and actual_revision==0):return False
        previous=d._submit;captured=None
        async def submit(frame):
            nonlocal captured
            # All reads precede the official handoff; exactly one event copy.
            captured=np.array(frame,dtype=np.uint8,copy=True,order='C')
            result=await previous(frame)
            return result
        d._submit=submit
        try:shown=self.base_show(raw,out,meta)
        finally:
            if d._submit is submit:d._submit=previous
        with d.condition:
            if shown and captured is not None and self.open_requested==d.ui_generation:
                captured.setflags(write=False);ins=d.inspection;ins.clear_locked()
                self.captured=captured
                ins.kind='ratio';ins.generation=d.ui_generation;ins.source=captured;ins.source_rect=(0,0,1280,720)
                ins.meta=dict(self.model);ins.dirty=True;ins.opened+=1;d.pending=None
                self.open_requested=False;d._show=self.base_show;d.condition.notify_all()
        return shown
    def controls(self):
        m=self.model;result={'cancel':(846,637,128,56),'apply':(986,637,128,56),'reset':(1126,99,128,56)}
        if m.get('field') is not None:
            for i,key in enumerate(list('123456789.0')+['del']):result['key_'+key]=(846+(i%3)*140,280+(i//3)*60,126,52)
        else:
            for i,key in enumerate(list(PRESETS)+['custom']):result['preset_'+key]=(846+(i%3)*140,205+(i//3)*96,126,82)
        if m['draft']=='custom':
            fy=204 if m.get('field') is not None else 402
            result.update(width=(876,fy,96,48),height=(1022,fy,96,48))
        return result
    def target(self,p):return next((key for key,r in self.controls().items() if inside(p,r)),None)
    def touch(self,event,generation):
        d=self.display
        if d.inspection.kind!='ratio':
            if d.inspection.kind is not None:return None
            if not inside(event.get('press'),ENTRY):return None
            if self.state.page=='home' or self.state.ticket.phase!='running':return None
            if event['phase']=='press':return dict(target='ratio_open',reason='await_release')
            origin=event.get('press_outcome') or {}
            accepted=bool(origin.get('target')=='ratio_open' and origin.get('generation')==generation and inside(event.get('release'),ENTRY) and event.get('peak_motion',0)<=32 and self.open(generation))
            return dict(target='ratio_open',accepted=accepted,consumed=True,reason='ratio_opened' if accepted else 'ratio_unavailable')
        if event['phase']=='cancel':return dict(consumed=True,reason='ratio_contact_cancelled')
        key=self.target(event.get('press'))
        # Reversible draft edits respond to the initial contact; noisy later
        # DOWN coordinates cannot discard an intended light tap. A draft never
        # changes the live mapping. Apply/reset still require a valid release.
        if event['phase']=='press' and key and (key.startswith(('preset_','key_')) or
                key in ('width','height','cancel') or key=='reset' and self.model.get('field') is not None):
            self.action(key)
            return dict(target='ratio_'+key,accepted=True,consumed=True,
                reason='ratio_cancel_press' if key=='cancel' else 'ratio_draft_press')
        if event['phase']=='press':return dict(target='ratio_'+(key or 'background'),consumed=False,reason='await_release')
        origin=event.get('press_outcome') or {}
        accepted=bool(key and origin.get('generation')==generation and origin.get('target')=='ratio_'+key and self.target(event.get('release'))==key and event.get('peak_motion',0)<=32)
        if accepted:self.action(key)
        return dict(target='ratio_'+(key or 'background'),accepted=accepted,consumed=True,reason='ratio_control' if accepted else 'ratio_contact_rejected')
    def redraw(self):
        with self.display.condition:
            if self.display.inspection.kind=='ratio':
                self.display.inspection.meta=dict(self.model);self.display.inspection.dirty=True;self.display.condition.notify_all()
    def close_panel(self):
        d=self.display
        with d.condition:
            d.inspection.clear_locked();d.canvas_views.clear();d.layouts.clear()
            d.inspection_restore=bool(d.ui_view=='snapshot' and d.last_static_packet is not None)
            d.condition.notify_all()
        if self.pending is None:self.captured=None
    def action(self,key):
        m=self.model
        if key=='cancel':self.close_panel();return
        if key=='reset' and m.get('field') is not None:m['field']=None
        elif key=='reset':self.apply('original');return
        elif key=='apply':
            try:value=normalize(m['width']+':'+m['height'] if m['draft']=='custom' else m['draft'])
            except ValueError:m['error']='invalid'
            else:self.apply(value);return
        elif key.startswith('preset_'):m['draft']=key[7:];m['field']=None;m['error']=None
        elif key in ('width','height'):m['field']=key;m['replace_next']=True
        elif key.startswith('key_') and m.get('field') is not None:
            field=m['field'];char=key[4:];text=m[field]
            if char=='del':text=text[:-1]
            else:
                if m.pop('replace_next',False):text=''
                if len(text)<6 and (char!='.' or '.' not in text):text+=char
            m[field]=text;m['error']=None
        self.redraw()
    def apply(self,value):
        with self.display.condition:
            if self.pending is not None:return
            mode=self.mode()
            if value==self.registry.applied[mode][0]:self.close_panel();return
            revision=self.registry.request(mode,value)
            self.pending=dict(mode=mode,value=value,revision=revision,generation=self.display.ui_generation,began=time.perf_counter(),shown=False)
            self.previous_offer=self.display.offer;self.display.offer=self.pending_offer
            self.display._show=self.pending_show
            self.close_panel();self.header('busy')
            checkpoint('OUTPUT_RATIO_REQUEST',profile=mode,value=value,revision=revision,event_only=True)
        if self.state.page=='snapshot':
            with self.state.condition:self.snapshot_task=dict(self.pending);self.state.condition.notify_all()
    def restore_offer(self):
        if self.display.offer==self.pending_offer:self.display.offer=self.previous_offer
    def pending_offer(self,out,meta,raw=None,**kwargs):
        with self.display.condition:pending=self.pending;previous=self.previous_offer
        if pending is not None and int(meta.get('ui_generation',-1))==pending['generation']:
            expected=0 if pending['value']=='original' else pending['revision']
            if out is not None and revision_of(meta)==expected and meta.get('state') in ('CURRENT','MANUAL'):
                pending['candidate_ready']=True
            elif meta.get('plan_failure') and not pending.get('candidate_ready'):
                self.fail('mapping_proof_rejected')
        return previous(out,meta,raw,**kwargs)
    def fail(self,reason,reopen=True):
        pending=self.pending
        if pending is None:return
        self.registry.rollback(pending['mode']);self.pending=None;self.snapshot_task=None
        self.restore_offer()
        self.display._show=self.base_show;self.header(self.registry.applied[pending['mode']][0])
        checkpoint('OUTPUT_RATIO_REJECTED',revision=pending['revision'],reason=reason,previous_setting_retained=True)
        if reopen:self.open(self.display.ui_generation,error='failed')
    def pending_show(self,raw,out,meta):
        with self.display.condition:p=self.pending
        if p is None:return self.base_show(raw,out,meta)
        expected_revision=0 if p['value']=='original' else p['revision']
        matching=(int(meta.get('ui_generation',-1))==p['generation'] and out is not None and revision_of(meta)==expected_revision and meta.get('state') in ('CURRENT','MANUAL'))
        if not matching:
            if time.perf_counter()-p['began']>6.:self.fail('no_verified_new_output');return False
            if not p['shown'] and self.captured is not None and p['generation']==self.display.ui_generation:
                d=self.display;frame,canvas=d._acquire_canvas('ratio_pending',p['generation'])
                canvas[:]=self.captured;canvas[:72]=d.ui_assets.headers[d.ui_view]
                key=int(frame.physical_address);d.canvas_views[key]=('ratio_pending',p['generation']);d.layouts[key]=(None,None)
                d.loop.run_until_complete(d._submit(frame));p['shown']=True
                return True
            return False
        expected=dimensions(p['value'])
        actual=tuple(out.shape[1::-1])
        if actual!=(expected or actual) or p['value']=='original' and actual not in ((362,512),(512,362)):
            self.fail('output_size_mismatch');return False
        self.header(p['value'])
        try:shown=self.base_show(raw,out,meta)
        except BaseException:
            self.fail('submission_failed',reopen=False);raise
        if shown and matching and self.pending is p:
            with self.display.condition:
                if self.pending is not p:return shown
                if not self.registry.finish(p['mode'],p['revision']):
                    self.fail('setting_revision_changed',reopen=False);return shown
                self.pending=None;self.display._show=self.base_show
                self.restore_offer()
                if p['value']=='original':self.display.last_submitted_layout=int(meta.get('layout_generation',0))%SHIFT
                self.captured=None
            checkpoint('OUTPUT_RATIO_APPLIED',profile=p['mode'],value=p['value'],revision=p['revision'],native_size=list(out.shape[1::-1]),complete_submission=True)
        return shown
    def reprocess_snapshot(self,context,task):
        """Serviced only by the existing P1/app owner, while the still page waits."""
        from v73_ratio import make_orientation
        from v64_io import PlanWorkspace
        from v64_p1_backend import make_plan,ProofCache
        from v64_camera_hdmi import FrameJob
        context.check();d=self.display;fixed=context.ticket.fixed_input
        if fixed is None or task['generation']!=context.generation:
            self.fail('fixed_source_unavailable');return
        with d.condition:previous=dict(d.latest_meta)
        if previous.get('camera_sequence')!=fixed.sequence or len(previous.get('corners',()))!=4:
            self.fail('fixed_source_pair_mismatch');return
        workspace=None;job=None
        try:
            context.backend._assert_owner()
            orientation=make_orientation('auto_two',(362,512),2)
            proposal=orientation.propose(previous['corners'],fixed.image.shape,0,timestamp=float(fixed.ready))
            size=tuple(proposal.size or (362,512));workspace=PlanWorkspace()
            tiles,detail=make_plan(proposal.quad,fixed.image.shape,size,proof_cache=ProofCache(128),workspace=workspace)
            orient=orientation.commit(proposal);row=dict(previous)
            row.update(index=int(previous.get('index',1))+1,state='MANUAL' if self.mode()=='manual' else 'CURRENT',
                corners=tuple(map(tuple,proposal.quad.tolist())),output_size=size,tiles=len(tiles),
                layout_generation=orient['layout_generation'],orientation=orient.get('orientation'),
                capture_ready_at=fixed.ready,color_mode=fixed.color_mode,ui_generation=context.generation)
            job=FrameJob(row['index'],fixed.frame(),tuple(tiles),size,row['state'],row['corners'],fixed.color_mode,fixed.image,row,source_owned=True)
            context.check();image,owner=context.backend.execute(job);context.check()
            with d.condition:
                d.frozen_generation=None;d.snapshot_receipt=None
            row.update(owner)
            d.offer(image,row,fixed.image,raw_owned=True,output_reference=context.backend.output_reference(image))
            receipt=d.wait_snapshot(context.generation,row['index'],fixed.sequence,context.cancel)
            if receipt is None:context.check();raise RuntimeError('Ratio snapshot was not submitted')
            checkpoint('SNAPSHOT_RATIO_REMAP',generation=context.generation,revision=task['revision'],
                source_sequence=fixed.sequence,camera_opened=False,redetection=False,hardware_proof_preserved=True)
        except ValueError as exc:self.fail(str(exc))
        finally:
            if job is not None:job.release_source()
            if workspace is not None:workspace.close()
