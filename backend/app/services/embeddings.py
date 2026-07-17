"""Embedding providers for optional dense retrieval.

The app imports this module without requiring OpenAI credentials. Real OpenAI
embedding calls happen only when dense retrieval is explicitly enabled.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import settings


class EmbeddingError(RuntimeError):
    """Raised when an embedding cannot be generated."""


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input text."""


class OpenAIEmbeddingProvider:
    """Small REST client for OpenAI embeddings without adding dependencies."""

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 30) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        body = json.dumps({"model": self.model, "input": texts}).encode("utf-8")
        request = Request(
            "https://api.openai.com/v1/embeddings",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise EmbeddingError(f"OpenAI embeddings failed with HTTP {error.code}: {detail}") from error
        except URLError as error:
            raise EmbeddingError(f"OpenAI embeddings network error: {error}") from error

        rows = sorted(payload.get("data", []), key=lambda row: row.get("index", 0))
        embeddings = [row.get("embedding", []) for row in rows]
        for embedding in embeddings:
            if len(embedding) != settings.embedding_dimension:
                raise EmbeddingError(
                    f"Embedding dimension {len(embedding)} does not match "
                    f"EMBEDDING_DIMENSION={settings.embedding_dimension}."
                )
        return embeddings


class DeterministicEmbeddingProvider:
    """Test-only embedding provider used in stub mode."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [_hash_embedding(text, self.dimension) for text in texts]


def get_embedding_provider() -> EmbeddingProvider:
    if settings.openai_api_key and not settings.use_stub:
        return OpenAIEmbeddingProvider(settings.openai_api_key, settings.embedding_model)
    if settings.use_stub:
        return DeterministicEmbeddingProvider(settings.embedding_dimension)
    raise EmbeddingError("OPENAI_API_KEY is required for dense retrieval.")


def embed_query(text: str) -> list[float]:
    return get_embedding_provider().embed([text])[0]


def content_hash(text: str, *, model: str | None = None) -> str:
    normalized = " ".join((text or "").split())
    payload = f"{model or settings.embedding_model}\n{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_embedding(text: str, dimension: int) -> list[float]:
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    counter = 0
    while len(values) < dimension:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        values.extend((byte / 127.5) - 1.0 for byte in digest)
        counter += 1
    vector = values[:dimension]
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]

