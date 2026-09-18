"""Offline persistence integration tests; all counseling content is synthetic.

The real routes, generation stub, persistence helpers and authentication guard run
against an in-memory PostgREST substitute. This does not test hosted Supabase RLS.
Run: python -m unittest test_persistence_workflow
Optional local browser harness: python test_persistence_workflow.py --serve
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from app.core.config import settings
from app.services.supabase_storage import SupabaseStorage
from app.services import supabase_store

TOKEN = "synthetic-access-token"
OTHER_TOKEN = "synthetic-other-token"
INPUT = {
    "case_id": "SYNTHETIC-PERSISTENCE", "session_number": 1,
    "session_date": "2026-09-09", "counselor_name": "합성 상담사",
    "counselor_memo": "합성 내담자는 산책 후 기분이 편안해졌다고 말했다.",
    "transcript_text": "내담자: 산책한 뒤 마음이 편안했어요.",
    "previous_session_summary": "", "persist": True,
}


def json_copy(value):
    return json.loads(json.dumps(value))


class MemoryStore:
    def __init__(self):
        self.tables = {}
        self.calls = []

    def request(self, method, table, *, actor, query=None, body=None, prefer=None):
        self.calls.append((method, table, actor))
        query = query or {}
        rows = self.tables.setdefault(table, [])

        def matches(row):
            if row.get("user_id") != actor:
                return False
            return all(str(row.get(key)) == str(value)[3:]
                       for key, value in query.items() if str(value).startswith("eq."))

        if method == "GET":
            result = [row for row in rows if matches(row)]
            if query.get("order"):
                key, direction = query["order"].split(".")
                result.sort(key=lambda row: str(row.get(key, "")), reverse=direction == "desc")
            if query.get("limit"):
                result = result[:int(query["limit"])]
            return json_copy(result)
        if method == "PATCH":
            result = []
            for row in rows:
                if matches(row):
                    row.update(json_copy(body))
                    result.append(row)
            return json_copy(result)
        if method == "DELETE":
            deleted = [row for row in rows if matches(row)]
            self.tables[table] = [row for row in rows if not matches(row)]
            return json_copy(deleted) if prefer == "return=representation" else None
        if method == "POST":
            result = []
            for value in body if isinstance(body, list) else [body]:
                assert value.get("user_id") == actor, "ownership must come from verified actor"
                conflict = query.get("on_conflict", "").split(",")
                existing = next((row for row in rows if conflict != [""]
                                 and all(row.get(key) == value.get(key) for key in conflict)), None)
                if existing:
                    assert existing["user_id"] == actor
                    existing.update(json_copy(value))
                    result.append(existing)
                else:
                    row = {"id": str(uuid4()), "created_at": "2026-09-09T00:00:00Z", **json_copy(value)}
                    rows.append(row)
                    result.append(row)
            return json_copy(result)
        raise AssertionError(f"Unexpected method {method}")


@contextmanager
def offline_environment():
    store = MemoryStore()
    actors = {TOKEN: "synthetic-user-a", OTHER_TOKEN: "synthetic-user-b"}

    def auth_response(request, **_):
        token = request.get_header("Authorization", "").removeprefix("Bearer ")
        if token not in actors:
            raise HTTPError(request.full_url, 401, "invalid", {}, None)
        return io.BytesIO(json.dumps({"id": actors[token]}).encode())

    def storage_request(storage, method, table, **kwargs):
        assert storage.access_token in actors, "Supabase Bearer token must be forwarded"
        return store.request(method, table, actor=actors[storage.access_token], **kwargs)

    def draft_request(method, actor, **kwargs):
        assert actor.access_token in actors
        return store.request(method, settings.supabase_drafts_table, actor=str(actor), **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.multiple(settings,
            enable_real_user_auth=True, enable_persistence=True, enable_rag=False,
            enable_case_memory=False, enable_raw_region_grounding=False, use_stub=True,
            supabase_url="http://synthetic.invalid", supabase_publishable_key="synthetic-public-key",
            supabase_service_key=None, supabase_service_role_key=None,
        ))
        stack.enter_context(patch("app.api.security.urlopen", side_effect=auth_response))
        stack.enter_context(patch.object(SupabaseStorage, "_request", storage_request))
        stack.enter_context(patch.object(supabase_store, "_request", draft_request))
        yield store


class PersistenceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.context = offline_environment()
        self.store = self.context.__enter__()
        self.addCleanup(self.context.__exit__, None, None, None)
        self.client = TestClient(app, raise_server_exceptions=False)
        self.headers = {"Authorization": f"Bearer {TOKEN}"}

    def generate(self):
        response = self.client.post("/api/notes/generate", json=INPUT, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertTrue(response.json()["persistence_report"]["stored"])
        return response.json()

    def test_temporary_draft_round_trip_and_owner_isolation(self):
        payload = {"case_id": INPUT["case_id"], "session_number": 1, "form": INPUT,
                   "draft_sections": [{"id": "session_content", "content": "합성 편집 문장"}]}
        saved = self.client.post("/api/notes/drafts", json=payload, headers=self.headers)
        self.assertEqual(saved.status_code, 200)
        draft_id = saved.json()["draft_id"]
        loaded = self.client.get(f"/api/notes/drafts/{draft_id}", headers=self.headers).json()
        self.assertEqual(loaded["form"], INPUT)
        self.assertEqual(loaded["draft_sections"], payload["draft_sections"])
        self.assertEqual(len(self.client.get("/api/notes/drafts", headers=self.headers).json()), 1)
        other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
        self.assertEqual(self.client.get(f"/api/notes/drafts/{draft_id}", headers=other).status_code, 404)
        self.assertEqual(self.client.get("/api/notes/drafts", headers=other).json(), [])

    def test_generate_edit_confirm_reload_preserves_full_text_and_original(self):
        generated = self.generate()
        note_id = generated["persistence_report"]["note_id"]
        url = f"/api/notes/records/{note_id}"
        draft = self.client.get(url, headers=self.headers).json()
        self.assertEqual(draft["confirmation_status"], "draft")
        self.assertEqual(draft["confirmed_json"], {})
        edited = "상담사가 수정한 합성 문장입니다. " * 50
        confirmed = {**draft["draft_json"], "session_content": {"text": edited},
                     "sections": {"session_content": edited},
                     "workspace_sections": [{"id": "session_content", "title": "상담 내용", "content": edited, "visible": True}]}
        response = self.client.post("/api/notes/confirm", headers=self.headers, json={
            "note_id": note_id, "confirmed_note": confirmed, "counselor_edited": True, "create_case_memory": False,
        })
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertEqual(response.json()["confirmation_status"], "confirmed")
        loaded = self.client.get(url, headers=self.headers).json()
        self.assertEqual(loaded["confirmed_json"], confirmed)
        self.assertEqual(loaded["draft_json"], draft["draft_json"])
        self.assertEqual(loaded["confirmation_status"], "confirmed")
        self.assertNotEqual(loaded["draft_json"]["session_content"]["text"], edited)
        other = {"Authorization": f"Bearer {OTHER_TOKEN}"}
        self.assertEqual(self.client.get(url, headers=other).status_code, 404)
        self.assertEqual(self.client.post("/api/notes/confirm", headers=other, json={
            "note_id": note_id, "confirmed_note": confirmed, "counselor_edited": True, "create_case_memory": False,
        }).status_code, 404)

    def test_temporary_draft_excludes_upload_caches_at_storage_boundary(self):
        raw = "SYNTHETIC-UNAPPLIED-UPLOAD-CACHE"
        payload = {
            "case_id": INPUT["case_id"], "session_number": 1, "form": {**INPUT, "attachments": [{"content": raw}]},
            "attachments": [{"id": "synthetic-material", "kind": "audio", "filename": "synthetic.wav",
                             "status": "transcribed", "appliedTargets": ["transcript_text"], "dirtySinceApply": True,
                             "extractedText": raw, "transcriptText": raw, "segments": [{"text": raw, "words": [{"text": raw}]}],
                             "nonverbalNotes": raw, "lastAppliedTranscriptText": raw, "lastAppliedNonverbalNotes": raw,
                             "warnings": [raw], "speakerRoleMap": {"speaker": {"content": raw}}}],
            "draft_sections": [{"id": "session_content", "title": "상담 내용", "content": "Counselor edit", "visible": True,
                                "evidence": [{"excerpt": raw}], "groundingItems": [{"source": {"text": raw}}]}],
            "final_document_sections": [{"id": "final", "title": "Final", "content": "Final edit", "contentKind": "paragraph",
                                         "groundingItems": [{"text": raw}]}],
            "result": {"case_id": INPUT["case_id"], "session_number": 1, "session_summary": "AI summary",
                       "workspace_note_id": "synthetic-note", "evidence_check": [{"source_excerpt": raw}],
                       "grounding": {"regions": [{"content": raw}]}, "full_response": {"sanitized_input": {"sources": {"transcript_text": raw}}}},
        }
        saved = self.client.post("/api/notes/drafts", json=payload, headers=self.headers)
        self.assertEqual(saved.status_code, 200, saved.text)
        stored = self.store.tables[settings.supabase_drafts_table][0]["data"]
        self.assertNotIn(raw, json.dumps(stored))
        self.assertEqual(stored["form"], INPUT)
        self.assertEqual(stored["draft_sections"][0]["content"], "Counselor edit")
        self.assertEqual(stored["final_document_sections"][0]["content"], "Final edit")
        self.assertTrue(stored["attachments"][0]["requiresReattachment"])
        self.assertTrue(stored["attachments"][0]["dirtySinceApply"])
        url = f'/api/notes/drafts/{saved.json()["draft_id"]}'
        loaded = self.client.get(url, headers=self.headers).json()
        self.assertEqual(loaded, stored)
        self.assertNotIn(raw, self.client.get("/api/notes/drafts", headers=self.headers).text)

    def test_temporary_projection_preserves_reports_and_filters_legacy_reads_without_deletion(self):
        fixture = Path(__file__).resolve().parent.parent / "frontend/scripts/fixtures/temporary-draft.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        saved = self.client.post("/api/notes/drafts", json=payload, headers=self.headers).json()
        row = self.store.tables[settings.supabase_drafts_table][0]
        clean = json_copy(row["data"])
        self.assertNotIn("SYNTHETIC-RAW-CACHE", json.dumps(clean))
        self.assertEqual(clean["form"]["transcript_text"], payload["form"]["transcript_text"])
        block = clean["supervision_report_draft"]["sections"][0]["contentBlocks"][0]
        self.assertEqual(block["text"], "Counselor report edit")
        self.assertEqual(block["rows"], [{"column": "Edited table cell"}])
        self.assertEqual(block["speakerTurns"][0]["text"], "Counselor-selected report excerpt")
        # Emulate an older stored draft. GET/list must not return caches or rewrite rows.
        row["data"] = {**payload, "draft_id": saved["draft_id"], "saved_at": saved["saved_at"]}
        legacy = json_copy(row["data"])
        url = f'/api/notes/drafts/{saved["draft_id"]}'
        self.assertEqual(self.client.get(url, headers=self.headers).json(), clean)
        self.assertNotIn("SYNTHETIC-RAW-CACHE", self.client.get("/api/notes/drafts", headers=self.headers).text)
        self.assertEqual(row["data"], legacy)

    def test_local_disk_uses_the_same_temporary_storage_boundary(self):
        fixture = Path(__file__).resolve().parent.parent / "frontend/scripts/fixtures/temporary-draft.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"TEMP_DRAFT_DIR": directory}), \
                patch.object(supabase_store, "configured_for", return_value=False):
            saved = self.client.post("/api/notes/drafts", json=payload, headers=self.headers).json()
            stored_files = list(Path(directory).rglob("*.json"))
            self.assertEqual(len(stored_files), 1)
            stored = json.loads(stored_files[0].read_text(encoding="utf-8"))
            self.assertNotIn("SYNTHETIC-RAW-CACHE", json.dumps(stored))
            self.assertEqual(stored["form"]["counselor_memo"], payload["form"]["counselor_memo"])
            url = f'/api/notes/drafts/{saved["draft_id"]}'
            self.assertEqual(self.client.get(url, headers=self.headers).json(), stored)

    def test_confirmed_string_object_sections_and_empty_values_survive_reconfirmation(self):
        for fields in ({"session_content": "Counselor string", "next_plan": ""},
                       {"session_content": {"text": "Counselor object"}, "next_plan": {"text": ""}},
                       {"sections": {"session_content": "Counselor sections", "next_plan": ""}}):
            with self.subTest(fields=fields):
                note_id = self.generate()["persistence_report"]["note_id"]
                url = f"/api/notes/records/{note_id}"
                original = self.client.get(url, headers=self.headers).json()["draft_json"]
                for _ in range(2):
                    response = self.client.post("/api/notes/confirm", headers=self.headers, json={
                        "note_id": note_id, "confirmed_note": fields, "counselor_edited": True, "create_case_memory": False,
                    })
                    self.assertEqual(response.status_code, 200)
                    loaded = self.client.get(url, headers=self.headers).json()
                    self.assertEqual(loaded["confirmed_json"], fields)
                    self.assertEqual(loaded["draft_json"], original)

    def test_missing_or_invalid_token_never_reaches_storage(self):
        for headers in ({}, {"Authorization": "Bearer invalid"}):
            for method, url, payload in [
                ("get", "/api/notes/records/synthetic", None), ("get", "/api/notes/drafts", None),
                ("post", "/api/notes/drafts", {"case_id": "SYNTHETIC", "session_number": 1}),
                ("post", "/api/notes/generate", INPUT),
                ("post", "/api/notes/confirm", {"note_id": "synthetic", "confirmed_note": {"text": "合成"}, "counselor_edited": True, "create_case_memory": False}),
            ]:
                response = self.client.request(method, url, json=payload, headers=headers)
                self.assertEqual(response.status_code, 401, url)
        self.assertEqual(self.store.calls, [])

    def test_detail_rejects_broken_session_case_chain(self):
        result = self.generate()
        note_id = result["persistence_report"]["note_id"]
        self.store.tables["sessions"][0]["case_id"] = "SYNTHETIC-OTHER-CASE"
        self.assertEqual(self.client.get(f"/api/notes/records/{note_id}", headers=self.headers).status_code, 409)

    def test_storage_failure_does_not_report_success(self):
        with patch.object(supabase_store, "_request", side_effect=RuntimeError("synthetic failure")):
            response = self.client.post("/api/notes/drafts", headers=self.headers,
                                        json={"case_id": "SYNTHETIC", "session_number": 1})
            self.assertEqual(response.status_code, 500)
        with patch.object(SupabaseStorage, "_request", side_effect=RuntimeError("synthetic failure")):
            response = self.client.post("/api/notes/generate", headers=self.headers, json=INPUT)
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()["persistence_report"]["stored"])
            response = self.client.get("/api/notes/records/synthetic", headers=self.headers)
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("synthetic failure", response.text)

    def test_serverless_entry_point_matches_detail(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from api.notes.record import app as wrapper
        result = self.generate()
        note_id = result["persistence_report"]["note_id"]
        wrapper_client = TestClient(wrapper)
        for path in (f"/api/notes/records/{note_id}", f"/api/notes/record?note_id={note_id}", f"/?note_id={note_id}"):
            response = wrapper_client.get(path, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["note_id"], note_id)
            self.assertEqual(wrapper_client.get(path).status_code, 401)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        import uvicorn
        from fastapi.middleware.cors import CORSMiddleware
        app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:4174"], allow_methods=["*"], allow_headers=["*"])

        @app.get("/auth/v1/settings")
        def synthetic_auth_settings():
            return {"external": {}}

        with offline_environment():
            uvicorn.run(app, host="127.0.0.1", port=8017, access_log=False)
    else:
        unittest.main()
