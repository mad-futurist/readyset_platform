import os
import uuid

import pytest
from fastapi import FastAPI, HTTPException, Request

from app.config import Settings
from app.rate_limit import InMemoryRateLimiter, RedisRateLimiter, client_address


def _request(peer: str, *, forwarded_for: str | None, settings: Settings) -> Request:
    app = FastAPI()
    app.state.settings = settings
    headers = [] if forwarded_for is None else [(b"x-forwarded-for", forwarded_for.encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 12345),
            "app": app,
        }
    )


def test_memory_limiter_allows_then_blocks_and_scopes_are_independent() -> None:
    limiter = InMemoryRateLimiter()
    limiter.check("login:one", limit=2, window_seconds=60)
    limiter.check("login:one", limit=2, window_seconds=60)
    with pytest.raises(HTTPException) as error:
        limiter.check("login:one", limit=2, window_seconds=60)
    assert error.value.status_code == 429
    limiter.check("register:one", limit=2, window_seconds=60)


def test_client_address_uses_direct_peer_when_proxy_headers_are_disabled() -> None:
    request = _request(
        "198.51.100.8",
        forwarded_for="203.0.113.10",
        settings=Settings(environment="test"),
    )
    assert client_address(request) == "198.51.100.8"


def test_client_address_ignores_spoofed_header_from_untrusted_peer() -> None:
    request = _request(
        "198.51.100.8",
        forwarded_for="203.0.113.10",
        settings=Settings(
            environment="test",
            trust_proxy_headers=True,
            trusted_proxy_cidrs=["10.0.0.0/8"],
        ),
    )
    assert client_address(request) == "198.51.100.8"


def test_client_address_walks_trusted_proxy_chain_from_right_to_left() -> None:
    request = _request(
        "10.0.0.3",
        forwarded_for="203.0.113.10, 10.0.0.2",
        settings=Settings(
            environment="test",
            trust_proxy_headers=True,
            trusted_proxy_cidrs=["10.0.0.0/8"],
        ),
    )
    assert client_address(request) == "203.0.113.10"


def test_client_address_malformed_forwarding_falls_back_to_peer() -> None:
    request = _request(
        "10.0.0.3",
        forwarded_for="not-an-ip, 10.0.0.2",
        settings=Settings(
            environment="test",
            trust_proxy_headers=True,
            trusted_proxy_cidrs=["10.0.0.0/8"],
        ),
    )
    assert client_address(request) == "10.0.0.3"


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
    keys = list(first.client.scan_iter(match=f"{prefix}:login:subject:*"))
    assert len(keys) == 1
    assert 0 < first.client.ttl(keys[0]) <= 61
    with pytest.raises(HTTPException) as error:
        first.check("login:subject", limit=2, window_seconds=60)
    assert error.value.status_code == 429
    second.check("register:subject", limit=1, window_seconds=60)
