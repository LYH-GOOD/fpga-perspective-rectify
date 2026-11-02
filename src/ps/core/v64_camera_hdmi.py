"""V74 automatic edges/conditional complete FB, immutable P1 and asynchronous HDMI."""
from pathlib import Path
from dataclasses import dataclass
from collections import deque
from contextvars import copy_context
import hashlib,os,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID,verify_package
from v31_camera import CameraSource
from v79_acquire import LiveAcquire,pump_acquisition
from v79_setup import NativeSetup,wait_native_with_preview,wait_for_placement
from v31_pixels import set_color_mode
from v31_detection import detect_refined
from v87_v74_tracking import PaperTracker,skip_dead_research
from v31_native import prepare_native
from v31_gc_budget import GcBudget
from v73_ratio import make_orientation as DualOrientation
from v64_io import prepare_io,PlanWorkspace
from v70_ps import materialize_tracking
from v64_p1_backend import P1Backend,make_plan,ProofCache
from v64_hdmi_display import HdmiLatest,native_display_rect
from v75_ui import UIReturnRequested
from run_logging import logged_run,checkpoint,frame_record,frame_log_scope
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]
_POISONED=False
_POISON_REASON=[]

@dataclass
class FrameJob:
    index:int
    lease:object
    tiles:tuple
    size:tuple
    state:str
    corners:tuple
    color_mode:int
    source_snapshot:object
    record:dict
    source_owned:bool=False
    def claim_source(self,owner):
        claim=getattr(self.lease,'claim',None)
        if claim is not None:
            claim(owner,self.index)
            self.record.update(source_buffer_index=self.lease.index,source_generation=self.lease.generation,source_last_owner=owner)
    def release_source(self):
        if self.lease is not None:self.lease.release()

