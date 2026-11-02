"""CPU work budget plus separate wall guard; no hardware and no hard preemption."""
from pathlib import Path
import hashlib,time
from p11_contract import RELEASE_ID
from v31_detection import RecoveryBudget,_DetectionStop
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class CpuRecoveryBudget(RecoveryBudget):
    def __init__(self,milliseconds,max_candidates,wall_max_s=.70):
        super().__init__(milliseconds,max_candidates)
        self.wall_max_s=float(wall_max_s);self.deadline=self.begin+self.wall_max_s
        self.deferred_stages=[]
    def can_start_stage(self,stage,cpu_s,wall_s,admission_cpu_s=.09,admission_wall_s=.12):
        """Reserve a complete existing admission; this is a launch guard, not preemption."""
        self.check('before_'+stage)
        remaining_cpu=self.milliseconds/1000.-(time.thread_time()-self.begin_cpu)
        remaining_wall=self.deadline-time.perf_counter()
        allowed=remaining_cpu>=cpu_s+admission_cpu_s and remaining_wall>=wall_s+admission_wall_s
        if not allowed:self.deferred_stages.append(dict(stage=stage,remaining_cpu_s=remaining_cpu,
            remaining_wall_s=remaining_wall,required_cpu_s=cpu_s+admission_cpu_s,
            required_wall_s=wall_s+admission_wall_s))
        return allowed
    def check(self,stage,finish_gate=False):
        # The inherited checkpoints still enforce wall guard/candidate count,
        # and retain stage times. CPU budget does not charge descheduled time.
        super().check(stage,finish_gate)
        if not finish_gate and time.thread_time()-self.begin_cpu>=self.milliseconds/1000.:
            self.stopped='thread_cpu_budget';raise _DetectionStop('恢复检测达到线程CPU预算')
    def summary(self):
        result=super().summary()
        result.update(budget_basis='thread_CPU_plus_separate_wall_guard',wall_guard_s=self.wall_max_s,
            candidate_duplicate_skips=int(getattr(self,'candidate_duplicate_skips',0)),
            deduplication_scope='exact geometry and refinement strategy; one current snapshot only',
            deferred_stages=list(self.deferred_stages),
            wall_guard_overshoot_s=max(0.,time.perf_counter()-self.deadline),
            cpu_budget_overshoot_s=max(0.,result['thread_cpu_s']-self.milliseconds/1000.),
            overshoot_s=max(0.,time.perf_counter()-self.deadline),
            deadline_kind='cooperative CPU checkpoints; native calls see wall guard; final gate cannot be preempted')
        return result



def compact_recovery_summary(summary):
    """Keep proposal/gate failures, without repeated full profile trees."""
    keys=('budget_ms','max_candidates','candidates','elapsed_s','thread_cpu_s','wall_minus_thread_cpu_s',
        'stop_reason','last_stage','budget_basis','wall_guard_s','cpu_budget_overshoot_s','wall_guard_overshoot_s','deferred_stages',
        'candidate_duplicate_skips','deduplication_scope')
    out={k:summary.get(k) for k in keys}
    out['candidate_proposals']=summary.get('candidate_proposals',())[:4]
    out['rejected_candidates']=[]
    for item in summary.get('rejected_candidates',())[-4:]:
        row={k:item.get(k) for k in ('detector','reason')}
        for name in ('gate','agreement'):
            v=item.get(name) or {}
            row[name]={k:v.get(k) for k in ('verified','reliable','min_support','max_rms','prediction_correction','line_normal_difference','normal_limit') if k in v}
        out['rejected_candidates'].append(row)
    out['detail_sampled']=False
    return out
