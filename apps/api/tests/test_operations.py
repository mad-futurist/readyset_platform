import json
import logging
from contextlib import nullcontext

from fastapi.testclient import TestClient

from app.main import _request_log
from app.storage import StorageUnavailable


class ReadyConnection:
    def execute(self, statement: object) -> None:
        return None


class ReadyEngine:
    def connect(self):
        return nullcontext(ReadyConnection())


class FailingDependency:
    def check_access(self) -> None:
        raise ConnectionError("secret-internal-host.example")


class FailingEngine:
    def connect(self):
        raise ConnectionError("db.internal")


class FailingCheck:
    def check_available(self) -> None:
        raise ConnectionError("dependency.internal")


def test_liveness_has_no_external_dependency_calls(client: TestClient) -> None:
    client.app.state.storage = FailingDependency()
    assert client.get("/livez").json() == {"status": "ok"}
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readiness_checks_dependencies_without_leaking_details(client: TestClient) -> None:
    client.app.state.database_engine = ReadyEngine()
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}

    client.app.state.storage = FailingDependency()
    failed = client.get("/readyz")
    assert failed.status_code == 503
    assert failed.json() == {"status": "unavailable"}
    assert "secret-internal-host" not in failed.text


def test_readiness_fails_for_database_limiter_and_scanner(client: TestClient) -> None:
    original_engine = client.app.state.database_engine
    original_storage = client.app.state.storage
    original_limiter = client.app.state.rate_limiter
    original_scanner = client.app.state.file_scanner
    try:
        client.app.state.database_engine = FailingEngine()
        assert client.get("/readyz").status_code == 503
        client.app.state.database_engine = ReadyEngine()
        client.app.state.storage = original_storage
        client.app.state.rate_limiter = FailingCheck()
        assert client.get("/readyz").status_code == 503
        client.app.state.rate_limiter = original_limiter
        client.app.state.file_scanner = FailingCheck()
        assert client.get("/readyz").status_code == 503
    finally:
        client.app.state.database_engine = original_engine
        client.app.state.storage = original_storage
        client.app.state.rate_limiter = original_limiter
        client.app.state.file_scanner = original_scanner


def test_unexpected_error_response_is_controlled_and_has_request_id(client: TestClient) -> None:
    @client.app.get("/test-only-unexpected")
    def fail() -> None:
        raise RuntimeError("sensitive internal exception")

    isolated = TestClient(client.app, base_url="http://localhost", raise_server_exceptions=False)
    response = isolated.get("/test-only-unexpected")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
    assert "sensitive internal exception" not in response.text


def test_storage_error_response_is_controlled(client: TestClient) -> None:
    @client.app.get("/test-only-storage-error")
    def fail_storage() -> None:
        raise StorageUnavailable("boto endpoint and credentials must not leak")

    isolated = TestClient(client.app, base_url="http://localhost", raise_server_exceptions=False)
    response = isolated.get("/test-only-storage-error")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert "boto endpoint" not in response.text


def test_structured_request_log_is_valid_json_with_required_fields(caplog) -> None:
    payload = {
        "timestamp": "2026-09-18T12:00:00+00:00",
        "level": "info",
        "request_id": "request-1",
        "method": "GET",
        "path": "/livez",
        "status": 200,
        "latency_ms": 1.5,
    }
    with caplog.at_level(logging.INFO, logger="readyset.request"):
        _request_log(payload, structured=True)
    assert json.loads(caplog.records[-1].message) == payload
