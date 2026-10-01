import os
import threading
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from test_postgres_integrity import _seed_document, _version

from app.config import Settings, get_settings
from app.database import get_db
from app.knowledge.chunking import StructureChunker
from app.knowledge.extraction import Block, ExtractedDocument
from app.knowledge.ingestion import finalize
from app.knowledge.jobs import LostLease, claim, enqueue, fail, owned_job, renew, retry
from app.knowledge.models import ChunkEmbedding, DocumentChunk, IngestionJob, JobStatus
from app.knowledge.providers import FakeEmbeddingProvider
from app.main import create_app
from app.models import (
    Document,
    DocumentVersion,
    IngestionStatus,
    Organization,
    OrganizationMembership,
    User,
)
from app.policy import OrganizationContext
from app.storage import MemoryObjectStorage

pytestmark = [pytest.mark.postgres, pytest.mark.vector]


@pytest.fixture
def vector_factory() -> Generator[sessionmaker[Session], None, None]:
    if os.getenv("RUN_POSTGRES_TESTS") != "1":
        pytest.skip("requires a migrated PostgreSQL/pgvector test database")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True, hide_parameters=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield factory
    with factory() as db:
        # Synthetic test jobs must not interfere with the next global queue test.
        db.execute(update(IngestionJob).where(IngestionJob.status.in_([JobStatus.PENDING, JobStatus.RETRYABLE, JobStatus.RUNNING])).values(
            status=JobStatus.FAILED, lease_owner=None, lease_expires_at=None))
        db.commit()
    engine.dispose()


@pytest.fixture
def vector_client(vector_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEVELOPMENT_TOKEN_EXPOSURE", "true")
    get_settings.cache_clear()
    app = create_app()
    app.state.storage = MemoryObjectStorage()
    def session() -> Generator[Session, None, None]:
        with vector_factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app, base_url="http://localhost") as client:
        yield client
    get_settings.cache_clear()


def seeded_job(factory: sessionmaker[Session], *, attempts: int = 3) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    user_id, org_id, document_id = _seed_document(factory)
    with factory() as db:
        version = _version(organization_id=org_id, document_id=document_id, user_id=user_id, number=1)
        db.add(version)
        db.flush()
        document = db.get(Document, document_id)
        assert document
        document.current_version_id = version.id
        job = enqueue(db, version, Settings(ingestion_max_attempts=attempts))
        db.commit()
        return org_id, version.id, job.id


def test_vector_extension_indexes_and_composite_integrity(vector_factory: sessionmaker[Session]) -> None:
    org, version_id, _ = seeded_job(vector_factory)
    _, other_org, _ = _seed_document(vector_factory)
    chunk_id = uuid.uuid4()
    with vector_factory() as db:
        assert db.scalar(text("SELECT extversion FROM pg_extension WHERE extname='vector'"))
        indexes = db.scalars(text("SELECT indexname FROM pg_indexes WHERE tablename IN ('document_chunks','chunk_embeddings')")).all()
        assert {"ix_embedding_cosine", "ix_chunk_lexical"} <= set(indexes)
        db.add(DocumentChunk(id=chunk_id, organization_id=other_org, document_version_id=version_id,
                             ordinal=0, text="wrong tenant", token_count=2, source_locator={}, heading_path=[], content_sha256="0" * 64))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(DocumentChunk(id=chunk_id, organization_id=org, document_version_id=version_id,
                             ordinal=0, text="right tenant", token_count=2, source_locator={"kind": "text", "line_start": 1}, heading_path=[], content_sha256="0" * 64))
        db.commit()
        db.add(ChunkEmbedding(organization_id=other_org, document_chunk_id=chunk_id, provider="fake", model="fake-hash-v1", dimensions=1536, embedding=[1.0] * 1536))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(ChunkEmbedding(organization_id=org, document_chunk_id=chunk_id, provider="fake", model="fake-hash-v1", dimensions=3, embedding=[1.0] * 1536))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        with pytest.raises(DBAPIError):
            # Bypass the Python vector adapter to prove PostgreSQL's fixed-width type.
            db.execute(text("""INSERT INTO chunk_embeddings
                (id, organization_id, document_chunk_id, provider, model, dimensions, embedding, created_at)
                VALUES (:id, :org, :chunk, 'fake', 'fake-hash-v1', 1536, '[1,0,0]'::vector, now())"""),
                       {"id": uuid.uuid4(), "org": org, "chunk": chunk_id})
        db.rollback()
        assert db.scalar(text("SELECT '[1,0,0]'::vector <=> '[1,0,0]'::vector")) == 0


def test_skip_locked_single_owner_and_parallel_distinct_jobs(vector_factory: sessionmaker[Session]) -> None:
    _, _, job_id = seeded_job(vector_factory)
    barrier = threading.Barrier(2)
    results: list[object] = []
    failures: list[BaseException] = []
    def worker() -> None:
        try:
            barrier.wait(timeout=10)
            with vector_factory() as db:
                results.append(claim(db, Settings()))
        except BaseException as failure:
            failures.append(failure)
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not failures
    active = [job for job in results if job is not None]
    assert len(active) == 1 and active[0].id == job_id
    _, _, second_id = seeded_job(vector_factory)
    _, _, third_id = seeded_job(vector_factory)
    results.clear()
    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not failures and len(results) == 2 and all(results)
    assert {job.id for job in results} == {second_id, third_id}


