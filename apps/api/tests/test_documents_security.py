import io
import uuid
import zipfile

import pytest
from conftest import auth_headers, create_org, register
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.file_security import FakeFileSecurityScanner, ScanResult
from app.storage import MemoryObjectStorage, StorageUnavailable


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

    fake_pdf = client.post(
        "/api/v1/documents",
        data={"title": "Fake PDF"},
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
        headers=auth_headers(client, org["id"]),
    )
    assert fake_pdf.status_code == 415

    valid_pdf = client.post(
        "/api/v1/documents",
        data={"title": "PDF"},
        files={"file": ("valid.pdf", b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n", "application/pdf")},
        headers=auth_headers(client, org["id"]),
    )
    assert valid_pdf.status_code == 201, valid_pdf.text

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as docx:
        docx.writestr("[Content_Types].xml", "<Types/>")
        docx.writestr("word/document.xml", "<document/>")
    valid_docx = client.post(
        "/api/v1/documents",
        data={"title": "DOCX"},
        files={
            "file": (
                "valid.docx",
                archive.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=auth_headers(client, org["id"]),
    )
    assert valid_docx.status_code == 201, valid_docx.text

    arbitrary_zip = io.BytesIO()
    with zipfile.ZipFile(arbitrary_zip, "w") as zipped:
        zipped.writestr("payload.exe", b"MZ")
    invalid_docx = client.post(
        "/api/v1/documents",
        data={"title": "Not DOCX"},
        files={
            "file": (
                "bad.docx",
                arbitrary_zip.getvalue(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=auth_headers(client, org["id"]),
    )
    assert invalid_docx.status_code == 415

    binary_text = client.post(
        "/api/v1/documents",
        data={"title": "Binary"},
        files={"file": ("bad.txt", b"hello\x00world", "text/plain")},
        headers=auth_headers(client, org["id"]),
    )
    assert binary_text.status_code == 415

    mismatch = client.post(
        "/api/v1/documents",
        data={"title": "Mismatch"},
        files={"file": ("wrong.txt", b"%PDF-1.7\n%%EOF", "text/plain")},
        headers=auth_headers(client, org["id"]),
    )
    assert mismatch.status_code == 415


def test_malware_scan_fails_closed_before_storage(client: TestClient) -> None:
    register(client, "scan@example.com")
    org = create_org(client, "Scanner")
    storage = client.app.state.storage
    assert isinstance(storage, MemoryObjectStorage)

    client.app.state.file_scanner = FakeFileSecurityScanner(ScanResult.CLEAN)
    clean = upload(client, org["id"], title="Clean")
    assert clean.status_code == 201
    assert len(storage.objects) == 1
    storage.objects.clear()

    client.app.state.file_scanner = FakeFileSecurityScanner(ScanResult.INFECTED)
    infected = upload(client, org["id"], title="Infected")
    assert infected.status_code == 422
    assert storage.objects == {}

    client.app.state.file_scanner = FakeFileSecurityScanner(ScanResult.UNAVAILABLE)
    unavailable = upload(client, org["id"], title="Unavailable")
    assert unavailable.status_code == 503
    assert storage.objects == {}


def test_database_failure_compensates_object_without_masking_original_error(
    client: TestClient,
    db_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    register(client, "compensation@example.com")
    org = create_org(client, "Compensation")
    storage = client.app.state.storage
    assert isinstance(storage, MemoryObjectStorage)
    def fail_document_commit(session: Session) -> None:
        raise RuntimeError("database commit failed")

    monkeypatch.setattr(db_factory.class_, "commit", fail_document_commit)
    with pytest.raises(RuntimeError, match="database commit failed"):
        upload(client, org["id"], title="Compensated")
    assert storage.objects == {}


def test_compensation_cleanup_failure_is_logged_and_original_error_survives(
    client: TestClient,
    db_factory: sessionmaker[Session],
    monkeypatch,
    caplog,
) -> None:
    class CleanupFailStorage(MemoryObjectStorage):
        def delete(self, key: str) -> None:
            raise ConnectionError("cleanup unavailable")

    register(client, "cleanup-failure@example.com")
    org = create_org(client, "Cleanup failure")
    client.app.state.storage = CleanupFailStorage()

    def fail_commit(session: Session) -> None:
        raise RuntimeError("authoritative database failure")

    monkeypatch.setattr(db_factory.class_, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="authoritative database failure"):
        upload(client, org["id"], title="Cleanup log")
    assert "Object compensation failed" in caplog.text


def test_unauthorized_request_never_reaches_storage(client: TestClient) -> None:
    class ObservedStorage(MemoryObjectStorage):
        reads = 0

        def open_stream(self, key: str):
            self.reads += 1
            return super().open_stream(key)

    storage = ObservedStorage()
    client.app.state.storage = storage
    response = client.get(
        f"/api/v1/documents/{uuid.uuid4()}/versions/{uuid.uuid4()}/download"
    )
    assert response.status_code == 401
    assert storage.reads == 0


def test_missing_download_object_returns_404_before_streaming(client: TestClient) -> None:
    register(client, "missing-object@example.com")
    organization = create_org(client, "Missing object")
    document = upload(client, organization["id"]).json()
    version = client.get(
        f"/api/v1/documents/{document['id']}/versions",
        headers={"X-ReadySet-Organization": organization["id"]},
    ).json()[0]
    storage = client.app.state.storage
    assert isinstance(storage, MemoryObjectStorage)
    storage.objects.clear()

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version['id']}/download",
        headers={"X-ReadySet-Organization": organization["id"]},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "object_not_found"


def test_storage_unavailable_download_returns_503_before_streaming(client: TestClient) -> None:
    class UnavailableStorage(MemoryObjectStorage):
        def open_stream(self, key: str):
            raise StorageUnavailable("sensitive internal endpoint detail")

    register(client, "unavailable-object@example.com")
    organization = create_org(client, "Unavailable object")
    document = upload(client, organization["id"]).json()
    version = client.get(
        f"/api/v1/documents/{document['id']}/versions",
        headers={"X-ReadySet-Organization": organization["id"]},
    ).json()[0]
    client.app.state.storage = UnavailableStorage()

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version['id']}/download",
        headers={"X-ReadySet-Organization": organization["id"]},
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "storage_unavailable"
    assert "sensitive" not in response.text


def test_upload_rate_limit_uses_user_organization_and_address_dimensions(
    client: TestClient,
) -> None:
    class RecordingLimiter:
        def __init__(self) -> None:
            self.keys: list[str] = []

        def check(self, key: str, *, limit: int, window_seconds: int) -> None:
            self.keys.append(key)

        def check_available(self) -> None:
            return None

    register(client, "upload-limit@example.com")
    org = create_org(client, "Upload limiter")
    limiter = RecordingLimiter()
    client.app.state.rate_limiter = limiter
    assert upload(client, org["id"]).status_code == 201
    assert any(key.startswith("upload:user:") for key in limiter.keys)
    assert f"upload:organization:{org['id']}" in limiter.keys
    assert any(key.startswith("upload:address:") for key in limiter.keys)

    class BlockingLimiter(RecordingLimiter):
        def check(self, key: str, *, limit: int, window_seconds: int) -> None:
            raise HTTPException(status_code=429, detail="Too many requests")

    client.app.state.rate_limiter = BlockingLimiter()
    assert upload(client, org["id"], title="Blocked").status_code == 429


def test_document_patch_rejects_null_non_nullable_fields(client: TestClient) -> None:
    register(client, "patch-doc@example.com")
    org = create_org(client, "Patch Documents")
    document = upload(client, org["id"]).json()
    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"title": None, "visibility": None},
        headers=auth_headers(client, org["id"]),
    )
    assert response.status_code == 422
