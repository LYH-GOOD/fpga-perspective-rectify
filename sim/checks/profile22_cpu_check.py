"""Installed CPU check. No camera/HDMI/PL is opened."""
from pathlib import Path
import json,types
from p11_contract import RELEASE_ID

def run():
    from reuse21_cpu_check import run as previous_run
    previous=previous_run()
    from v119_profile_ui import ProfileUI,progress_at
    display=types.SimpleNamespace(timeout=3.)
    state=types.SimpleNamespace(page='compare',stopping=False,camera_profile='480P')
    ui=ProfileUI(state,display)
    def request(name):ui.bind_request(1);return True
    state.request_camera_profile=request
    assert ui.apply()
    view=display.profile_overlay;started=view['started']
    assert progress_at(view,started)==0. and progress_at(view,started+1.)==.95
    assert progress_at(view,started+10.)==.99
    assert ui.applied('600P',1) and ui.busy
    ready=ui.ready_after
    view=ui.frame_view(display.profile_overlay,1,(600,800,2),ready+.01,10,ready+.02)
    assert view['complete'] and ui.busy
    assert ui.submitted(view,1,ready+.01,10) and not ui.busy
    assert not ui.submitted(view,1,ready+.01,10)
    assert ui.apply();ui.cancel('cpu_smoke');assert not ui.busy
    display.profile_controller=None
    return dict(passed=bool(previous['passed']),release_id=RELEASE_ID,previous_cpu_check=previous,
        actual_profile_metadata_check=True,hardware_opened=False,board_FPS_tested=False)

if __name__=='__main__':
    result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
