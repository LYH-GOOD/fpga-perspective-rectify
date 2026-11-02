"""Conservative target departure/return latch; small probes only when needed.

This proposes new admission, never corners or a CURRENT output receipt.
Tracking loss alone cannot establish absence. Stable empty evidence must be
observed before a separate stable reappearance can start another search epoch.
"""
from pathlib import Path
import hashlib
import cv2,numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class TargetCycle:
    def __init__(self,interval=.5):
        self.interval=float(interval);self.next_at=0.;self.state='UNKNOWN'
        self.reference=None;self.quad=None;self.empty=None;self.pending=None
        self.negative_since=None;self.negative_count=0;self.positive_since=None;self.positive_count=0
        self.last_sequence=None;self.probes=0
        self.candidate_box=None;self.candidate_count=0;self.candidate_since=None
        self.candidate_version=0;self.candidate_anchor=None;self.present_at=None
    @staticmethod
    def small(image):
        step=max(1,round(max(image.shape[:2])/160))
        view=image[::step,::step]
        return np.ascontiguousarray(view[:,:,0] if view.shape[2]==2 else cv2.cvtColor(view,cv2.COLOR_BGR2GRAY))
    def lock(self,image,quad):
        self.reference=self.small(image)
        self.quad=np.asarray(quad,np.float32)*np.array([self.reference.shape[1]/image.shape[1],self.reference.shape[0]/image.shape[0]],np.float32)
        self.state='PRESENT';self.pending=None;self.negative_count=self.positive_count=0
        self.negative_since=self.positive_since=None
        self.reset_candidate(new_target=True)
    def reset_candidate(self,new_target=False):
        # Box, count and start time form one observation history. Never retain
        # an old box with a cleared clock across a missing contour or new lock.
        self.candidate_box=None;self.candidate_count=0;self.candidate_since=None;self.present_at=None
        if new_target:self.candidate_anchor=None
    def tracking_good(self):
        # Measured tracking is stronger evidence than a missing coarse contour.
        if self.state!='ABSENT':self.state='PRESENT'
        self.negative_count=0;self.negative_since=None
    @staticmethod
    def _quads(small):
        smooth=cv2.GaussianBlur(small,(3,3),0)
        low=max(8,min(24,int(float(np.std(smooth))*.35)))
        edge=cv2.Canny(smooth,low,low*3)
        contours,_=cv2.findContours(edge,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        h,w=small.shape;found=[]
        for c in contours:
            area=abs(cv2.contourArea(c))
            if not .018*h*w<=area<=.90*h*w:continue
            p=cv2.approxPolyDP(c,.028*cv2.arcLength(c,True),True)
            if len(p)!=4 or not cv2.isContourConvex(p):continue
            q=p.reshape(4,2).astype(np.float32)
            if np.any(q[:,0]<=1) or np.any(q[:,1]<=1) or np.any(q[:,0]>=w-2) or np.any(q[:,1]>=h-2):continue
            lengths=np.linalg.norm(q-np.roll(q,1,axis=0),axis=1)
            if lengths.min()<8 or lengths.max()/lengths.min()>4.5:continue
            found.append((area,q))
        return [q for _,q in sorted(found,key=lambda pair:pair[0],reverse=True)[:8]]
    @staticmethod
    def _difference(a,b):
        delta=a.astype(np.float32)-b.astype(np.float32)
        delta-=np.median(delta)
        return np.abs(delta)
    def _empty_evidence(self,small):
        if self.empty is not None and self.empty.shape==small.shape:
            d=self._difference(small,self.empty)
            if float(d.mean())<5. and float(np.mean(d>15))<.08:return True
        if self.reference is not None and self.reference.shape==small.shape:
            q=self.quad;center=q.mean(0)
            core=np.zeros(small.shape,np.uint8);ring=np.zeros_like(core);inside=np.zeros_like(core)
            cv2.fillConvexPoly(core,np.rint(center+(q-center)*.60).astype(np.int32),1)
            cv2.fillConvexPoly(ring,np.rint(center+(q-center)*1.16).astype(np.int32),1)
            cv2.fillConvexPoly(inside,np.rint(center+(q-center)*.90).astype(np.int32),1)
            ring[inside!=0]=0;c=small[core!=0];r=small[ring!=0]
            if c.size<20 or r.size<20:return False
            d=self._difference(small,self.reference)[core!=0]
            disappeared=float(d.mean())>5. and float(np.mean(d>10.))>.15
            resembles_background=abs(float(np.median(c))-float(np.median(r)))<18. and abs(float(np.std(c))-float(np.std(r)))<16.
            return disappeared and resembles_background
        # Startup/failed-AI waiting has no known object boundary. Require a
        # broadly uniform background, not merely failure to find a rectangle.
        h,w=small.shape;med=[];spread=[]
        for y in range(3):
            for x in range(3):
                cell=small[y*h//3:(y+1)*h//3,x*w//3:(x+1)*w//3]
                med.append(float(np.median(cell)));spread.append(float(np.std(cell)))
        med.sort();spread.sort()
        return med[-2]-med[1]<24. and spread[-2]-spread[1]<16.
    def _foreground(self,small):
        if self.empty is None or self.empty.shape!=small.shape:return None
        mask=(self._difference(small,self.empty)>12.).astype(np.uint8)
        changed=float(mask.mean())
        if not .01<changed<.65:return None
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours,key=cv2.contourArea,reverse=True)[:3]:
            x,y,w,h=cv2.boundingRect(c)
            if w>=10 and h>=10 and w*h>=.025*small.size and cv2.contourArea(c)>.012*small.size:
                return np.array([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],np.float32)
        return None
    def _candidate_signal(self,q,now):
        if q is None:self.reset_candidate();return
        box=np.r_[q.min(0),q.max(0)]
        stable=(self.candidate_since is not None and self.candidate_box is not None
            and float(np.max(np.abs(box-self.candidate_box)))<=8.)
        if stable:self.candidate_count+=1
        else:self.candidate_count=1;self.candidate_since=now;self.present_at=None
        self.candidate_box=box
        if self.candidate_count>=3 and self.candidate_since is not None and now-self.candidate_since>=1.:
            self.present_at=now
            if self.candidate_anchor is None or float(np.max(np.abs(box-self.candidate_anchor)))>8.:
                self.candidate_anchor=box.copy();self.candidate_version+=1
    def observe(self,image,sequence,now):
        if now<self.next_at or sequence==self.last_sequence:return None
        self.next_at=now+self.interval;self.last_sequence=sequence;self.probes+=1
        small=self.small(image);quads=self._quads(small)
        proposal=quads[0] if quads else self._foreground(small) if self.state=='ABSENT' else None
        self._candidate_signal(proposal,now)
        if self.state=='ABSENT':
            q=proposal
            changed=self.empty is not None and float(self._difference(small,self.empty).mean())>3.
            if q is None or not changed:
                self.pending=None;self.positive_count=0;self.positive_since=None;return None
            box=np.r_[q.min(0),q.max(0)]
            stable=(self.positive_since is not None and self.pending is not None
                and float(np.max(np.abs(box-self.pending)))<=8.)
            if not stable:self.positive_count=1;self.positive_since=now
            else:self.positive_count+=1
            self.pending=box
            if self.positive_count>=3 and self.positive_since is not None and now-self.positive_since>=1.:
                self.state='PRESENT';self.reference=None;self.quad=None;self.pending=None
                self.negative_count=0;self.negative_since=None
                return 'RETURNED'
            return None
        if quads or not self._empty_evidence(small):
            self.negative_count=0;self.negative_since=None;return None
        if self.negative_since is None:self.negative_since=now
        self.negative_count+=1
        if self.negative_count>=4 and now-self.negative_since>=1.5:
            self.state='ABSENT';self.empty=small.copy();self.pending=None
            self.positive_count=0;self.positive_since=None
            return 'ABSENT'
        return None
