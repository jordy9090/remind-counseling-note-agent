"""Synthetic, offline authorization and transport regressions.

Run from backend: python -m unittest test_security_access_boundaries

Real FastAPI routes, Vercel aliases, auth checks and REST serialization run with
mocked urlopen only. The small transport models row visibility for route tests;
it is NOT PostgreSQL/PostgREST and cannot certify deployed RLS, foreign keys,
DELETE privileges, or storage buckets. Direct database policy tests remain an
integration gate. Export renders the caller's supplied body, not a stored ID.
No credentials, real records, remote calls, or paid inference are required.
"""
from __future__ import annotations

import importlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
import zipfile
from contextlib import ExitStack
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch
from uuid import uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.api.security import AuthenticatedActor, require_preview_access
from app.core.config import settings
from app.main import app
from app.schemas.evidence import TranscriptTurn
from app.schemas.note import TemporaryDraftSaveRequest
from app.services import draft_store, raw_evidence_retrieval, retrieval, supabase_store
from app.services.supabase_storage import SupabaseStorage, _storage_for_actor
from app.services.transcript_storage import TranscriptStorageError, get_transcript_turns, store_transcript_turns
from app.services.transcript_windows import index_transcript_windows


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

WRAPPER_MODULES = {
    name: importlib.import_module(module)
    for name, module in {
        "generate": "api.notes.generate", "confirm": "api.notes.confirm",
        "record": "api.notes.record", "draft": "api.notes.draft",
        "drafts": "api.notes.drafts", "recompose": "api.notes.recompose",
        "supervision": "api.notes.supervision-report", "cases": "api.cases.dashboard",
        "export": "api.documents.export", "capabilities": "api.documents.capabilities",
        "extract": "api.materials.documents.extract",
    }.items()
}
APPS = {"backend": app, **{name: module.app for name, module in WRAPPER_MODULES.items()}}
# Routes that intentionally work without login. Each one must be listed in
# docs/security/data-inventory-and-access-matrix.md and covered by its own guest test below.
PUBLIC_ROUTES = {("backend", "/api/notes/quick-summary"), ("generate", "/api/notes/quick-summary")}
QUICK_SUMMARY_TEXT = "Synthetic counseling note for the public quick summary boundary test."
USERS = {"a": "11111111-1111-4111-8111-111111111111", "b": "22222222-2222-4222-8222-222222222222"}
TOKENS = {"a": "synthetic-access-a", "b": "synthetic-access-b"}
PUBLIC_KEY = "synthetic-public-key"
SERVICE_KEY = "synthetic-service-key-must-not-be-used"
CASES = {key: f"SYNTHETIC-CASE-{key.upper()}" for key in USERS}
SESSIONS = {"a": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "b": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"}
NOTES = {"a": "aaaaaaaa-0000-4000-8000-000000000001", "b": "bbbbbbbb-0000-4000-8000-000000000002"}


def api_routes(application):
    pending = list(application.routes)
    while pending:
        route = pending.pop()
        if isinstance(route, APIRoute):
            yield route
            continue
        included_router = getattr(route, "original_router", None)
        if included_router is not None:
            pending.extend(included_router.routes)
PRIVATE_B = "SYNTHETIC-PRIVATE-B-CONTENT"
PUBLIC_A = "SYNTHETIC-A-SUBMITTED-CONTENT"
DRAFT_ID = "draft_shared_synthetic"


def copied(value):
    return json.loads(json.dumps(value))


def input_payload(case_id=CASES["a"], *, persist=False):
    return {"case_id": case_id, "session_number": 1, "session_date": "2026-10-13",
            "counselor_name": "Synthetic counselor", "counselor_memo": PUBLIC_A,
            "transcript_text": "", "persist": persist, "insight_lens": "none"}


def confirm_payload():
    return {"note_id": NOTES["b"], "confirmed_note": {"sections": {"session_content": PUBLIC_A}},
            "counselor_edited": True, "create_case_memory": False}


def export_payload():
    return {"format": "docx", "document_type": "session_note", "case_id": CASES["b"],
            "session_number": 1, "title": "Synthetic caller document",
            "sections": [{"id": "body", "title": "Synthetic body", "content": PUBLIC_A}]}


class OfflineTransport:
    """Minimal fixture transport; its owner filtering is an explicit assumption."""

    def __init__(self):
        self.calls = []
        self.tables = {}
        for key, user in USERS.items():
            text = PRIVATE_B if key == "b" else PUBLIC_A
            source = {"counselor_memo": text, "transcript_text": text}
            self.add("cases", {"id": CASES[key], "user_id": user, "counselor_id": user,
                               "case_alias": text, "status": "active"})
            self.add("sessions", {"id": SESSIONS[key], "case_id": CASES[key], "user_id": user,
                                  "session_number": 1, "session_date": "2026-10-13",
                                  "session_title": text, "transcript_status": "completed",
                                  "raw_input_text": json.dumps({"masked": False, **source}),
                                  "sanitized_input_text": json.dumps({"sources": source})})
            self.add("generated_notes", {"id": NOTES[key], "case_id": CASES[key], "user_id": user,
                                         "session_id": SESSIONS[key], "note_type": "session_note",
                                         "draft_json": {"session_content": {"text": text}},
                                         "confirmed_json": {"sections": {"session_content": text}},
                                         "confirmation_status": "confirmed", "confirmed_by": user})
            self.add("evidence_items", {"id": f"evidence-{key}", "case_id": CASES[key],
                                       "session_id": SESSIONS[key], "user_id": user,
                                       "source_type": "transcript", "source_ref": f"source-{key}",
                                       "source_text": text, "linked_field": "session_content"})
            self.add("transcript_turns", {"id": f"turn-{key}", "case_id": CASES[key],
                                         "session_id": SESSIONS[key], "user_id": user,
                                         "counselor_id": user, "turn_index": 0,
                                         "speaker_role": "client", "sanitized_text": text})
            self.add("transcript_windows", {"id": f"window-{key}", "user_id": user,
                                           "counselor_id": user, "case_id": CASES[key],
                                           "session_id": SESSIONS[key], "start_turn_index": 0,
                                           "end_turn_index": 0, "window_text": text,
                                           "source_ref": f"window:{key}", "content_hash": f"hash-{key}"})
            self.add("case_memory_chunks", {"id": f"memory-{key}", "case_id": CASES[key],
                                           "user_id": user, "counselor_id": user,
                                           "session_id": SESSIONS[key], "source_note_id": NOTES[key],
                                           "source_ref": f"memory:{key}", "chunk_text": text,
                                           "field_type": "session_content", "session_number": 1})
        record = {"draft_id": DRAFT_ID, "case_id": CASES["b"], "session_number": 1,
                  "saved_at": "2026-10-13T00:00:00Z", "form": {"counselor_memo": PRIVATE_B}}
        self.add("counseling_drafts", {"draft_id": supabase_store._scoped_draft_id(DRAFT_ID, user_id=USERS["b"]),
                                      "user_id": USERS["b"], "case_id": CASES["b"],
                                      "saved_at": record["saved_at"], "data": record})

    def add(self, table, row):
        self.tables.setdefault(table, []).append({"created_at": "2026-10-13T00:00:00Z", **row})

    def owner_bytes(self, user):
        return json.dumps({name: [row for row in rows if row.get("user_id") == user]
                           for name, rows in self.tables.items() if any(row.get("user_id") == user for row in rows)},
                          sort_keys=True, ensure_ascii=False).encode()

    @staticmethod
    def response(payload):
        return io.BytesIO(json.dumps(payload).encode())

    @staticmethod
    def denied(request, code=403):
        raise HTTPError(request.full_url, code, "Synthetic denied", {}, io.BytesIO(b'{"message":"Synthetic denied"}'))

    def urlopen(self, request, **_kwargs):
        parsed = urlsplit(request.full_url)
        assert parsed.netloc == "synthetic.invalid", "Unexpected outbound origin"
        headers = {name.lower(): value for name, value in request.header_items()}
        assert headers.get("apikey") == PUBLIC_KEY, "User operations must use the public key"
        token = headers.get("authorization", "").removeprefix("Bearer ")
        token_users = {TOKENS[key]: user for key, user in USERS.items()}
        if parsed.path == "/auth/v1/user":
            if token == "synthetic-anonymous":
                return self.response({"id": "synthetic-guest", "is_anonymous": True})
            if token not in token_users:
                self.denied(request, 401)
            return self.response({"id": token_users[token], "is_anonymous": False})
        assert token in token_users, "A verified user JWT must reach storage"
        user = token_users[token]
        table = parsed.path.removeprefix("/rest/v1/")
        query = {key: value[0] for key, value in parse_qs(parsed.query).items()}
        body = json.loads(request.data) if request.data else None
        method = request.get_method()
        self.calls.append({"method": method, "table": table, "query": query,
                           "body": copied(body), "headers": headers, "user": user})
        if table.startswith("rpc/"):
            return self.response(self.rpc(table, body, user))
        rows = self.tables.setdefault(table, [])

        def matches(row):
            if row.get("user_id") != user:
                return False
            for field, condition in query.items():
                if condition.startswith("eq.") and str(row.get(field)) != condition[3:]:
                    return False
                if condition.startswith("neq.") and str(row.get(field)) == condition[4:]:
                    return False
                if condition.startswith("in.(") and str(row.get(field)) not in condition[4:-1].split(","):
                    return False
            return True

        if method == "GET":
            result = [row for row in rows if matches(row)]
            if query.get("order"):
                for part in reversed(query["order"].split(",")):
                    field, direction = part.split(".")[:2]
                    result.sort(key=lambda row: str(row.get(field, "")), reverse=direction == "desc")
            offset = int(query.get("offset", 0))
            return self.response(result[offset:offset + int(query.get("limit", len(result)))])
        if method == "PATCH":
            result = []
            for row in rows:
                if matches(row):
                    row.update(copied(body))
                    result.append(row)
            return self.response(result)
        if method == "DELETE":
            removed = [row for row in rows if matches(row)]
            self.tables[table] = [row for row in rows if not matches(row)]
            return self.response(removed)
        assert method == "POST", "Unexpected fixture method"
        result = []
        for value in body if isinstance(body, list) else [body]:
            assert value.get("user_id") == user, "Owner must come from verified identity"
            conflict = query.get("on_conflict") or ("draft_id" if table == "counseling_drafts" else "id")
            existing = next((row for row in rows if all(field in value and row.get(field) == value[field]
                                                       for field in conflict.split(","))), None)
            if existing and existing.get("user_id") != user:
                self.denied(request)
            if existing:
                existing.update(copied(value))
                result.append(existing)
            else:
                row = {"id": str(uuid4()), "created_at": "2026-10-13T00:00:00Z", **copied(value)}
                rows.append(row)
                result.append(row)
        return self.response(result)

    def rpc(self, table, body, user):
        if table == "rpc/match_case_memory_chunks":
            assert body["filter_counselor_id"] == user
            return [{**row, "chunk_id": row["id"], "similarity_score": 1.0}
                    for row in self.tables["case_memory_chunks"]
                    if row["user_id"] == user and row["case_id"] == body["filter_case_id"]]
        if table == "rpc/match_transcript_windows":
            assert body["filter_user_id"] == user
            return [{**row, "window_id": row["id"], "session_number": 1, "similarity_score": 1.0}
                    for row in self.tables["transcript_windows"]
                    if row["user_id"] == user and row["case_id"] == body["filter_case_id"]]
        raise AssertionError("Unexpected RPC")


class AccessBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory(prefix="remind-synthetic-access-"))
        self.directory = Path(directory)
        self.stack.enter_context(patch.dict(os.environ, {"TEMP_DRAFT_DIR": str(self.directory / "drafts"),
                                                        "RECOMPOSE_CACHE_DIR": str(self.directory / "cache"),
                                                        "UPLOAD_TMP_DIR": str(self.directory)}))
        self.stack.enter_context(patch.multiple(settings, runtime_environment="test", enable_real_user_auth=True,
            allow_legacy_preview_token=False, remind_allow_local_bypass=False, enable_persistence=True,
            enable_rag=False, enable_case_memory=False, enable_dense_retrieval=False,
            enable_raw_region_grounding=False, use_stub=True, openai_api_key="synthetic-not-a-provider-key",
            supabase_url="https://synthetic.invalid", supabase_publishable_key=PUBLIC_KEY,
            supabase_anon_key=None, supabase_service_key=SERVICE_KEY, supabase_service_role_key=SERVICE_KEY,
            supabase_drafts_table="counseling_drafts", save_original_input=True, save_raw_input=False))
        self.transport = OfflineTransport()
        for target in ("app.api.security.urlopen", "app.services.supabase_storage.urlopen", "app.services.supabase_store.urlopen"):
            self.stack.enter_context(patch(target, side_effect=self.transport.urlopen))
        self.clients = {name: self.stack.enter_context(TestClient(application, raise_server_exceptions=False))
                        for name, application in APPS.items()}
        # Windows event loops create a local socketpair during client startup.
        # Block socket connections only after those in-process portals exist.
        self.stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")))
        self.stack.enter_context(patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden")))
        self.actor = AuthenticatedActor(USERS["a"], TOKENS["a"])
        self.before_b = self.transport.owner_bytes(USERS["b"])

    def request(self, name, method, path, *, user="a", **kwargs):
        return self.clients[name].request(method, path, headers={"Authorization": f"Bearer {TOKENS[user]}"}, **kwargs)

    def assert_b_unchanged(self):
        self.assertEqual(self.transport.owner_bytes(USERS["b"]), self.before_b)

    def assert_private(self, response):
        self.assertNotIn(PRIVATE_B, response.text)
        self.assert_b_unchanged()

    def test_note_record_all_aliases_deny_known_foreign_note(self):
        for name, path in [("backend", f'/api/notes/records/{NOTES["b"]}'),
                           ("record", f'/api/notes/records/{NOTES["b"]}'),
                           ("record", f'/api/notes/record?note_id={NOTES["b"]}'),
                           ("record", f'/?note_id={NOTES["b"]}')]:
            with self.subTest(name=name, path=path):
                owner = self.request(name, "GET", path, user="b")
                self.assertEqual(owner.status_code, 200)
                self.assertIn(PRIVATE_B, owner.text)
                denied = self.request(name, "GET", path)
                self.assertEqual(denied.status_code, 404)
                self.assert_private(denied)
        for call in self.transport.calls:
            if call["method"] == "GET" and call["table"] in {"generated_notes", "sessions", "cases"}:
                self.assertEqual(call["query"]["user_id"], f'eq.{call["user"]}')

    def test_confirmation_all_aliases_cannot_mutate_known_foreign_note(self):
        for name, path in [("backend", "/api/notes/confirm"), ("confirm", "/api/notes/confirm"), ("confirm", "/")]:
            with self.subTest(name=name, path=path):
                response = self.request(name, "POST", path, json=confirm_payload())
                self.assertEqual(response.status_code, 404)
                self.assert_private(response)
        self.assertFalse(any(call["method"] != "GET" for call in self.transport.calls))

    def test_case_dashboard_aliases_deny_foreign_case(self):
        paths = [("backend", f'/api/cases/{CASES["b"]}/dashboard'),
                 ("cases", f'/api/cases/{CASES["b"]}/dashboard')]
        paths += [("cases", f'{path}?case_id={CASES["b"]}') for path in ("/", "/api/cases", "/api/cases/dashboard")]
        for name, path in paths:
            with self.subTest(name=name, path=path):
                self.assertEqual(self.request(name, "GET", path, user="b").status_code, 200)
                response = self.request(name, "GET", path)
                self.assertEqual(response.status_code, 404)
                self.assert_private(response)

    def test_case_profile_and_schedule_aliases_cannot_mutate_foreign_case(self):
        for scope, payload in (("profile", {"case_alias": PUBLIC_A}), ("schedule", {"total_scheduled_session_count": 9})):
            paths = [("backend", f'/api/cases/{CASES["b"]}/{scope}'), ("cases", f'/api/cases/{CASES["b"]}/{scope}')]
            paths += [("cases", f'{path}?case_id={CASES["b"]}&scope={scope}') for path in ("/", "/api/cases/dashboard")]
            for name, path in paths:
                with self.subTest(name=name, path=path):
                    response = self.request(name, "PATCH", path, json=payload)
                    self.assertEqual(response.status_code, 404)
                    self.assert_private(response)
        self.assertFalse(any(call["method"] == "PATCH" for call in self.transport.calls))

    def test_case_lists_and_draft_searches_exclude_foreign_content(self):
        paths = [("backend", "/api/cases"), ("backend", f'/api/notes/drafts?case_id={CASES["b"]}')]
        paths += [("cases", path) for path in ("/", "/api/cases", "/api/cases/dashboard?scope=list")]
        paths += [("drafts", f'{path}?case_id={CASES["b"]}') for path in ("/", "/api/notes/drafts")]
        for name, path in paths:
            with self.subTest(name=name, path=path):
                response = self.request(name, "GET", path)
                self.assertEqual(response.status_code, 200)
                self.assert_private(response)
                self.assertNotIn(CASES["b"], response.text)

    def test_case_create_cannot_claim_existing_foreign_id(self):
        for name, path in [("backend", "/api/cases"), ("cases", "/"), ("cases", "/api/cases"), ("cases", "/api/cases/dashboard")]:
            with self.subTest(name=name, path=path):
                response = self.request(name, "POST", path, json={"case_id": CASES["b"], "case_alias": PUBLIC_A})
                self.assertGreaterEqual(response.status_code, 400)
                self.assert_private(response)

    def test_draft_detail_aliases_deny_guessed_id_and_owner_can_read(self):
        paths = [("backend", f"/api/notes/drafts/{DRAFT_ID}"), ("drafts", f"/{DRAFT_ID}"),
                 ("drafts", f"/api/notes/drafts/{DRAFT_ID}"), ("draft", f"/api/notes/drafts/{DRAFT_ID}"),
                 ("draft", f"/api/notes/draft?draft_id={DRAFT_ID}"), ("draft", f"/?draft_id={DRAFT_ID}")]
        for name, path in paths:
            with self.subTest(name=name, path=path):
                self.assertIn(PRIVATE_B, self.request(name, "GET", path, user="b").text)
                response = self.request(name, "GET", path)
                self.assertEqual(response.status_code, 404)
                self.assert_private(response)

    def test_same_draft_id_is_namespaced_to_verified_actor_on_every_save_alias(self):
        for name, path in [("backend", "/api/notes/drafts"), ("drafts", "/"), ("drafts", "/api/notes/drafts")]:
            with self.subTest(name=name, path=path):
                response = self.request(name, "POST", path, json={"draft_id": DRAFT_ID, "case_id": CASES["a"],
                    "session_number": 1, "form": {"counselor_memo": PUBLIC_A, "user_id": USERS["b"]}, "user_id": USERS["b"]})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["draft_id"], DRAFT_ID)
                self.assert_private(response)
        a = self.request("backend", "GET", f"/api/notes/drafts/{DRAFT_ID}")
        self.assertIn(PUBLIC_A, a.text)
        self.assertNotIn(PRIVATE_B, a.text)
        keys = {row["draft_id"] for row in self.transport.tables["counseling_drafts"]}
        self.assertEqual(len(keys), 2)
        for call in self.transport.calls:
            if call["method"] == "POST":
                self.assertEqual(call["body"]["user_id"], USERS["a"])
                self.assertEqual(call["body"]["draft_id"], supabase_store._scoped_draft_id(DRAFT_ID, user_id=USERS["a"]))

    def test_generation_cannot_persist_over_foreign_case_or_retrieve_its_content(self):
        with patch.object(settings, "enable_rag", True):
            for name, path in [("backend", "/api/notes/generate"), ("generate", "/"), ("generate", "/api/notes/generate")]:
                with self.subTest(name=name, path=path):
                    response = self.request(name, "POST", path, json=input_payload(CASES["b"], persist=True))
                    self.assertEqual(response.status_code, 200, response.text[:200])
                    self.assertFalse(response.json()["persistence_report"]["stored"])
                    self.assertEqual(response.json()["retrieved_case_context"], [])
                    self.assert_private(response)

    def test_recompose_aliases_do_not_load_foreign_content(self):
        for name, path in [("backend", "/api/notes/recompose"), ("recompose", "/"), ("recompose", "/api/notes/recompose")]:
            with self.subTest(name=name, path=path):
                response = self.request(name, "POST", path, json={"session_input": input_payload(CASES["b"]), "visible_section_ids": []})
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assert_private(response)

    def test_recomposition_cache_cannot_reuse_another_actors_retrieved_context(self):
        payload = {"session_input": input_payload(CASES["b"]), "visible_section_ids": []}
        with patch.object(settings, "enable_rag", True):
            owner = self.request("backend", "POST", "/api/notes/recompose", user="b", json=payload)
            self.assertEqual(owner.status_code, 200)
            self.assertIn(PRIVATE_B, owner.text)
            other = self.request("backend", "POST", "/api/notes/recompose", json=payload)
            self.assertEqual(other.status_code, 200)
            self.assert_private(other)
            self.assertNotEqual(owner.json()["cache_key"], other.json()["cache_key"])
            self.assertFalse(other.json()["cache_hit"])
            repeated = self.request("backend", "POST", "/api/notes/recompose", json=payload)
            self.assertTrue(repeated.json()["cache_hit"])
            self.assert_private(repeated)

    def test_owned_note_cannot_follow_a_foreign_session_or_case_reference(self):
        note = next(row for row in self.transport.tables["generated_notes"] if row["user_id"] == USERS["a"])
        session = next(row for row in self.transport.tables["sessions"] if row["user_id"] == USERS["a"])
        for mode in ("foreign_session", "foreign_case"):
            with self.subTest(mode=mode):
                note["session_id"] = SESSIONS["b"] if mode == "foreign_session" else SESSIONS["a"]
                # For the case attempt, make the caller's note/session agree so
                # the final owned-case lookup, rather than mismatch checking, rejects it.
                note["case_id"] = session["case_id"] = CASES["b"] if mode == "foreign_case" else CASES["a"]
                response = self.request("backend", "GET", f'/api/notes/records/{NOTES["a"]}')
                self.assertEqual(response.status_code, 409)
                self.assert_private(response)

    def test_supervision_aliases_do_not_load_foreign_content(self):
        for name, path in [("backend", "/api/notes/supervision-report"), ("supervision", "/"), ("supervision", "/api/notes/supervision-report")]:
            with self.subTest(name=name, path=path):
                response = self.request(name, "POST", path, json={"session_input": input_payload(CASES["b"]), "persist": True})
                self.assertEqual(response.status_code, 200, response.text[:200])
                self.assert_private(response)

    def test_export_contract_renders_caller_body_without_reading_foreign_records(self):
        for name, path in [("backend", "/api/documents/export"), ("export", "/"), ("export", "/api/documents/export")]:
            with self.subTest(name=name, path=path):
                self.transport.calls.clear()
                response = self.request(name, "POST", path, json=export_payload())
                self.assertEqual(response.status_code, 200)
                with zipfile.ZipFile(io.BytesIO(response.content)) as document:
                    xml = document.read("word/document.xml").decode()
                self.assertIn(PUBLIC_A, xml)
                self.assertNotIn(PRIVATE_B, xml)
                self.assertFalse(any(call["method"] == "GET" for call in self.transport.calls))
                self.assert_b_unchanged()

    def test_every_protected_route_and_wrapper_alias_rejects_guests_before_services(self):
        guarded = []
        public = set()
        for name, application in APPS.items():
            for route in api_routes(application):
                if name == "backend" and route.path in {"/", "/health", "/api/health"}:
                    continue
                if (name, route.path) in PUBLIC_ROUTES:
                    public.add((name, route.path))
                    continue
                self.assertTrue(any(dep.call is require_preview_access for dep in route.dependant.dependencies),
                                f"Missing authentication dependency: {name} {route.path}")
                path = route.path.replace("{note_id}", NOTES["b"]).replace("{case_id}", CASES["b"]).replace("{draft_id}", DRAFT_ID)
                for method in route.methods:
                    guarded.append((name, method, path))
        # A stale allowlist entry fails too, so the list cannot silently grow.
        self.assertEqual(public, PUBLIC_ROUTES)
        self.assertGreaterEqual(len(guarded), 50)
        with ExitStack() as blockers:
            spies = [blockers.enter_context(patch(target, side_effect=AssertionError("Protected service reached before authentication")))
                     for target in ("app.api.routes.notes.run_note_pipeline", "app.services.recompose_cache.run_note_pipeline",
                                    "app.api.routes.notes.run_supervision_report_pipeline",
                                    "app.services.document_export.DocumentExportService.export", "app.services.document_export.DocumentExportService.capabilities",
                                    "app.api.routes.materials.persist_upload_to_temp", "api.materials.documents.extract.persist_upload_to_temp",
                                    "app.api.routes.audio.persist_upload_to_temp", "app.api.routes.audio.get_transcription_service")]
            spies.append(blockers.enter_context(patch.object(WRAPPER_MODULES["supervision"], "run_supervision_report_pipeline",
                                                             side_effect=AssertionError("Protected service reached before authentication"))))
            for name, method, path in guarded:
                for headers in ({}, {"Authorization": "Bearer synthetic-invalid"}, {"Authorization": "Bearer synthetic-anonymous"}):
                    with self.subTest(name=name, method=method, path=path, auth=headers):
                        response = self.clients[name].request(method, path, headers=headers, json={})
                        self.assertEqual(response.status_code, 401)
            for spy in spies:
                spy.assert_not_called()
        self.assertEqual(self.transport.calls, [])
        self.assert_b_unchanged()

    def test_public_quick_summary_serves_guests_without_reaching_storage_or_other_users(self):
        from app.services.quick_summary import rate_limiter

        with ExitStack() as blockers:
            spies = [blockers.enter_context(patch(target, side_effect=AssertionError("Protected service reached by a guest")))
                     for target in ("app.api.routes.notes.run_note_pipeline", "app.api.routes.notes.save_temporary_draft",
                                    "app.api.routes.notes.persist_generated_note")]
            for name, path in sorted(PUBLIC_ROUTES):
                rate_limiter.reset()
                with self.subTest(name=name, path=path):
                    response = self.clients[name].post(path, json={"text": QUICK_SUMMARY_TEXT})
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertLessEqual({"main_content", "client_response", "counselor_intervention", "next_plan"},
                                         set(response.json()))
                    self.assert_private(response)
            for spy in spies:
                spy.assert_not_called()
        rate_limiter.reset()
        # No Supabase request at all: nothing is read, stored, or verified for a guest.
        self.assertEqual(self.transport.calls, [])
        self.assert_b_unchanged()

    def test_session_input_deletion_is_owner_scoped_and_keeps_the_summary(self):
        paths = lambda note: (("backend", f"/api/notes/records/{note}/input-deletion"),
                              ("record", f"/api/notes/record?note_id={note}&scope=input-deletion"),
                              ("record", f"/api/notes/records/{note}/input-deletion"))
        for name, path in paths(NOTES["b"]):
            with self.subTest(name=name, path=path):
                response = self.request(name, "POST", path)
                self.assertEqual(response.status_code, 404)
                self.assert_private(response)
        self.assert_b_unchanged()
        self.assertFalse(any(call["method"] in {"PATCH", "DELETE"} for call in self.transport.calls))

        notes_before = copied(self.transport.tables["generated_notes"])
        evidence_before = copied(self.transport.tables["evidence_items"])
        response = self.request("record", "POST", f'/api/notes/records/{NOTES["a"]}/input-deletion')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["session_id"], SESSIONS["a"])
        session = next(row for row in self.transport.tables["sessions"] if row["id"] == SESSIONS["a"])
        self.assertIsNone(session["raw_input_text"])
        self.assertIsNone(session["sanitized_input_text"])
        for table in ("transcript_turns", "transcript_windows"):
            self.assertFalse([row for row in self.transport.tables[table] if row["user_id"] == USERS["a"]])
        # The summary and its evidence stay; only the input is removed.
        self.assertEqual(self.transport.tables["generated_notes"], notes_before)
        self.assertEqual(self.transport.tables["evidence_items"], evidence_before)
        self.assertIsNone(self.request("backend", "GET", f'/api/notes/records/{NOTES["a"]}').json()["session_input"])
        self.assert_b_unchanged()

    def test_delete_methods_are_unsupported_not_a_database_deletion_test(self):
        paths = [("backend", "/api/cases"), ("backend", f'/api/cases/{CASES["b"]}/dashboard'),
                 ("backend", f'/api/notes/records/{NOTES["b"]}'), ("backend", f"/api/notes/drafts/{DRAFT_ID}"),
                 ("record", f'/api/notes/record?note_id={NOTES["b"]}'),
                 ("draft", f"/api/notes/draft?draft_id={DRAFT_ID}"), ("cases", f'/api/cases/dashboard?case_id={CASES["b"]}')]
        for name, path in paths:
            with self.subTest(name=name, path=path):
                self.assertEqual(self.request(name, "DELETE", path).status_code, 405)
        self.assertEqual(self.transport.calls, [])
        self.assert_b_unchanged()

    def test_real_rest_clients_forward_jwt_and_public_key_even_with_service_key_configured(self):
        client = _storage_for_actor(self.actor)
        self.assertIsInstance(client, SupabaseStorage)
        client.select("cases", {"user_id": f'eq.{USERS["a"]}'})
        supabase_store.list_draft_rows(actor=self.actor)
        for call in self.transport.calls:
            self.assertEqual(call["headers"]["authorization"], f'Bearer {TOKENS["a"]}')
            self.assertEqual(call["headers"]["apikey"], PUBLIC_KEY)
            self.assertNotIn(SERVICE_KEY, json.dumps(call))

    def test_retrieval_filters_known_foreign_case_and_all_owned_child_queries(self):
        client = _storage_for_actor(self.actor)
        with patch.object(settings, "enable_rag", True):
            self.assertEqual(retrieval.retrieve_case_context(CASES["b"], user_id=USERS["a"], storage_client=client), [])
            owned = retrieval.retrieve_case_context(CASES["a"], user_id=USERS["a"], storage_client=client)
        self.assertEqual(len(owned), 1)
        self.assertIn(PUBLIC_A, owned[0].summary)
        self.assertNotIn(PRIVATE_B, str(owned))
        for call in self.transport.calls:
            self.assertEqual(call["query"]["user_id"], f'eq.{USERS["a"]}')
            if call["table"] in {"generated_notes", "evidence_items"}:
                self.assertEqual(call["query"]["session_id"], f'in.({SESSIONS["a"]})')
        self.assert_b_unchanged()

    def test_transcript_known_foreign_session_read_and_mutation_are_scoped(self):
        client = _storage_for_actor(self.actor)
        scope = {"user_id": USERS["a"], "case_id": CASES["b"], "session_id": SESSIONS["b"], "storage_client": client}
        self.assertEqual(get_transcript_turns(**scope), [])
        with self.assertRaises(TranscriptStorageError):
            store_transcript_turns(**scope, counselor_id=USERS["a"],
                                   turns=[TranscriptTurn(turn_index=0, speaker_role="client", sanitized_text=PUBLIC_A)])
        self.assertEqual(index_transcript_windows(**scope, counselor_id=USERS["a"]), ([], 0))
        for call in self.transport.calls:
            self.assertEqual(call["method"], "GET")
            self.assertEqual(call["query"]["user_id"], f'eq.{USERS["a"]}')
            self.assertEqual(call["query"]["case_id"], f'eq.{CASES["b"]}')
            self.assertEqual(call["query"].get("session_id", call["query"].get("id")), f'eq.{SESSIONS["b"]}')
        self.assert_b_unchanged()

    def test_dense_rpcs_serialize_authenticated_scope_not_foreign_owner(self):
        client = _storage_for_actor(self.actor)
        with patch.multiple(settings, enable_rag=True, enable_dense_retrieval=True), \
                patch.object(retrieval, "embed_query", return_value=[0.0, 1.0]), \
                patch.object(raw_evidence_retrieval, "embed_query", return_value=[0.0, 1.0]):
            self.assertEqual(retrieval.retrieve_case_memory_chunks(query_text=PUBLIC_A, counselor_id=USERS["a"],
                             case_id=CASES["b"], storage_client=client), [])
            self.assertEqual(raw_evidence_retrieval.retrieve_transcript_window_candidates(query_text=PUBLIC_A,
                             user_id=USERS["a"], case_id=CASES["b"], storage_client=client), [])
        rpc_calls = [call for call in self.transport.calls if call["table"].startswith("rpc/")]
        self.assertEqual(len(rpc_calls), 2)
        for call in rpc_calls:
            self.assertEqual(call["body"].get("filter_user_id", call["body"].get("filter_counselor_id")), USERS["a"])
            self.assertEqual(call["body"]["filter_case_id"], CASES["b"])
        self.assert_b_unchanged()

    def test_local_disk_known_draft_id_stays_in_actor_directory(self):
        with patch.object(supabase_store, "configured_for", return_value=False):
            b_request = TemporaryDraftSaveRequest(draft_id=DRAFT_ID, case_id=CASES["b"], session_number=1, form={"counselor_memo": PRIVATE_B})
            draft_store.save_temporary_draft(b_request, actor=USERS["b"])
            b_path = self.directory / "drafts" / USERS["b"] / f"{DRAFT_ID}.json"
            before = b_path.read_bytes()
            self.assertIsNone(draft_store.get_temporary_draft(DRAFT_ID, actor=USERS["a"]))
            self.assertEqual(draft_store.list_temporary_drafts(actor=USERS["a"], case_id=CASES["b"]), [])
            draft_store.save_temporary_draft(b_request.model_copy(update={"case_id": CASES["a"], "form": {"counselor_memo": PUBLIC_A}}), actor=USERS["a"])
            self.assertEqual(b_path.read_bytes(), before)
            self.assertNotIn(PRIVATE_B, draft_store.get_temporary_draft(DRAFT_ID, actor=USERS["a"]).model_dump_json())
            self.assertEqual(len(list((self.directory / "drafts").rglob("*.json"))), 2)

    def test_local_disk_rejects_guessed_paths_and_normalizes_invalid_save_ids(self):
        with patch.object(supabase_store, "configured_for", return_value=False):
            draft_store.save_temporary_draft(TemporaryDraftSaveRequest(draft_id=DRAFT_ID, case_id=CASES["b"], session_number=1,
                                            form={"counselor_memo": PRIVATE_B}), actor=USERS["b"])
            b_path = self.directory / "drafts" / USERS["b"] / f"{DRAFT_ID}.json"
            before = b_path.read_bytes()
            for guessed in (f"../{USERS['b']}/{DRAFT_ID}", f"..\\{USERS['b']}\\{DRAFT_ID}", str(b_path), "%2e%2e%2fprivate", "x" * 81):
                with self.subTest(guessed=guessed):
                    self.assertIsNone(draft_store.get_temporary_draft(guessed, actor=USERS["a"]))
                    saved = draft_store.save_temporary_draft(TemporaryDraftSaveRequest(draft_id=guessed, case_id=CASES["a"], session_number=1), actor=USERS["a"])
                    self.assertRegex(saved.draft_id, r"^draft_[0-9a-f]{32}$")
                    self.assertTrue((self.directory / "drafts" / USERS["a"] / f"{saved.draft_id}.json").is_file())
                    self.assertEqual(b_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
