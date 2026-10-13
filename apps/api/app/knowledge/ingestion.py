import hashlib
import json
import logging
import tempfile
import time
import uuid
from collections.abc import Callable

from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.knowledge.chunking import Chunk, StructureChunker
from app.knowledge.extraction import ExtractedDocument, ExtractionError, StructuredExtractor
from app.knowledge.jobs import (
    ClaimedJob,
    LostLease,
    _audit,
    _version,
    database_now,
    fail,
    owned_job,
    transition,
)
from app.knowledge.models import ChunkEmbedding, DocumentChunk, ExtractedArtifact, JobStatus
from app.knowledge.providers import EmbeddingProvider, ProviderError, validate_vectors
from app.models import IngestionStatus
from app.storage import ObjectNotFound, ObjectStorage, StorageError

logger = logging.getLogger("readyset.worker")


def finalize(db: Session, claimed: ClaimedJob, extracted: ExtractedDocument,
             chunks: list[Chunk], vectors: list[list[float]], chunker: str,
             provider: EmbeddingProvider, metadata: dict[str, object]) -> None:
    job = owned_job(db, claimed)
    version = _version(db, job)
    validate_vectors(vectors, len(chunks), provider.dimensions)
    if not chunks or any(not chunk.text.strip() or chunk.token_count <= 0 for chunk in chunks):
        raise ExtractionError("invalid_extraction")
    db.execute(delete(DocumentChunk).where(DocumentChunk.organization_id == claimed.organization_id,
                                         DocumentChunk.document_version_id == claimed.document_version_id))
    db.execute(delete(ExtractedArtifact).where(ExtractedArtifact.organization_id == claimed.organization_id,
                                             ExtractedArtifact.document_version_id == claimed.document_version_id))
    db.add(ExtractedArtifact(organization_id=claimed.organization_id, document_version_id=claimed.document_version_id,
                            extractor=extracted.extractor, chunker=chunker, blocks=extracted.serialize(), processing_metadata=metadata))
    chunk_ids = []
    for chunk in chunks:
        chunk_id = uuid.uuid5(claimed.document_version_id, f"{chunker}:{chunk.ordinal}:{chunk.content_sha256}")
        chunk_ids.append(chunk_id)
        db.add(DocumentChunk(id=chunk_id, organization_id=claimed.organization_id,
                             document_version_id=claimed.document_version_id, ordinal=chunk.ordinal,
                             text=chunk.text, token_count=chunk.token_count, source_locator=chunk.source_locator,
                             heading_path=chunk.heading_path, content_sha256=chunk.content_sha256))
    db.flush()
    for chunk_id, vector in zip(chunk_ids, vectors, strict=True):
        db.add(ChunkEmbedding(organization_id=claimed.organization_id, document_chunk_id=chunk_id,
                              provider=provider.provider, model=provider.model, dimensions=provider.dimensions, embedding=vector))
    # Check again after potentially slow persistence, while holding the job lock.
    owned_job(db, claimed)
    transition(version, IngestionStatus.READY)
    version.ingestion_error_code, version.ingestion_retryable = None, False
    job.status, job.completed_at = JobStatus.SUCCEEDED, database_now(db)
    job.lease_owner = job.lease_expires_at = None
    _audit(db, job, "succeeded", {"chunk_count": len(chunks), "model": provider.model})
    db.commit()


class IngestionProcessor:
    def __init__(self, factory: sessionmaker[Session], storage: ObjectStorage,
                 provider: EmbeddingProvider, settings: Settings) -> None:
        self.factory, self.storage, self.provider, self.settings = factory, storage, provider, settings

    def process(self, claimed: ClaimedJob, check_lease: Callable[[], None] = lambda: None) -> None:
        started = time.perf_counter()
        timings: dict[str, float] = {}
        stage = "download"
        stage_started = started

        def next_stage(name: str) -> None:
            nonlocal stage, stage_started
            check_lease()
            duration = round(time.perf_counter() - stage_started, 3)
            timings[stage] = duration
            logger.info(json.dumps({"job_id": str(claimed.id), "organization_id": str(claimed.organization_id),
                                    "document_version_id": str(claimed.document_version_id), "attempt": claimed.attempt,
                                    "stage": stage, "duration_seconds": duration}))
            stage, stage_started = name, time.perf_counter()

        try:
            with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as source:
                opened = self.storage.open_stream(claimed.storage_key)
                digest, size = hashlib.sha256(), 0
                try:
                    for data in opened.iter_bytes():
                        check_lease()
                        size += len(data)
                        if size > self.settings.max_upload_bytes or size > claimed.size_bytes:
                            raise ExtractionError("source_integrity")
                        digest.update(data)
                        source.write(data)
                finally:
                    opened.close()
                if size != claimed.size_bytes or digest.hexdigest() != claimed.sha256:
                    raise ExtractionError("source_integrity")
                source.seek(0)
                next_stage("extract")
                extracted = StructuredExtractor(self.settings).extract(source, claimed.mime_type)
            next_stage("chunk")
            chunker = StructureChunker(self.settings.chunk_target_tokens, self.settings.chunk_max_tokens, self.settings.embedding_tokenizer)
            chunks = chunker.chunk(extracted)
            if len(chunks) > self.settings.extraction_max_blocks:
                raise ExtractionError("extraction_limit")
            next_stage("embed")
            vectors: list[list[float]] = []
            calls = 0
            for offset in range(0, len(chunks), self.settings.embedding_batch_size):
                check_lease()
                batch = chunks[offset:offset + self.settings.embedding_batch_size]
                batch_vectors = self.provider.embed_texts([chunk.text for chunk in batch])
                validate_vectors(batch_vectors, len(batch), self.provider.dimensions)
                vectors.extend(batch_vectors)
                calls += 1
            next_stage("persist")
            metadata: dict[str, object] = {"block_count": len(extracted.blocks), "chunk_count": len(chunks),
                                          "input_tokens": sum(chunk.token_count for chunk in chunks), "embedding_calls": calls,
                                          "model": self.provider.model, "stage_seconds": timings,
                                          "processing_seconds": round(time.perf_counter() - started, 3)}
            with self.factory() as db:
                finalize(db, claimed, extracted, chunks, vectors, chunker.identity, self.provider, metadata)
            next_stage("succeeded")
            logger.info(json.dumps({"job_id": str(claimed.id), "stage": "complete", "status": "SUCCEEDED", **metadata}))
        except LostLease:
            logger.info(json.dumps({"job_id": str(claimed.id), "stage": stage, "status": "LEASE_LOST"}))
        except Exception as exc:
            if isinstance(exc, ExtractionError):
                code, retryable = exc.code, False
            elif isinstance(exc, ProviderError):
                code, retryable = exc.code, exc.retryable
            elif isinstance(exc, ObjectNotFound):
                code, retryable = "source_missing", False
            elif isinstance(exc, StorageError):
                code, retryable = "storage_unavailable", True
            else:
                code, retryable = "processing_unavailable", True
            try:
                with self.factory() as db:
                    fail(db, claimed, self.settings, code=code, retryable=retryable)
            except Exception:
                # DB outage/lease loss is recovered by expiry; no exception payload logging.
                code = "failure_record_unavailable"
            logger.warning(json.dumps({"job_id": str(claimed.id), "organization_id": str(claimed.organization_id),
                                       "document_version_id": str(claimed.document_version_id), "attempt": claimed.attempt,
                                       "stage": stage, "status": "FAILED", "error_code": code,
                                       "duration_seconds": round(time.perf_counter() - started, 3)}))
