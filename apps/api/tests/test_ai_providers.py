import json

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.knowledge.providers import (
    OpenAIChatProvider,
    OpenAIClient,
    OpenAIEmbeddingProvider,
    ProviderError,
)


def provider_settings() -> Settings:
    return Settings(ai_enabled=True, embedding_provider="openai", embedding_model="text-embedding-3-small",
                    chat_provider="openai", chat_model="deployment-selected-model", openai_api_key="test-placeholder")


def test_openai_batched_embeddings_order_and_dimensions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["input"] == ["first", "second"] and data["dimensions"] == 1536
        assert request.url.scheme == "https"
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [2.0] * 1536}, {"index": 0, "embedding": [1.0] * 1536}]})
    settings = provider_settings()
    provider = OpenAIEmbeddingProvider(settings, OpenAIClient(settings, httpx.MockTransport(handler)))
    assert provider.embed_texts(["first", "second"])[0][0] == 1.0


@pytest.mark.parametrize(("status", "retryable"), [(429, True), (503, True), (400, False), (401, False)])
def test_provider_failure_categories_never_expose_payload(status: int, retryable: bool) -> None:
    settings = provider_settings()
    client = OpenAIClient(settings, httpx.MockTransport(lambda _: httpx.Response(status, json={"error": "secret document and provider key"})))
    with pytest.raises(ProviderError) as failure:
        client.post("embeddings", {})
    assert failure.value.retryable is retryable
    assert "secret" not in str(failure.value)


def test_chat_structured_contract_and_usage_no_provider_dtos() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.content)
        assert data["store"] is False and "tools" not in data
        assert data["max_completion_tokens"] == 100
        assert data["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"answer": "Evidence [S1]", "labels": ["S1"]})}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    settings = provider_settings()
    result = OpenAIChatProvider(settings, OpenAIClient(settings, httpx.MockTransport(handler))).generate("system", "context", 100)
    assert result.labels == ["S1"] and result.usage == {"prompt_tokens": 10, "completion_tokens": 5}


def test_missing_credentials_dimensions_bounds_and_hardened_fakes_rejected() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(ai_enabled=True, embedding_provider="openai", embedding_model="text-embedding-3-small")
    with pytest.raises(ValidationError):
        Settings(embedding_dimensions=3)
    with pytest.raises(ValidationError, match="CHUNK_TARGET"):
        Settings(chunk_target_tokens=200, chunk_max_tokens=100)
    with pytest.raises(ValidationError, match="production providers"):
        Settings(environment="production", ai_enabled=True)
