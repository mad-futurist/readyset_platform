import uuid
from urllib.parse import parse_qs, urlparse

import httpx
from conftest import auth_headers, register
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.models import (
    AuthIdentity,
    OAuthLoginState,
    OneTimeToken,
    PasswordCredential,
    SessionRecord,
    User,
    UserStatus,
)
from app.security import hash_token


def _enable_google(client: TestClient) -> Settings:
    settings = Settings(
        environment="test",
        google_auth_enabled=True,
        google_client_id="test-client",
        google_client_secret="test-secret",
    )
    client.app.dependency_overrides[get_settings] = lambda: settings
    return settings


def _start(client: TestClient, db_factory: sessionmaker[Session]) -> tuple[str, str]:
    response = client.get("/api/v1/auth/google/start")
    assert response.status_code == 200, response.text
    state = parse_qs(urlparse(response.json()["authorization_url"]).query)["state"][0]
    with db_factory() as db:
        pending = db.scalar(
            select(OAuthLoginState).where(OAuthLoginState.state_hash == hash_token(state))
        )
        assert pending
        return state, pending.nonce


def _mock_google(monkeypatch, *, subject: str, email: str, nonce: str, verified: bool = True):
    monkeypatch.setattr(
        "app.routes.auth.exchange_google_code",
        lambda *_args, **_kwargs: "mock-id-token",
    )
    monkeypatch.setattr(
        "app.routes.auth.verify_google_token",
        lambda *_args, **_kwargs: {
            "sub": subject,
            "email": email,
            "email_verified": verified,
            "nonce": nonce,
            "name": "Google Owner",
        },
    )


def _callback(client: TestClient, state: str):
    return client.get(
        "/api/v1/auth/google/callback",
        params={"code": "mock-code", "state": state},
        follow_redirects=False,
    )


def test_oauth_binding_cookie_is_narrow_secure_and_http_only(
    client: TestClient, db_factory: sessionmaker[Session]
) -> None:
    settings = Settings(
        environment="test",
        cookie_secure=True,
        google_auth_enabled=True,
        google_client_id="test-client",
        google_client_secret="test-secret",
    )
    client.app.dependency_overrides[get_settings] = lambda: settings
    response = client.get("/api/v1/auth/google/start")
    assert response.status_code == 200
    cookie_header = response.headers["set-cookie"]
    assert f"{settings.oauth_binding_cookie_name}=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=lax" in cookie_header
    assert "Path=/api/v1/auth/google/callback" in cookie_header


def test_unverified_password_prehijack_does_not_survive_google_link(
    client: TestClient, db_factory: sessionmaker[Session], monkeypatch
) -> None:
    registration = register(client, "victim@example.com", "Attacker supplied", authenticate=False)
    old_token = registration["development_verification_token"]
    assert old_token
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={
                "email": "victim@example.com",
                "password": "correct horse battery staple",
            },
        ).status_code
        == 401
    )

    _enable_google(client)
    state, nonce = _start(client, db_factory)
    _mock_google(monkeypatch, subject="google-victim", email="victim@example.com", nonce=nonce)
    assert _callback(client, state).status_code == 303
    authenticated = client.get("/api/v1/auth/me")
    assert authenticated.status_code == 200
    assert authenticated.json()["user"]["display_name"] == "Google Owner"

    with db_factory() as db:
        session = db.scalar(select(SessionRecord).where(SessionRecord.revoked_at.is_(None)))
        assert session
        identity = db.get(AuthIdentity, session.auth_identity_id)
        assert identity and identity.provider == "google"
        assert db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == identity.user_id,
                AuthIdentity.provider == "password",
            )
        ) is None
        assert db.scalar(select(func.count(PasswordCredential.auth_identity_id))) == 0
        tokens = list(
            db.scalars(
                select(OneTimeToken).where(
                    OneTimeToken.user_id == identity.user_id,
                    OneTimeToken.purpose == "verify_email",
                )
            )
        )
        assert tokens and all(token.consumed_at is not None for token in tokens)

    assert client.post("/api/v1/auth/verify-email", json={"token": old_token}).status_code == 400
    resend = client.post(
        "/api/v1/auth/verification/resend", json={"email": "victim@example.com"}
    )
    assert resend.status_code == 202
    assert resend.json()["development_token"] is None

    assert client.post("/api/v1/auth/logout", headers=auth_headers(client)).status_code == 204
    assert (
        client.post(
            "/api/v1/auth/login",
            json={
                "email": "victim@example.com",
                "password": "correct horse battery staple",
            },
        ).status_code
        == 401
    )


