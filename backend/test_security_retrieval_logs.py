"""Offline evidence that retrieval audit rows omit the supplied query text.

This exercises the logging helper and its insertion payload, not hosted log
retention, database policies, other application logs, or provider telemetry.
"""
from __future__ import annotations

import hashlib
import io
import json
import socket
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.retrieval import _log_retrieval


class RetrievalLogPrivacyTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")))
        self.client = SimpleNamespace(retrieval_enabled=True, insert=Mock(return_value=[]))
        self.metadata = {
            "user_id": "synthetic-user-a",
            "counselor_id": "synthetic-counselor-a",
            "case_id": "synthetic-case-a",
            "retrieval_scope": "case_memory",
            "retrieval_method": "case_memory_dense",
            "source_refs": ["synthetic-note:one", "synthetic-note:two"],
            "embedding_latency_ms": 3,
            "rpc_latency_ms": 5,
            "total_latency_ms": 11,
        }

    def log(self, query):
        return _log_retrieval(storage_client=self.client, query_text=query, **self.metadata)

    def test_distinct_queries_insert_only_digest_and_expected_metadata(self):
        queries = ["SYNTHETIC-PRIVATE-QUERY-ONE-가", "SYNTHETIC-PRIVATE-QUERY-TWO-LONGER-나"]
        for query in queries:
            self.assertIsNone(self.log(query))
        self.assertEqual(self.client.insert.call_count, 2)

        rows = []
        for query, call in zip(queries, self.client.insert.call_args_list, strict=True):
            with self.subTest(query=query):
                self.assertEqual(call.args[0], "retrieval_logs")
                self.assertEqual(call.kwargs, {"return_representation": False})
                self.assertEqual(len(call.args[1]), 1)
                row = call.args[1][0]
                # An exact field set catches added raw-query or result-text fields.
                self.assertEqual(row, {
                    "user_id": self.metadata["user_id"],
                    "counselor_id": self.metadata["counselor_id"],
                    "case_id": self.metadata["case_id"],
                    "retrieval_scope": "case_memory",
                    "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                    "query_length": len(query),
                    "retrieval_method": "case_memory_dense",
                    "returned_source_refs": self.metadata["source_refs"],
                    "result_count": 2,
                    "latency_ms": 11,
                    "embedding_latency_ms": 3,
                    "rpc_latency_ms": 5,
                    "total_latency_ms": 11,
                })
                serialized = json.dumps(row, ensure_ascii=False)
                for raw_query in queries:
                    self.assertNotIn(raw_query, serialized)
                self.assertNotIn("SYNTHETIC-PRIVATE-QUERY", serialized)
                rows.append(row)
        self.assertNotEqual(rows[0]["query_hash"], rows[1]["query_hash"])
        self.assertNotEqual(rows[0]["query_length"], rows[1]["query_length"])

    def test_disabled_retrieval_does_not_insert_an_audit_row(self):
        self.client.retrieval_enabled = False
        self.assertIsNone(self.log("SYNTHETIC-PRIVATE-QUERY-DISABLED"))
        self.client.insert.assert_not_called()

    def test_audit_insert_failure_is_silent_and_non_fatal(self):
        # The current helper deliberately treats audit writes as best effort.
        self.client.insert.side_effect = RuntimeError("SYNTHETIC-PRIVATE-ERROR-BODY")
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr), self.assertNoLogs(level="DEBUG"):
            self.assertIsNone(self.log("SYNTHETIC-PRIVATE-QUERY-FAILED-INSERT"))
        self.client.insert.assert_called_once()
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
