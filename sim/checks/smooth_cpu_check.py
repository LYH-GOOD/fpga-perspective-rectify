"""CPU-only install smoke for display state/cancellation; no device access."""
from pathlib import Path
import json
import numpy as np
from p11_contract import RELEASE_ID

def run():
    from hotfix_cpu_check import run as previous_check
    from v112_display_hold import DisplayHold
    from v31_detection import detection_cancel_scope,_budget_check,_ACQUIRE_CANCEL
    previous=previous_check()
    raw=np.zeros((16,16,2),np.uint8);raw.setflags(write=False)
    out=np.full((16,16,4),100,np.uint8)
    snap=DisplayHold.snapshot(raw,out,{'camera_sequence':1})
    out.fill(0)
    assert np.all(snap['out']==100) and type(snap['out']) is np.ndarray and not snap['out'].flags.writeable
    assert snap['raw'] is raw
    h=DisplayHold();h.payload=snap;h.stop();assert h.payload is None and h.attempted
    h.reset();assert not h.attempted and h.payload is None
    seen=[]
    with detection_cancel_scope(lambda:seen.append(1)):_budget_check('install_cpu_smoke')
    assert seen==[1] and _ACQUIRE_CANCEL.get() is None
    result=dict(release_id=RELEASE_ID,passed=True,display_and_cancel_checks=5,previous_cpu_check=previous,
        live_board_fps_measured=False,scope='CPU RAM ownership/reset/cancel/native checks; no camera/HDMI/PL access')
    Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result

if __name__=='__main__':run()
