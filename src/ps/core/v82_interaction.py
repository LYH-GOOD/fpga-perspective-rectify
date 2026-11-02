"""Event-only inspection pages and low-rate placement hints; no device IO."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

MANUAL_RECT=(180,0,200,72)
REFIND_RECT=(380,0,200,72)
ZOOM_RECT=(580,0,180,72)
SOURCE_RECT=(24,148,640,480)
CALIB_CONTROLS={'undo':(716,366,244,64),'refresh':(980,366,244,64),
    'confirm':(716,446,244,72),'auto':(980,446,244,72)}
AI_CONTROLS={'refresh':(716,366,244,64),'retry':(980,366,244,64),
    'manual':(716,446,244,64),'auto':(980,446,244,64)}
AI_STAGES=('queued','loading','ready','busy','parent_preprocess','parent_fit_corners',
    'inference','check_assets','import_numpy','import_ncnn','load_parameters','load_weights','warmup')
ZOOM_CONTROLS={'zoom_scale':(716,560,244,64),'zoom_close':(980,560,244,64)}
CALIB_LOUPE=(716,148,240,192)
CORNER_HIT_RADIUS=28
CALIB_CONTROLS.update({name:(716+i*128,630,112,56)
    for i,name in enumerate(('left','up','down','right'))})


def inside(point,rect):
    x,y,w,h=rect
    return point is not None and x<=point[0]<x+w and y<=point[1]<y+h


def selected_quad(points,shape):
    """Explicit user selection still requires a visible convex geometric quad."""
    if len(points)!=4:raise ValueError('Select all four corners first')
    q=np.asarray(points,np.float32).reshape(4,2)
    if not np.isfinite(q).all():raise ValueError('Invalid manual coordinates')
    hull=cv2.convexHull(q).reshape(-1,2)
    if len(hull)!=4:raise ValueError('Four distinct exterior corners are required')
    from v8_geometry import order_corners
    from v31_detection import _visible_quad
    return _visible_quad(order_corners(hull),shape,preserve_order=True)


class Inspection:
    """One immutable ordinary-RAM source; HDMI owner alone renders/submits it.

    Every method uses the display condition. No touch handler reads pooled video
    pixels or owns a camera/VDMA lease. Requests have a page generation and token.
    """
    def __init__(self,display):
        self.display=display;self.kind=None;self.generation=-1;self.token=0
        self.source=None;self.source_rect=None;self.points=();self.action=None
        self.dirty=False;self.zoom_requested=None;self.scale=2;self.focus=None
        self.notice='';self.meta={};self.opened=0;self.redraws=0
        self.selected=None;self.edit_history=[];self.edit_contact=None
        from v741_reading import ReadingPan
        self.reading=ReadingPan(self)
    def clear_locked(self):
        self.kind=None;self.source=None;self.source_rect=None;self.points=()
        self.action=None;self.dirty=False;self.zoom_requested=None;self.focus=None;self.meta={}
        self.selected=None;self.edit_history=[];self.edit_contact=None
        self.token+=1;self.reading.clear_locked()
    #   ⭐ 2026-10-27：坐标换算。源图（800x600）在屏幕上是被等比缩小显示的
    #      （v64_hdmi_display.HdmiLatest._fit_shape），所以：
    #        屏幕点 → 源图点：先减矩形原点，再乘 (源宽/矩形宽)
    #      640x480 时缩放系数恒为 1，行为与改动前完全一致。
    def _source_size(self):
        sh=self.meta.get('source_shape') if isinstance(self.meta,dict) else None
        if not sh or len(sh)!=2 or not self.source_rect:return self.source_rect[2],self.source_rect[3]
        return int(sh[1]),int(sh[0])
    #   ⚠️ 必须与 `v64_hdmi_display.preview_scale_enabled()` **完全一致**：
    #      True = 等比缩放（乘系数）；False = 居中裁剪（加偏移）。
    #   ⭐ 2026-10-28：显示改成【绘制时用原生缩放】（见 `v64_hdmi_display._draw`），
    #      所以这里**恒为等比缩放**，不再依赖 OpenCV 的 BGR→YUYV 编码常量。
    _SCALE_PREVIEW = True

    def _source_offset(self):
        if self._SCALE_PREVIEW:
            return 0, 0
        sw, sh = self._source_size()
        _, _, w, h = self.source_rect
        return max(0, (sw - int(w)) // 2), max(0, (sh - int(h)) // 2)

    def _source_scale(self):
        if not self._SCALE_PREVIEW:
            return 1., 1.
        sw, sh = self._source_size()
        _, _, w, h = self.source_rect
        return (float(sw) / max(1, w), float(sh) / max(1, h))

    def _to_source(self, point):
        x, y = self.source_rect[0], self.source_rect[1]
        ox, oy = self._source_offset()
        sx, sy = self._source_scale()
        return (float(point[0] - x) + ox) * sx, (float(point[1] - y) + oy) * sy
    def _clamp_source(self,x,y):
        sw,sh=self._source_size()
        return (float(np.clip(x,0,sw-1)),float(np.clip(y,0,sh-1)))
    def begin_calibration(self,raw,color_mode,generation,sequence):
        # Caller owns the frozen raw source until confirmation/retirement.
        from v64_io import yuyv_bgr_into
        h,w=raw.shape[:2];image=np.empty((h,w,3),np.uint8)
        yuyv_bgr_into(raw,color_mode,image,(0,0,w,h))
        image.setflags(write=False)
        with self.display.condition:
            if generation!=self.display.ui_generation or self.display.stop:return False
            self.clear_locked();self.kind='calibration';self.generation=generation
            self.source=image;self.source_rect=SOURCE_RECT;self.points=();self.notice='select'
            self.meta=dict(sequence=int(sequence),source_shape=tuple(raw.shape[:2]))
            self.dirty=True;self.opened+=1;self.display.pending=None;self.display.condition.notify_all()
        checkpoint('MANUAL_CALIBRATION_FROZEN',generation=generation,sequence=int(sequence),
            source_shape=list(raw.shape[:2]),source_rect=list(SOURCE_RECT),coordinate_mapping='native 1to1; frozen source',hardware_access=False)
        return True
    def request_zoom(self,generation):
        with self.display.condition:
            if generation!=self.display.ui_generation or self.display.stop or self.kind:return False
            if self.display.latest_meta.get('ui_generation')!=generation:return False
            if self.display.ui_view=='snapshot' and self.display.frozen_generation!=generation:return False
            if self.display.latest_meta.get('state') not in ('CURRENT','HELD','MANUAL','MANUAL_HELD'):
                return False
            self.zoom_requested=generation;self.display.condition.notify_all();return True
    def open_zoom_locked(self,image,meta):
        generation=int(meta.get('ui_generation',-1))
        if self.zoom_requested!=generation or generation!=self.display.ui_generation:return False
        if self.display.pending is not None:
            self.display.pending=None;self.display.ui_discarded+=1
        self.clear_locked();self.kind='zoom';self.generation=generation
        self.source=np.array(image,copy=True,order='C');self.source.setflags(write=False)
        h,w=self.source.shape[:2]
        #   ⚠️ 2026-10-31：600P 时 w=800 会让 x=24+(640-800)//2=-56，负索引切片变空 ⇒
        #      再赋值就 ValueError。夹到非负；640x480 档 x=24、y=134，与改动前相同。
        self.source_rect=(max(0,24+(640-w)//2),max(0,100+(548-h)//2),w,h)
        self.focus=(w//2,h//2);self.scale=2;self.meta=dict(sequence=meta.get('camera_sequence'),source_shape=(h,w),page=self.display.ui_view)
        self.dirty=True;self.opened+=1
        checkpoint('READING_FREEZE_READY',generation=generation,sequence=meta.get('camera_sequence'),
            source_shape=[h,w],fixed_source=True,processing_continues=True,ordinary_RAM_bytes=self.source.nbytes)
        return True
    def target(self,point,generation):
        with self.display.condition:
            if self.kind is None or generation!=self.generation:return None
            if self.kind=='calibration':
                if self.meta.get('ai_only'):
                    for name,rect in AI_CONTROLS.items():
                        if inside(point,rect):return 'inspect_'+name
                    return 'inspect_background'
                if inside(point,self.source_rect):return 'inspect_point'
                for name,rect in CALIB_CONTROLS.items():
                    if inside(point,rect):return 'inspect_'+name
            elif self.kind=='zoom':
                target=self.reading.target_locked(point)
                if target is not None:return target
                for name,rect in ZOOM_CONTROLS.items():
                    if inside(point,rect):return 'inspect_'+name
            return 'inspect_background'
    def _point_notice_locked(self):
        self.notice='select'
        if len(self.points)==4:
            try:selected_quad(self.points,self.meta['source_shape'])
            except ValueError:self.notice='invalid'
            else:self.notice='ready'
    def _edit_redraw_locked(self):
        self._point_notice_locked();self.dirty=True;self.display.condition.notify_all()
    def _remember_locked(self,points,selected):
        self.edit_history.append((points,selected))
        if len(self.edit_history)>64:del self.edit_history[0]
    def begin_point_contact(self,point,generation,contact_id):
        """Stage an edit on frozen RAM; a matching release alone commits it."""
        with self.display.condition:
            if (self.kind!='calibration' or generation!=self.generation or self.notice in ('busy','ai_busy')
                    or contact_id is None or not inside(point,self.source_rect)):
                return False,'corner_edit_unavailable',self.token
            if self.edit_contact is not None:return False,'corner_contact_busy',self.token
            x,y,w,h=self.source_rect;p=self._to_source(point)
            distances=[np.hypot(p[0]-a,p[1]-b) for a,b in self.points]
            index=int(np.argmin(distances)) if distances and min(distances)<=CORNER_HIT_RADIUS else None
            before=self.points;old_selected=self.selected
            if index is None:
                if len(before)>=4:return False,'touch_existing_corner_to_adjust',self.token
                index=len(before);offset=(0.,0.);self.points=before+(p,)
            else:offset=(before[index][0]-p[0],before[index][1]-p[1])
            self.edit_contact=dict(contact_id=contact_id,token=self.token,generation=generation,
                index=index,before=before,selected=old_selected,offset=offset)
            self.selected=index;self.focus=self.points[index];self._edit_redraw_locked()
            return True,'corner_contact_started',self.token
    def _matching_contact_locked(self,event,generation):
        edit=self.edit_contact;origin=event.get('press_outcome') or {}
        return bool(edit is not None and self.kind=='calibration' and self.generation==generation
            and edit['generation']==generation and edit['token']==self.token
            and origin.get('inspection_token')==self.token and event.get('contact_id')==edit['contact_id'])
    def _update_contact_locked(self,point):
        edit=self.edit_contact
        bx,by=self._to_source(point)
        p=self._clamp_source(bx+edit['offset'][0],by+edit['offset'][1])
        points=list(self.points);points[edit['index']]=p;self.points=tuple(points)
        self.focus=p;self._edit_redraw_locked()
    def move_point_contact(self,event,generation):
        with self.display.condition:
            if not self._matching_contact_locked(event,generation):return False,'corner_contact_changed'
            point=event.get('position')
            if point is None:return False,'missing_move_coordinates'
            self._update_contact_locked(point)
            return True,'corner_drag_preview'
    def cancel_point_contact(self,contact_id=None):
        with self.display.condition:
            edit=self.edit_contact
            if edit is None or (contact_id is not None and contact_id!=edit['contact_id']):return False
            self.points=edit['before'];self.selected=edit['selected'];self.edit_contact=None
            self.focus=self.points[self.selected] if self.selected is not None else None
            self._edit_redraw_locked();return True
    def finish_point_contact(self,event,generation):
        with self.display.condition:
            if not self._matching_contact_locked(event,generation):return False,'corner_contact_changed'
            if event.get('release') is None:
                self.cancel_point_contact(event.get('contact_id'));return False,'missing_release_coordinates'
            edit=self.edit_contact
            self._update_contact_locked(event['release'])
            p=self.points[edit['index']]
            if any(i!=edit['index'] and np.hypot(p[0]-q[0],p[1]-q[1])<10 for i,q in enumerate(self.points)):
                self.cancel_point_contact(event.get('contact_id'));return False,'corners_too_close'
            changed=self.points!=edit['before']
            if changed:self._remember_locked(edit['before'],edit['selected'])
            self.edit_contact=None;self._edit_redraw_locked()
            checkpoint('MANUAL_CORNER_EDIT',generation=generation,sequence=self.meta['sequence'],
                corner=edit['index']+1,point=p,changed=changed,points=len(self.points),
                operation='place' if len(edit['before'])<len(self.points) else 'drag',
                frozen_source=True,hardware_access=False)
            return True,'corner_edit_committed' if changed else 'corner_selected'
    def release(self,target,press,release,generation,token=None):
        with self.display.condition:
            if generation!=self.generation or self.kind is None or token!=self.token:return False,'inspection_changed'
            if self.target(release,generation)!=target:return False,'release_outside_target'
            if self.kind=='calibration' and self.notice=='busy':return False,'calibration_busy'
            if self.kind=='calibration' and self.notice=='ai_busy' and target not in ('inspect_refresh','inspect_auto','inspect_manual'):
                return False,'ai_request_busy'
            if self.kind=='calibration' and self.edit_contact is not None:return False,'finish_corner_drag_first'
            if target=='inspect_point':return False,'point_requires_matching_contact'
            elif target=='inspect_undo':
                if not self.edit_history:return False,'no_corner_edit_to_undo'
                self.points,self.selected=self.edit_history.pop()
                self.focus=self.points[self.selected] if self.selected is not None else None
                self._point_notice_locked()
                checkpoint('MANUAL_CORNER_UNDO',generation=generation,points=len(self.points),frozen_source=True)
            elif target in ('inspect_left','inspect_up','inspect_down','inspect_right'):
                if self.selected is None:return False,'select_corner_before_nudge'
                delta={'inspect_left':(-1,0),'inspect_up':(0,-1),'inspect_down':(0,1),'inspect_right':(1,0)}[target]
                before=self.points;old_selected=self.selected;p=before[self.selected]
                q=self._clamp_source(p[0]+delta[0],p[1]+delta[1])
                if q==p:return False,'corner_at_source_boundary'
                if any(i!=self.selected and np.hypot(q[0]-v[0],q[1]-v[1])<10 for i,v in enumerate(before)):
                    return False,'corners_too_close'
                self._remember_locked(before,old_selected)
                points=list(before);points[self.selected]=q;self.points=tuple(points);self.focus=q
                self._point_notice_locked()
            elif target=='inspect_retry':
                if not self.meta.get('ai_only'):return False,'not_ai_page'
                return self.queue_ai(generation,ai_only=True),'ai_retry_queued'
            elif target=='inspect_manual':
                if not self.meta.get('ai_only'):return False,'not_ai_page'
                self.action=('manual',None);self.notice='busy'
                checkpoint('AI_MANUAL_FALLBACK_REQUESTED',generation=generation,explicit_user=True)
            elif target=='inspect_refresh':self.action=('refresh',None);self.notice='busy'
            elif target=='inspect_confirm':
                try:q=selected_quad(self.points,self.meta['source_shape'])
                except ValueError:self.notice='invalid';self.dirty=True;self.display.condition.notify_all();return False,'manual_quad_invalid'
                self.action=('confirm',q.copy());self.notice='busy'
                checkpoint('MANUAL_CORNERS_CONFIRMED',generation=generation,sequence=self.meta['sequence'],
                    corners=q.tolist(),authority='explicit user four points',automatic_edge_proof=False,hardware_proof_still_required=True)
            elif target=='inspect_auto':self.action=('auto',None);self.notice='busy'
            elif target=='inspect_focus':
                fx,fy=self._to_source(release)
                fx,fy=self._clamp_source(fx,fy)
                self.focus=(int(fx),int(fy))
            elif target=='inspect_zoom_scale':
                self.reading.cancel_locked();self.scale=4 if self.scale==2 else 2
            elif target=='inspect_zoom_close':
                self.clear_locked();self.display.canvas_views.clear();self.display.layouts.clear()
                self.display.inspection_restore=bool(self.display.ui_view=='snapshot' and self.display.last_static_packet is not None)
                self.display.condition.notify_all();return True,'reading_closed_resume_latest'
            else:return False,'outside_controls'
            self.dirty=True;self.display.condition.notify_all();return True,target
    def begin_ai(self,raw,color_mode,generation,sequence):
        if not self.begin_calibration(raw,color_mode,generation,sequence):return False
        return self.queue_ai(generation,ai_only=True)
    def ai_progress(self,generation,stage):
        with self.display.condition:
            if (self.generation!=generation or self.notice!='ai_busy'
                    or self.display.ui_generation!=generation or self.display.stop):return
            if self.meta.get('ai_stage')==stage:return
            self.meta['ai_stage']=stage;self.dirty=True;self.display.condition.notify_all()
    def ai_alignment_failed(self,generation,error):
        with self.display.condition:
            if (self.generation!=generation or self.display.ui_generation!=generation
                    or self.display.stop or not self.meta.get('ai_only')):return
            self.notice='ai_alignment_failed';self.action=None;self.dirty=True
            self.display.condition.notify_all()
            checkpoint('AI_ALIGNMENT_REJECTED',generation=generation,error=str(error)[:1200],
                retry_available=True,manual_fallback='explicit_user_only')
    def queue_ai(self,generation,ai_only=False):
        with self.display.condition:
            if (self.kind!='calibration' or self.generation!=generation
                    or self.display.ui_generation!=generation or self.display.stop
                    or self.source is None or self.notice in ('busy','ai_busy')):return False
            self.meta['ai_request_id']=int(self.meta.get('ai_request_id',0))+1
            self.meta['ai_only']=bool(ai_only)
            self.meta['ai_stage']='queued'
            self.action=('ai',None);self.notice='ai_busy';self.dirty=True
            self.display.condition.notify_all();return True
    def ai_input(self,generation):
        with self.display.condition:
            if (self.kind!='calibration' or self.generation!=generation
                    or self.display.ui_generation!=generation or self.display.stop
                    or self.notice!='ai_busy' or self.source is None):
                raise ValueError('AI selection is no longer current')
            receipt=dict(release_id=RELEASE_ID,generation=generation,token=self.token,
                sequence=self.meta['sequence'],request_id=self.meta['ai_request_id'])
            return receipt,self.source
    def ai_failed(self,generation,error,failure_kind='runtime_error',diagnostics=None):
        with self.display.condition:
            if self.kind=='calibration' and self.generation==generation and self.notice=='ai_busy':
                self.notice=('ai_timeout' if failure_kind=='timeout' else 'ai_failed'
                    if failure_kind in ('no_plane','invalid_geometry') else 'ai_runtime_failed')
                self.dirty=True;self.display.condition.notify_all()
                checkpoint('AI_CORNERS_FAILED',generation=generation,error=str(error)[:1200],
                    failure_kind=failure_kind,diagnostics=diagnostics or [],manual_available=True)
    def apply_ai_result(self,receipt,source,result):
        with self.display.condition:
            expected=dict(release_id=RELEASE_ID,generation=self.generation,token=self.token,
                sequence=self.meta.get('sequence'),request_id=self.meta.get('ai_request_id'))
            if (self.kind!='calibration' or self.display.ui_generation!=self.generation
                    or self.display.stop or self.source is not source or self.notice!='ai_busy'
                    or self.action is not None or receipt!=expected
                    or any(result.get(k)!=v for k,v in expected.items())):
                return False
            if result.get('status')!='candidate':
                self.ai_failed(self.generation,result.get('error','AI did not complete'),
                    result.get('failure_kind','runtime_error'),result.get('diagnostics'));return False
            try:
                q=selected_quad(result['quad'],self.meta['source_shape'])
            except (ValueError,TypeError,KeyError) as exc:
                self.ai_failed(self.generation,exc,'invalid_geometry');return False
            self._remember_locked(self.points,self.selected)
            self.points=tuple(map(tuple,q.tolist()));self.selected=None;self.focus=None
            self.action=('confirm',q.copy());self.notice='busy'
            self.dirty=True;self.display.condition.notify_all()
            checkpoint('AI_CORNERS_CANDIDATE',generation=self.generation,sequence=self.meta['sequence'],
                corners=q.tolist(),request_id=receipt['request_id'],request_ms=result.get('request_ms'),
                worker_ms=result.get('worker_ms'),mask_fit_iou=result.get('mask_fit_iou'),
                authority='explicit AI click; AI seed to shared correction backend',
                model_sha256=result.get('model_sha256'),hardware_access=False)
            return True
    def take_action(self,generation):
        with self.display.condition:
            if generation!=self.generation:return None
            result=self.action;self.action=None;return result
    def end_calibration(self,generation):
        with self.display.condition:
            if self.generation==generation:
                self.clear_locked();self.display.canvas_views.clear();self.display.layouts.clear();self.display.condition.notify_all()
    def payload_locked(self):
        if not self.kind or not self.dirty:return None
        self.dirty=False;self.redraws+=1
        return dict(kind=self.kind,generation=self.generation,token=self.token,source=self.source,
            source_rect=self.source_rect,points=self.points,notice=self.notice,focus=self.focus,
            scale=self.scale,meta=dict(self.meta),selected=self.selected,dragging=self.edit_contact is not None)


def _ai_editor_assets(assets):
    # Decoded once on the explicitly requested AI page, never on a live frame.
    if hasattr(assets,'ai_header'):return
    root=Path(__file__).resolve().parent
    def read(name,shape):
        value=cv2.imdecode(np.frombuffer((root/name).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if value is None or value.shape!=shape:raise ValueError('Invalid AI UI asset '+name)
        return value
    assets.ai_header=read('v98_ai_header.png',(72,1280,3))
    assets.ai_help=read('v98_ai_help.png',(232,544,3))
    buttons=read('v102_ai_controls.png',(128,488,3))
    assets.ai_buttons={name:buttons[(i//2)*64:(i//2+1)*64,(i%2)*244:(i%2+1)*244]
        for i,name in enumerate(AI_CONTROLS)}
    assets.ai_retry_disabled=cv2.convertScaleAbs(assets.ai_buttons['retry'],alpha=.4)
    stages=read('v102_ai_stages.png',(len(AI_STAGES)*48,512,3))
    assets.ai_stage_patches={name:stages[i*48:(i+1)*48] for i,name in enumerate(AI_STAGES)}
    atlas=read('v98_ai_notices.png',(384,512,3))
    for i,name in enumerate(('ai_busy','ai_ready','ai_failed','ai_timeout','ai_runtime_failed','ai_alignment_failed')):
        assets.calibration_notices[name]=atlas[i*64:(i+1)*64]


def _render_ai(canvas,payload,assets):
    _ai_editor_assets(assets);canvas.fill(0);canvas[:72]=assets.ai_header
    x,y,w,h=payload['source_rect'];canvas[y:y+h,x:x+w]=payload['source']
    canvas[108:340,704:1248]=assets.ai_help
    for name,(a,b,c,d) in AI_CONTROLS.items():
        canvas[b:b+d,a:a+c]=(assets.ai_retry_disabled if name=='retry'
            and payload['notice'] in ('ai_busy','busy') else assets.ai_buttons[name])
    notice=assets.calibration_notices.get(payload['notice'],assets.calibration_notices['ai_ready'])
    canvas[540:604,716:1228]=notice
    stage=payload['meta'].get('ai_stage','queued')
    # Chinese stage text is cached with the UI assets; no font work on board.
    patch=assets.ai_stage_patches.get(stage,assets.ai_stage_patches['busy'])
    if payload['notice']=='ai_busy':canvas[620:668,716:1228]=patch
    cv2.putText(canvas,'AI | SOURCE seq=%s'%payload['meta']['sequence'],(32,112),
        cv2.FONT_HERSHEY_SIMPLEX,.65,(230,230,230),1,cv2.LINE_AA)


def render_inspection(canvas,payload,assets):
    """Called only by the existing HDMI owner; expensive work is event-only."""
    if payload['kind']=='ratio':
        from v73_ratio_ui import render_ratio
        return render_ratio(canvas,payload,assets)
    if payload['kind']=='album':
        from v97_album import render_album
        return render_album(canvas,payload,assets)
    if payload['kind']=='zoom':
        from v741_reading import render_reading
        return render_reading(canvas,payload,assets)
    if payload['kind']=='calibration' and payload['meta'].get('ai_only'):
        return _render_ai(canvas,payload,assets)
    canvas.fill(0)
    canvas[:72]=(assets.headers['snapshot'] if payload['kind']=='zoom' and payload['meta'].get('page')=='snapshot' else assets.ratio_reading_header if payload['kind']=='zoom' else assets.inspect_header)
    image=payload['source'];x,y,w,h=payload['source_rect']
    #   ⚠️ 2026-10-31：600P 的源图是 800x600，而 SOURCE_RECT 固定 640x480，
    #      直接赋值会 ValueError: could not broadcast (600,800,3) into (480,640,3)。
    #      640x480 档位两者相等，走原路径，行为不变。
    #      坐标换算不在这里做 —— `_source_scale()` 已按 (源/矩形) 处理好触摸点。
    if image.shape[:2]!=(h,w):
        canvas[y:y+h,x:x+w]=cv2.resize(image,(w,h),interpolation=cv2.INTER_NEAREST)
    else:
        canvas[y:y+h,x:x+w]=image
    if payload['kind']=='calibration':
        canvas[108:340,704:1248]=assets.calibration_help
        points=payload['points']
        selected=payload.get('selected')
        if selected is not None and selected<len(points):
            fx,fy=points[selected];oh,ow=image.shape[:2];lx,ly,lw,lh=CALIB_LOUPE
            span_w=min(ow,lw//4);span_h=min(oh,lh//4)
            sx=int(np.clip(round(fx)-span_w//2,0,ow-span_w));sy=int(np.clip(round(fy)-span_h//2,0,oh-span_h))
            cv2.resize(image[sy:sy+span_h,sx:sx+span_w],(lw,lh),dst=canvas[ly:ly+lh,lx:lx+lw],interpolation=cv2.INTER_NEAREST)
            px=lx+int(round((fx-sx+.5)*lw/span_w-.5));py=ly+int(round((fy-sy+.5)*lh/span_h-.5))
            cv2.line(canvas,(max(lx,px-13),py),(min(lx+lw-1,px+13),py),(0,230,255),1,cv2.LINE_AA)
            cv2.line(canvas,(px,max(ly,py-13)),(px,min(ly+lh-1,py+13)),(0,230,255),1,cv2.LINE_AA)
            cv2.rectangle(canvas,(lx-1,ly-1),(lx+lw,ly+lh),(80,230,255),1)
            cv2.putText(canvas,'P%d (%d, %d)'%(selected+1,round(fx),round(fy)),(980,328),cv2.FONT_HERSHEY_SIMPLEX,.48,(100,235,245),1,cv2.LINE_AA)
        if len(points)==4:
            try:q=selected_quad(points,payload['meta']['source_shape'])
            except ValueError:q=None
            if q is not None:cv2.polylines(canvas,[np.rint(q+[x,y]).astype(np.int32)],True,(80,230,255),2,cv2.LINE_AA)
        for i,p in enumerate(points):
            v=tuple(np.rint(np.asarray(p)+[x,y]).astype(int));cv2.circle(canvas,v,7,(30,230,255),2,cv2.LINE_AA)
            if i==selected:cv2.circle(canvas,v,14,(70,245,255),2,cv2.LINE_AA)
            cv2.putText(canvas,str(i+1),(v[0]+10,v[1]-8),cv2.FONT_HERSHEY_SIMPLEX,.65,(30,230,255),2,cv2.LINE_AA)
        for name,rect in CALIB_CONTROLS.items():
            a,b,c,d=rect;canvas[b:b+d,a:a+c]=assets.inspection_buttons[name]
        notice=payload['notice'];message=assets.calibration_notices.get(notice,assets.calibration_notices['select'])
        canvas[542:606,716:1228]=message
        cv2.putText(canvas,'POINTS %d / 4 | SOURCE seq=%s'%(len(points),payload['meta']['sequence']),
            (32,112),cv2.FONT_HERSHEY_SIMPLEX,.65,(230,230,230),1,cv2.LINE_AA)
