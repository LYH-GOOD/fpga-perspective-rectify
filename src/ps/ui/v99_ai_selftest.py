"""Recorded-image CPU self-test of the actual resident worker and four-corner handoff."""
from pathlib import Path
import hashlib,json,os,sys,threading,time,types
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT=Path(__file__).resolve().parent


def process_seconds(pid):
    try:
        fields=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()
        return (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    except (OSError,ValueError,AttributeError):
        if os.name!='nt':return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return None
        try:
            values=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(x) for x in values]):return None
            return sum(((x.dwHighDateTime<<32)|x.dwLowDateTime) for x in values[2:])/1e7
        finally:kernel.CloseHandle(handle)
    except (OSError,AttributeError):return None


def run_selftest(output=None,service_factory=None,idle_s=1.,event_sink=None):
    import numpy as np,cv2
    import v82_interaction as interaction
    from v99_ai_service import Service,Request,memory_info
    events=[]
    def emit(stage,**fields):
        events.append(dict(stage=stage,**fields))
        if event_sink is not None:event_sink(stage,**fields)
    config=json.loads((ROOT/'v99_ai_selftest.json').read_text(encoding='utf-8'))
    if config['release_id']!=RELEASE_ID:raise ValueError('Self-test version mismatch')
    for item in config['cases']:
        if hashlib.sha256((ROOT/item['image']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Self-test image mismatch')
    report=dict(status='running',release_id=RELEASE_ID,scope='recorded BGR CPU resident IPC and original corner handoff',
        camera_accessed=False,pl_accessed=False,hdmi_accessed=False,physical_fps_measured=False,cases=[])
    output=Path(output or ROOT/'ai_selftest_result.json')
    service=(service_factory or Service)(event_sink=emit,preload=True);old_log=interaction.checkpoint;interaction.checkpoint=emit
    try:
        service.enter_home()
        if not service.wait_ready(65.) and service.state!='on_demand':raise RuntimeError('AI initialization failed: '+str(service.last_error))
        report['initial_worker']=dict(service.worker_info);report['parent_memory_before_live']=memory_info()
        service.prepare_live()
        if service.process is None:
            report['resident_released_for_memory']=True  # explicit calls remain available
        first_pid=None
        for index,item in enumerate(config['cases']):
            image=cv2.imdecode(np.frombuffer((ROOT/item['image']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape!=(480,640,3):raise ValueError('Invalid self-test image')
            image.setflags(write=False)
            display=types.SimpleNamespace(condition=threading.Condition(),ui_generation=7,stop=False,
                pending=None,canvas_views={},layouts={},ai_service=service)
            editor=interaction.Inspection(display);display.inspection=editor
            editor.kind='calibration';editor.generation=7;editor.source=image;editor.source_rect=interaction.SOURCE_RECT
            editor.meta=dict(sequence=100+index,source_shape=(480,640));editor.notice='select'
            assert editor.queue_ai(7,ai_only=True);assert editor.take_action(7)==('ai',None)
            task=Request(editor,7);started=time.perf_counter()
            try:
                if not task.done.wait(75.):raise TimeoutError('Self-test request did not finish')
                task.poll()
            finally:task.close()
            action=editor.take_action(7)
            if action is None or action[0]!='confirm':raise RuntimeError('Self-test AI failed: '+str(task.result))
            expected=np.array(item['quad'],np.float32)
            error=float(np.max(np.linalg.norm(action[1]-expected,axis=1)))
            if error>2.5:raise ValueError('Self-test corner drift %.3fpx exceeds 2.5px'%error)
            pid=task.result.get('pid');first_pid=pid if first_pid is None else first_pid
            report['cases'].append(dict(id=item['id'],quad=action[1].tolist(),max_corner_drift_px=error,
                elapsed_ms=(time.perf_counter()-started)*1000.,worker_ms=task.result.get('worker_ms'),
                pid=pid,automatic_original_handoff=True,memory=task.result.get('memory')))
            emit('AI_SELFTEST_CASE_PASSED',id=item['id'],max_corner_drift_px=error,pid=pid)
        report['same_worker_for_all_cases']=len({x['pid'] for x in report['cases']})==1
        if service.process is not None:
            pid=service.process.pid;before=process_seconds(pid);began=time.monotonic();time.sleep(idle_s)
            after=process_seconds(pid);elapsed=time.monotonic()-began
            cpu=(after-before)/elapsed*100. if before is not None and after is not None else None
            report['idle']=dict(seconds=elapsed,worker_cpu_percent_one_core=cpu,state=service.state,
                measured=cpu is not None,idle_cpu_check_passed=cpu is not None and cpu<=2.)
        report['parent_imported_ncnn']='ncnn' in sys.modules
        report['worker_opencv_imported']=service.worker_info.get('opencv_imported')
        report['resident_admitted']=service.process is not None
        report['status']='passed';emit('AI_SELFTEST_PASSED',cases=len(report['cases']),idle=report.get('idle'))
    except Exception as exc:
        report.update(status='failed',error=str(exc),last_stage=service.last_stage)
        emit('AI_SELFTEST_FAILED',error=str(exc),last_stage=service.last_stage)
    finally:
        try:service.close()
        finally:interaction.checkpoint=old_log
        report['manager_retired']=not service.thread.is_alive()
        report['child_retired']=service.last_process is None or service.last_process.poll() is not None
        report['events']=events
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    def show(stage,**fields):
        print(json.dumps(dict(stage=stage,**fields),ensure_ascii=False),flush=True)
    result=run_selftest(event_sink=show)
    print('%d/%d corner checks passed'%(len(result['cases']),len(result['cases'])) if result['status']=='passed' else 'Self-test failed: '+result.get('error','unknown'),flush=True)
    sys.exit(0 if result['status']=='passed' else 1)
