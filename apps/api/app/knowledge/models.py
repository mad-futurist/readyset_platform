import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    literal_column,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import JSON_DOCUMENT, utcnow


class JobStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYABLE = "RETRYABLE"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "document_version_id"],
            ["document_versions.organization_id", "document_versions.id"], ondelete="CASCADE",
        ),
        UniqueConstraint("document_version_id"),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts", name="ck_job_attempts"),
        CheckConstraint("(status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_expires_at IS NULL)", name="ck_job_lease"),
        Index("ix_job_claim", "status", "available_at", "lease_expires_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_message: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExtractedArtifact(Base):
    __tablename__ = "extracted_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(["organization_id", "document_version_id"], ["document_versions.organization_id", "document_versions.id"], ondelete="CASCADE"),
        UniqueConstraint("document_version_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    extractor: Mapped[str] = mapped_column(String(120))
    chunker: Mapped[str] = mapped_column(String(255))
    artifact_type: Mapped[str] = mapped_column(String(40), default="normalized_blocks")
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT)
    processing_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(["organization_id", "document_version_id"], ["document_versions.organization_id", "document_versions.id"], ondelete="CASCADE"),
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint("document_version_id", "ordinal"),
        CheckConstraint("ordinal >= 0 AND token_count > 0 AND length(text) > 0", name="ck_chunk_content"),
        Index("ix_chunk_version", "organization_id", "document_version_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    source_locator: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT)
    heading_path: Mapped[list[str]] = mapped_column(JSON_DOCUMENT)
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_chunk_lexical", func.to_tsvector(literal_column("'simple'::regconfig"), DocumentChunk.text),
      postgresql_using="gin", _table=DocumentChunk.__table__).ddl_if(dialect="postgresql")  # type: ignore[arg-type]


class ChunkEmbedding(Base):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        ForeignKeyConstraint(["organization_id", "document_chunk_id"], ["document_chunks.organization_id", "document_chunks.id"], ondelete="CASCADE"),
        UniqueConstraint("document_chunk_id", "provider", "model"),
        CheckConstraint("dimensions = 1536", name="ck_embedding_dimensions"),
        Index("ix_embedding_org_model", "organization_id", "provider", "model"),
        Index("ix_embedding_cosine", "embedding", postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}).ddl_if(dialect="postgresql"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    document_chunk_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(1536).with_variant(JSON(), "sqlite"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
