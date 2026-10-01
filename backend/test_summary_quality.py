"""Regression tests for session-summary prose and its single repair attempt."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.core.config import settings
from app.graph.nodes import generate_summary
from app.schemas.note import (
    EvidenceMappedData,
    InputSources,
    SanitizedInput,
    SessionInfo,
    SessionSummaryDraft,
    StructuredCaseData,
    SummarySection,
)
from app.services.summary_quality import SummaryQualityError, summary_quality_issues


def _section(text: str, ref: str = "transcript_text") -> SummarySection:
    return SummarySection(text=text, evidence_type="direct", source_refs=[ref])


def _summary() -> SessionSummaryDraft:
    return SessionSummaryDraft(
        session_info=SessionInfo(case_id="SYNTH-SUMMARY", session_number=1, session_date="2026-10-02"),
        presenting_problem=_section("내담자는 시험 전날 잠들기 어려웠던 경험을 보고함."),
        session_theme=_section("시험 준비를 멈추기 어려운 마음을 탐색함."),
        session_content=_section(
            "내담자는 시험 준비를 마친 뒤에도 내용을 확인하느라 잠들기 어려웠다고 보고함. "
            "상담자는 준비를 멈추려 할 때 어떤 생각이 드는지 질문함. "
            "내담자는 빠뜨린 내용이 있을까 걱정된다고 표현했으며, 잠들기 전의 걱정이 남아 있다고 함."
        ),
        counselor_intervention=_section("상담자는 준비를 멈추려 할 때 떠오르는 생각을 질문함."),
        client_response=_section("내담자는 빠뜨린 내용이 있을까 걱정되며 아직 잠들기 어렵다고 표현함."),
        reflection=SummarySection(text="[상담사 확인 필요]", evidence_type="counselor_input", requires_review=True),
        next_plan=_section("다음 회기에 시험 전날의 걱정을 다시 살펴볼 것을 제안함."),
    )


def _state() -> dict:
    return {
        "sanitized_input": SanitizedInput(
            case_id="SYNTH-SUMMARY", session_number=1, session_date="2026-10-02", counselor_name="",
            sources=InputSources(
                counselor_memo="시험 전날 잠들기 어려웠던 경험을 다룸.",
                transcript_text=(
                    "내담자: 준비를 마쳐도 자꾸 다시 확인해요. 잠이 안 와요.\n"
                    "상담자: 준비를 멈추려 할 때 어떤 생각이 드나요?\n"
                    "내담자: 빠뜨린 내용이 있을까 걱정돼요. 아직 잠들기 어려워요.\n"
                    "상담자: 다음 회기에 시험 전날의 걱정을 다시 살펴볼까요?"
                ),
            ),
        ),
        "structured_case_data": StructuredCaseData(),
        "evidence_mapped_data": EvidenceMappedData(),
    }


class SummaryQualityTests(unittest.TestCase):
    def test_concise_prose_and_ready_written_memo_are_accepted(self) -> None:
        summary = _summary()
        self.assertEqual({}, summary_quality_issues(summary))
        summary.session_content.text = _state()["sanitized_input"].sources.counselor_memo
        self.assertEqual({}, summary_quality_issues(summary))

    def test_dialogue_dump_and_speaker_labels_are_rejected(self) -> None:
        for text in (
            "계속 확인해요. 잠이 안 와요. 걱정돼요.",
            "내담자: 준비를 멈추기 어려웠다.",
            "[counselor] 준비를 멈추는 순간을 질문했다.",
            '“계속 확인해요. 잠이 안 와요.”',
        ):
            with self.subTest(text=text):
                summary = _summary()
                summary.session_content.text = text
                self.assertIn("session_content", summary_quality_issues(summary))

    def test_short_supporting_quotes_do_not_count_as_dialogue_dump(self) -> None:
        summary = _summary()
        summary.client_response.text = (
            "내담자는 “계속 확인해요. 잠이 안 와요.”라고 표현했으며, 시험을 앞둔 걱정을 보고함."
        )
        self.assertEqual({}, summary_quality_issues(summary))

    def test_many_short_quotations_cannot_hide_a_dialogue_dump(self) -> None:
        summary = _summary()
        summary.client_response.text = (
            '내담자는 다음과 같이 말함. "계속 확인해요." "잠이 안 와요." '
            '"걱정돼요." "다시 보고 싶어요."'
        )
        self.assertIn("client_response", summary_quality_issues(summary))

    def test_excessive_length_or_sentence_count_is_rejected(self) -> None:
        for text in ("걱정을 표현함. " * 9, "걱정" * 701):
            with self.subTest(length=len(text)):
                summary = _summary()
                summary.session_content.text = text
                self.assertIn("session_content", summary_quality_issues(summary))

    def test_valid_summary_uses_one_call_and_preserves_source_reference(self) -> None:
        llm = Mock()
        llm.invoke.return_value = _summary()
        with patch.object(settings, "use_stub", False), patch.object(settings, "openai_api_key", "synthetic-key"), patch(
            "app.graph.nodes.get_structured_llm", return_value=llm
        ):
            result = generate_summary(_state())["session_summary_draft"]
        self.assertEqual(1, llm.invoke.call_count)
        self.assertIn("transcript_text", result.session_content.source_refs)
        self.assertEqual(_summary().session_content.text, result.session_content.text)

    def test_one_repair_uses_original_sources_and_returns_rewritten_summary(self) -> None:
        rejected = _summary()
        rejected.session_content.text = "계속 확인해요. 잠이 안 와요. 걱정돼요."
        repaired = _summary()
        llm = Mock()
        llm.invoke.side_effect = [rejected, repaired]
        state = _state()
        with patch.object(settings, "use_stub", False), patch.object(settings, "openai_api_key", "synthetic-key"), patch(
            "app.graph.nodes.get_structured_llm", return_value=llm
        ):
            result = generate_summary(state)["session_summary_draft"]
        self.assertEqual(2, llm.invoke.call_count)
        repair_prompt = llm.invoke.call_args_list[1].args[0]
        self.assertIn(state["sanitized_input"].sources.counselor_memo, repair_prompt)
        self.assertIn("항목별 수정 사유", repair_prompt)
        self.assertIn("session_content", repair_prompt)
        self.assertIn("새로운 개입·변화·계획을 보충하지 마세요", repair_prompt)
        self.assertEqual(repaired.session_content.text, result.session_content.text)
        self.assertIn("transcript_text", result.session_content.source_refs)

    def test_repeated_quality_failure_stops_after_two_calls_with_safe_error(self) -> None:
        rejected = _summary()
        rejected.counselor_intervention.text = "어떤 생각이 드나요? 함께 살펴볼까요?"
        llm = Mock()
        llm.invoke.side_effect = [rejected, rejected]
        with patch.object(settings, "use_stub", False), patch.object(settings, "openai_api_key", "synthetic-key"), patch(
            "app.graph.nodes.get_structured_llm", return_value=llm
        ):
            with self.assertRaises(SummaryQualityError) as caught:
                generate_summary(_state())
        self.assertEqual(2, llm.invoke.call_count)
        self.assertNotIn("어떤 생각", str(caught.exception))
        self.assertNotIn("시험", str(caught.exception))
        self.assertIn("입력 자료는 유지", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
