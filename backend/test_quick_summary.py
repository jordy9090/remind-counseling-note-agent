"""Quick summary: public access, PII masking before the LLM, length cap, rate limit, Vercel routing."""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("USE_STUB", "1")

from fastapi import HTTPException  # noqa: E402
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

    def test_frontend_timestamped_speaker_labels_remain_separated_in_stub_mode(self) -> None:
        text = (
            "[0:00] 상담자： 오늘 어떤 점을 이야기하고 싶나요?\n"
            "[0:04] 내담자: 발표 전 걱정이 커졌어요.\n"
            "[0:08] 화자 미배정: 이 문장은 역할을 추정하면 안 됩니다."
        )

        response = self.client.post("/api/notes/quick-summary", json={"text": text})

        self.assertEqual(200, response.status_code, response.text)
        body = response.json()
        self.assertIn("오늘 어떤 점을 이야기하고 싶나요", body["counselor_intervention"])
        self.assertIn("발표 전 걱정이 커졌어요", body["client_response"])
        self.assertNotIn("발표 전 걱정", body["counselor_intervention"])
        self.assertNotIn("어떤 점을 이야기", body["client_response"])
        self.assertNotIn("역할을 추정", response.text)

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
                patch("app.graph.nodes.get_structured_llm", side_effect=lambda schema, **_: FakeLLM(schema)):
            result = qs.generate_quick_summary(SAMPLE + " 원문고유표식ABC123은 구조화 뒤 반복 전송하지 않는다.")
        self.assertEqual(2, len(prompts))
        self.assertTrue(all("010-1234-5678" not in prompt for prompt in prompts))
        self.assertIn("[PHONE]", prompts[0])
        self.assertEqual(1, sum("[PHONE]" in prompt for prompt in prompts))
        self.assertEqual(1, sum("원문고유표식ABC123" in prompt for prompt in prompts))
        self.assertEqual(result.next_plan, "[상담사 확인 필요]")

    def test_institution_rare_occupation_and_distinctive_event_are_masked_before_llm(self) -> None:
        raw_fragments = ("한빛고등학교", "우주비행사", "전국별빛대회 최우수상")
        text = (
            "내담자는 한빛고등학교에 다니며 부모가 우주비행사라고 말했다. "
            "전국별빛대회 최우수상을 받은 뒤 주변의 관심이 부담스럽다고 표현했다."
        )
        prompts: list[str] = []

        class RecordingLLM:
            def __init__(self, schema):
                self.schema = schema

            def invoke(self, prompt: str):
                prompts.append(prompt)
                if self.schema is StructuredCaseData:
                    return StructuredCaseData(
                        session_content=[EvidenceItem(content="주변의 관심에 대한 부담을 다룸.", evidence_type="direct", source_refs=["transcript_text"])],
                    )
                return SessionSummaryDraft(
                    session_info=SessionInfo(case_id="public-quick-summary", session_number=1, session_date=""),
                    session_theme=SummarySection(text="주변 관심에 대한 부담", evidence_type="direct", source_refs=["transcript_text"]),
                    presenting_problem=SummarySection(text="부담감", evidence_type="direct", source_refs=["transcript_text"]),
                    session_content=SummarySection(text="주변 관심에 대한 부담을 다룸.", evidence_type="direct", source_refs=["transcript_text"]),
                    client_response=SummarySection(text="내담자는 부담스럽다고 표현함.", evidence_type="direct", source_refs=["transcript_text"]),
                    counselor_intervention=SummarySection(text="[상담사 확인 필요]", evidence_type="needs_review", requires_review=True),
                    reflection=SummarySection(text="[상담사 확인 필요]", evidence_type="needs_review", requires_review=True),
                    next_plan=SummarySection(text="[상담사 확인 필요]", evidence_type="needs_review", requires_review=True),
                )

        with patch.object(qs.settings, "use_stub", False), patch.object(qs.settings, "openai_api_key", "test"), patch(
            "app.graph.nodes.get_structured_llm", side_effect=lambda schema, **_: RecordingLLM(schema)
        ):
            result = qs.generate_quick_summary(text)

        self.assertTrue(prompts)
        self.assertTrue(all(fragment not in prompt for prompt in prompts for fragment in raw_fragments))
        self.assertIn("[INSTITUTION]", prompts[0])
        self.assertIn("[OCCUPATION]", prompts[0])
        self.assertIn("[UNIQUE_EVENT]", prompts[0])
        self.assertTrue(all(fragment not in prompts[1] for fragment in raw_fragments))
        self.assertEqual(
            {"institution", "rare_occupation", "specific_event"},
            set(result.masked_categories),
        )

    def test_rejects_too_short_and_too_long_input(self) -> None:
        self.assertEqual(self.client.post("/api/notes/quick-summary", json={"text": "짧음"}).status_code, 422)
        too_long = "가" * (qs.QUICK_SUMMARY_MAX_CHARS + 1)
        self.assertEqual(self.client.post("/api/notes/quick-summary", json={"text": too_long}).status_code, 422)

    def test_rejects_token_heavy_input_below_character_limit(self) -> None:
        token_heavy = "쀍" * 7_000
        self.assertLess(len(token_heavy), qs.QUICK_SUMMARY_MAX_CHARS)
        self.assertEqual(
            422,
            self.client.post("/api/notes/quick-summary", json={"text": token_heavy}).status_code,
        )

    def test_cost_guard_reuses_the_validated_token_estimate(self) -> None:
        with patch.object(
            qs,
            "estimate_korean_tokens",
            wraps=qs.estimate_korean_tokens,
        ) as estimate_tokens:
            response = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE})

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, estimate_tokens.call_count)
        self.assertEqual(SAMPLE, estimate_tokens.call_args.args[0])

    def test_anonymous_requests_are_rate_limited_per_ip(self) -> None:
        limit = qs.ANONYMOUS_LIMIT[0]
        headers = {"x-real-ip": "203.0.113.7"}
        with patch.object(qs.settings, "trust_proxy_client_ip_headers", True):
            for _ in range(limit):
                self.assertEqual(self.client.post("/api/notes/quick-summary", json={"text": SAMPLE}, headers=headers).status_code, 200)
            blocked = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE}, headers=headers)
            self.assertEqual(blocked.status_code, 429)
            self.assertIn("Retry-After", blocked.headers)
            other_ip = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE}, headers={"x-real-ip": "203.0.113.8"})
            self.assertEqual(other_ip.status_code, 200)

    def test_untrusted_forwarded_ip_header_cannot_rotate_the_quota(self) -> None:
        limit = qs.ANONYMOUS_LIMIT[0]
        with patch.dict(os.environ, {"VERCEL": ""}), patch.object(
            qs.settings, "trust_proxy_client_ip_headers", False
        ):
            for index in range(limit):
                response = self.client.post(
                    "/api/notes/quick-summary",
                    json={"text": SAMPLE},
                    headers={"x-real-ip": f"203.0.113.{index + 1}"},
                )
                self.assertEqual(200, response.status_code)
            blocked = self.client.post(
                "/api/notes/quick-summary",
                json={"text": SAMPLE},
                headers={"x-real-ip": "203.0.113.99"},
            )
        self.assertEqual(429, blocked.status_code)

    def test_invalid_bearer_is_rate_limited_before_repeated_auth_checks(self) -> None:
        headers = {"Authorization": "Bearer synthetic-invalid"}
        with patch.object(qs.settings, "enable_real_user_auth", True), patch(
            "app.api.routes.notes._require_supabase_user",
            side_effect=HTTPException(status_code=401, detail="synthetic invalid token"),
        ) as authenticate:
            statuses = [
                self.client.post(
                    "/api/notes/quick-summary", json={"text": SAMPLE}, headers=headers
                ).status_code
                for _ in range(qs.ANONYMOUS_LIMIT[0] + 2)
            ]

        self.assertEqual([200] * qs.ANONYMOUS_LIMIT[0] + [429, 429], statuses)
        self.assertEqual(qs.ANONYMOUS_LIMIT[0], authenticate.call_count)

    def test_valid_bearer_uses_user_quota_instead_of_anonymous_ip_quota(self) -> None:
        headers = {"Authorization": "Bearer synthetic-valid"}
        with patch.object(qs.settings, "enable_real_user_auth", True), patch(
            "app.api.routes.notes._require_supabase_user", return_value="synthetic-user"
        ):
            statuses = [
                self.client.post(
                    "/api/notes/quick-summary", json={"text": SAMPLE}, headers=headers
                ).status_code
                for _ in range(qs.ANONYMOUS_LIMIT[0] + 1)
            ]

        self.assertEqual([200] * (qs.ANONYMOUS_LIMIT[0] + 1), statuses)

    def test_rate_limiter_rejects_new_keys_when_active_key_capacity_is_full(self) -> None:
        limiter = qs._SlidingWindowLimiter(max_keys=2)
        limiter.check("first", 5, 60, now=0)
        limiter.check("second", 5, 60, now=0)

        with self.assertRaises(qs.QuickSummaryRateLimited):
            limiter.check("third", 5, 60, now=1)

        limiter.check("third", 5, 60, now=60)
        self.assertLessEqual(len(limiter._hits), 2)

    def test_busy_instance_fails_fast_without_running_the_summary(self) -> None:
        with patch.object(qs._concurrency_guard, "acquire", return_value=False), patch.object(
            qs._concurrency_guard, "release"
        ) as release, patch("app.services.quick_summary.run_summary_core") as core:
            response = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE})
        self.assertEqual(503, response.status_code)
        self.assertEqual("1", response.headers["Retry-After"])
        core.assert_not_called()
        release.assert_not_called()

    def test_estimated_cost_limit_blocks_before_provider_execution(self) -> None:
        with patch.object(qs.settings, "llm_provider", "openai"), patch.object(
            qs.settings, "openai_model", "gpt-5.4"
        ), patch.object(qs.settings, "quick_summary_max_estimated_cost_usd", 0.000001), patch(
            "app.services.quick_summary.run_summary_core"
        ) as core:
            response = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE})
        self.assertEqual(503, response.status_code)
        self.assertIn("비용 한도", response.json()["detail"])
        core.assert_not_called()

    def test_unknown_provider_pricing_blocks_before_provider_execution(self) -> None:
        with patch.object(qs.settings, "llm_provider", "openai_compatible"), patch.object(
            qs.settings, "llm_input_cost_per_million_usd", None
        ), patch.object(qs.settings, "llm_output_cost_per_million_usd", None), patch(
            "app.services.quick_summary.run_summary_core"
        ) as core:
            response = self.client.post("/api/notes/quick-summary", json={"text": SAMPLE})
        self.assertEqual(503, response.status_code)
        self.assertIn("비용 한도", response.json()["detail"])
        core.assert_not_called()

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
