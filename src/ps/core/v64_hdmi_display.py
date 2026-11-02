"""Same-frame P1 INPUT | RECTIFIED, exact user pair, finite status submission.

Display owns all VideoFrames. CPU snapshots isolate both MMAP and remap CMA.
Automatic raw snapshots are immutable ordinary RAM, retained in two slots.
This uses P1's24bit BGR configure/binding and direct-to-VDMA composition.
"""
from pathlib import Path
from contextvars import copy_context
from collections import deque
import asyncio,hashlib,os,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from v64_io import yuyv_bgr_into,bgra_bgr_into
from v71_display import paired_copy,_library
from run_logging import checkpoint
from v108_hybrid_status import footer as hybrid_footer
from v116_continuity import valid_continuity
from v123_live_ui import LiveUI
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SUPPORTED_MODES=((640,480),(1280,720),(1024,600))
_RETAINED=[]


def _current_tap_quad(meta,shape,generation,submitted,now):
    """Event-only evidence from the already submitted source; no image reads."""
    if (meta.get('ui_generation')!=generation or meta.get('state')!='CURRENT'
            or meta.get('admission_mode')=='manual' or meta.get('recovery_active')
            or meta.get('epoch') is None):return None
    try:
        ages=(now-float(submitted),now-float(meta['capture_ready_at']),now-float(meta['verified_at']))
        if not all(np.isfinite(age) and 0.<=age<=limit for age,limit in zip(ages,(.25,.35,.35))):return None
        q=np.asarray(meta.get('corners',()),np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q):return None
        h,w=shape[:2]
        if np.any(q<0.) or np.any(q[:,0]>w-1) or np.any(q[:,1]>h-1):return None
        shortest=float(np.min(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)))
        if shortest<24. or abs(cv2.contourArea(q))<576.:return None
        return q,max(12.,.05*shortest),shortest
    except (KeyError,TypeError,ValueError,OverflowError,cv2.error):return None


