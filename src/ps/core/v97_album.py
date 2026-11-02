"""Event-only SD captures and touch album. The HDMI owner alone reads video pixels.

The IO worker receives owned ordinary RAM, never camera/CMA/VideoFrame references.
No directory access, image copy, encoding or decode occurs on an idle live frame.
"""
from pathlib import Path
from contextvars import copy_context
from collections import OrderedDict
import hashlib,os,threading,time,uuid
import cv2
import numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

CAPTURE_RECT=(1000,640,120,56)
ALBUM_RECT=(1132,640,120,56)
BACK_RECT=(0,0,216,72)
PHOTO_RECT=(32,96,1216,520)
TILES=tuple((40+c*408,100+r*260,384,240) for r in range(2) for c in range(3))
FOOTER=tuple((32+i*200,632,184,64) for i in range(6))
BUTTON_NAMES=('previous','next','grid','zoom','delete','clear','confirm','cancel')
NOTICE_NAMES=('idle','waiting','saving','saved','error','unavailable','busy','empty','loading','deleted','confirm','select')


def inside(point,rect):
    x,y,w,h=rect
    return point is not None and x<=point[0]<x+w and y<=point[1]<y+h


def event(stage,**detail):
    # A completed SD task can outlive application logging during a slow shutdown.
    try:checkpoint(stage,**detail)
    except BaseException:pass


class MediaAssets:
    def __init__(self,root):
        def read(name,shape):
            value=cv2.imread(str(root/name),cv2.IMREAD_COLOR)
            if value is None or value.shape!=shape:raise ValueError('Invalid album asset '+name)
            value.setflags(write=False)
            return value
        self.bar=read('v97_media_bar.png',(56,252,3))
        self.header=read('v97_album_header.png',(72,1280,3))
        buttons=read('v97_album_buttons.png',(len(BUTTON_NAMES)*64,184,3))
        self.buttons={name:buttons[i*64:(i+1)*64] for i,name in enumerate(BUTTON_NAMES)}
        notices=read('v97_media_notices.png',(len(NOTICE_NAMES)*32,244,3))
        self.notices={name:notices[i*32:(i+1)*32] for i,name in enumerate(NOTICE_NAMES)}


