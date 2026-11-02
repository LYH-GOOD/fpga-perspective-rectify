"""Wall/OS-thread CPU and GC evidence; no MMIO and no callbacks doing I/O."""
from pathlib import Path
from collections import deque
from functools import wraps
from dataclasses import replace
from types import MappingProxyType
import gc,hashlib,threading,time
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DIAGNOSTICS_PATCH='v30-diagnostics-thread-os-20261005-1'
_OS_FIELDS=('voluntary_context_switches','involuntary_context_switches','minor_page_faults','major_page_faults')
_NATIVE_NAMES=('p11_lk_anchor', 'p11_lk_track', 'p11_lk_promote', 'p11_gray2', 'p11_gaussian3', 'p11_quad_valid', 'p11_spatial', 'p11_lk_filter', 'p11_edges', 'p11_guard', 'p11_plan_geometry', 'p11_prepare', 'p11_packet', 'p11_signature', 'p11_prepare_control', 'p11_probe', 'p11_wait_io', 'p11_observe2', 'p11_edges_motion', 'p11_copy_bgr', 'p11_arm_io', 'p11_plan_wait', 'p11_frame_state', 'p11_motion_values', 'outer_calls', 'p11_observe_edges', 'p11_lk_checked', 'p11_roi_features', 'p11_owner_batch', 'p11_owner_complete')
# Only these native scopes instrument OS counters in the existing C++ ABI.
_NATIVE_OS_INDICES=(1,7,17,18,24,25,26,27,28,29)
_LOCAL=threading.local();_EVENTS=deque(maxlen=4096);_GC_START={};_NUMBER=0
def _callback(action,info):
 global _NUMBER
 ident=threading.get_ident();now=time.perf_counter();cpu=time.thread_time()
 if action=='start':_GC_START[ident]=(now,cpu,getattr(_LOCAL,'phase',None),info.get('generation'))
 else:
  begin=_GC_START.pop(ident,None)
  if begin:
   _NUMBER+=1;_EVENTS.append(dict(number=_NUMBER,begin=begin[0],end=now,wall_s=now-begin[0],thread_cpu_s=cpu-begin[1],thread_id=ident,phase=begin[2],generation=begin[3],collected=info.get('collected'),uncollectable=info.get('uncollectable')))
def enable_gc():
 if _callback not in gc.callbacks:gc.callbacks.append(_callback)
def disable_gc():
 if _callback in gc.callbacks:gc.callbacks.remove(_callback)
 _GC_START.clear()
def gc_cursor():return _NUMBER

def gc_records(after=0):
 # Per-frame callers need only new events. Do not rebuild all historical
 # dictionaries on every frame or the diagnostic itself can trigger GC.
 if after>=_NUMBER:return []
 events=[]
 for event in reversed(list(_EVENTS)):
  if event['number']<=after:break
  events.append(dict(event))
 events.reverse();return events

def gc_retention(after=0):
 snapshot=list(_EVENTS)
 first=snapshot[0]['number'] if snapshot else _NUMBER+1
 return dict(cursor=_NUMBER,capacity=_EVENTS.maxlen,unavailable_since_cursor=max(0,first-after-1))
def _diagnostic_workspace(reuse=True):
 """Separate pre/post snapshots per OS thread; nested calls use private buffers."""
 import numpy as np
 cached=getattr(_LOCAL,'snapshot_workspace',None) if reuse else None
 if cached is None:
  cached=dict(native_before=np.empty(90,np.float64),native_after=np.empty(90,np.float64),
   native_delta=np.empty(90,np.float64),os_before=np.empty((30,4),np.float64),
   os_after=np.empty((30,4),np.float64),os_delta=np.empty((30,4),np.float64))
  if reuse:_LOCAL.snapshot_workspace=cached
 return cached

def _native(out=None):
 from v31_native import profile_snapshot
 return profile_snapshot(raw=True,out=out)
