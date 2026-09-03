import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas.evidence import StoredTranscriptTurn
from app.services.transcript_storage import build_transcript_span_text
from research.raw_evidence_experiments.schemas import EvidenceEpisode, TurnFunctionLabel, TurnFunctionLabelPayload
from research.raw_evidence_experiments.services import evidence_turn_functions
from research.raw_evidence_experiments.services.evidence_extraction import (
    extract_evidence_episode_spans, extract_evidence_episode_spans_direct,
)
from research.raw_evidence_experiments.services.evidence_turn_functions import (
    DEFAULT_MAX_SCENE_TURNS, _build_turn_function_prompt,
    assemble_evidence_episodes_from_turn_functions, assemble_evidence_episodes_with_diagnostics,
    label_turn_functions_with_diagnostics,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic_raw_dialogue_longitudinal.json"


def make_turns(roles):
    return [StoredTranscriptTurn(
        id=f"t{index}", user_id="u", counselor_id="u", case_id="c", session_id="s",
        turn_index=index, speaker_role=role, sanitized_text=f"exact raw turn {index}",
    ) for index, role in enumerate(roles)]


def make_labels(functions):
    return [TurnFunctionLabel(turn_index=index, function=function) for index, function in enumerate(functions)]


class TurnFunctionExtractionTests(unittest.TestCase):
    def test_structured_output_allows_only_index_and_function(self):
        valid = TurnFunctionLabelPayload.model_validate({
            "labels": [{"turn_index": 0, "function": "client_report"}],
        })
        self.assertEqual(valid.labels[0].function, "client_report")
        for extra in ({"text": "forbidden"}, {"summary": "forbidden"}, {"start_turn_index": 0}):
            with self.assertRaises(ValidationError):
                TurnFunctionLabelPayload.model_validate({
                    "labels": [{"turn_index": 0, "function": "client_report", **extra}],
                })

    def test_speaker_function_consistency_and_unknown_are_backend_validated(self):
        turns = make_turns(["client", "counselor", "unknown"])
        raw = {"labels": [
            {"turn_index": 0, "function": "counselor_intervention"},
            {"turn_index": 1, "function": "client_report"},
            {"turn_index": 2, "function": "client_response"},
        ]}
        labels, diagnostics = label_turn_functions_with_diagnostics(turns=turns, classifier=lambda _: raw)
        self.assertEqual(labels, [])
        self.assertEqual(sum(item.code == "invalid_speaker_function" for item in diagnostics), 3)

    def test_client_report_and_clarification_are_one_event(self):
        turns = make_turns(["client", "counselor", "client", "counselor", "client"])
        labels = make_labels([
            "client_report", "counselor_clarification", "client_report",
            "counselor_clarification", "client_report",
        ])
        spans = assemble_evidence_episodes_from_turn_functions(turns, labels)
        self.assertEqual([(item.episode_type, item.start_turn_index, item.end_turn_index) for item in spans], [
            ("client_event_state", 0, 4),
        ])

    def test_event_to_intervention_is_forced_boundary(self):
        turns = make_turns(["client", "counselor", "client", "counselor", "client", "counselor", "client"])
        labels = make_labels([
            "client_report", "counselor_clarification", "client_report",
            "counselor_intervention", "client_response", "counselor_clarification", "client_response",
        ])
        spans = assemble_evidence_episodes_from_turn_functions(turns, labels)
        self.assertEqual([(item.episode_type, item.start_turn_index, item.end_turn_index) for item in spans], [
            ("client_event_state", 0, 2), ("intervention_response", 3, 6),
        ])

    def test_intervention_chain_stays_grouped(self):
        turns = make_turns(["counselor", "client", "counselor", "client", "counselor", "client"])
        labels = make_labels([
            "counselor_intervention", "client_response", "counselor_clarification",
            "client_response", "counselor_intervention", "client_response",
        ])
        spans = assemble_evidence_episodes_from_turn_functions(turns, labels)
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in spans], [(0, 5)])

    def test_orphan_response_is_excluded_and_diagnosed(self):
        turns = make_turns(["client"])
        spans, diagnostics = assemble_evidence_episodes_with_diagnostics(
            turns, make_labels(["client_response"]),
        )
        self.assertEqual(spans, [])
        self.assertEqual([item.code for item in diagnostics], ["orphan_client_response"])

    def test_other_breaks_active_scene(self):
        turns = make_turns(["counselor", "client", "counselor", "counselor", "client"])
        labels = make_labels([
            "counselor_intervention", "client_response", "other",
            "counselor_intervention", "client_response",
        ])
        spans = assemble_evidence_episodes_from_turn_functions(turns, labels)
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in spans], [(0, 1), (3, 4)])

    def test_max_span_is_constant_and_creates_deterministic_boundary(self):
        roles = ["counselor" if index % 2 == 0 else "client" for index in range(14)]
        functions = ["counselor_intervention" if index % 2 == 0 else "client_response" for index in range(14)]
        spans = assemble_evidence_episodes_from_turn_functions(
            make_turns(roles), make_labels(functions), max_scene_turns=DEFAULT_MAX_SCENE_TURNS,
        )
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in spans], [(0, 11), (12, 13)])

    def test_assembled_span_builds_only_exact_raw_episode_text(self):
        turns = make_turns(["client", "counselor", "client"])
        span = assemble_evidence_episodes_from_turn_functions(
            turns, make_labels(["client_report", "counselor_clarification", "client_report"]),
        )[0]
        text = build_transcript_span_text(turns, span.start_turn_index, span.end_turn_index)
        self.assertEqual(text.splitlines(), [
            "[client] exact raw turn 0", "[counselor] exact raw turn 1", "[client] exact raw turn 2",
        ])

    def test_opt_in_storage_path_passes_assembled_span_to_existing_builder(self):
        turns = make_turns(["client"])
        stored = EvidenceEpisode(
            id="e1", user_id="u", counselor_id="u", case_id="c", session_id="s",
            episode_type="client_event_state", start_turn_index=0, end_turn_index=0,
            source_ref="transcript:s:0-0", episode_text="[client] exact raw turn 0", content_hash="hash",
        )
        raw = {"labels": [{"turn_index": 0, "function": "client_report"}]}
        with (
            patch.object(evidence_turn_functions, "get_transcript_turns", return_value=turns),
            patch.object(evidence_turn_functions, "create_evidence_episode_from_span", return_value=stored) as create,
        ):
            result = evidence_turn_functions.extract_and_store_evidence_episodes_from_turn_functions(
                user_id="u", counselor_id="u", case_id="c", session_id="s", classifier=lambda _: raw,
            )
        self.assertEqual(result.episodes[0].episode_text, "[client] exact raw turn 0")
        self.assertEqual(create.call_args.kwargs["span"], result.spans[0])

    def test_direct_span_baseline_alias_is_backward_compatible(self):
        turns = make_turns(["client"])
        raw = {"episodes": [{
            "episode_type": "client_event_state", "start_turn_index": 0, "end_turn_index": 0,
        }]}
        old = extract_evidence_episode_spans(turns=turns, extractor=lambda _: raw)
        direct = extract_evidence_episode_spans_direct(turns=turns, extractor=lambda _: raw)
        self.assertEqual(old, direct)

    def test_fixture_has_explicit_complete_turn_function_gold(self):
        corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(sum(len(item["turn_function_gold"]) for item in corpus["sessions"]), 64)
        for session in corpus["sessions"]:
            self.assertEqual(
                {item["turn_index"] for item in session["turns"]},
                {item["turn_index"] for item in session["turn_function_gold"]},
            )

    def test_prompt_has_four_non_fixture_few_shots_and_no_text_output(self):
        corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
        session = corpus["sessions"][0]
        turns = [StoredTranscriptTurn(
            id=f't{item["turn_index"]}', user_id=corpus["user_id"], counselor_id=corpus["counselor_id"],
            case_id=corpus["case_id"], session_id=session["session_id"], **item,
        ) for item in session["turns"]]
        prompt = _build_turn_function_prompt(turns)
        for number in range(1, 5):
            self.assertIn(f"Few-shot {number}", prompt)
        self.assertIn("ONLY turn_index and function", prompt)
        self.assertIn("NOT clinical interpretation", prompt)
        self.assertNotIn("저녁 메뉴를 물으셨는데", prompt.split("Few-shot 1")[1].split("Transcript:")[0])

    def test_three_run_evaluation_artifact_structure(self):
        from research.raw_evidence_experiments.scripts.evaluate_turn_function_assembly import evaluate

        corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
        outputs = {}
        for run_index in range(3):
            for session in corpus["sessions"]:
                turns = [StoredTranscriptTurn(
                    id=f't{item["turn_index"]}', user_id=corpus["user_id"], counselor_id=corpus["counselor_id"],
                    case_id=corpus["case_id"], session_id=session["session_id"], **item,
                ) for item in session["turns"]]
                labels = [TurnFunctionLabel.model_validate(item) for item in session["turn_function_gold"]]
                spans, diagnostics = assemble_evidence_episodes_with_diagnostics(turns, labels)
                outputs[(run_index, session["session_number"])] = (turns, labels, spans, diagnostics)
        direct = {"model": "test", "prompt_only": {"mean_metrics": {}, "stability": {}, "runs": []}}
        artifact = evaluate(corpus, direct, outputs)
        self.assertEqual(artifact["runs"], 3)
        self.assertEqual(len(artifact["turn_function_labeling"]["runs"]), 3)
        self.assertEqual(len(artifact["function_labeling_episode_assembly"]["runs"]), 3)
        self.assertEqual(len(artifact["required_case_details"]), 4)
        self.assertEqual(artifact["turn_function_labeling"]["stability"]["turn_label_exact_agreement_rate"], 1.0)
        self.assertGreaterEqual(artifact["gold_label_oracle_assembly"]["metrics"]["matched_gold_count"], 14)


if __name__ == "__main__":
    unittest.main()
