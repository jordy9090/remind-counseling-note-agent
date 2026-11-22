"""Client check-in routes (내담자 수시 기록); every account and record is synthetic.

The real routes, auth guard and service run against an in-memory PostgREST substitute that
mirrors the row policies and the two SECURITY DEFINER functions of
20261122000100_client_check_ins.sql. It does not execute the SQL itself.
Run: python -m unittest test_client_check_ins
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.schemas.client_check_in import CLIENT_CONSENT_VERSION
from app.services.supabase_storage import SupabaseStorage, SupabaseStorageError

ACCOUNTS = {"token-counselor-a": "counselor-a", "token-counselor-b": "counselor-b",
            "token-client-c": "client-c", "token-client-d": "client-d"}
ALLOWED_EMOTIONS = {"불안", "슬픔", "화남", "무기력", "외로움", "긴장", "피곤함", "괜찮음", "편안함", "기쁨"}


def headers(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer token-{name}"}


class PolicyStore:
    """Rows plus the access rules of the migration, evaluated per verified account."""

    def __init__(self):
        self.cases: list[dict] = []
        self.links: list[dict] = []
        self.check_ins: list[dict] = []
        self.app_metadata: dict[str, dict] = {}
        self.user_metadata: dict[str, dict] = {}
        self.now = datetime.now(UTC)

    @staticmethod
    def _filter(rows, query):
        out = []
        for row in rows:
            keep = True
            for key, value in query.items():
                if key in {"select", "order", "limit"}:
                    continue
                value = str(value)
                if value.startswith("eq."):
                    keep &= str(row.get(key)) == value[3:]
                elif value.startswith("neq."):
                    keep &= str(row.get(key)) != value[4:]
                elif value.startswith("in.("):
                    keep &= str(row.get(key)) in value[4:-1].split(",")
            if keep:
                out.append(row)
        if query.get("order"):
            column, direction = str(query["order"]).split(".")
            out.sort(key=lambda row: str(row.get(column) or ""), reverse=direction == "desc")
        if query.get("limit"):
            out = out[:int(query["limit"])]
        return json.loads(json.dumps(out))

    @staticmethod
    def _fail(code: str):
        raise SupabaseStorageError(f"synthetic {code}", error_code=code)

    def request(self, actor: str, method: str, path: str, query: dict | None, body):
        query = query or {}
        if path == "cases" and method == "GET":
            return self._filter([c for c in self.cases if c["user_id"] == actor], query)
        if path == "client_links":
            if method == "GET":
                visible = [l for l in self.links if l["user_id"] == actor or l["client_user_id"] == actor]
                return self._filter(visible, query)
            if method == "POST":
                created = []
                for value in body:
                    owns_case = any(c["id"] == value["case_id"] and c["user_id"] == actor for c in self.cases)
                    if value.get("user_id") != actor or value.get("status") != "invited" or value.get("client_user_id") or not owns_case:
                        self._fail("42501")
                    if any(l["case_id"] == value["case_id"] and l["status"] != "ended" for l in self.links):
                        self._fail("23505")
                    row = {"id": str(uuid4()), "client_user_id": None, "created_at": self.now.isoformat(),
                           "accepted_at": None, "ended_at": None, "consented_at": None, "consent_version": None,
                           "ended_by": None, **value}
                    self.links.append(row)
                    created.append(row)
                return json.loads(json.dumps(created))
            self._fail("42501")  # no update/delete grant
        if path == "client_check_ins":
            mine = lambda row: row["client_user_id"] == actor
            counselor_reads = lambda row: any(l["id"] == row["link_id"] and l["user_id"] == actor for l in self.links)
            if method == "GET":
                return self._filter([r for r in self.check_ins if mine(r) or counselor_reads(r)], query)
            if method == "POST":
                created = []
                for value in body:
                    link_ok = any(l["id"] == value["link_id"] and l["client_user_id"] == actor and l["status"] == "active"
                                  for l in self.links)
                    if value.get("client_user_id") != actor or not link_ok:
                        self._fail("42501")
                    if not 0 <= value["mood"] <= 10 or len(value["note"]) > 1000 or not set(value["emotions"]) <= ALLOWED_EMOTIONS:
                        self._fail("23514")
                    row = {"id": str(uuid4()), "created_at": datetime.now(UTC).isoformat(), **value}
                    self.check_ins.append(row)
                    created.append(row)
                return json.loads(json.dumps(created))
            if method == "DELETE":
                targets = [r for r in self._filter([r for r in self.check_ins if mine(r)], query)]
                ids = {r["id"] for r in targets}
                self.check_ins = [r for r in self.check_ins if r["id"] not in ids]
                return targets
            self._fail("42501")
        if path == "rpc/accept_client_invite":
            if any(c["user_id"] == actor for c in self.cases):
                self._fail("42501")
            if any(l["client_user_id"] == actor and l["status"] == "active" for l in self.links):
                self._fail("23505")
            link = next((l for l in self.links if l.get("invite_token_hash") == body["p_token_hash"]), None)
            if (not link or link["status"] != "invited" or datetime.fromisoformat(link["invite_expires_at"]) <= datetime.now(UTC)
                    or link["user_id"] == actor):
                self._fail("22023")
            link.update(status="active", client_user_id=actor, invite_token_hash=None,
                        consent_version=body["p_consent_version"], consented_at=self.now.isoformat(), accepted_at=self.now.isoformat())
            self.app_metadata.setdefault(actor, {})["remind_role"] = "client"
            return link["id"]
        if path == "rpc/end_client_link":
            link = next((l for l in self.links if l["id"] == body["p_link_id"] and l["status"] != "ended"
                         and (l["user_id"] == actor or l["client_user_id"] == actor)), None)
            if not link:
                self._fail("P0002")
            link.update(status="ended", ended_at=datetime.now(UTC).isoformat(), invite_token_hash=None,
                        ended_by="counselor" if link["user_id"] == actor else "client")
            return None
        raise AssertionError(f"unexpected {method} {path}")


class ClientCheckInTests(unittest.TestCase):
    def setUp(self):
        self.store = PolicyStore()
        self.store.cases = [{"id": "case-a", "user_id": "counselor-a", "case_alias": "합성 내담자"},
                            {"id": "case-b", "user_id": "counselor-b", "case_alias": "다른 합성 내담자"}]
        store = self.store

        def auth_response(request, **_):
            token = request.get_header("Authorization", "").removeprefix("Bearer ")
            if token not in ACCOUNTS:
                raise HTTPError(request.full_url, 401, "invalid", {}, None)
            user = ACCOUNTS[token]
            return io.BytesIO(json.dumps({"id": user, "app_metadata": store.app_metadata.get(user, {}),
                                          "user_metadata": store.user_metadata.get(user, {})}).encode())

        def storage_request(storage, method, path, *, query=None, body=None, prefer=None):
            return store.request(ACCOUNTS[storage.access_token], method, path, query, body)

        stack = ExitStack()
        stack.enter_context(patch.multiple(settings, enable_real_user_auth=True, supabase_url="http://synthetic.invalid",
                                           supabase_publishable_key="synthetic-public-key",
                                           supabase_service_key=None, supabase_service_role_key=None))
        stack.enter_context(patch("app.api.security.urlopen", side_effect=auth_response))
        stack.enter_context(patch.object(SupabaseStorage, "_request", storage_request))
        self.addCleanup(stack.close)
        self.client = TestClient(app, raise_server_exceptions=False)

    def invite(self, counselor="counselor-a", case_id="case-a") -> str:
        response = self.client.post(f"/api/cases/{case_id}/client-invites", headers=headers(counselor))
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["token"]

    def accept(self, token, client="client-c", consent=CLIENT_CONSENT_VERSION):
        return self.client.post("/api/client/invites/accept", headers=headers(client),
                                json={"token": token, "consent_version": consent})

    def test_invite_accept_record_and_read_with_separated_roles(self):
        token = self.invite()
        self.assertNotIn(token, json.dumps(self.store.links), "only the token hash is stored")
        accepted = self.accept(token)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["linked"], True)

        # The client account is now refused by every counselor route.
        for path in ("/api/cases", "/api/cases/case-a/check-ins", "/api/cases/case-a/dashboard"):
            self.assertEqual(self.client.get(path, headers=headers("client-c")).status_code, 403, path)

        created = self.client.post("/api/client/check-ins", headers=headers("client-c"),
                                   json={"mood": 3, "emotions": ["불안", "피곤함", "불안"], "note": "  회의 전에 숨이 막혔어요.  "})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["emotions"], ["불안", "피곤함"])
        self.assertEqual(created.json()["note"], "회의 전에 숨이 막혔어요.")

        counselor_view = self.client.get("/api/cases/case-a/check-ins", headers=headers("counselor-a"))
        self.assertEqual(counselor_view.status_code, 200)
        self.assertEqual([entry["mood"] for entry in counselor_view.json()], [3])
        link = self.client.get("/api/cases/case-a/client-link", headers=headers("counselor-a")).json()
        self.assertEqual(link["status"], "active")

        # Another counselor and another client see nothing of it.
        self.assertEqual(self.client.get("/api/cases/case-a/check-ins", headers=headers("counselor-b")).status_code, 404)
        self.assertEqual(self.client.get("/api/cases/case-a/client-link", headers=headers("counselor-b")).status_code, 404)
        self.accept(self.invite("counselor-b", "case-b"), client="client-d")
        self.assertEqual(self.client.get("/api/client/check-ins", headers=headers("client-d")).json(), [])
        self.assertEqual(self.client.get("/api/cases/case-b/check-ins", headers=headers("counselor-b")).json(), [])

        # The counselor cannot write or delete entries; the client deletes their own.
        entry_id = created.json()["id"]
        self.assertEqual(self.client.delete(f"/api/client/check-ins/{entry_id}", headers=headers("counselor-a")).status_code, 403)
        self.assertEqual(self.client.delete(f"/api/client/check-ins/{entry_id}", headers=headers("client-d")).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/client/check-ins/{entry_id}", headers=headers("client-c")).status_code, 204)
        self.assertEqual(self.client.get("/api/cases/case-a/check-ins", headers=headers("counselor-a")).json(), [])

    def test_invites_are_single_use_expiring_and_not_for_counselors(self):
        token = self.invite()
        self.assertEqual(self.accept(token, client="counselor-b").status_code, 409, "a counselor account cannot join")
        self.assertEqual(self.accept(token, consent="old-version").status_code, 409)
        self.assertEqual(self.accept(token).status_code, 200)
        self.assertEqual(self.accept(token, client="client-d").status_code, 410, "the invite was already used")

        expired = self.invite("counselor-b", "case-b")
        self.store.links[-1]["invite_expires_at"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        self.assertEqual(self.accept(expired, client="client-d").status_code, 410)
        self.assertEqual(self.accept("x" * 43, client="client-d").status_code, 410)
        self.assertEqual(self.client.post("/api/client/invites/accept", json={"token": token, "consent_version": "v"}).status_code, 401)

    def test_reinvite_revokes_unused_invite_and_active_link_blocks_new_invites(self):
        first = self.invite()
        second = self.invite()
        self.assertEqual(self.accept(first).status_code, 410, "the earlier invite was revoked")
        self.assertEqual(self.accept(second).status_code, 200)
        conflict = self.client.post("/api/cases/case-a/client-invites", headers=headers("counselor-a"))
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(self.client.post("/api/cases/case-b/client-invites", headers=headers("counselor-a")).status_code, 404)

    def test_ended_link_stops_new_entries_but_keeps_history(self):
        self.accept(self.invite())
        self.client.post("/api/client/check-ins", headers=headers("client-c"), json={"mood": 6})
        self.assertEqual(self.client.post("/api/client/link/end", headers=headers("client-c")).status_code, 204)
        self.assertEqual(self.client.post("/api/client/check-ins", headers=headers("client-c"), json={"mood": 5}).status_code, 409)
        self.assertEqual(len(self.client.get("/api/client/check-ins", headers=headers("client-c")).json()), 1)
        self.assertEqual(len(self.client.get("/api/cases/case-a/check-ins", headers=headers("counselor-a")).json()), 1)
        self.assertIsNone(self.client.get("/api/cases/case-a/client-link", headers=headers("counselor-a")).json())
        self.assertEqual(self.client.get("/api/client/me", headers=headers("client-c")).json()["linked"], False)
        # The counselor can invite again after the link ended.
        self.invite()

    def test_validation_and_role_boundaries(self):
        self.accept(self.invite())
        for body in ({"mood": 11}, {"mood": -1}, {"mood": 5, "emotions": ["행복"]}, {"mood": 5, "note": "가" * 1001}, {}):
            self.assertEqual(self.client.post("/api/client/check-ins", headers=headers("client-c"), json=body).status_code, 422, body)
        self.assertEqual(self.client.get("/api/client/check-ins").status_code, 401)
        self.assertEqual(self.client.get("/api/client/check-ins", headers=headers("counselor-a")).status_code, 403)
        self.assertEqual(self.client.delete("/api/client/check-ins/not-a-uuid", headers=headers("client-c")).status_code, 422)

    def test_user_metadata_never_grants_or_removes_the_client_role(self):
        self.store.user_metadata["counselor-a"] = {"remind_role": "client"}
        self.assertNotEqual(self.client.get("/api/cases/case-a/client-link", headers=headers("counselor-a")).status_code, 403)
        self.accept(self.invite())
        self.store.user_metadata["client-c"] = {"remind_role": "counselor"}
        self.assertEqual(self.client.get("/api/cases", headers=headers("client-c")).status_code, 403)


if __name__ == "__main__":
    unittest.main()
