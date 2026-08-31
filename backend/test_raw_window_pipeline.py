import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas.evidence import RetrievedTranscriptWindow, StoredTranscriptTurn
from app.services import raw_evidence_retrieval, transcript_windows
from app.services.raw_evidence_retrieval import build_candidate_regions, retrieve_transcript_window_candidates
from app.services.transcript_windows import (
    build_transcript_window_source_ref, build_transcript_windows, ensure_transcript_window_embedding,
)


def make_turns(count=8, *, user_id="u", case_id="c", session_id="s"):
    return [StoredTranscriptTurn(
        id=f"{session_id}-{index}", user_id=user_id, counselor_id=user_id, case_id=case_id,
        session_id=session_id, turn_index=index,
        speaker_role="client" if index % 2 == 0 else "counselor",
        sanitized_text=f"exact raw turn {index}",
    ) for index in range(count)]


def window(window_id, session_id, start, end, score, session_number=1):
    return RetrievedTranscriptWindow(
        window_id=window_id, session_id=session_id, session_number=session_number,
        start_turn_index=start, end_turn_index=end,
        source_ref=f"transcript_window:{session_id}:{start}-{end}",
        window_text="untrusted retrieved window text", similarity_score=score,
    )


class RawWindowPipelineTests(unittest.TestCase):
    def test_deterministic_windows_overlap_and_terminal_coverage(self):
        windows = build_transcript_windows(make_turns(8))
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in windows], [(0, 5), (2, 7)])
        self.assertEqual(windows[-1].end_turn_index, 7)
        self.assertEqual(windows[0].window_text.splitlines(), [
            "[client] exact raw turn 0", "[counselor] exact raw turn 1", "[client] exact raw turn 2",
            "[counselor] exact raw turn 3", "[client] exact raw turn 4", "[counselor] exact raw turn 5",
        ])

    def test_terminal_window_is_added_after_regular_stride_windows(self):
        windows = build_transcript_windows(make_turns(10))
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in windows], [
            (0, 5), (3, 8), (4, 9),
        ])

    def test_window_source_ref_is_deterministic(self):
        expected = "transcript_window:s:2-7"
        self.assertEqual(build_transcript_window_source_ref("s", 2, 7), expected)
        self.assertEqual(build_transcript_window_source_ref("s", 2, 7), expected)

    def test_window_builder_rejects_mixed_ownership_scope(self):
        turns = make_turns(3)
        turns[2] = turns[2].model_copy(update={"user_id": "other", "case_id": "other-case"})
        with self.assertRaisesRegex(ValueError, "one user/case/session scope"):
            build_transcript_windows(turns)

    def test_window_embedding_uses_exact_window_text_and_reuses_hash(self):
        row = build_transcript_windows(make_turns(6))[0].model_dump(mode="json")

        class Storage:
            def __init__(self):
                self.existing = {"content_hash": row["content_hash"], "embedding_model": None, "embedding": None}
                self.updated = None
            def maybe_single(self, *_): return self.existing
            def update(self, _table, values, **_):
                self.updated = values
                self.existing.update(values)
                return []

        class Provider:
            def __init__(self): self.inputs = []
            def embed(self, texts): self.inputs.extend(texts); return [[0.1, 0.2]]

        storage, provider = Storage(), Provider()
        with patch.object(transcript_windows, "storage", storage), patch.object(
            transcript_windows, "get_embedding_provider", return_value=provider,
        ):
            self.assertTrue(ensure_transcript_window_embedding(row))
            self.assertEqual(provider.inputs, [row["window_text"]])
            self.assertFalse(ensure_transcript_window_embedding(row))
            self.assertEqual(len(provider.inputs), 1)

    def test_dense_candidate_retrieval_enforces_scope_k_and_order(self):
        rows = [window("w1", "s1", 0, 5, .9).model_dump(), window("w2", "s2", 0, 5, .8, 2).model_dump()]

        class Storage:
            params = None
            def rpc(self, name, params):
                self.params = params
                self.name = name
                return rows

        storage = Storage()
        with patch.object(raw_evidence_retrieval, "storage", storage), patch.object(
            raw_evidence_retrieval, "embed_query", return_value=[1.0],
        ):
            results = retrieve_transcript_window_candidates(
                query_text="query", user_id="u", case_id="c", candidate_k=12,
            )
        self.assertEqual(storage.name, "match_transcript_windows")
        self.assertEqual(storage.params["filter_user_id"], "u")
        self.assertEqual(storage.params["filter_case_id"], "c")
        self.assertEqual(storage.params["match_count"], 12)
        self.assertEqual([item.window_id for item in results], ["w1", "w2"])

    def test_overlapping_windows_merge_then_expand_from_raw_turns(self):
        turns = make_turns(12, session_id="s3")
        regions = build_candidate_regions(
            windows=[window("a", "s3", 4, 9, .9, 3), window("b", "s3", 7, 10, .8, 3)],
            user_id="u", case_id="c", turn_loader=lambda **_: turns,
        )
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in regions], [(2, 11)])
        self.assertNotIn("untrusted retrieved window text", regions[0].region_text)
        self.assertEqual(regions[0].region_text.splitlines()[0], "[client] exact raw turn 2")
        self.assertEqual(regions[0].region_text.splitlines()[-1], "[counselor] exact raw turn 11")

    def test_adjacent_windows_are_merged(self):
        turns = make_turns(10, session_id="s")
        regions = build_candidate_regions(
            windows=[window("a", "s", 0, 2, .9), window("b", "s", 3, 5, .8)],
            user_id="u", case_id="c", context_expansion=0, turn_loader=lambda **_: turns,
        )
        self.assertEqual([(item.start_turn_index, item.end_turn_index) for item in regions], [(0, 5)])

    def test_migration_has_rls_scope_cosine_and_no_security_definer(self):
        sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260828000300_transcript_window_retrieval.sql").read_text(encoding="utf-8")
        self.assertIn("alter table public.transcript_windows enable row level security", sql)
        self.assertIn("(select auth.uid())::text = user_id", sql)
        self.assertIn("revoke all on table public.transcript_windows from anon", sql)
        self.assertIn("w.user_id = filter_user_id", sql)
        self.assertIn("w.case_id = filter_case_id", sql)
        self.assertIn("operator(extensions.<=>) query_embedding", sql)
        self.assertIn("security invoker", sql)
        self.assertNotIn("security definer", sql)


if __name__ == "__main__":
    unittest.main()
