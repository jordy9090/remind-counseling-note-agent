"""Synthetic evidence retention, privacy masking and payload-boundary regressions."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app.schemas.note import TemporaryDraftSaveRequest
from app.services import draft_store
from app.services.temporary_draft_payload import temporary_draft_payload


class SummaryEvidencePersistenceTests(unittest.TestCase):
    def test_history_round_trip_masks_excerpt_and_keeps_owner_boundary(self):
        evidence = {"label": "축어록", "excerpt": "내담자: 연락처는 010-1234-5678이고 목이 답답했어요.",
                    "sourceRef": "transcript.turn_2", "sourceType": "transcript", "confidence": "high", "needsReview": False,
                    "raw_input": "SYNTHETIC-RAW-INPUT"}
        request = TemporaryDraftSaveRequest(case_id="quick-summary", session_number=0, screen="quick_summary", form={},
            draft_sections=[{"id": "client_response", "title": "내담자 반응", "content": "답답함을 표현함.",
                             "visible": True, "requiresReview": False, "evidence": [evidence]}])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TEMP_DRAFT_DIR": directory}), \
                patch("app.services.supabase_store.configured_for", return_value=False):
            saved = draft_store.save_temporary_draft(request, actor="synthetic-owner")
            loaded = draft_store.get_temporary_draft(saved.draft_id, actor="synthetic-owner")
            self.assertIsNone(draft_store.get_temporary_draft(saved.draft_id, actor="synthetic-other"))
            self.assertEqual(1, len(draft_store.list_temporary_drafts(actor="synthetic-owner")))
            self.assertEqual({}, loaded.form)
            self.assertNotIn("010-1234-5678", loaded.model_dump_json())
            self.assertNotIn("SYNTHETIC-RAW-INPUT", loaded.model_dump_json())
            restored = loaded.draft_sections[0]["evidence"][0]
            self.assertEqual("transcript.turn_2", restored["sourceRef"])
            self.assertIn("목이 답답했어요.", restored["excerpt"])
            self.assertFalse(restored["needsReview"])

    def test_unattributed_cache_whole_transcript_and_malformed_excerpts_are_dropped(self):
        for evidence in (None, [{"excerpt": "SYNTHETIC-RAW-CACHE"}],
                         [{"label": "원문", "excerpt": "SYNTHETIC-RAW-CACHE", "sourceRef": "transcript_text", "sourceType": "transcript"}],
                         [{"label": "원문", "excerpt": "SYNTHETIC-RAW-CACHE", "sourceRef": "transcript.turn_1", "sourceType": "counselor_memo"}]):
            with self.subTest(evidence=evidence):
                saved = temporary_draft_payload({"draft_sections": [{"id": "client_response", "evidence": evidence}]})
                self.assertNotIn("SYNTHETIC-RAW-CACHE", json.dumps(saved))
                self.assertNotIn("evidence", saved["draft_sections"][0])


if __name__ == "__main__":
    unittest.main()
