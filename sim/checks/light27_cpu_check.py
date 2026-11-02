"""Installed PL-light control/contract CPU check; no MMIO or camera access."""
from pathlib import Path
import json,types
def run():
 from target26_cpu_check import run as previous_run
 previous=previous_run()
 from p11_contract import RELEASE_ID
 from v122_light import LightControl,LightDriver,VERSION
 from unittest.mock import patch
 c=LightControl();now=[100.]
 class Registers:
  def __init__(self):self.cfg=0;self.active=0
  def read(self,n):return {0:self.cfg,4:VERSION,8:self.active}.get(n,0)
  def write(self,n,v):self.cfg=v
 reg=Registers();ov=types.SimpleNamespace(ip_dict={'axis_light_0':dict(phys_addr=0x40002000,addr_range=4096)})
 driver=LightDriver(ov,lambda *a:reg,c)
 with patch('v122_light.time.perf_counter',side_effect=lambda:now[0]):
  c.request(25);receipt=driver.begin_frame([1,2]);assert reg.cfg==64
  c.request(100);assert reg.cfg==64
  reg.active=64;driver.completed_frame();assert receipt['percent']==25
  now[0]=100.05;assert driver.begin_frame([1])['percent']==25
  now[0]=100.101;assert driver.begin_frame([1])['percent']==100
  reg.active=256;driver.completed_frame()
 return dict(passed=previous['passed'],release_id=RELEASE_ID,previous_cpu_check=previous,
  light_Q8_frame_boundary_and_multitile_checked=True,latest_only_100ms_checked=True,
  hardware_opened=False,board_FPS_tested=False)
if __name__=='__main__':
 result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False,indent=2))
