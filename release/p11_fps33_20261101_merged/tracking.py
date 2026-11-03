"""tracking —— 合并层，含 28 个原始模块。

本文件由 build/merge_layers.py 生成，不要直接编辑。
每个原始模块的边界见下方 "# ===== [NN/MM] 模块名 =====" 分节标记。
"""


from pathlib import Path
import hashlib


from pathlib import Path
import hashlib,time
from contextlib import contextmanager
from contextvars import ContextVar
import numpy as np
import cv2
from pathlib import Path
import hashlib
import time
import cv2
import numpy as np
import contextvars,hashlib,threading,time
import cv2,numpy as np
import ctypes, hashlib, json, platform, shutil, subprocess, sys, shlex, threading, time, weakref, math
import copy,hashlib
from dataclasses import dataclass
from contextvars import copy_context
import hashlib,threading,time
import cv2,numpy as np
from contextvars import copy_context
import hashlib,os,signal,subprocess,tempfile,threading,time
import ctypes,hashlib,json,os,platform,shutil,struct,threading,time
import hashlib,math,time
from functools import wraps
import hashlib,math
import hashlib,time,threading
import hashlib,threading
import os
import hashlib
import ctypes, hashlib, json, platform, shutil, subprocess, sys, shlex, threading, time, weakref, math
import hashlib,time
from collections import deque
import math
import operator
from threading import Lock
import ctypes,hashlib,platform,shutil,subprocess,threading,time
import ctypes, hashlib, os, platform, shutil, subprocess, threading


_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ======================================================================
# ===== [01/28] v31_detection =====
# ======================================================================


"""Multicolor rectangles: Y-first or sampled color bands verify all four exterior edges.

First/reacquisition use small color proposals. Normal frames use raw Y first;
weak Y proof may sample bounded raw chroma bands from the same leased frame.
Hue-independent exterior gradients precede white components; never partially refined H.
"""
from core import RELEASE_ID as RELEASE_ID
from geometry import find_paper_quad as find_paper_quad
from geometry import refine_edges as refine_edges
from geometry import order_corners as order_corners
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class QuadDetectionError(ValueError):
    def __init__(self,message,diagnostics):
        super().__init__(message);self.diagnostics=dict(diagnostics)

class _DetectionStop(RuntimeError):
    """Internal cooperative stop; candidate rejection must not swallow it."""

_RECOVERY_BUDGET=ContextVar('p11_recovery_detection_budget',default=None)
_ACQUIRE_CANCEL=ContextVar('p11_acquire_cooperative_cancel',default=None)
_RECOVERY_OBSERVATION=ContextVar('p11_current_Y_observation',default=None)
_RECOVERY_OFFSET=ContextVar('p11_recovery_view_offset',default=(0,0))
_RECOVERY_SEEDS=ContextVar('p11_recent_coarse_candidate_slice',default=None)

class RecoveryBudget:
    def __init__(self,milliseconds,max_candidates,begin=None,begin_cpu=None):
        now=time.perf_counter();cpu=time.thread_time()
        self.begin=now if begin is None else float(begin)
        self.begin_cpu=cpu if begin_cpu is None else float(begin_cpu)
        self.pre_detection_s=max(0.,now-self.begin)
        self.deadline=self.begin+milliseconds/1000.
        self.stage_begin=self.begin;self.stage_cpu=self.begin_cpu;self.stages={}
        self.milliseconds=float(milliseconds);self.max_candidates=int(max_candidates)
        self.candidates=0;self.last_stage='begin';self.stopped=None;self.proposals=[];self.rejections=[];self.admission_active=False
        self.completed_gate_after_deadline=0
    def _stages(self,now,cpu):
        result={k:dict(v) for k,v in self.stages.items()}
        row=result.setdefault(self.last_stage,dict(wall_s=0.,thread_cpu_s=0.,calls=0))
        row['wall_s']+=now-self.stage_begin;row['thread_cpu_s']+=cpu-self.stage_cpu;row['calls']+=1
        return result
    def check(self,stage,finish_gate=False):
        now=time.perf_counter();cpu=time.thread_time()
        # Mutate one interval; copying all nested stage dictionaries at every
        # polygon/profile checkpoint costs time and adds short-lived objects.
        row=self.stages.setdefault(self.last_stage,dict(wall_s=0.,thread_cpu_s=0.,calls=0))
        row['wall_s']+=now-self.stage_begin;row['thread_cpu_s']+=cpu-self.stage_cpu;row['calls']+=1
        self.stage_begin=now;self.stage_cpu=cpu;self.last_stage=stage
        if finish_gate:
            if not self.admission_active:raise RuntimeError('Final gate without an admitted candidate')
            self.completed_gate_after_deadline+=int(now>=self.deadline)
            return  # Finish only the already-refined candidate's safety gate.
        if stage!='candidate_admission' and not self.admission_active and self.candidates>=self.max_candidates:
            self.stopped='candidate_limit'
            raise _DetectionStop('恢复检测达到候选上限')
        if time.perf_counter()>=self.deadline:
            self.stopped='cooperative_deadline'
            raise _DetectionStop('恢复检测达到协作时间预算')
    def claim(self,label,coarse):
        self.check('candidate_admission')
        if self.candidates>=self.max_candidates:
            self.stopped='candidate_limit'
            raise _DetectionStop('恢复检测达到候选上限')
        self.candidates+=1
        self.proposals.append(dict(detector=label,coarse_corners=np.asarray(coarse).tolist()))
    def summary(self):
        now=time.perf_counter();cpu=time.thread_time();elapsed=now-self.begin
        return dict(budget_ms=self.milliseconds,max_candidates=self.max_candidates,
            candidates=self.candidates,elapsed_s=elapsed,thread_cpu_s=cpu-self.begin_cpu,
            pre_detection_s=max(0.,self.begin-getattr(self,'tracker_begin',self.begin)),whole_tracker_budget=False,
            detector_elapsed_s=elapsed,total_tracker_budget_ms=getattr(self,'tracker_budget_ms',None),
            total_tracker_elapsed_s=now-getattr(self,'tracker_begin',self.begin),
            wall_minus_thread_cpu_s=max(0.,elapsed-cpu+self.begin_cpu),stages=self._stages(now,cpu),
            stage_scope="exclusive checkpoint intervals, including CV calls and host wrapper; no double addition",
            overshoot_s=max(0.,elapsed-self.milliseconds/1000.),
            stop_reason=self.stopped,last_stage=self.last_stage,candidate_proposals=list(self.proposals),rejected_candidates=list(self.rejections),
            completed_gate_after_deadline=self.completed_gate_after_deadline,
            deadline_kind='cooperative_between_CV_operations; a running call and final safety gate are not preempted')

@contextmanager
def recovery_detection_scope(budget,observation=None):
    token=_RECOVERY_BUDGET.set(budget);obs_token=_RECOVERY_OBSERVATION.set(observation)
    offset_token=_RECOVERY_OFFSET.set((0,0))
    try:yield
    finally:
        _RECOVERY_OFFSET.reset(offset_token);_RECOVERY_OBSERVATION.reset(obs_token);_RECOVERY_BUDGET.reset(token)

@contextmanager
def recovery_candidate_scope(seeds=(),seed_only=False):
    # Coarse coordinates only. No source image, H or safety receipt is reused.
    value=dict(seeds=tuple(seeds),seed_only=bool(seed_only)) if seeds or seed_only else None
    token=_RECOVERY_SEEDS.set(value)
    try:yield
    finally:_RECOVERY_SEEDS.reset(token)

@contextmanager
def recovery_view_scope(offset):
    token=_RECOVERY_OFFSET.set(tuple(offset))
    try:yield
    finally:_RECOVERY_OFFSET.reset(token)

@contextmanager
def detection_cancel_scope(check):
    # Scoped to the acquisition worker, without changing its detector schedule,
    # thresholds or the already-existing recovery-budget checks.
    token=_ACQUIRE_CANCEL.set(check)
    try:yield
    finally:_ACQUIRE_CANCEL.reset(token)

def _budget_check(stage,finish_gate=False):
    cancel=_ACQUIRE_CANCEL.get()
    if cancel is not None:cancel()
    budget=_RECOVERY_BUDGET.get()
    if budget is not None:budget.check(stage,finish_gate=finish_gate)

def _small_color(image,work_width):
    h,w=image.shape[:2];width=min(w,max(16,int(work_width)))
    if image.ndim==3 and image.shape[2]==2:
        from core import require_yuyv as require_yuyv; from core import model_bgr as model_bgr
        require_yuyv(image);width=max(2,(width//2)*2)
        height=max(2,int(round(h*width/float(w))))
        pairs=image.reshape(h,w//2,4)
        reduced=cv2.resize(pairs,(width//2,height),interpolation=cv2.INTER_LINEAR) if width<w else pairs
        return model_bgr(np.ascontiguousarray(reduced).reshape(reduced.shape[0],width,2))
    height=max(2,int(round(h*width/float(w))))
    return cv2.resize(image,(width,height),interpolation=cv2.INTER_LINEAR) if width<w else image

def _visible_quad(quad,shape,preserve_order=False):
    # Coarse polygons need sorting. A measured/tracked cyclic order is a
    # physical corner correspondence and must survive rotation/refinement.
    q=np.ascontiguousarray(quad,np.float32) if preserve_order else order_corners(quad)
    if q.shape!=(4,2):raise ValueError('candidate_four_corner_shape_invalid')
    h,w=shape[:2]
    if (not np.isfinite(q).all() or np.any(q<2) or np.any(q[:,0]>w-3) or np.any(q[:,1]>h-3)):
        raise ValueError('candidate_touches_image_border_or_is_clipped')
    if not cv2.isContourConvex(q) or abs(cv2.contourArea(q))<.035*w*h:
        raise ValueError('candidate_not_convex_or_area_too_small')
    edges=np.roll(q,-1,axis=0)-q;lengths=np.linalg.norm(edges,axis=1)
    if lengths.min()<max(12.,.04*min(h,w)) or lengths.min()/lengths.max()<.10:
        raise ValueError('candidate_collapsed_short_edge')
    sine=np.abs(np.cross(edges,np.roll(edges,1,axis=0)))/(lengths*np.roll(lengths,1))
    if np.min(sine)<.15:raise ValueError('candidate_nearly_collinear_corner')
    return q

def exterior_gate(evidence,candidate,proposal,radius,require_light=False):
    """Independent four-edge gate; not relative to a potentially bad old anchor."""
    support=evidence.get('edge_support',[0.]*4);rms=evidence.get('edge_rms',[1e30]*4)
    correction=float(np.max(np.linalg.norm(np.asarray(candidate)-proposal,axis=1)))
    positive=sum(p>0 for p in evidence.get('edge_polarity',[]))
    valid=(evidence.get('valid',False) and evidence.get('supported_edges',0)==4
           and evidence.get('refined_corners',0)==4 and min(support)>=.60
           and max(rms)<=1. and correction<=radius*.65
           and (not require_light or positive>=3))
    return dict(reliable=bool(valid),min_support=float(min(support)),max_rms=float(max(rms)),
                prediction_correction=correction,positive_edges=positive,radius=radius,
                supported_edges=evidence.get('supported_edges',0),refined_corners=evidence.get('refined_corners',0))

def _contour_proposals(gray,limit,incremental=False):
    proposals=_iter_contour_proposals(gray,limit)
    if incremental:return proposals
    return sorted(list(proposals),key=lambda q:abs(cv2.contourArea(q)),reverse=True)[:12]

def _iter_contour_proposals(gray,limit):
    h,w=gray.shape;scale=min(1.,float(limit)/max(h,w));ow,oh=round(w*scale),round(h*scale)
    view=cv2.resize(gray,(ow,oh),interpolation=cv2.INTER_LINEAR) if scale<1 else gray
    blur=cv2.GaussianBlur(view,(5,5),0);candidates=[]
    for low,high in ((15,50),(50,150)):
        _budget_check("Y_contours")
        edges=cv2.dilate(cv2.Canny(blur,low,high),np.ones((3,3),np.uint8))
        contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        for c in sorted(contours,key=cv2.contourArea,reverse=True)[:20]:
            _budget_check("Y_contour_polygon")
            if abs(cv2.contourArea(c))<.035*ow*oh:continue
            for epsilon in (.012,.022,.04):
                polygon=cv2.approxPolyDP(c,epsilon*cv2.arcLength(c,True),True)
                if len(polygon)!=4 or not cv2.isContourConvex(polygon):continue
                try:q=_visible_quad((order_corners(polygon)+.5)*[w/ow,h/oh]-.5,gray.shape)
                except ValueError:continue
                if not any(np.max(np.linalg.norm(q-old,axis=1))<4. for old in candidates):
                    candidates.append(q);yield q
                break
    return

def _color_proposals(color,source_shape):
    """Adaptive whiteness components, including less neutral white balance.

    Reject border-connected distractors separately rather than assuming the
    largest component is the paper. These are proposals, not accepted corners.
    """
    h,w=color.shape[:2];H,W=source_shape[:2]
    white=np.min(color,axis=2).astype(np.uint8)
    threshold,_=cv2.threshold(white,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
    _budget_check('color_statistics')
    saturation=cv2.cvtColor(color,cv2.COLOR_BGR2HSV)[:,:,1]
    bright=white>threshold
    if not bright.any():return []
    # 256-bin integer percentile avoids a float image and selection workspace.
    mask=bright.astype(np.uint8)*255
    hist=cv2.calcHist([saturation],[0],mask,[256],[0,256]).ravel().astype(np.int64)
    cumulative=hist.cumsum();rank=.8*(int(cumulative[-1])-1)
    lo=int(np.searchsorted(cumulative,int(np.floor(rank))+1))
    hi=int(np.searchsorted(cumulative,int(np.ceil(rank))+1))
    percentile=lo+(hi-lo)*(rank-np.floor(rank))
    adaptive=float(np.clip(percentile/255.+.04,.12,.55))
    candidates=[]
    for cutoff in dict.fromkeys((adaptive,min(.55,adaptive+.12))):
        _budget_check("color_components")
        mask=(bright&(saturation<=cutoff*255.)).astype(np.uint8)*255
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        count,labels,stats,_=cv2.connectedComponentsWithStats(mask,8)
        for label in sorted(range(1,count),key=lambda k:stats[k,cv2.CC_STAT_AREA],reverse=True)[:8]:
            _budget_check("color_polygon")
            x,y,cw,ch,area=stats[label]
            if area<.035*w*h or x<2 or y<2 or x+cw>w-2 or y+ch>h-2:continue
            contours,_=cv2.findContours((labels==label).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            if not contours:continue
            contour=cv2.convexHull(max(contours,key=cv2.contourArea))
            for epsilon in (.012,.022,.04,.065):
                polygon=cv2.approxPolyDP(contour,epsilon*cv2.arcLength(contour,True),True)
                if len(polygon)!=4:continue
                try:q=_visible_quad((order_corners(polygon)+.5)*[W/w,H/h]-.5,source_shape)
                except ValueError:continue
                if not any(np.max(np.linalg.norm(q-old,axis=1))<3 for old in candidates):candidates.append(q)
                break
    return sorted(candidates,key=lambda q:abs(cv2.contourArea(q)),reverse=True)[:8]

def detect_refined(image,limit=640,refine=True,prefer_mask=True,color_reference=None,tracking_limit=320):
    budget=_RECOVERY_BUDGET.get()
    try:return _detect_refined(image,limit,refine,prefer_mask,color_reference,tracking_limit)
    except _DetectionStop as exc:
        detail=dict(reason=str(exc),recovery_budget=budget.summary(),input_shape=list(image.shape))
        from core import checkpoint as checkpoint
        if getattr(budget,'log_detail',True):checkpoint('RECOVERY_DETECTION_STOPPED',**detail)
        else:
            checkpoint('RECOVERY_DETECTION_STOPPED',reason=str(exc),recovery_budget=compact_recovery_summary(detail['recovery_budget']),input_shape=detail['input_shape'])
        raise QuadDetectionError(str(exc),detail) from exc

def current_boundary(image,gray,scale,quad,offset=(0,0),measured=None,evidence=None,checks='auto',allow_color=True,radius=3.,fast_only=False,deadline=None,expected_polarity=None,color_profiles=24,prefer_color=False,prefer_vector=False,source_validated=False,boundary_prior=None):
    """Current exterior: Y fast path or one bounded fused raw-color transaction.

    prefer_color is a request for an actual independent source64 proof; an
    expired call cannot return ordinary small-Y evidence as that proof.
    prefer_vector keeps color recovery continuous without full-frame CSC.
    """
    from geometry import refine_boundary as refine_boundary; from geometry import original_y_boundary as original_y_boundary
    from geometry import array_key as array_key
    begin=time.perf_counter();cpu=time.thread_time()
    scale=np.asarray(scale,np.float64);origin=np.asarray(offset,np.float64);q=np.asarray(quad,np.float32)
    if scale.shape!=(2,) or not np.isfinite(scale).all() or np.any(scale<=0):raise ValueError('Boundary scale invalid')
    required64=bool(prefer_color);profiles=64 if required64 else color_profiles
    key=array_key(image)
    def validate(e,c):
        gate=exterior_gate(e,c,q,radius)
        flips=0 if expected_polarity is None or e.get('color_vector_proof') else sum(a*b<0 for a,b in zip(expected_polarity,e.get('edge_polarity',[])))
        actual64=(e.get('same_frame_source') and e.get('profiles_per_edge')==64
            and e.get('current_source_key')==key and e.get('source_proof_kind') in ('raw_YUV_profiles','source_color_profiles','source_Y_profiles'))
        gate.update(polarity_flips=flips,actual_source64=bool(actual64),
            reliable=bool(gate['reliable'] and flips<2 and (not required64 or actual64)))
        return gate
    def detail(e,backend):
        e=dict(e);e.update(edge_backend=backend,initial_Y_gate=initial_gate,
            boundary_fallback_s=time.perf_counter()-begin,boundary_fallback_thread_cpu_s=time.thread_time()-cpu)
        return e
    def available():return deadline is None or time.perf_counter()<deadline
    if measured is None or evidence is None:measured,evidence=edge_measure__v87_v74_tracking(gray,q,radius,checks)
    evidence=dict(evidence,current_source_key=key);gate=validate(evidence,measured);initial_gate=dict(gate)
    # V49: a reliable current Y fit finishes the ordinary transaction.
    # A historical colour-family hint does not force new colour sampling.
    if gate['reliable'] and not required64:return measured,evidence,gate
    color_attempted=False
    def vector():
        local=_visible_quad((q+.5)*scale-.5-origin,image.shape,preserve_order=True)
        candidate,e=refine_boundary(image,local,max(2.5,min(24.,radius*float(scale.max()))),profiles=profiles,
            max_rms=float(scale.min()),minimum_contrast=8.,fraction_limits=(.12,.88) if profiles==24 else (.10,.90),deadline=deadline,boundary_prior=boundary_prior)
        observed=((candidate+origin+.5)/scale-.5).astype(np.float32)
        e['edge_rms']=[float(v)/float(scale.min()) for v in e['edge_rms']]
        e.update(tracking_roi_offset=origin.tolist(),direct_Y_primary=True,fast_path_chroma_allowed=True)
        e=detail(e,'sampled_current_YUV'+str(profiles));return observed,e,validate(e,observed)
    color_available=allow_color and image.ndim==3 and image.shape[2] in (2,3)
    if color_available and (prefer_vector or source_validated) and available():
        measured,evidence,gate=vector();color_attempted=True
        if gate['reliable']:return measured,evidence,gate
        # A current vector proof uses one definition; another Y crossing is
        # not a substitute when this physical boundary failed or timed out.
        evidence=dict(evidence,valid=False,vector_family_rejected=True)
        return measured,evidence,validate(evidence,measured)
    # An accepted original candidate already has its source64 proof. Do not
    # repeat that proof during its independent current24 safety gate.
    if not source_validated and available():
        proof=original_y_boundary(image,scale,q,offset,radius)
        if proof is not None:
            candidate,e=proof;g=validate(e,candidate)
            if g['reliable']:return candidate,detail(e,'cpp_current_source_Y64'),g
            if required64:measured,evidence,gate=candidate,e,g
    if color_available and not color_attempted and available():
        measured,evidence,gate=vector()
        if gate['reliable']:return measured,evidence,gate
    if required64:
        # Clearing validity is essential: callers also recompute _edge_gate.
        failed=detail(evidence,'source64_required_not_verified')
        failed.update(valid=False,refined_corners=0,supported_edges=0,source64_missing_or_rejected=True)
        return measured,failed,validate(failed,measured)
    if fast_only or source_validated or not available():
        return measured,detail(evidence,evidence.get('edge_backend','current_Y_or_YUV_fast')),gate
    robust,e=refine_boundary(gray,q,radius,profiles=24,max_rms=1.,minimum_contrast=8.,fraction_limits=(.10,.90),deadline=deadline)
    e.update(current_source_key=key)
    return robust,detail(e,'coherent_current_Y24'),validate(e,robust)


def _detect_refined(image,limit,refine,prefer_mask,color_reference,tracking_limit):
    began=time.perf_counter();raw=image.ndim==3 and image.shape[2]==2
    budget=_RECOVERY_BUDGET.get();_budget_check('source_Y_prepare')
    h,w=image.shape[:2];gray=None
    def source_gray():
        nonlocal gray
        if gray is None:
            _budget_check('lazy_source_Y_fallback')
            from core import luminance as luminance
            gray=luminance(image) if raw else image if image.ndim==2 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        return gray
    observation=dict(input_shape=list(image.shape),gray_source='direct_Y' if raw else 'BGR_or_gray',
        color_assist_used=False,color_assist_requested=bool(prefer_mask),detection_limit=limit,
        coarse_interpolation='INTER_LINEAR',target_policy='multicolor_planar_rectangle',
        fixed_hue_required=False,positive_edges_required=False)
    mask_detail={};failures=[];proposals=[];color=None
    search_limit=min(limit,320) if budget is not None else limit
    work_width=max(16,min(256,round(search_limit*w/max(h,w))))
    from geometry import rectangle_proposals__v41_quad as rectangle_proposals; from geometry import refine_boundary as refine_boundary
    color_input=color_reference if color_reference is not None else image
    def prepare_color():
        nonlocal color
        if color is None:
            _budget_check('color_proposal_prepare')
            src=cv2.cvtColor(color_input,cv2.COLOR_GRAY2BGR) if color_input.ndim==2 else color_input
            color=_small_color(src,work_width)
            observation.update(color_work_shape=list(color.shape),color_assist_used=True)
        return color
    # V48: no eager Lab collection before a candidate can reach admission.
    observation['proposal_schedule']='bounded_YUV_outer_enclosure_pool_then_Y_then_bounded_Lab'
    mask_detail['proposal_method']='YUV_gradient_stream_with_original_four_edge_proof' 
    mask_s=time.perf_counter()-began
    _budget_check('tracking_observation')
    reused=_RECOVERY_OBSERVATION.get() if budget is not None else None
    offset=np.asarray(_RECOVERY_OFFSET.get(),np.float32)
    if reused is None:
        observer=GrayObserver__v87_v74_tracking(tracking_limit)
        tracked_gray,tracking_scale=observer.get(image if image.ndim==3 else cv2.cvtColor(image,cv2.COLOR_GRAY2BGR))
        offset[:]=0.;observation['tracking_observation_reused']=False
    else:
        tracked_gray=reused['gray'];tracking_scale=reused['scale']
        if (tracked_gray.ndim!=2 or tracked_gray.dtype!=np.uint8 or np.shape(tracking_scale)!=(2,)
            or not np.isfinite(tracking_scale).all() or np.any(tracking_scale<=0) or np.any(offset<0)
            or offset[0]+w>reused['source_shape'][1] or offset[1]+h>reused['source_shape'][0]):
            raise ValueError('Current Y recovery observation/ROI layout mismatch')
        observation.update(tracking_observation_reused=True,tracking_source_shape=list(reused['source_shape']),tracking_roi_offset=offset.tolist())
    attempted=[];proven_outer=[]
    duplicate_attempts=CandidateAttempts() if budget is not None else None
    def admit(label,coarse):
        from geometry import proven_outer_parent as proven_outer_parent
        parent=proven_outer_parent(coarse,proven_outer)
        if parent is not None:
            failures.append(dict(detector=label,reason='internal_rectangle_has_current_proven_outer',boundary_selection=parent))
            return None
        if budget is not None:budget.claim(label,coarse)
        q=_visible_quad(coarse,image.shape);attempted.append(q.copy())
        half=min(24.,max(6.,.008*max(h,w),2.5*max(h/192.,w/256.)))
        def accepted(e):return (e.get('refined_corners')==4 and len(e.get('edges',[]))==4
            and all(x.get('accepted',False) and x.get('supported',0)>=38 for x in e['edges']))
        result=q;edges={};original=None;attempts=[]
        color_first=prefer_mask and ('multicolor' in label)
        color_attempted=False
        def color_refine():
            _budget_check('original_YUV_band_refinement')
            # Prefer raw YUYV vectors when available: no RGB clipping of a red edge.
            source=image if raw else color_reference if color_reference is not None else image
            if source.shape[:2]!=image.shape[:2]:raise ValueError('Color reference belongs to a different source layout')
            return refine_boundary(source,q,half,deadline=None if budget is None else budget.deadline)
        if color_first and image.ndim==3:
            result,edges=color_refine();color_attempted=True
            attempts.append(dict(backend='coherent_original_YUV64',refinement_s=edges['refinement_s'],refined_corners=edges['refined_corners']))
        if not accepted(edges):
            _budget_check('original_Y_edge_refinement')
            native=refine_original_yuyv64__v87_v74_native(image,q,half) if raw else refine_original_y64__v87_v74_native(source_gray(),q,half)
            if native is None:
                c=time.thread_time();result,edges=refine_edges(source_gray(),q,half_window=half)
                edges.update(backend='python_original_Y_64x65',refinement_thread_cpu_s=time.thread_time()-c)
            else:result,edges=native
            original=edges
            attempts.append(dict(backend=edges.get('backend'),refinement_s=edges.get('refinement_s',0.),refined_corners=edges.get('refined_corners',0)))
        if not accepted(edges) and prefer_mask and image.ndim==3 and not color_attempted:
            result,edges=color_refine();color_attempted=True
            attempts.append(dict(backend='coherent_original_YUV64',refinement_s=edges['refinement_s'],refined_corners=edges['refined_corners']))
        if not accepted(edges):
            _budget_check('original_Y_coherent_refinement')
            result,edges=refine_boundary(source_gray(),q,half)
            attempts.append(dict(backend='coherent_original_Y64',refinement_s=edges['refinement_s'],refined_corners=edges['refined_corners']))
        edges.update(refinement_attempts=attempts,refinement_attempt_wall_s=sum(a['refinement_s'] for a in attempts),
            original_Y_attempt=original if original is not None and not accepted(original) else None)
        if not accepted(edges):
            failures.append(dict(detector=label,reason='all_four_original_edges_required',corners=q.tolist(),edge_refinement=edges));return None
        result=_visible_quad(result,image.shape,preserve_order=True)
        _budget_check('current_four_edge_gate',finish_gate=budget is not None)
        from geometry import proof_band as proof_band; from geometry import line_lock as line_lock; from geometry import sample_locked_color as sample_locked_color; from geometry import detector_source64 as detector_source64; from geometry import current_agreement as current_agreement; from geometry import declare_current_y24 as declare_current_y24
        from geometry import array_key as array_key
        from geometry import border_signature as border_signature
        measured=(result+offset+.5)/tracking_scale-.5
        original=detector_source64(image,tracking_scale,edges,derived_gray=gray)
        if original['valid'] and min(original['edge_support'])>=.80 and max(original['edge_rms'])<=.65:
            proven_outer.append(result.copy())
        narrow,half_proof=proof_band(tracking_scale,original)
        # Independent CURRENT24 samples remain on the already selected source
        # primary line. They cannot restart a broad Y/colour crossing search.
        checked,evidence=sample_locked_color(image,tracking_scale,measured,24,
            None if budget is None else budget.deadline,border_signature(edges),
            half_source=half_proof,offset=offset,lock_evidence=original)
        gate=exterior_gate(evidence,checked,measured,3.);lock=line_lock(measured,checked)
        current=declare_current_y24(evidence)
        agreement=current_agreement(checked,measured,current,original,tracking_scale,array_key(image))
        if current.get('profiles_per_edge')!=24:agreement.update(verified=False,reason='detector_independent24_grid_required')
        if not gate['reliable'] or not lock['verified'] or not agreement['verified']:
            failures.append(dict(detector=label,reason='current_observation_left_original_source_line',corners=q.tolist(),
                original_refined_corners=result.tolist(),gate=gate,line_lock=lock,agreement=agreement,edge_evidence=evidence));return None
        source=result+offset
        if reused is not None:_visible_quad(source,reused['source_shape'],preserve_order=True)
        # A receipt for the secondary intersections would falsely bind their
        # evidence to different returned corners. Revalidate in the caller.
        receipt=(issue_current_receipt(reused,image,source,original,current,checked,
            tracking_scale,agreement,gate) if not np.any(offset) else None)
        from geometry import issue_startup_receipt as issue_startup_receipt
        startup_receipt=(issue_startup_receipt(image,result,original,current,checked,
            tracking_scale,agreement,gate) if not np.any(offset) else None)
        evidence=dict(original,original_source_line_retained=True,current_line_lock=lock,
            current_independent24_agreement=agreement)
        return result,dict(observation,_current_boundary_receipt=receipt,_initial_boundary_receipt=startup_receipt,detector=label,edge_refinement=edges,tracking_validation=gate,
            tracking_edge_evidence=evidence,boundary_selection=dict(policy='source_primary_outer_lines',
                original_source_corners=result.tolist(),independent_current_corners=checked.tolist(),
                line_lock=lock,source64_independent24=agreement,proof_half_source_pixels=half_proof,
                proven_outer_hypotheses=len(proven_outer)),mask_s=mask_s,mask_diagnostics=mask_detail,rejected_candidates=failures,
            area_ratio=float(abs(cv2.contourArea(result))/(w*h)),detection_s=time.perf_counter()-began,
            recovery_budget=None if budget is None else budget.summary())
    def try_admit(label,q):
        if duplicate_attempts is not None and duplicate_attempts.repeated(q,prefer_mask and 'multicolor' in label):
            budget.candidate_duplicate_skips=duplicate_attempts.repeats
            observation['candidate_duplicate_skips']=duplicate_attempts.repeats
            return None
        if any(np.max(np.linalg.norm(np.asarray(q)-old,axis=1))<2. for old in attempted):return None
        before=len(failures)
        if budget is not None:budget.admission_active=True
        try:result=admit(label,q)
        except (ValueError,cv2.error) as exc:failures.append(dict(detector=label,reason=str(exc)));result=None
        finally:
            if budget is not None:budget.admission_active=False
        if budget is not None and result is None:budget.rejections.extend(failures[before:])
        return result
    try:
        saved=_RECOVERY_SEEDS.get()
        if saved is not None:
            observation['proposal_schedule']='recent_coarse_hint_current_source_reproof'
            observation['recent_candidate_slice']=True
            for seed in saved['seeds']:
                _budget_check('recent_candidate_current_admission')
                coarse=np.asarray(seed.get('coarse_corners'),np.float32)
                if coarse.shape!=(4,2) or not np.isfinite(coarse).all():continue
                result=try_admit('v67_recent_'+str(seed.get('detector','multicolor_exterior')),coarse)
                if result is not None:return result
            if saved['seed_only']:
                if budget is not None:budget.stopped='recent_candidate_slice_miss'
                raise _DetectionStop('候选复用片段未通过当前四边准入；后续请求继续或扩大搜索')
        if budget is not None:
            current=None if reused is None else reused.get('verified_edge_proposal')
            if current is not None:
                local=np.asarray(current,np.float32)-offset
                try:local=_visible_quad(local,image.shape)
                except ValueError:local=None
                if local is not None:
                    result=try_admit('current_exterior_original_verified',local)
                    if result is not None:return result
        if prefer_mask:
            from geometry import exterior_candidates as exterior_candidates
            # Keep at least one admission for a different proposal family.
            # Previously a pair of rejected nested color contours exhausted
            # the ordinary two-candidate budget before Y had any opportunity.
            color_limit=None if budget is None else max(1,budget.max_candidates//2)
            observation['color_candidate_limit']=color_limit
            for q in exterior_candidates(image,_budget_check,192):
                if budget is not None and budget.candidates>=color_limit:break
                result=try_admit('stream_multicolor_exterior',q)
                if result is not None:return result
        if budget is not None:
            _budget_check('next_current_Y_search')
            small=tracked_gray
            y_limit=budget.max_candidates  # consume the remaining Y admissions; heavy fallback requires spare budget
            observation['Y_admission_limit_before_color']=y_limit
            for proposal in (_contour_proposals(small,min(240,search_limit),incremental=True) if budget.candidates<y_limit else ()):
                q=(proposal+.5)*tracking_scale-.5-offset
                try:q=_visible_quad(q,image.shape)
                except ValueError:continue
                result=try_admit('current_Y_contour_verified',q)
                if result is not None:return result
                if budget.candidates>=y_limit:break
            if prefer_mask:
                from geometry import iter_recovery_rectangles as iter_recovery_rectangles
                permit=getattr(budget,'can_start_stage',None)
                cheap_ok=permit('Lab_contour',.025,.04) if permit is not None else budget.deadline-time.perf_counter()>=.16
                if cheap_ok:
                    allow_lines=lambda:permit('Hough160',.10,.14) if permit is not None else budget.deadline-time.perf_counter()>=.26
                    observation.update(color_fallback_used=True,color_proposal_schedule='immediate_contour_admission_then_budgeted_Hough160')
                    # Generator yields into the unchanged strict admit function.
                    # A successful cheap contour returns before Hough is called.
                    for q in iter_recovery_rectangles(prepare_color(),image.shape,_budget_check,allow_lines,max_candidates=8):
                        result=try_admit('multicolor_gradient_rectangle',q)
                        if result is not None:return result
                else:observation['heavy_color_fallback_deferred']='insufficient_compute_or_wall_for_search_plus_admission'
        for label,q in proposals:
            result=try_admit(label,q)
            if result is not None:return result
        if prefer_mask and budget is None:
            # Full startup may use heavier Lab/line fallback only after streams.
            for q in rectangle_proposals(prepare_color(),image.shape,_budget_check,max_candidates=12,include_lines=True):
                result=try_admit('multicolor_line_fallback',q)
                if result is not None:return result
        # White paper remains a fallback, not a universal definition of a target.
        if prefer_mask and color is not None and budget is None:
            _budget_check('legacy_paper_fallback')
            proposal=find_paper_quad(color,work_width=color.shape[1],camera_color=True,diagnostics=mask_detail)
            if proposal is not None:
                q=(np.asarray(proposal,np.float32)+.5)*[w/color.shape[1],h/color.shape[0]]-.5
                result=try_admit('p1_camera_white_fallback',q)
                if result is not None:return result
            for q in _color_proposals(color,image.shape):
                result=try_admit('adaptive_white_fallback',q)
                if result is not None:return result
        coarse_limit=min(search_limit,max(160,round(max(h,w)/3.)))
        for contour_limit in dict.fromkeys((coarse_limit,search_limit)):
            for proposal in _contour_proposals(tracked_gray,contour_limit):
                q=(proposal+.5)*tracking_scale-.5-offset
                result=try_admit('Y_contour_verified',q)
                if result is not None:return result
    except (ValueError,cv2.error) as exc:failures.append(dict(detector='candidate_validation',reason=str(exc)))
    from core import checkpoint as checkpoint
    detail=dict(observation,mask_s=mask_s,mask_diagnostics=mask_detail,rejected_candidates=failures,
        contour_or_refinement_reason='no_candidate_with_four_verified_exterior_edges',detection_s=time.perf_counter()-began,
        recovery_budget=None if budget is None else budget.summary())
    if budget is None or getattr(budget,'log_detail',True):checkpoint('DOCUMENT_DETECTION_FAILED',**detail)
    else:
        checkpoint('DOCUMENT_DETECTION_FAILED',reason=detail['contour_or_refinement_reason'],recovery_budget=compact_recovery_summary(detail['recovery_budget']))
    raise QuadDetectionError('未找到四条可信矩形外边缘；不提交错误 H。请查看候选与四边诊断。',detail)


# ======================================================================
# ===== [02/28] v31_tracking =====
# ======================================================================


"""Per-frame paper edges first; confidence-triggered predicted sparse LK.

Coordinates returned to the caller are original BGR pixel coordinates. No PL
access occurs here. A failed reacquisition returns valid=False, never stale H.
"""
from core import RELEASE_ID as RELEASE_ID
from core import luminance as luminance; from core import model_bgr as model_bgr; from core import gray_half as gray_half

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class LKExteriorMismatch__v31_tracking(ValueError):
    """FB/motion fit succeeded, but the CURRENT exterior did not verify it."""

class GrayObserver__v31_tracking:
    """Reuse three gray slots; pinned anchor and last observation stay intact."""
    def __init__(self, limit, backend='auto', gaussian_backend='auto'):
        if backend not in ('auto','legacy'):raise ValueError('gray_backend须为auto/legacy')
        if gaussian_backend not in ('auto','legacy'):raise ValueError('gaussian_backend须为auto/legacy')
        self.limit,self.backend=limit,backend
        self.gaussian_backend=gaussian_backend
        self.blur_workspace=None
        self.scratch=None
        self.detail={};self.pool=[];self.pinned=None;self.last=None;self.merged_edges=None;self.merged_error=None
        self.timing=np.empty(2,np.float64)
        self._layout=None;self._scale=None;self._geometry=None
        self.transaction=ObservationWorkspace__v31_native()
    def pin(self,gray):self.pinned=gray
    def output(self,shape):
        if not self.pool or self.pool[0].shape!=shape:self.pool=[np.empty(shape,np.uint8) for _ in range(3)]
        return next(a for a in self.pool if a is not self.pinned and a is not self.last)

    def get(self,image,edge_context=None):
        began=time.perf_counter();cpu=time.thread_time();h,w=image.shape[:2];self.merged_edges=None;self.merged_error=None
        self.transaction.decode_timing=(0.,0.)
        layout=(h,w,self.limit)
        if layout!=self._layout:
            scale=min(1.,self.limit/max(h,w));ow,oh=round(w*scale),round(h*scale)
            self._scale=np.frombuffer(np.array([w/ow,h/oh],np.float64).tobytes(),np.float64)
            self._geometry=(scale,ow,oh);self._layout=layout
        scale,ow,oh=self._geometry
        #   ⚠️ 2026-10-28：**这里一旦走慢路径，每帧要 60+ ms，而且日志里完全看不出来。**
        #      原生 fused 路径要求降采样**恰好 2 倍**（见下面几处 `(ow*2,oh*2)==(w,h)`）。
        #      600P（800x600）配 limit=320 时 scale=0.4 ⇒ 640x480 ≠ 800x600 ⇒ 退回
        #      OpenCV，实测 `observation_wrapper_s` **63 ms**，动态帧率从 15 掉到 5。
        #      480P 要 320、600P 要 400 —— 切档时务必同步改 `tracking_max_dim`。
        if not (ow*2,oh*2)==(w,h) and not getattr(self,'_slow_warned',False):
            self._slow_warned=True
            try:
                from core import checkpoint as _ck
                _ck('GRAY_OBSERVER_SLOW_PATH',warning='原生 fused 要求恰好 2 倍降采样',
                    image_shape=[h,w],limit=self.limit,gray_shape=[oh,ow],
                    fix='把 tracking_max_dim 设成 长边/2（640x480 ⇒ 320，800x600 ⇒ 400）')
            except Exception:
                pass
        if self.backend=='auto' and self.gaussian_backend=='auto' and (ow*2,oh*2)==(w,h):
            if self.scratch is None or self.scratch.shape!=(oh,ow):self.scratch=np.empty((oh,ow),np.uint8)
            if self.blur_workspace is None or self.blur_workspace.size<3*ow:self.blur_workspace=np.empty(3*ow,np.uint16)
            out=self.output((oh,ow));fused_result=None
            if edge_context is not None:
                merged=self.transaction.observe(image,self.scratch,self.blur_workspace,out,*edge_context)
                if merged is not None:
                    self.merged_edges,detail=merged;self.merged_error=detail.get('edge_error');fused_result=(out,detail)
            if fused_result is None:fused_result=fused_observation2__v31_native(image,self.scratch,self.blur_workspace,out,self.timing)
            if fused_result is not None:
                observation,detail=fused_result;elapsed=time.perf_counter()-began
                self.detail=dict(detail,backend='cpp_fused_area2_gaussian3',blur_backend='cpp_fixed_gaussian3',
                    shape=[oh,ow],gray_s=elapsed,
                    native_return_overhead_s=max(0.,elapsed-detail.get('native_transaction_s',detail['resize_gray_s']+detail['blur_s'])))
                self.detail['observation_transaction_s']=elapsed;self.detail['output_pool_reused']=True
                self.last=observation
                self.detail['thread_cpu_s']=time.thread_time()-cpu
                return observation,self._scale
        backend='opencv_area_then_gray';fused=False
        if self.backend=='auto' and (ow*2,oh*2)==(w,h):
            if self.scratch is None or self.scratch.shape!=(oh,ow):
                self.scratch=np.empty((oh,ow),np.uint8)
            fused=gray_area2__v31_native(image,self.scratch)
            if fused:gray=self.scratch;backend=native_status__v31_native().get('gray_backend','fused_area2')
        if not fused:
            if image.shape[2]==2:
                if (ow*2,oh*2)==(w,h):
                    if self.scratch is None or self.scratch.shape!=(oh,ow):self.scratch=np.empty((oh,ow),np.uint8)
                    gray=gray_half(image,self.scratch)
                else:
                    y=luminance(image);gray=cv2.resize(y,(ow,oh),interpolation=cv2.INTER_AREA) if scale<1 else y
                backend='direct_Y_normalized'
            else:
                view=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_AREA) if scale<1 else image
                gray=cv2.cvtColor(view,cv2.COLOR_BGR2GRAY)
        resize_s=time.perf_counter()-began;t=time.perf_counter()
        # Fresh blurred allocation is deliberate: anchor_gray must survive
        # intermediate frames and the native pyramid promotion.
        observation=None;blur_backend='opencv_gaussian3'
        if self.gaussian_backend=='auto':
            if self.blur_workspace is None or self.blur_workspace.size<3*ow:
                self.blur_workspace=np.empty(3*ow,np.uint16)
            observation=gaussian3__v31_native(gray,self.blur_workspace)
            if observation is not None:blur_backend=native_status__v31_native().get('blur_backend','cpp_gaussian3')
        if observation is None:observation=cv2.GaussianBlur(gray,(3,3),.6)
        self.detail=dict(backend=backend,blur_backend=blur_backend,shape=[oh,ow],resize_gray_s=resize_s,
                         blur_s=time.perf_counter()-t,gray_s=time.perf_counter()-began)
        self.last=observation
        self.detail['thread_cpu_s']=time.thread_time()-cpu
        return observation,self._scale

def _gray__v31_tracking(image,limit):
    return GrayObserver__v31_tracking(limit,'legacy').get(image)


def _valid__v31_tracking(q, shape, reference=None, checks='auto'):
    if checks=='auto':
        result=quad_valid__v31_native(q,shape,reference)
        if result is not None:return result
    q = np.asarray(q, np.float32).reshape(4, 2)
    h, w = shape[:2]
    if not np.isfinite(q).all() or not cv2.isContourConvex(q):
        return False
    if np.cross(q[1]-q[0], q[2]-q[1]) <= 0:
        return False
    area = abs(cv2.contourArea(q))
    if area < .035*w*h or np.any(q < 0) or np.any(q[:, 0] > w-1) or np.any(q[:, 1] > h-1):
        return False
    if reference is not None:
        old = abs(cv2.contourArea(np.asarray(reference, np.float32)))
        if not .55 < area/max(old, 1.) < 1.8:
            return False
    return True


def _edge_python__v31_tracking(gray, quad, radius=5., checks='auto'):
    """Sample 24 short normal profiles per OUTER paper edge, then intersect TLS lines."""
    q = np.asarray(quad, np.float64).reshape(4, 2)
    offsets = np.linspace(-radius, radius, 25)
    fractions = np.linspace(.055, .945, 24)
    center = q.mean(axis=0)
    lines, supports, shifts, polarity, rms_values = [], [], [], [], []
    for i in range(4):
        a, b = q[i], q[(i+1) % 4]
        edge = b-a
        normal = np.array([-edge[1], edge[0]]) / max(np.linalg.norm(edge), 1e-6)
        if np.dot(center-(a+b)*.5, normal) < 0:
            normal = -normal
        base = a + fractions[:, None]*edge
        xy = base[:, None, :] + offsets[None, :, None]*normal
        p = cv2.remap(gray, xy[..., 0].astype(np.float32), xy[..., 1].astype(np.float32),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        outer, inner = np.median(p[:, :4], axis=1), np.median(p[:, -4:], axis=1)
        contrast = inner-outer
        signed = (p-(outer+inner)[:, None]*.5)*np.where(contrast >= 0, 1., -1.)[:, None]
        crossing = (signed[:, :-1] <= 0) & (signed[:, 1:] > 0)
        scores = np.where(crossing, np.abs((offsets[:-1]+offsets[1:])*.5), np.inf)
        col = np.argmin(scores, axis=1)
        row = np.arange(len(base))
        before, after = signed[row, col], signed[row, col+1]
        alpha = np.clip(-before/np.maximum(after-before, 1e-6), 0., 1.)
        shift = offsets[col] + alpha*(offsets[col+1]-offsets[col])
        good = (np.abs(contrast) >= 8) & crossing.any(axis=1) & (np.abs(shift) < radius*.85)
        line = None
        rms = 1e30
        support = float(good.mean())
        if good.sum() >= 10 and np.ptp(fractions[good]) >= .55:
            points = base[good]+shift[good, None]*normal
            for _ in range(2):
                mean = points.mean(axis=0)
                n = _tls_normal__v31_tracking(points-mean)
                residual = np.abs((points-mean)@n)
                keep = residual <= max(.6, 2.5*float(np.median(residual)))
                if keep.all() or keep.sum() < 8:
                    break
                points = points[keep]
            mean = points.mean(axis=0)
            n = _tls_normal__v31_tracking(points-mean)
            rms = float(np.sqrt(np.mean(((points-mean)@n)**2)))
            if rms <= 1.25:
                line = np.r_[n, -n@mean]
        lines.append(line)
        rms_values.append(rms)
        supports.append(support if line is not None else 0.)
        shifts.append(float(np.median(np.abs(shift[good]))) if good.any() else radius)
        median_contrast = float(np.median(contrast))
        polarity.append(int(np.sign(median_contrast)) if abs(median_contrast) >= 8 else 0)
    corrected = q.copy()
    refined = 0
    for i in range(4):
        if lines[i-1] is None or lines[i] is None:
            continue
        cross = np.cross(lines[i-1], lines[i])
        if abs(cross[2]) > .06:
            point = cross[:2]/cross[2]
            if np.linalg.norm(point-q[i]) < radius*2.8:
                corrected[i] = point
                refined += 1
    supported_edges = sum(s >= .42 for s in supports)
    valid = supported_edges >= 3 and refined >= 2 and _valid__v31_tracking(corrected, gray.shape, q, checks)
    return corrected.astype(np.float32), dict(valid=bool(valid), supported_edges=supported_edges,
        edge_support=supports, edge_polarity=polarity, refined_corners=refined,
        median_edge_shift=float(np.median(shifts)),edge_rms=rms_values,max_edge_rms=max(rms_values))



def _tls_normal__v31_tracking(centered):
    xx=float(np.sum(centered[:,0]**2));yy=float(np.sum(centered[:,1]**2))
    xy=float(np.sum(centered[:,0]*centered[:,1]))
    if np.hypot(xx-yy,2*xy)<=1e-10*(xx+yy+1):
        raise ValueError('TLS edge samples degenerate')
    theta=.5*np.arctan2(2*xy,xx-yy)
    return np.array([-np.sin(theta),np.cos(theta)])

def edge_measure__v31_tracking(gray,quad,radius=5.,checks='auto'):
    began=time.perf_counter()
    native=measure_edges__v31_native(gray,quad,radius,checked=checks=='auto')
    if native is None:
        q,evidence=_edge_python__v31_tracking(gray,quad,radius,checks)
        evidence['edge_backend']='numpy_analytic_tls'
    else:
        q,evidence=native
        evidence['valid']=(evidence['native_valid'] if checks=='auto' else
            evidence['supported_edges']>=3 and evidence['refined_corners']>=2 and _valid__v31_tracking(q,gray.shape,quad,checks))
    evidence['edge_measure_s']=time.perf_counter()-began
    return q,evidence

def _spatial_support__v31_tracking(points,quad,checks='auto'):
    if checks=='auto':
        result=spatial_support__v31_native(points,quad)
        if result is not None:return result
    p=np.asarray(points,np.float32).reshape(-1,2)
    if len(p)<4:return False
    area=abs(cv2.contourArea(np.asarray(quad,np.float32)))
    if abs(cv2.contourArea(cv2.convexHull(p)))<.25*max(area,1):return False
    # Require points near three different border segments, not one grid line.
    q=np.asarray(quad,np.float32);edge=np.roll(q,-1,axis=0)-q
    d=p[:,None,:]-q[None,:,:]
    t=np.clip(np.sum(d*edge[None,:,:],axis=2)/np.maximum(np.sum(edge*edge,axis=1),1e-6),0,1)
    distance=np.linalg.norm(d-t[:,:,None]*edge[None,:,:],axis=2)
    near=np.argmin(distance,axis=1)
    return len(np.unique(near))>=3 or len(p)==4  # four widely spaced tracked paper corners

class PaperTracker__v31_tracking:
    def __init__(self, interval=3, limit=320, detection_limit=640, detector=None,
                 gray_backend='auto',feature_policy='quality',gaussian_backend='auto',tracking_checks='auto',
                 tracking_policy='motion_adaptive',lk_max_gap=30,lk_min_gap=6):
        if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 10:
            raise ValueError('track_interval 须为 1..10 的整数')
        if not 160 <= limit <= 640:
            raise ValueError('tracking_max_dim 须为 160..640')
        if tracking_policy not in ('motion_adaptive','edge_first','periodic'):raise ValueError('tracking_policy须为motion_adaptive/edge_first/periodic')
        if isinstance(lk_max_gap,bool) or not isinstance(lk_max_gap,int) or not 3<=lk_max_gap<=60:
            raise ValueError('lk_max_gap须为3..60')
        if isinstance(lk_min_gap,bool) or not isinstance(lk_min_gap,int) or not 3<=lk_min_gap<=lk_max_gap:raise ValueError('lk_min_gap须为3..lk_max_gap')
        self.lk_min_gap=lk_min_gap
        self.motion_ema=self.correction_ema=self.drift_budget=0.
        self.accumulated_drift=np.zeros((4,2),np.float32)
        self.policy,self.lk_max_gap=tracking_policy,lk_max_gap
        self.interval, self.limit, self.detection_limit = interval, limit, detection_limit
        self.detector = detector
        self.velocity = np.zeros((4, 2), np.float32)
        self.started = False
        self.last_index = self.anchor_index = 0
        self.lost = False
        self.seed_index=0
        self.seed_count=0
        self._promoted_points=None
        self.lk_cache=LKCache__v31_native()
        self.candidate_lk_cache=LKCache__v31_native();self._candidate_donor=None
        self.last_lk_timing={}
        if feature_policy not in ('quality','legacy'):raise ValueError('feature_policy须为quality/legacy')
        if tracking_checks not in ('auto','legacy'):raise ValueError('tracking_checks须为auto/legacy')
        self.checks=tracking_checks
        self.feature_policy=feature_policy
        self.observer=GrayObserver__v31_tracking(limit,gray_backend,gaussian_backend)
        self.last_gray=None
        self.light_results=False
        self.last_feature_detail={}
        self.edge_workspace=EdgeMotionWorkspace__v31_native()
        self._current_motion_values=None
        self.edge_recovery_count=0
        self._roi_failures=0;self._roi_retry_lk=0;self._roi_lk_checks=0
        self._roi_last_q=None;self._roi_mask=None;self._roi_inside=None
        self._gap_anchor_reuses=0
        self._burst_until=-1;self._frame_deadline=None;self._update_index=0
        self.anchor_gray=None;self.lk_channel='Y';self._flow_gray=None;self._flow_cache=None;self._chroma_pool=[]
        self._channel_audit_index=-100;self._channel_evidence={};self._edge_radius=3.
        self.state='UNINITIALIZED';self._total_deadline=None;self._reserved_detection_ms=0.
        self._lk_initial=np.empty((100,1,2),np.float32)
        self._lk_anchor_quad=np.empty((4,2),np.float32)
        self._lk_prediction_quad=np.empty((4,2),np.float32)
        self.recovery_budget_ms=None;self.recovery_max_candidates=2;self.recovery_backoff_max_frames=4
        self.reacquire_budget_ms=240.;self.reacquire_max_candidates=4
        self._recovery_failures=0;self._recovery_next_index=0;self._recovery_attempts=0
        self._recovery_next_at=0.;self._continuity_proof_next_at=0.;self.continuity_hold=False
        self.recovery_retry_min_s=.20;self.recovery_retry_max_s=.60
        self.recovery_stats=dict(attempts=0,deferred=0,successes=0,budget_stops=0,elapsed_s=0.,overshoot_s=0.)
        self.recovery_snapshots=[]
        self._vector_boundary=False;self._target_signature=None;self._recovery_confirmations=3
        self.recovery_worker=None;self.recovery_result_max_age_s=.90
        self.photometric=IlluminationMotion()
        self.stability=StableEdgeWorkspace();self.stability_detail={}
        self._stability_drift_start=np.zeros((4,2),np.float32)
        self._last_measured_motion=0.;self._edge_lock_next_at=0.;self._edge_lock_failures=0
        self.current_proofs=CurrentProofWorkspace()
        self.fastpath_detail={};self.quick_recovery_detail={};self._quick_recovery_attempted=False
        self.book_rescue=BookRescue()

    def configure_book_rescue(self,enabled=True,cpu_ms=70.):
        self.book_rescue.configure(enabled,cpu_ms)

    def configure_async_recovery(self,enabled=True,result_max_age_s=.90):
        if not isinstance(enabled,bool) or isinstance(result_max_age_s,bool) or not np.isfinite(result_max_age_s) or not .1<=result_max_age_s<=1.:
            raise ValueError('async_recovery bool; recovery_result_max_age_s .1..1 seconds')
        self.recovery_result_max_age_s=float(result_max_age_s)
        if enabled and self.recovery_worker is None:
            self.recovery_worker=RecoveryWorker(self.detection_limit,self.limit)

    def _async_wait(self,image,index,began,cpu,reason,result=None,observation=None,request_background=True):
        self.lost=True;self.state='LOST';self.velocity[:]=0;self.last_index=index
        age=max(0.,time.perf_counter()-getattr(self,'_last_physical_at',began))
        local_first=(age<.45 and getattr(self,'_local_attempts',0)<2
            and self._last_measured_motion<=4. and not getattr(self,'source_force_reacquire',False))
        request_background=bool(request_background and not local_first)
        requested=self.recovery_worker.request(image,index,
            getattr(self,'source_ready_at',began),getattr(self,'source_sequence',None),
            self.reacquire_budget_ms,self.reacquire_max_candidates) if request_background else False
        detail=dict(state='async_detection_in_progress',requested=requested,
            result=None if result is None else {k:result.get(k) for k in
                ('valid','index','sequence','ready','completed_at','worker_s','worker_cpu_s','reason')},
            worker=self.recovery_worker.snapshot(),hardware_access=False,
            ordinary_frame_heavy_recovery_skipped=True,current_candidate_required_before_new_H=True,
            background_deferred_for_local_first=not request_background,
            local_attempts=int(getattr(self,'_local_attempts',0)),local_first_grace_s=.45,
            large_motion_skips_local=self._last_measured_motion>4.)
        record=dict(valid=False,mode='lost_skip',reason=reason,trigger=reason,index=index,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu,
            gray_s=0.,gray_detail=dict(state='not_measured_while_background_busy'),
            feature_update_s=0.,feature_detail=dict(action='async_wait',roi_s=0.),lk_timing={},
            tracking_policy=self.policy,lk_channel=self.lk_channel,lk_trigger='async_recovery',
            tracking_state=self.state,edge_gate={},edge_evidence={},detection=None,
            final_admission_gate=dict(reliable=False),recovery_attempt=detail,edge_stability=dict(self.stability_detail),
            v49_fastpath=dict(self.fastpath_detail),quick_current_candidate=dict(self.quick_recovery_detail),
            current_proof_workspace=self.current_proofs.summary())
        if observation is not None:record.update(observation)
        return record

    def _admit_async_candidate(self,image,gray,scale,result,index):
        # Background coordinates are a proposal ONLY. All admitted edges come
        # from the currently leased input. The worker's receipt is never reused.
        from geometry import exterior_agreement as exterior_agreement; from geometry import array_key as array_key; from geometry import actual_source64 as actual_source64
        age=max(0.,time.perf_counter()-result['ready'])
        if age>self.recovery_result_max_age_s:raise ValueError('Background candidate too old')
        proposal=((np.asarray(result['quad'],np.float32)+.5)/scale-.5).astype(np.float32)
        transport=dict(used=False,backend='bounded_candidate_corner_forward_backward_LK')
        donor=result.get('source_gray');donor_scale=result.get('source_scale')
        if donor is not None and donor.shape==gray.shape and np.allclose(donor_scale,scale,rtol=0,atol=1e-6):
            t=time.perf_counter();cpu=time.thread_time()
            points=proposal.reshape(4,1,2)
            criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02)
            donor_key=(result['index'],result['ready'],result.get('sequence'))
            if self._candidate_donor!=donor_key:self.candidate_lk_cache.anchor(donor);self._candidate_donor=donor_key
            native=self.candidate_lk_cache.track(gray,points,levels=2,iterations=20,generation=int(index))
            if native is None:
                moved,status,error=cv2.calcOpticalFlowPyrLK(donor,gray,points,None,
                    winSize=(21,21),maxLevel=2,criteria=criteria)
            else:moved,status,error,back,back_status=native
            if moved is not None and status is not None and np.all(status):
                if native is None:
                    back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,donor,moved,None,
                        winSize=(21,21),maxLevel=2,criteria=criteria)
                fb=float(np.max(np.linalg.norm(back.reshape(4,2)-proposal,axis=1))) if back is not None else float('inf')
                transported=moved.reshape(4,2)
                if (back_status is not None and np.all(back_status) and np.isfinite(transported).all()
                        and fb<=1. and error is not None and np.max(error)<=30.
                        and _valid__v31_tracking(transported,gray.shape,proposal,self.checks)):
                    proposal=transported.astype(np.float32);transport.update(used=True,fb_max=fb)
                else:transport.update(reason='candidate_flow_rejected',fb_max=fb)
            else:transport['reason']='candidate_flow_unavailable'
            transport.update(wall_s=time.perf_counter()-t,thread_cpu_s=time.thread_time()-cpu,
                pyramid_workspace_reused=native is not None)
        if not _valid__v31_tracking(proposal,gray.shape,checks=self.checks):raise ValueError('Background candidate geometry invalid')
        reference=proposal.copy()
        measured,small_evidence=edge_measure__v31_tracking(gray,reference,6.,self.checks)
        gray_gate=exterior_gate(small_evidence,measured,reference,6.)
        gray_trusted=(gray_gate.get('reliable') and gray_gate.get('min_support',0.)>=.80
            and gray_gate.get('max_rms',1e30)<=.65 and gray_gate.get('prediction_correction',1e30)<=.75)
        seed=measured if gray_trusted else reference
        primary,evidence,second_gate,agreement=self._source_confirmation(
            image,gray,seed,small_evidence,new_candidate=True,radius=6.,
            reference=reference,gray_reliable=bool(gray_trusted))
        transport.update(original_candidate_preserved=True,gray_seed_used=bool(gray_trusted),
            gray_gate=gray_gate,source_reference=reference.tolist())
        from geometry import search_gate as search_gate
        first=search_gate(evidence,primary,proposal,6.)
        verified=(first.get('reliable') and second_gate.get('reliable') and agreement.get('verified')
            and _valid__v31_tracking(primary,gray.shape,checks=self.checks))
        if not verified:
            from core import checkpoint as checkpoint
            checkpoint('ASYNC_CANDIDATE_CURRENT_REJECTED',current_index=index,
                background_index=result['index'],candidate_age_s=age,
                first_gate=first,independent_gate=second_gate,agreement=agreement,
                candidate_transport=transport,hardware_access=False)
            raise ValueError('Background proposal failed current independent exterior proof: '+str(agreement.get('reason','four_edge_disagreement')))
        return primary,evidence,dict(state='async_candidate_current_frame_verified',
            background_index=result['index'],background_sequence=result['sequence'],candidate_age_s=age,
            current_index=index,candidate_transport=transport,first_validation=first,second_validation=second_gate,
            source_line_agreement=agreement,old_H_not_used=True,stale_receipt_used=False)

    def _local_due(self):
        now=time.perf_counter();age=now-getattr(self,'_last_physical_at',0.)
        # Two early local attempts, then an occasional cheap current-Y probe.
        # An expired output H never forbids proving a fresh local candidate.
        attempts=getattr(self,'_local_attempts',0)
        return bool(age>=0 and now>=getattr(self,'_local_next_at',0.)
            and ((attempts<2 and age<=1.5 and self._last_measured_motion<=4.) or age>.60)
            and not getattr(self,'source_force_reacquire',False))

    def _quick_current_candidate(self,image,gray,scale,index):
        """One current-Y contour candidate per loss episode, strict admission.

        Proposal generation and original64/independent24 share one CPU/wall
        budget. A miss does not fall through to a full foreground search.
        """
        if self._quick_recovery_attempted:return None
        self._quick_recovery_attempted=True
        from geometry import array_key as array_key
        began=time.perf_counter();cpu=time.thread_time()
        budget=CpuRecoveryBudget(120.,1,wall_max_s=.30)
        observation=dict(gray=gray,scale=scale,source_shape=image.shape,frame_index=index,source_key=array_key(image))
        detail=dict(attempted=True,verified=False,proposal_source='current_tracking_Y_contour',
            maximum_candidates=1,maximum_attempts_per_loss_episode=1,hardware_access=False,
            old_H_not_used=True,full_foreground_search=False)
        self.quick_recovery_detail=detail
        try:
            with recovery_detection_scope(budget,observation):
                budget.check('v69_current_Y_proposal')
                proposal=next(iter(_contour_proposals(gray,min(240,self.detection_limit),incremental=True)),None)
                if proposal is None:
                    detail['reason']='no_current_Y_contour_candidate';return None
                if not _valid__v31_tracking(np.asarray(proposal,np.float32),gray.shape,checks=self.checks):
                    detail['reason']='current_Y_candidate_geometry_invalid';return None
                budget.check('v69_immediate_candidate_admission')
                coarse=(np.asarray(proposal,np.float32)+.5)*scale-.5
                seed=dict(detector='v69_current_Y_contour',coarse_corners=coarse.tolist())
                with recovery_candidate_scope((seed,),True):full,detection=self._detect(image)
            receipt=read_current_receipt(detection,image,gray,scale,index,full)
            detection.pop('_current_boundary_receipt',None)
            if receipt is None:
                detail['reason']='current_candidate_receipt_not_bound';return None
            candidate,evidence,gate=receipt
            if not gate.get('reliable') or not _valid__v31_tracking(candidate,gray.shape,checks=self.checks):
                detail['reason']='current_candidate_final_geometry_invalid';return None
            agreement=gate.get('current_source_agreement',{})
            if not agreement.get('verified'):
                detail['reason']='current_candidate_independent_proof_missing';return None
            self.last_source_confirmation=dict(agreement,final_gate=dict(gate))
            detail.update(verified=True,reason='current_candidate_immediately_admitted',
                same_frame_receipt_reused=True,original_corners_preserved=True)
            return candidate,evidence,dict(state='v69_current_candidate_verified',
                first_validation=gate,source_line_agreement=agreement,quick_current_candidate=detail,
                current_index=index,old_H_not_used=True,stale_receipt_used=False)
        except (ValueError,cv2.error,_DetectionStop) as exc:
            detail.update(reason=str(exc),exception_type=type(exc).__name__);return None
        finally:
            detail.update(wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu,
                budget=compact_recovery_summary(budget.summary()))

    def _local_exterior(self,image,gray,scale,prediction,index):
        """Current source lines only; bounded local proposal before full search.

        Strict new/current independent proof stays mandatory after LOST. This
        routine neither promotes old LK data nor renews any hold timestamp.
        """
        if not self._local_due():return None
        from geometry import sample_locked_color as sample_locked_color; from geometry import search_gate as search_gate
        now=time.perf_counter();cpu=time.thread_time()
        if not getattr(self,'_local_attempts',0):self._local_batch_at=now
        self._local_attempts=getattr(self,'_local_attempts',0)+1
        periodic=(self._local_attempts>2 or now-getattr(self,'_last_physical_at',now)>1.5
            or self._last_measured_motion>4.)
        self._local_next_at=now+(.65 if periodic else .20)
        deadline=now+.25
        if self._frame_deadline is not None:deadline=min(deadline,self._frame_deadline)
        age=max(0.,now-getattr(self,'_last_physical_at',now))
        radius=max(3.,min(12.,max(self._edge_radius,3.+2.*age)))
        try:
            if periodic:
                primary,e=edge_measure__v31_tracking(gray,prediction,min(6.,radius),self.checks)
                if not search_gate(e,primary,prediction,min(6.,radius)).get('reliable'):return None
            else:
                primary,e=sample_locked_color(image,scale,prediction,64,deadline,self._target_signature,
                    half_source=min(24.,radius*float(np.max(scale))),lock_physical=False)
            first=search_gate(e,primary,prediction,radius)
            if not first.get('reliable'):return None
            from geometry import layer_continuity as layer_continuity
            continuity=layer_continuity(self._target_signature,e)
            if not continuity['verified']:return None
            remaining_cpu=.12-(time.thread_time()-cpu)
            if remaining_cpu<=0 or time.perf_counter()>=deadline:return None
            observed,current,gate,agreement=self._source_confirmation(image,gray,primary,e,
                new_candidate=True,radius=radius,reference=prediction,gray_reliable=periodic,proof_deadline=deadline,proof_cpu_s=remaining_cpu)
            if (time.perf_counter()>deadline or time.thread_time()-cpu>.12
                or not gate.get('reliable') or not agreement.get('verified')
                or not _valid__v31_tracking(observed,gray.shape,self.q,self.checks)):return None
            return observed,current,dict(state='local_current_source_exterior_reacquired',
                first_validation=first,second_validation=gate,source_line_agreement=agreement,
                local_attempt=self._local_attempts,local_wall_s=time.perf_counter()-now,
                low_rate_current_Y_probe=periodic,
                local_thread_cpu_s=time.thread_time()-cpu,old_H_not_used=True,
                global_detection_skipped=True,hold_timer_renewed=False,physical_layer_continuity=continuity)
        except (ValueError,cv2.error):return None

    def configure_recovery(self,budget_ms=120.,max_candidates=2,backoff_max_frames=4,reacquire_budget_ms=240.,reacquire_max_candidates=4):
        if isinstance(reacquire_budget_ms,bool) or not np.isfinite(reacquire_budget_ms) or not budget_ms<=reacquire_budget_ms<=500:
            raise ValueError('reacquire_budget_ms must be recovery_budget_ms..500')
        if isinstance(budget_ms,bool) or not np.isfinite(budget_ms) or not 40<=budget_ms<=500:
            raise ValueError('recovery_budget_ms must be 40..500')
        for name,value,low,high in (('recovery_max_candidates',max_candidates,1,8),
                ('recovery_backoff_max_frames',backoff_max_frames,1,8),
                ('reacquire_max_candidates',reacquire_max_candidates,max_candidates,8)):
            if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
                raise ValueError(name+' outside bounded integer range')
        self.recovery_budget_ms=float(budget_ms);self.recovery_max_candidates=max_candidates
        self.recovery_backoff_max_frames=backoff_max_frames
        self.reacquire_budget_ms=float(reacquire_budget_ms);self.reacquire_max_candidates=reacquire_max_candidates

    def _remember_recovery_failure(self,gray,index,prediction,detail):
        # Four owned small-Y snapshots only. Encoding/saving is after formal timing.
        # Retain first + most recent three instead of growing with a long outage.
        if self._recovery_failures>1 and self._recovery_failures%4:return
        item=dict(index=int(index),gray=gray.copy(),corners=prediction.copy(),detail=dict(detail))
        if len(self.recovery_snapshots)>=4:self.recovery_snapshots.pop(1)
        self.recovery_snapshots.append(item)

    def _detect(self, image):
        if self.detector is not None:
            return self.detector(image)
        return detect_refined(image, self.detection_limit, True)

    def _roi_features(self,gray,q,retained=None,variant=0):
        if variant:return self._edge_strip_features(gray,q,retained,variant)
        if self.checks=='auto':
            began=time.perf_counter();native=self.lk_cache.roi_features(gray,q,retained)
            if native is not None:
                points,detail=native
                from geometry import outer_features as outer_features
                before=len(points);points=outer_features(points,q)
                self.last_feature_detail=dict(detail,roi_s=time.perf_counter()-began,
                    outer_band_filter=True,interior_features_removed=before-len(points),features=len(points),
                    added=max(0,len(points)-(0 if retained is None else len(retained))))
                return points
        """Small OUTER-paper corner patches; exclude interior repeating grid.

        Actual GFTT points only. If a textureless sheet gives no usable four
        regions, the existing full boundary seed remains the fallback.
        """
        began=time.perf_counter();h,w=gray.shape
        points=[] if retained is None else list(np.asarray(retained,np.float32).reshape(-1,2))
        before=len(points);regions=0
        for corner in q:
            if sum(float(np.linalg.norm(p-corner))<18 for p in points)>=2:
                continue
            x,y=corner;x0=max(0,int(x)-20);y0=max(0,int(y)-20)
            x1=min(w,int(x)+21);y1=min(h,int(y)+21)
            if min(x1-x0,y1-y0)<7:continue
            qi=np.rint(q-[x0,y0]).astype(np.int32)
            mask=np.zeros((y1-y0,x1-x0),np.uint8)
            cv2.polylines(mask,[qi],True,255,4)
            inside=np.zeros_like(mask);cv2.fillConvexPoly(inside,qi,255)
            mask=cv2.bitwise_and(mask,inside)
            if len(points)>=100:break
            found=cv2.goodFeaturesToTrack(gray[y0:y1,x0:x1],maxCorners=6,
                    qualityLevel=.012,minDistance=5,mask=mask,blockSize=5)
            regions+=1
            if found is None:continue
            for point in found.reshape(-1,2)[:4]+[x0,y0]:
                if len(points)>=100:break
                if not points or min(float(np.linalg.norm(p-point)) for p in points)>4:
                    points.append(point.astype(np.float32))
        out=np.asarray(points,np.float32).reshape(-1,2)
        self.last_feature_detail=dict(action='outer_corner_roi',regions=regions,
            added=len(out)-before,features=len(out),roi_s=time.perf_counter()-began)
        from geometry import outer_features as outer_features
        out=outer_features(out,q);self.last_feature_detail.update(features=len(out),added=max(0,len(out)-before))
        return out


    def _edge_strip_features(self,gray,q,retained,variant):
        """Alternate bounded outer-edge strips after corner patches add nothing."""
        began=time.perf_counter();cpu=time.thread_time();h,w=gray.shape
        if self._roi_mask is None or self._roi_mask.shape!=gray.shape:
            self._roi_mask=np.zeros_like(gray);self._roi_inside=np.zeros_like(gray)
        self._roi_mask.fill(0);self._roi_inside.fill(0)
        qi=np.rint(q).astype(np.int32);cv2.fillConvexPoly(self._roi_inside,qi,255)
        edges=(variant%2,(variant%2)+2)
        for edge in edges:
            a,b=q[edge],q[(edge+1)%4]
            cv2.line(self._roi_mask,tuple(np.rint(a+.12*(b-a)).astype(int)),
                tuple(np.rint(a+.88*(b-a)).astype(int)),255,4)
        cv2.bitwise_and(self._roi_mask,self._roi_inside,dst=self._roi_mask)
        points=[] if retained is None else list(np.asarray(retained,np.float32).reshape(-1,2))
        before=len(points)
        # Two bounded patches; no whole-image feature search, no invented points.
        for edge in edges:
            a,b=q[edge],q[(edge+1)%4]
            x0=max(0,int(min(a[0],b[0]))-5);x1=min(w,int(max(a[0],b[0]))+6)
            y0=max(0,int(min(a[1],b[1]))-5);y1=min(h,int(max(a[1],b[1]))+6)
            if min(x1-x0,y1-y0)<7:continue
            found=cv2.goodFeaturesToTrack(gray[y0:y1,x0:x1],maxCorners=4,qualityLevel=.012,
                minDistance=5,mask=self._roi_mask[y0:y1,x0:x1],blockSize=5)
            if found is None:continue
            for point in found.reshape(-1,2)+[x0,y0]:
                if len(points)>=100:break
                if not points or min(float(np.linalg.norm(p-point)) for p in points)>4:
                    points.append(point.astype(np.float32))
        out=np.asarray(points,np.float32).reshape(-1,2)
        self.last_feature_detail=dict(action='alternate_outer_edge_strips',regions=2,
            variant=variant,added=len(out)-before,features=len(out),workspace_reused=True,
            roi_s=time.perf_counter()-began,roi_thread_cpu_s=time.thread_time()-cpu)
        from geometry import outer_features as outer_features
        out=outer_features(out,q);self.last_feature_detail.update(features=len(out),added=max(0,len(out)-before))
        return out

    def _quality_replenish(self,gray,points,q,quality,evidence):
        from geometry import outer_features as outer_features
        points=outer_features(points,q)
        self._roi_lk_checks+=1
        supported=_spatial_support__v31_tracking(points,q,self.checks)
        reliable=(quality and supported and len(points)>=4 and
            min(evidence.get('edge_support',[0.]*4))>=.8 and max(evidence.get('edge_rms',[1e30]*4))<=.65)
        if reliable and len(points)>=12:
            self.last_feature_detail=dict(action='promote_validated_inliers',features=len(points),roi_s=0.)
            return points
        if reliable and self._roi_lk_checks<self._roi_retry_lk:
            self.last_feature_detail=dict(action='bounded_roi_backoff',features=len(points),added=0,
                roi_s=0.,failures=self._roi_failures,next_retry_lk=self._roi_retry_lk,
                current_lk=self._roi_lk_checks,maximum_skipped_lk_checks=7,
                retained_fb_and_four_edge_checks=True)
            return points
        before=len(points);variant=self._roi_failures%3 if self._roi_failures else 0
        out=self._roi_features(gray,q,points,variant)
        self._roi_last_q=q.copy()
        self._roi_failures=(min(8,self._roi_failures+1) if len(out)<=before else 0)
        # Low-yield refill backs off only while motion, FB inliers, spatial
        # support AND all four measured edges remain trustworthy.
        delay=min(8,1<<min(3,self._roi_failures)) if reliable else 1
        self._roi_retry_lk=self._roi_lk_checks+delay
        self.last_feature_detail.update(failures=self._roi_failures,next_retry_lk=self._roi_retry_lk,
            current_lk=self._roi_lk_checks,variant=variant,quality_override=not reliable)
        return out

    def _channel_quality(self,plane,q,points):
        # Four short outside/inside bands in the SMALL scalar plane; no full CSC.
        d=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(d,axis=1)
        normal=np.stack((-d[:,1],d[:,0]),axis=1)/np.maximum(length[:,None],1e-6)
        normal*=np.where(np.sum((q.mean(axis=0)-q-d*.5)*normal,axis=1)<0,-1.,1.)[:,None]
        base=q[:,None,:]+np.linspace(.1,.9,12)[None,:,None]*d[:,None,:]
        xy=base[:,:,None,:]+np.array([-3.,3.])[None,None,:,None]*normal[:,None,None,:]
        value=cv2.remap(plane,xy[...,0].reshape(48,2).astype(np.float32),
            xy[...,1].reshape(48,2).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        per_edge=np.median(np.abs(value[:,1].astype(np.float32)-value[:,0]).reshape(4,12),axis=1)
        spatial=_spatial_support__v31_tracking(points,q,self.checks)
        # A channel must cover the exterior spatially, not only yield many ink points.
        score=(min(len(points),40)/40.)*float(np.mean(np.minimum(per_edge,48.)))*float(spatial)
        return dict(score=score,spatial=bool(spatial),features=len(points),edge_contrast=per_edge.tolist())

    def _seed(self, gray, q, index, source_image=None, same_target=False):
        self._gap_anchor_reuses=0
        self._roi_failures=0;self._roi_retry_lk=0;self._roi_lk_checks=0;self._roi_last_q=None
        def features(plane):
            points=self._roi_features(plane,q) if self.feature_policy=='quality' else np.empty((0,2),np.float32)
            if not _spatial_support__v31_tracking(points,q,self.checks):
                points=self._full_features(plane,q)
                self.last_feature_detail.update(action='full_boundary_fallback',features=len(points))
            return points
        raw=source_image is not None and source_image.ndim==3 and source_image.shape[2]==2
        flow_gray=self._flow_observation(source_image,gray) if raw and self.lk_channel!='Y' else gray
        points=features(flow_gray);quality=self._channel_quality(flow_gray,q,points)
        audit=raw and (not quality['spatial'] or (not same_target and index-self._channel_audit_index>=12))
        chosen=self.lk_channel if raw else 'Y';scores={chosen:quality};feature_detail=dict(self.last_feature_detail)
        if audit:
            current=chosen;best_score=quality['score'];self._channel_audit_index=index
            # Fixed channel per NEW anchor; forward/backward LK never mixes channels.
            for channel in ('Y','U','V'):
                if channel==current:continue
                plane=gray if channel=='Y' else self._chroma_observation(source_image,gray.shape,channel)
                found=features(plane);check=self._channel_quality(plane,q,found);scores[channel]=check
                if check['spatial'] and (not quality['spatial'] or check['score']>best_score*1.2+2.):
                    chosen,flow_gray,points=channel,plane,found
                    quality=check;best_score=check['score'];feature_detail=dict(self.last_feature_detail)
        self.lk_channel=chosen;self._flow_gray=flow_gray;self._flow_cache=None
        self._channel_evidence=dict(selected=chosen,audited=audit,scores=scores,channel_fixed_until_new_anchor=True,
            same_target_channel_retained=bool(same_target and not audit))
        self.last_feature_detail=dict(feature_detail,channel_selection=self._channel_evidence)
        self.anchor_gray=flow_gray;self.observer.pin(gray)
        self.anchor_q=q.copy();self.anchor_points=points.astype(np.float32).reshape(-1,1,2)
        self.anchor_index=index;self.seed_index=index;self.seed_count+=1;self.lk_cache.anchor(flow_gray)
        self.book_rescue.mark_anchor(getattr(self,'source_ready_at',time.perf_counter()),self.anchor_q,self.lk_channel)

    def _chroma_observation(self,image,shape,channel):
        from geometry import chroma_gray as chroma_gray
        if not self._chroma_pool or self._chroma_pool[0].shape!=tuple(shape):
            self._chroma_pool=[np.empty(shape,np.uint8) for _ in range(3)]
        plane=next(p for p in self._chroma_pool if p is not self.anchor_gray and p is not self._flow_gray)
        chroma_gray(image,shape,channel,plane);self._flow_gray=plane
        return plane

    def _flow_observation(self,image,gray):
        if self.lk_channel=='Y' or image is None:return gray
        if self._flow_cache is not None and self._flow_cache[0]==self._update_index:
            return self._flow_cache[1]
        plane=self._chroma_observation(image,gray.shape,self.lk_channel)
        self._flow_cache=(self._update_index,plane)
        return plane

    def _full_features(self,gray,q):
        mask = np.zeros_like(gray)
        qi = np.rint(q).astype(np.int32)
        cv2.polylines(mask, [qi], True, 255, 4)
        inside = np.zeros_like(gray)
        cv2.fillConvexPoly(inside, qi, 255)
        mask = cv2.bitwise_and(mask, inside)
        points = cv2.goodFeaturesToTrack(gray, maxCorners=96, qualityLevel=.012,
                                        minDistance=5, mask=mask, blockSize=5)
        points = np.empty((0, 2), np.float32) if points is None else points.reshape(-1, 2)
        for corner in (q if self.feature_policy=='legacy' else ()):
            if not len(points) or np.min(np.linalg.norm(points-corner, axis=1)) > 2:
                points = np.vstack((points, corner))
        from geometry import outer_features as outer_features
        return outer_features(points,q)

    def initialize(self, image, quad=None, index=1, initial_evidence=None, initial_detection=None):
        if quad is None:
            quad, detection = self._detect(image)
        else:
            detection = initial_detection if isinstance(initial_detection,dict) else {'state': 'supplied_first_frame_detection'}
        if initial_evidence is None:initial_evidence=detection.get('tracking_edge_evidence',{})
        # A hint selects the CURRENT verifier. Only a single-use receipt bound
        # to this still-leased source permits same-frame proof reuse.
        self._vector_boundary=bool(initial_evidence.get('color_vector_proof'))
        gray, scale = self.observer.get(image)
        self.last_gray=gray
        self._update_index=index;self.current_proofs.begin(image,gray,index,scale)
        q = (np.asarray(quad, np.float32)+.5)/scale-.5
        if not _valid__v31_tracking(q, gray.shape,checks=self.checks):
            raise ValueError('首帧纸张四角无效或已超出画面')
        self.shape, self.scale = image.shape, scale
        self.q = q.astype(np.float32)
        from geometry import consume_startup_receipt as consume_startup_receipt
        receipt=consume_startup_receipt(detection,image,quad,scale)
        if receipt is not None:
            primary,source,source_gate,agreement=receipt
        else:
            # External/mismatched corners receive a fresh proof. Never reuse an
            # old source receipt or let unreliable small Y shift this original.
            checked,evidence=edge_measure__v31_tracking(gray,self.q,3.,checks=self.checks)
            initial_gate=exterior_gate(evidence,checked,self.q,3.)
            original=self.q.copy()
            gray_trusted=bool(initial_gate.get('reliable') and initial_gate.get('min_support',0.)>=.80
                and initial_gate.get('max_rms',1e30)<=.65 and initial_gate.get('prediction_correction',1e30)<=.75)
            primary,source,source_gate,agreement=self._source_confirmation(image,gray,
                checked if gray_trusted else original,evidence,new_candidate=True,radius=3.,
                reference=original,gray_reliable=gray_trusted)
        if not source_gate.get('reliable') or not agreement.get('verified') or not _valid__v31_tracking(primary,gray.shape,checks=self.checks):
            from core import checkpoint as checkpoint
            checkpoint('INITIAL_CURRENT_LINE_PROOF_FAILED',gate=source_gate,agreement=agreement,
                source_corners=np.asarray(quad).tolist(),hardware_access=False)
            raise ValueError('首帧物理外框未通过当前源图独立四边证明: '+str(agreement.get('reason','four_edge_disagreement')))
        checked,evidence,initial_gate=primary,source,source_gate
        detection.update(initial_source_line_agreement=agreement,original_primary_preserved=True)
        self.q=checked.astype(np.float32)
        self.edge_polarity = evidence['edge_polarity']
        self._vector_boundary=bool(evidence.get('color_vector_proof'))
        from geometry import border_signature as border_signature
        self._target_signature=border_signature(evidence)
        detection=dict(detection,initial_edge_gate=initial_gate)
        self.velocity[:] = 0
        self._lk_budget_deferrals=0
        self._seed(gray, self.q, index, image)
        self.last_index = index
        self.started, self.lost = True, False
        self.state='TRACKING'
        self._last_physical_at=time.perf_counter();self._local_next_at=0.;self._local_attempts=0
        self._v81_local_flow_hint=None
        return self.corners(), detection

    def write_corners(self,out):
        if out.shape!=(4,2) or out.dtype!=np.float32:raise ValueError('Corner workspace must be4x2 float32')
        np.add(self.q,.5,out=out);np.multiply(out,self.scale,out=out);np.subtract(out,.5,out=out)
        return out

    def corners(self):
        return self.write_corners(np.empty((4,2),np.float32))

    def _lk(self, gray, prediction=None, fast=False, source_image=None,rescue=None):
        attempts=list(self.last_lk_timing.get('attempts',()))
        began=time.perf_counter();cpu=time.thread_time();failure=None
        self.lk_cache.last_checked_timing={}
        try:return self._lk_impl(gray,prediction,fast,source_image,rescue)
        except BaseException as exc:
            failure=str(exc);raise
        finally:
            detail=dict(self.last_lk_timing,**self.lk_cache.last_checked_timing)
            detail.pop('attempts',None)
            detail.update(search='cover_rescue' if rescue is not None else 'fast' if fast else 'full',accepted=failure is None,
                reason=failure,wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu)
            attempts.append(detail)
            self.last_lk_timing=dict(detail,attempts=attempts,attempt_count=len(attempts),
                total_attempt_wall_s=sum(v['wall_s'] for v in attempts),
                total_attempt_thread_cpu_s=sum(v['thread_cpu_s'] for v in attempts))

    def _lk_impl(self, gray, prediction=None, fast=False, source_image=None,rescue=None):
        began=time.perf_counter()
        self.last_lk_timing={}
        flow_gray=self._flow_observation(source_image,gray)
        p = self.anchor_points if rescue is None else rescue[0]
        if len(p)<4:raise ValueError('外边框有效特征少于4个')
        params = dict(winSize=(21, 21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, .02))
        initial=None
        if prediction is not None:
            self._lk_anchor_quad[:]=self.anchor_q;self._lk_prediction_quad[:]=prediction
            motion=cv2.getPerspectiveTransform(self._lk_anchor_quad,self._lk_prediction_quad)
            initial=self._lk_initial[:len(p)]
            cv2.perspectiveTransform(p,motion,dst=initial)
        if fast:params.update(maxLevel=2,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,12,.02))
        checked=self.lk_cache.checked(flow_gray,p,initial,self.anchor_q,self.q,self.last_index,params['maxLevel'],params['criteria'][1]) if self.checks=='auto' and rescue is None else None
        native=None if checked is not None else self.lk_cache.track(flow_gray,p,initial=initial,levels=params['maxLevel'],
            iterations=params['criteria'][1],generation=self.last_index if rescue is not None else None)
        if checked is not None:
            q,retained,filter_detail,times=checked;self.last_lk_timing.update(times)
            fit_began=time.perf_counter()
        else:
            if native is None:
                forward, status, error = cv2.calcOpticalFlowPyrLK(self.anchor_gray, flow_gray, p, initial,
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW if initial is not None else 0, **params)
            else:
                forward,status,error,backward,status_b=native
            if forward is None:
                raise ValueError('LK 没有返回特征')
            if native is None:
                backward, status_b, _ = cv2.calcOpticalFlowPyrLK(flow_gray, self.anchor_gray, forward, p.copy(),
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **params)
            if backward is None:
                raise ValueError('LK 反向跟踪失败')
            self.last_lk_timing['forward_backward_flow_s']=time.perf_counter()-began
            fit_began=time.perf_counter()
            filtered=filter_lk__v31_native(p,forward,backward,status,status_b,error,self.anchor_q,self.q,gray.shape) if self.checks=='auto' else None
            if filtered is not None:
                q,retained,filter_detail=filtered
            else:
                fb = np.linalg.norm(backward.reshape(-1, 2)-p.reshape(-1, 2), axis=1)
                good = status.ravel().astype(bool) & status_b.ravel().astype(bool)
                good &= (fb < 1.4) & (error.ravel() < 30)
                if good.sum() < 4:
                    raise ValueError('外边框有效特征少于4个')
                a=p.reshape(-1,2)[good];z=forward.reshape(-1,2)[good]
                motion_model='projective_candidate'
                if len(a)<8:
                    affine,inliers=cv2.estimateAffinePartial2D(a,z,method=cv2.RANSAC,
                        ransacReprojThreshold=1.6,maxIters=1000,confidence=.99,refineIters=10)
                    H=None if affine is None else np.vstack((affine,[0.,0.,1.]))
                    motion_model='similarity_candidate'
                else:
                    H,inliers=cv2.findHomography(a,z,cv2.RANSAC,1.6,maxIters=1000,confidence=.99)
                    if H is not None and inliers is not None and inliers.sum()<8:
                        affine,inliers=cv2.estimateAffinePartial2D(a,z,method=cv2.RANSAC,
                            ransacReprojThreshold=1.6,maxIters=1000,confidence=.99,refineIters=10)
                        H=None if affine is None else np.vstack((affine,[0.,0.,1.]))
                        motion_model='similarity_candidate'
                if H is None or not np.isfinite(H).all() or inliers is None:
                    raise ValueError('边框特征不能确定运动映射')
                retained=forward.reshape(-1,2)[good][inliers.ravel().astype(bool)]
                original=p.reshape(-1,2)[good][inliers.ravel().astype(bool)]
                if not _spatial_support__v31_tracking(original,self.anchor_q,self.checks):
                    raise ValueError("边缘特征分布退化，不能只凭RANSAC内点率")
                fraction = float(inliers.mean())
                if inliers.sum() < 4 or fraction < .65:
                    raise ValueError('边框特征几何一致性不足')
                q = cv2.perspectiveTransform(self.anchor_q.reshape(1, 4, 2), H).reshape(4, 2)
                if not _valid__v31_tracking(q, gray.shape, self.q,self.checks):
                    raise ValueError('跟踪四角越界或形变异常')
                filter_detail=dict(features=len(p),good_features=int(good.sum()),
                    inlier_fraction=fraction,fb_median=float(np.median(fb[good])),filter_backend='opencv_python_ransac',motion_model=motion_model,
                    current_four_edges_required=True)
        if checked is None:self.last_lk_timing['fb_filter_ransac_s']=time.perf_counter()-fit_began
        if rescue is not None:
            rim=verify_rim_flow(p,forward,backward,status,status_b,error,rescue[1],self.anchor_q,q)
            self.last_lk_timing['cover_rim_consistency']=rim
            if (not rim['verified'] or filter_detail.get('good_features',0)<8
                    or filter_detail.get('inlier_fraction',0.)<.85 or filter_detail.get('fb_median',1e30)>=.7):
                raise ValueError('Cover proposal lacks consistent real rim forward/backward evidence')
            if not self.book_rescue.available():raise ValueError('Cover FB finished outside rescue compute budget')
            if time.thread_time()-self.book_rescue.cpu>self.book_rescue.selection_cpu_s+self.book_rescue.flow_cpu_s:
                raise ValueError('Complete cover FB finished outside its reserved flow compute slice')
        self.last_lk_timing['motion_fit']=dict(filter_detail)
        self.last_lk_timing['current_flow_proposal']=q.tolist()
        travel=float(np.max(np.linalg.norm(q-self.q,axis=1)))
        shortest=float(np.min(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)))
        cap=max(3.,min(7.5,.06*shortest,24./float(np.max(self.scale))))
        radius=float(np.clip(max(3.,self._edge_radius)+.10*travel,3.,cap))
        # Keep full FB/filtering above. Reuse only THIS frame's already
        # measured physical line, bounded again against the fresh FB quad.
        complete=self.current_proofs.motion_result(source_image,gray,self._update_index,self.scale,q,radius) if source_image is not None else None
        observed=(complete[:2] if complete is not None else
            self.current_proofs.measurement(source_image,gray,self._update_index,self.scale,q,radius) if source_image is not None else None)
        if observed is None:measured,evidence=edge_measure__v31_tracking(gray,q,radius,self.checks)
        else:measured,evidence=observed
        self.last_lk_timing.update(current_measurement_reused=observed is not None,
            complete_current_proof_reused=complete is not None)
        from geometry import search_gate as search_gate; from geometry import sample_locked_color as sample_locked_color
        from geometry import border_signature as border_signature
        def current_search(e,c):
            g=search_gate(e,c,q,radius)
            flips=0 if e.get('color_vector_proof') else sum(a*b<0 for a,b in zip(self.edge_polarity,e.get('edge_polarity',[])))
            return dict(g,reliable=bool(g['reliable'] and flips==0),polarity_flips=flips)
        lk_gate=current_search(evidence,measured)
        if source_image is not None and not lk_gate['reliable']:
            measured,evidence=sample_locked_color(source_image,self.scale,q,64,self._frame_deadline,
                self._target_signature,half_source=min(24.,max(3.,radius*float(np.max(self.scale)))),
                lock_physical=False)
            lk_gate=current_search(evidence,measured)
        lock_required=bool(rescue is not None or radius>3. or lk_gate.get('prediction_correction',0.)>1.5 or evidence.get('color_vector_proof'))
        if lk_gate['reliable'] and lock_required:
            # Wider first search cannot justify itself. Independently spaced
            # source Y64 (or YUV64) must agree with all four refined edges.
            from geometry import stable_fb_context as stable_fb_context
            stable_fb=stable_fb_context(filter_detail,travel,lk_gate['prediction_correction'],
                self.lost,getattr(self,'source_elapsed_s',None),
                processing_gap=bool(getattr(self,'source_processing_gap',False)))
            if complete is not None:
                second,independent,strict_gate,agreement=complete
                self.last_source_confirmation=dict(agreement,final_gate=dict(strict_gate))
            else:
                second,independent,strict_gate,agreement=self._source_confirmation(source_image,gray,measured,evidence,
                    radius=radius,reference=q,gray_reliable=lk_gate['reliable'],stable_fb=stable_fb,
                    proof_deadline=self.book_rescue.deadline if rescue is not None else None,
                    proof_cpu_s=min(self.book_rescue.proof_cpu_s,max(0.,self.book_rescue.cpu_s-
                        (time.thread_time()-self.book_rescue.cpu))) if rescue is not None else None)
            self.last_lk_timing['stable_FB_context']=stable_fb
            verified=(strict_gate is not None and strict_gate['reliable'] and agreement['verified']
                and _valid__v31_tracking(second,gray.shape,self.q,self.checks))
            self.last_lk_timing['source_line_agreement']=agreement
            self.last_lk_timing['independent_source_gate']=strict_gate
            lk_gate['independent_source_verified']=bool(verified)
            if verified:measured,evidence=second,independent
            else:lk_gate['reliable']=False
        self.last_lk_timing['motion_adaptive_exterior_radius']=radius
        self.last_lk_timing['search_proof_separated']=True
        if not lk_gate['reliable']:
            self.last_lk_timing['failed_exterior_gate']=dict(lk_gate)
            self.last_lk_timing['failed_LK_corners']=q.tolist()
            self.last_lk_timing.update(failure_class='current_exterior_mismatch',
                redundant_full_retry_skipped=True)
            raise LKExteriorMismatch__v31_tracking('LK 四角未通过四条纸张外边缘检查')
        self.last_lk_timing['current_four_edge_gate']=dict(lk_gate)
        if rescue is not None:
            self.book_rescue.remember_flow(p,forward,backward,status,status_b,error,rescue[1],
                self.anchor_q,measured,getattr(self,'source_ready_at',time.perf_counter()),self.lk_channel)
        # Cover points are transient proposals; normal anchors remain exterior-only.
        self._promoted_points=retained.astype(np.float32) if rescue is None else None
        return measured, dict(evidence, **filter_detail)

    def _boundary(self,*args,**kwargs):
        kwargs.setdefault('prefer_vector',self._vector_boundary)
        kwargs.setdefault('boundary_prior',self._target_signature)
        candidate,evidence,gate=current_boundary(*args,**kwargs)
        if gate.get('reliable') and evidence.get('color_vector_proof'):self._vector_boundary=True
        return candidate,evidence,gate

    def _source_confirmation(self,image,gray,candidate,evidence,new_candidate=False,radius=3.,
            reference=None,gray_reliable=None,stable_fb=False,proof_deadline=None,proof_cpu_s=None):
        """Wide candidate search is separate from a narrow current-line proof.

        Normal tracking locks the measured CURRENT line. New admission may
        search from its immutable proposal, then locks its current source64
        line. Independent 24/64 samples never receive the motion search band.
        """
        from geometry import actual_source64 as actual_source64; from geometry import array_key as array_key
        from geometry import original_y_boundary as original_y_boundary
        from geometry import border_signature as border_signature
        from geometry import proof_band as proof_band; from geometry import line_lock as line_lock; from geometry import current_agreement as current_agreement; from geometry import declare_current_y24 as declare_current_y24; from geometry import sample_locked_color as sample_locked_color; from geometry import search_gate as search_gate
        begin=time.perf_counter();cpu=time.thread_time();deadline=begin+.40
        cpu_limit=.18 if new_candidate else .12
        if proof_deadline is not None:deadline=min(deadline,float(proof_deadline))
        if proof_cpu_s is not None:cpu_limit=min(cpu_limit,max(0.,float(proof_cpu_s)))
        wall_limit=max(0.,deadline-begin)
        narrow,half=proof_band(self.scale,evidence)
        proof_gate_radius=3.  # Keep geometry allowance independent of sample width.
        details=dict(budget_basis='proof_thread_CPU_and_separate_wall_guard',
            cpu_budget_s=cpu_limit,wall_guard_s=wall_limit,prior_frame_deadline_not_reused=proof_deadline is None,
            search_radius_tracking=float(radius),proof_radius_tracking=narrow,
            proof_half_source_pixels=half,proof_gate_radius=proof_gate_radius,
            motion_search_band_reused_for_proof=False,
            strict_new_candidate=bool(new_candidate),same_target_FB=bool(stable_fb and not new_candidate))
        memo_token=None
        def available():return time.perf_counter()<deadline and time.thread_time()-cpu<cpu_limit
        def gate(e,q,p,r):
            return exterior_gate(e,q,p,r) if new_candidate else self._edge_gate(e,q,p,r)
        def done(q,e,g,a):
            if memo_token is not None and g.get('reliable') and a.get('verified'):
                self.current_proofs.remember(memo_token,q,e,g,a)
            details.update(wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu,
                wall_guard_hit=time.perf_counter()>=deadline,cpu_budget_hit=time.thread_time()-cpu>=cpu_limit,
                scope='cooperative between calls; native calls cannot be preempted')
            a=dict(a,current_proof_timing=dict(details),old_H_not_used=True)
            if not a.get('verified'):
                a['failure_class']=failure_class(dict(reason=a.get('reason',''),agreement=a,edge_evidence=e))
            self.last_source_confirmation=dict(a,final_gate=dict(g))
            return q,e,g,a
        failed=dict(reliable=False)
        if image is None:return done(candidate,dict(valid=False),failed,dict(verified=False,reason='no_current_source'))
        key=array_key(image);candidate=np.asarray(candidate,np.float32).copy()
        reference=np.asarray(candidate if reference is None else reference,np.float32).copy()
        fitted=evidence.get('physical_source_corners')
        fitted=np.asarray(fitted,np.float32) if fitted is not None else None
        current_primary_bound=bool(evidence.get('valid') and evidence.get('supported_edges')==4
            and evidence.get('refined_corners')==4 and actual_source64(evidence,key) and fitted is not None and fitted.shape==(4,2)
            and np.isfinite(fitted).all() and np.max(np.abs((fitted+.5)/self.scale-.5-candidate))<1e-3)
        if gray_reliable is None:
            gray_reliable=bool(gate(evidence,candidate,reference,radius).get('reliable'))
        memo_token=self.current_proofs.token(image,gray,self._update_index,self.scale,candidate,reference,
            radius,new_candidate,gray_reliable,stable_fb)
        reused_result=self.current_proofs.get(memo_token)
        if reused_result is not None:
            q,e,g,a=reused_result
            a=dict(a,current_same_frame_proof_reused=True,repeated_border_search_skipped=True,
                current_proof_timing=dict(metadata_receipt_reuse=True,wall_s=time.perf_counter()-begin,
                    thread_cpu_s=time.thread_time()-cpu,native_sampling_repeated=False))
            self.last_source_confirmation=dict(a,final_gate=dict(g))
            return q,e,g,a
        details.update(original_reference_preserved=True,reference_corners=reference.tolist(),
            gray_reliable=bool(gray_reliable),color_seed='original_reference' if new_candidate else 'current_locked_line')
        # Strong CURRENT Y and independently spaced source-Y64 share a narrow
        # normal neighborhood. A historical color hint cannot override this.
        if gray_reliable and evidence.get('valid') and not evidence.get('color_vector_proof') and not current_primary_bound and available():
            proof=original_y_boundary(image,self.scale,candidate,radius=narrow)
            if proof is not None:
                yq,ye=proof;yg=gate(ye,yq,candidate,proof_gate_radius);lock=line_lock(candidate,yq)
                first=declare_current_y24(evidence)
                # The tracked Y was produced by this synchronous update. Bind
                # its actual 24-grid to this current source, never as source64.
                first=dict(first,same_frame_source=True,current_source_key=key)
                ya=current_agreement(candidate,yq,first,ye,self.scale,key,
                    stable_fb=stable_fb and not new_candidate)
                details['Y_attempt']=dict(gate=yg,agreement=ya,line_lock=lock)
                if yg.get('reliable') and ya.get('verified') and lock.get('verified'):
                    ya.update(boundary_definition='locked_current_Y24_independent_source_Y64',
                        current_source64_reused=False,line_lock=lock)
                    return done(yq,ye,yg,ya)
                values=first.get('edge_support',[0.]*4)
                weak_Y=(len(values)==4 and min(values)>=.70
                    and sum(v<.80 for v in values)==1)
                if (stable_fb and not new_candidate and weak_Y and yg.get('reliable')
                    and lock.get('verified') and min(ye.get('edge_support',[0.]*4))>=.80
                    and available() and cpu_limit-(time.thread_time()-cpu)>=.025):
                    # Native Y24 reports pre-trim support, not retained span.
                    # Measure one actual independent source24 layout instead
                    # of inventing coverage or repeating an entire YUV64 fit.
                    _,fresh_half=proof_band(self.scale,ye)
                    fresh_q,fresh_e=sample_locked_color(image,self.scale,yq,24,deadline,
                        half_source=fresh_half,lock_evidence=ye)
                    fresh_gate=gate(fresh_e,fresh_q,yq,proof_gate_radius)
                    fresh_lock=line_lock(yq,fresh_q)
                    fresh_agreement=current_agreement(fresh_q,yq,fresh_e,ye,self.scale,key,stable_fb=True)
                    details['fresh_source24_against_existing_Y64']=dict(gate=fresh_gate,
                        agreement=fresh_agreement,line_lock=fresh_lock)
                    if fresh_gate.get('reliable') and fresh_agreement.get('verified') and fresh_lock.get('verified'):
                        fresh_agreement.update(boundary_definition='fresh_source_Y64_and_independent_raw24',
                            existing_source_Y64_retained=True,native_Y24_retained_span_fabricated=False)
                        return done(yq,ye,yg,fresh_agreement)
        if not available():
            return done(candidate,evidence,failed,dict(verified=False,reason='current_proof_budget_exhausted',deadline_hit=True))
        # For new candidates only, obtain a broad current source64 primary from
        # the untouched transported proposal. Unreliable gray cannot move it.
        # A weak Y fit is a proposal, never the seed for a different color
        # physical layer. Keep the untouched motion/candidate reference.
        search=reference if new_candidate or not gray_reliable else candidate
        reused=current_primary_bound
        primary,source=candidate,evidence;paired_secondary=None;pair_detail={}
        pair_trusted=bool(not new_candidate and stable_fb and gray_reliable and evidence.get('valid')
            and not evidence.get('color_vector_proof') and min(evidence.get('edge_support',[0.]*4))>=.80
            and max(evidence.get('edge_rms',[1e30]*4))<=.65
            and gate(evidence,candidate,reference,radius).get('prediction_correction',1e30)<=.75)
        if pair_trusted and not reused:
            from geometry import sample_locked_pair as sample_locked_pair
            paired=sample_locked_pair(image,self.scale,candidate,deadline,evidence,half,
                max(.0005,cpu_limit-(time.thread_time()-cpu)))
            if paired is not None:
                (primary,source),paired_secondary,pair_detail=paired
                details['paired_native_transaction']=pair_detail
        if not reused:
            if paired_secondary is not None:
                first=gate(source,primary,candidate,proof_gate_radius)
            elif new_candidate:
                primary,source=sample_locked_color(image,self.scale,search,64,deadline,
                    half_source=min(24.,max(3.,float(radius)*float(np.max(self.scale)))),lock_physical=False)
                first=search_gate(source,primary,search,radius)
            else:
                primary,source=sample_locked_color(image,self.scale,search,64,deadline,border_signature(evidence),half_source=half,lock_evidence=evidence)
                first=gate(source,primary,search,proof_gate_radius)
            details['color_primary_gate']=first
            provenance=actual_source64(source,key)
            if not first.get('reliable') or not provenance:
                return done(primary,source,failed,dict(verified=False,
                    reason='current_raw_source64_shift_or_quality_rejected' if provenance else 'current_raw_source64_not_completed',
                    deadline_hit=source.get('deadline_hit',False),source64_provenance_verified=bool(provenance),rejected_gate=dict(first)))
        if not new_candidate and source.get('color_vector_proof'):
            from geometry import layer_continuity as layer_continuity
            continuity=layer_continuity(self._target_signature,source)
            details['physical_layer_continuity']=continuity
            if not continuity['verified']:
                return done(primary,source,failed,dict(verified=False,reason='current_signed_physical_layer_changed'))
        # Stable tracking fixes BOTH sample layouts around one current measured
        # line. New admission fixes them around its just-measured source64 line.
        if new_candidate:
            narrow,half=proof_band(self.scale,source)
            details.update(proof_radius_tracking=narrow,proof_half_source_pixels=half)
            if reused:
                first=search_gate(source,primary,reference,radius)
                details['color_primary_gate']=first
                if not first.get('reliable'):
                    return done(primary,source,failed,dict(verified=False,reason='reused_primary_search_bounds_rejected'))
        # A weak/broad tracking-Y line is a search proposal. A fresh strong
        # source64 line can establish the narrow reference after bounded
        # same-target checks, rather than proving a different old-Y layer.
        gray_search_gate=gate(evidence,candidate,reference,radius)
        gray_trusted=bool(gray_reliable and evidence.get('valid') and not evidence.get('color_vector_proof') and
            gray_search_gate.get('prediction_correction',1e30)<=.75 and
            min(evidence.get('edge_support',[0.]*4))>=.80 and
            max(evidence.get('edge_rms',[1e30]*4))<=.65)
        raw_lock=line_lock(candidate,primary)
        stable_rebase=bool(stable_fb and not new_candidate
            and raw_lock.get('line_normal_difference',1e30)<=1.0
            and raw_lock.get('corner_difference',1e30)<=1.5)
        raw_rebase=bool(not new_candidate and not gray_trusted and actual_source64(source,key)
            and source.get('valid') and source.get('supported_edges')==4
            and source.get('refined_corners')==4
            and min(source.get('edge_support',[0.]*4))>=(.75 if stable_rebase else .80)
            and max(source.get('edge_rms',[1e30]*4))<=.65
            and raw_lock.get('line_normal_difference',1e30)<=1.25
            and raw_lock.get('corner_difference',1e30)<=2.)
        details['fresh_source64_reference']=dict(used=raw_rebase,raw_shift=raw_lock,
            old_tracking_Y_is_proposal_only=raw_rebase,independent24_still_required=True)
        pair_rebase=bool(paired_secondary is not None and raw_lock.get('verified'))
        if paired_secondary is not None and not pair_rebase:
            return done(primary,source,failed,dict(verified=False,reason='paired_primary_left_current_search_line',line_lock=raw_lock))
        locked=np.asarray(primary if new_candidate or raw_rebase or pair_rebase else candidate,np.float32).copy()
        primary_lock=line_lock(locked,primary)
        if not primary_lock.get('verified'):
            return done(primary,source,failed,dict(verified=False,reason='source64_left_locked_current_line',line_lock=primary_lock))
        # A completed native pair may finish its existing safety gates after
        # the compute checkpoint; it must not start another sampling call.
        complete_pair=bool(paired_secondary is not None and pair_detail.get('complete'))
        if not available() and not complete_pair:
            return done(primary,source,failed,dict(verified=False,reason='independent_proof_budget_exhausted',deadline_hit=True))
        if paired_secondary is not None and np.array_equal(locked,primary):
            observed,current=paired_secondary
        else:observed,current=sample_locked_color(image,self.scale,locked,24,deadline,border_signature(source),half_source=half,lock_evidence=source)
        checked=gate(current,observed,locked,proof_gate_radius)
        secondary_lock=line_lock(locked,observed)
        agreement=current_agreement(observed,primary,current,source,self.scale,key,
            stable_fb=stable_fb and not new_candidate)
        if not agreement.get('verified') and available() and cpu_limit-(time.thread_time()-cpu)>=.030:
            from geometry import repair_independent24 as repair_independent24
            repaired=repair_independent24(image,self.scale,primary,source,observed,current,half,deadline)
            if repaired is not None:
                observed,current=repaired
                checked=gate(current,observed,locked,proof_gate_radius)
                secondary_lock=line_lock(locked,observed)
                agreement=current_agreement(observed,primary,current,source,self.scale,key,
                    stable_fb=stable_fb and not new_candidate)
                agreement['single_current_side_remeasured']=True
        agreement.update(verified=bool(agreement.get('verified') and primary_lock.get('verified') and secondary_lock.get('verified')),
            current_source64_reused=reused,boundary_definition='locked_current_source64_and_independent24',
            normal_half_window_source_pixels=half,secondary_radius_tracking=narrow,
            primary_line_lock=primary_lock,secondary_line_lock=secondary_lock,
            independent_deadline_hit=current.get('deadline_hit',False),
            current_primary_prior_used=border_signature(source) is not None)
        if not secondary_lock.get('verified'):agreement['reason']='independent24_left_locked_current_line'
        return done(primary,source,checked,agreement)

    def _edge_gate(self,evidence,candidate,prediction,radius):
        supports=evidence.get('edge_support',[0.]*4)
        rms=evidence.get('edge_rms',[1e30]*4)
        correction=float(np.max(np.linalg.norm(candidate-prediction,axis=1)))
        raw_flips=sum(a*b<0 for a,b in zip(self.edge_polarity,evidence.get('edge_polarity',[])))
        # Weak Y can reverse sign on a chromatic exterior. Its raw sign is
        # diagnostic only after the coherent current YUV proof passes all
        # four support/RMS/geometry gates; ordinary Y keeps its polarity gate.
        flips=0 if evidence.get('color_vector_proof') else raw_flips
        reliable=(evidence.get('valid',False) and evidence.get('supported_edges',0)==4
            and evidence.get('refined_corners',0)==4 and min(supports)>=.60
            and max(rms)<=1.0 and correction<=radius*.65 and flips==0)
        return dict(reliable=bool(reliable),min_support=float(min(supports)),max_rms=float(max(rms)),
            prediction_correction=correction,polarity_flips=flips,raw_Y_polarity_flips=raw_flips,radius=radius)

    def _stabilize_current_edges(self,image,gray,candidate,evidence,gate,prediction,previous):
        """Current profiles decide every output; joint geometry only selects work."""
        result=self.stability.measure(gray,previous,prediction,candidate,evidence,
            allow_filter=not evidence.get('color_vector_proof',False))
        if result is None:return candidate,evidence,gate,False
        filtered,updated,detail=result;self.stability_detail=detail
        self._last_measured_motion=detail['raw_motion']
        if detail['physical_layer_suspect']:
            now=time.perf_counter();detail['local_lock_attempted']=False
            if now>=self._edge_lock_next_at:
                detail['local_lock_attempted']=True;cpu=time.thread_time()
                # One narrow CURRENT Y measurement around the physical prediction.
                tight,tight_e=edge_measure__v31_tracking(gray,prediction,1.75,self.checks)
                tight_g=self._edge_gate(tight_e,tight,prediction,1.75)
                from geometry import line_lock as line_lock
                lock=line_lock(prediction,tight)
                strong=(tight_g.get('reliable') and tight_g['min_support']>=.80
                    and tight_g['max_rms']<=.65 and lock.get('verified'))
                if strong:
                    q,e,g,a=self._source_confirmation(image,gray,tight,tight_e,reference=prediction,
                        gray_reliable=True,radius=1.75,proof_deadline=min(now+.18,self._frame_deadline or now+.18),
                        proof_cpu_s=max(0.,.08-(time.thread_time()-cpu)))
                    strong=bool(g.get('reliable') and a.get('verified') and line_lock(prediction,q).get('verified'))
                    if strong:
                        detail.update(local_lock_verified=True,local_lock_wall_s=time.perf_counter()-now,
                            local_lock_thread_cpu_s=time.thread_time()-cpu,current_source_proof_reused=False)
                        self._edge_lock_failures=0;self._edge_lock_next_at=0.
                        self._current_motion_values=None;self.accumulated_drift[:]=self._stability_drift_start
                        return q,e,g,True
                self._edge_lock_failures=min(3,self._edge_lock_failures+1)
                self._edge_lock_next_at=now+min(.6,.15*(2**(self._edge_lock_failures-1)))
                detail.update(local_lock_verified=False,local_lock_wall_s=time.perf_counter()-now,
                    local_lock_thread_cpu_s=time.thread_time()-cpu,next_local_lock_at=self._edge_lock_next_at)
            # Do not authorize an isolated layer jump by four-corner geometry alone.
            return candidate,evidence,dict(gate,reliable=False,physical_layer_ambiguous=True),False
        if detail['filtered']:
            checked=self._edge_gate(updated,filtered,prediction,self._edge_radius)
            if checked.get('reliable'):
                self._current_motion_values=None;self.accumulated_drift[:]=self._stability_drift_start
                return filtered,updated,checked,False
            detail.update(filtered=False,filter_rejected_by_original_gate=True)
        return candidate,evidence,gate,False

    def _exit_verified_calm_burst(self,mode,candidate,previous,prediction,index):
        """Exit only after complete CURRENT FB plus independent same-edge proof."""
        if mode!='lk_measured' or self.anchor_index!=index:return
        timing=self.last_lk_timing;proof=timing.get('source_line_agreement',{})
        gate=timing.get('current_four_edge_gate',{})
        motion=float(np.max(np.linalg.norm(candidate-previous,axis=1)))
        correction=float(np.max(np.linalg.norm(candidate-prediction,axis=1)))
        normalized=motion/max(1.,float(getattr(self,'source_step',1.)))
        okay=('forward_backward_flow_s' in timing and timing.get('stable_FB_context',False)
            and proof.get('verified') and gate.get('reliable') and gate.get('min_support',0.)>=.80
            and gate.get('max_rms',1e30)<=.65 and motion<=1.25 and normalized<=.45 and correction<=.75
            and len(self.anchor_points)>=4)
        timing['calm_burst_exit']=dict(verified=bool(okay),motion_pixels=motion,
            motion_per_capture_frame=normalized,prediction_correction=correction,
            complete_FB_and_independent_edges_required=True)
        if okay:
            self._burst_until=index-1
            self.motion_ema=min(self.motion_ema,normalized);self.correction_ema=min(self.correction_ema,correction)
            self.accumulated_drift.fill(0.);self.drift_budget=0.
            self._edge_lock_failures=0;self._edge_lock_next_at=0.

    def _motion_schedule(self,gate,candidate,prediction,previous,age):
        values=self._current_motion_values;self._current_motion_values=None
        if values is None:
            values=motion_values__v31_native(candidate,prediction,previous,self.anchor_q,self.accumulated_drift) if self.checks=='auto' else None
        if values is None:
            motion=float(np.max(np.linalg.norm(candidate-previous,axis=1)))
            self.accumulated_drift+=(candidate-prediction)
            drift=float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))
            diagonal=float(np.linalg.norm(previous[2]-previous[0]))
            travel=float(np.max(np.linalg.norm(candidate-self.anchor_q,axis=1)))
        else:motion,_,drift,diagonal,travel=values
        source_step=max(1.,float(getattr(self,'source_step',1.)))
        normalized=motion/source_step
        elapsed=getattr(self,'source_elapsed_s',None)
        self.motion_ema=.8*self.motion_ema+.2*normalized
        self._last_measured_motion=float(motion)
        self.correction_ema=.8*self.correction_ema+.2*gate['prediction_correction']
        self.drift_budget+=max(0.,gate['prediction_correction']-.75*gate['max_rms'])
        quality=max(.25,min(1.,gate['min_support']))
        target=max(self.lk_min_gap,min(self.lk_max_gap,round(self.lk_max_gap*quality/(1.+.45*self.motion_ema+.7*self.correction_ema))))
        urgent=(motion>4. or normalized>2. or gate['prediction_correction']>1.5
                or gate['min_support']<.75 or gate['max_rms']>.75)
        if urgent:self._burst_until=self._update_index+3
        # Confidence/motion can override the quiet-scene minimum. FB is never
        # skipped; a successful check promotes current points/pyramids together.
        burst=self._update_index<=self._burst_until
        reason=('hard_maximum_age' if age>=self.lk_max_gap else
                'motion_burst' if burst and age>=1 else
                'accumulated_drift' if age>=self.lk_min_gap and (drift>2. or self.drift_budget>6.) else
                'anchor_displacement' if age>=self.lk_min_gap and travel>max(16.,max(1.,diagonal)*.18) else
                'adaptive_age' if age>=target else None)
        return reason,dict(target_gap=target,hard_max_gap=self.lk_max_gap,min_gap=self.lk_min_gap,
            motion_pixels=motion,motion_per_capture_frame=normalized,source_step=source_step,
            source_elapsed_s=elapsed,processing_gap=bool(getattr(self,'source_processing_gap',False)),motion_ema=self.motion_ema,correction_ema=self.correction_ema,
            burst_active=burst,burst_until_processed_frame=self._burst_until,
            accumulated_drift_pixels=drift,accumulated_excess_residual=self.drift_budget,
            anchor_travel_pixels=travel,min_support=gate['min_support'],prediction_correction=gate['prediction_correction'])

    def _try_book_rescue(self,gray,prediction,image,normal_reason):
        index=self._update_index;book=self.book_rescue;prior_index=book.frame_index
        motion=self.last_lk_timing.get('motion_fit',{})
        if (self.last_lk_timing.get('failure_class')=='current_exterior_mismatch'
                and motion.get('good_features',0)>=8 and motion.get('inlier_fraction',0.)>=.85
                and motion.get('fb_median',1e30)<.7):
            self.last_lk_timing['book_rescue']=dict(attempted=False,
                reason='motion_already_supported_requires_current_edge_remeasure',selection_s=0.)
            return None
        try:
            selected=book.prepare(self.anchor_gray,gray,self.anchor_q,prediction,self.anchor_points,
                index,getattr(self,'source_ready_at',time.perf_counter()),self.lost,self.lk_channel)
        except (ValueError,cv2.error) as exc:
            if book.frame_index==index:self.last_lk_timing['book_rescue']=book.finish(False,exc)
            return None
        if selected is None:
            if book.frame_index==index and prior_index!=index:
                self.last_lk_timing['book_rescue']=book.finish(False,book.detail.get('reason'))
            return None
        previous_deadline=self._frame_deadline;self._frame_deadline=book.deadline
        success=False;failure=None
        try:
            if not book.available():raise ValueError('Cover selection exhausted rescue budget')
            deep=float(np.max(np.linalg.norm(prediction-self.anchor_q,axis=1)))>12.
            result=self._lk(gray,prediction,fast=not deep,source_image=image,rescue=selected)
            if not book.available():raise ValueError('Cover current proof finished outside rescue compute budget')
            success=True
            return result
        except (ValueError,cv2.error) as exc:
            failure=str(exc);self._promoted_points=None
            return None
        finally:
            self._frame_deadline=previous_deadline
            detail=book.finish(success,failure)
            detail.update(normal_failure=str(normal_reason),interior_points_promoted=False,
                auxiliary_coordinates_cached=bool(book.pending is not None),
                independent_current_line_proof_required=True)
            self.last_lk_timing['book_rescue']=detail

    def _lk_current(self,gray,prediction,image):
        from geometry import LKPhaseBudget as LKPhaseBudget; from geometry import LKWorkBudgetExceeded as LKWorkBudgetExceeded
        budget=LKPhaseBudget();prior_deadline=self._frame_deadline
        self._frame_deadline=budget.deadline
        displacement=float(np.max(np.linalg.norm(prediction-self.anchor_q,axis=1)))
        deep=(displacement>12. or float(getattr(self,'source_step',1.))>=6.)
        started=time.perf_counter()
        try:
            try:
                candidate,evidence=self._lk(gray,prediction,fast=not deep,source_image=image)
                self.book_rescue.normal_success()
                self.last_lk_timing.update(search_policy='direct_full_large_motion' if deep else 'predicted_fast',
                    predicted_anchor_displacement=displacement)
                return candidate,evidence
            except LKExteriorMismatch__v31_tracking:
                self._promoted_points=None
                raise  # Repeating the same motion solve cannot prove another edge.
            except (ValueError,cv2.error) as exc:
                self._promoted_points=None
                classified=flow_failure_class(self.last_lk_timing,exc)
                if classified!='motion_unproved':
                    self.last_lk_timing.update(recovery_failure_class=classified,redundant_full_retry_skipped=True)
                    raise LKExteriorMismatch__v31_tracking(str(exc)) from exc
                if deep:raise
                if not budget.retry_allowed():
                    raise LKWorkBudgetExceeded('Complete fast FB attempt finished; full retry deferred by CPU/wall guard') from exc
                spent=time.perf_counter()-started
                candidate,evidence=self._lk(gray,prediction,fast=False,source_image=image)
                self.book_rescue.normal_success()
                self.last_lk_timing.update(search_policy='full_after_fast',fast_attempt_s=spent,
                    predicted_anchor_displacement=displacement)
                return candidate,evidence
        except (ValueError,cv2.error) as exc:
            classified=flow_failure_class(self.last_lk_timing,exc)
            self.last_lk_timing['recovery_failure_class']=classified
            if classified!='motion_unproved':
                # A completed reliable FB solve needs current physical-edge
                # evidence, not another flow/texture solve of this same frame.
                self._promoted_points=None
                self.last_lk_timing.update(cover_retry_skipped=True,
                    cover_retry_skip_reason=classified,next_action='fresh_local_current_edges' if
                    classified=='current_exterior_unproved' else 'fresh_visible_candidate')
                proposed=self.last_lk_timing.get('current_flow_proposal')
                if (classified=='current_exterior_unproved' and proposed is not None
                    and not self.lost and not getattr(self,'source_force_reacquire',False)):
                    q=np.asarray(proposed,np.float32)
                    if q.shape==(4,2) and _valid__v31_tracking(q,gray.shape,self.q,self.checks):
                        self._v81_local_flow_hint=(q.copy(),float(getattr(self,'source_ready_at',time.perf_counter())))
                raise
            # The complete original fast/full retry policy has failed first.
            # A separate finite rescue budget must not replace a normal retry.
            self._promoted_points=None
            rescued=self._try_book_rescue(gray,prediction,image,exc)
            if rescued is not None:return rescued
            raise
        finally:
            entry=budget.summary()
            entry['scope']='normal LK attempt budget; enclosing elapsed includes any separately logged failure-only cover rescue'
            rescue_detail=self.book_rescue.detail if self.book_rescue.frame_index==self._update_index else {}
            entry['cover_rescue_thread_cpu_s']=rescue_detail.get('thread_cpu_s',0.)
            entry['normal_attempt_thread_cpu_s']=max(0.,entry['thread_cpu_s']-entry['cover_rescue_thread_cpu_s'])
            self.last_lk_timing['entry_budget']=entry
            self._frame_deadline=prior_deadline

    def _strict_current_reanchor(self,image,gray,prediction,candidate,evidence):
        radius=self._edge_radius
        gate=self._edge_gate(evidence,candidate,prediction,radius)
        if not gate['reliable']:
            candidate,evidence,_=self._boundary(image,gray,self.scale,prediction,
                measured=candidate,evidence=evidence,checks=self.checks,radius=radius,fast_only=True,deadline=self._frame_deadline,
                expected_polarity=self.edge_polarity,color_profiles=64,prefer_color=True,prefer_vector=True)
            gate=self._edge_gate(evidence,candidate,prediction,radius)
        strict=lambda g:g['reliable'] and g['min_support']>=.80 and g['max_rms']<=.65
        if not strict(gate) or gate['prediction_correction']>1.:return None
        second,independent,checked,agreement=self._source_confirmation(image,gray,candidate,evidence)
        if not strict(checked) or not agreement['verified']:return None
        if not _valid__v31_tracking(second,gray.shape,self.q,self.checks):return None
        return second,independent,dict(state='current_four_edges_twice_verified',
            first_validation=gate,second_validation=checked,source_line_agreement=agreement,old_H_not_used=True)

    def _recover_current_edges(self,gray,candidate,evidence,prediction,previous,gate,reason):
        # Only a correspondence-shortage failure may use stricter independently
        # measured CURRENT outer edges. Other LK/geometry failures fully redetect.
        shortage=('少于4' in reason or 'consistency rejected: -2' in reason)
        if (not shortage or candidate is None or not gate.get('reliable')
            or self.edge_recovery_count>=2 or gate['min_support']<.80
            or gate['max_rms']>.65 or gate['prediction_correction']>1.0):return None
        measured,checked=edge_measure__v31_tracking(gray,candidate,3.,self.checks)
        independent=self._edge_gate(checked,measured,candidate,3.)
        if (not independent['reliable'] or independent['min_support']<.80
            or independent['max_rms']>.65 or independent['prediction_correction']>.6
            or not _valid__v31_tracking(measured,gray.shape,previous,self.checks)):return None
        return measured,checked,dict(state='current_outer_edges_verified',lk_shortage=reason,
            validation=independent,consecutive_recoveries=self.edge_recovery_count+1)

    def _detect_nearby(self,image,prediction,scale,bounded=False,force_full=False):
        # Alternate ROI-first and full-view attempts after repeated failure.
        # Both share ONE candidate/time budget; a spent ROI budget is not reset.
        # A failed current exterior is evidence that the old ROI is unsafe.
        # Search the existing whole small Y, then refine its NEW candidate.
        full_first=force_full or (bounded and (self.lost or self._recovery_attempts%2==0))
        route='current_exterior_mismatch_global_Y' if force_full else ('lost_or_alternate_global_Y' if full_first else 'verified_prediction_ROI')
        raw_yuyv=image.ndim==3 and image.shape[2]==2
        # A full detector is kept as final fallback. ROI candidates must also
        # match the previous current-frame geometry and measured exterior edges.
        q=((prediction+.5)*scale-.5).astype(np.float32);h,w=image.shape[:2]
        pad=max(24.,float(max(scale))*12.)
        lo=np.maximum(0,np.floor(q.min(axis=0)-pad)).astype(int)
        hi=np.minimum([w,h],np.ceil(q.max(axis=0)+pad)).astype(int)
        x0,y0=map(int,lo);x1,y1=map(int,hi)
        if raw_yuyv:
            # A local YUYV view must start on Y0/U and contain complete pairs.
            x0=(x0//2)*2;x1=min(w,((x1+1)//2)*2)
        if not full_first and (x1-x0)*(y1-y0)<.80*w*h and min(x1-x0,y1-y0)>=32:
            began=time.perf_counter()
            try:
                with recovery_view_scope((x0,y0)):local,info=self._detect(image[y0:y1,x0:x1])
                full=np.asarray(local,np.float32)+[x0,y0]
                observed=((full+.5)/scale-.5).astype(np.float32)
                if not _valid__v31_tracking(observed,self.last_gray.shape,self.q,self.checks):raise ValueError('ROI detection geometry mismatch')
                receipt=read_current_receipt(info,image,self.last_gray,scale,self._update_index,full)
                if receipt is None:
                    measured,e=edge_measure__v31_tracking(self.last_gray,observed,3.,self.checks)
                    g=self._edge_gate(e,measured,observed,3.)
                    if not g['reliable']:
                        measured,e,_=self._boundary(image,self.last_gray,scale,observed,measured=measured,evidence=e,checks=self.checks)
                        g=self._edge_gate(e,measured,observed,3.)
                    if not g['reliable']:raise ValueError('ROI detection does not match current exterior')
                return full,dict(info,roi=[x0,y0,x1,y1],recovery_backend='p1_predicted_roi',recovery_route=route,stale_prediction_ROI_skipped=False,roi_detection_s=time.perf_counter()-began)
            except (ValueError,cv2.error,TypeError):
                if bounded:
                    try:_budget_check('ROI_to_full_fallback')
                    except _DetectionStop as exc:
                        raise QuadDetectionError(str(exc),_RECOVERY_BUDGET.get().summary()) from exc
        full,info=self._detect(image)
        return full,dict(info,recovery_backend='p1_full_frame',recovery_route=route,
            stale_prediction_ROI_skipped=bool(force_full))

    def _search_radius(self,previous,step,source_gap):
        speed=max(float(np.max(np.linalg.norm(self.velocity,axis=1))),self.motion_ema)
        drift=float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))
        uncertainty=.25*speed*max(0.,step-1.)+.15*drift+.5*self.correction_ema+(1. if source_gap else 0.)
        shortest=float(np.min(np.linalg.norm(np.roll(previous,-1,axis=0)-previous,axis=1)))
        cap=max(3.,min(6.,.06*shortest))
        return float(np.clip(3.+uncertainty,3.,cap)),dict(radius_cap=cap,prediction_uncertainty=uncertainty,
            source_step=step,speed_per_capture_frame=speed,all_four_edges_required=True)

    def update(self, image, index):
        self.last_source_confirmation={}  # Per-current-frame diagnostic only.
        self.edge_workspace.decode_timing=(0.,0.)
        self.observer.transaction.decode_timing=(0.,0.)
        self.current_proofs.clear()
        self.fastpath_detail=dict(policy='V49_ordinary_current_edges',route='pending',
            ordinary_stability_probe=False,ordinary_illumination_probe=False,same_frame_receipt_reused=False)
        self.quick_recovery_detail=dict(attempted=False,verified=False)
        self.photometric.detail=dict(available=False,reason='V49_ordinary_path_no_illumination_probe',frame_index=index)
        self.stability_detail=dict(available=False,reason='V49_ordinary_path_no_extra_stability_remeasurement',frame_index=index)
        began=time.perf_counter();begin_cpu=time.thread_time();self._update_index=index;self._flow_cache=None
        budget_ms=(None if self.recovery_budget_ms is None else
            self.reacquire_budget_ms if (self.lost or getattr(self,'source_force_reacquire',False)) else self.recovery_budget_ms)
        lost_at_entry=self.lost
        retry_deferred=bool(lost_at_entry and getattr(self,'continuity_hold',False) and began<self._recovery_next_at)
        if retry_deferred:self._recovery_next_index=max(self._recovery_next_index,index+1)
        self._total_deadline=None if budget_ms is None else began+budget_ms/1000.
        # Current proof has priority. Global search gets the remaining budget;
        # an exhausted update rejects this frame and retries on the next one.
        # Reserving 60ms first starved FB LK's independent 64/24 proof.
        self._reserved_detection_ms=0. if budget_ms is None or lost_at_entry or self.recovery_worker is not None else min(15.,budget_ms*.125)
        self._frame_deadline=(None if budget_ms is None else
            began+.40 if self.recovery_worker is not None else
            self._total_deadline if lost_at_entry else began+(budget_ms-self._reserved_detection_ms)/1000.)
        if not self.started or image.shape!=self.shape or index<=self.last_index:
            raise ValueError('连续帧尺寸或顺序改变')
        async_result=None
        if lost_at_entry and self.recovery_worker is not None:
            async_result=self.recovery_worker.take()
            current_proposal=bool(async_result is not None and async_result.get('valid')
                and time.perf_counter()-async_result['ready']<=self.recovery_result_max_age_s)
            if not current_proposal:
                if self._quick_recovery_attempted and not self._local_due():
                    return self._async_wait(image,index,began,begin_cpu,'Awaiting current admitted background candidate',async_result)
                async_result=None
        previous=self.q.copy();dt=max(1.,float(getattr(self,"source_step",index-self.last_index)))
        source_gap=bool(getattr(self,'source_force_reacquire',False))
        # Do not extrapolate a stale velocity across a long USB capture gap.
        prediction=previous.copy() if source_gap else self.q+self.velocity*dt
        self._edge_radius,search_detail=self._search_radius(previous,dt,source_gap)
        self._stability_drift_start[:]=self.accumulated_drift
        context=(prediction,previous,self.anchor_q,self.accumulated_drift,self.edge_polarity,self._edge_radius) if not lost_at_entry and self.checks=='auto' and self.policy=='motion_adaptive' else None
        tg=time.perf_counter();gray,scale=self.observer.get(image,context)
        self.last_gray=gray;gray_s=time.perf_counter()-tg
        self.current_proofs.begin(image,gray,index,scale)
        self._promoted_points=None;self.last_lk_timing={}
        age=index-self.anchor_index+int(getattr(self,"source_age_extra",0))
        scheduled=(age>=(self.interval if self.policy=='periodic' else self.lk_max_gap)
            or bool(self._lk_budget_deferrals))
        # previous/dt/prediction were computed before this same-frame observation.
        evidence,reason,detection={},None,None
        mode,reseed='edge_measured',False;gate={};lk_trigger=None;motion_schedule={};adaptive_reason=None
        stable_detail=dict(eligible=False,policy='strict_current_reacquisition')
        self._current_motion_values=None
        measured_edge_candidate=None;measured_edge_evidence=None;recovery_detail={};gap_anchor_retained=False;recovery_attempt_detail={}
        from geometry import LKWorkBudgetExceeded as LKWorkBudgetExceeded
        try:
            if lost_at_entry and async_result is not None:
                candidate,evidence,recovery_detail=self._admit_async_candidate(image,gray,scale,async_result,index)
                gate=recovery_detail['first_validation'];mode,reseed='current_edge_reacquire',True
                self.edge_polarity=list(evidence['edge_polarity'])
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
            elif lost_at_entry and self.recovery_worker is not None:
                hint=getattr(self,'_v81_local_flow_hint',None);self._v81_local_flow_hint=None
                hint_current=bool(hint is not None and self._local_due()
                    and 0<=time.perf_counter()-hint[1]<=.35 and not source_gap)
                if hint_current:
                    # Coordinates only, one use. No receipt/H/valid timestamp
                    # comes from this prior failed frame; prove CURRENT edges.
                    self._quick_recovery_attempted=True
                    local=self._local_exterior(image,gray,scale,hint[0],index)
                    if local is not None:local[2]['proposal_source']='recent_complete_FB_coordinates_only'
                else:
                    if self._local_due():
                        self._quick_recovery_attempted=True
                        local=self._local_exterior(image,gray,scale,prediction,index)
                    elif not self._quick_recovery_attempted:
                        local=self._quick_current_candidate(image,gray,scale,index)
                    else:local=None
                if local is None:
                    return self._async_wait(image,index,began,begin_cpu,'Local current exterior unproved; await background candidate',
                        observation=dict(gray_s=gray_s,gray_detail=dict(self.observer.detail),
                            current_source_proof=dict(self.last_source_confirmation)))
                candidate,evidence,recovery_detail=local
                gate=recovery_detail['first_validation'];mode,reseed='current_edge_reacquire',True
                self.edge_polarity=list(evidence['edge_polarity'])
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
            elif lost_at_entry:
                self.state='LOST' 
                candidate,evidence=edge_measure__v31_tracking(gray,prediction,3.,self.checks)
                gate=self._edge_gate(evidence,candidate,prediction,3.)
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
                # Leave most of the total budget for global detection if the
                # current exterior cannot be proved near its last location.
                current_deadline=self._frame_deadline
                self._frame_deadline=min(current_deadline,time.perf_counter()+.055) if current_deadline is not None else None
                proof_allowed=(not retry_deferred or (gate['reliable'] and
                    time.perf_counter()>=self._continuity_proof_next_at))
                if proof_allowed and getattr(self,'continuity_hold',False):
                    self._continuity_proof_next_at=time.perf_counter()+.10
                try:proof=(self._strict_current_reanchor(image,gray,prediction,candidate,evidence)
                    if proof_allowed else None)
                finally:self._frame_deadline=current_deadline
                if proof is not None:
                    candidate,evidence,recovery_detail=proof
                    mode,reseed='current_edge_reacquire',True
                    recovery_detail.update(state='LOST_current_source64_reacquired',old_LK_skipped=True)
                elif index<self._recovery_next_index:
                    raise ValueError('LOST: current exterior not proved; global retry deferred')
                else:raise ValueError('LOST: prioritize current global detection; old LK skipped')
            if self.observer.merged_error is not None:raise ValueError('Native edge observation rejected: '+str(self.observer.merged_error))
            if mode=='current_edge_reacquire':pass
            elif source_gap:
                was_lost=self.lost
                if self.observer.merged_edges is not None:
                    candidate,evidence,gate,self._current_motion_values=self.observer.merged_edges
                else:candidate,evidence=edge_measure__v31_tracking(gray,prediction,self._edge_radius,self.checks)
                proof=self._strict_current_reanchor(image,gray,prediction,candidate,evidence)
                if proof is None:
                    candidate,evidence=self._lk_current(gray,prediction,image)
                    mode,reseed='lk_measured',True;lk_trigger='lost_or_capture_gap'
                else:
                    candidate,evidence,recovery_detail=proof
                    gate=self._edge_gate(evidence,candidate,candidate,3.)
                    measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
                    anchor_supported=_spatial_support__v31_tracking(self.anchor_points,self.anchor_q,self.checks)
                    travel=float(np.max(np.linalg.norm(candidate-self.anchor_q,axis=1)))
                    can_retain=(not was_lost and self.policy=='motion_adaptive' and anchor_supported
                        and age<self.lk_max_gap and travel<=1. and self._gap_anchor_reuses<3
                        and float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))<2.
                        and self.drift_budget<6.)
                    if scheduled and (anchor_supported or self._lk_budget_deferrals):
                        self.current_proofs.remember_measurement(image,gray,index,scale,candidate,evidence)
                        candidate,evidence=self._lk_current(gray,candidate,image)
                        mode,reseed='lk_measured',True;lk_trigger='gap_maximum_anchor_age'
                    elif can_retain:
                        mode,reseed='gap_edge_reanchor',False
                        gap_anchor_retained=True;self._gap_anchor_reuses+=1
                        recovery_detail.update(anchor_action='retain_original_gray_points_pyramid',anchor_age=age)
                    else:
                        # Re-seeding is allowed only from two current measured
                        # exterior proofs. It is not a synthetic LK observation.
                        mode,reseed='gap_edge_reanchor',True
                        recovery_detail['anchor_action']='seed_current_twice_verified_edges'
                    recovery_detail.update(source_gap=source_gap,was_lost=was_lost,source_step=dt)
            elif self.policy=='periodic'  and (self.lost or scheduled):
                candidate,evidence=self._lk(gray,source_image=image);mode,reseed='lk_measured',True;lk_trigger='periodic'
            else:
                # Even at maximum LK age, measure the CURRENT outer boundary first.
                radius=self._edge_radius
                fused=self.observer.merged_edges
                if fused is None:
                    fused=self.edge_workspace.measure(gray,prediction,previous,self.anchor_q,
                        self.accumulated_drift,self.edge_polarity,radius) if self.checks=='auto' and self.policy=='motion_adaptive' else None
                if fused is None:
                    candidate,evidence=edge_measure__v31_tracking(gray,prediction,radius,checks=self.checks)
                    gate=self._edge_gate(evidence,candidate,prediction,radius)
                else:candidate,evidence,gate,self._current_motion_values=fused
                if not gate['reliable']:
                    candidate,evidence,_=self._boundary(image,gray,scale,prediction,measured=candidate,evidence=evidence,
                        checks=self.checks,radius=radius,fast_only=True,deadline=self._frame_deadline,
                        expected_polarity=self.edge_polarity,color_profiles=24,
                        prefer_color=False,prefer_vector=False)
                    gate=self._edge_gate(evidence,candidate,prediction,radius)
                    self._current_motion_values=None
                from display import evidence_snapshot as evidence_snapshot
                measured_edge_candidate=candidate.copy();measured_edge_evidence=evidence_snapshot(evidence)
                self.fastpath_detail['route']='current_color_edges' if evidence.get('color_vector_proof') else 'current_Y_edges'
                if self.policy=='motion_adaptive' and gate['reliable']:
                    # A replaced measurement recomputes drift once from its saved
                    # pre-observation value, rather than counting both searches.
                    if self._current_motion_values is None:self.accumulated_drift[:]=self._stability_drift_start
                    adaptive_reason,motion_schedule=self._motion_schedule(gate,candidate,prediction,previous,age)
                    if radius>3.25 and gate['prediction_correction']>1.:
                        adaptive_reason='expanded_band_current_motion';motion_schedule['wide_band_FB_required']=True
                    if self._lk_budget_deferrals:
                        adaptive_reason='pending_complete_current_FB'
                        motion_schedule['deferred_FB_required']=True
                    scheduled=adaptive_reason is not None
                need_lk=self.lost or not gate['reliable'] or scheduled
                if self.policy=='periodic':
                    need_lk=self.lost or not gate['reliable'];mode='prediction_edge_corrected'
                if need_lk:
                    lk_trigger=('lost' if self.lost else (adaptive_reason or 'maximum_gap') if scheduled and gate['reliable']
                                else 'edge_confidence')
                    if gate['reliable']:self.current_proofs.remember_measurement(image,gray,index,scale,candidate,evidence)
                    candidate,evidence=self._lk_current(gray,candidate if gate['reliable'] else prediction,image)
                    mode,reseed='lk_measured',True
            if mode=='edge_measured':
                stable_detail=ordinary_policy(evidence,self._edge_gate(evidence,candidate,prediction,self._edge_radius),
                    age,self.lk_max_gap,scheduled=scheduled,lost=lost_at_entry)
            if self._edge_radius>3.25 and mode=='edge_measured':
                # V49 expanded ordinary searches require actual source four
                # edges before H, while LK/new admission keep independent proof.
                from geometry import original_y_boundary as original_y_boundary
                proof=original_y_boundary(image,scale,candidate,radius=3.)
                precise,precise_e=(candidate,dict(valid=False)) if proof is None else proof
                pg=self._edge_gate(precise_e,precise,candidate,3.) if proof is not None else dict(reliable=False)
                if not pg['reliable']:
                    precise,precise_e,_=self._boundary(image,gray,scale,candidate,
                        measured=precise,evidence=precise_e,checks=self.checks,radius=3.,fast_only=True,
                        deadline=self._frame_deadline,expected_polarity=self.edge_polarity,
                        color_profiles=64,prefer_color=True)
                    pg=self._edge_gate(precise_e,precise,candidate,3.)
                if not pg['reliable']:
                    raise LKExteriorMismatch__v31_tracking('V49 expanded band failed current source-resolution four-edge proof')
                candidate,evidence=precise,precise_e
                gate=pg
                self.fastpath_detail['expanded_source_four_edges']=True
            flips=0 if evidence.get('color_vector_proof') else sum(a*b<0 for a,b in zip(self.edge_polarity,evidence.get('edge_polarity',[])))
            if flips>=2:raise ValueError('边界极性改变，拒绝内部网格边界')
            fresh_admission=(mode=='current_edge_reacquire' and
                (async_result is not None or self.quick_recovery_detail.get('verified',False)))
            reference=None if fresh_admission else previous
            if not _valid__v31_tracking(candidate,gray.shape,reference,self.checks):raise ValueError('本帧四角不合法')
        except (ValueError,cv2.error) as exc:
            reason=str(exc)
            if isinstance(exc,LKWorkBudgetExceeded) and not lost_at_entry and getattr(self,'_lk_budget_deferrals',0)<2:
                # Do not call a time deferral a target replacement. No current
                # admission or anchor promotion occurs. Next frame still owes FB;
                # the pipeline may use ONLY its pre-existing finite HELD policy.
                self._promoted_points=None;self.last_index=index
                self._lk_budget_deferrals=getattr(self,'_lk_budget_deferrals',0)+1
                return dict(valid=False,mode='budget_deferred',reason=reason,index=index,
                    tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-begin_cpu,
                    gray_s=gray_s,gray_detail=dict(self.observer.detail),feature_update_s=0.,
                    feature_detail=dict(action='retain_real_anchor_pending_FB',roi_s=0.),
                    lk_timing=dict(self.last_lk_timing),lk_trigger=lk_trigger,
                    tracking_state=self.state,edge_gate=dict(gate),edge_evidence=dict(evidence),
                    final_admission_gate=dict(reliable=False),current_source_proof=dict(self.last_source_confirmation),
                    recovery_attempt=dict(state='compute_budget_deferred',physical_loss_proven=False,
                        current_output_verified=False,hold_timer_renewed=False,FB_required_next_frame=True,
                        consecutive_deferrals=self._lk_budget_deferrals,maximum_consecutive_deferrals=2))
            if isinstance(exc,LKWorkBudgetExceeded):
                self.last_lk_timing.update(budget_deferral_limit_reached=True,
                    recovery_reason='bounded_compute_retries_exhausted; request new current anchor',physical_loss_proven=False)
            try:
                recovered=self._recover_current_edges(gray,measured_edge_candidate,measured_edge_evidence,
                    prediction,previous,gate,reason)
                if recovered is not None:
                    candidate,evidence,edge_recovery=recovered
                    recovery_detail=dict(recovery_detail,**edge_recovery,source_gap=source_gap,
                        anchor_action="seed_current_verified_frame_after_LK_shortage")
                    mode,reseed='measured_edge_recovery',True
                    self.edge_recovery_count+=1
                else:
                    if self.recovery_worker is not None:
                        return self._async_wait(image,index,began,begin_cpu,reason,async_result,
                            dict(gray_s=gray_s,gray_detail=dict(self.observer.detail),edge_gate=dict(gate),
                                 edge_evidence=dict(evidence),lk_timing=dict(self.last_lk_timing),lk_trigger=lk_trigger,
                                 current_source_proof=dict(self.last_source_confirmation)),request_background=not self._local_due())
                    if self.recovery_budget_ms is not None:
                        if self.lost and index<self._recovery_next_index:
                            recovery_attempt_detail=dict(state='bounded_backoff',next_index=self._recovery_next_index,
                                maximum_processed_frame_gap=self.recovery_backoff_max_frames,
                                current_edge_observation_attempted=True,current_edge_candidate_available=measured_edge_candidate is not None,invalid_frame_skipped=True)
                            self.recovery_stats['deferred']+=1
                            raise ValueError('Recovery retry deferred; no stale H submitted')
                        from geometry import array_key as array_key
                        reacquire=self.lost or source_gap
                        stage_begin=time.perf_counter();stage_cpu=time.thread_time()
                        remaining_ms=max(0.,(self._total_deadline-stage_begin)*1000.)
                        budget=RecoveryBudget(remaining_ms,
                            self.reacquire_max_candidates if reacquire else self.recovery_max_candidates,
                            begin=stage_begin,begin_cpu=stage_cpu)
                        budget.tracker_begin=began;budget.tracker_budget_ms=budget_ms
                        self._frame_deadline=self._total_deadline
                        self.state='REACQUIRING'
                        self._recovery_attempts+=1;self.recovery_stats['attempts']+=1
                        # This merely prioritizes a current candidate, without
                        # waiving LK or original-Y/final independent admission.
                        strong=(measured_edge_candidate is not None and gate.get('reliable')
                            and gate['min_support']>=.80 and gate['max_rms']<=.65
                            and gate['prediction_correction']<=1.)
                        proposal=((measured_edge_candidate+.5)*scale-.5) if strong else None
                        try:
                            with recovery_detection_scope(budget,dict(gray=gray,scale=scale,source_shape=image.shape,
                                    verified_edge_proposal=proposal,frame_index=index,
                                    source_key=array_key(image))):
                                global_current=(lost_at_entry or isinstance(exc,LKExteriorMismatch__v31_tracking) or not gate.get('reliable',False))
                                full,detection=self._detect_nearby(image,measured_edge_candidate if strong else prediction,scale,bounded=True,force_full=global_current)
                        finally:
                            recovery_attempt_detail=dict(budget.summary(),budget_class="reacquisition" if reacquire else "ordinary",
                                 current_Y_reused=True,current_exterior_proposal_used=bool(strong),
                                 whole_tracker_budget=False,total_tracker_budget_ms=budget_ms,
                                 pre_detection_s=stage_begin-began,detector_phase_budget_ms=remaining_ms,
                                 detector_first_on_LOST=lost_at_entry,old_LK_skipped=lost_at_entry,
                                 reserved_detection_ms=self._reserved_detection_ms,
                                 total_tracker_elapsed_s=time.perf_counter()-began,
                                 global_current_Y_first=bool(lost_at_entry or isinstance(exc,LKExteriorMismatch__v31_tracking) or not gate.get('reliable',False)),
                                 trigger_class='LKExteriorMismatch' if isinstance(exc,LKExteriorMismatch__v31_tracking) else 'current_geometry_or_flow')
                            self.recovery_stats['elapsed_s']+=recovery_attempt_detail['elapsed_s']
                            self.recovery_stats['overshoot_s']+=recovery_attempt_detail['overshoot_s']
                            self.recovery_stats['budget_stops']+=int(budget.stopped is not None)
                    else:full,detection=self._detect_nearby(image,prediction,scale)
                    candidate=((np.asarray(full)+.5)/scale-.5).astype(np.float32)
                    if not _valid__v31_tracking(candidate,gray.shape,checks=self.checks):raise ValueError('重检四角异常')
                    receipt=read_current_receipt(detection,image,gray,scale,index,full)
                    detection.pop('_current_boundary_receipt',None)
                    if receipt is not None:
                        measured,reacquired,reacquisition_gate=receipt
                        self.last_source_confirmation=dict(reacquisition_gate.get('current_source_agreement',{}),
                            final_gate=dict(reacquisition_gate))
                    else:
                        measured,reacquired=edge_measure__v31_tracking(gray,candidate,3.,self.checks)
                        reacquisition_gate=exterior_gate(reacquired,measured,candidate,3.)
                        if not reacquisition_gate['reliable']:
                            measured,reacquired,reacquisition_gate=self._boundary(image,gray,scale,candidate,measured=measured,evidence=reacquired,checks=self.checks)
                    recovery_detail=dict(recovery_detail,state='full_redetection_validation',validation=reacquisition_gate,
                        edge_evidence=reacquired,corners=candidate.tolist())
                    if not reacquisition_gate['reliable'] or not _valid__v31_tracking(measured,gray.shape,checks=self.checks):
                        raise ValueError('重检未通过四条外边缘验证: '+str(reacquisition_gate))
                    # Use the measured intersections, not the coarse proposal.
                    # Strong full-frame detection establishes its own polarity;
                    # ordinary tracking still rejects polarity flips and uses FB LK.
                    candidate=measured
                    self.edge_polarity=reacquired['edge_polarity']
                    mode,reseed='full_redetect',True;evidence=reacquired
                    self.edge_recovery_count=0
            except (ValueError,cv2.error) as failure:
                self.lost=True;self.state='LOST';self.velocity[:]=0;self.last_index=index
                if self.recovery_budget_ms is not None and recovery_attempt_detail.get('state')!='bounded_backoff':
                    self._recovery_failures+=1
                    gap=min(self.recovery_backoff_max_frames,1<<min(3,max(0,self._recovery_failures-1)))
                    self._recovery_next_index=index+gap
                    if getattr(self,'continuity_hold',False):
                        retry_s=min(self.recovery_retry_max_s,self.recovery_retry_min_s*(2**min(2,self._recovery_failures-1)))
                        self._recovery_next_at=time.perf_counter()+retry_s
                        recovery_attempt_detail.update(next_retry_at=self._recovery_next_at,retry_backoff_s=retry_s)
                    recovery_attempt_detail.update(failure_count=self._recovery_failures,next_index=self._recovery_next_index,
                        current_edge_observation_attempted=True,current_edge_candidate_available=measured_edge_candidate is not None,invalid_frame_skipped=True)
                    self._remember_recovery_failure(gray,index,prediction,recovery_attempt_detail)
                return dict(valid=False,mode='lost_skip',reason=str(failure),trigger=reason,
                    tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-begin_cpu,index=index,gray_s=gray_s,
                    gray_detail=dict(self.observer.detail),feature_update_s=0.,
                    feature_detail=dict(action='lost_skip',roi_s=0.),lk_timing=dict(self.last_lk_timing),
                    tracking_policy=self.policy,lk_channel=self.lk_channel,lk_trigger=lk_trigger,edge_gate=gate,
                    tracking_state=self.state,prediction_gate=dict(gate),final_admission_gate=dict(reliable=False),
                    lk_current_gate=self.last_lk_timing.get('current_four_edge_gate'),search_band=search_detail,
                    edge_evidence=evidence,detection=detection,reacquisition=recovery_detail,
                    detector_failure=getattr(failure,'diagnostics',None),source_gap=source_gap,
                    recovery_attempt=recovery_attempt_detail)
        self._lk_budget_deferrals=0
        self._v81_local_flow_hint=None
        self.photometric.commit()
        from geometry import align_current as align_current; from geometry import border_signature as border_signature; from geometry import target_relation as target_relation
        identity=dict(state='tracked_current_target',target_changed=False,same_target=True)
        if mode in ('full_redetect','current_edge_reacquire'):
            candidate,evidence=align_current(candidate,evidence,previous)
            self.edge_polarity=list(evidence['edge_polarity'])
            identity,signature=target_relation(previous,candidate,evidence,self._target_signature)
            self._recovery_confirmations=1
            if signature is not None:self._target_signature=signature.copy()
        else:
            self._recovery_confirmations=min(3,self._recovery_confirmations+1)
            signature=border_signature(evidence)
            if signature is not None:self._target_signature=signature.copy()
        if evidence.get('color_vector_proof'):self._vector_boundary=True
        elif identity.get('target_changed'):self._vector_boundary=False
        # Smooth corner velocity only. The newly measured corners themselves
        # are used for H; averaging H coefficients would create geometric lag.
        if self._recovery_failures:
            self.recovery_stats['successes']+=1
        self._recovery_failures=0;self._recovery_next_index=0;self._recovery_attempts=0
        self._recovery_next_at=0.;self._continuity_proof_next_at=0.
        change = (candidate-previous)/max(dt, 1)
        if mode=='lk_measured':self.edge_recovery_count=0
        self.velocity = (self.velocity*.25+change*.75).astype(np.float32)
        if mode in ('full_redetect','gap_edge_reanchor','current_edge_reacquire'):
            self.velocity[:] = 0
            self._promoted_points=None
            self._last_measured_motion=0.;self._edge_lock_failures=0;self._edge_lock_next_at=0.
        same_recovery=bool(mode in ('full_redetect','current_edge_reacquire','gap_edge_reanchor') and identity.get('same_target'))
        if mode in ('full_redetect','current_edge_reacquire'):
            if not identity.get('same_target'):
                self.lk_channel='Y';self._flow_cache=None;self._channel_audit_index=-100
                self.book_rescue.cache=None;self.book_rescue.pending=None
            self.motion_ema=self.correction_ema=0.
            self._burst_until=-1
        np.copyto(self.q,candidate,casting='unsafe')
        self.last_index, self.lost = index, False
        self.state='TRACKING' if self._recovery_confirmations>=3 else 'RECOVERING'
        feature_s=0.;feature_reused=False
        self.last_feature_detail=dict(action='gap_original_anchor_retained' if gap_anchor_retained else 'unchanged_between_lk',
            roi_s=0.,gap_anchor_retained=gap_anchor_retained,consecutive_gap_anchor_reuses=self._gap_anchor_reuses)
        if reseed:
            ts=time.perf_counter()
            anchor_travel=float(np.max(np.linalg.norm(self.q-self.anchor_q,axis=1)))
            retain_original=(same_recovery and self.policy=='motion_adaptive'
                and _spatial_support__v31_tracking(self.anchor_points,self.anchor_q,self.checks)
                and age<self.lk_max_gap and anchor_travel<=min(6.,.04*float(np.min(np.linalg.norm(np.roll(self.q,-1,axis=0)-self.q,axis=1))))
                and self._gap_anchor_reuses<3)
            if retain_original:
                self._gap_anchor_reuses+=1;gap_anchor_retained=True;feature_reused=True
                self.observer.pin(self.anchor_gray if self.lk_channel=='Y' else self.last_gray)
                self.last_feature_detail=dict(action='same_target_original_verified_anchor_retained',roi_s=0.,
                    channel_audit_skipped=True,anchor_age=age,anchor_travel=anchor_travel,
                    forward_backward_due_by=self.anchor_index+self.lk_max_gap,
                    points_synthesized=False,pyramid_promoted=False)
            else:
                self._gap_anchor_reuses=0
            points=self._promoted_points
            if (not retain_original and self.feature_policy=='quality' and mode not in ('full_redetect','measured_edge_recovery','gap_edge_reanchor','current_edge_reacquire') and points is not None):
                # Maintain measured points while their distribution and LK
                # quality remain good; no unconditional 45-frame rebuild.
                quality=(evidence.get('inlier_fraction',0.)>=.85 and
                         evidence.get('fb_median',float('inf'))<.7 and
                         _spatial_support__v31_tracking(points,self.q,self.checks))
                points=self._quality_replenish(self._flow_observation(image,gray),points,self.q,quality,evidence)
            if retain_original:pass
            elif (mode not in ('full_redetect','measured_edge_recovery','gap_edge_reanchor','current_edge_reacquire') and points is not None and
                _spatial_support__v31_tracking(points,self.q,self.checks) and
                (self.feature_policy=='quality' or index-self.seed_index<45)):
                self.anchor_gray=self._flow_observation(image,gray);self.observer.pin(gray)
                self.anchor_q=self.q.copy()
                self.anchor_points=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
                self.anchor_index=index
                self.lk_cache.promote()
                self.book_rescue.mark_anchor(getattr(self,'source_ready_at',time.perf_counter()),self.anchor_q,self.lk_channel)
                feature_reused=True
            else:
                self._seed(gray,self.q,index,image,same_target=same_recovery)
            self.accumulated_drift[:]=0;self.drift_budget=0.
            feature_s=time.perf_counter()-ts
        verified_now=time.perf_counter();source_ready=getattr(self,'source_ready_at',verified_now)
        self._exit_verified_calm_burst(mode,candidate,previous,prediction,index)
        self._last_physical_at=float(source_ready) if np.isfinite(source_ready) and 0<=source_ready<=verified_now else verified_now
        self._local_attempts=0;self._local_next_at=0.
        self._quick_recovery_attempted=False
        self.fastpath_detail.update(route=mode if mode!='edge_measured' else self.fastpath_detail['route'],
            same_frame_receipt_reused=bool(gate.get('same_frame_receipt_reused') or self.last_source_confirmation.get('current_same_frame_proof_reused')))
        tc=time.perf_counter();source_corners=self.corners();source_corners.flags.writeable=False
        source_corners_s=time.perf_counter()-tc
        confidence=float(np.mean(evidence.get('edge_support',[1.])))
        tracker_elapsed=time.perf_counter()-began;tracker_cpu=time.thread_time()-begin_cpu
        post_observation_s=max(0.,tracker_elapsed-(tg-began)-gray_s)
        def diagnostics():
            if self._update_index!=index:raise RuntimeError('Expired tracking diagnostic view; materialize before next frame')
            tm=time.perf_counter();cm=time.thread_time()
            result=dict(valid=True, mode=mode, corners=source_corners.tolist(),
                        confidence=confidence,
                        edge_evidence=evidence, detection=detection, trigger=reason,
                        corner_shift_pixels=float(np.max(np.linalg.norm((self.q-previous)*scale, axis=1))),
                        tracker_s=tracker_elapsed,tracker_thread_cpu_s=tracker_cpu, index=index, scheduled=scheduled,
                        lk_trigger=lk_trigger,tracking_policy=self.policy,lk_channel=self.lk_channel,edge_gate=gate,
                        tracking_state=self.state,prediction_gate=dict(gate),
                        final_admission_gate=self._edge_gate(evidence,self.q,self.q,3.),
                        lk_current_gate=self.last_lk_timing.get('current_four_edge_gate'),search_band=search_detail,
                        channel_selection=dict(self._channel_evidence),
                        lk_age_frames=age,lk_max_gap=self.lk_max_gap,motion_schedule=motion_schedule,
                        gray_s=gray_s, feature_update_s=feature_s, feature_reused=feature_reused,
                        gap_anchor_retained=gap_anchor_retained,
                        gray_detail=dict(self.observer.detail),feature_detail=dict(self.last_feature_detail),
                        feature_seed_count=self.seed_count,feature_count=len(self.anchor_points),
                        edge_recovery=recovery_detail,lk_timing=dict(self.last_lk_timing),recovery_attempt=recovery_attempt_detail,
                        target_identity=identity,target_changed=identity.get('target_changed',False),
                        recovery_confirmations=self._recovery_confirmations,color_boundary_continuity=self._vector_boundary,
                        current_proof_budget_ms=budget_ms-self._reserved_detection_ms if budget_ms is not None else None,
                        same_target_recovery=same_recovery,
                        current_source_proof=dict(self.last_source_confirmation),photometric=dict(self.photometric.detail),
                        edge_stability=dict(self.stability_detail),
                        stable_tracking_policy=stable_detail,localization_baseline='V49_ordinary_V68_strict_new_admission',
                        v49_fastpath=dict(self.fastpath_detail),quick_current_candidate=dict(self.quick_recovery_detail),
                        current_proof_workspace=self.current_proofs.summary(),
                        current_proof_budget_scope='independent LK CPU/wall; narrow current-line proof; strict new admission')
            result['tracking_metadata_build_s']=time.perf_counter()-tm
            result['tracking_metadata_thread_cpu_s']=time.thread_time()-cm
            result['source_corners_s']=source_corners_s
            return result
        if not self.light_results:return diagnostics()
        # Only the current PS caller may consume _diagnostics; it never enters
        # FrameJob or the log queue. The tiny corners snapshot owns its bytes.
        return dict(valid=True,mode=mode,corners=source_corners,confidence=confidence,
            index=index,scheduled=scheduled,lk_trigger=lk_trigger,trigger=reason,
            feature_count=len(self.anchor_points),target_changed=identity.get('target_changed',False),
            tracker_s=tracker_elapsed,tracker_thread_cpu_s=tracker_cpu,tracking_state=self.state,
            edge_gate=gate,lk_timing=self.last_lk_timing,current_source_proof=self.last_source_confirmation,
            v49_fastpath=self.fastpath_detail,quick_current_candidate=self.quick_recovery_detail,
            current_proof_workspace=self.current_proofs.summary(),source_corners_s=source_corners_s,
            post_observation_s=post_observation_s,gray_s=gray_s,_diagnostics=diagnostics)


# ======================================================================
# ===== [03/28] v31_startup =====
# ======================================================================


"""Bounded observed camera stabilization and initial detection admission.

Every discarded MMAP frame is released once. Only an accepted frame transfers
its lease to the caller; no startup frame is submitted to DMA here.
"""
from core import RELEASE_ID as RELEASE_ID
from core import model_bgr as model_bgr; from core import require_yuyv as require_yuyv
from core import checkpoint as checkpoint; from core import RUN_LOG as RUN_LOG

_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def validate_startup(min_frames=12,max_frames=60,stable_pairs=4,timeout_s=3.,detect_attempts=6):
    for name,value in (('startup_min_frames',min_frames),('startup_max_frames',max_frames),
                       ('startup_stable_pairs',stable_pairs),('startup_detect_attempts',detect_attempts)):
        if isinstance(value,bool) or not isinstance(value,int):raise ValueError(name+'必须是整数')
    if not 3<=min_frames<=max_frames<=300 or not 2<=stable_pairs<max_frames:
        raise ValueError('启动帧数须满足3<=min<=max<=300，稳定比较次数须为2..max-1')
    if not 1<=detect_attempts<=12 or not np.isfinite(timeout_s) or not .5<=timeout_s<=10.:
        raise ValueError('首帧检测重试须为1..12次，启动稳定超时须为0.5..10秒')


def _signature(frame,mode):
    image=require_yuyv(frame.image)
    # Only a small strided probe is copied. No full-frame BGR/gray conversion is
    # needed to observe exposure and color stability during startup.
    y=image[::8,::8,0].astype(np.float32)
    if not mode&1:y=np.clip((y-16.)*(255./219.),0.,255.)
    levels=np.percentile(y,(10,50,90))
    u=float(np.median(image[::8,0::16,1]))
    v=float(np.median(image[::8,1::16,1]))
    return np.r_[levels,u,v],dict(luma_p10=float(levels[0]),luma_p50=float(levels[1]),
        luma_p90=float(levels[2]),u_median=u,v_median=v,
        dark_clip_fraction=float(np.mean(y<=2)),bright_clip_fraction=float(np.mean(y>=253)))


def stabilize_camera(camera,min_frames=12,max_frames=60,stable_pairs=4,timeout_s=3.):
    validate_startup(min_frames,max_frames,stable_pairs,timeout_s)
    began=time.perf_counter();deadline=began+timeout_s
    previous=None;previous_sequence=None;previous_ready=None;stable=0;sampling_s=0.;last={}
    tolerance=np.array([5.,3.,5.,3.,3.],np.float64)
    checkpoint('CAMERA_STABILITY_BEGIN',durable=True,min_frames=min_frames,max_frames=max_frames,
        stable_pairs=stable_pairs,timeout_s=timeout_s,tolerance=tolerance.tolist(),
        scope='startup_only_before_initial_detection_and_formal_measurement')
    observed=0
    try:
        for _ in range(max_frames):
            remaining=deadline-time.perf_counter()
            if remaining<=0:break
            try:frame=camera.take(remaining)
            except TimeoutError:
                # Frames were observed: reaching the final wait deadline means
                # stability was not proved, not that the camera supplied no YUYV.
                if observed:break
                raise
            keep=False
            observed+=1
            try:
                probe_begin=time.perf_counter();current,last=_signature(frame,camera.color_mode)
                sampling_s+=time.perf_counter()-probe_begin
                sequence_ok=(previous_sequence is None or
                    0<((frame.sequence-previous_sequence)&0xffffffff)<0x80000000)
                if previous_ready is not None and frame.ready<=previous_ready:sequence_ok=False
                if not sequence_ok:raise ValueError('启动观察的摄像头帧序号或时间不递增')
                delta=np.abs(current-previous) if previous is not None else None
                stable=stable+1 if delta is not None and bool(np.all(delta<=tolerance)) else 0
                previous=current;previous_sequence=frame.sequence;previous_ready=frame.ready
                # Require both enough distinct observations and a minimum real
                # settle time; statistics alone cannot establish camera focus.
                ready=(observed>=min_frames and stable>=stable_pairs and
                       time.perf_counter()-began>=min(.35,timeout_s*.5))
                if ready:
                    report=dict(state='observed_stable',frames_observed=observed,
                        frames_released=observed-1,consecutive_stable_pairs=stable,
                        stabilization_s=time.perf_counter()-began,sampling_s=sampling_s,
                        selected_sequence=int(frame.sequence),last_probe=last,
                        thresholds=tolerance.tolist(),focus_not_measured=True,
                        outside_formal_frame_measurement=True)
                    checkpoint('CAMERA_STABILITY_READY',durable=True,**report)
                    keep=True
                    return frame,report
            finally:
                if not keep:frame.release()
        raise TimeoutError('已收到有效YUYV帧，但启动截止前未能证明亮度/色度稳定（画面波动或后续帧不足）；请查看frames_observed/last_probe')
    except BaseException as exc:
        try:checkpoint('CAMERA_STABILITY_FAILED',durable=True,frames_observed=observed,
            stable_pairs=stable,elapsed_s=time.perf_counter()-began,last_probe=last,
            last_frame_age_s=None if previous_ready is None else time.perf_counter()-previous_ready,
            failure_scope='startup_stability_not_proven' if observed else 'no_valid_frame_observed',
            exception_type=type(exc).__name__,exception=str(exc))
        except BaseException:pass
        raise


def admit_initial_frame(camera,first,detector,attempts=6,timeout_s=6.,save_failed_frame=True,register_lease=None,candidate_preview=None):
    """Own first until accepted; return (lease, owned BGR, detection, report)."""
    began=time.perf_counter();deadline=began+timeout_s
    frame=first;history=[];last_bgr=None;last_failure=None;conversion_s=0.;detection_s=0.
    accepted=False
    try:
        for attempt in range(1,attempts+1):
            remaining=deadline-time.perf_counter()
            if remaining<=0:break
            if frame is None:
                try:frame=camera.take(remaining)
                except TimeoutError as exc:
                    if last_failure is None:raise
                    checkpoint('CAMERA_INITIAL_INPUT_TIMEOUT',exception=str(exc),failed_attempts=len(history))
                    break
            if register_lease is not None:register_lease(frame)
            convert_begin=time.perf_counter();bgr=model_bgr(frame.image)
            conversion_s+=time.perf_counter()-convert_begin
            if candidate_preview is not None:candidate_preview(frame,attempt)
            detect_begin=time.perf_counter()
            try:
                quad,info=detector(frame.image,bgr)
            except QuadDetectionError as exc:
                elapsed=time.perf_counter()-detect_begin;detection_s+=elapsed
                last_failure=exc;last_bgr=bgr
                failure=dict(attempt=attempt,sequence=int(frame.sequence),detection_s=elapsed,
                             reason=str(exc),diagnostics=exc.diagnostics)
                history.append(failure)
                checkpoint('CAMERA_INITIAL_DETECTION_RETRY',**failure)
                frame.release();frame=None
                continue
            elapsed=time.perf_counter()-detect_begin;detection_s+=elapsed
            report=dict(state='accepted',attempts=attempt,failed_attempts=len(history),
                selected_sequence=int(frame.sequence),color_conversion_s=conversion_s,
                detection_s=detection_s,admission_s=time.perf_counter()-began,
                corners=np.asarray(quad).tolist(),detector=info.get('detector'),
                failed_diagnostics=history,outside_formal_frame_measurement=True)
            checkpoint('CAMERA_INITIAL_DETECTION_READY',durable=True,**report)
            accepted=True
            return frame,bgr,(quad,info),report
        image_path=None
        if save_failed_frame and last_bgr is not None:
            path=RUN_LOG.parent/'camera_startup_failed.jpg'
            try:
                if cv2.imwrite(str(path),last_bgr):image_path=str(path)
            except (OSError,cv2.error) as image_error:
                checkpoint('CAMERA_FAILED_IMAGE_SAVE_ERROR',exception=str(image_error))
        checkpoint('CAMERA_INITIAL_DETECTION_FAILED',durable=True,attempts=len(history),
            elapsed_s=time.perf_counter()-began,last_failure=str(last_failure),
            image_path=image_path,failed_diagnostics=history,
            instruction='整张纸的四角须在画面内，建议各留20–30像素背景边距')
        raise ValueError('启动检测未找到完整四角；请调整取景后重试。失败预览：'+str(image_path)) from last_failure
    finally:
        if not accepted and frame is not None:frame.release()


# ======================================================================
# ===== [04/28] v58_budget =====
# ======================================================================


"""CPU work budget plus separate wall guard; no hardware and no hard preemption."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class CpuRecoveryBudget(RecoveryBudget):
    def __init__(self,milliseconds,max_candidates,wall_max_s=.70):
        super().__init__(milliseconds,max_candidates)
        self.wall_max_s=float(wall_max_s);self.deadline=self.begin+self.wall_max_s
        self.deferred_stages=[]
    def can_start_stage(self,stage,cpu_s,wall_s,admission_cpu_s=.09,admission_wall_s=.12):
        """Reserve a complete existing admission; this is a launch guard, not preemption."""
        self.check('before_'+stage)
        remaining_cpu=self.milliseconds/1000.-(time.thread_time()-self.begin_cpu)
        remaining_wall=self.deadline-time.perf_counter()
        allowed=remaining_cpu>=cpu_s+admission_cpu_s and remaining_wall>=wall_s+admission_wall_s
        if not allowed:self.deferred_stages.append(dict(stage=stage,remaining_cpu_s=remaining_cpu,
            remaining_wall_s=remaining_wall,required_cpu_s=cpu_s+admission_cpu_s,
            required_wall_s=wall_s+admission_wall_s))
        return allowed
    def check(self,stage,finish_gate=False):
        # The inherited checkpoints still enforce wall guard/candidate count,
        # and retain stage times. CPU budget does not charge descheduled time.
        super().check(stage,finish_gate)
        if not finish_gate and time.thread_time()-self.begin_cpu>=self.milliseconds/1000.:
            self.stopped='thread_cpu_budget';raise _DetectionStop('恢复检测达到线程CPU预算')
    def summary(self):
        result=super().summary()
        result.update(budget_basis='thread_CPU_plus_separate_wall_guard',wall_guard_s=self.wall_max_s,
            candidate_duplicate_skips=int(getattr(self,'candidate_duplicate_skips',0)),
            deduplication_scope='exact geometry and refinement strategy; one current snapshot only',
            deferred_stages=list(self.deferred_stages),
            wall_guard_overshoot_s=max(0.,time.perf_counter()-self.deadline),
            cpu_budget_overshoot_s=max(0.,result['thread_cpu_s']-self.milliseconds/1000.),
            overshoot_s=max(0.,time.perf_counter()-self.deadline),
            deadline_kind='cooperative CPU checkpoints; native calls see wall guard; final gate cannot be preempted')
        return result


def compact_recovery_summary(summary):
    """Keep proposal/gate failures, without repeated full profile trees."""
    keys=('budget_ms','max_candidates','candidates','elapsed_s','thread_cpu_s','wall_minus_thread_cpu_s',
        'stop_reason','last_stage','budget_basis','wall_guard_s','cpu_budget_overshoot_s','wall_guard_overshoot_s','deferred_stages',
        'candidate_duplicate_skips','deduplication_scope')
    out={k:summary.get(k) for k in keys}
    out['candidate_proposals']=summary.get('candidate_proposals',())[:4]
    out['rejected_candidates']=[]
    for item in summary.get('rejected_candidates',())[-4:]:
        row={k:item.get(k) for k in ('detector','reason')}
        for name in ('gate','agreement'):
            v=item.get(name) or {}
            row[name]={k:v.get(k) for k in ('verified','reliable','min_support','max_rms','prediction_correction','line_normal_difference','normal_limit') if k in v}
        out['rejected_candidates'].append(row)
    out['detail_sampled']=False
    return out


# ======================================================================
# ===== [05/28] v58_recovery =====
# ======================================================================


"""Bounded CPU-only P1-style recovery. Own RAM only; never MMAP/CMA/MMIO."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

_CURSOR_SKIP='recovery_candidate_previously_rejected_in_scene_pass'

class SearchBudget:
    """Construct lazily to preserve import order of existing recovery modules."""
    @staticmethod
    def create(milliseconds,candidates,wall_max_s,cursor):
        class ProgressBudget(CpuRecoveryBudget):
            def __init__(self):
                super().__init__(milliseconds,candidates,wall_max_s=wall_max_s)
                self.cursor=dict(cursor);self.visited={};self.positions=[]
            def claim(self,label,coarse):
                position=self.visited.get(label,0)+1;self.visited[label]=position
                if position<=self.cursor.get(label,0):
                    self.check('recovery_cursor_skip')
                    raise ValueError(_CURSOR_SKIP)
                super().claim(label,coarse);self.positions.append((label,position))
            def completed_cursor(self):
                from collections import Counter
                rejected=Counter(row.get('detector') for row in self.rejections
                    if row.get('reason') not in (_CURSOR_SKIP,'internal_rectangle_has_current_proven_outer'))
                progress=dict(self.cursor)
                for label,position in self.positions:
                    if rejected[label]>0:
                        progress[label]=max(position,progress.get(label,0));rejected[label]-=1
                return progress
        return ProgressBudget()

class RecoveryWorker:
    def __init__(self,detection_limit,tracking_limit,retry_s=.10):
        self.detection_limit=int(detection_limit);self.tracking_limit=int(tracking_limit)
        self.retry_s=float(retry_s);self.condition=threading.Condition()
        self.pending=None;self.result=None;self.busy=False;self.stopped=False;self.error=None
        self.next_request=0.;self.context=contextvars.copy_context()
        self.recent_seeds=[];self.seed_ready=0.;self.seed_shape=None;self.seed_probe=None
        self.seed_cursor=0;self.seed_failures=0;self.detail_next_at=0.
        self.search_round=0;self.search_cursors={True:{},False:{}};self.search_probe=None
        self.metrics=dict(requests=0,successes=0,failures=0,copy_s=0.,worker_wall_s=0.,worker_cpu_s=0.,
            candidate_limit=4,queue_capacity=1,owned_source_bytes=0,hardware_access=False,
            recent_candidate_slices=0,recent_candidate_successes=0,full_searches=0)
        self.thread=threading.Thread(target=self._entry,name='p11-cpu-recovery',daemon=True)
        self.thread.start()

    def request(self,image,index,ready,sequence,budget_ms,max_candidates):
        # Reservation prevents a second copy, even if a caller is interrupted.
        with self.condition:
            if self.error is not None:raise RuntimeError('CPU recovery worker failed') from self.error
            if self.stopped or self.busy or self.pending is not None or self.result is not None or time.perf_counter()<self.next_request:
                return False
            self.busy=True
        began=time.perf_counter()
        try:
            owned=np.array(image,dtype=np.uint8,copy=True,order='C');owned.flags.writeable=False
            item=dict(image=owned,index=int(index),ready=float(ready),sequence=sequence,
                budget_ms=float(budget_ms),max_candidates=int(max_candidates),copied_at=time.perf_counter())
        except BaseException:
            with self.condition:self.busy=False;self.condition.notify_all()
            raise
        with self.condition:
            if self.stopped:self.busy=False;return False
            self.pending=item;self.metrics['requests']+=1;self.metrics['copy_s']+=time.perf_counter()-began
            self.metrics['owned_source_bytes']=owned.nbytes;self.condition.notify_all()
        return True

    def take(self):
        with self.condition:
            if self.error is not None:raise RuntimeError('CPU recovery worker failed') from self.error
            value=self.result;self.result=None
            return value

    def snapshot(self):
        with self.condition:return dict(self.metrics,busy=self.busy,pending=self.pending is not None,
            result_ready=self.result is not None,error=None if self.error is None else repr(self.error))

    def _entry(self):
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.busy=False;self.condition.notify_all()

    def _run(self):
        from core import checkpoint as checkpoint
        observer=GrayObserver__v87_v74_tracking(self.tracking_limit)  # Private to this CPU thread.
        while True:
            with self.condition:
                while self.pending is None and not self.stopped:self.condition.wait()
                if self.stopped:return
                item=self.pending;self.pending=None
            began=time.perf_counter();cpu=time.thread_time()
            # Proposal work in the supplied log already consumed ~300ms CPU
            # before candidate0. Keep a finite separate wall guard, but leave
            # the configured compute budget for actual candidate admission.
            # Hints are geometry proposals, remeasured on this owned CURRENT
            # snapshot; a bounded hint miss never grants a cached proof.
            raw=item['image'];probe=raw[::max(1,raw.shape[0]//12),::max(1,raw.shape[1]//16),0].astype(np.float32) if raw.ndim==3 and raw.shape[2]==2 else None
            centered=None if probe is None else probe-float(np.mean(probe))
            compatible=bool(self.recent_seeds and self.seed_shape==raw.shape and centered is not None
                and self.seed_probe is not None and centered.shape==self.seed_probe.shape
                and 0<=item['ready']-self.seed_ready<=.9 and self.seed_failures<2
                and float(np.median(np.abs(centered-self.seed_probe)))<=12.)
            seeds=(self.recent_seeds[self.seed_cursor%len(self.recent_seeds)],) if compatible else ()
            if compatible:self.seed_cursor+=1
            changed=(centered is None or self.search_probe is None or centered.shape!=self.search_probe.shape
                or float(np.median(np.abs(centered-self.search_probe)))>12.)
            if changed:self.search_cursors={True:{},False:{}};self.search_round=0
            self.search_probe=None if centered is None else centered.copy()
            prefer_mask=True if compatible else self.search_round%2==0
            cursor={} if compatible else self.search_cursors[prefer_mask]
            if not compatible:self.search_round+=1
            slice_ms=min(item['budget_ms'],180.) if compatible else item['budget_ms']
            budget=SearchBudget.create(slice_ms,1 if compatible else item['max_candidates'],.65 if compatible else 1.0,cursor)
            detailed=began>=self.detail_next_at
            if detailed:self.detail_next_at=began+2.
            budget.log_detail=detailed
            with self.condition:self.metrics['recent_candidate_slices' if compatible else 'full_searches']+=1
            result={k:v for k,v in item.items() if k!='image'}
            try:
                source_gray,source_scale=observer.get(item['image'])
                observation=dict(gray=source_gray,scale=source_scale,source_shape=item['image'].shape)
                with recovery_detection_scope(budget,observation),recovery_candidate_scope(seeds,compatible):
                    quad,info=detect_refined(item['image'],self.detection_limit,True,
                        prefer_mask=prefer_mask,tracking_limit=self.tracking_limit)
                result.update(valid=True,source_gray=source_gray.copy(),source_scale=np.asarray(source_scale).copy(),
                    quad=np.asarray(quad,np.float32).copy(),
                    detector_label=info.get('method',info.get('detector')),stale_receipt_retained=False)
            except (ValueError,cv2.error) as exc:
                result.update(valid=False,reason=str(exc),diagnostics=getattr(exc,'diagnostics',None))
            if compatible:
                self.seed_failures=0 if result['valid'] else self.seed_failures+1
                if result['valid']:
                    with self.condition:self.metrics['recent_candidate_successes']+=1
            else:
                progress=budget.completed_cursor()
                advanced=progress!=cursor
                unfinished=([budget.proposals[i] for i,(label,position) in enumerate(budget.positions)
                    if position>progress.get(label,0)] if budget.stopped in ('thread_cpu_budget','cooperative_deadline') else [])
                self.search_cursors[prefer_mask]=progress if (advanced or unfinished) and sum(progress.values())<12 else {}
                # Rejected geometry is not retried as a cheap hint. A candidate
                # interrupted before its gate may resume on a NEW snapshot,
                # without replaying expensive proposal enumeration or evidence.
                self.recent_seeds=([dict(detector='multicolor_exterior' if prefer_mask else 'current_Y',coarse_corners=np.asarray(quad).tolist())]
                    if result['valid'] else unfinished[:1])
                self.seed_ready=float(item['ready']);self.seed_shape=raw.shape;self.seed_probe=None if centered is None else centered.copy()
                self.seed_cursor=0;self.seed_failures=0
            result.update(recent_candidate_slice=compatible,coarse_hint_count=len(self.recent_seeds),
                completed_at=time.perf_counter(),worker_s=time.perf_counter()-began,
                worker_cpu_s=time.thread_time()-cpu,budget=budget.summary())
            checkpoint('ASYNC_RECOVERY_RESULT',index=item['index'],camera_sequence=item['sequence'],
                recent_candidate_slice=compatible,slice_cpu_budget_ms=slice_ms,coarse_hint_count=len(self.recent_seeds),
                valid=result['valid'],source_age_s=time.perf_counter()-item['ready'],
                proposal_family='YUV' if prefer_mask else 'Y',candidate_cursor_before=cursor,
                candidate_cursor_after=self.search_cursors[prefer_mask],
                worker_s=result['worker_s'],worker_cpu_s=result['worker_cpu_s'],
                budget=result['budget'] if detailed else compact_recovery_summary(result['budget']),detail_sampled=detailed,
                hardware_access=False,ownership='one owned ordinary-RAM snapshot')
            with self.condition:
                self.busy=False
                if self.stopped:return
                self.result=result;self.next_request=time.perf_counter()+self.retry_s
                self.metrics['successes' if result['valid'] else 'failures']+=1
                self.metrics['worker_wall_s']+=result['worker_s'];self.metrics['worker_cpu_s']+=result['worker_cpu_s']
                self.condition.notify_all()
            # Do not keep source pixels alongside the finished metadata result.
            item=None

    def close(self):
        with self.condition:
            self.stopped=True;self.pending=None;self.result=None;self.condition.notify_all()
        self.thread.join(5.)
        if self.thread.is_alive():raise TimeoutError('CPU recovery call did not retire; owned RAM retained by worker')
        if self.error is not None:raise RuntimeError('CPU recovery worker failed') from self.error


# ======================================================================
# ===== [06/28] v67_observation =====
# ======================================================================


"""Small photometric diagnostics; never alters image pixels or proves a quad."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class IlluminationMotion:
    def __init__(self):
        u,v=np.meshgrid(np.linspace(.15,.85,8),np.linspace(.15,.85,8))
        u=u.ravel();v=v.ravel()
        self.weights=np.stack(((1-u)*(1-v),u*(1-v),u*v,(1-u)*v),axis=1).astype(np.float32)
        self.xy=np.empty((64,2),np.float32);self.previous=None;self.current=None
        self.last_grace_at=-1e9;self.detail={}
    def observe(self,image,quad,enabled=True):
        began=time.perf_counter();cpu=time.thread_time()
        if not enabled:self.previous=None
        self.current=None
        if image.ndim!=3 or image.shape[2]!=2:
            self.detail=dict(available=False,reason='YUYV_required');return self.detail
        q=np.asarray(quad,np.float32)
        np.matmul(self.weights,q,out=self.xy)
        x=np.clip(np.rint(self.xy[:,0]).astype(np.int32),0,image.shape[1]-1)
        y=np.clip(np.rint(self.xy[:,1]).astype(np.int32),0,image.shape[0]-1)
        values=image[y,x,0].astype(np.float32);self.current=values
        mean=float(np.mean(values));clipped=float(np.mean((values<=20)|(values>=235)))
        changed=False;residual=None;gain=1.;delta=0.
        if self.previous is not None:
            p=self.previous;pm=float(np.mean(p));a=p-pm;b=values-mean
            variance=float(np.dot(a,a));gain=float(np.clip(np.dot(a,b)/max(variance,1.),.5,2.)) if variance>=64. else 1.
            residual=float(np.median(np.abs(b-gain*a)));delta=mean-pm
            changed=bool(abs(delta)>=6. and residual<=5. and .7<=gain<=1.4 and clipped<.10)
        self.detail=dict(available=True,sample_count=64,luma_mean=mean,luma_delta=delta,estimated_gain=gain,
            photometric_residual=residual,clipped_fraction=clipped,illumination_change=changed,
            probe_s=time.perf_counter()-began,probe_thread_cpu_s=time.thread_time()-cpu,
            image_pixels_modified=False,geometric_proof_granted=False)
        return self.detail
    def eligible(self,gate,candidate,previous,age,maximum,reason):
        movement=float(np.max(np.linalg.norm(np.asarray(candidate)-previous,axis=1)))
        eligible=bool(self.detail.get('illumination_change') and gate.get('reliable')
            and gate.get('min_support',0.)>=.80 and gate.get('max_rms',1e30)<=.50
            and gate.get('prediction_correction',1e30)<=1.25 and movement<=1.25
            and age<maximum and reason in ('motion_burst','expanded_band_current_motion')
            and time.perf_counter()-self.last_grace_at>=.5)
        self.detail.update(geometry_motion_tracking_pixels=movement,local_reproof_eligible=eligible,
            prior_LK_trigger=reason,hard_FB_age_preserved=True)
        return eligible
    def accepted_grace(self):
        self.last_grace_at=time.perf_counter();self.detail['current_independent_reproof_passed']=True
    def commit(self):
        if self.current is not None:self.previous=self.current.copy()


# ======================================================================
# ===== [07/28] v31_native =====
# ======================================================================


"""Optional host-architecture C++ helper. Compile once, never inside frame timing."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB__v31_native=None
_STATUS__v31_native={'backend':'numpy_analytic_tls','reason':'native_not_loaded','lk_backend':'opencv_python_binding'}

def prepare_native__v31_native(build=True, required=False,cancel=None):
    global _LIB__v31_native, _STATUS__v31_native
    from core import checkpoint as checkpoint
    check_cancel(cancel)
    root=Path(__file__).resolve().parent
    source=root/'v31_native.cpp'
    manifest=json.loads((root/'release_manifest.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if manifest.get('release_id')!=RELEASE_ID or manifest.get('sha256',{}).get(source.name)!=digest:
        raise ValueError('native source/release hash mismatch; upload complete V31 folder')
    checkpoint('NATIVE_SOURCE_VERIFIED',source_sha256=digest,already_loaded=_LIB__v31_native is not None)
    if _LIB__v31_native is not None and _STATUS__v31_native.get('source_sha256')==digest:
        return dict(_STATUS__v31_native,already_loaded=True)
    cv_flags=[]
    cv_version=None
    pkg=shutil.which('pkg-config')
    if sys.platform.startswith('linux') and pkg:
        import cv2
        probe=setup_command([pkg,'--modversion','opencv4'],10,cancel,'NATIVE_OPENCV_VERSION')
        if probe.returncode==0 and probe.stdout.strip()==cv2.__version__:
            flags=setup_command([pkg,'--cflags','--libs','opencv4'],10,cancel,'NATIVE_OPENCV_FLAGS')
            if flags.returncode==0:
                cv_flags=shlex.split(flags.stdout);cv_version=probe.stdout.strip()
    variant='lk_'+cv_version if cv_flags else 'base'
    name='v31_native_'+digest[:16]+'_'+platform.machine()+'_'+variant+'.so'
    target=root/name
    cache_flags=['-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread']
    if platform.machine()=='armv7l':cache_flags+=['-mfpu=neon']
    if cv_flags:cache_flags+=['-DP11_OPENCV_LK']+cv_flags
    try:
        if not sys.platform.startswith('linux'):
            raise RuntimeError('板端 Linux 编译；Windows 无需编译')
        restore(target,source,'tracker',cache_flags,cancel)
        if not target.is_file():
            if not build:raise RuntimeError('native helper 尚未编译')
            compiler=shutil.which('g++') or shutil.which('c++')
            if not compiler:raise RuntimeError('板端没有 g++/c++；可用解析 TLS 回退，未声称达到30FPS')
            temp=target.with_suffix('.building.so')
            command=[compiler,'-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread',str(source),'-o',str(temp)]
            if platform.machine()=='armv7l':command+=['-mfpu=neon']
            if cv_flags:command+=['-DP11_OPENCV_LK']+cv_flags
            try:
                result=setup_command(command,180,cancel,'NATIVE_BUILD')
                if result.returncode!=0:raise RuntimeError((result.stdout+result.stderr)[-4000:])
                check_cancel(cancel);temp.replace(target)
            finally:
                if temp.exists():temp.unlink()
        check_cancel(cancel)
        checkpoint('NATIVE_LOAD_BEGIN',path=str(target),hardware_access=False)
        lib=ctypes.CDLL(str(target))
        lib.p11_v31_abi.restype=ctypes.c_int
        if lib.p11_v31_abi()!=3107:raise RuntimeError('native helper ABI mismatch')
        vp=ctypes.c_void_p;ci=ctypes.c_int
        lib.p11_edges.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_edges.restype=ci
        lib.p11_guard.argtypes=[vp,vp,vp,ci,vp];lib.p11_guard.restype=ci
        lib.p11_gray2.argtypes=[vp,ci,ci,ci,vp];lib.p11_gray2.restype=ci
        lib.p11_gray_backend.restype=ci
        lib.p11_gaussian3.argtypes=[vp,ci,ci,ci,vp,vp];lib.p11_gaussian3.restype=ci
        lib.p11_quad_valid.argtypes=[vp,ci,ci,vp];lib.p11_quad_valid.restype=ci
        lib.p11_spatial.argtypes=[vp,ci,vp];lib.p11_spatial.restype=ci
        lib.p11_prepare.argtypes=[vp,ci,ci,vp];lib.p11_prepare.restype=ci
        lib.p11_packet.argtypes=[vp,vp,ci,ci,ci,ci,ci,vp];lib.p11_packet.restype=ci
        lib.p11_signature.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp];lib.p11_signature.restype=ci
        lib.p11_filter_available.restype=ci
        if lib.p11_filter_available():
            lib.p11_lk_filter.argtypes=[vp,vp,vp,vp,vp,vp,ci,vp,vp,ci,ci,vp,vp,vp]
            lib.p11_lk_filter.restype=ci
        lib.p11_plan_geometry.argtypes=[vp,vp,vp,ci,ci,vp,vp,ci,vp,vp]
        lib.p11_plan_geometry.restype=ci
        lib.p11_prepare_control.argtypes=[vp,vp,ci,ci,vp,vp,ci,vp,vp,ci,ci,ci,ci,ci,vp,vp]
        lib.p11_prepare_control.restype=ci
        lib.p11_lk_available.restype=ci
        if lib.p11_lk_available():
            lib.p11_lk_create.restype=vp
            lib.p11_lk_destroy.argtypes=[vp];lib.p11_lk_destroy.restype=None
            lib.p11_lk_anchor.argtypes=[vp,vp,ci,ci];lib.p11_lk_anchor.restype=ci
            lib.p11_lk_track.argtypes=[vp,vp,ci,ci,vp,ci,vp,vp,vp,vp,vp,vp,ci,ci]
            lib.p11_lk_track.restype=ci
            lib.p11_lk_track_generation.argtypes=lib.p11_lk_track.argtypes+[ctypes.c_uint32]
            lib.p11_lk_track_generation.restype=ci
            lib.p11_cover_features.argtypes=[vp,ci,ci,vp,vp,ci,vp,vp,ctypes.c_double]
            lib.p11_cover_features.restype=ci
            lib.p11_lk_promote.argtypes=[vp];lib.p11_lk_promote.restype=ci
        lib.p11_observe2.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp];lib.p11_observe2.restype=ci
        lib.p11_probe.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp];lib.p11_probe.restype=ci
        lib.p11_wait_io.argtypes=[vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp]
        lib.p11_wait_io.restype=ci
        lib.p11_profile_snapshot.argtypes=[vp,ci];lib.p11_profile_snapshot.restype=ci
        lib.p11_edges_checked.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp];lib.p11_edges_checked.restype=ci
        lib.p11_motion_values.argtypes=[vp,vp,vp,vp,vp,vp];lib.p11_motion_values.restype=ci
        lib.p11_copy_bgr.argtypes=[vp,vp,ci,ci,ci,ci];lib.p11_copy_bgr.restype=ci
        lib.p11_arm_io.argtypes=[vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ci];lib.p11_arm_io.restype=ci
        lib.p11_frame_state.argtypes=[vp,vp,vp];lib.p11_frame_state.restype=ci
        lib.p11_plan_wait.argtypes=[vp,vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp];lib.p11_plan_wait.restype=ci
        lib.p11_profile_os_snapshot.argtypes=[vp,ci];lib.p11_profile_os_snapshot.restype=ci
        lib.p11_edges_motion.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp]
        lib.p11_edges_motion.restype=ci
        lib.p11_frame_create.argtypes=[];lib.p11_frame_create.restype=vp
        lib.p11_frame_destroy.argtypes=[vp];lib.p11_frame_destroy.restype=None
        lib.p11_frame_prepare.argtypes=[vp,vp,vp,ci,ci,ci,ctypes.c_double,ctypes.c_double,ci,ci,vp,vp,vp,vp,ci,ci,vp,vp,ci,vp,vp,ci,ci,ci,ci,vp,vp,vp,vp,vp,vp]
        lib.p11_frame_prepare.restype=ci
        lib.p11_observe_edges.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp,vp]
        lib.p11_observe_edges.restype=ci
        if lib.p11_lk_available():
            lib.p11_lk_checked.argtypes=[vp,vp,ci,ci,vp,ci,vp,ci,ci,ctypes.c_uint32,vp,vp,vp,vp,vp,vp];lib.p11_lk_checked.restype=ci
            lib.p11_lk_checked_motion.argtypes=[vp,vp,ci,ci,vp,ci,vp,ci,ci,ctypes.c_uint32,vp,vp,vp,vp,vp,vp,vp]
            lib.p11_lk_checked_motion.restype=ci
            lib.p11_roi_features.argtypes=[vp,ci,ci,vp,vp,ci,vp,vp];lib.p11_roi_features.restype=ci
        lib.p11_refine64.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_refine64.restype=ci
        lib.p11_yuyv_refine64.argtypes=[vp,ci,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_yuyv_refine64.restype=ci
        lib.p11_preview_canvas_maps.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,ci,ci,vp,vp,vp,vp,vp]
        lib.p11_preview_canvas_maps.restype=ci
        lib.p11_preview_canvas_linear.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,ci,ci,vp,vp,vp,vp,vp,vp]
        lib.p11_preview_canvas_linear.restype=ci
        lib.p11_yuyv_profiles.argtypes=[vp,ci,ci,ci,vp,vp,ci,vp]
        lib.p11_yuyv_profiles.restype=ci
        lib.p11_io_probe.argtypes=[vp,vp,ctypes.c_uint32,ci,vp];lib.p11_io_probe.restype=ci
        lib.p11_owner_batch.argtypes=[vp,vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_double,ci,vp];lib.p11_owner_batch.restype=ci
        lib.p11_owner_complete.argtypes=[vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp]
        lib.p11_owner_complete.restype=ci
        lib.p11_yuyv_gray2.argtypes=[vp,ci,ci,ci,ci,vp];lib.p11_yuyv_gray2.restype=ci
        lib.p11_yuyv_observe2.argtypes=[vp,ci,ci,ci,ci,vp,vp,vp,vp];lib.p11_yuyv_observe2.restype=ci
        lib.p11_yuyv_observe_edges.argtypes=[vp,ci,ci,ci,ci,vp,vp,vp,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp,vp];lib.p11_yuyv_observe_edges.restype=ci
        lib.p11_copy_yuyv.argtypes=[vp,vp,ci,ci,ci,ci];lib.p11_copy_yuyv.restype=ci
        lib.p11_yuyv_bgr.argtypes=[vp,ci,ci,ci,ci,vp];lib.p11_yuyv_bgr.restype=ci
        lib.p11_yuyv_preview.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci]
        lib.p11_yuyv_preview.restype=ci
        lib.p11_yuyv_preview_nearest.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci]
        lib.p11_yuyv_preview_nearest.restype=ci
        lib.p11_bgr_preview_nearest.argtypes=[vp,ci,ci,ci,vp,ci,ci,vp,vp]
        lib.p11_bgr_preview_nearest.restype=ci
        lib.p11_preview_pair_copy.argtypes=[vp,vp,ci,ci,ci,ci,vp,vp,ci,ci,ci,ci,vp]
        lib.p11_preview_pair_copy.restype=ci
        lib.p11_compact_preview.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,vp,ci,ci,vp,vp,vp,vp]
        lib.p11_compact_preview.restype=ci
        lib.p11_coherent_profiles.argtypes=[vp,ci,ci,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp]
        lib.p11_coherent_profiles.restype=ci
        lib.p11_yuyv_exterior.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,ci,
            ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp,vp]
        lib.p11_yuyv_exterior.restype=ci
        lib.p11_locked_yuyv_exterior.argtypes=lib.p11_yuyv_exterior.argtypes+[ctypes.c_double]
        lib.p11_locked_yuyv_exterior.restype=ci
        lib.p11_v83_locked_yuyv_exterior.argtypes=lib.p11_locked_yuyv_exterior.argtypes
        lib.p11_v83_locked_yuyv_exterior.restype=ci
        lib.p11_v67_locked_pair.argtypes=[vp,ci,ci,ci,vp]+[ctypes.c_double]*5+[vp]+[ctypes.c_double]*3+[vp]*5
        lib.p11_v67_locked_pair.restype=ci
        lib.p11_v68_stabilize.argtypes=[vp,ci,ci,ci]+[vp]*6+[ci]+[vp]*4
        lib.p11_v68_stabilize.restype=ci
        lib.p11_locked_coherent_profiles.argtypes=[vp,ci,ci,ctypes.c_double,ctypes.c_double,
            ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp,vp]
        lib.p11_locked_coherent_profiles.restype=ci
        lib.p11_owner_admit.argtypes=[vp,vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_double,vp,vp]
        lib.p11_owner_admit.restype=ci
        lib.p11_preview_snapshot.argtypes=[vp,ci,ci,ci,vp,ci,ci,vp,ci,ci,ci,vp,ci,ci,vp]
        lib.p11_preview_snapshot.restype=ci
        check_cancel(cancel)
        _LIB__v31_native=lib
        _STATUS__v31_native={'backend':'cpp_v83_local_signed_physical_edges_cached_FB','path':str(target),'abi':3107,
                 'independent_edge_prior':'current_point_local_signed_sides',
                 'source_sha256':digest,'already_loaded':False,
                 'preview_snapshot_available':True,'preview_snapshot_signature':'paired_area2_15args',
                 'preview_snapshot_factors':[1,2],
                 'gray_backend':'yuyv_Y_area2_neon' if lib.p11_gray_backend()==2 else 'yuyv_Y_area2_scalar',
                 'geometry_backend':'cpp_projection_q8_and_fixed_guard',
                 'lk_backend':'cpp_cached_pyramids' if lib.p11_lk_available() else 'opencv_python_binding',
                 'lk_pyramid_cache':bool(lib.p11_lk_available()),'lk_pyramid_policy':'lazy_requested_levels',
                 'cover_selection_backend':'cpp_corner_tensor_quota_patch_dedup' if lib.p11_lk_available() else 'disabled',
                 'rescue_current_pyramid_generation_reuse':bool(lib.p11_lk_available()),
                  'stable_edge_backend':'cpp_joint_motion_and_current_gray_recheck','locked_pair_backend':'cpp_current_locked64_independent24','packed_exterior_backend':'cpp_direct_YUV_bands_no_full_plane_pack',
                   'coherent_exterior_backend':'cpp_YUV_spatial_signed_peak_lock_TLS','opencv_dev_version':cv_version,
                 'blur_backend':'cpp_fixed_separable_neon' if lib.p11_gray_backend()==2 else 'cpp_fixed_separable_scalar',
                 'tracking_checks_backend':'cpp_ransac_motion_candidate' if lib.p11_filter_available() else 'python_ransac_cpp_geometry',
                 'original_Y_refinement_backend':'cpp_original_Y_64x65' if lib.p11_lk_available() else 'python_original_Y_64x65',
                 'control_backend':'cpp_checked_immutable_packet','appearance_backend':'cpp_gray_signature',
                 'merged_control_backend':'cpp_geometry_guard_tone_packet','preview_backend':'cpp_cached_q8_bilinear_direct_canvas',
                  'owner_completion_backend':'cpp_cached_owner_poll_snapshot',
                 'copy_backend':'cpp_bgr_memcpy','input_copy_backend':'cpp_yuyv_memcpy','owner_control_backend':'cpp_batch_arm_readonly_plan_wait',
                  'wait_backend':'cpp_owner_completion_gil_released','probe_backend':'cpp_aligned_32x32','observation_context':'cpp_edges_gate_motion_workspace','fused_frame_backend':'cpp_current_quad_probe_control'}
        remember(target,source,'tracker',cache_flags)
    except (RuntimeError,OSError,subprocess.SubprocessError) as exc:
        _LIB__v31_native=None;_STATUS__v31_native={'backend':'numpy_analytic_tls','reason':str(exc),
                          'lk_backend':'opencv_python_binding','lk_pyramid_cache':False}
        if required:raise RuntimeError(_STATUS__v31_native['reason']) from exc
    checkpoint('NATIVE_LOAD_END',backend=_STATUS__v31_native.get('backend'),reason=_STATUS__v31_native.get('reason'),
        source_sha256=digest)
    return dict(_STATUS__v31_native)

def native_status__v31_native():return dict(_STATUS__v31_native)

def gaussian3__v31_native(gray, workspace):
    if _LIB__v31_native is None:return None
    g=np.ascontiguousarray(gray,np.uint8);h,w=g.shape
    if workspace.dtype!=np.uint16 or workspace.size<3*w or not workspace.flags.c_contiguous:
        raise ValueError('Gaussian workspace layout invalid')
    out=np.empty_like(g)
    code=_LIB__v31_native.p11_gaussian3(g.ctypes.data,w,h,g.strides[0],workspace.ctypes.data,out.ctypes.data)
    if code:raise ValueError('native Gaussian rejected: '+str(code))
    return out

def quad_valid__v31_native(quad, shape, reference=None):
    if _LIB__v31_native is None:return None
    q=np.ascontiguousarray(quad,np.float64).reshape(4,2)
    ref=None if reference is None else np.ascontiguousarray(reference,np.float64).reshape(4,2)
    code=_LIB__v31_native.p11_quad_valid(q.ctypes.data,int(shape[1]),int(shape[0]),None if ref is None else ref.ctypes.data)
    if code<0:raise ValueError('native quad check rejected: '+str(code))
    return bool(code)

def spatial_support__v31_native(points,quad):
    if _LIB__v31_native is None:return None
    p=np.ascontiguousarray(points,np.float32).reshape(-1,2)
    if len(p)<4:return False
    if len(p)>100:raise ValueError('native boundary feature count exceeds100')
    q=np.ascontiguousarray(quad,np.float64).reshape(4,2)
    code=_LIB__v31_native.p11_spatial(p.ctypes.data,len(p),q.ctypes.data)
    if code<0:raise ValueError('native spatial check rejected: '+str(code))
    return bool(code)

_LK_FILTER=threading.local()

def filter_lk__v31_native(points,forward,backward,status,reverse,error,anchor,previous,shape):
    if _LIB__v31_native is None or not _LIB__v31_native.p11_filter_available():return None
    p=np.ascontiguousarray(points,np.float32).reshape(-1,2);n=len(p)
    if not 4<=n<=100:raise ValueError('native LK filter feature count invalid')
    f=np.ascontiguousarray(forward,np.float32).reshape(n,2)
    b=np.ascontiguousarray(backward,np.float32).reshape(n,2)
    s=np.ascontiguousarray(status,np.uint8).reshape(n)
    sb=np.ascontiguousarray(reverse,np.uint8).reshape(n)
    e=np.ascontiguousarray(error,np.float32).reshape(n)
    if not hasattr(_LK_FILTER,'buffers'):
        _LK_FILTER.buffers=(np.empty((4,2),np.float64),np.empty((4,2),np.float64),
            np.empty((4,2),np.float32),np.empty((100,2),np.float32),np.empty(5,np.float64))
    a,old,q,retained,stats=_LK_FILTER.buffers;a[:]=anchor;old[:]=previous;stats.fill(0.)
    code=_LIB__v31_native.p11_lk_filter(p.ctypes.data,f.ctypes.data,b.ctypes.data,s.ctypes.data,sb.ctypes.data,
        e.ctypes.data,n,a.ctypes.data,old.ctypes.data,shape[1],shape[0],q.ctypes.data,
        retained.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native LK consistency rejected: '+str(code))
    return q.copy(),retained[:int(stats[4])].copy(),dict(workspace_reused=True,features=n,good_features=int(stats[1]),
        inlier_fraction=float(stats[2]),fb_median=float(stats[3]),filter_backend='cpp_ransac_geometry')

def prepare_regs__v31_native(H,w,h):
    if _LIB__v31_native is None:return None
    mat=np.ascontiguousarray(H,np.float64)
    if mat.shape!=(3,3):raise ValueError('H shape invalid')
    regs=np.empty(8,np.int32)
    code=_LIB__v31_native.p11_prepare(mat.ctypes.data,int(w),int(h),regs.ctypes.data)
    if code:raise ValueError('native fixed H corner preflight rejected: '+str(code))
    return tuple(int(x) for x in regs)

def encode_packet__v31_native(field,regs,wi,hi,wo,ho,flags):
    if _LIB__v31_native is None:return None
    f=np.asarray(field)
    if f.shape!=(21,21,4) or f.dtype!=np.int32:raise ValueError('control field must be int32 21x21x4')
    f=np.ascontiguousarray(f)
    r=np.ascontiguousarray(regs,np.int32);out=np.empty(1776,dtype='<u4')
    code=_LIB__v31_native.p11_packet(f.ctypes.data,r.ctypes.data,wi,hi,wo,ho,flags,out.ctypes.data)
    if code:raise ValueError('native control field/range rejected: '+str(code))
    return out.tobytes()

def gray_signature__v31_native(gray,H,kernel):
    if _LIB__v31_native is None:return None
    g=np.ascontiguousarray(gray,np.uint8);mat=np.ascontiguousarray(H,np.float64)
    k=np.ascontiguousarray(kernel,np.float32).reshape(9)
    if g.ndim!=2 or mat.shape!=(3,3):raise ValueError('signature layout invalid')
    structure=np.empty((128,96),np.float32);background=np.empty((8,8),np.float32)
    stats=np.empty(2,np.float64)
    code=_LIB__v31_native.p11_signature(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],mat.ctypes.data,
        k.ctypes.data,structure.ctypes.data,background.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native appearance signature rejected: '+str(code))
    return dict(structure=structure,background=background,mean=float(stats[0]),std=float(stats[1]),
                backend='cpp_gray_signature')

def gray_area2__v31_native(image, out):
    """Return False for unsupported layouts/sizes; never silently copy full BGR."""
    if _LIB__v31_native is None:return False
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3 or
        image.strides[2]!=1 or image.strides[1]!=3):return False
    h,w=image.shape[:2]
    if w%2 or h%2 or min(w,h)<4 or max(w,h)>8192:return False
    if image.strides[0]<w*3:return False
    if out.shape!=(h//2,w//2) or out.dtype!=np.uint8 or not out.flags.c_contiguous:
        raise ValueError('gray observation destination layout invalid')
    code=_LIB__v31_native.p11_gray2(image.ctypes.data,w,h,image.strides[0],out.ctypes.data)
    if code:raise ValueError('native gray observation rejected: '+str(code))
    return True

def merged_geometry__v31_native(H, regs, nodes, nx, ny, uv, samples):
    """Return None for Python fallback; native failures remain hard rejections."""
    if _LIB__v31_native is None:return None
    if len(regs)!=8 or any(int(x)!=x or not -(1<<31)<=int(x)<(1<<31) for x in regs):
        raise ValueError('native geometry registers outside signed32')
    mat=np.ascontiguousarray(H,np.float64)
    r=np.ascontiguousarray(regs,np.int32)
    if mat.shape!=(3,3) or r.shape!=(8,) or not np.isfinite(mat).all():
        raise ValueError('native geometry H/register shape invalid')
    nodes=np.ascontiguousarray(nodes,np.float64)
    uv=np.ascontiguousarray(uv,np.int32);samples=np.ascontiguousarray(samples,np.float64)
    if (nodes.shape!=(ny*nx,2) or uv.ndim!=2 or uv.shape[1]!=2 or
        samples.shape!=uv.shape or not 1<=len(uv)<=20000 or
        not (np.isfinite(nodes).all() and np.isfinite(samples).all())):
        raise ValueError('native geometry cached sample layout invalid')
    field=np.empty((21,21,4),np.int32);residual=np.empty(1,np.float64)
    code=_LIB__v31_native.p11_plan_geometry(mat.ctypes.data,r.ctypes.data,nodes.ctypes.data,nx,ny,
        uv.ctypes.data,samples.ctypes.data,len(uv),field.ctypes.data,residual.ctypes.data)
    if code:raise ValueError('native geometry range/quantization rejected; no image DMA: '+str(code))
    return field,float(residual[0])

class LKCache__v31_native:
    """Own both padded pyramids/derivatives; reuse forward/backward then promote."""
    def __init__(self):
        self.lib=_LIB__v31_native
        self.forward=np.empty((100,1,2),np.float32);self.backward=np.empty_like(self.forward)
        self.status=np.empty(100,np.uint8);self.reverse=np.empty(100,np.uint8);self.errors=np.empty(100,np.float32)
        self.quad=np.empty((4,2),np.float32);self.retained=np.empty((100,2),np.float32)
        self.anchor_quad=np.empty((4,2),np.float64);self.previous_quad=np.empty_like(self.anchor_quad)
        self.filter_stats=np.empty(5,np.float64);self.flow_times=np.empty(2,np.float64)
        self.last_checked_timing={};self.motion_info=np.empty(4,np.float64)
        self.roi_quad=np.empty((4,2),np.float32);self.roi_stats=np.empty(3,np.int32)
        self.pointer=self.lib.p11_lk_create() if self.lib and self.lib.p11_lk_available() else None
        if self.lib and self.lib.p11_lk_available() and not self.pointer:
            raise MemoryError('native LK context allocation failed')
    def anchor(self,gray):
        if not self.pointer:return
        g=np.ascontiguousarray(gray,np.uint8)
        code=self.lib.p11_lk_anchor(self.pointer,g.ctypes.data,g.shape[1],g.shape[0])
        if code:raise ValueError('native LK anchor rejected: '+str(code))
    def track(self,gray,points,initial=None,levels=3,iterations=20,generation=None):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if guess is not None and not np.isfinite(guess).all():raise ValueError('LK prediction not finite')
        if not 4<=len(p)<=100:raise ValueError('LK feature count outside4..100')
        f=self.forward[:len(p)];b=self.backward[:len(p)];s=self.status[:len(p)];sb=self.reverse[:len(p)]
        error=self.errors[:len(p)]
        entry=self.lib.p11_lk_track if generation is None else self.lib.p11_lk_track_generation
        tail=() if generation is None else (int(generation),)
        code=entry(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],
            p.ctypes.data,len(p),f.ctypes.data,b.ctypes.data,s.ctypes.data,sb.ctypes.data,error.ctypes.data,
            None if guess is None else guess.ctypes.data,int(levels),int(iterations),*tail)
        if code:raise ValueError('native LK rejected frame: '+str(code))
        return f,s,error,b,sb
    def checked(self,gray,points,initial,anchor,previous,generation,levels=3,iterations=20):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if not 4<=len(p)<=100 or (guess is not None and not np.isfinite(guess).all()):raise ValueError('LK prediction/features invalid')
        if isinstance(generation,bool) or not isinstance(generation,(int,np.integer)) or not 0<=int(generation)<0xffffffff:raise ValueError('LK frame generation invalid')
        self.anchor_quad[:]=anchor;self.previous_quad[:]=previous
        self.filter_stats.fill(0.);self.flow_times.fill(0.)
        began=time.perf_counter();cpu=time.thread_time()
        code=self.lib.p11_lk_checked_motion(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],p.ctypes.data,len(p),
            None if guess is None else guess.ctypes.data,int(levels),int(iterations),int(generation),self.anchor_quad.ctypes.data,
            self.previous_quad.ctypes.data,self.quad.ctypes.data,self.retained.ctypes.data,self.filter_stats.ctypes.data,self.flow_times.ctypes.data,self.motion_info.ctypes.data)
        self.last_checked_timing=dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),native_checked_wall_s=time.perf_counter()-began,
            native_checked_thread_cpu_s=time.thread_time()-cpu,native_checked_code=int(code),
            transaction_backend='cpp_bidirectional_lk_filter',
            motion_model={0:'unavailable',1:'similarity_candidate',2:'projective_candidate'}.get(int(self.motion_info[0]),'invalid'),
            motion_good_features=int(self.motion_info[1]),motion_inliers=int(self.motion_info[2]),
            motion_reprojection_rms=float(self.motion_info[3]),current_four_edges_required=True)
        if code<=-100:raise ValueError('native LK rejected frame: '+str(code+100))
        if code:raise ValueError('native LK consistency rejected: '+str(code))
        n=int(self.filter_stats[4])
        detail=dict(lk_backend='cpp_cached_pyramids_checked',features=len(p),good_features=int(self.filter_stats[1]),filter_backend='cpp_bidirectional_lk_filter',
            inliers=n,inlier_fraction=float(self.filter_stats[2]),fb_median=float(self.filter_stats[3]),
            motion_model=self.last_checked_timing['motion_model'],motion_reprojection_rms=float(self.motion_info[3]),
            current_four_edges_required=True)
        return self.quad.copy(),self.retained[:n].copy(),detail,dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),transaction_backend='cpp_bidirectional_lk_filter')
    def roi_features(self,gray,quad,retained=None):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);points=np.empty((0,2),np.float32) if retained is None else np.ascontiguousarray(retained,np.float32).reshape(-1,2)
        if len(points)>100:raise ValueError('ROI retained features exceed100')
        self.roi_quad[:]=quad
        code=self.lib.p11_roi_features(g.ctypes.data,g.shape[1],g.shape[0],self.roi_quad.ctypes.data,
            points.ctypes.data,len(points),self.retained.ctypes.data,self.roi_stats.ctypes.data)
        if code:raise ValueError('Native corner ROI rejected: '+str(code))
        return self.retained[:int(self.roi_stats[0])].copy(),dict(action='native_outer_corner_roi',regions=int(self.roi_stats[1]),
            added=int(self.roi_stats[2]),features=int(self.roi_stats[0]),workspace_reused=True)
    def promote(self):
        if self.pointer:
            code=self.lib.p11_lk_promote(self.pointer)
            if code:raise ValueError('native LK promotion failed: '+str(code))
    def close(self):
        if self.pointer:
            self.lib.p11_lk_destroy(self.pointer);self.pointer=None
    def __del__(self):
        try:self.close()
        except Exception:pass

def measure_edges__v31_native(gray, quad, radius, checked=False):
    if _LIB__v31_native is None:return None
    g=np.ascontiguousarray(gray,dtype=np.uint8)
    if g.ndim!=2:raise ValueError('native edges require grayscale')
    q=np.ascontiguousarray(quad,dtype=np.float64).reshape(4,2)
    result=np.empty((4,2),np.float64);stats=np.empty(21,np.float64)
    function=_LIB__v31_native.p11_edges_checked if checked else _LIB__v31_native.p11_edges
    code=function(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],q.ctypes.data,
                       float(radius),result.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native edge helper rejected input: '+str(code))
    return result.astype(np.float32),dict(edge_support=stats[:4].tolist(),
        edge_polarity=stats[4:8].astype(int).tolist(),refined_corners=int(stats[16]),
        supported_edges=int(stats[17]),median_edge_shift=float(np.median(stats[8:12])),
        edge_rms=stats[12:16].tolist(),max_edge_rms=float(max(stats[12:16])),
        edge_backend='cpp_analytic_tls',native_valid=bool(stats[20]) if checked else None)

def fixed_coordinates__v31_native(regs,u,v,field):
    if len(regs)!=8 or any(int(r)!=r or not -(1<<31)<=int(r)<(1<<31) for r in regs):
        raise ValueError('H寄存器超出signed32，禁止截断后误加载')
    if _LIB__v31_native is None:
        from geometry import coordinates as coordinates
        x,y,_=coordinates(regs,u,v,field)
        return x/65536.,y/65536.
    u,v=np.broadcast_arrays(u,v)
    uv=np.ascontiguousarray(np.column_stack([u.ravel(),v.ravel()]),np.int32)
    r=np.ascontiguousarray(regs,np.int32);f=np.ascontiguousarray(field,np.int32)
    out=np.empty((len(uv),2),np.float64)
    if r.shape!=(8,) or f.shape!=(21,21,4):raise ValueError('native guard shape mismatch')
    code=_LIB__v31_native.p11_guard(r.ctypes.data,f.ctypes.data,uv.ctypes.data,len(uv),out.ctypes.data)
    if code:raise ValueError('定点几何采样范围不安全，未启动图像DMA: '+str(code))
    return out[:,0].reshape(u.shape),out[:,1].reshape(u.shape)


def prepare_control__v31_native(H,nodes,nx,ny,uv,samples,gain,offset,wi,hi,wo,ho,flags=15):
    """One native call; same fixed arithmetic and 0.65-source-pixel guard."""
    if _LIB__v31_native is None:return None
    mat=np.ascontiguousarray(H,np.float64)
    nodes=np.ascontiguousarray(nodes,np.float64)
    uv=np.ascontiguousarray(uv,np.int32)
    samples=np.ascontiguousarray(samples,np.float64)
    gain=np.ascontiguousarray(gain,np.int32);offset=np.ascontiguousarray(offset,np.int32)
    if (mat.shape!=(3,3) or nodes.shape!=(nx*ny,2) or uv.ndim!=2 or uv.shape[1]!=2
        or samples.shape!=uv.shape or gain.shape!=(21,21) or offset.shape!=(21,21)
        or not 1<=len(uv)<=20000 or not 1<=nx<=21 or not 1<=ny<=21
        or not all(np.isfinite(a).all() for a in (mat,nodes,samples))):
        raise ValueError('merged control geometry layout invalid')
    if any(isinstance(n,bool) or int(n)!=n or not 2<=int(n)<=1280 for n in (wi,hi,wo,ho)):
        raise ValueError('merged control dimensions outside2..1280')
    out=np.empty(1776,dtype='<u4');residual=np.empty(1,np.float64)
    code=_LIB__v31_native.p11_prepare_control(mat.ctypes.data,nodes.ctypes.data,nx,ny,uv.ctypes.data,
        samples.ctypes.data,len(uv),gain.ctypes.data,offset.ctypes.data,wi,hi,wo,ho,flags,
        out.ctypes.data,residual.ctypes.data)
    if code:raise ValueError('native merged control rejected; no image DMA: '+str(code))
    return out.tobytes(),float(residual[0])


def probe_signature__v31_native(gray,H):
    if _LIB__v31_native is None:return None
    g=np.ascontiguousarray(gray,np.uint8);mat=np.ascontiguousarray(H,np.float64)
    if g.ndim!=2 or mat.shape!=(3,3):raise ValueError('Probe layout invalid')
    structure=np.empty((32,32),np.float32);background=np.empty((8,8),np.float32)
    stats=np.empty(2,np.float64)
    code=_LIB__v31_native.p11_probe(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],mat.ctypes.data,
        structure.ctypes.data,background.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('Aligned probe rejected: '+str(code))
    return dict(structure=structure,background=background,mean=float(stats[0]),std=float(stats[1]),
        backend='cpp_aligned_32x32')


def wait_io__v31_native(pl_array,dma_array,before,kind,timeout,out=None):
    """None means unsupported layout: caller retains Python polling. Never copy MMIO."""
    if _LIB__v31_native is None:return None
    for array,minimum in ((pl_array,0x3c),(dma_array,0x38)):
        if (not isinstance(array,np.ndarray) or array.dtype!=np.dtype('uint32')
            or not array.flags.c_contiguous or array.nbytes<minimum or array.ctypes.data%4):return None
    if np.isfinite(timeout) and float(timeout)>3600:return None
    if int(kind) not in (0,1) or not np.isfinite(timeout) or not 0<float(timeout)<=3600:
        raise ValueError('Native wait arguments invalid')
    result=np.empty(4,np.uint32) if out is None else out
    if result.shape!=(4,) or result.dtype!=np.uint32 or not result.flags.c_contiguous or not result.flags.writeable:raise ValueError('Wait output workspace invalid')
    code=_LIB__v31_native.p11_wait_io(pl_array.ctypes.data,dma_array.ctypes.data,int(before)&0xffffffff,
        int(kind),float(timeout),result.ctypes.data)
    if code<0:raise ValueError('Native wait rejected: '+str(code))
    return int(code),dict(pl_status=int(result[0]),pl_error=int(result[1]),tx=int(result[2]),rx=int(result[3]))


def fused_observation2__v31_native(image,scratch,workspace,out=None,timing=None):
    if _LIB__v31_native is None:return None
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3
        or image.strides[1:]!=(3,1) or image.strides[0]<image.shape[1]*3):return None
    h,w=image.shape[:2]
    if w%2 or h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (scratch.shape!=(h//2,w//2) or scratch.dtype!=np.uint8 or not scratch.flags.c_contiguous
        or workspace.dtype!=np.uint16 or workspace.size<3*(w//2) or not workspace.flags.c_contiguous):
        raise ValueError('Fused observation workspace invalid')
    if out is None:out=np.empty_like(scratch)
    if timing is None:timing=np.empty(2,np.float64)
    if out.shape!=scratch.shape or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable or np.shares_memory(out,scratch):
        raise ValueError('Observation output aliases scratch or has invalid layout')
    code=_LIB__v31_native.p11_observe2(image.ctypes.data,w,h,image.strides[0],scratch.ctypes.data,
        workspace.ctypes.data,out.ctypes.data,timing.ctypes.data)
    if code:raise ValueError('Fused observation rejected: '+str(code))
    return out,dict(resize_gray_s=float(timing[0]),blur_s=float(timing[1]))

def profile_snapshot__v31_native(raw=False,out=None):
    if _LIB__v31_native is None:return None if raw else {}
    f=_LIB__v31_native.p11_profile_snapshot
    if out is None:out=np.empty(90,np.float64)
    if (not isinstance(out,np.ndarray) or out.dtype!=np.float64 or out.shape!=(90,)
            or not out.flags.c_contiguous or not out.flags.writeable):
        raise ValueError('Native profile output workspace invalid')
    if f(out.ctypes.data,len(out)):raise RuntimeError('Native profile layout rejected')
    if raw:return out
    names=['p11_lk_anchor', 'p11_lk_track', 'p11_lk_promote', 'p11_gray2', 'p11_gaussian3', 'p11_quad_valid', 'p11_spatial', 'p11_lk_filter', 'p11_edges', 'p11_guard', 'p11_plan_geometry', 'p11_prepare', 'p11_packet', 'p11_signature', 'p11_prepare_control', 'p11_probe', 'p11_wait_io', 'p11_observe2', 'p11_edges_motion', 'p11_copy_bgr', 'p11_arm_io', 'p11_plan_wait', 'p11_frame_state', 'p11_motion_values', 'outer_calls', 'p11_observe_edges', 'p11_lk_checked', 'p11_roi_features', 'p11_owner_batch', 'p11_owner_complete']
    return {name:dict(wall_s=float(out[i*3]),thread_cpu_s=float(out[i*3+1]),calls=int(out[i*3+2])) for i,name in enumerate(names)}


def _mmio_layout__v31_native(array,minimum):
    return (isinstance(array,np.ndarray) and array.dtype==np.dtype('uint32')
        and array.flags.c_contiguous and array.nbytes>=minimum and array.ctypes.data%4==0)

def copy_bgr_native__v31_native(source,destination):
    if _LIB__v31_native is None:return False
    h,w=source.shape[:2]
    code=_LIB__v31_native.p11_copy_bgr(source.ctypes.data,destination.ctypes.data,w,h,
                          source.strides[0],destination.strides[0])
    if code:raise ValueError('Native BGR copy rejected: '+str(code))
    return True

def arm_io__v31_native(pl,dma,src,dst,send,receive,sequence=None):
    if _LIB__v31_native is None or not _mmio_layout__v31_native(pl,12) or not _mmio_layout__v31_native(dma,0x5c):return False
    values=(src,dst,send,receive,0 if sequence is None else sequence)
    if any(isinstance(n,bool) or int(n)!=n or not 0<=int(n)<=0xffffffff for n in values):
        raise ValueError('Native arm uint32 argument invalid')
    code=_LIB__v31_native.p11_arm_io(pl.ctypes.data,dma.ctypes.data,*map(int,values),int(sequence is not None))
    if code:raise RuntimeError('Native owner arm rejected: '+str(code))
    return True

def frame_state__v31_native(pl,dma):
    if _LIB__v31_native is None or not _mmio_layout__v31_native(pl,0xcc) or not _mmio_layout__v31_native(dma,0x5c):return None
    out=np.empty(12,np.uint32)
    if _LIB__v31_native.p11_frame_state(pl.ctypes.data,dma.ctypes.data,out.ctypes.data):
        raise RuntimeError('Native frame state rejected')
    return tuple(map(int,out))

def plan_wait__v31_native(planner,pixel,dma,sequence,kind,timeout):
    if (_LIB__v31_native is None or not _mmio_layout__v31_native(planner,0x74) or not _mmio_layout__v31_native(pixel,0xe0)
        or not _mmio_layout__v31_native(dma,0x38)):return None
    if (isinstance(sequence,bool) or not 0<int(sequence)<=0xffffffff or kind not in (0,1)
        or not np.isfinite(timeout) or not 0<float(timeout)<=3600):
        raise ValueError('Native plan wait argument invalid')
    out=np.zeros(4,np.uint32)
    code=_LIB__v31_native.p11_plan_wait(planner.ctypes.data,pixel.ctypes.data,dma.ctypes.data,
                           int(sequence),int(kind),float(timeout),out.ctypes.data)
    if code<0:raise RuntimeError('Native plan wait rejected')
    return int(code),tuple(map(int,out))


def motion_values__v31_native(candidate,prediction,previous,anchor,drift):
    if _LIB__v31_native is None:return None
    points=[np.ascontiguousarray(q,np.float32).reshape(4,2) for q in (candidate,prediction,previous,anchor)]
    if drift.shape!=(4,2) or drift.dtype!=np.float32 or not drift.flags.c_contiguous:
        raise ValueError('Motion drift workspace invalid')
    out=np.empty(5,np.float64)
    code=_LIB__v31_native.p11_motion_values(*(q.ctypes.data for q in points),drift.ctypes.data,out.ctypes.data)
    if code:raise ValueError('Native motion reduction rejected: '+str(code))
    return tuple(map(float,out))


class EdgeMotionWorkspace__v31_native:
    """Private chronological PS context; buffers reused across frames."""
    def __init__(self):
        self.predicted=np.empty((4,2),np.float64)
        self.previous=np.empty((4,2),np.float32);self.anchor=np.empty((4,2),np.float32)
        self.polarity=np.empty(4,np.int32)
        self.result=np.empty((4,2),np.float64);self.stats=np.empty(21,np.float64)
        self.result32=np.empty((4,2),np.float32);self.light_results=False;self.decode_timing=(0.,0.)
        self.motion=np.empty(5,np.float64);self.gate=np.empty(6,np.float64)
    def measure(self,gray,prediction,previous,anchor,drift,polarity,radius=5.):
        if _LIB__v31_native is None:return None
        g=np.ascontiguousarray(gray,np.uint8)
        if g.ndim!=2 or drift.dtype!=np.float32 or drift.shape!=(4,2) or not drift.flags.c_contiguous:
            raise ValueError('Observation context layout invalid')
        self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
        code=_LIB__v31_native.p11_edges_motion(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,
            drift.ctypes.data,self.polarity.ctypes.data,float(radius),self.result.ctypes.data,
            self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data)
        if code:raise ValueError('Native observation context rejected: '+str(code))
        return self.decode()
    def decode(self):
        if self.light_results:
            from display import decode_light_edges as decode_light_edges
            return decode_light_edges(self)
        stats=self.stats;shifts=sorted(float(v) for v in stats[8:12])
        evidence=dict(valid=bool(stats[20]),edge_support=stats[:4].tolist(),
            edge_polarity=stats[4:8].astype(int).tolist(),refined_corners=int(stats[16]),
            supported_edges=int(stats[17]),median_edge_shift=(shifts[1]+shifts[2])*.5,
            edge_rms=stats[12:16].tolist(),max_edge_rms=float(self.gate[2]),
            edge_backend='cpp_edges_gate_motion_context')
        gate=dict(reliable=bool(self.gate[0]),min_support=float(self.gate[1]),
            max_rms=float(self.gate[2]),prediction_correction=float(self.gate[3]),
            polarity_flips=int(self.gate[4]),radius=float(self.gate[5]))
        return self.result.astype(np.float32),evidence,gate,tuple(map(float,self.motion)) if gate['reliable'] else None


def profile_os_snapshot__v31_native(out=None):
    if _LIB__v31_native is None:return None
    values=np.empty((30,4),np.float64) if out is None else out
    if (not isinstance(values,np.ndarray) or values.dtype!=np.float64 or values.shape!=(30,4)
            or not values.flags.c_contiguous or not values.flags.writeable):
        raise ValueError('Native OS profile output workspace invalid')
    code=_LIB__v31_native.p11_profile_os_snapshot(values.ctypes.data,values.size)
    if code:raise RuntimeError('Native OS profile layout mismatch')
    return values


class FusedPrepareLayoutError__v31_native(ValueError):
    """A Python/native memory contract error; distinct from a scene rejection."""


def _frame_int__v31_native(value,low,high,name):
    if (isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer))
            or not low<=int(value)<=high):
        raise FusedPrepareLayoutError__v31_native('Fused '+name+' must be integer in '+str((low,high)))
    return int(value)


def _readonly_array__v31_native(value,dtype,shape,name):
    try:array=np.ascontiguousarray(value,dtype)
    except (TypeError,ValueError) as exc:
        raise FusedPrepareLayoutError__v31_native('Fused '+name+' conversion invalid') from exc
    if array.shape!=shape:
        raise FusedPrepareLayoutError__v31_native('Fused '+name+' shape invalid: '+str(array.shape))
    # Bytes-backed snapshots cannot be mutated by their original owner. A
    # readonly typed cache supplied by the chronological producer needs no copy.
    if array.flags.writeable:array=np.frombuffer(array.tobytes(),dtype).reshape(shape)
    return array


def _destroy_frame_context__v31_native(library,pointer):
    # The finalizer's arguments keep the owning CDLL alive independently of
    # module-global _LIB; closing a later session cannot unload this callback.
    library.p11_frame_destroy(pointer)


class FramePrepareWorkspace__v31_native:
    """One chronological producer owns input, output and native guard scratch.

    scale is exactly [source_width / gray_width, source_height / gray_height].
    C++ consumes separate sx/sy doubles; scalar scale is deliberately rejected.
    Only immutable reference/control identities qualify for validation caching.
    Current q, scale and H are rewritten for every frame. Returned observations,
    H and control bytes own their memory and never alias this scratch workspace.
    """
    def __init__(self):
        self.quad=np.empty((4,2),np.float64);self.scale=np.empty(2,np.float64)
        self.H=np.empty((3,3),np.float64);self.shape=np.empty(4,np.float64)
        self.structure=np.empty((32,32),np.float32);self.background=np.empty((8,8),np.float32)
        self.info=np.empty(11,np.float64);self.packet=np.empty(1776,dtype='<u4')
        self._quad_pointer=self.quad.ctypes.data
        self._output_pointers=tuple(a.ctypes.data for a in
            (self.H,self.shape,self.structure,self.background,self.info,self.packet))
        self.references=None;self.reference_arrays=None;self.reference_pointers=None
        self.control_arrays=None;self.control_inputs=None;self.control_layout=None;self.control_pointers=None
        self._owner=None;self._context=None;self._context_library=None;self._context_finalizer=None

    def close(self):
        if self._context_finalizer is not None:self._context_finalizer()
        self._context=None;self._context_library=None;self._context_finalizer=None

    def _native_context(self):
        if self._context_library is not _LIB__v31_native:
            self.close();pointer=_LIB__v31_native.p11_frame_create()
            if not pointer:raise RuntimeError('Native frame workspace allocation failed')
            self._context=pointer;self._context_library=_LIB__v31_native
            # Retain this specific CDLL, not the later module-global _LIB.
            self._context_finalizer=weakref.finalize(self,_destroy_frame_context__v31_native,_LIB__v31_native,pointer)
        return self._context

    def prepare(self,q,gray,scale,wo,ho,refs,control=None):
        if _LIB__v31_native is None:return None
        began=time.perf_counter();owner=threading.get_ident()
        if self._owner is None:self._owner=owner
        elif owner!=self._owner:raise FusedPrepareLayoutError__v31_native('Fused workspace requires one chronological producer thread')
        try:qa=np.asarray(q);sa=np.asarray(scale);g=np.asarray(gray)
        except (TypeError,ValueError) as exc:
            raise FusedPrepareLayoutError__v31_native('Fused frame input conversion invalid') from exc
        if qa.shape!=(4,2) or qa.dtype.kind not in 'fiu' or sa.shape!=(2,) or sa.dtype.kind not in 'fiu':
            raise FusedPrepareLayoutError__v31_native('Fused quad must be4x2; scale must be finite positive [sx, sy]')
        if (g.dtype!=np.uint8 or g.ndim!=2 or min(g.shape)<2 or max(g.shape)>1280
                or g.strides[1]!=1 or not g.shape[1]<=g.strides[0]<=0x7fffffff):
            raise FusedPrepareLayoutError__v31_native('Fused grayscale byte/stride contract invalid')
        np.copyto(self.quad,qa,casting='unsafe');np.copyto(self.scale,sa,casting='unsafe')
        sx=float(self.scale[0]);sy=float(self.scale[1])
        if not math.isfinite(sx) or not math.isfinite(sy) or sx<=0 or sy<=0:
            raise FusedPrepareLayoutError__v31_native('Fused scale must contain finite positive sx and sy')
        # Current q values are checked by p11_quad_h before probing or control
        # encoding. A scene/quad rejection must not disable later valid frames.
        wo=_frame_int__v31_native(wo,2,1280,'output width');ho=_frame_int__v31_native(ho,2,1280,'output height')
        try:key=tuple(refs)
        except TypeError as exc:raise FusedPrepareLayoutError__v31_native('Fused references tuple invalid') from exc
        if len(key)!=3:raise FusedPrepareLayoutError__v31_native('Probe references require structure/background/shape')
        reference_hit=(self.references is not None and all(a is b for a,b in zip(key,self.references)))
        if not reference_hit:
            self.reference_arrays=tuple(_readonly_array__v31_native(a,dtype,shape,name)
                for a,dtype,shape,name in zip(key,(np.float32,np.float32,np.float64),
                    ((32,32),(8,8),(4,)),('structure reference','background reference','shape reference')))
            self.reference_pointers=tuple(a.ctypes.data for a in self.reference_arrays)
            self.references=key if all(isinstance(a,np.ndarray) and not a.flags.writeable for a in key) else None
        rs,rb,rshape=self.reference_pointers
        control_hit=False
        if control is None:
            nx=ny=count=wi=hi=flags=0;pointers=(0,0,0,0,0)
        else:
            if not isinstance(control,(tuple,list)) or len(control)!=10:
                raise FusedPrepareLayoutError__v31_native('Fused control tuple requires10 fields')
            nodes,nx,ny,uv,samples,gain,offset,wi,hi,flags=control
            nx=_frame_int__v31_native(nx,2,21,'node columns');ny=_frame_int__v31_native(ny,2,21,'node rows')
            wi=_frame_int__v31_native(wi,2,1280,'input width');hi=_frame_int__v31_native(hi,2,1280,'input height')
            flags=_frame_int__v31_native(flags,0,15,'border flags')
            arrays=(nodes,uv,samples,gain,offset);layout=(nx,ny,wi,hi,flags)
            control_hit=(self.control_inputs is not None and layout==self.control_layout
                and all(a is b for a,b in zip(arrays,self.control_inputs)))
            if not control_hit:
                expected_dtypes=(np.float64,np.int32,np.float64,np.int32,np.int32)
                if (any(not isinstance(a,np.ndarray) or a.dtype!=dtype or not a.flags.c_contiguous
                        for a,dtype in zip(arrays,expected_dtypes))
                    or nodes.shape!=(nx*ny,2) or uv.ndim!=2 or uv.shape[1]!=2
                    or samples.shape!=uv.shape or gain.shape!=(21,21) or offset.shape!=(21,21)
                    or not 1<=len(uv)<=20000):
                    raise FusedPrepareLayoutError__v31_native('Fused control pointer/dtype/layout invalid before native access')
                self.control_arrays=tuple(_readonly_array__v31_native(a,dtype,a.shape,'control input')
                    for a,dtype in zip(arrays,expected_dtypes))
                self.control_pointers=tuple(a.ctypes.data for a in self.control_arrays)
                self.control_layout=layout
                self.control_inputs=arrays if all(not a.flags.writeable for a in arrays) else None
            pointers=self.control_pointers;count=len(self.control_arrays[1])
        context=self._native_context();native_begin=time.perf_counter()
        code=_LIB__v31_native.p11_frame_prepare(context,self._quad_pointer,g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            sx,sy,wo,ho,rs,rb,rshape,pointers[0],nx,ny,pointers[1],pointers[2],count,
            pointers[3],pointers[4],wi,hi,flags,int(control is not None),*self._output_pointers)
        if code in (-1,-5,-7):
            raise FusedPrepareLayoutError__v31_native('Native frame pointer/reference/owner contract rejected: '+str(code))
        if code:raise ValueError('Current quad/probe rejected before image DMA: '+str(code))
        publish_begin=time.perf_counter()
        observations=tuple(a.copy() for a in (self.structure,self.background,self.shape))
        for a in observations:a.setflags(write=False)
        probe=dict(structure=observations[0],background=observations[1],shape=observations[2],
            mean=float(self.info[0]),std=float(self.info[1]),backend='cpp_current_quad_probe_control')
        changes=tuple(float(x) for x in self.info[2:5])
        status=int(self.info[6]);wire=self.packet.tobytes() if control is not None and status==0 else None
        H=self.H.copy();finished=time.perf_counter()
        return dict(H=H,probe=probe,changes=changes,wire=wire,residual=float(self.info[5]),control_code=status,
            h_native_s=float(self.info[7]),probe_native_s=float(self.info[8]),control_native_s=float(self.info[9]),
            native_transaction_s=float(self.info[10]),wrapper_prepare_s=native_begin-began,
            wrapper_publish_s=finished-publish_begin,wrapper_total_s=finished-began,
            reference_cache_hit=reference_hit,control_cache_hit=control_hit)


class ObservationWorkspace__v31_native(EdgeMotionWorkspace__v31_native):
    """Own bounded gray/filter/corner buffers; no pointer escapes the call."""
    def __init__(self):
        super().__init__();self.times=np.empty(4,np.float64)
    def observe(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius=5.):
        if _LIB__v31_native is None:return None
        h,w=image.shape[:2]
        if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3 or image.strides[1:]!=(3,1)
            or image.strides[0]<w*3 or min(w,h)<4 or max(w,h)>1280 or w%2 or h%2):return None
        if (out.shape!=(h//2,w//2) or scratch.shape!=out.shape or out.dtype!=np.uint8 or scratch.dtype!=np.uint8
            or rows.dtype!=np.uint16 or rows.size<3*(w//2) or drift.dtype!=np.float32 or drift.shape!=(4,2)
            or any(not a.flags.c_contiguous or not a.flags.writeable for a in (scratch,rows,out,drift))
            or np.shares_memory(out,scratch)):
            raise ValueError('Merged observation workspace invalid before native access')
        self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
        code=_LIB__v31_native.p11_observe_edges(image.ctypes.data,w,h,image.strides[0],scratch.ctypes.data,rows.ctypes.data,out.ctypes.data,
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,drift.ctypes.data,self.polarity.ctypes.data,
            float(radius),self.result.ctypes.data,self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data,self.times.ctypes.data)
        if code and code>-200:raise ValueError('Merged observation rejected: '+str(code))
        return (self.decode() if code==0 else None),dict(edge_error=(code+200 if code else None),resize_gray_s=float(self.times[0]),blur_s=float(self.times[1]),edge_gate_motion_s=float(self.times[2]),
            native_transaction_s=float(self.times[3]),transaction_backend='cpp_gray_gaussian_edges_confidence_motion')

class OwnerBatch__v31_native:
    """Cached admitted mappings/output scratch; only the creating owner may call."""
    def __init__(self,planner,pixel,dma):
        import threading
        self.lib=_LIB__v31_native;self.owner=threading.get_ident();self.arrays=(planner,pixel,dma)
        self.available=bool(self.lib)
        for a,minimum in zip(self.arrays,(0xc4,0xe4,0x5c)):
            self.available=self.available and isinstance(a,np.ndarray) and a.dtype==np.uint32 and a.flags.c_contiguous and a.nbytes>=minimum and a.ctypes.data%4==0
        self.pointers=tuple(a.ctypes.data for a in self.arrays) if self.available else ()
        self.state=np.empty(20,np.uint32)
    def call(self,operation=0,sequence=0,src=0,dst=0,timeout=1.):
        import threading
        if threading.get_ident()!=self.owner:raise RuntimeError('Native device transaction must stay on owner')
        if not self.available:return None
        if not 0<float(timeout)<=(30 if operation==3 else 1) or not np.isfinite(timeout):raise ValueError('Owner batch deadline invalid')
        code=self.lib.p11_owner_batch(*self.pointers,int(src),int(dst),int(sequence),float(timeout),int(operation),self.state.ctypes.data)
        if code<0:raise ValueError('Native device transaction layout rejected: '+str(code))
        return int(code),self.state
    def admit(self,sequence,input_size,output_size,capacity,timeout=1.):
        if threading.get_ident()!=self.owner:raise RuntimeError('Native device transaction must stay on owner')
        if not self.available:return None
        if not hasattr(self,'admit_times'):self.admit_times=np.empty(2,np.float64)
        code=self.lib.p11_owner_admit(*self.pointers,int(sequence),int(input_size),int(output_size),int(capacity),float(timeout),self.state.ctypes.data,self.admit_times.ctypes.data)
        if code<0:raise ValueError('Native owner admission layout rejected '+str(code))
        return int(code),self.state,self.admit_times


def preview_snapshot_available__v31_native():
    # The loader admits ABI3107 and binds the unchanged 15-argument export.
    # A future ABI needs explicit admission here; do not assume ABI>=3106.
    return bool(_LIB__v31_native is not None and _STATUS__v31_native.get('abi')==3107
        and _STATUS__v31_native.get('preview_snapshot_available',False)
        and _STATUS__v31_native.get('preview_snapshot_signature')=='paired_area2_15args')


def preview_snapshot__v31_native(raw,raw_out,bgr,bgr_out,times):
    if not preview_snapshot_available__v31_native():return False
    from core import require_yuyv as require_yuyv
    require_yuyv(raw)
    for value,channels in ((raw_out,2),(bgr,3),(bgr_out,3)):
        if value.dtype!=np.uint8 or value.ndim!=3 or value.shape[2]!=channels or value.strides[-1]!=1 or value.strides[-2]!=channels:
            raise ValueError('Preview snapshot layout invalid')
    if (not raw_out.flags.c_contiguous or not bgr_out.flags.c_contiguous
            or not raw_out.flags.writeable or not bgr_out.flags.writeable
            or times.shape!=(2,) or times.dtype!=np.float64
            or not times.flags.c_contiguous or not times.flags.writeable):
        raise ValueError('Preview snapshot workspace invalid')
    code=_LIB__v31_native.p11_preview_snapshot(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],raw_out.ctypes.data,raw_out.shape[1],raw_out.shape[0],
        bgr.ctypes.data,bgr.shape[1],bgr.shape[0],bgr.strides[0],bgr_out.ctypes.data,bgr_out.shape[1],bgr_out.shape[0],times.ctypes.data)
    if code:raise ValueError('Preview snapshot rejected '+str(code))
    return True

def completion_probe__v31_native(pl_array,dma_array,before,kind,out):
    if _LIB__v31_native is None:return None
    if out.dtype!=np.uint32 or out.shape!=(4,) or not out.flags.c_contiguous:raise ValueError('Completion probe scratch invalid')
    code=_LIB__v31_native.p11_io_probe(pl_array.ctypes.data,dma_array.ctypes.data,int(before)&0xffffffff,int(kind),out.ctypes.data)
    if code<0:raise ValueError('Native completion probe rejected: '+str(code))
    return int(code),dict(pl_status=int(out[0]),pl_error=int(out[1]),tx=int(out[2]),rx=int(out[3]))


def copy_entry__v31_native():
    """Admitted CPU memcpy only; no device mapping is supplied to the worker."""
    return _LIB__v31_native.p11_copy_bgr if _LIB__v31_native is not None else None


class OwnerCompletion__v31_native:
    """Persistent mapping pointers, result scratch and function bindings."""
    def __init__(self,pl,dma):
        self.owner=threading.get_ident();self.arrays=(pl,dma)
        self.available=bool(_LIB__v31_native) and _mmio_layout__v31_native(pl,0xcc) and _mmio_layout__v31_native(dma,0x5c)
        self.state=np.zeros(12,np.uint32);self.completed=None
        self.before=0;self.kind=1
        self.stats=dict(probe_calls=0,wait_calls=0,native_wait_s=0.,snapshots=0)
        if self.available:
            self.pointers=(int(pl.ctypes.data),int(dma.ctypes.data))
            self.output=int(self.state.ctypes.data)
            self.function=_LIB__v31_native.p11_owner_complete;self.state_function=_LIB__v31_native.p11_frame_state
    def begin(self,before,kind):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached completion owner')
        if kind not in (0,1):raise ValueError('Completion kind invalid')
        self.before=int(before)&0xffffffff;self.kind=kind;self.completed=None
    def poll(self,timeout=0.):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached completion owner')
        if not self.available:return None
        began=time.perf_counter()
        code=self.function(*self.pointers,self.before,self.kind,float(timeout),self.output)
        self.stats['native_wait_s']+=time.perf_counter()-began
        self.stats['wait_calls' if timeout else 'probe_calls']+=1
        if code<0:raise ValueError('Cached owner completion rejected: '+str(code))
        if code==0:self.completed=(self.before,self.kind)
        return int(code)
    def snapshot(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached snapshot owner')
        if not self.available:return None
        self.completed=None;code=self.state_function(*self.pointers,self.output)
        if code:raise ValueError('Cached owner snapshot rejected: '+str(code))
        self.stats['snapshots']+=1;return self.state
    def completed_state(self,before,kind=1):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong completion-state owner')
        return self.state if self.completed==(int(before)&0xffffffff,kind) else None
    def error_state(self):
        return dict(pl_status=int(self.state[0]),pl_error=int(self.state[1]),
                    tx=int(self.state[2]),rx=int(self.state[3]))





# Raw YUYV dispatch, keeping the existing BGR helper only for setup previews.
_bgr_gray_area2__v31_native=gray_area2__v31_native
_bgr_fused_observation2__v31_native=fused_observation2__v31_native
_bgr_observe__v31_native=ObservationWorkspace__v31_native.observe
_bgr_copy_entry__v31_native=copy_entry__v31_native

def gray_area2__v31_native(image,out):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_gray_area2__v31_native(image,out)
    if _LIB__v31_native is None:return False
    from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return False
    if out.shape!=(h//2,w//2) or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable:raise ValueError('Y output workspace')
    code=_LIB__v31_native.p11_yuyv_gray2(image.ctypes.data,w,h,image.strides[0],color_mode(),out.ctypes.data)
    if code:raise ValueError('Y observer rejected '+str(code))
    return True

def fused_observation2__v31_native(image,scratch,workspace,out=None,timing=None):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_fused_observation2__v31_native(image,scratch,workspace,out,timing)
    if _LIB__v31_native is None:return None
    from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (scratch.shape!=(h//2,w//2) or scratch.dtype!=np.uint8 or not scratch.flags.c_contiguous or not scratch.flags.writeable
        or workspace.dtype!=np.uint16 or workspace.size<3*(w//2) or not workspace.flags.c_contiguous or not workspace.flags.writeable):raise ValueError('Y Gaussian workspace')
    if out is None:out=np.empty_like(scratch)
    if timing is None:timing=np.empty(2,np.float64)
    if (out.shape!=scratch.shape or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable
        or np.shares_memory(out,scratch) or timing.dtype!=np.float64 or timing.shape!=(2,) or not timing.flags.c_contiguous):raise ValueError('Y output alias/layout')
    code=_LIB__v31_native.p11_yuyv_observe2(image.ctypes.data,w,h,image.strides[0],color_mode(),scratch.ctypes.data,workspace.ctypes.data,out.ctypes.data,timing.ctypes.data)
    if code:raise ValueError('Y fused observer rejected '+str(code))
    return out,dict(resize_gray_s=float(timing[0]),blur_s=float(timing[1]),input_format='YUYV',ps_luminance='direct_Y_normalized')

def _y_observe__v31_native(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius=5.):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_observe__v31_native(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius)
    if _LIB__v31_native is None:return None
    from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (out.shape!=(h//2,w//2) or scratch.shape!=out.shape or out.dtype!=np.uint8 or scratch.dtype!=np.uint8
        or rows.dtype!=np.uint16 or rows.size<3*(w//2) or drift.dtype!=np.float32 or drift.shape!=(4,2)
        or any(not a.flags.c_contiguous or not a.flags.writeable for a in (scratch,rows,out,drift)) or np.shares_memory(out,scratch)):raise ValueError('Y edge workspace')
    self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
    if self.light_results:
        from display import observe_yuyv_bound as observe_yuyv_bound
        code=observe_yuyv_bound(self,image,scratch,rows,out,drift,radius,color_mode(),_LIB__v31_native)
    else:
        code=_LIB__v31_native.p11_yuyv_observe_edges(image.ctypes.data,w,h,image.strides[0],color_mode(),scratch.ctypes.data,rows.ctypes.data,out.ctypes.data,
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,drift.ctypes.data,self.polarity.ctypes.data,
            float(radius),self.result.ctypes.data,self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data,self.times.ctypes.data)
    if code and code>-200:raise ValueError('Y edge observer rejected '+str(code))
    return (self.decode() if code==0 else None),dict(edge_error=(code+200 if code else None),resize_gray_s=float(self.times[0]),blur_s=float(self.times[1]),
        edge_gate_motion_s=float(self.times[2]),native_transaction_s=float(self.times[3]),transaction_backend='cpp_Y_gaussian_edges_confidence_motion',input_format='YUYV')
ObservationWorkspace__v31_native.observe=_y_observe__v31_native

def copy_yuyv_native__v31_native(source,destination):
    if _LIB__v31_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(source);require_yuyv(destination)
    if source.shape!=destination.shape or not destination.flags.writeable or np.shares_memory(source,destination):raise ValueError('YUYV copy destination/alias')
    code=_LIB__v31_native.p11_copy_yuyv(source.ctypes.data,destination.ctypes.data,source.shape[1],source.shape[0],source.strides[0],destination.strides[0])
    if code:raise ValueError('YUYV copy rejected '+str(code))
    return True

def copy_entry__v31_native(bpp=3):
    return (_LIB__v31_native.p11_copy_yuyv if bpp==2 else _bgr_copy_entry__v31_native()) if _LIB__v31_native is not None else None

def yuyv_model_bgr__v31_native(image,mode):
    if _LIB__v31_native is None:return None
    from core import require_yuyv as require_yuyv
    require_yuyv(image);h,w=image.shape[:2];out=np.empty((h,w,3),np.uint8)
    code=_LIB__v31_native.p11_yuyv_bgr(image.ctypes.data,w,h,image.strides[0],int(mode),out.ctypes.data)
    if code:raise ValueError('Model CSC rejected '+str(code))
    return out

def yuyv_preview_into__v31_native(image,mode,out,fast=False):
    if _LIB__v31_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(image)
    if (out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=3 or not out.flags.c_contiguous
            or min(out.shape[:2])<1 or max(out.shape[:2])>640):raise ValueError('Preview workspace layout invalid')
    h,w=image.shape[:2];ho,wo=out.shape[:2]
    entry=_LIB__v31_native.p11_yuyv_preview_nearest if fast else _LIB__v31_native.p11_yuyv_preview
    code=entry(image.ctypes.data,w,h,image.strides[0],int(mode),out.ctypes.data,wo,ho)
    if code:raise ValueError('Preview resize/CSC rejected '+str(code))
    return True


def bgr_preview_into__v31_native(image,out,xmap,ymap):
    """Nearest preview only. All buffers belong to the ordinary-RAM UI worker."""
    if _LIB__v31_native is None:return False
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3
            or image.strides[2]!=1 or image.strides[1]!=3
            or out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=3 or not out.flags.c_contiguous):
        raise ValueError('BGR preview workspace layout invalid')
    h,w=image.shape[:2];ho,wo=out.shape[:2]
    if any(a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (xmap,ymap)):
        raise ValueError('BGR preview index map invalid')
    if xmap.size!=wo or ymap.size!=ho:raise ValueError('BGR preview index map size mismatch')
    code=_LIB__v31_native.p11_bgr_preview_nearest(image.ctypes.data,w,h,image.strides[0],
        out.ctypes.data,wo,ho,xmap.ctypes.data,ymap.ctypes.data)
    if code:raise ValueError('BGR preview resize rejected '+str(code))
    return True


def preview_pair_copy__v31_native(raw,raw_out,bgr,bgr_out,times):
    """One GIL-released row-copy call. Caller pins camera/output until it returns."""
    if _LIB__v31_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(raw)
    if (raw_out.dtype!=np.uint8 or raw.shape!=raw_out.shape or not raw_out.flags.c_contiguous
        or bgr.dtype!=np.uint8 or bgr.ndim!=3 or bgr.shape[2]!=3 or bgr.strides[1:]!=(3,1)
        or bgr_out.dtype!=np.uint8 or bgr.shape!=bgr_out.shape or not bgr_out.flags.c_contiguous
        or times.dtype!=np.float64 or times.shape!=(2,) or not times.flags.c_contiguous):
        raise ValueError('Paired preview copy workspace mismatch')
    rh,rw=raw.shape[:2];bh,bw=bgr.shape[:2]
    code=_LIB__v31_native.p11_preview_pair_copy(raw.ctypes.data,raw_out.ctypes.data,rw,rh,raw.strides[0],raw_out.strides[0],
        bgr.ctypes.data,bgr_out.ctypes.data,bw,bh,bgr.strides[0],bgr_out.strides[0],times.ctypes.data)
    if code:raise ValueError('Paired preview copy rejected '+str(code))
    return True

class CompactPreview__v31_native:
    """Pinned packet/workspace arguments; used only by the single UI worker."""
    def __init__(self,raw,output,work):
        self.available=_LIB__v31_native is not None and work.compact
        self.times=np.zeros(3,np.float64);self.refs=(raw,output,work)
        if not self.available:return
        from core import require_yuyv as require_yuyv
        require_yuyv(raw)
        arrays=(output,work.left,work.canvas)
        if work.right is not None:arrays=arrays+(work.right,)
        if any(a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=3 or not a.flags.c_contiguous for a in arrays):
            raise ValueError('Compact preview workspace must be contiguous BGR')
        hi,wi=raw.shape[:2];bh,bw=output.shape[:2];height,lw=work.left.shape[:2]
        rw=work.canvas.shape[1]-lw
        if work.canvas.shape!=(height,lw+rw,3):raise ValueError('Compact preview canvas shape mismatch')
        if work.right is None:
            if output.shape!=(height,rw,3):raise ValueError('Compact preview native right shape mismatch')
            xs=ys=right=0
        else:
            if work.right.shape!=(height,rw,3):raise ValueError('Compact preview right shape mismatch')
            if any(a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (work.xmap,work.ymap)):
                raise ValueError('Compact preview index map layout mismatch')
            if work.xmap.size!=rw or work.ymap.size!=height:raise ValueError('Compact preview map sizes mismatch')
            xs,ys,right=work.xmap.ctypes.data,work.ymap.ctypes.data,work.right.ctypes.data
        self.entry=_LIB__v31_native.p11_compact_preview
        self.args=(raw.ctypes.data,wi,hi,raw.strides[0],0,output.ctypes.data,bw,bh,output.strides[0],
            work.left.ctypes.data,lw,right,rw,height,xs,ys,work.canvas.ctypes.data,self.times.ctypes.data)
    def run(self,mode):
        if not self.available:return False
        args=self.args
        code=self.entry(*args[:4],int(mode),*args[5:])
        if code:raise ValueError('Compact preview transaction rejected '+str(code))
        return True


_REFINE64__v31_native=threading.local()
def refine_original_y64__v31_native(gray,quad,half_window,packed_mode=None):
    """P1 64x65 original-Y profiles + robust TLS in one native transaction."""
    if _LIB__v31_native is None or not _LIB__v31_native.p11_lk_available():return None
    from geometry import order_corners as order_corners
    import cv2
    start=time.perf_counter();cpu=time.thread_time()
    if packed_mode is None:
        if not isinstance(gray,np.ndarray) or gray.dtype!=np.uint8 or gray.ndim!=2:
            raise ValueError('native64 requires original uint8 Y plane')
        g=np.ascontiguousarray(gray)
    else:
        from core import require_yuyv as require_yuyv
        g=require_yuyv(gray)
        if packed_mode not in (0,1,2,3):raise ValueError('native64 YUYV color range invalid')
    q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('native64 requires ordered convex current corners')
    if not np.isfinite(half_window) or not 3<=half_window<=48:raise ValueError('native64 half_window must be3..48')
    if not hasattr(_REFINE64__v31_native,'buffers'):
        _REFINE64__v31_native.buffers=(np.empty((4,2),np.float64),np.empty(27,np.float64))
    out,stats=_REFINE64__v31_native.buffers
    args=(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0])
    tail=(q.ctypes.data,float(half_window),out.ctypes.data,stats.ctypes.data)
    code=(_LIB__v31_native.p11_refine64(*args,*tail) if packed_mode is None else
          _LIB__v31_native.p11_yuyv_refine64(*args,int(packed_mode),*tail))
    if code==-9:return None
    if code:raise ValueError('native original-Y64 rejected input: '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(stats).all():
        raise ValueError('native original-Y64 returned invalid geometry')
    count=int(stats[24]);edges=[]
    for i in range(4):
        n=int(stats[i*6]);info=dict(edge=i,profiles=64,supported=n,accepted=bool(stats[i*6+4]),profile_contrast=float(stats[i*6+5]))
        if n>=20:info.update(tls_rms=float(stats[i*6+1]),retained=int(stats[i*6+2]),coverage=float(stats[i*6+3]))
        edges.append(info)
    try:
        candidate=out.astype(np.float32)
        if not cv2.isContourConvex(candidate):raise ValueError('native64 refined convexity invalid')
        area_ratio=abs(cv2.contourArea(candidate))/abs(cv2.contourArea(q.astype(np.float32)))
        if not .85<=area_ratio<=1.15 or np.max(np.linalg.norm(candidate-q,axis=1))>3*half_window:
            raise ValueError('native64 refined area/order/displacement invalid')
    except (ValueError,cv2.error):
        candidate=q.astype(np.float32);count=0
    return candidate,dict(method='p1_pyramid_subpixel_profiles_tls',backend='cpp_packed_Y_64x65_Q5' if packed_mode is not None else 'cpp_original_Y_64x65',
        state='refined' if count else 'coarse_retained',refined_corners=count,edges=edges,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(candidate-q,axis=1).tolist(),
        refinement_s=time.perf_counter()-start,refinement_thread_cpu_s=time.thread_time()-cpu,
        native_wall_s=float(stats[25]),native_thread_cpu_s=float(stats[26]),
        workspace_reused=True,interpolation='opencv_uint8_linear_replicate',
        tls_solver='analytic_2x2_principal_axis',original_profile_gates_preserved=True)


def refine_original_yuyv64__v31_native(image,quad,half_window):
    from core import color_mode as color_mode
    return refine_original_y64__v31_native(image,quad,half_window,packed_mode=color_mode())

_COHERENT__v31_native=__import__('threading').local()

def coherent_profiles__v31_native(bands,half_window,fraction_limits,minimum_contrast,boundary_prior=None,line_lock_radius=None):
    """One ctypes transaction for all four current Y/color exterior bands; no device access."""
    if _LIB__v31_native is None:return None
    data=np.ascontiguousarray(bands,np.float32)
    if data.ndim!=4 or data.shape[0]!=4 or data.shape[1] not in (24,64) or data.shape[2]!=65 or data.shape[3] not in (1,3):
        raise ValueError('Coherent exterior band layout invalid')
    shape=(4,data.shape[1],3)
    if not hasattr(_COHERENT__v31_native,'out') or _COHERENT__v31_native.out.shape!=shape:
        _COHERENT__v31_native.out=np.empty(shape,np.float32);_COHERENT__v31_native.times=np.empty(2,np.float64)
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Current consensus side prior invalid')
    if line_lock_radius is not None:
        if not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window:raise ValueError('Current consensus peak lock invalid')
        code=_LIB__v31_native.p11_locked_coherent_profiles(data.ctypes.data,data.shape[1],data.shape[3],float(half_window),
            float(fraction_limits[0]),float(fraction_limits[1]),float(minimum_contrast),float(line_lock_radius),
            0 if prior is None else prior.ctypes.data,_COHERENT__v31_native.out.ctypes.data,_COHERENT__v31_native.times.ctypes.data)
    else:
        code=_LIB__v31_native.p11_coherent_profiles(data.ctypes.data,data.shape[1],data.shape[3],float(half_window),
            float(fraction_limits[0]),float(fraction_limits[1]),float(minimum_contrast),_COHERENT__v31_native.out.ctypes.data,_COHERENT__v31_native.times.ctypes.data)
    if code:raise ValueError('Native exterior consensus rejected bands: '+str(code))
    return _COHERENT__v31_native.out,dict(backend='cpp_four_edge_three_peak_consensus',
        native_wall_s=float(_COHERENT__v31_native.times[0]),native_thread_cpu_s=float(_COHERENT__v31_native.times[1]),workspace_reused=True)

def preview_canvas_into__v31_native(raw,output,work,mode,times,interpolation='nearest'):
    """Borrow source arrays ONLY for this call; destination is owned UI RAM.

    V48 UI worker calls this with owned ordinary-RAM snapshots. Direct borrowed
    use also remains valid only within the call; no source pointer is retained.
    """
    if _LIB__v31_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(raw)
    if (not work.compact or work.right is None or output.dtype!=np.uint8 or output.ndim!=3
        or output.shape[2]!=3 or output.strides[1:]!=(3,1)):
        raise ValueError('Preview borrowed source layout')
    if any(a.dtype!=np.uint8 or not a.flags.c_contiguous or not a.flags.writeable
           for a in (work.left,work.right,work.canvas)):
        raise ValueError('Preview packet workspace')
    if times.shape!=(3,) or times.dtype!=np.float64 or not times.flags.c_contiguous:raise ValueError('Preview timing workspace')
    hi,wi=raw.shape[:2];bh,bw=output.shape[:2];height,lw=work.left.shape[:2];rw=work.right.shape[1]
    if output.strides[0]<3*bw or not 2<=min(hi,wi,bh,bw,height,lw,rw) or max(hi,wi,bh,bw)>1280 or not 0<=int(mode)<=3:
        raise ValueError('Preview dimensions/row stride/mode invalid')
    if not times.flags.writeable:raise ValueError('Preview timing destination is read-only')
    if work.canvas.shape!=(height,lw+rw,3) or work.right.shape[0]!=height:raise ValueError('Preview canvas shape')
    if interpolation=='linear':
        axes=getattr(work,'linear_maps',None)
        if axes is None or len(axes)!=5:raise ValueError('Missing cached linear preview maps')
        sizes=(lw,height,lw,rw,height)
        for axis,size in zip(axes,sizes):
            if (axis.dtype!=np.int32 or axis.shape!=(size,3) or not axis.flags.c_contiguous
                or axis.flags.writeable):raise ValueError('Linear preview map layout')
        if work.linear_layout!=(hi,wi,bh,bw,height,lw,rw):raise ValueError('Linear preview source layout changed')
        code=_LIB__v31_native.p11_preview_canvas_linear(raw.ctypes.data,wi,hi,raw.strides[0],int(mode),
            output.ctypes.data,bw,bh,output.strides[0],work.canvas.ctypes.data,lw,rw,height,
            *(axis.ctypes.data for axis in axes),times.ctypes.data)
        if code:raise ValueError('Bilinear preview canvas transaction rejected '+str(code))
        return True
    if interpolation!='nearest':raise ValueError('Unknown preview interpolation')
    if any(a is None or a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (work.xmap,work.ymap)):
        raise ValueError('Preview map workspace layout')
    if work.xmap.size!=rw or work.ymap.size!=height or np.any(work.xmap<0) or np.any(work.xmap>=bw) or np.any(work.ymap<0) or np.any(work.ymap>=bh):
        raise ValueError('Preview map bounds')
    if not times.flags.writeable:raise ValueError('Preview timing destination is read-only')
    if work.canvas.shape!=(height,lw+rw,3) or work.right.shape[0]!=height:raise ValueError('Preview canvas shape')
    layout=(hi,wi,height,lw)
    if getattr(work,'left_layout',None)!=layout:
        work.left_xmap=(np.arange(lw,dtype=np.int32)*wi//lw)
        work.left_ymap=(np.arange(height,dtype=np.int32)*hi//height)
        work.left_xmap.flags.writeable=False;work.left_ymap.flags.writeable=False;work.left_layout=layout
    code=_LIB__v31_native.p11_preview_canvas_maps(raw.ctypes.data,wi,hi,raw.strides[0],int(mode),
        output.ctypes.data,bw,bh,output.strides[0],work.canvas.ctypes.data,lw,rw,height,
        work.left_xmap.ctypes.data,work.left_ymap.ctypes.data,work.xmap.ctypes.data,work.ymap.ctypes.data,
        times.ctypes.data)
    if code:raise ValueError('Preview canvas transaction rejected '+str(code))
    return True

def packed_vector_profiles__v31_native(image,x,y):
    """Borrow packed source only until return; sample bounded Y/U/V bands."""
    if _LIB__v31_native is None:return None
    from core import require_yuyv as require_yuyv
    require_yuyv(image)
    if max(image.shape[:2])>1280:return None
    mx=np.ascontiguousarray(x,np.float32);my=np.ascontiguousarray(y,np.float32)
    if mx.shape!=my.shape or not 1<=mx.size<=4*64*65:
        raise ValueError('Packed exterior profile coordinate layout invalid')
    output=np.empty((*mx.shape,3),np.float32);h,w=image.shape[:2]
    code=_LIB__v31_native.p11_yuyv_profiles(image.ctypes.data,w,h,image.strides[0],mx.ctypes.data,
        my.ctypes.data,mx.size,output.ctypes.data)
    if code:raise ValueError('Packed exterior sampler rejected '+str(code))
    return output


_EXTERIOR__v31_native=threading.local()
def fused_yuyv_exterior__v31_native(image,quad,half_window,profiles=64,min_support=.60,max_rms=1.5,
                        minimum_contrast=12.,fraction_limits=(.10,.90),deadline=None,boundary_prior=None,line_lock_radius=None,local_signed=False):
    """Current borrowed YUYV bands, consensus, robust TLS and corners in one call.

    CPU-only thread-local scratch. Output arrays are copied, no source pointer
    escapes the transaction. Expired work returns rejected evidence, not fallback.
    """
    if _LIB__v31_native is None or image.ndim!=3 or image.shape[2]!=2 or max(image.shape[:2])>1280:return None
    from core import require_yuyv as require_yuyv
    from geometry import array_key as array_key
    import cv2
    raw=require_yuyv(image);q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('Fused current exterior requires cyclic convex corners')
    if not hasattr(_EXTERIOR__v31_native,'buffers'):
        _EXTERIOR__v31_native.buffers=(np.empty((4,2),np.float64),np.empty(80,np.float64))
    out,s=_EXTERIOR__v31_native.buffers;begin=time.perf_counter();cpu=time.thread_time()
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Boundary side prior invalid')
    if line_lock_radius is not None and (not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window):raise ValueError('Fused current physical lock invalid')
    function=_LIB__v31_native.p11_yuyv_exterior if line_lock_radius is None else _LIB__v31_native.p11_locked_yuyv_exterior
    if local_signed:
        if line_lock_radius is None:raise ValueError('Local signed proof requires a locked physical line')
        function=_LIB__v31_native.p11_v83_locked_yuyv_exterior
    args=() if line_lock_radius is None else (float(line_lock_radius),)
    code=function(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],q.ctypes.data,
        float(half_window),int(profiles),float(fraction_limits[0]),float(fraction_limits[1]),
        float(minimum_contrast),float(min_support),float(max_rms),0. if deadline is None else float(deadline),
        0 if prior is None else prior.ctypes.data,out.ctypes.data,s.ctypes.data,*args)
    if code not in (0,1):raise ValueError('Fused current YUV exterior rejected input: '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(s).all():raise ValueError('Invalid native exterior result')
    result,evidence=_decode_yuyv_exterior__v31_native(raw,q,out,s,half_window,profiles,fraction_limits,boundary_prior,line_lock_radius,
        time.perf_counter()-begin,time.thread_time()-cpu)
    evidence['signed_reference']='point_local_current_primary' if local_signed else 'edge_median_or_unconstrained'
    return result,evidence


def _decode_yuyv_exterior__v31_native(raw,q,out,s,half_window,profiles,fraction_limits,boundary_prior,line_lock_radius,wall_s,cpu_s):
    from geometry import array_key as array_key
    edges=[];support=[];rms=[];colors=[]
    for i in range(4):
        z=s[i*13:(i+1)*13];accepted=bool(z[4])
        edges.append(dict(edge=i,profiles=profiles,supported=int(z[0]),retained=int(z[1]),
            coverage=float(z[2]),tls_rms=float(z[3]),accepted=accepted,polarity=0,Y_polarity=int(z[12]),
            highlight_fraction=float(s[65+i]),dark_clip_fraction=float(s[69+i]),
            contrast_backend='unclipped_YUV_vector_gradient'))
        support.append(float(z[1])/profiles if accepted else 0.);rms.append(float(z[3]))
        colors.append(z[6:12].tolist())
    evidence=dict(method='coherent_multicolor_gradient_TLS',state='refined' if s[53] else 'rejected',
        valid=bool(s[53]),refined_corners=int(s[52]),supported_edges=sum(e['accepted'] for e in edges),
        edges=edges,edge_support=support,edge_rms=rms,edge_polarity=[0]*4,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(out-q,axis=1).tolist(),
        refinement_s=float(wall_s),refinement_thread_cpu_s=float(cpu_s),
        backend='cpp_fused_current_YUV_exterior',profiles_per_edge=int(profiles),fraction_limits=list(fraction_limits),
        vector_sample_backend='cpp_direct_YUV_bands_no_full_plane_pack',consensus_backend='cpp_four_edge_three_peak_consensus',
        native_wall_s=float(s[54]),native_thread_cpu_s=float(s[55]),sampling_s=float(s[56]),sampling_thread_cpu_s=float(s[57]),
        consensus_native_wall_s=float(s[58]),consensus_native_thread_cpu_s=float(s[59]),fit_s=float(s[60]),fit_thread_cpu_s=float(s[61]),
        deadline_hit=bool(s[62]),workspace_reused=True,same_frame_color_bands_only=True,
        color_vector_proof=True,brightness_polarity_required=False,same_frame_source=True,
        current_source_key=array_key(raw),source_proof_kind='raw_YUV_profiles',border_colors=colors,
        physical_source_corners=out.astype(np.float32).tolist(),
        gradient_consensus_required=True,area_ratio=float(s[63]),corner_order_preserved=True,
        boundary_prior_used=boundary_prior is not None,border_color_sampling='fitted_line_sides_3px',
        physical_peak_lock=line_lock_radius is not None,peak_lock_radius_source=line_lock_radius,
        signed_peak_lock=bool(line_lock_radius is not None and boundary_prior is not None))
    return out.astype(np.float32),evidence



def fused_locked_pair__v31_native(image,quad,half_window,primary_lock,scale_min,deadline=None,boundary_prior=None,cpu_budget_s=.12):
    """Two independent current-color sample layouts; all geometric gates remain outside."""
    if _LIB__v31_native is None or image.ndim!=3 or image.shape[2]!=2:return None
    from core import require_yuyv as require_yuyv
    raw=require_yuyv(image);q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Native pair quad layout invalid')
    if not hasattr(_EXTERIOR__v31_native,'pair'):
        _EXTERIOR__v31_native.pair=(np.empty((2,4,2),np.float64),np.empty((2,80),np.float64),np.empty(4,np.float64))
    out,stats,timing=_EXTERIOR__v31_native.pair
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Native pair prior invalid')
    began=time.perf_counter();cpu=time.thread_time()
    code=_LIB__v31_native.p11_v67_locked_pair(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],q.ctypes.data,
        float(half_window),8.,.60,float(scale_min),0. if deadline is None else float(deadline),
        0 if prior is None else prior.ctypes.data,float(primary_lock),float(scale_min),float(cpu_budget_s),
        out[0].ctypes.data,stats[0].ctypes.data,out[1].ctypes.data,stats[1].ctypes.data,timing.ctypes.data)
    if code not in (0,1,2,3):raise ValueError('Native pair input rejected '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(stats).all():raise ValueError('Native pair output invalid')
    first=_decode_yuyv_exterior__v31_native(raw,q,out[0],stats[0],half_window,64,(.10,.90),boundary_prior,primary_lock,stats[0,54],stats[0,55])
    first[1]['signed_reference']='point_local_current_primary'
    secondary_lock=min(.70*half_window,float(np.clip(1.25+.75*max(stats[0,i*13+3] for i in range(4)),1.25,2.)))
    # The core derives the secondary signed prior from the current primary.
    second=_decode_yuyv_exterior__v31_native(raw,out[0],out[1],stats[1],half_window,24,(.12,.88),True if stats[0,53] else None,secondary_lock,stats[1,54],stats[1,55])
    second[1]['signed_reference']='point_local_current_primary'
    detail=dict(backend='cpp_current_locked64_independent24',code=int(code),complete=code==0,
        pair_wall_s=time.perf_counter()-began,pair_thread_cpu_s=time.thread_time()-cpu,
        native_pair_wall_s=float(timing[0]),native_pair_thread_cpu_s=float(timing[1]),
        independent_grids=[[64,.10,.90],[24,.12,.88]],same_locked_line=True,
        secondary_reference='fresh_primary64',geometric_proof_granted=False)
    return first,second,detail


# ======================================================================
# ===== [08/28] v68_stability =====
# ======================================================================


"""Private CPU workspace: joint edge motion and bounded, remeasured jitter filter."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

class StableEdgeWorkspace:
    def __init__(self):
        self.quads=np.empty((3,4,2),np.float64)
        self.support=np.empty(4,np.float64);self.rms=np.empty(4,np.float64)
        self.polarity=np.empty(4,np.int32);self.out=np.empty((4,2),np.float64)
        self.checked=np.empty((4,2),np.float64);self.edges=np.empty(21,np.float64)
        self.stats=np.empty(26,np.float64)
    def measure(self,gray,previous,prediction,candidate,evidence,allow_filter=True):
        if _LIB__v31_native is None:return None
        began=time.perf_counter();cpu=time.thread_time()
        g=np.ascontiguousarray(gray,np.uint8)
        if g.ndim!=2:raise ValueError('Stable edges require current gray plane')
        for i,q in enumerate((previous,prediction,candidate)):
            if np.shape(q)!=(4,2):raise ValueError('Stable edge quad layout invalid')
            self.quads[i]=q
        supports=evidence.get('edge_support',());rms=evidence.get('edge_rms',());polarity=evidence.get('edge_polarity',())
        if len(supports)!=4 or len(rms)!=4 or len(polarity)!=4:return None
        self.support[:]=supports;self.rms[:]=rms;self.polarity[:]=polarity
        code=_LIB__v31_native.p11_v68_stabilize(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            self.quads[0].ctypes.data,self.quads[1].ctypes.data,self.quads[2].ctypes.data,
            self.support.ctypes.data,self.rms.ctypes.data,self.polarity.ctypes.data,int(bool(allow_filter)),
            self.out.ctypes.data,self.checked.ctypes.data,self.edges.ctypes.data,self.stats.ctypes.data)
        if code:raise ValueError('Stable current-edge helper rejected input '+str(code))
        if not np.isfinite(self.out).all() or not np.isfinite(self.stats).all():raise ValueError('Stable edge result invalid')
        s=self.stats
        detail=dict(backend='cpp_joint_line_motion_current_recheck',physical_layer_suspect=bool(s[0]),
            filtered=bool(s[1]),raw_motion=float(s[2]),prediction_correction=float(s[3]),
            joint_motion_residual=float(s[4]),largest_edge_offset=float(s[5]),second_edge_offset=float(s[6]),
            noise_pixels=float(s[7]),filter_alpha=float(s[8]),filter_shift=float(s[9]) if s[1] else 0.,
            proposed_filter_shift=float(s[9]),
            current_fit_line_error=float(s[10]),remeasured_line_error=float(s[11]),
            native_wall_s=float(s[12]),native_thread_cpu_s=float(s[13]),current_remeasured=bool(s[14]),
            strong_current_edges=bool(s[15]),signed_edge_offsets=s[16:20].tolist(),
            real_motion_filter_bypassed=bool(s[20]),current_quad_valid=bool(s[21]),filter_proposed=bool(s[22]),
            remeasure_support=float(s[23]),remeasure_rms=float(s[24]),filtered_quad_valid=bool(s[25]),
            wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu,
            independent_source_proof_granted=False,old_H_not_used=True)
        updated=evidence
        if detail['filtered']:
            e=self.edges
            updated=dict(evidence,valid=bool(e[20]),supported_edges=int(e[17]),refined_corners=int(e[16]),
                edge_support=[min(float(e[i]),float(self.support[i])) for i in range(4)],
                edge_rms=[max(float(e[12+i]),float(self.rms[i])) for i in range(4)],
                edge_polarity=[int(e[4+i]) for i in range(4)],
                edge_backend='cpp_current_Y24_filtered_quad_recheck',filtered_current_line_recheck=True,
                filter_max_shift_tracking_pixels=.25,current_recheck_radius=1.75)
        result=self.out.astype(np.float32)
        detail.update(wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu)
        return result,updated,detail


# ======================================================================
# ===== [09/28] v69_policy =====
# ======================================================================


"""V49 ordinary-path support: current-frame CPU proof reuse, no device access."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class CurrentProofWorkspace:
    """At most four completed requests, scoped to one source/gray/index.

    Owns small corners and CPU evidence only. No camera arrays, leases, native
    pointers, H or hardware proof are retained. Failed proofs are never cached.
    """
    def __init__(self):
        self.scope=None;self.entries=[];self.hits=0;self.stores=0

    def clear(self):
        self.scope=None;self.entries.clear();self.hits=self.stores=0

    def begin(self,image,gray,index,scale):
        from geometry import array_key as array_key
        self.clear()
        self.scope=(id(image),array_key(image),id(gray),array_key(gray),int(index),
            tuple(float(v) for v in scale))

    def token(self,image,gray,index,scale,candidate,reference,radius,new_candidate,gray_reliable,stable_fb):
        from geometry import array_key as array_key
        scope=(id(image),array_key(image),id(gray),array_key(gray),int(index),
            tuple(float(v) for v in scale))
        if scope!=self.scope:return None
        a=np.asarray(candidate,np.float32);b=np.asarray(reference,np.float32)
        if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():return None
        return (a.tobytes(),b.tobytes(),float(radius),bool(new_candidate),bool(gray_reliable),bool(stable_fb))

    def get(self,token):
        if token is None:return None
        for key,quad,evidence,gate,agreement in self.entries:
            if key==token:
                self.hits+=1
                return quad.copy(),copy.deepcopy(evidence),dict(gate),copy.deepcopy(agreement)
        return None

    def remember(self,token,quad,evidence,gate,agreement):
        from geometry import actual_source64 as actual_source64
        if (token is None or self.scope is None or not gate.get('reliable')
                or not agreement.get('verified') or not actual_source64(evidence,self.scope[1])
                or not agreement.get('source64_provenance_verified')
                or not agreement.get('independent_sampling_verified')):return
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return
        self.entries=[item for item in self.entries if item[0]!=token]
        self.entries.append((token,q.copy(),copy.deepcopy(evidence),dict(gate),copy.deepcopy(agreement)))
        if len(self.entries)>4:self.entries.pop(0)
        self.stores+=1

    def summary(self):
        return dict(hits=self.hits,stored=self.stores,entries=len(self.entries),capacity=4,
            same_live_source_only=True,failed_proofs_retained=False,hardware_proof_reused=False)


def issue_current_receipt(observation,image,source_quad,primary,secondary,secondary_quad,scale,agreement,gate):
    """Only a synchronous, full-source detection may publish this receipt.

    ROI/donor/background observations receive no reusable current receipt.
    Primary returned corners remain the physical boundary reference.
    """
    from geometry import array_key as array_key
    from geometry import issue_startup_receipt as issue_startup_receipt
    if (not isinstance(observation,dict) or 'frame_index' not in observation
            or observation.get('source_key')!=array_key(image)):return None
    gray=observation.get('gray')
    if gray is None:return None
    proof=issue_startup_receipt(image,source_quad,primary,secondary,secondary_quad,scale,agreement,gate)
    if proof is None:return None
    return dict(kind='v69_same_frame_primary64_independent24',
        frame_index=int(observation['frame_index']),gray_instance_id=id(gray),gray_key=array_key(gray),proof=proof)


def read_current_receipt(info,image,gray,scale,index,full):
    """Recheck bound metadata; the caller removes it after final admission.

    Two same-call readers (ROI/full return and final tracker admission) can
    inspect it while the exact source is leased. No sampling is repeated.
    """
    from geometry import array_key as array_key
    from geometry import consume_startup_receipt as consume_startup_receipt
    if not isinstance(info,dict):return None
    receipt=info.get('_current_boundary_receipt')
    if (not isinstance(receipt,dict) or receipt.get('kind')!='v69_same_frame_primary64_independent24'
            or receipt.get('frame_index')!=index or receipt.get('gray_instance_id')!=id(gray)
            or receipt.get('gray_key')!=array_key(gray)):return None
    result=consume_startup_receipt({'_initial_boundary_receipt':copy.deepcopy(receipt.get('proof'))},image,full,scale)
    if result is None:return None
    quad,evidence,gate,agreement=result
    agreement=dict(agreement,startup_same_frame_proof_reused=False,
        current_same_frame_proof_reused=True,receipt_single_use=False,
        receipt_scope='synchronous current frame; removed after final tracker admission')
    return quad,evidence,dict(gate,same_frame_receipt_reused=True,
        repeated_border_selection_skipped=True,current_source_agreement=agreement)


def ordinary_policy(evidence,gate,age,max_gap,scheduled=False,lost=False):
    """The V49 normal four-edge gate; scheduling still owns complete FB LK."""
    eligible=(not lost and not scheduled and 0<=age<max_gap and gate.get('reliable',False)
        and evidence.get('valid',False) and evidence.get('supported_edges')==4
        and evidence.get('refined_corners')==4 and not evidence.get('color_vector_proof',False))
    return dict(eligible=bool(eligible),policy='V49_current_Y_four_edges',
        current_four_edges_required=True,scheduled_FB_not_skipped=True,
        anchor_age=int(age),max_anchor_age=int(max_gap),reacquisition=bool(lost))


# ======================================================================
# ===== [10/28] v78_localization =====
# ======================================================================


"""Failure-only, bounded cover-texture proposals. No H admission or device IO."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class BookRescue:
    """Failure-only cover motion. Cache coordinates, never source image history."""
    def __init__(self,enabled=True,cpu_ms=70.):
        self.configure(enabled,cpu_ms)
        self.anchor_ready=None;self.next_at=0.;self.failures=0;self.frame_index=None
        self.mask=None;self.detail={};self.begin=self.cpu=0.;self.deadline=0.
        self.output=np.empty((32,2),np.float32);self.stats=np.empty(8,np.int32)
        self.cache=None;self.pending=None;self.cache_uses=0
    def configure(self,enabled,cpu_ms):
        if not isinstance(enabled,bool):raise ValueError('book_rescue must be bool')
        if isinstance(cpu_ms,bool) or not np.isfinite(cpu_ms) or not 30<=float(cpu_ms)<=120:
            raise ValueError('book_rescue_cpu_ms must be30..120')
        self.enabled=enabled;self.proof_cpu_s=float(cpu_ms)/1000.
        self.selection_cpu_s=min(.008,self.proof_cpu_s*.15);self.flow_cpu_s=.040
        self.cpu_s=self.selection_cpu_s+self.flow_cpu_s+self.proof_cpu_s
    def mark_anchor(self,ready,quad=None,channel=None):
        self.anchor_ready=float(ready);self.cache=None;self.cache_uses=0
        pending=self.pending;self.pending=None
        if pending is not None and quad is not None and channel==pending['channel']:
            shift=float(np.max(np.linalg.norm(np.asarray(quad)-pending['quad'],axis=1)))
            if shift<=1.5 and 0<=float(ready)-pending['ready']<=.35:
                self.cache=dict(pending,anchor_ready=float(ready));self.cache_uses=int(pending.get('uses',0))
    def available(self):
        return time.perf_counter()<self.deadline and time.thread_time()-self.cpu<self.cpu_s
    def normal_success(self):self.failures=0
    def prepare(self,anchor,current,quad,prediction,rim,index,ready,lost,flow_channel):
        """At most16 corner-zone cover points plus up to16 real rim points.

        The central region is excluded. Screen-like dark rims and duplicate local
        patterns are rejected conservatively; these are guards, not semantics.
        """
        if not self.enabled:return None
        now=time.perf_counter()
        if self.frame_index==index or now<self.next_at:return None
        self.frame_index=index;self.begin=now;self.cpu=time.thread_time();self.deadline=now+.30
        self.detail=dict(attempted=True,verified=False,index=int(index),policy='current_first_failure_only_cover_proposal',
            cpu_budget_s=self.cpu_s,proof_cpu_budget_s=self.proof_cpu_s,
            selection_cpu_budget_s=self.selection_cpu_s,flow_reserved_cpu_s=self.flow_cpu_s,
            wall_guard_s=.30,flow_channel=flow_channel,
            center_excluded=True,full_FB_required=True,current_four_edges_required=True,
            old_H_can_renew_from_texture=False,semantic_book_identity_proven=False)
        age=float('inf') if self.anchor_ready is None else float(ready)-self.anchor_ready
        self.detail['anchor_age_s']=age
        if lost or not 0<=age<=1.5:
            self.detail['reason']='no_recent_verified_anchor';return None
        if anchor is None or anchor.shape!=current.shape or anchor.dtype!=np.uint8:
            self.detail['reason']='anchor_plane_unavailable';return None
        q=np.asarray(quad,np.float32);p=np.asarray(prediction,np.float32)
        if q.shape!=(4,2) or p.shape!=(4,2) or not np.isfinite(q).all() or not np.isfinite(p).all():
            self.detail['reason']='invalid_cover_proposal';return None
        edge=np.roll(p,-1,axis=0)-p;length=np.linalg.norm(edge,axis=1)
        if min(length)<24:
            self.detail['reason']='cover_too_small';return None
        normal=np.stack((-edge[:,1],edge[:,0]),axis=1)/length[:,None]
        normal*=np.where(np.sum((p.mean(axis=0)-p)*normal,axis=1)>=0,1.,-1.)[:,None]
        xy=p[:,None,None,:]+np.linspace(.12,.88,8)[None,:,None,None]*edge[:,None,None,:]+np.array([2.,4.])[None,None,:,None]*normal[:,None,None,:]
        x=np.clip(np.rint(xy[...,0]).astype(np.int32),0,current.shape[1]-1)
        y=np.clip(np.rint(xy[...,1]).astype(np.int32),0,current.shape[0]-1)
        rim_luma=np.median(current[y,x],axis=(1,2))
        self.detail['current_inner_rim_luma']=rim_luma.tolist()
        if np.sum(rim_luma<75.)>=3:
            self.detail['reason']='dark_rim_screen_guard';return None
        cache=self.cache
        if (cache is not None and cache['anchor_ready']==self.anchor_ready and cache['channel']==flow_channel
                and 0<=float(ready)-cache['origin_ready']<=.75 and self.cache_uses<3):
            self.cache_uses+=1
            self.detail.update(selection_backend='verified_auxiliary_coordinates',selection_reused=True,
                cache_use=self.cache_uses,selection_s=time.perf_counter()-self.begin,
                selection_thread_cpu_s=time.thread_time()-self.cpu)
            return cache['points'],cache['rim_count']
        if _LIB__v31_native is None or not _LIB__v31_native.p11_lk_available():
            self.detail['reason']='native_cover_selector_unavailable';return None
        from geometry import outer_features as outer_features
        original=np.ascontiguousarray(outer_features(rim,q),np.float32).reshape(-1,2)
        if len(original)<3:
            self.detail['reason']='fewer_than_three_real_rim_anchors';return None
        anchor=np.ascontiguousarray(anchor,np.uint8);q=np.ascontiguousarray(q,np.float32)
        self.stats.fill(0)
        code=_LIB__v31_native.p11_cover_features(anchor.ctypes.data,anchor.shape[1],anchor.shape[0],q.ctypes.data,
            original.ctypes.data,len(original),self.output.ctypes.data,self.stats.ctypes.data,self.selection_cpu_s)
        if code:raise ValueError('Native cover selector rejected '+str(code))
        n,rim_count,cover_count,regions,repeated,clipped,timeout,candidates=map(int,self.stats)
        self.detail.update(rim_features=rim_count,cover_features=cover_count,cover_regions=regions,
            selection_backend='cpp_corner_tensor_spatial_quota_patch_dedup',selection_reused=False,
            duplicate_patterns_rejected=repeated,low_contrast_or_clipped_rejected=clipped,
            selection_budget_hit=bool(timeout),selection_candidates=candidates,
            selection_s=time.perf_counter()-self.begin,selection_thread_cpu_s=time.thread_time()-self.cpu)
        if cover_count<8 or regions<3 or not self.available():
            self.detail['reason']='insufficient_distributed_cover_texture' if not timeout else 'selection_budget'
            return None
        return self.output[:n].reshape(-1,1,2),rim_count
    def remember_flow(self,points,forward,backward,status,reverse,error,rim_count,anchor_quad,quad,ready,channel):
        a=np.asarray(points).reshape(-1,2);z=np.asarray(forward).reshape(-1,2)
        b=np.asarray(backward).reshape(-1,2)
        H=cv2.getPerspectiveTransform(np.asarray(anchor_quad,np.float32),np.asarray(quad,np.float32))
        mapped=cv2.perspectiveTransform(a.reshape(1,-1,2),H)[0]
        good=(np.asarray(status).ravel().astype(bool)&np.asarray(reverse).ravel().astype(bool)
            &np.isfinite(z).all(axis=1)&np.isfinite(b).all(axis=1)&np.isfinite(mapped).all(axis=1)
            &(np.linalg.norm(b-a,axis=1)<.7)&(np.asarray(error).ravel()<25.)
            &(np.linalg.norm(mapped-z,axis=1)<=1.25))
        nr=int(good[:rim_count].sum());nc=int(good[rim_count:].sum())
        if nr>=3 and nc>=8:
            self.pending=dict(points=np.ascontiguousarray(z[good],np.float32).reshape(-1,1,2),rim_count=nr,
                quad=np.asarray(quad,np.float32).copy(),ready=float(ready),channel=channel,
                origin_ready=(self.cache['origin_ready'] if self.detail.get('selection_reused') else self.anchor_ready),
                uses=self.cache_uses if self.detail.get('selection_reused') else 0)
    def finish(self,success,reason=None):
        now=time.perf_counter();used=time.thread_time()-self.cpu
        self.failures=0 if success else min(3,self.failures+1)
        if not success:self.pending=None
        self.next_at=now+(.25 if success else min(1.,.25*(2**(self.failures-1))))
        self.detail.update(verified=bool(success),wall_s=now-self.begin,thread_cpu_s=used,
            cpu_budget_hit=used>=self.cpu_s,wall_guard_hit=now>=self.deadline,
            cpu_overshoot_s=max(0.,used-self.cpu_s),next_attempt_at=self.next_at,
            scope='cooperative checkpoints; a complete native FB/proof call cannot be preempted')
        if reason is not None:self.detail['reason']=str(reason)
        return dict(self.detail)


def verify_rim_flow(points,forward,backward,status,reverse,error,rim_count,anchor_quad,moved_quad):
    """Cover motion must agree with >=3 widely distributed real exterior tracks."""
    a=np.asarray(points,np.float32).reshape(-1,2)[:rim_count]
    z=np.asarray(forward,np.float32).reshape(-1,2)[:rim_count]
    b=np.asarray(backward,np.float32).reshape(-1,2)[:rim_count]
    error=np.asarray(error).reshape(-1)[:rim_count]
    good=np.asarray(status).ravel()[:rim_count].astype(bool)&np.asarray(reverse).ravel()[:rim_count].astype(bool)
    good&=np.isfinite(z).all(axis=1)&np.isfinite(b).all(axis=1)&np.isfinite(error)
    good&=(np.linalg.norm(b-a,axis=1)<.7)&(error<25.)
    H=cv2.getPerspectiveTransform(np.asarray(anchor_quad,np.float32),np.asarray(moved_quad,np.float32))
    predicted=cv2.perspectiveTransform(a.reshape(1,-1,2),H)[0]
    good&=np.isfinite(predicted).all(axis=1)&(np.linalg.norm(predicted-z,axis=1)<=1.25)
    kept=a[good];area=abs(cv2.contourArea(np.asarray(anchor_quad,np.float32)))
    coverage=abs(cv2.contourArea(cv2.convexHull(kept))) / max(area,1.) if len(kept)>=3 else 0.
    verified=bool(len(kept)>=3 and coverage>=.15)
    return dict(verified=verified,rim_good_features=int(good.sum()),rim_total=rim_count,
        rim_hull_fraction=coverage,min_rim_features=3,min_rim_hull_fraction=.15,
        max_rim_reprojection=1.25,complete_rim_forward_backward_required=True)


# ======================================================================
# ===== [11/28] v79_acquire =====
# ======================================================================


"""Live acquisition: owned CPU snapshots, current hint proof, no device access."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


@dataclass
class OwnedFrame:
    image:object
    ready:float
    sequence:int
    timestamp:float
    flags:int=0
    released:bool=False
    def release(self):self.released=True  # Ordinary RAM; never a V4L2 lease.


class LiveAcquire:
    """One bounded worker, one replaceable snapshot, no MMAP or PL pointers.

    Detection failure keeps the page alive. The worker's old quad is only a
    proposal: a later snapshot must pass strict current admission before use.
    """
    def __init__(self,detection_limit,tracking_limit,factory=None):
        self.detection_limit=detection_limit;self.tracking_limit=tracking_limit;self.factory=factory
        self.condition=threading.Condition();self.latest=None;self.result=None
        self.stop=False;self.error=None;self.candidate=();self.candidate_ready=0.;self.context=copy_context()
        self.attempts=0;self.rejections=0;self.worker_cpu_s=0.;self.worker_wall_s=0.
        self.candidate_retry=CandidateRetry()
        self.thread=threading.Thread(target=self._entry,name='p11-initial-acquisition',daemon=True)
        self.thread.start()
    def offer(self,frame):
        with self.condition:
            if self.error is not None:raise RuntimeError('Initial acquisition worker failed') from self.error
            if self.stop or self.result is not None:return
            # Latest-slot replacement is bounded to two ordinary snapshots
            # (one in use, one waiting); no camera buffer crosses threads.
            self.latest=OwnedFrame(np.array(frame.image,copy=True,order='C'),float(frame.ready),
                int(frame.sequence),float(frame.timestamp),int(frame.flags))
            self.condition.notify_all()
    def take(self):
        with self.condition:
            if self.error is not None:raise RuntimeError('Initial acquisition worker failed') from self.error
            value=self.result;self.result=None
            return value
    def _next(self,after=-1.):
        with self.condition:
            while not self.stop and (self.latest is None or self.latest.ready<=after):self.condition.wait(.1)
            if self.stop:return None
            item=self.latest;self.latest=None
            return item
    def _detect(self,frame,observer,seed=None):
        gray,scale=observer.get(frame.image)
        # Full search and strict hint proof have separate CPU slices; never
        # pass a stale source receipt or let search exhaust current admission.
        budget=CpuRecoveryBudget(420. if seed is None else 220.,4 if seed is None else 1,
            wall_max_s=1. if seed is None else .65)
        budget.log_detail=False
        seeds=() if seed is None else (dict(detector='live_multicolor_exterior',coarse_corners=np.asarray(seed).tolist()),)
        observation=dict(gray=gray,scale=scale,source_shape=frame.image.shape)
        if seed is None:self.candidate_retry.begin(frame.image)
        # Strict current revalidation of a successful proposal is never skipped
        # by a negative hint from a different source frame.
        success=False;started=time.perf_counter()
        try:
            with recovery_detection_scope(budget,observation),recovery_candidate_scope(seeds,seed is not None),candidate_retry_scope(self.candidate_retry if seed is None else None):
                result=detect_refined(frame.image,self.detection_limit,True,prefer_mask=True,
                    tracking_limit=self.tracking_limit)
            success=True;return result
        finally:
            if seed is None:self.candidate_retry.completed(success,time.perf_counter()-started)
    def _entry(self):
        try:self.context.run(self._run)
        except BaseException as exc:
            with self.condition:self.error=exc;self.condition.notify_all()
    def _run(self):
        observer=GrayObserver__v31_tracking(self.tracking_limit);pending=None;pending_ready=0.;hint_misses=0;next_log=0.
        while True:
            frame=self._next()
            if frame is None:return
            begin=time.perf_counter();cpu=time.thread_time();built=None
            try:
                self.attempts+=1
                if pending is not None and 0<=frame.ready-pending_ready<=.9 and hint_misses<2:
                    current=frame;hint_misses+=1
                    quad,info=self._detect(current,observer,pending)
                else:
                    quad,info=self._detect(frame,observer)
                    pending=np.asarray(quad,np.float32).copy();pending_ready=frame.ready;hint_misses=0
                    with self.condition:
                        self.candidate=tuple(map(tuple,pending.tolist()));self.candidate_ready=frame.ready
                    current=self._next(frame.ready)
                    if current is None:return
                    quad,info=self._detect(current,observer,pending)
                if time.perf_counter()-current.ready>.40:
                    raise ValueError('Strict current candidate completed too late; request a fresh snapshot')
                detection=(quad,info)
                built=self.factory(current,detection) if self.factory else None
                if time.perf_counter()-current.ready>.75:
                    raise ValueError('Initialization exceeded current source age; retry without publishing old H')
                report=dict(attempts=self.attempts,rejections=self.rejections,
                    source_sequence=current.sequence,current_revalidated=True,
                    elapsed_worker_cpu_s=self.worker_cpu_s+time.thread_time()-cpu,
                    startup_gate_removed=True,owned_source=True)
                with self.condition:
                    cancelled=self.stop
                    if not cancelled:
                        self.result=(current,detection,built,report);self.latest=None;self.stop=True
                        self.condition.notify_all()
                if cancelled and built is not None:built.close()
                return
            except (ValueError,cv2.error) as exc:
                if built is not None:built.close()
                self.rejections+=1
                now=time.perf_counter()
                if now>=next_log:
                    checkpoint('LIVE_ACQUIRE_RETRY',attempts=self.attempts,rejections=self.rejections,
                        reason=str(exc),preview_continues=True,hardware_access=False)
                    next_log=now+2.
            finally:
                self.worker_cpu_s+=time.thread_time()-cpu;self.worker_wall_s+=time.perf_counter()-begin
    def close(self):
        with self.condition:
            self.stop=True;self.latest=None;self.condition.notify_all()
        self.thread.join(5.)
        if self.thread.is_alive():raise TimeoutError('Initial CPU call is still retiring; keep owned workspace pinned')
        with self.condition:unused=self.result;self.result=None
        if unused is not None and unused[2] is not None:unused[2].close()


def pump_acquisition(worker,camera,display,check,generation,deadline=None,context=None,*,already_running=False,ready_after=None):
    began=time.perf_counter();next_offer=0.;observed=0;first_ready=None
    checkpoint('LIVE_ACQUIRE_BEGIN',preview_continues=True,strict_current_admission=True,
        exposure_stability_blocks_display=False,queue_capacity=1,hardware_access=False,
        already_running_stream=already_running,source_ready_after=ready_after)
    while True:
        check()
        if deadline is not None and time.perf_counter()>=deadline:
            raise TimeoutError('Live acquisition session deadline reached')
        ready=worker.take()
        if ready is not None:
            checkpoint('LIVE_ACQUIRE_ACCEPTED',**ready[3],preview_frames=observed,
                elapsed_s=time.perf_counter()-began)
            return ready
        try:frame=camera.take(.10)
        except TimeoutError:continue
        try:
            if ready_after is not None and float(frame.ready)<ready_after:continue
            observed+=1
            if first_ready is None:first_ready=float(frame.ready)
            now=time.perf_counter()
            if now>=next_offer:
                with worker.condition:candidate=worker.candidate;candidate_ready=worker.candidate_ready
                display.offer(None,dict(index=-2,camera_sequence=int(frame.sequence),state='SEARCHING',
                    corners=(),candidate_corners=candidate,candidate_ready_at=candidate_ready,
                    color_mode=int(camera.color_mode),verified_at=0.,
                    capture_ready_at=float(frame.ready),correction_fps=0.,ui_generation=generation(),
                    **startup_meta(context,'acquiring')),frame.image)
                # Startup does not add more than eight full preview copies/s.
                next_offer=now+.125
            # Let automatic exposure begin settling while the RAW view is
            # already visible. No brightness-stability timeout can hide it.
            if already_running or observed>=12 and float(frame.ready)-first_ready>=.35:worker.offer(frame)
        finally:frame.release()


# ======================================================================
# ===== [12/28] v79_setup =====
# ======================================================================


"""CPU-only native setup behind a live raw view; cancellable child processes."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class NativeSetupCancelled(Exception):pass


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():raise NativeSetupCancelled('Native setup cancelled by session owner')


def _retire_child(child):
    if child.poll() is not None:return
    if os.name=='posix':
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    else:child.terminate()
    try:child.wait(1.)
    except subprocess.TimeoutExpired:
        if os.name=='posix':
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        else:child.kill()
        child.wait(2.)


def setup_command(command,timeout,cancel,stage):
    """No shell, preexec hook, device handles or compiler stdout PIPE deadlock."""
    check_cancel(cancel);begin=time.perf_counter();child=None;next_log=begin+3.
    checkpoint(stage+'_BEGIN',program=Path(command[0]).name,timeout_s=float(timeout),hardware_access=False)
    with tempfile.TemporaryFile() as output,tempfile.TemporaryFile() as errors:
        try:
            child=subprocess.Popen(command,stdout=output,stderr=errors,start_new_session=os.name=='posix')
            if stage.endswith('BUILD') and hasattr(os,'setpriority'):
                try:os.setpriority(os.PRIO_PROCESS,child.pid,8)
                except (OSError,AttributeError):pass
            while child.poll() is None:
                check_cancel(cancel);now=time.perf_counter()
                if now-begin>=timeout:raise subprocess.TimeoutExpired(command,timeout)
                if now>=next_log:
                    checkpoint(stage+'_PROGRESS',elapsed_s=now-begin,raw_preview_expected=True,hardware_access=False)
                    next_log=now+3.
                if cancel is None:time.sleep(.05)
                elif cancel.wait(.05):check_cancel(cancel)
            check_cancel(cancel)
            output.seek(0,2);output.seek(max(0,output.tell()-8000))
            errors.seek(0,2);errors.seek(max(0,errors.tell()-8000))
            stdout=output.read().decode('utf-8',errors='replace');stderr=errors.read().decode('utf-8',errors='replace')
            checkpoint(stage+'_END',returncode=child.returncode,elapsed_s=time.perf_counter()-begin,
                error_tail=stderr[-2000:] if child.returncode else None)
            return subprocess.CompletedProcess(command,child.returncode,stdout,stderr)
        except BaseException as exc:
            if child is not None:_retire_child(child)
            checkpoint(stage+'_ABORTED',exception_type=type(exc).__name__,exception=str(exc),
                elapsed_s=time.perf_counter()-begin,owned_child_retired=child is None or child.poll() is not None)
            raise


class NativeSetup:
    """Only compiles/loads CPU helpers; never operates camera, MMIO or VDMA."""
    def __init__(self):
        self.cancel=threading.Event();self.done=threading.Event();self.error=None;self.status=None
        self.context=copy_context();self.thread=None
        self.started_at=None;self.finished_at=None;self.trigger=None
    @property
    def elapsed_s(self):
        return 0. if self.started_at is None else max(0.,(self.finished_at or time.perf_counter())-self.started_at)
    def start(self,trigger='raw_preview'):
        check_cancel(self.cancel)
        if self.thread is not None:return
        self.started_at=time.perf_counter();self.trigger=trigger
        self.thread=threading.Thread(target=self._entry,name='p11-native-startup',daemon=True);self.thread.start()
    def _entry(self):
        try:self.context.run(self._run)
        except NativeSetupCancelled:
            checkpoint('NATIVE_SETUP_CANCELLED',owned_subprocess_retirement_requested=True,hardware_access=False)
        except BaseException as exc:
            self.error=exc
            checkpoint('NATIVE_SETUP_FAILED',durable=True,exception_type=type(exc).__name__,exception=str(exc),hardware_access=False)
        finally:self.finished_at=time.perf_counter();self.done.set()
    def _run(self):
        from display import prepare_io as prepare_io; from display import _BUILD_INFO as _BUILD_INFO
        began=time.perf_counter();checkpoint('NATIVE_SETUP_BEGIN',background=True,
            raw_preview_already_submitted=self.trigger=='raw_preview',trigger=self.trigger)
        io_begin=time.perf_counter();library=prepare_io(cancel=self.cancel)
        checkpoint('IO_LOAD_END',abi=6601,path=str(library._name))
        checkpoint('P1_IO_READY',abi=6601,path=str(library._name),setup_s=time.perf_counter()-io_begin,
            neon=bool(library.p11_v66_caps()&1),outside_frame_measurement=True,cpu_only=True,hardware_modified=False)
        checkpoint('PS_PREPARE_READY',plan_abi=int(library.p11_v70_plan_abi()),light_results=True,
            geometry_batch=bool(library.p11_v70_geometry_available()),build=dict(_BUILD_INFO),
            outside_frame_measurement=True)
        self.status=prepare_native__v31_native(required=False,cancel=self.cancel)
        self.status['V74_detector']=prepare_native__v87_v74_native(required=False,cancel=self.cancel)
        checkpoint('V87_V74_NATIVE_READY',**self.status['V74_detector'])
        from geometry import prepare_color_runtime as prepare_color_runtime
        self.status['color_setup']=prepare_color_runtime(self.cancel)
        addon=prepare_transactions(cancel=self.cancel)
        self.status['V91_transactions']=dict(available=addon is not None,abi=9101,
            original_four_libraries_unchanged=True,small_addon_only=True)
        checkpoint('NATIVE_SETUP_END',elapsed_s=time.perf_counter()-began,backend=self.status.get('backend'),
            already_loaded=self.status.get('already_loaded',False))
    def result(self):
        if not self.done.is_set():raise RuntimeError('Native setup has not completed')
        if self.error is not None:raise RuntimeError('Native setup failed: '+type(self.error).__name__+': '+str(self.error)) from self.error
        if self.status is None:raise NativeSetupCancelled('Native setup retired before producing a status')
        return dict(self.status)
    def close(self):
        self.cancel.set()
        if self.thread is not None:
            self.thread.join(5.)
            if self.thread.is_alive():raise TimeoutError('Native setup has not retired; CPU worker retained')


def startup_meta(context,phase,worker=None):
    ticket=context.ticket if context is not None else None
    return dict(ui_startup_phase=phase,placement_required=bool(ticket is not None and ticket.placement_required),
        placement_confirmed=bool(ticket is not None and ticket.placement.is_set()),
        native_setup_elapsed_s=worker.elapsed_s if worker is not None else 0.)


def wait_native_with_preview(worker,camera,display,check,generation,deadline=None,context=None):
    """Single producer; release camera leases after display owns its raw copy."""
    began=time.perf_counter();last_frame=began;next_offer=0.;offered=0;started=worker.thread is not None
    if context is not None:context.set_phase('preparing')
    if started:checkpoint('NATIVE_SETUP_REUSED',done=worker.done.is_set(),elapsed_s=worker.elapsed_s,hardware_access=False)
    with display.condition:initial_panels=display.panels_submitted
    while True:
        check();now=time.perf_counter()
        if deadline is not None and now>=deadline:raise TimeoutError('Native startup reached session deadline')
        if display.error is not None:raise display.error
        if started and worker.done.is_set():return worker.result()
        if not started:
            with display.condition:
                submitted=display.panels_submitted>initial_panels and display.ui_generation==generation()
            if submitted:
                checkpoint('RAW_PREVIEW_FIRST_SUBMITTED',elapsed_s=now-began,preview_offers=offered,
                    generation=generation(),physical_panel_scan_measured=False)
                worker.start();started=True
            elif now-began>3. and offered:
                raise TimeoutError('Raw camera frames were offered but HDMI submission was not confirmed')
        try:frame=camera.take(.1)
        except TimeoutError:
            if time.perf_counter()-last_frame>3.:raise TimeoutError('No valid camera frame during visible native startup')
            continue
        try:
            now=time.perf_counter();last_frame=now
            if now>=next_offer:
                display.offer(None,dict(index=-2,camera_sequence=int(frame.sequence),state='INITIALIZING',corners=(),
                    color_mode=int(camera.color_mode),verified_at=0.,capture_ready_at=float(frame.ready),
                    correction_fps=0.,ui_generation=generation(),**startup_meta(context,'preparing',worker)),frame.image)
                offered+=1;next_offer=now+.125
        finally:frame.release()


def wait_for_placement(camera,display,check,generation,deadline=None,context=None):
    """Legacy call name retained; automatic current-frame admission never waits for touch."""
    check()
    if context is not None:context.set_phase('acquiring')
    checkpoint('AUTOMATIC_ADMISSION_BEGIN',generation=generation(),confirmation_required=False,
        skipped_validation=False,strict_current_admission=True)


# ======================================================================
# ===== [13/28] v80_cache =====
# ======================================================================


"""Release-independent CPU helper cache; no device, frame or model data."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LOCK__v80_cache=threading.RLock()
# Filled by the release assembler using reviewed baseline loader bytes.
LEGACY_LOADER_SHA256 = {'tracker': ['3b344449de4da614f3b55898f4296a4ffd675e8d22d7c1064164085bc79e20c0', 'df64ea52980a42620aad7759d95ce1ab1e6b603515acda00ef247d09ec3f350e', 'f40711f9ae073c06c7b177831f5ce4c316ef877cee0fc616ab9e3044d38ec199', 'f2578e5250515d7063940679b1f9e3f5bfb310c54b5b7c6eb503097c5a0f8bd8', '522dff375efb56848524a07d45a724bc1a18dd3072592c213072a6487ce02dbf'], 'io': ['9e19f967f922647c305ec5e8572008fb878e78ef952491d5e5e774c4f9d4c2c0', '12f4566a4639bab9b6eb985b5846561c057c33fe20d81e4bd88919f7c0671d17'], 'capture': ['982f5f783d310534c4b605758b721a3c01023e08ee0698a8ee16d2a75d87ad36', 'b88ef3d7516ec72727c680c56e255eb08276f5ddde52ebab5a4eb313f524e29e', '6343d8277577dc5b5893cdc1937991632460d1b6761e5f30d061c1a61532060e']}  # REVIEWED_V74_CACHE_LOADER
_FAMILIES={'tracker':('v31_native.py','p11_v31_abi',3107),
    'io':('v64_io.py','p11_v64_abi',6601),'capture':('v31_camera.py','p11_camera_abi',3102),
    'transaction':('v91_native.py','p11_v91_abi',9101)}


def shared_root():
    configured=os.environ.get('P11_NATIVE_CACHE_ROOT')
    return Path(configured).expanduser().resolve()/'v2' if configured else Path.home()/'.cache'/'p11_native'/'v2'


def _hash(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def _spec(target,source,family,flags):
    source=Path(source);target=Path(target)
    if family not in _FAMILIES:raise ValueError('Unknown CPU cache family')
    item=dict(schema=1,family=family,source_sha256=_hash(source),architecture=platform.machine(),
        target_name=target.name,compiler_flags=list(flags),abi=_FAMILIES[family][2])
    key=hashlib.sha256(json.dumps(item,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return item,key


def _probe(path,family):
    with path.open('rb') as stream:header=stream.read(20)
    machine={'armv7l':40,'aarch64':183,'x86_64':62}.get(platform.machine())
    if len(header)<20 or header[:4]!=b'\x7fELF' or header[5]!=1:
        raise ValueError('Cache artifact is not a supported little-endian ELF')
    if machine is not None and struct.unpack_from('<H',header,18)[0]!=machine:
        raise ValueError('Cache ELF architecture mismatch')
    if not 1024<=path.stat().st_size<=64*1024*1024:raise ValueError('Cache ELF size outside bounds')
    lib=ctypes.CDLL(str(path.resolve()))
    function=getattr(lib,_FAMILIES[family][1]);function.argtypes=[];function.restype=ctypes.c_int
    if function()!=_FAMILIES[family][2]:raise ValueError('CPU helper ABI mismatch')


def _copy_atomic(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name(target.name+'.'+str(os.getpid())+'.'+str(threading.get_ident())+'.'+str(time.time_ns())+'.tmp')
    try:
        shutil.copyfile(source,temporary)
        if _hash(source)!=_hash(temporary):raise ValueError('CPU cache copy hash mismatch')
        os.replace(str(temporary),str(target))
    finally:
        if temporary.exists():temporary.unlink()


def _write_receipt(path,value):
    temporary=path.with_name(path.name+'.'+str(os.getpid())+'.'+str(time.time_ns())+'.tmp')
    try:
        temporary.write_text(json.dumps(value,sort_keys=True)+'\n',encoding='utf-8')
        os.replace(str(temporary),str(path))
    finally:
        if temporary.exists():temporary.unlink()


def restore(target,source,family,flags,cancel=None,source_alias=None):
    """Import a known recipe and full source match; reject bad cache, then build normally."""
    if source_alias not in (None,'v31_native.cpp'):raise ValueError('Unsupported historical cache source alias')
    source_leaf=source_alias or Path(source).name
    target=Path(target);source=Path(source);begin=time.perf_counter()
    if platform.system()!='Linux':return False
    item,key=_spec(target,source,family,flags);root=target.parent.resolve()
    shared=shared_root();artifact=shared/(key+'.so');receipt=shared/(key+'.json')
    with _LOCK__v80_cache:
        check_cancel(cancel)
        from core import check_local as check_local; from core import remember_local as remember_local; from core import restore_pack as restore_pack
        if target.is_file():
            if check_local(target,item):
                try:_probe(target,family)
                except (OSError,ValueError,AttributeError,TypeError) as exc:
                    checkpoint('CPU_NATIVE_LOCAL_REJECTED',family=family,exception=str(exc))
                else:
                    checkpoint('CPU_NATIVE_LOCAL_VERIFIED',family=family,path=str(target),
                        source_sha256=item['source_sha256'],artifact_sha256=_hash(target),abi=item['abi'])
                    return False
            # Preserve unregistered/corrupt bytes for inspection, never load them.
            quarantine=target.with_name(target.name+'.unverified.'+str(time.time_ns()))
            os.replace(str(target),str(quarantine))
            checkpoint('CPU_NATIVE_LOCAL_QUARANTINED',family=family,path=str(quarantine),
                reason='missing or mismatched source/recipe/environment/binary receipt')
        if restore_pack(target,item,cancel):return True
        if artifact.is_file() and receipt.is_file():
            try:
                meta=json.loads(receipt.read_text(encoding='utf-8'))
                from core import environment as environment
                if (meta.get('spec')!=item or meta.get('environment')!=environment()
                    or meta.get('artifact_sha256')!=_hash(artifact)):raise ValueError('Cache receipt/environment mismatch')
                _probe(artifact,family);check_cancel(cancel);_copy_atomic(artifact,target);remember_local(target,item)
                checkpoint('CPU_NATIVE_CACHE_HIT',family=family,source='shared',path=str(target),elapsed_s=time.perf_counter()-begin)
                return True
            except (OSError,ValueError,AttributeError,TypeError) as exc:
                checkpoint('CPU_NATIVE_CACHE_REJECTED',family=family,source='shared',exception=str(exc))
        try:
            siblings=sorted((p for p in root.parent.iterdir() if p.name.startswith('p11_rgb_v') and p.is_dir()),
                key=lambda p:p.stat().st_mtime,reverse=True)[:128]
        except OSError:siblings=[]
        loader=_FAMILIES[family][0];allowed=set(LEGACY_LOADER_SHA256.get(family,()))
        for folder in siblings:
            check_cancel(cancel)
            if folder.resolve()==root or folder.resolve().parent!=root.parent:continue
            candidate=folder/target.name
            if not candidate.is_file():continue
            try:
                # Portable receipt binds actual source, recipe, environment and
                # binary SHA; also covers the independent V74 helper in V87+.
                if check_local(candidate,item):
                    _probe(candidate,family);check_cancel(cancel);_copy_atomic(candidate,target);remember_local(target,item)
                    checkpoint('CPU_NATIVE_CACHE_HIT',family=family,source='verified_previous_receipt',
                        previous_folder=folder.name,path=str(target),elapsed_s=time.perf_counter()-begin)
                    return True
                if not allowed or _hash(folder/loader) not in allowed:continue
                if _hash(folder/source_leaf)!=item['source_sha256']:continue
                manifest=json.loads((folder/'release_manifest.json').read_text(encoding='utf-8'))
                if manifest.get('sha256',{}).get(source_leaf)!=item['source_sha256']:continue
                # Probe only the declared ABI. No camera/VDMA/MMIO call is made.
                _probe(candidate,family);check_cancel(cancel);_copy_atomic(candidate,target);remember_local(target,item)
                checkpoint('CPU_NATIVE_CACHE_HIT',family=family,source='reviewed_previous_release',
                    previous_folder=folder.name,path=str(target),elapsed_s=time.perf_counter()-begin)
                return True
            except (OSError,ValueError,AttributeError,TypeError) as exc:
                checkpoint('CPU_NATIVE_CACHE_REJECTED',family=family,source=folder.name,exception=str(exc))
        checkpoint('CPU_NATIVE_CACHE_MISS',family=family,elapsed_s=time.perf_counter()-begin,
            exact_source_and_recipe_required=True)
        return False


def remember(target,source,family,flags):
    """Best-effort atomic persistence after the caller has bound/checked its ABI."""
    target=Path(target);source=Path(source)
    if platform.system()!='Linux' or not target.is_file():return
    try:
        item,key=_spec(target,source,family,flags)
        from core import remember_local as remember_local
        remember_local(target,item)
        shared=shared_root()
        artifact=shared/(key+'.so');receipt=shared/(key+'.json');digest=_hash(target)
        with _LOCK__v80_cache:
            if artifact.is_file() and receipt.is_file():
                try:
                    meta=json.loads(receipt.read_text(encoding='utf-8'))
                    from core import environment as environment
                    if meta.get('spec')==item and meta.get('environment')==environment() and meta.get('artifact_sha256')==digest and _hash(artifact)==digest:return
                except (OSError,ValueError,TypeError):pass
            _copy_atomic(target,artifact)
            from core import environment as environment
            _write_receipt(receipt,dict(spec=item,environment=environment(),artifact_sha256=digest,created_by_release=RELEASE_ID))
        checkpoint('CPU_NATIVE_CACHE_STORED',family=family,path=str(artifact),bytes=target.stat().st_size)
    except (OSError,ValueError,TypeError) as exc:
        checkpoint('CPU_NATIVE_CACHE_STORE_SKIPPED',family=family,exception=str(exc),local_library_retained=True)


# ======================================================================
# ===== [14/28] v81_evidence =====
# ======================================================================


"""Failure-only current exterior grades and retry routing; CPU metadata only."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def flow_failure_class(timing,reason):
    fit=timing.get('motion_fit') or {}
    complete=('forward_backward_flow_s' in timing and fit.get('good_features',0)>=4
        and fit.get('inlier_fraction',0.)>=.85 and fit.get('fb_median',1e30)<.7)
    if not complete:return 'motion_unproved'
    if 'candidate_touches_image_border_or_is_clipped' in str(reason):return 'current_geometry_clipped'
    if (timing.get('failure_class')=='current_exterior_mismatch'
        or 'four' in str(reason) or '四' in str(reason) or 'source64' in str(reason)):
        return 'current_exterior_unproved'
    return 'motion_unproved'


def _reports(evidence,n):
    reports=evidence.get('edges',());supports=evidence.get('edge_support',())
    if len(reports)!=4 or len(supports)!=4:return None
    if (not evidence.get('valid') or evidence.get('supported_edges')!=4
        or evidence.get('refined_corners')!=4 or evidence.get('profiles_per_edge')!=n
        or evidence.get('deadline_hit') or not evidence.get('color_vector_proof')):return None
    counts=[];coverage=[]
    for report,support in zip(reports,supports):
        retained=report.get('retained',0);span=report.get('coverage',0.)
        if (report.get('profiles')!=n or not report.get('accepted')
            or not 0<retained<=n or not math.isfinite(float(support))
            or abs(float(support)-retained/n)>1e-5 or not math.isfinite(float(span)) or span<.62):return None
        counts.append(int(retained));coverage.append(float(span))
    return counts,coverage


def joint_color_grade(first,second,agreement,source_key,stable_fb=False):
    """Two actual current sample grids; no missing edge or old-H substitution.

    A tight joint-sample grade can resolve discretization differences at new
    admission. A single weaker primary side additionally requires complete
    same-target FB plus very strong independent24 and tighter line agreement.
    """
    if (not agreement.get('source64_provenance_verified') or not agreement.get('independent_sampling_verified')
        or first.get('current_source_key')!=source_key or not first.get('same_frame_source')):return None
    a=_reports(first,24);b=_reports(second,64)
    if a is None or b is None:return None
    n24,n64=a[0],b[0]
    rms=agreement.get('max_rms',1e30);normal=agreement.get('line_normal_difference',1e30)
    corner=agreement.get('corner_difference',1e30);limit=agreement.get('normal_limit',0.)
    quantized=(min(n64)>=51 and min(n24)>=21 and rms<=.50
        and normal<=min(.75,limit) and corner<=1.)
    tight=rms<=.35 and normal<=min(.50,limit) and corner<=.80
    # >=21/24 and >=48/64, with >=71/88 paired retained samples on EVERY
    # physical side. Both grids retain broad spatial coverage and fitted lines.
    joint=tight and all(x>=21 and y>=48 and x+y>=71 for x,y in zip(n24,n64))
    stable=(stable_fb and min(n24)>=21 and sum(n24)>=91
        and min(n64)>=40 and sum(n64)>=212
        and sum(y<48 for y in n64)<=1 and sum(y>=55 for y in n64)>=3
        and agreement.get('max_rms',1e30)<=.30
        and agreement.get('line_normal_difference',1e30)<=.40
        and agreement.get('corner_difference',1e30)<=.65)
    if not quantized and not joint and not stable:return None
    return dict(verified=True,admission_grade='current_color_count_quantization' if quantized else
        'joint_current_color_samples' if joint else 'stable_FB_single_sparse_color_edge',
        admission_policy='current_source64_and_independent24_spatial_evidence',
        joint_sample_grade=True,stable_FB_support_tolerance=bool(stable and not joint and not quantized),
        per_edge_retained24=n24,per_edge_retained64=n64,
        per_edge_joint_support=[(x+y)/88. for x,y in zip(n24,n64)],
        minimum_coverage=min(a[1]+b[1]),complete_current_FB_required=bool(stable and not joint and not quantized),
        all_four_current_fitted_lines_required=True,zero_support_edge_allowed=False,
        original_support_values_preserved=True,global_threshold_unchanged=True)


def low_contrast_retry(image,quad,half,failed,deadline=None):
    """One small-band retry only after three well-fitted source color sides.

    Harmonize original color contrast12 with the existing tracking contrast8;
    never whiten the image, expand the candidate or accept a missing fourth edge.
    """
    reports=failed.get('edges',())
    if (not failed.get('color_vector_proof') or failed.get('deadline_hit') or len(reports)!=4
        or sum(bool(r.get('accepted')) and r.get('retained',0)>=48
            and r.get('coverage',0.)>=.62 and r.get('tls_rms',1e30)<=1. for r in reports)<3):return None
    began=time.perf_counter();cpu=time.thread_time()
    end=min(began+.10,float(deadline)) if deadline is not None else began+.10
    if end-began<.025:return None
    from geometry import refine_boundary as refine_boundary
    result,evidence=refine_boundary(image,quad,min(8.,float(half)),profiles=64,
        max_rms=1.,minimum_contrast=8.,deadline=end)
    detail=dict(attempted=True,minimum_contrast=8.,previous_minimum_contrast=12.,
        half_source_pixels=min(8.,float(half)),wall_s=time.perf_counter()-began,
        thread_cpu_s=time.thread_time()-cpu,wall_guard_s=end-began,
        source_shape=list(image.shape),four_edges_still_required=True,
        full_image_enhancement=False,full_image_copy=False)
    evidence=dict(evidence,low_contrast_band_retry=detail)
    return result,evidence,detail


# ======================================================================
# ===== [15/28] v83_recovery =====
# ======================================================================


"""Failure-only bounded proposal scheduling; never stores H or a proof receipt."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ACTIVE=ContextVar('p11_v83_candidate_retry',default=None)


def scene_probe(image):
    h,w=image.shape[:2];sy=max(1,h//12);sx=max(2,(w//16)//2*2)
    y=image[::sy,::sx] if image.ndim==2 else image[::sy,::sx,0]
    if image.ndim==3 and image.shape[2]==2:
        u=image[::sy,::sx,1];v=image[::sy,1::sx,1]
        cols=min(y.shape[1],u.shape[1],v.shape[1])
        return np.stack((y[:,:cols],u[:,:cols],v[:,:cols])).astype(np.float32)
    return np.asarray(y,np.float32)[None].copy()


def scene_changed(a,b):
    if a is None or b is None or a.shape!=b.shape:return True
    d=np.abs(a-b)
    # Include local changes, not only a frame-wide median dominated by the desk.
    return bool(float(np.mean(d))>7. or float(np.percentile(d,95))>24.)


def failure_class(detail):
    if not isinstance(detail,dict):return 'unclassified'
    reason=str(detail.get('reason',''))
    if 'budget' in reason or 'deadline' in reason:return 'compute_budget'
    agreement=detail.get('agreement') or detail.get('source_line_agreement') or {}
    if 'budget' in str(agreement.get('reason','')) or agreement.get('deadline_hit'):return 'compute_budget'
    e=detail.get('edge_refinement') or detail.get('edge_evidence') or {}
    reports=e.get('edges',())
    if any(not x.get('accepted') and x.get('highlight_fraction',0.)>.25 for x in reports):
        return 'possible_highlight_edge_loss'
    if 'clipped' in reason:return 'clipped_geometry'
    if 'all_four_original' in reason:
        failed=[r for r in reports if not r.get('accepted')]
        if any(r.get('supported',0)==0 for r in failed):return 'no_current_edge_samples_in_search_band'
        if any(r.get('retained',0)>0 and r.get('coverage',0)<.60 for r in failed):return 'insufficient_current_edge_span'
        if any(r.get('supported',0)>0 and r.get('retained',0)==0 for r in failed):return 'incoherent_current_candidate_band'
        if any(0<r.get('retained',0)<.60*r.get('profiles',64) for r in failed):return 'weak_spatial_support'
        return 'current_source_line_fit_rejected'
    if agreement.get('min_support',1.)==0:return 'missing_independent_edge'
    if (agreement.get('line_normal_difference',0.)>agreement.get('normal_limit',float('inf'))
            or 'layer' in reason or 'left_locked' in str(agreement.get('reason',''))):return 'neighbour_line_disagreement'
    if agreement.get('min_support',1.)<.8:return 'weak_spatial_support'
    return 'unproved_current_exterior'


class CandidateRetry:
    """Bounded negative hints, <=1.2s; scene/motion can invalidate immediately.

    These records can only suppress repeated computation. They never accept a
    candidate, renew a hold timer or bypass current independent edge sampling.
    """
    def __init__(self):
        self.probe=None;self.entries=[];self.failures=0;self.skipped=0;self.resets=0;self.classes={}
        self.batch=[];self.batch_started=0.;self.batch_skipped=0;self.cycle_wall_s=.25
        self.expired_rechecks=0
    def begin(self,image):
        self.batch=[];self.batch_started=time.perf_counter()
        probe=scene_probe(image)
        if scene_changed(probe,self.probe):
            self.entries.clear();self.failures=0;self.probe=probe;self.resets+=1
        return probe
    def _entry(self,quad):
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return None
        center=q.mean(axis=0)
        for entry in reversed(self.entries):
            delta=center-entry['center']
            if float(delta@delta)>36.:continue
            d=entry['cycles']-q
            if float(np.min(np.max(np.sum(d*d,axis=2),axis=1)))<=16.:return entry
        return None
    def allow(self,quad):
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return True
        for old in self.batch:
            d=old-q
            if float(np.min(np.max(np.sum(d*d,axis=2),axis=1)))<=4.:
                self.batch_skipped+=1;return False
        self.batch.append(np.stack([np.roll(v,k,axis=0) for v in (q,q[::-1]) for k in range(4)]))
        if len(self.batch)>32:self.batch.pop(0)
        entry=self._entry(quad)
        allowed=entry is None or time.perf_counter()>=entry['until']
        if not allowed:self.skipped+=1
        elif entry is not None:self.expired_rechecks+=1
        return allowed
    def reject(self,quad,detail):
        kind=failure_class(detail);self.classes[kind]=self.classes.get(kind,0)+1
        # A compute deadline is not evidence that this boundary is wrong.
        if kind=='compute_budget':return
        entry=self._entry(quad);count=1 if entry is None else entry['count']+1
        # A fixed150ms hint expired before the next ~0.8-1s search reached
        # admission. Cover one observed cycle, then force fresh remeasurement.
        elapsed=max(0.,time.perf_counter()-self.batch_started)
        delay=min(1.20,max(.35,self.cycle_wall_s+.20,elapsed+.20)*(1.+.20*min(count-1,2)))
        q=np.asarray(quad,np.float32).copy()
        value=dict(quad=q,center=q.mean(axis=0),cycles=np.stack([np.roll(v,k,axis=0) for v in (q,q[::-1]) for k in range(4)]),
            count=count,kind=kind,until=time.perf_counter()+delay)
        if entry is not None:self.entries=[x for x in self.entries if x is not entry]
        self.entries.append(value)
        if len(self.entries)>24:self.entries.pop(0)
    def completed(self,valid,wall_s=None):
        elapsed=max(0.,time.perf_counter()-self.batch_started) if wall_s is None else max(0.,float(wall_s))
        self.cycle_wall_s=.5*self.cycle_wall_s+.5*min(1.,elapsed)
        self.failures=0 if valid else min(4,self.failures+1)
        if valid:self.entries.clear()
    def delay(self):return .10 if not self.failures else min(.60,.15*2**min(self.failures-1,2))
    def summary(self):
        return dict(negative_hints=len(self.entries),repeated_candidates_skipped=self.skipped,
            same_batch_candidates_skipped=self.batch_skipped,expired_candidate_rechecks=self.expired_rechecks,
            scene_resets=self.resets,failure_classes=dict(self.classes),maximum_negative_hint_s=1.20,
            observed_cycle_wall_s=self.cycle_wall_s,cached_current_proof=False,old_H_lifetime_changed=False)


@contextmanager
def candidate_retry_scope(policy):
    token=_ACTIVE.set(policy)
    try:yield
    finally:_ACTIVE.reset(token)


def active_retry():return _ACTIVE.get()


# ======================================================================
# ===== [16/28] v86_policy =====
# ======================================================================


"""Per-run CPU policies; inherited by copied worker contexts, never global mutable options."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DEFAULTS=dict(auto_tracking_mode='strict',tracking_audit_s=1.,outer_candidate_competition=False,
    recovery_local_first=False,detection_contrast_fallback=False)
_POLICY=ContextVar('p11_v86_policy',default=None)


def policy():return dict(DEFAULTS if _POLICY.get() is None else _POLICY.get())


def policy_run(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        options=policy()
        for key in DEFAULTS:
            if key in kwargs:options[key]=kwargs.pop(key)
        if options['auto_tracking_mode'] not in ('motion','strict'):
            raise ValueError('auto_tracking_mode must be motion or strict')
        if options['auto_tracking_mode']=='motion':
            from core import checkpoint as checkpoint
            checkpoint('V89_LEGACY_AUTO_OPTION',requested='motion',effective='strict',
                automatic_path='V74_current_edges_conditional_complete_FB',manual_requires_calibration=True)
        options['auto_tracking_mode']='strict'
        for key in ('outer_candidate_competition','recovery_local_first','detection_contrast_fallback'):
            if not isinstance(options[key],bool):raise ValueError(key+' must be bool')
        interval=options['tracking_audit_s']
        if isinstance(interval,bool) or not math.isfinite(float(interval)) or not .5<=float(interval)<=3.:
            raise ValueError('tracking_audit_s must be0.5..3.0 seconds')
        options.update(outer_candidate_competition=False,recovery_local_first=False,detection_contrast_fallback=False)
        options['tracking_audit_s']=float(interval);token=_POLICY.set(options)
        try:return function(*args,**kwargs)
        finally:_POLICY.reset(token)
    return wrapped


# ======================================================================
# ===== [17/28] v86_tracking =====
# ======================================================================


"""Compatibility entry: all automatic work uses the complete original V74 frontend.

Manual motion lives only in v82_manual and requires explicit UI calibration.
The former automatic MotionFrontend/audit/reentry machinery is not imported.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def create_frontend(*args,**kwargs):
    from display import Frontend as Frontend
    # Two trailing historical book-rescue options are ignored by exact V74.
    # Both initial auto acquisition and recovery after manual loss use this.
    return Frontend(*args[:13],**kwargs)


# ======================================================================
# ===== [18/28] v88_recovery =====
# ======================================================================


"""Latest owned-frame recovery using the unchanged V74 admission and native kernels."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class RecoveryCancelled(Exception):pass


class SliceBudget(CpuRecoveryBudget):
    """Cooperative CPU slice; continue full-search candidate ordinal across requests."""
    def __init__(self,worker,milliseconds,candidates,skip=None):
        super().__init__(milliseconds,candidates,wall_max_s=1.2)
        self.worker=worker;self.skip=dict(skip or {});self.visited={};self.log_detail=False
    def check(self,stage,finish_gate=False):
        with self.worker.condition:stopped=self.worker.stop
        if stopped:raise RecoveryCancelled()
        super().check(stage,finish_gate)
    def claim(self,label,coarse):
        position=self.visited.get(label,0)+1;self.visited[label]=position
        if position<=self.skip.get(label,0):
            self.check('v88_candidate_cursor_skip')
            # V74 try_admit catches a candidate ValueError and continues the
            # original stream. No previous evidence or H is accepted here.
            raise ValueError('V88 earlier candidate ordinal already attempted in this scene cycle')
        super().claim(label,coarse)


def detect_slice(worker,frame,observer,hint=None,cursor=None):
    worker.last_budget=None
    gray,scale=observer.get(frame.image)
    budget=SliceBudget(worker,worker.budget_ms,1 if hint is not None else 2,None if hint is not None else cursor)
    observation=dict(gray=gray,scale=scale,source_shape=frame.image.shape)
    seeds=() if hint is None else (dict(detector='multicolor_exterior',coarse_corners=np.asarray(hint).tolist()),)
    try:
        with recovery_detection_scope(budget,observation),recovery_candidate_scope(seeds,hint is not None):
            return detect_refined(frame.image,worker.detection_limit,True,prefer_mask=True,
                tracking_limit=worker.tracking_limit),budget
    finally:worker.last_budget=budget


def freshen_source(worker,source,detection):
    """Only old initial video sources get a latest-frame V74 hint reproof.

    Caller keeps ownership of source on failure. A returned replacement is
    separately owned; caller releases the original after successful transfer.
    """
    if time.perf_counter()-source.ready<=.55:return source,detection,dict(refreshed=False)
    observer=GrayObserver__v87_v74_tracking(worker.tracking_limit);candidate=source;current=detection
    original_sequence=int(source.sequence)
    # Initial V74 search stays unrestricted. Only its old result is transported;
    # the strict current source64/independent24 admission is unchanged.
    worker.budget_ms=420.;worker.last_budget=None
    try:
        for _ in range(2):
            latest=worker._take_owned(3.)
            try:current,_=detect_slice(worker,latest,observer,current[0])
            except BaseException:latest.release();raise
            if candidate is not source:candidate.release()
            candidate=latest
            if time.perf_counter()-candidate.ready<=.55:
                return candidate,current,dict(refreshed=True,original_sequence=original_sequence,
                    handoff_sequence=int(candidate.sequence),same_current_V74_admission=True)
        raise ValueError('V88 current handoff still too old; keep live preview and retry')
    except BaseException:
        if candidate is not source:candidate.release()
        raise


class V74Reacquire(LiveAcquire):
    """One replaceable ordinary-RAM snapshot; no camera leases or PL in worker."""
    def __init__(self,detection_limit,tracking_limit,factory=None,quad=None,budget_ms=420.):
        self.hint=None if quad is None else np.asarray(quad,np.float32).copy()
        self.budget_ms=float(budget_ms);self.last_budget=None;self.unpublished=None
        super().__init__(detection_limit,tracking_limit,factory)
    def _run(self):
        observer=GrayObserver__v87_v74_tracking(self.tracking_limit);local_tries=0;cursor={};probe=None;next_log=0.
        while True:
            frame=self._next()
            if frame is None:return
            built=None;started=time.perf_counter();cpu=time.thread_time();phase='local';transferred=False
            try:
                raw=frame.image
                scene=raw[::max(1,raw.shape[0]//12),::max(2,raw.shape[1]//16//2*2),0].astype(np.float32)
                scene-=float(scene.mean())
                changed=probe is not None and (probe.shape!=scene.shape or float(np.median(np.abs(scene-probe)))>12.)
                if changed:cursor={};local_tries=2
                probe=scene
                phase='local' if self.hint is not None and local_tries<2 else 'full_slice'
                if phase=='local':local_tries+=1
                detection,budget=detect_slice(self,frame,observer,self.hint if phase=='local' else None,cursor)
                self.hint=np.asarray(detection[0],np.float32).copy()
                with self.condition:
                    self.candidate=tuple(map(tuple,self.hint.tolist()));self.candidate_ready=float(frame.ready)
                    if self.stop:raise RecoveryCancelled()
                if time.perf_counter()-frame.ready>.55:
                    local_tries=0
                    raise ValueError('V88 recovered source needs latest-frame local continuation')
                built=self.factory(frame,detection) if self.factory else None
                self.unpublished=built
                if time.perf_counter()-frame.ready>.70:
                    local_tries=0
                    raise ValueError('V88 recovery initialization exceeded fresh handoff age')
                report=dict(attempts=self.attempts,rejections=self.rejections,source_sequence=int(frame.sequence),
                    source_age_s=max(0.,time.perf_counter()-frame.ready),owned_source=True,
                    current_revalidated=True,initial_source_verified=True,recovery_phase=phase,
                    v88_local_recovery=phase=='local',candidate_cursor=dict(cursor),
                    admission_policy='unchanged V74 source64 plus independent24',
                    current_frame_validation_before_output='complete_FB_or_V74_current_exterior',
                    elapsed_worker_cpu_s=self.worker_cpu_s+time.thread_time()-cpu)
                with self.condition:
                    if self.stop:raise RecoveryCancelled()
                    self.result=(frame,detection,built,report);self.latest=None;self.stop=True
                    self.unpublished=None;self.condition.notify_all();transferred=True
                return
            except RecoveryCancelled:return
            except (ValueError,cv2.error) as exc:
                self.rejections+=1
                budget=self.last_budget
                if phase=='full_slice':
                    visited={} if budget is None else dict(budget.visited)
                    advanced=any(v>cursor.get(k,0) for k,v in visited.items())
                    progress=dict(cursor)
                    for label,position in visited.items():progress[label]=max(position,progress.get(label,0))
                    cursor=progress if advanced and sum(progress.values())<12 else {}
                    local_tries=0
                if time.perf_counter()>=next_log:
                    checkpoint('V88_RECOVERY_SLICE',phase=phase,reason=str(exc),attempts=self.attempts,
                        rejections=self.rejections,candidate_cursor=cursor,live_preview_continues=True,
                        budget=None if budget is None else compact_recovery_summary(budget.summary()),
                        hard_preemption=False,hardware_access=False)
                    next_log=time.perf_counter()+2.
            finally:
                self.attempts+=1
                if not transferred:
                    # Preserve a frontend on this worker if its close raises;
                    # outer cleanup must retain the worker until retirement.
                    if built is not None:built.close();self.unpublished=None
                    frame.release()
                self.worker_cpu_s+=time.thread_time()-cpu;self.worker_wall_s+=time.perf_counter()-started
    def close(self):
        super().close()
        if self.unpublished is not None:self.unpublished.close();self.unpublished=None


# ======================================================================
# ===== [19/28] v87_acquire =====
# ======================================================================


"""V74 stabilization + unrestricted original detector admission, inside a visible CPU worker."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class AcquisitionStopped(Exception):pass


class V74Acquire(LiveAcquire):
    """UI/lifetime bridge only. No420ms candidate budget, negative hints or second admission."""
    def __init__(self,detection_limit,tracking_limit,factory=None,quad=None,budget_ms=420.,*,recovery=False,target_selection=None,target_report=None,target_progress=None,phase_report=None):
        self.is_recovery=bool(recovery or quad is not None)
        self.unpublished=None
        self.target_selection=target_selection;self.target_report=target_report
        self.target_progress=target_progress
        self.phase_report=phase_report
        super().__init__(detection_limit,tracking_limit,factory)
    def _take_owned(self,timeout):
        deadline=time.perf_counter()+float(timeout)
        with self.condition:
            while self.latest is None and not self.stop:
                remaining=deadline-time.perf_counter()
                if remaining<=0:raise TimeoutError('V74 acquisition: no owned camera snapshot')
                self.condition.wait(min(.1,remaining))
            if self.stop:raise AcquisitionStopped()
            frame=self.latest;self.latest=None;return frame
    def _check_target(self):
        with self.condition:
            if self.stop:raise AcquisitionStopped()
    def _run(self):
        owner=self
        class CameraProxy:
            @property
            def color_mode(self):
                from core import color_mode as color_mode
                return color_mode()
            def take(self,timeout):return owner._take_owned(timeout)
        proxy=CameraProxy();next_log=0.
        target=TapDetector(self.target_selection,self.detection_limit,self.tracking_limit,self.target_report,self._check_target) if self.target_selection is not None else None
        while True:
            first=selected=None;built=None;began=time.perf_counter();cpu=time.thread_time()
            try:
                # Recovery already has a running exposure stream. Initial entry
                # retains V74's exact12/150/4 stability rule and6s guard.
                if self.phase_report is not None:self.phase_report('STABILIZING')
                if self.is_recovery:first=proxy.take(3.);stability=dict(policy='already_running_camera')
                else:first,stability=stabilize_camera(proxy,12,150,4,6.)
                if self.phase_report is not None:self.phase_report('SEARCHING')
                def preview(frame,attempt):
                    with self.condition:
                        if self.stop:raise AcquisitionStopped()
                seed=first;first=None  # Ownership transfers even when cancelled.
                with detection_cancel_scope(self._check_target):
                    selected,_,detection,admission=admit_initial_frame(proxy,seed,
                        lambda raw,bgr:(target(raw,bgr) if target is not None else detect_refined(raw,self.detection_limit,True,prefer_mask=True,
                            color_reference=bgr,tracking_limit=self.tracking_limit)),
                        attempts=6,timeout_s=12.,save_failed_frame=False,candidate_preview=preview)
                self._check_target()
                if self.phase_report is not None:self.phase_report('CANDIDATE')
                self.attempts+=int(admission.get('attempts',1));self.rejections+=int(admission.get('failed_attempts',0))
                with self.condition:
                    self.candidate=tuple(map(tuple,np.asarray(detection[0]).tolist()));self.candidate_ready=float(selected.ready)
                    stopped=self.stop
                if stopped:raise AcquisitionStopped()
                if self.target_progress is not None:self.target_progress('verify')
                # One overview per accepted acquisition, outside the tracking loop.
                # Existing CURRENT/H/PL admission still runs after this UI hint.
                notice=None
                if self.target_report is not None:
                    if target is None:
                        notice=target_overview(selected.image,detection,self.detection_limit,self.tracking_limit,self._check_target)
                    else:notice='selecting' if target.selected else 'fallback'
                handoff=dict(refreshed=False)
                if self.factory is not None:
                    replacement,detection,handoff=freshen_source(self,selected,detection)
                    if replacement is not selected:selected.release();selected=replacement
                selection_proof=None
                if target is not None:
                    from ui import map_point as map_point; from ui import proof as proof
                    point,mapping=map_point(target.selection,selected.image,selected.sequence)
                    if not target.selected or cv2.pointPolygonTest(np.asarray(detection[0],np.float32),point,True)<0.:
                        raise ValueError('当前结果不属于本次点选目标')
                    selection_proof=proof(target.selection,point,selected.sequence,mapping,selection_method='automatic_physical_candidate',current_aligned=False)
                # Original source proof is exactV74. A chronological current FB
                # or V74 ordinary check must still pass before any DMA output.
                built=self.factory(selected,detection) if self.factory else None
                self.unpublished=built
                if self.phase_report is not None:self.phase_report('READY')
                if notice is not None:self.target_report(notice)
                report=dict(attempts=self.attempts,rejections=self.rejections,source_sequence=int(selected.sequence),
                    current_revalidated=bool(handoff['refreshed']),initial_source_verified=True,owned_source=True,
                    admission_policy='V74 stabilize_camera + admit_initial_frame + full detect_refined',
                    elapsed_worker_cpu_s=self.worker_cpu_s+time.thread_time()-cpu,
                    startup_stability=stability,source_age_s=max(0.,time.perf_counter()-selected.ready),
                    handoff=handoff,
                    current_frame_validation_before_output='complete_FB_or_V74_current_exterior')
                if selection_proof is not None:report['target_selection_proof']=selection_proof
                with self.condition:
                    stopped=self.stop
                    if not stopped:
                        self.result=(selected,detection,built,report);self.latest=None;self.stop=True
                        self.unpublished=None;self.condition.notify_all()
                if not stopped:
                    # The result slot now owns the frontend and source snapshot.
                    built=selected=None
                return
            except (AcquisitionStopped,RecoveryCancelled):
                return
            except (ValueError,TimeoutError,cv2.error) as exc:
                self.rejections+=1;self.attempts+=1
                if time.perf_counter()>=next_log:
                    checkpoint('V87_V74_ACQUIRE_RETRY',reason=str(exc),attempts=self.attempts,
                        preview_continues=True,legacy_detector_budgeted=False)
                    next_log=time.perf_counter()+2.
            finally:
                if built is not None:built.close();self.unpublished=None
                if first is not None:first.release()
                if selected is not None:selected.release()
                self.worker_cpu_s+=time.thread_time()-cpu;self.worker_wall_s+=time.perf_counter()-began
    def close(self):
        began=time.perf_counter()
        super().close()
        if self.unpublished is not None:self.unpublished.close();self.unpublished=None
        checkpoint('ACQUIRE_RETIRED',elapsed_s=time.perf_counter()-began,
            cooperative_stage_checks=True,worker_joined=not self.thread.is_alive(),forced_termination=False)




def target_quads(image):
    """Search-time coarse rectangles only; never evidence, H, or PL authority."""
    raw=image.ndim==3 and image.shape[2]==2
    gray=image[:,:,0] if raw else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    proposals=list(_contour_proposals(gray,320))
    if image.ndim==3:proposals.extend(_color_proposals(_small_color(image,192),image.shape))
    result=[]
    for quad in sorted(proposals,key=lambda q:abs(cv2.contourArea(q)),reverse=True):
        q=np.asarray(quad,np.float32)
        area=abs(cv2.contourArea(q))
        # The same outline and its interior print must not count as two books.
        if any(cv2.intersectConvexConvex(q,old)[0]>=.85*area for old in result):continue
        result.append(q)
        if len(result)==8:break
    return result


def prove_target(image,quad,limit,tracking_limit,color_reference=None,check=None,*,luma_first=False):
    """A coarse tap hint enters the existing full-source64/independent24 gate."""
    class TargetBudget(CpuRecoveryBudget):
        def check(self,stage,finish_gate=False):
            if check is not None:check()
            super().check(stage,finish_gate)
    budget=TargetBudget(1200.,1,wall_max_s=2.);budget.log_detail=False
    seeds=(dict(detector='tap_current_Y' if luma_first else 'tap_multicolor_exterior',coarse_corners=np.asarray(quad).tolist()),)
    with recovery_detection_scope(budget),recovery_candidate_scope(seeds,True):
        return detect_refined(image,limit,True,prefer_mask=True,color_reference=color_reference,tracking_limit=tracking_limit)


def target_overview(image,detection,limit,tracking_limit,check=None):
    """Hint only when a second independent rectangle passes original admission."""
    chosen=np.asarray(detection[0],np.float32);area=abs(cv2.contourArea(chosen))
    checked=0
    for q in target_quads(image):
        if check is not None:check()
        if cv2.intersectConvexConvex(chosen,q)[0]>.20*min(area,abs(cv2.contourArea(q))):continue
        checked+=1
        try:other,_=prove_target(image,q,limit,tracking_limit,check=check)
        except (QuadDetectionError,ValueError,cv2.error):
            if checked>=3:break
            continue
        if cv2.intersectConvexConvex(chosen,other)[0]<=.20*min(area,abs(cv2.contourArea(other))):return 'multiple'
        if checked>=3:break
    return 'idle'


class TargetSliceExpired(Exception):pass


def tap_candidates(image,point,check=None):
    """Retain different hypotheses for the clicked object, not only white blobs.

    These are proposals only. A frozen source never grants a CURRENT receipt.
    Keep near-outline variants until strict current admission has tried them.
    """
    from geometry import exterior_candidates as exterior_candidates
    def guard(stage=None):
        if check is not None:check()
    candidates=[]
    def add(q):
        q=np.asarray(q,np.float32)
        if cv2.pointPolygonTest(q,point,True)<2.:return None
        if any(np.max(np.linalg.norm(q-old,axis=1))<2. for old in candidates):return None
        candidates.append(q);return q
    for q in exterior_candidates(image,guard,192):
        guard();q=add(q)
        if q is not None:yield q
        if len(candidates)>=12:return
    gray=image[:,:,0] if image.ndim==3 and image.shape[2]==2 else cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    for q in _contour_proposals(gray,320,incremental=True):
        guard();q=add(q)
        if q is not None:yield q
        if len(candidates)>=12:return
    if image.ndim==3:
        for q in _color_proposals(_small_color(image,192),image.shape):
            guard();q=add(q)
            if q is not None:yield q
            if len(candidates)>=12:return


class TapDetector:
    """Bounded CURRENT retries for one tap, without an old-frame proof veto."""
    def __init__(self,selection,limit,tracking_limit,report=None,check=None):
        self.selection=selection;self.limit=limit;self.tracking_limit=tracking_limit
        self.report=report;self.check=check;self.seed=None;self.selected=False
        self.calls=0;self.cursor=0;self.finished=False
    def __call__(self,image,bgr):
        if self.finished:
            raise QuadDetectionError('本次点选自动搜索已结束，等待原策略转AI',dict(selection_only=True))
        self.calls+=1;self.selected=False
        from ui import map_point as map_point
        try:point,mapping=map_point(self.selection,image)
        except (ValueError,cv2.error) as exc:
            raise QuadDetectionError(str(exc),dict(selection_only=True)) from exc
        began=time.perf_counter();cpu=time.thread_time();failures=[];candidates=[]
        def check():
            if self.check is not None:self.check()
            if time.thread_time()-cpu>.60 or time.perf_counter()-began>1.2:raise TargetSliceExpired()
        def proposals():
            if self.seed is not None:yield self.seed
            for source in (image,):
                for q in tap_candidates(source,point,check):
                    if any(np.max(np.linalg.norm(q-old,axis=1))<2. for old in candidates):continue
                    candidates.append(q);yield q
        def try_candidate(q):
            for luma_first in (False,True):
                check()
                try:result=prove_target(image,q,self.limit,self.tracking_limit,bgr,check=check,luma_first=luma_first)
                except (QuadDetectionError,ValueError,cv2.error) as exc:
                    failures.append(dict(strategy='Y' if luma_first else 'YUV',reason=str(exc)));continue
                if cv2.pointPolygonTest(np.asarray(result[0],np.float32),point,True)<-2.:
                    failures.append(dict(reason='proved_rectangle_does_not_contain_clicked_point'));continue
                proposed_area=abs(cv2.contourArea(np.asarray(q,np.float32)));proved=np.asarray(result[0],np.float32)
                proved_area=abs(cv2.contourArea(proved));intersection=cv2.intersectConvexConvex(np.asarray(q,np.float32),proved)[0]
                if intersection/max(1.,proposed_area+proved_area-intersection)<.70:
                    failures.append(dict(reason='proved_rectangle_changed_target_candidate'));continue
                self.seed=np.asarray(result[0],np.float32).copy();self.selected=True
                checkpoint('TAP_TARGET_CURRENT_ACCEPTED',attempt=self.calls,current_frame_only=True,
                    luma_first=luma_first,candidate_count=len(candidates))
                return result
            self.cursor+=1
            return None
        try:
            # Admit immediately as proposals arrive; never collect a whole
            # multi-family pool before the first target can reach its gate.
            attempted=0
            for position,q in enumerate(proposals()):
                if position<self.cursor:continue
                if attempted>=4:break
                attempted+=1
                result=try_candidate(q)
                if result is not None:return result
            if not attempted:
                self.cursor=0
                # A new snapshot gets another chance even if its candidate
                # count shrank below the previous frame's search cursor.
                for q in candidates[:4]:
                    result=try_candidate(q)
                    if result is not None:return result
        except TargetSliceExpired:failures.append(dict(reason='target_slice_exhausted_retry_latest_frame'))
        if (candidates or failures) and self.calls<3:
            checkpoint('TAP_TARGET_RETRY',attempt=self.calls,latest_frame_required=True,candidate_count=len(candidates),failures=failures[-6:])
            raise QuadDetectionError('点选候选未通过当前四边验证，换最新画面重试',dict(attempt=self.calls,failures=failures[-6:]))
        self.finished=True
        if self.report is not None:self.report('fallback')
        checkpoint('TAP_TARGET_FALLBACK',search_route_only=True,final_target_result_pending=True,attempts=self.calls,candidate_count=len(candidates),failures=failures[-6:])
        raise QuadDetectionError('点选自动未找到，保留本次目标意图等待AI',dict(selection_only=True,attempts=self.calls))


# ======================================================================
# ===== [20/28] v90_transaction =====
# ======================================================================


"""Bounded ownership and exact geometry reuse; no device operations here."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class OutputReference:
    """One explicit reference to a completed, cache-synchronized output slot."""
    def __init__(self,pool,index,array):
        self.pool=pool;self.index=index;self.array=array;self.released=False

    def retain(self,out):
        with self.pool.lock:
            if self.released or self.pool.closed:raise RuntimeError('Output reference retired')
            if (out.shape!=self.array.shape or out.dtype!=self.array.dtype or
                    out.strides!=self.array.strides or out.ctypes.data!=self.array.ctypes.data):
                raise ValueError('Output reference does not own this completed frame')
            self.pool.counts[self.index]+=1
            return OutputReference(self.pool,self.index,self.array)

    def release(self):
        with self.pool.lock:
            if not self.released:
                self.pool.counts[self.index]-=1;self.released=True
                if self.pool.counts[self.index]<0:raise RuntimeError('Output reference underflow')

    def __del__(self):
        # Interrupted publication must not strand a reference whose temporary
        # owner never reached the normal explicit-release path.
        try:self.release()
        except BaseException:pass


class OutputSlots:
    """Three slots: one DMA writer, one HDMI reader and one pending output.

    Allocation/free remain on the P1 owner. HDMI may only retain/release a
    completed slot. No physical buffer can be reused while a reader holds it.
    """
    def __init__(self,allocate,capacity):
        self.lock=threading.RLock();self.counts=[];self.buffers=[];self.closed=False
        try:
            for _ in range(3):
                self.buffers.append(allocate(shape=(int(capacity)*4,),dtype=np.uint8));self.counts.append(0)
        except BaseException:
            for buffer in self.buffers:buffer.freebuffer()
            self.buffers.clear();raise

    def acquire(self,width,height):
        with self.lock:
            if self.closed:raise RuntimeError('Output pool closed')
            index=next((i for i,n in enumerate(self.counts) if n==0),None)
            if index is None:raise RuntimeError('All output slots retained; ownership invariant broken')
            buffer=self.buffers[index]
            if width*height*4>buffer.nbytes:raise ValueError('Output pool capacity exceeded')
            self.counts[index]=1
            return OutputReference(self,index,buffer[:width*height*4].reshape(height,width,4))

    def close(self):
        with self.lock:
            if self.closed:return
            if any(self.counts):raise RuntimeError('HDMI still references output slots: '+str(self.counts))
            for buffer in self.buffers:buffer.freebuffer()
            self.buffers.clear();self.closed=True


_GEOMETRY=ContextVar('p11_v90_exact_geometry_transaction',default=None)


def geometry_transaction(function):
    """Memoize geometry only during one synchronous call, including nested calls."""
    @wraps(function)
    def run(*args,**kwargs):
        if _GEOMETRY.get() is not None:return function(*args,**kwargs)
        workspace=dict(entries={},calls=0,hits=0)
        token=_GEOMETRY.set(workspace)
        try:return function(*args,**kwargs)
        finally:
            if args:
                args[0]._v90_geometry_stats=dict(calls=workspace['calls'],hits=workspace['hits'],
                    entries=len(workspace['entries']),scope='one synchronous transaction; geometry only',
                    frame_index=getattr(args[0],'_update_index',None),function=function.__name__,
                    sampling_reused=False,FB_checks_skipped=False)
            _GEOMETRY.reset(token)
    return run


def pair_geometry(first,second):
    """Exact original float64 line/corner arithmetic; never a proof receipt."""
    a=np.asarray(first,np.float64);b=np.asarray(second,np.float64)
    if a.shape!=(4,2) or b.shape!=(4,2) or not np.isfinite(a).all() or not np.isfinite(b).all():
        return 'invalid',None,None
    workspace=_GEOMETRY.get();key=None
    if workspace is not None:
        workspace['calls']+=1;key=tuple(sorted((a.tobytes(),b.tobytes())))
        cached=workspace['entries'].get(key)
        if cached is not None:
            workspace['hits']+=1;return cached
    values=[]
    for p,q in ((a,b),(b,a)):
        edges=np.roll(p,-1,axis=0)-p;length=np.linalg.norm(edges,axis=1)
        if np.min(length)<4:return 'degenerate',None,None
        normal=np.stack((-edges[:,1],edges[:,0]),axis=1)/length[:,None]
        points=q[:,None,:]+np.array([.15,.5,.85])[None,:,None]*(np.roll(q,-1,axis=0)-q)[:,None,:]
        values.append(float(np.max(np.abs(np.sum((points-p[:,None,:])*normal[:,None,:],axis=2)))))
    result=(None,max(values),float(np.max(np.linalg.norm(a-b,axis=1))))
    if workspace is not None and len(workspace['entries'])<64:workspace['entries'][key]=result
    return result


class CandidateAttempts:
    """Same-frame exact duplicate suppression; no approximate/negative cache.

    The detector's existing <2px rejection remains. This additionally recognizes
    identical proposals from different families/start vertices/winding. New
    source frames always start empty and receive all current strict proofs.
    """
    def __init__(self):self.seen=set();self.repeats=0;self.unique=0

    def repeated(self,quad,strategy):
        q=np.asarray(quad,np.float32)
        if q.shape!=(4,2) or not np.isfinite(q).all():return False
        variants=[]
        for packed in (q.tobytes(),q[::-1].tobytes()):
            variants.extend(packed[8*i:]+packed[:8*i] for i in range(4))
        # Color-first and Y-first are different transactions even if their
        # geometry is identical; neither may suppress the other.
        key=(bool(strategy),min(variants))
        if key in self.seen:self.repeats+=1;return True
        if len(self.seen)<256:self.seen.add(key)
        self.unique+=1;return False


# ======================================================================
# ===== [21/28] v87_v74_tracking =====
# ======================================================================


"""Per-frame paper edges first; confidence-triggered predicted sparse LK.

Coordinates returned to the caller are original BGR pixel coordinates. No PL
access occurs here. A failed reacquisition returns valid=False, never stale H.
"""
from core import RELEASE_ID as RELEASE_ID
from core import luminance as luminance; from core import model_bgr as model_bgr; from core import gray_half as gray_half

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

# ⭐⭐ 2026-10-18（把 V1.1 的优化合并进 V94）：
#   gate 失守后那次 `_boundary` 「重搜」的开关。
#   【默认 False = 行为与原 V94 完全一致】；notebook 里设 P11_SKIP_RESEARCH=1 才跳过。
#
# 证据（V1.1 上做的 A/B，跑的是本 tracker 的同一段代码）：
#   - edge_confidence 帧 tracker 170.0 → 121.9 ms（−28%）
#   - tracker p90 −18%、service p90 −15%、中位持平、confidence 完全相同
#   - V89-M 上板复验：干净场景 156.9 → 126.0 ms（−20%）
#   ⚠️ V94 换了 V90/V91 原生事务，绝对毫秒会变，但这段 `current_boundary` 调用本身没变。
#
# ⚠️ 用环境变量而不是改常量：改 .py 会让 sha256 与 release_manifest.json 不一致
#    ⇒ verify_package 直接抛错，还得 Kernel->Restart（_SOURCE_SHA256 是 import 时算的）。
# ⚠️ 在【调用时】读 ⇒ 改完下一次跟踪就生效，不用重启内核。
SKIP_DEAD_RESEARCH = False


def skip_dead_research():
    """A/B 开关：环境变量 P11_SKIP_RESEARCH=1 就跳过那次 _boundary 重搜。"""
    return os.environ.get('P11_SKIP_RESEARCH') == '1'


# ⭐⭐ 2026-10-18 静态保持（static hold）：
#   静止超过 min_frames 帧后，跳过 observer/边测量/门限，直接复用上一帧四角；
#   一旦帧差超过退出阈值、或距上次完整测量超过 max_hold_s，立即走原完整路径。
#   默认 False（行为与 V94-M 完全一致）；notebook 里设 P11_STATIC_HOLD=1 才开。
#   预算（V94-M 实测，静态 edge_measured 帧）：service 46.3 ms，其中 tracker 23.0 ms。
STATIC_HOLD = False


def static_hold_enabled():
    return os.environ.get('P11_STATIC_HOLD') == '1'


def _hold_float(name,default):
    try:return float(os.environ.get(name,default))
    except (TypeError,ValueError):return float(default)


def static_hold_settings():
    """静态保持参数。阈值会乘上自适应噪声底，见 _static_hold。"""
    return dict(enabled=static_hold_enabled(),continuity=os.environ.get('P11_STATIC_EDGE_CONTINUITY','1')!='0',
        enter=_hold_float('P11_HOLD_ENTER',4.),exit=_hold_float('P11_HOLD_EXIT',8.),
        enter_frac=_hold_float('P11_HOLD_CHANGE',.03),exit_frac=_hold_float('P11_HOLD_EXIT_CHANGE',.08),
        max_s=_hold_float('P11_HOLD_MAX_S',.8),min_frames=max(1,int(_hold_float('P11_HOLD_MIN_FRAMES',3))),
        enter_gain=_hold_float('P11_HOLD_ENTER_GAIN',1.5),exit_gain=_hold_float('P11_HOLD_EXIT_GAIN',2.2),
        smooth=max(1,int(_hold_float('P11_HOLD_SMOOTH',3))))


class LKExteriorMismatch__v87_v74_tracking(ValueError):
    """FB/motion fit succeeded, but the CURRENT exterior did not verify it."""

class GrayObserver__v87_v74_tracking:
    """Reuse three gray slots; pinned anchor and last observation stay intact."""
    def __init__(self, limit, backend='auto', gaussian_backend='auto'):
        if backend not in ('auto','legacy'):raise ValueError('gray_backend须为auto/legacy')
        if gaussian_backend not in ('auto','legacy'):raise ValueError('gaussian_backend须为auto/legacy')
        self.limit,self.backend=limit,backend
        self.gaussian_backend=gaussian_backend
        self.blur_workspace=None
        self.scratch=None
        self.detail={};self.pool=[];self.pinned=None;self.last=None;self.merged_edges=None;self.merged_error=None
        self.timing=np.empty(2,np.float64)
        self._layout=None;self._scale=None;self._geometry=None
        self.transaction=ObservationWorkspace__v87_v74_native()
    def pin(self,gray):self.pinned=gray
    def output(self,shape):
        if not self.pool or self.pool[0].shape!=shape:self.pool=[np.empty(shape,np.uint8) for _ in range(3)]
        return next(a for a in self.pool if a is not self.pinned and a is not self.last)

    def get(self,image,edge_context=None):
        began=time.perf_counter();cpu=time.thread_time();h,w=image.shape[:2];self.merged_edges=None;self.merged_error=None
        self.transaction.decode_timing=(0.,0.)
        layout=(h,w,self.limit)
        if layout!=self._layout:
            scale=min(1.,self.limit/max(h,w));ow,oh=round(w*scale),round(h*scale)
            self._scale=np.frombuffer(np.array([w/ow,h/oh],np.float64).tobytes(),np.float64)
            self._geometry=(scale,ow,oh);self._layout=layout
        scale,ow,oh=self._geometry
        #   ⚠️ 2026-10-28：原生 fused 灰度要求降采样**恰好 2 倍**（见下面几处
        #      `(ow*2,oh*2)==(w,h)`）。480P 要 320、600P 要 400 ——
        #      切档方案里若只改相机宽高而不改 `tracking_max_dim`，
        #      会**静默**退回 Python 慢路径（实测 11 ms → 63 ms）。
        #      这里打一次性 checkpoint，让"切档后变慢"能一眼看出来。
        if not (ow*2,oh*2)==(w,h) and not getattr(self,'_slow_warned',False):
            self._slow_warned=True
            try:
                from core import checkpoint as _ck
                _ck('GRAY_OBSERVER_SLOW_PATH',warning='原生 fused 要求恰好 2 倍降采样',
                    image_shape=[h,w],limit=self.limit,gray_shape=[oh,ow],
                    fix='tracking_max_dim 必须等于 长边/2（640x480⇒320，800x600⇒400）')
            except Exception:pass
        if self.backend=='auto' and self.gaussian_backend=='auto' and (ow*2,oh*2)==(w,h):
            if self.scratch is None or self.scratch.shape!=(oh,ow):self.scratch=np.empty((oh,ow),np.uint8)
            if self.blur_workspace is None or self.blur_workspace.size<3*ow:self.blur_workspace=np.empty(3*ow,np.uint16)
            out=self.output((oh,ow));fused_result=None
            if edge_context is not None:
                merged=self.transaction.observe(image,self.scratch,self.blur_workspace,out,*edge_context)
                if merged is not None:
                    self.merged_edges,detail=merged;self.merged_error=detail.get('edge_error');fused_result=(out,detail)
            if fused_result is None:fused_result=fused_observation2__v87_v74_native(image,self.scratch,self.blur_workspace,out,self.timing)
            if fused_result is not None:
                observation,detail=fused_result;elapsed=time.perf_counter()-began
                self.detail=dict(detail,backend='cpp_fused_area2_gaussian3',blur_backend='cpp_fixed_gaussian3',
                    shape=[oh,ow],gray_s=elapsed,
                    native_return_overhead_s=max(0.,elapsed-detail.get('native_transaction_s',detail['resize_gray_s']+detail['blur_s'])))
                self.detail['observation_transaction_s']=elapsed;self.detail['output_pool_reused']=True
                self.last=observation
                self.detail['thread_cpu_s']=time.thread_time()-cpu
                return observation,self._scale
        backend='opencv_area_then_gray';fused=False
        if self.backend=='auto' and (ow*2,oh*2)==(w,h):
            if self.scratch is None or self.scratch.shape!=(oh,ow):
                self.scratch=np.empty((oh,ow),np.uint8)
            fused=gray_area2__v87_v74_native(image,self.scratch)
            if fused:gray=self.scratch;backend=native_status__v87_v74_native().get('gray_backend','fused_area2')
        if not fused:
            if image.shape[2]==2:
                if (ow*2,oh*2)==(w,h):
                    if self.scratch is None or self.scratch.shape!=(oh,ow):self.scratch=np.empty((oh,ow),np.uint8)
                    gray=gray_half(image,self.scratch)
                else:
                    y=luminance(image);gray=cv2.resize(y,(ow,oh),interpolation=cv2.INTER_AREA) if scale<1 else y
                backend='direct_Y_normalized'
            else:
                view=cv2.resize(image,(ow,oh),interpolation=cv2.INTER_AREA) if scale<1 else image
                gray=cv2.cvtColor(view,cv2.COLOR_BGR2GRAY)
        resize_s=time.perf_counter()-began;t=time.perf_counter()
        # Fresh blurred allocation is deliberate: anchor_gray must survive
        # intermediate frames and the native pyramid promotion.
        observation=None;blur_backend='opencv_gaussian3'
        if self.gaussian_backend=='auto':
            if self.blur_workspace is None or self.blur_workspace.size<3*ow:
                self.blur_workspace=np.empty(3*ow,np.uint16)
            observation=gaussian3__v87_v74_native(gray,self.blur_workspace)
            if observation is not None:blur_backend=native_status__v87_v74_native().get('blur_backend','cpp_gaussian3')
        if observation is None:observation=cv2.GaussianBlur(gray,(3,3),.6)
        self.detail=dict(backend=backend,blur_backend=blur_backend,shape=[oh,ow],resize_gray_s=resize_s,
                         blur_s=time.perf_counter()-t,gray_s=time.perf_counter()-began)
        self.last=observation
        self.detail['thread_cpu_s']=time.thread_time()-cpu
        return observation,self._scale

def _gray__v87_v74_tracking(image,limit):
    return GrayObserver__v87_v74_tracking(limit,'legacy').get(image)


def _valid__v87_v74_tracking(q, shape, reference=None, checks='auto'):
    if checks=='auto':
        result=quad_valid__v87_v74_native(q,shape,reference)
        if result is not None:return result
    q = np.asarray(q, np.float32).reshape(4, 2)
    h, w = shape[:2]
    if not np.isfinite(q).all() or not cv2.isContourConvex(q):
        return False
    if np.cross(q[1]-q[0], q[2]-q[1]) <= 0:
        return False
    area = abs(cv2.contourArea(q))
    if area < .035*w*h or np.any(q < 0) or np.any(q[:, 0] > w-1) or np.any(q[:, 1] > h-1):
        return False
    if reference is not None:
        old = abs(cv2.contourArea(np.asarray(reference, np.float32)))
        if not .55 < area/max(old, 1.) < 1.8:
            return False
    return True


def _edge_python__v87_v74_tracking(gray, quad, radius=5., checks='auto'):
    """Sample 24 short normal profiles per OUTER paper edge, then intersect TLS lines."""
    q = np.asarray(quad, np.float64).reshape(4, 2)
    offsets = np.linspace(-radius, radius, 25)
    fractions = np.linspace(.055, .945, 24)
    center = q.mean(axis=0)
    lines, supports, shifts, polarity, rms_values = [], [], [], [], []
    for i in range(4):
        a, b = q[i], q[(i+1) % 4]
        edge = b-a
        normal = np.array([-edge[1], edge[0]]) / max(np.linalg.norm(edge), 1e-6)
        if np.dot(center-(a+b)*.5, normal) < 0:
            normal = -normal
        base = a + fractions[:, None]*edge
        xy = base[:, None, :] + offsets[None, :, None]*normal
        p = cv2.remap(gray, xy[..., 0].astype(np.float32), xy[..., 1].astype(np.float32),
                      cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        outer, inner = np.median(p[:, :4], axis=1), np.median(p[:, -4:], axis=1)
        contrast = inner-outer
        signed = (p-(outer+inner)[:, None]*.5)*np.where(contrast >= 0, 1., -1.)[:, None]
        crossing = (signed[:, :-1] <= 0) & (signed[:, 1:] > 0)
        scores = np.where(crossing, np.abs((offsets[:-1]+offsets[1:])*.5), np.inf)
        col = np.argmin(scores, axis=1)
        row = np.arange(len(base))
        before, after = signed[row, col], signed[row, col+1]
        alpha = np.clip(-before/np.maximum(after-before, 1e-6), 0., 1.)
        shift = offsets[col] + alpha*(offsets[col+1]-offsets[col])
        good = (np.abs(contrast) >= 8) & crossing.any(axis=1) & (np.abs(shift) < radius*.85)
        line = None
        rms = 1e30
        support = float(good.mean())
        if good.sum() >= 10 and np.ptp(fractions[good]) >= .55:
            points = base[good]+shift[good, None]*normal
            for _ in range(2):
                mean = points.mean(axis=0)
                n = _tls_normal__v87_v74_tracking(points-mean)
                residual = np.abs((points-mean)@n)
                keep = residual <= max(.6, 2.5*float(np.median(residual)))
                if keep.all() or keep.sum() < 8:
                    break
                points = points[keep]
            mean = points.mean(axis=0)
            n = _tls_normal__v87_v74_tracking(points-mean)
            rms = float(np.sqrt(np.mean(((points-mean)@n)**2)))
            if rms <= 1.25:
                line = np.r_[n, -n@mean]
        lines.append(line)
        rms_values.append(rms)
        supports.append(support if line is not None else 0.)
        shifts.append(float(np.median(np.abs(shift[good]))) if good.any() else radius)
        median_contrast = float(np.median(contrast))
        polarity.append(int(np.sign(median_contrast)) if abs(median_contrast) >= 8 else 0)
    corrected = q.copy()
    refined = 0
    for i in range(4):
        if lines[i-1] is None or lines[i] is None:
            continue
        cross = np.cross(lines[i-1], lines[i])
        if abs(cross[2]) > .06:
            point = cross[:2]/cross[2]
            if np.linalg.norm(point-q[i]) < radius*2.8:
                corrected[i] = point
                refined += 1
    supported_edges = sum(s >= .42 for s in supports)
    valid = supported_edges >= 3 and refined >= 2 and _valid__v87_v74_tracking(corrected, gray.shape, q, checks)
    return corrected.astype(np.float32), dict(valid=bool(valid), supported_edges=supported_edges,
        edge_support=supports, edge_polarity=polarity, refined_corners=refined,
        median_edge_shift=float(np.median(shifts)),edge_rms=rms_values,max_edge_rms=max(rms_values))



def _tls_normal__v87_v74_tracking(centered):
    xx=float(np.sum(centered[:,0]**2));yy=float(np.sum(centered[:,1]**2))
    xy=float(np.sum(centered[:,0]*centered[:,1]))
    if np.hypot(xx-yy,2*xy)<=1e-10*(xx+yy+1):
        raise ValueError('TLS edge samples degenerate')
    theta=.5*np.arctan2(2*xy,xx-yy)
    return np.array([-np.sin(theta),np.cos(theta)])

def edge_measure__v87_v74_tracking(gray,quad,radius=5.,checks='auto'):
    began=time.perf_counter()
    native=measure_edges__v87_v74_native(gray,quad,radius,checked=checks=='auto')
    if native is None:
        q,evidence=_edge_python__v87_v74_tracking(gray,quad,radius,checks)
        evidence['edge_backend']='numpy_analytic_tls'
    else:
        q,evidence=native
        evidence['valid']=(evidence['native_valid'] if checks=='auto' else
            evidence['supported_edges']>=3 and evidence['refined_corners']>=2 and _valid__v87_v74_tracking(q,gray.shape,quad,checks))
    evidence['edge_measure_s']=time.perf_counter()-began
    return q,evidence

def _spatial_support__v87_v74_tracking(points,quad,checks='auto'):
    if checks=='auto':
        result=spatial_support__v87_v74_native(points,quad)
        if result is not None:return result
    p=np.asarray(points,np.float32).reshape(-1,2)
    if len(p)<4:return False
    area=abs(cv2.contourArea(np.asarray(quad,np.float32)))
    if abs(cv2.contourArea(cv2.convexHull(p)))<.25*max(area,1):return False
    # Require points near three different border segments, not one grid line.
    q=np.asarray(quad,np.float32);edge=np.roll(q,-1,axis=0)-q
    d=p[:,None,:]-q[None,:,:]
    t=np.clip(np.sum(d*edge[None,:,:],axis=2)/np.maximum(np.sum(edge*edge,axis=1),1e-6),0,1)
    distance=np.linalg.norm(d-t[:,:,None]*edge[None,:,:],axis=2)
    near=np.argmin(distance,axis=1)
    return len(np.unique(near))>=3 or len(p)==4  # four widely spaced tracked paper corners

class PaperTracker__v87_v74_tracking:
    def __init__(self, interval=3, limit=320, detection_limit=640, detector=None,
                 gray_backend='auto',feature_policy='quality',gaussian_backend='auto',tracking_checks='auto',
                 tracking_policy='motion_adaptive',lk_max_gap=30,lk_min_gap=6):
        if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 10:
            raise ValueError('track_interval 须为 1..10 的整数')
        if not 160 <= limit <= 640:
            raise ValueError('tracking_max_dim 须为 160..640')
        if tracking_policy not in ('motion_adaptive','edge_first','periodic'):raise ValueError('tracking_policy须为motion_adaptive/edge_first/periodic')
        if isinstance(lk_max_gap,bool) or not isinstance(lk_max_gap,int) or not 3<=lk_max_gap<=60:
            raise ValueError('lk_max_gap须为3..60')
        if isinstance(lk_min_gap,bool) or not isinstance(lk_min_gap,int) or not 3<=lk_min_gap<=lk_max_gap:raise ValueError('lk_min_gap须为3..lk_max_gap')
        self.lk_min_gap=lk_min_gap
        self.motion_ema=self.correction_ema=self.drift_budget=0.
        self.accumulated_drift=np.zeros((4,2),np.float32)
        self.policy,self.lk_max_gap=tracking_policy,lk_max_gap
        self.interval, self.limit, self.detection_limit = interval, limit, detection_limit
        self.detector = detector
        self.velocity = np.zeros((4, 2), np.float32)
        self.started = False
        self.last_index = self.anchor_index = 0
        self.lost = False
        self.seed_index=0
        self.seed_count=0
        self._promoted_points=None
        self.lk_cache=LKTransaction()
        self.post_lk=PostLKWorkspace()
        self.last_lk_timing={}
        if feature_policy not in ('quality','legacy'):raise ValueError('feature_policy须为quality/legacy')
        if tracking_checks not in ('auto','legacy'):raise ValueError('tracking_checks须为auto/legacy')
        self.checks=tracking_checks
        self.feature_policy=feature_policy
        self.observer=GrayObserver__v87_v74_tracking(limit,gray_backend,gaussian_backend)
        self.last_gray=None
        self.light_results=False
        self.last_feature_detail={}
        self.edge_workspace=EdgeMotionWorkspace__v87_v74_native()
        self._current_motion_values=None
        self.edge_recovery_count=0
        # ⭐ 静态保持状态
        self._hold_ref=None;self._hold_count=0;self._hold_active=False;self._hold_since=0.
        self._hold_last_full=0.;self._hold_gate={};self._hold_confidence=0.;self._hold_frames=0
        self._hold_motion=0.;self._hold_changed=0.
        self._hold_tmp=None;self._hold_hist=[];self._hold_floor_m=4.;self._hold_floor_c=.03
        self._hold_smooth=(0.,0.);self._hold_cfg=None
        self._still_q=None;self._still_samples=None;self._still_calm=False;self._still_radius=3.
        self._still_edge_motion=0.;self._still_release='initial'
        self._roi_failures=0;self._roi_retry_lk=0;self._roi_lk_checks=0
        # ⭐ 2026-10-28：重取点【成功】后的最小间隔（单位：LK 帧）。
        #    实测 native 四角 ROI 18~25 ms、边缘条 30~33 ms，占动态帧约 13 ms；
        #    而原来成功后 `delay=1` ⇒ 下一帧立刻又搜。P11_ROI_SEARCH_GAP=1 回到旧行为。
        try:self._roi_search_gap=max(1,min(8,int(os.environ.get('P11_ROI_SEARCH_GAP','3'))))
        except ValueError:self._roi_search_gap=3
        self._roi_last_q=None;self._roi_mask=None;self._roi_inside=None
        self._gap_anchor_reuses=0
        self._burst_until=-1;self._frame_deadline=None;self._update_index=0
        self.anchor_gray=None;self.lk_channel='Y';self._flow_gray=None;self._flow_cache=None;self._chroma_pool=[]
        self._channel_audit_index=-100;self._channel_evidence={};self._edge_radius=3.
        self.state='UNINITIALIZED';self._total_deadline=None;self._reserved_detection_ms=0.
        self._lk_initial=np.empty((100,1,2),np.float32)
        self._lk_anchor_quad=np.empty((4,2),np.float32)
        self._lk_prediction_quad=np.empty((4,2),np.float32)
        self.recovery_budget_ms=None;self.recovery_max_candidates=2;self.recovery_backoff_max_frames=4
        self.reacquire_budget_ms=240.;self.reacquire_max_candidates=4
        self._recovery_failures=0;self._recovery_next_index=0;self._recovery_attempts=0
        self._recovery_next_at=0.;self._continuity_proof_next_at=0.;self.continuity_hold=False
        self.recovery_retry_min_s=.20;self.recovery_retry_max_s=.60
        self.recovery_stats=dict(attempts=0,deferred=0,successes=0,budget_stops=0,elapsed_s=0.,overshoot_s=0.)
        self.recovery_snapshots=[]
        self._vector_boundary=False;self._target_signature=None;self._recovery_confirmations=3
        self.recovery_worker=None;self.recovery_result_max_age_s=.90
        self.photometric=IlluminationMotion()
        self.stability=StableEdgeWorkspace();self.stability_detail={}
        self._stability_drift_start=np.zeros((4,2),np.float32)
        self._last_measured_motion=0.;self._edge_lock_next_at=0.;self._edge_lock_failures=0
        self.current_proofs=CurrentProofWorkspace()
        self.fastpath_detail={};self.quick_recovery_detail={};self._quick_recovery_attempted=False

    def configure_async_recovery(self,enabled=True,result_max_age_s=.90):
        if not isinstance(enabled,bool) or isinstance(result_max_age_s,bool) or not np.isfinite(result_max_age_s) or not .1<=result_max_age_s<=1.:
            raise ValueError('async_recovery bool; recovery_result_max_age_s .1..1 seconds')
        self.recovery_result_max_age_s=float(result_max_age_s)
        if enabled and self.recovery_worker is None:
            self.recovery_worker=RecoveryWorker(self.detection_limit,self.limit)

    def _async_wait(self,image,index,began,cpu,reason,result=None,observation=None,request_background=True):
        self.lost=True;self.state='LOST';self.velocity[:]=0;self.last_index=index
        age=max(0.,time.perf_counter()-getattr(self,'_last_physical_at',began))
        local_first=(age<.20 and not self._quick_recovery_attempted and getattr(self,'_local_attempts',0)<2
            and self._last_measured_motion<=4. and not getattr(self,'source_force_reacquire',False))
        request_background=bool(request_background and not local_first)
        requested=self.recovery_worker.request(image,index,
            getattr(self,'source_ready_at',began),getattr(self,'source_sequence',None),
            self.reacquire_budget_ms,self.reacquire_max_candidates) if request_background else False
        detail=dict(state='async_detection_in_progress',requested=requested,
            result=None if result is None else {k:result.get(k) for k in
                ('valid','index','sequence','ready','completed_at','worker_s','worker_cpu_s','reason')},
            worker=self.recovery_worker.snapshot(),hardware_access=False,
            ordinary_frame_heavy_recovery_skipped=True,current_candidate_required_before_new_H=True,
            background_deferred_for_local_first=not request_background,
            local_attempts=int(getattr(self,'_local_attempts',0)),local_first_grace_s=.20,
            large_motion_skips_local=self._last_measured_motion>4.)
        record=dict(valid=False,mode='lost_skip',reason=reason,trigger=reason,index=index,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu,
            gray_s=0.,gray_detail=dict(state='not_measured_while_background_busy'),
            feature_update_s=0.,feature_detail=dict(action='async_wait',roi_s=0.),lk_timing={},
            tracking_policy=self.policy,lk_channel=self.lk_channel,lk_trigger='async_recovery',
            tracking_state=self.state,edge_gate={},edge_evidence={},detection=None,
            final_admission_gate=dict(reliable=False),recovery_attempt=detail,edge_stability=dict(self.stability_detail),
            v49_fastpath=dict(self.fastpath_detail),quick_current_candidate=dict(self.quick_recovery_detail),
            current_proof_workspace=self.current_proofs.summary())
        if observation is not None:record.update(observation)
        return record

    def _admit_async_candidate(self,image,gray,scale,result,index):
        # Background coordinates are a proposal ONLY. All admitted edges come
        # from the currently leased input. The worker's receipt is never reused.
        from geometry import exterior_agreement as exterior_agreement; from geometry import array_key as array_key; from geometry import actual_source64 as actual_source64
        age=max(0.,time.perf_counter()-result['ready'])
        if age>self.recovery_result_max_age_s:raise ValueError('Background candidate too old')
        proposal=((np.asarray(result['quad'],np.float32)+.5)/scale-.5).astype(np.float32)
        transport=dict(used=False,backend='bounded_candidate_corner_forward_backward_LK')
        donor=result.get('source_gray');donor_scale=result.get('source_scale')
        if donor is not None and donor.shape==gray.shape and np.allclose(donor_scale,scale,rtol=0,atol=1e-6):
            t=time.perf_counter();cpu=time.thread_time()
            points=proposal.reshape(4,1,2)
            criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,20,.02)
            moved,status,error=cv2.calcOpticalFlowPyrLK(donor,gray,points,None,
                winSize=(21,21),maxLevel=2,criteria=criteria)
            if moved is not None and status is not None and np.all(status):
                back,back_status,_=cv2.calcOpticalFlowPyrLK(gray,donor,moved,None,
                    winSize=(21,21),maxLevel=2,criteria=criteria)
                fb=float(np.max(np.linalg.norm(back.reshape(4,2)-proposal,axis=1))) if back is not None else float('inf')
                transported=moved.reshape(4,2)
                if (back_status is not None and np.all(back_status) and np.isfinite(transported).all()
                        and fb<=1. and error is not None and np.max(error)<=30.
                        and _valid__v87_v74_tracking(transported,gray.shape,proposal,self.checks)):
                    proposal=transported.astype(np.float32);transport.update(used=True,fb_max=fb)
                else:transport.update(reason='candidate_flow_rejected',fb_max=fb)
            else:transport['reason']='candidate_flow_unavailable'
            transport.update(wall_s=time.perf_counter()-t,thread_cpu_s=time.thread_time()-cpu)
        if not _valid__v87_v74_tracking(proposal,gray.shape,checks=self.checks):raise ValueError('Background candidate geometry invalid')
        reference=proposal.copy()
        measured,small_evidence=edge_measure__v87_v74_tracking(gray,reference,6.,self.checks)
        gray_gate=exterior_gate(small_evidence,measured,reference,6.)
        gray_trusted=(gray_gate.get('reliable') and gray_gate.get('min_support',0.)>=.80
            and gray_gate.get('max_rms',1e30)<=.65 and gray_gate.get('prediction_correction',1e30)<=.75)
        seed=measured if gray_trusted else reference
        primary,evidence,second_gate,agreement=self._source_confirmation(
            image,gray,seed,small_evidence,new_candidate=True,radius=6.,
            reference=reference,gray_reliable=bool(gray_trusted))
        transport.update(original_candidate_preserved=True,gray_seed_used=bool(gray_trusted),
            gray_gate=gray_gate,source_reference=reference.tolist())
        from geometry import search_gate as search_gate
        first=search_gate(evidence,primary,proposal,6.)
        verified=(first.get('reliable') and second_gate.get('reliable') and agreement.get('verified')
            and _valid__v87_v74_tracking(primary,gray.shape,checks=self.checks))
        if not verified:
            from core import checkpoint as checkpoint
            checkpoint('ASYNC_CANDIDATE_CURRENT_REJECTED',current_index=index,
                background_index=result['index'],candidate_age_s=age,
                first_gate=first,independent_gate=second_gate,agreement=agreement,
                candidate_transport=transport,hardware_access=False)
            raise ValueError('Background proposal failed current independent exterior proof: '+str(agreement.get('reason','four_edge_disagreement')))
        return primary,evidence,dict(state='async_candidate_current_frame_verified',
            background_index=result['index'],background_sequence=result['sequence'],candidate_age_s=age,
            current_index=index,candidate_transport=transport,first_validation=first,second_validation=second_gate,
            source_line_agreement=agreement,old_H_not_used=True,stale_receipt_used=False)

    def _local_due(self):
        now=time.perf_counter();age=now-getattr(self,'_last_physical_at',0.)
        # At most two local attempts per actual validation failure episode.
        # Expiring output hold does not reset or extend this search budget.
        return bool(0<=age<=1.5 and now>=getattr(self,'_local_next_at',0.)
            and getattr(self,'_local_attempts',0)<2 and self._last_measured_motion<=4.
            and not getattr(self,'source_force_reacquire',False))

    def _quick_current_candidate(self,image,gray,scale,index):
        """One current-Y contour candidate per loss episode, strict admission.

        Proposal generation and original64/independent24 share one CPU/wall
        budget. A miss does not fall through to a full foreground search.
        """
        if self._quick_recovery_attempted:return None
        self._quick_recovery_attempted=True
        from geometry import array_key as array_key
        began=time.perf_counter();cpu=time.thread_time()
        budget=CpuRecoveryBudget(120.,1,wall_max_s=.30)
        observation=dict(gray=gray,scale=scale,source_shape=image.shape,frame_index=index,source_key=array_key(image))
        detail=dict(attempted=True,verified=False,proposal_source='current_tracking_Y_contour',
            maximum_candidates=1,maximum_attempts_per_loss_episode=1,hardware_access=False,
            old_H_not_used=True,full_foreground_search=False)
        self.quick_recovery_detail=detail
        try:
            with recovery_detection_scope(budget,observation):
                budget.check('v69_current_Y_proposal')
                proposal=next(iter(_contour_proposals(gray,min(240,self.detection_limit),incremental=True)),None)
                if proposal is None:
                    detail['reason']='no_current_Y_contour_candidate';return None
                if not _valid__v87_v74_tracking(np.asarray(proposal,np.float32),gray.shape,checks=self.checks):
                    detail['reason']='current_Y_candidate_geometry_invalid';return None
                budget.check('v69_immediate_candidate_admission')
                coarse=(np.asarray(proposal,np.float32)+.5)*scale-.5
                seed=dict(detector='v69_current_Y_contour',coarse_corners=coarse.tolist())
                with recovery_candidate_scope((seed,),True):full,detection=self._detect(image)
            receipt=read_current_receipt(detection,image,gray,scale,index,full)
            detection.pop('_current_boundary_receipt',None)
            if receipt is None:
                detail['reason']='current_candidate_receipt_not_bound';return None
            candidate,evidence,gate=receipt
            if not gate.get('reliable') or not _valid__v87_v74_tracking(candidate,gray.shape,checks=self.checks):
                detail['reason']='current_candidate_final_geometry_invalid';return None
            agreement=gate.get('current_source_agreement',{})
            if not agreement.get('verified'):
                detail['reason']='current_candidate_independent_proof_missing';return None
            self.last_source_confirmation=dict(agreement,final_gate=dict(gate))
            detail.update(verified=True,reason='current_candidate_immediately_admitted',
                same_frame_receipt_reused=True,original_corners_preserved=True)
            return candidate,evidence,dict(state='v69_current_candidate_verified',
                first_validation=gate,source_line_agreement=agreement,quick_current_candidate=detail,
                current_index=index,old_H_not_used=True,stale_receipt_used=False)
        except (ValueError,cv2.error,_DetectionStop) as exc:
            detail.update(reason=str(exc),exception_type=type(exc).__name__);return None
        finally:
            detail.update(wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu,
                budget=compact_recovery_summary(budget.summary()))

    def _local_exterior(self,image,gray,scale,prediction,index):
        """Current source lines only; bounded local proposal before full search.

        Strict new/current independent proof stays mandatory after LOST. This
        routine neither promotes old LK data nor renews any hold timestamp.
        """
        if not self._local_due():return None
        from geometry import sample_locked_color as sample_locked_color; from geometry import search_gate as search_gate
        now=time.perf_counter();cpu=time.thread_time()
        if not getattr(self,'_local_attempts',0):self._local_batch_at=now
        self._local_attempts=getattr(self,'_local_attempts',0)+1;self._local_next_at=now+.20
        deadline=now+.22
        if self._frame_deadline is not None:deadline=min(deadline,self._frame_deadline)
        age=max(0.,now-getattr(self,'_last_physical_at',now))
        radius=max(3.,min(12.,max(self._edge_radius,3.+2.*age)))
        try:
            primary,e=sample_locked_color(image,scale,prediction,64,deadline,self._target_signature,
                half_source=min(24.,radius*float(np.max(scale))),lock_physical=False)
            first=search_gate(e,primary,prediction,radius)
            if not first.get('reliable'):return None
            from geometry import layer_continuity as layer_continuity
            continuity=layer_continuity(self._target_signature,e)
            if not continuity['verified']:return None
            remaining_cpu=.16-(time.thread_time()-cpu)
            if remaining_cpu<=0 or time.perf_counter()>=deadline:return None
            observed,current,gate,agreement=self._source_confirmation(image,gray,primary,e,
                new_candidate=True,radius=radius,reference=prediction,gray_reliable=False,proof_deadline=deadline,proof_cpu_s=remaining_cpu)
            if (time.perf_counter()>deadline or time.thread_time()-cpu>.16
                or not gate.get('reliable') or not agreement.get('verified')
                or not _valid__v87_v74_tracking(observed,gray.shape,self.q,self.checks)):return None
            return observed,current,dict(state='local_current_source_exterior_reacquired',
                first_validation=first,second_validation=gate,source_line_agreement=agreement,
                local_attempt=self._local_attempts,local_wall_s=time.perf_counter()-now,
                local_thread_cpu_s=time.thread_time()-cpu,old_H_not_used=True,
                global_detection_skipped=True,hold_timer_renewed=False,physical_layer_continuity=continuity)
        except (ValueError,cv2.error):return None

    def configure_recovery(self,budget_ms=120.,max_candidates=2,backoff_max_frames=4,reacquire_budget_ms=240.,reacquire_max_candidates=4):
        if isinstance(reacquire_budget_ms,bool) or not np.isfinite(reacquire_budget_ms) or not budget_ms<=reacquire_budget_ms<=500:
            raise ValueError('reacquire_budget_ms must be recovery_budget_ms..500')
        if isinstance(budget_ms,bool) or not np.isfinite(budget_ms) or not 40<=budget_ms<=500:
            raise ValueError('recovery_budget_ms must be 40..500')
        for name,value,low,high in (('recovery_max_candidates',max_candidates,1,8),
                ('recovery_backoff_max_frames',backoff_max_frames,1,8),
                ('reacquire_max_candidates',reacquire_max_candidates,max_candidates,8)):
            if isinstance(value,bool) or not isinstance(value,int) or not low<=value<=high:
                raise ValueError(name+' outside bounded integer range')
        self.recovery_budget_ms=float(budget_ms);self.recovery_max_candidates=max_candidates
        self.recovery_backoff_max_frames=backoff_max_frames
        self.reacquire_budget_ms=float(reacquire_budget_ms);self.reacquire_max_candidates=reacquire_max_candidates

    def _remember_recovery_failure(self,gray,index,prediction,detail):
        # Four owned small-Y snapshots only. Encoding/saving is after formal timing.
        # Retain first + most recent three instead of growing with a long outage.
        if self._recovery_failures>1 and self._recovery_failures%4:return
        item=dict(index=int(index),gray=gray.copy(),corners=prediction.copy(),detail=dict(detail))
        if len(self.recovery_snapshots)>=4:self.recovery_snapshots.pop(1)
        self.recovery_snapshots.append(item)

    def _detect(self, image):
        if self.detector is not None:
            return self.detector(image)
        return detect_refined(image, self.detection_limit, True)

    def _roi_features(self,gray,q,retained=None,variant=0):
        if variant:return self._edge_strip_features(gray,q,retained,variant)
        if self.checks=='auto':
            began=time.perf_counter();native=self.lk_cache.roi_features(gray,q,retained)
            if native is not None:
                points,detail=native
                from geometry import outer_features as outer_features
                before=len(points);points=outer_features(points,q)
                self.last_feature_detail=dict(detail,roi_s=time.perf_counter()-began,
                    outer_band_filter=True,interior_features_removed=before-len(points),features=len(points),
                    added=max(0,len(points)-(0 if retained is None else len(retained))))
                return points
        """Small OUTER-paper corner patches; exclude interior repeating grid.

        Actual GFTT points only. If a textureless sheet gives no usable four
        regions, the existing full boundary seed remains the fallback.
        """
        began=time.perf_counter();h,w=gray.shape
        points=[] if retained is None else list(np.asarray(retained,np.float32).reshape(-1,2))
        before=len(points);regions=0
        for corner in q:
            if sum(float(np.linalg.norm(p-corner))<18 for p in points)>=2:
                continue
            x,y=corner;x0=max(0,int(x)-20);y0=max(0,int(y)-20)
            x1=min(w,int(x)+21);y1=min(h,int(y)+21)
            if min(x1-x0,y1-y0)<7:continue
            qi=np.rint(q-[x0,y0]).astype(np.int32)
            mask=np.zeros((y1-y0,x1-x0),np.uint8)
            cv2.polylines(mask,[qi],True,255,4)
            inside=np.zeros_like(mask);cv2.fillConvexPoly(inside,qi,255)
            mask=cv2.bitwise_and(mask,inside)
            if len(points)>=100:break
            found=cv2.goodFeaturesToTrack(gray[y0:y1,x0:x1],maxCorners=6,
                    qualityLevel=.012,minDistance=5,mask=mask,blockSize=5)
            regions+=1
            if found is None:continue
            for point in found.reshape(-1,2)[:4]+[x0,y0]:
                if len(points)>=100:break
                if not points or min(float(np.linalg.norm(p-point)) for p in points)>4:
                    points.append(point.astype(np.float32))
        out=np.asarray(points,np.float32).reshape(-1,2)
        self.last_feature_detail=dict(action='outer_corner_roi',regions=regions,
            added=len(out)-before,features=len(out),roi_s=time.perf_counter()-began)
        from geometry import outer_features as outer_features
        out=outer_features(out,q);self.last_feature_detail.update(features=len(out),added=max(0,len(out)-before))
        return out


    def _edge_strip_features(self,gray,q,retained,variant):
        """Alternate bounded outer-edge strips after corner patches add nothing."""
        began=time.perf_counter();cpu=time.thread_time();h,w=gray.shape
        if self._roi_mask is None or self._roi_mask.shape!=gray.shape:
            self._roi_mask=np.zeros_like(gray);self._roi_inside=np.zeros_like(gray)
        self._roi_mask.fill(0);self._roi_inside.fill(0)
        qi=np.rint(q).astype(np.int32);cv2.fillConvexPoly(self._roi_inside,qi,255)
        edges=(variant%2,(variant%2)+2)
        for edge in edges:
            a,b=q[edge],q[(edge+1)%4]
            cv2.line(self._roi_mask,tuple(np.rint(a+.12*(b-a)).astype(int)),
                tuple(np.rint(a+.88*(b-a)).astype(int)),255,4)
        cv2.bitwise_and(self._roi_mask,self._roi_inside,dst=self._roi_mask)
        points=[] if retained is None else list(np.asarray(retained,np.float32).reshape(-1,2))
        before=len(points)
        # Two bounded patches; no whole-image feature search, no invented points.
        for edge in edges:
            a,b=q[edge],q[(edge+1)%4]
            x0=max(0,int(min(a[0],b[0]))-5);x1=min(w,int(max(a[0],b[0]))+6)
            y0=max(0,int(min(a[1],b[1]))-5);y1=min(h,int(max(a[1],b[1]))+6)
            if min(x1-x0,y1-y0)<7:continue
            found=cv2.goodFeaturesToTrack(gray[y0:y1,x0:x1],maxCorners=4,qualityLevel=.012,
                minDistance=5,mask=self._roi_mask[y0:y1,x0:x1],blockSize=5)
            if found is None:continue
            for point in found.reshape(-1,2)+[x0,y0]:
                if len(points)>=100:break
                if not points or min(float(np.linalg.norm(p-point)) for p in points)>4:
                    points.append(point.astype(np.float32))
        out=np.asarray(points,np.float32).reshape(-1,2)
        self.last_feature_detail=dict(action='alternate_outer_edge_strips',regions=2,
            variant=variant,added=len(out)-before,features=len(out),workspace_reused=True,
            roi_s=time.perf_counter()-began,roi_thread_cpu_s=time.thread_time()-cpu)
        from geometry import outer_features as outer_features
        out=outer_features(out,q);self.last_feature_detail.update(features=len(out),added=max(0,len(out)-before))
        return out

    def _quality_replenish(self,gray,points,q,quality,evidence):
        from geometry import outer_features as outer_features
        points=outer_features(points,q)
        self._roi_lk_checks+=1
        supported=_spatial_support__v87_v74_tracking(points,q,self.checks)
        reliable=(quality and supported and len(points)>=4 and
            min(evidence.get('edge_support',[0.]*4))>=.8 and max(evidence.get('edge_rms',[1e30]*4))<=.65)
        if reliable and len(points)>=12:
            self.last_feature_detail=dict(action='promote_validated_inliers',features=len(points),roi_s=0.)
            return points
        if reliable and self._roi_lk_checks<self._roi_retry_lk:
            self.last_feature_detail=dict(action='bounded_roi_backoff',features=len(points),added=0,
                roi_s=0.,failures=self._roi_failures,next_retry_lk=self._roi_retry_lk,
                current_lk=self._roi_lk_checks,maximum_skipped_lk_checks=7,
                retained_fb_and_four_edge_checks=True)
            return points
        before=len(points);variant=self._roi_failures%3 if self._roi_failures else 0
        out=self._roi_features(gray,q,points,variant)
        self._roi_last_q=q.copy()
        self._roi_failures=(min(8,self._roi_failures+1) if len(out)<=before else 0)
        # Low-yield refill backs off only while motion, FB inliers, spatial
        # support AND all four measured edges remain trustworthy.
        delay=min(8,1<<min(3,self._roi_failures)) if reliable else 1
        self._roi_retry_lk=self._roi_lk_checks+delay
        # ⭐ 2026-10-28：这次真加了点（`len(out)>before`）且跟踪本来就可靠 ⇒
        #    按 `_roi_search_gap` 隔几帧再搜，而不是下一帧立刻重搜。
        #    只在"可靠但点数仍<12"这种纹理偏少的场景生效，`reliable=False` 的
        #    快速重试路径（delay=1）完全不动。
        if reliable and len(out)>before:
            self._roi_retry_lk=max(self._roi_retry_lk,self._roi_lk_checks+self._roi_search_gap)
        self.last_feature_detail.update(failures=self._roi_failures,next_retry_lk=self._roi_retry_lk,
            current_lk=self._roi_lk_checks,variant=variant,quality_override=not reliable)
        return out

    def _channel_quality(self,plane,q,points):
        # Four short outside/inside bands in the SMALL scalar plane; no full CSC.
        d=np.roll(q,-1,axis=0)-q;length=np.linalg.norm(d,axis=1)
        normal=np.stack((-d[:,1],d[:,0]),axis=1)/np.maximum(length[:,None],1e-6)
        normal*=np.where(np.sum((q.mean(axis=0)-q-d*.5)*normal,axis=1)<0,-1.,1.)[:,None]
        base=q[:,None,:]+np.linspace(.1,.9,12)[None,:,None]*d[:,None,:]
        xy=base[:,:,None,:]+np.array([-3.,3.])[None,None,:,None]*normal[:,None,None,:]
        value=cv2.remap(plane,xy[...,0].reshape(48,2).astype(np.float32),
            xy[...,1].reshape(48,2).astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        per_edge=np.median(np.abs(value[:,1].astype(np.float32)-value[:,0]).reshape(4,12),axis=1)
        spatial=_spatial_support__v87_v74_tracking(points,q,self.checks)
        # A channel must cover the exterior spatially, not only yield many ink points.
        score=(min(len(points),40)/40.)*float(np.mean(np.minimum(per_edge,48.)))*float(spatial)
        return dict(score=score,spatial=bool(spatial),features=len(points),edge_contrast=per_edge.tolist())

    def _seed(self, gray, q, index, source_image=None, same_target=False):
        self._gap_anchor_reuses=0
        self._roi_failures=0;self._roi_retry_lk=0;self._roi_lk_checks=0;self._roi_last_q=None
        def features(plane):
            points=self._roi_features(plane,q) if self.feature_policy=='quality' else np.empty((0,2),np.float32)
            if not _spatial_support__v87_v74_tracking(points,q,self.checks):
                points=self._full_features(plane,q)
                self.last_feature_detail.update(action='full_boundary_fallback',features=len(points))
            return points
        raw=source_image is not None and source_image.ndim==3 and source_image.shape[2]==2
        flow_gray=self._flow_observation(source_image,gray) if raw and self.lk_channel!='Y' else gray
        points=features(flow_gray);quality=self._channel_quality(flow_gray,q,points)
        audit=raw and (not quality['spatial'] or (not same_target and index-self._channel_audit_index>=12))
        chosen=self.lk_channel if raw else 'Y';scores={chosen:quality};feature_detail=dict(self.last_feature_detail)
        if audit:
            current=chosen;best_score=quality['score'];self._channel_audit_index=index
            # Fixed channel per NEW anchor; forward/backward LK never mixes channels.
            for channel in ('Y','U','V'):
                if channel==current:continue
                plane=gray if channel=='Y' else self._chroma_observation(source_image,gray.shape,channel)
                found=features(plane);check=self._channel_quality(plane,q,found);scores[channel]=check
                if check['spatial'] and (not quality['spatial'] or check['score']>best_score*1.2+2.):
                    chosen,flow_gray,points=channel,plane,found
                    quality=check;best_score=check['score'];feature_detail=dict(self.last_feature_detail)
        self.lk_channel=chosen;self._flow_gray=flow_gray;self._flow_cache=None
        self._channel_evidence=dict(selected=chosen,audited=audit,scores=scores,channel_fixed_until_new_anchor=True,
            same_target_channel_retained=bool(same_target and not audit))
        self.last_feature_detail=dict(feature_detail,channel_selection=self._channel_evidence)
        self.anchor_gray=flow_gray;self.observer.pin(gray)
        self.anchor_q=q.copy();self.anchor_points=points.astype(np.float32).reshape(-1,1,2)
        self.anchor_index=index;self.seed_index=index;self.seed_count+=1;self.lk_cache.anchor(flow_gray)

    def _chroma_observation(self,image,shape,channel):
        from geometry import chroma_gray as chroma_gray
        if not self._chroma_pool or self._chroma_pool[0].shape!=tuple(shape):
            self._chroma_pool=[np.empty(shape,np.uint8) for _ in range(3)]
        plane=next(p for p in self._chroma_pool if p is not self.anchor_gray and p is not self._flow_gray)
        chroma_gray(image,shape,channel,plane);self._flow_gray=plane
        return plane

    def _flow_observation(self,image,gray):
        if self.lk_channel=='Y' or image is None:return gray
        if self._flow_cache is not None and self._flow_cache[0]==self._update_index:
            return self._flow_cache[1]
        plane=self._chroma_observation(image,gray.shape,self.lk_channel)
        self._flow_cache=(self._update_index,plane)
        return plane

    def _full_features(self,gray,q):
        mask = np.zeros_like(gray)
        qi = np.rint(q).astype(np.int32)
        cv2.polylines(mask, [qi], True, 255, 4)
        inside = np.zeros_like(gray)
        cv2.fillConvexPoly(inside, qi, 255)
        mask = cv2.bitwise_and(mask, inside)
        points = cv2.goodFeaturesToTrack(gray, maxCorners=96, qualityLevel=.012,
                                        minDistance=5, mask=mask, blockSize=5)
        points = np.empty((0, 2), np.float32) if points is None else points.reshape(-1, 2)
        for corner in (q if self.feature_policy=='legacy' else ()):
            if not len(points) or np.min(np.linalg.norm(points-corner, axis=1)) > 2:
                points = np.vstack((points, corner))
        from geometry import outer_features as outer_features
        return outer_features(points,q)

    def initialize(self, image, quad=None, index=1, initial_evidence=None, initial_detection=None):
        if quad is None:
            quad, detection = self._detect(image)
        else:
            detection = initial_detection if isinstance(initial_detection,dict) else {'state': 'supplied_first_frame_detection'}
        if initial_evidence is None:initial_evidence=detection.get('tracking_edge_evidence',{})
        # A hint selects the CURRENT verifier. Only a single-use receipt bound
        # to this still-leased source permits same-frame proof reuse.
        self._vector_boundary=bool(initial_evidence.get('color_vector_proof'))
        gray, scale = self.observer.get(image)
        self.last_gray=gray
        self._update_index=index;self.current_proofs.begin(image,gray,index,scale)
        q = (np.asarray(quad, np.float32)+.5)/scale-.5
        if not _valid__v87_v74_tracking(q, gray.shape,checks=self.checks):
            raise ValueError('首帧纸张四角无效或已超出画面')
        self.shape, self.scale = image.shape, scale
        self.q = q.astype(np.float32)
        from geometry import consume_startup_receipt as consume_startup_receipt
        receipt=consume_startup_receipt(detection,image,quad,scale)
        if receipt is not None:
            primary,source,source_gate,agreement=receipt
        else:
            # External/mismatched corners receive a fresh proof. Never reuse an
            # old source receipt or let unreliable small Y shift this original.
            checked,evidence=edge_measure__v87_v74_tracking(gray,self.q,3.,checks=self.checks)
            initial_gate=exterior_gate(evidence,checked,self.q,3.)
            original=self.q.copy()
            gray_trusted=bool(initial_gate.get('reliable') and initial_gate.get('min_support',0.)>=.80
                and initial_gate.get('max_rms',1e30)<=.65 and initial_gate.get('prediction_correction',1e30)<=.75)
            primary,source,source_gate,agreement=self._source_confirmation(image,gray,
                checked if gray_trusted else original,evidence,new_candidate=True,radius=3.,
                reference=original,gray_reliable=gray_trusted)
        if not source_gate.get('reliable') or not agreement.get('verified') or not _valid__v87_v74_tracking(primary,gray.shape,checks=self.checks):
            from core import checkpoint as checkpoint
            checkpoint('INITIAL_CURRENT_LINE_PROOF_FAILED',gate=source_gate,agreement=agreement,
                source_corners=np.asarray(quad).tolist(),hardware_access=False)
            raise ValueError('首帧物理外框未通过当前源图独立四边证明: '+str(agreement.get('reason','four_edge_disagreement')))
        checked,evidence,initial_gate=primary,source,source_gate
        detection.update(initial_source_line_agreement=agreement,original_primary_preserved=True)
        self.q=checked.astype(np.float32)
        self.edge_polarity = evidence['edge_polarity']
        self._vector_boundary=bool(evidence.get('color_vector_proof'))
        from geometry import border_signature as border_signature
        self._target_signature=border_signature(evidence)
        detection=dict(detection,initial_edge_gate=initial_gate)
        self.velocity[:] = 0
        self._lk_budget_deferrals=0
        self._seed(gray, self.q, index, image)
        self.last_index = index
        self.started, self.lost = True, False
        self.state='TRACKING'
        self._last_physical_at=time.perf_counter();self._local_next_at=0.;self._local_attempts=0
        return self.corners(), detection

    def write_corners(self,out):
        if out.shape!=(4,2) or out.dtype!=np.float32:raise ValueError('Corner workspace must be4x2 float32')
        np.add(self.q,.5,out=out);np.multiply(out,self.scale,out=out);np.subtract(out,.5,out=out)
        return out

    def corners(self):
        return self.write_corners(np.empty((4,2),np.float32))

    def _lk(self, gray, prediction=None, fast=False, source_image=None):
        attempts=list(self.last_lk_timing.get('attempts',()))
        began=time.perf_counter();cpu=time.thread_time();failure=None
        self.lk_cache.last_checked_timing={}
        self.post_lk.clear();self.post_lk.detail={}
        try:return self._lk_impl(gray,prediction,fast,source_image)
        except BaseException as exc:
            failure=str(exc);raise
        finally:
            detail=dict(self.last_lk_timing,**self.lk_cache.last_checked_timing)
            detail['postlk_native_transaction']=dict(self.post_lk.detail)
            self.post_lk.clear()
            detail.pop('attempts',None)
            detail.update(search='fast' if fast else 'full',accepted=failure is None,
                reason=failure,wall_s=time.perf_counter()-began,thread_cpu_s=time.thread_time()-cpu)
            attempts.append(detail)
            self.last_lk_timing=dict(detail,attempts=attempts,attempt_count=len(attempts),
                total_attempt_wall_s=sum(v['wall_s'] for v in attempts),
                total_attempt_thread_cpu_s=sum(v['thread_cpu_s'] for v in attempts))

    @geometry_transaction
    def _lk_impl(self, gray, prediction=None, fast=False, source_image=None):
        began=time.perf_counter()
        self.last_lk_timing={}
        flow_gray=self._flow_observation(source_image,gray)
        p = self.anchor_points
        if len(p)<4:raise ValueError('外边框有效特征少于4个')
        params = dict(winSize=(21, 21), maxLevel=3,
                      criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 20, .02))
        initial=None
        if prediction is not None:
            self._lk_anchor_quad[:]=self.anchor_q;self._lk_prediction_quad[:]=prediction
            motion=cv2.getPerspectiveTransform(self._lk_anchor_quad,self._lk_prediction_quad)
            initial=self._lk_initial[:len(p)]
            cv2.perspectiveTransform(p,motion,dst=initial)
        if fast:params.update(maxLevel=2,criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,12,.02))
        checked=self.lk_cache.checked(flow_gray,p,initial,self.anchor_q,self.q,self.last_index,params['maxLevel'],params['criteria'][1]) if self.checks=='auto' else None
        native=None if checked is not None else self.lk_cache.track(flow_gray,p,initial=initial,levels=params['maxLevel'],iterations=params['criteria'][1])
        if checked is not None:
            q,retained,filter_detail,times=checked;self.last_lk_timing.update(times)
            fit_began=time.perf_counter()
        else:
            if native is None:
                forward, status, error = cv2.calcOpticalFlowPyrLK(self.anchor_gray, flow_gray, p, initial,
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW if initial is not None else 0, **params)
            else:
                forward,status,error,backward,status_b=native
            if forward is None:
                raise ValueError('LK 没有返回特征')
            if native is None:
                backward, status_b, _ = cv2.calcOpticalFlowPyrLK(flow_gray, self.anchor_gray, forward, p.copy(),
                    flags=cv2.OPTFLOW_USE_INITIAL_FLOW, **params)
            if backward is None:
                raise ValueError('LK 反向跟踪失败')
            self.last_lk_timing['forward_backward_flow_s']=time.perf_counter()-began
            fit_began=time.perf_counter()
            filtered=filter_lk__v87_v74_native(p,forward,backward,status,status_b,error,self.anchor_q,self.q,gray.shape) if self.checks=='auto' else None
            if filtered is not None:
                q,retained,filter_detail=filtered
            else:
                fb = np.linalg.norm(backward.reshape(-1, 2)-p.reshape(-1, 2), axis=1)
                good = status.ravel().astype(bool) & status_b.ravel().astype(bool)
                good &= (fb < 1.4) & (error.ravel() < 30)
                if good.sum() < 4:
                    raise ValueError('外边框有效特征少于4个')
                a=p.reshape(-1,2)[good];z=forward.reshape(-1,2)[good]
                motion_model='projective_candidate'
                if len(a)<8:
                    affine,inliers=cv2.estimateAffinePartial2D(a,z,method=cv2.RANSAC,
                        ransacReprojThreshold=1.6,maxIters=1000,confidence=.99,refineIters=10)
                    H=None if affine is None else np.vstack((affine,[0.,0.,1.]))
                    motion_model='similarity_candidate'
                else:
                    H,inliers=cv2.findHomography(a,z,cv2.RANSAC,1.6,maxIters=1000,confidence=.99)
                    if H is not None and inliers is not None and inliers.sum()<8:
                        affine,inliers=cv2.estimateAffinePartial2D(a,z,method=cv2.RANSAC,
                            ransacReprojThreshold=1.6,maxIters=1000,confidence=.99,refineIters=10)
                        H=None if affine is None else np.vstack((affine,[0.,0.,1.]))
                        motion_model='similarity_candidate'
                if H is None or not np.isfinite(H).all() or inliers is None:
                    raise ValueError('边框特征不能确定运动映射')
                retained=forward.reshape(-1,2)[good][inliers.ravel().astype(bool)]
                original=p.reshape(-1,2)[good][inliers.ravel().astype(bool)]
                if not _spatial_support__v87_v74_tracking(original,self.anchor_q,self.checks):
                    raise ValueError("边缘特征分布退化，不能只凭RANSAC内点率")
                fraction = float(inliers.mean())
                if inliers.sum() < 4 or fraction < .65:
                    raise ValueError('边框特征几何一致性不足')
                q = cv2.perspectiveTransform(self.anchor_q.reshape(1, 4, 2), H).reshape(4, 2)
                if not _valid__v87_v74_tracking(q, gray.shape, self.q,self.checks):
                    raise ValueError('跟踪四角越界或形变异常')
                filter_detail=dict(features=len(p),good_features=int(good.sum()),
                    inlier_fraction=fraction,fb_median=float(np.median(fb[good])),filter_backend='opencv_python_ransac',motion_model=motion_model,
                    current_four_edges_required=True)
        if checked is None:self.last_lk_timing['fb_filter_ransac_s']=time.perf_counter()-fit_began
        self.last_lk_timing['motion_fit']=dict(filter_detail)
        travel=float(np.max(np.linalg.norm(q-self.q,axis=1)))
        shortest=float(np.min(np.linalg.norm(np.roll(q,-1,axis=0)-q,axis=1)))
        cap=max(3.,min(7.5,.06*shortest,24./float(np.max(self.scale))))
        radius=float(np.clip(max(3.,self._edge_radius)+.10*travel,3.,cap))
        unlocked_radius=radius
        static_reference=bool(self._still_calm and self._still_q is not None)
        if static_reference:
            # LK remains complete. Its raw motion model can release the lock
            # before CURRENT edge selection, independently of output smoothing.
            lock_motion=float(np.max(np.linalg.norm(q-self._still_q,axis=1)))
            if lock_motion>1.:
                self._release_static_edges('current_FB_motion')
            else:
                q=self._still_q.copy();radius=self._still_radius
        # ⭐ 2026-10-28 计时：post_lk 一次 native 事务（24网格+64网格）的完整墙钟，
        #    与它自己报的 `transaction_s` 对比即可看出 Python 侧的包装开销。
        postlk_t=time.perf_counter()
        fused=self.post_lk.measure(gray,q,radius,source_image,self.scale,self._update_index,self.checks,self.edge_polarity)
        self.last_lk_timing['postlk_measure_s']=time.perf_counter()-postlk_t
        measured,evidence=edge_measure__v87_v74_tracking(gray,q,radius,self.checks) if fused is None else fused
        from geometry import search_gate as search_gate; from geometry import sample_locked_color as sample_locked_color
        from geometry import border_signature as border_signature
        def current_search(e,c):
            g=search_gate(e,c,q,radius)
            flips=0 if e.get('color_vector_proof') else sum(a*b<0 for a,b in zip(self.edge_polarity,e.get('edge_polarity',[])))
            return dict(g,reliable=bool(g['reliable'] and flips==0),polarity_flips=flips)
        lk_gate=current_search(evidence,measured)
        if source_image is not None and not lk_gate['reliable']:
            measured,evidence=sample_locked_color(source_image,self.scale,q,64,self._frame_deadline,
                self._target_signature,half_source=min(24.,max(3.,radius*float(np.max(self.scale)))),
                lock_physical=bool(self._still_calm))
            lk_gate=current_search(evidence,measured)
        lock_required=bool(unlocked_radius>3. or lk_gate.get('prediction_correction',0.)>1.5 or evidence.get('color_vector_proof'))
        if lk_gate['reliable'] and lock_required:
            # Wider first search cannot justify itself. Independently spaced
            # source Y64 (or YUV64) must agree with all four refined edges.
            from geometry import stable_fb_context as stable_fb_context
            stable_fb=stable_fb_context(filter_detail,travel,lk_gate['prediction_correction'],
                self.lost,getattr(self,'source_elapsed_s',None),
                processing_gap=bool(getattr(self,'source_processing_gap',False)))
            second,independent,strict_gate,agreement=self._source_confirmation(source_image,gray,measured,evidence,
                radius=radius,reference=q,gray_reliable=lk_gate['reliable'],stable_fb=stable_fb)
            self.last_lk_timing['stable_FB_context']=stable_fb
            verified=(strict_gate is not None and strict_gate['reliable'] and agreement['verified']
                and _valid__v87_v74_tracking(second,gray.shape,self.q,self.checks))
            self.last_lk_timing['source_line_agreement']=agreement
            self.last_lk_timing['independent_source_gate']=strict_gate
            lk_gate['independent_source_verified']=bool(verified)
            if verified:measured,evidence=second,independent
            else:lk_gate['reliable']=False
        self.last_lk_timing['motion_adaptive_exterior_radius']=radius
        self.last_lk_timing['search_proof_separated']=True
        if not lk_gate['reliable']:
            self.last_lk_timing['failed_exterior_gate']=dict(lk_gate)
            self.last_lk_timing['failed_LK_corners']=q.tolist()
            self.last_lk_timing.update(failure_class='current_exterior_mismatch',
                redundant_full_retry_skipped=True)
            raise LKExteriorMismatch__v87_v74_tracking('LK 四角未通过四条纸张外边缘检查')
        self.last_lk_timing['current_four_edge_gate']=dict(lk_gate)
        self._promoted_points=np.ascontiguousarray(retained,dtype=np.float32)
        return measured, dict(evidence, **filter_detail)

    def _boundary(self,*args,**kwargs):
        kwargs.setdefault('prefer_vector',self._vector_boundary)
        kwargs.setdefault('boundary_prior',self._target_signature)
        candidate,evidence,gate=current_boundary(*args,**kwargs)
        if gate.get('reliable') and evidence.get('color_vector_proof'):self._vector_boundary=True
        return candidate,evidence,gate

    @geometry_transaction
    def _source_confirmation(self,image,gray,candidate,evidence,new_candidate=False,radius=3.,
            reference=None,gray_reliable=None,stable_fb=False,proof_deadline=None,proof_cpu_s=None):
        """Wide candidate search is separate from a narrow current-line proof.

        Normal tracking locks the measured CURRENT line. New admission may
        search from its immutable proposal, then locks its current source64
        line. Independent 24/64 samples never receive the motion search band.
        """
        from geometry import actual_source64 as actual_source64; from geometry import array_key as array_key
        from geometry import original_y_boundary as original_y_boundary
        from geometry import border_signature as border_signature
        from geometry import proof_band as proof_band; from geometry import line_lock as line_lock; from geometry import current_agreement as current_agreement; from geometry import declare_current_y24 as declare_current_y24; from geometry import sample_locked_color as sample_locked_color; from geometry import search_gate as search_gate
        narrow,half=proof_band(self.scale,evidence)
        entry_s=time.perf_counter()
        prepared=(self.post_lk.take_source(image,gray,candidate,self.scale,self._update_index,narrow)
            if not new_candidate and gray_reliable is not False and proof_deadline is None and proof_cpu_s is None else None)
        decode_s=time.perf_counter()-entry_s
        begin=time.perf_counter() if prepared is None else prepared['begin']
        cpu=time.thread_time() if prepared is None else prepared['cpu'];deadline=begin+.40
        cpu_limit=.18 if new_candidate else .12
        if proof_deadline is not None:deadline=min(deadline,float(proof_deadline))
        if proof_cpu_s is not None:cpu_limit=min(cpu_limit,max(0.,float(proof_cpu_s)))
        wall_limit=max(0.,deadline-begin)
        proof_gate_radius=3.  # Keep geometry allowance independent of sample width.
        details=dict(budget_basis='proof_thread_CPU_and_separate_wall_guard',
            cpu_budget_s=cpu_limit,wall_guard_s=wall_limit,prior_frame_deadline_not_reused=proof_deadline is None,
            search_radius_tracking=float(radius),proof_radius_tracking=narrow,
            proof_half_source_pixels=half,proof_gate_radius=proof_gate_radius,
            motion_search_band_reused_for_proof=False,
            strict_new_candidate=bool(new_candidate),same_target_FB=bool(stable_fb and not new_candidate),
            postlk_native_source_prepared=prepared is not None,repeated_source_sampling_skipped=prepared is not None,
            # ⭐ 2026-10-28 计时：take_source 解码（复用 post_lk 缓冲）本身的耗时。
            decode_s=decode_s)
        memo_token=None
        def available():return time.perf_counter()<deadline and time.thread_time()-cpu<cpu_limit
        def gate(e,q,p,r):
            return exterior_gate(e,q,p,r) if new_candidate else self._edge_gate(e,q,p,r)
        def done(q,e,g,a):
            if memo_token is not None and g.get('reliable') and a.get('verified'):
                self.current_proofs.remember(memo_token,q,e,g,a)
            details.update(wall_s=time.perf_counter()-begin,thread_cpu_s=time.thread_time()-cpu,
                wall_guard_hit=time.perf_counter()>=deadline,cpu_budget_hit=time.thread_time()-cpu>=cpu_limit,
                scope='cooperative between calls; native calls cannot be preempted')
            a=dict(a,current_proof_timing=dict(details),old_H_not_used=True)
            self.last_source_confirmation=dict(a,final_gate=dict(g))
            return q,e,g,a
        failed=dict(reliable=False)
        if image is None:return done(candidate,dict(valid=False),failed,dict(verified=False,reason='no_current_source'))
        key=array_key(image);candidate=np.asarray(candidate,np.float32).copy()
        reference=np.asarray(candidate if reference is None else reference,np.float32).copy()
        if gray_reliable is None:
            gray_reliable=bool(gate(evidence,candidate,reference,radius).get('reliable'))
        memo_token=self.current_proofs.token(image,gray,self._update_index,self.scale,candidate,reference,
            radius,new_candidate,gray_reliable,stable_fb)
        reused_result=self.current_proofs.get(memo_token)
        if reused_result is not None:
            q,e,g,a=reused_result
            a=dict(a,current_same_frame_proof_reused=True,repeated_border_search_skipped=True,
                current_proof_timing=dict(metadata_receipt_reuse=True,wall_s=time.perf_counter()-begin,
                    thread_cpu_s=time.thread_time()-cpu,native_sampling_repeated=False))
            self.last_source_confirmation=dict(a,final_gate=dict(g))
            return q,e,g,a
        details.update(original_reference_preserved=True,reference_corners=reference.tolist(),
            gray_reliable=bool(gray_reliable),color_seed='original_reference' if new_candidate else 'current_locked_line')
        # Strong CURRENT Y and independently spaced source-Y64 share a narrow
        # normal neighborhood. A historical color hint cannot override this.
        if gray_reliable and evidence.get('valid') and not evidence.get('color_vector_proof') and (available() or prepared is not None):
            # Finish the original gates for already completed CURRENT source64;
            # no new search may use the completed-call budget exception.
            proof=original_y_boundary(image,self.scale,candidate,radius=narrow) if prepared is None else prepared['proof']
            if proof is not None:
                yq,ye=proof;yg=gate(ye,yq,candidate,proof_gate_radius);lock=line_lock(candidate,yq)
                first=declare_current_y24(evidence)
                ya=current_agreement(candidate,yq,first,ye,self.scale,key,
                    stable_fb=stable_fb and not new_candidate)
                details['Y_attempt']=dict(gate=yg,agreement=ya,line_lock=lock)
                details['y_gate_wall_s']=time.perf_counter()-begin
                if yg.get('reliable') and ya.get('verified') and lock.get('verified'):
                    ya.update(boundary_definition='locked_current_Y24_independent_source_Y64',
                        current_source64_reused=prepared is not None,line_lock=lock)
                    return done(yq,ye,yg,ya)
        if not available():
            return done(candidate,evidence,failed,dict(verified=False,reason='current_proof_budget_exhausted',deadline_hit=True))
        # For new candidates only, obtain a broad current source64 primary from
        # the untouched transported proposal. Unreliable gray cannot move it.
        search=reference if new_candidate else candidate
        reused=bool(actual_source64(evidence,key) and evidence.get('color_vector_proof'))
        primary,source=candidate,evidence;paired_secondary=None;pair_detail={}
        pair_trusted=bool(not new_candidate and stable_fb and gray_reliable and evidence.get('valid')
            and not evidence.get('color_vector_proof') and min(evidence.get('edge_support',[0.]*4))>=.80
            and max(evidence.get('edge_rms',[1e30]*4))<=.65
            and gate(evidence,candidate,reference,radius).get('prediction_correction',1e30)<=.75)
        if pair_trusted and not reused:
            from geometry import sample_locked_pair as sample_locked_pair
            paired=sample_locked_pair(image,self.scale,candidate,deadline,evidence,half,
                max(.0005,cpu_limit-(time.thread_time()-cpu)))
            if paired is not None:
                (primary,source),paired_secondary,pair_detail=paired
                details['paired_native_transaction']=pair_detail
        if not reused:
            if paired_secondary is not None:
                first=gate(source,primary,candidate,proof_gate_radius)
            elif new_candidate:
                primary,source=sample_locked_color(image,self.scale,search,64,deadline,
                    half_source=min(24.,max(3.,float(radius)*float(np.max(self.scale)))),lock_physical=False)
                first=search_gate(source,primary,search,radius)
            else:
                primary,source=sample_locked_color(image,self.scale,search,64,deadline,border_signature(evidence),half_source=half,lock_evidence=evidence)
                first=gate(source,primary,search,proof_gate_radius)
            details['color_primary_gate']=first
            provenance=actual_source64(source,key)
            if not first.get('reliable') or not provenance:
                return done(primary,source,failed,dict(verified=False,
                    reason='current_raw_source64_shift_or_quality_rejected' if provenance else 'current_raw_source64_not_completed',
                    deadline_hit=source.get('deadline_hit',False),source64_provenance_verified=bool(provenance),rejected_gate=dict(first)))
        if not new_candidate and source.get('color_vector_proof'):
            from geometry import layer_continuity as layer_continuity
            continuity=layer_continuity(self._target_signature,source)
            details['physical_layer_continuity']=continuity
            if not continuity['verified']:
                return done(primary,source,failed,dict(verified=False,reason='current_signed_physical_layer_changed'))
        # Stable tracking fixes BOTH sample layouts around one current measured
        # line. New admission fixes them around its just-measured source64 line.
        if new_candidate:
            narrow,half=proof_band(self.scale,source)
            details.update(proof_radius_tracking=narrow,proof_half_source_pixels=half)
            if reused:
                first=search_gate(source,primary,reference,radius)
                details['color_primary_gate']=first
                if not first.get('reliable'):
                    return done(primary,source,failed,dict(verified=False,reason='reused_primary_search_bounds_rejected'))
        # A weak/broad tracking-Y line is a search proposal. A fresh strong
        # source64 line can establish the narrow reference after bounded
        # same-target checks, rather than proving a different old-Y layer.
        gray_search_gate=gate(evidence,candidate,reference,radius)
        gray_trusted=bool(gray_reliable and evidence.get('valid') and not evidence.get('color_vector_proof') and
            gray_search_gate.get('prediction_correction',1e30)<=.75 and
            min(evidence.get('edge_support',[0.]*4))>=.80 and
            max(evidence.get('edge_rms',[1e30]*4))<=.65)
        raw_lock=line_lock(candidate,primary)
        raw_rebase=bool(not new_candidate and not gray_trusted and actual_source64(source,key)
            and source.get('valid') and source.get('supported_edges')==4
            and min(source.get('edge_support',[0.]*4))>=.80
            and max(source.get('edge_rms',[1e30]*4))<=.65
            and raw_lock.get('line_normal_difference',1e30)<=1.25
            and raw_lock.get('corner_difference',1e30)<=2.)
        details['fresh_source64_reference']=dict(used=raw_rebase,raw_shift=raw_lock,
            old_tracking_Y_is_proposal_only=raw_rebase,independent24_still_required=True)
        locked=np.asarray(primary if new_candidate or raw_rebase else candidate,np.float32).copy()
        primary_lock=line_lock(locked,primary)
        if not primary_lock.get('verified'):
            return done(primary,source,failed,dict(verified=False,reason='source64_left_locked_current_line',line_lock=primary_lock))
        # A completed native pair may finish its existing safety gates after
        # the compute checkpoint; it must not start another sampling call.
        complete_pair=bool(paired_secondary is not None and pair_detail.get('complete'))
        if not available() and not complete_pair:
            return done(primary,source,failed,dict(verified=False,reason='independent_proof_budget_exhausted',deadline_hit=True))
        if paired_secondary is not None and np.array_equal(locked,candidate):
            observed,current=paired_secondary
        else:observed,current=sample_locked_color(image,self.scale,locked,24,deadline,border_signature(source),half_source=half,lock_evidence=source)
        checked=gate(current,observed,locked,proof_gate_radius)
        secondary_lock=line_lock(locked,observed)
        agreement=current_agreement(observed,primary,current,source,self.scale,key,
            stable_fb=stable_fb and not new_candidate)
        agreement.update(verified=bool(agreement.get('verified') and primary_lock.get('verified') and secondary_lock.get('verified')),
            current_source64_reused=reused,boundary_definition='locked_current_source64_and_independent24',
            normal_half_window_source_pixels=half,secondary_radius_tracking=narrow,
            primary_line_lock=primary_lock,secondary_line_lock=secondary_lock,
            independent_deadline_hit=current.get('deadline_hit',False),
            current_primary_prior_used=border_signature(source) is not None)
        if not secondary_lock.get('verified'):agreement['reason']='independent24_left_locked_current_line'
        return done(primary,source,checked,agreement)

    def _edge_gate(self,evidence,candidate,prediction,radius):
        supports=evidence.get('edge_support',[0.]*4)
        rms=evidence.get('edge_rms',[1e30]*4)
        correction=float(np.max(np.linalg.norm(candidate-prediction,axis=1)))
        raw_flips=sum(a*b<0 for a,b in zip(self.edge_polarity,evidence.get('edge_polarity',[])))
        # Weak Y can reverse sign on a chromatic exterior. Its raw sign is
        # diagnostic only after the coherent current YUV proof passes all
        # four support/RMS/geometry gates; ordinary Y keeps its polarity gate.
        flips=0 if evidence.get('color_vector_proof') else raw_flips
        reliable=(evidence.get('valid',False) and evidence.get('supported_edges',0)==4
            and evidence.get('refined_corners',0)==4 and min(supports)>=.60
            and max(rms)<=1.0 and correction<=radius*.65 and flips==0)
        return dict(reliable=bool(reliable),min_support=float(min(supports)),max_rms=float(max(rms)),
            prediction_correction=correction,polarity_flips=flips,raw_Y_polarity_flips=raw_flips,radius=radius)

    def _stabilize_current_edges(self,image,gray,candidate,evidence,gate,prediction,previous):
        """Current profiles decide every output; joint geometry only selects work."""
        result=self.stability.measure(gray,previous,prediction,candidate,evidence,
            allow_filter=not evidence.get('color_vector_proof',False))
        if result is None:return candidate,evidence,gate,False
        filtered,updated,detail=result;self.stability_detail=detail
        self._last_measured_motion=detail['raw_motion']
        if detail['physical_layer_suspect']:
            now=time.perf_counter();detail['local_lock_attempted']=False
            if now>=self._edge_lock_next_at:
                detail['local_lock_attempted']=True;cpu=time.thread_time()
                # One narrow CURRENT Y measurement around the physical prediction.
                tight,tight_e=edge_measure__v87_v74_tracking(gray,prediction,1.75,self.checks)
                tight_g=self._edge_gate(tight_e,tight,prediction,1.75)
                from geometry import line_lock as line_lock
                lock=line_lock(prediction,tight)
                strong=(tight_g.get('reliable') and tight_g['min_support']>=.80
                    and tight_g['max_rms']<=.65 and lock.get('verified'))
                if strong:
                    q,e,g,a=self._source_confirmation(image,gray,tight,tight_e,reference=prediction,
                        gray_reliable=True,radius=1.75,proof_deadline=min(now+.18,self._frame_deadline or now+.18),
                        proof_cpu_s=max(0.,.08-(time.thread_time()-cpu)))
                    strong=bool(g.get('reliable') and a.get('verified') and line_lock(prediction,q).get('verified'))
                    if strong:
                        detail.update(local_lock_verified=True,local_lock_wall_s=time.perf_counter()-now,
                            local_lock_thread_cpu_s=time.thread_time()-cpu,current_source_proof_reused=False)
                        self._edge_lock_failures=0;self._edge_lock_next_at=0.
                        self._current_motion_values=None;self.accumulated_drift[:]=self._stability_drift_start
                        return q,e,g,True
                self._edge_lock_failures=min(3,self._edge_lock_failures+1)
                self._edge_lock_next_at=now+min(.6,.15*(2**(self._edge_lock_failures-1)))
                detail.update(local_lock_verified=False,local_lock_wall_s=time.perf_counter()-now,
                    local_lock_thread_cpu_s=time.thread_time()-cpu,next_local_lock_at=self._edge_lock_next_at)
            # Do not authorize an isolated layer jump by four-corner geometry alone.
            return candidate,evidence,dict(gate,reliable=False,physical_layer_ambiguous=True),False
        if detail['filtered']:
            checked=self._edge_gate(updated,filtered,prediction,self._edge_radius)
            if checked.get('reliable'):
                self._current_motion_values=None;self.accumulated_drift[:]=self._stability_drift_start
                return filtered,updated,checked,False
            detail.update(filtered=False,filter_rejected_by_original_gate=True)
        return candidate,evidence,gate,False

    def _exit_verified_calm_burst(self,mode,candidate,previous,prediction,index):
        """Exit only after complete CURRENT FB plus independent same-edge proof."""
        if mode!='lk_measured' or self.anchor_index!=index:return
        timing=self.last_lk_timing;proof=timing.get('source_line_agreement',{})
        gate=timing.get('current_four_edge_gate',{})
        motion=float(np.max(np.linalg.norm(candidate-previous,axis=1)))
        correction=float(np.max(np.linalg.norm(candidate-prediction,axis=1)))
        normalized=motion/max(1.,float(getattr(self,'source_step',1.)))
        okay=('forward_backward_flow_s' in timing and timing.get('stable_FB_context',False)
            and proof.get('verified') and gate.get('reliable') and gate.get('min_support',0.)>=.80
            and gate.get('max_rms',1e30)<=.65 and motion<=1.25 and normalized<=.45 and correction<=.75
            and len(self.anchor_points)>=4)
        timing['calm_burst_exit']=dict(verified=bool(okay),motion_pixels=motion,
            motion_per_capture_frame=normalized,prediction_correction=correction,
            complete_FB_and_independent_edges_required=True)
        if okay:
            self._burst_until=index-1
            self.motion_ema=min(self.motion_ema,normalized);self.correction_ema=min(self.correction_ema,correction)
            self.accumulated_drift.fill(0.);self.drift_budget=0.
            self._edge_lock_failures=0;self._edge_lock_next_at=0.

    def _motion_schedule(self,gate,candidate,prediction,previous,age):
        values=self._current_motion_values;self._current_motion_values=None
        if values is None:
            values=motion_values__v87_v74_native(candidate,prediction,previous,self.anchor_q,self.accumulated_drift) if self.checks=='auto' else None
        if values is None:
            motion=float(np.max(np.linalg.norm(candidate-previous,axis=1)))
            self.accumulated_drift+=(candidate-prediction)
            drift=float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))
            diagonal=float(np.linalg.norm(previous[2]-previous[0]))
            travel=float(np.max(np.linalg.norm(candidate-self.anchor_q,axis=1)))
        else:motion,_,drift,diagonal,travel=values
        source_step=max(1.,float(getattr(self,'source_step',1.)))
        normalized=motion/source_step
        elapsed=getattr(self,'source_elapsed_s',None)
        self.motion_ema=.8*self.motion_ema+.2*normalized
        self._last_measured_motion=float(motion)
        self.correction_ema=.8*self.correction_ema+.2*gate['prediction_correction']
        self.drift_budget+=max(0.,gate['prediction_correction']-.75*gate['max_rms'])
        quality=max(.25,min(1.,gate['min_support']))
        target=max(self.lk_min_gap,min(self.lk_max_gap,round(self.lk_max_gap*quality/(1.+.45*self.motion_ema+.7*self.correction_ema))))
        urgent=(motion>4. or normalized>2. or gate['prediction_correction']>1.5
                or gate['min_support']<.75 or gate['max_rms']>.75)
        if urgent:self._burst_until=self._update_index+3
        # Confidence/motion can override the quiet-scene minimum. FB is never
        # skipped; a successful check promotes current points/pyramids together.
        burst=self._update_index<=self._burst_until
        reason=('hard_maximum_age' if age>=self.lk_max_gap else
                'motion_burst' if burst and age>=1 else
                'accumulated_drift' if age>=self.lk_min_gap and (drift>2. or self.drift_budget>6.) else
                'anchor_displacement' if age>=self.lk_min_gap and travel>max(16.,max(1.,diagonal)*.18) else
                'adaptive_age' if age>=target else None)
        return reason,dict(target_gap=target,hard_max_gap=self.lk_max_gap,min_gap=self.lk_min_gap,
            motion_pixels=motion,motion_per_capture_frame=normalized,source_step=source_step,
            source_elapsed_s=elapsed,processing_gap=bool(getattr(self,'source_processing_gap',False)),motion_ema=self.motion_ema,correction_ema=self.correction_ema,
            burst_active=burst,burst_until_processed_frame=self._burst_until,
            accumulated_drift_pixels=drift,accumulated_excess_residual=self.drift_budget,
            anchor_travel_pixels=travel,min_support=gate['min_support'],prediction_correction=gate['prediction_correction'])

    def _lk_current(self,gray,prediction,image):
        from geometry import LKPhaseBudget as LKPhaseBudget; from geometry import LKWorkBudgetExceeded as LKWorkBudgetExceeded
        budget=LKPhaseBudget();prior_deadline=self._frame_deadline
        self._frame_deadline=budget.deadline
        displacement=float(np.max(np.linalg.norm(prediction-self.anchor_q,axis=1)))
        deep=(displacement>12. or float(getattr(self,'source_step',1.))>=6.)
        started=time.perf_counter()
        try:
            try:
                candidate,evidence=self._lk(gray,prediction,fast=not deep,source_image=image)
                self.last_lk_timing.update(search_policy='direct_full_large_motion' if deep else 'predicted_fast',
                    predicted_anchor_displacement=displacement)
                return candidate,evidence
            except LKExteriorMismatch__v87_v74_tracking:
                self._promoted_points=None
                raise  # Repeating the same motion solve cannot prove another edge.
            except (ValueError,cv2.error) as exc:
                self._promoted_points=None
                if deep:raise
                if not budget.retry_allowed():
                    raise LKWorkBudgetExceeded('Complete fast FB attempt finished; full retry deferred by CPU/wall guard') from exc
                spent=time.perf_counter()-started
                candidate,evidence=self._lk(gray,prediction,fast=False,source_image=image)
                self.last_lk_timing.update(search_policy='full_after_fast',fast_attempt_s=spent,
                    predicted_anchor_displacement=displacement)
                return candidate,evidence
        finally:
            self.last_lk_timing['entry_budget']=budget.summary()
            self._frame_deadline=prior_deadline

    def _strict_current_reanchor(self,image,gray,prediction,candidate,evidence):
        radius=self._edge_radius
        gate=self._edge_gate(evidence,candidate,prediction,radius)
        if not gate['reliable']:
            candidate,evidence,_=self._boundary(image,gray,self.scale,prediction,
                measured=candidate,evidence=evidence,checks=self.checks,radius=radius,fast_only=True,deadline=self._frame_deadline,
                expected_polarity=self.edge_polarity,color_profiles=64,prefer_color=True,prefer_vector=True)
            gate=self._edge_gate(evidence,candidate,prediction,radius)
        strict=lambda g:g['reliable'] and g['min_support']>=.80 and g['max_rms']<=.65
        if not strict(gate) or gate['prediction_correction']>1.:return None
        second,independent,checked,agreement=self._source_confirmation(image,gray,candidate,evidence)
        if not strict(checked) or not agreement['verified']:return None
        if not _valid__v87_v74_tracking(second,gray.shape,self.q,self.checks):return None
        return second,independent,dict(state='current_four_edges_twice_verified',
            first_validation=gate,second_validation=checked,source_line_agreement=agreement,old_H_not_used=True)

    def _recover_current_edges(self,gray,candidate,evidence,prediction,previous,gate,reason):
        # Only a correspondence-shortage failure may use stricter independently
        # measured CURRENT outer edges. Other LK/geometry failures fully redetect.
        shortage=('少于4' in reason or 'consistency rejected: -2' in reason)
        if (not shortage or candidate is None or not gate.get('reliable')
            or self.edge_recovery_count>=2 or gate['min_support']<.80
            or gate['max_rms']>.65 or gate['prediction_correction']>1.0):return None
        measured,checked=edge_measure__v87_v74_tracking(gray,candidate,3.,self.checks)
        independent=self._edge_gate(checked,measured,candidate,3.)
        if (not independent['reliable'] or independent['min_support']<.80
            or independent['max_rms']>.65 or independent['prediction_correction']>.6
            or not _valid__v87_v74_tracking(measured,gray.shape,previous,self.checks)):return None
        return measured,checked,dict(state='current_outer_edges_verified',lk_shortage=reason,
            validation=independent,consecutive_recoveries=self.edge_recovery_count+1)

    def _detect_nearby(self,image,prediction,scale,bounded=False,force_full=False):
        # Alternate ROI-first and full-view attempts after repeated failure.
        # Both share ONE candidate/time budget; a spent ROI budget is not reset.
        # A failed current exterior is evidence that the old ROI is unsafe.
        # Search the existing whole small Y, then refine its NEW candidate.
        full_first=force_full or (bounded and (self.lost or self._recovery_attempts%2==0))
        route='current_exterior_mismatch_global_Y' if force_full else ('lost_or_alternate_global_Y' if full_first else 'verified_prediction_ROI')
        raw_yuyv=image.ndim==3 and image.shape[2]==2
        # A full detector is kept as final fallback. ROI candidates must also
        # match the previous current-frame geometry and measured exterior edges.
        q=((prediction+.5)*scale-.5).astype(np.float32);h,w=image.shape[:2]
        pad=max(24.,float(max(scale))*12.)
        lo=np.maximum(0,np.floor(q.min(axis=0)-pad)).astype(int)
        hi=np.minimum([w,h],np.ceil(q.max(axis=0)+pad)).astype(int)
        x0,y0=map(int,lo);x1,y1=map(int,hi)
        if raw_yuyv:
            # A local YUYV view must start on Y0/U and contain complete pairs.
            x0=(x0//2)*2;x1=min(w,((x1+1)//2)*2)
        if not full_first and (x1-x0)*(y1-y0)<.80*w*h and min(x1-x0,y1-y0)>=32:
            began=time.perf_counter()
            try:
                with recovery_view_scope((x0,y0)):local,info=self._detect(image[y0:y1,x0:x1])
                full=np.asarray(local,np.float32)+[x0,y0]
                observed=((full+.5)/scale-.5).astype(np.float32)
                if not _valid__v87_v74_tracking(observed,self.last_gray.shape,self.q,self.checks):raise ValueError('ROI detection geometry mismatch')
                receipt=read_current_receipt(info,image,self.last_gray,scale,self._update_index,full)
                if receipt is None:
                    measured,e=edge_measure__v87_v74_tracking(self.last_gray,observed,3.,self.checks)
                    g=self._edge_gate(e,measured,observed,3.)
                    if not g['reliable']:
                        measured,e,_=self._boundary(image,self.last_gray,scale,observed,measured=measured,evidence=e,checks=self.checks)
                        g=self._edge_gate(e,measured,observed,3.)
                    if not g['reliable']:raise ValueError('ROI detection does not match current exterior')
                return full,dict(info,roi=[x0,y0,x1,y1],recovery_backend='p1_predicted_roi',recovery_route=route,stale_prediction_ROI_skipped=False,roi_detection_s=time.perf_counter()-began)
            except (ValueError,cv2.error,TypeError):
                if bounded:
                    try:_budget_check('ROI_to_full_fallback')
                    except _DetectionStop as exc:
                        raise QuadDetectionError(str(exc),_RECOVERY_BUDGET.get().summary()) from exc
        full,info=self._detect(image)
        return full,dict(info,recovery_backend='p1_full_frame',recovery_route=route,
            stale_prediction_ROI_skipped=bool(force_full))

    def _search_radius(self,previous,step,source_gap):
        speed=max(float(np.max(np.linalg.norm(self.velocity,axis=1))),self.motion_ema)
        drift=float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))
        uncertainty=.25*speed*max(0.,step-1.)+.15*drift+.5*self.correction_ema+(1. if source_gap else 0.)
        shortest=float(np.min(np.linalg.norm(np.roll(previous,-1,axis=0)-previous,axis=1)))
        cap=max(3.,min(6.,.06*shortest))
        return float(np.clip(3.+uncertainty,3.,cap)),dict(radius_cap=cap,prediction_uncertainty=uncertainty,
            source_step=step,speed_per_capture_frame=speed,all_four_edges_required=True)

    def _release_static_edges(self,reason):
        self._still_q=None;self._still_samples=None;self._still_calm=False
        self._still_radius=3.
        self._still_release=reason

    def _pin_static_edges(self,sample_shape):
        # Only once on entry. These are indices into the ALREADY computed
        # 60x80 difference, not another image read or detector invocation.
        q=self.corners();fractions=np.linspace(.08,.92,24)[:,None]
        points=[]
        for a,b in zip(q,np.roll(q,-1,axis=0)):
            edge=b-a;normal=np.array([-edge[1],edge[0]])/max(1.,float(np.linalg.norm(edge)))
            base=a+fractions*edge
            for offset in (-8.,0.,8.):points.append(base+offset*normal)
        xy=np.rint(np.concatenate(points)/8.).astype(np.intp)
        h,w=sample_shape;xy[:,0]=np.clip(xy[:,0],0,w-1);xy[:,1]=np.clip(xy[:,1],0,h-1)
        self._still_samples=np.unique(xy[:,1]*w+xy[:,0])
        self._still_q=self.q.copy();self._still_release=None
        # Keep the original band for already stable/soft covers. Narrow only
        # after actual low-motion corrections indicate a neighboring edge.
        correction=max(self.correction_ema,float(self._hold_gate.get('prediction_correction',0.)))
        self._still_radius=2. if correction>.75 else 3.

    def _static_hold(self, image, index, began, cpu, lost_at_entry):
        """⭐ 静止保持：60x80 Y 采样（预分配）+ 3 帧中值 + 自适应噪声底。

        rev4：固定阈值在高噪声场景会永远进不去（`hold_changed` 中位 5.6% > 3%），
        且 120x160 采样每帧约 9 ms。这里改成 60x80 + 预分配 + 噪声自适应。
        """
        self._still_calm=False
        # Numeric options are session configuration (Notebook sets them before
        # construction). Cache their parsing to pay for the small local cue.
        # The two on/off switches remain live for A/B and normal disablement.
        cfg=self._hold_cfg
        if cfg is None:cfg=self._hold_cfg=static_hold_settings()
        continuity=os.environ.get('P11_STATIC_EDGE_CONTINUITY','1')!='0'
        if not static_hold_enabled() or image is None or image.ndim!=3 or image.shape[2]!=2:
            self._release_static_edges('disabled_or_layout')
            return None
        sample=image[::8,::8,0]
        ref=self._hold_ref
        if ref is None or ref.shape!=sample.shape:
            self._release_static_edges('new_sample_layout')
            ref=self._hold_ref=np.empty(sample.shape,np.int16)
            np.copyto(ref,sample,casting='unsafe')
            self._hold_hist=[];self._hold_count=0;self._hold_active=False
            self._hold_last_full=time.perf_counter()
            return None
        tmp=self._hold_tmp
        if tmp is None or tmp.shape!=sample.shape:
            tmp=self._hold_tmp=np.empty(sample.shape,np.int16)
        np.subtract(ref,sample,out=tmp,casting='unsafe')
        np.abs(tmp,out=tmp)
        motion=float(tmp.mean())
        changed=float(np.count_nonzero(tmp>8))/float(tmp.size)
        self._hold_motion=motion;self._hold_changed=changed
        # 自适应噪声底：低于底时快速跟随，高于底时极慢上升
        fm=self._hold_floor_m;fc=self._hold_floor_c
        fm+=(.20 if motion<fm else .01)*(motion-fm)
        fc+=(.20 if changed<fc else .01)*(changed-fc)
        self._hold_floor_m=fm;self._hold_floor_c=fc
        hist=self._hold_hist;hist.append((motion,changed))
        if len(hist)>cfg['smooth']:hist.pop(0)
        sm=sorted(v[0] for v in hist)[len(hist)//2]
        sc=sorted(v[1] for v in hist)[len(hist)//2]
        self._hold_smooth=(sm,sc)
        now=time.perf_counter()
        # ⚠️ 进入用【平滑值】（要求持续静止）；退出用【原始值】（一有大变化立刻退出）。
        # 上限防止自适应把阈值放得太松（噪声大到无法区分慢动作时宁可少保持）。
        if self._hold_active:
            exit_m=min(12.,max(cfg['exit'],cfg['exit_gain']*fm))
            exit_c=min(.18,max(cfg['exit_frac'],cfg['exit_gain']*fc))
            blocked=motion>exit_m or changed>exit_c
        else:
            limit_m=min(10.,max(cfg['enter'],cfg['enter_gain']*fm))
            limit_c=min(.15,max(cfg['enter_frac'],cfg['enter_gain']*fc))
            blocked=sm>limit_m or sc>limit_c
        # A small book can move without changing the whole-view mean much.
        # Compare boundary-near cells to the SAME fixed raw reference; slow
        # movement accumulates across holds and periodic complete checks.
        local_blocked=False
        if not continuity and self._still_q is not None:self._release_static_edges('continuity_disabled')
        if continuity and self._still_samples is not None:
            near=tmp.ravel()[self._still_samples]
            self._still_edge_motion=float(near.sum())/float(near.size)
            # Uniform exposure/noise should keep the original global decision;
            # only excess change concentrated at the book border wakes early.
            local_blocked=(self._still_edge_motion>max(6.,min(8.,1.5*fm))
                and self._still_edge_motion>1.5*motion)
        if (lost_at_entry or self.state!='TRACKING' or blocked or local_blocked
                or getattr(self,'source_force_reacquire',False)):
            self._release_static_edges('lost_or_gap' if lost_at_entry or getattr(self,'source_force_reacquire',False)
                else 'raw_motion' if blocked or local_blocked else 'not_tracking')
            np.copyto(ref,sample,casting='unsafe')
            self._hold_count=0;self._hold_active=False;self._hold_last_full=now
            return None
        self._still_calm=self._still_q is not None
        self._hold_count+=1
        if not self._hold_active:
            if self._hold_count<cfg['min_frames']:
                self._hold_last_full=now
                return None
            self._hold_active=True;self._hold_since=now;self._hold_frames=0
            if continuity and self._still_q is None:self._pin_static_edges(sample.shape)
        self._still_calm=self._still_q is not None
        if now-self._hold_last_full>cfg['max_s']:
            # 到点强制完整测量一次（防慢速漂移）
            self._hold_active=False;self._hold_count=0;self._hold_last_full=now
            return None
        self._hold_frames+=1
        self.velocity[:]=0
        self.last_index=index;self.state='TRACKING';self.lost=False
        self.fastpath_detail=dict(policy='static_hold',route='static_hold',
            ordinary_stability_probe=False,ordinary_illumination_probe=False,same_frame_receipt_reused=False)
        corners=self.corners();corners.flags.writeable=False
        return dict(valid=True,mode='static_hold',corners=corners,
            confidence=float(self._hold_confidence),index=index,scheduled=False,
            lk_trigger=None,edge_rescue=None,trigger='static_hold',
            feature_count=len(self.anchor_points),target_changed=False,
            tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-cpu,
            tracking_state='TRACKING',edge_gate=dict(self._hold_gate),lk_timing={},
            current_source_proof=dict(self.last_source_confirmation),
            v49_fastpath=dict(self.fastpath_detail),
            quick_current_candidate=dict(attempted=False,verified=False),
            current_proof_workspace=self.current_proofs.summary(),
            source_corners_s=0.,post_observation_s=0.,gray_s=0.,
            static_hold=dict(motion=motion,changed=changed,smooth_motion=sm,smooth_changed=sc,
                floor_m=fm,floor_c=fc,held_s=now-self._hold_since,frames=self._hold_frames,
                max_hold_s=cfg['max_s'],edge_motion=self._still_edge_motion,
                fixed_raw_reference=True,static_edge_reference=self._still_calm))

    def update(self, image, index):
        self.last_source_confirmation={}  # Per-current-frame diagnostic only.
        self.edge_workspace.decode_timing=(0.,0.)
        self.observer.transaction.decode_timing=(0.,0.)
        self.current_proofs.clear()
        self.fastpath_detail=dict(policy='V49_ordinary_current_edges',route='pending',
            ordinary_stability_probe=False,ordinary_illumination_probe=False,same_frame_receipt_reused=False)
        self.quick_recovery_detail=dict(attempted=False,verified=False)
        self.photometric.detail=dict(available=False,reason='V49_ordinary_path_no_illumination_probe',frame_index=index)
        self.stability_detail=dict(available=False,reason='V49_ordinary_path_no_extra_stability_remeasurement',frame_index=index)
        began=time.perf_counter();begin_cpu=time.thread_time();self._update_index=index;self._flow_cache=None
        budget_ms=(None if self.recovery_budget_ms is None else
            self.reacquire_budget_ms if (self.lost or getattr(self,'source_force_reacquire',False)) else self.recovery_budget_ms)
        lost_at_entry=self.lost
        retry_deferred=bool(lost_at_entry and getattr(self,'continuity_hold',False) and began<self._recovery_next_at)
        if retry_deferred:self._recovery_next_index=max(self._recovery_next_index,index+1)
        self._total_deadline=None if budget_ms is None else began+budget_ms/1000.
        # Current proof has priority. Global search gets the remaining budget;
        # an exhausted update rejects this frame and retries on the next one.
        # Reserving 60ms first starved FB LK's independent 64/24 proof.
        self._reserved_detection_ms=0. if budget_ms is None or lost_at_entry or self.recovery_worker is not None else min(15.,budget_ms*.125)
        self._frame_deadline=(None if budget_ms is None else
            began+.40 if self.recovery_worker is not None else
            self._total_deadline if lost_at_entry else began+(budget_ms-self._reserved_detection_ms)/1000.)
        if not self.started or image.shape!=self.shape or index<=self.last_index:
            raise ValueError('连续帧尺寸或顺序改变')
        async_result=None
        if lost_at_entry and self.recovery_worker is not None:
            async_result=self.recovery_worker.take()
            current_proposal=bool(async_result is not None and async_result.get('valid')
                and time.perf_counter()-async_result['ready']<=self.recovery_result_max_age_s)
            if not current_proposal:
                if self._quick_recovery_attempted and not self._local_due():
                    return self._async_wait(image,index,began,begin_cpu,'Awaiting current admitted background candidate',async_result)
                async_result=None
        previous=self.q.copy();dt=max(1.,float(getattr(self,"source_step",index-self.last_index)))
        source_gap=bool(getattr(self,'source_force_reacquire',False))
        # Do not extrapolate a stale velocity across a long USB capture gap.
        prediction=previous.copy() if source_gap else self.q+self.velocity*dt
        self._edge_radius,search_detail=self._search_radius(previous,dt,source_gap)
        self._stability_drift_start[:]=self.accumulated_drift
        # ⭐ 2026-10-28 计时：静止门控也在 `tg` 之前，`post_observation_s` 把这段
        #    算成了"观测之后"，导致 800x600 有 ~18.5 ms 无法归因。单独打点。
        hold_begin=time.perf_counter()
        held=self._static_hold(image,index,began,begin_cpu,lost_at_entry)
        hold_s=time.perf_counter()-hold_begin
        if held is not None:return held
        if self._still_calm:
            # Fix the physical search reference, NOT the output coordinates.
            # The existing measurement still supplies this frame's corners.
            prediction=self._still_q.copy();self._edge_radius=min(self._edge_radius,self._still_radius)
        context=(prediction,previous,self.anchor_q,self.accumulated_drift,self.edge_polarity,self._edge_radius) if not lost_at_entry and self.checks=='auto' and self.policy=='motion_adaptive' else None
        tg=time.perf_counter();gray,scale=self.observer.get(image,context)
        self.last_gray=gray;gray_s=time.perf_counter()-tg
        self.current_proofs.begin(image,gray,index,scale)
        self._promoted_points=None;self.last_lk_timing={}
        age=index-self.anchor_index+int(getattr(self,"source_age_extra",0))
        scheduled=(age>=(self.interval if self.policy=='periodic' else self.lk_max_gap)
            or bool(self._lk_budget_deferrals))
        # previous/dt/prediction were computed before this same-frame observation.
        evidence,reason,detection={},None,None
        mode,reseed='edge_measured',False;gate={};lk_trigger=None;motion_schedule={};adaptive_reason=None
        stable_detail=dict(eligible=False,policy='strict_current_reacquisition')
        self._current_motion_values=None
        self._rescue_detail=None        # ⭐ 2026-10-18 埋点：每帧先清，防串味
        measured_edge_candidate=None;measured_edge_evidence=None;recovery_detail={};gap_anchor_retained=False;recovery_attempt_detail={}
        from geometry import LKWorkBudgetExceeded as LKWorkBudgetExceeded
        try:
            if lost_at_entry and async_result is not None:
                candidate,evidence,recovery_detail=self._admit_async_candidate(image,gray,scale,async_result,index)
                gate=recovery_detail['first_validation'];mode,reseed='current_edge_reacquire',True
                self.edge_polarity=list(evidence['edge_polarity'])
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
            elif lost_at_entry and self.recovery_worker is not None:
                quick_due=not self._quick_recovery_attempted
                local=(self._quick_current_candidate(image,gray,scale,index) if quick_due else
                    self._local_exterior(image,gray,scale,prediction,index))
                if local is None:
                    return self._async_wait(image,index,began,begin_cpu,'Local current exterior unproved; await background candidate',
                        observation=dict(gray_s=gray_s,gray_detail=dict(self.observer.detail),
                            current_source_proof=dict(self.last_source_confirmation)))
                candidate,evidence,recovery_detail=local
                gate=recovery_detail['first_validation'];mode,reseed='current_edge_reacquire',True
                self.edge_polarity=list(evidence['edge_polarity'])
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
            elif lost_at_entry:
                self.state='LOST' 
                candidate,evidence=edge_measure__v87_v74_tracking(gray,prediction,3.,self.checks)
                gate=self._edge_gate(evidence,candidate,prediction,3.)
                measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
                # Leave most of the total budget for global detection if the
                # current exterior cannot be proved near its last location.
                current_deadline=self._frame_deadline
                self._frame_deadline=min(current_deadline,time.perf_counter()+.055) if current_deadline is not None else None
                proof_allowed=(not retry_deferred or (gate['reliable'] and
                    time.perf_counter()>=self._continuity_proof_next_at))
                if proof_allowed and getattr(self,'continuity_hold',False):
                    self._continuity_proof_next_at=time.perf_counter()+.10
                try:proof=(self._strict_current_reanchor(image,gray,prediction,candidate,evidence)
                    if proof_allowed else None)
                finally:self._frame_deadline=current_deadline
                if proof is not None:
                    candidate,evidence,recovery_detail=proof
                    mode,reseed='current_edge_reacquire',True
                    recovery_detail.update(state='LOST_current_source64_reacquired',old_LK_skipped=True)
                elif index<self._recovery_next_index:
                    raise ValueError('LOST: current exterior not proved; global retry deferred')
                else:raise ValueError('LOST: prioritize current global detection; old LK skipped')
            if self.observer.merged_error is not None:raise ValueError('Native edge observation rejected: '+str(self.observer.merged_error))
            if mode=='current_edge_reacquire':pass
            elif source_gap:
                was_lost=self.lost
                if self.observer.merged_edges is not None:
                    candidate,evidence,gate,self._current_motion_values=self.observer.merged_edges
                else:candidate,evidence=edge_measure__v87_v74_tracking(gray,prediction,self._edge_radius,self.checks)
                proof=self._strict_current_reanchor(image,gray,prediction,candidate,evidence)
                if proof is None:
                    candidate,evidence=self._lk_current(gray,prediction,image)
                    mode,reseed='lk_measured',True;lk_trigger='lost_or_capture_gap'
                else:
                    candidate,evidence,recovery_detail=proof
                    gate=self._edge_gate(evidence,candidate,candidate,3.)
                    measured_edge_candidate=candidate.copy();measured_edge_evidence=dict(evidence)
                    anchor_supported=_spatial_support__v87_v74_tracking(self.anchor_points,self.anchor_q,self.checks)
                    travel=float(np.max(np.linalg.norm(candidate-self.anchor_q,axis=1)))
                    can_retain=(not was_lost and self.policy=='motion_adaptive' and anchor_supported
                        and age<self.lk_max_gap and travel<=1. and self._gap_anchor_reuses<3
                        and float(np.max(np.linalg.norm(self.accumulated_drift,axis=1)))<2.
                        and self.drift_budget<6.)
                    if scheduled and (anchor_supported or self._lk_budget_deferrals):
                        candidate,evidence=self._lk_current(gray,candidate,image)
                        mode,reseed='lk_measured',True;lk_trigger='gap_maximum_anchor_age'
                    elif can_retain:
                        mode,reseed='gap_edge_reanchor',False
                        gap_anchor_retained=True;self._gap_anchor_reuses+=1
                        recovery_detail.update(anchor_action='retain_original_gray_points_pyramid',anchor_age=age)
                    else:
                        # Re-seeding is allowed only from two current measured
                        # exterior proofs. It is not a synthetic LK observation.
                        mode,reseed='gap_edge_reanchor',True
                        recovery_detail['anchor_action']='seed_current_twice_verified_edges'
                    recovery_detail.update(source_gap=source_gap,was_lost=was_lost,source_step=dt)
            elif self.policy=='periodic'  and (self.lost or scheduled):
                candidate,evidence=self._lk(gray,source_image=image);mode,reseed='lk_measured',True;lk_trigger='periodic'
            else:
                # Even at maximum LK age, measure the CURRENT outer boundary first.
                radius=self._edge_radius
                fused=self.observer.merged_edges
                if fused is None:
                    fused=self.edge_workspace.measure(gray,prediction,previous,self.anchor_q,
                        self.accumulated_drift,self.edge_polarity,radius) if self.checks=='auto' and self.policy=='motion_adaptive' else None
                if fused is None:
                    candidate,evidence=edge_measure__v87_v74_tracking(gray,prediction,radius,checks=self.checks)
                    gate=self._edge_gate(evidence,candidate,prediction,radius)
                else:candidate,evidence,gate,self._current_motion_values=fused
                if not gate['reliable'] and not (SKIP_DEAD_RESEARCH or skip_dead_research()):
                    # ⭐ 埋点：记重搜【前】的 gate 指标（只读，不改行为）
                    _pre_sup=float(gate.get('min_support',0.));_pre_rms=float(gate.get('max_rms',0.))
                    _pre_corr=float(gate.get('prediction_correction',0.));_pre_flip=int(gate.get('polarity_flips',0) or 0)
                    _pre_edges=int(evidence.get('supported_edges',0) or 0);_pre_corners=int(evidence.get('refined_corners',0) or 0)
                    _pre_valid=bool(evidence.get('valid',False))
                    candidate,evidence,_=self._boundary(image,gray,scale,prediction,measured=candidate,evidence=evidence,
                        checks=self.checks,radius=radius,fast_only=True,deadline=self._frame_deadline,
                        expected_polarity=self.edge_polarity,color_profiles=24,
                        prefer_color=False,prefer_vector=False)
                    gate=self._edge_gate(evidence,candidate,prediction,radius)
                    self._current_motion_values=None
                    # ⭐ 重搜【后】再记一次 —— 量的是【改善了多少】
                    _post_sup=float(gate.get('min_support',0.));_post_rms=float(gate.get('max_rms',0.))
                    _post_corr=float(gate.get('prediction_correction',0.));_post_flip=int(gate.get('polarity_flips',0) or 0)
                    _post_edges=int(evidence.get('supported_edges',0) or 0);_post_corners=int(evidence.get('refined_corners',0) or 0)
                    _post_valid=bool(evidence.get('valid',False))
                    self._rescue_detail=dict(
                        pre_support=_pre_sup,post_support=_post_sup,
                        pre_rms=_pre_rms,post_rms=_post_rms,
                        support_gain=_post_sup-_pre_sup,
                        post_meets_support=bool(_post_sup>=.60),
                        post_meets_rms=bool(_post_rms<=1.0),
                        pre_valid=_pre_valid,post_valid=_post_valid,
                        pre_edges=_pre_edges,post_edges=_post_edges,
                        pre_corners=_pre_corners,post_corners=_post_corners,
                        pre_correction=_pre_corr,post_correction=_post_corr,
                        pre_flips=_pre_flip,post_flips=_post_flip,
                        recovered=bool(gate.get('reliable')))
                if (SKIP_DEAD_RESEARCH or skip_dead_research()) and not gate['reliable']:
                    # ⚠️ 跳过重搜时仍保留原分支的这次重置 —— 让 A/B 只差"_boundary 本身"
                    self._current_motion_values=None
                from display import evidence_snapshot as evidence_snapshot
                measured_edge_candidate=candidate.copy();measured_edge_evidence=evidence_snapshot(evidence)
                self.fastpath_detail['route']='current_color_edges' if evidence.get('color_vector_proof') else 'current_Y_edges'
                if self.policy=='motion_adaptive' and gate['reliable']:
                    if self._still_calm and gate['prediction_correction']>.75:self._still_radius=2.
                    # A replaced measurement recomputes drift once from its saved
                    # pre-observation value, rather than counting both searches.
                    if self._current_motion_values is None:self.accumulated_drift[:]=self._stability_drift_start
                    adaptive_reason,motion_schedule=self._motion_schedule(gate,candidate,prediction,previous,age)
                    if radius>3.25 and gate['prediction_correction']>1.:
                        adaptive_reason='expanded_band_current_motion';motion_schedule['wide_band_FB_required']=True
                    if self._lk_budget_deferrals:
                        adaptive_reason='pending_complete_current_FB'
                        motion_schedule['deferred_FB_required']=True
                    scheduled=adaptive_reason is not None
                need_lk=self.lost or not gate['reliable'] or scheduled
                if self.policy=='periodic':
                    need_lk=self.lost or not gate['reliable'];mode='prediction_edge_corrected'
                if need_lk:
                    lk_trigger=('lost' if self.lost else (adaptive_reason or 'maximum_gap') if scheduled and gate['reliable']
                                else 'edge_confidence')
                    candidate,evidence=self._lk_current(gray,candidate if gate['reliable'] else prediction,image)
                    mode,reseed='lk_measured',True
            if mode=='edge_measured':
                stable_detail=ordinary_policy(evidence,self._edge_gate(evidence,candidate,prediction,self._edge_radius),
                    age,self.lk_max_gap,scheduled=scheduled,lost=lost_at_entry)
            if self._edge_radius>3.25 and mode=='edge_measured':
                # V49 expanded ordinary searches require actual source four
                # edges before H, while LK/new admission keep independent proof.
                from geometry import original_y_boundary as original_y_boundary
                proof=original_y_boundary(image,scale,candidate,radius=3.)
                precise,precise_e=(candidate,dict(valid=False)) if proof is None else proof
                pg=self._edge_gate(precise_e,precise,candidate,3.) if proof is not None else dict(reliable=False)
                if not pg['reliable']:
                    precise,precise_e,_=self._boundary(image,gray,scale,candidate,
                        measured=precise,evidence=precise_e,checks=self.checks,radius=3.,fast_only=True,
                        deadline=self._frame_deadline,expected_polarity=self.edge_polarity,
                        color_profiles=64,prefer_color=True)
                    pg=self._edge_gate(precise_e,precise,candidate,3.)
                if not pg['reliable']:
                    raise LKExteriorMismatch__v87_v74_tracking('V49 expanded band failed current source-resolution four-edge proof')
                candidate,evidence=precise,precise_e
                gate=pg
                self.fastpath_detail['expanded_source_four_edges']=True
            flips=0 if evidence.get('color_vector_proof') else sum(a*b<0 for a,b in zip(self.edge_polarity,evidence.get('edge_polarity',[])))
            if flips>=2:raise ValueError('边界极性改变，拒绝内部网格边界')
            fresh_admission=(mode=='current_edge_reacquire' and
                (async_result is not None or self.quick_recovery_detail.get('verified',False)))
            reference=None if fresh_admission else previous
            if not _valid__v87_v74_tracking(candidate,gray.shape,reference,self.checks):raise ValueError('本帧四角不合法')
        except (ValueError,cv2.error) as exc:
            reason=str(exc)
            if isinstance(exc,LKWorkBudgetExceeded) and not lost_at_entry and getattr(self,'_lk_budget_deferrals',0)<2:
                # Do not call a time deferral a target replacement. No current
                # admission or anchor promotion occurs. Next frame still owes FB;
                # the pipeline may use ONLY its pre-existing finite HELD policy.
                self._promoted_points=None;self.last_index=index
                self._lk_budget_deferrals=getattr(self,'_lk_budget_deferrals',0)+1
                return dict(valid=False,mode='budget_deferred',reason=reason,index=index,
                    tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-begin_cpu,
                    gray_s=gray_s,gray_detail=dict(self.observer.detail),feature_update_s=0.,
                    feature_detail=dict(action='retain_real_anchor_pending_FB',roi_s=0.),
                    lk_timing=dict(self.last_lk_timing),lk_trigger=lk_trigger,
                    tracking_state=self.state,edge_gate=dict(gate),edge_evidence=dict(evidence),
                    final_admission_gate=dict(reliable=False),current_source_proof=dict(self.last_source_confirmation),
                    recovery_attempt=dict(state='compute_budget_deferred',physical_loss_proven=False,
                        current_output_verified=False,hold_timer_renewed=False,FB_required_next_frame=True,
                        consecutive_deferrals=self._lk_budget_deferrals,maximum_consecutive_deferrals=2))
            if isinstance(exc,LKWorkBudgetExceeded):
                self.last_lk_timing.update(budget_deferral_limit_reached=True,
                    recovery_reason='bounded_compute_retries_exhausted; request new current anchor',physical_loss_proven=False)
            try:
                from core import recover_audit_edges as recover_audit_edges
                recovered=recover_audit_edges(self,image,gray,measured_edge_candidate,measured_edge_evidence,
                    prediction,previous,gate,reason,lk_trigger,lost_at_entry,source_gap)
                if recovered is None:
                    recovered=self._recover_current_edges(gray,measured_edge_candidate,measured_edge_evidence,
                        prediction,previous,gate,reason)
                if recovered is not None:
                    candidate,evidence,edge_recovery=recovered
                    recovery_detail=dict(recovery_detail,**edge_recovery,source_gap=source_gap,
                        anchor_action="seed_current_verified_frame_after_LK_shortage")
                    mode='audit_edge_reanchor' if edge_recovery.get('audit_failure_reproved') else 'measured_edge_recovery'
                    reseed=True
                    if mode=='measured_edge_recovery':self.edge_recovery_count+=1
                else:
                    if self.recovery_worker is not None:
                        return self._async_wait(image,index,began,begin_cpu,reason,async_result,
                            dict(gray_s=gray_s,gray_detail=dict(self.observer.detail),edge_gate=dict(gate),
                                 edge_evidence=dict(evidence),lk_timing=dict(self.last_lk_timing),lk_trigger=lk_trigger,
                                 current_source_proof=dict(self.last_source_confirmation)),request_background=not self._local_due())
                    if self.recovery_budget_ms is not None:
                        if self.lost and index<self._recovery_next_index:
                            recovery_attempt_detail=dict(state='bounded_backoff',next_index=self._recovery_next_index,
                                maximum_processed_frame_gap=self.recovery_backoff_max_frames,
                                current_edge_observation_attempted=True,current_edge_candidate_available=measured_edge_candidate is not None,invalid_frame_skipped=True)
                            self.recovery_stats['deferred']+=1
                            raise ValueError('Recovery retry deferred; no stale H submitted')
                        from geometry import array_key as array_key
                        reacquire=self.lost or source_gap
                        stage_begin=time.perf_counter();stage_cpu=time.thread_time()
                        remaining_ms=max(0.,(self._total_deadline-stage_begin)*1000.)
                        budget=RecoveryBudget(remaining_ms,
                            self.reacquire_max_candidates if reacquire else self.recovery_max_candidates,
                            begin=stage_begin,begin_cpu=stage_cpu)
                        budget.tracker_begin=began;budget.tracker_budget_ms=budget_ms
                        self._frame_deadline=self._total_deadline
                        self.state='REACQUIRING'
                        self._recovery_attempts+=1;self.recovery_stats['attempts']+=1
                        # This merely prioritizes a current candidate, without
                        # waiving LK or original-Y/final independent admission.
                        strong=(measured_edge_candidate is not None and gate.get('reliable')
                            and gate['min_support']>=.80 and gate['max_rms']<=.65
                            and gate['prediction_correction']<=1.)
                        proposal=((measured_edge_candidate+.5)*scale-.5) if strong else None
                        try:
                            with recovery_detection_scope(budget,dict(gray=gray,scale=scale,source_shape=image.shape,
                                    verified_edge_proposal=proposal,frame_index=index,
                                    source_key=array_key(image))):
                                global_current=(lost_at_entry or isinstance(exc,LKExteriorMismatch__v87_v74_tracking) or not gate.get('reliable',False))
                                full,detection=self._detect_nearby(image,measured_edge_candidate if strong else prediction,scale,bounded=True,force_full=global_current)
                        finally:
                            recovery_attempt_detail=dict(budget.summary(),budget_class="reacquisition" if reacquire else "ordinary",
                                 current_Y_reused=True,current_exterior_proposal_used=bool(strong),
                                 whole_tracker_budget=False,total_tracker_budget_ms=budget_ms,
                                 pre_detection_s=stage_begin-began,detector_phase_budget_ms=remaining_ms,
                                 detector_first_on_LOST=lost_at_entry,old_LK_skipped=lost_at_entry,
                                 reserved_detection_ms=self._reserved_detection_ms,
                                 total_tracker_elapsed_s=time.perf_counter()-began,
                                 global_current_Y_first=bool(lost_at_entry or isinstance(exc,LKExteriorMismatch__v87_v74_tracking) or not gate.get('reliable',False)),
                                 trigger_class='LKExteriorMismatch' if isinstance(exc,LKExteriorMismatch__v87_v74_tracking) else 'current_geometry_or_flow')
                            self.recovery_stats['elapsed_s']+=recovery_attempt_detail['elapsed_s']
                            self.recovery_stats['overshoot_s']+=recovery_attempt_detail['overshoot_s']
                            self.recovery_stats['budget_stops']+=int(budget.stopped is not None)
                    else:full,detection=self._detect_nearby(image,prediction,scale)
                    candidate=((np.asarray(full)+.5)/scale-.5).astype(np.float32)
                    if not _valid__v87_v74_tracking(candidate,gray.shape,checks=self.checks):raise ValueError('重检四角异常')
                    receipt=read_current_receipt(detection,image,gray,scale,index,full)
                    detection.pop('_current_boundary_receipt',None)
                    if receipt is not None:
                        measured,reacquired,reacquisition_gate=receipt
                        self.last_source_confirmation=dict(reacquisition_gate.get('current_source_agreement',{}),
                            final_gate=dict(reacquisition_gate))
                    else:
                        measured,reacquired=edge_measure__v87_v74_tracking(gray,candidate,3.,self.checks)
                        reacquisition_gate=exterior_gate(reacquired,measured,candidate,3.)
                        if not reacquisition_gate['reliable']:
                            measured,reacquired,reacquisition_gate=self._boundary(image,gray,scale,candidate,measured=measured,evidence=reacquired,checks=self.checks)
                    recovery_detail=dict(recovery_detail,state='full_redetection_validation',validation=reacquisition_gate,
                        edge_evidence=reacquired,corners=candidate.tolist())
                    if not reacquisition_gate['reliable'] or not _valid__v87_v74_tracking(measured,gray.shape,checks=self.checks):
                        raise ValueError('重检未通过四条外边缘验证: '+str(reacquisition_gate))
                    # Use the measured intersections, not the coarse proposal.
                    # Strong full-frame detection establishes its own polarity;
                    # ordinary tracking still rejects polarity flips and uses FB LK.
                    candidate=measured
                    self.edge_polarity=reacquired['edge_polarity']
                    mode,reseed='full_redetect',True;evidence=reacquired
                    self.edge_recovery_count=0
            except (ValueError,cv2.error) as failure:
                self.lost=True;self.state='LOST';self.velocity[:]=0;self.last_index=index
                if self.recovery_budget_ms is not None and recovery_attempt_detail.get('state')!='bounded_backoff':
                    self._recovery_failures+=1
                    gap=min(self.recovery_backoff_max_frames,1<<min(3,max(0,self._recovery_failures-1)))
                    self._recovery_next_index=index+gap
                    if getattr(self,'continuity_hold',False):
                        retry_s=min(self.recovery_retry_max_s,self.recovery_retry_min_s*(2**min(2,self._recovery_failures-1)))
                        self._recovery_next_at=time.perf_counter()+retry_s
                        recovery_attempt_detail.update(next_retry_at=self._recovery_next_at,retry_backoff_s=retry_s)
                    recovery_attempt_detail.update(failure_count=self._recovery_failures,next_index=self._recovery_next_index,
                        current_edge_observation_attempted=True,current_edge_candidate_available=measured_edge_candidate is not None,invalid_frame_skipped=True)
                    self._remember_recovery_failure(gray,index,prediction,recovery_attempt_detail)
                return dict(valid=False,mode='lost_skip',reason=str(failure),trigger=reason,
                    tracker_s=time.perf_counter()-began,tracker_thread_cpu_s=time.thread_time()-begin_cpu,index=index,gray_s=gray_s,
                    gray_detail=dict(self.observer.detail),feature_update_s=0.,
                    feature_detail=dict(action='lost_skip',roi_s=0.),lk_timing=dict(self.last_lk_timing),
                    edge_rescue=getattr(self,"_rescue_detail",None),   # ⭐ 防未初始化
                    tracking_policy=self.policy,lk_channel=self.lk_channel,lk_trigger=lk_trigger,edge_gate=gate,
                    tracking_state=self.state,prediction_gate=dict(gate),final_admission_gate=dict(reliable=False),
                    lk_current_gate=self.last_lk_timing.get('current_four_edge_gate'),search_band=search_detail,
                    edge_evidence=evidence,detection=detection,reacquisition=recovery_detail,
                    detector_failure=getattr(failure,'diagnostics',None),source_gap=source_gap,
                    recovery_attempt=recovery_attempt_detail)
        self._lk_budget_deferrals=0
        self.photometric.commit()
        from geometry import align_current as align_current; from geometry import border_signature as border_signature; from geometry import target_relation as target_relation
        identity=dict(state='tracked_current_target',target_changed=False,same_target=True)
        if mode in ('full_redetect','current_edge_reacquire'):
            candidate,evidence=align_current(candidate,evidence,previous)
            self.edge_polarity=list(evidence['edge_polarity'])
            identity,signature=target_relation(previous,candidate,evidence,self._target_signature)
            self._recovery_confirmations=1
            if signature is not None:self._target_signature=signature.copy()
        else:
            self._recovery_confirmations=min(3,self._recovery_confirmations+1)
            signature=border_signature(evidence)
            if signature is not None:self._target_signature=signature.copy()
        if evidence.get('color_vector_proof'):self._vector_boundary=True
        elif identity.get('target_changed'):self._vector_boundary=False
        # Smooth corner velocity only. The newly measured corners themselves
        # are used for H; averaging H coefficients would create geometric lag.
        if self._recovery_failures:
            self.recovery_stats['successes']+=1
        self._recovery_failures=0;self._recovery_next_index=0;self._recovery_attempts=0
        self._recovery_next_at=0.;self._continuity_proof_next_at=0.
        change = (candidate-previous)/max(dt, 1)
        if mode=='lk_measured':self.edge_recovery_count=0
        self.velocity = (self.velocity*.25+change*.75).astype(np.float32)
        if mode in ('full_redetect','gap_edge_reanchor','current_edge_reacquire','audit_edge_reanchor'):
            self.velocity[:] = 0
            self._promoted_points=None
            self._last_measured_motion=0.;self._edge_lock_failures=0;self._edge_lock_next_at=0.
        same_recovery=bool(mode in ('full_redetect','current_edge_reacquire','gap_edge_reanchor','audit_edge_reanchor') and identity.get('same_target'))
        if mode in ('full_redetect','current_edge_reacquire'):
            if not identity.get('same_target'):
                self.lk_channel='Y';self._flow_cache=None;self._channel_audit_index=-100
            self.motion_ema=self.correction_ema=0.
            self._burst_until=-1
        if self._still_calm and self._still_q is not None:
            from geometry import line_lock as line_lock
            if not line_lock(self._still_q,candidate).get('verified'):
                self._release_static_edges('current_edges_left_reference')
        np.copyto(self.q,candidate,casting='unsafe')
        self.last_index, self.lost = index, False
        self.state='TRACKING' if self._recovery_confirmations>=3 else 'RECOVERING'
        feature_s=0.;feature_reused=False
        self.last_feature_detail=dict(action='gap_original_anchor_retained' if gap_anchor_retained else 'unchanged_between_lk',
            roi_s=0.,gap_anchor_retained=gap_anchor_retained,consecutive_gap_anchor_reuses=self._gap_anchor_reuses)
        if reseed:
            ts=time.perf_counter()
            anchor_travel=float(np.max(np.linalg.norm(self.q-self.anchor_q,axis=1)))
            retain_original=(same_recovery and not recovery_detail.get('force_current_anchor',False) and self.policy=='motion_adaptive'
                and _spatial_support__v87_v74_tracking(self.anchor_points,self.anchor_q,self.checks)
                and age<self.lk_max_gap and anchor_travel<=min(6.,.04*float(np.min(np.linalg.norm(np.roll(self.q,-1,axis=0)-self.q,axis=1))))
                and self._gap_anchor_reuses<3)
            if retain_original:
                self._gap_anchor_reuses+=1;gap_anchor_retained=True;feature_reused=True
                self.observer.pin(self.anchor_gray if self.lk_channel=='Y' else self.last_gray)
                self.last_feature_detail=dict(action='same_target_original_verified_anchor_retained',roi_s=0.,
                    channel_audit_skipped=True,anchor_age=age,anchor_travel=anchor_travel,
                    forward_backward_due_by=self.anchor_index+self.lk_max_gap,
                    points_synthesized=False,pyramid_promoted=False)
            else:
                self._gap_anchor_reuses=0
            points=self._promoted_points
            if (not retain_original and self.feature_policy=='quality' and mode not in ('full_redetect','measured_edge_recovery','gap_edge_reanchor','current_edge_reacquire','audit_edge_reanchor') and points is not None):
                # Maintain measured points while their distribution and LK
                # quality remain good; no unconditional 45-frame rebuild.
                quality=(evidence.get('inlier_fraction',0.)>=.85 and
                         evidence.get('fb_median',float('inf'))<.7 and
                         _spatial_support__v87_v74_tracking(points,self.q,self.checks))
                points=self._quality_replenish(self._flow_observation(image,gray),points,self.q,quality,evidence)
            if retain_original:pass
            elif (mode not in ('full_redetect','measured_edge_recovery','gap_edge_reanchor','current_edge_reacquire','audit_edge_reanchor') and points is not None and
                _spatial_support__v87_v74_tracking(points,self.q,self.checks) and
                (self.feature_policy=='quality' or index-self.seed_index<45)):
                self.anchor_gray=self._flow_observation(image,gray);self.observer.pin(gray)
                self.anchor_q=self.q.copy()
                self.anchor_points=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
                self.anchor_index=index
                self.lk_cache.promote()
                feature_reused=True
            else:
                self._seed(gray,self.q,index,image,same_target=same_recovery)
            self.accumulated_drift[:]=0;self.drift_budget=0.
            feature_s=time.perf_counter()-ts
            # ⭐ 2026-10-28 计时：其中【重取点搜索】占多少（promote 快路径为 0）。
            feature_roi_s=float(self.last_feature_detail.get('roi_s') or 0.)
        else:feature_roi_s=0.
        verified_now=time.perf_counter();source_ready=getattr(self,'source_ready_at',verified_now)
        self._exit_verified_calm_burst(mode,candidate,previous,prediction,index)
        self._last_physical_at=float(source_ready) if np.isfinite(source_ready) and 0<=source_ready<=verified_now else verified_now
        self._local_attempts=0;self._local_next_at=0.
        self._quick_recovery_attempted=False
        self.fastpath_detail.update(route=mode if mode!='edge_measured' else self.fastpath_detail['route'],
            same_frame_receipt_reused=bool(gate.get('same_frame_receipt_reused') or self.last_source_confirmation.get('current_same_frame_proof_reused')))
        if static_hold_enabled():
            self._hold_gate=dict(gate);self._hold_confidence=float(np.mean(evidence.get('edge_support',[1.])))
        tc=time.perf_counter();source_corners=self.corners();source_corners.flags.writeable=False
        source_corners_s=time.perf_counter()-tc
        confidence=float(np.mean(evidence.get('edge_support',[1.])))
        tracker_elapsed=time.perf_counter()-began;tracker_cpu=time.thread_time()-begin_cpu
        post_observation_s=max(0.,tracker_elapsed-(tg-began)-gray_s)
        # ⭐ 2026-10-28 计时：把 post_observation 再拆成 LK / 其余。
        #    `lk_s` 取 LK 自己记的 total_attempt_wall_s（含证据门），
        #    `tail_s` = 观测结束到帧尾中 LK 之外的部分（重播点、corners 等）。
        lk_s=float(self.last_lk_timing.get('total_attempt_wall_s') or 0.)
        pre_obs_s=max(0.,(tg-began)-hold_s)
        tail_s=max(0.,post_observation_s-lk_s-feature_s)
        def diagnostics():
            if self._update_index!=index:raise RuntimeError('Expired tracking diagnostic view; materialize before next frame')
            tm=time.perf_counter();cm=time.thread_time()
            result=dict(valid=True, mode=mode, corners=source_corners.tolist(),
                        confidence=confidence,
                        edge_evidence=evidence, detection=detection, trigger=reason,
                        corner_shift_pixels=float(np.max(np.linalg.norm((self.q-previous)*scale, axis=1))),
                        tracker_s=tracker_elapsed,tracker_thread_cpu_s=tracker_cpu, index=index, scheduled=scheduled,
                        lk_trigger=lk_trigger,tracking_policy=self.policy,lk_channel=self.lk_channel,edge_gate=gate,
                        tracking_state=self.state,prediction_gate=dict(gate),
                        final_admission_gate=self._edge_gate(evidence,self.q,self.q,3.),
                        lk_current_gate=self.last_lk_timing.get('current_four_edge_gate'),search_band=search_detail,
                        channel_selection=dict(self._channel_evidence),
                        lk_age_frames=age,lk_max_gap=self.lk_max_gap,motion_schedule=motion_schedule,
                        gray_s=gray_s, feature_update_s=feature_s, feature_reused=feature_reused,
                        gap_anchor_retained=gap_anchor_retained,
                        gray_detail=dict(self.observer.detail),feature_detail=dict(self.last_feature_detail),
                        feature_seed_count=self.seed_count,feature_count=len(self.anchor_points),
                        edge_recovery=recovery_detail,lk_timing=dict(self.last_lk_timing),recovery_attempt=recovery_attempt_detail,
                        target_identity=identity,target_changed=identity.get('target_changed',False),
                        recovery_confirmations=self._recovery_confirmations,color_boundary_continuity=self._vector_boundary,
                        current_proof_budget_ms=budget_ms-self._reserved_detection_ms if budget_ms is not None else None,
                        same_target_recovery=same_recovery,
                        current_source_proof=dict(self.last_source_confirmation),photometric=dict(self.photometric.detail),
                        edge_stability=dict(self.stability_detail),
                        static_edges=dict(active=self._still_calm,release=self._still_release,
                            edge_motion=self._still_edge_motion,current_measurement_retained=True),
                        stable_tracking_policy=stable_detail,localization_baseline='V49_ordinary_V68_strict_new_admission',
                        v49_fastpath=dict(self.fastpath_detail),quick_current_candidate=dict(self.quick_recovery_detail),
                        current_proof_workspace=self.current_proofs.summary(),
                        current_proof_budget_scope='independent LK CPU/wall; narrow current-line proof; strict new admission')
            result['tracking_metadata_build_s']=time.perf_counter()-tm
            result['tracking_metadata_thread_cpu_s']=time.thread_time()-cm
            result['source_corners_s']=source_corners_s
            result.update(pre_obs_s=pre_obs_s,static_hold_s=hold_s,lk_s=lk_s,tail_s=tail_s,
                feature_s=feature_s,feature_roi_s=feature_roi_s,roi_search_gap=self._roi_search_gap)
            return result
        if not self.light_results:return diagnostics()
        # Only the current PS caller may consume _diagnostics; it never enters
        # FrameJob or the log queue. The tiny corners snapshot owns its bytes.
        return dict(valid=True,mode=mode,corners=source_corners,confidence=confidence,
            index=index,scheduled=scheduled,lk_trigger=lk_trigger,edge_rescue=getattr(self,"_rescue_detail",None),trigger=reason,
            feature_count=len(self.anchor_points),target_changed=identity.get('target_changed',False),
            tracker_s=tracker_elapsed,tracker_thread_cpu_s=tracker_cpu,tracking_state=self.state,
            edge_gate=gate,lk_timing=self.last_lk_timing,current_source_proof=self.last_source_confirmation,
            v49_fastpath=self.fastpath_detail,quick_current_candidate=self.quick_recovery_detail,
            current_proof_workspace=self.current_proofs.summary(),source_corners_s=source_corners_s,
            static_edges=dict(active=self._still_calm,release=self._still_release,
                edge_motion=self._still_edge_motion,current_measurement_retained=True),
            post_observation_s=post_observation_s,gray_s=gray_s,
            pre_obs_s=pre_obs_s,static_hold_s=hold_s,lk_s=lk_s,tail_s=tail_s,
            feature_s=feature_s,feature_roi_s=feature_roi_s,roi_search_gap=self._roi_search_gap,
            _diagnostics=diagnostics)


# ======================================================================
# ===== [22/28] v88_motion =====
# ======================================================================


"""Reuse motion masks and existing CPU checks; no device access or new native ABI."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class MotionWorkspace:
    def __init__(self):
        self.delta=np.empty((100,2),np.float32);self.square=np.empty_like(self.delta)
        self.fb=np.empty(100,np.float32);self.good=np.empty(100,np.bool_)
        self.finite=np.empty((100,2),np.bool_);self.flag=np.empty(100,np.bool_)
    def filter(self,p,forward,back,status,reverse):
        n=len(p);fb=self.fb[:n];good=self.good[:n];flag=self.flag[:n]
        delta=self.delta[:n];square=self.square[:n];finite=self.finite[:n]
        np.subtract(back.reshape(-1,2),p.reshape(-1,2),out=delta)
        np.multiply(delta,delta,out=square);np.add(square[:,0],square[:,1],out=fb);np.sqrt(fb,out=fb)
        np.less(fb,.8,out=good);np.isfinite(fb,out=flag);np.logical_and(good,flag,out=good)
        np.isfinite(forward.reshape(-1,2),out=finite)
        np.logical_and(finite[:,0],finite[:,1],out=flag);np.logical_and(good,flag,out=good)
        np.not_equal(status.ravel(),0,out=flag);np.logical_and(good,flag,out=good)
        np.not_equal(reverse.ravel(),0,out=flag);np.logical_and(good,flag,out=good)
        return fb,good


def distributed(points,source_quad,scale):
    if points is None or len(points)<8:return False
    # Match legacy input rounding before hull area and nearest-side checks.
    small=np.asarray((source_quad+.5)/scale-.5,np.float32)
    result=spatial_support__v31_native(points,small)
    if result is not None:return bool(result)
    return bool(_spatial_support__v31_tracking(points,small,'legacy'))


def valid_quad(quad,shape,previous):
    quad=np.asarray(quad,np.float32);previous=np.asarray(previous,np.float32)
    result=quad_valid__v31_native(quad,shape,previous)
    if result is not None:return bool(result)
    return bool(_valid__v31_tracking(quad,shape,previous,'legacy'))


# ======================================================================
# ===== [23/28] v87_v74_native =====
# ======================================================================


"""Optional host-architecture C++ helper. Compile once, never inside frame timing."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB__v87_v74_native=None
_STATUS__v87_v74_native={'backend':'numpy_analytic_tls','reason':'native_not_loaded','lk_backend':'opencv_python_binding'}

def prepare_native__v87_v74_native(build=True, required=False,cancel=None):
    global _LIB__v87_v74_native, _STATUS__v87_v74_native
    root=Path(__file__).resolve().parent
    check_cancel(cancel)
    source=root/'v87_v74_native.cpp'
    manifest=json.loads((root/'release_manifest.json').read_text(encoding='utf-8'))
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if manifest.get('release_id')!=RELEASE_ID or manifest.get('sha256',{}).get(source.name)!=digest:
        raise ValueError('native source/release hash mismatch; upload complete V31 folder')
    if _LIB__v87_v74_native is not None and _STATUS__v87_v74_native.get('source_sha256')==digest:return dict(_STATUS__v87_v74_native,already_loaded=True)
    cv_flags=[]
    cv_version=None
    pkg=shutil.which('pkg-config')
    if sys.platform.startswith('linux') and pkg:
        import cv2
        probe=setup_command([pkg,'--modversion','opencv4'],10,cancel,'V74_DETECTOR_OPENCV_VERSION')
        if probe.returncode==0 and probe.stdout.strip()==cv2.__version__:
            flags=setup_command([pkg,'--cflags','--libs','opencv4'],10,cancel,'V74_DETECTOR_OPENCV_FLAGS')
            if flags.returncode==0:
                cv_flags=shlex.split(flags.stdout);cv_version=probe.stdout.strip()
    variant='lk_'+cv_version if cv_flags else 'base'
    name='v31_native_'+digest[:16]+'_'+platform.machine()+'_'+variant+'.so'
    target=root/name
    try:
        if not sys.platform.startswith('linux'):
            raise RuntimeError('板端 Linux 编译；Windows 无需编译')
        cache_flags=['-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread']
        if platform.machine()=='armv7l':cache_flags+=['-mfpu=neon']
        if cv_flags:cache_flags+=['-DP11_OPENCV_LK']+cv_flags
        restore(target,source,'tracker',cache_flags,cancel,source_alias='v31_native.cpp')
        if not target.is_file():
            if not build:raise RuntimeError('native helper 尚未编译')
            compiler=shutil.which('g++') or shutil.which('c++')
            if not compiler:raise RuntimeError('板端没有 g++/c++；可用解析 TLS 回退，未声称达到30FPS')
            temp=target.with_suffix('.building.so')
            command=[compiler,'-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread',str(source),'-o',str(temp)]
            if platform.machine()=='armv7l':command+=['-mfpu=neon']
            if cv_flags:command+=['-DP11_OPENCV_LK']+cv_flags
            result=setup_command(command,180,cancel,'V74_DETECTOR_BUILD')
            if result.returncode!=0:raise RuntimeError(result.stdout[-4000:])
            check_cancel(cancel);temp.replace(target)
        lib=ctypes.CDLL(str(target))
        lib.p11_v31_abi.restype=ctypes.c_int
        if lib.p11_v31_abi()!=3107:raise RuntimeError('native helper ABI mismatch')
        vp=ctypes.c_void_p;ci=ctypes.c_int
        lib.p11_edges.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_edges.restype=ci
        lib.p11_guard.argtypes=[vp,vp,vp,ci,vp];lib.p11_guard.restype=ci
        lib.p11_gray2.argtypes=[vp,ci,ci,ci,vp];lib.p11_gray2.restype=ci
        lib.p11_gray_backend.restype=ci
        lib.p11_gaussian3.argtypes=[vp,ci,ci,ci,vp,vp];lib.p11_gaussian3.restype=ci
        lib.p11_quad_valid.argtypes=[vp,ci,ci,vp];lib.p11_quad_valid.restype=ci
        lib.p11_spatial.argtypes=[vp,ci,vp];lib.p11_spatial.restype=ci
        lib.p11_prepare.argtypes=[vp,ci,ci,vp];lib.p11_prepare.restype=ci
        lib.p11_packet.argtypes=[vp,vp,ci,ci,ci,ci,ci,vp];lib.p11_packet.restype=ci
        lib.p11_signature.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp];lib.p11_signature.restype=ci
        lib.p11_filter_available.restype=ci
        if lib.p11_filter_available():
            lib.p11_lk_filter.argtypes=[vp,vp,vp,vp,vp,vp,ci,vp,vp,ci,ci,vp,vp,vp]
            lib.p11_lk_filter.restype=ci
        lib.p11_plan_geometry.argtypes=[vp,vp,vp,ci,ci,vp,vp,ci,vp,vp]
        lib.p11_plan_geometry.restype=ci
        lib.p11_prepare_control.argtypes=[vp,vp,ci,ci,vp,vp,ci,vp,vp,ci,ci,ci,ci,ci,vp,vp]
        lib.p11_prepare_control.restype=ci
        lib.p11_lk_available.restype=ci
        if lib.p11_lk_available():
            lib.p11_lk_create.restype=vp
            lib.p11_lk_destroy.argtypes=[vp];lib.p11_lk_destroy.restype=None
            lib.p11_lk_anchor.argtypes=[vp,vp,ci,ci];lib.p11_lk_anchor.restype=ci
            lib.p11_lk_track.argtypes=[vp,vp,ci,ci,vp,ci,vp,vp,vp,vp,vp,vp,ci,ci]
            lib.p11_lk_track.restype=ci
            lib.p11_lk_promote.argtypes=[vp];lib.p11_lk_promote.restype=ci
        lib.p11_observe2.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp];lib.p11_observe2.restype=ci
        lib.p11_probe.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp];lib.p11_probe.restype=ci
        lib.p11_wait_io.argtypes=[vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp]
        lib.p11_wait_io.restype=ci
        lib.p11_profile_snapshot.argtypes=[vp,ci];lib.p11_profile_snapshot.restype=ci
        lib.p11_edges_checked.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp];lib.p11_edges_checked.restype=ci
        lib.p11_motion_values.argtypes=[vp,vp,vp,vp,vp,vp];lib.p11_motion_values.restype=ci
        lib.p11_copy_bgr.argtypes=[vp,vp,ci,ci,ci,ci];lib.p11_copy_bgr.restype=ci
        lib.p11_arm_io.argtypes=[vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ci];lib.p11_arm_io.restype=ci
        lib.p11_frame_state.argtypes=[vp,vp,vp];lib.p11_frame_state.restype=ci
        lib.p11_plan_wait.argtypes=[vp,vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp];lib.p11_plan_wait.restype=ci
        lib.p11_profile_os_snapshot.argtypes=[vp,ci];lib.p11_profile_os_snapshot.restype=ci
        lib.p11_edges_motion.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp]
        lib.p11_edges_motion.restype=ci
        lib.p11_frame_create.argtypes=[];lib.p11_frame_create.restype=vp
        lib.p11_frame_destroy.argtypes=[vp];lib.p11_frame_destroy.restype=None
        lib.p11_frame_prepare.argtypes=[vp,vp,vp,ci,ci,ci,ctypes.c_double,ctypes.c_double,ci,ci,vp,vp,vp,vp,ci,ci,vp,vp,ci,vp,vp,ci,ci,ci,ci,vp,vp,vp,vp,vp,vp]
        lib.p11_frame_prepare.restype=ci
        lib.p11_observe_edges.argtypes=[vp,ci,ci,ci,vp,vp,vp,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp,vp]
        lib.p11_observe_edges.restype=ci
        if lib.p11_lk_available():
            lib.p11_lk_checked.argtypes=[vp,vp,ci,ci,vp,ci,vp,ci,ci,ctypes.c_uint32,vp,vp,vp,vp,vp,vp];lib.p11_lk_checked.restype=ci
            lib.p11_lk_checked_motion.argtypes=[vp,vp,ci,ci,vp,ci,vp,ci,ci,ctypes.c_uint32,vp,vp,vp,vp,vp,vp,vp]
            lib.p11_lk_checked_motion.restype=ci
            lib.p11_roi_features.argtypes=[vp,ci,ci,vp,vp,ci,vp,vp];lib.p11_roi_features.restype=ci
        lib.p11_refine64.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_refine64.restype=ci
        lib.p11_yuyv_refine64.argtypes=[vp,ci,ci,ci,ci,vp,ctypes.c_double,vp,vp]
        lib.p11_yuyv_refine64.restype=ci
        lib.p11_preview_canvas_maps.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,ci,ci,vp,vp,vp,vp,vp]
        lib.p11_preview_canvas_maps.restype=ci
        lib.p11_preview_canvas_linear.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,ci,ci,vp,vp,vp,vp,vp,vp]
        lib.p11_preview_canvas_linear.restype=ci
        lib.p11_yuyv_profiles.argtypes=[vp,ci,ci,ci,vp,vp,ci,vp]
        lib.p11_yuyv_profiles.restype=ci
        lib.p11_io_probe.argtypes=[vp,vp,ctypes.c_uint32,ci,vp];lib.p11_io_probe.restype=ci
        lib.p11_owner_batch.argtypes=[vp,vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_double,ci,vp];lib.p11_owner_batch.restype=ci
        lib.p11_owner_complete.argtypes=[vp,vp,ctypes.c_uint32,ci,ctypes.c_double,vp]
        lib.p11_owner_complete.restype=ci
        lib.p11_yuyv_gray2.argtypes=[vp,ci,ci,ci,ci,vp];lib.p11_yuyv_gray2.restype=ci
        lib.p11_yuyv_observe2.argtypes=[vp,ci,ci,ci,ci,vp,vp,vp,vp];lib.p11_yuyv_observe2.restype=ci
        lib.p11_yuyv_observe_edges.argtypes=[vp,ci,ci,ci,ci,vp,vp,vp,vp,vp,vp,vp,vp,ctypes.c_double,vp,vp,vp,vp,vp];lib.p11_yuyv_observe_edges.restype=ci
        lib.p11_copy_yuyv.argtypes=[vp,vp,ci,ci,ci,ci];lib.p11_copy_yuyv.restype=ci
        lib.p11_yuyv_bgr.argtypes=[vp,ci,ci,ci,ci,vp];lib.p11_yuyv_bgr.restype=ci
        lib.p11_yuyv_preview.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci]
        lib.p11_yuyv_preview.restype=ci
        lib.p11_yuyv_preview_nearest.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci]
        lib.p11_yuyv_preview_nearest.restype=ci
        lib.p11_bgr_preview_nearest.argtypes=[vp,ci,ci,ci,vp,ci,ci,vp,vp]
        lib.p11_bgr_preview_nearest.restype=ci
        lib.p11_preview_pair_copy.argtypes=[vp,vp,ci,ci,ci,ci,vp,vp,ci,ci,ci,ci,vp]
        lib.p11_preview_pair_copy.restype=ci
        lib.p11_compact_preview.argtypes=[vp,ci,ci,ci,ci,vp,ci,ci,ci,vp,ci,vp,ci,ci,vp,vp,vp,vp]
        lib.p11_compact_preview.restype=ci
        lib.p11_coherent_profiles.argtypes=[vp,ci,ci,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp]
        lib.p11_coherent_profiles.restype=ci
        lib.p11_yuyv_exterior.argtypes=[vp,ci,ci,ci,vp,ctypes.c_double,ci,
            ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp,vp]
        lib.p11_yuyv_exterior.restype=ci
        lib.p11_locked_yuyv_exterior.argtypes=lib.p11_yuyv_exterior.argtypes+[ctypes.c_double]
        lib.p11_locked_yuyv_exterior.restype=ci
        lib.p11_v67_locked_pair.argtypes=[vp,ci,ci,ci,vp]+[ctypes.c_double]*5+[vp]+[ctypes.c_double]*3+[vp]*5
        lib.p11_v67_locked_pair.restype=ci
        lib.p11_v68_stabilize.argtypes=[vp,ci,ci,ci]+[vp]*6+[ci]+[vp]*4
        lib.p11_v68_stabilize.restype=ci
        lib.p11_locked_coherent_profiles.argtypes=[vp,ci,ci,ctypes.c_double,ctypes.c_double,
            ctypes.c_double,ctypes.c_double,ctypes.c_double,vp,vp,vp]
        lib.p11_locked_coherent_profiles.restype=ci
        lib.p11_owner_admit.argtypes=[vp,vp,vp,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_double,vp,vp]
        lib.p11_owner_admit.restype=ci
        lib.p11_preview_snapshot.argtypes=[vp,ci,ci,ci,vp,ci,ci,vp,ci,ci,ci,vp,ci,ci,vp]
        lib.p11_preview_snapshot.restype=ci
        remember(target,source,'tracker',cache_flags)
        _LIB__v87_v74_native=lib
        _STATUS__v87_v74_native={'source_sha256':digest,'backend':'cpp_V74_original_detection_kernels','path':str(target),'abi':3107,
                 'preview_snapshot_available':True,'preview_snapshot_signature':'paired_area2_15args',
                 'preview_snapshot_factors':[1,2],
                 'gray_backend':'yuyv_Y_area2_neon' if lib.p11_gray_backend()==2 else 'yuyv_Y_area2_scalar',
                 'geometry_backend':'cpp_projection_q8_and_fixed_guard',
                 'lk_backend':'cpp_cached_pyramids' if lib.p11_lk_available() else 'opencv_python_binding',
                 'lk_pyramid_cache':bool(lib.p11_lk_available()),'lk_pyramid_policy':'lazy_requested_levels',
                  'stable_edge_backend':'cpp_joint_motion_and_current_gray_recheck','locked_pair_backend':'cpp_current_locked64_independent24','packed_exterior_backend':'cpp_direct_YUV_bands_no_full_plane_pack',
                   'coherent_exterior_backend':'cpp_YUV_spatial_signed_peak_lock_TLS','opencv_dev_version':cv_version,
                 'blur_backend':'cpp_fixed_separable_neon' if lib.p11_gray_backend()==2 else 'cpp_fixed_separable_scalar',
                 'tracking_checks_backend':'cpp_ransac_motion_candidate' if lib.p11_filter_available() else 'python_ransac_cpp_geometry',
                 'original_Y_refinement_backend':'cpp_original_Y_64x65' if lib.p11_lk_available() else 'python_original_Y_64x65',
                 'control_backend':'cpp_checked_immutable_packet','appearance_backend':'cpp_gray_signature',
                 'merged_control_backend':'cpp_geometry_guard_tone_packet','preview_backend':'cpp_cached_q8_bilinear_direct_canvas',
                  'owner_completion_backend':'cpp_cached_owner_poll_snapshot',
                 'copy_backend':'cpp_bgr_memcpy','input_copy_backend':'cpp_yuyv_memcpy','owner_control_backend':'cpp_batch_arm_readonly_plan_wait',
                  'wait_backend':'cpp_owner_completion_gil_released','probe_backend':'cpp_aligned_32x32','observation_context':'cpp_edges_gate_motion_workspace','fused_frame_backend':'cpp_current_quad_probe_control'}
    except (RuntimeError,OSError,subprocess.SubprocessError) as exc:
        _LIB__v87_v74_native=None;_STATUS__v87_v74_native={'backend':'numpy_analytic_tls','reason':str(exc),
                          'lk_backend':'opencv_python_binding','lk_pyramid_cache':False}
        if required:raise RuntimeError(_STATUS__v87_v74_native['reason']) from exc
    return dict(_STATUS__v87_v74_native)

def native_status__v87_v74_native():return dict(_STATUS__v87_v74_native)

def gaussian3__v87_v74_native(gray, workspace):
    if _LIB__v87_v74_native is None:return None
    g=np.ascontiguousarray(gray,np.uint8);h,w=g.shape
    if workspace.dtype!=np.uint16 or workspace.size<3*w or not workspace.flags.c_contiguous:
        raise ValueError('Gaussian workspace layout invalid')
    out=np.empty_like(g)
    code=_LIB__v87_v74_native.p11_gaussian3(g.ctypes.data,w,h,g.strides[0],workspace.ctypes.data,out.ctypes.data)
    if code:raise ValueError('native Gaussian rejected: '+str(code))
    return out

def quad_valid__v87_v74_native(quad, shape, reference=None):
    if _LIB__v87_v74_native is None:return None
    q=np.ascontiguousarray(quad,np.float64).reshape(4,2)
    ref=None if reference is None else np.ascontiguousarray(reference,np.float64).reshape(4,2)
    code=_LIB__v87_v74_native.p11_quad_valid(q.ctypes.data,int(shape[1]),int(shape[0]),None if ref is None else ref.ctypes.data)
    if code<0:raise ValueError('native quad check rejected: '+str(code))
    return bool(code)

def spatial_support__v87_v74_native(points,quad):
    if _LIB__v87_v74_native is None:return None
    p=np.ascontiguousarray(points,np.float32).reshape(-1,2)
    if len(p)<4:return False
    if len(p)>100:raise ValueError('native boundary feature count exceeds100')
    q=np.ascontiguousarray(quad,np.float64).reshape(4,2)
    code=_LIB__v87_v74_native.p11_spatial(p.ctypes.data,len(p),q.ctypes.data)
    if code<0:raise ValueError('native spatial check rejected: '+str(code))
    return bool(code)

def filter_lk__v87_v74_native(points,forward,backward,status,reverse,error,anchor,previous,shape):
    if _LIB__v87_v74_native is None or not _LIB__v87_v74_native.p11_filter_available():return None
    p=np.ascontiguousarray(points,np.float32).reshape(-1,2);n=len(p)
    if not 4<=n<=100:raise ValueError('native LK filter feature count invalid')
    f=np.ascontiguousarray(forward,np.float32).reshape(n,2)
    b=np.ascontiguousarray(backward,np.float32).reshape(n,2)
    s=np.ascontiguousarray(status,np.uint8).reshape(n)
    sb=np.ascontiguousarray(reverse,np.uint8).reshape(n)
    e=np.ascontiguousarray(error,np.float32).reshape(n)
    a=np.ascontiguousarray(anchor,np.float64).reshape(4,2)
    old=np.ascontiguousarray(previous,np.float64).reshape(4,2)
    q=np.empty((4,2),np.float32);retained=np.empty((n,2),np.float32);stats=np.empty(5,np.float64)
    code=_LIB__v87_v74_native.p11_lk_filter(p.ctypes.data,f.ctypes.data,b.ctypes.data,s.ctypes.data,sb.ctypes.data,
        e.ctypes.data,n,a.ctypes.data,old.ctypes.data,shape[1],shape[0],q.ctypes.data,
        retained.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native LK consistency rejected: '+str(code))
    return q,retained[:int(stats[4])].copy(),dict(features=n,good_features=int(stats[1]),
        inlier_fraction=float(stats[2]),fb_median=float(stats[3]),filter_backend='cpp_ransac_geometry')

def prepare_regs__v87_v74_native(H,w,h):
    if _LIB__v87_v74_native is None:return None
    mat=np.ascontiguousarray(H,np.float64)
    if mat.shape!=(3,3):raise ValueError('H shape invalid')
    regs=np.empty(8,np.int32)
    code=_LIB__v87_v74_native.p11_prepare(mat.ctypes.data,int(w),int(h),regs.ctypes.data)
    if code:raise ValueError('native fixed H corner preflight rejected: '+str(code))
    return tuple(int(x) for x in regs)

def encode_packet__v87_v74_native(field,regs,wi,hi,wo,ho,flags):
    if _LIB__v87_v74_native is None:return None
    f=np.asarray(field)
    if f.shape!=(21,21,4) or f.dtype!=np.int32:raise ValueError('control field must be int32 21x21x4')
    f=np.ascontiguousarray(f)
    r=np.ascontiguousarray(regs,np.int32);out=np.empty(1776,dtype='<u4')
    code=_LIB__v87_v74_native.p11_packet(f.ctypes.data,r.ctypes.data,wi,hi,wo,ho,flags,out.ctypes.data)
    if code:raise ValueError('native control field/range rejected: '+str(code))
    return out.tobytes()

def gray_signature__v87_v74_native(gray,H,kernel):
    if _LIB__v87_v74_native is None:return None
    g=np.ascontiguousarray(gray,np.uint8);mat=np.ascontiguousarray(H,np.float64)
    k=np.ascontiguousarray(kernel,np.float32).reshape(9)
    if g.ndim!=2 or mat.shape!=(3,3):raise ValueError('signature layout invalid')
    structure=np.empty((128,96),np.float32);background=np.empty((8,8),np.float32)
    stats=np.empty(2,np.float64)
    code=_LIB__v87_v74_native.p11_signature(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],mat.ctypes.data,
        k.ctypes.data,structure.ctypes.data,background.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native appearance signature rejected: '+str(code))
    return dict(structure=structure,background=background,mean=float(stats[0]),std=float(stats[1]),
                backend='cpp_gray_signature')

def gray_area2__v87_v74_native(image, out):
    """Return False for unsupported layouts/sizes; never silently copy full BGR."""
    if _LIB__v87_v74_native is None:return False
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3 or
        image.strides[2]!=1 or image.strides[1]!=3):return False
    h,w=image.shape[:2]
    if w%2 or h%2 or min(w,h)<4 or max(w,h)>8192:return False
    if image.strides[0]<w*3:return False
    if out.shape!=(h//2,w//2) or out.dtype!=np.uint8 or not out.flags.c_contiguous:
        raise ValueError('gray observation destination layout invalid')
    code=_LIB__v87_v74_native.p11_gray2(image.ctypes.data,w,h,image.strides[0],out.ctypes.data)
    if code:raise ValueError('native gray observation rejected: '+str(code))
    return True

def merged_geometry__v87_v74_native(H, regs, nodes, nx, ny, uv, samples):
    """Return None for Python fallback; native failures remain hard rejections."""
    if _LIB__v87_v74_native is None:return None
    if len(regs)!=8 or any(int(x)!=x or not -(1<<31)<=int(x)<(1<<31) for x in regs):
        raise ValueError('native geometry registers outside signed32')
    mat=np.ascontiguousarray(H,np.float64)
    r=np.ascontiguousarray(regs,np.int32)
    if mat.shape!=(3,3) or r.shape!=(8,) or not np.isfinite(mat).all():
        raise ValueError('native geometry H/register shape invalid')
    nodes=np.ascontiguousarray(nodes,np.float64)
    uv=np.ascontiguousarray(uv,np.int32);samples=np.ascontiguousarray(samples,np.float64)
    if (nodes.shape!=(ny*nx,2) or uv.ndim!=2 or uv.shape[1]!=2 or
        samples.shape!=uv.shape or not 1<=len(uv)<=20000 or
        not (np.isfinite(nodes).all() and np.isfinite(samples).all())):
        raise ValueError('native geometry cached sample layout invalid')
    field=np.empty((21,21,4),np.int32);residual=np.empty(1,np.float64)
    code=_LIB__v87_v74_native.p11_plan_geometry(mat.ctypes.data,r.ctypes.data,nodes.ctypes.data,nx,ny,
        uv.ctypes.data,samples.ctypes.data,len(uv),field.ctypes.data,residual.ctypes.data)
    if code:raise ValueError('native geometry range/quantization rejected; no image DMA: '+str(code))
    return field,float(residual[0])

class LKCache__v87_v74_native:
    """Own both padded pyramids/derivatives; reuse forward/backward then promote."""
    def __init__(self):
        self.lib=_LIB__v87_v74_native
        self.forward=np.empty((100,1,2),np.float32);self.backward=np.empty_like(self.forward)
        self.status=np.empty(100,np.uint8);self.reverse=np.empty(100,np.uint8);self.errors=np.empty(100,np.float32)
        self.quad=np.empty((4,2),np.float32);self.retained=np.empty((100,2),np.float32)
        self.anchor_quad=np.empty((4,2),np.float64);self.previous_quad=np.empty_like(self.anchor_quad)
        self.filter_stats=np.empty(5,np.float64);self.flow_times=np.empty(2,np.float64)
        self.last_checked_timing={};self.motion_info=np.empty(4,np.float64)
        self.roi_quad=np.empty((4,2),np.float32);self.roi_stats=np.empty(3,np.int32)
        self.pointer=self.lib.p11_lk_create() if self.lib and self.lib.p11_lk_available() else None
        if self.lib and self.lib.p11_lk_available() and not self.pointer:
            raise MemoryError('native LK context allocation failed')
    def anchor(self,gray):
        if not self.pointer:return
        g=np.ascontiguousarray(gray,np.uint8)
        code=self.lib.p11_lk_anchor(self.pointer,g.ctypes.data,g.shape[1],g.shape[0])
        if code:raise ValueError('native LK anchor rejected: '+str(code))
    def track(self,gray,points,initial=None,levels=3,iterations=20):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if guess is not None and not np.isfinite(guess).all():raise ValueError('LK prediction not finite')
        if not 4<=len(p)<=100:raise ValueError('LK feature count outside4..100')
        f=self.forward[:len(p)];b=self.backward[:len(p)];s=self.status[:len(p)];sb=self.reverse[:len(p)]
        error=self.errors[:len(p)]
        code=self.lib.p11_lk_track(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],
            p.ctypes.data,len(p),f.ctypes.data,b.ctypes.data,s.ctypes.data,sb.ctypes.data,error.ctypes.data,
            None if guess is None else guess.ctypes.data,int(levels),int(iterations))
        if code:raise ValueError('native LK rejected frame: '+str(code))
        return f,s,error,b,sb
    def checked(self,gray,points,initial,anchor,previous,generation,levels=3,iterations=20):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if not 4<=len(p)<=100 or (guess is not None and not np.isfinite(guess).all()):raise ValueError('LK prediction/features invalid')
        if isinstance(generation,bool) or not isinstance(generation,(int,np.integer)) or not 0<=int(generation)<0xffffffff:raise ValueError('LK frame generation invalid')
        self.anchor_quad[:]=anchor;self.previous_quad[:]=previous
        self.filter_stats.fill(0.);self.flow_times.fill(0.)
        began=time.perf_counter();cpu=time.thread_time()
        code=self.lib.p11_lk_checked_motion(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],p.ctypes.data,len(p),
            None if guess is None else guess.ctypes.data,int(levels),int(iterations),int(generation),self.anchor_quad.ctypes.data,
            self.previous_quad.ctypes.data,self.quad.ctypes.data,self.retained.ctypes.data,self.filter_stats.ctypes.data,self.flow_times.ctypes.data,self.motion_info.ctypes.data)
        self.last_checked_timing=dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),native_checked_wall_s=time.perf_counter()-began,
            native_checked_thread_cpu_s=time.thread_time()-cpu,native_checked_code=int(code),
            transaction_backend='cpp_bidirectional_lk_filter',
            motion_model={0:'unavailable',1:'similarity_candidate',2:'projective_candidate'}.get(int(self.motion_info[0]),'invalid'),
            motion_good_features=int(self.motion_info[1]),motion_inliers=int(self.motion_info[2]),
            motion_reprojection_rms=float(self.motion_info[3]),current_four_edges_required=True)
        if code<=-100:raise ValueError('native LK rejected frame: '+str(code+100))
        if code:raise ValueError('native LK consistency rejected: '+str(code))
        n=int(self.filter_stats[4])
        detail=dict(lk_backend='cpp_cached_pyramids_checked',features=len(p),good_features=int(self.filter_stats[1]),filter_backend='cpp_bidirectional_lk_filter',
            inliers=n,inlier_fraction=float(self.filter_stats[2]),fb_median=float(self.filter_stats[3]),
            motion_model=self.last_checked_timing['motion_model'],motion_reprojection_rms=float(self.motion_info[3]),
            current_four_edges_required=True)
        return self.quad.copy(),self.retained[:n].copy(),detail,dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),transaction_backend='cpp_bidirectional_lk_filter')
    def roi_features(self,gray,quad,retained=None):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);points=np.empty((0,2),np.float32) if retained is None else np.ascontiguousarray(retained,np.float32).reshape(-1,2)
        if len(points)>100:raise ValueError('ROI retained features exceed100')
        self.roi_quad[:]=quad
        code=self.lib.p11_roi_features(g.ctypes.data,g.shape[1],g.shape[0],self.roi_quad.ctypes.data,
            points.ctypes.data,len(points),self.retained.ctypes.data,self.roi_stats.ctypes.data)
        if code:raise ValueError('Native corner ROI rejected: '+str(code))
        return self.retained[:int(self.roi_stats[0])].copy(),dict(action='native_outer_corner_roi',regions=int(self.roi_stats[1]),
            added=int(self.roi_stats[2]),features=int(self.roi_stats[0]),workspace_reused=True)
    def promote(self):
        if self.pointer:
            code=self.lib.p11_lk_promote(self.pointer)
            if code:raise ValueError('native LK promotion failed: '+str(code))
    def close(self):
        if self.pointer:
            self.lib.p11_lk_destroy(self.pointer);self.pointer=None
    def __del__(self):
        try:self.close()
        except Exception:pass

def measure_edges__v87_v74_native(gray, quad, radius, checked=False):
    if _LIB__v87_v74_native is None:return None
    g=np.ascontiguousarray(gray,dtype=np.uint8)
    if g.ndim!=2:raise ValueError('native edges require grayscale')
    q=np.ascontiguousarray(quad,dtype=np.float64).reshape(4,2)
    result=np.empty((4,2),np.float64);stats=np.empty(21,np.float64)
    function=_LIB__v87_v74_native.p11_edges_checked if checked else _LIB__v87_v74_native.p11_edges
    code=function(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],q.ctypes.data,
                       float(radius),result.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('native edge helper rejected input: '+str(code))
    return result.astype(np.float32),dict(edge_support=stats[:4].tolist(),
        edge_polarity=stats[4:8].astype(int).tolist(),refined_corners=int(stats[16]),
        supported_edges=int(stats[17]),median_edge_shift=float(np.median(stats[8:12])),
        edge_rms=stats[12:16].tolist(),max_edge_rms=float(max(stats[12:16])),
        edge_backend='cpp_analytic_tls',native_valid=bool(stats[20]) if checked else None)

def fixed_coordinates__v87_v74_native(regs,u,v,field):
    if len(regs)!=8 or any(int(r)!=r or not -(1<<31)<=int(r)<(1<<31) for r in regs):
        raise ValueError('H寄存器超出signed32，禁止截断后误加载')
    if _LIB__v87_v74_native is None:
        from geometry import coordinates as coordinates
        x,y,_=coordinates(regs,u,v,field)
        return x/65536.,y/65536.
    u,v=np.broadcast_arrays(u,v)
    uv=np.ascontiguousarray(np.column_stack([u.ravel(),v.ravel()]),np.int32)
    r=np.ascontiguousarray(regs,np.int32);f=np.ascontiguousarray(field,np.int32)
    out=np.empty((len(uv),2),np.float64)
    if r.shape!=(8,) or f.shape!=(21,21,4):raise ValueError('native guard shape mismatch')
    code=_LIB__v87_v74_native.p11_guard(r.ctypes.data,f.ctypes.data,uv.ctypes.data,len(uv),out.ctypes.data)
    if code:raise ValueError('定点几何采样范围不安全，未启动图像DMA: '+str(code))
    return out[:,0].reshape(u.shape),out[:,1].reshape(u.shape)


def prepare_control__v87_v74_native(H,nodes,nx,ny,uv,samples,gain,offset,wi,hi,wo,ho,flags=15):
    """One native call; same fixed arithmetic and 0.65-source-pixel guard."""
    if _LIB__v87_v74_native is None:return None
    mat=np.ascontiguousarray(H,np.float64)
    nodes=np.ascontiguousarray(nodes,np.float64)
    uv=np.ascontiguousarray(uv,np.int32)
    samples=np.ascontiguousarray(samples,np.float64)
    gain=np.ascontiguousarray(gain,np.int32);offset=np.ascontiguousarray(offset,np.int32)
    if (mat.shape!=(3,3) or nodes.shape!=(nx*ny,2) or uv.ndim!=2 or uv.shape[1]!=2
        or samples.shape!=uv.shape or gain.shape!=(21,21) or offset.shape!=(21,21)
        or not 1<=len(uv)<=20000 or not 1<=nx<=21 or not 1<=ny<=21
        or not all(np.isfinite(a).all() for a in (mat,nodes,samples))):
        raise ValueError('merged control geometry layout invalid')
    if any(isinstance(n,bool) or int(n)!=n or not 2<=int(n)<=1280 for n in (wi,hi,wo,ho)):
        raise ValueError('merged control dimensions outside2..1280')
    out=np.empty(1776,dtype='<u4');residual=np.empty(1,np.float64)
    code=_LIB__v87_v74_native.p11_prepare_control(mat.ctypes.data,nodes.ctypes.data,nx,ny,uv.ctypes.data,
        samples.ctypes.data,len(uv),gain.ctypes.data,offset.ctypes.data,wi,hi,wo,ho,flags,
        out.ctypes.data,residual.ctypes.data)
    if code:raise ValueError('native merged control rejected; no image DMA: '+str(code))
    return out.tobytes(),float(residual[0])


def probe_signature__v87_v74_native(gray,H):
    if _LIB__v87_v74_native is None:return None
    g=np.ascontiguousarray(gray,np.uint8);mat=np.ascontiguousarray(H,np.float64)
    if g.ndim!=2 or mat.shape!=(3,3):raise ValueError('Probe layout invalid')
    structure=np.empty((32,32),np.float32);background=np.empty((8,8),np.float32)
    stats=np.empty(2,np.float64)
    code=_LIB__v87_v74_native.p11_probe(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],mat.ctypes.data,
        structure.ctypes.data,background.ctypes.data,stats.ctypes.data)
    if code:raise ValueError('Aligned probe rejected: '+str(code))
    return dict(structure=structure,background=background,mean=float(stats[0]),std=float(stats[1]),
        backend='cpp_aligned_32x32')


def wait_io__v87_v74_native(pl_array,dma_array,before,kind,timeout,out=None):
    """None means unsupported layout: caller retains Python polling. Never copy MMIO."""
    if _LIB__v87_v74_native is None:return None
    for array,minimum in ((pl_array,0x3c),(dma_array,0x38)):
        if (not isinstance(array,np.ndarray) or array.dtype!=np.dtype('uint32')
            or not array.flags.c_contiguous or array.nbytes<minimum or array.ctypes.data%4):return None
    if np.isfinite(timeout) and float(timeout)>3600:return None
    if int(kind) not in (0,1) or not np.isfinite(timeout) or not 0<float(timeout)<=3600:
        raise ValueError('Native wait arguments invalid')
    result=np.empty(4,np.uint32) if out is None else out
    if result.shape!=(4,) or result.dtype!=np.uint32 or not result.flags.c_contiguous or not result.flags.writeable:raise ValueError('Wait output workspace invalid')
    code=_LIB__v87_v74_native.p11_wait_io(pl_array.ctypes.data,dma_array.ctypes.data,int(before)&0xffffffff,
        int(kind),float(timeout),result.ctypes.data)
    if code<0:raise ValueError('Native wait rejected: '+str(code))
    return int(code),dict(pl_status=int(result[0]),pl_error=int(result[1]),tx=int(result[2]),rx=int(result[3]))


def fused_observation2__v87_v74_native(image,scratch,workspace,out=None,timing=None):
    if _LIB__v87_v74_native is None:return None
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3
        or image.strides[1:]!=(3,1) or image.strides[0]<image.shape[1]*3):return None
    h,w=image.shape[:2]
    if w%2 or h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (scratch.shape!=(h//2,w//2) or scratch.dtype!=np.uint8 or not scratch.flags.c_contiguous
        or workspace.dtype!=np.uint16 or workspace.size<3*(w//2) or not workspace.flags.c_contiguous):
        raise ValueError('Fused observation workspace invalid')
    if out is None:out=np.empty_like(scratch)
    if timing is None:timing=np.empty(2,np.float64)
    if out.shape!=scratch.shape or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable or np.shares_memory(out,scratch):
        raise ValueError('Observation output aliases scratch or has invalid layout')
    code=_LIB__v87_v74_native.p11_observe2(image.ctypes.data,w,h,image.strides[0],scratch.ctypes.data,
        workspace.ctypes.data,out.ctypes.data,timing.ctypes.data)
    if code:raise ValueError('Fused observation rejected: '+str(code))
    return out,dict(resize_gray_s=float(timing[0]),blur_s=float(timing[1]))

def profile_snapshot__v87_v74_native(raw=False,out=None):
    if _LIB__v87_v74_native is None:return None if raw else {}
    f=_LIB__v87_v74_native.p11_profile_snapshot
    if out is None:out=np.empty(90,np.float64)
    if (not isinstance(out,np.ndarray) or out.dtype!=np.float64 or out.shape!=(90,)
            or not out.flags.c_contiguous or not out.flags.writeable):
        raise ValueError('Native profile output workspace invalid')
    if f(out.ctypes.data,len(out)):raise RuntimeError('Native profile layout rejected')
    if raw:return out
    names=['p11_lk_anchor', 'p11_lk_track', 'p11_lk_promote', 'p11_gray2', 'p11_gaussian3', 'p11_quad_valid', 'p11_spatial', 'p11_lk_filter', 'p11_edges', 'p11_guard', 'p11_plan_geometry', 'p11_prepare', 'p11_packet', 'p11_signature', 'p11_prepare_control', 'p11_probe', 'p11_wait_io', 'p11_observe2', 'p11_edges_motion', 'p11_copy_bgr', 'p11_arm_io', 'p11_plan_wait', 'p11_frame_state', 'p11_motion_values', 'outer_calls', 'p11_observe_edges', 'p11_lk_checked', 'p11_roi_features', 'p11_owner_batch', 'p11_owner_complete']
    return {name:dict(wall_s=float(out[i*3]),thread_cpu_s=float(out[i*3+1]),calls=int(out[i*3+2])) for i,name in enumerate(names)}


def _mmio_layout__v87_v74_native(array,minimum):
    return (isinstance(array,np.ndarray) and array.dtype==np.dtype('uint32')
        and array.flags.c_contiguous and array.nbytes>=minimum and array.ctypes.data%4==0)

def copy_bgr_native__v87_v74_native(source,destination):
    if _LIB__v87_v74_native is None:return False
    h,w=source.shape[:2]
    code=_LIB__v87_v74_native.p11_copy_bgr(source.ctypes.data,destination.ctypes.data,w,h,
                          source.strides[0],destination.strides[0])
    if code:raise ValueError('Native BGR copy rejected: '+str(code))
    return True

def arm_io__v87_v74_native(pl,dma,src,dst,send,receive,sequence=None):
    if _LIB__v87_v74_native is None or not _mmio_layout__v87_v74_native(pl,12) or not _mmio_layout__v87_v74_native(dma,0x5c):return False
    values=(src,dst,send,receive,0 if sequence is None else sequence)
    if any(isinstance(n,bool) or int(n)!=n or not 0<=int(n)<=0xffffffff for n in values):
        raise ValueError('Native arm uint32 argument invalid')
    code=_LIB__v87_v74_native.p11_arm_io(pl.ctypes.data,dma.ctypes.data,*map(int,values),int(sequence is not None))
    if code:raise RuntimeError('Native owner arm rejected: '+str(code))
    return True

def frame_state__v87_v74_native(pl,dma):
    if _LIB__v87_v74_native is None or not _mmio_layout__v87_v74_native(pl,0xcc) or not _mmio_layout__v87_v74_native(dma,0x5c):return None
    out=np.empty(12,np.uint32)
    if _LIB__v87_v74_native.p11_frame_state(pl.ctypes.data,dma.ctypes.data,out.ctypes.data):
        raise RuntimeError('Native frame state rejected')
    return tuple(map(int,out))

def plan_wait__v87_v74_native(planner,pixel,dma,sequence,kind,timeout):
    if (_LIB__v87_v74_native is None or not _mmio_layout__v87_v74_native(planner,0x74) or not _mmio_layout__v87_v74_native(pixel,0xe0)
        or not _mmio_layout__v87_v74_native(dma,0x38)):return None
    if (isinstance(sequence,bool) or not 0<int(sequence)<=0xffffffff or kind not in (0,1)
        or not np.isfinite(timeout) or not 0<float(timeout)<=3600):
        raise ValueError('Native plan wait argument invalid')
    out=np.zeros(4,np.uint32)
    code=_LIB__v87_v74_native.p11_plan_wait(planner.ctypes.data,pixel.ctypes.data,dma.ctypes.data,
                           int(sequence),int(kind),float(timeout),out.ctypes.data)
    if code<0:raise RuntimeError('Native plan wait rejected')
    return int(code),tuple(map(int,out))


def motion_values__v87_v74_native(candidate,prediction,previous,anchor,drift):
    if _LIB__v87_v74_native is None:return None
    points=[np.ascontiguousarray(q,np.float32).reshape(4,2) for q in (candidate,prediction,previous,anchor)]
    if drift.shape!=(4,2) or drift.dtype!=np.float32 or not drift.flags.c_contiguous:
        raise ValueError('Motion drift workspace invalid')
    out=np.empty(5,np.float64)
    code=_LIB__v87_v74_native.p11_motion_values(*(q.ctypes.data for q in points),drift.ctypes.data,out.ctypes.data)
    if code:raise ValueError('Native motion reduction rejected: '+str(code))
    return tuple(map(float,out))


class EdgeMotionWorkspace__v87_v74_native:
    """Private chronological PS context; buffers reused across frames."""
    def __init__(self):
        self.predicted=np.empty((4,2),np.float64)
        self.previous=np.empty((4,2),np.float32);self.anchor=np.empty((4,2),np.float32)
        self.polarity=np.empty(4,np.int32)
        self.result=np.empty((4,2),np.float64);self.stats=np.empty(21,np.float64)
        self.result32=np.empty((4,2),np.float32);self.light_results=False;self.decode_timing=(0.,0.)
        self.motion=np.empty(5,np.float64);self.gate=np.empty(6,np.float64)
    def measure(self,gray,prediction,previous,anchor,drift,polarity,radius=5.):
        if _LIB__v87_v74_native is None:return None
        g=np.ascontiguousarray(gray,np.uint8)
        if g.ndim!=2 or drift.dtype!=np.float32 or drift.shape!=(4,2) or not drift.flags.c_contiguous:
            raise ValueError('Observation context layout invalid')
        self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
        code=_LIB__v87_v74_native.p11_edges_motion(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,
            drift.ctypes.data,self.polarity.ctypes.data,float(radius),self.result.ctypes.data,
            self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data)
        if code:raise ValueError('Native observation context rejected: '+str(code))
        return self.decode()
    def decode(self):
        if self.light_results:
            from display import decode_light_edges as decode_light_edges
            return decode_light_edges(self)
        stats=self.stats;shifts=sorted(float(v) for v in stats[8:12])
        evidence=dict(valid=bool(stats[20]),edge_support=stats[:4].tolist(),
            edge_polarity=stats[4:8].astype(int).tolist(),refined_corners=int(stats[16]),
            supported_edges=int(stats[17]),median_edge_shift=(shifts[1]+shifts[2])*.5,
            edge_rms=stats[12:16].tolist(),max_edge_rms=float(self.gate[2]),
            edge_backend='cpp_edges_gate_motion_context')
        gate=dict(reliable=bool(self.gate[0]),min_support=float(self.gate[1]),
            max_rms=float(self.gate[2]),prediction_correction=float(self.gate[3]),
            polarity_flips=int(self.gate[4]),radius=float(self.gate[5]))
        return self.result.astype(np.float32),evidence,gate,tuple(map(float,self.motion)) if gate['reliable'] else None


def profile_os_snapshot__v87_v74_native(out=None):
    if _LIB__v87_v74_native is None:return None
    values=np.empty((30,4),np.float64) if out is None else out
    if (not isinstance(values,np.ndarray) or values.dtype!=np.float64 or values.shape!=(30,4)
            or not values.flags.c_contiguous or not values.flags.writeable):
        raise ValueError('Native OS profile output workspace invalid')
    code=_LIB__v87_v74_native.p11_profile_os_snapshot(values.ctypes.data,values.size)
    if code:raise RuntimeError('Native OS profile layout mismatch')
    return values


class FusedPrepareLayoutError__v87_v74_native(ValueError):
    """A Python/native memory contract error; distinct from a scene rejection."""


def _frame_int__v87_v74_native(value,low,high,name):
    if (isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer))
            or not low<=int(value)<=high):
        raise FusedPrepareLayoutError__v87_v74_native('Fused '+name+' must be integer in '+str((low,high)))
    return int(value)


def _readonly_array__v87_v74_native(value,dtype,shape,name):
    try:array=np.ascontiguousarray(value,dtype)
    except (TypeError,ValueError) as exc:
        raise FusedPrepareLayoutError__v87_v74_native('Fused '+name+' conversion invalid') from exc
    if array.shape!=shape:
        raise FusedPrepareLayoutError__v87_v74_native('Fused '+name+' shape invalid: '+str(array.shape))
    # Bytes-backed snapshots cannot be mutated by their original owner. A
    # readonly typed cache supplied by the chronological producer needs no copy.
    if array.flags.writeable:array=np.frombuffer(array.tobytes(),dtype).reshape(shape)
    return array


def _destroy_frame_context__v87_v74_native(library,pointer):
    # The finalizer's arguments keep the owning CDLL alive independently of
    # module-global _LIB; closing a later session cannot unload this callback.
    library.p11_frame_destroy(pointer)


class FramePrepareWorkspace__v87_v74_native:
    """One chronological producer owns input, output and native guard scratch.

    scale is exactly [source_width / gray_width, source_height / gray_height].
    C++ consumes separate sx/sy doubles; scalar scale is deliberately rejected.
    Only immutable reference/control identities qualify for validation caching.
    Current q, scale and H are rewritten for every frame. Returned observations,
    H and control bytes own their memory and never alias this scratch workspace.
    """
    def __init__(self):
        self.quad=np.empty((4,2),np.float64);self.scale=np.empty(2,np.float64)
        self.H=np.empty((3,3),np.float64);self.shape=np.empty(4,np.float64)
        self.structure=np.empty((32,32),np.float32);self.background=np.empty((8,8),np.float32)
        self.info=np.empty(11,np.float64);self.packet=np.empty(1776,dtype='<u4')
        self._quad_pointer=self.quad.ctypes.data
        self._output_pointers=tuple(a.ctypes.data for a in
            (self.H,self.shape,self.structure,self.background,self.info,self.packet))
        self.references=None;self.reference_arrays=None;self.reference_pointers=None
        self.control_arrays=None;self.control_inputs=None;self.control_layout=None;self.control_pointers=None
        self._owner=None;self._context=None;self._context_library=None;self._context_finalizer=None

    def close(self):
        if self._context_finalizer is not None:self._context_finalizer()
        self._context=None;self._context_library=None;self._context_finalizer=None

    def _native_context(self):
        if self._context_library is not _LIB__v87_v74_native:
            self.close();pointer=_LIB__v87_v74_native.p11_frame_create()
            if not pointer:raise RuntimeError('Native frame workspace allocation failed')
            self._context=pointer;self._context_library=_LIB__v87_v74_native
            # Retain this specific CDLL, not the later module-global _LIB.
            self._context_finalizer=weakref.finalize(self,_destroy_frame_context__v87_v74_native,_LIB__v87_v74_native,pointer)
        return self._context

    def prepare(self,q,gray,scale,wo,ho,refs,control=None):
        if _LIB__v87_v74_native is None:return None
        began=time.perf_counter();owner=threading.get_ident()
        if self._owner is None:self._owner=owner
        elif owner!=self._owner:raise FusedPrepareLayoutError__v87_v74_native('Fused workspace requires one chronological producer thread')
        try:qa=np.asarray(q);sa=np.asarray(scale);g=np.asarray(gray)
        except (TypeError,ValueError) as exc:
            raise FusedPrepareLayoutError__v87_v74_native('Fused frame input conversion invalid') from exc
        if qa.shape!=(4,2) or qa.dtype.kind not in 'fiu' or sa.shape!=(2,) or sa.dtype.kind not in 'fiu':
            raise FusedPrepareLayoutError__v87_v74_native('Fused quad must be4x2; scale must be finite positive [sx, sy]')
        if (g.dtype!=np.uint8 or g.ndim!=2 or min(g.shape)<2 or max(g.shape)>1280
                or g.strides[1]!=1 or not g.shape[1]<=g.strides[0]<=0x7fffffff):
            raise FusedPrepareLayoutError__v87_v74_native('Fused grayscale byte/stride contract invalid')
        np.copyto(self.quad,qa,casting='unsafe');np.copyto(self.scale,sa,casting='unsafe')
        sx=float(self.scale[0]);sy=float(self.scale[1])
        if not math.isfinite(sx) or not math.isfinite(sy) or sx<=0 or sy<=0:
            raise FusedPrepareLayoutError__v87_v74_native('Fused scale must contain finite positive sx and sy')
        # Current q values are checked by p11_quad_h before probing or control
        # encoding. A scene/quad rejection must not disable later valid frames.
        wo=_frame_int__v87_v74_native(wo,2,1280,'output width');ho=_frame_int__v87_v74_native(ho,2,1280,'output height')
        try:key=tuple(refs)
        except TypeError as exc:raise FusedPrepareLayoutError__v87_v74_native('Fused references tuple invalid') from exc
        if len(key)!=3:raise FusedPrepareLayoutError__v87_v74_native('Probe references require structure/background/shape')
        reference_hit=(self.references is not None and all(a is b for a,b in zip(key,self.references)))
        if not reference_hit:
            self.reference_arrays=tuple(_readonly_array__v87_v74_native(a,dtype,shape,name)
                for a,dtype,shape,name in zip(key,(np.float32,np.float32,np.float64),
                    ((32,32),(8,8),(4,)),('structure reference','background reference','shape reference')))
            self.reference_pointers=tuple(a.ctypes.data for a in self.reference_arrays)
            self.references=key if all(isinstance(a,np.ndarray) and not a.flags.writeable for a in key) else None
        rs,rb,rshape=self.reference_pointers
        control_hit=False
        if control is None:
            nx=ny=count=wi=hi=flags=0;pointers=(0,0,0,0,0)
        else:
            if not isinstance(control,(tuple,list)) or len(control)!=10:
                raise FusedPrepareLayoutError__v87_v74_native('Fused control tuple requires10 fields')
            nodes,nx,ny,uv,samples,gain,offset,wi,hi,flags=control
            nx=_frame_int__v87_v74_native(nx,2,21,'node columns');ny=_frame_int__v87_v74_native(ny,2,21,'node rows')
            wi=_frame_int__v87_v74_native(wi,2,1280,'input width');hi=_frame_int__v87_v74_native(hi,2,1280,'input height')
            flags=_frame_int__v87_v74_native(flags,0,15,'border flags')
            arrays=(nodes,uv,samples,gain,offset);layout=(nx,ny,wi,hi,flags)
            control_hit=(self.control_inputs is not None and layout==self.control_layout
                and all(a is b for a,b in zip(arrays,self.control_inputs)))
            if not control_hit:
                expected_dtypes=(np.float64,np.int32,np.float64,np.int32,np.int32)
                if (any(not isinstance(a,np.ndarray) or a.dtype!=dtype or not a.flags.c_contiguous
                        for a,dtype in zip(arrays,expected_dtypes))
                    or nodes.shape!=(nx*ny,2) or uv.ndim!=2 or uv.shape[1]!=2
                    or samples.shape!=uv.shape or gain.shape!=(21,21) or offset.shape!=(21,21)
                    or not 1<=len(uv)<=20000):
                    raise FusedPrepareLayoutError__v87_v74_native('Fused control pointer/dtype/layout invalid before native access')
                self.control_arrays=tuple(_readonly_array__v87_v74_native(a,dtype,a.shape,'control input')
                    for a,dtype in zip(arrays,expected_dtypes))
                self.control_pointers=tuple(a.ctypes.data for a in self.control_arrays)
                self.control_layout=layout
                self.control_inputs=arrays if all(not a.flags.writeable for a in arrays) else None
            pointers=self.control_pointers;count=len(self.control_arrays[1])
        context=self._native_context();native_begin=time.perf_counter()
        code=_LIB__v87_v74_native.p11_frame_prepare(context,self._quad_pointer,g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],
            sx,sy,wo,ho,rs,rb,rshape,pointers[0],nx,ny,pointers[1],pointers[2],count,
            pointers[3],pointers[4],wi,hi,flags,int(control is not None),*self._output_pointers)
        if code in (-1,-5,-7):
            raise FusedPrepareLayoutError__v87_v74_native('Native frame pointer/reference/owner contract rejected: '+str(code))
        if code:raise ValueError('Current quad/probe rejected before image DMA: '+str(code))
        publish_begin=time.perf_counter()
        observations=tuple(a.copy() for a in (self.structure,self.background,self.shape))
        for a in observations:a.setflags(write=False)
        probe=dict(structure=observations[0],background=observations[1],shape=observations[2],
            mean=float(self.info[0]),std=float(self.info[1]),backend='cpp_current_quad_probe_control')
        changes=tuple(float(x) for x in self.info[2:5])
        status=int(self.info[6]);wire=self.packet.tobytes() if control is not None and status==0 else None
        H=self.H.copy();finished=time.perf_counter()
        return dict(H=H,probe=probe,changes=changes,wire=wire,residual=float(self.info[5]),control_code=status,
            h_native_s=float(self.info[7]),probe_native_s=float(self.info[8]),control_native_s=float(self.info[9]),
            native_transaction_s=float(self.info[10]),wrapper_prepare_s=native_begin-began,
            wrapper_publish_s=finished-publish_begin,wrapper_total_s=finished-began,
            reference_cache_hit=reference_hit,control_cache_hit=control_hit)


class ObservationWorkspace__v87_v74_native(EdgeMotionWorkspace__v87_v74_native):
    """Own bounded gray/filter/corner buffers; no pointer escapes the call."""
    def __init__(self):
        super().__init__();self.times=np.empty(4,np.float64)
    def observe(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius=5.):
        if _LIB__v87_v74_native is None:return None
        h,w=image.shape[:2]
        if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3 or image.strides[1:]!=(3,1)
            or image.strides[0]<w*3 or min(w,h)<4 or max(w,h)>1280 or w%2 or h%2):return None
        if (out.shape!=(h//2,w//2) or scratch.shape!=out.shape or out.dtype!=np.uint8 or scratch.dtype!=np.uint8
            or rows.dtype!=np.uint16 or rows.size<3*(w//2) or drift.dtype!=np.float32 or drift.shape!=(4,2)
            or any(not a.flags.c_contiguous or not a.flags.writeable for a in (scratch,rows,out,drift))
            or np.shares_memory(out,scratch)):
            raise ValueError('Merged observation workspace invalid before native access')
        self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
        code=_LIB__v87_v74_native.p11_observe_edges(image.ctypes.data,w,h,image.strides[0],scratch.ctypes.data,rows.ctypes.data,out.ctypes.data,
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,drift.ctypes.data,self.polarity.ctypes.data,
            float(radius),self.result.ctypes.data,self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data,self.times.ctypes.data)
        if code and code>-200:raise ValueError('Merged observation rejected: '+str(code))
        return (self.decode() if code==0 else None),dict(edge_error=(code+200 if code else None),resize_gray_s=float(self.times[0]),blur_s=float(self.times[1]),edge_gate_motion_s=float(self.times[2]),
            native_transaction_s=float(self.times[3]),transaction_backend='cpp_gray_gaussian_edges_confidence_motion')

class OwnerBatch__v87_v74_native:
    """Cached admitted mappings/output scratch; only the creating owner may call."""
    def __init__(self,planner,pixel,dma):
        import threading
        self.lib=_LIB__v87_v74_native;self.owner=threading.get_ident();self.arrays=(planner,pixel,dma)
        self.available=bool(self.lib)
        for a,minimum in zip(self.arrays,(0xc4,0xe4,0x5c)):
            self.available=self.available and isinstance(a,np.ndarray) and a.dtype==np.uint32 and a.flags.c_contiguous and a.nbytes>=minimum and a.ctypes.data%4==0
        self.pointers=tuple(a.ctypes.data for a in self.arrays) if self.available else ()
        self.state=np.empty(20,np.uint32)
    def call(self,operation=0,sequence=0,src=0,dst=0,timeout=1.):
        import threading
        if threading.get_ident()!=self.owner:raise RuntimeError('Native device transaction must stay on owner')
        if not self.available:return None
        if not 0<float(timeout)<=(30 if operation==3 else 1) or not np.isfinite(timeout):raise ValueError('Owner batch deadline invalid')
        code=self.lib.p11_owner_batch(*self.pointers,int(src),int(dst),int(sequence),float(timeout),int(operation),self.state.ctypes.data)
        if code<0:raise ValueError('Native device transaction layout rejected: '+str(code))
        return int(code),self.state
    def admit(self,sequence,input_size,output_size,capacity,timeout=1.):
        if threading.get_ident()!=self.owner:raise RuntimeError('Native device transaction must stay on owner')
        if not self.available:return None
        if not hasattr(self,'admit_times'):self.admit_times=np.empty(2,np.float64)
        code=self.lib.p11_owner_admit(*self.pointers,int(sequence),int(input_size),int(output_size),int(capacity),float(timeout),self.state.ctypes.data,self.admit_times.ctypes.data)
        if code<0:raise ValueError('Native owner admission layout rejected '+str(code))
        return int(code),self.state,self.admit_times


def preview_snapshot_available__v87_v74_native():
    # The loader admits ABI3107 and binds the unchanged 15-argument export.
    # A future ABI needs explicit admission here; do not assume ABI>=3106.
    return bool(_LIB__v87_v74_native is not None and _STATUS__v87_v74_native.get('abi')==3107
        and _STATUS__v87_v74_native.get('preview_snapshot_available',False)
        and _STATUS__v87_v74_native.get('preview_snapshot_signature')=='paired_area2_15args')


def preview_snapshot__v87_v74_native(raw,raw_out,bgr,bgr_out,times):
    if not preview_snapshot_available__v87_v74_native():return False
    from core import require_yuyv as require_yuyv
    require_yuyv(raw)
    for value,channels in ((raw_out,2),(bgr,3),(bgr_out,3)):
        if value.dtype!=np.uint8 or value.ndim!=3 or value.shape[2]!=channels or value.strides[-1]!=1 or value.strides[-2]!=channels:
            raise ValueError('Preview snapshot layout invalid')
    if (not raw_out.flags.c_contiguous or not bgr_out.flags.c_contiguous
            or not raw_out.flags.writeable or not bgr_out.flags.writeable
            or times.shape!=(2,) or times.dtype!=np.float64
            or not times.flags.c_contiguous or not times.flags.writeable):
        raise ValueError('Preview snapshot workspace invalid')
    code=_LIB__v87_v74_native.p11_preview_snapshot(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],raw_out.ctypes.data,raw_out.shape[1],raw_out.shape[0],
        bgr.ctypes.data,bgr.shape[1],bgr.shape[0],bgr.strides[0],bgr_out.ctypes.data,bgr_out.shape[1],bgr_out.shape[0],times.ctypes.data)
    if code:raise ValueError('Preview snapshot rejected '+str(code))
    return True

def completion_probe__v87_v74_native(pl_array,dma_array,before,kind,out):
    if _LIB__v87_v74_native is None:return None
    if out.dtype!=np.uint32 or out.shape!=(4,) or not out.flags.c_contiguous:raise ValueError('Completion probe scratch invalid')
    code=_LIB__v87_v74_native.p11_io_probe(pl_array.ctypes.data,dma_array.ctypes.data,int(before)&0xffffffff,int(kind),out.ctypes.data)
    if code<0:raise ValueError('Native completion probe rejected: '+str(code))
    return int(code),dict(pl_status=int(out[0]),pl_error=int(out[1]),tx=int(out[2]),rx=int(out[3]))


def copy_entry__v87_v74_native():
    """Admitted CPU memcpy only; no device mapping is supplied to the worker."""
    return _LIB__v87_v74_native.p11_copy_bgr if _LIB__v87_v74_native is not None else None


class OwnerCompletion__v87_v74_native:
    """Persistent mapping pointers, result scratch and function bindings."""
    def __init__(self,pl,dma):
        self.owner=threading.get_ident();self.arrays=(pl,dma)
        self.available=bool(_LIB__v87_v74_native) and _mmio_layout__v87_v74_native(pl,0xcc) and _mmio_layout__v87_v74_native(dma,0x5c)
        self.state=np.zeros(12,np.uint32);self.completed=None
        self.before=0;self.kind=1
        self.stats=dict(probe_calls=0,wait_calls=0,native_wait_s=0.,snapshots=0)
        if self.available:
            self.pointers=(int(pl.ctypes.data),int(dma.ctypes.data))
            self.output=int(self.state.ctypes.data)
            self.function=_LIB__v87_v74_native.p11_owner_complete;self.state_function=_LIB__v87_v74_native.p11_frame_state
    def begin(self,before,kind):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached completion owner')
        if kind not in (0,1):raise ValueError('Completion kind invalid')
        self.before=int(before)&0xffffffff;self.kind=kind;self.completed=None
    def poll(self,timeout=0.):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached completion owner')
        if not self.available:return None
        began=time.perf_counter()
        code=self.function(*self.pointers,self.before,self.kind,float(timeout),self.output)
        self.stats['native_wait_s']+=time.perf_counter()-began
        self.stats['wait_calls' if timeout else 'probe_calls']+=1
        if code<0:raise ValueError('Cached owner completion rejected: '+str(code))
        if code==0:self.completed=(self.before,self.kind)
        return int(code)
    def snapshot(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong cached snapshot owner')
        if not self.available:return None
        self.completed=None;code=self.state_function(*self.pointers,self.output)
        if code:raise ValueError('Cached owner snapshot rejected: '+str(code))
        self.stats['snapshots']+=1;return self.state
    def completed_state(self,before,kind=1):
        if threading.get_ident()!=self.owner:raise RuntimeError('Wrong completion-state owner')
        return self.state if self.completed==(int(before)&0xffffffff,kind) else None
    def error_state(self):
        return dict(pl_status=int(self.state[0]),pl_error=int(self.state[1]),
                    tx=int(self.state[2]),rx=int(self.state[3]))


# Raw YUYV dispatch, keeping the existing BGR helper only for setup previews.
_bgr_gray_area2__v87_v74_native=gray_area2__v87_v74_native
_bgr_fused_observation2__v87_v74_native=fused_observation2__v87_v74_native
_bgr_observe__v87_v74_native=ObservationWorkspace__v87_v74_native.observe
_bgr_copy_entry__v87_v74_native=copy_entry__v87_v74_native

def gray_area2__v87_v74_native(image,out):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_gray_area2__v87_v74_native(image,out)
    if _LIB__v87_v74_native is None:return False
    from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return False
    if out.shape!=(h//2,w//2) or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable:raise ValueError('Y output workspace')
    code=_LIB__v87_v74_native.p11_yuyv_gray2(image.ctypes.data,w,h,image.strides[0],color_mode(),out.ctypes.data)
    if code:raise ValueError('Y observer rejected '+str(code))
    return True

def fused_observation2__v87_v74_native(image,scratch,workspace,out=None,timing=None):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_fused_observation2__v87_v74_native(image,scratch,workspace,out,timing)
    if _LIB__v87_v74_native is None:return None
    from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (scratch.shape!=(h//2,w//2) or scratch.dtype!=np.uint8 or not scratch.flags.c_contiguous or not scratch.flags.writeable
        or workspace.dtype!=np.uint16 or workspace.size<3*(w//2) or not workspace.flags.c_contiguous or not workspace.flags.writeable):raise ValueError('Y Gaussian workspace')
    if out is None:out=np.empty_like(scratch)
    if timing is None:timing=np.empty(2,np.float64)
    if (out.shape!=scratch.shape or out.dtype!=np.uint8 or not out.flags.c_contiguous or not out.flags.writeable
        or np.shares_memory(out,scratch) or timing.dtype!=np.float64 or timing.shape!=(2,) or not timing.flags.c_contiguous):raise ValueError('Y output alias/layout')
    code=_LIB__v87_v74_native.p11_yuyv_observe2(image.ctypes.data,w,h,image.strides[0],color_mode(),scratch.ctypes.data,workspace.ctypes.data,out.ctypes.data,timing.ctypes.data)
    if code:raise ValueError('Y fused observer rejected '+str(code))
    return out,dict(resize_gray_s=float(timing[0]),blur_s=float(timing[1]),input_format='YUYV',ps_luminance='direct_Y_normalized')

def _y_observe__v87_v74_native(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius=5.):
    if image.ndim!=3 or image.shape[2]!=2:return _bgr_observe__v87_v74_native(self,image,scratch,rows,out,prediction,previous,anchor,drift,polarity,radius)
    if _LIB__v87_v74_native is None:return None
    from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
    require_yuyv(image);h,w=image.shape[:2]
    if h%2 or min(w,h)<4 or max(w,h)>1280:return None
    if (out.shape!=(h//2,w//2) or scratch.shape!=out.shape or out.dtype!=np.uint8 or scratch.dtype!=np.uint8
        or rows.dtype!=np.uint16 or rows.size<3*(w//2) or drift.dtype!=np.float32 or drift.shape!=(4,2)
        or any(not a.flags.c_contiguous or not a.flags.writeable for a in (scratch,rows,out,drift)) or np.shares_memory(out,scratch)):raise ValueError('Y edge workspace')
    self.predicted[:]=prediction;self.previous[:]=previous;self.anchor[:]=anchor;self.polarity[:]=polarity
    if self.light_results:
        from display import observe_yuyv_bound as observe_yuyv_bound
        code=observe_yuyv_bound(self,image,scratch,rows,out,drift,radius,color_mode(),_LIB__v87_v74_native)
    else:
        code=_LIB__v87_v74_native.p11_yuyv_observe_edges(image.ctypes.data,w,h,image.strides[0],color_mode(),scratch.ctypes.data,rows.ctypes.data,out.ctypes.data,
            self.predicted.ctypes.data,self.previous.ctypes.data,self.anchor.ctypes.data,drift.ctypes.data,self.polarity.ctypes.data,
            float(radius),self.result.ctypes.data,self.stats.ctypes.data,self.motion.ctypes.data,self.gate.ctypes.data,self.times.ctypes.data)
    if code and code>-200:raise ValueError('Y edge observer rejected '+str(code))
    return (self.decode() if code==0 else None),dict(edge_error=(code+200 if code else None),resize_gray_s=float(self.times[0]),blur_s=float(self.times[1]),
        edge_gate_motion_s=float(self.times[2]),native_transaction_s=float(self.times[3]),transaction_backend='cpp_Y_gaussian_edges_confidence_motion',input_format='YUYV')
ObservationWorkspace__v87_v74_native.observe=_y_observe__v87_v74_native

def copy_yuyv_native__v87_v74_native(source,destination):
    if _LIB__v87_v74_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(source);require_yuyv(destination)
    if source.shape!=destination.shape or not destination.flags.writeable or np.shares_memory(source,destination):raise ValueError('YUYV copy destination/alias')
    code=_LIB__v87_v74_native.p11_copy_yuyv(source.ctypes.data,destination.ctypes.data,source.shape[1],source.shape[0],source.strides[0],destination.strides[0])
    if code:raise ValueError('YUYV copy rejected '+str(code))
    return True

def copy_entry__v87_v74_native(bpp=3):
    return (_LIB__v87_v74_native.p11_copy_yuyv if bpp==2 else _bgr_copy_entry__v87_v74_native()) if _LIB__v87_v74_native is not None else None

def yuyv_model_bgr__v87_v74_native(image,mode):
    if _LIB__v87_v74_native is None:return None
    from core import require_yuyv as require_yuyv
    require_yuyv(image);h,w=image.shape[:2];out=np.empty((h,w,3),np.uint8)
    code=_LIB__v87_v74_native.p11_yuyv_bgr(image.ctypes.data,w,h,image.strides[0],int(mode),out.ctypes.data)
    if code:raise ValueError('Model CSC rejected '+str(code))
    return out

def yuyv_preview_into__v87_v74_native(image,mode,out,fast=False):
    if _LIB__v87_v74_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(image)
    if (out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=3 or not out.flags.c_contiguous
            or min(out.shape[:2])<1 or max(out.shape[:2])>640):raise ValueError('Preview workspace layout invalid')
    h,w=image.shape[:2];ho,wo=out.shape[:2]
    entry=_LIB__v87_v74_native.p11_yuyv_preview_nearest if fast else _LIB__v87_v74_native.p11_yuyv_preview
    code=entry(image.ctypes.data,w,h,image.strides[0],int(mode),out.ctypes.data,wo,ho)
    if code:raise ValueError('Preview resize/CSC rejected '+str(code))
    return True


def bgr_preview_into__v87_v74_native(image,out,xmap,ymap):
    """Nearest preview only. All buffers belong to the ordinary-RAM UI worker."""
    if _LIB__v87_v74_native is None:return False
    if (image.dtype!=np.uint8 or image.ndim!=3 or image.shape[2]!=3
            or image.strides[2]!=1 or image.strides[1]!=3
            or out.dtype!=np.uint8 or out.ndim!=3 or out.shape[2]!=3 or not out.flags.c_contiguous):
        raise ValueError('BGR preview workspace layout invalid')
    h,w=image.shape[:2];ho,wo=out.shape[:2]
    if any(a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (xmap,ymap)):
        raise ValueError('BGR preview index map invalid')
    if xmap.size!=wo or ymap.size!=ho:raise ValueError('BGR preview index map size mismatch')
    code=_LIB__v87_v74_native.p11_bgr_preview_nearest(image.ctypes.data,w,h,image.strides[0],
        out.ctypes.data,wo,ho,xmap.ctypes.data,ymap.ctypes.data)
    if code:raise ValueError('BGR preview resize rejected '+str(code))
    return True


def preview_pair_copy__v87_v74_native(raw,raw_out,bgr,bgr_out,times):
    """One GIL-released row-copy call. Caller pins camera/output until it returns."""
    if _LIB__v87_v74_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(raw)
    if (raw_out.dtype!=np.uint8 or raw.shape!=raw_out.shape or not raw_out.flags.c_contiguous
        or bgr.dtype!=np.uint8 or bgr.ndim!=3 or bgr.shape[2]!=3 or bgr.strides[1:]!=(3,1)
        or bgr_out.dtype!=np.uint8 or bgr.shape!=bgr_out.shape or not bgr_out.flags.c_contiguous
        or times.dtype!=np.float64 or times.shape!=(2,) or not times.flags.c_contiguous):
        raise ValueError('Paired preview copy workspace mismatch')
    rh,rw=raw.shape[:2];bh,bw=bgr.shape[:2]
    code=_LIB__v87_v74_native.p11_preview_pair_copy(raw.ctypes.data,raw_out.ctypes.data,rw,rh,raw.strides[0],raw_out.strides[0],
        bgr.ctypes.data,bgr_out.ctypes.data,bw,bh,bgr.strides[0],bgr_out.strides[0],times.ctypes.data)
    if code:raise ValueError('Paired preview copy rejected '+str(code))
    return True

class CompactPreview__v87_v74_native:
    """Pinned packet/workspace arguments; used only by the single UI worker."""
    def __init__(self,raw,output,work):
        self.available=_LIB__v87_v74_native is not None and work.compact
        self.times=np.zeros(3,np.float64);self.refs=(raw,output,work)
        if not self.available:return
        from core import require_yuyv as require_yuyv
        require_yuyv(raw)
        arrays=(output,work.left,work.canvas)
        if work.right is not None:arrays=arrays+(work.right,)
        if any(a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=3 or not a.flags.c_contiguous for a in arrays):
            raise ValueError('Compact preview workspace must be contiguous BGR')
        hi,wi=raw.shape[:2];bh,bw=output.shape[:2];height,lw=work.left.shape[:2]
        rw=work.canvas.shape[1]-lw
        if work.canvas.shape!=(height,lw+rw,3):raise ValueError('Compact preview canvas shape mismatch')
        if work.right is None:
            if output.shape!=(height,rw,3):raise ValueError('Compact preview native right shape mismatch')
            xs=ys=right=0
        else:
            if work.right.shape!=(height,rw,3):raise ValueError('Compact preview right shape mismatch')
            if any(a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (work.xmap,work.ymap)):
                raise ValueError('Compact preview index map layout mismatch')
            if work.xmap.size!=rw or work.ymap.size!=height:raise ValueError('Compact preview map sizes mismatch')
            xs,ys,right=work.xmap.ctypes.data,work.ymap.ctypes.data,work.right.ctypes.data
        self.entry=_LIB__v87_v74_native.p11_compact_preview
        self.args=(raw.ctypes.data,wi,hi,raw.strides[0],0,output.ctypes.data,bw,bh,output.strides[0],
            work.left.ctypes.data,lw,right,rw,height,xs,ys,work.canvas.ctypes.data,self.times.ctypes.data)
    def run(self,mode):
        if not self.available:return False
        args=self.args
        code=self.entry(*args[:4],int(mode),*args[5:])
        if code:raise ValueError('Compact preview transaction rejected '+str(code))
        return True


_REFINE64__v87_v74_native=threading.local()
def refine_original_y64__v87_v74_native(gray,quad,half_window,packed_mode=None):
    """P1 64x65 original-Y profiles + robust TLS in one native transaction."""
    if _LIB__v87_v74_native is None or not _LIB__v87_v74_native.p11_lk_available():return None
    from geometry import order_corners as order_corners
    import cv2
    start=time.perf_counter();cpu=time.thread_time()
    if packed_mode is None:
        if not isinstance(gray,np.ndarray) or gray.dtype!=np.uint8 or gray.ndim!=2:
            raise ValueError('native64 requires original uint8 Y plane')
        g=np.ascontiguousarray(gray)
    else:
        from core import require_yuyv as require_yuyv
        g=require_yuyv(gray)
        if packed_mode not in (0,1,2,3):raise ValueError('native64 YUYV color range invalid')
    q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('native64 requires ordered convex current corners')
    if not np.isfinite(half_window) or not 3<=half_window<=48:raise ValueError('native64 half_window must be3..48')
    if not hasattr(_REFINE64__v87_v74_native,'buffers'):
        _REFINE64__v87_v74_native.buffers=(np.empty((4,2),np.float64),np.empty(27,np.float64))
    out,stats=_REFINE64__v87_v74_native.buffers
    args=(g.ctypes.data,g.shape[1],g.shape[0],g.strides[0])
    tail=(q.ctypes.data,float(half_window),out.ctypes.data,stats.ctypes.data)
    code=(_LIB__v87_v74_native.p11_refine64(*args,*tail) if packed_mode is None else
          _LIB__v87_v74_native.p11_yuyv_refine64(*args,int(packed_mode),*tail))
    if code==-9:return None
    if code:raise ValueError('native original-Y64 rejected input: '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(stats).all():
        raise ValueError('native original-Y64 returned invalid geometry')
    count=int(stats[24]);edges=[]
    for i in range(4):
        n=int(stats[i*6]);info=dict(edge=i,profiles=64,supported=n,accepted=bool(stats[i*6+4]),profile_contrast=float(stats[i*6+5]))
        if n>=20:info.update(tls_rms=float(stats[i*6+1]),retained=int(stats[i*6+2]),coverage=float(stats[i*6+3]))
        edges.append(info)
    try:
        candidate=out.astype(np.float32)
        if not cv2.isContourConvex(candidate):raise ValueError('native64 refined convexity invalid')
        area_ratio=abs(cv2.contourArea(candidate))/abs(cv2.contourArea(q.astype(np.float32)))
        if not .85<=area_ratio<=1.15 or np.max(np.linalg.norm(candidate-q,axis=1))>3*half_window:
            raise ValueError('native64 refined area/order/displacement invalid')
    except (ValueError,cv2.error):
        candidate=q.astype(np.float32);count=0
    return candidate,dict(method='p1_pyramid_subpixel_profiles_tls',backend='cpp_packed_Y_64x65_Q5' if packed_mode is not None else 'cpp_original_Y_64x65',
        state='refined' if count else 'coarse_retained',refined_corners=count,edges=edges,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(candidate-q,axis=1).tolist(),
        refinement_s=time.perf_counter()-start,refinement_thread_cpu_s=time.thread_time()-cpu,
        native_wall_s=float(stats[25]),native_thread_cpu_s=float(stats[26]),
        workspace_reused=True,interpolation='opencv_uint8_linear_replicate',
        tls_solver='analytic_2x2_principal_axis',original_profile_gates_preserved=True)


def refine_original_yuyv64__v87_v74_native(image,quad,half_window):
    from core import color_mode as color_mode
    return refine_original_y64__v87_v74_native(image,quad,half_window,packed_mode=color_mode())

_COHERENT__v87_v74_native=__import__('threading').local()

def coherent_profiles__v87_v74_native(bands,half_window,fraction_limits,minimum_contrast,boundary_prior=None,line_lock_radius=None):
    """One ctypes transaction for all four current Y/color exterior bands; no device access."""
    if _LIB__v87_v74_native is None:return None
    data=np.ascontiguousarray(bands,np.float32)
    if data.ndim!=4 or data.shape[0]!=4 or data.shape[1] not in (24,64) or data.shape[2]!=65 or data.shape[3] not in (1,3):
        raise ValueError('Coherent exterior band layout invalid')
    shape=(4,data.shape[1],3)
    if not hasattr(_COHERENT__v87_v74_native,'out') or _COHERENT__v87_v74_native.out.shape!=shape:
        _COHERENT__v87_v74_native.out=np.empty(shape,np.float32);_COHERENT__v87_v74_native.times=np.empty(2,np.float64)
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Current consensus side prior invalid')
    if line_lock_radius is not None:
        if not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window:raise ValueError('Current consensus peak lock invalid')
        code=_LIB__v87_v74_native.p11_locked_coherent_profiles(data.ctypes.data,data.shape[1],data.shape[3],float(half_window),
            float(fraction_limits[0]),float(fraction_limits[1]),float(minimum_contrast),float(line_lock_radius),
            0 if prior is None else prior.ctypes.data,_COHERENT__v87_v74_native.out.ctypes.data,_COHERENT__v87_v74_native.times.ctypes.data)
    else:
        code=_LIB__v87_v74_native.p11_coherent_profiles(data.ctypes.data,data.shape[1],data.shape[3],float(half_window),
            float(fraction_limits[0]),float(fraction_limits[1]),float(minimum_contrast),_COHERENT__v87_v74_native.out.ctypes.data,_COHERENT__v87_v74_native.times.ctypes.data)
    if code:raise ValueError('Native exterior consensus rejected bands: '+str(code))
    return _COHERENT__v87_v74_native.out,dict(backend='cpp_four_edge_three_peak_consensus',
        native_wall_s=float(_COHERENT__v87_v74_native.times[0]),native_thread_cpu_s=float(_COHERENT__v87_v74_native.times[1]),workspace_reused=True)

def preview_canvas_into__v87_v74_native(raw,output,work,mode,times,interpolation='nearest'):
    """Borrow source arrays ONLY for this call; destination is owned UI RAM.

    V48 UI worker calls this with owned ordinary-RAM snapshots. Direct borrowed
    use also remains valid only within the call; no source pointer is retained.
    """
    if _LIB__v87_v74_native is None:return False
    from core import require_yuyv as require_yuyv
    require_yuyv(raw)
    if (not work.compact or work.right is None or output.dtype!=np.uint8 or output.ndim!=3
        or output.shape[2]!=3 or output.strides[1:]!=(3,1)):
        raise ValueError('Preview borrowed source layout')
    if any(a.dtype!=np.uint8 or not a.flags.c_contiguous or not a.flags.writeable
           for a in (work.left,work.right,work.canvas)):
        raise ValueError('Preview packet workspace')
    if times.shape!=(3,) or times.dtype!=np.float64 or not times.flags.c_contiguous:raise ValueError('Preview timing workspace')
    hi,wi=raw.shape[:2];bh,bw=output.shape[:2];height,lw=work.left.shape[:2];rw=work.right.shape[1]
    if output.strides[0]<3*bw or not 2<=min(hi,wi,bh,bw,height,lw,rw) or max(hi,wi,bh,bw)>1280 or not 0<=int(mode)<=3:
        raise ValueError('Preview dimensions/row stride/mode invalid')
    if not times.flags.writeable:raise ValueError('Preview timing destination is read-only')
    if work.canvas.shape!=(height,lw+rw,3) or work.right.shape[0]!=height:raise ValueError('Preview canvas shape')
    if interpolation=='linear':
        axes=getattr(work,'linear_maps',None)
        if axes is None or len(axes)!=5:raise ValueError('Missing cached linear preview maps')
        sizes=(lw,height,lw,rw,height)
        for axis,size in zip(axes,sizes):
            if (axis.dtype!=np.int32 or axis.shape!=(size,3) or not axis.flags.c_contiguous
                or axis.flags.writeable):raise ValueError('Linear preview map layout')
        if work.linear_layout!=(hi,wi,bh,bw,height,lw,rw):raise ValueError('Linear preview source layout changed')
        code=_LIB__v87_v74_native.p11_preview_canvas_linear(raw.ctypes.data,wi,hi,raw.strides[0],int(mode),
            output.ctypes.data,bw,bh,output.strides[0],work.canvas.ctypes.data,lw,rw,height,
            *(axis.ctypes.data for axis in axes),times.ctypes.data)
        if code:raise ValueError('Bilinear preview canvas transaction rejected '+str(code))
        return True
    if interpolation!='nearest':raise ValueError('Unknown preview interpolation')
    if any(a is None or a.dtype!=np.int32 or not a.flags.c_contiguous or a.ndim!=1 for a in (work.xmap,work.ymap)):
        raise ValueError('Preview map workspace layout')
    if work.xmap.size!=rw or work.ymap.size!=height or np.any(work.xmap<0) or np.any(work.xmap>=bw) or np.any(work.ymap<0) or np.any(work.ymap>=bh):
        raise ValueError('Preview map bounds')
    if not times.flags.writeable:raise ValueError('Preview timing destination is read-only')
    if work.canvas.shape!=(height,lw+rw,3) or work.right.shape[0]!=height:raise ValueError('Preview canvas shape')
    layout=(hi,wi,height,lw)
    if getattr(work,'left_layout',None)!=layout:
        work.left_xmap=(np.arange(lw,dtype=np.int32)*wi//lw)
        work.left_ymap=(np.arange(height,dtype=np.int32)*hi//height)
        work.left_xmap.flags.writeable=False;work.left_ymap.flags.writeable=False;work.left_layout=layout
    code=_LIB__v87_v74_native.p11_preview_canvas_maps(raw.ctypes.data,wi,hi,raw.strides[0],int(mode),
        output.ctypes.data,bw,bh,output.strides[0],work.canvas.ctypes.data,lw,rw,height,
        work.left_xmap.ctypes.data,work.left_ymap.ctypes.data,work.xmap.ctypes.data,work.ymap.ctypes.data,
        times.ctypes.data)
    if code:raise ValueError('Preview canvas transaction rejected '+str(code))
    return True

def packed_vector_profiles__v87_v74_native(image,x,y):
    """Borrow packed source only until return; sample bounded Y/U/V bands."""
    if _LIB__v87_v74_native is None:return None
    from core import require_yuyv as require_yuyv
    require_yuyv(image)
    if max(image.shape[:2])>1280:return None
    mx=np.ascontiguousarray(x,np.float32);my=np.ascontiguousarray(y,np.float32)
    if mx.shape!=my.shape or not 1<=mx.size<=4*64*65:
        raise ValueError('Packed exterior profile coordinate layout invalid')
    output=np.empty((*mx.shape,3),np.float32);h,w=image.shape[:2]
    code=_LIB__v87_v74_native.p11_yuyv_profiles(image.ctypes.data,w,h,image.strides[0],mx.ctypes.data,
        my.ctypes.data,mx.size,output.ctypes.data)
    if code:raise ValueError('Packed exterior sampler rejected '+str(code))
    return output


_EXTERIOR__v87_v74_native=threading.local()
def fused_yuyv_exterior__v87_v74_native(image,quad,half_window,profiles=64,min_support=.60,max_rms=1.5,
                        minimum_contrast=12.,fraction_limits=(.10,.90),deadline=None,boundary_prior=None,line_lock_radius=None):
    """Current borrowed YUYV bands, consensus, robust TLS and corners in one call.

    CPU-only thread-local scratch. Output arrays are copied, no source pointer
    escapes the transaction. Expired work returns rejected evidence, not fallback.
    """
    if _LIB__v87_v74_native is None or image.ndim!=3 or image.shape[2]!=2 or max(image.shape[:2])>1280:return None
    from core import require_yuyv as require_yuyv
    from geometry import array_key as array_key
    import cv2
    raw=require_yuyv(image);q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all() or not cv2.isContourConvex(q.astype(np.float32)):
        raise ValueError('Fused current exterior requires cyclic convex corners')
    if not hasattr(_EXTERIOR__v87_v74_native,'buffers'):
        _EXTERIOR__v87_v74_native.buffers=(np.empty((4,2),np.float64),np.empty(80,np.float64))
    out,s=_EXTERIOR__v87_v74_native.buffers;begin=time.perf_counter();cpu=time.thread_time()
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Boundary side prior invalid')
    if line_lock_radius is not None and (not np.isfinite(line_lock_radius) or not 0<float(line_lock_radius)<=half_window):raise ValueError('Fused current physical lock invalid')
    function=_LIB__v87_v74_native.p11_yuyv_exterior if line_lock_radius is None else _LIB__v87_v74_native.p11_locked_yuyv_exterior
    args=() if line_lock_radius is None else (float(line_lock_radius),)
    code=function(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],q.ctypes.data,
        float(half_window),int(profiles),float(fraction_limits[0]),float(fraction_limits[1]),
        float(minimum_contrast),float(min_support),float(max_rms),0. if deadline is None else float(deadline),
        0 if prior is None else prior.ctypes.data,out.ctypes.data,s.ctypes.data,*args)
    if code not in (0,1):raise ValueError('Fused current YUV exterior rejected input: '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(s).all():raise ValueError('Invalid native exterior result')
    return _decode_yuyv_exterior__v87_v74_native(raw,q,out,s,half_window,profiles,fraction_limits,boundary_prior,line_lock_radius,
        time.perf_counter()-begin,time.thread_time()-cpu)


def _decode_yuyv_exterior__v87_v74_native(raw,q,out,s,half_window,profiles,fraction_limits,boundary_prior,line_lock_radius,wall_s,cpu_s):
    from geometry import array_key as array_key
    edges=[];support=[];rms=[];colors=[]
    for i in range(4):
        z=s[i*13:(i+1)*13];accepted=bool(z[4])
        edges.append(dict(edge=i,profiles=profiles,supported=int(z[0]),retained=int(z[1]),
            coverage=float(z[2]),tls_rms=float(z[3]),accepted=accepted,polarity=0,Y_polarity=int(z[12]),
            contrast_backend='unclipped_YUV_vector_gradient'))
        support.append(float(z[1])/profiles if accepted else 0.);rms.append(float(z[3]))
        colors.append(z[6:12].tolist())
    evidence=dict(method='coherent_multicolor_gradient_TLS',state='refined' if s[53] else 'rejected',
        valid=bool(s[53]),refined_corners=int(s[52]),supported_edges=sum(e['accepted'] for e in edges),
        edges=edges,edge_support=support,edge_rms=rms,edge_polarity=[0]*4,
        half_window_pixels=float(half_window),corner_displacements=np.linalg.norm(out-q,axis=1).tolist(),
        refinement_s=float(wall_s),refinement_thread_cpu_s=float(cpu_s),
        backend='cpp_fused_current_YUV_exterior',profiles_per_edge=int(profiles),fraction_limits=list(fraction_limits),
        vector_sample_backend='cpp_direct_YUV_bands_no_full_plane_pack',consensus_backend='cpp_four_edge_three_peak_consensus',
        native_wall_s=float(s[54]),native_thread_cpu_s=float(s[55]),sampling_s=float(s[56]),sampling_thread_cpu_s=float(s[57]),
        consensus_native_wall_s=float(s[58]),consensus_native_thread_cpu_s=float(s[59]),fit_s=float(s[60]),fit_thread_cpu_s=float(s[61]),
        deadline_hit=bool(s[62]),workspace_reused=True,same_frame_color_bands_only=True,
        color_vector_proof=True,brightness_polarity_required=False,same_frame_source=True,
        current_source_key=array_key(raw),source_proof_kind='raw_YUV_profiles',border_colors=colors,
        gradient_consensus_required=True,area_ratio=float(s[63]),corner_order_preserved=True,
        boundary_prior_used=boundary_prior is not None,border_color_sampling='fitted_line_sides_3px',
        physical_peak_lock=line_lock_radius is not None,peak_lock_radius_source=line_lock_radius,
        signed_peak_lock=bool(line_lock_radius is not None and boundary_prior is not None))
    return out.astype(np.float32),evidence


def fused_locked_pair__v87_v74_native(image,quad,half_window,primary_lock,scale_min,deadline=None,boundary_prior=None,cpu_budget_s=.12):
    """Two independent current-color sample layouts; all geometric gates remain outside."""
    if _LIB__v87_v74_native is None or image.ndim!=3 or image.shape[2]!=2:return None
    from core import require_yuyv as require_yuyv
    raw=require_yuyv(image);q=np.ascontiguousarray(quad,np.float64)
    if q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Native pair quad layout invalid')
    if not hasattr(_EXTERIOR__v87_v74_native,'pair'):
        _EXTERIOR__v87_v74_native.pair=(np.empty((2,4,2),np.float64),np.empty((2,80),np.float64),np.empty(4,np.float64))
    out,stats,timing=_EXTERIOR__v87_v74_native.pair
    prior=None if boundary_prior is None else np.ascontiguousarray(np.asarray(boundary_prior)*[255.,224.,224.],np.float64)
    if prior is not None and (prior.shape!=(4,3) or not np.isfinite(prior).all()):raise ValueError('Native pair prior invalid')
    began=time.perf_counter();cpu=time.thread_time()
    code=_LIB__v87_v74_native.p11_v67_locked_pair(raw.ctypes.data,raw.shape[1],raw.shape[0],raw.strides[0],q.ctypes.data,
        float(half_window),8.,.60,float(scale_min),0. if deadline is None else float(deadline),
        0 if prior is None else prior.ctypes.data,float(primary_lock),float(scale_min),float(cpu_budget_s),
        out[0].ctypes.data,stats[0].ctypes.data,out[1].ctypes.data,stats[1].ctypes.data,timing.ctypes.data)
    if code not in (0,1,2,3):raise ValueError('Native pair input rejected '+str(code))
    if not np.isfinite(out).all() or not np.isfinite(stats).all():raise ValueError('Native pair output invalid')
    first=_decode_yuyv_exterior__v87_v74_native(raw,q,out[0],stats[0],half_window,64,(.10,.90),boundary_prior,primary_lock,stats[0,54],stats[0,55])
    secondary_lock=min(.70*half_window,float(np.clip(1.25+.75*max(stats[0,i*13+3] for i in range(4)),1.25,2.)))
    # The core derives the secondary signed prior from the current primary.
    second=_decode_yuyv_exterior__v87_v74_native(raw,q,out[1],stats[1],half_window,24,(.12,.88),True if stats[0,53] else None,secondary_lock,stats[1,54],stats[1,55])
    detail=dict(backend='cpp_current_locked64_independent24',code=int(code),complete=code==0,
        pair_wall_s=time.perf_counter()-began,pair_thread_cpu_s=time.thread_time()-cpu,
        native_pair_wall_s=float(timing[0]),native_pair_thread_cpu_s=float(timing[1]),
        independent_grids=[[64,.10,.90],[24,.12,.88]],same_locked_line=True,geometric_proof_granted=False)
    return first,second,detail


# ======================================================================
# ===== [24/28] v90_lk =====
# ======================================================================


"""Original complete checked LK transaction with persistent FFI bindings.

The C++ pyramid, forward/backward, filtering and RANSAC implementation is exact
V74. Validation, returned ownership and all acceptance thresholds are retained.
"""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class LKTransaction(LKCache__v87_v74_native):
    def __init__(self):
        super().__init__()
        self._addresses={name:int(getattr(self,name).ctypes.data) for name in (
            'anchor_quad','previous_quad','quad','retained','filter_stats','flow_times','motion_info')}
        self._checked_motion=self.lib.p11_lk_checked_motion if self.pointer else None

    def checked(self,gray,points,initial,anchor,previous,generation,levels=3,iterations=20):
        if not self.pointer:return None
        g=np.ascontiguousarray(gray,np.uint8);p=np.ascontiguousarray(points,np.float32).reshape(-1,1,2)
        guess=None if initial is None else np.ascontiguousarray(initial,np.float32).reshape(p.shape)
        if not 4<=len(p)<=100 or (guess is not None and not np.isfinite(guess).all()):raise ValueError('LK prediction/features invalid')
        if isinstance(generation,bool) or not isinstance(generation,(int,np.integer)) or not 0<=int(generation)<0xffffffff:raise ValueError('LK frame generation invalid')
        self.anchor_quad[:]=anchor;self.previous_quad[:]=previous
        self.filter_stats.fill(0.);self.flow_times.fill(0.)
        began=time.perf_counter();cpu=time.thread_time()
        code=self._checked_motion(self.pointer,g.ctypes.data,g.shape[1],g.shape[0],p.ctypes.data,len(p),
            None if guess is None else guess.ctypes.data,int(levels),int(iterations),int(generation),self._addresses['anchor_quad'],
            self._addresses['previous_quad'],self._addresses['quad'],self._addresses['retained'],self._addresses['filter_stats'],self._addresses['flow_times'],self._addresses['motion_info'])
        self.last_checked_timing=dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),native_checked_wall_s=time.perf_counter()-began,
            native_checked_thread_cpu_s=time.thread_time()-cpu,native_checked_code=int(code),
            transaction_backend='cpp_bidirectional_lk_filter',workspace_bindings_reused=True,complete_FB=code==0,
            motion_model={0:'unavailable',1:'similarity_candidate',2:'projective_candidate'}.get(int(self.motion_info[0]),'invalid'),
            motion_good_features=int(self.motion_info[1]),motion_inliers=int(self.motion_info[2]),
            motion_reprojection_rms=float(self.motion_info[3]),current_four_edges_required=True)
        if code<=-100:raise ValueError('native LK rejected frame: '+str(code+100))
        if code:raise ValueError('native LK consistency rejected: '+str(code))
        n=int(self.filter_stats[4])
        detail=dict(lk_backend='cpp_cached_pyramids_checked',features=len(p),good_features=int(self.filter_stats[1]),filter_backend='cpp_bidirectional_lk_filter',
            inliers=n,inlier_fraction=float(self.filter_stats[2]),fb_median=float(self.filter_stats[3]),
            motion_model=self.last_checked_timing['motion_model'],motion_reprojection_rms=float(self.motion_info[3]),
            current_four_edges_required=True)
        return self.quad.copy(),self.retained[:n].copy(),detail,dict(forward_backward_flow_s=float(self.flow_times[0]),
            fb_filter_ransac_s=float(self.flow_times[1]),transaction_backend='cpp_bidirectional_lk_filter')


# ======================================================================
# ===== [25/28] v91_policy =====
# ======================================================================


"""Optional plan-probe backoff only; never suppress a current hardware proof."""
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


class MergeProbeBackoff:
    def __init__(self):
        self.failures=0;self.next_at=0.;self.reference=None;self.topology=None;self.delay=1.;self.deferred=0

    def ready(self,now,quad,boxes,stable):
        if not boxes or len(boxes)<=1:return False
        topology=tuple(tuple(b) for b in boxes);q=np.asarray(quad,np.float32)
        moved=self.reference is not None and float(np.max(np.linalg.norm(q-self.reference,axis=1)))>4.
        if topology!=self.topology or moved:
            # A changing target must not reset a failed probe into a new
            # immediate probe on every small-motion frame. Re-evaluate after
            # one second of this geometry; the first topology may probe now.
            self.next_at=now+1. if self.reference is not None else 0.
            self.failures=0;self.delay=1.;self.topology=topology;self.reference=q.copy()
        if not stable:return False
        if now<self.next_at:self.deferred+=1;return False
        return True

    def observe(self,now,quad,boxes,requested,detail):
        if not requested:return
        attempted=bool(detail.get('merge_probe_attempts'));accepted=bool(detail.get('merge_probe_accepted'))
        if attempted:
            self.failures=0 if accepted else min(3,self.failures+1)
            self.delay=1. if accepted else float(min(8,2**self.failures))
        else:self.delay=8.  # No valid adjacent pair: do not enter legacy every frame.
        self.next_at=now+self.delay;self.reference=np.asarray(quad,np.float32).copy()
        self.topology=tuple(tuple(b) for b in boxes)

    def summary(self):
        return dict(merge_probe_failure_streak=self.failures,merge_probe_retry_s=self.delay,
            merge_probe_deferred_frames=self.deferred,merge_probe_backoff_only=True,
            current_packet_and_rowproof_skipped=False)


# ======================================================================
# ===== [26/28] v107_policy =====
# ======================================================================


"""Cheap, completed-output evidence for automatic-to-AI rescue.

Caller timestamps use the same monotonic clock.  The owner must report only
successful output completion and must gate callbacks by its run/generation;
metadata alone cannot identify an old callback completed after a reset.
"""

from core import RELEASE_ID as RELEASE_ID

_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_SOURCE_AGE_S = .5


class OutputMonitor:
    """One automatic epoch, with constant-time output observation.

    CURRENT, unfrozen output with a fresh nonnegative camera sequence counts.
    Sequence numbers must increase within an epoch, as on the live camera;
    duplicate/backward sequences and out-of-order completion times are ignored.
    A provided positive capture timestamp also needs age in [0, .5] seconds.

    Until the first accepted output, only the startup deadline applies.  After
    it, allow a complete window before testing the open-left rolling interval
    (now-window_s, now].  tick returns a reason once, then latches until reset.
    capture_ok=False defers the trigger without restarting either deadline.
    suspend disables this epoch, including late observations.  A new epoch is
    explicitly created by reset; its camera sequence can restart from zero.
    """

    def __init__(self, start, startup_s=3., window_s=1., minimum=4):
        start = self._timestamp(start)
        startup_s = self._timestamp(startup_s)
        window_s = self._timestamp(window_s)
        if startup_s < 0. or window_s <= 0.:
            raise ValueError('output monitor needs startup_s>=0 and window_s>0')
        if isinstance(minimum, bool):
            raise ValueError('minimum must be a positive integer')
        try:
            minimum = operator.index(minimum)
        except TypeError:
            raise ValueError('minimum must be a positive integer') from None
        if minimum < 1:
            raise ValueError('minimum must be a positive integer')
        self.startup_s = startup_s
        self.window_s = window_s
        self.minimum = minimum
        self._lock = Lock()
        self.reset(start)

    @staticmethod
    def _timestamp(value):
        stamp = float(value)
        if not math.isfinite(stamp):
            raise ValueError('output monitor requires finite monotonic timestamps')
        return stamp

    def reset(self, now):
        now = self._timestamp(now)
        with self._lock:
            self.start = now
            self.first_valid = None
            self.last_valid = None
            self._sequence = -1
            self._times = deque()
            self._active = True
            self._triggered = False

    def suspend(self):
        with self._lock:
            self._active = False

    def _prune(self, now):
        cutoff = now - self.window_s
        while self._times and self._times[0] <= cutoff:
            self._times.popleft()

    def observe(self, row, completed_at):
        """Record one completed output; return whether it added valid evidence."""
        if row.get('state') != 'CURRENT' or row.get('frozen_output', False):
            return False
        try:
            completed_at = self._timestamp(completed_at)
            raw_sequence = row.get('camera_sequence', -1)
            if isinstance(raw_sequence, bool):
                return False
            sequence = operator.index(raw_sequence)
            ready = row.get('capture_ready_at', 0.)
            ready = 0. if ready is None else self._timestamp(ready)
        except (TypeError, ValueError, OverflowError):
            return False
        if sequence < 0 or (ready > 0. and not 0. <= completed_at-ready <= MAX_SOURCE_AGE_S):
            return False
        with self._lock:
            if (not self._active or self._triggered or completed_at < self.start
                    or sequence <= self._sequence
                    or (self.last_valid is not None and completed_at < self.last_valid)):
                return False
            self._sequence = sequence
            self._prune(completed_at)
            self._times.append(completed_at)
            if self.first_valid is None:
                self.first_valid = completed_at
            self.last_valid = completed_at
            return True

    def tick(self, now, capture_ok=True):
        """Return startup_no_output / low_fps at most once in this epoch."""
        now = self._timestamp(now)
        with self._lock:
            if (not self._active or self._triggered or not capture_ok
                    or now < self.start
                    or (self.last_valid is not None and now < self.last_valid)):
                return None
            if self.first_valid is None:
                reason = 'startup_no_output' if now-self.start >= self.startup_s else None
            elif now-self.first_valid < self.window_s:
                reason = None
            else:
                self._prune(now)
                reason = 'low_fps' if len(self._times) < self.minimum else None
            if reason is not None:
                self._triggered = True
            return reason

    def fps(self, now):
        """Completed unique current outputs per configured rolling second."""
        now = self._timestamp(now)
        with self._lock:
            # Usually now >= last_valid. Keep a backward read harmless rather
            # than dropping evidence needed by the next monotonic read.
            if self.last_valid is None or now >= self.last_valid:
                self._prune(now)
                return len(self._times) / self.window_s
            cutoff = now - self.window_s
            return sum(cutoff < stamp <= now for stamp in self._times) / self.window_s


# ======================================================================
# ===== [27/28] v91_native =====
# ======================================================================


"""Small CPU addon: unchanged native kernels, bound current-frame transactions."""
from core import RELEASE_ID as RELEASE_ID
from core import checkpoint as checkpoint
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB__v91_native=None;_ERROR__v91_native=None;_LOCK__v91_native=threading.RLock()


def prepare_transactions(cancel=None,required=False):
    global _LIB__v91_native,_ERROR__v91_native
    with _LOCK__v91_native:
        if _LIB__v91_native is not None:return _LIB__v91_native
        if _ERROR__v91_native is not None:
            if required:raise RuntimeError(_ERROR__v91_native)
            return None
        try:
            check_cancel(cancel)
            if platform.system()!='Linux':raise RuntimeError('V91 CPU addon requires PYNQ Linux')
            root=Path(__file__).resolve().parent;source=root/'v91_transaction.cpp'
            flags=['-O3','-ffp-contract=off','-std=c++11','-fPIC','-shared','-pthread']
            if platform.machine()=='armv7l':flags.append('-mfpu=neon')
            digest=hashlib.sha256(source.read_bytes()+platform.machine().encode()+' '.join(flags).encode()).hexdigest()[:20]
            target=root/('v91_transaction_'+digest+'_'+platform.machine()+'.so')
            restore(target,source,'transaction',flags,cancel)
            if not target.is_file():
                compiler=shutil.which('g++') or shutil.which('c++')
                if not compiler:raise RuntimeError('No compiler for small V91 CPU addon')
                temporary=target.with_suffix('.building.so')
                try:
                    result=setup_command([compiler]+flags+[str(source),'-o',str(temporary)],90,cancel,'V91_TRANSACTION_BUILD')
                    if result.returncode:raise RuntimeError(result.stderr[-2000:])
                    check_cancel(cancel);temporary.replace(target)
                finally:
                    if temporary.exists():temporary.unlink()
            lib=ctypes.CDLL(str(target));vp=ctypes.c_void_p;ci=ctypes.c_int
            lib.p11_v91_abi.argtypes=[];lib.p11_v91_abi.restype=ci
            if lib.p11_v91_abi()!=9101:raise ValueError('V91 CPU transaction ABI mismatch')
            lib.p11_v91_postlk.argtypes=[vp,vp,vp,ci,ci,ci,vp,ci,ci,ci,ci,vp,ctypes.c_double,vp,vp,vp,vp,vp,vp,vp]
            lib.p11_v91_postlk.restype=ci
            lib.p11_v91_pack_create.argtypes=[vp];lib.p11_v91_pack_create.restype=vp
            lib.p11_v91_pack_destroy.argtypes=[vp];lib.p11_v91_pack_destroy.restype=None
            lib.p11_v91_pack_batch.argtypes=[vp,vp,ci,ci,ci,ci,vp,ci,vp,ctypes.c_size_t,vp]
            lib.p11_v91_pack_batch.restype=ci
            _LIB__v91_native=lib;remember(target,source,'transaction',flags)
            checkpoint('V91_TRANSACTION_READY',abi=9101,path=str(target),hardware_access=False,
                original_kernels_unchanged=True,opencv_headers_required=False)
            return lib
        except NativeSetupCancelled:raise
        except (OSError,RuntimeError,ValueError,AttributeError,subprocess.SubprocessError) as exc:
            _ERROR__v91_native=type(exc).__name__+': '+str(exc)
            checkpoint('V91_TRANSACTION_UNAVAILABLE',exception=_ERROR__v91_native,fallback='unchanged V90 kernels and owner path',hardware_access=False)
            if required:raise
            return None


def _address(function):return int(ctypes.cast(function,ctypes.c_void_p).value)


def _key(array):return (id(array),int(array.ctypes.data),tuple(array.shape),tuple(array.strides),array.dtype.str)


class PostLKWorkspace:
    def __init__(self):
        self.lib=prepare_transactions();self.pending=None;self.detail={}
        self.kernels=_LIB__v87_v74_native
        self.available=bool(self.lib is not None and _LIB__v87_v74_native is not None and _LIB__v87_v74_native.p11_lk_available())
        self.proposed=np.empty((4,2),np.float64);self.scale=np.empty(2,np.float64)
        self.current=np.empty((4,2),np.float64);self.edges=np.empty(21,np.float64)
        self.polarity=np.empty(4,np.int32)
        self.source=np.empty((4,2),np.float64);self.source_stats=np.empty(27,np.float64);self.meta=np.empty(8,np.float64)
        if self.available:
            self.edge_function=_address(_LIB__v87_v74_native.p11_edges_checked);self.source_function=_address(_LIB__v87_v74_native.p11_yuyv_refine64)

    def clear(self):self.pending=None

    def measure(self,gray,quad,radius,image,scale,index,checks,previous_polarity):
        self.pending=None;self.detail=dict(native_transaction_used=False,source_proof_reused=False)
        if not self.available or checks!='auto' or image is None or image.ndim!=3 or image.shape[2]!=2:return None
        from core import require_yuyv as require_yuyv; from core import color_mode as color_mode
        image=require_yuyv(image);g=np.ascontiguousarray(gray,np.uint8)
        if g.ndim!=2:return None
        self.proposed[:]=quad;self.scale[:]=scale
        self.polarity.fill(0)
        for i,value in enumerate(previous_polarity[:4]):self.polarity[i]=int(value)
        begin=time.perf_counter();cpu=time.thread_time()
        code=self.lib.p11_v91_postlk(self.edge_function,self.source_function,
            g.ctypes.data,g.shape[1],g.shape[0],g.strides[0],image.ctypes.data,image.shape[1],image.shape[0],image.strides[0],
            color_mode(),self.proposed.ctypes.data,float(radius),self.scale.ctypes.data,self.polarity.ctypes.data,
            self.current.ctypes.data,self.edges.ctypes.data,self.source.ctypes.data,self.source_stats.ctypes.data,self.meta.ctypes.data)
        if code:raise ValueError('V91 post-LK original kernel rejected input: '+str(code))
        q=self.current.astype(np.float32);stats=self.edges
        evidence=dict(edge_support=stats[:4].tolist(),edge_polarity=stats[4:8].astype(int).tolist(),
            refined_corners=int(stats[16]),supported_edges=int(stats[17]),median_edge_shift=float(np.median(stats[8:12])),
            edge_rms=stats[12:16].tolist(),max_edge_rms=float(max(stats[12:16])),edge_backend='cpp_analytic_tls',
            native_valid=bool(stats[20]),valid=bool(stats[20]),edge_measure_s=float(self.meta[5]))
        self.detail=dict(native_transaction_used=True,transaction_s=time.perf_counter()-begin,
            transaction_thread_cpu_s=time.thread_time()-cpu,current24_native_s=float(self.meta[5]),
            source64_native_s=float(self.meta[6]),source64_thread_cpu_s=float(self.meta[7]),
            independent_source_prepared=bool(self.meta[4]),source_proof_reused=False,
            grids=[[24,.055,.945],[64,.06,.94]],original_native_kernels=True)
        if self.meta[4]:
            self.pending=(_key(image),_key(gray),int(index),q.tobytes(),tuple(float(v) for v in scale))
        return q,evidence

    def take_source(self,image,gray,candidate,scale,index,narrow):
        pending=self.pending;self.pending=None
        if pending is None or image is None:return None
        q=np.asarray(candidate,np.float32);s=np.asarray(scale,np.float64)
        if q.shape!=(4,2) or not np.isfinite(q).all() or s.shape!=(2,):return None
        token=(_key(image),_key(gray),int(index),q.tobytes(),tuple(float(v) for v in s))
        half=min(24.,max(3.,float(narrow)*float(s.max())))
        if token!=pending:
            self.detail['source_reuse_rejected']='current_source_gray_index_quad_or_scale_mismatch';return None
        if half!=float(self.meta[0]) or float(narrow)!=float(self.meta[1]):
            self.detail['source_reuse_rejected']='current_proof_band_mismatch';return None
        local=(q+.5)*s-.5
        h,w=image.shape[:2]
        if (not np.isfinite(local).all() or np.any(local<2) or np.any(local[:,0]>w-3)
                or np.any(local[:,1]>h-3) or not cv2.isContourConvex(local.astype(np.float32))):return None
        result,detail=_decode_source64(local,half,self.source,self.source_stats)
        edges=detail['edges'];accepted=len(edges)==4 and detail.get('refined_corners')==4 and all(e.get('accepted',False) for e in edges)
        support=[e.get('retained',0)/64. if e.get('accepted',False) else 0. for e in edges]
        rms=[float(e.get('tls_rms',1e30))/float(s.min()) for e in edges]
        contrast=np.array([e.get('profile_contrast',0.) for e in edges],np.float64)
        polarity=np.where(np.abs(contrast)>=8,np.sign(contrast),0).astype(int).tolist()
        valid=bool(accepted and min(support)>=.60 and all(e.get('coverage',0.)>=.60 for e in edges))
        origin=np.zeros(2,np.float64)
        observed=((result+origin+.5)/s-.5).astype(np.float32)
        from geometry import array_key as array_key
        evidence=dict(valid=valid,refined_corners=4 if valid else 0,supported_edges=sum(v>=.60 for v in support),
            edge_support=support,edge_rms=rms,edge_polarity=polarity,edge_backend='cpp_current_source_Y64',
            method='p1_original_resolution_normal_profiles_TLS',source_proof=detail,tracking_roi_offset=[0.,0.],
            same_frame_source=True,profiles_per_edge=64,current_source_key=array_key(image),
            source_proof_kind='source_Y_profiles',fraction_limits=[.06,.94],
            boundary_fallback_s=time.perf_counter()-float(self.meta[2]),
            boundary_fallback_thread_cpu_s=time.thread_time()-float(self.meta[3]),postlk_native_transaction=True)
        self.detail['source_proof_reused']=True
        return dict(proof=(observed,evidence),begin=float(self.meta[2]),cpu=float(self.meta[3]))


def _decode_source64(q,half,out,stats):
    """Original V74 refine64 returned-corner guards and edge metadata."""
    if not np.isfinite(out).all() or not np.isfinite(stats).all():raise ValueError('native original-Y64 returned invalid geometry')
    count=int(stats[24]);edges=[]
    for i in range(4):
        n=int(stats[i*6]);info=dict(edge=i,profiles=64,supported=n,accepted=bool(stats[i*6+4]),profile_contrast=float(stats[i*6+5]))
        if n>=20:info.update(tls_rms=float(stats[i*6+1]),retained=int(stats[i*6+2]),coverage=float(stats[i*6+3]))
        edges.append(info)
    try:
        candidate=out.astype(np.float32)
        if not cv2.isContourConvex(candidate):raise ValueError('native64 refined convexity invalid')
        area_ratio=abs(cv2.contourArea(candidate))/abs(cv2.contourArea(q.astype(np.float32)))
        if not .85<=area_ratio<=1.15 or np.max(np.linalg.norm(candidate-q,axis=1))>3*half:
            raise ValueError('native64 refined area/order/displacement invalid')
    except (ValueError,cv2.error):candidate=q.astype(np.float32);count=0
    return candidate,dict(method='p1_pyramid_subpixel_profiles_tls',backend='cpp_packed_Y_64x65_Q5',
        state='refined' if count else 'coarse_retained',refined_corners=count,edges=edges,half_window_pixels=float(half),
        corner_displacements=np.linalg.norm(candidate-q,axis=1).tolist(),
        refinement_s=float(stats[25]),refinement_thread_cpu_s=float(stats[26]),
        native_wall_s=float(stats[25]),native_thread_cpu_s=float(stats[26]),workspace_reused=True,
        interpolation='opencv_uint8_linear_replicate',tls_solver='analytic_2x2_principal_axis',original_profile_gates_preserved=True)


class PackedInput:
    def __init__(self,job,offsets,detail):
        self.token=(id(job),job.index,int(job.color_mode),tuple(id(t) for t in job.tiles))
        self.offsets=tuple(offsets);self.detail=dict(detail)
        #   ⭐ C2：DMA 每个像素搬几个字节。4 = 老路径（PS 打好 BGRX32）；
        #      2 = PL 侧转换（PS 只搬 YUYV）。execute() 用它算 n_in。
        self.bpp=int(detail.get('input_bpp',4))

    def matches(self,job):return self.token==(id(job),job.index,int(job.color_mode),tuple(id(t) for t in job.tiles))


class InputPackWorkspace:
    def __init__(self):
        self.owner=threading.get_ident();self.lib=prepare_transactions();self.pointer=None
        self.descriptors=np.empty((32,5),np.int32);self.stats=np.empty(10,np.float64)
        from display import prepare_io as prepare_io
        self.kernel=prepare_io()
        if self.lib is not None:
            self.pointer=self.lib.p11_v91_pack_create(_address(self.kernel.p11_v64_pack))
            if not self.pointer:raise MemoryError('V91 input packing workspace allocation failed')

    def pack(self,job,destination):
        #   ⭐ 2026-10-24 仪表：把 pack() 拆成 4 段，定位 input_copy_s 里那 4.7ms 的非原生开销。
        _t0=time.perf_counter()
        if threading.get_ident()!=self.owner:raise RuntimeError('Input packing must remain on P1 owner')
        if self.pointer is None or not 2<=len(job.tiles)<=32:return None
        offset=0;offsets=[]
        for i,tile in enumerate(job.tiles):
            x,y,w,h=map(int,tile.crop)
            if min(w,h)<2 or offset+w*h*4>destination.nbytes:return None
            self.descriptors[i]=(x,y,w,h,offset);offsets.append(offset);offset+=w*h*4
        _t1=time.perf_counter()
        from core import require_yuyv as require_yuyv
        image=require_yuyv(job.lease.image)
        if destination.dtype!=np.uint8 or not destination.flags.c_contiguous or not destination.flags.writeable:
            raise ValueError('V91 input destination must be writable contiguous uint8 CMA')
        _t2=time.perf_counter()
        code=self.lib.p11_v91_pack_batch(self.pointer,image.ctypes.data,image.strides[0],image.shape[1],image.shape[0],
            int(job.color_mode),self.descriptors.ctypes.data,len(job.tiles),destination.ctypes.data,destination.nbytes,self.stats.ctypes.data)
        _t3=time.perf_counter()
        if code:raise ValueError('V91 input batch rejected: '+str(code))
        detail=dict(input_pack_batch=True,input_pack_tiles=len(job.tiles),input_pack_bytes=offset,
            input_pack_kernel_calls=int(self.stats[0]),input_pack_converted_pixels=int(self.stats[1]),
            input_pack_requested_pixels=int(self.stats[2]),input_pack_native_s=float(self.stats[4]),
            input_pack_thread_cpu_s=float(self.stats[5]),input_pack_workspace_bytes=int(self.stats[6]),
            input_pack_original_color_kernel=True,input_pack_row_reuse=bool(self.stats[8]),
            input_pack_overlap_area=int(self.stats[9]),
            input_pack_desc_s=_t1-_t0,input_pack_prep_s=_t2-_t1,input_pack_call_s=_t3-_t2)
        out=PackedInput(job,offsets,detail)
        out.detail['input_pack_total_s']=time.perf_counter()-_t0
        return out

    def close(self):
        if threading.get_ident()!=self.owner:raise RuntimeError('Packing workspace close must stay on owner')
        if self.pointer:self.lib.p11_v91_pack_destroy(self.pointer);self.pointer=None


# ======================================================================
# ===== [28/28] v105_native =====
# ======================================================================


"""Lazy CPU edge addon: compile once at selection/startup, never per frame."""
from core import checkpoint as checkpoint
from core import RELEASE_ID as RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_LIB__v105_native=None
_ERROR__v105_native=None
_LOCK__v105_native=threading.Lock()

def prepare_edges():
    global _LIB__v105_native,_ERROR__v105_native
    with _LOCK__v105_native:
        if _LIB__v105_native is not None:return _LIB__v105_native
        if _ERROR__v105_native is not None:return None
        try:
            source=Path(__file__).with_name('v105_edges.cpp')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()[:20]
            suffix='.dll' if platform.system()=='Windows' else '.so'
            target=source.with_name('v105_edges_'+digest+'_'+platform.machine()+suffix)
            if not target.exists():
                compiler=os.environ.get('P11_EDGE_CXX') or shutil.which('g++') or shutil.which('c++')
                if not compiler:raise RuntimeError('C++ compiler unavailable')
                cmd=[compiler]+(['c++'] if Path(compiler).stem=='zig' else [])+['-O3','-std=c++11','-ffp-contract=off','-shared']
                if Path(compiler).stem=='zig':cmd+=['-fno-exceptions','-fno-rtti','-nostdlib++']
                if suffix=='.so':cmd+=['-fPIC']
                if platform.machine()=='armv7l':cmd+=['-mfpu=neon']
                temporary=target.with_name(target.stem+'.building'+suffix)
                try:
                    result=subprocess.run(cmd+[str(source),'-o',str(temporary)],capture_output=True,text=True,timeout=300 if os.name=='nt' else 90,
                        **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
                    if result.returncode:raise RuntimeError(result.stderr[-1600:])
                    temporary.replace(target)
                finally:
                    if temporary.exists():temporary.unlink()
            lib=ctypes.CDLL(str(target));ptr=ctypes.c_void_p;integer=ctypes.c_int
            lib.p11_edges_abi.argtypes=[];lib.p11_edges_abi.restype=integer
            if lib.p11_edges_abi()!=10501:raise RuntimeError('edge ABI mismatch')
            lib.p11_edges.argtypes=[ptr,integer,integer,integer,ptr,ctypes.c_float,ptr,ptr,ptr,ptr]
            lib.p11_edges.restype=integer
            _LIB__v105_native=lib;checkpoint('PHYSICAL_NATIVE_READY',abi=10501,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),path=str(target))
            return lib
        except (OSError,RuntimeError,subprocess.SubprocessError) as exc:
            _ERROR__v105_native=str(exc);checkpoint('PHYSICAL_NATIVE_UNAVAILABLE',reason=_ERROR__v105_native,fallback='vectorized CPU edge implementation')
            return None

class EdgeWorkspace:
    def __init__(self):
        self.lib=prepare_edges();self.body=np.empty(96,np.float32);self.q=np.empty((4,2),np.float32)
        self.stats=np.empty(12,np.float32)
    def measure(self,gray,q,radius,reference):
        gray=np.ascontiguousarray(gray,np.uint8);q=np.ascontiguousarray(q,np.float32)
        ref=None if reference is None else np.ascontiguousarray(reference,np.float32)
        if gray.ndim!=2 or q.shape!=(4,2) or not np.isfinite(q).all():raise ValueError('Invalid edge input')
        if ref is not None and (ref.size!=96 or not np.isfinite(ref).all()):raise ValueError('Invalid edge reference')
        result=self.lib.p11_edges(gray.ctypes.data,gray.shape[1],gray.shape[0],gray.strides[0],q.ctypes.data,
            radius,None if ref is None else ref.ctypes.data,self.body.ctypes.data,self.q.ctypes.data,self.stats.ctypes.data)
        if result:raise ValueError('physical_edge_proof_failed:'+str(result))
        return self.q.copy(),dict(support=self.stats[:4].tolist(),edge_rms=self.stats[4:8].tolist(),
            sample_count=96,edge_backend='native105',body=self.body.copy())
