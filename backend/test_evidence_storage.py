import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.schemas.evidence import EvidenceEpisodeSpan, TranscriptTurn
from app.services import evidence_storage
from app.services.evidence_storage import (
    EvidenceStorageError, build_episode_source_ref, build_episode_text,
    create_evidence_episode_from_span, get_transcript_turns, store_transcript_turns,
)

FIXTURE_PATH = Path(__file__).parent / "tests" / "fixtures" / "synthetic_transcript_turns.json"


class FakeEvidenceStorage:
    def __init__(self, fixture):
        self.sessions = [{"id": fixture["session_id"], "user_id": fixture["user_id"], "case_id": fixture["case_id"]}]
        self.transcript_turns = []
        self.evidence_episodes = []

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


class EvidenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.corpus = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.fake = FakeEvidenceStorage(self.corpus)
        self.storage_patch = patch.object(evidence_storage, "storage", self.fake)
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
        self.assertEqual(build_episode_source_ref(self.corpus["session_id"], 1, 6), expected)
        self.assertEqual(build_episode_source_ref(self.corpus["session_id"], 1, 6), expected)

    def test_episode_text_is_exact_raw_grounding(self):
        turns = self.store_fixture()
        episode = create_evidence_episode_from_span(
            user_id=self.corpus["user_id"], counselor_id=self.corpus["counselor_id"], case_id=self.corpus["case_id"],
            session_id=self.corpus["session_id"], span=EvidenceEpisodeSpan.model_validate(self.corpus["episode"]),
        )
        expected = [f'[{turn.speaker_role}] {turn.sanitized_text}' for turn in turns if 1 <= turn.turn_index <= 6]
        self.assertEqual(episode.episode_text.splitlines(), expected)
        self.assertTrue(all(turn.sanitized_text in episode.episode_text for turn in turns[1:7]))

    def test_build_orders_shuffled_turns(self):
        text = build_episode_text(list(reversed(self.turns())), 1, 3)
        self.assertEqual(text.splitlines(), [
            "[counselor] 실제 상황처럼 한번 말해볼까요?", "[client] 지금요?",
            "[counselor] 네. 제가 어머니 역할을 해볼게요.",
        ])

    def test_missing_turn_raises(self):
        turns = [turn for turn in self.turns() if turn.turn_index != 4]
        with self.assertRaisesRegex(ValueError, "Missing transcript turns"):
            build_episode_text(turns, 1, 6)

    def test_role_index_fields_are_rejected_by_span_only_schema(self):
        with self.assertRaisesRegex(ValidationError, "Extra inputs are not permitted"):
            EvidenceEpisodeSpan(
                episode_type="intervention_response", start_turn_index=1, end_turn_index=4,
                intervention_turn_indices=[0, 3], response_turn_indices=[2, 4],
            )

    def test_migration_does_not_persist_derived_role_index_arrays(self):
        sql = (Path(__file__).parents[1] / "supabase" / "migrations" / "20260828000100_raw_evidence_layer.sql").read_text(encoding="utf-8")
        self.assertNotIn("intervention_turn_indices", sql)
        self.assertNotIn("response_turn_indices", sql)

    def test_episode_type_role_semantics_are_derived_from_turns(self):
        counselor_only = [TranscriptTurn(turn_index=0, speaker_role="counselor", sanitized_text="질문")]
        with self.assertRaisesRegex(ValueError, "one counselor and one client"):
            evidence_storage.validate_episode_role_feasibility(
                EvidenceEpisodeSpan(episode_type="intervention_response", start_turn_index=0, end_turn_index=0), counselor_only,
            )
        with self.assertRaisesRegex(ValueError, "one client"):
            evidence_storage.validate_episode_role_feasibility(
                EvidenceEpisodeSpan(episode_type="client_event_state", start_turn_index=0, end_turn_index=0), counselor_only,
            )
        evidence_storage.validate_episode_role_feasibility(
            EvidenceEpisodeSpan(episode_type="client_event_state", start_turn_index=0, end_turn_index=1), self.turns()[:2],
        )

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
        with self.assertRaisesRegex(EvidenceStorageError, "requested user/case scope"):
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
