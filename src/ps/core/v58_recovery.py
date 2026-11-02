"""Bounded CPU-only P1-style recovery. Own RAM only; never MMAP/CMA/MMIO."""
from pathlib import Path
import contextvars,hashlib,threading,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

_CURSOR_SKIP='recovery_candidate_previously_rejected_in_scene_pass'

class SearchBudget:
    """Construct lazily to preserve import order of existing recovery modules."""
    @staticmethod
    def create(milliseconds,candidates,wall_max_s,cursor):
        from v58_budget import CpuRecoveryBudget
        class ProgressBudget(CpuRecoveryBudget):
            def __init__(self):
                super().__init__(milliseconds,candidates,wall_max_s=wall_max_s)
                self.cursor=dict(cursor);self.visited={};self.positions=[]
            def claim(self,label,coarse):
                position=self.visited.get(label,0)+1;self.visited[label]=position
                if position<=self.cursor.get(label,0):
                    self.check('recovery_cursor_skip')
                    raise ValueError(_CURSOR_SKIP)
                super().claim(label,coarse);self.positions.append((label,position))
            def completed_cursor(self):
                from collections import Counter
                rejected=Counter(row.get('detector') for row in self.rejections
                    if row.get('reason') not in (_CURSOR_SKIP,'internal_rectangle_has_current_proven_outer'))
                progress=dict(self.cursor)
                for label,position in self.positions:
                    if rejected[label]>0:
                        progress[label]=max(position,progress.get(label,0));rejected[label]-=1
                return progress
        return ProgressBudget()

