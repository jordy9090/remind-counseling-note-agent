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
from app.services import quick_summary as qs  # noqa: E402

SAMPLE = "내담자는 이번 주 취업 준비로 불안이 커졌다고 말했다. 연락처 010-1234-5678로 연락 달라고 했다. 상담자는 감정을 명료화했다."
QUALITY_SAMPLE = (
    "내담자: 동료의 부탁을 거절했지만 동료가 실망했다고 말한 것은 아니에요. 그래도 미안함은 남아 있어요.\n"
    "상담자: 동료의 실제 반응과 예상한 반응을 나누어 살펴보면 어떨까요?\n"
    "내담자: 실제로는 괜찮다고 답했어요. 오늘 별도의 행동 과제는 정하지 않았어요."
)


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
        captured: dict[str, str] = {}

        class FakeLLM:
            def invoke(self, prompt: str):
                captured["prompt"] = prompt
                return qs._QuickSummaryDraft(main_content="a", client_response="b", counselor_intervention="c", next_plan="d")

        with patch.object(qs.settings, "use_stub", False), patch.object(qs.settings, "openai_api_key", "test"), \
                patch("app.services.llm.get_structured_llm", return_value=FakeLLM()):
            result = qs.generate_quick_summary(SAMPLE)
        self.assertNotIn("010-1234-5678", captured["prompt"])
        self.assertIn("[PHONE]", captured["prompt"])
        self.assertEqual(result.next_plan, "d")

    def test_quality_prompt_includes_roles_counterevidence_and_plan_boundaries(self) -> None:
        prompts: list[str] = []

        class FakeLLM:
            def invoke(self, prompt: str):
                prompts.append(prompt)
                return qs._QuickSummaryDraft(
                    main_content="동료의 실제 반응과 예상한 반응을 구분해 살펴봄.",
                    client_response="미안함은 남아 있으나 동료는 괜찮다고 답했다고 표현함.",
                    counselor_intervention="상담자는 실제 반응과 예상한 반응을 나누어 탐색할 것을 제안함.",
                    next_plan="입력 내용에서 확인되지 않음",
                )

        with patch.object(qs.settings, "use_stub", False), patch.object(qs.settings, "openai_api_key", "test"), \
                patch("app.services.llm.get_structured_llm", return_value=FakeLLM()):
            result = qs.generate_quick_summary(QUALITY_SAMPLE)

        self.assertEqual(len(prompts), 1)
        prompt = prompts[0]
        self.assertIn(QUALITY_SAMPLE, prompt)
        self.assertIn('각 항목에 해당하는 내용이 입력에 없으면 "입력 내용에서 확인되지 않음"', prompt)
        self.assertIn("상담자의 질문·반영과 내담자의 표현·반응을 구분", prompt)
        self.assertIn("관찰된 사실과 내담자의 예상·지각을 구분", prompt)
        self.assertIn("반대 근거", prompt)
        self.assertIn('상담자의 제안은 "제안함"', prompt)
        self.assertIn('명시적으로 합의한 계획만 "하기로 함"', prompt)
        self.assertIn("별도 과제나 계획을 새로 만들지 마세요", prompt)
        self.assertIn("자료가 적으면 짧게", prompt)
        self.assertEqual(result.next_plan, "입력 내용에서 확인되지 않음")

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
