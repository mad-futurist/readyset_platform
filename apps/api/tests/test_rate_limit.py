import os
import uuid

import pytest
from fastapi import HTTPException

from app.rate_limit import InMemoryRateLimiter, RedisRateLimiter


def test_memory_limiter_allows_then_blocks_and_scopes_are_independent() -> None:
    limiter = InMemoryRateLimiter()
    limiter.check("login:one", limit=2, window_seconds=60)
    limiter.check("login:one", limit=2, window_seconds=60)
    with pytest.raises(HTTPException) as error:
        limiter.check("login:one", limit=2, window_seconds=60)
    assert error.value.status_code == 429
    limiter.check("register:one", limit=2, window_seconds=60)


@pytest.mark.redis
def test_redis_limiter_is_shared_and_atomic() -> None:
    url = os.getenv("REDIS_TEST_URL")
    if not url:
        pytest.skip("REDIS_TEST_URL is not configured")
    prefix = f"readyset:test:{uuid.uuid4()}"
    first = RedisRateLimiter(url, prefix)
    second = RedisRateLimiter(url, prefix)
    first.check("login:subject", limit=2, window_seconds=60)
    second.check("login:subject", limit=2, window_seconds=60)
    with pytest.raises(HTTPException) as error:
        first.check("login:subject", limit=2, window_seconds=60)
    assert error.value.status_code == 429
