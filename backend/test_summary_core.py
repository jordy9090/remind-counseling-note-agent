"""Shared-core and public execution-boundary regression tests."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("USE_STUB", "1")

from app.core.config import settings  # noqa: E402
from app.graph import summary_core  # noqa: E402
from app.graph.graph import run_note_pipeline  # noqa: E402
from app.graph.summary_core import PUBLIC_QUICK_POLICY, run_summary_core  # noqa: E402
from app.schemas.note import SessionInput  # noqa: E402
from app.services import quick_summary  # noqa: E402


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
        ]
        for state in cases:
            with self.subTest(keys=sorted(state)):
                with self.assertRaises(ValueError):
                    run_summary_core(state, policy=PUBLIC_QUICK_POLICY)


if __name__ == "__main__":
    unittest.main()
