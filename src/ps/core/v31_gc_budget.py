"""Owner-scoped, bounded GC pause; always restore the process' prior state."""
from pathlib import Path
import gc,hashlib,time
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def memory_state():
    try:
        values={k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines()) if k in ('MemAvailable','SwapFree','SwapTotal')}
        status=Path('/proc/self/status').read_text().splitlines()
        values.update({k:int(v.split()[0])*1024 for k,v in (line.split(':',1) for line in status if ':' in line) if k in ('VmRSS','VmSwap')})
        return values
    except (OSError,ValueError):return {}

class GcBudget:
    def __init__(self,policy='bounded',max_frames=240,max_seconds=30.,growth_mb=24):
        if policy not in ('normal','bounded'):raise ValueError('gc_policy须为normal/bounded')
        if isinstance(max_frames,bool) or not isinstance(max_frames,int) or not 1<=max_frames<=1000:raise ValueError('gc_max_frames须为1..1000')
        if not 1.<=float(max_seconds)<=60. or not 4<=growth_mb<=64:raise ValueError('GC duration/growth budget invalid')
        self.policy=policy;self.max_frames=max_frames;self.max_seconds=float(max_seconds);self.growth_bytes=int(growth_mb)*1024*1024
        self.original=gc.isenabled();self.paused=False;self.reason=None;self.closed=False;self.frames=0
        self.start=time.perf_counter();self.start_count=gc.get_count()[0];self.initial=memory_state()
        self.startup_collect_s=0.;self.resume_at=None;self.pause_started=None
    def __enter__(self):
        from run_logging import checkpoint
        if self.policy=='bounded' and self.original and self.initial.get('MemAvailable',0)>=96*1024*1024:
            began=time.perf_counter();gc.collect(2);self.startup_collect_s=time.perf_counter()-began
            self.initial=memory_state()
            if self.initial.get('MemAvailable',0)>=96*1024*1024:
                gc.disable();self.paused=True
        self.start=time.perf_counter();self.start_count=gc.get_count()[0]
        if self.paused:self.pause_started=self.start
        try:
            checkpoint('GC_BUDGET_BEGIN',policy=self.policy,paused=self.paused,prior_enabled=self.original,
                max_frames=self.max_frames,max_seconds=self.max_seconds,growth_bytes=self.growth_bytes,
                startup_collect_s=self.startup_collect_s,memory=self.initial,outside_frame_measurement=True)
        except BaseException:
            if self.original:gc.enable()
            else:gc.disable()
            self.paused=False;raise
        return self
    def check(self,index):
        if not self.paused:return
        self.frames+=1;reason=None;memory={}
        if self.frames>=self.max_frames:reason='frame_limit'
        elif time.perf_counter()-self.start>=self.max_seconds:reason='time_limit'
        elif gc.get_count()[0]-self.start_count>50000:reason='allocation_count_limit'
        if index%8==0 or reason:
            memory=memory_state()
            if memory.get('MemAvailable',0)<64*1024*1024:reason='available_memory_low'
            elif memory.get('VmRSS',0)-self.initial.get('VmRSS',0)>self.growth_bytes:reason='rss_growth_limit'
            elif memory.get('VmSwap',0)>self.initial.get('VmSwap',0)+1024*1024:reason='process_swap_growth'
        if reason:
            gc.enable();self.paused=False;self.reason=reason;self.resume_at=time.perf_counter()
            from run_logging import checkpoint
            checkpoint('GC_BUDGET_RESTORED',index=index,reason=reason,memory=memory,
                measured_pause_s=self.resume_at-self.start,automatic_gc_enabled=True)
    def summary(self):
        return dict(policy=self.policy,prior_enabled=self.original,frames_checked=self.frames,
            pause_s=(self.resume_at or time.perf_counter())-self.pause_started if self.pause_started is not None else 0.,
            restored_early_reason=self.reason,startup_collect_s=self.startup_collect_s,memory=memory_state())
    def __exit__(self,*error):
        # ExitStack closes CPU/loader workers before restoring GC.
        if self.original:gc.enable()
        else:gc.disable()
        self.paused=False;self.closed=True
        return False
