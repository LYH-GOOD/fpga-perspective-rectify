"""Resident request facade, imported only by an explicit AI selection."""
from pathlib import Path
import hashlib
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
from v99_ai_service import Request,start_request
