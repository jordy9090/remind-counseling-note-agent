"""Offline integration contracts for the quick-only summary Skill route."""
from __future__ import annotations

from contextlib import ExitStack
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.graph import graph, nodes
from app.schemas.insight import RelationalInsights
from app.schemas.note import (
    EvidenceItem, EvidenceMappedData, GenerateNoteResponse, ReviewableClaim,
    SessionInfo, SessionInput, SessionSummaryDraft, StructuredCaseData,
)
from app.services.summary_verification import PlanAssessment, PlanEvidence, SummaryCorrectionValidation, SummaryVerification
from app.services.summary_corrections import SourceRefReview, TextCorrection
from app.services import quick_summary
from app.services.summary_skill import SummarySkillResult
from test_quick_summary import _load_vercel_generate
from test_summary_quality import _state, _summary


class SummarySkillPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(
            settings, use_stub=False, openai_api_key="synthetic-key",
            enable_rag=False, enable_raw_region_grounding=False,
            enable_persistence=False, enable_case_memory=False,
            enable_real_user_auth=True, remind_allow_local_bypass=False,
            allow_legacy_preview_token=False,
        ))
        self.stack.enter_context(patch("app.graph.nodes._storage_for_actor", return_value=Mock(configured=False)))
        self.entity_extraction = self.stack.enter_context(patch(
            "app.services.storage_deidentification._extract_entities", return_value=None,
        ))
        source = _state()["sanitized_input"]
        self.session_input = SessionInput(
            case_id=source.case_id, session_number=source.session_number,
            session_date=source.session_date, counselor_name=source.counselor_name,
            counselor_memo=source.sources.counselor_memo,
            transcript_text=source.sources.transcript_text,
            persist=False, insight_lens="none",
        )
        self.schema_calls: list[type] = []
        self.verification = SummaryVerification()
        self.structured_llm = self.stack.enter_context(patch(
            "app.graph.nodes.get_structured_llm", side_effect=self._fake_llm,
        ))
        self.verifier_prompt = self.stack.enter_context(patch(
            "app.graph.nodes._build_verification_prompt", wraps=nodes._build_verification_prompt,
        ))
        self.skill = self.stack.enter_context(patch(
            "app.services.summary_skill.run_summary_skill", side_effect=self._fake_skill,
        ))
        self.insights = self.stack.enter_context(patch(
            "app.graph.graph.generate_relational_insights",
            return_value=RelationalInsights(
                status="insufficient_evidence", supervision_memo="합성 자료의 상담사 검토가 필요함.",
            ),
        ))
        quick_summary.rate_limiter.reset()
        self.addCleanup(quick_summary.rate_limiter.reset)

    def _fake_llm(self, schema, **kwargs):
        self.schema_calls.append(SummaryVerification if issubclass(schema, SummaryVerification) else schema)
        if schema is StructuredCaseData:
            output = StructuredCaseData(session_content=[EvidenceItem(
                content="내담자는 시험 준비를 반복 확인한다고 보고함.",
                evidence_type="direct", source_refs=["transcript_text"],
            )])
        elif schema is SessionSummaryDraft:
            output = _summary()
        elif issubclass(schema, SummaryVerification):
            output = self.verification.model_copy(deep=True)
            output.source_ref_reviews = [SourceRefReview(field=field, keep_source_refs=section.source_refs)
                                         for field, section in _summary() if field != "session_info"]
            output.next_plan_assessment = PlanAssessment(status="supported_future", evidence=[
                PlanEvidence(source_ref="transcript.turn_4", quote="다음 회기에 시험 전날의 걱정을 다시 살펴볼까요?"),
            ])
        else:
            raise AssertionError(f"Unexpected model schema: {schema.__name__}")
        return Mock(invoke=Mock(return_value=output))

    def _fake_skill(self, sanitized):
        summary = _summary()
        summary.session_info = SessionInfo(
            case_id=sanitized.case_id, session_number=sanitized.session_number,
            session_date=sanitized.session_date, client_alias=sanitized.client_alias,
            counselor_name=sanitized.counselor_name,
        )
        return SummarySkillResult(
            summary=summary, skill_sha256="synthetic-skill-sha", model_calls=1,
            latency_ms=17, usage={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
            response_model="synthetic-model",
        )

    def test_quick_nonstub_uses_skill_once_and_preserves_independent_verification(self) -> None:
        claim = _summary().client_response.text
        self.verification = SummaryVerification(unsupported_or_risky_claims=[ReviewableClaim(
            claim=claim, reason="합성 검증에서 표현의 근거를 재확인해야 함.", recommendation="상담사 검토 필요",
        )])
        response = quick_summary.generate_quick_summary(self.session_input.transcript_text)
        self.skill.assert_called_once()
        self.assertEqual([SummaryVerification], self.schema_calls)
        self.verifier_prompt.assert_called_once()
        sanitized, extracted, mapped, summary, _privacy = self.verifier_prompt.call_args.args
        self.assertEqual(self.skill.call_args.args[0], sanitized)
        self.assertEqual(self.session_input.transcript_text, sanitized.sources.transcript_text)
        self.assertEqual(StructuredCaseData(), extracted)
        self.assertEqual(EvidenceMappedData(), mapped)
        self.assertEqual(_summary().session_content.text, summary.session_content.text)
        self.assertEqual(StructuredCaseData(), response.structured_case_data)
        self.assertEqual(EvidenceMappedData(), response.evidence_mapped_data)
        self.assertFalse(response.stub)
        self.assertFalse(response.retrieval_report.enabled)
        self.assertGreaterEqual(response.retrieval_report.generation_latency_ms, 17)
        self.insights.assert_called_once()
        self.assertEqual("insufficient_evidence", response.relational_insights.status)
        self.assertIsNotNone(response.document_transform_preview)
        self.assertIsNotNone(response.session_note_draft)
        self.assertEqual([claim], [item.claim for item in response.verification_report.unsupported_or_risky_claims])
        self.assertTrue(response.session_summary_draft.client_response.requires_review)
        self.assertEqual(1, response.confirmed_session_note["review_summary"]["risky_claim_count"])

    def test_standard_pipeline_still_extracts_summarizes_and_verifies(self) -> None:
        response = graph.run_note_pipeline(self.session_input, allow_retrieval=False)
        self.skill.assert_not_called()
        self.assertEqual([StructuredCaseData, SessionSummaryDraft, SummaryVerification], self.schema_calls)
        self.assertEqual(1, len(response.structured_case_data.session_content))
        self.assertEqual(1, len(response.evidence_mapped_data.items))
        self.verifier_prompt.assert_called_once()
        self.assertFalse(response.stub)

    def test_explicit_stub_keeps_legacy_path_without_skill_or_model_calls(self) -> None:
        with patch.object(settings, "use_stub", True):
            response = graph.run_note_pipeline(
                self.session_input, allow_retrieval=False, use_summary_skill=True,
            )
        self.skill.assert_not_called()
        self.structured_llm.assert_not_called()
        self.assertTrue(response.stub)
        self.assertTrue(response.structured_case_data.session_content)
        self.assertTrue(response.evidence_mapped_data.items)

    def test_skill_scope_guard_rejects_unsupported_callers_before_graph_execution(self) -> None:
        scenarios = (
            ({}, {"allow_retrieval": True}),
            ({"persist": True}, {}),
            ({"previous_session_summary": "이전 회기의 합성 요약"}, {}),
            ({}, {"requested_section_ids": ["session_content"]}),
            ({}, {"session_topic": "합성 사용자 지정 주제"}),
            ({"target_document_type": "supervision_report"}, {}),
            ({"target_document_type": "termination_report"}, {}),
        )
        with patch.object(graph.note_graph, "invoke") as invoke:
            for input_changes, option_changes in scenarios:
                with self.subTest(input_keys=list(input_changes), option_keys=list(option_changes)):
                    options = {"allow_retrieval": False, "use_summary_skill": True, **option_changes}
                    with self.assertRaises(ValueError):
                        graph.run_note_pipeline(self.session_input.model_copy(update=input_changes), **options)
            invoke.assert_not_called()
        self.skill.assert_not_called()
        self.structured_llm.assert_not_called()

    def test_vercel_public_route_retains_full_response_and_regular_auth_boundary(self) -> None:
        module = _load_vercel_generate()
        original_overrides = module.app.dependency_overrides.copy()
        module.app.dependency_overrides.clear()
        self.addCleanup(lambda: setattr(module.app, "dependency_overrides", original_overrides))
        with TestClient(module.app) as client:
            response = client.post(
                "/api/notes/generate?scope=quick", json={"text": self.session_input.transcript_text},
            )
            self.assertEqual(200, response.status_code)
            parsed = GenerateNoteResponse.model_validate(response.json())
            for name in (
                "presenting_problem", "session_theme", "session_content", "counselor_intervention",
                "client_response", "next_plan", "reflection",
            ):
                self.assertTrue(getattr(parsed.session_summary_draft, name).text)
            # These payload fields supply the existing risk and supervision UI sections.
            self.assertIn("위험 관련 확인 가능 정보", parsed.session_note_draft.sections)
            self.assertTrue(parsed.relational_insights.supervision_memo)
            self.assertIsNotNone(parsed.verification_report)
            self.assertFalse(parsed.stub)
            denied = client.post("/api/notes/generate", json=self.session_input.model_dump(mode="json"))
            self.assertEqual(401, denied.status_code)
        self.skill.assert_called_once()
        self.assertEqual([SummaryVerification], self.schema_calls)
        self.insights.assert_called_once()

    def test_vercel_skill_failure_is_safe_502_without_legacy_fallback(self) -> None:
        self.skill.side_effect = RuntimeError("SYNTHETIC-PRIVATE-PROVIDER-DETAIL")
        module = _load_vercel_generate()
        with TestClient(module.app) as client:
            response = client.post(
                "/api/notes/generate?scope=quick", json={"text": self.session_input.transcript_text},
            )
        self.assertEqual(502, response.status_code)
        self.assertNotIn("SYNTHETIC-PRIVATE-PROVIDER-DETAIL", response.text)
        self.assertNotIn("session_summary_draft", response.json())
        self.skill.assert_called_once()
        self.structured_llm.assert_not_called()
        self.assertFalse(settings.use_stub)

    def test_repeated_invalid_proposal_ends_the_request_without_a_partial_draft(self) -> None:
        from app.services.summary_corrections import TextCorrection

        invalid = SummaryVerification(source_ref_reviews=[
            SourceRefReview(field=field, keep_source_refs=section.source_refs)
            for field, section in _summary() if field != "session_info"
        ], text_corrections=[TextCorrection(field="session_theme", original="missing", replacement="fabricated")])
        verifier = Mock(invoke=Mock(return_value=invalid))
        self.structured_llm.side_effect = None
        self.structured_llm.return_value = verifier
        module = _load_vercel_generate()
        with TestClient(module.app) as client:
            response = client.post(
                "/api/notes/generate?scope=quick", json={"text": self.session_input.transcript_text},
            )
        self.assertEqual(502, response.status_code)
        self.assertEqual({"detail": "요약 검증을 마치지 못했어요. 잠시 후 다시 시도해주세요."}, response.json())
        self.assertEqual(2, verifier.invoke.call_count)
        self.skill.assert_called_once()
        self.insights.assert_called_once()

    def _approved_post(self):
        from app.api.security import AuthenticatedActor
        from app.main import app
        from app.services import deid_review as review
        from app.services.qwen_deidentification import Entities

        actor = AuthenticatedActor("synthetic-owner", "synthetic-token")
        self.stack.enter_context(patch.multiple(settings, poc_mode=True, require_deid_review=True,
                                                deid_review_signing_key="synthetic-signing-key-" * 3))
        self.stack.enter_context(patch("app.api.routes.notes._require_supabase_user", return_value=actor))
        self.stack.enter_context(patch.object(review, "detect_entities", return_value=Entities(entities=[])))
        prepared = review.prepare_review(review.ReviewStart(purpose="quick", payload={"text": self.session_input.transcript_text}), actor)
        found = review.start_review(review.ReviewStart(purpose="quick", payload=prepared["payload"],
                                                       preparation_token=prepared["preparation_token"]), actor)
        approved = review.confirm_review(review.ReviewConfirm(purpose="quick", payload=found["payload"],
                                                              detection_token=found["detection_token"]), actor)
        def submit():
            return TestClient(app).post("/api/notes/quick-summary", json=approved["payload"],
                headers={"Authorization": "Bearer synthetic-token", "X-Review-Receipt": approved["receipt"]})
        return submit

    def test_authenticated_quick_route_recovers_inside_one_approved_post(self) -> None:
        submit = self._approved_post()
        valid = self._fake_llm(SummaryVerification).invoke()
        invalid = valid.model_copy(update={"text_corrections": [
            TextCorrection(field="session_theme", original="absent", replacement="invented")
        ]})
        verifier = Mock(invoke=Mock(side_effect=[invalid, valid]))
        self.structured_llm.side_effect = None
        self.structured_llm.return_value = verifier
        response = submit()
        self.assertEqual(200, response.status_code)
        result = GenerateNoteResponse.model_validate(response.json())
        self.assertEqual(_summary().session_content.text, result.session_summary_draft.session_content.text)
        self.assertIsNotNone(result.verification_report)
        self.assertFalse(result.stub)
        self.assertEqual(2, verifier.invoke.call_count)
        self.skill.assert_called_once()
        self.insights.assert_called_once()

    def _rejected_proposal(self):
        original = self._fake_llm(SummaryVerification).invoke()
        return original.model_copy(update={"text_corrections": [
            TextCorrection(field="session_theme", original="탐색함", replacement="살펴봄")
        ]})

    def _configure_final_rejection(self, next_theme, outcomes):
        first = self._fake_skill(_state()["sanitized_input"])
        second = self._fake_skill(_state()["sanitized_input"])
        second.summary.session_theme.text = next_theme
        self.skill.side_effect = [first, second]
        verifier = Mock(invoke=Mock(side_effect=outcomes))
        self.structured_llm.side_effect = None
        self.structured_llm.return_value = verifier
        return verifier

    def test_final_rejection_regenerates_distinct_draft_on_same_approved_post(self):
        from app.api.routes import notes

        submit = self._approved_post()
        fresh_theme = "시험 준비를 끝낸 뒤에도 확인을 반복했다고 함."
        valid = self._fake_llm(SummaryVerification).invoke()
        verifier = self._configure_final_rejection(fresh_theme, [
            self._rejected_proposal(), SummaryCorrectionValidation(correction_validated=False), valid,
        ])
        with patch.object(notes, "reviewed_request", wraps=notes.reviewed_request) as receipts, patch.object(
            notes, "review_actor", wraps=notes.review_actor,
        ) as actors, patch.object(notes.rate_limiter, "check", wraps=notes.rate_limiter.check) as quota:
            response = submit()
        self.assertEqual(200, response.status_code)
        result = GenerateNoteResponse.model_validate(response.json())
        self.assertEqual(fresh_theme, result.session_summary_draft.session_theme.text)
        self.assertFalse(result.stub)
        self.assertEqual(self.skill.call_count, 2)
        self.assertEqual(self.skill.call_args_list[0], self.skill.call_args_list[1])
        self.assertEqual(3, verifier.invoke.call_count)
        self.assertEqual(2, actors.call_count)
        self.assertEqual(2, receipts.call_count)
        self.assertEqual(receipts.call_args_list[0], receipts.call_args_list[1])
        quota.assert_called_once()

    def test_final_rejection_cannot_return_original_rejected_or_unverified_candidate(self):
        submit = self._approved_post()
        proposal = self._rejected_proposal()
        denied = SummaryCorrectionValidation(correction_validated=False)
        for theme, extra, expected_verifications in (
            (_summary().session_theme.text, [], 2),
            (_summary().session_theme.text.replace("탐색함", "살펴봄"), [], 2),
            ("시험을 준비할 때의 마음을 탐색함.", [proposal, denied], 4),
        ):
            with self.subTest(expected_verifications=expected_verifications, theme_length=len(theme)):
                verifier = self._configure_final_rejection(theme, [proposal, denied, *extra])
                self.skill.reset_mock()
                response = submit()
                self.assertEqual(502, response.status_code)
                self.assertEqual({"detail": "요약 검증을 마치지 못했어요. 잠시 후 다시 시도해주세요."}, response.json())
                self.assertEqual(2, self.skill.call_count)
                self.assertEqual(expected_verifications, verifier.invoke.call_count)

    def test_recovery_budget_stops_after_slow_attempt_or_prior_edit_recovery(self):
        from app.api.routes import notes

        submit = self._approved_post()
        valid = self._rejected_proposal()
        invalid = valid.model_copy(update={"text_corrections": [
            TextCorrection(field="session_theme", original="absent", replacement="invented")
        ]})
        denied = SummaryCorrectionValidation(correction_validated=False)
        for elapsed, responses in ((90.1, [valid, denied]), (1, [invalid, valid, denied])):
            with self.subTest(elapsed=elapsed):
                verifier = self._configure_final_rejection("다시 작성한 주제.", responses)
                self.skill.reset_mock()
                with patch.object(notes, "monotonic", side_effect=[0, elapsed]):
                    response = submit()
                self.assertEqual(502, response.status_code)
                self.assertEqual({"detail": "요약 검증을 마치지 못했어요. 잠시 후 다시 시도해주세요."}, response.json())
                self.skill.assert_called_once()
                self.assertEqual(len(responses), verifier.invoke.call_count)

    def test_changed_actor_cannot_use_original_receipt_for_fresh_generation(self):
        from app.api.security import AuthenticatedActor
        from app.api.routes import notes

        submit = self._approved_post()
        verifier = self._configure_final_rejection("새로운 주제.", [
            self._rejected_proposal(), SummaryCorrectionValidation(correction_validated=False),
        ])
        with patch.object(notes, "review_actor", side_effect=[
            AuthenticatedActor("synthetic-owner", "synthetic-token"),
            AuthenticatedActor("different-owner", "different-token"),
        ]):
            response = submit()
        self.assertEqual(409, response.status_code)
        self.skill.assert_called_once()
        self.assertEqual(2, verifier.invoke.call_count)

    def test_placeholder_only_regeneration_is_rejected_before_verification(self):
        from app.services.summary_quality import QuickCorrectionRejected, SummaryQualityError, check_fresh_quick_draft

        original = _summary()
        empty = _summary()
        for field, section in empty:
            if field != "session_info":
                section.text = "[상담사 확인 필요]"
        with self.assertRaises(SummaryQualityError):
            check_fresh_quick_draft(empty, QuickCorrectionRejected(original, original).rejected_digests)


if __name__ == "__main__":
    unittest.main()
