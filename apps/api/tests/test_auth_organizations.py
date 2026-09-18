from conftest import auth_headers, create_org, register
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models import AuditEvent, AuthIdentity, Organization, SessionRecord


def test_register_login_logout_and_password_is_not_returned(
    client: TestClient, db_factory: sessionmaker[Session]
) -> None:
    registered = register(client, "Owner@Example.com")
    assert registered["user"]["primary_email"] == "Owner@example.com"
    assert "password" not in str(registered)
    assert registered["development_verification_token"]
    assert client.app.state.email_sender.outbox[-1].recipient == "Owner@example.com"
    with db_factory() as db:
        session = db.scalar(select(SessionRecord).where(SessionRecord.revoked_at.is_(None)))
        assert session
        identity = db.get(AuthIdentity, session.auth_identity_id)
        assert identity and identity.provider == "password"

    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout", headers=auth_headers(client)).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    logged_in = client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "correct horse battery staple"},
    )
    assert logged_in.status_code == 200


def test_mutations_require_csrf(client: TestClient) -> None:
    register(client, "csrf@example.com")
    response = client.post("/api/v1/organizations", json={"name": "No CSRF"})
    assert response.status_code == 403


def test_verification_resend_rotates_token_and_delivers_email(client: TestClient) -> None:
    first = register(client, "verify-again@example.com", authenticate=False)
    resent = client.post(
        "/api/v1/auth/verification/resend", json={"email": "verify-again@example.com"}
    )
    assert resent.status_code == 202
    second_token = resent.json()["development_token"]
    assert second_token and second_token != first["development_verification_token"]
    assert client.app.state.email_sender.outbox[-1].recipient == "verify-again@example.com"
    assert (
        client.post(
            "/api/v1/auth/verify-email",
            json={"token": first["development_verification_token"]},
        ).status_code
        == 400
    )
    assert (
        client.post("/api/v1/auth/verify-email", json={"token": second_token}).status_code
        == 204
    )


def test_password_reset_revokes_sessions_and_all_reset_tokens(
    client: TestClient, db_factory: sessionmaker[Session]
) -> None:
    register(client, "reset@example.com")
    requested = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "reset@example.com"}
    )
    assert requested.status_code == 202
    assert client.app.state.email_sender.outbox[-1].recipient == "reset@example.com"
    first_token = requested.json()["development_token"]
    second_token = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "reset@example.com"}
    ).json()["development_token"]
    assert first_token and second_token
    assert (
        client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": second_token, "password": "a new correct horse battery staple"},
        ).status_code
        == 204
    )
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "reset@example.com", "password": "correct horse battery staple"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/v1/auth/login",
            json={
                "email": "reset@example.com",
                "password": "a new correct horse battery staple",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": first_token, "password": "another correct horse battery staple"},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": second_token, "password": "another correct horse battery staple"},
        ).status_code
        == 400
    )
    with db_factory() as db:
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "user.password_reset"))


def test_google_start_fails_closed_when_provider_is_unconfigured(client: TestClient) -> None:
    assert client.get("/api/v1/auth/google/start").status_code == 503


def test_multiple_organizations_require_explicit_context(client: TestClient) -> None:
    register(client, "multi@example.com")
    first = create_org(client, "First")
    second = create_org(client, "Second")
    assert first["id"] != second["id"]
    assert client.get("/api/v1/people").status_code == 400
    assert (
        client.get("/api/v1/people", headers={"X-ReadySet-Organization": first["id"]}).status_code
        == 200
    )


def test_organization_slug_insert_race_returns_conflict(
    client: TestClient, db_factory: sessionmaker[Session], monkeypatch
) -> None:
    register(client, "slug-race@example.com")
    original_flush = db_factory.class_.flush

    def flush_with_collision(session: Session, *args, **kwargs) -> None:
        if any(isinstance(item, Organization) for item in session.new):
            raise IntegrityError("insert organization", {}, Exception("unique collision"))
        original_flush(session, *args, **kwargs)

    monkeypatch.setattr(db_factory.class_, "flush", flush_with_collision)
    response = client.post(
        "/api/v1/organizations",
        json={"name": "Collision"},
        headers=auth_headers(client),
    )
    assert response.status_code == 409
    assert response.json()["error"]["message"] == "Organization slug is already in use"
    assert "unique collision" not in response.text


