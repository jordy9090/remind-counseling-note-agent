"""Embedding providers for optional dense retrieval.

The app imports this module without requiring OpenAI credentials. Real OpenAI
embedding calls happen only when dense retrieval is explicitly enabled.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import settings


class EmbeddingError(RuntimeError):
    """Raised when an embedding cannot be generated."""


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input text."""


@dataclass
class EmbeddingCacheEntry:
    embedding: list[float]
    expires_at: float


_QUERY_EMBEDDING_CACHE: "OrderedDict[str, EmbeddingCacheEntry]" = OrderedDict()
_CACHE_HITS = 0
_CACHE_MISSES = 0


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
    """Embed a retrieval query with a bounded hash-keyed TTL cache."""
    if settings.disable_embedding_cache or settings.embedding_cache_ttl_seconds <= 0:
        return get_embedding_provider().embed([text])[0]

    global _CACHE_HITS, _CACHE_MISSES
    now = time.monotonic()
    cache_key = _query_cache_key(text)
    cached = _QUERY_EMBEDDING_CACHE.get(cache_key)
    if cached and cached.expires_at > now:
        _CACHE_HITS += 1
        _QUERY_EMBEDDING_CACHE.move_to_end(cache_key)
        return list(cached.embedding)
    if cached:
        _QUERY_EMBEDDING_CACHE.pop(cache_key, None)

    _CACHE_MISSES += 1
    embedding = get_embedding_provider().embed([text])[0]
    _QUERY_EMBEDDING_CACHE[cache_key] = EmbeddingCacheEntry(
        embedding=list(embedding),
        expires_at=now + settings.embedding_cache_ttl_seconds,
    )
    _trim_query_embedding_cache()
    return embedding


def clear_embedding_cache() -> None:
    global _CACHE_HITS, _CACHE_MISSES
    _QUERY_EMBEDDING_CACHE.clear()
    _CACHE_HITS = 0
    _CACHE_MISSES = 0


def embedding_cache_stats() -> dict[str, int]:
    return {"entries": len(_QUERY_EMBEDDING_CACHE), "hits": _CACHE_HITS, "misses": _CACHE_MISSES}


def content_hash(text: str, *, model: str | None = None) -> str:
    normalized = " ".join((text or "").split())
    payload = f"{model or settings.embedding_model}\n{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _query_cache_key(text: str) -> str:
    normalized = " ".join((text or "").split())
    query_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{settings.embedding_model}:{query_hash}"


def _trim_query_embedding_cache() -> None:
    max_entries = max(settings.embedding_cache_max_entries, 1)
    while len(_QUERY_EMBEDDING_CACHE) > max_entries:
        _QUERY_EMBEDDING_CACHE.popitem(last=False)


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
