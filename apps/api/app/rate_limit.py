import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class InProcessRateLimiter:
    """A bounded local guard; production must also enforce a shared edge limit."""

    def __init__(self, max_keys: int = 10_000) -> None:
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(status_code=429, detail="Too many requests")
            events.append(now)
            if len(self._events) > self.max_keys:
                stale = [
                    candidate
                    for candidate, values in self._events.items()
                    if not values or values[-1] < cutoff
                ]
                for candidate in stale[: len(self._events) - self.max_keys]:
                    self._events.pop(candidate, None)


def check_auth_rate(request: Request, scope: str, *, limit: int = 10) -> None:
    address = request.client.host if request.client else "unknown"
    request.app.state.auth_limiter.check(f"{scope}:{address}", limit=limit, window_seconds=60)