def test_invitation_requires_verified_email_and_revocation_is_immediate(client: TestClient) -> None:
    register(client, "owner@example.com", "Owner")
    org = create_org(client, "Acme")
    invitation = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "member@example.com", "role": "MEMBER"},
        headers=auth_headers(client, org["id"]),
    )
    assert invitation.status_code == 201
    assert client.app.state.email_sender.outbox[-1].recipient == "member@example.com"

    member_client = TestClient(client.app, base_url="http://localhost")
    member = register(member_client, "member@example.com", "Member", authenticate=False)
    assert (
        member_client.post(
            "/api/v1/auth/login",
            json={
                "email": "member@example.com",
                "password": "correct horse battery staple",
            },
        ).status_code
        == 401
    )
    rejected = member_client.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": invitation.json()["development_token"]},
        headers=auth_headers(member_client),
    )
    assert rejected.status_code == 401
    assert (
        member_client.post(
            "/api/v1/auth/verify-email",
            json={"token": member["development_verification_token"]},
        ).status_code
        == 204
    )
    assert (
        member_client.post(
            "/api/v1/auth/login",
            json={
                "email": "member@example.com",
                "password": "correct horse battery staple",
            },
        ).status_code
        == 200
    )
    accepted = member_client.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": invitation.json()["development_token"]},
        headers=auth_headers(member_client),
    )
    assert accepted.status_code == 200
    assert (
        member_client.post(
            "/api/v1/organizations/invitations/accept",
            json={"token": invitation.json()["development_token"]},
            headers=auth_headers(member_client),
        ).status_code
        == 400
    )
    membership_id = accepted.json()["id"]
    assert (
        member_client.get(
            "/api/v1/people", headers={"X-ReadySet-Organization": org["id"]}
        ).status_code
        == 200
    )

    revoked = client.delete(
        f"/api/v1/organizations/current/members/{membership_id}",
        headers=auth_headers(client, org["id"]),
    )
    assert revoked.status_code == 204
    assert (
        member_client.get(
            "/api/v1/people", headers={"X-ReadySet-Organization": org["id"]}
        ).status_code
        == 404
    )


def test_invitation_reissue_invalidates_old_token_and_can_be_revoked(
    client: TestClient,
) -> None:
    register(client, "invite-owner@example.com")
    org = create_org(client, "Invitation Lifecycle")
    first = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "invitee@example.com", "role": "MEMBER"},
        headers=auth_headers(client, org["id"]),
    ).json()
    second = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "invitee@example.com", "role": "MANAGER"},
        headers=auth_headers(client, org["id"]),
    ).json()
    assert second["id"] == first["id"]
    assert second["development_token"] != first["development_token"]

    invitee = TestClient(client.app, base_url="http://localhost")
    register(invitee, "invitee@example.com")
    assert (
        invitee.post(
            "/api/v1/organizations/invitations/accept",
            json={"token": first["development_token"]},
            headers=auth_headers(invitee),
        ).status_code
        == 400
    )
    assert (
        client.delete(
            f"/api/v1/organizations/current/invitations/{second['id']}",
            headers=auth_headers(client, org["id"]),
        ).status_code
        == 204
    )
    assert (
        invitee.post(
            "/api/v1/organizations/invitations/accept",
            json={"token": second["development_token"]},
            headers=auth_headers(invitee),
        ).status_code
        == 400
    )


def test_owner_can_transfer_ownership_atomically(client: TestClient) -> None:
    register(client, "first-owner@example.com")
    org = create_org(client, "Ownership")
    invitation = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "next-owner@example.com", "role": "ADMIN"},
        headers=auth_headers(client, org["id"]),
    ).json()
    next_owner = TestClient(client.app, base_url="http://localhost")
    register(next_owner, "next-owner@example.com")
    membership = next_owner.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": invitation["development_token"]},
        headers=auth_headers(next_owner),
    ).json()

    transferred = client.post(
        "/api/v1/organizations/current/ownership-transfer",
        json={"membership_id": membership["id"]},
        headers=auth_headers(client, org["id"]),
    )
    assert transferred.status_code == 200
    assert transferred.json()["role"] == "OWNER"
    members = client.get(
        "/api/v1/organizations/current/members",
        headers={"X-ReadySet-Organization": org["id"]},
    ).json()
    assert sorted(item["role"] for item in members) == ["ADMIN", "OWNER"]
    assert (
        client.post(
            "/api/v1/organizations/current/ownership-transfer",
            json={"membership_id": membership["id"]},
            headers=auth_headers(client, org["id"]),
        ).status_code
        == 403
    )
    assert (
        client.delete(
            f"/api/v1/organizations/current/members/{membership['id']}",
            headers=auth_headers(client, org["id"]),
        ).status_code
        == 409
    )
