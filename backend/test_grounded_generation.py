"""Tests for the PR4 opt-in raw-region grounded generation integration."""
from __future__ import annotations

import unittest
from dataclasses import dataclass
from unittest.mock import patch

from app.core.config import settings
from app.graph.graph import run_note_pipeline
from app.schemas.evidence import CandidateTranscriptRegion
from app.schemas.grounding import (
    ClaimSupportValidation,
    EvidenceNeed,
    GroundedClaim,
    GroundedGenerationDraft,
    GroundingContext,
    GroundingSource,
)
from app.schemas.note import InputSources, SanitizedInput, SessionInput
from app.services.grounded_generation import (
    assemble_grounding_context,
    build_grounded_generation_prompt,
    formulate_evidence_needs,
    retrieve_raw_regions_for_needs,
    validate_evidence_ids,
)
from app.services.claim_support_validation import build_claim_support_prompt, validate_claim_support
from app.services.supabase_storage import _grounding_evidence_rows


def _sanitized(previous_summary: str = "") -> SanitizedInput:
    return SanitizedInput(
        case_id="SYNTH-PR4",
        session_number=9,
        session_date="2026-08-29",
        counselor_name="synthetic-counselor",
        sources=InputSources(
            counselor_memo="현재 회기에는 부모 갈등 이후의 변화를 확인했다.",
            transcript_text="[client] 이번에는 의견을 말했다.",
            previous_session_summary=previous_summary,
            counseling_goal="부모와 갈등 상황에서 자신의 의견을 표현하기",
            key_issue_tags=["자기표현", "부모 갈등"],
        ),
        sensitive_info_candidates=[],
    )


def _region(session_number: int, source_ref: str, score: float = 0.8) -> CandidateTranscriptRegion:
    return CandidateTranscriptRegion(
        session_id=f"session-{session_number}",
        session_number=session_number,
        start_turn_index=0,
        end_turn_index=7,
        region_text="[counselor] 실제 장면을 확인했다.\n[client] 부모에게 제 의견을 끝까지 말했어요.",
        source_ref=source_ref,
        retrieval_score=score,
        retrieval_rank=1,
        window_ids=[f"window-{session_number}"],
    )


@dataclass
class _Memory:
    source_ref: str
    chunk_text: str
    session_id: str = "session-3"
    session_number: int = 3
    similarity_score: float = 0.7
    retrieval_method: str = "case_memory_dense"


class GroundedGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = {
            "enable_raw_region_grounding": settings.enable_raw_region_grounding,
            "enable_rag": settings.enable_rag,
            "enable_dense_retrieval": settings.enable_dense_retrieval,
            "use_stub": settings.use_stub,
        }

    def tearDown(self) -> None:
        for key, value in self.original.items():
            setattr(settings, key, value)

    def test_evidence_needs_are_bounded_and_do_not_concatenate_previous_summary(self) -> None:
        secret_marker = "PREVIOUS_SUMMARY_MUST_NOT_ENTER_QUERY"
        needs = formulate_evidence_needs(_sanitized(secret_marker), "session_note")
        self.assertEqual(5, len(needs))
        self.assertTrue(all(secret_marker not in need.query_text for need in needs))
        joined = " ".join(need.query_text for need in needs)
        self.assertNotIn("진단", joined)
        self.assertNotIn("예후", joined)
        self.assertNotIn("점수", joined)

    def test_raw_retrieval_preserves_user_case_scope_and_top_five(self) -> None:
        needs = [EvidenceNeed(need_id="N1", target_field="session_content", query_text="query", source_requirement="raw_factual")]
        calls = []

        def fake_retriever(**kwargs):
            calls.append(kwargs)
            return [_region(index, f"transcript:session-{index}:0-7", 1 - index / 100) for index in range(1, 8)]

        results = retrieve_raw_regions_for_needs(
            needs=needs,
            user_id="user-A",
            case_id="case-A",
            current_session_number=9,
            top_k=5,
            region_retriever=fake_retriever,
        )
        self.assertEqual({"query_text": "query", "user_id": "user-A", "case_id": "case-A"}, calls[0])
        self.assertEqual(5, len(results["N1"]))

    def test_context_deduplicates_source_ref_and_retains_need_mapping(self) -> None:
        needs = [
            EvidenceNeed(need_id="N1", target_field="session_content", query_text="event", source_requirement="raw_factual"),
            EvidenceNeed(need_id="N2", target_field="client_response", query_text="response", source_requirement="raw_factual"),
            EvidenceNeed(need_id="N3", target_field="reflection", query_text="judgment", source_requirement="counselor_judgment"),
        ]
        shared = _region(5, "transcript:session-5:0-7")
        context = assemble_grounding_context(
            needs=needs,
            raw_regions_by_need={"N1": [shared], "N2": [shared]},
            counselor_memory_chunks=[_Memory("confirmed_note:note-3:reflection", "상담사는 자기표현 연습을 유지하기로 판단했다.")],
        )
        self.assertEqual(2, context.diagnostics.retrieved_region_count)
        self.assertEqual(1, context.diagnostics.deduplicated_region_count)
        self.assertEqual(["R1"], context.need_to_evidence_ids["N1"])
        self.assertEqual(["R1"], context.need_to_evidence_ids["N2"])
        self.assertEqual(["M1"], context.need_to_evidence_ids["N3"])
        self.assertEqual(8, context.diagnostics.raw_evidence_turn_count)

    def test_prompt_separates_source_hierarchy(self) -> None:
        leaked_query = "보고서 발표 마감 수면 부족 집중 어려움"
        need = EvidenceNeed(need_id="N1", target_field="session_content", query_text=leaked_query, source_requirement="raw_factual")
        context = assemble_grounding_context(needs=[need], raw_regions_by_need={"N1": [_region(5, "transcript:session-5:0-7")]})
        prompt = build_grounded_generation_prompt(_sanitized(), context)
        self.assertIn("=== RAW TRANSCRIPT EVIDENCE ===", prompt)
        self.assertIn("=== COUNSELOR-CONFIRMED MEMORY ===", prompt)
        self.assertIn("=== AUTHORITATIVE DOCUMENTATION KB ===", prompt)
        self.assertIn("Never invent an evidence ID", prompt)
        self.assertIn('"need_id": "N1"', prompt)
        self.assertIn('"target_field": "session_content"', prompt)
        self.assertIn('"source_requirement": "raw_factual"', prompt)
        self.assertNotIn(leaked_query, prompt)
        self.assertNotIn("현재 회기에는 부모 갈등 이후의 변화를 확인했다.", prompt)
        self.assertNotIn("이번에는 의견을 말했다.", prompt)
        self.assertNotIn("counseling_goal", prompt)

    def test_support_prompt_contains_only_claim_and_directly_cited_source(self) -> None:
        claim = GroundedClaim(
            claim_id="C1", need_id="N1", target_field="session_content",
            text="보고서 마감으로 잠을 거의 못 잤다.", support_type="direct_evidence",
            evidence_ids=["R1"], review_required=False,
        )
        evidence = {
            "R1": GroundingSource(
                evidence_id="R1", source_type="raw_transcript", source_ref="transcript:s4:0-1",
                source_text="[client] 보고서 마감이 겹쳐 거의 잠을 못 잤어요.",
            ),
            "R2": GroundingSource(
                evidence_id="R2", source_type="raw_transcript", source_ref="transcript:s1:0-1",
                source_text="SHOULD_NOT_BE_VISIBLE 다른 회기의 부모 갈등", need_ids=["N1"],
            ),
        }
        prompt = build_claim_support_prompt(claim=claim, evidence_by_id=evidence)
        self.assertIn(claim.text, prompt)
        self.assertIn(evidence["R1"].source_text, prompt)
        self.assertNotIn("SHOULD_NOT_BE_VISIBLE", prompt)
        self.assertNotIn("query_text", prompt)
        self.assertNotIn("source_ref", prompt)

    def test_exact_support_returns_supported(self) -> None:
        settings.use_stub = False
        claim = GroundedClaim(
            claim_id="C1", need_id="N1", target_field="session_content",
            text="보고서 마감으로 거의 잠을 자지 못했다.", support_type="direct_evidence",
            evidence_ids=["R1"], review_required=False,
        )
        evidence = {"R1": GroundingSource(
            evidence_id="R1", source_type="raw_transcript", source_ref="transcript:s4:0-1",
            source_text="[client] 보고서 마감이 겹쳐 거의 잠을 못 잤어요.",
        )}
        runnable = unittest.mock.Mock()
        runnable.invoke.return_value = ClaimSupportValidation(verdict="supported", supported_evidence_ids=["R1"])
        with patch("app.services.claim_support_validation.get_structured_llm", return_value=runnable):
            verdict = validate_claim_support(claim=claim, evidence_by_id=evidence)
        self.assertEqual("supported", verdict.verdict)

    def test_partial_support_returns_partial(self) -> None:
        settings.use_stub = False
        claim = GroundedClaim(
            claim_id="C1", need_id="N1", target_field="session_content",
            text="보고서 마감으로 수면이 부족했고 집중력도 크게 저하됐다.", support_type="direct_evidence",
            evidence_ids=["R1"], review_required=False,
        )
        evidence = {"R1": GroundingSource(
            evidence_id="R1", source_type="raw_transcript", source_ref="transcript:s4:0-1",
            source_text="[client] 보고서 마감이 겹쳐 거의 잠을 못 잤어요.",
        )}
        runnable = unittest.mock.Mock()
        runnable.invoke.return_value = ClaimSupportValidation(
            verdict="partial", supported_evidence_ids=["R1"], category="missing_fact"
        )
        with patch("app.services.claim_support_validation.get_structured_llm", return_value=runnable):
            verdict = validate_claim_support(claim=claim, evidence_by_id=evidence)
        self.assertEqual("partial", verdict.verdict)

    def test_wrong_source_swap_is_downgraded(self) -> None:
        need = EvidenceNeed(
            need_id="N1", target_field="session_content", query_text="academic", source_requirement="raw_factual"
        )
        context = assemble_grounding_context(
            needs=[need], raw_regions_by_need={"N1": [_region(1, "transcript:session-1:0-7")]}
        )
        draft = GroundedGenerationDraft(claims=[GroundedClaim(
            claim_id="C1", need_id="N1", target_field="session_content",
            text="보고서와 발표 마감으로 잠을 거의 못 잤다.", support_type="direct_evidence",
            evidence_ids=["R1"], review_required=False,
        )])
        checked = validate_evidence_ids(
            draft, context,
            support_validator=lambda **_: ClaimSupportValidation(
                verdict="unsupported", supported_evidence_ids=[], category="wrong_event"
            ),
        )
        self.assertEqual("unsupported", checked.claims[0].support_type)
        self.assertEqual([], checked.claims[0].evidence_ids)
        self.assertTrue(checked.claims[0].review_required)
        self.assertEqual("unsupported", checked.claim_support_validations["C1"].verdict)

    def test_partial_support_is_downgraded_without_relinking(self) -> None:
        need = EvidenceNeed(need_id="N1", target_field="session_content", query_text="academic", source_requirement="raw_factual")
        context = assemble_grounding_context(needs=[need], raw_regions_by_need={"N1": [_region(4, "transcript:session-4:0-7")]})
        draft = GroundedGenerationDraft(claims=[GroundedClaim(
            claim_id="C1", need_id="N1", target_field="session_content", text="수면과 집중이 어려웠다.",
            support_type="direct_evidence", evidence_ids=["R1"], review_required=False,
        )])
        checked = validate_evidence_ids(
            draft, context,
            support_validator=lambda **_: ClaimSupportValidation(
                verdict="partial", supported_evidence_ids=["R1"], category="missing_fact"
            ),
        )
        self.assertEqual("unsupported", checked.claims[0].support_type)
        self.assertEqual([], checked.claims[0].evidence_ids)
        self.assertTrue(checked.claims[0].review_required)

    def test_invalid_evidence_id_fails_closed(self) -> None:
        need = EvidenceNeed(need_id="N1", target_field="session_content", query_text="event", source_requirement="raw_factual")
        context = assemble_grounding_context(needs=[need], raw_regions_by_need={"N1": [_region(5, "transcript:session-5:0-7")]})
        draft = GroundedGenerationDraft(claims=[
            GroundedClaim(
                claim_id="C1", need_id="N1", target_field="session_content", text="확인되지 않은 사실",
                support_type="direct_evidence", evidence_ids=["R100"], review_required=False,
            )
        ])
        result = validate_evidence_ids(draft, context)
        self.assertEqual("unsupported", result.claims[0].support_type)
        self.assertEqual([], result.claims[0].evidence_ids)
        self.assertTrue(result.claims[0].review_required)
        self.assertEqual(0.0, result.metrics.citation_validity)

    def test_evidence_from_another_need_fails_closed(self) -> None:
        needs = [
            EvidenceNeed(need_id="N1", target_field="session_content", query_text="first", source_requirement="raw_factual"),
            EvidenceNeed(need_id="N2", target_field="client_response", query_text="setback", source_requirement="raw_factual"),
        ]
        context = assemble_grounding_context(
            needs=needs,
            raw_regions_by_need={
                "N1": [_region(5, "transcript:session-5:0-7")],
                "N2": [_region(6, "transcript:session-6:0-7")],
            },
        )
        draft = GroundedGenerationDraft(claims=[
            GroundedClaim(
                claim_id="C1", need_id="N1", target_field="session_content", text="후퇴했다.",
                support_type="direct_evidence", evidence_ids=["R2"], review_required=False,
            )
        ])
        result = validate_evidence_ids(draft, context)
        self.assertEqual("unsupported", result.claims[0].support_type)
        self.assertIn("not retrieved for its EvidenceNeed", result.citation_diagnostics[0].reason)

    def test_clinical_inference_is_always_review_required(self) -> None:
        need = EvidenceNeed(need_id="N1", target_field="reflection", query_text="interpret", source_requirement="raw_factual")
        context = assemble_grounding_context(needs=[need], raw_regions_by_need={"N1": [_region(5, "transcript:session-5:0-7")]})
        draft = GroundedGenerationDraft(claims=[
            GroundedClaim(
                claim_id="C1", need_id="N1", target_field="reflection", text="회피가 유지되는 것으로 보인다.",
                claim_kind="clinical_inference", support_type="clinical_inference",
                evidence_ids=["R1"], review_required=False,
            )
        ])
        result = validate_evidence_ids(draft, context)
        self.assertTrue(result.claims[0].review_required)

    def test_source_removal_prevents_source_backed_factual_claim(self) -> None:
        need = EvidenceNeed(need_id="N1", target_field="session_content", query_text="attempt", source_requirement="raw_factual")
        full = assemble_grounding_context(needs=[need], raw_regions_by_need={"N1": [_region(5, "transcript:session-5:0-7")]})
        draft = GroundedGenerationDraft(claims=[
            GroundedClaim(
                claim_id="C1", need_id="N1", target_field="session_content", text="부모에게 의견을 말했다.",
                support_type="direct_evidence", evidence_ids=["R1"], review_required=False,
            )
        ])
        supported = lambda **_: ClaimSupportValidation(verdict="supported", supported_evidence_ids=["R1"])
        self.assertEqual(
            "direct_evidence",
            validate_evidence_ids(draft, full, support_validator=supported).claims[0].support_type,
        )
        removed = GroundingContext(needs=[need], sources=[], need_to_evidence_ids={"N1": []})
        checked = validate_evidence_ids(draft, removed)
        self.assertEqual("unsupported", checked.claims[0].support_type)
        self.assertTrue(checked.claims[0].review_required)

    def test_grounding_evidence_rows_keep_exact_source_snapshot(self) -> None:
        need = EvidenceNeed(need_id="N1", target_field="session_content", query_text="event", source_requirement="raw_factual")
        context = assemble_grounding_context(needs=[need], raw_regions_by_need={"N1": [_region(5, "transcript:session-5:0-7")]})
        draft = GroundedGenerationDraft(claims=[
            GroundedClaim(
                claim_id="C1", need_id="N1", target_field="session_content", text="생성된 요약 문장",
                support_type="direct_evidence", evidence_ids=["R1"], review_required=False,
            )
        ])
        result = validate_evidence_ids(
            draft,
            context,
            support_validator=lambda **_: ClaimSupportValidation(verdict="supported", supported_evidence_ids=["R1"]),
        )
        rows = _grounding_evidence_rows(result, case_id="case-A", session_id="current", user_id="user-A")
        self.assertEqual(context.sources[0].source_text, rows[0]["source_text"])
        self.assertNotEqual(draft.claims[0].text, rows[0]["source_text"])

    def test_counselor_judgment_requires_semantic_m_support(self) -> None:
        need = EvidenceNeed(
            need_id="N1", target_field="reflection", query_text="strategy", source_requirement="counselor_judgment"
        )
        context = assemble_grounding_context(
            needs=[need], raw_regions_by_need={},
            counselor_memory_chunks=[_Memory(
                "confirmed_note:note-3:reflection",
                "상담사는 짧은 핵심 문장 반복을 계속 연습하기로 판단했다.",
            )],
        )
        draft = GroundedGenerationDraft(claims=[GroundedClaim(
            claim_id="C1", need_id="N1", target_field="reflection",
            text="상담사는 핵심 문장 반복 연습을 유지하기로 판단했다.",
            support_type="counselor_judgment", evidence_ids=["M1"], review_required=False,
        )])
        checked = validate_evidence_ids(
            draft, context,
            support_validator=lambda **_: ClaimSupportValidation(
                verdict="supported", supported_evidence_ids=["M1"]
            ),
        )
        self.assertEqual("counselor_judgment", checked.claims[0].support_type)
        self.assertFalse(checked.claims[0].review_required)

    def test_clinical_inference_with_m_source_still_requires_review(self) -> None:
        need = EvidenceNeed(
            need_id="N1", target_field="reflection", query_text="strategy", source_requirement="counselor_judgment"
        )
        context = assemble_grounding_context(
            needs=[need], raw_regions_by_need={},
            counselor_memory_chunks=[_Memory(
                "confirmed_note:note-3:reflection", "상담사는 자기표현 연습을 유지하기로 판단했다."
            )],
        )
        draft = GroundedGenerationDraft(claims=[GroundedClaim(
            claim_id="C1", need_id="N1", target_field="reflection",
            text="자기표현 연습을 유지하는 것이 필요해 보인다.", claim_kind="clinical_inference",
            support_type="counselor_judgment", evidence_ids=["M1"], review_required=False,
        )])
        checked = validate_evidence_ids(
            draft, context,
            support_validator=lambda **_: ClaimSupportValidation(
                verdict="supported", supported_evidence_ids=["M1"]
            ),
        )
        self.assertEqual("counselor_judgment", checked.claims[0].support_type)
        self.assertTrue(checked.claims[0].review_required)

    def test_false_flag_does_not_invoke_raw_retrieval(self) -> None:
        settings.enable_raw_region_grounding = False
        settings.use_stub = True
        payload = SessionInput(
            case_id="SYNTH-FALSE-FLAG",
            session_number=9,
            counselor_memo="다음 회기에 확인한다.",
            transcript_text="[client] 의견을 말했다.",
        )
        with patch("app.graph.nodes.retrieve_raw_regions_for_needs", side_effect=AssertionError("must not run")):
            result = run_note_pipeline(payload, actor="user-A")
        self.assertIsNone(result.grounding)
        self.assertNotIn("grounding", result.model_dump(mode="json"))


if __name__ == "__main__":
    unittest.main()
