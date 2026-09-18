import hashlib
import threading
import time
from collections import defaultdict, deque
from typing import Any, Protocol

from fastapi import HTTPException, Request

from app.config import RateLimitBackend, Settings
from app.security import normalize_email


class RateLimiterUnavailable(RuntimeError):
    pass


class RateLimiter(Protocol):
    def check(self, key: str, *, limit: int, window_seconds: int) -> None: ...
    def check_available(self) -> None: ...


class InMemoryRateLimiter:
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

    def check_available(self) -> None:
        return None


_CHECK_SCRIPT = """
local value = redis.call('INCR', KEYS[1])
if value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
return value
"""


class RedisRateLimiter:
    def __init__(self, url: str, prefix: str) -> None:
        import redis

        self.client: Any = redis.Redis.from_url(
            url, socket_connect_timeout=2, socket_timeout=2
        )
        self.prefix = prefix

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        bucket = int(time.time()) // window_seconds
        redis_key = f"{self.prefix}:{key}:{bucket}"
        try:
            value = int(self.client.eval(_CHECK_SCRIPT, 1, redis_key, window_seconds + 1))
        except Exception as exc:
            raise RateLimiterUnavailable from exc
        if value > limit:
            raise HTTPException(status_code=429, detail="Too many requests")

    def check_available(self) -> None:
        try:
            self.client.ping()
        except Exception as exc:
            raise RateLimiterUnavailable from exc


def create_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.rate_limit_backend == RateLimitBackend.REDIS and settings.redis_url:
        return RedisRateLimiter(settings.redis_url, settings.rate_limit_key_prefix)
    return InMemoryRateLimiter()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _address(request: Request) -> str:
    # The ASGI peer is authoritative; do not trust arbitrary forwarding headers.
    return _digest(request.client.host if request.client else "unknown")


def check_auth_rate(
    request: Request, scope: str, *, limit: int = 10, email: str | None = None
) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    try:
        limiter.check(f"{scope}:address:{_address(request)}", limit=limit, window_seconds=60)
        if email:
            limiter.check(
                f"{scope}:email:{_digest(normalize_email(email))}",
                limit=limit,
                window_seconds=60,
            )
    except RateLimiterUnavailable as exc:
        raise HTTPException(status_code=503, detail="Rate limiting is temporarily unavailable") from exc


def check_upload_rate(request: Request, user_id: object, organization_id: object) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    try:
        for key, limit in (
            (f"upload:user:{user_id}", 20),
            (f"upload:organization:{organization_id}", 100),
            (f"upload:address:{_address(request)}", 30),
        ):
            limiter.check(key, limit=limit, window_seconds=60)
    except RateLimiterUnavailable as exc:
        raise HTTPException(status_code=503, detail="Rate limiting is temporarily unavailable") from exc


InProcessRateLimiter = InMemoryRateLimiter
