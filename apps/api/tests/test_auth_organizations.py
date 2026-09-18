from conftest import auth_headers, create_org, register
from fastapi.testclient import TestClient


def test_register_login_logout_and_password_is_not_returned(client: TestClient) -> None:
    registered = register(client, "Owner@Example.com")
    assert registered["user"]["primary_email"] == "Owner@example.com"
    assert "password" not in str(registered)
    assert registered["development_verification_token"]

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


def test_password_reset_revokes_sessions_and_token_is_single_use(client: TestClient) -> None:
    register(client, "reset@example.com")
    requested = client.post(
        "/api/v1/auth/password-reset/request", json={"email": "reset@example.com"}
    )
    assert requested.status_code == 202
    token = requested.json()["development_token"]
    assert token
    assert (
        client.post(
            "/api/v1/auth/password-reset/confirm",
            json={"token": token, "password": "a new correct horse battery staple"},
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
            json={"token": token, "password": "another correct horse battery staple"},
        ).status_code
        == 400
    )


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


def test_invitation_requires_verified_email_and_revocation_is_immediate(client: TestClient) -> None:
    register(client, "owner@example.com", "Owner")
    org = create_org(client, "Acme")
    invitation = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "member@example.com", "role": "MEMBER"},
        headers=auth_headers(client, org["id"]),
    )
    assert invitation.status_code == 201

    member_client = TestClient(client.app, base_url="http://localhost")
    member = register(member_client, "member@example.com", "Member")
    rejected = member_client.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": invitation.json()["development_token"]},
        headers=auth_headers(member_client),
    )
    assert rejected.status_code == 403
    assert (
        member_client.post(
            "/api/v1/auth/verify-email",
            json={"token": member["development_verification_token"]},
        ).status_code
        == 204
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
