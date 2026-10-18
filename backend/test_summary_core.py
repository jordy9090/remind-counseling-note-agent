"""Shared-core and public execution-boundary regression tests."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("USE_STUB", "1")

from app.core.config import settings  # noqa: E402
from app.graph import summary_core  # noqa: E402
from app.graph.graph import run_note_pipeline  # noqa: E402
from app.graph.summary_core import (  # noqa: E402
    AUTHENTICATED_FULL_POLICY,
    PUBLIC_QUICK_POLICY,
    _sanitized_chunk,
    run_summary_core,
)
from app.schemas.note import InputSources, SanitizedInput, SessionInput  # noqa: E402
from app.services import quick_summary  # noqa: E402
from app.services.transcript_chunking import SourceChunk, TranscriptLimitError  # noqa: E402


SYNTHETIC_TEXT = (
    "내담자는 발표 준비가 늦어질까 걱정된다고 말했다. "
    "상담자는 걱정이 커지는 상황과 신체 반응을 구체적으로 확인했다."
)


def _session_input(**updates) -> SessionInput:
    values = {
        "case_id": "synthetic-case",
        "session_number": 1,
        "counselor_memo": "",
        "transcript_text": SYNTHETIC_TEXT,
        "persist": False,
        "insight_lens": "none",
    }
    values.update(updates)
    return SessionInput(**values)


class SummaryCoreTests(unittest.TestCase):
    def test_quick_and_full_paths_call_the_same_core_runner(self) -> None:
        with patch.object(
            quick_summary,
            "run_summary_core",
            wraps=summary_core.run_summary_core,
        ) as quick_runner:
            quick_summary.generate_quick_summary(SYNTHETIC_TEXT)
        self.assertEqual(1, quick_runner.call_count)
        self.assertEqual(PUBLIC_QUICK_POLICY, quick_runner.call_args.kwargs["policy"])

        with patch.object(
            summary_core,
            "run_summary_core",
            wraps=summary_core.run_summary_core,
        ) as full_runner, patch.object(settings, "use_stub", True), patch.object(settings, "enable_rag", False), patch.object(
            settings, "enable_raw_region_grounding", False
        ):
            run_note_pipeline(_session_input(), actor="synthetic-owner")
        self.assertEqual(1, full_runner.call_count)

    def test_direct_full_pipeline_keeps_raw_input_budget_validation(self) -> None:
        with patch.object(
            summary_core,
            "validate_summary_input_budget",
            wraps=summary_core.validate_summary_input_budget,
        ) as validate_budget, patch.object(settings, "use_stub", True), patch.object(
            settings, "enable_rag", False
        ), patch.object(settings, "enable_raw_region_grounding", False):
            run_note_pipeline(_session_input(), actor="synthetic-owner")

        validate_budget.assert_called_once()

    def test_sanitized_issue_tags_are_counted_in_budget(self) -> None:
        session_input = _session_input(key_issue_tags=["개발자"])
        for tags in (["가" * 96_001], [""] * 9_600):
            with self.subTest(tag_count=len(tags)):
                sanitized = SanitizedInput(
                    case_id=session_input.case_id,
                    session_number=session_input.session_number,
                    session_date=session_input.session_date,
                    counselor_name=session_input.counselor_name,
                    sources=InputSources(
                        counselor_memo="",
                        transcript_text=SYNTHETIC_TEXT,
                        key_issue_tags=tags,
                    ),
                )

                with self.assertRaises(TranscriptLimitError):
                    run_summary_core(
                        {
                            "session_input": session_input,
                            "sanitized_input": sanitized,
                            "input_budget_prevalidated": True,
                        },
                        policy=AUTHENTICATED_FULL_POLICY,
                    )

    def test_length_expanding_recompose_topic_is_counted_after_masking(self) -> None:
        session_input = _session_input()
        session_topic = "개발자 " * 10_000

        with self.assertRaises(TranscriptLimitError):
            run_summary_core(
                {
                    "session_input": session_input,
                    "session_topic": session_topic,
                },
                policy=AUTHENTICATED_FULL_POLICY,
            )

    def test_sanitized_session_date_is_counted_in_budget(self) -> None:
        session_input = _session_input(session_date="2026-10-19")
        token_heavy_pattern = "".join(chr(0x20000 + index) for index in range(512))
        for session_date in ("가" * 96_001, (token_heavy_pattern * 94)[:48_001]):
            with self.subTest(session_date_chars=len(session_date)):
                sanitized = SanitizedInput(
                    case_id=session_input.case_id,
                    session_number=session_input.session_number,
                    session_date=session_date,
                    counselor_name=session_input.counselor_name,
                    sources=InputSources(
                        counselor_memo="",
                        transcript_text=SYNTHETIC_TEXT,
                    ),
                )

                with self.assertRaises(TranscriptLimitError):
                    run_summary_core(
                        {
                            "session_input": session_input,
                            "sanitized_input": sanitized,
                            "input_budget_prevalidated": True,
                        },
                        policy=AUTHENTICATED_FULL_POLICY,
                    )

    def test_public_core_never_calls_storage_or_retrieval(self) -> None:
        with patch("app.graph.nodes._storage_for_actor", side_effect=AssertionError("storage called")), patch(
            "app.graph.nodes.retrieve_case_context", side_effect=AssertionError("retrieval called")
        ), patch("app.graph.nodes.retrieve_case_memory_chunks", side_effect=AssertionError("retrieval called")):
            result = quick_summary.generate_quick_summary(SYNTHETIC_TEXT)
        self.assertTrue(result.main_content)

    def test_public_policy_rejects_actor_previous_context_and_persistence(self) -> None:
        cases = [
            ({"session_input": _session_input(), "actor": "owner"}),
            ({"session_input": _session_input(previous_session_summary="이전 기록")}),
            ({"session_input": _session_input(persist=True)}),
            ({"session_input": _session_input(), "retrieved_case_context": [object()]}),
            ({"session_input": _session_input(), "grounding": {"sources": [object()]}}),
        ]
        for state in cases:
            with self.subTest(keys=sorted(state)):
                with self.assertRaises(ValueError):
                    run_summary_core(state, policy=PUBLIC_QUICK_POLICY)

    def test_long_input_includes_auxiliary_sources_once(self) -> None:
        sanitized = SanitizedInput(
            case_id="synthetic-case",
            session_number=1,
            session_date="2026-10-19",
            counselor_name="Synthetic Counselor",
            sources=InputSources(
                counselor_memo="memo",
                transcript_text="transcript",
                previous_session_summary="previous",
                counseling_goal="goal",
                psychological_test_summary="test",
                key_issue_tags=["tag"],
                nonverbal_notes="nonverbal",
            ),
        )
        first = _sanitized_chunk(
            sanitized,
            SourceChunk("counselor_memo", "counselor_memo.chars_0_4", "memo", 0, 4, 1, 2),
        )
        second = _sanitized_chunk(
            sanitized,
            SourceChunk("transcript_text", "transcript_text.chars_0_10", "transcript", 0, 10, 2, 2),
        )

        self.assertEqual("previous", first.sources.previous_session_summary)
        self.assertEqual("goal", first.sources.counseling_goal)
        self.assertEqual("test", first.sources.psychological_test_summary)
        self.assertEqual(["tag"], first.sources.key_issue_tags)
        self.assertEqual("nonverbal", first.sources.nonverbal_notes)
        self.assertEqual("", second.sources.previous_session_summary)
        self.assertEqual("", second.sources.counseling_goal)
        self.assertEqual([], second.sources.key_issue_tags)


if __name__ == "__main__":
    unittest.main()
