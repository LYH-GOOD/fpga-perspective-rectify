"""Exact V87 manual FB tracker. Failure policy lives in the current controller."""
from pathlib import Path
import hashlib,os,time
import cv2,numpy as np
from p11_contract import RELEASE_ID
from run_logging import checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

#   ⭐ 2026-10-26：手动模式的【静止门控】。
#   动机（run-result(18) 实测）：手动跟踪帧 `capture→output` **114.9 ms**，其中
#   `tracker_s` **66.8 ms**（双向金字塔 LK 3 层×20 迭代 + RANSAC 300 次），
#   而 PL 的 `dma_wait` 只有 9.8 ms ⇒ 慢 100% 在 PS 跟踪，且**纸完全不动也照跑**。
#   自动模式早有等价机制（`v87_v74_tracking._static_hold`），这里按同样口径补一份。
#
#   ⚠️ **为什么"跳过"也必须刷新锚点**：`update()` 开头有
#        if not self.first and not 0<elapsed<=.75: raise ValueError('expired_anchor')
#      跳过时若不更新 `previous_ready` / `self.gray`，超过 0.75 s 后恢复会直接失败。
#   ⚠️ **为什么要设最长保持时间**：门控可能判错（如光照突变但画面没动），
#      超过 `MAX_S` 强制做一次真实跟踪，作为兜底。
#   ⚠️ 开关：`P11_MANUAL_STATIC_HOLD=0` 可完全关闭，回到改动前行为。
#
#   ===== rev2（2026-10-26，run-result(92) 实测推翻 rev1）=====
#   rev1 用**固定阈值 4.0(进) / 8.0(出)** 直接照抄自动模式的数字 —— 这是错的。
#   自动模式那 4.0/8.0 是【乘了自适应噪声底】之后的**下限**：
#        limit = max(enter, enter_gain * floor)
#   而 rev1 少了 floor 这一层 ⇒ 退出阈值 = 实测噪声底(0.55) 的 **14.5 倍**，永远够不着。
#
#   实测后果：1219/1297 帧被判"静止"，真实跟踪只剩 **每 912 ms 一次**
#   （68 帧 / 74.9 s），而被跳过的帧上纸的角点位移 **100% 是 0** ——
#   也就是"帧率上去了，动态跟随变成 0.9 秒一跳一格"。用户反馈正是这句。
#
#   rev2 三项修正：
#     ① **自适应噪声底**（快降 0.20 / 慢升 0.01），阈值 = max(下限, 系数 × 底)；
#     ② 进入用 **3 帧中值**（要求持续静止），退出用**原始值**（一动就退）；
#     ③ `MAX_S` 0.8 → **0.2 s**，并且到点只强制一帧真实跟踪、**不清保持态**
#        （否则每次都要再攒 `MIN_FRAMES` 帧，实际跳过率砍半）。
#
#   ⚠️ **`MAX_S` 才是真正兜住滞后量的那一条**，阈值只是尽量少误判。原因：
#      纸只占画面 ~19%，手慢慢动 1~3 px/帧 时全幅帧差只有 0.8~1.5，
#      和静止噪声底 0.55 只差 1.5~2.7 倍 —— 任何全幅统计量都分不开。
#      所以：**纸停了 ⇒ 跳过（快）；纸在动 ⇒ 由 MAX_S 限住滞后 ≤0.2 s**。
#      实测分离度：静止 0.54~0.59，明显移动 2.1~2.9。
#
#   标定依据（run-result(92)，`hold_diff` 全部实测值）：0.54 0.55 0.56 0.57 0.59
#   0.76 0.79 0.83 0.84 1.16 1.20 1.44 2.09 2.33 2.90
_HOLD_ON = os.environ.get('P11_MANUAL_STATIC_HOLD', '1') != '0'
#   ⚠️ `_HOLD_ENTER` / `_HOLD_EXIT` 是【下限】，实际阈值 = max(下限, 系数 × 噪声底)
_HOLD_ENTER = float(os.environ.get('P11_MANUAL_HOLD_ENTER', '0.9'))
_HOLD_EXIT = float(os.environ.get('P11_MANUAL_HOLD_EXIT', '1.6'))
_HOLD_ENTER_GAIN = float(os.environ.get('P11_MANUAL_HOLD_ENTER_GAIN', '1.5'))
_HOLD_EXIT_GAIN = float(os.environ.get('P11_MANUAL_HOLD_EXIT_GAIN', '2.2'))
_HOLD_CHANGE = float(os.environ.get('P11_MANUAL_HOLD_CHANGE', '0.02'))
_HOLD_EXIT_CHANGE = float(os.environ.get('P11_MANUAL_HOLD_EXIT_CHANGE', '0.04'))
_HOLD_MIN_FRAMES = max(1, int(float(os.environ.get('P11_MANUAL_HOLD_MIN_FRAMES', '2'))))
_HOLD_SMOOTH = max(1, int(float(os.environ.get('P11_MANUAL_HOLD_SMOOTH', '3'))))
_HOLD_MAX_S = float(os.environ.get('P11_MANUAL_HOLD_MAX_S', '0.2'))
#   ⭐ 见 `_reseed_points`：单帧位移超过这个值就不救（防止从病态点集外推单应）
_RESEED_MAX_MOVE = float(os.environ.get('P11_MANUAL_RESEED_MAX_MOVE', '12'))
#   ⭐ 2026-10-26（run 95）：会话死因从 `spatial_support` 换成了 `inliers_failed`（2/2）。
#      采样到的成功帧 `inlier_fraction` 全是 **1.0**、`rms` 只有 0.03~0.15 ——
#      余量很大，说明失败的那一帧是"少数点被误匹配"把比例拉了下来，而不是真的跟丢。
#      ⇒ 把 RANSAC 阈值和内点率门槛各松一档（**其余六道关一道没动**：
#      FB 一致性 / rms≤0.75 / `_valid` / 位移≤64 / `selected_quad` / `_distributed`）。
#   ⚠️ 这是**在没看到失败帧数据时的保守放宽**，不是诊断结论 ——
#      下次上板看 `MANUAL_TRACK_FAIL` 里的 `inlier_count / feature_count` 才能定。
_RANSAC_PX = float(os.environ.get('P11_MANUAL_RANSAC_PX', '1.8'))
_INLIER_MIN = float(os.environ.get('P11_MANUAL_INLIER_MIN', '0.75'))


