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

    def test_continued_method_keeps_prior_definition_and_current_agreement(self):
        current = "다음 주에도 같은 방법을 두 번 시도할게요."
        prior = "4초 들이마시고 6초 내쉬는 호흡을 세 번"
        ref = "stored_session_note:synthetic-prior"
        self.catalog.update({"transcript.turn_6": current, ref: prior})
        plan = self.summary.next_plan
        plan.text = "이전 회기의 4초 들이마시고 6초 내쉬는 호흡을 세 번 하는 방법을 다음 주 두 번 시도하기로 함."
        plan.source_refs = ["transcript.turn_6"]
        assessment = SummaryVerification(next_plan_assessment=PlanAssessment(
            status="supported_future", evidence=[PlanEvidence(source_ref="transcript.turn_6", quote=current)],
            prior_context_evidence=[PlanEvidence(source_ref=ref, quote=prior)]))
        before = plan.text
        apply_summary_verification(self.summary, assessment, self.catalog)
        self.assertEqual(before, plan.text)
        self.assertEqual(["transcript.turn_6", ref], plan.source_refs)
        self.assertEqual("mixed", plan.evidence_type)

    def test_historical_definition_never_substitutes_for_current_agreement(self):
        ref = "stored_session_note:synthetic-prior"
        self.catalog[ref] = "4초 들이마시고 6초 내쉬는 호흡을 세 번"
        for status in ("supported_future", "not_documented", "uncertain", "in_session_only"):
            with self.subTest(status=status):
                summary = _summary()
                apply_summary_verification(summary, SummaryVerification(next_plan_assessment=PlanAssessment(
                    status=status, prior_context_evidence=[PlanEvidence(source_ref=ref, quote=self.catalog[ref])])), self.catalog)
                self.assertEqual([], summary.next_plan.source_refs)
                self.assertTrue(summary.next_plan.requires_review)
                self.assertTrue(summary.next_plan.text.startswith("["))

    def test_forged_or_nonhistorical_definition_anchors_fail_closed(self):
        self.catalog.update({"transcript.turn_6": "같은 방법을 두 번 시도할게요.",
                             "stored_session_note:synthetic-prior": "4초 들이마시고 6초 내쉬기"})
        for ref, quote in (("stored_session_note:synthetic-prior", "5초 들이마시기"),
                           ("stored_session_note:missing", "4초 들이마시기"),
                           ("transcript.turn_6", "같은 방법을 두 번 시도할게요."),
                           ("stored_session_note:synthetic-prior", "")):
            with self.subTest(ref=ref, quote=quote):
                summary = _summary()
                apply_summary_verification(summary, SummaryVerification(next_plan_assessment=PlanAssessment(
                    status="supported_future", evidence=[PlanEvidence(source_ref="transcript.turn_6", quote=self.catalog["transcript.turn_6"])],
                    prior_context_evidence=[PlanEvidence(source_ref=ref, quote=quote)])), self.catalog)
                self.assertEqual("[다음 계획은 원문 확인 필요]", summary.next_plan.text)
                self.assertEqual([], summary.next_plan.source_refs)

    def test_changed_or_stopped_plan_does_not_keep_unvalidated_history(self):
        ref = "stored_session_note:synthetic-prior"
        self.catalog[ref] = "4초 들이마시고 6초 내쉬기"
        for text in ("이번 주에는 호흡 과제를 중단하기로 함.", "2초 들이마시고 5초 내쉬기를 한 번만 하기로 함."):
            with self.subTest(text=text):
                summary = _summary()
                self.catalog["counselor_memo"] = text
                summary.next_plan.text = text
                summary.next_plan.source_refs = ["counselor_memo", ref]
                apply_summary_verification(summary, SummaryVerification(next_plan_assessment=PlanAssessment(
                    status="supported_future", evidence=[PlanEvidence(source_ref="counselor_memo", quote=text)])), self.catalog)
                self.assertEqual(text, summary.next_plan.text)
                self.assertEqual(["counselor_memo"], summary.next_plan.source_refs)

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

    def test_named_warning_does_not_spread_to_similarly_worded_sections(self):
        text = "내담자는 친구의 연락을 기다리며 답답함을 느꼈다고 말함."
        self.summary.session_content.text = text
        self.summary.client_response.text = text
        report = VerificationReport(unsupported_or_risky_claims=[ReviewableClaim(
            claim="client_response: " + text, reason="The response timing is uncertain.",
            recommendation="Review the response field.",
        )])
        _apply_verification_consistency(self.summary, report)
        self.assertTrue(self.summary.client_response.requires_review)
        self.assertFalse(self.summary.session_content.requires_review)

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



