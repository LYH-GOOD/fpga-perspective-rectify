"""Cheap, completed-output evidence for automatic-to-AI rescue.

Caller timestamps use the same monotonic clock.  The owner must report only
successful output completion and must gate callbacks by its run/generation;
metadata alone cannot identify an old callback completed after a reset.
"""
from collections import deque
import hashlib
import math
import operator
from pathlib import Path
from threading import Lock

from p11_contract import RELEASE_ID

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
