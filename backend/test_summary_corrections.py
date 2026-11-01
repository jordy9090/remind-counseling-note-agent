"""Actual edits, bounded re-verification and safe failure for summary corrections."""
import unittest
from unittest.mock import Mock, patch

from app.core.config import settings
from app.graph.nodes import _source_catalog, verify_output
from app.schemas.note import SessionSummaryDraft, VerificationReport
from app.services.summary_corrections import SourceRefReview, TextCorrection, correct_summary, introduced_script_fields
from app.services.summary_quality import SummaryQualityError
from app.services.summary_verification import PlanAssessment, PlanEvidence, SummaryVerification
from test_summary_quality import _state, _summary


def reviews(summary):
    return [SourceRefReview(field=field, keep_source_refs=section.source_refs)
            for field, section in summary if field != "session_info"]


class SummaryCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.state = _state()
        self.summary = _summary()
        self.catalog = _source_catalog(self.state["sanitized_input"], [])
        self.summary.next_plan.text = "[자료에서 확인되지 않음]"
        self.summary.next_plan.source_refs = []

    def test_corrects_mixed_script_token_without_changing_other_wording(self):
        self.summary.session_content.text = "연락 일정과 개인 메시지 결정은 अलग개로 나누어 봄."
        edit = TextCorrection(field="session_content", original="अलग개로", replacement="별개로")
        candidate, changed = correct_summary(self.summary, [edit], reviews(self.summary), self.catalog)
        self.assertEqual("연락 일정과 개인 메시지 결정은 별개로 나누어 봄.", candidate.session_content.text)
        self.assertEqual(["session_content"], changed)
        self.assertIn("अलग개로", self.summary.session_content.text, "candidate edits are atomic")

    def test_valid_source_foreign_wording_is_preserved(self):
        self.catalog["counselor_memo"] = "내담자는 नमस्ते 라고 적었다고 말함."
        self.summary.session_content.text = "내담자는 “नमस्ते”라고 적었다고 말함."
        self.summary.session_content.source_refs = ["counselor_memo"]
        self.assertEqual([], introduced_script_fields(self.summary, self.catalog))
        candidate, changed = correct_summary(self.summary, [], reviews(self.summary), self.catalog)
        self.assertEqual([], changed)
        self.assertEqual(self.summary.session_content.text, candidate.session_content.text)

    def test_drops_only_unnecessary_refs_without_rewriting_quote_or_claim(self):
        self.summary.session_theme.text = '내담자는 “잠이 안 와요.”라고 말함.'
        self.summary.session_theme.source_refs = ["transcript.turn_1", "transcript.turn_4"]
        decisions = reviews(self.summary)
        next(item for item in decisions if item.field == "session_theme").keep_source_refs = ["transcript.turn_1"]
        candidate, changed = correct_summary(self.summary, [], decisions, self.catalog)
        self.assertEqual(["transcript.turn_1"], candidate.session_theme.source_refs)
        self.assertEqual(self.summary.session_theme.text, candidate.session_theme.text)
        self.assertEqual(["session_theme"], changed)

    def test_rejects_missing_unknown_empty_and_quote_breaking_reference_decisions(self):
        self.summary.session_theme.text = '내담자는 “잠이 안 와요.”라고 말함.'
        self.summary.session_theme.source_refs = ["transcript.turn_1", "transcript.turn_4"]
        for keep in ([], ["transcript.turn_4"], ["unknown"], ["transcript.turn_2"]):
            with self.subTest(keep=keep):
                decisions = reviews(self.summary)
                next(item for item in decisions if item.field == "session_theme").keep_source_refs = keep
                with self.assertRaises(SummaryQualityError):
                    correct_summary(self.summary, [], decisions, self.catalog)
        with self.assertRaises(SummaryQualityError):
            correct_summary(self.summary, [], [], self.catalog)

    def test_rejects_quote_edits_missing_spans_numbers_and_sentence_rewrites(self):
        for text, original, replacement in (
            ('내담자는 “유치하죠”라고 말함.', '유치하죠', '유치해요'),
            ('내담자는 서운함을 보고함.', '없음', '있음'),
            ('내담자는 3회를 말함.', '3회', '4회'),
            ('내담자가 안 보내겠다고 함.', '안 보내겠다고', '보냈다고'),
        ):
            with self.subTest(original=original):
                self.summary.session_content.text = text
                with self.assertRaises(SummaryQualityError):
                    correct_summary(self.summary, [TextCorrection(field="session_content", original=original, replacement=replacement)], reviews(self.summary), self.catalog)

    def test_unresolved_introduced_script_is_not_returned_as_a_review_warning(self):
        self.summary.session_content.text = "두 결정은 अलग개로 나눔."
        with self.assertRaises(SummaryQualityError):
            correct_summary(self.summary, [], reviews(self.summary), self.catalog)

    def test_pipeline_rechecks_actual_candidate_once_and_returns_only_final_report(self):
        self.summary.session_content.text = "두 결정은 अलग개로 나눔."
        self.state["session_summary_draft"] = self.summary
        first = SummaryVerification(source_ref_reviews=reviews(self.summary), text_corrections=[
            TextCorrection(field="session_content", original="अलग개로", replacement="별개로"),
        ])
        final = SummaryVerification(source_ref_reviews=reviews(self.summary), correction_validated=True)
        invoke = Mock(side_effect=[first, final])
        with patch.object(settings, "use_stub", False), patch("app.graph.nodes.get_structured_llm", return_value=Mock(invoke=invoke)):
            result = verify_output(self.state)
        self.assertEqual(2, invoke.call_count)
        self.assertEqual("두 결정은 별개로 나눔.", result["session_summary_draft"].session_content.text)
        self.assertIn("single final validation", invoke.call_args.args[0])
        self.assertIs(type(result["verification_report"]), VerificationReport)
        self.assertEqual(set(VerificationReport.model_fields), set(result["verification_report"].model_dump()))

    def test_recheck_cannot_loop_or_accept_unvalidated_edit(self):
        self.summary.session_content.text = "두 결정은 अलग개로 나눔."
        self.state["session_summary_draft"] = self.summary
        first = SummaryVerification(source_ref_reviews=reviews(self.summary), text_corrections=[
            TextCorrection(field="session_content", original="अलग개로", replacement="별개로"),
        ])
        for final in (
            SummaryVerification(source_ref_reviews=reviews(self.summary)),
            SummaryVerification(source_ref_reviews=reviews(self.summary), correction_validated=True,
                                text_corrections=[TextCorrection(field="session_content", original="별개로", replacement="따로")]),
        ):
            with self.subTest(validated=final.correction_validated):
                invoke = Mock(side_effect=[first, final])
                with patch.object(settings, "use_stub", False), patch("app.graph.nodes.get_structured_llm", return_value=Mock(invoke=invoke)):
                    with self.assertRaises(SummaryQualityError): verify_output(self.state)
                self.assertEqual(2, invoke.call_count)
                self.assertIn("अलग개로", self.summary.session_content.text)

    def test_supported_plan_anchor_cannot_restore_a_removed_reference(self):
        from app.services.summary_verification import apply_summary_verification
        self.summary.next_plan = _summary().next_plan
        self.summary.next_plan.source_refs = ["transcript.turn_4"]
        assessment = SummaryVerification(source_ref_reviews=reviews(self.summary), next_plan_assessment=PlanAssessment(
            status="supported_future", evidence=[PlanEvidence(source_ref="transcript.turn_4", quote="다음 회기에")],
        ))
        apply_summary_verification(self.summary, assessment, self.catalog)
        self.assertEqual(["transcript.turn_4"], self.summary.next_plan.source_refs)


if __name__ == "__main__":
    unittest.main()
