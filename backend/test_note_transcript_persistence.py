import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.config import settings
from app.schemas.note import InputSources, SanitizedInput, SessionInput
from app.services.supabase_storage import persist_generated_note


class Dumpable:
    def __init__(self, value):
        self.value = value

    def model_dump(self, **_):
        return self.value


class FakeStorage:
    configured = True

    def __init__(self):
        self.inserts = []

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
        evidence_mapped_data=SimpleNamespace(items=[]),
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
            report = persist_generated_note(make_input("Client: 홍길동은 불안해요."), result, actor="user-1")

        self.assertTrue(report.stored)
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
        with patch("app.services.supabase_storage._storage_for_actor", return_value=storage), patch(
            "app.services.transcript_storage.store_transcript_turns"
        ) as store_turns, patch(
            "app.services.transcript_windows.index_transcript_windows"
        ) as index_windows:
            report = persist_generated_note(make_input(""), make_result(""), actor="user-1")

        self.assertTrue(report.stored)
        store_turns.assert_not_called()
        index_windows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
