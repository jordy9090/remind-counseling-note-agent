import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas.evidence import (
    EpisodeExtractionPayload, EvidenceEpisodeSpan, RetrievedEvidenceEpisode, StoredTranscriptTurn,
)
from app.services import evidence_extraction, evidence_retrieval
from app.services.evidence_extraction import consolidate_episode_fragments, extract_evidence_episode_spans
from app.services.evidence_retrieval import diversify_evidence_episodes, retrieve_evidence_episodes, span_overlap_ratio

FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "synthetic_raw_dialogue_longitudinal.json"


def episode(episode_id, session, start, end, score, episode_type="client_event_state", source_ref=None):
    return RetrievedEvidenceEpisode(
        episode_id=episode_id, session_id=f"s{session}", session_number=session, episode_type=episode_type,
        start_turn_index=start, end_turn_index=end, source_ref=source_ref or f"transcript:s{session}:{start}-{end}",
        episode_text=f"stored exact text {episode_id}", similarity_score=score,
    )


class FakeRetrievalStorage:
    def __init__(self, rows):
        self.rows = rows
        self.last_params = None

    def rpc(self, name, params):
        self.last_params = params
        assert name == "match_evidence_episodes"
        return self.rows[: min(max(params["match_count"], 1), 50)]


class EvidencePipelineTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads(FIXTURE.read_text(encoding="utf-8"))
        session = self.corpus["sessions"][2]
        self.turns = [StoredTranscriptTurn(
            id=f't{i}', user_id=self.corpus["user_id"], counselor_id=self.corpus["counselor_id"],
            case_id=self.corpus["case_id"], session_id=session["session_id"], **turn,
        ) for i, turn in enumerate(session["turns"])]

    def test_structured_valid_extraction_and_duplicate_dedup(self):
        candidate = self.corpus["sessions"][2]["gold_episodes"][0]
        spans = extract_evidence_episode_spans(
            turns=self.turns, extractor=lambda _: {"episodes": [candidate, candidate]},
        )
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].episode_type, "intervention_response")

    def test_malformed_and_speaker_role_mismatch_are_rejected_independently(self):
        raw = {"episodes": [
            {"episode_type": "client_event_state", "start_turn_index": 0, "end_turn_index": 99,
            },
            {"episode_type": "intervention_response", "start_turn_index": 0, "end_turn_index": 0},
            self.corpus["sessions"][2]["gold_episodes"][0],
        ]}
        spans = extract_evidence_episode_spans(turns=self.turns, extractor=lambda _: raw)
        self.assertEqual(len(spans), 1)

    def test_llm_summary_field_cannot_become_stored_evidence(self):
        invalid = {**self.corpus["sessions"][2]["gold_episodes"][0], "summary": "LLM이 만든 요약"}
        spans = extract_evidence_episode_spans(turns=self.turns, extractor=lambda _: {"episodes": [invalid]})
        self.assertEqual(spans, [])

    def test_llm_role_index_fields_are_rejected(self):
        invalid = {**self.corpus["sessions"][2]["gold_episodes"][0], "response_turn_indices": [1, 3]}
        spans = extract_evidence_episode_spans(turns=self.turns, extractor=lambda _: {"episodes": [invalid]})
        self.assertEqual(spans, [])

    def test_scene_fragment_consolidation_helper_uses_span_only_inputs(self):
        raw = {"episodes": [
            {"episode_type": "intervention_response", "start_turn_index": 0, "end_turn_index": 1,
            },
            {"episode_type": "intervention_response", "start_turn_index": 2, "end_turn_index": 3,
            },
            {"episode_type": "intervention_response", "start_turn_index": 4, "end_turn_index": 7,
            },
        ]}
        spans = extract_evidence_episode_spans(turns=self.turns, extractor=lambda _: raw)
        consolidated, _ = consolidate_episode_fragments(spans, turns=self.turns)
        self.assertEqual([(span.start_turn_index, span.end_turn_index) for span in consolidated], [(0, 7)])
        self.assertEqual(consolidated[0].episode_type, "intervention_response")

    def test_consolidation_off_on_ablation_uses_same_validated_spans(self):
        raw = {"episodes": [
            {"episode_type": "intervention_response", "start_turn_index": 0, "end_turn_index": 1},
            {"episode_type": "intervention_response", "start_turn_index": 2, "end_turn_index": 3},
        ]}
        off, _ = evidence_extraction._extract_with_diagnostics(
            turns=self.turns, extractor=lambda _: raw, consolidate_fragments=False,
        )
        on, _ = evidence_extraction._extract_with_diagnostics(
            turns=self.turns, extractor=lambda _: raw, consolidate_fragments=True,
        )
        self.assertEqual([(span.start_turn_index, span.end_turn_index) for span in off], [(0, 1), (2, 3)])
        self.assertEqual([(span.start_turn_index, span.end_turn_index) for span in on], [(0, 3)])

    def test_event_to_intervention_transition_remains_two_episodes(self):
        raw = {"episodes": [
            {"episode_type": "client_event_state", "start_turn_index": 0, "end_turn_index": 1},
            {"episode_type": "intervention_response", "start_turn_index": 2, "end_turn_index": 3},
        ]}
        spans = extract_evidence_episode_spans(turns=self.turns, extractor=lambda _: raw)
        self.assertEqual(
            [(span.episode_type, span.start_turn_index, span.end_turn_index) for span in spans],
            [("client_event_state", 0, 1), ("intervention_response", 2, 3)],
        )

    def test_span_only_payload_rejects_internal_metadata_and_role_indices(self):
        for extra in (
            {"metadata_json": {"model_note": "not allowed"}},
            {"intervention_turn_indices": [0], "response_turn_indices": [1]},
        ):
            raw = {"episodes": [{
                "episode_type": "intervention_response", "start_turn_index": 0, "end_turn_index": 1, **extra,
            }]}
            with self.assertRaises(ValidationError):
                EpisodeExtractionPayload.model_validate(raw)
            spans = extract_evidence_episode_spans(turns=self.turns, extractor=lambda _, value=raw: value)
            self.assertEqual(spans, [])

    def test_coverage_recovery_only_sends_uncovered_client_heavy_turns(self):
        seen_indices = []

        def extractor(turns):
            seen_indices.extend(turn.turn_index for turn in turns)
            return {"episodes": [{
                "episode_type": "client_event_state", "start_turn_index": 4, "end_turn_index": 7,
            }]}

        recovered, diagnostics = evidence_extraction.extract_uncovered_client_event_spans(
            turns=self.turns,
            first_pass_spans=[EvidenceEpisodeSpan(
                episode_type="intervention_response", start_turn_index=0, end_turn_index=3,
            )],
            extractor=extractor,
        )
        self.assertEqual(seen_indices, [4, 5, 6, 7])
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in recovered], [(4, 7)])
        self.assertEqual(diagnostics, [])

    def test_coverage_recovery_rejects_intervention_and_cross_gap_spans(self):
        first_pass = [EvidenceEpisodeSpan(
            episode_type="intervention_response", start_turn_index=2, end_turn_index=3,
        )]
        raw = {"episodes": [
            {"episode_type": "intervention_response", "start_turn_index": 0, "end_turn_index": 1},
            {"episode_type": "client_event_state", "start_turn_index": 0, "end_turn_index": 4},
        ]}
        recovered, diagnostics = evidence_extraction.extract_uncovered_client_event_spans(
            turns=self.turns, first_pass_spans=first_pass, extractor=lambda _: raw,
        )
        self.assertEqual(recovered, [])
        self.assertTrue(any(item.code == "invalid_coverage_episode" for item in diagnostics))
        self.assertTrue(any(item.code == "invalid_episode" for item in diagnostics))

    def test_repeated_run_stability_artifact_shape(self):
        from scripts.evaluate_simplified_scene_extraction import _evaluate_path

        session = self.corpus["sessions"][2]
        spans = [EvidenceEpisodeSpan.model_validate(item) for item in session["gold_episodes"]]
        outputs = {(run_index, session["session_number"]): (self.turns, spans, []) for run_index in range(3)}
        artifact = _evaluate_path({"sessions": [session]}, outputs, consolidate=False)
        self.assertEqual(set(artifact), {"mean_metrics", "stability", "runs"})
        self.assertEqual(len(artifact["runs"]), 3)
        self.assertTrue(all(set(item) == {"run", "metrics", "episodes"} for item in artifact["runs"]))
        self.assertEqual(set(artifact["stability"]), {
            "exact_same_span_rate", "consistent_iou_0_5_match_rate", "gold_episode_count",
        })
        self.assertEqual(artifact["stability"]["exact_same_span_rate"], 1.0)
        self.assertEqual(artifact["stability"]["consistent_iou_0_5_match_rate"], 1.0)

    def test_consolidation_does_not_merge_different_types_or_excessive_span(self):
        first = self.corpus["sessions"][2]["gold_episodes"][0]
        different = {"episode_type": "client_event_state", "start_turn_index": 0, "end_turn_index": 1,
                    }
        spans = extract_evidence_episode_spans(turns=self.turns, extractor=lambda _: {"episodes": [first, different]})
        self.assertEqual(len(spans), 2)
        parsed = [evidence_extraction.EvidenceEpisodeSpan.model_validate(first), evidence_extraction.EvidenceEpisodeSpan(
            episode_type="intervention_response", start_turn_index=8, end_turn_index=9,
        )]
        extended_turns = self.turns + [self.turns[0].model_copy(update={"turn_index": 8}), self.turns[1].model_copy(update={"turn_index": 9})]
        kept, _ = consolidate_episode_fragments(parsed, turns=extended_turns, max_scene_turns=8)
        self.assertEqual(len(kept), 2)

    def test_scene_prompt_has_three_non_benchmark_few_shots_and_hard_role_rules(self):
        prompt = evidence_extraction._build_extraction_prompt(self.turns)
        self.assertIn("Few-shot A", prompt)
        self.assertIn("Few-shot B", prompt)
        self.assertIn("Few-shot C", prompt)
        self.assertIn("Few-shot D", prompt)
        self.assertIn("MUST include >=1 actual counselor turn", prompt)
        self.assertIn("do NOT select only the few most important scenes", prompt)
        self.assertNotIn("엄마가 반대할 것 같으면 말을 못 하겠어요", prompt)

    def test_embedding_uses_episode_text_and_reuses_unchanged_hash(self):
        episode_row = {
            "id": "e1", "user_id": "u", "case_id": "c", "session_id": "s", "source_ref": "transcript:s:0-1",
            "episode_type": "client_event_state", "episode_text": "[client] exact stored turn", "content_hash": "hash",
        }
        class Storage:
            def __init__(self): self.existing = {"id": "e1", "content_hash": "old", "embedding_model": None, "embedding": None}; self.updated = None
            def maybe_single(self, *_): return self.existing
            def update(self, _table, values, **_): self.updated = values; self.existing.update({"content_hash": "hash", **values}); return []
        class Provider:
            def __init__(self): self.inputs = []
            def embed(self, texts): self.inputs.extend(texts); return [[0.1, 0.2]]
        storage, provider = Storage(), Provider()
        with patch.object(evidence_extraction, "storage", storage), patch.object(evidence_extraction, "get_embedding_provider", return_value=provider):
            self.assertTrue(evidence_extraction._ensure_episode_embedding(episode_row))
            self.assertEqual(provider.inputs, [episode_row["episode_text"]])
            storage.existing["content_hash"] = "hash"
            storage.existing["embedding_model"] = evidence_extraction.settings.embedding_model
            self.assertFalse(evidence_extraction._ensure_episode_embedding(episode_row))
            self.assertEqual(len(provider.inputs), 1)

    def test_retrieval_passes_scope_and_candidate_k_and_returns_db_text(self):
        row = episode("e1", 3, 0, 7, 0.9, "intervention_response").model_dump()
        row["episode_text"] = "[client] DB exact value"
        fake = FakeRetrievalStorage([row])
        with patch.object(evidence_retrieval, "storage", fake), patch.object(evidence_retrieval, "embed_query", return_value=[1.0]):
            results = retrieve_evidence_episodes(query_text="query", user_id="u1", case_id="c1", candidate_k=12)
        self.assertEqual(fake.last_params["filter_user_id"], "u1")
        self.assertEqual(fake.last_params["filter_case_id"], "c1")
        self.assertEqual(fake.last_params["match_count"], 12)
        self.assertEqual(results[0].episode_text, "[client] DB exact value")

    def test_rpc_sql_enforces_scope_and_cosine_order(self):
        sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260828000200_evidence_episode_retrieval.sql").read_text(encoding="utf-8")
        self.assertIn("e.user_id = filter_user_id", sql)
        self.assertIn("e.case_id = filter_case_id", sql)
        self.assertIn("operator(extensions.<=>) query_embedding", sql)
        self.assertIn("order by e.embedding operator(extensions.<=>) query_embedding asc", sql)

    def test_diversification_exact_overlap_cap_and_unique_sessions(self):
        candidates = [
            episode("a", 1, 0, 5, .99), episode("a-copy", 1, 0, 5, .98, source_ref="transcript:s1:0-5"),
            episode("b", 1, 1, 5, .97), episode("c", 1, 7, 8, .96), episode("d", 1, 10, 11, .95),
            episode("e", 2, 0, 2, .94), episode("f", 3, 0, 2, .93), episode("g", 4, 0, 2, .92),
        ]
        diversified = diversify_evidence_episodes(candidates, max_results=5, max_per_session=2)
        self.assertEqual([item.episode_id for item in diversified], ["a", "c", "e", "f", "g"])
        self.assertEqual(len({item.session_id for item in diversified}), 4)
        self.assertLessEqual(max(sum(item.session_id == sid for item in diversified) for sid in {x.session_id for x in diversified}), 2)
        self.assertGreaterEqual(span_overlap_ratio(candidates[0], candidates[2]), .7)

    def test_diversification_preserves_gold_and_type_when_relevance_is_close(self):
        candidates = [episode(str(i), i, 0, 1, .90 - i * .01) for i in range(1, 6)]
        gold = episode("gold", 7, 0, 3, .855, "intervention_response")
        diversified = diversify_evidence_episodes(candidates + [gold], type_diversity_max_score_drop=.05)
        self.assertIn("gold", [item.episode_id for item in diversified])

    def test_fixture_is_raw_synthetic_and_gold_spans_exist(self):
        self.assertEqual(len(self.corpus["sessions"]), 8)
        self.assertEqual(sum(len(session["turns"]) for session in self.corpus["sessions"]), 64)
        self.assertIn("synthetic", self.corpus["description"].lower())
        self.assertIn("negative_control", self.corpus["sessions"][3]["stage"])
        for session in self.corpus["sessions"]:
            indices = {turn["turn_index"] for turn in session["turns"]}
            for gold in session["gold_episodes"]:
                self.assertTrue(set(range(gold["start_turn_index"], gold["end_turn_index"] + 1)) <= indices)


if __name__ == "__main__":
    unittest.main()
