import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.schemas.note import InputSources, SanitizedInput, SessionInput
from app.services.supabase_storage import persist_generated_note, persist_transcript_evidence


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, **_):
        return self.value


class FakeStorage:
    configured = True

    def __init__(self):
        self.inserts = []
        self.transcript_turns = [{"id": "existing-turn", "sanitized_text": "existing"}]
        self.transcript_windows = [{"id": "existing-window", "embedding": [1.0]}]

    def maybe_single(self, table, query):
        return None

    def upsert(self, table, rows, *, on_conflict):
        if table == "sessions":
            return [{"id": "session-1", **rows[0]}]
        return rows

    def insert(self, table, rows, *, return_representation=True):
        self.inserts.append((table, rows))
        if table == "generated_notes":
            return [{"id": "note-1", **rows[0]}]
        return []


def make_input(transcript_text):
    return SessionInput(
        case_id="CASE-1",
        session_number=1,
        counselor_memo="synthetic memo",
        transcript_text=transcript_text,
        persist=True,
    )


def make_result(sanitized_transcript):
    sanitized_input = SanitizedInput(
        case_id="CASE-1",
        session_number=1,
        session_date="",
        counselor_name="",
        sources=InputSources(
            counselor_memo="synthetic memo",
            transcript_text=sanitized_transcript,
        ),
    )
    return SimpleNamespace(
        session_summary_draft=Dumpable({}),
        grounding=None,
        evidence_mapped_data=SimpleNamespace(items=[SimpleNamespace(
            evidence_type="transcript",
            source_refs=["transcript.turn_1"],
            content="synthetic evidence",
            field="session_content",
        )]),
        verification_report=Dumpable({}),
        sanitized_input=sanitized_input,
    )


class NoteTranscriptPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.original_enable_persistence = settings.enable_persistence
        settings.enable_persistence = True

    def tearDown(self):
        settings.enable_persistence = self.original_enable_persistence

    def test_persisted_transcript_is_stored_and_indexed_from_sanitized_text(self):
        storage = FakeStorage()
        result = make_result("Client: [PERSON]은 불안해요.\n상담자: 함께 살펴볼게요.")

        with patch("app.services.supabase_storage._storage_for_actor", return_value=storage), patch(
            "app.services.transcript_storage.store_transcript_turns"
        ) as store_turns, patch(
            "app.services.transcript_windows.index_transcript_windows"
        ) as index_windows:
            store_turns.return_value = [SimpleNamespace() for _ in range(2)]
            index_windows.return_value = ([SimpleNamespace()], 1)
            report = persist_generated_note(make_input("Client: 홍길동은 불안해요."), result, actor="user-1")

        self.assertTrue(report.stored)
        self.assertTrue(report.evidence_indexing_attempted)
        self.assertTrue(report.evidence_indexing_succeeded)
        stored_turns = store_turns.call_args.kwargs["turns"]
        self.assertEqual([turn.sanitized_text for turn in stored_turns], ["[PERSON]은 불안해요.", "함께 살펴볼게요."])
        self.assertNotIn("홍길동", " ".join(turn.sanitized_text for turn in stored_turns))
        index_windows.assert_called_once_with(
            user_id="user-1",
            counselor_id="user-1",
            case_id="CASE-1",
            session_id="session-1",
            storage_client=storage,
        )

    def test_persistence_without_transcript_skips_raw_evidence_indexing(self):
        storage = FakeStorage()
        existing_turns = list(storage.transcript_turns)
        existing_windows = list(storage.transcript_windows)
        with patch("app.services.supabase_storage._storage_for_actor", return_value=storage):
            report = persist_generated_note(make_input(""), make_result(""), actor="user-1")

        self.assertTrue(report.stored)
        self.assertFalse(report.evidence_indexing_attempted)
        self.assertFalse(report.evidence_indexing_succeeded)
        self.assertEqual(storage.transcript_turns, existing_turns)
        self.assertEqual(storage.transcript_windows, existing_windows)

    def test_indexing_failure_keeps_note_and_internal_retry_does_not_duplicate_records(self):
        storage = FakeStorage()
        session_input = make_input("Client: synthetic text")
        result = make_result("Client: synthetic text")
        with patch("app.services.supabase_storage._storage_for_actor", return_value=storage), patch(
            "app.services.transcript_storage.store_transcript_turns",
            return_value=[SimpleNamespace()],
        ) as store_turns, patch(
            "app.services.transcript_windows.index_transcript_windows",
            side_effect=RuntimeError("synthetic indexing failure"),
        ) as index_windows:
            report = persist_generated_note(session_input, result, actor="user-1")

            self.assertTrue(report.stored)
            self.assertTrue(report.evidence_indexing_attempted)
            self.assertFalse(report.evidence_indexing_succeeded)
            self.assertIn("synthetic indexing failure", report.evidence_indexing_message)
            self.assertEqual(sum(table == "generated_notes" for table, _ in storage.inserts), 1)
            self.assertEqual(sum(table == "evidence_items" for table, _ in storage.inserts), 1)

            index_windows.side_effect = None
            index_windows.return_value = ([SimpleNamespace()], 1)
            counts = persist_transcript_evidence(
                session_input=session_input,
                result=result,
                user_id="user-1",
                session_id="session-1",
                storage_client=storage,
            )

        self.assertEqual(counts, (1, 1, 1))
        self.assertEqual(store_turns.call_count, 2)
        self.assertEqual(index_windows.call_count, 2)
        self.assertEqual(sum(table == "generated_notes" for table, _ in storage.inserts), 1)
        self.assertEqual(sum(table == "evidence_items" for table, _ in storage.inserts), 1)


if __name__ == "__main__":
    unittest.main()
