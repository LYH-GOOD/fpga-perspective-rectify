"""Compatibility entry: all automatic work uses the complete original V74 frontend.

Manual motion lives only in v82_manual and requires explicit UI calibration.
The former automatic MotionFrontend/audit/reentry machinery is not imported.
"""
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def create_frontend(*args,**kwargs):
    from v64_camera_hdmi import Frontend
    # Two trailing historical book-rescue options are ignored by exact V74.
    # Both initial auto acquisition and recovery after manual loss use this.
    return Frontend(*args[:13],**kwargs)
