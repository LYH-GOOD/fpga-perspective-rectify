"""Installation smoke for reset invariants; no camera, HDMI, PL or live FPS."""
from pathlib import Path
import json
import numpy as np
from p11_contract import RELEASE_ID
from v109_target_cycle import TargetCycle

def run():
    from recovery_cpu_check import run as previous_check
    previous=previous_check()
    c=TargetCycle();q=np.array([[20,20],[100,20],[100,90],[20,90]],np.float32)
    for t in (100.,100.5,101.):c._candidate_signal(q,t)
    assert c.candidate_version==1
    c._candidate_signal(None,101.5)
    assert c.candidate_box is None and c.candidate_since is None and c.present_at is None
    c._candidate_signal(q,102.);c._candidate_signal(q,102.5)
    assert c.present_at is None
    c._candidate_signal(q,103.)
    assert c.present_at==103. and c.candidate_since==102. and c.candidate_version==1
    result=dict(release_id=RELEASE_ID,passed=True,timer_reset_checks=4,previous_cpu_check=previous,
        live_board_fps_measured=False,scope='CPU clock/reset and unchanged native checks; board FPS pending')
    Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result

if __name__=='__main__':run()