class Frontend:
    """One chronological CPU worker; current four-corner proof renews TTL."""
    def __init__(self,camera,first,detection,size,tracking_limit,detection_limit,hold_s,
                 lk_min_gap,lk_max_gap,orientation_mode='auto_two',reacquire_budget_ms=420.,
                 plan_strategy='fast_safe',proof_cpu_budget_ms=12.):
        self.camera=camera;self.size=tuple(size);self.hold_s=hold_s
        self.raw_required=None
        self.orientation=DualOrientation(orientation_mode,size,2);self.last_verified=None
        self.proof_cache=ProofCache(128);self.plan_strategy=plan_strategy
        self.plan_workspace=PlanWorkspace();self.plan_states={}
        self.proof_cpu_budget_s=float(proof_cpu_budget_ms)/1000.
        self.last_detail_at=0.;self.last_detail_signature=None
        self.tracker=PaperTracker(interval=3,limit=tracking_limit,detection_limit=detection_limit,
            feature_policy='quality',tracking_checks='auto',tracking_policy='motion_adaptive',
            lk_min_gap=lk_min_gap,lk_max_gap=lk_max_gap)
        self.tracker.light_results=True
        self.tracker.observer.transaction.light_results=True
        self.tracker.edge_workspace.light_results=True
        try:
            self.tracker.continuity_hold=True
            self.tracker.configure_recovery(120.,2,4,float(reacquire_budget_ms),4)
            self.tracker.configure_async_recovery(True,.90)
            self.tracker.initialize(first.image,detection[0],index=0,initial_detection=detection[1])
            self.last_sequence=int(first.sequence);self.last_ready=float(first.ready)
            self.anchor_sequence=int(first.sequence);self.anchor_index=self.tracker.anchor_index
            self.last_camera_counters=self._capture_counters()
            # Each job owns one immutable ordinary-RAM source. The two-slot
            # display may retain it after camera/CMA release without recopying.
            # No mutable rotating source slot is lent to the display thread.
            proposal=self.orientation.propose(self.tracker.corners(),first.image.shape,0,timestamp=float(first.ready))
            q=proposal.quad;actual=tuple(proposal.size or self.size);tiles,plan=self.plan(q,first.image.shape,actual)
            orient=self.orientation.commit(proposal)
            self.last_verified=dict(tiles=tiles,size=actual,corners=tuple(map(tuple,q.tolist())),verified_at=float(first.ready),
                layout_generation=orient.get('layout_generation',0),orientation=orient.get('orientation'),
                switch_requested_at=None,switch_decided_at=None)
            self.initial=dict(corners=self.last_verified['corners'],orientation=orient,plan=plan,
                sequence=int(first.sequence),physical_verified_at=float(first.ready))
        except BaseException:
            self.close();raise
    def plan(self,q,shape,size):
        signature=(tuple(shape[:2]),tuple(size),self.plan_strategy)
        entry=self.plan_states.get(signature)
        if entry is None:
            entry=dict(boxes=None,last_q=None,probe_at=0.,cursor=0,key=None,cached=None)
            from v91_policy import MergeProbeBackoff
            entry['merge_backoff']=MergeProbeBackoff()
            self.plan_states[signature]=entry
            if len(self.plan_states)>2:self.plan_states.pop(next(iter(self.plan_states)))
        key=np.asarray(q,np.float32).tobytes()
        if key==entry['key']:
            return entry['cached'][0],dict(entry['cached'][1],plan_cached=True,proof_s=0.,proof_thread_cpu_s=0.,
                proof_coordinate_samples=0,interval_blocks=0,proof_cache_hits=0,proof_attempts=0,proof_budget_splits=0,
                mapping_native_s=0.,mapping_native_thread_cpu_s=0.,merge_probe_attempts=0,merge_probe_accepted=0,
                native_geometry_s=0.,native_geometry_thread_cpu_s=0.,native_geometry_calls=0,
                native_geometry_used=False,native_geometry_fallback=None,native_plan_cached=True,
                h_native_s=0.,h_native_thread_cpu_s=0.,geometry_result_decode_s=0.,geometry_result_decode_thread_cpu_s=0.)
        now=time.perf_counter()
        stable=entry['last_q'] is not None and float(np.max(np.linalg.norm(np.asarray(q)-entry['last_q'],axis=1)))<=3.
        probe=entry['merge_backoff'].ready(now,q,entry['boxes'],stable)
        if probe:entry['probe_at']=now
        tiles,detail=make_plan(q,shape,size,proof_cache=self.proof_cache,strategy=self.plan_strategy,
            proof_cpu_budget_s=self.proof_cpu_budget_s,partition_boxes=entry['boxes'],
            merge_probe=probe,merge_cursor=entry['cursor'],workspace=self.plan_workspace)
        if detail.get('merge_probe_attempts'):entry['cursor']+=1
        entry['merge_backoff'].observe(time.perf_counter(),q,tuple(tile.box for tile in tiles),probe,detail)
        detail.update(entry['merge_backoff'].summary())
        entry.update(boxes=tuple(tile.box for tile in tiles),last_q=np.asarray(q,np.float32).copy(),key=key,cached=(tiles,detail))
        return tiles,dict(detail,plan_cached=False,layout_partition_entries=len(self.plan_states))
    def _capture_counters(self):
        # No MMAP pointer escapes; these counters belong to the capture thread.
        with self.camera.condition:
            if self.camera.error is not None:raise RuntimeError('Camera capture worker failed') from self.camera.error
            return (self.camera.captured,self.camera.dropped,self.camera.invalid,self.camera.sequence_gaps)
    def prepare(self,index):
        capture_begin=time.perf_counter();lease=self.camera.take(3.)
        began=time.perf_counter();cpu=time.thread_time()
        try:
            self.tracker.source_step=max(1,(int(lease.sequence)-self.last_sequence)&0xffffffff)
            self.tracker.source_elapsed_s=max(1e-6,float(lease.ready)-self.last_ready)
            counters=self._capture_counters()
            deltas=tuple(max(0,a-b) for a,b in zip(counters,self.last_camera_counters))
            self.last_camera_counters=counters
            frame_age=max(0.,began-float(lease.ready));gap=self.tracker.source_elapsed_s
            # A selected-frame gap is not a USB outage. Continued capture and
            # observed latest-slot drops identify processing skips, not a guess
            # from sequence alone. Stale, invalid, missing or very old inputs
            # keep the strict reanchor route; hard capture-age LK remains.
            processing_skips=bool(self.tracker.source_step>=3 and deltas[0]>=3 and deltas[1]>=1
                and deltas[2]==0 and deltas[3]==0 and frame_age<=.20 and gap<=.75)
            self.tracker.source_processing_gap=processing_skips
            self.tracker.source_force_reacquire=bool(frame_age>.20 or gap>.75 or(gap>.35 and not processing_skips))
            gap_kind=('processing_latest_skips' if processing_skips else
                'capture_or_stale_gap' if self.tracker.source_force_reacquire else 'normal_selected_interval')
            captured_age=(int(lease.sequence)-self.anchor_sequence)&0xffffffff
            processed_age=max(0,index-self.tracker.anchor_index)
            self.tracker.source_age_extra=max(0,captured_age-processed_age)
            self.tracker.source_ready_at=float(lease.ready);self.tracker.source_sequence=int(lease.sequence)
            self.last_sequence=int(lease.sequence);self.last_ready=float(lease.ready)
            tracker_begin=time.perf_counter();track=self.tracker.update(lease.image,index)
            if self.tracker.anchor_index!=self.anchor_index:
                self.anchor_index=self.tracker.anchor_index;self.anchor_sequence=int(lease.sequence)
            tracker_s=time.perf_counter()-tracker_begin;plan_s=0.;plan={};failure=None;orientation_s=0.;orientation_cpu_s=0.
            if track.get('valid',False):
                q=np.asarray(track['corners'],np.float32)
                to=time.perf_counter();co=time.thread_time()
                lk=track.get('lk_timing') or {};proof=track.get('current_source_proof') or {}
                full_current=bool(proof.get('verified') and
                    (track.get('mode')=='lk_measured' and 'forward_backward_flow_s' in lk
                     or track.get('mode') in ('full_redetect','current_edge_reacquire')))
                proposal=self.orientation.propose(q,lease.image.shape,index,
                    new_target=bool(track.get('target_changed',False)),confidence=float(track.get('confidence',0.)),
                    timestamp=float(lease.ready),strong_verified=full_current)
                q=proposal.quad;orient=proposal.detail
                if track.get('target_changed',False):self.plan_states.clear()
                actual=tuple(proposal.size or self.size);t=time.perf_counter()
                orientation_s=t-to;orientation_cpu_s=time.thread_time()-co
                try:tiles,plan=self.plan(q,lease.image.shape,actual)
                except ValueError as exc:failure=str(exc)
                else:
                    tc=time.perf_counter();cc=time.thread_time()
                    orient=self.orientation.commit(proposal)
                    if self.last_verified and self.last_verified.get('layout_generation')==orient.get('layout_generation'):
                        orient=dict(orient,switch_requested_at=self.last_verified.get('switch_requested_at'),switch_decided_at=self.last_verified.get('switch_decided_at'))
                    self.last_verified=dict(tiles=tiles,size=actual,corners=tuple(map(tuple,q.tolist())),verified_at=float(lease.ready),
                        layout_generation=orient.get('layout_generation',0),orientation=orient.get('orientation'),
                        switch_requested_at=orient.get('switch_requested_at'),switch_decided_at=orient.get('switch_decided_at'))
                    orientation_s+=time.perf_counter()-tc;orientation_cpu_s+=time.thread_time()-cc
                plan_s=time.perf_counter()-t
            else:
                self.orientation.lost(float(lease.ready));orient={}
            current=bool(track.get('valid',False) and failure is None)
            previous=self.last_verified;age=max(0.,time.perf_counter()-previous['verified_at']) if previous else float('inf')
            state='CURRENT' if current else 'HELD' if previous and age<=self.hold_s else 'LOST'
            used=previous if state!='LOST' else dict(tiles=(),size=previous['size'] if previous else self.size,corners=(),verified_at=0.,
                layout_generation=previous.get('layout_generation',0) if previous else 0,orientation=previous.get('orientation') if previous else None)
            snapshot_begin=time.perf_counter()
            raw_required=state=='LOST' or self.raw_required is None or self.raw_required()
            from v113_live_preview import source_snapshot as owned_snapshot
            source_snapshot=owned_snapshot(self.camera,lease) if raw_required else None
            if source_snapshot is not None:source_snapshot.flags.writeable=False
            snapshot_s=time.perf_counter()-snapshot_begin
            metadata_begin=time.perf_counter();metadata_cpu=time.thread_time()
            record=dict(index=index,camera_sequence=int(lease.sequence),capture_ready_at=float(lease.ready),
                camera_timestamp=float(lease.timestamp),verified_at=float(used['verified_at']),state=state,
                color_mode=int(self.camera.color_mode),source_snapshot_s=snapshot_s,
                source_capture_gap_s=float(self.tracker.source_elapsed_s),source_step=int(self.tracker.source_step),
                source_gap_reacquire=bool(self.tracker.source_force_reacquire),captured_anchor_age=int(captured_age),
                source_gap_kind=gap_kind,source_processing_skips=processing_skips,source_age_at_prepare_s=frame_age,
                capture_observed_delta=deltas[0],latest_drop_delta=deltas[1],invalid_capture_delta=deltas[2],driver_sequence_gap_delta=deltas[3],
                capture_wait_s=began-capture_begin,ps_prepare_s=time.perf_counter()-began,ps_prepared_at=time.perf_counter(),
                ps_thread_cpu_s=time.thread_time()-cpu,tracker_s=tracker_s,plan_update_s=plan_s,
                corners=used['corners'],output_size=used['size'],tiles=len(used['tiles']),held_age_s=age,
                confidence=float(track.get('confidence',0.)),mode=track.get('mode'),plan_failure=failure,
                layout_generation=used.get('layout_generation',0),orientation=used.get('orientation'),
                direction_proposed=orient.get('pending_orientation'),direction_decision=orient.get('decision'),
                direction_angle_degrees=orient.get('long_axis_angle_degrees'),direction_confirmations=orient.get('confirmation_count'),
                direction_committed=bool(current and orient.get('orientation_committed')),
                direction_switch=bool(current and (orient.get('changed') or orient.get('mapping_reoriented'))),
                switch_requested_at=used.get('switch_requested_at'),switch_decided_at=used.get('switch_decided_at'))
            source_proof=track.get('current_source_proof',{})
            stability=getattr(self.tracker,'stability_detail',{})
            photo=getattr(self.tracker.photometric,'detail',{})
            controls=self.camera.control_detail
            lk=track.get('lk_timing',{});edge=track.get('edge_gate',{})
            fastpath=track.get('v49_fastpath',{})
            quick=track.get('quick_current_candidate',{})
            proof_workspace=track.get('current_proof_workspace',{})
            record.update(proof_s=plan.get('proof_s',0.),proof_thread_cpu_s=plan.get('proof_thread_cpu_s',0.),
                proof_coordinate_samples=plan.get('proof_coordinate_samples',0),interval_blocks=plan.get('interval_blocks',0),
                proof_attempts=plan.get('proof_attempts',0),proof_cache_hits=plan.get('proof_cache_hits',0),
                proof_budget_splits=plan.get('proof_budget_splits',0),plan_cached=bool(plan.get('plan_cached',False)),
                plan_strategy=self.plan_strategy,proof_methods=plan.get('proof_methods',()),
                partition_reused=bool(plan.get('partition_reused',False)),
                merge_probe_attempts=plan.get('merge_probe_attempts',0),merge_probe_accepted=plan.get('merge_probe_accepted',0),
                mapping_native_s=plan.get('mapping_native_s',0.),mapping_native_thread_cpu_s=plan.get('mapping_native_thread_cpu_s',0.),
                track_reason=track.get('reason'),lk_trigger=track.get('lk_trigger'),
                # ⭐ 2026-10-18 合并 V1.1 优化：把开关状态写进每一帧
                skip_research=bool(skip_dead_research()),
                edge_rescue=track.get('edge_rescue'),   # 重搜前后 gate 指标（A/B 用）
                static_hold=track.get('static_hold'),   # ⭐ 静态保持：motion/held_s/frames
                hold_motion=getattr(self.tracker,'_hold_motion',None),   # 每帧帧差（诊断为什么没保持）
                hold_changed=getattr(self.tracker,'_hold_changed',None),
                hold_smooth=getattr(self.tracker,'_hold_smooth',None),
                hold_floor=getattr(self.tracker,'_hold_floor_m',None),
                hold_count=getattr(self.tracker,'_hold_count',None),
                hold_active=bool(getattr(self.tracker,'_hold_active',False)),
                feature_count=track.get('feature_count'),min_edge_support=edge.get('min_support'),max_edge_rms=edge.get('max_rms'),
                stable_FB_context=lk.get('stable_FB_context'),current_source_proof_verified=source_proof.get('verified'),
                current_source_proof_reason=source_proof.get('reason'),
                current_source_support=source_proof.get('min_support'),current_source_rms=source_proof.get('max_rms'),
                current_source_normal_difference=source_proof.get('line_normal_difference'),
                luma_mean=photo.get('luma_mean'),luma_delta=photo.get('luma_delta'),
                luma_clipped_fraction=photo.get('clipped_fraction'),photometric_residual=photo.get('photometric_residual'),
                illumination_change=bool(photo.get('illumination_change')),
                illumination_local_reproof=bool(photo.get('current_independent_reproof_passed')),
                illumination_probe_s=photo.get('probe_s',0.),
                camera_exposure_absolute=controls.get('exposure_absolute'),camera_gain=controls.get('gain'),
                camera_exposure_auto_priority=controls.get('exposure_auto_priority'),camera_controls_queried_at=controls.get('queried_at'),
                paired_current_proof=bool(source_proof.get('current_proof_timing',{}).get('paired_native_transaction')),
                physical_layer_suspect=bool(stability.get('physical_layer_suspect')),
                corner_filter_applied=bool(stability.get('filtered')),corner_filter_shift=stability.get('filter_shift',0.),
                edge_stability_s=stability.get('wall_s',0.),edge_stability_thread_cpu_s=stability.get('thread_cpu_s',0.),
                local_edge_lock_attempted=bool(stability.get('local_lock_attempted')),
                local_edge_lock_verified=bool(stability.get('local_lock_verified')),
                local_edge_lock_s=stability.get('local_lock_wall_s',0.),local_edge_lock_thread_cpu_s=stability.get('local_lock_thread_cpu_s',0.),
                calm_FB_burst_exit=bool(lk.get('calm_burst_exit',{}).get('verified')),
                localization_baseline='V74_complete_automatic',
                automatic_path='V74_current_edges_conditional_complete_FB',
                complete_FB=bool('forward_backward_flow_s' in lk),
                source_snapshot_owned=source_snapshot is not None,source_snapshot_skipped=source_snapshot is None,
                lk_transaction_geometry=getattr(self.tracker,'_v90_geometry_stats',None),
                postlk_native_transaction=dict(self.tracker.post_lk.detail) if track.get('mode')=='lk_measured' else None,
                merge_probe_failure_streak=plan.get('merge_probe_failure_streak'),
                merge_probe_retry_s=plan.get('merge_probe_retry_s'),
                v49_fastpath_route=fastpath.get('route'),same_frame_receipt_reused=bool(fastpath.get('same_frame_receipt_reused')),
                current_proof_reuse_hits=int(proof_workspace.get('hits',0)),
                current_proof_store_count=int(proof_workspace.get('stored',0)),
                quick_current_candidate_attempted=bool(quick.get('attempted')),
                quick_current_candidate_verified=bool(quick.get('verified')),
                quick_current_candidate_s=quick.get('wall_s',0.),
                quick_current_candidate_thread_cpu_s=quick.get('thread_cpu_s',0.),
                quick_current_candidate_reason=quick.get('reason'),
                ps_light_results=bool(self.tracker.light_results),
                observation_wrapper_s=track.get('gray_s',0.),
                observation_native_s=self.tracker.observer.detail.get('native_transaction_s',0.) if track.get('gray_s',0.)>0 else 0.,
                result_decode_s=sum(w.decode_timing[0] for w in (self.tracker.observer.transaction,self.tracker.edge_workspace)),
                result_decode_thread_cpu_s=sum(w.decode_timing[1] for w in (self.tracker.observer.transaction,self.tracker.edge_workspace)),
                source_corners_s=track.get('source_corners_s',0.),post_observation_s=track.get('post_observation_s',0.),
                # ⭐ 2026-10-28 计时：把 tracker_s 拆成 静止门控/观测前/LK/帧尾 四段。
                pre_obs_s=track.get('pre_obs_s',0.),static_hold_s=track.get('static_hold_s',0.),
                lk_s=track.get('lk_s',0.),post_lk_tail_s=track.get('tail_s',0.),
                # ⭐ 2026-10-28：锚点重取点的总耗时，与其中【搜索】部分；外加生效的间隔。
                feature_s=track.get('feature_s',0.),feature_roi_s=track.get('feature_roi_s',0.),
                roi_search_gap=int(track.get('roi_search_gap',0) or 0),
                orientation_prepare_s=orientation_s,orientation_thread_cpu_s=orientation_cpu_s,
                native_geometry_used=bool(plan.get('native_geometry_used',False)),
                native_geometry_fallback=plan.get('native_geometry_fallback'),
                native_geometry_calls=int(plan.get('native_geometry_calls',0)),
                native_geometry_s=plan.get('native_geometry_s',0.),native_geometry_thread_cpu_s=plan.get('native_geometry_thread_cpu_s',0.),
                h_native_s=plan.get('h_native_s',0.),h_native_thread_cpu_s=plan.get('h_native_thread_cpu_s',0.),
                geometry_result_decode_s=plan.get('geometry_result_decode_s',0.),
                geometry_result_decode_thread_cpu_s=plan.get('geometry_result_decode_thread_cpu_s',0.))
            # Keep every timing/quad/state. A recurring slow/recovery condition
            # does not serialize the same large proof tree on every frame.
            now=time.perf_counter();signature=(state,track.get('mode'),track.get('reason'))
            changed=signature!=self.last_detail_signature
            detailed=index==1 or index%60==0 or((changed or tracker_s>.12) and now-self.last_detail_at>=2.)
            record['diagnostic_detail']=bool(detailed)
            if detailed:
                record.update(tracker_detail=materialize_tracking(track),plan_detail=plan,orientation_detail=orient)
                self.last_detail_at=now;self.last_detail_signature=signature
            # Include the per-frame summary/detail selection in preparation,
            # not as an unreported gap before publishing the ready job.
            record['metadata_build_s']=time.perf_counter()-metadata_begin
            record['metadata_thread_cpu_s']=time.thread_time()-metadata_cpu
            record['ps_prepare_s']=time.perf_counter()-began
            record['ps_thread_cpu_s']=time.thread_time()-cpu
            record['ps_prepared_at']=time.perf_counter()
            seal=time.perf_counter()
            job=FrameJob(index,lease,used['tiles'],used['size'],state,used['corners'],self.camera.color_mode,source_snapshot,record,source_owned=source_snapshot is not None)
            record['job_seal_s']=time.perf_counter()-seal
            record['ps_prepare_total_s']=time.perf_counter()-began
            record['ps_prepare_total_thread_cpu_s']=time.thread_time()-cpu
            return job
        except BaseException:lease.release();raise
    def close(self):
        # Stop recovery before releasing LK/workspaces read by that CPU worker.
        worker=getattr(self.tracker,'recovery_worker',None)
        if worker is not None:worker.close()
        self.tracker.lk_cache.close()
        for name in ('edge_workspace','workspace'):
            obj=getattr(self.tracker,name,None)
            if obj is not None and hasattr(obj,'close'):obj.close()
        transaction=getattr(self.tracker.observer,'transaction',None)
        if transaction is not None and hasattr(transaction,'close'):transaction.close()
        self.plan_workspace.close()

