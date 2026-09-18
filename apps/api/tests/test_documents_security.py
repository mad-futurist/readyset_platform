from conftest import auth_headers, create_org, register
from fastapi.testclient import TestClient


def upload(
    client: TestClient,
    organization_id: str,
    title: str = "Policy",
    visibility: str = "ORGANIZATION",
):
    return client.post(
        "/api/v1/documents",
        data={"title": title, "visibility": visibility, "domain": "security"},
        files={"file": ("policy.txt", b"classified policy", "text/plain")},
        headers=auth_headers(client, organization_id),
    )


def test_document_upload_download_version_and_audit(client: TestClient) -> None:
    register(client, "docs@example.com")
    org = create_org(client, "Docs")
    created = upload(client, org["id"])
    assert created.status_code == 201, created.text
    document = created.json()
    versions = client.get(
        f"/api/v1/documents/{document['id']}/versions",
        headers={"X-ReadySet-Organization": org["id"]},
    ).json()
    assert len(versions) == 1
    assert versions[0]["sha256"]
    downloaded = client.get(
        f"/api/v1/documents/{document['id']}/versions/{versions[0]['id']}/download",
        headers={"X-ReadySet-Organization": org["id"]},
    )
    assert downloaded.content == b"classified policy"

    second = client.post(
        f"/api/v1/documents/{document['id']}/versions",
        files={"file": ("policy-v2.txt", b"new content", "text/plain")},
        headers=auth_headers(client, org["id"]),
    )
    assert second.status_code == 201
    assert second.json()["version_number"] == 2
    events = client.get("/api/v1/audit-events", headers={"X-ReadySet-Organization": org["id"]})
    actions = {event["action"] for event in events.json()["items"]}
    assert {"document.created", "document.version_uploaded", "document.downloaded"} <= actions


def test_cross_tenant_document_and_version_ids_never_leak(client: TestClient) -> None:
    register(client, "orga@example.com")
    org_a = create_org(client, "Org A")
    document = upload(client, org_a["id"]).json()
    version = client.get(
        f"/api/v1/documents/{document['id']}/versions",
        headers={"X-ReadySet-Organization": org_a["id"]},
    ).json()[0]

    other_client = TestClient(client.app, base_url="http://localhost")
    register(other_client, "orgb@example.com")
    org_b = create_org(other_client, "Org B")
    headers = {"X-ReadySet-Organization": org_b["id"]}
    assert (
        other_client.get(f"/api/v1/documents/{document['id']}", headers=headers).status_code == 404
    )
    assert (
        other_client.get(
            f"/api/v1/documents/{document['id']}/versions/{version['id']}/download", headers=headers
        ).status_code
        == 404
    )
    assert (
        other_client.post(
            f"/api/v1/documents/{document['id']}/versions",
            files={"file": ("bad.txt", b"bad", "text/plain")},
            headers=auth_headers(other_client, org_b["id"]),
        ).status_code
        == 404
    )


def test_spoofed_organization_form_field_is_ignored_by_contract(client: TestClient) -> None:
    register(client, "no-spoof@example.com")
    org_a = create_org(client, "A")
    other_client = TestClient(client.app, base_url="http://localhost")
    register(other_client, "other-org@example.com")
    org_b = create_org(other_client, "B")
    response = client.post(
        "/api/v1/documents",
        data={"title": "Scoped", "organization_id": org_b["id"]},
        files={"file": ("doc.txt", b"content", "text/plain")},
        headers=auth_headers(client, org_a["id"]),
    )
    assert response.status_code == 201
    assert response.json()["organization_id"] == org_a["id"]


def test_restricted_document_requires_grant_and_team_grant_works(client: TestClient) -> None:
    register(client, "acl-owner@example.com")
    org = create_org(client, "ACL")
    restricted = upload(client, org["id"], visibility="RESTRICTED").json()
    invitation = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "acl-member@example.com", "role": "MEMBER"},
        headers=auth_headers(client, org["id"]),
    ).json()
    member_client = TestClient(client.app, base_url="http://localhost")
    member = register(member_client, "acl-member@example.com")
    member_client.post(
        "/api/v1/auth/verify-email", json={"token": member["development_verification_token"]}
    )
    member_client.post(
        "/api/v1/organizations/invitations/accept",
        json={"token": invitation["development_token"]},
        headers=auth_headers(member_client),
    )
    org_header = {"X-ReadySet-Organization": org["id"]}
    assert (
        member_client.get(f"/api/v1/documents/{restricted['id']}", headers=org_header).status_code
        == 404
    )

    grant = client.put(
        f"/api/v1/documents/{restricted['id']}/access",
        json={"user_ids": [member["user"]["id"]], "team_ids": []},
        headers=auth_headers(client, org["id"]),
    )
    assert grant.status_code == 200
    assert (
        member_client.get(f"/api/v1/documents/{restricted['id']}", headers=org_header).status_code
        == 200
    )

    client.put(
        f"/api/v1/documents/{restricted['id']}/access",
        json={"user_ids": [], "team_ids": []},
        headers=auth_headers(client, org["id"]),
    )
    assert (
        member_client.get(f"/api/v1/documents/{restricted['id']}", headers=org_header).status_code
        == 404
    )

    profile = client.post(
        "/api/v1/people",
        json={"display_name": "ACL Member", "user_id": member["user"]["id"]},
        headers=auth_headers(client, org["id"]),
    ).json()
    team = client.post(
        "/api/v1/teams",
        json={"name": "Security"},
        headers=auth_headers(client, org["id"]),
    ).json()
    client.post(
        f"/api/v1/teams/{team['id']}/members",
        json={"employee_profile_id": profile["id"]},
        headers=auth_headers(client, org["id"]),
    )
    client.put(
        f"/api/v1/documents/{restricted['id']}/access",
        json={"user_ids": [], "team_ids": [team["id"]]},
        headers=auth_headers(client, org["id"]),
    )
    assert (
        member_client.get(f"/api/v1/documents/{restricted['id']}", headers=org_header).status_code
        == 200
    )


def test_upload_validation(client: TestClient) -> None:
    register(client, "upload@example.com")
    org = create_org(client, "Upload")
    unsupported = client.post(
        "/api/v1/documents",
        data={"title": "Executable"},
        files={"file": ("bad.exe", b"MZ", "application/x-msdownload")},
        headers=auth_headers(client, org["id"]),
    )
    assert unsupported.status_code == 415
