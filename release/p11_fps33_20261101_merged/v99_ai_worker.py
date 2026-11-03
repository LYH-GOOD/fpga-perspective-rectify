"""Lean resident inference only: no OpenCV, geometry, camera or FPGA imports."""
# ⚠️ 本文件由 build/make_ai_entries.py 生成，不要直接编辑。
#    源头：src/ps/ui/v99_ai_worker.py（+ src/ps/ui/v99_ai_protocol.py）
#    改动请改源头，然后重跑 `python build/make_ai_entries.py <输出目录>`。
from pathlib import Path
import argparse,hashlib,json,os,platform,socket,struct,sys,time
# ---- 与发布清单同源：子进程不导入 core（core 顶层 import cv2/numpy）----
def _release_id():
    """版本号从 release_manifest.json 读，和 p11_contract.RELEASE_ID 是同一份底本。"""
    return json.loads((Path(__file__).resolve().parent / 'release_manifest.json')
                      .read_text(encoding='utf-8'))['release_id']
RELEASE_ID = _release_id()
# ---- 以下 6 条来自 v99_ai_protocol.py，按原文本内联（本文件要能单独跑）----
MAX_HEADER=16384


FRAME_BYTES=480*640*3


def connect_address(address):
    if address.startswith('tcp:'):
        host,port=address[4:].rsplit(':',1)
        if host!='127.0.0.1':raise ValueError('AI TCP fallback is loopback only')
        connection=socket.socket(socket.AF_INET,socket.SOCK_STREAM);target=(host,int(port))
    else:
        connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);target=address
    try:
        connection.settimeout(10.);connection.connect(target);connection.settimeout(None)
        return connection
    except BaseException:connection.close();raise


def recv_exact(sock,count):
    result=bytearray(count);view=memoryview(result);offset=0
    while offset<count:
        used=sock.recv_into(view[offset:],count-offset)
        if not used:raise EOFError('AI connection closed during a message')
        offset+=used
    return bytes(result)


