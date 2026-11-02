"""Streaming low-resolution exterior proposals; each still needs source proof."""
from pathlib import Path
import hashlib
import cv2
import numpy as np
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def exterior_candidates(image,check,limit=192):
    """Rank bounded outer/enclosed hypotheses; all still need source proof."""
    from v62_exterior import ranked_exterior_candidates
    yield from ranked_exterior_candidates(image,check,limit)
