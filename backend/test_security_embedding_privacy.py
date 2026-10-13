"""Offline privacy checks for embedding failures and the query cache.

Only synthetic text and credentials are used. Provider transport is mocked;
these tests neither make paid inference calls nor verify provider retention.
Run: python -m unittest test_security_embedding_privacy
"""
from __future__ import annotations

import io
import json
import traceback
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

from app.core.config import settings
from app.services import embeddings


SYNTHETIC_TEXT = "SYNTHETIC-PRIVATE-EMBEDDING-CONTENT"


class EmbeddingFailurePrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = embeddings.OpenAIEmbeddingProvider("synthetic-key", "synthetic-model")

    def assert_private_failure(self, error: Exception, expected: str) -> None:
        with patch.object(embeddings, "urlopen", side_effect=error):
            try:
                self.provider.embed([SYNTHETIC_TEXT])
            except embeddings.EmbeddingError as caught:
                self.assertIn(expected, str(caught))
                self.assertNotIn(SYNTHETIC_TEXT, str(caught))
                self.assertNotIn(SYNTHETIC_TEXT, traceback.format_exc())
            else:
                self.fail("Provider failures must remain explicit errors")

    def test_http_failure_keeps_status_without_provider_body_or_reason(self) -> None:
        body = io.BytesIO(json.dumps({"error": SYNTHETIC_TEXT}).encode())
        error = HTTPError("https://synthetic.invalid", 429, SYNTHETIC_TEXT, {}, body)
        self.assert_private_failure(error, "HTTP 429")
        self.assertTrue(body.closed, "The upstream error response must be closed")

    def test_network_failure_hides_provider_reason_and_traceback_chain(self) -> None:
        self.assert_private_failure(URLError(SYNTHETIC_TEXT), "network")

    def test_timeout_hides_provider_reason(self) -> None:
        self.assert_private_failure(TimeoutError(SYNTHETIC_TEXT), "network")

    def test_success_keeps_embedding_order_and_dimensions(self) -> None:
        response = io.BytesIO(json.dumps({"data": [
            {"index": 1, "embedding": [0.0, 1.0]},
            {"index": 0, "embedding": [1.0, 0.0]},
        ]}).encode())
        with patch.object(embeddings, "urlopen", return_value=response) as transport, \
                patch.object(settings, "embedding_dimension", 2):
            result = self.provider.embed(["synthetic one", "synthetic two"])
        self.assertEqual(result, [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(json.loads(transport.call_args.args[0].data)["input"],
                         ["synthetic one", "synthetic two"])

    def test_empty_input_does_not_call_provider(self) -> None:
        with patch.object(embeddings, "urlopen") as transport:
            self.assertEqual(self.provider.embed([]), [])
        transport.assert_not_called()


class EmbeddingCachePrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        embeddings.clear_embedding_cache()
        self.addCleanup(embeddings.clear_embedding_cache)
        config = patch.multiple(settings, embedding_model="synthetic-model",
                                disable_embedding_cache=False,
                                embedding_cache_ttl_seconds=10,
                                embedding_cache_max_entries=2)
        config.start()
        self.addCleanup(config.stop)
        self.provider = Mock()
        self.provider.embed.return_value = [[0.25, 0.75]]
        provider_patch = patch.object(embeddings, "get_embedding_provider", return_value=self.provider)
        provider_patch.start()
        self.addCleanup(provider_patch.stop)

    def test_cache_stores_vectors_and_hashes_without_source_text(self) -> None:
        embeddings.embed_query(SYNTHETIC_TEXT)
        self.assertNotIn(SYNTHETIC_TEXT, repr(embeddings._QUERY_EMBEDDING_CACHE))
        self.assertEqual(embeddings.embedding_cache_stats(), {"entries": 1, "hits": 0, "misses": 1})

    def test_cache_hit_returns_an_independent_vector_copy(self) -> None:
        first = embeddings.embed_query(SYNTHETIC_TEXT)
        first[0] = -1
        cached = embeddings.embed_query(SYNTHETIC_TEXT)
        cached[0] = -2
        self.assertEqual(embeddings.embed_query(SYNTHETIC_TEXT), [0.25, 0.75])
        self.provider.embed.assert_called_once()

    def test_expired_entry_is_recomputed_and_entry_count_is_bounded(self) -> None:
        with patch.object(embeddings.time, "monotonic", return_value=1):
            embeddings.embed_query(SYNTHETIC_TEXT)
        with patch.object(embeddings.time, "monotonic", return_value=12):
            embeddings.embed_query(SYNTHETIC_TEXT)
            embeddings.embed_query("synthetic second")
            embeddings.embed_query("synthetic third")
        self.assertEqual(self.provider.embed.call_count, 4)
        self.assertEqual(embeddings.embedding_cache_stats()["entries"], 2)

    def test_failed_embedding_does_not_enter_cache(self) -> None:
        self.provider.embed.side_effect = embeddings.EmbeddingError("Synthetic failure")
        with self.assertRaises(embeddings.EmbeddingError):
            embeddings.embed_query(SYNTHETIC_TEXT)
        self.assertEqual(embeddings.embedding_cache_stats()["entries"], 0)

    def test_cache_disable_bypasses_storage(self) -> None:
        with patch.object(settings, "disable_embedding_cache", True):
            embeddings.embed_query(SYNTHETIC_TEXT)
            embeddings.embed_query(SYNTHETIC_TEXT)
        self.assertEqual(self.provider.embed.call_count, 2)
        self.assertEqual(embeddings.embedding_cache_stats()["entries"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
