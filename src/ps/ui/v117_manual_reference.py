"""True-manual-only reference motion; one existing native FB transaction."""
from pathlib import Path
import hashlib,time
import cv2,numpy as np
from run_logging import checkpoint
from p11_contract import RELEASE_ID
from v92_manual_v87 import ManualTracker as OriginalTracker,_RANSAC_PX,_INLIER_MIN
from v105_manual_tracking import PersistentManualTracker as OriginalPersistent
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_CANON=np.float32([[0,0],[63,0],[63,63],[0,63]])
_RING=np.ones((64,64),bool);_RING[4:-4,4:-4]=False

def similarity(a,b):
    x=a-a.mean(0);y=b-b.mean(0);den=float(np.sum(x*x))
    if den<1.e-6:return None,float('inf')
    c=float(np.sum(x*y))/den;s=float(np.sum(x[:,0]*y[:,1]-x[:,1]*y[:,0]))/den
    M=np.array([[c,-s],[s,c]],np.float64);t=b.mean(0)-M@a.mean(0)
    H=np.eye(3);H[:2,:2]=M;H[:2,2]=t
    error=float(np.sqrt(np.mean(np.sum((a@M.T+t-b)**2,axis=1))))
    return H,error

class ReferenceTracker(OriginalTracker):
    def __init__(self,frame,quad,limit=320,authority='manual'):
        self.boundary_points=False
        super().__init__(frame,quad,limit,authority)
        self.reference_q=(self.q+.5)/self.scale-.5
        self.reference_points=None if self.points is None else self.points.copy()
        self.reference_epoch=0;self.last_model='initial';self.next_audit=float(frame.ready)+1.
        self.reference_template=self._template(self.gray,self.reference_q)
        self.reference_vector=self.reference_template[_RING].astype(np.float32)
        self.reference_vector-=self.reference_vector.mean()
        self.reference_norm=float(np.linalg.norm(self.reference_vector))
        self.audit_count=0;self.audit_failed=0;self.last_audit=None
        self._roi_indices=None;self._refresh_roi(self.gray.shape)
        checkpoint('MANUAL_REFERENCE_READY',source_sha256=_SOURCE_SHA256,working_points=0 if self.points is None else len(self.points),
            maximum_points=32,one_fb=True,reference_shape=[64,64],audit_period_s=1.,manual_only=True)
    @staticmethod
    def _template(gray,q):
        H=cv2.getPerspectiveTransform(np.asarray(q,np.float32),_CANON)
        return cv2.warpPerspective(gray,H,(64,64),flags=cv2.INTER_LINEAR)
    def _features(self,gray,q):
        self.boundary_points=False
        p=super()._features(gray,q)
        if p is None:return p
        pts=p.reshape(-1,2);small=np.asarray((np.asarray(q)+.5)/self.scale-.5,np.float32)
        distance=np.array([cv2.pointPolygonTest(small,tuple(map(float,x)),True) for x in pts])
        boundary=p[(distance>=-1.)&(distance<=3.)]
        area=max(1.,abs(cv2.contourArea(small)))
        if len(boundary)>=4 and abs(cv2.contourArea(cv2.convexHull(boundary)))>=.35*area:
            p=boundary;self.boundary_points=True
        if len(p)<=24:return p
        pts=p.reshape(-1,2)
        chosen=[]
        # Keep boundary coverage, then greedily retain separated existing points.
        for corner in small:
            order=np.argsort(np.sum((pts-corner)**2,axis=1))
            chosen.append(next(int(i) for i in order if int(i) not in chosen))
        distance=np.min(np.sum((pts[:,None]-pts[chosen][None])**2,axis=2),axis=1)
        while len(chosen)<24:
            distance[chosen]=-1.;i=int(np.argmax(distance));chosen.append(i)
            distance=np.minimum(distance,np.sum((pts-pts[i])**2,axis=1))
        selected=np.ascontiguousarray(pts[chosen].reshape(-1,1,2),np.float32)
        return selected if self._distributed(selected,q) else p
    def _distributed(self,points,q):
        if self.boundary_points and points is not None and len(points)>=4:
            small=np.asarray((np.asarray(q)+.5)/self.scale-.5,np.float32)
            return abs(cv2.contourArea(cv2.convexHull(points)))>=.35*max(1.,abs(cv2.contourArea(small)))
        return super()._distributed(points,q)
    def _reseed_points(self,points,q,gray,move):
        if self._distributed(points,q):return points,False
        return super()._reseed_points(points,q,gray,move)
    def _refresh_roi(self,shape):
        h,w=shape
        if self.points is None or not len(self.points):self._roi_indices=None;return
        centers=np.rint(self.points.reshape(-1,2)).astype(np.int32);yy,xx=np.mgrid[-3:4,-3:4]
        xs=np.clip(centers[:,0,None]+xx.reshape(1,-1),0,w-1).reshape(-1)
        ys=np.clip(centers[:,1,None]+yy.reshape(1,-1),0,h-1).reshape(-1)
        # Same6400-sample budget, centred on actual target features rather than
        # flat background/cover pixels. Index work happens only after real flow.
        self._roi_indices=(np.resize(ys,6400).reshape(80,80),np.resize(xs,6400).reshape(80,80))
    def _still(self,gray,now):
        return False if self._roi_indices is None else super()._still(gray[self._roi_indices],now)
    def _audit(self,gray,q,stamp):
        current=self._template(gray,q)[_RING].astype(np.float32);current-=current.mean()
        norm=float(np.linalg.norm(current));count=len(current)
        self.audit_count+=1;self.next_audit=stamp+1.
        if min(norm,self.reference_norm)<3.*np.sqrt(count):
            self.last_audit=dict(state='insufficient_texture',ncc=None);return True
        ncc=float(np.dot(current,self.reference_vector)/(norm*self.reference_norm))
        self.last_audit=dict(state='matched' if ncc>=.15 else 'mismatch',ncc=ncc)
        if ncc<.15:self.audit_failed+=1;return False
        return True
    def update(self,frame):
        begin=time.perf_counter();cpu=time.thread_time()
        if self.fixed:return super().update(frame)
        detail=dict(manual_tracking='FB_TRACK',manual_motion_proved=False,manual_reference17=True)
        try:
            stamp=float(frame.ready);elapsed=stamp-self.previous_ready
            if not self.first and not 0.<elapsed<=.75:raise ValueError('manual_capture_gap_or_expired_anchor')
            gray,scale=self.observer.get(frame.image)
            if not np.array_equal(scale,self.scale):raise ValueError('manual_source_layout_changed')
            if not self.first and self._still(gray,time.perf_counter()):
                # The point coordinates and native pyramid stay at the last
                # actual flow image. Capture/static samples have their own clock.
                detail.update(static_hold=True,hold_frames=self.hold_frames,reference_epoch=self.reference_epoch,
                    feature_count=len(self.points),manual_motion_model=self.last_model)
                return self.q.copy(),dict(detail,tracker_s=time.perf_counter()-begin,tracker_thread_cpu_s=time.thread_time()-cpu)
            p=self.points
            if not self._distributed(p,self.q):raise ValueError('manual_outer_features_insufficient')
            flow=time.perf_counter();native=self.lk_cache.track(gray,p,levels=3,iterations=20,generation=int(frame.sequence)&0xffffffff)
            if native is None:
                args=dict(winSize=(21,21),maxLevel=3,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02))
                f,s,_=cv2.calcOpticalFlowPyrLK(self.gray,gray,p,None,**args)
                if f is None or s is None:raise ValueError('manual_forward_flow_failed')
                back,sb,_=cv2.calcOpticalFlowPyrLK(gray,self.gray,f,None,**args)
            else:f,s,error,back,sb=native
            if f is None or back is None or s is None or sb is None:raise ValueError('manual_backward_flow_failed')
            fb=np.linalg.norm(back.reshape(-1,2)-p.reshape(-1,2),axis=1)
            good=(s.ravel()!=0)&(sb.ravel()!=0)&np.isfinite(f).all(axis=(1,2))&np.isfinite(fb)&(fb<.8)
            detail.update(forward_backward_flow_s=time.perf_counter()-flow,feature_count=len(p),good_features=int(good.sum()),
                lk_backend='native_cached_bidirectional_pyramids' if native is not None else 'opencv_bidirectional')
            minimum=4 if self.boundary_points else 8
            if good.sum()<minimum or float(np.median(fb[good]))>.35:raise ValueError('manual_FB_consistency_failed')
            a=self.reference_points.reshape(-1,2)[good];b=f.reshape(-1,2)[good]
            simple,simple_rms=similarity(a,b);model='similarity_reference'
            if simple is not None and simple_rms<=.20:
                H=simple;keep=np.ones(len(a),bool);fraction=1.;rms=simple_rms
            else:
                H,inliers=cv2.findHomography(a,b,cv2.RANSAC,_RANSAC_PX,maxIters=300,confidence=.995)
                if H is None or inliers is None or not np.isfinite(H).all():raise ValueError('manual_motion_model_failed')
                keep=inliers.ravel()!=0;fraction=float(np.mean(keep));model='projective_reference'
                if keep.sum()<minimum or fraction<_INLIER_MIN:raise ValueError('manual_motion_inliers_failed')
                projected=cv2.perspectiveTransform(a[keep].reshape(-1,1,2),H).reshape(-1,2)
                rms=float(np.sqrt(np.mean(np.sum((projected-b[keep])**2,axis=1))))
                if rms>.75:raise ValueError('manual_reprojection_error')
            next_q=cv2.perspectiveTransform(self.reference_q.reshape(-1,1,2),H).reshape(-1,2)
            small=(self.q+.5)/self.scale-.5
            from v31_tracking import _valid
            if not _valid(next_q,gray.shape,small,'legacy'):raise ValueError('manual_current_quad_invalid')
            move=float(np.max(np.linalg.norm(next_q-small,axis=1)))
            if move>64:raise ValueError('manual_motion_too_large')
            q=(next_q+.5)*self.scale-.5
            from v82_interaction import selected_quad
            selected_quad(q,frame.image.shape)
            retained=np.ascontiguousarray(b[keep].reshape(-1,1,2),np.float32)
            next_points,reseeded=self._reseed_points(retained,q,gray,move)
            if next_points is None:raise ValueError('manual_motion_spatial_support_failed')
            top_up=not self.boundary_points and len(next_points)<16 and time.perf_counter()-self.last_seed>=1.
            if reseeded or top_up or stamp>=self.next_audit:
                if not self._audit(gray,next_q,stamp):raise ValueError('manual_reference_mismatch')
            if top_up:
                seeds=self._features(gray,q)
                if self._distributed(seeds,q):next_points=seeds;reseeded=True
                self.last_seed=time.perf_counter()
            if native is not None:self.lk_cache.promote()
            self.q=q.astype(np.float32);self.points=next_points
            if reseeded:
                self.reference_q=next_q.copy();self.reference_points=next_points.copy();self.reference_epoch+=1
            else:self.reference_points=np.ascontiguousarray(self.reference_points[good][keep],np.float32)
            self.gray=gray;self.observer.pin(gray);self.previous_ready=stamp;self.first=False
            self._refresh_roi(gray.shape)
            self._hold_last_full=time.perf_counter();self.last_model=model;self.last_failure=None
            detail.update(manual_motion_proved=True,manual_motion_model=model,reference_epoch=self.reference_epoch,
                reference_audits=self.audit_count,reference_audit=self.last_audit,reference_reseeded=reseeded,
                inlier_fraction=fraction,inlier_count=int(keep.sum()),fb_median=float(np.median(fb[good])),
                reprojection_rms=rms,similarity_rms=simple_rms,features_retained=len(next_points))
            result=self.q.copy()
        except (ValueError,cv2.error) as exc:
            self.last_failure=str(exc);detail['reason']=str(exc);result=None
            checkpoint('MANUAL_REFERENCE_FAIL',reason=str(exc),feature_count=detail.get('feature_count'),
                good_features=detail.get('good_features'),reference_epoch=self.reference_epoch)
        detail.update(tracker_s=time.perf_counter()-begin,tracker_thread_cpu_s=time.thread_time()-cpu)
        return result,detail

class PersistentReferenceTracker(OriginalPersistent):
    def __init__(self,frame,quad,limit=320,authority='manual'):
        from v105_native import prepare_edges
        prepare_edges()
        self.primary=ReferenceTracker(frame,quad,limit,authority);self.edge=None;self.failures=0
        self.next_retry=0.;self.limit=limit;self.authority=authority;self.closed=False
        if self.primary.fixed:
            from v104_physical_tracking import PhysicalTracker
            try:self.edge=PhysicalTracker.from_observation(self.primary.gray,self.primary.scale,self.primary.q,self.primary.previous_ready,limit,authority)
            except (ValueError,cv2.error):pass
            if self.edge is not None:self.primary.close()
