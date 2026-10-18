"""Synthetic regression coverage for failed summary generation boundaries."""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.notes.generate import app as generate_app
from api.notes.recompose import app as recompose_app
from app.api.security import require_preview_access
from app.core.config import settings
from app.main import app as main_app
from app.graph.graph import run_note_pipeline
from app.graph import summary_core
from app.api.routes.notes import _run_pipeline_with_stub_fallback
from app.schemas.note import PersistenceReport, RecomposeNoteRequest, SessionInput
from app.services.recompose_cache import build_recompose_cache_key
from app.services.summary_quality import SummaryQualityError
from app.services.transcript_chunking import TranscriptLimitError


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

    def test_oversized_generation_returns_clear_limit_error_without_persisting(self):
        for app in (generate_app, main_app):
            with self.subTest(app=app.title), patch(
                "app.api.routes.notes.run_note_pipeline",
                side_effect=TranscriptLimitError("요청당 입력 한도를 초과했습니다."),
            ), patch("app.api.routes.notes.persist_generated_note") as persist:
                response = TestClient(app).post("/api/notes/generate", json=INPUT)
                self.assertEqual(413, response.status_code)
                self.assertEqual("요청당 입력 한도를 초과했습니다.", response.json()["detail"])
                persist.assert_not_called()

    def test_oversized_persistent_input_is_rejected_before_deidentification_provider(self):
        oversized = SessionInput(**{**INPUT, "transcript_text": "가" * 96_001})
        with patch.object(settings, "enable_persistence", True), patch(
            "app.api.routes.notes.deidentify_session_input"
        ) as deidentify, patch("app.api.routes.notes.run_note_pipeline") as pipeline:
            with self.assertRaises(HTTPException) as caught:
                _run_pipeline_with_stub_fallback(oversized, actor="synthetic-owner")
        self.assertEqual(413, caught.exception.status_code)
        deidentify.assert_not_called()
        pipeline.assert_not_called()

    def test_oversized_issue_tags_are_rejected_before_provider(self):
        cases = (
            (["가" * 96_001], "요청당 입력 한도는 96,000자입니다. 현재 96,055자입니다."),
            (["🧭" * 48_001], "요청당 추정 입력 토큰 한도는 96,000개입니다."),
            ([""] * 9_600, "요청당 입력 한도는 96,000자입니다. 현재 96,044자입니다."),
        )
        with patch("app.api.routes.notes.run_note_pipeline") as pipeline, patch(
            "app.api.routes.notes.persist_generated_note"
        ) as persist:
            for tags, expected_detail in cases:
                with self.subTest(expected_detail=expected_detail):
                    payload = {**INPUT, "key_issue_tags": tags, "persist": False}
                    response = TestClient(main_app).post("/api/notes/generate", json=payload)

                    self.assertEqual(413, response.status_code)
                    self.assertEqual(expected_detail, response.json()["detail"])
        pipeline.assert_not_called()
        persist.assert_not_called()

    def test_oversized_session_dates_are_rejected_before_provider(self):
        token_heavy_pattern = "".join(chr(0x20000 + index) for index in range(512))
        cases = (
            ("가" * 96_001, "요청당 입력 한도는 96,000자입니다."),
            ((token_heavy_pattern * 94)[:48_001], "요청당 추정 입력 토큰 한도는 96,000개입니다."),
        )
        with patch(
            "app.api.routes.notes.run_note_pipeline",
            side_effect=AssertionError("generation provider pipeline reached"),
        ) as generation_pipeline, patch(
            "app.api.routes.notes.persist_generated_note"
        ) as persist, patch(
            "app.services.recompose_cache._case_source_revision",
            side_effect=AssertionError("source revision reached"),
        ) as source_revision, patch(
            "app.services.recompose_cache.run_note_pipeline",
            side_effect=AssertionError("recomposition provider pipeline reached"),
        ) as recompose_pipeline:
            for session_date, expected_detail in cases:
                session_input = {**INPUT, "session_date": session_date, "persist": False}
                for app in (generate_app, main_app):
                    with self.subTest(app=app.title, endpoint="generate", expected_detail=expected_detail):
                        response = TestClient(app).post("/api/notes/generate", json=session_input)
                        self.assertEqual(413, response.status_code, response.text[:300])
                        self.assertIn(expected_detail, response.json()["detail"])
                for app in (recompose_app, main_app):
                    with self.subTest(app=app.title, endpoint="recompose", expected_detail=expected_detail):
                        response = TestClient(app).post(
                            "/api/notes/recompose",
                            json={
                                "session_input": session_input,
                                "session_topic": "합성 주제",
                                "visible_section_ids": ["session_content"],
                            },
                        )
                        self.assertEqual(413, response.status_code, response.text[:300])
                        self.assertIn(expected_detail, response.json()["detail"])
        generation_pipeline.assert_not_called()
        persist.assert_not_called()
        source_revision.assert_not_called()
        recompose_pipeline.assert_not_called()

    def test_authenticated_route_reuses_raw_input_budget_validation(self):
        payload = {
            **INPUT,
            "transcript_text": "synthetic full preprocessing line.\n" * 400,
            "persist": False,
            "insight_lens": "none",
        }
        with patch.object(settings, "use_stub", True), patch.object(
            settings, "enable_persistence", False
        ), patch.object(settings, "enable_rag", False), patch.object(
            summary_core,
            "estimate_korean_tokens",
            wraps=summary_core.estimate_korean_tokens,
        ) as token_estimate, patch(
            "app.api.routes.notes.persist_generated_note",
            return_value=PersistenceReport(enabled=False, requested=False),
        ):
            response = TestClient(main_app).post("/api/notes/generate", json=payload)

        self.assertEqual(200, response.status_code, response.text[:300])
        self.assertEqual(2, token_estimate.call_count)
        self.assertEqual(
            [len(call.args[0]) for call in token_estimate.call_args_list],
            [
                len(payload["session_date"] + payload["counselor_memo"] + payload["transcript_text"]),
                len(payload["session_date"] + payload["counselor_memo"] + payload["transcript_text"].strip()),
            ],
        )

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

    def test_recomposition_control_fields_are_rejected_before_cache_or_provider(self):
        cases = (
            (
                {"session_input": INPUT, "session_topic": "가" * 96_001},
                "요청당 입력 한도는 96,000자입니다.",
            ),
            (
                {"session_input": INPUT, "session_topic": "🧭" * 48_001},
                "요청당 추정 입력 토큰 한도는 96,000개입니다.",
            ),
            (
                {
                    "session_input": INPUT,
                    "session_topic": "합성 주제",
                    "visible_section_ids": [f"section-{index}" for index in range(10_000)],
                },
                "요청당 입력 한도는 96,000자입니다.",
            ),
        )
        with patch(
            "app.services.recompose_cache._case_source_revision",
            side_effect=AssertionError("source revision reached"),
        ) as source_revision, patch(
            "app.services.recompose_cache.run_note_pipeline",
            side_effect=AssertionError("provider pipeline reached"),
        ) as pipeline:
            for app in (recompose_app, main_app):
                for payload, expected_detail in cases:
                    with self.subTest(app=app.title, fields=tuple(payload)):
                        response = TestClient(app).post("/api/notes/recompose", json=payload)

                        self.assertEqual(413, response.status_code, response.text[:300])
                        self.assertIn(expected_detail, response.json()["detail"])
        source_revision.assert_not_called()
        pipeline.assert_not_called()

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
