"""Quick summary: the regular pipeline without login — de-identified input, no retrieval, length cap,
rate limit, Vercel routing. Synthetic text only."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("USE_STUB", "1")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import quick_summary as qs  # noqa: E402

SAMPLE = "내담자는 이번 주 취업 준비로 불안이 커졌다고 말했다. 연락처 010-1234-5678로 연락 달라고 했다. 상담자는 감정을 명료화했다."
TRANSCRIPT = "내담자: 요즘 잠을 잘 못 자요.\n상담자: 언제부터 그랬나요?\n내담자: 시험 기간부터요."


def _load_vercel_generate():
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("vercel_generate", root / "api" / "notes" / "generate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["vercel_generate"] = module
    spec.loader.exec_module(module)
    return module


class QuickSummaryTest(unittest.TestCase):
    def setUp(self) -> None:
        qs.rate_limiter.reset()
        self.client = TestClient(app)

    def test_returns_the_regular_summary_response_without_login(self) -> None:
        response = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        draft = body["session_summary_draft"]
        for key in ("session_theme", "presenting_problem", "session_content", "counselor_intervention",
                    "client_response", "reflection", "next_plan"):
            self.assertIn("text", draft[key])
        self.assertIn("verification_report", body)
        self.assertNotIn("010-1234-5678", response.text)

    def test_pipeline_runs_on_deidentified_input_without_retrieval(self) -> None:
        calls = {}

        def fake_pipeline(session_input, *args, **kwargs):
            calls["input"] = session_input
            calls["kwargs"] = kwargs
            raise RuntimeError("stop after capturing")

        with patch("app.graph.graph.run_note_pipeline", side_effect=fake_pipeline):
            response = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("010-1234-5678", response.text)
        self.assertEqual(calls["kwargs"], {"actor": "", "allow_retrieval": False, "use_summary_skill": True})
        self.assertNotIn("010-1234-5678", calls["input"].counselor_memo)
        self.assertFalse(calls["input"].persist)

    def test_speaker_lines_are_treated_as_a_transcript(self) -> None:
        transcript = qs.quick_summary_session_input(TRANSCRIPT)
        self.assertEqual((transcript.transcript_text, transcript.counselor_memo), (TRANSCRIPT, ""))
        memo = qs.quick_summary_session_input(SAMPLE)
        self.assertEqual((memo.counselor_memo, memo.transcript_text), (SAMPLE, ""))

    def test_rejects_too_short_and_too_long_input(self) -> None:
        self.assertEqual(self.client.post("/api/notes/quick-summary", json={"text": "짧음"}).status_code, 422)
        too_long = "가" * (qs.QUICK_SUMMARY_MAX_CHARS + 1)
        self.assertEqual(self.client.post("/api/notes/quick-summary", json={"text": too_long}).status_code, 422)

    def test_audio_editor_timestamps_preserve_transcript_source(self) -> None:
        for text in (
            "[0:00] 상담자: 오늘은 어떤 일이 있었나요?\n[1:02:03] 내담자: 학교에 안 갔어요.",
            "[0:00] 화자 speaker_0: 오늘은 어떤 일이 있었나요?\n[0:10] 화자 chunk_1_unmatched_2: 학교에 안 갔어요.",
        ):
            with self.subTest(text=text):
                parsed = qs.quick_summary_session_input(text)
                self.assertEqual(parsed.transcript_text, text)
                self.assertEqual(parsed.counselor_memo, "")
                self.assertFalse(parsed.persist)

    def test_authenticated_two_hour_transcript_reaches_model_without_truncation(self) -> None:
        from app.schemas.note import InputSources, SanitizedInput
        from app.services.summary_skill import build_summary_skill_request
        text = "\n".join(
            f"[{minute // 60}:{minute % 60:02}:00] 내담자: 오늘 느낀 불안과 일상생활의 변화를 함께 점검했습니다. " * 8
            + f"\n상담자: {minute}번째 구간에서 다룬 생각을 다시 확인하겠습니다."
            for minute in range(120)
        ) + "\n[1:59:59] 내담자: 마지막으로 수면 일지는 쓰지 않기로 했고 다음 회기에 다시 상의하기로 했어요."
        self.assertGreater(len(text), qs.QUICK_SUMMARY_MAX_CHARS)
        self.assertLess(len(text), qs.AUTHENTICATED_MAX_CHARS)
        captured = {}

        def pipeline(session_input, **kwargs):
            sanitized = SanitizedInput(
                case_id=session_input.case_id, session_number=1, session_date="", counselor_name="",
                sources=InputSources(counselor_memo=session_input.counselor_memo, transcript_text=session_input.transcript_text),
            )
            captured["body"] = json.loads(build_summary_skill_request(sanitized).messages[1].content)
            raise RuntimeError("Synthetic stop before model call")

        with patch("app.api.routes.notes._optional_actor", return_value="synthetic-user"), patch(
            "app.graph.graph.run_note_pipeline", side_effect=pipeline
        ):
            response = self.client.post("/api/notes/quick-summary", json={"text": text})
        self.assertEqual(response.status_code, 502)
        submitted = captured["body"]["sources"]["transcript_text"]
        for line in text.splitlines():
            self.assertTrue(line.rstrip() in submitted, "Every source line, including the tail, must reach generation")
        self.assertIn(f"transcript.turn_{len(text.splitlines())}", captured["body"]["allowed_source_refs"])
        # The larger budget requires a verified actor, not a user-supplied flag.
        self.assertEqual(self.client.post("/api/notes/quick-summary", json={"text": text}).status_code, 422)

    def test_authenticated_limit_and_privacy_preview_cover_same_input(self) -> None:
        from app.services.deidentification_preview import preview_items
        text = "내담자: " + "상담 내용 확인. " * 11990
        text = text[:qs.AUTHENTICATED_MAX_CHARS]
        self.assertEqual(qs.validate_quick_summary_text(text, max_chars=qs.AUTHENTICATED_MAX_CHARS), text.strip())
        self.assertIsNotNone(preview_items([text]))
        with self.assertRaises(qs.QuickSummaryInputError):
            qs.validate_quick_summary_text("가" * (qs.AUTHENTICATED_MAX_CHARS + 1), max_chars=qs.AUTHENTICATED_MAX_CHARS)

    def test_anonymous_requests_are_rate_limited_per_ip(self) -> None:
        limit = qs.ANONYMOUS_LIMIT[0]
        headers = {"x-real-ip": "203.0.113.7"}
        for _ in range(limit):
            self.assertEqual(self.client.post("/api/notes/quick-summary", json={"text": SAMPLE}, headers=headers).status_code, 200)
        blocked = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE}, headers=headers)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)
        other_ip = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE}, headers={"x-real-ip": "203.0.113.8"})
        self.assertEqual(other_ip.status_code, 200)

    def test_vercel_rewrite_reaches_quick_summary_without_auth(self) -> None:
        module = _load_vercel_generate()
        client = TestClient(module.app)
        response = client.post("/api/notes/generate?scope=quick", json={"text": SAMPLE})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("session_summary_draft", response.json())
        # The regular generate path keeps requiring authentication.
        self.assertNotEqual(client.post("/api/notes/generate", json={}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
