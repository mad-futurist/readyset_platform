import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.knowledge.chunking import TokenCounter
from app.knowledge.contracts import RetrievedEvidence
from app.knowledge.lexical import significant_query
from app.knowledge.models import ChunkEmbedding, DocumentChunk
from app.knowledge.providers import EmbeddingProvider, validate_vectors
from app.models import Document, DocumentStatus, DocumentVersion, IngestionStatus
from app.policy import OrganizationContext, document_access_predicate


class KnowledgeRetriever:
    def __init__(self, settings: Settings, embedding: EmbeddingProvider) -> None:
        self.settings, self.embedding = settings, embedding

    def eligible(self, context: OrganizationContext):  # type: ignore[no-untyped-def]
        return (select(
            DocumentChunk.id.label("chunk_id"), DocumentChunk.text.label("excerpt"),
            DocumentChunk.source_locator, Document.id.label("document_id"), Document.title,
            DocumentVersion.id.label("document_version_id"), DocumentVersion.version_number,
        ).select_from(DocumentChunk).join(DocumentVersion,
            (DocumentVersion.id == DocumentChunk.document_version_id) &
            (DocumentVersion.organization_id == DocumentChunk.organization_id)
        ).join(Document,
            (Document.id == DocumentVersion.document_id) &
            (Document.organization_id == DocumentVersion.organization_id)
        ).where(
            DocumentChunk.organization_id == context.organization.id,
            document_access_predicate(context), Document.status == DocumentStatus.ACTIVE,
            Document.current_version_id == DocumentVersion.id,
            DocumentVersion.ingestion_status == IngestionStatus.READY,
        ))

    def retrieve(self, db: Session, context: OrganizationContext, query: str, top_k: int | None = None,
                 document_ids: list[uuid.UUID] | None = None) -> list[RetrievedEvidence]:
        limit = min(top_k or self.settings.retrieval_top_k, self.settings.retrieval_top_k)
        if not 1 <= limit <= 20:
            raise ValueError("Invalid result bound")
        if TokenCounter(self.settings.embedding_tokenizer).count(query) > 8000:
            raise ValueError("Query exceeds embedding token limit")
        eligible = self.eligible(context)
        if document_ids is not None:
            eligible = eligible.where(Document.id.in_(document_ids))
        if db.get_bind().dialect.name != "postgresql":
            # Fast transport/policy tests only. Production worker/retrieval uses PostgreSQL.
            words = query.split()
            eligible = eligible.where(DocumentChunk.text.ilike(f"%{words[0]}%"))
            rows = db.execute(eligible.order_by(DocumentChunk.id).limit(limit)).mappings().all()
            return [self._evidence(context, dict(row), 1 / (61 + index)) for index, row in enumerate(rows)]
        vector = self.embedding.embed_texts([query])
        validate_vectors(vector, 1, self.embedding.dimensions)
        # The MATERIALIZED security boundary contains only current authorized evidence.
        # Distance/ranking is applied AFTER this boundary, never to global candidates.
        authorized = eligible.add_columns(ChunkEmbedding.embedding).join(ChunkEmbedding,
            (ChunkEmbedding.document_chunk_id == DocumentChunk.id) &
            (ChunkEmbedding.organization_id == DocumentChunk.organization_id)
        ).where(ChunkEmbedding.provider == self.embedding.provider,
                ChunkEmbedding.model == self.embedding.model,
                ChunkEmbedding.dimensions == self.embedding.dimensions).cte("authorized").prefix_with("MATERIALIZED")
        distance = authorized.c.embedding.cosine_distance(vector[0])
        columns = [column for column in authorized.c if column.key != "embedding"]
        semantic = db.execute(select(*columns).order_by(distance, authorized.c.chunk_id).limit(limit * 3)).mappings().all()
        lexical_vector = func.to_tsvector("english", authorized.c.excerpt)
        lexical_query = func.websearch_to_tsquery("english", significant_query(query))
        lexical = db.execute(select(*columns).where(lexical_vector.op("@@")(lexical_query)).order_by(
            func.ts_rank_cd(lexical_vector, lexical_query, 32).desc(), authorized.c.chunk_id
        ).limit(limit * 3)).mappings().all()
        scores: dict[uuid.UUID, float] = {}
        evidence: dict[uuid.UUID, dict[str, Any]] = {}
        for candidates in (semantic, lexical):
            for rank, row in enumerate(candidates, 1):
                chunk_id = row["chunk_id"]
                scores[chunk_id] = scores.get(chunk_id, 0) + 1 / (60 + rank)
                evidence[chunk_id] = dict(row)
        ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], str(chunk_id)))[:limit]
        items = [self._evidence(context, evidence[chunk_id], scores[chunk_id]) for chunk_id in ids]
        return items if self.still_authorized(db, context, items) else []

    @staticmethod
    def _evidence(context: OrganizationContext, row: dict[str, Any], score: float) -> RetrievedEvidence:
        return RetrievedEvidence(organization_id=context.organization.id, document_id=row["document_id"],
                                 document_version_id=row["document_version_id"], chunk_id=row["chunk_id"],
                                 title=row["title"], version_number=row["version_number"],
                                 source_locator=row["source_locator"], excerpt=row["excerpt"], score=score)

    def still_authorized(self, db: Session, context: OrganizationContext, items: list[RetrievedEvidence]) -> bool:
        ids = {item.chunk_id for item in items}
        if not ids:
            return True
        rows = db.execute(self.eligible(context).where(DocumentChunk.id.in_(ids))).mappings().all()
        return {row["chunk_id"] for row in rows} == ids