def delta(after,before,detailed=True,scratch=None):
 if after is None:return {}
 import numpy as np
 old=np.zeros_like(after) if before is None else before
 if scratch is None:raw=np.maximum(0.,after-old).reshape(-1,3)
 else:
  np.subtract(after,old,out=scratch);np.maximum(scratch,0.,out=scratch);raw=scratch.reshape(-1,3)
 indices=range(len(_NATIVE_NAMES)) if detailed else (24,)
 return {_NATIVE_NAMES[i]:dict(wall_s=float(raw[i,0]),thread_cpu_s=float(raw[i,1]),calls=int(raw[i,2]))
         for i in indices if raw[i,2]>0}

def _thread_usage():
 try:
  import resource
  u=resource.getrusage(resource.RUSAGE_THREAD)
  return (u.ru_nvcsw,u.ru_nivcsw,u.ru_minflt,u.ru_majflt)
 except (ImportError,AttributeError,OSError):return None

def _native_os(out=None):
 from v31_native import profile_os_snapshot
 return profile_os_snapshot(out=out)

def _usage_delta(after,before):
 """Difference of cumulative counters; unavailable data stays unavailable."""
 if after is None or before is None:return {}
 return {name:max(0,int(a)-int(b)) for name,a,b in zip(_OS_FIELDS,after,before)}

def _native_os_delta(after,before,detailed=True,scratch=None):
 if after is None or before is None:return {}
 import numpy as np
 after=np.asarray(after);before=np.asarray(before)
 expected=(len(_NATIVE_NAMES),len(_OS_FIELDS))
 if after.shape!=expected or before.shape!=expected:
  raise ValueError('Native OS profile layout mismatch')
 if scratch is None:raw=np.maximum(0.,after-before)
 else:
  np.subtract(after,before,out=scratch);np.maximum(scratch,0.,out=scratch);raw=scratch
 indices=_NATIVE_OS_INDICES if detailed else (24,)
 return {_NATIVE_NAMES[i]:{name:int(raw[i,j]) for j,name in enumerate(_OS_FIELDS)}
         for i in indices}

