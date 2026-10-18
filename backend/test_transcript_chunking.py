"""Long synthetic transcript bounds, positions, and failure semantics."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("USE_STUB", "1")

from app.graph.summary_core import AUTHENTICATED_FULL_POLICY, run_summary_core  # noqa: E402
from app.schemas.note import (  # noqa: E402
    EvidenceItem,
    SessionInfo,
    SessionInput,
    SessionSummaryDraft,
    StructuredCaseData,
    SummarySection,
)
from app.services.transcript_chunking import TranscriptLimitError, split_source_text  # noqa: E402
from benchmarks.long_transcript_benchmark import EVENT_MARKERS, generate_synthetic_transcript  # noqa: E402


class TranscriptChunkingTests(unittest.TestCase):
    def test_60_minute_transcript_preserves_boundaries_offsets_and_events(self) -> None:
        text = generate_synthetic_transcript(60, "timestamps")
        chunks = split_source_text(
            text,
            source_field="transcript_text",
            target_chars=4_000,
            max_chunks=8,
        )
        self.assertGreater(len(chunks), 1)
        self.assertEqual(text, "".join(chunk.text for chunk in chunks))
        for chunk in chunks:
            self.assertEqual(chunk.text, text[chunk.start_char:chunk.end_char])
            self.assertEqual(
                f"transcript_text.chars_{chunk.start_char}_{chunk.end_char}",
                chunk.source_ref,
            )
        reconstructed = "".join(chunk.text for chunk in chunks)
        self.assertTrue(all(marker in reconstructed for marker in EVENT_MARKERS.values()))

    def test_input_over_chunk_budget_fails_without_truncation(self) -> None:
        text = generate_synthetic_transcript(60, "speakers")
        with self.assertRaises(TranscriptLimitError):
            split_source_text(
                text,
                source_field="transcript_text",
                target_chars=1_000,
                max_chunks=2,
            )

    def test_boundary_selection_uses_the_available_chunk_capacity(self) -> None:
        text = ("짧은 문장.\n" * 99) + ("마지막 문장" * 20)
        chunks = split_source_text(
            text,
            source_field="counselor_memo",
            target_chars=500,
            max_chunks=3,
        )
        self.assertLessEqual(len(chunks), 3)
        self.assertEqual(text, "".join(chunk.text for chunk in chunks))

    def test_full_core_uses_position_references_for_long_input(self) -> None:
        text = generate_synthetic_transcript(60, "speakers")
        result = run_summary_core(
            {
                "session_input": SessionInput(
                    case_id="synthetic-long",
                    session_number=1,
                    counselor_memo="",
                    transcript_text=text,
                    persist=False,
                    insight_lens="none",
                )
            },
            policy=AUTHENTICATED_FULL_POLICY,
        )
        self.assertTrue(result["hierarchical_summary"])
        self.assertGreater(len(result["source_segments"]), 1)
        refs = [
            ref
            for item in result["evidence_mapped_data"].items
            for ref in item.source_refs
        ]
        self.assertTrue(any(ref.startswith("transcript_text.chars_") for ref in refs))
        self.assertIsNotNone(result.get("core_verification_report"))

    def test_hierarchical_merge_preserves_early_middle_and_late_events(self) -> None:
        text = generate_synthetic_transcript(60, "speakers")

        def structure_chunk(state: dict) -> dict:
            chunk_text = state["sanitized_input"].sources.transcript_text
            events = [
                EvidenceItem(content=marker, evidence_type="direct", source_refs=["transcript_text"])
                for marker in EVENT_MARKERS.values()
                if marker in chunk_text
            ]
            return {
                "structured_case_data": StructuredCaseData(
                    session_content=events,
                    counselor_interventions=[item for item in events if "상담자는" in item.content],
                    client_responses=[item for item in events if "내담자는" in item.content],
                )
            }

        def summarize_merged(state: dict) -> dict:
            items = state["structured_case_data"].session_content
            refs = [ref for item in items for ref in item.source_refs]
            section = SummarySection(
                text=" ".join(item.content for item in items),
                evidence_type="direct",
                source_refs=refs,
            )
            return {
                "session_summary_draft": SessionSummaryDraft(
                    session_info=SessionInfo(case_id="synthetic-long", session_number=1, session_date=""),
                    presenting_problem=section,
                    session_theme=section,
                    session_content=section,
                    counselor_intervention=section,
                    client_response=section,
                    reflection=SummarySection(text="[상담사 확인 필요]", evidence_type="needs_review"),
                    next_plan=SummarySection(text="[상담사 확인 필요]", evidence_type="needs_review"),
                )
            }

        with patch("app.graph.summary_core.structure_session", side_effect=structure_chunk), patch(
            "app.graph.summary_core.generate_summary", side_effect=summarize_merged
        ):
            result = run_summary_core(
                {
                    "session_input": SessionInput(
                        case_id="synthetic-long",
                        session_number=1,
                        counselor_memo="",
                        transcript_text=text,
                        persist=False,
                        insight_lens="none",
                    )
                },
                policy=AUTHENTICATED_FULL_POLICY,
            )

        merged_text = " ".join(
            item.content for item in result["structured_case_data"].session_content
        )
        self.assertTrue(all(marker in merged_text for marker in EVENT_MARKERS.values()))
        self.assertEqual(1, len(result["structured_case_data"].counselor_interventions))
        self.assertGreaterEqual(len(result["structured_case_data"].client_responses), 1)
        self.assertTrue(all(
            "상담자는" not in item.content
            for item in result["structured_case_data"].client_responses
        ))


if __name__ == "__main__":
    unittest.main()
