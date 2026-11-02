"""Bounded observed camera stabilization and initial detection admission.

Every discarded MMAP frame is released once. Only an accepted frame transfers
its lease to the caller; no startup frame is submitted to DMA here.
"""
from pathlib import Path
import hashlib,time
import numpy as np
import cv2
from p11_contract import RELEASE_ID
from v31_pixels import model_bgr,require_yuyv
from v31_detection import QuadDetectionError
from run_logging import checkpoint,RUN_LOG

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def validate_startup(min_frames=12,max_frames=60,stable_pairs=4,timeout_s=3.,detect_attempts=6):
    for name,value in (('startup_min_frames',min_frames),('startup_max_frames',max_frames),
                       ('startup_stable_pairs',stable_pairs),('startup_detect_attempts',detect_attempts)):
        if isinstance(value,bool) or not isinstance(value,int):raise ValueError(name+'必须是整数')
    if not 3<=min_frames<=max_frames<=300 or not 2<=stable_pairs<max_frames:
        raise ValueError('启动帧数须满足3<=min<=max<=300，稳定比较次数须为2..max-1')
    if not 1<=detect_attempts<=12 or not np.isfinite(timeout_s) or not .5<=timeout_s<=10.:
        raise ValueError('首帧检测重试须为1..12次，启动稳定超时须为0.5..10秒')


def _signature(frame,mode):
    image=require_yuyv(frame.image)
    # Only a small strided probe is copied. No full-frame BGR/gray conversion is
    # needed to observe exposure and color stability during startup.
    y=image[::8,::8,0].astype(np.float32)
    if not mode&1:y=np.clip((y-16.)*(255./219.),0.,255.)
    levels=np.percentile(y,(10,50,90))
    u=float(np.median(image[::8,0::16,1]))
    v=float(np.median(image[::8,1::16,1]))
    return np.r_[levels,u,v],dict(luma_p10=float(levels[0]),luma_p50=float(levels[1]),
        luma_p90=float(levels[2]),u_median=u,v_median=v,
        dark_clip_fraction=float(np.mean(y<=2)),bright_clip_fraction=float(np.mean(y>=253)))


def stabilize_camera(camera,min_frames=12,max_frames=60,stable_pairs=4,timeout_s=3.):
    validate_startup(min_frames,max_frames,stable_pairs,timeout_s)
    began=time.perf_counter();deadline=began+timeout_s
    previous=None;previous_sequence=None;previous_ready=None;stable=0;sampling_s=0.;last={}
    tolerance=np.array([5.,3.,5.,3.,3.],np.float64)
    checkpoint('CAMERA_STABILITY_BEGIN',durable=True,min_frames=min_frames,max_frames=max_frames,
        stable_pairs=stable_pairs,timeout_s=timeout_s,tolerance=tolerance.tolist(),
        scope='startup_only_before_initial_detection_and_formal_measurement')
    observed=0
    try:
        for _ in range(max_frames):
            remaining=deadline-time.perf_counter()
            if remaining<=0:break
            try:frame=camera.take(remaining)
            except TimeoutError:
                # Frames were observed: reaching the final wait deadline means
                # stability was not proved, not that the camera supplied no YUYV.
                if observed:break
                raise
            keep=False
            observed+=1
            try:
                probe_begin=time.perf_counter();current,last=_signature(frame,camera.color_mode)
                sampling_s+=time.perf_counter()-probe_begin
                sequence_ok=(previous_sequence is None or
                    0<((frame.sequence-previous_sequence)&0xffffffff)<0x80000000)
                if previous_ready is not None and frame.ready<=previous_ready:sequence_ok=False
                if not sequence_ok:raise ValueError('启动观察的摄像头帧序号或时间不递增')
                delta=np.abs(current-previous) if previous is not None else None
                stable=stable+1 if delta is not None and bool(np.all(delta<=tolerance)) else 0
                previous=current;previous_sequence=frame.sequence;previous_ready=frame.ready
                # Require both enough distinct observations and a minimum real
                # settle time; statistics alone cannot establish camera focus.
                ready=(observed>=min_frames and stable>=stable_pairs and
                       time.perf_counter()-began>=min(.35,timeout_s*.5))
                if ready:
                    report=dict(state='observed_stable',frames_observed=observed,
                        frames_released=observed-1,consecutive_stable_pairs=stable,
                        stabilization_s=time.perf_counter()-began,sampling_s=sampling_s,
                        selected_sequence=int(frame.sequence),last_probe=last,
                        thresholds=tolerance.tolist(),focus_not_measured=True,
                        outside_formal_frame_measurement=True)
                    checkpoint('CAMERA_STABILITY_READY',durable=True,**report)
                    keep=True
                    return frame,report
            finally:
                if not keep:frame.release()
        raise TimeoutError('已收到有效YUYV帧，但启动截止前未能证明亮度/色度稳定（画面波动或后续帧不足）；请查看frames_observed/last_probe')
    except BaseException as exc:
        try:checkpoint('CAMERA_STABILITY_FAILED',durable=True,frames_observed=observed,
            stable_pairs=stable,elapsed_s=time.perf_counter()-began,last_probe=last,
            last_frame_age_s=None if previous_ready is None else time.perf_counter()-previous_ready,
            failure_scope='startup_stability_not_proven' if observed else 'no_valid_frame_observed',
            exception_type=type(exc).__name__,exception=str(exc))
        except BaseException:pass
        raise


