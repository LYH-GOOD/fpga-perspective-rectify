"""CPU metadata/overlay ownership smoke, preserving all native kernel checks."""
from pathlib import Path
import json
from p11_contract import RELEASE_ID
def run():
    from live_cpu_check import run as previous_check
    from v114_geometry_overlay import GeometryOverlay
    previous=previous_check();g=GeometryOverlay();q=((20.,20.),(100.,20.),(100.,90.),(20.,90.))
    def r(i,t,**kw):return dict(camera_sequence=i,capture_ready_at=t,state='CURRENT',corners=q,hybrid_epoch=0,**kw)
    g.observe(r(1,100.),100.);g.observe(r(2,100.05),100.05)
    assert g.select(2,100.05,100.1)['kind']=='CURRENT'
    assert g.select(3,100.1,100.12)['kind']=='REFERENCE'
    assert not g.select(9,100.3,100.31)['quad']
    g.reset(1,'new_target');assert not g.select(3,100.1,100.12)['quad']
    g.observe(r(8,100.2),100.2);assert not g.select(8,100.2,100.21)['quad']
    result=dict(passed=True,release_id=RELEASE_ID,geometry_checks=5,previous_cpu_check=previous,
        live_board_fps_measured=False,scope='CPU bounded metadata only; no camera/HDMI/PL')
    Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result
if __name__=='__main__':run()
