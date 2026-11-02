"""Installed CPU smoke for manual17; never opens camera, HDMI or PL."""
from pathlib import Path
import json,time,types
import cv2,numpy as np
from p11_contract import RELEASE_ID
def run():
    from paired_cpu_check import run as previous_run
    previous=previous_run()
    from v117_manual_reference import ReferenceTracker
    from v64_hdmi_display import PageFeedback
    import threading
    q=np.float32([[140,90],[490,90],[490,390],[140,390]])
    image=np.full((480,640,3),200,np.uint8);cv2.fillConvexPoly(image,q.astype(np.int32),(235,235,235))
    for y in range(120,370,30):cv2.putText(image,'BOOK TEXT',(170,y),cv2.FONT_HERSHEY_SIMPLEX,.6,(70,70,70),1)
    stamp=time.perf_counter();first=types.SimpleNamespace(image=image,ready=stamp,sequence=1)
    tracker=ReferenceTracker(first,q);errors=[];native=bool(tracker.lk_cache.pointer)
    try:
        for i in range(1,7):
            current=cv2.warpAffine(image,np.float32([[1,0,i*2],[0,1,0]]),(640,480),borderMode=cv2.BORDER_REPLICATE)
            frame=types.SimpleNamespace(image=current,ready=time.perf_counter(),sequence=i+1)
            got,detail=tracker.update(frame)
            assert got is not None,detail
            error=float(np.max(np.linalg.norm(got-(q+[i*2,0]),axis=1)));assert error<4.5,error;errors.append(error)
    finally:tracker.close()
    async def submit(frame):return 0
    d=types.SimpleNamespace(condition=threading.Condition(),target_switch=None,_submit=submit,canvas_views={})
    feedback=PageFeedback(d);feedback.begin('compare',1,'ai_calibration')
    assert feedback.loading['until']=='output'
    feedback.live_frame(dict(ui_generation=1,hybrid_phase='RECOVERY_COOLDOWN'),False)
    assert feedback.loading['live_settled'];feedback.cancel();assert '_feedback_live' not in d.__dict__
    return dict(passed=previous['passed'],release_id=RELEASE_ID,manual_reference_checks=6,progress_checks=3,
        manual_corner_max_error_px=max(errors),native_lk_executed=native,
        previous_cpu_check=previous,live_board_fps_measured=False,hardware_opened=False)
if __name__=='__main__':
    report=run();Path(__file__).with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