def _bind_cpu(name):
    """P11_CPU_AFFINITY=1 时把当前线程绑到 CPU1（主线程在 notebook 里绑 CPU0）。

    2026-10-24：实测输入打包的 ctypes 调用 p50=5.68ms、p90=12.7ms，而原生只 2.38ms；
    25% 的帧超过 10ms ⇒ 不是 GIL（prepare 负载翻倍差值不变），是 OS 抢占。
    双核三线程，把两个后台线程绑到 CPU1、主线程独占 CPU0，减少互相抢占。
    """
    import os as _os
    if _os.environ.get('P11_CPU_AFFINITY') != '1':
        return
    try:
        _os.sched_setaffinity(0, {1})
    except Exception:
        pass


class PrepareQueue:
    """At most one queued job. Stop always disposes captured frame leases."""
    def __init__(self,frontend,count,warmup):
        self.frontend=frontend;self.count=count;self.allowed=warmup;self.taken=0
        #   ⭐ 2026-10-31：预取深度。原来的单槽（depth=1）让 PS 只能在 owner `take(N)`
        #      之后才开始准备 N+1，而预取点在第 N 帧 DMA 等待的开头（约 10ms 进帧），
        #      PS 需要 23.5ms ⇒ 预取命中率只有 14%，input_copy 5.34ms 一直压在关键路径上。
        #      depth=2 让 PS 能提前两帧，预取点在 N 帧时 N+1 早已就绪。
        #      P11_PREPARE_AHEAD=1 可退回原行为。相机有 6 个 V4L2 buffer，同时最多持 3 个 lease。
        #   ⚠️ 2026-10-31 实测：depth=2 确实把 input_copy 5.34→1.54ms、service 36.7→33.7ms，
        #      但 ps_prepare 墙钟从 23.6 涨到 29.7ms，和显示线程抢同一个 GIL ⇒
        #      并排(PAIRED) compose 39.4→45.2ms、显示 17→15fps。用户看到的是并排，净效果更差。
        #      所以**默认回 1**；开关保留，等显示侧不再是瓶颈再启用。
        try:self.depth=max(1,min(3,int(os.environ.get('P11_PREPARE_AHEAD','1'))))
        except ValueError:self.depth=1
        self.slots=[]                       # 已准备待取走，按 index 升序
        self.stop=False;self.error=None;self.finished=False;self.condition=threading.Condition();self.handoff=None
        self.context=copy_context();self.credit_wait_s=0.;self.publish_wait_s=0.
        self.worker=threading.Thread(target=self._entry,name='ps_prepare',daemon=True);self.worker.start()
    def _entry(self):
        _bind_cpu('ps_prepare')
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.finished=True;self.condition.notify_all()
    def _run(self):
        for index in range(1,self.count+1):
            with self.condition:
                begin=time.perf_counter()
                while not self.stop and (index>self.allowed or index>self.taken+self.depth):self.condition.wait()
                self.credit_wait_s+=time.perf_counter()-begin
                if self.stop:break
            item=self.frontend.prepare(index)
            with self.condition:
                begin=time.perf_counter()
                while not self.stop and len(self.slots)>=self.depth:self.condition.wait()
                self.publish_wait_s+=time.perf_counter()-begin
                if self.stop:item.release_source();break
                item.claim_source('prepared_queue');self.slots.append(item);self.condition.notify_all()
        with self.condition:self.finished=True;self.condition.notify_all()
    def allow_measured(self):
        with self.condition:self.allowed=self.count;self.condition.notify_all()
    def take(self,index,cancel=None):
        idle=getattr(self,'idle_callback',None)
        while True:
            with self.condition:
                if self.slots:
                    item=self.slots[0]
                    if item.index!=index:raise RuntimeError('Frame preparation order changed')
                    self.handoff=item;item.claim_source('owner_execute')
                    self.slots.pop(0);self.taken=index;self.condition.notify_all();return item
                if cancel is not None and cancel.is_set():raise UIReturnRequested()
                if self.error is not None:raise self.error
                if self.finished or self.stop:raise RuntimeError('PS preparation ended early')
                self.condition.wait(.04 if idle is not None else .2)
                if self.slots:continue
                if self.error is not None or self.finished or self.stop or cancel is not None and cancel.is_set():continue
            if idle is not None:idle()
    def peek(self):
        with self.condition:
            return self.slots[0] if (self.slots and not self.stop and self.error is None) else None
    def close(self):
        with self.condition:
            self.stop=True;pending=list(self.slots);self.slots=[];self.condition.notify_all()
        errors=[]
        for item in pending:
            try:item.release_source()
            except BaseException as exc:errors.append(('queued_source',repr(exc)))
        self.worker.join(10.)
        if self.worker.is_alive():_RETAINED.append(self);raise RuntimeError('PS worker active; keep camera/contexts')
        if self.handoff is not None:
            try:self.handoff.release_source();self.handoff=None
            except BaseException as exc:errors.append(('owner_handoff_source',repr(exc)))
        if errors:raise RuntimeError('Prepare source cleanup failed '+str(errors))

