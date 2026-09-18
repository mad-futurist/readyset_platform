from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.database import Base, get_db
from app.main import create_app
from app.storage import MemoryObjectStorage


@pytest.fixture
def db_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def client(
    db_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEVELOPMENT_TOKEN_EXPOSURE", "true")
    get_settings.cache_clear()
    app = create_app()
    app.state.storage = MemoryObjectStorage()

    def override_db():  # type: ignore[no-untyped-def]
        db = db_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url="http://localhost") as test_client:
        yield test_client
    get_settings.cache_clear()


def register(
    client: TestClient, email: str, name: str = "Test User", *, authenticate: bool = True
) -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct horse battery staple", "display_name": name},
    )
    assert response.status_code == 202, response.text
    registration = response.json()
    if not authenticate:
        return registration
    assert (
        client.post(
            "/api/v1/auth/verify-email",
            json={"token": registration["development_verification_token"]},
        ).status_code
        == 204
    )
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct horse battery staple"},
    )
    assert login.status_code == 200, login.text
    result = login.json()
    result["development_verification_token"] = registration["development_verification_token"]
    return result


def auth_headers(client: TestClient, organization_id: str | None = None) -> dict[str, str]:
    headers = {"X-CSRF-Token": client.cookies.get("rs_csrf") or ""}
    if organization_id:
        headers["X-ReadySet-Organization"] = organization_id
    return headers


def create_org(client: TestClient, name: str) -> dict:
    response = client.post(
        "/api/v1/organizations",
        json={"name": name},
        headers=auth_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()
