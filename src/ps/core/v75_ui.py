"""Static HDMI pages and event-driven UI; the existing owners keep all device access."""
from pathlib import Path
from collections import deque
from dataclasses import dataclass,field
import hashlib,json,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID,verify_package
from run_logging import checkpoint,logged_run
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]

#   ⭐ 2026-10-29：相机输入档位表。**`tracking_max_dim` 必须跟着档位走** ——
#      原生 fused 灰度要求降采样"恰好 2 倍"（`(ow*2,oh*2)==(w,h)`）：
#      640x480 ⇒ 320，800x600 ⇒ 400。设错**不报错**，只是静默退回 Python 慢路径
#      （实测 11 ms → 63 ms），这是切档最容易踩的坑。
CAMERA_PROFILES={
    '480P':dict(width=640,height=480,fps=30,tracking_max_dim=320,label='480P · 640×480'),
    '600P':dict(width=800,height=600,fps=15,tracking_max_dim=400,label='600P · 800×600'),
}
#   P1 的两块 CMA 输入缓冲按**最大档位**分配一次，之后只改有效尺寸，
#   切档时不再申请/释放 DMA 内存（+1.38 MB CMA，赛前确认过够用）。
MAX_INPUT_SHAPE=(600,800)


def camera_profile_for(width,height):
    for name,p in CAMERA_PROFILES.items():
        if (int(width),int(height))==(p['width'],p['height']):return name
    raise ValueError('Unknown camera profile %dx%d'%(width,height))


class UIReturnRequested(Exception):
    """Cooperative return at a safe camera/owner boundary."""


class UIAssets:
    def __init__(self,mode):
        self.mode=tuple(mode);root=Path(__file__).resolve().parent
        spec=json.loads((root/'v75_ui_layout.json').read_text(encoding='utf-8'))
        if self.mode!=tuple(spec['mode']):raise ValueError('UI assets require the retained V74 HDMI1280x720 mode')
        self.home=cv2.imread(str(root/'v75_home.png'),cv2.IMREAD_COLOR)
        self.header=cv2.imread(str(root/'v75_header.png'),cv2.IMREAD_COLOR)
        if self.home is None or self.home.shape!=(self.mode[1],self.mode[0],3):raise ValueError('Invalid UI home asset')
        if self.header is None or self.header.shape!=(72,self.mode[0],3):raise ValueError('Invalid UI header asset')
        self.headers={'compare':self.header}
        badges=cv2.imread(str(root/'v79_status.png'),cv2.IMREAD_COLOR)
        if badges is None or badges.shape!=(160,512,3):raise ValueError('Invalid V79 cached status asset')
        badges.setflags(write=False)
        self.status_badges={state:badges[i*28:(i+1)*28,:320]
            for i,state in enumerate(('SEARCHING','CURRENT','HELD','LOST'))}
        self.acquire_hint=badges[112:160]
        self.clipped_hint=cv2.imread(str(root/'v81_clipped_hint.png'),cv2.IMREAD_COLOR)
        if self.clipped_hint is None or self.clipped_hint.shape!=(48,512,3):raise ValueError('Invalid current-frame placement hint')
        self.clipped_hint.setflags(write=False)
        setup=cv2.imread(str(root/'v79_setup_status.png'),cv2.IMREAD_COLOR)
        if setup is None or setup.shape!=(76,512,3):raise ValueError('Invalid native setup status asset')
        setup.setflags(write=False);self.status_badges['INITIALIZING']=setup[:28,:320]
        self.setup_hint=setup[28:]
        placement=cv2.imread(str(root/'v79_placement_help.png'),cv2.IMREAD_COLOR)
        controls=cv2.imread(str(root/'v79_placement_controls.png'),cv2.IMREAD_COLOR)
        if placement is None or placement.shape!=(172,512,3):raise ValueError('Invalid placement help asset')
        if controls is None or controls.shape!=(216,280,3):raise ValueError('Invalid placement controls asset')
        placement.setflags(write=False);controls.setflags(write=False)
        self.status_badges['PLACEMENT']=placement[:28,:320]
        self.placement_hints={name:placement[28+i*48:76+i*48]
            for i,name in enumerate(('placement','confirmed','preparing'))}
        self.placement_controls={name:controls[i*72:(i+1)*72]
            for i,name in enumerate(('confirm','confirmed','acquiring'))}
        refind=cv2.imread(str(root/'v80_refind.png'),cv2.IMREAD_COLOR)
        if refind is None or refind.shape!=(144,220,3):raise ValueError('Invalid refind button asset')
        refind.setflags(write=False);self.refind_controls={'ready':refind[:72],'preparing':refind[72:]}
        for view in ('rectified','snapshot'):
            image=cv2.imread(str(root/('v77_header_'+view+'.png')),cv2.IMREAD_COLOR)
            if image is None or image.shape!=self.header.shape:raise ValueError('Invalid '+view+' UI header')
            image.setflags(write=False);self.headers[view]=image
        self.snapshot_busy=cv2.imread(str(root/'v79_snapshot_busy.png'),cv2.IMREAD_COLOR)
        if self.snapshot_busy is None or self.snapshot_busy.shape!=self.header.shape:
            raise ValueError('Invalid snapshot busy header')
        self.snapshot_busy.setflags(write=False)
        self.return_patch=cv2.imread(str(root/'v77_return_pressed.png'),cv2.IMREAD_COLOR)
        if self.return_patch is None or self.return_patch.shape!=(72,180,3):raise ValueError('Invalid return feedback asset')
        self.return_patch.setflags(write=False);self.return_home=None
        self.buttons=tuple((entry['view'],tuple(entry['rect'])) for entry in spec['buttons'])
        self.layout_switch=tuple(spec['layout_switch_hit_rect'])
        self.refind=tuple(spec['refind_hit_rect'])
        self.snapshot_recapture=tuple(spec['snapshot_recapture_hit_rect'])
        self.back=tuple(spec['back_hit_rect']);self.home.setflags(write=False);self.header.setflags(write=False)
        self.error_home=None;self.home_pressed=None;self.home_pressed_cache=None;self.home_pressed_key=None
        from v82_assets import load_interaction_assets
        load_interaction_assets(self,root)
        self.ai=(280,0,100,72);self.manual=(180,0,100,72)
        hints=cv2.imread(str(root/'v97_3_target_hints.png'),cv2.IMREAD_COLOR)
        if hints is None or hints.shape!=(1616,1280,3):raise ValueError('Invalid cached target selection assets')
        hints.setflags(write=False)
        self.target_hints={(view,name):hints[(i*4+j)*40:(i*4+j+1)*40,:640]
            for i,view in enumerate(('compare','rectified')) for j,name in enumerate(('multiple','selecting','selected','miss'))}
        # One existing asset file: keep per-frame package admission's file list.
        for view in ('compare','rectified'):
            self.target_hints[(view,'fallback')]=self.target_hints[(view,'miss')]
            self.target_hints[(view,'not_covered')]=hints[1032:1072,:640]
            self.target_hints[(view,'unconfirmed')]=hints[1072:1112,:640]
            self.target_hints[(view,'current')]=hints[1576:1616,:640]
        progress=hints[320:960];self.switch_busy_header=hints[960:1032]
        self.switch_progress={name:progress[i*128:(i+1)*128] for i,name in enumerate(('prepare','edges','verify','display','miss'))}
        self.switch_progress['fallback']=self.switch_progress['miss']
        self.navigation_progress={name:hints[1112+i*32:1112+(i+1)*32]
            for i,name in enumerate(('prepare','search','verify','display','layout','home','calibration','zoom','album','snapshot','ready'))}
        self.entry_progress={name:hints[1464:1576,i*320:(i+1)*320]
            for i,name in enumerate(('prepare','search','verify','display'))}
        from v73_ratio_ui import load_assets
        load_assets(self,root)
        from v119_profile_ui import load_assets as load_profile_assets
        load_profile_assets(self,root)
        from v120_image_settings import load_assets as load_settings_assets
        load_settings_assets(self,root)
        from v123_live_ui import load_assets as load_live_assets
        load_live_assets(self,root)
        from v74_hold import load_assets as load_hold_assets
        load_hold_assets(self,root)
        from v97_album import MediaAssets
        self.media_assets=MediaAssets(root)
        checkpoint('UI_ASSETS_READY',mode=list(self.mode),resident_bytes=self.home.nbytes+sum(h.nbytes for h in self.headers.values())+self.return_patch.nbytes+self.snapshot_busy.nbytes+setup.nbytes+badges.nbytes+placement.nbytes+controls.nbytes+refind.nbytes+self.clipped_hint.nbytes,
            back_hit_rect=list(self.back),layout_switch_hit_rect=list(self.layout_switch),
            snapshot_recapture_hit_rect=list(self.snapshot_recapture),
            decode_scope='once before sessions',home_redraw='page changes only',header_redraw='per-buffer page changes only',
            ratio_asset_resident_bytes=self.ratio_asset_resident_bytes,ratio_render='inspection events; frozen background cached per buffer')
    @staticmethod
    def inside(point,rect):
        x,y,w,h=rect;return x<=point[0]<x+w and y<=point[1]<y+h
    def home_frame(self,error=False,feedback=False):
        if feedback:
            if self.return_home is None:
                self.return_home=self.home.copy();self.return_home[:72,:180]=self.return_patch
                self.return_home.setflags(write=False)
            return self.return_home
        if not error:
            rect=self.home_pressed
            if rect is None:return self.home
            if rect!=self.home_pressed_key:
                panel=self.home.copy();x,y,w,h=rect
                cv2.rectangle(panel,(x,y),(x+w-1,y+h-1),(230,245,90),3,cv2.LINE_AA)
                panel.setflags(write=False);self.home_pressed_cache=panel;self.home_pressed_key=rect
            return self.home_pressed_cache
        if self.error_home is None:
            self.error_home=self.home.copy()
            cv2.putText(self.error_home,'START FAILED - ADJUST SCENE AND RETRY; SEE run-result.log',
                (60,self.mode[1]-32),cv2.FONT_HERSHEY_SIMPLEX,.48,(210,225,255),1,cv2.LINE_AA)
            self.error_home.setflags(write=False)
        return self.error_home


