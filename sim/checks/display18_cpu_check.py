"""Installed CPU-only display smoke, followed by the retained native17 checks."""
from pathlib import Path
import json
from p11_contract import RELEASE_ID

def run():
    from manual17_cpu_check import run as previous_run
    previous=previous_run()
    from v115_pair_display import PairDisplayState
    from v64_hdmi_display import HdmiLatest
    p=PairDisplayState()
    row=dict(state='CURRENT',hybrid_epoch=0,camera_sequence=1,capture_ready_at=100.,verified_at=100.,
        corners=((1,1),(10,1),(10,10),(1,10)))
    assert p.observe(row,True,True,100.)=='PAIRED'
    state=p.snapshot(100.2);assert state['display_mode']=='PAIRED' and state['pair_producer_stalled']
    assert p.snapshot(100.501)['display_mode']=='RAW_ONLY'
    d=HdmiLatest.__new__(HdmiLatest);d.ui_assets=None;d._live_pixels_seen=True
    assert d._show(None,None,dict(state='LOST',ui_view='compare',ui_generation=1)) is False
    return dict(passed=previous['passed'],release_id=RELEASE_ID,display_policy_checks=4,
        previous_cpu_check=previous,hardware_opened=False,live_board_fps_measured=False)

if __name__=='__main__':
    report=run();Path(__file__).with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
