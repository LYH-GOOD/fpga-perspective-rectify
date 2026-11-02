"""One-time corner handoff and cached source label; no per-frame AI hooks."""
from pathlib import Path
from contextlib import contextmanager
import hashlib,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v92_manual_v87 import ManualTracker
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def unchanged(a,b):
    # Full observed gray image, not a few sample pixels. Restrictive thresholds
    # deliberately fall back to complete FB on camera noise/exposure changes.
    if a.shape!=b.shape:return False
    diff=cv2.absdiff(a,b)
    return float(cv2.norm(diff,cv2.NORM_INF))<=1. and float(cv2.mean(diff)[0])<=.15


def align_current(context,camera,frozen,quad):
    """Never seed a moving live tracker directly from the old inference frame."""
    from v79_acquire import OwnedFrame
    verifier=None;current=None
    try:
        context.check();lease=camera.take(3.)
        try:
            image=np.array(lease.image,copy=True,order='C');image.setflags(write=False)
            current=OwnedFrame(image,float(lease.ready),int(lease.sequence),float(lease.timestamp),int(lease.flags))
        finally:lease.release()
        context.check()
        primary_failure=None
        try:
            from v105_manual_tracking import PersistentManualTracker
            verifier=PersistentManualTracker(frozen,quad,320,authority='ai_bridge')
            if getattr(verifier,'physical',False):
                q,detail=verifier.update(current,radius=12.)
                if q is None:raise ValueError(str(detail.get('reason')))
                method='manual_default_physical_fallback'
            else:
                gray,scale=verifier.observer.get(current.image)
                if np.array_equal(scale,verifier.scale) and unchanged(verifier.gray,gray):
                    q=np.asarray(quad,np.float32).copy();method='strict_gray_static'
                elif verifier.fixed:raise ValueError('current alignment needs texture or static continuity')
                else:
                    q,detail=verifier.update(current)
                    if q is None:raise ValueError(str(detail.get('reason')))
                    method='original_complete_FB_RANSAC'
        except (ValueError,cv2.error) as exc:
            primary_failure=str(exc)
            if verifier is not None:verifier.close();verifier=None
            # One bounded physical-body fallback at admission only; all old
            # exterior gates remain. Never grant CURRENT to an old AI quad.
            try:
                from v104_physical_tracking import PhysicalTracker
                verifier=PhysicalTracker(frozen,quad,320,authority='ai_bridge_physical_fallback')
                q,detail=verifier.update(current,radius=12.)
                if q is None:raise ValueError(str(detail.get('reason')))
                method='manual_then_physical_four_edges'
            except (ValueError,cv2.error) as fallback:
                raise ValueError('AI current-frame alignment failed: manual='+primary_failure+'; physical='+str(fallback)) from fallback
        context.check()
        checkpoint('AI_CURRENT_FRAME_ALIGNED',generation=context.generation,source_sequence=frozen.sequence,
            current_sequence=current.sequence,source_age_s=max(0.,current.ready-frozen.ready),method=method,
            current_anchor=True,non_physical_FB_thresholds_preserved=True,
            physical_four_edge_evidence=getattr(verifier,'physical',False),primary_failure=primary_failure,
            admission_strategy='manual first, one bounded physical fallback')
        return current,q
    except BaseException:
        if current is not None:current.release()
        raise
    finally:
        if verifier is not None:verifier.close()


@contextmanager
def badges(display):
    assets=getattr(display,'ui_assets',None)
    if assets is None:yield;return
    image=cv2.imdecode(np.frombuffer((Path(__file__).resolve().parent/'v100_ai_badges.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if image is None or image.shape!=(84,320,3):raise ValueError('Invalid AI status badges')
    image.setflags(write=False)
    names=('MANUAL','MANUAL_HELD','MANUAL_FIXED');old={n:assets.status_badges[n] for n in names}
    previous_template=display.manual_status_template
    try:
        for i,n in enumerate(names):assets.status_badges[n]=image[i*28:(i+1)*28]
        display.manual_status_template='AI ASSIST %s | CORR %.1f | DISP %.1f | %s'
        yield
    finally:
        assets.status_badges.update(old);display.manual_status_template=previous_template


def run_ai(context,**kwargs):
    from v82_manual import run_manual
    checkpoint('AI_CORRECTION_SESSION_BEGIN',generation=context.generation,corner_source='ai',
        tracking='AI physical-body seed then batched physical edges; other planes retain FB',automatic_pipeline='shared correction backend',
        ai_flow_revision='20261027-9-recovery',inference_required=True,background_inference=False)
    with badges(context.display):return run_manual(context,**kwargs)
