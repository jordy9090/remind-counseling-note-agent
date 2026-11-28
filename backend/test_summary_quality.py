"""Regression tests for session-summary prose and its single repair attempt."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from app.core.config import settings
from app.graph.nodes import generate_summary, _build_summary_prompt
from app.schemas.note import (
    EvidenceMappedData,
    EvidenceMappedItem,
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
    def test_generated_metadata_is_bound_to_the_authoritative_session(self) -> None:
        state = _state()
        state["sanitized_input"].client_alias = "SYNTHETIC-ALIAS"
        state["sanitized_input"].counselor_name = "SYNTHETIC-COUNSELOR"
        generated = _summary()
        generated.session_info = SessionInfo(case_id="MODEL-INVENTED-CASE", session_number=99,
            session_date="1900-01-01", client_alias="MODEL-ALIAS", counselor_name="MODEL-NAME")
        with patch.multiple(settings, use_stub=False, openai_api_key="synthetic-key"), patch(
            "app.graph.nodes.get_structured_llm", return_value=Mock(invoke=Mock(return_value=generated)),
        ):
            result = generate_summary(state)["session_summary_draft"]
        self.assertEqual({key: getattr(state["sanitized_input"], key) for key in SessionInfo.model_fields},
                         result.session_info.model_dump())

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
        for text in ("걱정을 표현함. " * 6, "걱정" * 301):
            with self.subTest(length=len(text)):
                summary = _summary()
                summary.session_content.text = text
                self.assertIn("session_content", summary_quality_issues(summary))

    def test_length_targets_are_not_hard_cuts_or_minimums(self) -> None:
        summary = _summary()
        summary.session_content.text = "준비 과정을 돌아보며 " * 25 + "걱정이 남아 있음을 표현함."
        original = summary.session_content.text
        self.assertGreater(len(original), 240)
        self.assertEqual({}, summary_quality_issues(summary))
        self.assertEqual(original, summary.session_content.text)

    def test_multiple_agreed_plans_keep_conditions_without_truncation(self) -> None:
        # Actual synthetic B generation: previously rejected solely at 278 chars.
        summary = _summary()
        summary.next_plan.text = (
            "오늘 집에 가서 단체방에는 책 수령과 관련해 자신의 가능한 시간만 답하고, 개인 메시지 초안은 내일 수영 후 "
            "저녁을 먹은 뒤 아홉 시쯤 다시 읽어 보내기·수정하기·더 기다리기 중 하나를 정한 뒤 이유를 한 줄 남기기로 했다. "
            "이번 주에 비슷한 일이 자연스럽게 생기면 한 번만 사실과 자신의 해석을 두 줄로 적고, 몸 느낌은 떠오르면 "
            "덧붙일 수 있으나 필수는 아니며, 다음 주 수요일 7시에 만나 초안 발송 여부와 답이 왔을 경우 그 내용을 "
            "어떻게 받아들였는지, 답이 없으면 없는 대로 보기로 했다."
        )
        original = summary.next_plan.text
        self.assertGreater(len(original), 250)
        self.assertEqual({}, summary_quality_issues(summary))
        self.assertEqual(original, summary.next_plan.text)
        summary.next_plan.text = original + " 다음 회기에 별도 계획을 확인함." * 2
        self.assertEqual({}, summary_quality_issues(summary))
        for extra in (" 추가 계획을 제안함." * 3, " 추가 내용" * 20):
            summary.next_plan.text = original + extra
            self.assertIn("next_plan", summary_quality_issues(summary))

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
        outline = repair_prompt.split("유지할 항목과 재작성 대상", 1)[1]
        self.assertNotIn(rejected.session_content.text, outline)
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

    def test_summary_prompt_keeps_sources_without_repeating_extracted_dialogue(self) -> None:
        state = _state()
        state["evidence_mapped_data"].items = [EvidenceMappedItem(
            field="client_response", content="SYNTHETIC-EXTRACTION-COPY", evidence_type="direct",
            source_refs=["transcript.turn_2"],
        )]
        prompt = _build_summary_prompt(state["sanitized_input"], state["structured_case_data"], state["evidence_mapped_data"])
        self.assertNotIn("SYNTHETIC-EXTRACTION-COPY", prompt)
        self.assertIn("transcript.turn_2", prompt)
        self.assertEqual(1, prompt.count("빠뜨린 내용이 있을까 걱정돼요."))

    def test_recorded_counselor_wish_survives_without_a_reflection_heading(self) -> None:
        state = _state()
        state["sanitized_input"].sources.counselor_memo = (
            "답답하지 않다고 바로 안심시켜주고 싶은 마음이 들었고, 침묵에 대해 해명하고 싶은 마음도 들었음."
        )
        summary = _summary()
        summary.reflection = SummarySection(
            text="상담자는 바로 안심시키고 침묵을 해명하고 싶은 마음이 들었다고 기록함.",
            evidence_type="counselor_input", source_refs=["counselor_memo"], requires_review=True,
        )
        llm = Mock()
        llm.invoke.return_value = summary
        with patch.object(settings, "use_stub", False), patch.object(settings, "openai_api_key", "synthetic-key"), patch(
            "app.graph.nodes.get_structured_llm", return_value=llm
        ):
            result = generate_summary(state)["session_summary_draft"]
        self.assertEqual(summary.reflection.text, result.reflection.text)
        self.assertIn("counselor_memo", result.reflection.source_refs)



def _state_v2() -> dict:
    state = _state()
    state["sanitized_input"].sources.transcript_text = (
        "내담자: 내가 못나 보여요. 편하게 말하고 싶어요.\n"
        "내담자: 어제 친구와 대화하다가 대답이 없어 입을 다물었어요.\n"
        "상담자: 그때 어떤 느낌이었나요?\n"
        "내담자: 두려웠어요.\n"
        "내담자: 아직은 말하기 힘들어요."
    )
    return state


def _summary_v2():
    from app.schemas.note import SessionSummaryV2, SummarySectionGroup
    legacy = _summary()
    shared = {name: getattr(legacy, name).model_copy(deep=True) for name in (
        "session_info", "session_theme", "session_content", "counselor_intervention", "reflection", "next_plan",
    )}
    shared["next_plan"] = SummarySection(text="[자료에서 확인되지 않음]", evidence_type="needs_review", requires_review=True)
    return SessionSummaryV2(
        **shared,
        presenting_concern=_section('"내가 못나 보여요." 내담자는 편하게 말하고 싶다는 바람을 표현함.', "transcript.turn_1"),
        episodes=SummarySectionGroup(items=[_section(
            "어제 친구와 대화 중 대답이 없어 입을 다물었다고 보고함.", "transcript.turn_2")]),
        client_reactions=SummarySectionGroup(items=[
            _section("내가 못나 보여요.", "transcript.turn_1"),
            _section("대답이 없어 입을 다물었어요.", "transcript.turn_2"),
            _section("두려웠어요.", "transcript.turn_4"),
            _section("아직은 말하기 힘들어요.", "transcript.turn_5"),
        ]),
        client_understanding=_section(
            "대답이 없을 때 입을 다무는 모습이 있다. 그때 두려운 감정이었을 수 있다. "
            "말하기 어려웠다는 표현에서 멈춘 반응이 이해될 수 있다.", "transcript.turn_2"),
    )


class SummaryV2QualityTests(unittest.TestCase):
    def test_four_verbatim_reactions_are_exempt_from_prose_and_quote_limits(self):
        from app.services.summary_quality import summary_quote_issues, enforce_summary_v2
        from app.graph.nodes import _source_catalog
        summary = _summary_v2()
        catalog = _source_catalog(_state_v2()["sanitized_input"], [])
        enforce_summary_v2(summary, catalog)
        self.assertEqual(4, len(summary.client_reactions.items))
        self.assertFalse(summary.client_reactions.requires_review)
        self.assertEqual({}, summary_quality_issues(summary))
        self.assertEqual({}, summary_quote_issues(summary, catalog))
        self.assertTrue(summary.client_understanding.requires_review)

    def test_mismatched_reaction_is_removed_without_repairing_its_words(self):
        from app.services.summary_quality import enforce_summary_v2, REACTION_WARNING
        from app.graph.nodes import _source_catalog
        catalog = _source_catalog(_state_v2()["sanitized_input"], [])
        cases = [
            ("못나 보인다.", ["transcript.turn_1"]),
            ("내가 못나 보여요.", ["transcript.turn_2"]),
            ("내가 못나 보여요.", ["transcript_text"]),
            ("내가 못나 보여요.", ["transcript.turn_1", "transcript.turn_1"]),
            ("내가 못나 보여요.", ["transcript.turn_999"]),
            ("그때 어떤 느낌이었나요?", ["transcript.turn_3"]),
            ("내가못나 보여요.", ["transcript.turn_1"]),
            ("내가 못나 보여요.\n두려웠어요.", ["transcript.turn_1"]),
            ("", ["transcript.turn_1"]),
        ]
        for text, refs in cases:
            with self.subTest(text=text, refs=refs):
                summary = _summary_v2()
                summary.client_reactions.items[0].text = text
                summary.client_reactions.items[0].source_refs = refs
                enforce_summary_v2(summary, catalog)
                self.assertEqual(3, len(summary.client_reactions.items))
                self.assertTrue(summary.client_reactions.requires_review)
                self.assertIn(REACTION_WARNING, summary.warnings)
                self.assertNotIn("transcript.turn_1", summary.client_reactions.source_refs)
                enforce_summary_v2(summary, catalog)
                self.assertEqual([REACTION_WARNING], summary.warnings)

    def test_understanding_warns_on_diagnoses_and_categorical_explanations(self):
        from app.services.summary_quality import enforce_summary_v2, UNDERSTANDING_WARNING
        for text in ("우울증이다.", "관계 때문이다.", "회피성 성격이다.", "불안장애가 있다.", "ADHD다."):
            with self.subTest(text=text):
                summary = _summary_v2()
                summary.client_understanding.text = text
                summary.client_understanding.requires_review = False
                enforce_summary_v2(summary, {})
                self.assertTrue(summary.client_understanding.requires_review)
                self.assertIn(UNDERSTANDING_WARNING, summary.warnings)

    def test_regular_generation_selects_v2_schema_and_keeps_local_identity(self):
        from app.schemas.note import SessionSummaryV2
        candidate = _summary_v2()
        candidate.session_info.case_id = "SYNTH-UNTRUSTED"
        candidate.client_reactions.items[0].text = "지어낸 반응"
        provider = Mock(invoke=Mock(return_value=candidate))
        with patch.object(settings, "summary_schema_version", "v2"), patch.object(settings, "use_stub", False), \
                patch("app.graph.nodes.get_structured_llm", return_value=provider) as setup:
            result = generate_summary(_state_v2())["session_summary_draft"]
        setup.assert_called_once_with(SessionSummaryV2)
        self.assertEqual("SYNTH-SUMMARY", result.session_info.case_id)
        self.assertEqual(3, len(result.client_reactions.items))
        self.assertNotIn("아래 7개", provider.invoke.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
