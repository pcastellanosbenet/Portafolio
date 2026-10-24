"""Small in-memory rate limiter for the demo API."""

from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    """Allow a fixed number of requests per client in a sliding window."""

    def __init__(self, *, max_requests: int = 30, window_s: float = 60.0) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_s <= 0:
            raise ValueError("window_s must be positive")
        self.max_requests = max_requests
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_s
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.max_requests:
            return False
        hits.append(now)
        return True

    def retry_after(self, key: str) -> int:
        hits = self._hits.get(key)
        if not hits:
            return 0
        return max(1, int(self.window_s - (time.monotonic() - hits[0])))