@dataclass
class _PageRun:
    generation:int
    start_generation:int
    page:str
    cancel:object
    phase:str='preparing'
    placement:object=field(default_factory=threading.Event)
    placement_required:bool=True
    manual:bool=False
    ai:bool=False
    ai_mode_locked:bool=False
    fixed_input:object=None
    target_selection:object=None
    switch_from:object=None
    switch_requested_at:float=0.


class UIState:
    def __init__(self,assets,confirm_placement=False):
        self.assets=assets;self.condition=threading.Condition();self.page='home';self.generation=0
        self.cancel=threading.Event();self.stopping=False;self.error=None;self.display=None
        self.ticket=_PageRun(0,0,'home',self.cancel);self.layout_switches=0
        self.ai_service=None
        self.last_return=-float('inf');self.last_layout=-float('inf');self.debounce_s=.20
        self.last_recapture=-float('inf');self.recapture_requests=0
        self.confirm_placement=confirm_placement;self.last_placement=-float('inf')
        self.last_refind=-float('inf');self.refind_requests=0
        self.tap_contact=None;self.last_tap_target=-float('inf');self.target_request_serial=0;self.ratio=None;self.hold=None
        self.contact_counts=dict(accepted=0,rejected=0,returns=0,layout_switches=0,snapshot_recaptures=0,refind_requests=0)
    def bind(self,display):
        self.display=display;self.ratio=None;self.hold=None;self.profile=None
        if hasattr(display,'_show'):
            from v73_ratio_ui import RatioUI
            self.ratio=RatioUI(self,display)
            from v120_image_settings import ImageSettingsUI
            self.profile=ImageSettingsUI(self,display)
            from v74_hold import HoldController
            self.hold=HoldController(self,display)
    def _home_feedback(self,rect):
        self.assets.home_pressed=rect
        if self.display is not None and self.page=='home':
            # A page-owner redraw request only; no VDMA access in touch thread.
            self.display.request_view('home',self.generation)
    def request(self,page,error=False,return_feedback=False,recapture=False,refind=False,manual=False,restart=False,target_selection=None,ai=None,profile_switch=False):
        if page not in ('home','compare','rectified','snapshot'):raise ValueError('Unknown UI page')
        if ai and page not in ('compare','rectified'):return False
        with self.condition:
            if self.stopping:return False
            if refind and ai is None and not manual:
                ai=self.ticket.ai_mode_locked
            manual=bool(manual or ai)
            self.assets.home_pressed=None
            self.tap_contact=None
            if recapture:
                if page!='snapshot' or self.page!='snapshot' or self.display is None:return False
                if not self.display.snapshot_is_frozen(self.generation):return False
            if refind and (page!=self.page or page not in ('compare','rectified')):return False
            if page==self.page and not error and not recapture and not refind and not manual and not restart:return False
            fixed_input=(self.ticket.fixed_input if manual and page=='snapshot' and self.page=='snapshot'
                and self.display is not None and self.display.snapshot_is_frozen(self.generation) else None)
            previous_ticket=self.ticket
            previous=self.page;layout_only=previous in ('compare','rectified') and page in ('compare','rectified') and not error and not refind and not manual and not restart
            if self.hold is not None:self.hold.end('page_request')
            self.page=page;self.generation+=1;generation=self.generation
            profile_ui=getattr(self,'profile',None)
            if profile_ui is not None:
                if profile_switch:profile_ui.bind_request(generation)
                else:
                    self.pending_profile=None
                    profile_ui.cancel('page_or_session_request')
            if self.ratio is not None:self.ratio.cancel_for_request(layout_only,generation)
            if layout_only:
                # The session token survives; only its display generation changes.
                self.ticket.generation=generation;self.ticket.page=page;self.layout_switches+=1
            else:
                if self.ai_service is not None and hasattr(self.ai_service,'note_transition'):
                    self.ai_service.note_transition('ai' if ai else 'manual_selection' if manual else 'live')
                self.cancel.set();self.cancel=threading.Event()
                self.ticket=_PageRun(generation,generation,page,self.cancel,placement_required=self.confirm_placement,manual=bool(manual),ai=bool(ai),ai_mode_locked=bool(ai),fixed_input=fixed_input,target_selection=target_selection,
                    switch_from=previous_ticket.start_generation,
                    switch_requested_at=time.perf_counter())
                if recapture:
                    self.recapture_requests+=1;self.ticket.placement.set()
                if refind:self.refind_requests+=1
            # Serialize display requests with UI state changes. No device access here.
            if self.display is not None and error and hasattr(self.display,'cancel_ui_feedback'):
                self.display.cancel_ui_feedback()
            if profile_switch and self.display is not None and hasattr(self.display,'cancel_ui_feedback'):
                self.display.cancel_ui_feedback()
            if not profile_switch and self.display is not None and hasattr(self.display,'begin_ui_transition'):
                if target_selection is None and not error:
                    kind=('home' if page=='home' else 'layout' if layout_only else 'ai_calibration' if ai else 'calibration' if manual
                        else 'enter' if previous=='home' and page in ('compare','rectified')
                        else 'snapshot' if page=='snapshot' else 'prepare')
                    self.display.begin_ui_transition(page,generation,kind)
            if self.display is not None:self.display.request_view(page,generation,error=error,
                layout_only=layout_only,return_feedback=return_feedback,preserve_target=target_selection is not None)
            if self.ratio is not None:self.ratio.prepare_header_transition()
            if self.display is not None and target_selection is not None:self.display.set_target_notice('selecting',generation)
            session_generation=self.ticket.start_generation;self.condition.notify_all()
            if page=='home' and self.ai_service is not None:
                from v99_ai_ui import entered_home
                entered_home(self)
        checkpoint('UI_MODE_REQUEST',page=page,previous_page=previous,generation=generation,
            session_generation=session_generation,error_banner=bool(error),layout_only=layout_only,
            camera_restarted=False if layout_only or fixed_input is not None or page=='home' else None,
            camera_restart_decision='shared_camera_after_reader_retirement',cooperative_cancel=not layout_only,
            fixed_snapshot_source_reused=fixed_input is not None,
            return_feedback=bool(return_feedback),snapshot_recapture=bool(recapture),explicit_refind=bool(refind),manual_calibration=bool(manual))
        return True
    def queue_target_selection(self,selection):
        """One new intent, immediately; existing live camera/owner keep running."""
        with self.condition:
            if self.stopping or self.page!='compare':return False
            generation=self.generation;self.target_request_serial+=1
            selection=dict(selection,request_id='%s:%s'%(generation,self.target_request_serial),source_generation=generation)
            locked=bool(self.ticket.ai_mode_locked)
            if not self.display.arm_target_switch(generation,None,point=selection['point'],request_id=selection['request_id']):return False
            accepted=self.request(self.page,restart=True,target_selection=selection,ai=locked)
            if not accepted:self.display.target_switch.restore()
            return accepted
    def touch(self,event):
        result=self._touch(event)
        if (self.display is not None and hasattr(self.display,'touch_feedback')
                and not str(result.get('target','')).startswith('settings_')):
            self.display.touch_feedback(event,result,self.generation)
        return result
    def _touch(self,event):
        """Return acts on press. Home/layout controls require a same-page release."""
        with self.condition:
            page=self.page;generation=self.generation;phase=event['phase'];press=event.get('press')
            base=dict(page=page,generation=generation,accepted=False,target=None,consumed=False)
            self.assets.manual=(180,0,100 if page in ('compare','rectified') else 200,72)
            #   ⭐ 2026-10-29：相机输入档位弹窗优先级最高 —— 它打开时盖在画面上，
            #      点哪里都先归它。返回 None 表示不归它管（面板关着且没点按钮）。
            profile=getattr(self,'profile',None)
            if profile is not None:
                prof=profile.touch(event,generation)
                if prof is not None:
                    result=dict(base);result.update(prof)
                    if result.get('accepted'):self.contact_counts['accepted']+=1
                    elif phase!='press':self.contact_counts['rejected']+=1
                    return result
            if self.hold is not None:
                held=self.hold.touch(event,generation)
                if held is not None:
                    if phase=='press' and held.get('accepted'):self.contact_counts['accepted']+=1
                    return dict(base,**held)
            if phase=='cancel':
                self.tap_contact=None
                if self.display is not None:
                    self.display.inspection.cancel_point_contact(event.get('contact_id'))
                    with self.display.condition:self.display.inspection.reading.cancel_locked(event.get('contact_id'))
                self._home_feedback(None)
                return dict(base,reason='contact_cancelled',consumed=True)
            if self.stopping:return dict(base,reason='application_stopping')
            if press is None:return dict(base,reason='missing_press_coordinates')
            if phase=='move':
                origin=event.get('press_outcome') or {}
                if (origin.get('generation')==generation and origin.get('page')==page
                        and origin.get('target')=='inspect_point' and self.display is not None):
                    accepted,reason=self.display.inspection.move_point_contact(event,generation)
                    return dict(base,target='inspect_point',accepted=accepted,reason=reason)
                if (origin.get('generation')==generation and origin.get('page')==page
                        and origin.get('target') in ('inspect_focus','inspect_pan') and self.display is not None):
                    accepted,reason=self.display.inspection.reading.move(event,generation)
                    return dict(base,target=origin['target'],accepted=accepted,reason=reason)
                return dict(base,reason='move_not_requested')
            back=page!='home' and self.assets.inside(press,self.assets.back)
            if self.ratio is not None and self.ratio.pending is not None and not back:
                return dict(base,target='ratio_apply_busy',consumed=True,reason='ratio_apply_in_progress_return_available')
            if not back and self.ratio is not None:
                ratio_result=self.ratio.touch(event,generation)
                if ratio_result is not None:
                    result=dict(base);result.update(ratio_result)
                    if result.get('accepted'):self.contact_counts['accepted']+=1
                    elif phase!='press':self.contact_counts['rejected']+=1
                    return result
            if page!='home' and self.display is not None and self.display.media is not None:
                media=self.display.media.touch(event,generation)
                if media is not None:
                    result=dict(base);result.update(media)
                    if media.get('accepted'):self.contact_counts['accepted']+=1
                    elif phase!='press':self.contact_counts['rejected']+=1
                    return result
            if phase=='press':
                self.tap_contact=None
                if self.display is not None:
                    with self.display.condition:self.display.inspection.reading.cancel_locked()
                if back:
                    now=time.perf_counter()
                    if now-self.last_return<self.debounce_s:
                        self.contact_counts['rejected']+=1
                        return dict(base,target='home',consumed=True,reason='return_debounce')
                    self.last_return=now
                    if self.request('home',return_feedback=True):
                        self.contact_counts['accepted']+=1;self.contact_counts['returns']+=1
                        return dict(base,accepted=True,target='home',consumed=True,reason='return_on_press',request_generation=self.generation)
                target=None
                if page!='home' and self.display is not None:
                    if (page in ('compare','rectified') and self.display.inspection.kind is None
                            and self.assets.inside(press,self.assets.ai)):
                        return dict(base,target='ai_calibration',reason='await_release')
                    # Fixed-image manual calibration remains a page control,
                    # including while a snapshot loupe overlay is displayed.
                    if self.assets.inside(press,self.assets.manual) and self.display.inspection.kind!='calibration':
                        return dict(base,target='manual_calibration',reason='await_release')
                    target=self.display.inspection.target(press,generation)
                    if target=='inspect_point':
                        started,reason,token=self.display.inspection.begin_point_contact(press,generation,event.get('contact_id'))
                        return dict(base,target=target,reason=reason,track_moves=started,inspection_token=token)
                    if target in ('inspect_focus','inspect_pan'):
                        started,reason,token=self.display.inspection.reading.begin(press,generation,event.get('contact_id'))
                        return dict(base,target=target,reason=reason,track_moves=started,inspection_token=token)
                    if target is not None:return dict(base,target=target,reason='await_inspection_release',
                        inspection_token=self.display.inspection.token)
                    if self.assets.inside(press,self.assets.manual):return dict(base,target='manual_calibration',reason='await_release')
                    if self.assets.inside(press,self.assets.zoom):return dict(base,target='reading_zoom',reason='await_release')
                if page=='home':
                    target=next((view for view,rect in self.assets.buttons if self.assets.inside(press,rect)),None)
                    if target is not None:
                        self._home_feedback(next(rect for view,rect in self.assets.buttons if view==target))
                elif page in ('compare','rectified') and self.assets.inside(press,self.assets.refind):
                    if self.ticket.phase=='preparing':
                        self.contact_counts['rejected']+=1
                        return dict(base,target='refind',consumed=True,reason='library_preparing_auto_search_queued')
                    target='refind'
                elif self.ticket.phase!='running' and self.assets.inside(press,self.assets.layout_switch):
                    self.contact_counts['rejected']+=1
                    return dict(base,target='startup_busy',consumed=True,reason='automatic_startup_in_progress')
                elif page in ('compare','rectified') and self.assets.inside(press,self.assets.layout_switch):target='layout_toggle'
                elif page=='snapshot' and self.assets.inside(press,self.assets.snapshot_recapture):
                    if self.display is None or not self.display.snapshot_is_frozen(generation):
                        self.contact_counts['rejected']+=1
                        return dict(base,target='snapshot_recapture',consumed=True,reason='snapshot_still_capturing')
                    target='snapshot_recapture'
                from v121_selection import can_select
                if (target is None and page=='compare' and can_select(self.ticket.manual,self.ticket.ai) and self.ticket.phase=='running'
                        and self.display is not None):
                    selection=self.display.tap_target_source(press,generation)
                    if selection is not None:
                        self.tap_contact=(event.get('contact_id'),selection)
                        return dict(base,target='tap_target',reason='await_target_release')
                return dict(base,target=target,reason='await_release' if target else 'outside_controls')
            origin=event.get('press_outcome') or {}
            if origin.get('generation')!=generation or origin.get('page')!=page:
                result=dict(base,reason='page_changed_during_contact')
            elif origin.get('target')=='inspect_point' and self.display is not None:
                accepted,reason=self.display.inspection.finish_point_contact(event,generation)
                self.contact_counts['accepted' if accepted else 'rejected']+=1
                return dict(base,target='inspect_point',accepted=accepted,reason=reason)
            elif origin.get('target') in ('inspect_focus','inspect_pan') and self.display is not None:
                accepted,reason=self.display.inspection.reading.finish(event,generation)
                self.contact_counts['accepted' if accepted else 'rejected']+=1
                return dict(base,target=origin['target'],accepted=accepted,reason=reason)
            elif event.get('release') is None:result=dict(base,reason='missing_release_coordinates')
            elif event.get('peak_motion',0.)>32:result=dict(base,target=origin.get('target'),reason='drag_over_32px')
            else:
                release=event['release'];target=None;reason='outside_controls'
                origin_target=origin.get('target') or ''
                if origin_target=='tap_target':
                    contact=self.tap_contact;self.tap_contact=None;target=origin_target
                    reason='target_contact_expired'
                    if contact is not None and contact[0]==event.get('contact_id') and time.perf_counter()-contact[1]['pressed_at']<=.75:
                        if (hasattr(self.display,'current_target_tap')
                                and self.display.current_target_tap(contact[1],release,generation)):
                            reason='current_target_release'
                        elif time.perf_counter()-self.last_tap_target<.5:reason='target_debounce' 
                        elif self.display.inspection.kind is None and self.queue_target_selection(contact[1]):
                            self.last_tap_target=time.perf_counter();reason='tap_target_release'
                            checkpoint('UI_TAP_TARGET',point=list(contact[1]['point']),source_sequence=contact[1]['sequence'],
                                source_rect=contact[1]['source_rect'],normalized_point=contact[1]['normalized_point'],
                                selection_request_id=self.ticket.target_selection['request_id'],
                                source_generation=generation,new_generation=self.generation,freeze_before_restart=False,live_preview=True,serialized_owner_restart=True,
                                original_current_proof_required=True,persistent_lock=False)
                elif origin_target.startswith('inspect_'):
                    target=origin_target
                    accepted,reason=self.display.inspection.release(target,press,release,generation,origin.get('inspection_token'))
                    if accepted and target=='inspect_auto':
                        self.request(page,restart=page=='snapshot',refind=page in ('compare','rectified'),ai=False)
                    elif accepted and target=='inspect_manual':
                        self.request(page,manual=True)
                    result=dict(base,target=target,accepted=accepted,reason=reason,request_generation=self.generation if accepted else None)
                    self.contact_counts['accepted' if accepted else 'rejected']+=1
                    return result
                elif origin_target=='ai_calibration':
                    target=origin_target;reason='release_outside_target'
                    if page in ('compare','rectified') and self.assets.inside(release,self.assets.ai):
                        reason='ai_calibration_release' if self.request(page,ai=True) else 'ai_request_ignored'
                elif origin_target=='manual_calibration':
                    target=origin_target;reason='release_outside_target'
                    if self.assets.inside(release,self.assets.manual):
                        reason='manual_calibration_release' if self.request(page,manual=True) else 'manual_request_ignored'
                elif origin_target=='reading_zoom':
                    target=origin_target;reason='release_outside_target'
                    if self.assets.inside(release,self.assets.zoom):
                        reason='reading_zoom_release' if self.display.inspection.request_zoom(generation) else 'reading_requires_current_result'
                elif page=='home':
                    for view,rect in self.assets.buttons:
                        if self.assets.inside(press,rect):
                            target=view;reason='release_outside_target'
                            if self.assets.inside(release,rect):reason='home_release';self.request(view)
                            break
                elif origin.get('target')=='refind':
                    target='refind';reason='release_outside_target'
                    if self.assets.inside(release,self.assets.refind):
                        now=time.perf_counter()
                        if now-self.last_refind<.5:reason='refind_debounce'
                        elif self.ticket.phase=='preparing':reason='library_preparing_auto_search_queued'
                        elif self.request(page,refind=True):
                            self.last_refind=now;reason='refind_release';self.contact_counts['refind_requests']+=1
                            checkpoint('UI_REFIND_REQUEST',previous_generation=generation,new_generation=self.generation,
                                stale_corners_discarded=True,serialized_owner_restart=True,validation_bypassed=False)
                elif self.ticket.phase!='running' and self.assets.inside(press,self.assets.layout_switch):
                    target='startup_busy';reason='startup_already_confirmed_or_acquiring'
                elif page in ('compare','rectified') and self.assets.inside(press,self.assets.layout_switch):
                    target='rectified' if page=='compare' else 'compare';reason='release_outside_target'
                    if self.assets.inside(release,self.assets.layout_switch):
                        now=time.perf_counter()
                        if now-self.last_layout<self.debounce_s:reason='layout_debounce'
                        else:
                            self.last_layout=now;reason='layout_release';self.request(target)
                elif page=='snapshot' and self.assets.inside(press,self.assets.snapshot_recapture):
                    target='snapshot_recapture';reason='release_outside_target'
                    if self.assets.inside(release,self.assets.snapshot_recapture):
                        now=time.perf_counter()
                        if now-self.last_recapture<self.debounce_s:reason='snapshot_recapture_debounce'
                        elif self.request('snapshot',recapture=True):
                            self.last_recapture=now;reason='snapshot_recapture_release'
                        else:reason='snapshot_still_capturing'
                accepted=reason in ('home_release','layout_release','snapshot_recapture_release','refind_release','manual_calibration_release','ai_calibration_release','reading_zoom_release','tap_target_release','current_target_release')
                result=dict(base,target=target,accepted=accepted,reason=reason,
                    request_generation=self.generation if accepted else None)
            self.contact_counts['accepted' if result['accepted'] else 'rejected']+=1
            self.tap_contact=None
            if page=='home' and not result['accepted']:self._home_feedback(None)
            if result['accepted'] and result['reason']=='layout_release':self.contact_counts['layout_switches']+=1
            if result['accepted'] and result['reason']=='snapshot_recapture_release':self.contact_counts['snapshot_recaptures']+=1
            return result
    def input_error(self,exc):
        with self.condition:
            if self.hold is not None:self.hold.end('touch_error')
            self.error=exc;self.stopping=True;self.cancel.set();self.condition.notify_all()
        checkpoint('UI_TOUCH_FAILED',durable=True,exception_type=type(exc).__name__,exception=str(exc))
    def next_session(self,deadline):
        while True:
            hot=getattr(self,'camera_handoff',None)
            if hot is not None:hot.close_unused()
            with self.condition:
                if self.error is not None:raise self.error
                if self.stopping or time.perf_counter()>=deadline:return None
                if self.display is not None and self.display.error is not None:raise self.display.error
                if self.page!='home':return self.page,self.ticket
                left=deadline-time.perf_counter();idle=hot.idle_remaining() if hot is not None else None
                self.condition.wait(min(left,1.,idle) if idle is not None else min(left,1.))
    def wait_fixed_page(self,generation,deadline,context=None):
        while True:
            hot=getattr(self,'camera_handoff',None)
            if hot is not None:hot.close_unused()
            task=None
            with self.condition:
                if self.stopping or self.generation!=generation or self.page!='snapshot':return
                if self.error is not None:raise self.error
                if self.display is not None and self.display.error is not None:raise self.display.error
                remaining=deadline-time.perf_counter()
                if remaining<=0:return
                if context is not None and self.ratio is not None and self.ratio.snapshot_task is not None:
                    task=self.ratio.snapshot_task;self.ratio.snapshot_task=None
                else:self.condition.wait(min(remaining,1.))
            if task is not None:self.ratio.reprocess_snapshot(context,task)
    def finish(self,ticket,error=False):
        with self.condition:
            ticket.fixed_input=None
            if self.ticket is ticket:self.request('home',error=error)
    def stop(self):
        with self.condition:
            profile=getattr(self,'profile',None)
            if profile is not None:profile.cancel('application_stop')
            if self.hold is not None:self.hold.end('application_stop')
            self.stopping=True;self.cancel.set();self.ticket.fixed_input=None;self.condition.notify_all()


