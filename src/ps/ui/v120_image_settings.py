"""Left settings panel. Profile22's switch/first-frame lifecycle is inherited."""
from pathlib import Path
import hashlib,json
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v119_profile_ui import ProfileUI,inside,render_overlay as render_profile,_put,BAR,PANEL,APPLY
from v120_sharp import SharpControl
from v122_light import LightControl
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CLOSE=(404,140,48,48)
TABS={'resolution':(36,192,128,48),'sharp':(180,192,128,48),'light':(324,192,128,48)}
LIGHT_PRESETS=(0,20,40,60,80,100)
PROFILE_OPTIONS={'480P':(36,256,416,84),'600P':(36,352,416,84)}
PRESETS=(0,10,15,20,30,40)
SLIDER=(36,454,416,64)
SLIDER_START=60;SLIDER_END=428

def load_assets(assets,root):
    import cv2
    root=Path(root);spec=json.loads((root/'v120_settings_atlas.json').read_text(encoding='utf-8'))
    atlas=cv2.imread(str(root/'v120_settings_atlas.png'),cv2.IMREAD_COLOR)
    if atlas is None or list(atlas.shape)!=spec['shape']:raise ValueError('Incorrect settings atlas')
    assets.settings_parts={}
    for name,(x,y,w,h) in spec['parts'].items():
        if min(x,y)<0 or min(w,h)<=0 or x+w>atlas.shape[1] or y+h>atlas.shape[0]:raise ValueError('Settings atlas rectangle invalid')
        part=atlas[y:y+h,x:x+w];part.flags.writeable=False;assets.settings_parts[name]=part
    assets.settings_atlas=atlas
    assets.settings_footers={}