class SummaryV2VerificationTests(unittest.TestCase):
    def test_versionless_payload_is_v1_even_when_runtime_is_v2(self):
        from pydantic import TypeAdapter, ValidationError
        from app.schemas.note import SessionSummary, SessionSummaryDraft
        from test_summary_quality import _summary_v2
        adapter = TypeAdapter(SessionSummary)
        with patch.object(settings, "summary_schema_version", "v2"):
            loaded = adapter.validate_python(_summary().model_dump())
            self.assertIsInstance(loaded, SessionSummaryDraft)
            self.assertEqual("v1", loaded.schema_version)
            with self.assertRaises(ValidationError):
                adapter.validate_python(_summary_v2().model_dump(exclude={"schema_version"}))
            with self.assertRaises(ValidationError):
                adapter.validate_python({**_summary().model_dump(), "schema_version": "v3"})

    def test_converter_merges_only_first_episode_and_preserves_metadata_without_aliases(self):
        from test_summary_quality import _summary_v2, _section
        from app.schemas.note import summary_v2_to_v1
        summary = _summary_v2()
        summary.episodes.items.append(_section("두 번째 사건", "transcript.turn_9"))
        summary.episodes.requires_review = True
        summary.client_reactions.requires_review = True
        adapted = summary_v2_to_v1(summary)
        self.assertEqual(summary.presenting_concern.text + "\n" + summary.episodes.items[0].text,
                         adapted.presenting_problem.text)
        self.assertEqual(["transcript.turn_1", "transcript.turn_2"], adapted.presenting_problem.source_refs)
        self.assertTrue(adapted.presenting_problem.requires_review)
        self.assertEqual("\n".join(item.text for item in summary.client_reactions.items), adapted.client_response.text)
        self.assertTrue(adapted.client_response.requires_review)
        self.assertEqual(summary.next_plan.model_dump(), adapted.next_plan.model_dump())
        adapted.next_plan.text = "changed"
        self.assertNotEqual("changed", summary.next_plan.text)
        self.assertNotIn("client_understanding", adapted.model_dump())
        self.assertEqual("v1", adapted.schema_version)
        self.assertNotIn("schema_version", adapted.model_dump())

    def test_verifier_uses_adapter_and_retains_v2_with_plan_and_diagnosis_warnings(self):
        from test_summary_quality import _state_v2, _summary_v2
        from app.services.summary_verification import SummaryAssessment
        state, summary = _state_v2(), _summary_v2()
        summary.client_understanding.text = "우울증 때문이다."
        summary.client_reactions.items[0].text = "일치하지 않는 인용"
        summary.next_plan.text = "앉아 있기로 함."
        state["session_summary_draft"] = summary
        assessment = SummaryAssessment(next_plan_assessment=PlanAssessment(status="in_session_only"))
        with patch.object(settings, "use_stub", False), patch("app.graph.nodes.get_structured_llm",
                return_value=Mock(invoke=Mock(return_value=assessment))) as provider:
            result = verify_output(state)
        provider.assert_called_once_with(SummaryAssessment)
        prompt = provider.return_value.invoke.call_args.args[0]
        self.assertIn('"presenting_problem"', prompt)
        self.assertIn('"client_understanding"', prompt)
        self.assertEqual("v2", result["session_summary_draft"].schema_version)
        self.assertEqual(3, len(summary.client_reactions.items))
        self.assertTrue(summary.client_reactions.requires_review)
        self.assertEqual("[자료에서 확인되지 않음]", summary.next_plan.text)
        fields = {item.field for item in result["verification_report"].requires_counselor_review}
        self.assertTrue({"client_understanding", "client_reactions", "next_plan"} <= fields)
        self.assertTrue(result["verification_report"].unsupported_or_risky_claims)

    def test_documents_and_supervision_consume_legacy_adapter_without_erasing_v2(self):
        from test_summary_quality import _state_v2, _summary_v2
        from app.schemas.note import SupervisionReportRequest, summary_v2_to_v1
        from app.graph.supervision_report import run_supervision_report_pipeline
        from app.graph.graph import _build_confirmed_session_note
        state, summary = _state_v2(), _summary_v2()
        state["session_summary_draft"] = summary
        state["session_input"] = SessionInput(
            case_id="SYNTH-SUMMARY", session_number=1, counselor_memo="", transcript_text="", insight_lens="none")
        state["verification_report"] = VerificationReport()
        result = transform_document_preview(state)
        self.assertIs(summary, result["session_summary_draft"])
        adapted = summary_v2_to_v1(summary)
        self.assertEqual(adapted.presenting_problem.text, result["session_note_draft"].sections["주호소/핵심 문제"])
        self.assertEqual(adapted.client_response.text, result["session_note_draft"].sections["내담자 반응"])
        confirmed = _build_confirmed_session_note({**state, **result})
        self.assertEqual(adapted.client_response.text, confirmed["sections"]["client_response"])
        report = run_supervision_report_pipeline(SupervisionReportRequest(
            session_input=state["session_input"], session_summary_draft=summary))
        self.assertIn("두려웠어요", report.model_dump_json())
        self.assertNotIn(summary.client_understanding.text, report.model_dump_json())

    def test_v1_and_v2_are_persisted_and_versionless_records_read_as_v1(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from test_persistence_workflow import INPUT, TOKEN, offline_environment
        for version in ("v1", "v2"):
            with self.subTest(version=version), offline_environment() as store, \
                    patch.object(settings, "summary_schema_version", version):
                client = TestClient(app)
                response = client.post("/api/notes/generate", json={**INPUT, "insight_lens": "none"},
                                       headers={"Authorization": "Bearer " + TOKEN})
                self.assertEqual(200, response.status_code)
                stored = store.tables["generated_notes"][0]
                self.assertEqual(version, stored["draft_json"]["schema_version"])
                draft = response.json()["session_summary_draft"]
                if version == "v1":
                    self.assertNotIn("schema_version", draft)
                    stored["draft_json"].pop("schema_version")
                else:
                    self.assertEqual("v2", draft["schema_version"])
                    self.assertIn("client_understanding", stored["draft_json"])
                reopened = client.get("/api/notes/records/" + stored["id"], headers={"Authorization": "Bearer " + TOKEN})
                self.assertEqual(200, reopened.status_code)
                self.assertEqual(version, reopened.json()["draft_json"]["schema_version"])


if __name__ == "__main__":
    unittest.main()
