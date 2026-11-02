"""CPU-only AI child. Stage traces go to stderr; the response is one stdout JSON."""
from pathlib import Path
import hashlib,json,os,platform,struct,sys,time
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT=Path(__file__).resolve().parent
START=time.perf_counter()


def trace(stage,**detail):
    value=dict(stage=stage,elapsed_ms=(time.perf_counter()-START)*1000.,**detail)
    print('P11_AI_STAGE '+json.dumps(value,allow_nan=False),file=sys.stderr,flush=True)


class NoPlaneFound(ValueError):pass


def validate_manifest():
    trace('check_assets')
    manifest=json.loads((ROOT/'v98_ai_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('release_id')!=RELEASE_ID or manifest.get('format')!=1:
        raise ValueError('AI manifest version mismatch')
    if (platform.machine()!='armv7l' or struct.calcsize('P')!=4 or sys.version_info[:2]!=(3,10)):
        raise RuntimeError('AI runtime requires the tested ARMv7 Python 3.10 board')
    for name,digest in manifest['sha256'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or not name.startswith('ai/'):
            raise ValueError('Unsafe AI asset path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('AI asset integrity mismatch: '+name)
    trace('assets_ready',files=len(manifest['sha256']))
    return manifest


def infer(header,data,manifest):
    sys.path.insert(0,str(ROOT/'ai'/'runtime'))
    trace('import_numpy')
    import numpy as np
    trace('import_cv2')
    import cv2
    trace('import_ncnn')
    import ncnn
    trace('import_geometry')
    from v98_ai_geometry import quad_from_mask,POSTPROCESS_VERSION
    cv2.setNumThreads(1)
    bgr=np.frombuffer(data,np.uint8).reshape(header['shape'])
    prep=manifest['preprocessing'];width=prep['width'];height=prep['height']
    trace('preprocess')
    rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
    small=cv2.resize(rgb,(width,height),interpolation=cv2.INTER_AREA)
    mean=np.array(prep['mean'],np.float32).reshape(1,1,3)
    std=np.array(prep['std'],np.float32).reshape(1,1,3)
    x=np.ascontiguousarray(((small.astype(np.float32)/255.-mean)/std).transpose(2,0,1))
    threads=header.get('threads',1)
    if type(threads) is not int or threads not in (1,2):raise ValueError('Invalid AI thread count')
    net=ncnn.Net();net.opt.use_vulkan_compute=False;net.opt.num_threads=threads
    net.opt.use_fp16_packed=False;net.opt.use_fp16_storage=False;net.opt.use_fp16_arithmetic=False
    net.opt.use_bf16_storage=False;net.opt.use_winograd_convolution=False
    try:
        trace('load_parameters')
        if net.load_param(str(ROOT/'ai'/'plane.ncnn.param'))!=0:raise RuntimeError('AI parameter load failed')
        trace('load_weights')
        if net.load_model(str(ROOT/'ai'/'plane.ncnn.bin'))!=0:raise RuntimeError('AI weights load failed')
        trace('inference',threads=threads)
        with net.create_extractor() as ex:
            if ex.input('in0',ncnn.Mat(x).clone())!=0:raise RuntimeError('AI input failed')
            rc,value=ex.extract('out0')
            if rc!=0:raise RuntimeError('AI output failed')
            logits=np.asarray(value).copy().reshape(height,width)
        if not np.isfinite(logits).all():raise ValueError('Non-finite AI output')
        trace('fit_corners')
        quad,fit=quad_from_mask(logits>0)
        if quad is None:raise NoPlaneFound('No usable plane found in this frame')
        quad=quad*np.array([bgr.shape[1]/width,bgr.shape[0]/height],np.float32)
        return dict(status='candidate',quad=quad.tolist(),mask_fit_iou=float(fit),
            postprocess=POSTPROCESS_VERSION,model_sha256=manifest['sha256']['ai/plane.ncnn.bin'])
    finally:net.clear()


def main():
    started=time.perf_counter();stream=sys.stdin.buffer
    trace('read_input',interpreter=sys.executable,machine=platform.machine())
    line=stream.readline(4097)
    if len(line)>4096 or not line.endswith(b'\n'):raise ValueError('Invalid AI header')
    header=json.loads(line)
    if (header.get('release_id')!=RELEASE_ID or header.get('shape')!=[480,640,3]
            or header.get('dtype')!='uint8'):raise ValueError('Invalid AI source format')
    receipt={key:header[key] for key in ('release_id','generation','token','sequence','request_id')}
    data=stream.read(480*640*3)
    if len(data)!=480*640*3 or stream.read(1):raise ValueError('Invalid AI source size')
    digest=hashlib.sha256(data).hexdigest()
    if digest!=header.get('source_sha256'):raise ValueError('AI source hash mismatch')
    memory={}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key,value=line.split(':',1)
            if key in ('MemAvailable','SwapFree','SwapTotal'):memory[key]=value.strip()
    except (OSError,ValueError):pass
    trace('input_ready',bytes=len(data),memory=memory)
    try:value=infer(header,data,validate_manifest())
    except NoPlaneFound as exc:value=dict(status='failed',failure_kind='no_plane',error=str(exc))
    except Exception as exc:value=dict(status='failed',failure_kind='runtime_error',error=str(exc)[:1000])
    trace('result_ready',status=value['status'],failure_kind=value.get('failure_kind'))
    value.update(receipt,source_sha256=digest,worker_ms=(time.perf_counter()-started)*1000.)
    print(json.dumps(value,allow_nan=False),flush=True)


if __name__=='__main__':main()
