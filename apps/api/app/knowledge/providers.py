import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.config import AIProvider, Settings


class ProviderError(RuntimeError):
    def __init__(self, *, retryable: bool, code: str = "provider_unavailable") -> None:
        self.retryable, self.code = retryable, code
        super().__init__("AI service is temporarily unavailable." if retryable else "AI service could not process this request.")


class EmbeddingProvider(Protocol):
    provider: str
    model: str
    dimensions: int

    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ChatResult:
    answer: str
    labels: list[str]
    usage: dict[str, int] = field(default_factory=dict)


class ChatProvider(Protocol):
    model: str

    def generate(self, system: str, context: str, max_tokens: int) -> ChatResult: ...


class FakeEmbeddingProvider:
    provider = "fake"

    def __init__(self, model: str = "fake-hash-v1", dimensions: int = 1536) -> None:
        self.model, self.dimensions = model, dimensions

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        result = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for word in re.findall(r"\w+", text.casefold()):
                index = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8]) % self.dimensions
                vector[index] += 1.0
            norm = math.sqrt(sum(value * value for value in vector))
            if not norm:
                vector[0] = norm = 1.0
            result.append([value / norm for value in vector])
        return result


class FakeChatProvider:
    def __init__(self, model: str = "fake-evidence-v1") -> None:
        self.model = model

    def generate(self, system: str, context: str, max_tokens: int) -> ChatResult:
        import json

        data = json.loads(context)
        evidence = data["evidence"][0]
        return ChatResult(f"Local preview: {evidence['text']} [S1]", ["S1"])


class _AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(max_length=24000)
    labels: list[str] = Field(max_length=20)


class OpenAIClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings, self.transport = settings, transport

    def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        key = self.settings.openai_api_key
        if not key:
            raise ProviderError(retryable=False, code="provider_configuration")
        try:
            with httpx.Client(timeout=self.settings.ai_provider_timeout_seconds, transport=self.transport) as client:
                response = client.post(f"https://api.openai.com/v1/{path}",
                                       headers={"Authorization": f"Bearer {key.get_secret_value()}"}, json=payload)
            if response.status_code >= 400:
                retryable = response.status_code in {408, 409, 429} or response.status_code >= 500
                raise ProviderError(retryable=retryable, code="provider_unavailable" if retryable else "provider_rejected")
            result: object = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ProviderError:
            raise
        except httpx.TransportError:
            raise ProviderError(retryable=True) from None
        except (ValueError, TypeError):
            raise ProviderError(retryable=False, code="invalid_provider_response") from None


def validate_vectors(vectors: list[list[float]], count: int, dimensions: int) -> None:
    if len(vectors) != count or any(
        len(vector) != dimensions or any(not math.isfinite(v) for v in vector)
        or not any(v != 0 for v in vector) for vector in vectors
    ):
        raise ProviderError(retryable=False, code="invalid_embedding")


class OpenAIEmbeddingProvider:
    provider = "openai"

    def __init__(self, settings: Settings, client: OpenAIClient | None = None) -> None:
        self.model, self.dimensions = settings.embedding_model, settings.embedding_dimensions
        self.client = client or OpenAIClient(settings)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        data = self.client.post("embeddings", {"model": self.model, "input": texts, "dimensions": self.dimensions, "encoding_format": "float"})
        try:
            rows = sorted(data["data"], key=lambda item: item["index"])
            if [row["index"] for row in rows] != list(range(len(texts))):
                raise ValueError()
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
            validate_vectors(vectors, len(texts), self.dimensions)
            return vectors
        except (KeyError, TypeError, ValueError):
            raise ProviderError(retryable=False, code="invalid_embedding") from None


class OpenAIChatProvider:
    def __init__(self, settings: Settings, client: OpenAIClient | None = None) -> None:
        self.model = settings.chat_model
        self.client = client or OpenAIClient(settings)

    def generate(self, system: str, context: str, max_tokens: int) -> ChatResult:
        data = self.client.post("chat/completions", {
            "model": self.model, "store": False, "max_completion_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": context}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "evidence_answer", "strict": True, "schema": {
                "type": "object", "properties": {"answer": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}}},
                "required": ["answer", "labels"], "additionalProperties": False}}},
        })
        try:
            choice = data["choices"][0]
            if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
                raise ValueError()
            answer = _AnswerPayload.model_validate_json(choice["message"]["content"])
            usage = {key: int(value) for key, value in data.get("usage", {}).items()
                     if key in {"prompt_tokens", "completion_tokens"} and isinstance(value, int)}
            return ChatResult(answer.answer, answer.labels, usage)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError):
            raise ProviderError(retryable=False, code="invalid_provider_response") from None


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == AIProvider.OPENAI:
        return OpenAIEmbeddingProvider(settings)
    return FakeEmbeddingProvider(settings.embedding_model, settings.embedding_dimensions)


def create_chat_provider(settings: Settings) -> ChatProvider:
    if settings.chat_provider == AIProvider.OPENAI:
        return OpenAIChatProvider(settings)
    return FakeChatProvider(settings.chat_model)
