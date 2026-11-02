"""Installed release28 CPU checks, including inherited native/control smoke.

Does not open a camera, overlay, MMIO, DMA or HDMI device.
"""
from pathlib import Path
import json

def run():
    from light27_cpu_check import run as previous_run
    previous=previous_run()
    from p11_contract import RELEASE_ID
    from v123_live_ui import OutputRate,source_key
    from v111_recovery import HybridFrontend
    r=OutputRate();row=dict(ui_generation=7,camera_sequence=1,state='MANUAL')
    assert r.observe(row,100.,True) and not r.observe(row,100.1,True)
    assert r.fps(100.2)==1./3. and r.fps(103.)==0.
    assert source_key(dict(correction_origin='AI',manual_tracking='FIXED'),True)=='AI'
    spec=json.loads((Path(__file__).parent/'v123_live_ui.json').read_text(encoding='utf-8'))
    assert spec['fps_label_px']==spec['fps_value_px']==52
    assert not hasattr(HybridFrontend,'_cooldown')
    return dict(passed=bool(previous['passed']),release_id=RELEASE_ID,previous_cpu_check=previous,
        unified_output_FPS_checked=True,cached_52px_typography_checked=True,AI_source_label_checked=True,
        fixed_cooldown_removed=True,hardware_opened=False,board_FPS_tested=False)

if __name__=='__main__':
    result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
