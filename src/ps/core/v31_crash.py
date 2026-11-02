"""Fatal signal stacks and bounded startup breadcrumbs in run-result.log.

Fatal handlers write directly to a pinned append descriptor, bypassing the
Python logger queue. SIGKILL/OOM cannot be intercepted; inspect dmesg for those.
"""
from pathlib import Path
import faulthandler, hashlib, os, threading
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_FILE=None
_LOCK=threading.Lock()


def install_crash_capture():
    global _FILE
    with _LOCK:
        if _FILE is None:
            _FILE=(Path(__file__).resolve().parent/'run-result.log').open('ab',buffering=0)
        # Keep this descriptor open for the entire kernel lifetime. Re-enable
        # explicitly if another library changed the signal handler meanwhile.
        faulthandler.enable(file=_FILE,all_threads=True)
        return dict(pid=os.getpid(),enabled=faulthandler.is_enabled(),
            log_file=str(Path(__file__).resolve().parent/'run-result.log'),
            caught_signals=['SIGSEGV','SIGBUS','SIGABRT','SIGFPE','SIGILL'],
            sigkill_oom_captured=False,scope='kernel_lifetime_pinned_append_fd',
            startup_trace_scope='first frame; warmup if warmup_frames>=1')


def startup_stage(stage,index,**data):
    # Deliberately only the first frame. No per-pixel logging or formal-stream
    # fsync loop. With zero warmup this diagnostic overhead is measured.
    if int(index or 0)!=1:return
    from run_logging import checkpoint
    checkpoint('STARTUP_'+stage,durable=True,index=1,pid=os.getpid(),
        thread_id=threading.get_ident(),**data)
