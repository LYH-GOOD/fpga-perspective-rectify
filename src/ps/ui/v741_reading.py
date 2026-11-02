"""Reading-only geometry, contact ownership and owner-side event rendering."""
from pathlib import Path
import hashlib,math,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def geometry(image,focus,factor):
    h,w=image.shape[:2];span=max(16,min(w,h,392//factor))
    sx=max(0,min(w-span,int(round(focus[0]))-span//2))
    sy=max(0,min(h-span,int(round(focus[1]))-span//2))
    side=min(392,span*factor)
    return (sx,sy,span),(716+(512-side)//2,148+(392-side)//2,side,side)


def inside(point,rect):
    if point is None or len(point)!=2 or not all(math.isfinite(v) for v in point):return False
    x,y,w,h=rect;return x<=point[0]<x+w and y<=point[1]<y+h


class ReadingPan:
    def __init__(self,inspection):
        self.inspection=inspection;self.contact=None;self.canvases={}
    def clear_locked(self):
        self.contact=None;self.canvases.clear()
    def cancel_locked(self,contact_id=None):
        if self.contact is None or contact_id is not None and self.contact['id']!=contact_id:return False
        self.contact=None;return True
    def target_locked(self,point):
        i=self.inspection
        if inside(point,i.source_rect):return 'inspect_focus'
        _,rect=geometry(i.source,i.focus,i.scale)
        if inside(point,rect):return 'inspect_pan'
        return None
    def begin(self,point,generation,contact_id):
        i=self.inspection
        with i.display.condition:
            if i.kind!='zoom' or generation!=i.generation or i.display.stop or contact_id is None:
                return False,'reading_unavailable',i.token
            target=self.target_locked(point)
            if target is None:return False,'outside_reading_image',i.token
            roi,_=geometry(i.source,i.focus,i.scale)
            self.contact=dict(id=contact_id,token=i.token,generation=generation,target=target,
                press=tuple(point),roi=roi,scale=i.scale,began=time.perf_counter())
            return True,'reading_contact_started',i.token
    def matching_locked(self,event,generation):
        i=self.inspection;c=self.contact;origin=event.get('press_outcome') or {}
        return bool(c is not None and i.kind=='zoom' and i.generation==generation
            and c['generation']==generation and c['token']==i.token
            and origin.get('inspection_token')==i.token and origin.get('target')==c['target']
            and event.get('contact_id')==c['id'])
    def update_locked(self,point):
        if point is None or len(point)!=2 or not all(math.isfinite(v) for v in point):return False
        i=self.inspection;c=self.contact;sx,sy,span=c['roi'];h,w=i.source.shape[:2]
        if c['target']=='inspect_focus':
            #   ⭐ 2026-10-27：源图可能被等比缩小显示（如 800x600 缩到 640x480），
            #      屏幕点要先换算成源图坐标再取 ROI。
            px,py=i._to_source(point)
            sx=int(round(px))-span//2;sy=int(round(py))-span//2
        else:
            # Move paper with the finger; map screen delta through the actual scale.
            sx=int(round(sx-(point[0]-c['press'][0])/c['scale']))
            sy=int(round(sy-(point[1]-c['press'][1])/c['scale']))
        focus=(max(0,min(w-span,sx))+span//2,max(0,min(h-span,sy))+span//2)
        if focus!=i.focus:
            i.focus=focus;i.dirty=True;i.display.condition.notify_all()
        return True
    def move(self,event,generation):
        i=self.inspection
        with i.display.condition:
            if not self.matching_locked(event,generation):return False,'reading_contact_changed'
            ok=self.update_locked(event.get('position'))
            return ok,'reading_pan_preview' if ok else 'missing_move_coordinates'
    def finish(self,event,generation):
        i=self.inspection
        with i.display.condition:
            if not self.matching_locked(event,generation):return False,'reading_contact_changed'
            c=self.contact;ok=self.update_locked(event.get('release'));self.contact=None
            if not ok:return False,'missing_release_coordinates'
            checkpoint('READING_PAN_FINISHED',generation=generation,sequence=i.meta.get('sequence'),
                region='overview' if c['target']=='inspect_focus' else 'loupe',scale=i.scale,
                focus=i.focus,contact_s=time.perf_counter()-c['began'],frozen_source=True,event_only=True)
            return True,'reading_pan_finished'


def restore_outline(canvas,image,source_rect,roi):
    """Erase only the previous outline's strips on the re-owned canvas."""
    x,y,w,h=source_rect;sx,sy,span=roi;left=x+sx;top=y+sy;right=left+span;bottom=top+span
    pad=4
    for ax,ay,bx,by in ((left-pad,top-pad,right+pad,top+pad),
                        (left-pad,bottom-pad,right+pad,bottom+pad),
                        (left-pad,top-pad,left+pad,bottom+pad),
                        (right-pad,top-pad,right+pad,bottom+pad)):
        ax=max(0,ax);ay=max(0,ay);bx=min(canvas.shape[1],bx);by=min(canvas.shape[0],by)
        canvas[ay:by,ax:bx]=0
        ix=max(x,ax);iy=max(y,ay);ex=min(x+w,bx);ey=min(y+h,by)
        if ix<ex and iy<ey:canvas[iy:ey,ix:ex]=image[iy-y:ey-y,ix-x:ex-x]


def render_reading(canvas,payload,assets):
    image=payload['source'];x,y,w,h=payload['source_rect']
    cached=payload.get('reading_background_cached',False)
    if not cached:
        canvas.fill(0)
        canvas[:72]=assets.headers['snapshot'] if payload['meta'].get('page')=='snapshot' else assets.ratio_reading_header
        canvas[y:y+h,x:x+w]=image;canvas[92:140,716:1228]=assets.reading_help
        from v82_interaction import ZOOM_CONTROLS
        for name,(a,b,c,d) in ZOOM_CONTROLS.items():canvas[b:b+d,a:a+c]=assets.inspection_buttons[name]
    else:
        restore_outline(canvas,image,payload['source_rect'],payload['reading_previous_roi'])
        canvas[73:100,24:664]=0
    roi,rect=geometry(image,payload['focus'],payload['scale'])
    sx,sy,span=roi;dx,dy,side,_=rect
    # Only these event-driven patches change. No video input or new full-frame copy.
    canvas[148:540,716:1228]=0
    cv2.resize(image[sy:sy+span,sx:sx+span],(side,side),dst=canvas[dy:dy+side,dx:dx+side],interpolation=cv2.INTER_LINEAR)
    cv2.rectangle(canvas,(x+sx,y+sy),(x+sx+span-1,y+sy+span-1),(20,230,255),2,cv2.LINE_AA)
    cv2.putText(canvas,'%dx | FROZEN seq=%s'%(payload['scale'],payload['meta']['sequence']),
        (32,92),cv2.FONT_HERSHEY_SIMPLEX,.65,(230,230,230),1,cv2.LINE_AA)
    return roi