class MediaController:
    def __init__(self,display,directory='/home/xilinx/captures',quality=90):
        folder=Path(directory).expanduser()
        if not folder.is_absolute():raise ValueError('capture_dir must be absolute')
        if not 70<=int(quality)<=95:raise ValueError('capture_jpeg_quality must be 70..95')
        self.display=display;self.folder=folder;self.quality=int(quality)
        self.assets=display.ui_assets.media_assets
        self.worker=None;self.context=copy_context();self.closed=False
        self.capture_request=None;self.save_job=None;self.delete_job=None;self.load_job=None
        self.saving=False;self.notice='idle';self.notice_until=0.;self.frozen_redraw=False
        self.live_tokens={};self.revision=0;self.presented_revision=-1;self.model={};self.files=();self.selected=set()
        self.mode='grid';self.page=0;self.photo_name=None;self.zoom=1;self.focus=None
        self.confirm_names=();self.return_mode='grid';self.thumb_cache=OrderedDict()
        self.opened_at=None;self.album_seconds=0.;self.saved=0;self.deleted=0;self.failures=0

    @property
    def active(self):
        return self.display.inspection.kind=='album'

    def _start_locked(self):
        if self.worker is None:
            worker=threading.Thread(target=lambda:self.context.run(self._run),name='photo_sd_io',daemon=True)
            self.worker=worker
            try:worker.start()
            except BaseException:self.worker=None;raise

    def _notice_locked(self,name,seconds=2.):
        self.notice=name;self.notice_until=time.perf_counter()+seconds
        self.frozen_redraw=True;self.display.condition.notify_all()

    def _discard_pending_locked(self):
        d=self.display
        if d.pending is not None:d.pending=None;d.ui_discarded+=1
        # Active/copying slots retain their original ownership until their caller finishes.
        for i,reference in enumerate(d.output_refs):
            if i not in (d.active_slot,d.copying_slot) and reference is not None:
                d.output_refs[i]=None;reference.release()

    def _model_locked(self,model):
        model=dict(model,revision=self.revision);self.model=model
        self.display.inspection.meta={'album':model}
        self.display.inspection.dirty=True
        self.display.condition.notify_all()

    def _schedule_locked(self,rescan=False):
        self.revision+=1
        ins=self.display.inspection
        self.load_job=dict(kind='load',revision=self.revision,token=ins.token,
            generation=ins.generation,mode=self.mode,page=self.page,photo=self.photo_name,
            zoom=self.zoom,focus=self.focus,files=tuple(self.files),rescan=rescan,
            selected=tuple(self.selected))
        self._model_locked(dict(self.model,mode=self.mode,busy=True,notice='loading',selected=tuple(self.selected)))
        try:self._start_locked()
        except Exception as exc:
            self.load_job=None
            self._model_locked(dict(self.model,busy=False,notice='error'))
            event('PHOTO_WORKER_START_FAILED',exception=repr(exc),realtime_pipeline_continues=True)
        self.display.condition.notify_all()

    def _open_locked(self,generation):
        d=self.display
        if d.inspection.kind:return False,'inspection_busy'
        if d.ui_view=='snapshot' and d.frozen_generation!=generation:return False,'snapshot_still_capturing'
        if self.capture_request is not None:
            self.capture_request=None;self.saving=False;self._notice_locked('unavailable')
        self._discard_pending_locked()
        ins=d.inspection;ins.clear_locked();ins.kind='album';ins.generation=generation;ins.opened+=1
        self.mode='grid';self.page=0;self.selected.clear();self.confirm_names=();self.model={}
        self.opened_at=time.perf_counter();self._schedule_locked(rescan=True)
        event('ALBUM_OPEN',generation=generation,directory=str(self.folder),tracking_continues=True,hardware_access=False)
        return True,'album_opened'

    def _close_locked(self):
        d=self.display
        if self.opened_at is not None:self.album_seconds+=time.perf_counter()-self.opened_at
        self.opened_at=None;self.revision+=1;self.load_job=None;self.model={};self.files=()
        self.selected.clear();self.confirm_names=()
        d.inspection.clear_locked();self._discard_pending_locked()
        d.canvas_views.clear();d.layouts.clear();self.live_tokens.clear()
        d.current_times.clear();d.submit_times.clear()
        d.inspection_restore=bool(d.ui_view=='snapshot' and d.last_static_packet is not None)
        d.condition.notify_all()
        event('ALBUM_CLOSE',generation=d.ui_generation,resume_latest=True,camera_restart=False,album_seconds=self.album_seconds)

    def page_changed_locked(self):
        # request_view may clear the Inspection before this hook is called.
        if self.opened_at is not None:self.album_seconds+=time.perf_counter()-self.opened_at
        self.opened_at=None;self.revision+=1;self.load_job=None;self.model={};self.files=()
        self.selected.clear();self.confirm_names=();self.live_tokens.clear();self.frozen_redraw=False
        if self.capture_request is not None:self.capture_request=None;self.saving=False

    def touch(self,touch,generation):
        """Called under UIState's lock; image data and SD access never enter this handler."""
        d=self.display
        with d.condition:
            if self.closed or d.stop or generation!=d.ui_generation:return None
            if d.inspection.kind and not self.active:return None
            phase=touch['phase'];press=touch.get('press');origin=touch.get('press_outcome') or {}
            if phase=='cancel':return dict(target='media_background',accepted=False,consumed=True,reason='media_contact_cancelled') if self.active else None
            if self.active:
                target=self._target_locked(press)
                if phase=='press':
                    if target=='media_back':
                        self._close_locked()
                        return dict(target=target,accepted=True,consumed=True,reason='album_return_on_press')
                    return dict(target=target,accepted=False,consumed=False,reason='await_album_release',media_revision=self.revision)
            else:
                target='media_capture' if inside(press,CAPTURE_RECT) else 'media_open' if inside(press,ALBUM_RECT) else None
                if phase=='press':
                    return None if target is None else dict(target=target,accepted=False,consumed=False,reason='await_media_release')
                if not str(origin.get('target','')).startswith('media_'):return None
            target=origin.get('target') or target
            result=dict(target=target,accepted=False,consumed=True,reason='media_release_rejected')
            release=touch.get('release')
            if (origin.get('generation')!=generation or origin.get('page')!=d.ui_view or release is None
                    or touch.get('peak_motion',0.)>32):return result
            if self.active:
                if origin.get('media_revision')!=self.revision or self._target_locked(release)!=target:return result
                accepted,reason=self._activate_locked(target,release)
            elif target=='media_capture' and inside(release,CAPTURE_RECT):
                if self.saving:accepted,reason=False,'capture_busy';self._notice_locked('busy')
                elif d.latest_meta.get('state') not in ('CURRENT','MANUAL'):
                    accepted,reason=False,'capture_requires_current_result';self._notice_locked('unavailable')
                else:
                    self.saving=True;self.capture_request=(generation,time.perf_counter()+2.)
                    self._notice_locked('waiting');accepted,reason=True,'capture_requested'
            elif target=='media_open' and inside(release,ALBUM_RECT):accepted,reason=self._open_locked(generation)
            else:accepted,reason=False,'media_release_outside'
            return dict(result,accepted=accepted,reason=reason,request_generation=generation if accepted else None)

    def _target_locked(self,point):
        if inside(point,BACK_RECT):return 'media_back'
        if self.model.get('busy') or self.presented_revision!=self.revision:return 'media_background'
        if self.mode=='confirm':
            return 'media_confirm' if inside(point,FOOTER[3]) else 'media_cancel' if inside(point,FOOTER[4]) else 'media_background'
        names=('previous','next','grid','zoom','delete','clear')
        for name,rect in zip(names,FOOTER):
            if inside(point,rect):return 'media_'+name
        if self.mode=='grid':
            for i,rect in enumerate(TILES[:len(self.model.get('items',()))]):
                if inside(point,rect):
                    x,y,w,h=rect
                    return 'media_select_'+str(i) if inside(point,(x+w-64,y+h-58,64,58)) else 'media_photo_'+str(i)
        elif self.mode=='photo' and inside(point,PHOTO_RECT):return 'media_focus'
        return 'media_background'

    def _activate_locked(self,target,point):
        if target.startswith(('media_select_','media_photo_')):
            i=int(target.rsplit('_',1)[1]);name=self.model['items'][i]['name']
            if target.startswith('media_select_'):
                if name in self.selected:self.selected.remove(name)
                else:self.selected.add(name)
                self.revision+=1;self._model_locked(dict(self.model,selected=tuple(self.selected)))
            else:
                self.mode='photo';self.photo_name=name;self.zoom=1;self.focus=None;self._schedule_locked()
        elif target in ('media_previous','media_next'):
            step=-1 if target=='media_previous' else 1
            if self.mode=='grid':self.page=max(0,min(max(0,(len(self.files)-1)//6),self.page+step))
            elif self.files:
                index=self.files.index(self.photo_name) if self.photo_name in self.files else 0
                self.photo_name=self.files[max(0,min(len(self.files)-1,index+step))];self.zoom=1;self.focus=None
            self._schedule_locked()
        elif target=='media_grid':self.mode='grid';self._schedule_locked(rescan=True)
        elif target=='media_zoom':
            if self.mode=='photo':self.zoom={1:2,2:4,4:1}[self.zoom];self._schedule_locked()
            elif len(self.selected)==1:
                self.mode='photo';self.photo_name=next(iter(self.selected));self.zoom=1;self.focus=None;self._schedule_locked()
            else:self._model_locked(dict(self.model,notice='select'));return False,'select_one_photo_to_view'
        elif target=='media_focus' and self.mode=='photo':
            mapping=self.model.get('mapping')
            if mapping:
                sx,sy,scale,x,y,w,h=mapping
                if inside(point,(x,y,w,h)):
                    self.focus=(sx+(point[0]-x)/scale,sy+(point[1]-y)/scale)
                    if self.zoom==1:self.zoom=2
                    self._schedule_locked()
        elif target=='media_clear':
            self.selected.clear();self.revision+=1;self._model_locked(dict(self.model,selected=()))
        elif target=='media_delete':
            names=tuple(self.selected) if self.mode=='grid' else (self.photo_name,) if self.photo_name else ()
            if not names:
                self._model_locked(dict(self.model,notice='select'))
                return False,'select_photos_before_delete'
            self.confirm_names=names;self.return_mode=self.mode;self.mode='confirm';self.revision+=1
            self._model_locked(dict(self.model,mode='confirm',delete_count=len(names),notice='confirm'))
        elif target=='media_cancel':self.mode=self.return_mode;self.confirm_names=();self._schedule_locked()
        elif target=='media_confirm':
            if self.delete_job is not None:return False,'delete_busy'
            self.revision+=1
            self.delete_job=dict(kind='delete',names=self.confirm_names,revision=self.revision)
            self.mode='grid';self._model_locked(dict(self.model,mode='grid',busy=True,notice='loading'))
            try:self._start_locked()
            except Exception as exc:
                self.delete_job=None;self._model_locked(dict(self.model,busy=False,notice='error'))
                event('PHOTO_WORKER_START_FAILED',exception=repr(exc),realtime_pipeline_continues=True)
                return False,'delete_worker_unavailable'
            self.display.condition.notify_all()
        else:return False,'album_outside_controls'
        return True,target

    def capture_from_output(self,out,meta):
        """Only HDMI owner calls this while active_slot pins the completed output."""
        if self.capture_request is None:return
        d=self.display
        with d.condition:
            request=self.capture_request
            if request is None:return
            generation,deadline=request
            if (generation!=meta.get('ui_generation') or d.ui_generation!=generation
                    or time.perf_counter()>deadline or out is None or meta.get('state') not in ('CURRENT','MANUAL')):
                self.capture_request=None;self.saving=False;self._notice_locked('unavailable');return
            self.capture_request=None
        began=time.perf_counter()
        try:
            if out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=4 or out.nbytes>4*1280*720:
                raise ValueError('Invalid completed capture layout')
            image=np.array(out,copy=True,order='C');image.setflags(write=False)
            copied=dict(index=int(meta.get('index',-1)),camera_sequence=int(meta.get('camera_sequence',-1)),
                capture_ready_at=float(meta.get('capture_ready_at',0.)),state=meta.get('state'),
                width=int(image.shape[1]),height=int(image.shape[0]),requested_generation=generation)
            with d.condition:
                if self.closed:self.saving=False;return
                self.save_job=(image,copied);self._notice_locked('saving',30.);self._start_locked();d.condition.notify_all()
            event('PHOTO_CAPTURE_COPIED',**copied,copy_s=time.perf_counter()-began,ordinary_RAM_bytes=image.nbytes,hardware_reference_retained=False)
        except BaseException as exc:
            with d.condition:self.save_job=None;self.saving=False;self.failures+=1;self._notice_locked('error')
            event('PHOTO_CAPTURE_FAILED',exception=repr(exc),realtime_pipeline_continues=True)

    def render_live(self,canvas,address,page_changed):
        # Cached patches are installed once per VideoFrame/status, never rebuilt.
        notice=self.notice if time.perf_counter()<self.notice_until else 'idle'
        token=(self.display.ui_generation,notice)
        if not page_changed and self.live_tokens.get(address)==token:return
        canvas[640:696,1000:1252]=self.assets.bar
        canvas[652:684,744:988]=self.assets.notices[notice]
        self.live_tokens[address]=token
        if len(self.live_tokens)>16:self.live_tokens={address:token}

    def presented_locked(self,payload):
        model=payload['meta'].get('album',{})
        if self.active and model.get('revision')==self.revision:
            self.presented_revision=self.revision
        event('ALBUM_PRESENTED',generation=payload['generation'],revision=model.get('revision'),
            mode=model.get('mode'),count=model.get('total',0),not_live_HDMI_FPS=True)

    def frozen_wait_locked(self):
        if self.notice=='idle':return None
        remaining=self.notice_until-time.perf_counter()
        if remaining>0:return remaining
        self.notice='idle';self.frozen_redraw=True
        return 0.

    @staticmethod
    def _name_ok(name):
        return isinstance(name,str) and Path(name).name==name and name.startswith('capture_') and name.endswith('.jpg')

    def _path(self,name):
        if not self._name_ok(name):raise ValueError('Invalid captured photo name')
        root=self.folder.resolve();path=(root/name).resolve()
        if path.parent!=root:raise ValueError('Photo is outside capture directory')
        return path

    def _thumb_path(self,name):
        if not self._name_ok(name):raise ValueError('Invalid thumbnail name')
        root=self.folder.resolve();directory=root/'.thumbs'
        if directory.is_symlink():raise ValueError('Thumbnail directory cannot be a symlink')
        path=(directory/name).resolve()
        if path.parent!=directory or directory.parent!=root:raise ValueError('Thumbnail is outside capture directory')
        return path

    def _scan(self):
        if not self.folder.exists():return ()
        # A bounded gallery of the most recent captures; scanning only happens on events.
        import heapq
        with os.scandir(self.folder) as entries:
            return tuple(heapq.nlargest(2000,(e.name for e in entries if self._name_ok(e.name) and e.is_file(follow_symlinks=False))))

    @staticmethod
    def _atomic(path,data):
        temporary=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()

    def _save(self,job):
        image,meta=job;began=time.perf_counter()
        self.folder.mkdir(parents=True,exist_ok=True)
        # Strip the unused X channel on the low-priority IO thread.
        bgr=cv2.cvtColor(image,cv2.COLOR_BGRA2BGR)
        okay,encoded=cv2.imencode('.jpg',bgr,[cv2.IMWRITE_JPEG_QUALITY,self.quality])
        if not okay:raise OSError('JPEG encoder failed')
        stamp=time.strftime('%Y%m%d_%H%M%S')
        name='capture_%s_%s_f%06d_%s.jpg'%(stamp,str(time.time_ns())[-9:],meta['camera_sequence'],uuid.uuid4().hex[:8])
        path=self._path(name);self._atomic(path,encoded.tobytes())
        # Thumbnail failure must not turn an already saved full photo into a failure.
        try:
            thumb=self._fit(bgr,344,184)[0]
            okay,small=cv2.imencode('.jpg',thumb,[cv2.IMWRITE_JPEG_QUALITY,80])
            if okay:
                thumb_path=self._thumb_path(name);thumb_path.parent.mkdir(exist_ok=True)
                self._atomic(thumb_path,small.tobytes())
        except Exception as exc:event('PHOTO_THUMBNAIL_DEFERRED',file=name,exception=repr(exc))
        event('PHOTO_SAVED',file=str(path),bytes=int(encoded.size),elapsed_s=time.perf_counter()-began,**meta)
        with self.display.condition:
            self.saved+=1;self.saving=False
            if not self.closed:
                self._notice_locked('saved')
                if self.active and self.mode=='grid':self._schedule_locked(rescan=True)

    @staticmethod
    def _fit(image,width,height,enlarge=False,zoom=1,focus=None):
        h,w=image.shape[:2];factor=min(width/w,height/h)
        if not enlarge:factor=min(1.,factor)
        factor*=zoom
        cw=min(w,max(1,int(width/factor)));ch=min(h,max(1,int(height/factor)))
        cx,cy=(w/2,h/2) if focus is None else focus
        sx=int(np.clip(cx-cw/2,0,w-cw));sy=int(np.clip(cy-ch/2,0,h-ch))
        dw=min(width,max(1,int(round(cw*factor))));dh=min(height,max(1,int(round(ch*factor))))
        x=(width-dw)//2;y=(height-dh)//2
        result=np.zeros((height,width,3),np.uint8)
        cv2.resize(image[sy:sy+ch,sx:sx+cw],(dw,dh),dst=result[y:y+dh,x:x+dw],interpolation=cv2.INTER_LINEAR)
        result.setflags(write=False)
        return result,(sx,sy,factor,x,y,dw,dh)

    def _read(self,path):
        if path.stat().st_size>16*1024*1024:raise ValueError('Captured photo exceeds gallery limit')
        image=cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        if image is None or image.shape[0]*image.shape[1]>1280*720:raise ValueError('Invalid captured photo dimensions')
        return image

    def _thumb(self,name):
        value=self.thumb_cache.get(name)
        if value is not None:self.thumb_cache.move_to_end(name);return value
        try:
            path=self._thumb_path(name)
            image=self._read(path) if path.is_file() else self._read(self._path(name))
        except Exception:return None
        value=self._fit(image,344,184)[0];self.thumb_cache[name]=value
        while len(self.thumb_cache)>8:self.thumb_cache.popitem(last=False)
        return value

    def _load(self,job):
        names=self._scan() if job['rescan'] else job['files']
        mode=job['mode'];page=max(0,min(job['page'],max(0,(len(names)-1)//6)))
        model=dict(mode=mode,busy=False,files=names,page=page,total=len(names),selected=job['selected'],notice='empty' if not names else 'idle')
        if mode=='photo' and job['photo'] in names:
            name=job['photo'];image=self._read(self._path(name))
            fitted,mapping=self._fit(image,PHOTO_RECT[2],PHOTO_RECT[3],zoom=job['zoom'],focus=job['focus'])
            sx,sy,factor,x,y,w,h=mapping
            model.update(photo=name,image=fitted,zoom=job['zoom'],position=names.index(name)+1,
                mapping=(sx,sy,factor,x+PHOTO_RECT[0],y+PHOTO_RECT[1],w,h))
        else:
            model['mode']='grid';model['items']=tuple(dict(name=n,image=self._thumb(n)) for n in names[page*6:page*6+6])
        d=self.display
        with d.condition:
            if (not self.closed and self.active and job['revision']==self.revision
                    and job['generation']==d.ui_generation and job['token']==d.inspection.token):
                if time.perf_counter()<self.notice_until and self.notice in ('error','deleted','saved'):
                    model['notice']=self.notice
                self.files=names;self.page=page;self.mode=model['mode'];self._model_locked(model)

    def _delete(self,job):
        removed=0;errors=[]
        for name in job['names']:
            try:
                path=self._path(name)
                if path.exists():path.unlink();removed+=1
                thumb=self._thumb_path(name)
                if thumb.exists() and not thumb.is_symlink():thumb.unlink()
                self.thumb_cache.pop(name,None)
            except Exception as exc:errors.append((name,repr(exc)))
        event('PHOTO_DELETE_COMPLETED',confirmed=True,requested=len(job['names']),deleted=removed,errors=errors)
        with self.display.condition:
            self.deleted+=removed;self.selected.clear();self.confirm_names=()
            if not self.closed:
                self._notice_locked('error' if errors else 'deleted')
                if self.active:self.mode='grid';self.page=0;self._schedule_locked(rescan=True)

    def _run(self):
        try:
            # Linux nice applies to this worker's native thread only.
            if hasattr(os,'setpriority') and hasattr(threading,'get_native_id'):
                try:os.setpriority(os.PRIO_PROCESS,threading.get_native_id(),10)
                except OSError:pass
            while True:
                with self.display.condition:
                    while not self.closed and self.save_job is None and self.delete_job is None and self.load_job is None:
                        self.display.condition.wait()
                    if self.save_job is not None:kind='save';job=self.save_job;self.save_job=None
                    elif self.delete_job is not None:kind='delete';job=self.delete_job;self.delete_job=None
                    elif self.closed:return
                    else:kind='load';job=self.load_job;self.load_job=None
                try:
                    if kind=='save':self._save(job)
                    elif kind=='delete':self._delete(job)
                    else:self._load(job)
                except BaseException as exc:
                    event('PHOTO_IO_FAILED',operation=kind,exception=repr(exc),hardware_reference_retained=False)
                    with self.display.condition:
                        self.failures+=1
                        if kind=='save':self.saving=False
                        if not self.closed:
                            self._notice_locked('error')
                            if self.active:self._model_locked(dict(self.model,busy=False,notice='error'))
                finally:job=None
        finally:event('PHOTO_IO_STOPPED',hardware_references=False)

    def statistics_locked(self):
        seconds=self.album_seconds+(time.perf_counter()-self.opened_at if self.opened_at is not None else 0.)
        return dict(directory=str(self.folder),saved=self.saved,deleted=self.deleted,failures=self.failures,
            album_active=self.active,album_seconds=seconds,capture_busy=self.saving,
            worker_started=self.worker is not None,encoding_on_live_thread=False)

    def close(self):
        with self.display.condition:
            self.closed=True;self.capture_request=None;self.load_job=None;self.display.condition.notify_all()
        worker=self.worker
        if worker is not None:
            worker.join(.5)
            if worker.is_alive():event('PHOTO_IO_FINISHING',owned_RAM_only=True,hardware_resources_retained=False)


def render_album(canvas,payload,assets):
    """Event-only composition. All file reads/decodes/resizes happened on the IO worker."""
    album=payload['meta'].get('album',{});media=assets.media_assets
    canvas[:]=(14,12,10);canvas[:72]=media.header
    mode=album.get('mode','grid');selected=set(album.get('selected',()))
    if mode=='photo' and album.get('image') is not None:
        x,y,w,h=PHOTO_RECT;canvas[y:y+h,x:x+w]=album['image']
        title='%d / %d | %dx | %s'%(album.get('position',0),album.get('total',0),album.get('zoom',1),album.get('photo',''))
    else:
        items=album.get('items',())
        for rect,item in zip(TILES,items):
            x,y,w,h=rect;cv2.rectangle(canvas,(x,y),(x+w-1,y+h-1),(45,42,38),-1)
            image=item.get('image')
            if image is not None:canvas[y+10:y+194,x+20:x+364]=image
            cv2.putText(canvas,item['name'][:41],(x+12,y+220),cv2.FONT_HERSHEY_SIMPLEX,.36,(225,225,225),1,cv2.LINE_AA)
            checked=item['name'] in selected
            color=(235,205,60) if checked else (125,115,105)
            cv2.rectangle(canvas,(x+w-48,y+h-44),(x+w-18,y+h-14),color,2)
            if checked:cv2.line(canvas,(x+w-43,y+h-29),(x+w-34,y+h-20),color,3);cv2.line(canvas,(x+w-34,y+h-20),(x+w-22,y+h-37),color,3)
        title='SD CARD | %d photos | page %d | selected %d'%(album.get('total',0),album.get('page',0)+1,len(selected))
    if mode!='confirm':
        for name,rect in zip(('previous','next','grid','zoom','delete','clear'),FOOTER):
            x,y,w,h=rect;canvas[y:y+h,x:x+w]=media.buttons[name]
    cv2.putText(canvas,title[:88],(390,46),cv2.FONT_HERSHEY_SIMPLEX,.42,(235,235,235),1,cv2.LINE_AA)
    notice=album.get('notice','idle')
    if notice!='idle':canvas[20:52,1012:1256]=media.notices.get(notice,media.notices['error'])
    if mode=='confirm':
        cv2.rectangle(canvas,(344,230),(936,454),(28,25,22),-1)
        cv2.rectangle(canvas,(344,230),(936,454),(105,95,85),2)
        canvas[278:310,518:762]=media.notices['confirm']
        cv2.putText(canvas,'%d PHOTO(S)'%album.get('delete_count',0),(518,370),cv2.FONT_HERSHEY_SIMPLEX,.8,(235,235,235),1,cv2.LINE_AA)
        for name,rect in (('confirm',FOOTER[3]),('cancel',FOOTER[4])):
            x,y,w,h=rect;canvas[y:y+h,x:x+w]=media.buttons[name]
