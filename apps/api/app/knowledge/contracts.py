import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Query cannot be blank")
        return value


class RetrievedEvidence(BaseModel):
    organization_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    version_number: int
    source_locator: dict[str, Any]
    excerpt: str
    score: float


class SearchResponse(BaseModel):
    items: list[RetrievedEvidence]


class AskRequest(SearchRequest):
    pass


class Citation(RetrievedEvidence):
    label: str


class AskResponse(BaseModel):
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool
