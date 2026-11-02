"""Event-owned right-view hold. Only the existing HDMI owner touches pixels."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v64_io import yuyv_bgr_into,bgra_bgr_into
from v64_hdmi_display import native_display_rect,fit_panel_shape
from v97_album import CAPTURE_RECT,ALBUM_RECT
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class HoldUnavailable(RuntimeError):pass

def load_assets(assets,root):
    value=cv2.imread(str(Path(root)/'v74_hold_badge.png'),cv2.IMREAD_COLOR)
    if value is None or value.shape!=(56,248,3):raise ValueError('Invalid hold badge')
    value.setflags(write=False);assets.hold_badge=value[:28];assets.hold_badge_small=value[28:,:48]

def inside(point,rect):
    return point is not None and rect is not None and rect[0]<=point[0]<rect[0]+rect[2] and rect[1]<=point[1]<rect[1]+rect[3]

class HoldController:
    def __init__(self,state,display):
        self.state=state;self.display=display;self.base_show=display._show
        self.handler=self.show;self.active=None;self.serial=0
        self.cleanup=None;self.clean_handler=self.acquire_clean;self.last_acquire=display._acquire_canvas
    def stop_cleanup_locked(self):
        d=self.display;record=self.cleanup
        if record is not None:
            if d._acquire_canvas==self.clean_handler:d._acquire_canvas=record['base']
            self.last_acquire=record['base'];self.cleanup=None
    def acquire_clean(self,*args,**kwargs):
        record=self.cleanup
        if record is None:return self.last_acquire(*args,**kwargs)
        frame,canvas=record['base'](*args,**kwargs);d=self.display
        with d.condition:
            if self.cleanup is record:
                key=int(frame.physical_address);patch=record['patches'].pop(key,None)
                if patch is not None:
                    rect,pixels,normal_token,hold_token=patch
                    if d.canvas_views.get(key)==hold_token:
                        x,y,w,h=rect;canvas[y:y+h,x:x+w]=pixels
                        d.canvas_views[key]=normal_token
                record['calls']+=1
                if not record['patches'] or record['calls']>=record['limit']:self.stop_cleanup_locked()
        return frame,canvas
    def current(self,session):
        d=self.display
        with d.condition:
            return self.active is session and session['generation']==d.ui_generation and session['view']==d.ui_view and not d.stop
    def begin(self,event,generation):
        d=self.display;s=self.state
        with d.condition:
            point=event.get('press')
            if point is None or point[1]<72 or inside(point,CAPTURE_RECT) or inside(point,ALBUM_RECT):return False
            if (self.active is not None or s.stopping or s.page not in ('compare','rectified') or
                    s.ticket.phase!='running' or d.ui_view!=s.page or generation!=d.ui_generation or
                    d.stop or d.error is not None or d.inspection.kind is not None or
                    d.inspection.zoom_requested is not None or d.target_switch is not None or d._show!=self.base_show):return False
            ratio=s.ratio;media=d.media
            if ratio is not None and (ratio.pending is not None or ratio.open_requested):return False
            if media is not None and (media.active or getattr(media,'capture_request',None) is not None):return False
            if not d.samples:return False
            sample=d.samples[-1]
            if sample.get('ui_generation')!=generation or sample.get('ui_view')!=s.page or sample.get('state') not in ('CURRENT','HELD','MANUAL','MANUAL_HELD'):return False
            details=sample.get('panel_native_details',{}).get('right',{})
            rect=details.get('destination_rect');shape=details.get('source_shape')
            if not rect or not shape or not inside(point,rect):return False
            self.stop_cleanup_locked()
            self.serial+=1
            session=dict(serial=self.serial,generation=generation,view=s.page,contact_id=event.get('contact_id'),
                press_rect=tuple(rect),press_index=sample.get('index'),press_sequence=sample.get('camera_sequence'),
                began=time.perf_counter(),image=None,source_index=None,source_sequence=None,source_kind=None,
                submitted=0,source_frames=0,cache_copies=0,visible=False,patches={})
            self.active=session;d._show=self.handler;d.current_times.clear()
            s.tap_contact=None
            checkpoint('UI_RIGHT_HOLD_BEGIN',generation=generation,view=s.page,contact_id=session['contact_id'],
                rect=list(rect),press_index=session['press_index'],event_only=True,left_remains_live=s.page=='compare')
        return True
    def end(self,reason):
        d=self.display
        with d.condition:
            if reason in ('page_request','touch_error','application_stop','view_changed'):self.stop_cleanup_locked()
            session=self.active
            if session is None:return
            self.active=None
            if d._show==self.handler:d._show=self.base_show
            if reason not in ('page_request','touch_error','application_stop','view_changed','display_error') and session['patches']:
                self.stop_cleanup_locked();base=d._acquire_canvas;self.last_acquire=base
                self.cleanup=dict(base=base,patches=dict(session['patches']),calls=0,limit=max(12,len(session['patches'])*4+4))
                d._acquire_canvas=self.clean_handler
            d.current_times.clear();d.condition.notify_all()
        checkpoint('UI_RIGHT_HOLD_END',generation=session['generation'],view=session['view'],reason=reason,
            duration_s=time.perf_counter()-session['began'],source_frames=session['source_frames'],
            frozen_canvas_submissions=session['submitted'],right_cache_copies=session['cache_copies'],
            source_kind=session['source_kind'],live_handler_restored=d._show==self.base_show)
    def touch(self,event,generation):
        phase=event['phase'];session=self.active
        if session is not None and phase=='press' and event.get('contact_id')!=session['contact_id']:
            self.end('new_contact');session=None
        if session is not None:
            if phase=='cancel' or phase=='release' and event.get('contact_id')==session['contact_id']:
                self.end('touch_cancelled' if phase=='cancel' else 'released')
                return dict(target='hold_view',accepted=True,consumed=True,reason='right_hold_released')
            return dict(target='hold_view',accepted=False,consumed=False,reason='right_hold_contact_owned')
        if phase=='press' and self.begin(event,generation):
            # The parser must deliver release even when the finger leaves the image.
            return dict(target='hold_view',accepted=True,consumed=False,reason='right_hold_started')
        return None
    def show(self,raw,out,meta):
        session=self.active
        if session is None:return self.base_show(raw,out,meta)
        if not self.current(session):
            self.end('view_changed');return self.base_show(raw,out,meta)
        if int(meta.get('ui_generation',-1))!=session['generation'] or meta.get('ui_view',session['view'])!=session['view']:return False
        session['source_frames']+=1
        if session['view']=='rectified' and session['visible']:return False
        was_visible=session['visible']
        try:
            if session['image'] is None and out is not None and meta.get('state') in ('CURRENT','HELD','MANUAL','MANUAL_HELD'):
                # This source is pinned by the existing display slot for this call.
                # The extra image is ordinary RAM and keeps no camera/P1/CMA lease.
                h,w=out.shape[:2];image=np.empty((h,w,3),np.uint8)
                bgra_bgr_into(out,image,(0,0,w,h));image.setflags(write=False)
                session.update(image=image,source_index=meta.get('index'),source_sequence=meta.get('camera_sequence'),source_kind='completed_output')
            if not self.current(session):return False
            shown=render_frozen(self.display,raw,out,meta,self,session)
            if shown and not was_visible:
                checkpoint('UI_RIGHT_HOLD_PRESENTED',generation=session['generation'],view=session['view'],
                    frozen_source_index=session['source_index'],frozen_source_sequence=session['source_sequence'],
                    source_kind=session['source_kind'],left_live=session['view']=='compare',new_correction_counted=False)
            return shown
        except HoldUnavailable:
            # Claim this contact through UP, but keep live input responsive.
            with self.display.condition:
                if self.display._show==self.handler:self.display._show=self.base_show
            checkpoint('UI_RIGHT_HOLD_UNAVAILABLE',generation=session['generation'],reason='no_owned_complete_result',contact_remains_owned=True)
            return self.base_show(raw,out,meta)
        except BaseException:
            self.end('display_error');raise

# BEGIN EVENT-ONLY FROZEN RENDERER
def render_frozen(self,raw,live_out,meta,controller,session):
    out=session['image']
    view=meta.get('ui_view','compare');generation=int(meta.get('ui_generation',0))
    if self.ui_assets is not None and generation!=self.ui_generation:return False
    began=time.perf_counter();cpu=time.thread_time()
    frame,canvas=self._acquire_canvas(view if meta['state']=='STARTING' else None,generation)
    acquired=time.perf_counter();acquired_cpu=time.thread_time()
    try:
        h,w=self.mode[1],self.mode[0];mid=w//2
        # Before acquisition (and after complete loss), show live input
        # even on the result-only page so placement remains visible.
        single=view=='rectified' and out is not None
        if single:raw=None
        left=native_display_rect(self.mode,fit_panel_shape(self.mode,raw.shape[:2]),0) if raw is not None else None
        if out is not None and single:
            oh,ow=out.shape[:2]
            if ow>w or oh>h-64:raise ValueError('Rectified native image exceeds HDMI canvas')
            right=((w-ow)//2,36+(h-64-oh)//2,ow,oh)
        else:right=native_display_rect(self.mode,out.shape[:2],1) if out is not None else None
        key=int(frame.physical_address);old=self.layouts.get(key)
        if out is None:
            # No new output: a recycled, now-owned canvas may contain a complete
            # prior right image. All reads precede any clear or device handoff.
            prior=None if old is None else old[1]
            token=self.canvas_views.get(key)
            if prior!=session['press_rect'] or not token or len(token)!=3 or token[:2]!=(view,generation):raise HoldUnavailable()
            px,py,pw,ph=prior
            out=np.array(canvas[py:py+ph,px:px+pw],dtype=np.uint8,copy=True,order='C')
            out.setflags(write=False);session.update(image=out,source_kind='owned_complete_canvas')
            single=view=='rectified';left=None if single else left;right=prior
            if single:raw=None
        page_token=(view,generation,'right_hold',session['serial'],self.target_notice)
        startup_phase=meta.get('ui_startup_phase');startup_action=None
        if startup_phase in ('preparing','placement'):
            startup_action=('confirmed' if meta.get('placement_confirmed') or not meta.get('placement_required') else 'confirm')
        elif startup_phase=='acquiring':startup_action='acquiring'
        if startup_action is not None:page_token=page_token+(startup_action,)
        prior_token=self.canvas_views.get(key);normal_token=(view,generation,self.target_notice)
        page_changed=self.ui_assets is not None and prior_token not in (page_token,normal_token)
        first_hold_buffer=prior_token!=page_token
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
                    else self.ui_assets.ratio_original_headers[view] if out is None else self.ui_assets.headers[view])
                if startup_action is not None:
                    canvas[:72,1000:1280]=self.ui_assets.placement_controls[startup_action]
                if view in ('compare','rectified'):
                    canvas[:72,380:580]=self.ui_assets.refind_controls[
                        'preparing' if startup_phase=='preparing' else 'ready']
                    if self.target_notice!='idle':
                        canvas[78:118,:640]=self.ui_assets.target_hints[(view,self.target_notice)]
                ui_header_restore_s=time.perf_counter()-ui_began
            # Cached top-left return pixels are not touched on warm buffers.
            label_end=1000 if view in ('compare','rectified','snapshot') else w
            # V82 cached touch controls occupy the header; dynamic labels
            # stay in the existing footer and never overwrite hit targets.
            self.canvas_views[key]=page_token
            if len(self.canvas_views)>16:self.canvas_views={key:page_token}
        canvas[h-28:].fill(0)
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
                #   ⚠️ 2026-10-28：`left` 是 `fit_panel_shape()` 算出来的显示尺寸
                #      （800x600 源图 ⇒ 640x480 槽），而 `yuyv_bgr_into()` 要求
                #      **矩形尺寸必须等于源图尺寸**，否则抛
                #      `Native BGR rectangle does not match source/frame bounds`。
                #      ⇒ 800x600 下按"右图冻结/查看"手势会**直接崩**。这里补缩放分支。
                done=False
                if raw.shape[:2]!=(rh,rw):
                    fused=getattr(self,'_fused',None)
                    if fused is None and not getattr(self,'_fused_failed',False):
                        try:
                            from v71_display import FusedDisplay
                            fused=FusedDisplay();self._fused=fused
                        except BaseException:
                            self._fused_failed=True;fused=None
                    if fused is not None:
                        try:fused.scale(0,raw,int(meta['color_mode']),canvas,left);done=True
                        except BaseException:done=False
                    if not done:
                        from v31_native import yuyv_preview_into
                        if self._scaled is None or self._scaled.shape[:2]!=(rh,rw):
                            self._scaled=np.empty((rh,rw,3),np.uint8)
                        if yuyv_preview_into(raw,int(meta['color_mode']),self._scaled,
                                fast=bool(getattr(self,'_preview_nearest',True))):
                            canvas[y:y+rh,x:x+rw]=self._scaled;done=True
                        else:
                            ih,iw=raw.shape[:2];y0=max(0,(ih-rh)//2);x0=max(0,(iw-rw)//2)
                            yuyv_bgr_into(np.ascontiguousarray(raw[y0:y0+rh,x0:x0+rw]),
                                meta['color_mode'],canvas,left)
                if not done:yuyv_bgr_into(raw,meta['color_mode'],canvas,left)
            input_convert_s=time.perf_counter()-t
            raw_backend='startup_OpenCV_or_model_CSC' if startup_fallback else 'native_YUYV_to_BGR_scaled_or_1to1'
            left_detail=dict(direct=True,resize_used=False,crop_used=False,backend=raw_backend,
                source_shape=list(raw.shape),destination_rect=list(left),polyphase_5_4_used=False)
            left_panel_s=time.perf_counter()-t;left_cpu_s=time.thread_time()-tc
            t=time.perf_counter();tc=time.thread_time()
            corners=meta.get('corners',())
            #   ⚠️ 2026-10-28：四角是【源图坐标】，左画面是【缩放后】的 ⇒ 先缩放再加偏移。
            _sx,_sy=rw/float(raw.shape[1]),rh/float(raw.shape[0])
            _scaled_pts=(rw,rh)!=tuple(raw.shape[1::-1])
            if len(corners)==4:
                points=np.asarray(corners,np.float32).copy()
                if _scaled_pts:points=np.stack([points[:,0]*_sx,points[:,1]*_sy],axis=1)
                points+=np.array([x,y],np.float32)
                color=(0,240,0) if meta['state']=='CURRENT' else (255,200,70) if meta['state']=='MANUAL' else (0,210,255)
                # A single colored outline preserves HELD status without
                # dozens of Python/NumPy/cv2.line calls on each frame.
                cv2.polylines(canvas,[np.rint(points).astype(np.int32)],True,color,2,cv2.LINE_AA)
            candidate=meta.get('candidate_corners',())
            if (not corners and len(candidate)==4 and
                    0<=time.perf_counter()-meta.get('candidate_ready_at',0.)<=.9):
                cq=np.asarray(candidate,np.float32)
                if _scaled_pts:cq=np.stack([cq[:,0]*_sx,cq[:,1]*_sy],axis=1)
                points=np.rint(cq+np.array([x,y],np.float32)).astype(np.int32)
                cv2.polylines(canvas,[points],True,(70,70,255),2,cv2.LINE_AA)
            corner_draw_s=time.perf_counter()-t;corner_draw_cpu_s=time.thread_time()-tc
        if out is not None:
            x,y,rw,rh=right;t=time.perf_counter();tc=time.thread_time()
            if first_hold_buffer or page_changed or old is None or old[1]!=right:
                canvas[y:y+rh,x:x+rw]=out
                badge=self.ui_assets.hold_badge if rw>=248 else self.ui_assets.hold_badge_small
                bh,bw=badge.shape[:2]
                if rw>=bw and y-bh-4>=72:
                    bx=x+(rw-bw)//2;by=y-bh-4
                    underlay=np.array(canvas[by:by+bh,bx:bx+bw],copy=True,order='C');underlay.setflags(write=False)
                    session['patches'][key]=((bx,by,bw,bh),underlay,normal_token,page_token)
                    canvas[by:by+bh,bx:bx+bw]=badge
                session['cache_copies']+=1
            output_convert_s=0.
            right_detail=dict(direct=True,resize_used=False,crop_used=False,backend='ordinary_RAM_frozen_BGR',
                source_shape=list(out.shape),destination_rect=list(right),right_frozen=True)
            right_panel_s=time.perf_counter()-t;right_cpu_s=time.thread_time()-tc
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
            status='MANUAL %s | M-CORR %.1f | DISP %.1f | %s'%(meta.get('manual_tracking',''),
                meta.get('manual_fps',0.),rate,('MOTION WATCH / AUTO RESUME' if meta.get('manual_fixed_watch') else 'RECALIBRATE AFTER MOVING')
                if meta.get('manual_tracking')=='FIXED' else 'FULL FB TRACK / FINITE HOLD')
            if meta.get('manual_tracking')=='SNAPSHOT':status='MANUAL SINGLE FRAME | RECAPTURE, RECALIBRATE OR RETURN'
        if meta['state']=='INITIALIZING':
            status='SETUP %.0fs | AUTO LOCATE WHEN READY | RAW VIEW ACTIVE'%meta.get('native_setup_elapsed_s',0.)
        elif meta['state']=='PLACEMENT':status='READY | AUTOMATIC CURRENT-FRAME LOCALIZATION'
        status=('INPUT LIVE | RECTIFIED FROZEN | RELEASE TO RESUME' if not single else 'RECTIFIED FROZEN | RELEASE TO RESUME')
        status_x=8
        if self.ui_assets is not None:
            state=meta['state'] if meta['state'] in self.ui_assets.status_badges else 'SEARCHING'
            if state=='MANUAL' and meta.get('manual_tracking')=='FIXED':state='MANUAL_FIXED'
            canvas[h-28:,:320]=self.ui_assets.status_badges[state];status_x=326
        cv2.putText(canvas,status,(status_x,h-9),cv2.FONT_HERSHEY_SIMPLEX,.40,(255,255,255),1,cv2.LINE_AA)
        if self.ui_assets is not None and generation!=self.ui_generation:
            return False
        if self.media is not None:
            if self.inspection.kind is None:self.media.render_live(canvas,key,page_changed)
            with self.condition:
                if self.media.active:return False
        if not controller.current(session):return False
        composed=time.perf_counter();composed_cpu=time.thread_time();polls=self.loop.run_until_complete(self._submit(frame));end=time.perf_counter()
        if meta.get('inspection_redraw'):return True
        sample=dict(index=meta['index'],camera_sequence=meta.get('camera_sequence'),state='DISPLAY_FROZEN',source_state=meta['state'],epoch=meta['epoch'],
            compose_s=composed-began,compose_thread_cpu_s=composed_cpu-cpu,
            frame_acquire_s=acquired-began,frame_acquire_thread_cpu_s=acquired_cpu-cpu,
            clear_layout_s=clear_end-acquired,clear_layout_thread_cpu_s=clear_cpu-acquired_cpu,
            left_panel_s=left_panel_s,left_panel_thread_cpu_s=left_cpu_s,
            right_panel_s=right_panel_s,right_panel_thread_cpu_s=right_cpu_s,
            panel_native_details=dict(left=left_detail,right=right_detail),corner_draw_s=corner_draw_s,corner_draw_thread_cpu_s=corner_draw_cpu_s,
            held_outline_backend='single_polylines',
            other_compose_s=max(0.,composed-clear_end-left_panel_s-right_panel_s-corner_draw_s),
            current_display_fps_2s=current_rate,display_rate_window_s=2.,
            display_backend='native_direct_color_convert_1to1',display_frontend_version=79,
            capture_age_ms=age,H_age_ms=h_age,
            ui_view=view,ui_generation=generation,ui_header_restore_s=ui_header_restore_s,
            display_scale_enabled=False,display_crop_enabled=False,native_substage_times_available=False,
            input_convert_s=input_convert_s,output_convert_s=output_convert_s,scale_s=scale_s,
            split_conversion_times_available=True,
            conversion_timing_scope='direct conversion wrappers; no resampling; native-only substage timers unavailable',
            vdma_submit_thread_cpu_s=time.thread_time()-composed_cpu,
            vdmasubmit_polls=polls,vdma_submit_s=end-composed,submitted_at=end,display_thread_cpu_s=time.thread_time()-cpu,
            capture_to_submit_s=end-meta.get('capture_ready_at',end),same_frame=False,input_backend=raw_backend,
            right_frozen=True,left_live=raw is not None,frozen_source_index=session['source_index'],frozen_source_sequence=session['source_sequence'],frozen_source_kind=session['source_kind'],
            layout_generation=int(meta.get('layout_generation',0)),orientation=meta.get('orientation'))
        snapshot_receipt=None;layout_receipt=None
        with self.condition:
            self.panels_submitted+=int(raw is not None);session['submitted']+=1;session['visible']=True
            # A frozen right image is never a new correction submission.
            if raw is not None or out is not None:self.submit_times.append(end)
            self.samples.append(sample)
            # Retain a reference to the already owned source; no pixel copy.
            self.tap_source=(raw,meta,left,end)
            stats=self.epoch_stats.setdefault(meta['epoch'],dict(submitted=0,current=0,panels=0,replaced=0,dropped=0))
            stats['right_frozen_canvas_submitted']=stats.get('right_frozen_canvas_submitted',0)+1
            stats['panels']+=int(raw is not None)
            if raw is not None or out is not None:stats['last_submitted_at']=end
            command=self.ui_layout_pending
            if (command is not None and meta['state']!='STARTING' and
                    (command[0],command[1])==(int(meta.get('ui_generation',0)),view)):
                layout_receipt=dict(page=view,generation=command[0],layout_only=True,
                    request_to_submit_s=end-command[2],camera_restarted=False,tracker_reinitialized=False,
                    same_frame=False,index=meta['index'],camera_sequence=meta.get('camera_sequence'),
                    physical_scan_time_measured=False)
                self.ui_layout_pending=None
        if snapshot_receipt is not None:checkpoint('SNAPSHOT_HDMI_FROZEN',**snapshot_receipt)
        if layout_receipt is not None:checkpoint('UI_PAGE_PRESENTED',**layout_receipt)
        if meta['index']>=0 and (meta['index']%60==0 or end-began>.12):checkpoint('HDMI_FRAME_DETAIL',**sample)
        return True
    finally:
        canvas=None;frame=None
