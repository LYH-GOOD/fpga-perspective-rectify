"""CPU/native smoke plus completed-pair metadata; never opens camera/HDMI."""
from pathlib import Path
import json
from p11_contract import RELEASE_ID

def run():
    from live_cpu_check import run as previous_check
    from v115_pair_display import PairDisplayState
    previous=previous_check();p=PairDisplayState()
    q=((20.,20.),(100.,20.),(100.,90.),(20.,90.))
    def row(i,t,epoch=0,state='CURRENT'):
        return dict(camera_sequence=i,capture_ready_at=t,state=state,corners=q,hybrid_epoch=epoch)
    assert p.observe(row(1,100.),True,True,100.)=='PAIRED'
    assert p.snapshot(100.06)['display_mode']=='PAIRED'
    assert p.observe(row(2,100.067),True,True,100.067)=='PAIRED'
    for t in (100.1,100.15,100.2):p.raw_displayed(t)
    assert p.snapshot(100.218)['display_mode']=='PAIRED'
    assert p.snapshot(100.218)['pair_producer_stalled']
    assert p.snapshot(100.568)['display_mode']=='RAW_ONLY'
    p.invalidate(1,'new_target')
    assert p.observe(row(3,100.6),True,True,100.6)=='DROP'
    assert p.observe(row(4,100.61,1),True,True,100.61)=='PAIRED'
    assert p.observe(row(5,100.62,1,'LOST'),True,False,100.62)=='RAW_ONLY'
    result=dict(passed=True,release_id=RELEASE_ID,pair_checks=9,previous_cpu_check=previous,
        live_board_fps_measured=False,scope='CPU/native and bounded pair metadata; no camera/HDMI/PL')
    Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result
if __name__=='__main__':run()
