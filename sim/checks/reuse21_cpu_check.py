"""Installed CPU/native smoke; never opens a camera, HDMI or PL device."""
from pathlib import Path
import json,platform,threading,types
from p11_contract import RELEASE_ID

def run():
    from display18_cpu_check import run as previous_run
    previous=previous_run()
    from v111_recovery import AIBudget,HybridFrontend
    from v75_hotswitch import CameraHandoff,camera_key
    budget=AIBudget();a=object();b=object();c=object()
    assert budget.reserve(1.,a) and budget.reserve(2.,b) and budget.reserve(3.,c)
    assert not budget.reserve(4.,object()) and budget.refund(b,5.) and not budget.refund(b,5.)
    assert len(budget.times)==2 and budget.reserve(5.,object())
    f=HybridFrontend.__new__(HybridFrontend);f.search_at=10.;f.started=9.;f.search_epoch_started=9.
    f.candidate_at=None;f.auto_stage='SEARCHING'
    assert not f._auto_search_expired(11.499) and f._auto_search_expired(11.5)
    f.candidate_at=11.5;f.auto_stage='CANDIDATE'
    assert not f._auto_search_expired(12.799) and f._auto_search_expired(12.8)
    assert f.LOSS_S==1.2
    # Instantiate the real broker without any devices; idle expiry is independent
    # from the2s recovery policy and consumes a parked stream only once.
    ticket=types.SimpleNamespace(page='home',cancel=threading.Event(),start_generation=2,
        switch_from=1,switch_requested_at=100.)
    state=types.SimpleNamespace(stopping=False,page='home',ticket=ticket,condition=threading.Condition())
    now=[100.];broker=CameraHandoff(state,clock=lambda:now[0])
    assert broker.idle_remaining() is None
    broker.close()
    capture_native=None
    if platform.system()=='Linux':
        from v31_camera import _library
        library=_library()
        assert library.p11_camera_abi()==3102 and library.p11_camera_reconfigure_abi()==1
        capture_native=dict(compiled_and_loaded=True,abi=3102,reconfigure_abi=1,camera_opened=False)
    return dict(passed=previous['passed'],release_id=RELEASE_ID,previous_cpu_check=previous,
        reuse_policy_checks=12,cooldown_s=2,capture_native=capture_native,hardware_opened=False,live_board_fps_measured=False)

if __name__=='__main__':
    result=run();Path(__file__).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
