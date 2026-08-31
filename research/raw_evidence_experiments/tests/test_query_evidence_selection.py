import unittest

from pydantic import ValidationError

from app.schemas.evidence import StoredTranscriptTurn
from research.raw_evidence_experiments.schemas import EvidenceSpanSelectionPayload
from research.raw_evidence_experiments.services.query_evidence_selection import (
    select_evidence_spans,
    select_evidence_spans_with_diagnostics,
)
from research.raw_evidence_experiments.scripts.evaluate_raw_window_selection import LocalWindowEvaluationStorage


def make_turns(count=8, *, user_id="u", case_id="c", session_id="s"):
    return [StoredTranscriptTurn(
        id=f"{session_id}-{index}",
        user_id=user_id,
        counselor_id=user_id,
        case_id=case_id,
        session_id=session_id,
        turn_index=index,
        speaker_role="client" if index % 2 == 0 else "counselor",
        sanitized_text=f"exact raw turn {index}",
    ) for index in range(count)]


class QueryEvidenceSelectionTests(unittest.TestCase):
    def test_local_rpc_excludes_other_user_and_case_windows(self):
        corpus = {
            "user_id": "u",
            "case_id": "c",
            "sessions": [{"session_id": "s1", "session_number": 1}],
        }
        storage = LocalWindowEvaluationStorage(corpus)
        base = {
            "id": "own",
            "user_id": "u",
            "counselor_id": "u",
            "case_id": "c",
            "session_id": "s1",
            "start_turn_index": 0,
            "end_turn_index": 1,
            "source_ref": "transcript_window:s1:0-1",
            "window_text": "own",
            "embedding": [1.0, 0.0],
        }
        storage.transcript_windows = [
            base,
            {**base, "id": "other-user", "user_id": "other", "source_ref": "foreign-user"},
            {**base, "id": "other-case", "case_id": "other", "source_ref": "foreign-case"},
        ]
        rows = storage.rpc("match_transcript_windows", {
            "query_embedding": [1.0, 0.0],
            "filter_user_id": "u",
            "filter_case_id": "c",
            "match_count": 12,
        })
        self.assertEqual([item["window_id"] for item in rows], ["own"])

    def test_selector_schema_forbids_text_reason_type_and_summary(self):
        for field in ("text", "summary", "reason", "episode_type", "clinical_meaning"):
            with self.assertRaises(ValidationError):
                EvidenceSpanSelectionPayload.model_validate({
                    "spans": [{"start_turn_index": 0, "end_turn_index": 1, field: "forbidden"}],
                })

    def test_selector_rejects_out_of_region_and_missing_intermediate_turn(self):
        turns = make_turns(4)[1:3]
        selected, diagnostics = select_evidence_spans_with_diagnostics(
            query_text="query",
            region_turns=turns,
            selector=lambda *_: {"spans": [{"start_turn_index": 0, "end_turn_index": 3}]},
        )
        self.assertEqual(selected, [])
        self.assertEqual([item.code for item in diagnostics], ["invalid_selected_span"])

    def test_selector_allows_empty_evidence(self):
        self.assertEqual(select_evidence_spans(
            query_text="unsupported query",
            region_turns=make_turns(3),
            selector=lambda *_: {"spans": []},
        ), [])

    def test_selected_span_is_exact_raw_grounded_with_deterministic_source_ref(self):
        selected = select_evidence_spans(
            query_text="query",
            region_turns=make_turns(5),
            session_number=2,
            selector=lambda *_: {"spans": [{"start_turn_index": 1, "end_turn_index": 3}]},
        )[0]
        self.assertEqual(selected.source_ref, "transcript:s:1-3")
        self.assertEqual(selected.evidence_text.splitlines(), [
            "[counselor] exact raw turn 1",
            "[client] exact raw turn 2",
            "[counselor] exact raw turn 3",
        ])


if __name__ == "__main__":
    unittest.main()
