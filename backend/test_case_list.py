"""Case list aggregation and ownership tests; all counseling content is synthetic.

Offline: the real routes, stub generation, and storage helpers run against the
in-memory PostgREST substitute from test_persistence_workflow. Hosted RLS is
not exercised here.
Run: python -m unittest test_case_list
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.schemas.note import CaseListResponse
from app.services.supabase_storage import aggregate_case_list
from test_persistence_workflow import INPUT, OTHER_TOKEN, TOKEN, offline_environment


class AggregateCaseListTests(unittest.TestCase):
    def test_counts_dates_and_activity_ordering(self) -> None:
        cases = [
            {"id": "CASE-OLD", "case_alias": "가명 A", "status": "active", "created_at": "2026-01-01T00:00:00Z",
             "total_scheduled_session_count": 10, "next_scheduled_date": "2026-10-01"},
            {"id": "CASE-NEW", "case_alias": None, "status": "closed", "created_at": "2026-02-01T00:00:00Z"},
        ]
        sessions = [
            {"case_id": "CASE-OLD", "session_number": 1, "session_date": "2026-03-02", "transcript_status": "completed", "created_at": "2026-03-02T00:00:00Z"},
            {"case_id": "CASE-OLD", "session_number": 3, "session_date": "2026-03-01", "transcript_status": "none", "created_at": "2026-03-01T00:00:00Z"},
            {"case_id": "CASE-FOREIGN", "session_number": 1, "session_date": "2026-03-09", "transcript_status": "completed"},
        ]
        notes = [
            {"case_id": "CASE-OLD", "note_type": "session_note", "confirmation_status": "confirmed", "created_at": "2026-03-01T01:00:00Z", "updated_at": "2026-09-01T00:00:00Z"},
            {"case_id": "CASE-OLD", "note_type": "session_note", "confirmation_status": "draft", "created_at": "2026-03-02T01:00:00Z"},
            {"case_id": "CASE-OLD", "note_type": "supervision_report", "confirmation_status": "draft", "created_at": "2026-03-02T02:00:00Z"},
        ]
        exports = [{"case_id": "CASE-OLD", "created_at": "2026-03-03T00:00:00Z"}]
        drafts = [{"case_id": "CASE-NEW", "session_number": 1, "saved_at": "2026-08-01T00:00:00Z"}]

        response = aggregate_case_list(cases, sessions, notes, exports, drafts)

        self.assertEqual(response.total_count, 2)
        self.assertEqual([item.case_id for item in response.cases], ["CASE-OLD", "CASE-NEW"])
        old = response.cases[0]
        self.assertEqual(old.case_alias, "가명 A")
        self.assertEqual(old.total_session_count, 2)
        self.assertEqual(old.latest_session_number, 3)
        self.assertEqual(old.first_consultation_date, "2026-03-01")
        self.assertEqual(old.latest_consultation_date, "2026-03-02")
        self.assertEqual(old.transcript_completed_count, 1)
        self.assertEqual(old.confirmed_note_count, 1)
        self.assertEqual(old.draft_note_count, 1)
        self.assertEqual(old.document_count, 3)
        self.assertEqual(old.export_count, 1)
        self.assertEqual(old.temporary_draft_count, 0)
        self.assertEqual(old.total_scheduled_session_count, 10)
        self.assertEqual(old.next_scheduled_date, "2026-10-01")
        self.assertEqual(old.updated_at, "2026-09-01T00:00:00Z")
        new = response.cases[1]
        self.assertEqual(new.status, "closed")
        self.assertEqual(new.total_session_count, 0)
        self.assertEqual(new.temporary_draft_count, 1)
        self.assertEqual(new.updated_at, "2026-08-01T00:00:00Z")

    def test_child_rows_never_create_cases(self) -> None:
        response = aggregate_case_list([], [{"case_id": "X", "session_number": 1}], [{"case_id": "X"}], [], [{"case_id": "X"}])
        self.assertEqual(response, CaseListResponse())


class CaseListRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = offline_environment()
        self.store = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers_a = {"Authorization": f"Bearer {TOKEN}"}
        self.headers_b = {"Authorization": f"Bearer {OTHER_TOKEN}"}

    def generate(self, headers: dict[str, str], **overrides) -> dict:
        response = self.client.post("/api/notes/generate", json={**INPUT, **overrides}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertTrue(response.json()["persistence_report"]["stored"])
        return response.json()

    def test_owned_cases_are_listed_with_counts_and_isolated_per_user(self) -> None:
        self.generate(self.headers_a, session_number=1, client_alias="합성 가명")
        second = self.generate(self.headers_a, session_number=2, session_date="2026-09-10", transcript_text="")
        self.generate(self.headers_b, case_id="SYNTHETIC-OTHER-USER")
        saved = self.client.post("/api/notes/drafts", headers=self.headers_a,
                                 json={"case_id": INPUT["case_id"], "session_number": 2, "form": INPUT})
        self.assertEqual(saved.status_code, 200)
        note_id = second["persistence_report"]["note_id"]
        confirm = self.client.post("/api/notes/confirm", headers=self.headers_a, json={
            "note_id": note_id, "confirmed_note": {"session_content": "상담사 확정 문장"},
            "counselor_edited": True, "create_case_memory": False,
        })
        self.assertEqual(confirm.status_code, 200, confirm.text[:200])

        listed = self.client.get("/api/cases", headers=self.headers_a)
        self.assertEqual(listed.status_code, 200, listed.text[:200])
        payload = listed.json()
        self.assertEqual(payload["total_count"], 1)
        item = payload["cases"][0]
        self.assertEqual(item["case_id"], INPUT["case_id"])
        self.assertEqual(item["case_alias"], "합성 가명")
        self.assertEqual(item["total_session_count"], 2)
        self.assertEqual(item["latest_session_number"], 2)
        self.assertEqual(item["first_consultation_date"], "2026-09-09")
        self.assertEqual(item["latest_consultation_date"], "2026-09-10")
        self.assertEqual(item["transcript_completed_count"], 1)
        self.assertEqual(item["confirmed_note_count"], 1)
        self.assertEqual(item["draft_note_count"], 1)
        self.assertEqual(item["document_count"], 2)
        self.assertEqual(item["temporary_draft_count"], 1)
        self.assertNotIn("SYNTHETIC-OTHER-USER", listed.text)

        other = self.client.get("/api/cases", headers=self.headers_b).json()
        self.assertEqual([case["case_id"] for case in other["cases"]], ["SYNTHETIC-OTHER-USER"])
        self.assertNotIn(INPUT["case_id"], str(other))
        dashboard = self.client.get(f"/api/cases/{INPUT['case_id']}/dashboard", headers=self.headers_b)
        self.assertEqual(dashboard.status_code, 404)

    def test_empty_list_for_new_user_and_missing_token(self) -> None:
        self.assertEqual(self.client.get("/api/cases").status_code, 401)
        self.assertEqual(self.client.get("/api/cases", headers={"Authorization": "Bearer invalid"}).status_code, 401)
        self.assertEqual(self.store.calls, [], "unauthenticated requests must never reach storage")
        self.assertEqual(self.client.get("/api/cases", headers=self.headers_b).json(), {"cases": [], "total_count": 0})

    def test_draft_table_failure_does_not_hide_cases(self) -> None:
        self.generate(self.headers_a)
        original = self.store.request

        def failing(method, table, **kwargs):
            if table == settings.supabase_drafts_table and method == "GET":
                from app.services.supabase_storage import SupabaseStorageError
                raise SupabaseStorageError("synthetic drafts outage")
            return original(method, table, **kwargs)

        with patch.object(self.store, "request", side_effect=failing):
            listed = self.client.get("/api/cases", headers=self.headers_a)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["cases"][0]["temporary_draft_count"], 0)
        self.assertEqual(listed.json()["cases"][0]["total_session_count"], 1)

    def test_serverless_entry_point_matches_route(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from api.cases.list import app as wrapper

        self.generate(self.headers_a)
        wrapper_client = TestClient(wrapper)
        for path in ("/api/cases", "/api/cases/list", "/"):
            response = wrapper_client.get(path, headers=self.headers_a)
            self.assertEqual(response.status_code, 200, path)
            self.assertEqual(response.json()["cases"][0]["case_id"], INPUT["case_id"])
            self.assertEqual(wrapper_client.get(path).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