def admit_initial_frame(camera,first,detector,attempts=6,timeout_s=6.,save_failed_frame=True,register_lease=None,candidate_preview=None):
    """Own first until accepted; return (lease, owned BGR, detection, report)."""
    began=time.perf_counter();deadline=began+timeout_s
    frame=first;history=[];last_bgr=None;last_failure=None;conversion_s=0.;detection_s=0.
    accepted=False
    try:
        for attempt in range(1,attempts+1):
            remaining=deadline-time.perf_counter()
            if remaining<=0:break
            if frame is None:
                try:frame=camera.take(remaining)
                except TimeoutError as exc:
                    if last_failure is None:raise
                    checkpoint('CAMERA_INITIAL_INPUT_TIMEOUT',exception=str(exc),failed_attempts=len(history))
                    break
            if register_lease is not None:register_lease(frame)
            convert_begin=time.perf_counter();bgr=model_bgr(frame.image)
            conversion_s+=time.perf_counter()-convert_begin
            if candidate_preview is not None:candidate_preview(frame,attempt)
            detect_begin=time.perf_counter()
            try:
                quad,info=detector(frame.image,bgr)
            except QuadDetectionError as exc:
                elapsed=time.perf_counter()-detect_begin;detection_s+=elapsed
                last_failure=exc;last_bgr=bgr
                failure=dict(attempt=attempt,sequence=int(frame.sequence),detection_s=elapsed,
                             reason=str(exc),diagnostics=exc.diagnostics)
                history.append(failure)
                checkpoint('CAMERA_INITIAL_DETECTION_RETRY',**failure)
                frame.release();frame=None
                continue
            elapsed=time.perf_counter()-detect_begin;detection_s+=elapsed
            report=dict(state='accepted',attempts=attempt,failed_attempts=len(history),
                selected_sequence=int(frame.sequence),color_conversion_s=conversion_s,
                detection_s=detection_s,admission_s=time.perf_counter()-began,
                corners=np.asarray(quad).tolist(),detector=info.get('detector'),
                failed_diagnostics=history,outside_formal_frame_measurement=True)
            checkpoint('CAMERA_INITIAL_DETECTION_READY',durable=True,**report)
            accepted=True
            return frame,bgr,(quad,info),report
        image_path=None
        if save_failed_frame and last_bgr is not None:
            path=RUN_LOG.parent/'camera_startup_failed.jpg'
            try:
                if cv2.imwrite(str(path),last_bgr):image_path=str(path)
            except (OSError,cv2.error) as image_error:
                checkpoint('CAMERA_FAILED_IMAGE_SAVE_ERROR',exception=str(image_error))
        checkpoint('CAMERA_INITIAL_DETECTION_FAILED',durable=True,attempts=len(history),
            elapsed_s=time.perf_counter()-began,last_failure=str(last_failure),
            image_path=image_path,failed_diagnostics=history,
            instruction='整张纸的四角须在画面内，建议各留20–30像素背景边距')
        raise ValueError('启动检测未找到完整四角；请调整取景后重试。失败预览：'+str(image_path)) from last_failure
    finally:
        if not accepted and frame is not None:frame.release()
