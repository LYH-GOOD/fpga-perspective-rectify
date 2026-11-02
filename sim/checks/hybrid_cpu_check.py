"""Installation CPU checks only; no camera, HDMI, DMA, or live FPS claim."""
from pathlib import Path
import hashlib,json,platform,time
from v107_policy import OutputMonitor
from p11_contract import RELEASE_ID

def run():
    m=OutputMonitor(100.)
    assert m.tick(102.999) is None and m.tick(103.)=='startup_no_output'
    assert m.tick(104.) is None
    m=OutputMonitor(100.)
    for i,t in enumerate((100.1,100.3,100.5,100.7,100.9),1):
        assert m.observe(dict(state='CURRENT',camera_sequence=i,capture_ready_at=t),t)
    assert m.tick(101.1) is None
    assert m.tick(101.31)=='low_fps'
    m=OutputMonitor(100.)
    assert not m.observe(dict(state='HELD',camera_sequence=1),101.)
    assert not m.observe(dict(state='CURRENT',camera_sequence=2,frozen_output=True),101.)
    rows=[dict(state='CURRENT',camera_sequence=i,capture_ready_at=100.+i/30.) for i in range(1,10001)]
    began=time.perf_counter()
    m=OutputMonitor(100.)
    for row in rows:m.observe(row,row['capture_ready_at'])
    hook_us=(time.perf_counter()-began)*1e6/len(rows)
    from trackfix_cpu_check import run as edge_check
    edge=edge_check()
    result=dict(release_id=RELEASE_ID,passed=True,policy_checks=4,output_hook_mean_us=hook_us,
        machine=platform.machine(),native_edge_check=edge,live_board_fps_measured=False,
        scope='CPU input-only installation smoke; compare live normal AUTO tracking via run-result.log')
    path=Path(__file__).with_suffix('.json');path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result
if __name__=='__main__':run()
