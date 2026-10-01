import uuid
from datetime import UTC, datetime, timedelta

import pytest
from conftest import auth_headers, create_org, register
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.knowledge.ingestion import IngestionProcessor
from app.knowledge.jobs import claim, fail, transition
from app.knowledge.models import (
    ChunkEmbedding,
    DocumentChunk,
    ExtractedArtifact,
    IngestionJob,
    JobStatus,
)
from app.knowledge.providers import FakeEmbeddingProvider, ProviderError
from app.models import DocumentVersion, IngestionStatus

pytestmark = pytest.mark.worker


def uploaded(client: TestClient, content: bytes = b"Rotate security keys every 30 days.") -> tuple[dict, dict]:
    register(client, f"worker-{uuid.uuid4().hex}@example.com")
    org = create_org(client, "Worker corpus")
    document = client.post("/api/v1/documents", data={"title": "Key policy"},
                           files={"file": ("keys.txt", content, "text/plain")}, headers=auth_headers(client, org["id"]))
    assert document.status_code == 201, document.text
    return org, document.json()


def test_upload_job_process_provenance_and_retry_idempotency(client: TestClient, db_factory: sessionmaker[Session]) -> None:
    org, document = uploaded(client)
    settings = Settings(ai_enabled=True)
    with db_factory() as db:
        jobs = list(db.scalars(select(IngestionJob)))
        assert len(jobs) == 1 and jobs[0].status == JobStatus.PENDING
        job = claim(db, settings)
        assert job
    processor = IngestionProcessor(db_factory, client.app.state.storage, FakeEmbeddingProvider(), settings)
    processor.process(job)
    with db_factory() as db:
        version = db.get(DocumentVersion, job.document_version_id)
        assert version and version.ingestion_status == IngestionStatus.READY
        chunk = db.scalar(select(DocumentChunk))
        assert chunk and chunk.document_version_id == version.id and chunk.organization_id == uuid.UUID(org["id"])
        assert chunk.source_locator["line_start"] == 1
        artifact = db.scalar(select(ExtractedArtifact))
        assert artifact and artifact.processing_metadata["embedding_calls"] == 1
    processor.process(job)  # redelivered expired/completed attempt cannot duplicate final state
    with db_factory() as db:
        assert db.scalar(select(func.count(DocumentChunk.id))) == 1
        assert db.scalar(select(func.count(ChunkEmbedding.id))) == 1
    assert client.get(f"/api/v1/documents/{document['id']}", headers=auth_headers(client, org["id"])).json()["current_ingestion_status"] == "READY"


def test_retry_backoff_safe_errors_and_authorized_retry(client: TestClient, db_factory: sessionmaker[Session]) -> None:
    org, document = uploaded(client)
    settings = Settings(ingestion_max_attempts=1)
    with db_factory() as db:
        job = claim(db, settings)
        assert job
        fail(db, job, settings, code="provider_unavailable", retryable=True)
        row = db.get(IngestionJob, job.id)
        assert row and row.status == JobStatus.RETRYABLE
        assert row.available_at > datetime.now(UTC).replace(tzinfo=None) if row.available_at.tzinfo is None else row.available_at > datetime.now(UTC)
        row.status = JobStatus.FAILED
        db.commit()
    path = f"/api/v1/documents/{document['id']}/versions/{job.document_version_id}/ingestion/retry"
    first = client.post(path, headers=auth_headers(client, org["id"]))
    second = client.post(path, headers=auth_headers(client, org["id"]))
    assert first.status_code == second.status_code == 200
    with db_factory() as db:
        row = db.get(IngestionJob, job.id)
        assert row and row.status == JobStatus.PENDING and row.attempt_count == 0
        assert db.scalar(select(func.count(IngestionJob.id))) == 1


def test_parser_failure_source_integrity_and_exhausted_crash(client: TestClient, db_factory: sessionmaker[Session]) -> None:
    _, _ = uploaded(client)
    settings = Settings()
    with db_factory() as db:
        job = claim(db, settings)
        assert job
    client.app.state.storage.objects[job.storage_key] = b"tampered bytes"
    IngestionProcessor(db_factory, client.app.state.storage, FakeEmbeddingProvider(), settings).process(job)
    with db_factory() as db:
        row = db.get(IngestionJob, job.id)
        assert row and row.status == JobStatus.FAILED and row.last_error_code == "source_integrity"
        assert db.scalar(select(func.count(DocumentChunk.id))) == 0
        row.status, row.attempt_count, row.lease_owner = JobStatus.RUNNING, row.max_attempts, uuid.uuid4()
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=60)
        db.get(DocumentVersion, job.document_version_id).ingestion_status = IngestionStatus.PROCESSING
        db.commit()
        assert claim(db, settings) is None
        db.refresh(row)
        assert row.status == JobStatus.FAILED and row.lease_owner is None


def test_nonsensical_state_transitions_are_rejected() -> None:
    version = DocumentVersion(ingestion_status=IngestionStatus.UPLOADED)
    with pytest.raises(ValueError):
        transition(version, IngestionStatus.READY)
    transition(version, IngestionStatus.PROCESSING)
    transition(version, IngestionStatus.READY)
    with pytest.raises(ValueError):
        transition(version, IngestionStatus.FAILED)


def test_provider_errors_do_not_log_private_payload(client: TestClient, db_factory: sessionmaker[Session], caplog: pytest.LogCaptureFixture) -> None:
    uploaded(client, b"confidential unicorn launch plan")
    class FailingProvider(FakeEmbeddingProvider):
        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            raise ProviderError(retryable=True)
    with db_factory() as db:
        job = claim(db, Settings())
        assert job
    IngestionProcessor(db_factory, client.app.state.storage, FailingProvider(), Settings()).process(job)
    assert "unicorn" not in caplog.text
    with db_factory() as db:
        row = db.get(IngestionJob, job.id)
        assert row and row.status == JobStatus.RETRYABLE and row.last_error_code == "provider_unavailable"
