"""Immediate sharpening protocol check; never opens hardware."""
from pathlib import Path
import json
def run():
 from sharp24_cpu_check import run as previous_run
 previous=previous_run()
 from p11_contract import RELEASE_ID
 from v120_sharp import SharpControl
 from unittest.mock import patch
 c=SharpControl();now=[100.]
 with patch('v120_sharp.time.perf_counter',side_effect=lambda:now[0]):
  c.request(10);assert c.for_frame()[1]==10
  now[0]=100.05;c.request(20);c.request(30);assert c.for_frame()[1]==10
  now[0]=100.101;assert c.for_frame()[1]==30
 return dict(passed=previous['passed'],release_id=RELEASE_ID,previous_cpu_check=previous,
  latest_only_100ms_frame_boundary_checked=True,hardware_opened=False,board_FPS_tested=False)
if __name__=='__main__':
 result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False,indent=2))
