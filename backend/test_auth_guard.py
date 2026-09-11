"""Tests for the protected-API auth guard (real-user Supabase JWT path).

Offline: Supabase's /auth/v1/user call is mocked.
  uv run python test_auth_guard.py
"""
from __future__ import annotations

import io
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import security
from app.main import app


def real_auth_settings(**overrides):
    base = dict(
        enable_real_user_auth=True,
        local_preview_bypass_enabled=False,
        allow_legacy_preview_token=False,
        remind_preview_api_token=None,
        remind_preview_actor="preview-actor",
        supabase_url="https://example.supabase.co",
        normalized_supabase_url="https://example.supabase.co",
        effective_supabase_auth_key="publishable-key",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@contextmanager
def supabase_user(payload: dict | None = None, *, status: int | None = None):
    """Mock urlopen: return a user payload, or raise an HTTPError with `status`."""

    class _Response:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=0):
        if status is not None:
            raise HTTPError(request.full_url, status, "error", hdrs=None, fp=io.BytesIO(b"{}"))
        return _Response(json.dumps(payload or {}).encode("utf-8"))

    with patch.object(security, "urlopen", fake_urlopen):
        yield


class SupabaseUserGuardTests(unittest.TestCase):
    def test_missing_bearer_token_is_rejected(self) -> None:
        with patch.object(security, "settings", real_auth_settings()):
            with self.assertRaises(HTTPException) as ctx:
                security.require_preview_access(None, None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_valid_user_returns_actor_with_token(self) -> None:
        with patch.object(security, "settings", real_auth_settings()), supabase_user(
            {"id": "user-a", "email": "a@example.com", "is_anonymous": False}
        ):
            actor = security.require_preview_access(None, "Bearer token-a")
        self.assertEqual(str(actor), "user-a")
        self.assertEqual(actor.access_token, "token-a")

    def test_anonymous_user_is_rejected(self) -> None:
        """익명 진입 제거: 원격에 익명 로그인이 켜져 있어도 보호 API는 거부한다."""
        with patch.object(security, "settings", real_auth_settings()), supabase_user(
            {"id": "anon-user", "is_anonymous": True}
        ):
            with self.assertRaises(HTTPException) as ctx:
                security.require_preview_access(None, "Bearer anon-token")
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("익명", ctx.exception.detail)

    def test_invalid_or_expired_token_is_rejected(self) -> None:
        with patch.object(security, "settings", real_auth_settings()), supabase_user(status=401):
            with self.assertRaises(HTTPException) as ctx:
                security.require_preview_access(None, "Bearer stale")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_two_users_resolve_to_distinct_actors(self) -> None:
        """Account A/B 격리의 전제: 토큰별로 서로 다른 user id가 actor가 된다."""
        with patch.object(security, "settings", real_auth_settings()):
            with supabase_user({"id": "user-a"}):
                actor_a = security.require_preview_access(None, "Bearer token-a")
            with supabase_user({"id": "user-b"}):
                actor_b = security.require_preview_access(None, "Bearer token-b")
        self.assertNotEqual(str(actor_a), str(actor_b))
        self.assertNotEqual(actor_a.access_token, actor_b.access_token)

    def test_real_auth_disabled_without_legacy_guard_is_503(self) -> None:
        settings = real_auth_settings(enable_real_user_auth=False)
        with patch.object(security, "settings", settings):
            with self.assertRaises(HTTPException) as ctx:
                security.require_preview_access(None, None)
        self.assertEqual(ctx.exception.status_code, 503)


class ProtectedRouteTests(unittest.TestCase):
    """End-to-end through FastAPI: protected routes reject requests without a user token."""

    def test_protected_route_without_token_is_401(self) -> None:
        with patch.object(security, "settings", real_auth_settings()):
            response = TestClient(app).get("/api/notes/drafts")
        self.assertEqual(response.status_code, 401)

    def test_protected_route_with_anonymous_token_is_401(self) -> None:
        with patch.object(security, "settings", real_auth_settings()), supabase_user(
            {"id": "anon", "is_anonymous": True}
        ):
            response = TestClient(app).get("/api/notes/drafts", headers={"Authorization": "Bearer anon"})
        self.assertEqual(response.status_code, 401)

    def test_health_stays_public(self) -> None:
        with patch.object(security, "settings", real_auth_settings()):
            response = TestClient(app).get("/api/health")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
