"""Failure-path tests for temporal scope, literal quotes and review alignment."""
import unittest
from unittest.mock import Mock, patch

from app.core.config import settings
from app.graph.nodes import _apply_verification_consistency, _source_catalog, transform_document_preview, verify_output
from app.schemas.note import CounselorReviewField, GroundedItem, ReviewableClaim, SessionInput, VerificationReport
from app.services.summary_verification import PlanAssessment, PlanEvidence, SummaryVerification, apply_summary_verification
from app.services.summary_corrections import SourceRefReview
from test_summary_quality import _state, _summary


class SummaryVerificationTests(unittest.TestCase):
    def setUp(self):
        self.state = _state()
        self.summary = _summary()
        self.catalog = _source_catalog(self.state["sanitized_input"], [])

    def test_c_in_session_response_cannot_remain_a_future_plan(self):
        self.summary.next_plan.text = "앉은 자세로 상담을 진행하기로 함."
        self.summary.next_plan.source_refs = ["transcript.turn_3"]
        self.state["sanitized_input"].sources.transcript_text = (
            "상담자: 잠깐 일어나서 해볼까요?\n내담자: 서서 하는 건 싫어요.\n상담자: 네. 앉아 있을게요."
        )
        self.state["session_summary_draft"] = self.summary
        assessment = SummaryVerification(next_plan_assessment=PlanAssessment(status="in_session_only"), source_ref_reviews=[
            SourceRefReview(field=field, keep_source_refs=section.source_refs)
            for field, section in self.summary if field != "session_info"
        ])
        with patch.object(settings, "use_stub", False), patch("app.graph.nodes.get_structured_llm", return_value=Mock(invoke=Mock(return_value=assessment))) as llm:
            result = verify_output(self.state)
        llm.assert_called_once()
        self.assertTrue(issubclass(llm.call_args.args[0], SummaryVerification))
        self.assertEqual("[자료에서 확인되지 않음]", self.summary.next_plan.text)
        self.assertEqual([], self.summary.next_plan.source_refs)
        self.assertTrue(self.summary.next_plan.requires_review)
        self.assertIs(type(result["verification_report"]), VerificationReport)
        self.assertNotIn("next_plan_assessment", result["verification_report"].model_dump())

    def test_conditional_future_plan_keeps_conditions_and_exact_evidence(self):
        quote = "내일 다시 읽고, 그때도 못 보내겠으면 안 보낼 수도 있어요."
        self.catalog["transcript.turn_6"] = "내담자: " + quote
        self.summary.next_plan.text = "내담자는 내일 다시 읽고 보낼지 결정하되 보내지 않을 수도 있다고 말함."
        assessment = SummaryVerification(next_plan_assessment=PlanAssessment(status="supported_future", evidence=[
            PlanEvidence(source_ref="transcript.turn_6", quote=quote),
        ]))
        before = self.summary.next_plan.text
        apply_summary_verification(self.summary, assessment, self.catalog)
        self.assertEqual(before, self.summary.next_plan.text)
        self.assertEqual(["transcript.turn_6"], self.summary.next_plan.source_refs)

    def test_missing_fabricated_prior_or_whole_transcript_anchors_fail_closed(self):
        for evidence in ([], [PlanEvidence(source_ref="transcript.turn_4", quote="동의했어요.")],
                         [PlanEvidence(source_ref="previous_session_summary", quote="다음 회기")],
                         [PlanEvidence(source_ref="transcript_text", quote="다음 회기")]):
            with self.subTest(evidence=evidence):
                summary = _summary()
                report = apply_summary_verification(summary, SummaryVerification(next_plan_assessment=PlanAssessment(
                    status="supported_future", evidence=evidence,
                )), self.catalog)
                self.assertEqual("[다음 계획은 원문 확인 필요]", summary.next_plan.text)
                self.assertEqual([], summary.next_plan.source_refs)
                self.assertTrue(report.requires_counselor_review)

    def test_plan_retains_conditions_when_generic_refs_omit_acceptance(self):
        self.catalog = {
            "transcript.turn_1": "상담자: 내일 초안을 읽고 보내기, 수정하기, 기다리기 중 골라 이유 한 줄을 남겨볼까요?",
            "transcript.turn_2": "내담자: 네. 보내기로 정한 건 아니고 수영과 저녁 식사 뒤 아홉 시쯤 다시 읽고 정할게요.",
            "transcript.turn_3": "내담자: 비슷한 일이 자연히 생기면 사실과 해석을 두 줄로 한 번만 적을게요. 매일 하지는 않고요.",
        }
        plan = self.summary.next_plan
        plan.text = "내일 수영·저녁 식사 후 9시쯤 초안을 읽고 발송·수정·대기 중 선택과 이유 한 줄을 남기되 발송은 미확정임. 비슷한 일이 자연히 생기면 사실·해석 두 줄을 한 번 기록하며 매일 하지는 않기로 함."
        plan.source_refs = ["transcript.turn_1", "transcript.turn_3"]
        before = plan.text
        assessment = SummaryVerification(
            source_ref_reviews=[SourceRefReview(field="next_plan", keep_source_refs=plan.source_refs)],
            next_plan_assessment=PlanAssessment(status="supported_future", evidence=[
                PlanEvidence(source_ref=ref, quote=text.split(": ", 1)[1]) for ref, text in self.catalog.items()
            ]),
        )
        report = apply_summary_verification(self.summary, assessment, self.catalog)
        self.assertEqual(before, plan.text)
        self.assertEqual(list(self.catalog), plan.source_refs)
        self.assertFalse(any(item.field == "next_plan" for item in report.requires_counselor_review))

    def test_added_plan_anchor_still_requires_literal_current_source_support(self):
        for source_ref, quote in (("transcript.turn_1", "보내기로 확정했어요."),
                                  ("previous_session_summary", "다음 회기에"),
                                  ("transcript.turn_999", "내일 읽을게요.")):
            with self.subTest(source_ref=source_ref):
                summary = _summary()
                result = SummaryVerification(
                    source_ref_reviews=[SourceRefReview(field="next_plan", keep_source_refs=summary.next_plan.source_refs)],
                    next_plan_assessment=PlanAssessment(status="supported_future", evidence=[
                        PlanEvidence(source_ref=source_ref, quote=quote)]))
                apply_summary_verification(summary, result, self.catalog)
                self.assertEqual("[다음 계획은 원문 확인 필요]", summary.next_plan.text)
                self.assertEqual([], summary.next_plan.source_refs)

    def test_bad_quote_is_removed_but_valid_quote_and_original_finding_survive(self):
        text = '내담자는 “잠이 안 와요.”라고 했고 “치료로 좋아졌어요.”라고 표현함.'
        self.summary.client_response.text = text
        self.summary.client_response.source_refs = ["transcript.turn_1"]
        report = apply_summary_verification(self.summary, SummaryVerification(grounded_items=[
            GroundedItem(claim=text, source_refs=["transcript.turn_1"]),
        ]), self.catalog)
        self.assertIn('“잠이 안 와요.”', self.summary.client_response.text)
        self.assertNotIn("치료로 좋아졌어요", self.summary.client_response.text)
        self.assertIn("[인용 원문 확인 필요]", self.summary.client_response.text)
        self.assertIn(text, [item.claim for item in report.unsupported_or_risky_claims])
        self.assertEqual([], report.grounded_items)
        self.assertTrue(self.summary.client_response.requires_review)

    def test_correct_quote_with_wrong_turn_cannot_hide_behind_whole_transcript(self):
        self.summary.client_response.text = '내담자는 “잠이 안 와요.”라고 말함.'
        self.summary.client_response.source_refs = ["transcript.turn_2", "transcript_text"]
        apply_summary_verification(self.summary, SummaryVerification(), self.catalog)
        self.assertNotIn("잠이 안 와요", self.summary.client_response.text)
        self.assertTrue(self.summary.client_response.requires_review)

    def test_field_review_does_not_depend_on_text_similarity_or_language(self):
        report = VerificationReport(requires_counselor_review=[CounselorReviewField(
            field="session_summary_draft.client_response.text", reason="The speaker is uncertain.",
        )])
        _apply_verification_consistency(self.summary, report)
        self.assertTrue(self.summary.client_response.requires_review)
        self.assertFalse(self.summary.session_content.requires_review)

    def test_unknown_placeholders_are_not_added_as_unsupported_claims(self):
        self.summary.next_plan.text = "[자료에서 확인되지 않음]"
        report = apply_summary_verification(self.summary, SummaryVerification(), self.catalog)
        self.assertEqual([], report.unsupported_or_risky_claims)

    def test_risky_claim_naming_a_field_marks_it_without_fuzzy_text_overlap(self):
        report = VerificationReport(unsupported_or_risky_claims=[ReviewableClaim(
            claim="session_theme의 '중심이었다'", reason="The excerpt does not establish session-wide importance.",
            recommendation="Counselor review required.",
        )])
        _apply_verification_consistency(self.summary, report)
        self.assertTrue(self.summary.session_theme.requires_review)
        self.assertFalse(self.summary.presenting_problem.requires_review)

    def test_termination_api_draft_and_selected_preview_never_copy_private_content(self):
        marker = "SYNTHETIC-PRIVATE-RECALL-DETAIL"
        sanitized = self.state["sanitized_input"]
        sanitized.sources.counseling_goal = marker
        sanitized.sources.previous_session_summary = marker
        for field in ("session_content", "client_response", "next_plan", "reflection", "counselor_intervention", "presenting_problem"):
            getattr(self.summary, field).text = marker
        self.state.update(session_summary_draft=self.summary, session_input=SessionInput(
            case_id="SYNTH-BOUNDARY", session_number=1, counselor_memo="", transcript_text="",
            target_document_type="termination_report", persist=False,
        ))
        result = transform_document_preview(self.state)
        termination = result["termination_report_draft"]
        self.assertNotIn(marker, termination.model_dump_json())
        self.assertNotIn(marker, result["document_transform_preview"].model_dump_json())
        self.assertTrue(all(not refs for refs in termination.source_refs.values()))
        self.assertEqual(set(termination.sections), set(termination.missing_or_review_fields))
        self.assertIn(marker, result["session_note_draft"].model_dump_json())


if __name__ == "__main__":
    unittest.main()
