"""Explicit board-only small-image diagnostic. Stop the UI before --board.

This loads the supplied overlay and exercises remap/DMA/sharp without camera or
HDMI scanout. It is NOT a camera/display FPS benchmark or bitstream provenance proof.
"""
from pathlib import Path
import json,sys,time
import numpy as np
from p11_contract import RELEASE_ID

def reference(image,level):
    """Independent 5x5 replicated-border box-unsharp, generated-IP Q8 arithmetic."""
    rgb=image[:,:,:3].astype(np.int64)
    padded=np.pad(rgb,((2,2),(2,2),(0,0)),mode='edge')
    total=np.zeros_like(rgb)
    for y in range(5):
        for x in range(5):total+=padded[y:y+rgb.shape[0],x:x+rgb.shape[1]]
    mean_q8=(total*(65536//25))>>8
    a8=int(level*256.+.5)
    return np.clip(rgb+(((rgb<<8)-mean_q8)*a8>>16),0,255).astype(np.uint8)

def run():
    from v64_p1_backend import P1Backend,make_plan
    from v64_camera_hdmi import FrameJob
    from v79_acquire import OwnedFrame
    from v31_pixels import color_mode
    from run_logging import checkpoint
    root=Path(__file__).resolve().parent;backend=None;checks=[]
    # YUYV input means the diagnostic covers the actual default PL colour path.
    raw=np.empty((64,64,2),np.uint8);yy,xx=np.indices(raw.shape[:2])
    raw[:,:,0]=np.where((xx//7+yy//6)%2==0,74,176).astype(np.uint8);raw[:,:,1]=128
    quad=np.array([[8,8],[55,8],[55,55],[8,55]],np.float32)
    tiles,proof=make_plan(quad,raw.shape,(48,48));assert len(tiles)==1
    def execute(index,tenths):
        backend.sharp_control.request(tenths)
        lease=OwnedFrame(raw.copy(),time.perf_counter(),index,time.perf_counter())
        job=FrameJob(index,lease,tiles,(48,48),'CURRENT',tuple(map(tuple,quad)),int(color_mode()),None,{})
        out,timing=backend.execute(job)
        return out.copy(),timing['sharp_receipt']
    try:
        backend=P1Backend(str(root/'system.bit'),input_shape=(64,64),output_size=(48,48))
        plain,receipt=execute(0,0);assert not receipt['enabled']
        for index,level in enumerate([1.,1.5,4.],1):
            actual,receipt=execute(index,int(level*10));expected=reference(plain,level)
            # Interior exact comparison separately avoids assuming a border
            # policy from the loose, nonmatching memory-mapped HLS source.
            delta=np.abs(actual[3:-3,3:-3,:3].astype(np.int16)-expected[3:-3,3:-3].astype(np.int16))
            result=dict(level=level,interior_max_error=int(delta.max()),interior_mismatches=int(np.count_nonzero(delta)),enabled=receipt['enabled'])
            checks.append(result)
            if not receipt['enabled'] or result['interior_mismatches']:
                np.savez(root/'sharp23_board_mismatch.npz',plain=plain,actual=actual,expected=expected)
                raise AssertionError('PL sharp numeric mismatch '+str(result))
        after,receipt=execute(4,0)
        assert not receipt['enabled'] and np.array_equal(after,plain),'Bypass output differs after disabling sharp'
        result=dict(passed=True,release_id=RELEASE_ID,checks=checks,bypass_round_trip=True,board_kernel_exercised=True,
            exact_border_policy_verified=False,multi_tile_enabled=False,camera_or_display_FPS_tested=False)
        checkpoint('SHARP_BOARD_CHECK_PASSED',**result)
        return result
    finally:
        if backend is not None:backend.close()

if __name__=='__main__':
    if sys.argv[1:]!=['--board']:raise SystemExit('Board diagnostic: stop UI, then run python3 sharp23_board_check.py --board as root.')
    root=Path(__file__).resolve().parent
    try:result=run()
    except BaseException as exc:
        result=dict(passed=False,release_id=RELEASE_ID,error=repr(exc),board_FPS_tested=False)
        (root/'sharp23_board_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');raise
    (root/'sharp23_board_check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