class RecoveryWorker:
    def __init__(self,detection_limit,tracking_limit,retry_s=.10):
        self.detection_limit=int(detection_limit);self.tracking_limit=int(tracking_limit)
        self.retry_s=float(retry_s);self.condition=threading.Condition()
        self.pending=None;self.result=None;self.busy=False;self.stopped=False;self.error=None
        self.next_request=0.;self.context=contextvars.copy_context()
        self.recent_seeds=[];self.seed_ready=0.;self.seed_shape=None;self.seed_probe=None
        self.seed_cursor=0;self.seed_failures=0;self.detail_next_at=0.
        self.search_round=0;self.search_cursors={True:{},False:{}};self.search_probe=None
        self.metrics=dict(requests=0,successes=0,failures=0,copy_s=0.,worker_wall_s=0.,worker_cpu_s=0.,
            candidate_limit=4,queue_capacity=1,owned_source_bytes=0,hardware_access=False,
            recent_candidate_slices=0,recent_candidate_successes=0,full_searches=0)
        self.thread=threading.Thread(target=self._entry,name='p11-cpu-recovery',daemon=True)
        self.thread.start()

    def request(self,image,index,ready,sequence,budget_ms,max_candidates):
        # Reservation prevents a second copy, even if a caller is interrupted.
        with self.condition:
            if self.error is not None:raise RuntimeError('CPU recovery worker failed') from self.error
            if self.stopped or self.busy or self.pending is not None or self.result is not None or time.perf_counter()<self.next_request:
                return False
            self.busy=True
        began=time.perf_counter()
        try:
            owned=np.array(image,dtype=np.uint8,copy=True,order='C');owned.flags.writeable=False
            item=dict(image=owned,index=int(index),ready=float(ready),sequence=sequence,
                budget_ms=float(budget_ms),max_candidates=int(max_candidates),copied_at=time.perf_counter())
        except BaseException:
            with self.condition:self.busy=False;self.condition.notify_all()
            raise
        with self.condition:
            if self.stopped:self.busy=False;return False
            self.pending=item;self.metrics['requests']+=1;self.metrics['copy_s']+=time.perf_counter()-began
            self.metrics['owned_source_bytes']=owned.nbytes;self.condition.notify_all()
        return True

    def take(self):
        with self.condition:
            if self.error is not None:raise RuntimeError('CPU recovery worker failed') from self.error
            value=self.result;self.result=None
            return value

    def snapshot(self):
        with self.condition:return dict(self.metrics,busy=self.busy,pending=self.pending is not None,
            result_ready=self.result is not None,error=None if self.error is None else repr(self.error))

    def _entry(self):
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.busy=False;self.condition.notify_all()

    def _run(self):
        from v31_detection import recovery_detection_scope,recovery_candidate_scope,detect_refined
        from v58_budget import CpuRecoveryBudget,compact_recovery_summary
        from run_logging import checkpoint
        from v87_v74_tracking import GrayObserver
        observer=GrayObserver(self.tracking_limit)  # Private to this CPU thread.
        while True:
            with self.condition:
                while self.pending is None and not self.stopped:self.condition.wait()
                if self.stopped:return
                item=self.pending;self.pending=None
            began=time.perf_counter();cpu=time.thread_time()
            # Proposal work in the supplied log already consumed ~300ms CPU
            # before candidate0. Keep a finite separate wall guard, but leave
            # the configured compute budget for actual candidate admission.
            # Hints are geometry proposals, remeasured on this owned CURRENT
            # snapshot; a bounded hint miss never grants a cached proof.
            raw=item['image'];probe=raw[::max(1,raw.shape[0]//12),::max(1,raw.shape[1]//16),0].astype(np.float32) if raw.ndim==3 and raw.shape[2]==2 else None
            centered=None if probe is None else probe-float(np.mean(probe))
            compatible=bool(self.recent_seeds and self.seed_shape==raw.shape and centered is not None
                and self.seed_probe is not None and centered.shape==self.seed_probe.shape
                and 0<=item['ready']-self.seed_ready<=.9 and self.seed_failures<2
                and float(np.median(np.abs(centered-self.seed_probe)))<=12.)
            seeds=(self.recent_seeds[self.seed_cursor%len(self.recent_seeds)],) if compatible else ()
            if compatible:self.seed_cursor+=1
            changed=(centered is None or self.search_probe is None or centered.shape!=self.search_probe.shape
                or float(np.median(np.abs(centered-self.search_probe)))>12.)
            if changed:self.search_cursors={True:{},False:{}};self.search_round=0
            self.search_probe=None if centered is None else centered.copy()
            prefer_mask=True if compatible else self.search_round%2==0
            cursor={} if compatible else self.search_cursors[prefer_mask]
            if not compatible:self.search_round+=1
            slice_ms=min(item['budget_ms'],180.) if compatible else item['budget_ms']
            budget=SearchBudget.create(slice_ms,1 if compatible else item['max_candidates'],.65 if compatible else 1.0,cursor)
            detailed=began>=self.detail_next_at
            if detailed:self.detail_next_at=began+2.
            budget.log_detail=detailed
            with self.condition:self.metrics['recent_candidate_slices' if compatible else 'full_searches']+=1
            result={k:v for k,v in item.items() if k!='image'}
            try:
                source_gray,source_scale=observer.get(item['image'])
                observation=dict(gray=source_gray,scale=source_scale,source_shape=item['image'].shape)
                with recovery_detection_scope(budget,observation),recovery_candidate_scope(seeds,compatible):
                    quad,info=detect_refined(item['image'],self.detection_limit,True,
                        prefer_mask=prefer_mask,tracking_limit=self.tracking_limit)
                result.update(valid=True,source_gray=source_gray.copy(),source_scale=np.asarray(source_scale).copy(),
                    quad=np.asarray(quad,np.float32).copy(),
                    detector_label=info.get('method',info.get('detector')),stale_receipt_retained=False)
            except (ValueError,cv2.error) as exc:
                result.update(valid=False,reason=str(exc),diagnostics=getattr(exc,'diagnostics',None))
            if compatible:
                self.seed_failures=0 if result['valid'] else self.seed_failures+1
                if result['valid']:
                    with self.condition:self.metrics['recent_candidate_successes']+=1
            else:
                progress=budget.completed_cursor()
                advanced=progress!=cursor
                unfinished=([budget.proposals[i] for i,(label,position) in enumerate(budget.positions)
                    if position>progress.get(label,0)] if budget.stopped in ('thread_cpu_budget','cooperative_deadline') else [])
                self.search_cursors[prefer_mask]=progress if (advanced or unfinished) and sum(progress.values())<12 else {}
                # Rejected geometry is not retried as a cheap hint. A candidate
                # interrupted before its gate may resume on a NEW snapshot,
                # without replaying expensive proposal enumeration or evidence.
                self.recent_seeds=([dict(detector='multicolor_exterior' if prefer_mask else 'current_Y',coarse_corners=np.asarray(quad).tolist())]
                    if result['valid'] else unfinished[:1])
                self.seed_ready=float(item['ready']);self.seed_shape=raw.shape;self.seed_probe=None if centered is None else centered.copy()
                self.seed_cursor=0;self.seed_failures=0
            result.update(recent_candidate_slice=compatible,coarse_hint_count=len(self.recent_seeds),
                completed_at=time.perf_counter(),worker_s=time.perf_counter()-began,
                worker_cpu_s=time.thread_time()-cpu,budget=budget.summary())
            checkpoint('ASYNC_RECOVERY_RESULT',index=item['index'],camera_sequence=item['sequence'],
                recent_candidate_slice=compatible,slice_cpu_budget_ms=slice_ms,coarse_hint_count=len(self.recent_seeds),
                valid=result['valid'],source_age_s=time.perf_counter()-item['ready'],
                proposal_family='YUV' if prefer_mask else 'Y',candidate_cursor_before=cursor,
                candidate_cursor_after=self.search_cursors[prefer_mask],
                worker_s=result['worker_s'],worker_cpu_s=result['worker_cpu_s'],
                budget=result['budget'] if detailed else compact_recovery_summary(result['budget']),detail_sampled=detailed,
                hardware_access=False,ownership='one owned ordinary-RAM snapshot')
            with self.condition:
                self.busy=False
                if self.stopped:return
                self.result=result;self.next_request=time.perf_counter()+self.retry_s
                self.metrics['successes' if result['valid'] else 'failures']+=1
                self.metrics['worker_wall_s']+=result['worker_s'];self.metrics['worker_cpu_s']+=result['worker_cpu_s']
                self.condition.notify_all()
            # Do not keep source pixels alongside the finished metadata result.
            item=None

    def close(self):
        with self.condition:
            self.stopped=True;self.pending=None;self.result=None;self.condition.notify_all()
        self.thread.join(5.)
        if self.thread.is_alive():raise TimeoutError('CPU recovery call did not retire; owned RAM retained by worker')
        if self.error is not None:raise RuntimeError('CPU recovery worker failed') from self.error