@dataclass
class UISession:
    backend:object
    display:object
    ticket:object
    native_setup:object
    hot:object=None
    @property
    def cancel(self):return self.ticket.cancel
    @property
    def generation(self):return self.ticket.generation
    def check(self):
        if self.cancel.is_set():raise UIReturnRequested()
    def set_phase(self,phase):
        self.check()
        if phase not in ('preparing','placement','acquiring','running'):raise ValueError('Unknown startup phase')
        self.ticket.phase=phase
        self.display.set_target_phase({'preparing':'prepare','placement':'prepare','acquiring':'edges','running':'display'}[phase],self.generation)
        checkpoint('UI_SESSION_PHASE',generation=self.generation,phase=phase,
            placement_confirmed=self.ticket.placement.is_set())


from v86_policy import policy_run

@logged_run
@policy_run
def run_ui(device='/dev/video0',touch_device='auto',bitfile='system.bit',max_duration_s=7200.,
           max_frames=0,warmup_frames=5,swap_xy=False,invert_x=False,invert_y=False,
           width=640,height=480,fps=30,output_size=(362,512),hdmi_mode=(1280,720),
           hdmi_max_fps=30.,timeout_s=3.,snapshot_timeout_s=20.,confirm_placement=False,
           capture_dir='/home/xilinx/captures',capture_jpeg_quality=90,**camera_options):
    """Cached home, press-action return, and one processing session for both live layouts."""
    if not 1<=float(max_duration_s)<=7200:raise ValueError('UI duration must be1..7200 seconds')
    if tuple(hdmi_mode)!=(1280,720):raise ValueError('V77 preserves HDMI1280x720')
    #   ⭐ 2026-10-27：允许 800x600（600P）。显示层会把超过面板的源等比缩到面板内
    #      （v64_hdmi_display.HdmiLatest._fit_shape），点选坐标由
    #      v82_interaction 的 _to_source() 按 source_shape 换算回原图。
    if (int(width),int(height)) not in ((640,480),(800,600)):
        raise ValueError('V77 UI camera mode must be 640x480 or 800x600, got %dx%d'%(width,height))
    if isinstance(max_frames,bool) or not isinstance(max_frames,int) or max_frames<0:raise ValueError('Invalid max_frames')
    if isinstance(warmup_frames,bool) or not isinstance(warmup_frames,int) or warmup_frames<0 or (max_frames and max_frames<=warmup_frames):raise ValueError('Invalid warmup_frames')
    if any(k.startswith('_') for k in camera_options):raise ValueError('Private UI session arguments are internal')
    if not 2<=float(snapshot_timeout_s)<=60:raise ValueError('Snapshot capture timeout must be2..60 seconds')
    if not isinstance(confirm_placement,bool):raise ValueError('confirm_placement must be bool')
    if confirm_placement:checkpoint('LEGACY_PLACEMENT_OPTION_IGNORED',automatic_admission=True)
    confirm_placement=False
    root=Path(__file__).resolve().parent;hardware=(root/bitfile).resolve();verify_package(str(hardware))
    cv2.setNumThreads(1)
    from v64_p1_backend import P1Backend
    from v64_hdmi_display import HdmiLatest
    from v75_touch import TouchInput
    from v79_setup import NativeSetup
    import v64_camera_hdmi as camera_module
    if camera_module._POISONED:raise RuntimeError('Previous session cleanup unsafe; restart board as run-result.log instructs')
    profile=camera_profile_for(width,height)
    #   档位表是唯一权威：即使 notebook 里 tracking_max_dim 写错，也按档位纠正。
    camera_options['tracking_max_dim']=CAMERA_PROFILES[profile]['tracking_max_dim']
    assets=UIAssets(hdmi_mode);state=UIState(assets,confirm_placement)
    native_setup=NativeSetup()
    from v75_hotswitch import CameraHandoff
    hot=CameraHandoff(state);state.camera_handoff=hot
    backend=display=touch=None;failure=None;cleanup=[];interrupted=False;ai_service=None
    sessions=deque(maxlen=4);session_count=0;frames=current=held=lost=0;fixed_captures=0;manual_corrections=0
    began=time.perf_counter();deadline=began+float(max_duration_s)
    try:
        # Validate touch before downloading hardware. Its worker is blocked in select when idle.
        touch=TouchInput(touch_device,hdmi_mode,state.touch,state.input_error,swap_xy,invert_x,invert_y)
        #   ⚠️ 输入 CMA 按**最大档位**分配（`P1Backend.input_shape` 只用于分配，
        #      实际尺寸来自每帧相机图像），这样切档时不用重新申请 DMA 内存。
        backend=P1Backend(str(hardware),MAX_INPUT_SHAPE,output_size,timeout_s)
        #   ⚠️⚠️ `P1Backend.input_shape` 在构造里**只用来分配两块 CMA**（`h*w*4`），
        #      分配完就没有运行期用途；但 `run_camera_hdmi:494` 和 `v76_snapshot:47`
        #      都会拿它和**当前档位**比对：
        #          `if backend.input_shape!=(height,width): raise ValueError('Borrowed UI resources do not match')`
        #      2026-10-29 现场：分配用最大档位后没改回来 ⇒ 切到 480P 后每个会话都抛
        #      `Borrowed UI resources do not match camera options`（25 次），
        #      表现成"闪退到首页之后点不进去"。
        #      ⇒ **分配用容量，比对用有效尺寸**，两个含义分开存。
        backend.capacity_shape=MAX_INPUT_SHAPE
        backend.input_shape=(height,width)
        try:
            display=HdmiLatest(backend.overlay,hdmi_mode,output_size,timeout_s,
                hold_max_age_s=camera_options.get('hold_max_age_s',1.5),
                input_shape=(height,width),max_fps=hdmi_max_fps,ui_assets=assets,
                capture_dir=capture_dir,capture_jpeg_quality=capture_jpeg_quality)
        except BaseException as exc:
            backend.failed=not bool(getattr(exc,'hdmi_shutdown_safe',False));raise
        #   ⚠️ `camera_profile` 必须在 `bind()` **之前**赋值 —— `bind()` 里会创建
        #      `ProfileUI`，它在 `__init__` 就按当前档位初始化按钮文字。
        #      2026-10-29 现场：赋值在 bind 之后 ⇒ 实际跑 800x600，按钮却写"480P"。
        display.sharp_control=backend.sharp_control
        display.light_control=backend.light_control
        state.camera_profile=profile;state.pending_profile=None
        state.bind(display)
        # ---- 相机输入档位：请求 → 结束本会话 → 下次会话用新档位重开（自动重新定位）----
        def request_camera_profile(name):
            """由 `v119_profile_ui.ProfileUI` 调用。只登记请求并结束当前会话，
            真正的换档在会话循环里做（相机必须已经关掉）。"""
            if name not in CAMERA_PROFILES or name==state.camera_profile:return False
            with state.condition:
                if state.stopping or state.page not in ('compare','rectified'):return False
                if state.ticket.phase!='running':return False
                state.pending_profile=name
                accepted=bool(state.request(state.page,refind=True,profile_switch=True))
                if not accepted:state.pending_profile=None
            checkpoint('CAMERA_PROFILE_SWITCH_REQUESTED',from_profile=state.camera_profile,
                to_profile=name,reason='new_input_session; target re-localized automatically')
            return accepted
        state.request_camera_profile=request_camera_profile
        # Preserve an exceptionally early touch that arrived during overlay setup.
        if state.generation:display.request_view(state.page,state.generation)
        checkpoint('UI_READY',durable=True,hdmi_mode=list(hdmi_mode),home_buttons=[b[0] for b in assets.buttons],
            return_location='top_left_press',back_hit_rect=list(assets.back),return_debounce_s=state.debounce_s,
            live_layout_switch='top_right_release',live_layout_reuses_camera_tracker_H=True,
            placement_confirmation=confirm_placement,native_setup_lifetime='whole application; survives home return',
            manual_calibration='explicit frozen four points; separate manual authority',
            reading='event-only frozen2x/4x; processing continues',placement_guidance_enabled=False,
            hdmi_scale=False,backend_reloaded_between_pages=False,
            background='static cached BGR; never decoded in a camera frame',touch=touch.detail)
        # HDMI has already initialized its IO helper; CPU-only tracker work can
        # now warm while home is idle. Returning home never restarts compilation.
        native_setup.start(trigger='home_ready')
        from v99_ai_ui import attach as attach_ai
        ai_service=attach_ai(state,native_setup)
        while True:
            hot.close_unused()
            choice=state.next_session(deadline)
            if choice is None:break
            page,ticket=choice
            if ticket.cancel.is_set():continue
            #   ⭐ 2026-10-29：切档在这里落地 —— 旧会话已经结束、相机已关，
            #      现在换相机尺寸 / 帧率 / tracking_max_dim，并让显示层重建 raw_pool。
            pending=getattr(state,'pending_profile',None)
            if pending and pending!=profile:
                p=CAMERA_PROFILES[pending]
                try:
                    from v75_hotswitch import camera_key
                    hot.prepare_profile(ticket,camera_key(device,p['width'],p['height'],p['fps'],camera_options.get('color_mode')))
                    display.rescale_input((p['height'],p['width']))
                except BaseException as exc:
                    previous=CAMERA_PROFILES[profile]
                    from v75_hotswitch import camera_key
                    hot.prepare_profile(ticket,camera_key(device,previous['width'],previous['height'],previous['fps'],camera_options.get('color_mode')))
                    checkpoint('UI_CAMERA_PROFILE_FAILED',requested=pending,active_profile=profile,
                        exception_type=type(exc).__name__,exception=str(exc)[:400],
                        previous_setting_retained=True)
                    with state.condition:state.pending_profile=None
                    if getattr(state,'profile',None) is not None:state.profile.failed('rescale_rejected')
                else:
                    profile=pending;width=p['width'];height=p['height'];fps=p['fps']
                    camera_options['tracking_max_dim']=p['tracking_max_dim']
                    #   有效尺寸跟着档位走（CMA 缓冲仍然是按容量分配的，不重分配）
                    backend.input_shape=(height,width)
                    with state.condition:
                        state.camera_profile=profile;state.pending_profile=None
                    if getattr(state,'profile',None) is not None:state.profile.applied(profile,ticket.generation)
                    checkpoint('UI_CAMERA_PROFILE_APPLIED',active_profile=profile,
                        width=width,height=height,fps=fps,
                        tracking_max_dim=p['tracking_max_dim'],
                        scope='new input session; target re-localized from scratch')
            generation=ticket.start_generation
            if ticket.cancel.is_set():continue
            ai_service.prepare_live(mode='ai' if ticket.ai else 'manual_selection' if ticket.manual else 'live')
            context=UISession(backend,display,ticket,native_setup,hot)
            if backend.active or backend.failed or backend.closed:raise RuntimeError('P1 backend is unsafe to reuse')
            # Old lookahead jobs had their leases drained before the prior session returned.
            # Indices restart at1; never accept an old (index,slot) prefill receipt.
            backend.packed.clear()
            checkpoint('UI_SESSION_BEGIN',generation=generation,view=page,tracking='fresh initial admission')
            ratio_scope=state.ratio.registry.scope('manual' if ticket.manual else 'auto')
            ratio_scope.__enter__()
            state.ratio.header(state.ratio.registry.applied['manual' if ticket.manual else 'auto'][0])
            try:
                if ticket.manual:
                    from v82_manual import run_manual
                    runner=run_manual
                    if ticket.ai:
                        from v100_ai_tracking import run_ai
                        runner=run_ai
                    result=runner(context,device=device,width=width,height=height,fps=fps,
                        output_size=output_size,max_frames=max_frames,warmup_frames=warmup_frames,
                        deadline=deadline,options=camera_options)
                elif page=='snapshot':
                    from v76_snapshot import capture_one
                    result=capture_one(context,device=device,width=width,height=height,fps=fps,
                        output_size=output_size,capture_timeout_s=min(float(snapshot_timeout_s),max(.1,deadline-time.perf_counter())),
                        options=camera_options,app_deadline=deadline)
                else:
                    result=camera_module.run_camera_hdmi.__wrapped__(device=device,bitfile=bitfile,
                        max_frames=max_frames,warmup_frames=warmup_frames,width=width,height=height,fps=fps,
                        output_size=output_size,hdmi_mode=hdmi_mode,hdmi_max_fps=hdmi_max_fps,timeout_s=timeout_s,
                        max_duration_s=max(1.,deadline-time.perf_counter()),_ui_context=context,**camera_options)
                session_count+=1
                frames+=result['frames'];current+=result['current'];held+=result['held'];lost+=result['lost']
                manual_corrections+=result.get('manual_corrections',0)
                # Retain four compact session summaries, not four512-row diagnostic trees.
                summary={k:result[k] for k in ('status','frames','current','held','lost','current_correction_fps',
                    'delivered_fps','hdmi_current_fps','hdmi_submit_fps','formal_elapsed_s','timing','hdmi_timing')}
                summary.update(view=page,view_at_end=ticket.page,generation=generation,
                    final_display_generation=ticket.generation);sessions.append(summary)
                summary['manual_corrections']=result.get('manual_corrections',0)
                summary['manual_fps']=result.get('manual_fps',0.)
                if page=='snapshot':summary['snapshot']=result.get('snapshot')
                checkpoint('UI_SESSION_END',**summary)
                if result.get('user_interrupted'):
                    interrupted=True;break
                if page=='snapshot' and result.get('fixed_frame',False):
                    fixed_captures+=1;state.wait_fixed_page(ticket.generation,deadline,context)
                state.finish(ticket)
            except UIReturnRequested:
                state.finish(ticket)
            except Exception as exc:
                if backend.failed or backend.active or camera_module._POISONED or display.error is not None:raise
                checkpoint('UI_SESSION_START_FAILED',durable=True,generation=generation,
                    exception_type=type(exc).__name__,exception=str(exc),traceback=__import__('traceback').format_exc(),safe_to_retry=True)
                state.finish(ticket,error=True)
            finally:ratio_scope.__exit__(None,None,None)
    except KeyboardInterrupt:
        interrupted=True;checkpoint('UI_USER_STOP',durable=True)
    except BaseException as exc:failure=exc
    finally:
        state.stop()
        try:hot.close()
        except BaseException as exc:
            cleanup.append(('hot_camera',repr(exc)));_RETAINED.append(hot)
            camera_module._POISONED=True
        try:native_setup.close()
        except BaseException as exc:
            cleanup.append(('native_setup',repr(exc)));_RETAINED.append(native_setup)
        if ai_service is not None:
            try:ai_service.close()
            except BaseException as exc:cleanup.append(('ai_service',repr(exc)));_RETAINED.append(ai_service)
        if touch is not None:
            try:touch.close()
            except BaseException as exc:cleanup.append(('touch',repr(exc)))
        # A failed PS/camera cleanup may still refer to overlay/CMA: retain everything.
        unsafe=camera_module._POISONED
        display_stopped=display is None
        if display is not None:
            try:display.close();display_stopped=True
            except BaseException as exc:
                display_stopped=bool(display.shutdown_safe);cleanup.append(('hdmi',repr(exc)))
        if backend is not None and display_stopped and not unsafe:
            try:backend.close()
            except BaseException as exc:cleanup.append(('backend',repr(exc)))
        if unsafe or not display_stopped or (backend is not None and not backend.closed):
            _RETAINED.append((backend,display,state,touch))
            camera_module._POISONED=True
            camera_module._POISON_REASON=list(camera_module._POISON_REASON)+cleanup+[('ui','resources retained')]
        if cleanup:checkpoint('UI_CLEANUP_FAILED',durable=True,errors=cleanup)
    if failure is not None:raise failure
    if cleanup:raise RuntimeError('UI cleanup incomplete: '+str(cleanup))
    return dict(release_id=RELEASE_ID,status='stopped' if interrupted else 'completed',
        sessions=session_count,frames=frames,current=current,held=held,lost=lost,
        fixed_captures=fixed_captures,snapshot_images_saved=0,snapshot_recapture_requests=state.recapture_requests,
        manual_corrections=manual_corrections,automatic_CURRENT_includes_manual=False,
        explicit_refind_requests=state.refind_requests,
        live_layout_switches=state.layout_switches,touch_contacts=dict(state.contact_counts),
        session_summaries=list(sessions),ui_wall_s=time.perf_counter()-began,
        fps_scope='each camera session excludes idle home time; do not divide by UI wall time',
        display=display.snapshot(include_samples=False) if display is not None else None)