def render_overlay(canvas,view,assets):
    if not view or 'settings_tab' not in view:return render_profile(canvas,view,assets)
    parts=assets.settings_parts
    if view.get('busy') or view.get('timeout_notice'):render_profile(canvas,view,assets)
    _put(canvas,parts['bar_'+view['active']],BAR[0],BAR[1])
    # Compose this tiny status patch only when its VALUE changes. Healthy
    # frames do one cached copy, without rebuilding text or UI pixel arrays.
    key=(view['sharp_requested'],view['light_requested']);footer=assets.settings_footers.get(key)
    if footer is None:
        import numpy as np
        footer=np.empty((32,254,3),np.uint8);footer[:]=(18,13,8)
        _put(footer,parts['footer_label'],0,0)
        _put(footer,parts['footer_number_'+str(key[0])],52,0)
        _put(footer,parts['light_footer_label'],134,0)
        _put(footer,parts['light_number_'+str(key[1])],186,0)
        footer.flags.writeable=False
        if len(assets.settings_footers)>=8:assets.settings_footers.clear()
        assets.settings_footers[key]=footer
    _put(canvas,footer,340,652)
    if not view.get('open') or view.get('busy') or view.get('timeout_notice'):return
    tab=view['settings_tab'];_put(canvas,parts['panel_'+tab],PANEL[0],PANEL[1])
    if tab=='resolution':
        for name,rect in PROFILE_OPTIONS.items():
            selected=name==view['profile_candidate']
            _put(canvas,parts['option_'+name+('_on' if selected else '_off')],rect[0],rect[1])
        _put(canvas,parts['profile_apply_'+('same' if view['profile_candidate']==view['active'] else view['profile_candidate'])],APPLY[0],528)
        return
    effect='light' if tab=='light' else 'sharp';number='light_number_' if tab=='light' else 'number_'
    presets=LIGHT_PRESETS if tab=='light' else PRESETS;maximum=100 if tab=='light' else 40
    actual=view[effect+'_actual'];candidate=view[effect+'_candidate']
    _put(canvas,parts[number+str(actual)],104,246)
    _put(canvas,parts[number+str(candidate)],324,246)
    for i,val in enumerate(presets):
        _put(canvas,parts[('light_preset_' if tab=='light' else 'preset_')+str(val)+('_on' if val==candidate else '_off')],36+(i%3)*144,288+(i//3)*64)
    _put(canvas,parts[number+str(candidate)],384,414)
    import cv2
    canvas[474:483,60:429]=(107,89,62)
    x=SLIDER_START+int((SLIDER_END-SLIDER_START)*candidate/maximum+.5)
    if x>SLIDER_START:canvas[474:483,SLIDER_START:x]=(235,219,85)
    cv2.circle(canvas,(x,478),16,(235,219,85),-1)
    cv2.circle(canvas,(x,478),16,(245,237,229),2)

class ImageSettingsUI(ProfileUI):
    def __init__(self,state,display):
        self.sharp=getattr(display,'sharp_control',None) or SharpControl()
        self.light=getattr(display,'light_control',None) or LightControl()
        self.light_candidate=self.light.requested[1]
        self.tab='resolution';self.profile_candidate=getattr(state,'camera_profile',None) or '480P'
        self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.drag=None
        super().__init__(state,display)
    def view(self):
        with self.lock:
            v=super().view();request=self.sharp.requested;receipt=self.sharp.last_submitted
            current=receipt is not None and receipt['serial']==request[0] and receipt['tenths']==request[1]
            status=('off' if request[1]==0 else 'waiting') if not current else (
                'PL' if receipt['enabled'] else 'multi' if receipt['reason']=='multi_tile_bypass' else
                'shape' if receipt['reason']=='output_shape_bypass' else 'off')
            v.update(settings_tab=self.tab,profile_candidate=self.profile_candidate,sharp_candidate=self.sharp_candidate,
                sharp_requested=request[1],sharp_actual=receipt['tenths'] if receipt is not None and receipt['enabled'] else 0,
                sharp_status=status)
            light_receipt=self.light.last_submitted
            v.update(light_candidate=self.light_candidate,light_requested=self.light.requested[1],
                light_actual=light_receipt['percent'] if light_receipt is not None else 0)
            return v
    def show(self):
        with self.lock:
            self.profile_candidate=self.active;self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.drag=None
        super().show()
    def hide(self,reason='user'):
        with self.lock:self.drag=None;self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.profile_candidate=self.active
        super().hide(reason)
    def cancel(self,reason='page_left'):
        with self.lock:self.drag=None;self.sharp_candidate=self.sharp.requested[1];self.light_candidate=self.light.requested[1];self.profile_candidate=self.active
        super().cancel(reason)
    def _target(self,point):
        if inside(point,CLOSE):return 'close'
        for tab,rect in TABS.items():
            if inside(point,rect):return 'tab_'+tab
        if self.tab=='resolution' and inside(point,(36,528,416,64)):return 'apply'
        if self.tab=='resolution':
            for name,rect in PROFILE_OPTIONS.items():
                if inside(point,rect):return 'profile_'+name
        else:
            for i,val in enumerate(LIGHT_PRESETS if self.tab=='light' else PRESETS):
                if inside(point,(36+(i%3)*144,288+(i//3)*64,128,56)):return 'preset_'+str(val)
            if inside(point,SLIDER):return 'slider'
        return None
    def _slider(self,point):
        if point is None:return
        maximum=100 if self.tab=='light' else 40
        value=max(0,min(maximum,int((point[0]-SLIDER_START)*maximum/(SLIDER_END-SLIDER_START)+.5)))
        if self.tab=='light':self.light_candidate=value;self.light.request(value)
        else:self.sharp_candidate=value;self.sharp.request(value)
        self.revision+=1;self.publish()
        # Live HDMI frames render the small dirty UI; never submit a new full
        # frame or reconfigure a camera for each move event.
    def touch(self,event,generation):
        if self.state.page not in ('compare','rectified'):return None
        if self.busy:return super().touch(event,generation)
        phase=event.get('phase');press=event.get('press');origin=event.get('press_outcome') or {}
        with self.lock:
            if phase=='cancel':
                if self.drag is not None or self.open:
                    self.hide('contact_cancelled');return dict(target='settings_cancel',consumed=True)
                return None
            if self.drag is not None:
                valid=(self.drag==(generation,event.get('contact_id')) and origin.get('target')=='settings_slider'
                    and origin.get('generation')==generation and origin.get('page')==self.state.page)
                if not valid:self.drag=None;return dict(target='settings_slider',consumed=True,reason='stale_drag')
                if phase in ('move','release'):
                    self._slider(event.get('position') if phase=='move' else event.get('release'))
                    if phase=='release':self.drag=None;(self.light if self.tab=='light' else self.sharp).finish()
                    return dict(target='settings_slider',consumed=phase=='release',track_moves=True,accepted=True)
                return dict(target='settings_slider',track_moves=True,consumed=False)
            if not self.open:return super().touch(event,generation)
            # Return remains accessible; state.request() performs cancellation.
            if inside(press,(0,0,180,72)):return None
            if phase=='press':
                target=self._target(press)
                if target=='close' or not inside(press,PANEL):
                    self.hide('close' if target=='close' else 'outside')
                    return dict(target='settings_close',consumed=True,accepted=True)
                if target=='slider':
                    self.drag=(generation,event.get('contact_id'));self._slider(press)
                    return dict(target='settings_slider',consumed=False,track_moves=True,accepted=True)
                if target is None:return dict(target='settings_panel',consumed=True)
                return dict(target='settings_'+target,consumed=False,reason='await_release')
            target=self._target(press)
            valid=(phase=='release' and target is not None and origin.get('target')=='settings_'+target
                and origin.get('generation')==generation and origin.get('page')==self.state.page
                and self._target(event.get('release'))==target and event.get('peak_motion',0)<=32)
            if not valid:return dict(target='settings_release',consumed=True,accepted=False)
            if target.startswith('tab_'):self.tab=target[4:]
            elif target.startswith('profile_'):self.profile_candidate=target[8:]
            elif target.startswith('preset_'):
                value=int(target[7:])
                if self.tab=='light':self.light_candidate=value;self.light.request(value);self.light.finish()
                else:self.sharp_candidate=value;self.sharp.request(value);self.sharp.finish()
            elif target=='apply':return dict(target='settings_apply',consumed=True,accepted=self.apply())
            self.revision+=1;self.publish()
            return dict(target='settings_'+target,consumed=True,accepted=True)
    def apply(self):
        with self.lock:
            if self.busy:return False
            if self.tab!='resolution':
                return False
            if self.profile_candidate==self.active:return False
        return super().apply()
    def sharp_submitted(self,meta):
        sharp_receipt=meta.get('sharp_receipt');light_receipt=meta.get('light_receipt')
        changed=sharp_receipt is not None and self.sharp.submitted(sharp_receipt)
        changed=(light_receipt is not None and self.light.submitted(light_receipt)) or changed
        if changed:
            with self.lock:self.revision+=1;self.publish()
