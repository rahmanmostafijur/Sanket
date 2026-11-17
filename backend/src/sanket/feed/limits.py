"""Caps on concurrent streams, per process and per profile."""

import threading
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class StreamSlot:
    """A held stream slot; `release` is idempotent."""

    _limiter: "StreamLimiter"
    profile_id: int
    _released: bool = field(default=False, init=False)

    def release(self) -> None:
        if not self._released:
            self._released = True
            self._limiter._release(self.profile_id)


class StreamLimiter:
    def __init__(self, max_streams: int, max_per_profile: int) -> None:
        self._max = max_streams
        self._max_per_profile = max_per_profile
        self._per_profile: Counter[int] = Counter()
        self._lock = threading.Lock()

    def acquire(self, profile_id: int) -> StreamSlot | None:
        """A slot, or None when the process or the profile is at its cap."""
        with self._lock:
            if sum(self._per_profile.values()) >= self._max:
                return None
            if self._per_profile[profile_id] >= self._max_per_profile:
                return None
            self._per_profile[profile_id] += 1
        return StreamSlot(self, profile_id)

    def _release(self, profile_id: int) -> None:
        with self._lock:
            self._per_profile[profile_id] -= 1
            if self._per_profile[profile_id] <= 0:
                del self._per_profile[profile_id]

    @property
    def open_streams(self) -> int:
        with self._lock:
            return sum(self._per_profile.values())