def test_locked_pending_job_is_skipped_without_waiting(vector_factory: sessionmaker[Session]) -> None:
    _, _, first = seeded_job(vector_factory)
    with vector_factory() as holder:
        holder.scalar(select(IngestionJob).where(IngestionJob.id == first).with_for_update())
        _, _, second = seeded_job(vector_factory)
        with vector_factory() as claimer:
            claimer.execute(text("SET LOCAL lock_timeout = '500ms'"))
            selected = claim(claimer, Settings())
            assert selected and selected.id == second


def test_expired_lease_reclaim_fencing_renewal_and_atomic_idempotency(vector_factory: sessionmaker[Session]) -> None:
    _, version_id, job_id = seeded_job(vector_factory)
    settings = Settings()
    with vector_factory() as db:
        original = claim(db, settings)
        assert original
        assert renew(db, original, settings)
        db.execute(update(IngestionJob).where(IngestionJob.id == job_id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=10)))
        db.commit()
        with pytest.raises(LostLease):
            owned_job(db, original)
        db.rollback()
        replacement = claim(db, settings)
        assert replacement and replacement.lease_owner != original.lease_owner and replacement.attempt == 2
        assert not renew(db, original, settings)
    extracted = ExtractedDocument([Block("paragraph", "Rotate keys every 30 days.", [], {"kind": "text", "line_start": 1, "line_end": 1}, 0)], "test-v1")
    chunker = StructureChunker(400, 800)
    chunks = chunker.chunk(extracted)
    provider = FakeEmbeddingProvider()
    vectors = provider.embed_texts([chunk.text for chunk in chunks])
    with vector_factory() as db:
        with pytest.raises(LostLease):
            finalize(db, original, extracted, chunks, vectors, chunker.identity, provider, {})
        db.rollback()
        finalize(db, replacement, extracted, chunks, vectors, chunker.identity, provider, {})
        ids = list(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_version_id == version_id)))
        assert len(ids) == 1
        assert db.get(DocumentVersion, version_id).ingestion_status == IngestionStatus.READY
        with pytest.raises(LostLease):
            finalize(db, replacement, extracted, chunks, vectors, chunker.identity, provider, {})
        db.rollback()
        assert list(db.scalars(select(DocumentChunk.id).where(DocumentChunk.document_version_id == version_id))) == ids


def test_concurrent_authorized_retry_has_one_job(vector_factory: sessionmaker[Session]) -> None:
    _, version_id, job_id = seeded_job(vector_factory)
    with vector_factory() as db:
        claimed = claim(db, Settings())
        assert claimed
        fail(db, claimed, Settings(), code="invalid_source", retryable=False)
        actor = db.get(DocumentVersion, version_id).created_by_user_id
    barrier = threading.Barrier(2)
    errors = []
    def retrying() -> None:
        try:
            barrier.wait(timeout=10)
            with vector_factory() as db:
                version = db.get(DocumentVersion, version_id)
                assert version
                retry(db, version, Settings(), actor)
                db.commit()
        except BaseException as exc:
            errors.append(exc)
    threads = [threading.Thread(target=retrying) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors
    with vector_factory() as db:
        jobs = list(db.scalars(select(IngestionJob).where(IngestionJob.document_version_id == version_id)))
        assert len(jobs) == 1 and jobs[0].id == job_id and jobs[0].attempt_count == 0


@pytest.mark.parametrize("scenario", ["cross_tenant_and_user_team_grants_revocation", "current_ready_archive_and_version_provenance",
                                     "ask_authorized_context_unknown_citations_injection_and_no_evidence", "access_revoked_during_generation_invalidates_answer"])
def test_real_pgvector_security_scenarios(vector_client: TestClient, vector_factory: sessionmaker[Session], scenario: str) -> None:
    import test_knowledge_security as security_scenarios
    getattr(security_scenarios, f"test_{scenario}")(vector_client, vector_factory)


def test_stale_admin_context_cannot_bypass_live_role_or_revocation(vector_factory: sessionmaker[Session]) -> None:
    from app.knowledge.retrieval import KnowledgeRetriever
    user_id, org_id, document_id = _seed_document(vector_factory)
    with vector_factory() as db:
        user, organization = db.get(User, user_id), db.get(Organization, org_id)
        membership = db.scalar(select(OrganizationMembership).where(OrganizationMembership.organization_id == org_id, OrganizationMembership.user_id == user_id))
        context = OrganizationContext(user=user, organization=organization, membership=membership)
        with vector_factory() as revoker:
            revoker.execute(update(OrganizationMembership).where(OrganizationMembership.id == membership.id).values(status="REVOKED"))
            revoker.commit()
        retriever = KnowledgeRetriever(Settings(), FakeEmbeddingProvider())
        assert db.execute(retriever.eligible(context)).all() == []
        # Predicate itself also fails closed even for a cached owner context.
        from app.policy import document_access_predicate
        assert db.scalar(select(func.count(Document.id)).where(Document.id == document_id, document_access_predicate(context))) == 0
