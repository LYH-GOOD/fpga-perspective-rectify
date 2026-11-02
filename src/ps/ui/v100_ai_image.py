"""Click-only preprocessing/postprocessing; ncnn stays outside the UI process."""
from pathlib import Path
import hashlib,json
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
ROOT=Path(__file__).resolve().parent
PREPROCESS_VERSION='rgb-area-imagenet-chw-f32-v1'


def prepare(source,receipt):
    #   ⭐ 2026-10-27：原来写死 640x480。换 800x600 摄像头时这里会直接抛，
    #      整个 AI 通路失效。模型输入本来就是 resize 到 256x192，
    #      所以这里只校验【类型/通道/只读】，尺寸交给 resize。
    if (source.dtype!=np.uint8 or source.ndim!=3 or source.shape[2]!=3
            or source.flags.writeable or min(source.shape[:2])<8):
        raise ValueError('AI requires an immutable HxWx3 uint8 BGR snapshot')
    manifest=json.loads((ROOT/'v98_ai_manifest.json').read_text(encoding='utf-8'))
    p=manifest['preprocessing'];w,h=p['width'],p['height']
    rgb=cv2.cvtColor(source,cv2.COLOR_BGR2RGB)
    small=cv2.resize(rgb,(w,h),interpolation=cv2.INTER_AREA)
    mean=np.asarray(p['mean'],np.float32).reshape(1,1,3)
    std=np.asarray(p['std'],np.float32).reshape(1,1,3)
    x=np.ascontiguousarray(((small.astype(np.float32)/255.-mean)/std).transpose(2,0,1),dtype='<f4')
    data=x.tobytes()
    header=dict(receipt,type='infer',shape=[3,h,w],dtype='float32-le',
        preprocessing=PREPROCESS_VERSION,source_shape=list(source.shape),
        source_sha256=hashlib.sha256(source.tobytes()).hexdigest(),tensor_sha256=hashlib.sha256(data).hexdigest())
    return header,data


def finish(result,payload,header,selection_context=None,source=None):
    from v98_ai_geometry import quad_from_mask
    if any(result.get(k)!=header[k] for k in ('source_sha256','tensor_sha256','preprocessing')):
        raise ValueError('AI image/tensor receipt mismatch')
    if result.get('status')!='mask':
        if payload:raise ValueError('Unexpected image payload for failed inference')
        return result
    if (result.get('shape')!=[192,256] or result.get('dtype')!='uint8'
            or len(payload)!=192*256 or hashlib.sha256(payload).hexdigest()!=result.get('mask_sha256')):
        raise ValueError('AI mask format/hash mismatch')
    mask=np.frombuffer(payload,np.uint8).reshape(192,256)
    if not np.isin(mask,(0,1)).all():raise ValueError('AI mask must be binary')
    from v121_selection import select_mask
    quad,fit,selection_detail=select_mask(mask!=0,selection_context,source)
    if quad is None:
        ambiguous=selection_detail.get('reason') in ('multiple_targets','merged_targets','merged_edges_unproved')
        return dict(result,status='failed',failure_kind='ambiguous_target' if ambiguous else 'no_plane',
            error='目标未分清，请点书中心或拉开两本书' if ambiguous else ('点击位置未找到完整目标，请重新点选' if selection_context is not None else '未找到完整目标'),selection_detail=selection_detail)
    #   ⭐ 同样不能写死 640x480：从 header 里的真实源尺寸换算回像素坐标。
    sh=header.get('source_shape') or [480,640,3]
    quad*=np.array([float(sh[1])/256.,float(sh[0])/192.],np.float32)
    answer=dict(result,status='candidate',quad=quad.tolist(),mask_fit_iou=float(fit),selection_detail=selection_detail)
    if selection_context is not None:
        from v121_selection import proof
        answer['target_selection_proof']=proof(selection_context,selection_context['point'],header['sequence'],
            selection_context.get('mapping','mapped'),selection_method=selection_detail['reason'],component=selection_detail.get('component'),
            candidate_count=selection_detail.get('candidate_count',1),current_aligned=False)
    return answer
