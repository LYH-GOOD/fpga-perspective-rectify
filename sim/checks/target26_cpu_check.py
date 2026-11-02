"""Installed target-selection CPU check, no camera/FPGA access."""
from pathlib import Path
import json

def run():
 from sharp25_cpu_check import run as previous_run
 previous=previous_run()
 import numpy as np
 from p11_contract import RELEASE_ID
 from v121_selection import source_point,select_mask,can_select
 assert source_point((400,360),(0,120,640,480),(600,800,2))==(500.,300.)
 assert can_select(True,True) and not can_select(True,False)
 m=np.zeros((192,256),np.uint8);m[40:161,20:105]=1;m[40:161,115:221]=1
 q,fit,detail=select_mask(m,dict(point=(60.,100.),source_shape=[192,256,3]))
 assert q is not None and q[:,0].max()<110 and fit>.9
 assert select_mask(m)[0] is None
 m[98:103,104:116]=1
 assert select_mask(m)[0] is None
 return dict(passed=previous['passed'],release_id=RELEASE_ID,previous_cpu_check=previous,
  point_scale600_checked=True,AI_manual_permission_checked=True,smaller_clicked_component_checked=True,
  multiple_and_bridge_rejected=True,hardware_opened=False,board_FPS_tested=False)

if __name__=='__main__':
 result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False,indent=2))
