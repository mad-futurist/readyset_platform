import io
import os
import uuid

import pytest
from botocore.exceptions import EndpointConnectionError
from conftest import auth_headers, create_org, register
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.storage import ObjectNotFound, S3ObjectStorage, StorageUnavailable


def _integration_storage() -> S3ObjectStorage:
    endpoint = os.getenv("S3_TEST_ENDPOINT_URL")
    if not endpoint:
        pytest.skip("S3_TEST_ENDPOINT_URL is not configured")
    settings = Settings(
        environment="test",
        storage_endpoint_url=endpoint,
        storage_access_key=os.environ["S3_TEST_ACCESS_KEY"],
        storage_secret_key=os.environ["S3_TEST_SECRET_KEY"],
        storage_bucket=os.environ["S3_TEST_BUCKET"],
        storage_auto_create_bucket=True,
    )
    storage = S3ObjectStorage(settings)
    storage.ensure_bucket()
    return storage


def test_storage_network_error_is_not_interpreted_as_missing_bucket() -> None:
    class UnavailableClient:
        def head_bucket(self, **kwargs):
            raise EndpointConnectionError(endpoint_url="https://objects.internal")

    storage = S3ObjectStorage.__new__(S3ObjectStorage)
    storage.bucket = "pre-created"
    storage.auto_create_bucket = False
    storage.client = UnavailableClient()
    with pytest.raises(StorageUnavailable):
        storage.ensure_bucket()


@pytest.mark.storage
def test_s3_compatible_object_lifecycle_and_missing_object() -> None:
    storage = _integration_storage()
    storage.check_access()
    key = f"integration/{uuid.uuid4()}"
    storage.put_stream(key, io.BytesIO(b"readyset-storage-test"), "text/plain")
    assert b"".join(storage.iter_bytes(key)) == b"readyset-storage-test"
    storage.delete(key)
    with pytest.raises(ObjectNotFound):
        b"".join(storage.iter_bytes(key))


@pytest.mark.storage
def test_s3_object_is_compensated_after_database_failure(
    client: TestClient,
    db_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    storage = _integration_storage()
    client.app.state.storage = storage
    register(client, "minio-compensation@example.com")
    organization = create_org(client, "MinIO compensation")
    prefix = f"organizations/{organization['id']}/"

    def fail_commit(session: Session) -> None:
        raise RuntimeError("database unavailable after object write")

    monkeypatch.setattr(db_factory.class_, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database unavailable"):
        client.post(
            "/api/v1/documents",
            data={"title": "Compensated"},
            files={"file": ("source.txt", b"bounded content", "text/plain")},
            headers=auth_headers(client, organization["id"]),
        )
    listed = storage.client.list_objects_v2(Bucket=storage.bucket, Prefix=prefix)
    assert listed.get("KeyCount", 0) == 0
