from conftest import auth_headers, create_org, register
from fastapi.testclient import TestClient


def test_people_are_tenant_scoped_and_frontend_cannot_spoof_user(client: TestClient) -> None:
    first_user = register(client, "a@example.com")
    org_a = create_org(client, "Org A")
    profile = client.post(
        "/api/v1/people",
        json={"display_name": "A Employee", "user_id": first_user["user"]["id"]},
        headers=auth_headers(client, org_a["id"]),
    )
    assert profile.status_code == 201

    other_client = TestClient(client.app, base_url="http://localhost")
    other_user = register(other_client, "b@example.com")
    org_b = create_org(other_client, "Org B")
    cross_tenant = client.post(
        "/api/v1/people",
        json={"display_name": "Spoof", "user_id": other_user["user"]["id"]},
        headers=auth_headers(client, org_a["id"]),
    )
    assert cross_tenant.status_code == 422
    assert (
        other_client.get(
            f"/api/v1/people/{profile.json()['id']}",
            headers={"X-ReadySet-Organization": org_b["id"]},
        ).status_code
        == 404
    )


def test_team_membership_and_cross_tenant_profile_rejected(client: TestClient) -> None:
    user = register(client, "team@example.com")
    org = create_org(client, "Teams")
    profile = client.post(
        "/api/v1/people",
        json={"display_name": "Taylor", "user_id": user["user"]["id"]},
        headers=auth_headers(client, org["id"]),
    ).json()
    team = client.post(
        "/api/v1/teams",
        json={"name": "Platform"},
        headers=auth_headers(client, org["id"]),
    ).json()
    assert (
        client.post(
            f"/api/v1/teams/{team['id']}/members",
            json={"employee_profile_id": profile["id"]},
            headers=auth_headers(client, org["id"]),
        ).status_code
        == 204
    )
    listed = client.get(
        f"/api/v1/teams/{team['id']}/members",
        headers={"X-ReadySet-Organization": org["id"]},
    )
    assert [member["id"] for member in listed.json()] == [profile["id"]]


def test_member_role_cannot_manage_people(client: TestClient) -> None:
    register(client, "role-owner@example.com")
    org = create_org(client, "Roles")
    invite = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "role-member@example.com", "role": "MEMBER"},
        headers=auth_headers(client, org["id"]),
    ).json()
    member_client = TestClient(client.app, base_url="http://localhost")
    register(member_client, "role-member@example.com")
    member_client.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": invite["development_token"]},
        headers=auth_headers(member_client),
    )
    denied = member_client.post(
        "/api/v1/people",
        json={"display_name": "Not allowed"},
        headers=auth_headers(member_client, org["id"]),
    )
    assert denied.status_code == 403


def test_profile_patch_rejects_null_non_nullable_fields(client: TestClient) -> None:
    register(client, "patch-person@example.com")
    org = create_org(client, "Patch People")
    profile = client.post(
        "/api/v1/people",
        json={"display_name": "Pat"},
        headers=auth_headers(client, org["id"]),
    ).json()
    response = client.patch(
        f"/api/v1/people/{profile['id']}",
        json={"display_name": None},
        headers=auth_headers(client, org["id"]),
    )
    assert response.status_code == 422
