"""Synthetic live API/worker acceptance; requires explicit local fake AI settings."""
import argparse
import time
import uuid
from pathlib import Path

import requests

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", default="http://localhost:8000")
parser.add_argument("--fixtures", type=Path, default=Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ingestion")
args = parser.parse_args()
base = args.base_url.rstrip("/") + "/api/v1"
owner = requests.Session()
member = requests.Session()
suffix = uuid.uuid4().hex


def call(client: requests.Session, method: str, path: str, status: int = 200, **kwargs):  # type: ignore[no-untyped-def]
    headers = kwargs.pop("headers", {})
    headers["X-CSRF-Token"] = client.cookies.get("rs_csrf", "")
    response = client.request(method, base + path, headers=headers, timeout=30, **kwargs)
    assert response.status_code == status, (method, path, response.status_code)
    return response.json() if response.content else None


def register(client: requests.Session, email: str) -> dict:
    credentials = {"email": email, "password": "synthetic acceptance password"}
    registration = call(client, "POST", "/auth/register", 202, json={**credentials, "display_name": "Synthetic acceptance"})
    call(client, "POST", "/auth/verify-email", 204, json={"token": registration["development_verification_token"]})
    return call(client, "POST", "/auth/login", json=credentials)


def wait_version(document_id: str, version_id: str, expected: str = "READY") -> dict:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        versions = call(owner, "GET", f"/documents/{document_id}/versions")
        version = next(row for row in versions if row["id"] == version_id)
        if version["ingestion_status"] == expected:
            return version
        if expected == "READY" and version["ingestion_status"] == "FAILED":
            raise AssertionError(f"Safe ingestion failure: {version['ingestion_error_code']}")
        time.sleep(0.2)
    raise AssertionError("Worker did not reach the expected state")


register(owner, f"m2-owner-{suffix}@example.com")
org = call(owner, "POST", "/organizations", 201, json={"name": f"M2 acceptance {suffix}"})
owner.headers["X-ReadySet-Organization"] = org["id"]
with (args.fixtures / "policies.pdf").open("rb") as source:
    document = call(owner, "POST", "/documents", 201, data={"title": "Synthetic company policy"}, files={"file": ("policies.pdf", source, "application/pdf")})
wait_version(document["id"], document["current_version_id"])
answer = call(owner, "POST", "/knowledge/ask", json={"query": "Where is the support desk?"})
assert answer["citations"] and answer["citations"][0]["source_locator"]["page"] == 3
assert answer["citations"][0]["document_version_id"] == document["current_version_id"]
new = call(owner, "POST", f"/documents/{document['id']}/versions", 201, files={"file": ("updated.txt", b"The support desk has moved to Lyon.", "text/plain")})
initial_items = call(owner, "POST", "/knowledge/search", json={"query": "support desk", "document_ids": [document["id"]]})["items"]
# A fast worker may already have finished; old-version evidence is never allowed.
assert {row["document_version_id"] for row in initial_items} <= {new["id"]}
wait_version(document["id"], new["id"])
items = call(owner, "POST", "/knowledge/search", json={"query": "support desk", "document_ids": [document["id"]]})["items"]
assert items and {row["document_version_id"] for row in items} == {new["id"]}
restricted = call(owner, "POST", "/documents", 201, data={"title": "Synthetic restricted policy", "visibility": "RESTRICTED"}, files={"file": ("restricted.txt", b"Restricted unicorn policy.", "text/plain")})
wait_version(restricted["id"], restricted["current_version_id"])
email = f"m2-member-{suffix}@example.com"
invitation = call(owner, "POST", "/organizations/current/invitations", 201, json={"email": email, "role": "MEMBER"})
identity = register(member, email)
membership = call(member, "POST", "/organizations/invitations/accept", json={"token": invitation["development_token"]})
member.headers["X-ReadySet-Organization"] = org["id"]
payload = {"query": "unicorn", "document_ids": [restricted["id"]]}
assert call(member, "POST", "/knowledge/search", json=payload)["items"] == []
call(owner, "PUT", f"/documents/{restricted['id']}/access", json={"user_ids": [identity["user"]["id"]]})
assert call(member, "POST", "/knowledge/search", json=payload)["items"]
call(owner, "PUT", f"/documents/{restricted['id']}/access", json={"user_ids": []})
assert call(member, "POST", "/knowledge/search", json=payload)["items"] == []
call(owner, "DELETE", f"/organizations/current/members/{membership['id']}", 204)
call(member, "POST", "/knowledge/search", 404, json=payload)
with (args.fixtures / "malformed.pdf").open("rb") as source:
    broken = call(owner, "POST", "/documents", 201, data={"title": "Synthetic broken PDF"}, files={"file": ("malformed.pdf", source, "application/pdf")})
failed = wait_version(broken["id"], broken["current_version_id"], "FAILED")
assert failed["ingestion_error_code"] == "invalid_source"
retry_path = f"/documents/{broken['id']}/versions/{broken['current_version_id']}/ingestion/retry"
call(owner, "POST", retry_path)
wait_version(broken["id"], broken["current_version_id"], "FAILED")
print("M2 live acceptance passed: PDF page provenance, new-version isolation, restricted grants/revocation, safe failure/retry.")
