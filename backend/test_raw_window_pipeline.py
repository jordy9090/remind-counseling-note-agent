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


class WindowStorage:
    def __init__(self, turns):
        self.transcript_turns = [turn.model_dump(mode="json") for turn in turns]
        self.transcript_windows = []

    def select(self, table, query):
        rows = list(getattr(self, table))
        for key, condition in query.items():
            if key in {"select", "order", "limit"}:
                continue
            if str(condition).startswith("eq."):
                rows = [row for row in rows if str(row.get(key) or "") == str(condition)[3:]]
        if query.get("order") == "turn_index.asc":
            rows.sort(key=lambda row: row["turn_index"])
        return rows[: int(query.get("limit") or len(rows))]

    def maybe_single(self, table, query):
        rows = self.select(table, query)
        return rows[0] if rows else None

    def upsert(self, table, rows, *, on_conflict):
        target = getattr(self, table)
        keys = on_conflict.split(",")
        stored = []
        for incoming in rows:
            existing = next((row for row in target if all(row.get(key) == incoming.get(key) for key in keys)), None)
            if existing is None:
                existing = {"id": f"{table}-{len(target) + 1}", **incoming}
                target.append(existing)
            else:
                existing.update(incoming)
            stored.append(dict(existing))
        return stored

    def update(self, table, values, *, query, return_representation=True):
        updated = []
        for row in getattr(self, table):
            if all(str(row.get(key) or "") == str(condition)[3:] for key, condition in query.items()):
                row.update(values)
                updated.append(dict(row))
        return updated if return_representation else []

    def delete(self, table, *, query, return_representation=False):
        target = getattr(self, table)
        deleted, kept = [], []
        for row in target:
            matches = all(str(row.get(key) or "") == str(condition)[3:] for key, condition in query.items())
            (deleted if matches else kept).append(row)
        setattr(self, table, kept)
        return deleted if return_representation else []


class Provider:
    def __init__(self):
        self.inputs = []
        self.failure = None

    def embed(self, texts):
        self.inputs.extend(texts)
        if self.failure:
            raise self.failure
        return [[float(len(self.inputs)), 0.0] for _ in texts]


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

    def test_reindex_removes_windows_with_obsolete_boundaries(self):
        storage = WindowStorage(make_turns(8))
        provider = Provider()
        with patch.object(transcript_windows, "get_embedding_provider", return_value=provider):
            transcript_windows.index_transcript_windows(
                user_id="u", counselor_id="u", case_id="c", session_id="s", storage_client=storage,
            )
            self.assertEqual(
                [(row["start_turn_index"], row["end_turn_index"]) for row in storage.transcript_windows],
                [(0, 5), (2, 7)],
            )
            storage.transcript_turns = [turn.model_dump(mode="json") for turn in make_turns(3)]
            transcript_windows.index_transcript_windows(
                user_id="u", counselor_id="u", case_id="c", session_id="s", storage_client=storage,
            )

        self.assertEqual(
            [(row["start_turn_index"], row["end_turn_index"]) for row in storage.transcript_windows],
            [(0, 2)],
        )

    def test_unchanged_hash_and_model_reuse_existing_embedding(self):
        storage = WindowStorage(make_turns(6))
        provider = Provider()
        with patch.object(transcript_windows, "get_embedding_provider", return_value=provider):
            transcript_windows.index_transcript_windows(
                user_id="u", counselor_id="u", case_id="c", session_id="s", storage_client=storage,
            )
            first_embedding = list(storage.transcript_windows[0]["embedding"])
            transcript_windows.index_transcript_windows(
                user_id="u", counselor_id="u", case_id="c", session_id="s", storage_client=storage,
            )

        self.assertEqual(len(provider.inputs), 1)
        self.assertEqual(storage.transcript_windows[0]["embedding"], first_embedding)

    def test_same_length_text_edit_reembeds_and_failure_leaves_no_stale_embedding(self):
        storage = WindowStorage(make_turns(6))
        provider = Provider()
        with patch.object(transcript_windows, "get_embedding_provider", return_value=provider):
            transcript_windows.index_transcript_windows(
                user_id="u", counselor_id="u", case_id="c", session_id="s", storage_client=storage,
            )
            original_hash = storage.transcript_windows[0]["content_hash"]
            original_embedding = storage.transcript_windows[0]["embedding"]
            original_text = storage.transcript_turns[2]["sanitized_text"]
            edited_text = "alter raw turn 2"
            self.assertEqual(len(edited_text), len(original_text))
            storage.transcript_turns[2]["sanitized_text"] = edited_text
            transcript_windows.index_transcript_windows(
                user_id="u", counselor_id="u", case_id="c", session_id="s", storage_client=storage,
            )
            self.assertNotEqual(storage.transcript_windows[0]["content_hash"], original_hash)
            self.assertNotEqual(storage.transcript_windows[0]["embedding"], original_embedding)
            self.assertEqual(len(provider.inputs), 2)

            storage.transcript_turns[2]["sanitized_text"] = "final raw turn 2"
            provider.failure = RuntimeError("synthetic embedding failure")
            with self.assertRaisesRegex(RuntimeError, "synthetic embedding failure"):
                transcript_windows.index_transcript_windows(
                    user_id="u", counselor_id="u", case_id="c", session_id="s", storage_client=storage,
                )

        self.assertEqual(len(storage.transcript_windows), 1)
        self.assertFalse(storage.transcript_windows[0].get("embedding"))

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
        sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260903000200_transcript_window_retrieval.sql").read_text(encoding="utf-8")
        self.assertIn("alter table public.transcript_windows enable row level security", sql)
        self.assertIn("(select auth.uid())::text = user_id", sql)
        self.assertIn("revoke all on table public.transcript_windows from anon", sql)
        self.assertIn("w.user_id = filter_user_id", sql)
        self.assertIn("w.case_id = filter_case_id", sql)
        self.assertIn("filter_user_id = (select auth.uid())::text", sql)
        self.assertIn("s.case_id = transcript_windows.case_id", sql)
        self.assertIn("s.user_id = transcript_windows.user_id", sql)
        self.assertIn("operator(extensions.<=>) query_embedding", sql)
        self.assertIn("security invoker", sql)
        self.assertNotIn("security definer", sql)


if __name__ == "__main__":
    unittest.main()
