"""AI-click camera transitions only. No worker, polling, frame or device hooks."""
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
from run_logging import checkpoint
from v75_hotswitch import camera_key
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_RETAINED=[]


def claim(context,device,width,height,fps,color_mode):
    broker=getattr(context,'hot',None)
    if broker is None:return None
    return broker.claim(context,camera_key(device,width,height,fps,color_mode))


def finish_previous_budget(transfer):
    # The old live epoch ends before click-only Python/model work. The original
    # run_manual starts its normal new budget after the corner handoff.
    budget=transfer.budget
    if budget is not None:
        try:budget.__exit__(None,None,None)
        except BaseException:
            _RETAINED.append(budget);raise
        transfer.budget=None


def park(context,camera,device,width,height,fps,color_mode,budget,*,readers_retired,backend_idle,admitted):
    broker=getattr(context,'hot',None)
    if broker is None or not context.cancel.is_set():return False
    # Broker rechecks identity, source generation, cancellation, parameters,
    # capture health and every CPU lease under its original owner/locks.
    return broker.offer(context,camera,camera_key(device,width,height,fps,color_mode),budget,
        readers_retired=readers_retired,backend_idle=backend_idle,admitted=admitted)
