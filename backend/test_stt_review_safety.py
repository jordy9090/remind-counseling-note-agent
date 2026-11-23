"""Transcript review safety found in the 2026-11-23 STT test; all text is synthetic.

- Public crisis and emergency lines are never offered for masking.
- A detected full name also covers the given-name forms the client uses.
- Risk statements in the transcript reach the "위험 신호" section as quoted lines.
Run: python -m unittest test_stt_review_safety
"""
from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from app.core.config import settings
from app.graph.nodes import _extract_risk_information
from app.schemas.note import InputSources, SanitizedInput
from app.services import deid_review as review
from app.services import qwen_deidentification as qwen

TRANSCRIPT = "\n".join([
    "[0:30] 내담자: 회사에서 김민준 팀장님이 회의 때마다 제 보고서를 지적했어요.",
    "[0:37] 내담자: 민준 팀장님 목소리만 들어도 심장이 뛰어요.",
    "[1:08] 내담자: 대학 동기 박서연한테만 말했어요. 서연이가 010-2345-6789로 전화하라고 했어요.",
    "[1:19] 상담자: 서연 씨가 든든한 친구네요.",
    "[1:30] 내담자: 이지원 대리는 지원을 받지 못했다고 했어요.",
    "[2:11] 상담자: 그런 생각이 강해지면 109 자살예방 상담전화나 1577-0199로 바로 연락해 주세요.",
])


class PublicHelpLineTests(unittest.TestCase):
    def test_public_lines_are_recognised_and_personal_numbers_are_not(self):
        for value in ("109", "1393", "1577-0199", "1588-9191", "112", "119", "자살예방 상담전화", "생명의전화"):
            self.assertTrue(review.is_public_help_line(value), value)
        for value in ("010-2345-6789", "010-1393-0000", "1093", "02-109-1234", "109동", "김민준", ""):
            self.assertFalse(review.is_public_help_line(value), value)


class ReviewItemTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, value in {"deid_review_signing_key": "synthetic-review-secret-" * 3, "require_deid_review": True, "poc_mode": False,
                            "enable_real_user_auth": False, "runtime_environment": "test",
                            "remind_allow_local_bypass": True, "remind_preview_actor": "synthetic-owner"}.items():
            stack.enter_context(patch.object(settings, name, value))
        stack.enter_context(patch("app.services.deid_review.detect_entities", return_value=qwen.Entities(entities=[
            qwen.Entity(original="김민준", category="name"),
            qwen.Entity(original="박서연", category="name"),
            qwen.Entity(original="이지원", category="name"),
            qwen.Entity(original="010-2345-6789", category="contact"),
            qwen.Entity(original="109", category="contact"),
            qwen.Entity(original="1577-0199", category="contact"),
            qwen.Entity(original="자살예방 상담전화", category="organization"),
        ])))

    def items(self) -> dict[str, str]:
        found = review.start_review(review.ReviewStart(purpose="quick", payload={"text": TRANSCRIPT}), "synthetic-owner")
        return {item["original"]: item["replacement"] for item in found["items"]}

    def test_crisis_lines_stay_and_personal_contact_is_masked(self):
        items = self.items()
        for kept in ("109", "1577-0199", "자살예방 상담전화"):
            self.assertNotIn(kept, items)
        self.assertEqual(items["010-2345-6789"], "연락처 비공개")

    def test_given_names_share_the_full_names_label(self):
        items = self.items()
        self.assertEqual(items["민준"], items["김민준"])
        self.assertEqual(items["서연"], items["박서연"])
        self.assertNotEqual(items["김민준"], items["박서연"])
        self.assertNotIn("지원", items, "an ambiguous given name stays with the counselor")


def sanitized(transcript: str, memo: str = "") -> SanitizedInput:
    return SanitizedInput(case_id="synthetic", session_number=1, session_date="", counselor_name="",
                          sources=InputSources(counselor_memo=memo, transcript_text=transcript))


class RiskSectionTests(unittest.TestCase):
    def test_transcript_risk_statements_are_quoted_with_sources(self):
        transcript = "\n".join([
            "[0:05] 내담자: 잠을 거의 못 잤어요.",
            "[1:53] 상담자: 혹시 스스로를 해치고 싶다는 생각이 든 적도 있었는지 여쭤봐도 될까요?",
            "[2:01] 내담자: 죽고 싶은 건 아닌데 가끔은 그냥 사라지고 싶다는 생각이 들어요.",
            "[2:11] 상담자: 그런 생각이 강해지면 109 자살예방 상담전화로 바로 연락해 주세요.",
        ])
        text, refs = _extract_risk_information(sanitized(transcript))
        self.assertIn("위험도는 상담사가 판단", text)
        self.assertIn("[2:01] 내담자: 죽고 싶은 건 아닌데 가끔은 그냥 사라지고 싶다는 생각이 들어요.", text)
        self.assertEqual(refs, ["transcript.turn_2", "transcript.turn_3", "transcript.turn_4"])
        self.assertNotIn("잠을 거의", text)

    def test_memo_and_transcript_are_both_kept_and_lines_are_bounded(self):
        transcript = "\n".join(f"[{i}:00] 내담자: 살기 싫다는 생각이 {i}번째로 들었어요." for i in range(12))
        text, refs = _extract_risk_information(sanitized(transcript, memo="자해 이력은 없다고 보고함. 수면이 줄었다."))
        self.assertTrue(text.startswith("자해 이력은 없다고 보고함."))
        self.assertEqual(refs[0], "counselor_memo")
        self.assertEqual(len([ref for ref in refs if ref.startswith("transcript.")]), 8)

    def test_no_statement_means_counselor_check_and_idioms_do_not_trigger(self):
        self.assertEqual(_extract_risk_information(sanitized("[0:10] 내담자: 숨이 막혀서 죽을 것 같았어요.")), ("[상담사 확인 필요]", []))
        self.assertEqual(_extract_risk_information(sanitized("")), ("[상담사 확인 필요]", []))


if __name__ == "__main__":
    unittest.main()
