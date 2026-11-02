"""Bounded split search with a per-photo coordinate atlas; hardware ABI9.

Atlas values rank candidates only. make_tile remains the authority for crop,
quantization, the 0.65-source-pixel guard and the exact PL suffix-row proof.
"""
from pathlib import Path
import hashlib,time
import cv2
import numpy as np
from p11_contract import RELEASE_ID
from v8_geometry import map_points,make_tile,TileGeometryError,GeometryPlanFallback
from v8_surface import NY,NX
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def plan_tiles_fast(model,image_shape,tile_size=1280,max_tiles=512,validator=None):
    if not 64<=tile_size<=1280:raise ValueError('tile_size须为64..1280')
    if validator is None:raise RuntimeError('需要PL精确规划器，不能用坐标预览认证行缓存安全')
    budget=48;hints={};atlas=None;atlas_attempted=False
    reasons={};events=[];fallback=None
    counters=dict(full_validation_attempts=0,predictive_splits=0,hint_evaluations=0,
        hint_s=0.,full_validation_s=0.,atlas_build_s=0.,atlas_builds=0,
        hint_batches=0,direct_hint_fallbacks=0,direct_prediction_evaluations=0,split_candidates=0,
        early_axis_accepts=0,hint_budget_exhaustions=0)
    wo,ho=model['width'],model['height'];ih,iw=image_shape[:2]

    def ensure_atlas():
        nonlocal atlas,atlas_attempted
        if atlas_attempted:return
        atlas_attempted=True;t=time.perf_counter();counters['atlas_builds']+=1
        try:
            # At most 129x129x2 float32, about 130KB. Never a full-image map.
            aw=min(129,max(17,(wo-1+15)//16+1))
            ah=min(129,max(17,(ho-1+15)//16+1))
            u,v=np.meshgrid(np.linspace(0,wo-1,aw),np.linspace(0,ho-1,ah))
            x,y=map_points(model,u,v)
            if np.all(np.isfinite(x)) and np.all(np.isfinite(y)):
                atlas=np.stack((x,y),axis=-1).astype(np.float32)
        except (ValueError,OverflowError,FloatingPointError):
            atlas=None
        finally:counters['atlas_build_s']+=time.perf_counter()-t

    def summarize(box,xx,yy):
        if not np.all(np.isfinite(xx)) or not np.all(np.isfinite(yy)):return None
        left=max(0,min(iw-2,int(np.floor(xx.min()))-3))
        right=min(iw,max(left+2,int(np.ceil(xx.max()))+4))
        top=max(0,min(ih-2,int(np.floor(yy.min()))-3))
        bottom=min(ih,max(top+2,int(np.ceil(yy.max()))+4))
        wi,hi=right-left,bottom-top
        #   ⚠️ 2026-10-27（800x600 实测）：这里原来是写死的
        #      `512 if wi<=320 else 256 if wi<=640 else 128`。
        #      硬件已经改成 ROWS=384，但 256 这一档没跟着改 —— 于是 crop 宽 306~404
        #      （落在 321..640 档）时预算被压到 256，而 peak_rows 实测 223~314，
        #      **每帧都被切成 2 块**，帧率从 15 掉到 1.5~3.5 fps。
        #      ⇒ 统一用硬件真实容量 `LINE_BUF_ROWS`；真正的安全仍由
        #        `peak_rows` 的 PL 证明把关（见 make_tile / validator）。
        from p11_contract import LINE_BUF_ROWS as _LBR
        rows=_LBR if wi<=640 else 128
        low=np.clip(np.floor(yy.min(axis=1)),0,ih-2)
        high=np.clip(np.floor(yy.max(axis=1)),0,ih-2)+1
        future=np.minimum.accumulate(low[::-1])[::-1]
        peak=float(np.max(high-future+1))+4
        single=float(np.max(high-low+1))+4
        axis='x' if single>rows else 'y'
        if wi>512 or hi>1280:axis='x' if wi>=hi else 'y'
        return dict(width=wi,height=hi,rows=rows,peak=peak,axis=axis,
            overload=max(wi/512.,hi/1280.,peak/rows),traffic=wi*hi,crop=(left,top,right,bottom),
            obvious=(wi>1296 or hi>1296 or peak>rows*1.18+8))

    def hint_many(boxes,direct=False):
        missing=list(dict.fromkeys(tuple(b) for b in boxes if tuple(b) not in hints))
        remaining=max(0,budget-counters['hint_evaluations'])
        if len(missing)>remaining:counters['hint_budget_exhaustions']+=1
        missing=missing[:remaining]
        if missing:
            started=time.perf_counter()
            counters['hint_evaluations']+=len(missing);counters['hint_batches']+=1
            try:
                if not direct:ensure_atlas()
                if atlas is not None and not direct:
                    # Batch all siblings/cuts into a single small native remap.
                    uu=[];vv=[]
                    for x0,y0,x1,y1 in missing:
                        u,v=np.meshgrid(np.linspace(x0,x1-1,9),np.linspace(y0,y1-1,17))
                        uu.append(u);vv.append(v)
                    mx=(np.concatenate(uu,axis=1)*(atlas.shape[1]-1)/(wo-1)).astype(np.float32)
                    my=(np.concatenate(vv,axis=1)*(atlas.shape[0]-1)/(ho-1)).astype(np.float32)
                    samples=cv2.remap(atlas,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
                    for i,box in enumerate(missing):
                        sample=samples[:,i*9:(i+1)*9]
                        hints[box]=summarize(box,sample[:,:,0],sample[:,:,1])
                else:
                    for box in missing:
                        counters['direct_prediction_evaluations' if direct else 'direct_hint_fallbacks']+=1
                        x0,y0,x1,y1=box
                        try:
                            u,v=np.meshgrid(np.linspace(x0,x1-1,9),np.linspace(y0,y1-1,17))
                            x,y=map_points(model,u,v);hints[box]=summarize(box,x,y)
                        except (ValueError,OverflowError,FloatingPointError):hints[box]=None
            finally:counters['hint_s']+=time.perf_counter()-started
        return [hints.get(tuple(box)) for box in boxes]

    def children(box,axis,cut):
        x0,y0,x1,y1=box
        if axis=='x':return (x0,y0,cut,y1),(cut,y0,x1,y1)
        return (x0,y0,x1,cut),(x0,cut,x1,y1)

    def choose_split(box,preferred,depth):
        x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
        if (preferred=='x' and w<4) or (preferred=='y' and h<4):
            preferred='y' if preferred=='x' else 'x'
        start,size=(x0,w) if preferred=='x' else (y0,h)
        selected=(preferred,start+size//2)
        if depth>=5 or counters['hint_evaluations']>=budget:return selected
        parent=hint_many([box])[0];best=None
        # Search two cuts on the indicated axis. Only inspect the other axis
        # when neither indicated-axis pair looks feasible. These are hints.
        for axis in (preferred,'y' if preferred=='x' else 'x'):
            start,size=(x0,w) if axis=='x' else (y0,h)
            if size<128:continue
            fractions=[.5]
            if parent is not None:
                boundary=(640 if parent['width']>640 else 320) if axis=='x' else 1280
                extent=parent['width'] if axis=='x' else parent['height']
                fraction=(boundary-12)/max(extent,1)
                if .25<fraction<.75:fractions.append(fraction)
            if len(fractions)==1:fractions.append(.375)
            candidates=[];boxes=[];seen=set()
            for fraction in fractions:
                cut=start+int(round(size*fraction))
                if cut in seen or min(cut-start,start+size-cut)<64:continue
                seen.add(cut);a,b=children(box,axis,cut)
                candidates.append((axis,cut,fraction));boxes.extend((a,b))
            predictions=hint_many(boxes);axis_fits=False;axis_overlap=1.
            counters['split_candidates']+=len(candidates)
            for i,(candidate_axis,cut,fraction) in enumerate(candidates):
                ha,hb=predictions[2*i:2*i+2]
                if ha is None or hb is None:continue
                overloads=(ha['overload'],hb['overload'])
                failed=sum(o>1 for o in overloads)
                ca,cb=ha['crop'],hb['crop']
                overlap=max(0,min(ca[2],cb[2])-max(ca[0],cb[0]))*max(0,min(ca[3],cb[3])-max(ca[1],cb[1]))
                traffic=ha['traffic']+hb['traffic']
                axis_overlap=min(axis_overlap,overlap/max(1,traffic))
                score=(failed,sum(max(0,o-1) for o in overloads),
                       (traffic+.5*overlap)/(w*h)+.05*abs(fraction-.5))
                if best is None or score<best:best=score;selected=(candidate_axis,cut)
                axis_fits|=failed==0
            if axis_fits and axis_overlap<=.12:
                if axis==preferred:counters['early_axis_accepts']+=1
                break
        return selected

    def plan_once():
        plans=[]
        def split(box,depth=0):
            x0,y0,x1,y1=box;w,h=x1-x0,y1-y0
            # Do not build an atlas for the common one-tile case. Its first
            # direct hint costs the same as v11; build only when cuts are needed.
            prediction=hint_many([box],direct=atlas is None)[0] if depth<3 and min(w,h)>=128 else None
            predicted=(prediction is not None and prediction['obvious'] and counters['predictive_splits']<8)
            if predicted:
                counters['predictive_splits']+=1
                error=None;reason='共享坐标预览预测超限，提前切分（不是安全证明）'
                preferred=prediction['axis']
            else:
                started=time.perf_counter();counters['full_validation_attempts']+=1
                try:tile=make_tile(model,box,image_shape,validator)
                except (ValueError,cv2.error) as e:
                    error=e;reason=str(e);preferred=getattr(e,'split_axis','x' if w>=h else 'y')
                else:
                    plans.append(tile)
                    if len(plans)>max_tiles:raise ValueError('分块数超过上限，请设置较小max_dim')
                    return
                finally:counters['full_validation_s']+=time.perf_counter()-started
            reasons[reason]=reasons.get(reason,0)+1
            if isinstance(error,TileGeometryError) and min(w,h)<=128:
                raise GeometryPlanFallback(reason+'；停止把局部曲率误差细分成微小块') from error
            if depth>=14 or max(w,h)<4:raise ValueError('无法安全分块: '+reason) from error
            axis,cut=choose_split(box,preferred,depth)
            events.append(dict(box=list(box),reason=reason,depth=depth,split_axis=axis,
                               split_coordinate=cut,predictive=bool(predicted)))
            a,b=children(box,axis,cut);split(a,depth+1);split(b,depth+1)
        xs=np.linspace(0,wo,int(np.ceil(wo/tile_size))+1).astype(int)
        ys=np.linspace(0,ho,int(np.ceil(ho/tile_size))+1).astype(int)
        for ya,yb in zip(ys[:-1],ys[1:]):
            for xa,xb in zip(xs[:-1],xs[1:]):split((int(xa),int(ya),int(xb),int(yb)))
        return plans

    try:plans=plan_once()
    except GeometryPlanFallback as e:
        if not (np.any(model['bend_x']) or np.any(model['bend_y'])):raise
        fallback=str(e);hints.clear();atlas=None;atlas_attempted=False
        # All model-dependent hint data is discarded before the retry.
        model['bend_x']=np.zeros((NY,NX));model['bend_y']=np.zeros((NY,NX))
        model['mesh_x']=np.zeros((33,33));model['mesh_y']=np.zeros((33,33))
        model['dewarp'].update(state='perspective_fallback',strength=0.,fallback_reason=fallback)
        plans=plan_once()
    model['plan_stats']=dict(initial_tile_size=tile_size,tile_count=len(plans),planner='adaptive',
        search_backend='v14_shared_atlas_overlap_cost',hint_source='interpolated_preview_only',
        atlas_shape=None if atlas is None else list(atlas.shape[:2]),
        min_tile_width=min(p['width'] for p in plans),min_tile_height=min(p['height'] for p in plans),
        split_reason_counts=reasons,split_events=events,geometry_fallback=fallback,
        geometry_guard_sample_step=16,geometry_guard_threshold=.65,hint_budget=budget,
        max_cut_candidates_per_split=4,
        timing_note='atlas_build_s is included in hint_s; full_validation_s includes nested lighting/control work',
        **counters)
    return plans
