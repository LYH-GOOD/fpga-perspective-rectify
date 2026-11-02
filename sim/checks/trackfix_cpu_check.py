"""Optional CPU check and same-input timing; no camera, HDMI, overlay or DMA."""
from pathlib import Path
import hashlib,importlib.util,json,platform,time,types
import cv2,numpy as np
from p11_contract import RELEASE_ID
from v104_physical_tracking import PhysicalTracker
from v105_native import prepare_edges

ROOT=Path(__file__).resolve().parent
Q=np.array([[130,95],[495,105],[515,370],[110,360]],np.float32)
def scene(q,seed,bg=160):
    im=np.full((480,640,3),bg,np.uint8);cv2.fillConvexPoly(im,np.rint(q).astype(np.int32),(20,20,20))
    inner=q.mean(0)+(q-q.mean(0))*.86;mask=np.zeros(im.shape[:2],np.uint8)
    cv2.fillConvexPoly(mask,np.rint(inner).astype(np.int32),255)
    video=np.random.default_rng(seed).integers(0,255,im.shape,dtype=np.uint8);im[mask>0]=video[mask>0]
    return im
def frame(im,i):return types.SimpleNamespace(image=im,sequence=i,ready=100.+i/30.)
def run():
    cv2.setNumThreads(1)
    if prepare_edges() is None:raise RuntimeError('原生边缘模块不可用：请检查安装日志和板端 g++；本次不能确认性能。')
    for bg in (0,160):
        tracker=PhysicalTracker(frame(scene(Q,0,bg),0),Q)
        try:
            for i in range(1,15):
                gt=Q+[i,0];q,detail=tracker.update(frame(scene(gt,i,bg),i))
                if q is None or np.max(np.linalg.norm(q-gt,axis=1))>3:raise AssertionError(detail)
        finally:tracker.close()
    spec=importlib.util.spec_from_file_location('baseline_physical4',ROOT/'trackfix_baseline_physical4.py')
    baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
    images=[frame(scene(Q+[i*.5,i*.12],i),i) for i in range(60)];timing={}
    for name,cls in [('physical4',baseline.PhysicalTracker),('trackfix5',PhysicalTracker)]:
        tracker=cls(images[0],Q);values=[];correct=0
        try:
            for i,f in enumerate(images[1:],1):
                start=time.perf_counter();q,d=tracker.update(f);elapsed=time.perf_counter()-start
                if i>5:values.append(elapsed*1000)
                correct+=q is not None
        finally:tracker.close()
        timing[name]=dict(current=correct,total=59,median_ms=float(np.median(values)),p95_ms=float(np.percentile(values,95)))
    report=dict(release_id=RELEASE_ID,passed=True,platform=platform.platform(),machine=platform.machine(),
        native_executed=True,native_arm_executed=platform.machine().startswith(('arm','aarch')),
        native_source_sha256=hashlib.sha256((ROOT/'v105_edges.cpp').read_bytes()).hexdigest(),
        timing=timing,real_camera_fps_measured=False,
        scope='CPU recorded/synthetic input only; actual output FPS requires live board run-result.log')
    (ROOT/'trackfix_cpu_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return report
if __name__=='__main__':run()
