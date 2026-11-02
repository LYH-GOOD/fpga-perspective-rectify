"""Pure NumPy/OpenCV mask-to-quadrilateral helpers; no training framework."""
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
import cv2
import numpy as np

POSTPROCESS_VERSION="mask_quad_huber_lines_v2"

def ordered(points):
    q=np.asarray(points,np.float32).reshape(4,2)
    q=q[np.argsort(np.arctan2(q[:,1]-q[:,1].mean(),q[:,0]-q[:,0].mean()))]
    q=np.roll(q,-np.argmin(q.sum(axis=1)),axis=0)
    if cv2.contourArea(q,oriented=True)<0: q=q[[0,3,2,1]]
    return q

def quad_from_mask(binary):
    count,labels,stats,_=cv2.connectedComponentsWithStats(binary.astype(np.uint8),8)
    if count<=1: return None,0.
    index=1+np.argmax(stats[1:,cv2.CC_STAT_AREA])
    component=(labels==index).astype(np.uint8)
    if component.sum()<binary.size*.02 or component.sum()>binary.size*.90: return None,0.
    contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    hull=cv2.convexHull(max(contours,key=cv2.contourArea))
    best=None;score=0.
    for eps in [.008,.012,.018,.025,.035,.05,.065,.08]:
        approx=cv2.approxPolyDP(hull,eps*cv2.arcLength(hull,True),True)
        if len(approx)!=4 or not cv2.isContourConvex(approx): continue
        q=ordered(approx)
        filled=np.zeros_like(component)
        cv2.fillPoly(filled,[np.rint(q).astype(np.int32)],1)
        iou=float(np.sum((filled>0)&(component>0))/max(1,np.sum((filled>0)|(component>0))))
        if iou>score: score=iou;best=q
    if score<.7: return None,score
    refined,fit=_refine_lines(binary,best)
    if refined is not None and fit>=score-.015: return refined,fit
    return best,score


def _refine_lines(binary,q):
    count,labels,stats,_=cv2.connectedComponentsWithStats(binary.astype(np.uint8),8)
    if count<=1:return None,0.
    component=(labels==(1+np.argmax(stats[1:,cv2.CC_STAT_AREA]))).astype(np.uint8)
    contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    points=max(contours,key=cv2.contourArea).reshape(-1,2).astype(np.float32)
    lines=[]
    for i in range(4):
        a=q[i];direction=q[(i+1)%4]-a
        length=float(np.linalg.norm(direction));unit=direction/length
        relative=points-a
        t=relative@unit/length
        distance=np.abs(relative[:,0]*unit[1]-relative[:,1]*unit[0])
        chosen=points[(t>.18)&(t<.82)&(distance<max(2.5,length*.06))]
        if len(chosen)<12:return None,0.
        vx,vy,x,y=cv2.fitLine(chosen,cv2.DIST_HUBER,0,.01,.01).reshape(4)
        lines.append((np.array([x,y]),np.array([vx,vy])))
    corners=[]
    for i in range(4):
        previous,dp=lines[(i-1)%4];current,dc=lines[i]
        matrix=np.column_stack((dp,-dc))
        if abs(np.linalg.det(matrix))<.1:return None,0.
        offset=np.linalg.solve(matrix,current-previous)[0]
        corners.append(previous+offset*dp)
    result=ordered(corners)
    h,w=binary.shape
    if not np.isfinite(result).all() or not cv2.isContourConvex(result):return None,0.
    if (result<0).any() or (result[:,0]>w-1).any() or (result[:,1]>h-1).any():return None,0.
    movement=np.mean(np.linalg.norm(result-q,axis=1))
    if movement>min(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1))*.15:return None,0.
    filled=np.zeros_like(component)
    cv2.fillPoly(filled,[np.rint(result).astype(np.int32)],1)
    iou=float(np.sum((filled>0)&(component>0))/max(1,np.sum((filled>0)|(component>0))))
    return result,iou