class PageFeedback:
    """Event-only compositor, removed from the instance after each interaction.

    Only the HDMI owner paints an unsubmitted canvas. No submitted VideoFrame,
    camera image, output lease, timer or background worker is retained here.
    """
    def __init__(self,display):
        self.display=display;self.loading=None;self.point=None;self.revision=0
        self.painted=set();self.entry_regions={};self.handler=self.submit;self.original=None;self.previous=None
        self.live_handler=self.live_frame
    def _attach_locked(self):
        d=self.display
        if d.__dict__.get('_submit') is self.handler:return
        # TargetSwitch temporarily captures _submit while freezing a canvas.
        # Its ownership transaction always has priority over cosmetic events.
        if d.target_switch is not None:return
        self.previous=d.__dict__.get('_submit');self.original=d._submit
        d._submit=self.handler
    def _detach_locked(self):
        d=self.display
        if d.__dict__.get('_feedback_live') is self.live_handler:del d._feedback_live
        if d.__dict__.get('_submit') is self.handler:
            if self.previous is None:del d._submit
            else:d._submit=self.previous
    def _invalidate_locked(self):
        for key in self.painted:self.display.canvas_views.pop(key,None)
        self.painted.clear()
    def _wake_locked(self):
        d=self.display
        if d.ui_view=='home':d.ui_dirty=True
        elif d.inspection.kind is not None:d.inspection.dirty=True
        elif d.ui_view=='snapshot' and d.last_static_packet is not None:d.inspection_restore=True
        d.condition.notify_all()
    def cancel(self):
        with self.display.condition:
            self.loading=self.point=None;self.revision+=1
            self.entry_regions.clear()
            self._invalidate_locked();self._detach_locked()
    def begin(self,view,generation,kind):
        d=self.display
        with d.condition:
            self._invalidate_locked();self.point=None;self.revision+=1
            until=('home' if view=='home' else 'inspection' if kind in ('calibration','zoom','album') else 'output')
            self.entry_regions.clear()
            self.loading=dict(view=view,generation=int(generation),kind=kind,
                stage='prepare' if kind in ('enter','ai_calibration') else kind,until=until)
            if kind=='ai_calibration':d._feedback_live=self.live_handler
            elif d.__dict__.get('_feedback_live') is self.live_handler:del d._feedback_live
            self._attach_locked()
        checkpoint('UI_NAVIGATION_BEGIN',generation=generation,page=view,kind=kind,
            event_driven=True,artificial_delay=False)
    def live_frame(self,meta,has_output):
        # Only present while an explicit AI navigation is unresolved. Called by
        # the owner for the exact canvas about to be submitted, never pixels.
        with self.display.condition:
            load=self.loading
            if load is None or load['kind']!='ai_calibration' or meta.get('ui_generation')!=load['generation']:return
            stage={'AI_LOADING':'prepare','AI_INFER':'search','AI_CONFIRM':'verify'}.get(meta.get('hybrid_phase'))
            if stage is not None and stage!=load['stage']:load['stage']=stage;self.revision+=1
            load['live_settled']=bool(has_output or meta.get('hybrid_phase') in
                ('RECOVERY_COOLDOWN','WAIT_TARGET','EMPTY_WAIT','AI_ERROR'))
    def phase(self,phase,generation):
        stage={'prepare':'prepare','edges':'search','verify':'verify','display':'display'}.get(phase)
        with self.display.condition:
            load=self.loading
            if load is None or load['generation']!=generation or load['until']!='output' or stage is None:return
            if load['kind']=='layout':return
            ranks={'prepare':0,'snapshot':0,'search':1,'verify':2,'display':3}
            if ranks.get(stage,0)<=ranks.get(load['stage'],-1):return
            load['stage']=stage;self.revision+=1
            self._wake_locked()
    def touch(self,event,result,generation):
        d=self.display;phase=event.get('phase');target=result.get('target') or ''
        # RatioUI owns its selection/focus feedback. The generic ring otherwise
        # dirties the frozen panel twice and invalidates its background cache.
        if target.startswith(('ratio_','hold_')):return
        if phase=='press' and target=='media_back' and result.get('accepted'):
            self.begin(d.ui_view,generation,'layout')
            with d.condition:self._wake_locked()
            return
        with d.condition:
            if phase=='press':
                if (result.get('generation')!=generation or not target or result.get('consumed')
                    or target in ('inspect_point','media_background') or d.target_switch is not None):return
                point=event.get('press')
                if point is None:return
                rect=None
                names={'manual_calibration':'manual','reading_zoom':'zoom','refind':'refind',
                    'layout_toggle':'layout_switch','snapshot_recapture':'snapshot_recapture'}
                if target in names:rect=getattr(d.ui_assets,names[target],None)
                self._invalidate_locked();self.point=dict(point=tuple(map(int,point)),rect=rect,generation=generation)
                self.revision+=1;self._attach_locked();self._wake_locked()
                checkpoint('UI_PRESS_FEEDBACK',generation=generation,target=target,event_only=True)
            elif phase in ('release','cancel'):
                self.point=None;self.revision+=1;self._invalidate_locked()
                if phase=='cancel' and self.loading is None:self._detach_locked()
                if self.loading is None:self._detach_locked()
                self._wake_locked()
        if phase!='release' or not result.get('accepted') or d.target_switch is not None:return
        reason=result.get('reason') or ''
        if target=='reading_zoom':kind='zoom'
        elif target.startswith('media_') and target!='media_capture':kind='layout' if target=='media_back' else 'album'
        elif reason.startswith('reading_closed'):kind='layout'
        else:return
        self.begin(d.ui_view,generation,kind)
        with d.condition:self._wake_locked()
    async def submit(self,frame):
        d=self.display
        with d.condition:
            load=None if self.loading is None else dict(self.loading)
            point=None if self.point is None else dict(self.point)
            revision=self.revision;original=self.original
            if load is None and point is None:self._detach_locked()
            key=int(frame.physical_address);token=d.canvas_views.get(key)
            valid=bool(token and len(token)>=2 and token[1]==d.ui_generation)
            if load is not None:
                valid=bool(valid and load['generation']==d.ui_generation)
                if token and token[0]=='target_switch':valid=False
            complete=False
            if load is not None and valid:
                if load['until']=='home':complete=token[0]=='home'
                elif load['until']=='inspection':
                    complete=bool(token[0]=='inspection' and len(token)>=3 and token[2]==d.inspection.token
                        and d.inspection.kind==load['kind'])
                    if load['kind']=='album' and d.media is not None:
                        complete=bool(complete and not d.media.model.get('busy',False))
                else:complete=bool(token[0]==load['view'] and
                    (d.layouts.get(key,(None,None))[1] is not None or load.get('live_settled',False)))
        # All access to frame pixels precedes the official VDMA handoff.
        if valid and (load is not None or point is not None):
            canvas=np.asarray(frame);painted=False
            old_entry=self.entry_regions.get(key)
            if complete and old_entry is not None:
                x,y,w,h=old_entry;right=d.layouts.get(key,(None,None))[1]
                # Erase only placeholder pixels outside the already composed
                # real output. Result geometry may be portrait or landscape.
                if right is not None:
                    rx,ry,rw,rh=right;lo=max(x,rx);hi=min(x+w,rx+rw);top=max(y,ry);bottom=min(y+h,ry+rh)
                    if lo>=hi or top>=bottom:canvas[y:y+h,x:x+w]=0
                    else:
                        canvas[y:top,x:x+w]=0;canvas[bottom:y+h,x:x+w]=0
                        canvas[top:bottom,x:lo]=0;canvas[top:bottom,hi:x+w]=0
                    painted=True
            fixed_status=bool(hasattr(d.ui_assets,'live_ui_parts') and token[0] in ('compare','rectified'))
            if load is not None and load['kind']=='enter' and not complete and token[-1] not in ('live_progress','fixed_live') and not fixed_status:
                # A single cached status tile on an already-owned startup
                # canvas. Phase changes alone advance it; no animation clock.
                x=(canvas.shape[1]//2 if load['view']=='rectified' else canvas.shape[1]*3//4)-160
                y=canvas.shape[0]//2-52
                canvas[y:y+112,x:x+320]=d.ui_assets.entry_progress[load['stage']]
                canvas[74:118]=0  # No second segmented bar or target hint.
                painted=True
                with d.condition:
                    self.entry_regions[key]=(x,y,320,112)
            if load is not None and load['kind']!='enter' and not (complete and load['until']=='output') and not fixed_status:
                stage='ready' if complete else load['stage']
                canvas[74:106]=d.ui_assets.navigation_progress[stage]
                painted=True
                if token[0] in ('compare','rectified') and d.layouts.get(key,(None,None))[1] is None:
                    canvas[106:118,:640]=0  # Old hint text fringes; no image occupies these rows.
            if point is not None and point['generation']==d.ui_generation:
                painted=True
                if point['rect'] is not None:
                    x,y,w,h=point['rect'];cv2.rectangle(canvas,(x+2,y+2),(x+w-3,y+h-3),(90,235,245),2,cv2.LINE_AA)
                else:
                    x,y=point['point'];cv2.circle(canvas,(x,y),16,(90,235,245),2,cv2.LINE_AA)
                    cv2.circle(canvas,(x,y),3,(90,235,245),-1,cv2.LINE_AA)
            canvas=None
            if painted:
                with d.condition:self.painted.add(key)
        result=await original(frame)
        # Metadata only after handoff. Never read frame or its NumPy view here.
        with d.condition:
            if complete and revision==self.revision and self.loading is not None:
                finished=self.loading;self.loading=None;self.revision+=1
                self.entry_regions.clear()
                self._invalidate_locked()
                if self.point is None:self._detach_locked()
                self._wake_locked()  # One event redraw removes the completed strip.
            else:finished=None
        if finished is not None:
            checkpoint('UI_NAVIGATION_PRESENTED',generation=finished['generation'],page=finished['view'],
                kind=finished['kind'],event_only=True,physical_scan_time_measured=False)
        return result


from v121_target_switch import TargetSwitch


def fit_panel_shape(mode, input_shape):
    """把摄像头尺寸等比缩进左边面板；放得下就原样返回（640x480 时不变）。

    ⚠️ 2026-10-28：`native_display_rect()` 只接受"1:1 放得下"的尺寸，
       而 800x600 放不进 640x656 的面板 ⇒ 所有用它算矩形的地方都必须先过这里。
    """
    cw, ch = map(int, mode); h, w = map(int, input_shape)
    pw = min(cw // 2, cw - (cw // 2)); ph = ch - 64
    if w <= pw and h <= ph: return (h, w)
    s = min(float(pw) / max(1, w), float(ph) / max(1, h))
    return (max(2, int(round(h * s)) // 2 * 2), max(2, int(round(w * s)) // 2 * 2))


def native_display_rect(mode,shape,side):
    """Center the complete source image at 1:1; never resize or crop it."""
    if side not in (0,1) or len(mode)!=2 or len(shape)!=2:
        raise ValueError('Invalid native HDMI panel layout')
    canvas_w,canvas_h=map(int,mode);h,w=map(int,shape)
    mid=canvas_w//2;x=0 if side==0 else mid
    width=mid if side==0 else canvas_w-mid;height=canvas_h-64
    if min(w,h,width,height)<1 or w>width or h>height:
        raise ValueError('V74 displays complete images at1:1 without scaling/cropping: '
            +str((w,h))+' does not fit panel '+str((width,height))+'; use1280x720 for default camera/output')
    return x+(width-w)//2,36+(height-h)//2,w,h

def validate_overlay(overlay,manifest):
    required=('remap','axi_dma_0','video/axi_vdma_disp','video/hdmi_out/frontend/vtc_out',
              'video/hdmi_out/frontend/axi_dynclk','video/hdmi_out/pixel_unpack','video/hdmi_out/color_convert')
    missing=[k for k in required if k not in overlay.ip_dict]
    if missing:raise RuntimeError('Specified P1 overlay missing '+str(missing))
    if int(overlay.ip_dict['remap']['phys_addr'])!=0x40000000:raise RuntimeError('P1 remap address mismatch')
    params=overlay.ip_dict['video/axi_vdma_disp']['parameters']
    for key,value in (('C_INCLUDE_MM2S',1),('C_INCLUDE_S2MM',0),('C_M_AXIS_MM2S_TDATA_WIDTH',32),('C_NUM_FSTORES',4)):
        if int(params.get(key,-1))!=value:raise RuntimeError('HDMI VDMA mismatch '+key)
    from pynq import MMIO
    actual=int(MMIO(0x40000000,0x40).read(0x30));expected=int(manifest['remap_version'])
    checkpoint('P1_HARDWARE_IDENTITY',actual_version=actual,expected_version=expected,
        actual_hex='0x%08x'%actual,expected_hex='0x%08x'%expected,matched=actual==expected)
    if actual!=expected:
        raise RuntimeError('P1 VERSION mismatch: actual=0x%08x expected=0x%08x; '
            'use the complete matching bit/HWH/software package'%(actual,expected))

class HdmiLatest:
    manual_status_template='MANUAL %s | M-CORR %.1f | DISP %.1f | %s'
    @staticmethod
    def _fit_shape(mode, input_shape):
        return fit_panel_shape(mode, input_shape)
    def __init__(self,overlay,mode=(1280,720),capacity=(362,512),timeout_s=3.,hold_max_age_s=1.5,
                 input_shape=(480,640),max_fps=30.,ui_assets=None,
                 capture_dir='/home/xilinx/captures',capture_jpeg_quality=90):
        if tuple(mode) not in SUPPORTED_MODES:raise ValueError('HDMI mode640x480/1280x720/1024x600 only')
        if not 1<=float(max_fps)<=30:raise ValueError('HDMI rate1..30 only')
        self.overlay=overlay;self.mode=tuple(mode);self.timeout=float(timeout_s);self.hold_max_age=float(hold_max_age_s)
        #   ⭐ 2026-10-27：允许摄像头分辨率大于面板（例如 800x600）。
        #      `native_display_rect()` 只接受"1:1 放得下"的尺寸，所以这里先算一个
        #      **显示用尺寸**（等比缩到能放下面板），raw 在 `_draw()` 里缩到这个尺寸。
        #      640x480 时两者相同，行为与改动前一模一样。
        self.display_shape=self._fit_shape(self.mode,input_shape)
        native_display_rect(self.mode,self.display_shape,0)
        #   ⭐ 2026-10-28：左预览「缩放 + YUYV→BGR」的备用工作区与取值开关。
        #      首选是 `FusedDisplay`（原生 NEON 5:4 多相），**懒创建**——
        #      启动阶段不能同步编译"正在展示其就绪状态"的那个原生库。
        self._scaled=None;self._fused=None;self._fused_failed=False
        self._preview_nearest=os.environ.get('P11_PREVIEW_NEAREST','1')!='0'
        #   ⭐ 2026-10-31：预览缩放后端三选一，用于 600P（800x600->640x480）A/B。
        #      fused   = NEON 5:4 多相（现状；实测 input_convert 中位 68.4ms / p90 94.6ms）
        #      nearest = 通用最近邻（p11_yuyv_preview_nearest，标量逐像素）
        #      crop    = 不缩放，居中裁 640x480（掉左右各 20% 视野，但走 1:1 快路 ~11ms）
        #      640x480->640x480（480P）不受影响，始终走 1:1。
        self._preview_scale=os.environ.get('P11_PREVIEW_SCALE','fused').strip().lower()
        if self._preview_scale not in ('fused','nearest','crop'):self._preview_scale='fused'
        #   ⭐ 2026-10-29：相机输入档位弹窗的叠加层。由 `v119_profile_ui.ProfileUI.publish()`
        #      写入；None = 不画。只在 `_draw` 末尾贴图，不参与布局。
        self.profile_overlay=None
        native_display_rect(self.mode,(capacity[1],capacity[0]),1)
        self.period=1./float(max_fps);self.max_fps=float(max_fps);self.input_shape=tuple(input_shape)
        self.condition=threading.Condition();self.pending=None;self.active_slot=None;self.copying_slot=None;self.stop=False
        self.ready=False;self.error=None;self.closed=False;self.shutdown_safe=False;self.context=copy_context()
        pixels=int(capacity[0])*int(capacity[1]);h,w=map(int,input_shape)
        self.pool=[np.empty((pixels,4),np.uint8) for _ in range(2)]
        self.raw_pool=[np.empty((h,w,2),np.uint8) for _ in range(2)]
        self.raw_refs=[None,None]  # Only standalone readonly ndarray owners, never camera/CMA views.
        self.output_refs=[None,None]  # Explicit leases to completed, invalidated P1 slots.
        self.slot_packets=[None,None];self.live_preview=None;self.live_packet=None;self.preview_rendered=None;self.live_last_offer_at=0.
        self.layouts={}
        self.submitted=self.offered=self.replaced=self.dropped=self.unique_current=self.panels_submitted=0
        self.cpu_copy_s=0.;self.samples=deque(maxlen=512);self.submit_times=deque(maxlen=120)
        self.latest_meta={};self.epoch=0;self.epoch_stats={}
        self.current_times=deque(maxlen=120);self.copy_stats=np.empty(4,np.float64)
        self.display_lib=_library()  # Initialize FFI once before producer/HDMI worker can share it.
        self.last_offer_timing={};self.last_submitted_layout=0
        self.ui_assets=ui_assets;self.ui_view='home' if ui_assets is not None else 'compare'
        self.ui_generation=0;self.ui_dirty=ui_assets is not None;self.ui_error_banner=False
        self.ui_requested_at=time.perf_counter();self.canvas_views={};self.ui_pages_submitted=0;self.ui_discarded=0
        self.ui_return_feedback=False;self.ui_layout_pending=None;self.ui_layout_switches=0;self.ui_feedback_submitted=0
        self.frozen_generation=None;self.snapshot_receipt=None;self.snapshots_frozen=0
        from v82_interaction import Inspection
        self.inspection=Inspection(self);self.last_static_packet=None;self.inspection_restore=False
        self.tap_source=None;self.target_notice='idle';self.target_switch=None
        self.media=None
        if ui_assets is not None:
            from v97_album import MediaController
            self.media=MediaController(self,capture_dir,capture_jpeg_quality)
        self.worker=threading.Thread(target=self._entry,name='hdmi_owner',daemon=True);self.worker.start()
        deadline=time.perf_counter()+(self.timeout*3 if self.mode==(1024,600) else self.timeout)+2.
        with self.condition:
            while not self.ready and self.error is None:
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('HDMI initialization timed out; worker/overlay retained')
                self.condition.wait(remaining)
            if self.error is not None:
                self.error.hdmi_shutdown_safe=self.shutdown_safe
                raise self.error
    def _entry(self):
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.condition.notify_all()
            if not self.shutdown_safe:_RETAINED.append(self)
            try:checkpoint('HDMI_FAILED',durable=True,exception_type=type(exc).__name__,exception=str(exc),
                vdmasafe=self.shutdown_safe,vdma_retained=not self.shutdown_safe)
            except BaseException:pass
    def _run(self):
        from pynq.lib.video import VideoMode,PIXEL_BGR
        self.loop=asyncio.new_event_loop();asyncio.set_event_loop(self.loop)
        self.vout=self.overlay.video.hdmi_out
        self.vout._vdma=self.overlay.video.axi_vdma_disp
        self.frontend=self.vout.frontend;self.channel=self.vout._vdma.writechannel
        next_publish=0.;last_meta=None;last_publish=0.
        try:
            checkpoint('HDMI_SETUP_BEGIN',durable=True,mode=list(self.mode),memory_format='BGR24',
                vdma='video/axi_vdma_disp',layout='INPUT | RECTIFIED',settings='P1 explicit binding/configure PIXEL_BGR')
            if self.channel.running:raise RuntimeError('Fresh overlay HDMI channel unexpectedly active')
            if self.mode==(1024,600):
                from v70_hdmi_timing import install_1024_frontend
                self.frontend=install_1024_frontend(self.vout,self.overlay,self.timeout)
            self.vout.configure(VideoMode(*self.mode,24),PIXEL_BGR)
            actual=list(self.vout.color_convert.colorspace)
            if self.vout.pixel_unpack.bits_per_pixel!=24:raise RuntimeError('HDMI pixel_unpack24 readback mismatch')
            if len(actual)!=12 or any(abs(float(a)-float(b))>1./256 for a,b in zip(actual,PIXEL_BGR.out_color)):
                raise RuntimeError('HDMI BGR matrix readback mismatch')
            if not callable(getattr(self.channel,'_writeframe_internal',None)):
                raise RuntimeError('Installed PYNQ VDMA lacks reviewed frame submission method')
            self.channel.cacheable_frames=True;self.vout.start()
            with self.condition:self.ready=True;self.condition.notify_all()
            timing=getattr(self.frontend,'detail',{})
            checkpoint('HDMI_READY',durable=True,mode=list(self.mode),refresh_hz=timing.get('refresh_hz',60),memory_format='BGR24',
                timing=timing,nominal_refresh_hz=60,
                layout='INPUT | RECTIFIED',same_frame=True,display_max_fps=self.max_fps,
                pixel_unpack_bits=24,color_matrix=actual,display_software_abi=7301,
                display_frontend_version=79,display_scale_enabled=False,display_crop_enabled=False,
                ui_enabled=self.ui_assets is not None,
                composition_backend='native_direct_color_convert_1to1',submission='finite_status_poll_then_official_frame_ownership',no_jpeg=True)
            while True:
                page_change=None;inspection_payload=None;static_inspect=None
                with self.condition:
                    if self.ui_assets is not None and self.ui_dirty and not self.stop:
                        page_change=(self.ui_view,self.ui_generation,self.ui_error_banner,self.ui_requested_at,self.ui_return_feedback)
                        # request_view already discarded old-generation pending work.
                        # Keep a fresh packet offered after that request.
                        self.ui_dirty=False
                    elif self.ui_assets is not None and not self.stop and self.inspection.dirty:
                        inspection_payload=self.inspection.payload_locked()
                    elif self.ui_assets is not None and not self.stop and self.inspection.kind:
                        self.condition.wait();continue
                    elif (self.ui_assets is not None and not self.stop and self.last_static_packet is not None and
                            (self.inspection.zoom_requested==self.ui_generation or self.inspection_restore
                             or (self.media is not None and self.media.frozen_redraw))):
                        action='zoom' if self.inspection.zoom_requested==self.ui_generation else 'restore'
                        static_inspect=(action,self.last_static_packet)
                        if self.media is not None:self.media.frozen_redraw=False
                        self.inspection_restore=False;self.active_slot=self.last_static_packet[0]
                    elif (self.ui_assets is not None and not self.stop and (self.ui_view=='home' or
                            (self.ui_view=='snapshot' and self.frozen_generation==self.ui_generation))):
                        wait_s=self.media.frozen_wait_locked() if self.media is not None and self.ui_view=='snapshot' else None
                        if wait_s==0.:continue
                        self.condition.wait(wait_s);continue
                    elif not self.stop:
                        now=time.perf_counter()
                        if now<next_publish:self.condition.wait(min(next_publish-now,.10));continue
                        if self.pending is None and not self._preview_due_locked(now):
                            self.condition.wait(min(.10,self.period))
                            if self.ui_dirty or self.inspection.dirty or self.inspection.kind or self.inspection_restore:continue
                    if self.stop and self.ui_assets is not None:self.pending=None;break
                    if self.stop and self.pending is None:break
                    special=page_change is not None or inspection_payload is not None or static_inspect is not None
                    packet=None if special else self.pending
                    if not special:self.pending=None
                    preview_only=False
                    if not special and self.ui_view=='compare' and self.live_preview is not None:
                        if packet is not None:self.live_packet=packet
                        elif self._preview_due_locked(time.perf_counter()):
                            packet=self.live_packet;preview_only=True
                            if packet is None:
                                stamp=time.perf_counter()
                                packet=(None,(),dict(state='WAITING',index=-1,camera_sequence=-1,
                                    verified_at=stamp,capture_ready_at=stamp,epoch=self.epoch,
                                    correction_fps=0.,corners=(),color_mode=0,ui_view=self.ui_view,
                                    ui_generation=self.ui_generation))
                    if packet is not None:self.active_slot=packet[0]
                if page_change is not None:
                    view,generation,error_banner,requested_at,return_feedback=page_change
                    last_meta=None;next_publish=0.
                    if view=='home':
                        if return_feedback:self._show_home(generation,False,requested_at,feedback=True)
                        self._show_home(generation,error_banner,requested_at)
                    else:
                        stamp=time.perf_counter()
                        submitted=self._show(None,None,dict(state='STARTING',index=-1,camera_sequence=-1,
                            verified_at=stamp,capture_ready_at=stamp,epoch=self.epoch,correction_fps=0.,corners=(),
                            color_mode=0,ui_view=view,ui_generation=generation))
                        if submitted:
                            checkpoint('UI_PAGE_PRESENTED',page=view,generation=generation,
                                request_to_submit_s=time.perf_counter()-requested_at,physical_scan_time_measured=False)
                    continue
                if inspection_payload is not None:
                    self._show_inspection(inspection_payload);continue
                if static_inspect is not None:
                    action,(slot,shape,meta)=static_inspect
                    out=self.pool[slot][:shape[0]*shape[1]].reshape(*shape,4)
                    try:
                        if action=='zoom':
                            image=cv2.cvtColor(out,cv2.COLOR_BGRA2BGR)
                            with self.condition:self.inspection.open_zoom_locked(image,meta);self.condition.notify_all()
                        else:self._show(self._raw_snapshot(slot),out,dict(meta,inspection_redraw=True))
                    finally:
                        with self.condition:self.active_slot=None;self.condition.notify_all()
                    continue
                now=time.perf_counter()
                if packet is None:
                    if self._profile_idle(now):
                        next_publish=time.perf_counter()+self.period
                        continue
                    if self.ui_view=='compare' and self.live_preview is not None and self.live_preview.active():continue
                    if last_meta is None or (last_meta.get('state')!='WAITING' and now-last_publish>.5 and now-last_meta.get('verified_at',now)>self.hold_max_age):
                        meta=dict(state='WAITING',index=-1,camera_sequence=-1,verified_at=now,capture_ready_at=now,
                            epoch=self.epoch,correction_fps=0.,corners=(),color_mode=0,
                            ui_view=self.ui_view,ui_generation=self.ui_generation)
                        self._show(None,None,meta);last_meta=meta;last_publish=time.perf_counter()
                        next_publish=last_publish+self.period
                    continue
                slot,out_shape,meta=packet
                raw=None if slot is None or not meta.get('has_raw_snapshot',True) else self._raw_snapshot(slot)
                out=None if not out_shape else self._output_snapshot(slot,out_shape)
                try:
                    raw,meta=self._preview_input(raw,meta,preview_only)
                    if meta.get('display_mode')=='RAW_ONLY':out=None
                    if meta['state'] in ('HELD','MANUAL_HELD') and (
                            (meta.get('continuity_output') and not valid_continuity(meta,now)) or
                            now-meta['verified_at']>self.hold_max_age):
                        out=None;meta=dict(meta,state='LOST',corners=(),verified_at=0.)
                    shown=self._show(raw,out,meta);last_meta=meta;last_publish=time.perf_counter()
                    if shown and meta.get('display_mode')=='RAW_ONLY':
                        with self.condition:self._retire_unpaired_output_locked(packet,raw,meta)
                    next_publish=max(next_publish+self.period,last_publish)
                finally:
                    raw=None;out=None  # Slot ownership keeps source bytes alive.
                    with self.condition:
                        if self.ui_view!='compare' or self.live_preview is None:self.active_slot=None
                        self.condition.notify_all()
        finally:
            # Stop the physical scanout before releasing any frame/cache. Even
            # failed startup may have populated _cache prior to start returning.
            checkpoint('HDMI_STOP_BEGIN',reason='application_exit_or_owner_error',
                page=self.ui_view,generation=self.ui_generation)
            self.channel._mmio.write(0x00,0x00011080);deadline=time.perf_counter()+self.timeout
            while self.channel.running:
                if time.perf_counter()>=deadline:raise TimeoutError('HDMI halt not proved; retain scanout/overlay')
                time.sleep(.001)
            self.channel.stop();self.frontend.stop();self.shutdown_safe=True;self.loop.close()
            checkpoint('HDMI_STOPPED',durable=True,physical_scanout_halted=True,
                buffers_released_after_halt=True)
    def _preview_due_locked(self,now):
        preview=getattr(self,'live_preview',None)
        if preview is None or not preview.active():return False
        state=preview.pairing.snapshot(now)
        if state['display_mode']=='PAIRED':return False
        value=preview.snapshot()
        if value is None:return False
        token=(value[0],value[1],self.ui_generation,state['pair_revision'])
        return token!=self.preview_rendered
    def _preview_input(self,raw,meta,preview_only=False):
        preview=getattr(self,'live_preview',None)
        if preview is None or not preview.active() or meta.get('ui_view')!='compare':return raw,meta
        now=time.perf_counter();state=preview.pairing.snapshot(now)
        paired=(not preview_only and meta.get('display_mode')=='PAIRED'
            and preview.pairing.packet_current(meta,now))
        if paired and not preview.pairing.valid(meta,raw is not None,True,now):
            preview.pairing.invalidate(reason='pair_expired');state=preview.pairing.snapshot(now);paired=False
        if paired:
            # Preserve the immutable raw that produced this actual completed image.
            return raw,dict(meta,**state,input_camera_sequence=meta.get('camera_sequence'),
                input_capture_ready_at=meta.get('capture_ready_at'),preview_only=False)
        value=preview.snapshot()
        if value is None:
            seq=meta.get('camera_sequence',-1);ready=meta.get('capture_ready_at',0.);image=raw;color=meta.get('color_mode',0)
        else:
            seq,ready,image,color,generation=value
            if generation!=meta.get('ui_generation'):
                # A stale preview must not erase the matching producer's raw.
                seq=meta.get('camera_sequence',-1);ready=meta.get('capture_ready_at',0.)
                image=raw;color=meta.get('color_mode',0)
        self.preview_rendered=(seq,ready,self.ui_generation,state['pair_revision'])
        return image,dict(meta,**dict(state,display_mode='RAW_ONLY'),state='LOST',corners=(),candidate_corners=(),
            input_camera_sequence=seq,input_capture_ready_at=ready,color_mode=color,preview_only=True,hybrid_valid_fps=0.)
    def _retire_unpaired_output_locked(self,packet,raw,meta):
        # Executed by HDMI owner after a RAW_ONLY submission, never while reading CMA.
        if self.live_packet is not packet:return
        slot=packet[0]
        if slot is not None:
            reference=self.output_refs[slot];self.output_refs[slot]=None
            if reference is not None:reference.release()
            self.raw_refs[slot]=raw
            saved=dict(meta,has_raw_snapshot=raw is not None)
            self.slot_packets[slot]=((),saved);self.live_packet=(slot,(),saved)
    def begin_ui_transition(self,view,generation,kind):
        with self.condition:
            controller=getattr(self,'page_feedback',None)
            if controller is None:controller=self.page_feedback=PageFeedback(self)
            if self.target_switch is not None:
                controller.cancel();return
            controller.begin(view,generation,kind)
    def cancel_ui_feedback(self):
        controller=getattr(self,'page_feedback',None)
        if controller is not None:controller.cancel()
    def touch_feedback(self,event,result,generation):
        with self.condition:
            controller=getattr(self,'page_feedback',None)
            if controller is None:controller=self.page_feedback=PageFeedback(self)
            controller.touch(event,result,generation)
    def arm_target_switch(self,generation,on_frozen,point=None,request_id=None):
        with self.condition:
            if (self.stop or self.error is not None or generation!=self.ui_generation or self.ui_view!='compare'
                    or self.inspection.kind is not None
                    or (self.media is not None and self.media.active)):return False
            if self.target_switch is not None:self.target_switch.restore()
            switch=TargetSwitch(self,on_frozen,point,request_id=request_id);self.target_switch=switch
            self._show=switch.handler;self.tap_source=None
        checkpoint('UI_TARGET_SWITCH_ARMED',generation=generation,event_only=True,request_id=request_id,live_preview=True)
        return True
    def set_target_phase(self,phase,generation):
        controller=getattr(self,'page_feedback',None)
        if controller is not None:controller.phase(phase,generation)
        with self.condition:
            switch=self.target_switch
            if switch is not None and switch.active and generation==switch.generation==self.ui_generation:
                switch.set_phase_locked(phase)
    def request_view(self,view,generation,error=False,layout_only=False,return_feedback=False,preserve_target=False):
        if self.ui_assets is None:raise RuntimeError('UI assets not configured')
        if view not in ('home','compare','rectified','snapshot'):raise ValueError('Unknown display view')
        with self.condition:
            if self.stop:return
            if int(generation)<self.ui_generation:return
            switch=self.target_switch
            if switch is not None:
                if not (preserve_target and not error and view in ('compare','rectified') and switch.retarget_locked(generation)):
                    switch.restore()
            previous=self.ui_view;previous_generation=self.ui_generation
            if layout_only and (previous not in ('compare','rectified') or view not in ('compare','rectified')):
                raise ValueError('Layout-only command requires two live views')
            self.ui_view=view;self.ui_generation=int(generation);self.ui_error_banner=bool(error)
            preview=getattr(self,'live_preview',None)
            if (layout_only or preserve_target) and preview is not None:
                # Explicit compare/result-only layout changes reuse this camera.
                # A manual/new session still requires a fresh binding.
                with preview.lock:
                    if preview.generation==previous_generation:
                        preview.generation=int(generation)
                        if preview.latest is not None:
                            seq,ready,raw,color,_=preview.latest
                            preview.latest=(seq,ready,raw,color,int(generation))
            self.live_packet=None;self.preview_rendered=None
            self.ui_requested_at=time.perf_counter();self.ui_return_feedback=bool(return_feedback)
            self.frozen_generation=None;self.snapshot_receipt=None
            self.last_static_packet=None;self.inspection_restore=False;self.inspection.clear_locked()
            self.tap_source=None
            if not layout_only:self.target_notice='idle'
            if self.media is not None:self.media.page_changed_locked()
            if layout_only:
                # Keep scanout until a complete new-layout frame can be submitted.
                # A startup page command already queued still uses the new view.
                self.ui_layout_switches+=1
                self.ui_layout_pending=(int(generation),view,self.ui_requested_at)
                if self.pending is not None:
                    slot,shape,meta=self.pending
                    if view=='compare' and not meta.get('has_raw_snapshot',True):
                        self.ui_discarded+=1;self.pending=None
                    else:
                        meta=dict(meta,ui_view=view,ui_generation=int(generation))
                        self.pending=(slot,shape,meta)
            else:
                self.ui_dirty=True;self.ui_layout_pending=None
                if self.pending is not None:self.ui_discarded+=1;self.pending=None
            self.condition.notify_all()
    def set_target_notice(self,notice,generation):
        controller=getattr(self,'page_feedback',None)
        if controller is not None and notice in ('idle','multiple','selecting'):controller.phase('verify',generation)
        with self.condition:
            if self.stop or generation!=self.ui_generation or self.ui_view not in ('compare','rectified'):return False
            switch=self.target_switch
            if switch is not None and generation==switch.generation and notice in ('miss','fallback'):
                switch.set_phase_locked('fallback')
            if notice not in ('idle','multiple','selecting','selected','miss','fallback','not_covered','unconfirmed','current'):raise ValueError('Invalid target notice')
            if notice!=self.target_notice:
                self.target_notice=notice;self.canvas_views.clear();self.condition.notify_all()
        checkpoint('UI_TARGET_NOTICE',notice=notice,generation=generation,
            scope='tap_event' if notice=='current' else 'acquisition_only',per_frame_detection=False)
        return True
    def tap_target_source(self,point,generation):
        # Called on a UI event: ordinary readonly RAM only, never MMAP/CMA/VDMA.
        with self.condition:
            value=self.tap_source
            if (self.stop or generation!=self.ui_generation or self.ui_view!='compare'
                    or self.inspection.kind is not None or self.media is not None and self.media.active or value is None):return None
            raw,meta,rect,submitted=value
            if (meta.get('ui_generation')!=generation or time.perf_counter()-submitted>.75
                    or time.perf_counter()-meta.get('capture_ready_at',0.)>1.2
                    or rect is None):return None
            from v121_selection import source_point,can_select
            if not can_select(meta.get('admission_mode')=='manual',meta.get('correction_origin')=='AI'):return None
            if type(raw) is not np.ndarray or not raw.flags.owndata or raw.flags.writeable or not raw.flags.c_contiguous:return None
            mapped=source_point(point,rect,raw.shape)
            if mapped is None:return None
            return dict(image=raw,point=mapped,normalized_point=(mapped[0]/raw.shape[1],mapped[1]/raw.shape[0]),ready=float(meta['capture_ready_at']),
                sequence=int(meta.get('camera_sequence',-1)),submitted_at=submitted,pressed_at=time.perf_counter(),
                current_target_meta=meta,source_rect=rect)
    def current_target_tap(self,selection,release,generation):
        """A clean tap may keep a fresh current quad; uncertainty always falls through.

        Both endpoints must lie well inside both the press and latest submitted
        quads. This is displayed-target geometry, not semantic book recognition.
        This method is called only by touch release, never by the frame loop.
        """
        with self.condition:
            if (self.stop or self.error is not None or self.target_switch is not None
                    or self.target_notice in ('selecting','miss','fallback','not_covered','unconfirmed')):return False
            original=selection.get('current_target_meta')
            if original is None:return False
            if not (original.get('target_selection_proof') or {}).get('single_target'):return False
            latest=self.tap_target_source(release,generation)
            if latest is None:return False
            meta=latest['current_target_meta'];now=time.perf_counter()
            if (meta.get('target_selection_proof') or {}).get('request_id')!=original['target_selection_proof'].get('request_id'):return False
            if (original.get('epoch')!=meta.get('epoch')
                    or selection.get('source_rect')!=latest['source_rect']
                    or selection['image'].shape!=latest['image'].shape):return False
            first=_current_tap_quad(original,selection['image'].shape,generation,
                selection['submitted_at'],selection['pressed_at'])
            last=_current_tap_quad(meta,latest['image'].shape,generation,latest['submitted_at'],now)
            if first is None or last is None:return False
            q0,margin0,edge0=first;q1,margin1,edge1=last
            if float(np.max(np.linalg.norm(q1-q0,axis=1)))>max(12.,.08*min(edge0,edge1)):return False
            points=(tuple(map(float,selection['point'])),tuple(map(float,latest['point'])))
            distances=[float(cv2.pointPolygonTest(q,p,True)) for q in (q0,q1) for p in points]
            if min(distances[:2])<margin0 or min(distances[2:])<margin1:return False
            if not self.set_target_notice('current',generation):return False
            checkpoint('UI_TAP_CURRENT_TARGET',generation=generation,point=list(points[0]),
                source_sequence=selection['sequence'],latest_sequence=latest['sequence'],
                minimum_inside_distance=min(distances),boundary_margin=max(margin0,margin1),
                target_restarted=False,camera_reopened=False,tracker_reinitialized=False,
                semantic_identity_proven=False,event_only=True)
            return True
    def snapshot_is_frozen(self,generation):
        # Touch reads only this receipt. It never calls camera/DMA/VDMA code.
        with self.condition:
            return bool(not self.stop and self.error is None and self.ui_view=='snapshot'
                and self.ui_generation==generation and self.frozen_generation==generation
                and self.snapshot_receipt is not None)
    def wait_snapshot(self,generation,index,sequence,cancel=None,timeout_s=None):
        deadline=time.perf_counter()+(self.timeout+2. if timeout_s is None else float(timeout_s))
        with self.condition:
            while True:
                if (cancel is not None and cancel.is_set()) or generation!=self.ui_generation:return None
                if self.error is not None:raise self.error
                if self.stop:raise RuntimeError('HDMI stopped before snapshot confirmation')
                receipt=self.snapshot_receipt
                if receipt is not None and (receipt['generation'],receipt['index'],receipt['camera_sequence'])==(generation,index,sequence):
                    return dict(receipt)
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('Single-frame HDMI submission was not confirmed')
                self.condition.wait(min(remaining,.2))
    def _acquire_canvas(self,page=None,generation=None):
        # Frame ownership has one release path: drop our Python reference.
        # In older PYNQ, explicitly freebuffer() on a cached frame returns its
        # pointer, then its __del__ may unmap that same cached pointer again.
        # Submitted frames remain referenced by the VDMA driver's _frames.
        frame=self.channel.newframe();canvas=np.asarray(frame)
        if page is not None:
            detail=dict(page=page,generation=generation,physical_address=int(frame.physical_address),
                virtual_address=int(canvas.ctypes.data),bytes=int(canvas.nbytes),
                cache_entries=len(getattr(getattr(self.channel,'_cache',None),'_cache',())),
                release_policy='reference_only_no_explicit_cached_frame_free')
            try:
                if canvas.shape!=(self.mode[1],self.mode[0],3) or canvas.dtype!=np.uint8:
                    raise RuntimeError('HDMI canvas layout mismatch')
                if not canvas.flags.c_contiguous or not canvas.flags.writeable or getattr(frame,'freed',False):
                    raise RuntimeError('HDMI canvas is not live writable memory')
                slots=getattr(self.channel,'_frames',())
                if any(slots[i] is not None and int(slots[i].physical_address)==detail['physical_address'] for i in range(len(slots))):
                    raise RuntimeError('HDMI newframe aliases a VDMA-owned frame')
                # Page transitions only: diagnose a stale mapping before a CPU
                # store can terminate the kernel. This is not a per-frame scan.
                cursor=detail['virtual_address'];end=cursor+detail['bytes']
                for line in Path('/proc/self/maps').read_text().splitlines():
                    fields=line.split(None,2);lo,hi=(int(v,16) for v in fields[0].split('-'))
                    if lo<=cursor<hi:
                        if not fields[1].startswith('rw'):break
                        cursor=min(end,hi)
                        if cursor==end:break
                if cursor!=end:raise RuntimeError('HDMI canvas mapping is incomplete; stop before writing')
                detail['mapping_read_write_verified']=True
                checkpoint('HDMI_CANVAS_ACQUIRED',**detail)
            except BaseException as exc:
                checkpoint('HDMI_CANVAS_REJECTED',durable=True,**detail,exception=str(exc))
                canvas=None;frame=None
                raise
        return frame,canvas
    def _show_home(self,generation,error_banner,requested_at,feedback=False):
        if generation!=self.ui_generation:return
        frame,canvas=self._acquire_canvas('home',generation)
        try:
            canvas[:]=self.ui_assets.home_frame(error_banner,feedback=feedback)
            key=int(frame.physical_address)
            self.canvas_views[key]=('home',generation);self.layouts[key]=(None,None)
            if generation!=self.ui_generation:return
            self.loop.run_until_complete(self._submit(frame))
            if feedback:self.ui_feedback_submitted+=1
            else:self.ui_pages_submitted+=1
            checkpoint('UI_RETURN_FEEDBACK_PRESENTED' if feedback else 'UI_PAGE_PRESENTED',page='home',generation=generation,
                request_to_submit_s=time.perf_counter()-requested_at,static=True,physical_scan_time_measured=False)
        finally:
            # No explicit freebuffer: a stale frame is recycled once by its
            # destructor; a submitted frame stays owned by channel._frames.
            canvas=None;frame=None
    def _status(self):
        mmio=self.channel._mmio
        return dict(control=int(mmio.read(0)),status=int(mmio.read(4)),park=int(mmio.read(0x28)),
            vsize=int(mmio.read(0x50)),hsize=int(mmio.read(0x54)),stride=int(mmio.read(0x58)),
            desired_frame=int(self.channel.desiredframe),pixel_bits=int(self.vout.pixel_unpack.bits_per_pixel))
    async def _submit(self,frame):
        # Same ownership/flush/schedule path as PYNQ writeframe, with a finite
        # readable-status wait instead of depending on an IRQ future's loop.
        mmio=self.channel._mmio;deadline=time.perf_counter()+self.timeout;polls=0
        while True:
            status=int(mmio.read(4))
            if status&0x70:raise RuntimeError('HDMI VDMA error '+str(self._status()))
            if status&1:raise RuntimeError('HDMI VDMA stopped before submission '+str(self._status()))
            if status&0x1000:break
            if time.perf_counter()>=deadline:
                detail=self._status();checkpoint('HDMI_SUBMIT_TIMEOUT',durable=True,registers=detail,polls=polls)
                raise TimeoutError('HDMI frame-ready timeout '+str(detail))
            polls+=1;await asyncio.sleep(.001)
        mmio.write(4,0x1000)
        self.channel._writeframe_internal(frame)
        return polls
    def _show_inspection(self,payload):
        from v82_interaction import render_inspection
        began=time.perf_counter();cpu=time.thread_time()
        generation=payload['generation']
        if generation!=self.ui_generation:return False
        frame,canvas=self._acquire_canvas('inspection_'+payload['kind'],generation)
        try:
            if payload['kind']=='ratio':
                key=int(frame.physical_address)
                payload=dict(payload,ratio_background_cached=self.canvas_views.get(key)==('inspection',generation,payload['token']))
            if payload['kind']=='zoom':
                key=int(frame.physical_address);previous=self.inspection.reading.canvases.get(key)
                cached=(self.canvas_views.get(key)==('inspection',generation,payload['token'])
                    and previous is not None and previous[0]==payload['token'])
                payload=dict(payload,reading_background_cached=cached,reading_previous_roi=previous[1] if cached else None)
            reading_roi=render_inspection(canvas,payload,self.ui_assets)
            with self.condition:
                current=(generation==self.ui_generation and self.inspection.token==payload['token'] and self.inspection.kind==payload['kind'])
            if not current:return False
            key=int(frame.physical_address);self.canvas_views[key]=('inspection',generation,payload['token'])
            if payload['kind']=='zoom':
                with self.condition:
                    if self.inspection.token==payload['token']:
                        cache=self.inspection.reading.canvases;cache[key]=(payload['token'],reading_roi)
                        if len(cache)>16:self.inspection.reading.canvases={key:cache[key]}
            self.layouts[key]=(None,None)
            composed=time.perf_counter();composed_cpu=time.thread_time()
            self.loop.run_until_complete(self._submit(frame));submitted=time.perf_counter()
            if payload['kind']=='album' and self.media is not None:
                with self.condition:self.media.presented_locked(payload)
            checkpoint('UI_INSPECTION_PRESENTED',generation=generation,kind=payload['kind'],
                points=len(payload['points']),event_only=True,physical_scan_time_measured=False,
                compose_s=composed-began,compose_thread_cpu_s=composed_cpu-cpu,vdma_submit_s=submitted-composed)
            return True
        finally:canvas=None;frame=None
    def _geometry_overlay(self,raw,meta,now):
        empty=dict(quad=(),kind='NONE',reason='raw_only',source_sequence=None,age_ms=None)
        if raw is None or meta.get('ui_view')=='rectified' or meta.get('display_mode')=='RAW_ONLY':return empty
        sequence=meta.get('input_camera_sequence',meta.get('camera_sequence',-1))
        ready=meta.get('input_capture_ready_at',meta.get('capture_ready_at',0.))
        continuity=bool(meta.get('continuity_output')) and valid_continuity(meta,now)
        if (sequence==meta.get('camera_sequence') and (meta.get('state') in ('CURRENT','MANUAL') or continuity)
                and not meta.get('frozen_output') and now-float(ready)<=.5
                and len(meta.get('corners',()))==4):
            empty.update(quad=meta['corners'],kind='CONTINUITY' if continuity else 'CURRENT',
                reason='current_frame_continuity' if continuity else 'completed_pair',source_sequence=sequence,
                age_ms=max(0.,now-float(meta['verified_at']))*1000. if continuity else 0.)
        return empty
    def _live_diagnostic(self,reason,meta,left,right,probe,physical_address=None):
        signature=(meta.get('ui_view','compare'),meta.get('ui_generation'),meta.get('hybrid_epoch'),
            left is not None,right is not None)
        key=(reason,signature)
        if key==getattr(self,'_live_diagnostic_key',None):return
        self._live_diagnostic_key=key;self._live_diagnostic_signature=signature
        now=time.perf_counter()
        if now-getattr(self,'_live_diagnostic_at',-1e9)<.25 and reason!='empty_canvas_suppressed':
            self._live_diagnostic_suppressed=getattr(self,'_live_diagnostic_suppressed',0)+1;return
        suppressed=getattr(self,'_live_diagnostic_suppressed',0)
        self._live_diagnostic_at=now;self._live_diagnostic_suppressed=0
        checkpoint('DISPLAY_LIVE_EVENT',reason=reason,index=meta.get('index'),state=meta.get('state'),
            ui_generation=meta.get('ui_generation'),hybrid_epoch=meta.get('hybrid_epoch'),
            hybrid_phase=meta.get('hybrid_phase'),camera_sequence=meta.get('camera_sequence'),
            input_camera_sequence=meta.get('input_camera_sequence',meta.get('camera_sequence')),
            left_present=left is not None,right_present=right is not None,
            preview_only=bool(meta.get('preview_only')),continuity_output=bool(meta.get('continuity_output')),
            continuity_from_owner_wait=bool(meta.get('continuity_from_owner_wait')),
            capture_ready_at=meta.get('capture_ready_at'),input_capture_ready_at=meta.get('input_capture_ready_at'),
            physical_address=physical_address,pixel_probe_bgr=probe,submitted=reason=='canvas_submitted',
            suppressed_transitions=suppressed,physical_scan_time_measured=False)
    def _profile_state(self,now):
        view=getattr(self,'profile_overlay',None)
        if view is not None and view.get('busy'):
            controller=getattr(self,'profile_controller',None)
            if controller is not None and controller.expire(now):view=self.profile_overlay
        return view

    def _profile_idle(self,now):
        """Owner-only UI during STREAMOFF. Never replay or copy camera pixels."""
        view=self._profile_state(now)
        failed=bool(view and view.get('phase')=='failed')
        if (not view or (not view.get('busy') and not failed) or view.get('generation')!=self.ui_generation
                or self.ui_view not in ('compare','rectified') or self.ui_assets is None
                or now<getattr(self,'_profile_next_redraw',0.)):return False
        if failed and getattr(self,'_profile_failure_presented',None)==view['serial']:return False
        # Normal queued output/current preview always gets priority. Snapshot
        # metadata under the condition, but NEVER submit while holding it.
        with self.condition:
            if self.stop or self.pending is not None or self.ui_dirty or self.inspection.kind:return False
            preview=getattr(self,'live_preview',None)
            page=self.ui_view;generation=self.ui_generation
        value=preview.snapshot() if preview is not None else None
        if value is not None and value[4]==generation and 0.<=now-value[1]<=.5:
            return False
        frame,canvas=self._acquire_canvas()
        try:
            canvas[:]=(32,28,24) # explicit neutral switching UI, not a blank live canvas
            canvas[:72]=self.ui_assets.headers[page]
            from v120_image_settings import render_overlay
            render_overlay(canvas,dict(view,timeout_notice=True) if failed else view,self.ui_assets)
            key=int(frame.physical_address)
            self.canvas_views[key]=(page,generation,'profile_wait',view['serial'])
            self.layouts[key]=(None,None)
            with self.condition:
                if generation!=self.ui_generation or self.stop or self.pending is not None:return False
            self.loop.run_until_complete(self._submit(frame))
            self._profile_next_redraw=now+.1
            if failed:self._profile_failure_presented=view['serial']
            if getattr(self,'_profile_wait_logged',None)!=view['serial']:
                self._profile_wait_logged=view['serial']
                checkpoint('CAMERA_PROFILE_WAIT_PRESENTED',generation=generation,
                    request_serial=view['serial'],target=view['target'],max_ui_hz=10,
                    camera_frame_replayed=False,physical_scan_time_measured=False)
            return True
        finally:canvas=None;frame=None

    def _show(self,raw,out,meta):
        view=meta.get('ui_view','compare');generation=int(meta.get('ui_generation',0))
        if self.ui_assets is not None and generation!=self.ui_generation:return False
        profile_view=getattr(self,'profile_overlay',None);profile_controller=None
        if profile_view is not None and profile_view.get('busy'):
            profile_view=self._profile_state(time.perf_counter())
            profile_controller=getattr(self,'profile_controller',None) if profile_view.get('busy') else None
        paused=False
        preview_only=bool(meta.get('preview_only'))
        if meta.get('display_mode')=='RAW_ONLY':out=None
        result_valid=(out is not None and (meta.get('state') in ('CURRENT','MANUAL') or valid_continuity(meta,time.perf_counter()))
            and not meta.get('frozen_output') and time.perf_counter()-float(meta.get('capture_ready_at',0.))<=.5)
        if view in ('compare','rectified') and not result_valid:
            out=None;meta=dict(meta,corners=(),hybrid_valid_fps=0.)
        if view in ('compare','rectified') and raw is None and out is None:
            preview=getattr(self,'live_preview',None)
            value=preview.snapshot() if preview is not None else None
            if value is not None and value[4]==generation and -.02<=time.perf_counter()-value[1]<=.5:
                sequence,ready,raw,color,_=value
                meta=dict(meta,input_camera_sequence=sequence,input_capture_ready_at=ready,color_mode=color,
                    preview_only=True,display_mode='RAW_ONLY',corners=(),candidate_corners=())
            elif getattr(self,'_live_pixels_seen',False) or meta.get('state') not in ('STARTING','INITIALIZING'):
                self._live_diagnostic('empty_canvas_suppressed',meta,None,None,None)
                return False
        same_frame=(raw is not None and out is not None and
            meta.get('input_camera_sequence',meta.get('camera_sequence'))==meta.get('camera_sequence'))
        if not same_frame:meta=dict(meta,corners=(),candidate_corners=())
        display_mode=meta.get('display_mode') or ('PAIRED' if same_frame else 'RAW_ONLY' if out is None else 'RECTIFIED')
        overlay=self._geometry_overlay(raw,meta,time.perf_counter()) if out is not None else dict(
            quad=(),kind='NONE',reason='no_valid_pixels',source_sequence=None,age_ms=None)
        began=time.perf_counter();cpu=time.thread_time()
        if profile_controller is not None and (raw is not None or result_valid):
            profile_view=profile_controller.frame_view(profile_view,generation,
                raw.shape if raw is not None else self.input_shape,
                meta.get('input_capture_ready_at',meta.get('capture_ready_at')),
                meta.get('input_camera_sequence',meta.get('camera_sequence')),began)
        frame,canvas=self._acquire_canvas(view if meta['state']=='STARTING' else None,generation)
        acquired=time.perf_counter();acquired_cpu=time.thread_time()
        try:
            h,w=self.mode[1],self.mode[0];mid=w//2
            # Before acquisition (and after complete loss), show live input
            # even on the result-only page so placement remains visible.
            single=view=='rectified' and out is not None
            if single:raw=None
            left=native_display_rect(self.mode,self._fit_shape(self.mode,raw.shape[:2]),0) if raw is not None else None
            live_wait=out is None and view in ('compare','rectified')
            if out is not None and single:
                oh,ow=out.shape[:2]
                if ow>w or oh>h-64:raise ValueError('Rectified native image exceeds HDMI canvas')
                right=((w-ow)//2,36+(h-64-oh)//2,ow,oh)
            else:right=native_display_rect(self.mode,out.shape[:2],1) if out is not None else None
            fixed_status=bool(self.ui_assets is not None and hasattr(self.ui_assets,'live_ui_parts') and view in ('compare','rectified'))
            live_ui=None
            if fixed_status:
                live_ui=getattr(self,'live_status',None)
                if live_ui is None:self.live_status=live_ui=LiveUI()
                # Keep native output dimensions. Only move a tall portrait down
                # past the fixed information strip; bottom controls begin640.
                if right is not None:
                    rx,ry,rw,rh=right;right=(rx,max(124,ry),rw,rh)
            key=int(frame.physical_address);old=self.layouts.get(key)
            page_token=(view,generation,out is not None) if view=='snapshot' else (
                view,generation,self.target_notice,'fixed_live')
            if profile_view is not None and (profile_view.get('busy') or profile_view.get('open')):
                # The settings rectangle does not move while dragging. A new
                # numeric candidate must not clear the whole HDMI canvas.
                token=('settings_open' if profile_view.get('open') and not profile_view.get('busy')
                       and 'settings_tab' in profile_view else profile_view['revision'])
                page_token=(view,generation,self.target_notice,token,'fixed_live')
            startup_phase=meta.get('ui_startup_phase');startup_action=None
            if startup_phase in ('preparing','placement'):
                startup_action=('confirmed' if meta.get('placement_confirmed') or not meta.get('placement_required') else 'confirm')
            elif startup_phase=='acquiring':startup_action='acquiring'
            if startup_action is not None:page_token=page_token+(startup_action,)
            page_changed=self.canvas_views.get(key)!=page_token
            if old is None or page_changed:canvas.fill(0)
            else:
                for prior,new in zip(old,(left,right)):
                    if prior is not None and prior!=new:
                        x,y,rw,rh=prior;canvas[y:y+rh,x:x+rw].fill(0)
            # Repaint text backgrounds (including antialias fringes), and only
            # changed image regions, rather than clearing720p every submission.
            ui_began=time.perf_counter();ui_header_restore_s=0.
            if self.ui_assets is None:canvas[:36].fill(0)
            else:
                if page_changed:
                    canvas[:72]=(self.ui_assets.snapshot_busy if view=='snapshot' and out is None
                        else self.ui_assets.headers[view])
                    if startup_action is not None:
                        canvas[:72,1000:1280]=self.ui_assets.placement_controls[startup_action]
                    if view in ('compare','rectified'):
                        canvas[:72,380:580]=self.ui_assets.refind_controls[
                            'preparing' if startup_phase=='preparing' else 'ready']
                        if self.target_notice!='idle' and not fixed_status:
                            canvas[78:118,:640]=self.ui_assets.target_hints[(view,self.target_notice)]
                    ui_header_restore_s=time.perf_counter()-ui_began
                # Cached top-left return pixels are not touched on warm buffers.
                label_end=1000 if view in ('compare','rectified','snapshot') else w
                # V82 cached touch controls occupy the header; dynamic labels
                # stay in the existing footer and never overwrite hit targets.
                self.canvas_views[key]=page_token
                if len(self.canvas_views)>16:self.canvas_views={key:page_token}
            if self.ui_assets is None:self.canvas_views[key]=page_token
            if not fixed_status:canvas[h-28:].fill(0)
            clear_end=time.perf_counter();clear_cpu=time.thread_time()
            raw_backend='none';input_convert_s=0.;output_convert_s=0.;scale_s=0.
            left_detail={};right_detail={};left_panel_s=right_panel_s=0.;left_cpu_s=right_cpu_s=0.
            corner_draw_s=0.;corner_draw_cpu_s=0.
            if raw is not None:
                x,y,rw,rh=left;t=time.perf_counter();tc=time.thread_time()
                # Startup must not synchronously compile the library whose
                # readiness it is trying to show. Only INITIALIZING can use
                # this temporary path; normal display remains unchanged.
                startup_fallback=False
                if meta['state']=='INITIALIZING':
                    from v64_io import _LIB as io_library
                    startup_fallback=io_library is None
                if startup_fallback:
                    if meta['color_mode']==0:
                        cv2.cvtColor(raw,cv2.COLOR_YUV2BGR_YUY2,dst=canvas[y:y+rh,x:x+rw])
                    else:
                        from v31_pixels import model_bgr
                        canvas[y:y+rh,x:x+rw]=model_bgr(raw)
                else:
                    #   ⭐ 2026-10-28：源图比面板大（800x600 放进 640x480 槽）时，
                    #      **在画的时候缩**。
                    #      ① 优先 `FusedDisplay.scale()`：800x600→640x480 恰好是 5:4，
                    #         命中原生 **NEON 5:4 多相**分支，直接写进 canvas。
                    #         实测左预览 **94 → 39.8 ms**，显示 7 → 14 fps。
                    #      ② 退回通用 YUYV 预览缩放（标量双线性/最近邻，实测 92~94 ms）。
                    #      ③ 再退回居中裁剪（颜色仍正确，只是视野变小）。
                    scaled_detail=None
                    if raw.shape[:2]!=(rh,rw):
                        #   ⭐ 2026-10-31：后端由 P11_PREVIEW_SCALE 选（fused/nearest/crop）。
                        #      crop 直接跳到最后那条居中裁剪，不碰多相也不碰最近邻。
                        if self._preview_scale=='fused':
                            if self._fused is None and not self._fused_failed:
                                try:
                                    from v71_display import FusedDisplay
                                    self._fused=FusedDisplay()
                                except BaseException:
                                    self._fused=None;self._fused_failed=True
                            if self._fused is not None:
                                try:
                                    scaled_detail=self._fused.scale(0,raw,int(meta['color_mode']),canvas,left)
                                except BaseException:
                                    scaled_detail=None
                        if scaled_detail is not None:
                            raw_backend=scaled_detail['backend']
                        elif self._preview_scale=='crop':
                            ih,iw=raw.shape[:2];y0=max(0,(ih-rh)//2);x0=max(0,(iw-rw)//2)
                            yuyv_bgr_into(np.ascontiguousarray(raw[y0:y0+rh,x0:x0+rw]),
                                meta['color_mode'],canvas,left)
                            raw_backend='crop_center_fallback'
                        else:
                            from v31_native import yuyv_preview_into
                            if self._scaled is None or self._scaled.shape[:2]!=(rh,rw):
                                self._scaled=np.empty((rh,rw,3),np.uint8)
                            if yuyv_preview_into(raw,int(meta['color_mode']),self._scaled,
                                    fast=self._preview_nearest):
                                canvas[y:y+rh,x:x+rw]=self._scaled
                                raw_backend=('native_YUYV_to_BGR_scaled_nearest' if self._preview_nearest
                                    else 'native_YUYV_to_BGR_scaled')
                            else:
                                ih,iw=raw.shape[:2];y0=max(0,(ih-rh)//2);x0=max(0,(iw-rw)//2)
                                yuyv_bgr_into(np.ascontiguousarray(raw[y0:y0+rh,x0:x0+rw]),
                                    meta['color_mode'],canvas,left)
                                raw_backend='crop_center_fallback'
                    else:
                        yuyv_bgr_into(raw,meta['color_mode'],canvas,left)
                        raw_backend='native_YUYV_to_BGR_1to1'
                input_convert_s=time.perf_counter()-t
                if startup_fallback:
                    raw_backend='startup_OpenCV_or_model_CSC';scaled_detail=None
                left_detail=dict(direct=True,resize_used=False,crop_used=False,backend=raw_backend,
                    source_shape=list(raw.shape),destination_rect=list(left),
                    polyphase_5_4_used=bool(scaled_detail and scaled_detail.get('polyphase_5_4_used')),
                    scale_native_s=(scaled_detail or {}).get('native_wall_s',0.),
                    scale_backend_all=(scaled_detail or {}).get('backend'))
                left_panel_s=time.perf_counter()-t;left_cpu_s=time.thread_time()-tc
                t=time.perf_counter();tc=time.thread_time()
                corners=overlay['quad']
                #   ⚠️ 2026-10-28（现场：绿框位置/大小都不对，还拖出黄绿长条）：
                #      四角是【源图坐标】（800x600），而左画面是【缩放后】的 640x480。
                #      直接 `points+=矩形原点` 按 1:1 画 ⇒ 框比实际大 1.25 倍、溢出到右半边。
                #      640x480 时系数恒为 1，行为与改动前完全一致。
                _sx,_sy=rw/float(raw.shape[1]),rh/float(raw.shape[0])
                if len(corners)==4:
                    points=np.asarray(corners,np.float32)
                    if (rw,rh)!=tuple(raw.shape[1::-1]):
                        points=np.stack([points[:,0]*_sx,points[:,1]*_sy],axis=1)
                    points=points+np.array([x,y],np.float32)
                    color=((0,210,255) if overlay['kind']=='REFERENCE' else
                        (255,200,70) if meta['state'] in ('MANUAL','MANUAL_HELD') else (0,240,0))
                    # A single colored outline preserves HELD status without
                    # dozens of Python/NumPy/cv2.line calls on each frame.
                    cv2.polylines(canvas,[np.rint(points).astype(np.int32)],True,color,2,cv2.LINE_AA)
                candidate=meta.get('candidate_corners',())
                if (not corners and len(candidate)==4 and
                        0<=time.perf_counter()-meta.get('candidate_ready_at',0.)<=.9):
                    cq=np.asarray(candidate,np.float32)
                    if (rw,rh)!=tuple(raw.shape[1::-1]):
                        cq=np.stack([cq[:,0]*_sx,cq[:,1]*_sy],axis=1)
                    points=np.rint(cq+np.array([x,y],np.float32)).astype(np.int32)
                    cv2.polylines(canvas,[points],True,(70,70,255),2,cv2.LINE_AA)
                corner_draw_s=time.perf_counter()-t;corner_draw_cpu_s=time.thread_time()-tc
            if out is not None:
                x,y,rw,rh=right;t=time.perf_counter();tc=time.thread_time()
                bgra_bgr_into(out,canvas,right)
                output_convert_s=time.perf_counter()-t
                right_detail=dict(direct=True,resize_used=False,crop_used=False,backend='native_BGRX_to_BGR_1to1',
                    source_shape=list(out.shape),destination_rect=list(right),polyphase_5_4_used=False)
                right_panel_s=time.perf_counter()-t;right_cpu_s=time.thread_time()-tc
            if live_wait and self.ui_assets is not None and view in ('compare','rectified') and not fixed_status:
                # Small cached status in the right region; no page/progress overlay.
                canvas[78:106,800:1120]=self.ui_assets.status_badges['SEARCHING']
            elif self.ui_assets is not None and view in ('compare','rectified') and not fixed_status:
                canvas[78:106,800:1120].fill(0)
            self.layouts[key]=(left,right)
            if len(self.layouts)>16:self.layouts={key:(left,right)}
            now=time.perf_counter()
            while self.submit_times and self.submit_times[0]<now-2.:self.submit_times.popleft()
            times=list(self.submit_times)
            rate=(len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0.
            with self.condition:
                while self.current_times and self.current_times[0]<now-2.:self.current_times.popleft()
                # Fixed2s includes CURRENT only; decays during lost/held updates.
                current_rate=len(self.current_times)/2.
            age=max(0.,now-meta.get('capture_ready_at',now))*1000
            verified=float(meta.get('verified_at',0.));h_age=max(0.,now-verified)*1000 if verified>0 else None
            label_x=184 if self.ui_assets is not None else 8
            if not single and self.ui_assets is None:
                label=('ORIGINAL seq=%d' if view=='snapshot' else 'INPUT seq=%d')%meta.get('camera_sequence',-1)
                cv2.putText(canvas,label,(label_x,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
            heading=('SNAPSHOT '+('READY' if out is not None else 'CAPTURING')) if view=='snapshot' else 'RECTIFIED '+meta['state']
            if self.ui_assets is None:cv2.putText(canvas,heading,(label_x if single else mid+8,24),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1,cv2.LINE_AA)
            status='CORR %.1f | DISP %.1f | CUR %.1f | CAP %.0fms | H %s'%(meta.get('correction_fps',0.),rate,current_rate,age,
                ('%.0fms'%h_age) if h_age is not None and meta['state'] in ('CURRENT','HELD') else '--')
            if meta.get('v86_motion_authority'):
                status=status.replace('CUR ', 'TRACK ')
            if view=='snapshot':
                status=('SINGLE FRAME | seq=%d | RECAPTURE OR RETURN'%meta.get('camera_sequence',-1)
                    if out is not None else 'SINGLE FRAME | WAITING FOR VERIFIED CORNERS')
            if meta.get('admission_mode')=='manual':
                status=self.manual_status_template%(meta.get('manual_tracking',''),
                    meta.get('manual_fps',0.),rate,('MOTION WATCH / AUTO RESUME' if meta.get('manual_fixed_watch') else 'RECALIBRATE AFTER MOVING')
                    if meta.get('manual_tracking')=='FIXED' else 'FULL FB TRACK / FINITE HOLD')
                if meta.get('manual_tracking')=='SNAPSHOT':status='MANUAL SINGLE FRAME | RECAPTURE, RECALIBRATE OR RETURN'
            if meta['state']=='INITIALIZING':
                status='SETUP %.0fs | AUTO LOCATE WHEN READY | RAW VIEW ACTIVE'%meta.get('native_setup_elapsed_s',0.)
            elif meta['state']=='PLACEMENT':status='READY | AUTOMATIC CURRENT-FRAME LOCALIZATION'
            status_x=8
            hybrid=hybrid_footer(meta,out is not None,rate) if 'correction_origin' in meta and not fixed_status else None
            if hybrid is not None:status=hybrid[1]
            if self.ui_assets is not None and not fixed_status:
                if hybrid is not None:canvas[h-28:,:320]=hybrid[0]
                else:
                    state=meta['state'] if meta['state'] in self.ui_assets.status_badges else 'SEARCHING'
                    if state=='MANUAL' and meta.get('manual_tracking')=='FIXED':state='MANUAL_FIXED'
                    canvas[h-28:,:320]=self.ui_assets.status_badges[state]
                status_x=326
            if fixed_status:
                live_ui.paint(canvas,self.ui_assets,meta,out is not None,self,now,key,force=page_changed)
            else:cv2.putText(canvas,status,(status_x,h-9),cv2.FONT_HERSHEY_SIMPLEX,.40,(255,255,255),1,cv2.LINE_AA)
            if self.ui_assets is not None and generation!=self.ui_generation:
                return False
            if self.ui_assets is not None and out is not None and not paused and self.inspection.zoom_requested==int(meta.get('ui_generation',-1)):
                from v82_interaction import render_inspection
                x,y,rw,rh=right
                with self.condition:
                    self.inspection.open_zoom_locked(canvas[y:y+rh,x:x+rw],meta)
                    payload=self.inspection.payload_locked()
                if payload is not None:
                    render_inspection(canvas,payload,self.ui_assets)
                    self.canvas_views[key]=('inspection',payload['generation'],payload['token']);self.layouts[key]=(None,None)
            if self.media is not None:
                if not preview_only:self.media.capture_from_output(out,meta)
                if self.inspection.kind is None:self.media.render_live(canvas,key,page_changed)
                with self.condition:
                    if self.media.active:return False
            feedback=getattr(self,'_feedback_live',None)
            if feedback is not None:feedback(meta,out is not None)
            # Probe only on a display-mode/epoch transition, never scan/copy an
            # image. Pixel reads must precede official VDMA ownership transfer.
            probe=None
            signature=(view,generation,meta.get('hybrid_epoch'),left is not None,right is not None)
            if signature!=getattr(self,'_live_diagnostic_signature',None):
                probe=[]
                for rect in (left,right):
                    if rect is None:probe.append(None);continue
                    x,y,rw,rh=rect
                    probe.append([canvas[y+rh//2,x+rw//2].tolist(),canvas[y+rh//3,x+rw//3].tolist()])
            #   相机输入档位弹窗：画在最终提交前，盖在左右两幅画面之上。
            #   ⚠️⚠️ 变量名**不能叫 `overlay`** —— 本方法后面还要用同名变量引用
            #      `v114_geometry_overlay` 的四角叠加字典（`overlay['kind']` / `['quad']`）。
            #      2026-10-29 现场就是这里把 `overlay` 覆盖成档位视图 ⇒
            #      `KeyError: 'kind'`，主界面一点"校正"整场崩。
            #   ⚠️ 可见性看**当前页面**，不看 `profile_overlay['visible']` ——
            #      那个标志只在 `publish()` 时刷新，而 `publish()` 只在开/关面板时调，
            #      上板实测：进实时页后它还是构造时的 home 值 ⇒ 按钮一次没画出来。
            if profile_view is not None and view in ('compare','rectified'):
                try:
                    from v120_image_settings import render_overlay
                    render_overlay(canvas,profile_view,self.ui_assets)
                except BaseException as exc:
                    self.profile_overlay=None
                    checkpoint('CAMERA_PROFILE_RENDER_FAILED',error=str(exc)[:400])
            composed=time.perf_counter();composed_cpu=time.thread_time();polls=self.loop.run_until_complete(self._submit(frame));end=time.perf_counter()
            if live_ui is not None:live_ui.rate.observe(meta,end,result_valid and out is not None)
            if profile_controller is not None and profile_view.get('complete'):
                profile_controller.submitted(profile_view,generation,
                    meta.get('input_capture_ready_at',meta.get('capture_ready_at')),
                    meta.get('input_camera_sequence',meta.get('camera_sequence')))
            if result_valid and out is not None:
                settings=getattr(self,'profile_controller',None)
                if settings is not None and hasattr(settings,'sharp_submitted'):settings.sharp_submitted(meta)
            if raw is not None or out is not None:self._live_pixels_seen=True
            if probe is not None:self._live_diagnostic('canvas_submitted',meta,left,right,probe,physical_address=key)
            if meta.get('inspection_redraw'):return True
            sample=dict(index=meta['index'],camera_sequence=meta.get('camera_sequence'),state=meta['state'],epoch=meta['epoch'],
                compose_s=composed-began,compose_thread_cpu_s=composed_cpu-cpu,
                frame_acquire_s=acquired-began,frame_acquire_thread_cpu_s=acquired_cpu-cpu,
                clear_layout_s=clear_end-acquired,clear_layout_thread_cpu_s=clear_cpu-acquired_cpu,
                left_panel_s=left_panel_s,left_panel_thread_cpu_s=left_cpu_s,
                right_panel_s=right_panel_s,right_panel_thread_cpu_s=right_cpu_s,
                panel_native_details=dict(left=left_detail,right=right_detail),corner_draw_s=corner_draw_s,corner_draw_thread_cpu_s=corner_draw_cpu_s,
                held_outline_backend='single_polylines',
                other_compose_s=max(0.,composed-clear_end-left_panel_s-right_panel_s-corner_draw_s),
                current_display_fps_2s=current_rate,display_rate_window_s=2.,
                output_display_fps_3s=live_ui.rate.fps(end) if live_ui is not None else None,
                display_backend='native_direct_color_convert_1to1',display_frontend_version=79,
                capture_age_ms=age,H_age_ms=h_age,
                ui_view=view,ui_generation=generation,ui_header_restore_s=ui_header_restore_s,
                display_scale_enabled=False,display_crop_enabled=False,native_substage_times_available=False,
                input_convert_s=input_convert_s,output_convert_s=output_convert_s,scale_s=scale_s,
                split_conversion_times_available=True,
                conversion_timing_scope='direct conversion wrappers; no resampling; native-only substage timers unavailable',
                vdma_submit_thread_cpu_s=time.thread_time()-composed_cpu,
                vdmasubmit_polls=polls,vdma_submit_s=end-composed,submitted_at=end,display_thread_cpu_s=time.thread_time()-cpu,
                capture_to_submit_s=end-meta.get('capture_ready_at',end),same_frame=same_frame,input_backend=raw_backend,
                input_camera_sequence=meta.get('input_camera_sequence',meta.get('camera_sequence')),
                input_capture_ready_at=meta.get('input_capture_ready_at',meta.get('capture_ready_at')),
                input_capture_age_ms=max(0.,end-meta.get('input_capture_ready_at',meta.get('capture_ready_at',end)))*1000.,
                result_camera_sequence=meta.get('camera_sequence') if out is not None else None,
                preview_only=preview_only,
                overlay_drawn=bool(raw is not None and len(overlay['quad'])==4),
                overlay_kind=overlay['kind'],overlay_reason=overlay['reason'],
                overlay_source_sequence=overlay['source_sequence'],overlay_age_ms=overlay['age_ms'],
                overlay_epoch=overlay.get('epoch'),
                display_mode=display_mode,pair_reason=meta.get('pair_reason'),
                paired_sequence=meta.get('camera_sequence') if display_mode=='PAIRED' and out is not None else None,
                pair_timeout_ms=meta.get('pair_timeout_ms'),pair_stall_ms=meta.get('pair_stall_ms'),
                pair_interarrival_ms=meta.get('pair_interarrival_ms'),pair_entry_regression_ms=meta.get('pair_entry_regression_ms'),
                continuity_output=bool(out is not None and meta.get('continuity_output')),
                continuity_age_s=max(0.,end-float(meta.get('verified_at',end))) if meta.get('continuity_output') else None,
                ai_mode_locked=meta.get('ai_mode_locked'),ai_target_acquired=meta.get('ai_target_acquired'),
                display_hold=paused,
                layout_generation=int(meta.get('layout_generation',0)),orientation=meta.get('orientation'))
            generation=sample['layout_generation']
            if out is not None and generation>self.last_submitted_layout:
                if meta.get('switch_requested_at') is not None:sample['direction_to_submit_s']=end-meta['switch_requested_at']
                self.last_submitted_layout=generation
            snapshot_receipt=None;layout_receipt=None
            with self.condition:
                self.submitted+=int(out is not None and not preview_only);self.panels_submitted+=int(raw is not None and not paused)
                self.unique_current+=int(out is not None and meta['state']=='CURRENT' and not preview_only)
                if raw is not None or out is not None:self.submit_times.append(end)
                if out is not None and not preview_only and meta['state']=='CURRENT' and meta['epoch']==self.epoch:self.current_times.append(end)
                self.samples.append(sample)
                preview=getattr(self,'live_preview',None)
                if display_mode=='RAW_ONLY' and raw is not None and preview is not None and preview.active():
                    preview.pairing.raw_displayed(meta.get('input_capture_ready_at',meta.get('capture_ready_at',end)))
                # Retain a reference to the already owned source; no pixel copy.
                self.tap_source=(raw,dict(meta,camera_sequence=meta.get('input_camera_sequence',meta.get('camera_sequence')),
                    capture_ready_at=meta.get('input_capture_ready_at',meta.get('capture_ready_at'))),left,end)
                stats=self.epoch_stats.setdefault(meta['epoch'],dict(submitted=0,current=0,panels=0,replaced=0,dropped=0))
                stats['submitted']+=int(out is not None and not preview_only);stats['current']+=int(out is not None and meta['state']=='CURRENT' and not preview_only)
                stats['panels']+=int(raw is not None and not paused)
                if paused:stats['display_hold_submissions']=stats.get('display_hold_submissions',0)+1
                if raw is not None or out is not None:stats['last_submitted_at']=end
                command=self.ui_layout_pending
                if (command is not None and meta['state']!='STARTING' and
                        (command[0],command[1])==(int(meta.get('ui_generation',0)),view)):
                    layout_receipt=dict(page=view,generation=command[0],layout_only=True,
                        request_to_submit_s=end-command[2],camera_restarted=False,tracker_reinitialized=False,
                        same_frame=True,index=meta['index'],camera_sequence=meta.get('camera_sequence'),
                        physical_scan_time_measured=False)
                    self.ui_layout_pending=None
                if (view=='snapshot' and raw is not None and out is not None and meta['state'] in ('CURRENT','MANUAL') and
                        int(meta.get('ui_generation',0))==self.ui_generation):
                    self.frozen_generation=self.ui_generation;self.snapshots_frozen+=1
                    snapshot_receipt=dict(generation=self.ui_generation,index=int(meta['index']),
                        camera_sequence=int(meta['camera_sequence']),submitted_at=end,
                        capture_to_submit_s=end-meta.get('capture_ready_at',end),
                        paired_input=True,input_shape=list(raw.shape[:2]),layout='original_left_rectified_right',
                        output_shape=list(out.shape[:2]),vdma_submission_confirmed=True,
                        physical_panel_scan_measured=False)
                    self.snapshot_receipt=snapshot_receipt;self.condition.notify_all()
                    self.last_static_packet=(self.active_slot,out.shape[:2],dict(meta))
            if snapshot_receipt is not None:checkpoint('SNAPSHOT_HDMI_FROZEN',**snapshot_receipt)
            if layout_receipt is not None:checkpoint('UI_PAGE_PRESENTED',**layout_receipt)
            if meta['index']>=0 and (meta['index']%60==0 or end-began>.12):checkpoint('HDMI_FRAME_DETAIL',**sample)
            return True
        finally:
            canvas=None;frame=None
    def begin_measurement(self):
        with self.condition:
            self.epoch+=1;self.current_times.clear();self.submit_times.clear();self.last_submitted_layout=0
            self.epoch_stats[self.epoch]=dict(submitted=0,current=0,panels=0,replaced=0,dropped=0)
            if len(self.epoch_stats)>64:self.epoch_stats.pop(next(iter(self.epoch_stats)))
        return self.epoch
    def _raw_snapshot(self,slot):
        # Caller pins active_slot under the display condition. Producer only
        # replaces an inactive slot; the strong reference spans composition.
        value=self.raw_refs[slot]
        return self.raw_pool[slot] if value is None else value
    def _output_snapshot(self,slot,shape):
        reference=self.output_refs[slot]
        return (self.pool[slot][:shape[0]*shape[1]].reshape(*shape,4)
                if reference is None else reference.array)
    def needs_raw_source(self):
        with self.condition:
            if self.media is not None and self.media.active:return False
            return self.ui_view!='rectified' or self.inspection.kind is not None
    def offer(self,out,meta,raw=None,*,raw_owned=False,output_reference=None):
        begin=time.perf_counter();cpu=time.thread_time();lock_wait=0.;raw_s=0.;out_s=0.
        preview=getattr(self,'live_preview',None)
        if preview is not None and 'hybrid_epoch' not in meta:preview.observe_geometry(meta)
        # Display receives only fields it uses, not the nested tracker/plan tree.
        selected={k:meta.get(k) for k in ('index','camera_sequence','state','corners','color_mode',
            'verified_at','capture_ready_at','correction_fps','layout_generation','orientation',
            'ui_startup_phase','placement_required','placement_confirmed','native_setup_elapsed_s','track_reason',
            'switch_requested_at','switch_decided_at','ui_generation','candidate_corners','candidate_ready_at',
            'min_edge_support','admission_mode','manual_tracking','manual_fps','recovery_active',
            'correction_origin','hybrid_phase','hybrid_epoch','frozen_output','hybrid_valid_fps','hybrid_trigger','tracking_engine','corner_source','target_cycle_state',
            'recovery_round','recovery_from_ai','recovery_retry_after_s',
            'continuity_output','continuity_deadline','continuity_age_s','continuity_epoch',
            'ai_mode_locked','ai_target_acquired','manual_reference_v17','sharp_receipt','light_receipt',
            'target_selection_proof','target_selection_failed') if k in meta}
        if (self.ui_view in ('compare','rectified') and
                ((selected.get('state') not in ('CURRENT','MANUAL') and not valid_continuity(selected,time.perf_counter()))
                    or selected.get('frozen_output'))):
            out=None;selected.update(state='LOST',corners=(),hybrid_valid_fps=0.)
        with self.condition:
            lock_wait+=time.perf_counter()-begin
            if self.error is not None:raise self.error
            if self.stop:raise RuntimeError('HDMI already stopped')
            if self.inspection.kind is not None:
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=time.perf_counter()-begin,display_raw_copy_s=0.,display_output_copy_s=0.,inspection_display_paused=True)
                return 0.
            view=self.ui_view;generation=self.ui_generation
            if self.ui_assets is not None and (view=='home' or selected.get('ui_generation')!=generation):
                self.ui_discarded+=1
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=lock_wait,display_raw_copy_s=0.,display_output_copy_s=0.,ui_offer_discarded=True)
                return 0.
            selected.update(ui_view=view,ui_generation=generation)
            preview=getattr(self,'live_preview',None)
            if (preview is not None and preview.active() and
                    preview.pairing.rejects(selected,raw is not None,out is not None,time.perf_counter())):
                self.ui_discarded+=1;self.last_offer_timing=dict(stale_or_duplicate_pair_discarded=True)
                return 0.
            if view=='snapshot' and self.frozen_generation==generation:
                raise RuntimeError('Single-frame page is already frozen; return before recapture')
            if self.copying_slot is not None:raise RuntimeError('HDMI paired snapshots require one producer')
            self.offered+=1;selected['epoch']=self.epoch
            if self.pending is not None:
                old=self.pending;self.pending=None;self.replaced+=1
                self.epoch_stats.setdefault(old[2]['epoch'],dict(submitted=0,current=0,panels=0,replaced=0,dropped=0))['replaced']+=1
            slot=next((i for i in range(2) if i!=self.active_slot),None)
            if slot is None:
                self.dropped+=1
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=lock_wait,display_raw_copy_s=0.,display_output_copy_s=0.)
                return 0.
            self.copying_slot=slot
            previous_output=self.output_refs[slot];self.output_refs[slot]=None
            if previous_output is not None:previous_output.release()
        borrowed_output=None
        try:
            # This reserved slot is absent from pending and cannot be selected
            # by the display worker. Expensive copies occur outside its lock.
            if raw is not None and (raw.shape!=self.raw_pool[slot].shape or raw.dtype!=np.uint8):raise ValueError('HDMI raw snapshot shape mismatch')
            if raw_owned and raw is not None and (type(raw) is not np.ndarray or not raw.flags.owndata or
                    raw.flags.writeable or not raw.flags.c_contiguous):
                raise ValueError('Owned HDMI raw snapshot must be standalone readonly ordinary-RAM ndarray')
            shape=()
            if out is not None:
                if raw is None and view!='rectified':
                    # A live layout switch may race one already prepared frame.
                    # Drop it; the next prepare observes the new raw requirement.
                    self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                        display_offer_lock_wait_s=lock_wait,display_raw_copy_s=0.,display_output_copy_s=0.,
                        ui_offer_discarded=True,raw_required_after_layout_switch=True)
                    return time.perf_counter()-begin
                if out.ndim!=3 or out.shape[2]!=4 or out.size>self.pool[slot].size:raise ValueError('HDMI output snapshot capacity mismatch')
                shape=out.shape[:2]
            copy_raw=None if view=='rectified' and out is not None else raw
            selected['has_raw_snapshot']=copy_raw is not None
            owned_raw=copy_raw if raw_owned else None
            # Frozen snapshots retain their ordinary-RAM copy for later zoom or
            # manual recalibration. Live output instead retains a completed CMA
            # slot until conversion into an independently owned HDMI canvas.
            if out is not None and output_reference is not None and view!='snapshot':
                borrowed_output=output_reference.retain(out)
            raw_to_copy=None if raw_owned else copy_raw
            out_to_copy=None if borrowed_output is not None else out
            if raw_to_copy is None and out_to_copy is None:
                self.copy_stats.fill(0.);raw_s=out_s=0.
            else:
                raw_s,out_s=paired_copy(self.display_lib,raw_to_copy,self.raw_pool[slot],
                    out_to_copy,self.pool[slot],self.copy_stats)
            selected['raw_snapshot_handoff']='owned_readonly_reference' if owned_raw is not None else 'no_raw' if copy_raw is None else 'copied_snapshot'
            if out is None and selected['state'] not in ('SEARCHING','LOST','STARTING','INITIALIZING','PLACEMENT'):selected['state']='WAITING'
            t=time.perf_counter()
            with self.condition:
                lock_wait+=time.perf_counter()-t
                if self.error is not None:raise self.error
                if self.stop:raise RuntimeError('HDMI stopped during snapshot copy')
                if self.inspection.kind is not None:
                    self.ui_discarded+=1
                    self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                        display_offer_lock_wait_s=lock_wait,display_raw_copy_s=raw_s,display_output_copy_s=out_s,
                        inspection_display_paused=True)
                    return time.perf_counter()-begin
                if self.ui_assets is not None and generation!=self.ui_generation:
                    self.ui_discarded+=1
                    self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                        display_offer_lock_wait_s=lock_wait,display_raw_copy_s=raw_s,display_output_copy_s=out_s,ui_offer_discarded=True)
                    return time.perf_counter()-begin
                preview=getattr(self,'live_preview',None)
                if preview is not None and preview.active():
                    mode=preview.pairing.observe(selected,copy_raw is not None,out is not None,time.perf_counter())
                    if mode=='DROP':
                        self.ui_discarded+=1
                        self.last_offer_timing=dict(stale_or_duplicate_pair_discarded=True)
                        return time.perf_counter()-begin
                    selected.update(preview.pairing.snapshot(time.perf_counter()))
                self.raw_refs[slot]=owned_raw
                self.output_refs[slot]=borrowed_output;borrowed_output=None
                self.slot_packets[slot]=(shape,selected)
                self.pending=(slot if copy_raw is not None or out is not None else None,shape,selected);self.latest_meta=selected
                self.live_last_offer_at=time.perf_counter()
                self.copying_slot=None;self.condition.notify_all()
                elapsed=time.perf_counter()-begin;self.cpu_copy_s+=elapsed
                self.last_offer_timing=dict(display_snapshot_thread_cpu_s=time.thread_time()-cpu,
                    display_offer_lock_wait_s=lock_wait,display_raw_copy_s=raw_s,display_output_copy_s=out_s,
                    display_raw_reference_handoff=owned_raw is not None,
                    display_output_reference_handoff=self.output_refs[slot] is not None,
                    display_pair_copy_native_s=float(self.copy_stats[2]),display_pair_copy_native_thread_cpu_s=float(self.copy_stats[3]))
                return elapsed
        finally:
            if borrowed_output is not None:borrowed_output.release()
            # Success already relinquished the reservation in the publish lock.
            # Only an interrupted copy needs another lock acquisition.
            if self.copying_slot==slot:
                with self.condition:
                    if self.copying_slot==slot:self.copying_slot=None;self.condition.notify_all()
    def snapshot(self,include_samples=True):
        with self.condition:
            last=self.samples[-1] if self.samples else {}
            right_frozen=bool(last.get('right_frozen') and last.get('ui_generation')==self.ui_generation and self.ui_view in ('compare','rectified'))
            result=dict(offered=self.offered,submitted=self.submitted,current_submitted=self.unique_current,
                split_panels_submitted=self.panels_submitted,replaced_pending=self.replaced,dropped=self.dropped,
                snapshot_copy_s=self.cpu_copy_s,epoch=self.epoch,epoch_stats={str(k):dict(v) for k,v in self.epoch_stats.items()},
                refresh_hz=getattr(getattr(self,'frontend',None),'detail',{}).get('refresh_hz',60),
                nominal_refresh_hz=60,display_max_fps=self.max_fps,mode=list(self.mode),memory_format='BGR24',same_frame=bool(last.get('same_frame',False)),
                transition_display_hold=bool(last.get('display_hold',False)),
                right_view_frozen=right_frozen,right_frozen_canvas_submitted=sum(v.get('right_frozen_canvas_submitted',0) for v in self.epoch_stats.values()),
                shutdown_safe=self.shutdown_safe,error=None if self.error is None else repr(self.error),
                fps_scope='unique correction and unique input panel submissions, not physical panel measurement',
                display_software_abi=7301,display_frontend_version=77,
                ui_enabled=self.ui_assets is not None,ui_view=self.ui_view,ui_generation=self.ui_generation,
                snapshot_frozen=self.ui_view=='snapshot' and self.frozen_generation==self.ui_generation,
                snapshots_frozen=self.snapshots_frozen,
                ui_home_submissions=self.ui_pages_submitted,ui_discarded_offers=self.ui_discarded,
                ui_layout_switches=self.ui_layout_switches,ui_return_feedback_submissions=self.ui_feedback_submitted,
                inspection_openings=self.inspection.opened,inspection_event_redraws=self.inspection.redraws,
                composition_backend='native_direct_color_convert_1to1',display_scale_enabled=False,display_crop_enabled=False,
                raw_snapshot_handoff='automatic immutable ordinary-RAM references; rectified live skips unused source',raw_reference_slots=2,
                output_snapshot_handoff='completed leased CMA slots for live; owned RAM copy for frozen stills',
                completed_output_slots=3,
                current_display_fps_2s=sum(t>=time.perf_counter()-2. for t in self.current_times)/2.,
                current_display_rate_scope='CURRENT-only submissions / fixed2s, warmup cleared; footer excludes submission being composed')
            preview=getattr(self,'live_preview',None)
            if preview is not None:
                result['live_preview']=dict(fallback_copies=preview.fallback_copies,
                    fallback_bytes=preview.fallback_bytes,prepared_publications=preview.prepared_publications,
                    fallback_max_fps=1./(preview.period*2),queue_capacity=1,
                    camera_consumer_added=False,hdmi_writer_added=False)
            result['input_camera_sequence']=last.get('input_camera_sequence')
            result['result_camera_sequence']=last.get('result_camera_sequence')
            if self.media is not None:result['photos']=self.media.statistics_locked()
            if include_samples:result['samples']=list(self.samples)
            return result
    def rescale_input(self, input_shape):
        """换相机档位：重算面板显示尺寸并**整体换掉** `raw_pool`。

        ⚠️ 只在两次会话之间调用（相机已关、旧会话已排空）。
        新池**先建好再原子替换引用**，显示线程下一帧自然用新池；
           旧池在显示线程丢引用后由 GC 回收，不会出现"写到已释放缓冲"。
        返回 True 表示尺寸真的变了。
        """
        h, w = (int(v) for v in input_shape)
        if (h, w) == tuple(self.input_shape):
            return False
        pool = [np.empty((h, w, 2), np.uint8) for _ in range(2)]
        shape = self._fit_shape(self.mode, (h, w))
        native_display_rect(self.mode, shape, 0)   # 放不下就在这里抛，先于替换
        with self.condition:
            self.input_shape = (h, w)
            self.display_shape = shape
            self.raw_pool = pool
            self._scaled = None                    # 旧缩放工作区尺寸已失效
            self.canvas_views.clear()
            self.layouts.clear()
        checkpoint('HDMI_INPUT_RESCALED', input_shape=[h, w],
                   display_shape=list(shape), raw_pool_rebuilt=True)
        return True

    def close(self):
        self.cancel_ui_feedback()
        if self.closed:return
        with self.condition:
            if self.target_switch is not None:self.target_switch.restore()
            self.stop=True;self.condition.notify_all()
        self.worker.join(self.timeout*2+3)
        if self.worker.is_alive():_RETAINED.append(self);raise RuntimeError('HDMI owner active; keep buffers/overlay')
        if self.media is not None:self.media.close()
        if self._fused is not None:self._fused.close();self._fused=None
        controller=getattr(self,'profile_controller',None)
        if controller is not None:controller.cancel('display_close')
        self.profile_controller=None;self.profile_overlay=None
        self.live_packet=None;self.preview_rendered=None;self.slot_packets[:]=[None,None]
        self.raw_refs[:]=[None,None]
        for reference in self.output_refs:
            if reference is not None:reference.release()
        self.output_refs[:]=[None,None]
        self.closed=True
        if self.error is not None:raise self.error
        if not self.shutdown_safe:raise RuntimeError('HDMI shutdown not proved')
