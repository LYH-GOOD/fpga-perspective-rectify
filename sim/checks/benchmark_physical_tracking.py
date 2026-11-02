"""Board CPU tracker comparison on recorded pixels; no camera/HDMI/FPGA access."""
from pathlib import Path
import argparse,json,time,types
import cv2,numpy as np
from p11_contract import RELEASE_ID
from v31_native import prepare_native
from v92_manual_v87 import ManualTracker
from v104_physical_tracking import PhysicalTracker

def run(frames=180):
    root=Path(__file__).resolve().parent
    native=prepare_native(build=True,required=False)
    source=cv2.imdecode(np.frombuffer((root/'ai_selftest/4000.png').read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    q=np.array([[164,122],[488,135],[509,360],[142,350]],np.float32)
    mask=np.zeros(source.shape[:2],np.uint8)
    cv2.fillConvexPoly(mask,np.array([[193,139],[464,150],[480,348],[174,338]],np.int32),255)
    ys,xs=np.nonzero(mask);rng=np.random.default_rng(751)
    # Same bounded precomputed input sequence for both trackers. The body and
    # desk are fixed while interior picture changes; input generation is untimed.
    pictures=[]
    for i in range(min(frames,60)):
        image=source.copy();image[ys,xs]=rng.integers(0,256,(len(xs),3),dtype=np.uint8)
        pictures.append(image)
    report=dict(release_id=RELEASE_ID,scope='recorded CPU comparison; not physical camera-to-HDMI FPS',
        native=native,frames=frames,physical_fps_measured=False,results={})
    for name,cls in [('fast3_original_FB',ManualTracker),('physical4_batch',PhysicalTracker)]:
        def frame(i):return types.SimpleNamespace(image=pictures[i%len(pictures)],sequence=i,ready=100.+i/30.)
        tracker=cls(frame(0),q);times=[];valid=0;errors=[]
        try:
            for i in range(1,frames+1):
                started=time.perf_counter();quad,detail=tracker.update(frame(i));elapsed=time.perf_counter()-started
                valid+=quad is not None
                if i>10:times.append(elapsed*1000.)
                if quad is not None:errors.append(float(np.max(np.linalg.norm(quad-q,axis=1))))
        finally:tracker.close()
        report['results'][name]=dict(current=valid,total=frames,median_ms=float(np.median(times)),
            p95_ms=float(np.percentile(times,95)),max_corner_error_px=max(errors,default=None))
    a=report['results']['fast3_original_FB'];b=report['results']['physical4_batch']
    report['tracker_median_not_slower']=b['median_ms']<=a['median_ms']
    report['tracker_p95_not_slower']=b['p95_ms']<=a['p95_ms']
    (root/'physical_benchmark_result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--frames',type=int,default=180);a=p.parse_args()
    if not 30<=a.frames<=600:raise ValueError('frames must be 30..600')
    print(json.dumps(run(a.frames),ensure_ascii=False,indent=2))
