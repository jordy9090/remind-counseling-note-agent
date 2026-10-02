"""Regression checks for conservative source attribution and verifier warnings."""
from __future__ import annotations

import json
import unittest

from app.graph.nodes import (
    _build_structure_prompt, _build_summary_prompt, _normalize_summary_refs,
    _reconcile_verification_claims, _resolve_source_refs,
)
from app.schemas.note import (
    EvidenceMappedData, InputSources, RetrievedCaseContextItem, ReviewableClaim, SanitizedInput,
    SessionInfo, SessionSummaryDraft, StructuredCaseData, SummarySection, VerificationReport,
)


class SourceReferenceTests(unittest.TestCase):
    def test_valid_memo_ref_is_not_contaminated_by_a_similar_transcript_turn(self) -> None:
        catalog = {
            "counselor_memo": "바로 안심시켜주고 싶은 마음이 들었음.",
            "transcript.turn_55": "내담자: 선생님도 답답하시죠? 안심하고 싶은 마음이 있어요.",
        }
        self.assertEqual(
            ["counselor_memo"],
            _resolve_source_refs("상담자는 안심시켜주고 싶은 마음을 기록함.", ["memo", "counselor_memo"], catalog),
        )

    def test_valid_provided_refs_keep_their_order_and_exclude_unknown_refs(self) -> None:
        catalog = {"transcript.turn_2": "두 번째 발화", "counselor_memo": "기록된 성찰"}
        self.assertEqual(
            ["counselor_memo", "transcript.turn_2"],
            _resolve_source_refs("직접 선택한 근거", ["counselor_memo", "unknown", "transcript.turn_2", "counselor_memo"], catalog),
        )

    def test_documented_source_paths_resolve_without_guessing_turn_labels(self) -> None:
        catalog = {"transcript_text": "발화가 기록되어 있음.", "counselor_memo": "성찰이 기록되어 있음."}
        self.assertEqual(["transcript_text"], _resolve_source_refs("축어록에 근거한 요약임.", ["sources.transcript_text"], catalog))
        self.assertEqual(["counselor_memo"], _resolve_source_refs("메모에 근거한 성찰임.", ["sources.counselor_memo"], catalog))
        for invalid in ("A01", "sources.transcript.turn_1", "sources.unknown_field"):
            self.assertEqual([], _resolve_source_refs("원문을 재서술한 별도 문장임.", [invalid], catalog))

    def test_prompts_supply_canonical_ids_even_without_an_evidence_index(self) -> None:
        memo = "SYNTHETIC-MEMO-SOURCE-ONLY-ONCE"
        transcript = "A01 내담자: SYNTHETIC-TURN-SOURCE-ONLY-ONCE"
        sanitized = SanitizedInput(
            case_id="SYNTH-REFS", session_number=1, session_date="2026-10-02", counselor_name="",
            sources=InputSources(counselor_memo=memo, transcript_text=transcript),
        )
        prior = RetrievedCaseContextItem(source_ref="stored_session_note:synthetic", session_id="prior",
                                         summary="SYNTHETIC-PRIOR-CONTEXT")
        prompts = (
            _build_structure_prompt(sanitized, [prior], None),
            _build_summary_prompt(sanitized, StructuredCaseData(), EvidenceMappedData(), case_context=[prior]),
        )
        for prompt in prompts:
            with self.subTest(stage="summary" if "Each section" in prompt else "structure"):
                catalog_text = prompt.split("Allowed source_refs (canonical identifiers only):\n", 1)[1]
                allowed = json.loads(catalog_text.split("\nChoose source_refs", 1)[0])
                self.assertEqual(["counselor_memo", "transcript_text", "transcript.turn_1", "stored_session_note:synthetic"], allowed)
                self.assertNotIn("A01", allowed)
                self.assertNotIn("previous_session_summary", allowed, "empty sources must not be offered as citations")
                self.assertEqual(1, prompt.count(memo), "reference metadata must not duplicate counseling material")
                self.assertEqual(1, prompt.count(transcript))

    def test_missing_refs_are_recovered_only_from_literal_source_text(self) -> None:
        catalog = {
            "transcript_text": "내담자: 말한다고 괜찮아지는 건 아직 모르겠어요.\n상담자: 어떤 마음인가요?",
            "transcript.turn_1": "내담자: 말한다고 괜찮아지는 건 아직 모르겠어요.",
            "transcript.turn_2": "상담자: 어떤 마음인가요?",
        }
        self.assertEqual(["transcript.turn_1"], _resolve_source_refs("말한다고  괜찮아지는 건 아직 모르겠어요.", [], catalog))
        for unsupported in ("말한 뒤 괜찮아졌다고 표현함.", "괜찮아졌음.", "", "마음"):
            with self.subTest(claim=unsupported):
                self.assertEqual([], _resolve_source_refs(unsupported, ["unknown"], catalog))

    def test_overlap_or_verbatim_text_never_overrides_verifier_risk_findings(self) -> None:
        sanitized = SanitizedInput(
            case_id="SYNTH-REFS", session_number=1, session_date="2026-10-02", counselor_name="",
            sources=InputSources(
                counselor_memo="상담자는 바로 안심시켜주고 싶은 마음이 들었음. 실제로 안심시키지는 않았음.",
                transcript_text="내담자: 동료가 실망한 것은 아니에요.",
            ),
        )
        claims = [
            ReviewableClaim(claim="상담자는 바로 안심시켜주었음.", reason="욕구를 실제 개입으로 바꿈.", recommendation="수행 여부를 확인하세요."),
            ReviewableClaim(claim="동료가 실망한 것", reason="원문의 부정을 빠뜨림.", recommendation="부정을 보존하세요."),
            ReviewableClaim(claim=sanitized.sources.counselor_memo, reason="인용이 실제 효과를 입증하지 않음.", recommendation="임상적 효과를 검토하세요."),
        ]
        verification = VerificationReport(unsupported_or_risky_claims=claims)
        original = verification.model_dump()
        _reconcile_verification_claims(verification, sanitized, [])
        self.assertEqual(original, verification.model_dump())

    def test_direct_section_with_no_resolvable_source_requires_review(self) -> None:
        sanitized = SanitizedInput(
            case_id="SYNTH-REFS", session_number=1, session_date="2026-10-02", counselor_name="",
            sources=InputSources(counselor_memo="내담자가 업무 부담을 이야기함.", transcript_text=""),
        )
        fields = ("session_theme", "presenting_problem", "session_content", "counselor_intervention",
                  "client_response", "reflection", "next_plan")
        summary = SessionSummaryDraft(
            session_info=SessionInfo(case_id="SYNTH-REFS", session_number=1, session_date="2026-10-02"),
            **{field: SummarySection(text="내담자가 업무 부담을 이야기함.", evidence_type="direct",
                                     source_refs=["counselor_memo"]) for field in fields},
        )
        summary.session_theme = SummarySection(
            text="확인되지 않은 진단이 확정됨.", evidence_type="direct", source_refs=["missing-source"],
        )
        _normalize_summary_refs(summary, sanitized, [])
        self.assertEqual([], summary.session_theme.source_refs)
        self.assertTrue(summary.session_theme.requires_review)
        self.assertEqual(["counselor_memo"], summary.session_content.source_refs)
        self.assertFalse(summary.session_content.requires_review)


if __name__ == "__main__":
    unittest.main()
