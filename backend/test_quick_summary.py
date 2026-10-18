"""Quick summary: public access, PII masking before the LLM, length cap, rate limit, Vercel routing."""
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
from app.schemas.note import (  # noqa: E402
    EvidenceItem,
    SessionInfo,
    SessionSummaryDraft,
    StructuredCaseData,
    SummarySection,
)
from app.services import quick_summary as qs  # noqa: E402

SAMPLE = "내담자는 이번 주 취업 준비로 불안이 커졌다고 말했다. 연락처 010-1234-5678로 연락 달라고 했다. 상담자는 감정을 명료화했다."


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

    def test_works_without_login_and_returns_four_items(self) -> None:
        response = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        for key in ("main_content", "client_response", "counselor_intervention", "next_plan"):
            self.assertTrue(body[key])
        self.assertIn("phone", body["masked_categories"])
        self.assertNotIn("010-1234-5678", response.text)

    def test_llm_receives_masked_text_only(self) -> None:
        prompts: list[str] = []

        class FakeLLM:
            def __init__(self, schema):
                self.schema = schema

            def invoke(self, prompt: str):
                prompts.append(prompt)
                if self.schema is StructuredCaseData:
                    return StructuredCaseData(
                        session_content=[EvidenceItem(content="취업 준비 불안을 다룸.", evidence_type="direct", source_refs=["transcript_text"])],
                        client_responses=[EvidenceItem(content="내담자는 불안이 커졌다고 표현함.", evidence_type="direct", source_refs=["transcript_text"])],
                        counselor_interventions=[EvidenceItem(content="상담자는 감정을 명료화함.", evidence_type="direct", source_refs=["transcript_text"])],
                        next_plan=[EvidenceItem(content="[상담사 확인 필요]", evidence_type="needs_review", source_refs=[])],
                    )
                return SessionSummaryDraft(
                    session_info=SessionInfo(case_id="public-quick-summary", session_number=1, session_date=""),
                    session_theme=SummarySection(text="취업 준비 불안", evidence_type="direct", source_refs=["transcript_text"]),
                    presenting_problem=SummarySection(text="취업 준비 과정의 불안", evidence_type="direct", source_refs=["transcript_text"]),
                    session_content=SummarySection(text="취업 준비 과정에서 커진 불안을 다룸.", evidence_type="direct", source_refs=["transcript_text"]),
                    client_response=SummarySection(text="내담자는 불안이 커졌다고 표현함.", evidence_type="direct", source_refs=["transcript_text"]),
                    counselor_intervention=SummarySection(text="상담자는 감정을 명료화함.", evidence_type="direct", source_refs=["transcript_text"]),
                    reflection=SummarySection(text="[상담사 확인 필요]", evidence_type="counselor_input", source_refs=[], requires_review=True),
                    next_plan=SummarySection(text="[상담사 확인 필요]", evidence_type="needs_review", source_refs=[], requires_review=True),
                )

        with patch.object(qs.settings, "use_stub", False), patch.object(qs.settings, "openai_api_key", "test"), \
                patch("app.graph.nodes.get_structured_llm", side_effect=lambda schema: FakeLLM(schema)):
            result = qs.generate_quick_summary(SAMPLE)
        self.assertEqual(2, len(prompts))
        self.assertTrue(all("010-1234-5678" not in prompt for prompt in prompts))
        self.assertTrue(all("[PHONE]" in prompt for prompt in prompts))
        self.assertEqual(result.next_plan, "[상담사 확인 필요]")

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
        self.assertIn("main_content", response.json())
        # The regular generate path keeps requiring authentication.
        self.assertNotEqual(client.post("/api/notes/generate", json={}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
