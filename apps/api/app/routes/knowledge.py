import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.audit import record_audit
from app.config import Settings, get_settings
from app.dependencies import Csrf, Db, OrgContext
from app.knowledge.answers import EvidenceAnswerer
from app.knowledge.contracts import AskRequest, AskResponse, SearchRequest, SearchResponse
from app.knowledge.providers import ChatProvider, EmbeddingProvider, ProviderError
from app.knowledge.retrieval import KnowledgeRetriever

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_embedding(request: Request) -> EmbeddingProvider:
    return request.app.state.embedding_provider  # type: ignore[no-any-return]


def get_chat(request: Request) -> ChatProvider:
    return request.app.state.chat_provider  # type: ignore[no-any-return]


def enabled(settings: Settings) -> None:
    if not settings.ai_enabled:
        raise HTTPException(status_code=503, detail="Knowledge processing is disabled")


@router.post("/search", response_model=SearchResponse)
def search(payload: SearchRequest, db: Db, context: OrgContext, csrf: Csrf,
           settings: Settings = Depends(get_settings), embedding: EmbeddingProvider = Depends(get_embedding)) -> SearchResponse:
    enabled(settings)
    started = time.perf_counter()
    try:
        items = KnowledgeRetriever(settings, embedding).retrieve(db, context, payload.query, payload.top_k, payload.document_ids)
    except ProviderError:
        raise HTTPException(status_code=503, detail="Knowledge search is temporarily unavailable") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="Query exceeds supported token bounds") from None
    record_audit(db, action="knowledge.search_performed", resource_type="knowledge", resource_id=None,
                 organization_id=context.organization.id, actor_user_id=context.user.id,
                 metadata={"result_count": len(items), "model": embedding.model,
                           "duration_ms": round((time.perf_counter() - started) * 1000)})
    db.commit()
    return SearchResponse(items=items)


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, db: Db, context: OrgContext, csrf: Csrf,
        settings: Settings = Depends(get_settings), embedding: EmbeddingProvider = Depends(get_embedding),
        chat: ChatProvider = Depends(get_chat)) -> AskResponse:
    enabled(settings)
    started = time.perf_counter()
    answerer = EvidenceAnswerer(settings, KnowledgeRetriever(settings, embedding), chat)
    try:
        response = answerer.ask(db, context, payload)
    except ProviderError:
        raise HTTPException(status_code=503, detail="Answer generation is temporarily unavailable") from None
    except ValueError:
        raise HTTPException(status_code=422, detail="Question exceeds supported token bounds") from None
    record_audit(db, action="knowledge.answer_generated", resource_type="knowledge", resource_id=None,
                 organization_id=context.organization.id, actor_user_id=context.user.id,
                 metadata={"citation_count": len(response.citations), "model": chat.model,
                           "usage": answerer.last_usage,
                           "duration_ms": round((time.perf_counter() - started) * 1000)})
    db.commit()
    return response