def send_message(sock,metadata,payload=b''):
    if len(payload)>FRAME_BYTES:raise ValueError('AI payload too large')
    value=dict(metadata,payload_bytes=len(payload))
    header=json.dumps(value,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(header)>MAX_HEADER:raise ValueError('AI header too large')
    sock.sendall(struct.pack('!I',len(header))+header)
    if payload:sock.sendall(payload)


def recv_message(sock):
    length=struct.unpack('!I',recv_exact(sock,4))[0]
    if not 1<=length<=MAX_HEADER:raise ValueError('Invalid AI header size')
    value=json.loads(recv_exact(sock,length))
    if not isinstance(value,dict):raise ValueError('AI metadata must be an object')
    count=value.pop('payload_bytes',0)
    if type(count) is not int or not 0<=count<=FRAME_BYTES:raise ValueError('Invalid AI payload size')
    return value,recv_exact(sock,count) if count else b''
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT=Path(__file__).resolve().parent
PREPROCESS_VERSION='rgb-area-imagenet-chw-f32-v1'


def memory_info():
    result={}
    for name,fields in [('/proc/self/status',('VmRSS','VmHWM','VmSwap','Threads')),
        ('/proc/self/smaps_rollup',('Pss',)),('/proc/meminfo',('MemAvailable','CmaFree','CmaTotal','SwapFree'))]:
        try:
            for line in Path(name).read_text().splitlines():
                if ':' not in line:continue
                key,value=line.split(':',1)
                if key in fields:result[key]=int(value.split()[0])
        except (OSError,ValueError):pass
    return result


def validate_assets():
    manifest=json.loads((ROOT/'v98_ai_manifest.json').read_text(encoding='utf-8'))
    if manifest.get('release_id')!=RELEASE_ID or manifest.get('format')!=1:raise ValueError('AI manifest version mismatch')
    if platform.machine()!='armv7l' or struct.calcsize('P')!=4 or sys.version_info[:2]!=(3,10):
        raise RuntimeError('AI runtime requires the tested ARMv7 Python 3.10 board')
    for name,digest in manifest['sha256'].items():
        path=(ROOT/name).resolve()
        if not name.startswith('ai/') or not path.is_relative_to(ROOT):raise ValueError('Unsafe AI resource path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('AI asset integrity mismatch: '+name)
    return manifest


class Model:
    def __init__(self,stage):
        stage('check_assets');self.manifest=validate_assets()
        sys.path.insert(0,str(ROOT/'ai/runtime'))
        stage('import_numpy');import numpy as np
        stage('import_ncnn');import ncnn
        self.np=np;self.ncnn=ncnn
        self.width=self.manifest['preprocessing']['width'];self.height=self.manifest['preprocessing']['height']
        self.threads=int(os.environ.get('P11_AI_THREADS','1'))
        if self.threads not in (1,2):raise ValueError('P11_AI_THREADS must be 1 or 2')
        self.net=ncnn.Net();self.net.opt.use_vulkan_compute=False;self.net.opt.num_threads=self.threads
        self.net.opt.use_fp16_packed=False;self.net.opt.use_fp16_storage=False;self.net.opt.use_fp16_arithmetic=False
        self.net.opt.use_bf16_storage=False;self.net.opt.use_winograd_convolution=False
        try:
            stage('load_parameters')
            if self.net.load_param(str(ROOT/'ai/plane.ncnn.param'))!=0:raise RuntimeError('AI parameter load failed')
            stage('load_weights')
            if self.net.load_model(str(ROOT/'ai/plane.ncnn.bin'))!=0:raise RuntimeError('AI weights load failed')
            stage('warmup');self.forward(np.zeros((3,self.height,self.width),np.float32))
        except BaseException:self.net.clear();raise

    def forward(self,x):
        with self.net.create_extractor() as ex:
            if ex.input('in0',self.ncnn.Mat(x).clone())!=0:raise RuntimeError('AI input failed')
            code,value=ex.extract('out0')
            if code!=0:raise RuntimeError('AI output failed')
            return self.np.asarray(value).copy().reshape(self.height,self.width)

    def infer(self,header,payload,stage):
        np=self.np
        #   ⚠️ 2026-10-28：`source_shape` 原来写死 [480,640,3]。
        #      换成 800x600 摄像头后父进程送来 [600,800,3] ⇒ 这里抛
        #      "Invalid AI tensor format"，**AI 通路整条失效**（现场 9 次全失败）。
        #      模型张量本来就是 resize 到 (3,h,w)，源图多大都不影响，
        #      所以只校验"是 3 通道、尺寸合理"，不校验具体分辨率。
        _src=header.get('source_shape') or []
        if (header.get('release_id')!=RELEASE_ID or header.get('shape')!=[3,self.height,self.width]
            or (len(_src)!=3 or _src[2]!=3 or not (16<=int(_src[0])<=2160) or not (16<=int(_src[1])<=3840))
            or header.get('dtype')!='float32-le'
            or header.get('preprocessing')!=PREPROCESS_VERSION or len(payload)!=3*self.height*self.width*4):
            raise ValueError('Invalid AI tensor format')
        if hashlib.sha256(payload).hexdigest()!=header.get('tensor_sha256'):raise ValueError('AI tensor hash mismatch')
        x=np.frombuffer(payload,dtype='<f4').reshape(3,self.height,self.width)
        if not np.isfinite(x).all():raise ValueError('Non-finite AI input')
        stage('inference');logits=self.forward(x)
        if not np.isfinite(logits).all():raise ValueError('Non-finite AI output')
        mask=np.ascontiguousarray(logits>0,np.uint8).tobytes()
        return dict(status='mask',shape=[self.height,self.width],dtype='uint8',
            mask_sha256=hashlib.sha256(mask).hexdigest(),model_sha256=self.manifest['sha256']['ai/plane.ncnn.bin']),mask

    def close(self):self.net.clear()


def serve(connection,nonce):
    start=time.perf_counter();model=None
    def stage(name):send_message(connection,dict(type='stage',stage=name,elapsed_ms=(time.perf_counter()-start)*1000.))
    send_message(connection,dict(type='hello',release_id=RELEASE_ID,nonce=nonce,pid=os.getpid(),
        interpreter=sys.executable,machine=platform.machine(),python=list(sys.version_info[:3])))
    try:
        model=Model(stage)
        send_message(connection,dict(type='ready',release_id=RELEASE_ID,pid=os.getpid(),memory=memory_info(),
            model_sha256=model.manifest['sha256']['ai/plane.ncnn.bin'],initialization_ms=(time.perf_counter()-start)*1000.,
            ncnn_version=model.ncnn.__version__,numpy_version=model.np.__version__,threads=model.threads,
            opencv_imported='cv2' in sys.modules,preprocessing=PREPROCESS_VERSION))
        while True:
            connection.settimeout(None)
            header,payload=recv_message(connection)
            if header.get('type')=='stop':return
            if header.get('type')!='infer':raise ValueError('Unknown AI command')
            start=time.perf_counter()
            receipt={k:header[k] for k in ('release_id','generation','token','sequence','request_id',
                'source_sha256','tensor_sha256','preprocessing')}
            try:result,mask=model.infer(header,payload,stage)
            except Exception as exc:result=dict(status='failed',failure_kind='runtime_error',error=str(exc)[:1000]);mask=b''
            payload=b''
            result.update(receipt,type='result',worker_ms=(time.perf_counter()-start)*1000.,memory=memory_info(),pid=os.getpid())
            send_message(connection,result,mask);mask=b'';result=None;header=None
    except EOFError:return
    except Exception as exc:
        try:send_message(connection,dict(type='error',error=str(exc)[:1200],failure_kind='runtime_error'))
        except OSError:pass
    finally:
        if model is not None:model.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--socket',required=True);p.add_argument('--nonce',required=True)
    args=p.parse_args()
    with connect_address(args.socket) as connection:serve(connection,args.nonce)


if __name__=='__main__':main()
