import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas.evidence import TranscriptTurn
from app.services import transcript_storage
from app.services.transcript_storage import (
    TranscriptStorageError,
    build_transcript_source_ref,
    build_transcript_span_text,
    get_transcript_turns,
    store_transcript_turns,
)

FIXTURE_PATH = Path(__file__).parent / "tests" / "fixtures" / "synthetic_transcript_turns.json"


class FakeTranscriptStorage:
    def __init__(self, fixture):
        self.sessions = [{"id": fixture["session_id"], "user_id": fixture["user_id"], "case_id": fixture["case_id"]}]
        self.transcript_turns = []

    def maybe_single(self, table, query):
        rows = self.select(table, query)
        return rows[0] if rows else None

    def select(self, table, query):
        rows = list(getattr(self, table))
        for key, condition in query.items():
            if key in {"select", "order", "limit"}:
                continue
            value = str(condition)
            if value.startswith("eq."):
                rows = [row for row in rows if str(row.get(key) or "") == value[3:]]
        if query.get("order") == "turn_index.asc":
            rows.sort(key=lambda row: row["turn_index"])
        return rows[: int(query.get("limit") or len(rows))]

    def upsert(self, table, rows, *, on_conflict):
        target = getattr(self, table)
        keys = on_conflict.split(",")
        result = []
        for incoming in rows:
            existing = next((row for row in target if all(row.get(key) == incoming.get(key) for key in keys)), None)
            if existing is None:
                existing = {"id": f"{table}-{len(target) + 1}", **incoming}
                target.append(existing)
            else:
                existing.update(incoming)
            result.append(existing)
        return result


class TranscriptStorageTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.fake = FakeTranscriptStorage(self.corpus)
        self.storage_patch = patch.object(transcript_storage, "storage", self.fake)
        self.storage_patch.start()

    def tearDown(self):
        self.storage_patch.stop()

    def turns(self):
        return [TranscriptTurn.model_validate(turn) for turn in self.corpus["turns"]]

    def store_fixture(self):
        return store_transcript_turns(
            user_id=self.corpus["user_id"], counselor_id=self.corpus["counselor_id"], case_id=self.corpus["case_id"],
            session_id=self.corpus["session_id"], turns=self.turns(),
        )

    def test_source_ref_is_deterministic(self):
        expected = f'transcript:{self.corpus["session_id"]}:1-6'
        self.assertEqual(build_transcript_source_ref(self.corpus["session_id"], 1, 6), expected)
        self.assertEqual(build_transcript_source_ref(self.corpus["session_id"], 1, 6), expected)

    def test_build_orders_shuffled_turns(self):
        text = build_transcript_span_text(list(reversed(self.turns())), 1, 3)
        self.assertEqual(text.splitlines(), [
            "[counselor] 실제 상황처럼 한번 말해볼까요?", "[client] 지금요?",
            "[counselor] 네. 제가 어머니 역할을 해볼게요.",
        ])

    def test_missing_turn_raises(self):
        turns = [turn for turn in self.turns() if turn.turn_index != 4]
        with self.assertRaisesRegex(ValueError, "Missing transcript turns"):
            build_transcript_span_text(turns, 1, 6)

    def test_production_migration_contains_turns_without_episode_table(self):
        sql = (
            Path(__file__).parents[1]
            / "supabase"
            / "migrations"
            / "20260828000100_raw_evidence_layer.sql"
        ).read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.transcript_turns", sql)
        self.assertNotIn("public.evidence_episodes", sql)

    def test_ownership_and_case_scope_excludes_other_turns(self):
        self.store_fixture()
        self.fake.transcript_turns.append({
            "id": "foreign", "user_id": "other-user", "counselor_id": "other-user", "case_id": "OTHER-CASE",
            "session_id": self.corpus["session_id"], "turn_index": 99, "speaker_role": "client",
            "sanitized_text": "다른 사용자의 문장", "source_type": "transcript", "metadata_json": {},
        })
        scoped = get_transcript_turns(
            user_id=self.corpus["user_id"], case_id=self.corpus["case_id"], session_id=self.corpus["session_id"],
        )
        self.assertEqual([turn.turn_index for turn in scoped], list(range(7)))
        with self.assertRaisesRegex(TranscriptStorageError, "requested user/case scope"):
            store_transcript_turns(
                user_id="other-user", counselor_id="other-user", case_id=self.corpus["case_id"],
                session_id=self.corpus["session_id"],
                turns=[TranscriptTurn(turn_index=0, speaker_role="unknown", sanitized_text="text")],
            )

    def test_storage_reuses_deidentification(self):
        stored = store_transcript_turns(
            user_id=self.corpus["user_id"], counselor_id=self.corpus["counselor_id"], case_id=self.corpus["case_id"],
            session_id=self.corpus["session_id"],
            turns=[TranscriptTurn(
                turn_index=0, speaker_role="unknown",
                sanitized_text="이름: 홍길동, 전화 010-1234-5678, 이메일 client@example.com",
            )],
        )
        text = stored[0].sanitized_text
        for raw in ("홍길동", "010-1234-5678", "client@example.com"):
            self.assertNotIn(raw, text)
        for token in ("[PERSON]", "[PHONE]", "[EMAIL]"):
            self.assertIn(token, text)
        self.assertEqual(self.fake.transcript_turns[0]["sanitized_text"], text)


if __name__ == "__main__":
    unittest.main()
