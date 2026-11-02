"""Board installation smoke: CPU-only; never opens camera, HDMI, PL or DMA."""
from pathlib import Path
import json,platform
import cv2,numpy as np
from p11_contract import RELEASE_ID
from v109_target_cycle import TargetCycle
def run():
    from hybrid_cpu_check import run as previous_check
    previous=previous_check()
    blank=np.full((480,640,3),200,np.uint8);target=blank.copy()
    cv2.rectangle(target,(140,90),(490,390),(20,20,20),-1)
    cycle=TargetCycle();events=[cycle.observe(blank,i+1,100.+i*.5) for i in range(4)]
    assert events==[None,None,None,'ABSENT']
    events=[cycle.observe(target,i+5,102.+i*.5) for i in range(3)]
    assert events==[None,None,'RETURNED']
    assert cycle.observe(target,8,104.) is None
    result=dict(release_id=RELEASE_ID,passed=True,target_cycle_checks=3,previous_cpu_check=previous,
        machine=platform.machine(),live_board_fps_measured=False,
        scope='CPU-only synthetic input and unchanged native edge kernel; not live camera/FPS acceptance')
    Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result
if __name__=='__main__':run()