class ManualTracker:
    """Only manual mode: actual outer-band features, complete FB and RANSAC.

    Manual selection authorizes the initial boundary, not an automatic four-edge
    receipt. With too little real texture the UI explicitly says FIXED; no fake
    optical-flow points or silent fallback from a failed moving track is used.
    """
    def __init__(self,frame,quad,limit=320,authority='manual'):
        from v31_tracking import GrayObserver
        self.observer=GrayObserver(limit);self.q=np.asarray(quad,np.float32).copy()
        self.lk_cache=None;self._mask=None;self._inside=None
        try:
            from v31_native import LKCache
            self.lk_cache=LKCache()
            self.gray,self.scale=self.observer.get(frame.image);self.observer.pin(self.gray)
            self.lk_cache.anchor(self.gray)
            self.previous_ready=float(frame.ready);self.first=True;self.last_seed=0.;self.last_failure=None
            #   ⭐ 静止门控状态（见文件头说明）
            self._hold_sample=None;self._hold_tmp=None;self._hold_hist=[]
            self._hold_since=0.;self._hold_active=False;self._hold_count=0
            self._hold_floor_m=_HOLD_ENTER;self._hold_floor_c=_HOLD_CHANGE
            self._hold_last_full=time.perf_counter()
            self.last_hold_diff=0.;self.last_hold_changed=0.;self.hold_frames=0
            self.points=self._features(self.gray,self.q);self.fixed=not self._distributed(self.points,self.q)
        except BaseException:
            self.close();raise
        self.kind='FIXED' if self.fixed else 'FB_TRACK'
        #   ⭐ `source_sha256`：这一版的源码指纹。**上板日志里对不上的时候，
        #      第一件事就是看它** —— run 94/95 的 `RELEASE_ID` 一模一样，
        #      根本分不出跑的是哪一版 PS 代码（2026-10-26 吃过这个亏）。
        checkpoint('MANUAL_TRACKER_READY' if authority=='manual' else 'V86_MOTION_TRACKER_READY',
            authority=authority,feature_count=0 if self.points is None else len(self.points),
            tracking=self.kind,feature_region='inside outer boundary band; no central playback area',
            fixed_means='explicit static coordinates; moving requires manual recalibration',automatic_edge_proof=False,
            source_sha256=_SOURCE_SHA256,
            ransac_px=_RANSAC_PX,inlier_min=_INLIER_MIN,reseed_max_move=_RESEED_MAX_MOVE,
            hold_max_s=_HOLD_MAX_S)
    def _features(self,gray,source_q):
        """在外环带找角点；带内纹理不够时【逐级放宽】，最后一档才允许纸内。

        ⚠️ 2026-10-26（run 93）：原来只调一次 `goodFeaturesToTrack(32,.012,5.)` 就定生死，
           某一场只找到 **7 个点**，而 `_distributed` 要求 ≥8 ⇒ 直接判 `FIXED`
           ⇒ **2021 帧（48%）完全不动**，用户反馈"还是没有动态跟随"。
           现在逐级放宽（宽带 / 低质量门限 / 大 blockSize / 多角点），
           只要纸上有纹理就一定能拿到 ≥8 个点；真的全无纹理才退回 FIXED。
        """
        q=(source_q+.5)/self.scale-.5;h,w=gray.shape
        if self._mask is None or self._mask.shape!=(h,w):
            self._mask=np.empty((h,w),np.uint8);self._inside=np.empty_like(self._mask)
        mask=self._mask;inside=self._inside;mask.fill(0);inside.fill(0)
        qi=np.rint(q).astype(np.int32);cv2.fillConvexPoly(inside,qi,255)
        best=None
        #   ⚠️ 收工条件不是"≥8 就够"：只找到 8 个但挤在一个角上时 `_distributed` 仍然不过，
        #      结果还是 FIXED。所以要求 **≥12 且空间分布合格**（12 个点对 8 参数单应余量够）。
        #   ⚠️ 每个档位的 `corners` 都封顶 32 —— 点越多 LK 越慢，
        #      而 `tracker_s` 已经 87 ms，不能为了鲁棒把每帧成本再推上去。
        for band,quality,dist,block,corners in ((12,.012,5.,3,32),(20,.006,4.,5,32),(28,.003,4.,7,32)):
            mask.fill(0)
            cv2.polylines(mask,[qi],True,255,band)
            cv2.bitwise_and(mask,inside,dst=mask)
            p=cv2.goodFeaturesToTrack(gray,corners,quality,dist,mask=mask,blockSize=block)
            if p is None:continue
            p=np.ascontiguousarray(p,np.float32)
            if best is None or len(p)>len(best):best=p
            if len(p)>=12 and self._distributed(p,source_q):return p
        #   最后一档：把纸的包围盒四等分，每格各找几个 —— 不再限于外环带。
        #   ⚠️ 分格是为了**保证空间分布**：整张纸一次找点时 `goodFeaturesToTrack`
        #      会挑最强的若干个，很容易全挤在一角，`_distributed` 照样不过 ⇒ 还是 FIXED。
        x0,y0=qi.min(axis=0);x1,y1=qi.max(axis=0)
        cells=[]
        for gy in range(2):
            for gx in range(2):
                a=(int(x0+gx*(x1-x0)//2),int(y0+gy*(y1-y0)//2))
                b=(int(x0+(gx+1)*(x1-x0)//2),int(y0+(gy+1)*(y1-y0)//2))
                mask.fill(0)
                cv2.rectangle(mask,a,b,255,-1)
                cv2.bitwise_and(mask,inside,dst=mask)
                pp=cv2.goodFeaturesToTrack(gray,8,.004,3.,mask=mask,blockSize=5)
                if pp is not None:cells.append(np.ascontiguousarray(pp,np.float32))
        if cells:
            p=np.concatenate(cells,axis=0)
            if best is None or len(p)>len(best):best=p
            if len(p)>=8 and self._distributed(p,source_q):return p
        return best
    def _distributed(self,points,q):
        if points is None or len(points)<8:return False
        from v31_tracking import _spatial_support
        return bool(_spatial_support(points,(q+.5)/self.scale-.5,'legacy'))
    #   ⭐ 2026-10-26（run 94）：跟踪【成功】但幸存点分布不合格时，**就地在当前帧、
    #      绕新四边形重新取一次点**，而不是整帧作废。
    #
    #   为什么这样是安全的：走到这一步时，四边形已经过了 FB 一致性(中位<0.35px)、
    #   RANSAC 内点率(>=0.85)、重投影 RMS(<=0.75px)、`_valid`、单帧位移(<=64px)、
    #   `selected_quad` 六道关。`_distributed` 卡的是**下一帧的跟踪基座**，
    #   不是这一帧的四边形对不对。
    #
    #   ⚠️ 但 `_distributed` 原本还兼一个作用：**防止 LK 整体滑到背景上**。所以这里
    #      限定 `move<=_RESEED_MAX_MOVE` 才救 —— 单帧位移很大同时又挤成一团，
    #      正是"从病态点集里外推单应"最危险的组合，那种情况照旧作废。
    #   ⚠️ 返回 None 表示本帧应当作废（调用方 raise `manual_motion_spatial_support_failed`）。
    def _reseed_points(self,points,q,gray,move):
        if self._distributed(points,q):return points,False
        if move>_RESEED_MAX_MOVE:return None,False
        seeds=self._features(gray,q)
        if seeds is None or len(seeds)<8 or not self._distributed(seeds,q):return None,False
        return np.ascontiguousarray(seeds,np.float32),True
    #   ⭐ 静止门控：80×80 采样 + 自适应噪声底 + 滞回 + 最长保持时间。
    #      口径与自动模式 `v87_v74_tracking._static_hold` 一致（rev2，见文件头）。
    #      返回 True = 本帧可以跳过跟踪；False = 必须做一次真实跟踪。
    def _still(self,gray,now):
        if not _HOLD_ON or self.fixed:return False
        h,w=gray.shape
        if h<80 or w<80:return False
        sample=gray[::max(1,h//80),::max(1,w//80)][:80,:80]
        prev=self._hold_sample
        if prev is None or prev.shape!=sample.shape:
            self._hold_sample=np.empty(sample.shape,np.int16)
            np.copyto(self._hold_sample,sample,casting='unsafe')
            self._hold_tmp=np.empty(sample.shape,np.int16)
            self._hold_hist=[];self._hold_count=0;self._hold_active=False
            self._hold_since=now;self._hold_last_full=now
            return False
        tmp=np.subtract(sample,prev,out=self._hold_tmp,casting='unsafe')
        np.abs(tmp,out=tmp)
        motion=float(tmp.mean())
        changed=float(np.count_nonzero(tmp>8))/float(tmp.size)
        np.copyto(prev,sample,casting='unsafe')
        self.last_hold_diff=motion;self.last_hold_changed=changed
        #   自适应噪声底：低于底时快速跟随（0.20），高于底时极慢上升（0.01）
        fm=self._hold_floor_m;fc=self._hold_floor_c
        fm+=(.20 if motion<fm else .01)*(motion-fm)
        fc+=(.20 if changed<fc else .01)*(changed-fc)
        self._hold_floor_m=fm;self._hold_floor_c=fc
        hist=self._hold_hist;hist.append((motion,changed))
        if len(hist)>_HOLD_SMOOTH:hist.pop(0)
        sm=sorted(v[0] for v in hist)[len(hist)//2]
        sc=sorted(v[1] for v in hist)[len(hist)//2]
        #   进入用【平滑值】（要求持续静止）；退出用【原始值】（一动就退）
        if self._hold_active:
            exit_m=max(_HOLD_EXIT,_HOLD_EXIT_GAIN*fm)
            exit_c=max(_HOLD_EXIT_CHANGE,_HOLD_EXIT_GAIN*fc)
            blocked=motion>exit_m or changed>exit_c
        else:
            limit_m=max(_HOLD_ENTER,_HOLD_ENTER_GAIN*fm)
            limit_c=max(_HOLD_CHANGE,_HOLD_ENTER_GAIN*fc)
            blocked=sm>limit_m or sc>limit_c
        if blocked:
            self._hold_active=False;self._hold_count=0
            return False
        if not self._hold_active:
            self._hold_count+=1
            if self._hold_count<_HOLD_MIN_FRAMES:return False
            self._hold_active=True;self._hold_since=now;self.hold_frames=0
        #   到点强制做一次真实跟踪（防慢速漂移），但【不清保持态】——
        #   下一帧仍按"已在保持"判定，不必重新攒 MIN_FRAMES 帧。
        if now-self._hold_last_full>=_HOLD_MAX_S:return False
        self.hold_frames+=1
        return True
    def update(self,frame):
        began=time.perf_counter();cpu=time.thread_time()
        if self.fixed:return self.q.copy(),dict(manual_tracking='FIXED',manual_motion_proved=False,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu)
        detail=dict(manual_tracking='FB_TRACK',manual_motion_proved=False)
        try:
            elapsed=float(frame.ready)-self.previous_ready
            if not self.first and not 0<elapsed<=.75:raise ValueError('manual_capture_gap_or_expired_anchor')
            gray,scale=self.observer.get(frame.image)
            if not np.array_equal(scale,self.scale):raise ValueError('manual_source_layout_changed')
            #   ⭐ 静止门控：画面没动 ⇒ 复用上一帧四角，跳过 LK + RANSAC。
            #   ⚠️ 必须同时刷新 gray / pin / previous_ready / first —— 否则
            #      下一次真实跟踪会撞 .75 s 的 expired_anchor 守卫。
            if not self.first and self._still(gray,time.perf_counter()):
                self.gray=gray;self.observer.pin(gray)
                self.previous_ready=float(frame.ready);self.first=False
                detail.update(static_hold=True,hold_frames=self.hold_frames,
                    hold_diff=self.last_hold_diff,hold_changed=self.last_hold_changed,
                    hold_floor_m=self._hold_floor_m,hold_floor_c=self._hold_floor_c,
                    hold_max_s=_HOLD_MAX_S,
                    feature_count=0 if self.points is None else len(self.points))
                detail.update(tracker_s=time.perf_counter()-began,
                    tracker_thread_cpu_s=time.thread_time()-cpu)
                return self.q.copy(),detail
            p=self.points
            if not self._distributed(p,self.q):raise ValueError('manual_outer_features_insufficient')
            flow=time.perf_counter();args=dict(winSize=(21,21),maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02))
            native=self.lk_cache.track(gray,p,levels=3,iterations=20,generation=int(frame.sequence)&0xffffffff)
            if native is None:f,s,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,p,None,**args)
            else:f,s,error,back,sb=native
            if f is None or s is None:raise ValueError('manual_forward_flow_failed')
            if native is None:back,sb,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,f,None,**args)
            if back is None or sb is None:raise ValueError('manual_backward_flow_failed')
            fb=np.linalg.norm(back.reshape(-1,2)-p.reshape(-1,2),axis=1)
            good=(s.ravel()!=0)&(sb.ravel()!=0)&np.isfinite(f).all(axis=(1,2))&np.isfinite(fb)&(fb<.8)
            detail.update(forward_backward_flow_s=time.perf_counter()-flow,feature_count=len(p),good_features=int(good.sum()),
                lk_backend='native_cached_bidirectional_pyramids' if native is not None else 'opencv_bidirectional')
            if good.sum()<8 or float(np.median(fb[good]))>.35:raise ValueError('manual_FB_consistency_failed')
            a=p.reshape(-1,2)[good];b=f.reshape(-1,2)[good]
            transform,inliers=cv2.findHomography(a,b,cv2.RANSAC,_RANSAC_PX,maxIters=300,confidence=.995)
            if transform is None or inliers is None or not np.isfinite(transform).all():raise ValueError('manual_motion_model_failed')
            keep=inliers.ravel()!=0;fraction=float(np.mean(keep))
            detail.update(inlier_fraction=fraction,inlier_count=int(keep.sum()),model_points=len(p))
            if keep.sum()<8 or fraction<_INLIER_MIN:raise ValueError('manual_motion_inliers_failed')
            projected=cv2.perspectiveTransform(a[keep].reshape(-1,1,2),transform).reshape(-1,2)
            rms=float(np.sqrt(np.mean(np.sum((projected-b[keep])**2,axis=1))))
            if rms>.75:raise ValueError('manual_reprojection_error')
            small=(self.q+.5)/self.scale-.5
            next_q=cv2.perspectiveTransform(small.reshape(-1,1,2),transform).reshape(-1,2)
            from v31_tracking import _valid
            if not _valid(next_q,gray.shape,small,'legacy'):raise ValueError('manual_current_quad_invalid')
            move=float(np.max(np.linalg.norm(next_q-small,axis=1)))
            if move>64:raise ValueError('manual_motion_too_large')
            q=(next_q+.5)*self.scale-.5
            from v82_interaction import selected_quad
            # Validate intersections without reordering physical corner identity.
            selected_quad(q,frame.image.shape)
            next_points,reseeded=self._reseed_points(
                np.ascontiguousarray(b[keep].reshape(-1,1,2),np.float32),q,gray,move)
            if next_points is None:raise ValueError('manual_motion_spatial_support_failed')
            if reseeded:detail.update(point_reseed_at='motion',point_reseed_px=move)
            if native is not None:self.lk_cache.promote()
            self.q=q.astype(np.float32);self.points=next_points
            self.gray=gray;self.observer.pin(gray);self.previous_ready=float(frame.ready);self.first=False
            # Low-rate top-up only after a successful complete flow transaction.
            if len(next_points)<16 and time.perf_counter()-self.last_seed>=1.:
                self.last_seed=time.perf_counter();seeds=self._features(gray,self.q)
                if self._distributed(seeds,self.q):self.points=seeds
            detail.update(manual_motion_proved=True,fb_median=float(np.median(fb[good])),
                inlier_fraction=fraction,reprojection_rms=rms,features_retained=len(self.points))
            self.last_failure=None;result=self.q.copy()
        except (ValueError,cv2.error) as exc:
            detail.update(reason=str(exc));self.last_failure=str(exc);result=None
            #   ⭐ 失败帧的数据只在这里才拿得到（`manual_track_detail` 是每 60 帧才记一条）。
            #      没有这几项，"为什么死"就只能靠猜 —— 2026-10-26 已经猜错过一次。
            try:
                checkpoint('MANUAL_TRACK_FAIL',reason=str(exc),
                    feature_count=detail.get('feature_count'),good_features=detail.get('good_features'),
                    inlier_fraction=detail.get('inlier_fraction'),inlier_count=detail.get('inlier_count'),
                    model_points=detail.get('model_points'),
                    reprojection_rms=detail.get('reprojection_rms'),fb_median=detail.get('fb_median'),
                    hold_active=self._hold_active,hold_frames=self.hold_frames,
                    source_sha256=_SOURCE_SHA256,tracker_s=time.perf_counter()-began)
            except Exception:pass
        #   ⭐ 真实跟踪做完（不管成败）⇒ 记一次"完整测量"，MAX_S 从这里重新计时
        self._hold_last_full=time.perf_counter()
        detail.update(tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu)
        return result,detail
    def close(self):
        # ObservationWorkspace owns NumPy work arrays, no native close handle.
        # Retire the caller's worker before dropping these pinned references.
        observer=self.observer
        if self.lk_cache is not None:self.lk_cache.close()
        if observer is None:return
        transaction=getattr(observer,'transaction',None)
        close=getattr(transaction,'close',None)
        if callable(close):close()
        self.observer=None;self.gray=None;self.points=None

