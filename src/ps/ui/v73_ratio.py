"""Event-activated output geometry; the untouched default orientation stays native."""
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import hashlib,math,threading
from p11_contract import RELEASE_ID
from v50_orientation import DualOrientation as OriginalOrientation
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

SHIFT=1<<20
PRESETS=('original','1:1','3:4','4:3','16:9')
_CONTEXT=ContextVar('p11_v73_ratio_profile',default=None)
_BINDINGS={}
class RatioPlanRejected(RuntimeError):pass

def normalize(value):
    if value=='original':return value
    try:
        first,second=str(value).split(':');w=float(first);h=float(second)
    except (TypeError,ValueError):raise ValueError('invalid_ratio')
    if not all(math.isfinite(v) and .1<=v<=9999 for v in (w,h)) or not .5<=w/h<=2:
        raise ValueError('ratio_range')
    return '%g:%g'%(w,h)

def dimensions(value):
    value=normalize(value)
    fixed={'1:1':(430,430),'3:4':(372,496),'4:3':(496,372),'16:9':(560,315)}
    if value=='original':return None
    if value in fixed:return fixed[value]
    w,h=map(float,value.split(':'));ratio=w/h
    height=min(512.,math.sqrt(185344./ratio))
    return int(height*ratio)//2*2,int(height)//2*2

class RatioRegistry:
    def __init__(self):
        self.lock=threading.RLock();self.serial=0;self.entries=[]
        self.desired={'auto':('original',0),'manual':('original',0)}
        self.applied=dict(self.desired)
        self.sizes={'auto':None,'manual':None}
        self.fronts={};self.pending_modes={'auto':False,'manual':False};self.on_reject=None
    @contextmanager
    def scope(self,mode):
        if mode not in self.desired:raise ValueError('Unknown ratio profile')
        with self.lock:
            for item,_ in self.entries:_BINDINGS.pop(item,None)
            self.entries=[]
        token=_CONTEXT.set((self,mode))
        try:yield
        finally:
            _CONTEXT.reset(token)
            with self.lock:
                for mode in self.desired:self._retire_fronts(mode)
                for item,_ in self.entries:_BINDINGS.pop(item,None)
                self.entries=[];self.fronts={}
    def register(self,item,mode):
        with self.lock:
            self.entries.append((item,mode))
            if len(self.entries)>64:del self.entries[:-64]
            if self.desired[mode][0]!='original':self._activate(item,mode)
        return item
    def _activate(self,item,mode):
        _BINDINGS[item]=(self,mode)
        item.__class__=RatioOrientation
    def attach_manual_frontend(self,front,mode):
        with self.lock:
            self.fronts[front.orientation]=dict(front=front,mode=mode,prepare=front.prepare,plan=front.plan,
                had_prepare='prepare' in front.__dict__,had_plan='plan' in front.__dict__)
            if self.pending_modes[mode]:self._install_front(self.fronts[front.orientation])
    def _install_front(self,entry):
        if 'wrapped_prepare' in entry:return
        front=entry['front'];mode=entry['mode'];base_prepare=entry['prepare'];base_plan=entry['plan']
        def plan(q,shape,size):
            try:return base_plan(q,shape,size)
            except ValueError as exc:
                with self.lock:
                    value,revision=self.desired[mode];enabled=self.pending_modes[mode];target=self.sizes[mode]
                matching=tuple(size)==target if target is not None else tuple(size) in (tuple(front.size),tuple(front.size)[::-1])
                if not enabled or not matching:raise
                if self.on_reject is not None:self.on_reject(mode,revision,str(exc))
                else:self.rollback(mode)
                raise RatioPlanRejected(str(exc)) from exc
        def prepare(index):
            try:return base_prepare(index)
            except RatioPlanRejected:
                # ManualTracker advances by source sequence/time, not job index.
                # The original outer exception path already released the rejected
                # lease. Retry once using the restored destination on a new frame.
                return base_prepare(index)
        entry.update(wrapped_prepare=prepare,wrapped_plan=plan);front.prepare=prepare;front.plan=plan
    def _retire_fronts(self,mode):
        for entry in self.fronts.values():
            if entry['mode']!=mode or 'wrapped_prepare' not in entry:continue
            front=entry['front']
            for name in ('prepare','plan'):
                if getattr(front,name)==entry['wrapped_'+name]:
                    if entry['had_'+name]:setattr(front,name,entry[name])
                    else:front.__dict__.pop(name,None)
                entry.pop('wrapped_'+name,None)
    def request(self,mode,value):
        value=normalize(value)
        with self.lock:
            self.serial+=1;self.desired[mode]=(value,self.serial)
            self.pending_modes[mode]=True
            self.sizes[mode]=dimensions(value)
            for item,profile in self.entries:
                if profile==mode:self._activate(item,mode)
            for entry in self.fronts.values():
                if entry['mode']==mode:self._install_front(entry)
            return self.serial
    def finish(self,mode,revision):
        with self.lock:
            if self.desired[mode][1]!=revision:return False
            self.applied[mode]=self.desired[mode]
            self.pending_modes[mode]=False;self._retire_fronts(mode)
            if self.applied[mode][0]=='original':self._restore(mode)
            return True
    def rollback(self,mode):
        with self.lock:
            self.desired[mode]=self.applied[mode]
            self.pending_modes[mode]=False;self._retire_fronts(mode)
            self.sizes[mode]=dimensions(self.desired[mode][0])
            if self.desired[mode][0]=='original':self._restore(mode)
    def _restore(self,mode):
        for item,profile in self.entries:
            if profile==mode:
                item.__class__=OriginalOrientation
                _BINDINGS.pop(item,None)

class RatioOrientation(OriginalOrientation):
    __slots__=()
    def propose(self,*args,**kwargs):
        # A touch may restore the original class while an old bound call runs.
        binding=_BINDINGS.get(self)
        if binding is None:return OriginalOrientation.propose(self,*args,**kwargs)
        registry,mode=binding
        with registry.lock:
            value,revision=registry.desired[mode];size=registry.sizes[mode]
        proposal=OriginalOrientation.propose(self,*args,**kwargs)
        size=size or proposal.size
        return replace(proposal,size=size,detail=dict(proposal.detail,
            output_size=list(size) if size is not None else None,
            output_ratio=value,output_ratio_revision=revision if value!='original' else 0,output_ratio_profile=mode))
    def commit(self,proposal):
        result=OriginalOrientation.commit(self,proposal)
        revision=proposal.detail.get('output_ratio_revision')
        if revision is not None:
            generation=int(result.get('layout_generation',0))
            if not 0<=generation<SHIFT:raise ValueError('orientation_generation_overflow')
            result['layout_generation']=int(revision)*SHIFT+generation
        return result

def make_orientation(*args,**kwargs):
    item=OriginalOrientation(*args,**kwargs);binding=_CONTEXT.get()
    return item if binding is None else binding[0].register(item,binding[1])

def register_manual_frontend(front):
    binding=_CONTEXT.get()
    if binding is not None:binding[0].attach_manual_frontend(front,binding[1])

def revision_of(meta):return int(meta.get('layout_generation',0))//SHIFT
