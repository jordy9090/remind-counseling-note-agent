"""Synthetic regression coverage for failed summary generation boundaries."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.notes.generate import app as generate_app
from api.notes.recompose import app as recompose_app
from app.api.security import require_preview_access
from app.core.config import settings
from app.main import app as main_app
from app.graph.graph import run_note_pipeline
from app.schemas.note import RecomposeNoteRequest, SessionInput
from app.services.recompose_cache import build_recompose_cache_key
from app.services.summary_quality import SummaryQualityError


INPUT = {
    "case_id": "SYNTHETIC-SUMMARY-FAILURE",
    "session_number": 1,
    "session_date": "2026-10-02",
    "counselor_name": "합성 상담사",
    "counselor_memo": "발표 전 긴장을 다루었음.",
    "transcript_text": "내담자: 발표를 앞두면 긴장돼요.",
    "persist": True,
}


class SummaryGenerationRouteTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(settings, "use_stub", False))
        for app in (generate_app, recompose_app, main_app):
            original = app.dependency_overrides.copy()
            self.addCleanup(lambda app=app, original=original: setattr(app, "dependency_overrides", original))
            app.dependency_overrides[require_preview_access] = lambda: "synthetic-owner"

    def test_generation_failures_never_retry_as_stub_or_persist(self):
        for app, path in ((generate_app, "/api/notes/generate"), (main_app, "/api/notes/generate")):
            for failure in (SummaryQualityError(), RuntimeError("PRIVATE_PROVIDER_DETAIL")):
                with self.subTest(app=app.title, failure=type(failure).__name__), patch(
                    "app.api.routes.notes.run_note_pipeline", side_effect=failure,
                ) as pipeline, patch("app.api.routes.notes.persist_generated_note") as persist:
                    response = TestClient(app).post(path, json=INPUT)
                    self.assertEqual(502, response.status_code)
                    self.assertNotIn("PRIVATE_PROVIDER_DETAIL", response.text)
                    self.assertNotIn("session_summary_draft", response.json())
                    pipeline.assert_called_once()
                    persist.assert_not_called()
                    self.assertFalse(settings.use_stub)

    def test_recomposition_reports_quality_failure_on_both_hosts(self):
        payload = {"session_input": INPUT, "visible_section_ids": ["session_content"]}
        for app, target in (
            (recompose_app, "api.notes.recompose.recompose_note_with_cache"),
            (main_app, "app.api.routes.notes.recompose_note_with_cache"),
        ):
            with self.subTest(app=app.title), patch(target, side_effect=SummaryQualityError()) as generate:
                response = TestClient(app).post("/api/notes/recompose", json=payload)
                self.assertEqual(502, response.status_code)
                generate.assert_called_once()
                self.assertFalse(settings.use_stub)

    def test_missing_model_key_cannot_silently_generate_a_sample(self):
        with patch.object(settings, "openai_api_key", None), patch("app.graph.graph.note_graph.invoke") as graph:
            with self.assertRaises(RuntimeError):
                run_note_pipeline(SessionInput(**INPUT), actor="synthetic-owner")
            graph.assert_not_called()

    def test_recomposition_cache_separates_demo_and_model_configuration(self):
        request = RecomposeNoteRequest(session_input=SessionInput(**INPUT), visible_section_ids=["session_content"])
        with patch.object(settings, "openai_api_key", None):
            missing = build_recompose_cache_key(request, actor="synthetic-owner")
            with patch.object(settings, "use_stub", True):
                demo = build_recompose_cache_key(request, actor="synthetic-owner")
        with patch.object(settings, "openai_api_key", "synthetic-key"):
            live = build_recompose_cache_key(request, actor="synthetic-owner")
            with patch.object(settings, "openai_model", "synthetic-other-model"):
                other_model = build_recompose_cache_key(request, actor="synthetic-owner")
        self.assertEqual(4, len({missing, demo, live, other_model}))


if __name__ == "__main__":
    unittest.main()
