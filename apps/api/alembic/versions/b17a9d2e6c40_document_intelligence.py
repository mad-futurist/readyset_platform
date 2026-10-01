"""Version-scoped document intelligence and fenced ingestion queue.

Revision ID: b17a9d2e6c40
Revises: f6f5b16f7d31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b17a9d2e6c40"
down_revision: str | None = "f6f5b16f7d31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Deployment role must have extension privileges or pre-provision vector.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("document_versions", sa.Column("ingestion_error_code", sa.String(64)))
    op.add_column("document_versions", sa.Column("ingestion_retryable", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("document_versions", "ingestion_retryable", server_default=None)
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "RUNNING", "RETRYABLE", "SUCCEEDED", "FAILED", name="jobstatus"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.Uuid()),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("last_error_message", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "document_version_id"], ["document_versions.organization_id", "document_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_version_id"),
        sa.CheckConstraint("attempt_count >= 0 AND max_attempts > 0 AND attempt_count <= max_attempts", name="ck_job_attempts"),
        sa.CheckConstraint("(status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_expires_at IS NULL)", name="ck_job_lease"),
    )
    op.create_index("ix_ingestion_jobs_organization_id", "ingestion_jobs", ["organization_id"])
    op.create_index("ix_job_claim", "ingestion_jobs", ["status", "available_at", "lease_expires_at"])
    # Existing M1 clean uploads are queued without touching source identity.
    op.execute("""INSERT INTO ingestion_jobs
        (id, organization_id, document_version_id, status, attempt_count, max_attempts, available_at, created_at, updated_at)
        SELECT gen_random_uuid(), organization_id, id, 'PENDING', 0, 3, now(), now(), now()
        FROM document_versions WHERE ingestion_status = 'UPLOADED'""")
    op.create_table(
        "extracted_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("extractor", sa.String(120), nullable=False),
        sa.Column("chunker", sa.String(255), nullable=False),
        sa.Column("artifact_type", sa.String(40), nullable=False),
        sa.Column("blocks", postgresql.JSONB(), nullable=False),
        sa.Column("processing_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "document_version_id"], ["document_versions.organization_id", "document_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_version_id"),
    )
    op.create_index("ix_extracted_artifacts_organization_id", "extracted_artifacts", ["organization_id"])
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("source_locator", postgresql.JSONB(), nullable=False),
        sa.Column("heading_path", postgresql.JSONB(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "document_version_id"], ["document_versions.organization_id", "document_versions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organization_id", "id"),
        sa.UniqueConstraint("document_version_id", "ordinal"),
        sa.CheckConstraint("ordinal >= 0 AND token_count > 0 AND length(text) > 0", name="ck_chunk_content"),
    )
    op.create_index("ix_chunk_version", "document_chunks", ["organization_id", "document_version_id"])
    # Functional lexical index is kept explicit in metadata for drift checks.
    op.execute("CREATE INDEX ix_chunk_lexical ON document_chunks USING gin (to_tsvector('simple'::regconfig, text))")
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("document_chunk_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "document_chunk_id"], ["document_chunks.organization_id", "document_chunks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("document_chunk_id", "provider", "model"),
        sa.CheckConstraint("dimensions = 1536", name="ck_embedding_dimensions"),
    )
    op.create_index("ix_embedding_org_model", "chunk_embeddings", ["organization_id", "provider", "model"])
    op.create_index("ix_embedding_cosine", "chunk_embeddings", ["embedding"], postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
    op.drop_table("document_chunks")
    op.drop_table("extracted_artifacts")
    op.drop_table("ingestion_jobs")
    sa.Enum(name="jobstatus").drop(op.get_bind(), checkfirst=True)
    op.drop_column("document_versions", "ingestion_retryable")
    op.drop_column("document_versions", "ingestion_error_code")
    # Do not remove a potentially shared extension.
