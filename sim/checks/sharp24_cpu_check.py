"""Installed remap1.5 capability/protocol check; no board access."""
from pathlib import Path
import json,types
from p11_contract import RELEASE_ID,EXPECTED_HW
def run():
 from sharp23_cpu_check import run as previous_run
 previous=previous_run()
 from v64_p1_backend import P1Backend,inspect_pair
 root=Path(__file__).resolve().parent;_,manifest,_=inspect_pair(root/'system.bit')
 assert EXPECTED_HW==manifest['remap_version']==0x10005
 assert manifest['input_contract']==dict(format='BGRX32',bytes_per_pixel=4,PL_YUYV=False,color_conversion='existing_native_CPU')
 backend=P1Backend.__new__(P1Backend);backend.input_yuyv=None
 class NoHardware:
  def read(self,*a):raise AssertionError('Must not probe unsupported CTRL bits')
  def write(self,*a):raise AssertionError('Must not write unsupported CTRL bits')
 backend.mmio=NoHardware()
 assert backend._input_format() is False and backend._input_format() is False
 return dict(passed=previous['passed'],release_id=RELEASE_ID,previous_cpu_check=previous,
  remap1p5_contract_checked=True,native_BGRX_input_selected=True,hardware_opened=False,board_FPS_tested=False)
if __name__=='__main__':
 result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False,indent=2))
