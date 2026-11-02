"""Installed CPU-only latest preview ownership/cancel/native smoke."""
from pathlib import Path
import json,threading,types
import numpy as np
from p11_contract import RELEASE_ID

def run():
    from hotfix_cpu_check import run as previous_check
    from v113_live_preview import bind_preview,source_snapshot
    from v31_detection import detection_cancel_scope,_budget_check,_ACQUIRE_CANCEL
    previous=previous_check()
    display=types.SimpleNamespace(condition=threading.Condition(),ui_view='compare',ui_generation=3,stop=False,period=1./30.)
    camera=types.SimpleNamespace(color_mode=0);preview=bind_preview(camera,display,3)
    now=[100.];preview.clock=lambda:now[0];preview.published_at=100.
    frame=types.SimpleNamespace(sequence=1,ready=100.,image=np.full((16,16,2),77,np.uint8))
    raw=source_snapshot(camera,frame)
    assert raw.flags.owndata and not raw.flags.writeable and preview.snapshot()[2] is raw
    frame.image.fill(4);assert np.all(raw==77)
    now[0]+=.1;frame.sequence=2;frame.ready=now[0];preview.capture(frame)
    assert source_snapshot(camera,frame) is frame.preview_snapshot
    assert preview.fallback_copies==1
    display.ui_generation=4;now[0]+=.1;preview.capture(frame);assert preview.fallback_copies==1
    seen=[]
    with detection_cancel_scope(lambda:seen.append(1)):_budget_check('live12_install')
    assert seen==[1] and _ACQUIRE_CANCEL.get() is None
    result=dict(release_id=RELEASE_ID,passed=True,preview_and_cancel_checks=6,previous_cpu_check=previous,
        live_board_fps_measured=False,scope='CPU-only RAM/ownership/cancel/native; no camera/HDMI/PL')
    Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return result

if __name__=='__main__':run()
