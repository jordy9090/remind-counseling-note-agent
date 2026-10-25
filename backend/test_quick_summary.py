"""Quick summary: the regular pipeline without login — de-identified input, no retrieval, length cap,
rate limit, Vercel routing. Synthetic text only."""
from __future__ import annotations

import importlib.util
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