def measured(method):
 """Keep diagnostic overhead inside the existing PS/owner timing boundaries."""
 @wraps(method)
 def wrap(self,*args,**kwargs):
  previous_phase=getattr(_LOCAL,'phase',None);_LOCAL.phase=method.__name__
  depth=getattr(_LOCAL,'diagnostic_depth',0);_LOCAL.diagnostic_depth=depth+1
  begin=time.perf_counter();cpu=time.thread_time();event_cursor=gc_cursor()
  native=usage=native_os=None
  try:
   workspace=_diagnostic_workspace(reuse=depth==0)
   from run_logging import native_os_sample
   call_index=(args[1] if len(args)>1 else kwargs.get('index',1)) if method.__name__=='prepare_bgr' else args[0].index
   sample_os=native_os_sample(call_index)
   native=_native(workspace['native_before']);usage=_thread_usage()
   native_os=_native_os(workspace['os_before']) if sample_os else None
   value=method(self,*args,**kwargs)
   end=time.perf_counter();used=time.thread_time()-cpu
   from run_logging import diagnostic_detail
   if method.__name__=='prepare_bgr':index=value.index;tracking=value.record.get('tracking',{})
   else:index=args[0].index;tracking=value[1].get('tracking',{})
   detailed=diagnostic_detail(index,end-begin,tracking)
   nd=delta(_native(workspace['native_after']),native,detailed=detailed,scratch=workspace['native_delta'])
   usage_after=_thread_usage();native_os_after=_native_os(workspace['os_after']) if sample_os else None
   thread_os=_usage_delta(usage_after,usage)
   native_events=_native_os_delta(native_os_after,native_os,detailed=detailed,scratch=workspace['os_delta'])
   for name,metrics in nd.items():
    if name in native_events:metrics['os_thread_events']=native_events[name]
   events=[e for e in gc_records(event_cursor) if e['end']>=begin and e['begin']<=end]
   detail=dict(diagnostics_patch=DIAGNOSTICS_PATCH,os_thread_events=thread_os,os_thread_events_available=usage is not None and usage_after is not None,native_os_events_available=native_os is not None and native_os_after is not None,native_os_scope='per-function OS snapshots sampled first/periodic frames; wall/native/OS-thread CPU counters retained each frame',wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),thread_id=threading.get_ident(),native=nd,native_function_times_are_inclusive=True,native_details_sampled=detailed,gc_overlap_s=sum(max(0.,min(end,e['end'])-max(begin,e['begin'])) for e in events),gc_events=len(events))
   outer=nd.get('outer_calls',{})
   detail.update(native_wall_s=outer.get('wall_s',0.),native_thread_cpu_s=outer.get('thread_cpu_s',0.),python_thread_cpu_estimate_s=max(0.,used-outer.get('thread_cpu_s',0.)),outside_native_wall_minus_cpu_s=max(0.,end-begin-used-outer.get('wall_s',0.)+outer.get('thread_cpu_s',0.)))
   # Keep the main diagnostic assembly cost in the phase and report it.
   tail_begin=end;end=time.perf_counter();used=time.thread_time()-cpu
   detail.update(wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),diagnostic_tail_s=end-tail_begin,
    python_thread_cpu_estimate_s=max(0.,used-outer.get('thread_cpu_s',0.)),outside_native_wall_minus_cpu_s=max(0.,end-begin-used-outer.get('wall_s',0.)+outer.get('thread_cpu_s',0.)))
   clock=getattr(self,'_prepare_timing' if method.__name__=='prepare_bgr' else '_owner_timing',None)
   partition=clock.report(begin,cpu,end,cpu+used) if clock is not None and clock.end is not None else {}
   # Partition assembly is diagnostic work, included in the same service scope.
   end=time.perf_counter();used=time.thread_time()-cpu
   detail.update(wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),diagnostic_tail_s=end-tail_begin)
   if partition:
    tail=partition['stages']['diagnostic_after']
    tail.update(wall_s=max(0.,end-clock.end),thread_cpu_s=max(0.,cpu+used-clock.cpu_end))
    tail['wall_minus_thread_cpu_s']=max(0.,tail['wall_s']-tail['thread_cpu_s'])
    partition.update(wall_s=end-begin,thread_cpu_s=used,wall_minus_thread_cpu_s=max(0.,end-begin-used),
     accounting_residual_s=end-begin-sum(v['wall_s'] for v in partition['stages'].values()))
   if method.__name__=='prepare_bgr':
    record=dict(value.record);record['prepare_diagnostics']=detail;record['prepare_stages']=partition
    return replace(value,record=MappingProxyType(record),begin=begin,ready=end)
   lease,record=value;record['owner_diagnostics']=detail;record['owner_stages']=partition
   record.update(hardware_begin=begin,hardware_end=end,hardware_owner_s=end-begin,bgr_service_s=record['ps_prepare_s']+end-begin,bgr_latency_s=end-record['ps_prepare_begin'],prepared_queue_s=max(0.,begin-record['ps_prepare_end']))
   return lease,record
  except BaseException as error:
   # Failed native calls still have useful CPU/wall evidence. Logging must
   # never replace the original computation/hardware exception.
   try:
    from run_logging import frame_record,current_log_metadata
    if current_log_metadata():
     frame_record('PHASE_FAILED',durable=True,phase=method.__name__,thread_id=threading.get_ident(),diagnostics_patch=DIAGNOSTICS_PATCH,
      os_thread_events=_usage_delta(_thread_usage(),usage),native_os_events=_native_os_delta(_native_os(),native_os),
      wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu,native=delta(_native(),native),
      gc_events=gc_records(event_cursor),exception_type=type(error).__name__,exception=str(error),
      partial_phase_stages=(getattr(self,'_prepare_timing' if method.__name__=='prepare_bgr' else '_owner_timing',None).stages
          if getattr(self,'_prepare_timing' if method.__name__=='prepare_bgr' else '_owner_timing',None) is not None else {}),
      prepare_stage=dict(getattr(self,'_last_prepare_stage',{})))
   except BaseException:pass
   raise
  finally:
   _LOCAL.phase=previous_phase;_LOCAL.diagnostic_depth=depth
 return wrap
