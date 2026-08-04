"""In-memory sliding-window rate limiting for HTTP endpoints.

A ``RateLimiter`` is a token bucket per key (typically the client IP):
at most ``limit`` calls are allowed inside a rolling ``window_sec`` window.
State lives in memory only (single process); an ``asyncio.Lock`` keeps the
timestamp deques consistent across concurrent requests.  Expired windows are
dropped from the per-key map on access so the dict cannot grow without bound
as distinct IPs come and go.
"""

import asyncio
import time
from collections import deque

from fastapi import Request

from app.core.errors import AppError


class RateLimiter:
    """Sliding-window token bucket: at most ``limit`` calls per ``window_sec``."""

    def __init__(self, limit: int, window_sec: int = 60) -> None:
        self._limit = limit
        self._window_sec = window_sec
        self._timestamps: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        """Record one call for ``key``; return ``False`` when over the limit.

        Expired timestamps are pruned on access; when a window has fully
        elapsed the key is dropped from ``_timestamps`` and the current call
        starts a fresh window, so empty per-key deques never linger.
        """
        now = time.monotonic()
        async with self._lock:
            window = self._timestamps.get(key)
            if window is None:
                self._timestamps[key] = deque([now])
                return True
            cutoff = now - self._window_sec
            while window and window[0] <= cutoff:
                window.popleft()
            if not window:
                # Every timestamp expired: pop the empty deque instead of
                # leaving it behind, then start a fresh window for this call.
                self._timestamps.pop(key, None)
                self._timestamps[key] = deque([now])
                return True
            if len(window) >= self._limit:
                return False
            window.append(now)
            return True


async def rate_limit_dependency(request: Request) -> None:
    """Reject the request with 429 once the client IP exceeds the configured rate.

    The limiter is created in ``main.py``'s lifespan from
    ``Settings.rate_limit_per_min`` and stored on ``app.state.rate_limiter``,
    so tests can override the env var before the app starts.
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    key = request.client.host if request.client else "unknown"
    if not await limiter.allow(key):
        raise AppError("rate_limited", message="rate limit exceeded")