def test_verified_password_user_links_google_and_repeat_login_is_idempotent(
    client: TestClient, db_factory: sessionmaker[Session], monkeypatch
) -> None:
    password_auth = register(client, "both@example.com")
    user_id = password_auth["user"]["id"]
    _enable_google(client)
    first_state, first_nonce = _start(client, db_factory)
    _mock_google(monkeypatch, subject="google-both", email="both@example.com", nonce=first_nonce)
    assert _callback(client, first_state).status_code == 303
    second_state, second_nonce = _start(client, db_factory)
    _mock_google(monkeypatch, subject="google-both", email="both@example.com", nonce=second_nonce)
    assert _callback(client, second_state).status_code == 303
    assert client.get("/api/v1/auth/me").json()["user"]["id"] == user_id
    with db_factory() as db:
        assert (
            db.scalar(
                select(func.count(AuthIdentity.id)).where(
                    AuthIdentity.user_id == uuid.UUID(user_id),
                    AuthIdentity.provider == "google",
                )
            )
            == 1
        )
        password_identity = db.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == uuid.UUID(user_id),
                AuthIdentity.provider == "password",
            )
        )
        assert password_identity and password_identity.email_verified_at is not None
        assert db.get(PasswordCredential, password_identity.id)


def test_oauth_binding_replay_unverified_claims_and_subject_conflict_fail_closed(
    client: TestClient, db_factory: sessionmaker[Session], monkeypatch
) -> None:
    _enable_google(client)
    state, nonce = _start(client, db_factory)
    client.cookies.delete("rs_oauth_binding", path="/api/v1/auth/google/callback")
    _mock_google(monkeypatch, subject="missing-binding", email="one@example.com", nonce=nonce)
    assert _callback(client, state).status_code == 400

    state, nonce = _start(client, db_factory)
    _mock_google(
        monkeypatch,
        subject="unverified-google",
        email="one@example.com",
        nonce=nonce,
        verified=False,
    )
    assert _callback(client, state).status_code == 401
    assert _callback(client, state).status_code == 400

    first_state, first_nonce = _start(client, db_factory)
    _mock_google(
        monkeypatch, subject="subject-one", email="conflict@example.com", nonce=first_nonce
    )
    assert _callback(client, first_state).status_code == 303
    second_state, second_nonce = _start(client, db_factory)
    _mock_google(
        monkeypatch, subject="subject-two", email="conflict@example.com", nonce=second_nonce
    )
    assert _callback(client, second_state).status_code == 409


def test_disabled_google_user_cannot_reauthenticate(
    client: TestClient, db_factory: sessionmaker[Session], monkeypatch
) -> None:
    _enable_google(client)
    state, nonce = _start(client, db_factory)
    _mock_google(monkeypatch, subject="disabled-subject", email="disabled@example.com", nonce=nonce)
    assert _callback(client, state).status_code == 303
    with db_factory() as db:
        user = db.scalar(select(User).where(User.normalized_email == "disabled@example.com"))
        assert user
        user.status = UserStatus.DISABLED
        db.commit()
    client.cookies.clear()
    state, nonce = _start(client, db_factory)
    _mock_google(monkeypatch, subject="disabled-subject", email="disabled@example.com", nonce=nonce)
    assert _callback(client, state).status_code == 401


def test_google_provider_error_is_controlled_and_state_cannot_be_replayed(
    client: TestClient, db_factory: sessionmaker[Session], monkeypatch
) -> None:
    settings = _enable_google(client)
    state, _nonce = _start(client, db_factory)

    def provider_failure(*_args, **_kwargs):
        raise httpx.ConnectError("provider unavailable")

    monkeypatch.setattr("app.routes.auth.exchange_google_code", provider_failure)
    response = _callback(client, state)
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Google authentication could not be completed"
    assert "provider unavailable" not in response.text
    assert client.cookies.get(settings.oauth_binding_cookie_name) is None
    assert _callback(client, state).status_code == 400


def test_duplicate_google_linking_race_returns_controlled_conflict(
    client: TestClient, db_factory: sessionmaker[Session], monkeypatch
) -> None:
    _enable_google(client)
    state, nonce = _start(client, db_factory)
    _mock_google(monkeypatch, subject="racing-subject", email="race@example.com", nonce=nonce)
    original_commit = db_factory.class_.commit

    def commit_with_collision(session: Session) -> None:
        if any(
            isinstance(item, AuthIdentity) and item.provider == "google"
            for item in session.new
        ):
            raise IntegrityError("insert auth identity", {}, Exception("unique collision"))
        original_commit(session)

    monkeypatch.setattr(db_factory.class_, "commit", commit_with_collision)
    response = _callback(client, state)
    assert response.status_code == 409
    assert response.json()["error"]["message"] == (
        "Google identity linking conflicted; retry sign-in"
    )
    assert "unique collision" not in response.text
