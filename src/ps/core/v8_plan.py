"""Immutable snapshots of plans already validated by the geometry planner.

Not a security boundary against hostile Python code. Prevents accidental mutation
and substitution of a stale table in the supported runner/runtime path.
"""
from pathlib import Path
from collections.abc import Mapping
from types import MappingProxyType
import hashlib,struct
import numpy as np
from p11_contract import RELEASE_ID,EXPECTED_HW,cache_profile
from pl_fields import validate_field
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_TOKEN=object()

def _parameters(data):
    return (tuple(data['input_shape']),data['width'],data['height'],
            tuple(data['regs']),data['border_flags'])

class ControlSnapshot:
    """Checked immutable wire bytes shared by preflight and sealed execution."""
    __slots__=('parameters','field','packet','key','backend','_token')
    def __init__(self,data,packet,backend,token):
        if token is not _TOKEN:raise TypeError('Use internal control preparation')
        if len(packet)!=1776*4:raise ValueError('ABI9控制包长度错误')
        object.__setattr__(self,'parameters',_parameters(data))
        object.__setattr__(self,'key',packet)
        object.__setattr__(self,'packet',np.frombuffer(packet,dtype='<u4'))
        object.__setattr__(self,'field',np.frombuffer(packet,dtype='<i4',offset=48).reshape(21,21,4))
        object.__setattr__(self,'backend',backend)
        object.__setattr__(self,'_token',token)
    def __setattr__(self,name,value):raise TypeError('Control snapshot is immutable')
    def matches(self,data,field):
        return field is self.field and self._token is _TOKEN and _parameters(data)==self.parameters

def checked_control(data,field):
    saved=data.get('_control_snapshot')
    return saved if type(saved) is ControlSnapshot and saved.matches(data,field) else None

class ControlContractError(RuntimeError):
    """A producer/consumer mismatch, not a geometry fallback or a PL proof."""

class InputLayoutError(ControlContractError):
    """Invalid YUYV metadata cannot be repaired by subdividing output tiles."""

def require_yuyv_shape(input_shape):
    """Keep source storage metadata distinct from a temporary BGR model image."""
    try:
        shape=tuple(input_shape)
        valid=(len(shape)==3 and shape[2]==2 and shape[1]%2==0
               and all(not isinstance(n,(bool,np.bool_)) and int(n)==n and int(n)>=2 for n in shape))
    except (TypeError,ValueError,OverflowError):
        valid=False
    if not valid:
        raise InputLayoutError('V31 plans require pair-aligned YUYV; actual input_shape='+repr(input_shape))
    return tuple(int(n) for n in shape)

def require_control_snapshot(data):
    """One key/packet API for frozen candidates and PL-certified plans.

    This checks CPU packet identity only. It never grants row-lifetime safety,
    seals a candidate, or accesses hardware. The key is the immutable wire bytes;
    no per-frame re-encoding or hashing is necessary.
    """
    if type(data) in (FrozenControlCandidate,ValidatedPlan) and data._token is _TOKEN:
        # Factory checked metadata once; every reachable parameter/field/packet
        # is immutable. This path confers no hardware row-lifetime certificate.
        return data['_control_snapshot']
    if not isinstance(data,Mapping):raise ControlContractError('Control candidate must be a mapping')
    try:
        saved=checked_control(data,data['field'])
    except (KeyError,TypeError,ValueError) as exc:
        raise ControlContractError('Control candidate metadata is incomplete') from exc
    if saved is None:raise ControlContractError('Control snapshot missing or parameters/field changed after freezing')
    if (saved.packet.dtype!=np.dtype('<u4') or saved.packet.shape!=(1776,)
            or saved.packet.flags.writeable or saved.field.flags.writeable):
        raise ControlContractError('Control snapshot layout/immutability mismatch')
    if 'control_key' in data and data['control_key']!=saved.key:
        raise ControlContractError('Published control key differs from checked snapshot')
    if 'control_packet' in data and data['control_packet'] is not saved.packet:
        raise ControlContractError('Published control packet differs from checked snapshot')
    return saved

def _freeze_control(data,backend='auto'):
    """Validate every channel before image DMA, then retain the exact wire bytes."""
    if backend not in ('auto','legacy'):raise ValueError('control_backend须为auto/legacy')
    require_yuyv_shape(data['input_shape'])
    hi,wi=data['input_shape'][:2];wo,ho=data['width'],data['height']
    if any(isinstance(n,bool) or int(n)!=n or not 2<=int(n)<=1280 for n in (wi,hi,wo,ho)):
        raise ValueError('单块尺寸必须为2..1280整数')
    regs=tuple(data['regs']);flags=data['border_flags']
    if len(regs)!=8 or any(isinstance(n,bool) or int(n)!=n or not -(1<<31)<=int(n)<(1<<31) for n in regs):
        raise ValueError('H寄存器必须为signed32整数')
    if isinstance(flags,bool) or int(flags)!=flags or not 0<=int(flags)<16:raise ValueError('源图边界标记错误')
    f=np.asarray(data['field']);packet=None
    if backend=='auto':
        from v31_native import encode_packet
        packet=encode_packet(f,regs,int(wi),int(hi),int(wo),int(ho),int(flags))
    name='cpp_checked_immutable_packet'
    if packet is None:
        f=validate_field(f)
        packet=struct.pack('<3I8iI',0x50394c44,(int(wi)<<16)|int(hi),(int(wo)<<16)|int(ho),
                           *regs,int(flags))+f.tobytes()
        name='python_checked_immutable_packet'
    data['regs']=regs
    frozen=ControlSnapshot(data,packet,name,_TOKEN)
    data['_control_snapshot']=frozen;data['field']=frozen.field
    return frozen