def _summary(rows,key):
    values=[float(r[key]) for r in rows if key in r and np.isfinite(r[key])]
    return dict(median_ms=float(np.median(values))*1000,p95_ms=float(np.percentile(values,95))*1000,p99_ms=float(np.percentile(values,99))*1000,
        max_ms=max(values)*1000,count=len(values)) if values else None

from v86_policy import policy_run,policy

@logged_run
@policy_run
def run_camera_hdmi(device='/dev/video0',bitfile='system.bit',max_frames=190,warmup_frames=5,
                    width=640,height=480,fps=30,output_size=(362,512),hdmi_mode=(1280,720),
                    max_duration_s=300.,tracking_max_dim=320,detection_max_dim=640,
                    hold_max_age_s=1.5,lk_min_gap=6,lk_max_gap=30,output_orientation='auto_two',
                    opencv_threads=1,timeout_s=3.,color_mode=None,progress_every=60,
                    startup_timeout_s=6.,startup_detect_attempts=6,gc_policy='bounded',hdmi_max_fps=30.,reacquire_budget_ms=420.,
                    plan_strategy='fast_safe',proof_cpu_budget_ms=12.,book_rescue=True,book_rescue_cpu_ms=70.,_ui_context=None,auto_tracking_mode='strict',tracking_audit_s=1.,
                    outer_candidate_competition=False,recovery_local_first=False,detection_contrast_fallback=False,hybrid_auto_ai=True):
    """max_frames=0 means live until duration/interrupt; all diagnostics in one log.

    Flat homography only: P1 has no local B-spline/light-field accelerator.
    Current/HELD/LOST counts are separate. A held H never renews its own TTL.
    """
    global _POISONED,_POISON_REASON
    borrowed=_ui_context is not None
    def check_ui():
        if borrowed:_ui_context.check()
    check_ui()
    if _POISONED:raise RuntimeError('Previous cleanup left resources active: '+str(_POISON_REASON)+
        '. Restart the PYNQ board and inspect the earlier V64_PRIMARY_FAILURE/HDMI_CLEANUP_FAILED in run-result.log')
    if isinstance(max_frames,bool) or not isinstance(max_frames,int) or max_frames<0:raise ValueError('max_frames must be nonnegative int')
    if not isinstance(warmup_frames,int) or warmup_frames<0 or (max_frames and max_frames<=warmup_frames):raise ValueError('Invalid warmup/frame count')
    if not .1<=float(hold_max_age_s)<=1.5:raise ValueError('Hold TTL must be0.1..1.5s')
    if not 1<=float(max_duration_s)<=7200:raise ValueError('Duration must be1..7200s')
    if int(width)%2 or width<2 or height<2 or width>1024:raise ValueError('P1 camera width must be even and<=1024')
    if not 16<=min(output_size) or max(output_size)>1024:raise ValueError('Output dimensions16..1024')
    if int(opencv_threads)!=1:raise ValueError('V68 requires one OpenCV thread')
    if not 1<=float(hdmi_max_fps)<=30:raise ValueError('HDMI max FPS must be1..30')
    if not 120<=float(reacquire_budget_ms)<=500:raise ValueError('Recovery CPU budget must be120..500ms')
    if plan_strategy not in ('fast_safe','exact_reference'):raise ValueError('Unknown plan strategy')
    if not 2<=float(proof_cpu_budget_ms)<=30:raise ValueError('Proof CPU budget must be2..30ms')
    if not isinstance(book_rescue,bool):raise ValueError('book_rescue must be bool')
    if isinstance(book_rescue_cpu_ms,bool) or not np.isfinite(book_rescue_cpu_ms) or not 30<=float(book_rescue_cpu_ms)<=120:
        raise ValueError('book_rescue_cpu_ms must be30..120')
    # Reject an undersized canvas before loading the overlay or starting DMA.
    #   ⭐ 2026-10-27：摄像头分辨率可以大于面板（如 800x600），显示前会等比缩小，
    #      所以这里校验的是【缩小后】的尺寸，而不是原始摄像头尺寸。
    from v64_hdmi_display import HdmiLatest as _HdmiLatest
    native_display_rect(hdmi_mode,_HdmiLatest._fit_shape(hdmi_mode,(height,width)),0)
    native_display_rect(hdmi_mode,(output_size[1],output_size[0]),1)
    if output_orientation=='auto_two':native_display_rect(hdmi_mode,(output_size[0],output_size[1]),1)
    setup=time.perf_counter();root=Path(__file__).resolve().parent;hardware=(root/bitfile).resolve()
    checkpoint('CAMERA_FUNCTION_ENTER',borrowed_UI=borrowed,raw_before_native_setup=True)
    checkpoint('CAMERA_PACKAGE_CHECK_BEGIN')
    verify_package(str(hardware))
    checkpoint('CAMERA_PACKAGE_CHECK_END')
    # run_ui configured OpenCV before its display/touch threads started.
    # Borrowed sessions must not reconfigure that global policy mid-display.
    if not borrowed:cv2.setNumThreads(1)
    elif cv2.getNumThreads()!=1:raise ValueError('UI OpenCV thread policy changed; restart the application')
    checkpoint('ACTIVE_PATH',v86_policy=policy(),tracking='V89 complete V74 automatic current four-edge measurement + conditional full bidirectional LK',
        hardware='only user E:/P1/board/system.bit + system.hwh',mapping='P1 planar RGB565',
        local_surface_enabled=False,light_correction_enabled=False,display='P1 BGR24 same-frame split',
        native_ready_scope='compiled CPU capabilities; unused V31 packet/tone/preview helpers are not active PL features',
        io_native_abi=6601,plan_strategy=plan_strategy,proof_cpu_budget_ms=float(proof_cpu_budget_ms),
        gap_policy='capture counters + freshness + current full FB/four edges; no selected-gap-only loss',
        display_max_fps=float(hdmi_max_fps),orientation_policy='two layouts/current proof commit/500ms evidence',
        illumination_policy='V69 ordinary path; no added illumination probe or pixel enhancement',
         edge_policy='V74 candidates/refinement/independent admission and original PaperTracker; manual core only after explicit calibration',
         recovery_policy='V74 current-edge local recovery + original asynchronous detector; finite hold<=1.5s',
         display_snapshot_policy='automatic: one immutable ordinary-RAM raw copy; corrected CMA still copied to reserved slot',
         display_software_abi=7301,display_frontend_version=79,
         display_composition='1280x720 source-size direct color conversion; no resize or crop')
    camera=backend=display=frontend=preparer=budget=first=acquirer=native_setup=job=None
    owns_native_setup=not borrowed
    hot=getattr(_ui_context,'hot',None) if borrowed else None
    transfer=None;camera_preserved=False
    from v75_hotswitch import camera_key
    stream_key=camera_key(device,width,height,fps,color_mode)
    rows=deque(maxlen=512);total=delivered=current=held=lost=0;formal_begin=formal_end=None
    speed_counts=dict(v86_motion_frames=0,v86_edge_verified_frames=0,partition_reused=0,merge_attempts=0,merge_accepted=0,direct_row_frames=0,assembled_frames=0,assembly_bytes=0,lookahead_prefills=0,
        v85_line_quantization_frames=0,v85_single_weak_edge_frames=0,v85_independent_side_remeasured_frames=0,
        v49_current_Y_frames=0,v49_current_color_frames=0,same_frame_receipt_frames=0,current_proof_reuse_hits=0,current_observation_reuse_hits=0,current_primary64_reuse_hits=0,current_FB_proof_reuse_hits=0,
        quick_current_candidate_attempts=0,quick_current_candidate_successes=0,
        native_geometry_frames=0,native_geometry_fallback_frames=0,native_geometry_calls=0,light_result_frames=0)
    current_times=deque(maxlen=120);initial=None;stability=None;run_error=None;cleanup=[];display_summary={};camera_end={}
    count=max_frames or 2147483647;interrupted=False;user_interrupted=False;returned_home=False;epoch=None;stage='pair_overlay'
    session_deadline=time.perf_counter()+float(max_duration_s)
    with frame_log_scope('compact',60,120.):
        try:
            if borrowed:
                backend=_ui_context.backend;display=_ui_context.display;backend._assert_owner()
                if (backend.path!=hardware or backend.input_shape!=(height,width) or display.mode!=tuple(hdmi_mode)
                        or int(output_size[0])*int(output_size[1])>backend.output_capacity):
                    raise ValueError('Borrowed UI resources do not match camera options')
            else:
                backend=P1Backend(str(hardware),(height,width),output_size,timeout_s)
                stage='hdmi_pipeline_start'
                try:display=HdmiLatest(backend.overlay,hdmi_mode,output_size,timeout_s,hold_max_age_s,
                    input_shape=(height,width),max_fps=hdmi_max_fps)
                except BaseException as exc:
                    # A constructor timeout can leave its display owner in driver
                    # start(). Keep the shared overlay pinned instead of reloading it.
                    backend.failed=not bool(getattr(exc,'hdmi_shutdown_safe',False));raise
            check_ui()
            stage='camera_open'
            transfer=hot.claim(_ui_context,stream_key) if hot is not None else None
            if transfer is not None:camera=transfer.camera;budget=transfer.budget
            else:
                checkpoint('CAMERA_OPEN_BEGIN',device=device,width=width,height=height,fps=fps)
                camera=CameraSource(device,width,height,fps,color_mode)
            set_color_mode(camera.color_mode)
            if borrowed:
                from v113_live_preview import bind_preview
                bind_preview(camera,display,_ui_context.generation)
            check_ui()
            checkpoint('CAMERA_READY',durable=True,**camera.metadata(),no_jpeg_decoder=True)
            stage='visible_native_setup'
            native_setup=_ui_context.native_setup if borrowed else NativeSetup()
            if transfer is not None:
                check_ui();status=native_setup.result()
            else:
                status=wait_native_with_preview(native_setup,camera,display,check_ui,
                    lambda:_ui_context.generation if borrowed else 0,deadline=session_deadline,context=_ui_context)
            if owns_native_setup:native_setup.close();native_setup=None
            checkpoint('NATIVE_READY',**status)
            check_ui()
            stage='placement_confirmation'
            if transfer is None:
                wait_for_placement(camera,display,check_ui,lambda:_ui_context.generation if borrowed else 0,
                    deadline=session_deadline,context=_ui_context)
            if borrowed:_ui_context.set_phase('acquiring')
            stage='live_acquisition'
            def build_frontend(frame,detection):
                from v86_tracking import create_frontend
                return create_frontend(camera,frame,detection,output_size,tracking_max_dim,detection_max_dim,
                    hold_max_age_s,lk_min_gap,lk_max_gap,output_orientation,reacquire_budget_ms,
                    plan_strategy,proof_cpu_budget_ms,book_rescue,book_rescue_cpu_ms)
            from v87_acquire import V74Acquire as LocalAcquire
            hybrid_enabled=bool(hybrid_auto_ai and borrowed and getattr(display,'ai_service',None) is not None)
            if hybrid_enabled:
                from v111_recovery import HybridFrontend
                hybrid_options=dict(tracking_max_dim=tracking_max_dim,detection_max_dim=detection_max_dim,
                    hold_max_age_s=hold_max_age_s,output_orientation=output_orientation,
                    reacquire_budget_ms=reacquire_budget_ms,plan_strategy=plan_strategy,
                    proof_cpu_budget_ms=proof_cpu_budget_ms,book_rescue=book_rescue,book_rescue_cpu_ms=book_rescue_cpu_ms)
                frontend=HybridFrontend(camera,output_size,hybrid_options,_ui_context,build_frontend,
                    recovery=transfer is not None and transfer.stabilized,target_selection=_ui_context.ticket.target_selection)
                _ui_context.ticket.target_selection=None
                stability=dict(policy='V74 exact automatic gate; AI distinct-frame plus current-source proof',
                    camera_reused=transfer is not None,hybrid=True)
                initial=dict(frontend.initial)
            else:
                target_selection=_ui_context.ticket.target_selection if borrowed else None
                def target_report(notice):
                    if borrowed and not _ui_context.cancel.is_set():display.set_target_notice(notice,_ui_context.generation)
                def target_progress(phase):
                    if borrowed and not _ui_context.cancel.is_set():display.set_target_phase(phase,_ui_context.generation)
                acquirer=LocalAcquire(detection_max_dim,tracking_max_dim,build_frontend,budget_ms=reacquire_budget_ms,
                    recovery=transfer is not None and transfer.stabilized,target_selection=target_selection,target_report=target_report if borrowed else None,
                    target_progress=target_progress if target_selection is not None else None)
                target_selection=None
                if borrowed:_ui_context.ticket.target_selection=None
                acquisition_check=transfer.acquisition_check(check_ui) if transfer is not None else check_ui
                first,detection,frontend,admission=pump_acquisition(acquirer,camera,display,acquisition_check,
                    lambda:_ui_context.generation if borrowed else 0,
                    deadline=session_deadline,context=_ui_context,already_running=transfer is not None and transfer.stabilized,
                    ready_after=transfer.ready_after if transfer is not None else None)
                acquirer.close();acquirer=None
                stability=dict(policy='already_running_camera_then_original_admission' if transfer is not None else 'V74_12_150_4_stabilization_then_original_admission',
                    strict_brightness_gate=transfer is None,live_preview_during_acquisition=True,
                    camera_reused=transfer is not None,full_current_target_admission=True)
                initial=dict(frontend.initial,admission=admission);first.release();first=None
            check_ui()
            if budget is None:budget=GcBudget(gc_policy,240,30.);budget.__enter__()
            stage='producer_start'
            frontend.raw_required=display.needs_raw_source
            if borrowed:_ui_context.set_phase('running')
            preparer=PrepareQueue(frontend,count,warmup_frames)
            continuity=None
            if borrowed:
                from v118_display_continuity import OwnerContinuity
                continuity=OwnerContinuity(frontend,backend,display,_ui_context)
                preparer.idle_callback=continuity.pump
            checkpoint('HDMI_SEQUENCE_READY',durable=True,release_id=RELEASE_ID,initial=initial,
                camera_reused=transfer is not None,initial_stabilization_repeated=transfer is None,
                full_current_target_admission=True,GC_window_reused=transfer is not None,
                setup_s=time.perf_counter()-setup,output_size=list(output_size),hdmi_mode=list(hdmi_mode),
                localization='V89 full V74 automatic detector/PaperTracker; current edges first, conditional complete FB; no automatic manual-motion entry',remap='P1 planar RGB565',
                book_rescue_policy='disabled: exact V74 localization strategy',
                book_rescue_cpu_ms=float(book_rescue_cpu_ms),
                queue_capacity=preparer.depth,max_prepare_ahead=preparer.depth)
            stage='frame_loop'
            # ⭐ 2026-10-18 静态输出冻结：静止保持帧不再跑 P1 remap/DMA，
            #   直接把上一帧已完成的校正图再提交一次（输入仍在变，但 H 不变）。
            freeze_output=False  # Live12 always remaps fresh pixels; no cached-output freeze.
            #   ⭐ 2026-10-25：逐帧日志降频。
            #      实测（run 86，LOG_WRITER_SUMMARY）：`_owned_payload()` 的**深拷贝**
            #      在主线程上花了 snapshot_s=13.69 s / 3122 帧 = **4.4 ms/帧**，
            #      占墙钟 10%。日志本身 24 MB / 3122 帧 = 7.7 KB/帧。
            #      ⇒ P11_LOG_EVERY=N：每 N 帧才写一条 V64_FRAME（默认 1 = 全记）。
            #      ⚠️ 只影响【落盘的逐帧记录】；内存里的 `rows` 仍然是每帧全收，
            #         所以 RUN_COMPLETED 的 timing 汇总**不受影响**。
            try:log_every=max(1,int(os.environ.get('P11_LOG_EVERY','1')))
            except ValueError:log_every=1
            last_output=None;last_output_sig=None;last_output_index=0
            for index in range(1,count+1):
                if borrowed and _ui_context.cancel.is_set():raise UIReturnRequested()
                if index==warmup_frames+1:
                    formal_begin=time.perf_counter();epoch=display.begin_measurement();preparer.allow_measured()
                if time.perf_counter()>=session_deadline:break
                try:
                    wait_begin=time.perf_counter();job=preparer.take(index,_ui_context.cancel if borrowed else None);taken=time.perf_counter()
                    row=dict(job.record,preparation_wait_s=taken-wait_begin,
                        parameter_queue_s=max(0.,taken-job.record['ps_prepared_at']))
                    if borrowed and _ui_context.cancel.is_set():raise UIReturnRequested()
                    if job.state=='LOST':
                        image=None;owner=dict(owner_s=0.,owner_thread_cpu_s=0.,tiles=0)
                        last_output=None;last_output_sig=None
                    else:
                        output_sig=(tuple(job.size),tuple(tuple(float(v) for v in c) for c in (job.record.get('corners') or ())))
                        if (freeze_output and job.record.get('mode')=='static_hold' and last_output is not None
                                and not backend.active and output_sig==last_output_sig):
                            image=last_output
                            owner=dict(owner_s=0.,owner_thread_cpu_s=0.,tiles=0,frozen_output=True,
                                frozen_frames=int(index-last_output_index))
                        else:
                            image,owner=backend.execute(job,preparer.peek)
                            last_output=image;last_output_sig=output_sig;last_output_index=index
                    ready=time.perf_counter();row.update(owner,output_ready_at=ready,
                        capture_to_output_s=ready-job.record['capture_ready_at'])
                    #   ⭐ 2026-10-31 诊断：service_s 除 take/owner/offer 之外还有 ~12ms 归不了因，
                    #      而 ps_prepare 的墙钟里只有一半是 CPU（疑似等 GIL）。纯计时，不改行为。
                    _t_a=time.perf_counter()
                    if job.lease.flags&0xe000==0x2000 and 0<=job.lease.timestamp<=ready:
                        row['driver_to_output_s']=ready-job.lease.timestamp
                    if hybrid_enabled:
                        if row.get('hybrid_epoch')!=frontend.epoch:
                            job.state='HELD' if image is not None else 'LOST';row['state']=job.state
                            row['continuity_output']=False
                        frontend.completed(row,ready)
                        row['hybrid_valid_fps']=frontend.rate.fps(ready)
                        if row.get('hybrid_epoch')==frontend.epoch:row['hybrid_phase']=frontend.phase
                    _t_b=time.perf_counter()
                    measured=index>warmup_frames
                    if measured:
                        total+=1;delivered+=int(job.state!='LOST');current+=int(job.state=='CURRENT')
                        held+=int(job.state=='HELD');lost+=int(job.state=='LOST')
                        speed_counts['v86_motion_frames']+=int(job.state=='CURRENT' and row.get('complete_FB',False))
                        speed_counts['v86_edge_verified_frames']+=int(job.state=='CURRENT' and bool(row.get('current_source_proof_verified',False)))
                        speed_counts['partition_reused']+=int(row.get('partition_reused',False))
                        speed_counts['merge_attempts']+=int(row.get('merge_probe_attempts',0))
                        speed_counts['merge_accepted']+=int(row.get('merge_probe_accepted',0))
                        speed_counts['direct_row_frames']+=int(owner.get('direct_row_receive',False))
                        speed_counts['assembled_frames']+=int(job.state!='LOST' and not owner.get('direct_row_receive',False))
                        speed_counts['assembly_bytes']+=int(owner.get('tile_assembly_bytes',0))
                        speed_counts['lookahead_prefills']+=int(owner.get('lookahead_prefills',0))
                        speed_counts['v85_line_quantization_frames']+=int(job.state=='CURRENT' and row.get('v85_line_quantization',False))
                        speed_counts['v85_single_weak_edge_frames']+=int(job.state=='CURRENT' and row.get('v85_single_weak_edge',False))
                        speed_counts['v85_independent_side_remeasured_frames']+=int(job.state=='CURRENT' and row.get('v85_independent_side_remeasured',False))
                        speed_counts['v49_current_Y_frames']+=int(job.state=='CURRENT' and row.get('v49_fastpath_route')=='current_Y_edges')
                        speed_counts['v49_current_color_frames']+=int(job.state=='CURRENT' and row.get('v49_fastpath_route')=='current_color_edges')
                        speed_counts['same_frame_receipt_frames']+=int(row.get('same_frame_receipt_reused',False))
                        speed_counts['current_proof_reuse_hits']+=int(row.get('current_proof_reuse_hits',0))
                        for reuse_key in ('current_observation_reuse_hits','current_primary64_reuse_hits','current_FB_proof_reuse_hits'):
                            speed_counts[reuse_key]+=int(row.get(reuse_key,0))
                        speed_counts['quick_current_candidate_attempts']+=int(row.get('quick_current_candidate_attempted',False))
                        speed_counts['quick_current_candidate_successes']+=int(job.state=='CURRENT' and row.get('quick_current_candidate_verified',False))
                        speed_counts['native_geometry_frames']+=int(row.get('native_geometry_used',False))
                        speed_counts['native_geometry_fallback_frames']+=int(bool(row.get('native_geometry_fallback')))
                        speed_counts['native_geometry_calls']+=int(row.get('native_geometry_calls',0))
                        speed_counts['light_result_frames']+=int(row.get('ps_light_results',False))
                        if job.state=='CURRENT':current_times.append(ready)
                    while current_times and current_times[0]<ready-2.:current_times.popleft()
                    corr=(len(current_times)-1)/(current_times[-1]-current_times[0]) if len(current_times)>1 and current_times[-1]>current_times[0] else 0.
                    row['correction_fps']=corr
                    if borrowed:row['ui_generation']=_ui_context.generation
                    #   ⭐ 2026-10-24 诊断：offer() 只报了内部子项，外面套一个总计时，
                    #      这样 service_s 才能拆成 take / owner / offer / release_source。
                    _t_c=time.perf_counter()
                    _t_offer=time.perf_counter()
                    row['display_snapshot_s']=display.offer(image,row,job.source_snapshot,raw_owned=job.source_owned,
                        output_reference=backend.output_reference(image))
                    row['display_offer_total_s']=time.perf_counter()-_t_offer
                    _t_d=time.perf_counter()
                    row.update(display.last_offer_timing)
                    if continuity is not None:continuity.remember(job,row)
                    _t_e=time.perf_counter()
                    if row.get('direction_switch') and row.get('switch_requested_at') is not None:
                        row['direction_to_output_s']=ready-row['switch_requested_at']
                    row['service_s']=time.perf_counter()-wait_begin
                    #   诊断分解（纯计时）：把 service_s 拆成
                    #   take前开销 / hybrid记账 / 计数器 / offer / offer后收尾。
                    row['svc_pre_s']=max(0.,ready-taken-float(owner.get('owner_s',0.)))
                    row['svc_hybrid_s']=max(0.,_t_b-_t_a)
                    row['svc_counters_s']=max(0.,_t_c-_t_b)
                    row['svc_offer_tail_s']=max(0.,_t_e-_t_d)
                    if measured:
                        rows.append(row);budget.check(index)
                        if log_every<=1 or index%log_every==0:
                            frame_record('V64_FRAME',**row)
                        if progress_every and total%progress_every==0:checkpoint('HDMI_PROGRESS',frames=total,current=current,held=held,lost=lost,
                            current_fps=current/max(1e-9,ready-formal_begin),correction_fps_recent=corr)
                    if owner.get('stop_requested',False):interrupted=True;user_interrupted=True;break
                finally:
                    if job is not None:job.release_source();job=None
            formal_end=time.perf_counter()
        except UIReturnRequested:
            interrupted=True;returned_home=True;formal_end=time.perf_counter()
            checkpoint('UI_CAMERA_RETURN',frames=total,hardware_abort=False)
        except KeyboardInterrupt:
            interrupted=True;user_interrupted=True;formal_end=time.perf_counter();checkpoint('HDMI_USER_STOP',durable=True,frames=total)
        except BaseException as exc:
            run_error=exc;formal_end=time.perf_counter()
            try:checkpoint('V64_PRIMARY_FAILURE',durable=True,failure_stage=stage,exception_type=type(exc).__name__,
                exception=str(exc),traceback=__import__('traceback').format_exc(),frames=total,remap_active=bool(backend and backend.active),
                remap_failed=bool(backend and backend.failed),hardware_source='E:/P1/board/system.bit + system.hwh')
            except BaseException:pass
        finally:
            if formal_begin is not None:
                checkpoint('HDMI_PRE_CLEANUP_SUMMARY',frames=total,current=current,held=held,lost=lost,
                    formal_elapsed_s=max(0.,(formal_end or time.perf_counter())-formal_begin),
                    display=display.snapshot(include_samples=False) if display else None)
            # Stop producer first: no native LK context or camera mapping may be
            # closed while CPU prepare/recovery still references it.
            preparer_stopped=True
            if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='prepare_stop_begin',frames=total)
            if native_setup is not None and owns_native_setup:
                try:native_setup.close()
                except BaseException as exc:cleanup.append(('native_setup',repr(exc)));preparer_stopped=False
            if acquirer is not None:
                try:acquirer.close()
                except BaseException as exc:cleanup.append(('initial_acquisition',repr(exc)));preparer_stopped=False
            if preparer is not None:
                try:preparer.close()
                except BaseException as exc:cleanup.append(('prepare',repr(exc)));preparer_stopped=False
            if job is not None and preparer_stopped:
                try:job.release_source();job=None
                except BaseException as exc:cleanup.append(('owner_source',repr(exc)))
            if first is not None:
                try:first.release()
                except BaseException as exc:cleanup.append(('first_lease',repr(exc)))
            if preparer_stopped and frontend is not None:
                if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='frontend_close_begin',frames=total)
                try:frontend.close()
                except BaseException as exc:cleanup.append(('frontend',repr(exc)));preparer_stopped=False
            if preparer_stopped and camera is not None:
                if backend is None or not backend.active:
                    try:camera.retire_consumers((preparer.worker,) if preparer is not None else (),current_owner_retired=True)
                    except BaseException as exc:cleanup.append(('consumer_drain',repr(exc)))
                camera_end=camera.metadata()
                try:
                    if hot is not None and _ui_context.cancel.is_set() and not user_interrupted and run_error is None and not cleanup:
                        camera_preserved=hot.offer(_ui_context,camera,stream_key,budget,
                            readers_retired=preparer_stopped,backend_idle=backend is not None and not backend.active and not backend.failed,
                            admitted=stability is not None and frontend is not None)
                    if not camera_preserved:
                        if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='camera_close_begin',frames=total)
                        camera.close()
                except BaseException as exc:cleanup.append(('camera',repr(exc)))
            if borrowed:checkpoint('UI_CAMERA_CLEANUP',phase='camera_cleanup_end',frames=total,errors=list(cleanup),capture_kept_running=camera_preserved)
            display_stopped=True
            if display is not None and not borrowed:
                try:display.close()
                except BaseException as exc:
                    display_stopped=bool(display.shutdown_safe)
                    if display_stopped:
                        if run_error is None:run_error=exc
                        checkpoint('HDMI_FAILED_BUT_HALTED',durable=True,exception=repr(exc),hardware_stopped=True)
                    else:cleanup.append(('hdmi',repr(exc)))
                display_summary=display.snapshot()
            elif display is not None:display_summary=display.snapshot(include_samples=False)
            if display_stopped and backend is not None and not borrowed:
                try:backend.close()
                except BaseException as exc:cleanup.append(('backend',repr(exc)))
            if budget is not None and not camera_preserved:budget.__exit__(None,None,None)
            if cleanup:
                _POISONED=True;_POISON_REASON=list(cleanup)
                _RETAINED.append((native_setup,acquirer,preparer,frontend,camera,display,backend))
                checkpoint('HDMI_CLEANUP_FAILED',durable=True,errors=cleanup,resources_retained=True)
        if run_error is not None:raise run_error
        if cleanup:raise RuntimeError('Cleanup safety check failed '+str(cleanup))
        elapsed=max(0.,(formal_end or time.perf_counter())-formal_begin) if formal_begin is not None else 0.
        ds=display_summary.get('epoch_stats',{}).get(str(epoch),{})
        samples=[s for s in display_summary.get('samples',[]) if s['epoch']==epoch]
        timings={} if borrowed and interrupted else {key:_summary(list(rows),key) for key in ('ps_prepare_s','ps_thread_cpu_s','ps_prepare_total_s','ps_prepare_total_thread_cpu_s','tracker_s','plan_update_s',
            'observation_wrapper_s','observation_native_s','result_decode_s','result_decode_thread_cpu_s','source_corners_s','post_observation_s',
            'pre_obs_s','static_hold_s','lk_s','post_lk_tail_s','feature_s','feature_roi_s',
            'orientation_prepare_s','orientation_thread_cpu_s','native_geometry_s','native_geometry_thread_cpu_s','h_native_s','h_native_thread_cpu_s',
            'geometry_result_decode_s','geometry_result_decode_thread_cpu_s','metadata_build_s','metadata_thread_cpu_s','job_seal_s','proof_s','proof_thread_cpu_s','mapping_native_s','mapping_native_thread_cpu_s','illumination_probe_s','edge_stability_s','edge_stability_thread_cpu_s','local_edge_lock_s','local_edge_lock_thread_cpu_s','quick_current_candidate_s','quick_current_candidate_thread_cpu_s','source_snapshot_s',
            'preparation_wait_s','parameter_queue_s','owner_s','owner_thread_cpu_s','control_s','input_copy_s',
            'cache_sync_s','dma_wait_s','tile_assembly_s','lookahead_service_s','display_snapshot_s','display_snapshot_thread_cpu_s','display_offer_lock_wait_s','display_raw_copy_s','display_output_copy_s','display_pair_copy_native_s','display_pair_copy_native_thread_cpu_s','direction_to_output_s','capture_to_output_s','driver_to_output_s',
            'svc_pre_s','svc_hybrid_s','svc_counters_s','svc_offer_tail_s',
            'owner_release_s','owner_prep_s','owner_sharp_prep_s','owner_arm_s','owner_sharp_done_s','owner_loop_s','owner_loop_accounted_s')}
        display_elapsed=max(0.,max(formal_end or 0.,ds.get('last_submitted_at',0.))-formal_begin) if formal_begin is not None else 0.
        metrics_frontend=(getattr(frontend,'delegate',None) or frontend) if frontend is not None else None
        result=dict(release_id=RELEASE_ID,status='stopped' if interrupted else 'completed',frames=total,
            user_interrupted=user_interrupted,returned_home=returned_home,
            delivered=delivered,current=current,held=held,lost=lost,formal_elapsed_s=elapsed,
            current_correction_fps=current/elapsed if elapsed else 0.,
            current_metric_scope='fresh current corners: complete FB motion OR strict exterior; HELD excluded',
            motion_tracked_frames=speed_counts['v86_motion_frames'],edge_verified_frames=speed_counts['v86_edge_verified_frames'],
            motion_correction_fps=speed_counts['v86_motion_frames']/elapsed if elapsed else 0.,
            independent_edge_verified_fps=speed_counts['v86_edge_verified_frames']/elapsed if elapsed else 0.,
            delivered_fps=delivered/elapsed if elapsed else 0.,held_fps=held/elapsed if elapsed else 0.,
            hdmi_submitted=ds.get('submitted',0),hdmi_current_submitted=ds.get('current',0),
            hdmi_panels_submitted=ds.get('panels',0),
            hdmi_panel_fps=ds.get('panels',0)/display_elapsed if display_elapsed else 0.,
            hdmi_submit_fps=ds.get('submitted',0)/display_elapsed if display_elapsed else 0.,
            hdmi_current_fps=ds.get('current',0)/display_elapsed if display_elapsed else 0.,
            formal_display_elapsed_s=display_elapsed,
            speed_counts=speed_counts,timing=timings,hdmi_timing={} if borrowed and interrupted else {k:_summary(samples,k) for k in ('compose_s','compose_thread_cpu_s','frame_acquire_s','frame_acquire_thread_cpu_s','clear_layout_s','clear_layout_thread_cpu_s','ui_header_restore_s','left_panel_s','left_panel_thread_cpu_s','right_panel_s','right_panel_thread_cpu_s','left_native_s','left_native_thread_cpu_s','right_native_s','right_native_thread_cpu_s','corner_draw_s','other_compose_s','input_convert_s','output_convert_s','scale_s','vdma_submit_s','vdma_submit_thread_cpu_s','direction_to_submit_s','capture_to_submit_s')},
            summary_window='last512 correction rows/last512 display submissions; totals cover all formal frames',
            camera=camera_end,camera_reused=transfer is not None,camera_preserved_for_next_target=camera_preserved,
            display=display_summary,gc=budget.summary() if budget else None,initial=initial,
            stability=stability,hardware_manifest=backend.manifest if backend else None,
            localization_baseline='V74 complete localization including original native kernels; current complete FB motion with safe reentry',
            plan_strategy=plan_strategy,proof_cpu_budget_ms=float(proof_cpu_budget_ms),proof_cache=metrics_frontend.proof_cache.snapshot() if metrics_frontend else None,native_plan_cache=dict(metrics_frontend.plan_workspace.batch.last_cache) if metrics_frontend else None,mapping='P1 planar',photometric='camera passthrough to RGB565 bilinear',
            pipeline='chronological PS producer / single remap owner / same-frame split latest HDMI owner',
            total_call_before_logging_s=time.perf_counter()-setup,rows=list(rows))
        checkpoint('HDMI_FINAL_SUMMARY',durable=True,frames=total,current=current,held=held,lost=lost,
            current_fps=result['current_correction_fps'],delivered_fps=result['delivered_fps'],
            hdmi_current_fps=result['hdmi_current_fps'],hdmi_submit_fps=result['hdmi_submit_fps'],hdmi_panel_fps=result['hdmi_panel_fps'],speed_counts=speed_counts,timing=timings,hdmi_timing=result['hdmi_timing'])
        return result
