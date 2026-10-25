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
    SessionInfo, SessionInput, SessionSummaryDraft, StructuredCaseData, VerificationReport,
)
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
        self.verification = VerificationReport()
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
        self.schema_calls.append(schema)
        if schema is StructuredCaseData:
            output = StructuredCaseData(session_content=[EvidenceItem(
                content="내담자는 시험 준비를 반복 확인한다고 보고함.",
                evidence_type="direct", source_refs=["transcript_text"],
            )])
        elif schema is SessionSummaryDraft:
            output = _summary()
        elif schema is VerificationReport:
            output = self.verification.model_copy(deep=True)
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
        self.verification = VerificationReport(unsupported_or_risky_claims=[ReviewableClaim(
            claim=claim, reason="합성 검증에서 표현의 근거를 재확인해야 함.", recommendation="상담사 검토 필요",
        )])
        response = quick_summary.generate_quick_summary(self.session_input.transcript_text)
        self.skill.assert_called_once()
        self.assertEqual([VerificationReport], self.schema_calls)
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
        self.assertEqual([StructuredCaseData, SessionSummaryDraft, VerificationReport], self.schema_calls)
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
        self.assertEqual([VerificationReport], self.schema_calls)
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


if __name__ == "__main__":
    unittest.main()