class ValidatedPlan(Mapping):
    __slots__=('_data','_token')
    def __init__(self,data,token):
        if token is not _TOKEN:raise TypeError('Use the geometry planner to create a validated plan')
        snapshot=dict(data)
        require_yuyv_shape(snapshot['input_shape'])
        for name in ('box','crop','regs','input_shape'):snapshot[name]=tuple(snapshot[name])
        # bytes-backed arrays cannot have WRITEABLE re-enabled by the caller.
        frozen=checked_control(data,data['field'])
        if frozen is None:frozen=_freeze_control(snapshot)
        snapshot['field']=frozen.field
        snapshot['descriptors']=np.frombuffer(np.asarray(data['descriptors'],np.uint32).tobytes(),np.uint32)
        # Encode once, after the same planner/field checks. Both views are backed
        # by immutable bytes: later table edits cannot retain a stale packet key.
        snapshot['_control_snapshot']=frozen
        snapshot['control_key']=frozen.key
        snapshot['control_packet']=frozen.packet
        object.__setattr__(self,'_data',MappingProxyType(snapshot))
        object.__setattr__(self,'_token',token)
    def __setattr__(self,name,value):raise TypeError('Validated plan is immutable')
    def __getitem__(self,key):return self._data[key]
    def __iter__(self):return iter(self._data)
    def __len__(self):return len(self._data)


class FrozenControlCandidate(Mapping):
    """Factory-owned immutable CPU packet; deliberately distinct from ValidatedPlan."""
    __slots__=('_data','_token')
    def __init__(self,data,token):
        if token is not _TOKEN:raise TypeError('Use internal candidate factory')
        snapshot=dict(data)
        for name in ('box','crop','regs','input_shape'):snapshot[name]=tuple(snapshot[name])
        frozen=require_control_snapshot(snapshot)
        snapshot['field']=frozen.field
        snapshot['control_key']=frozen.key;snapshot['control_packet']=frozen.packet
        snapshot['descriptors']=np.frombuffer(np.asarray(snapshot['descriptors'],np.uint32).tobytes(),np.uint32)
        object.__setattr__(self,'_data',MappingProxyType(snapshot))
        object.__setattr__(self,'_token',token)
    def __setattr__(self,name,value):raise TypeError('Frozen candidate is immutable')
    def __getitem__(self,key):return self._data[key]
    def __iter__(self):return iter(self._data)
    def __len__(self):return len(self._data)

def freeze_candidate(data):
    if type(data) in (FrozenControlCandidate,ValidatedPlan) and data._token is _TOKEN:return data
    return FrozenControlCandidate(data,_TOKEN)

def _seal_checked(data,input_shape):
    """Internal: caller checked crop/model guards and exact PL row planning."""
    shape=require_yuyv_shape(input_shape)
    if require_yuyv_shape(data['input_shape'])!=shape:
        raise InputLayoutError('Certified candidate input_shape differs from execution input_shape')
    if '_control_snapshot' in data:require_control_snapshot(data)
    d=dict(data);d.update(input_shape=shape,hardware_abi=EXPECTED_HW,release_id=RELEASE_ID)
    return ValidatedPlan(d,_TOKEN)


def require_plan(plan,input_shape):
    if type(plan) is not ValidatedPlan or plan._token is not _TOKEN:
        raise ValueError('需要本版规划器生成的不可变计划，不能传入自行修改的dict')
    if tuple(input_shape)!=plan['input_shape'] or plan['hardware_abi']!=EXPECTED_HW or plan['release_id']!=RELEASE_ID:
        raise ValueError('计划的输入尺寸、硬件ABI或发布版本不匹配')
    if plan.get('planning_backend')!='pl_exact_suffix_rows':raise ValueError('需要ABI9的PL规划证明')
    if cache_profile(input_shape[1])[1]!=plan['capacity_rows']:
        raise ValueError('缓存档位与计划不匹配')
    return plan


def with_tone(plan,gain_q8,offset_q8):
    """Replace only photometric channels: dx/dy, crop and row lifetime are intact."""
    require_plan(plan,plan['input_shape'])
    if np.shape(gain_q8)!=(21,21) or np.shape(offset_q8)!=(21,21):
        raise ValueError('光补系数须为21x21')
    field=plan['field'].copy();field[:,:,2]=gain_q8;field[:,:,3]=offset_q8
    validate_field(field)
    d=dict(plan);d['field']=field
    return ValidatedPlan(d,_TOKEN)


def _bind_native_control(data,packet):
    """Internal output of checked native preparation; still NOT a PL proof."""
    if not isinstance(packet,bytes) or len(packet)!=1776*4:
        raise ValueError('native control packet length invalid')
    require_yuyv_shape(data['input_shape'])
    hi,wi=data['input_shape'][:2];wo,ho=data['width'],data['height']
    header=struct.unpack_from('<3I8iI',packet)
    if header[:3]!=(0x50394c44,(wi<<16)|hi,(wo<<16)|ho) or header[-1]!=data['border_flags']:
        raise ValueError('native control packet dimensions/flags mismatch')
    data['regs']=tuple(header[3:11])
    frozen=ControlSnapshot(data,packet,'cpp_geometry_guard_tone_packet',_TOKEN)
    data['_control_snapshot']=frozen;data['field']=frozen.field
    return frozen
