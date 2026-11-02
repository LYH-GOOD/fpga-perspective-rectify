"""Per-run CPU policies; inherited by copied worker contexts, never global mutable options."""
from pathlib import Path
from contextvars import ContextVar
from functools import wraps
import hashlib,math
from p11_contract import RELEASE_ID
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
            from run_logging import checkpoint
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
