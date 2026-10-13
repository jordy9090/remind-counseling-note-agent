"""Synthetic checks for private generation errors at both recomposition routes."""
from __future__ import annotations

import asyncio
import io
import os
import socket
from contextlib import ExitStack, redirect_stderr
from pathlib import Path
import sys
import tempfile
import traceback
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
from openai import BadRequestError
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.notes import recompose as vercel_recompose
from app.api.routes import notes
from app.api.security import require_preview_access
from app.core.config import settings
from app.main import app as main_app
from app.schemas.note import RecomposeNoteRequest, StructuredCaseData
from app.services.summary_quality import SummaryQualityError


PRIVATE_TEXT = "SYNTHETIC-PRIVATE-COUNSELING-DETAIL"
PUBLIC_FAILURE = "요약초안 재구성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
PAYLOAD = {
    "session_input": {
        "case_id": "synthetic-diagnostics-case",
        "session_number": 1,
        "counselor_memo": "발표 전 긴장을 다루었음.",
        "transcript_text": "내담자: 발표를 앞두면 긴장돼요.",
        "insight_lens": "none",
        "persist": False,
    },
    "visible_section_ids": ["session_content"],
}
HOSTS = ((main_app, notes.recompose_note_draft),
         (vercel_recompose.app, vercel_recompose.recompose_note_draft))


def provider_failure() -> BadRequestError:
    response = httpx.Response(400, request=httpx.Request("POST", "https://synthetic.invalid/responses"))
    return BadRequestError(PRIVATE_TEXT, response=response, body={"message": PRIVATE_TEXT})


def validation_failure() -> ValidationError:
    try:
        StructuredCaseData.model_validate({"session_content": [PRIVATE_TEXT]})
    except ValidationError as error:
        return error
    raise AssertionError("Synthetic model output must fail schema validation")


class RecompositionDiagnosticPrivacyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.cache_dir = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="remind-route-diagnostics-"))
        self.stack.enter_context(patch.dict(os.environ, {"RECOMPOSE_CACHE_DIR": self.cache_dir}))
        for name, value in {
            "use_stub": False, "openai_api_key": "synthetic-key",
            "enable_rag": False, "enable_dense_retrieval": False,
            "enable_raw_region_grounding": False, "enable_persistence": False,
        }.items():
            self.stack.enter_context(patch.object(settings, name, value))
        original_connect = socket.socket.connect

        def local_connect(sock, address):
            # Windows asyncio uses a loopback socket pair for its local wakeup pipe.
            if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
                return original_connect(sock, address)
            raise AssertionError("External network forbidden")

        self.stack.enter_context(patch("socket.socket.connect", local_connect))
        self.stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("Network forbidden")))
        for app, _ in HOSTS:
            original = app.dependency_overrides.copy()
            self.addCleanup(lambda app=app, original=original: setattr(app, "dependency_overrides", original))
            app.dependency_overrides[require_preview_access] = lambda: "synthetic-owner"

    def assert_private_failure(self, failure_factory) -> None:
        for app, _ in HOSTS:
            with self.subTest(host=app.title):
                failure = failure_factory()
                self.assertIn(PRIVATE_TEXT, str(failure), "The source exception must carry the synthetic canary")
                model = Mock()
                model.invoke.side_effect = failure
                stderr = io.StringIO()
                with patch("app.graph.nodes.get_structured_llm", return_value=model), redirect_stderr(stderr):
                    response = TestClient(app).post("/api/notes/recompose", json=PAYLOAD)
                model.invoke.assert_called_once()
                self.assertEqual(500, response.status_code)
                self.assertEqual({"detail": PUBLIC_FAILURE}, response.json())
                self.assertNotIn(PRIVATE_TEXT, stderr.getvalue())
                self.assertEqual([], list(Path(self.cache_dir).iterdir()), "Failed generations must not be cached")

    def test_provider_errors_do_not_expose_response_bodies(self) -> None:
        self.assert_private_failure(provider_failure)

    def test_validation_errors_do_not_expose_rejected_model_output(self) -> None:
        self.assert_private_failure(validation_failure)

    def test_formatted_http_exceptions_do_not_include_private_causes(self) -> None:
        request = RecomposeNoteRequest.model_validate(PAYLOAD)
        for app, handler in HOSTS:
            with self.subTest(host=app.title):
                model = Mock()
                model.invoke.side_effect = provider_failure()
                with patch("app.graph.nodes.get_structured_llm", return_value=model), redirect_stderr(io.StringIO()):
                    with self.assertRaises(HTTPException) as caught:
                        asyncio.run(handler(request, actor="synthetic-owner"))
                diagnostic = "".join(traceback.format_exception(caught.exception))
                self.assertNotIn(PRIVATE_TEXT, diagnostic)
                self.assertTrue(caught.exception.__suppress_context__)
                self.assertIsNone(caught.exception.__cause__)

    def test_quality_failures_keep_the_existing_public_502(self) -> None:
        for app, _ in HOSTS:
            with self.subTest(host=app.title):
                model = Mock()
                model.invoke.side_effect = SummaryQualityError()
                with patch("app.graph.nodes.get_structured_llm", return_value=model):
                    response = TestClient(app).post("/api/notes/recompose", json=PAYLOAD)
                self.assertEqual(502, response.status_code)
                self.assertEqual({"detail": str(SummaryQualityError())}, response.json())
                self.assertEqual([], list(Path(self.cache_dir).iterdir()))

    def test_successful_generation_and_cache_reuse_remain_available(self) -> None:
        for index, (app, _) in enumerate(HOSTS):
            cache_dir = str(Path(self.cache_dir) / str(index))
            with self.subTest(host=app.title), patch.dict(os.environ, {"RECOMPOSE_CACHE_DIR": cache_dir}), \
                    patch.object(settings, "use_stub", True):
                client = TestClient(app)
                first = client.post("/api/notes/recompose", json=PAYLOAD)
                self.assertEqual(200, first.status_code, first.text)
                self.assertFalse(first.json()["cache_hit"])
                self.assertEqual(["session_content"], first.json()["visible_section_ids"])
                with patch("app.services.recompose_cache.run_note_pipeline", side_effect=AssertionError("Cache miss")):
                    second = client.post("/api/notes/recompose", json=PAYLOAD)
                self.assertEqual(200, second.status_code, second.text)
                self.assertTrue(second.json()["cache_hit"])
                self.assertEqual(first.json()["result"], second.json()["result"])
                self.assertEqual(first.json()["cache_key"], second.json()["cache_key"])

    def test_unauthenticated_calls_still_stop_before_generation(self) -> None:
        for app, _ in HOSTS:
            with self.subTest(host=app.title), patch.object(settings, "enable_real_user_auth", True), \
                    patch("app.graph.nodes.get_structured_llm") as model:
                app.dependency_overrides.pop(require_preview_access)
                response = TestClient(app).post("/api/notes/recompose", json=PAYLOAD)
                self.assertEqual(401, response.status_code)
                model.assert_not_called()
                self.assertEqual([], list(Path(self.cache_dir).iterdir()))


if __name__ == "__main__":
    unittest.main()
