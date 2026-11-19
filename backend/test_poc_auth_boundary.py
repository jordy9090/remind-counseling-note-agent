"""Synthetic fail-closed PoC identity checks; run only with the offline harness."""
import io
import json
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

if os.environ.get("REMIND_POC_OFFLINE") != "1":
    raise unittest.SkipTest("Use backend/tests/run_poc_review.py")

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.api import security
from app.core.config import settings, validate_runtime_security
from app.main import app
from api.notes.drafts import app as drafts_app


class PoCAuthBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(settings, poc_mode=True,
            runtime_environment="test", enable_real_user_auth=False, remind_allow_local_bypass=True,
            allow_legacy_preview_token=True, remind_preview_api_token="synthetic-preview",
            supabase_url="https://synthetic.invalid", supabase_publishable_key="synthetic-public",
            supabase_anon_key=None, supabase_service_key="synthetic-service",
            supabase_service_role_key=None))

    def test_local_and_legacy_identity_never_reach_draft_services_in_poc(self):
        for bypass in (True, False):
            for application, path in ((app, "/api/notes/drafts"), (drafts_app, "/api/notes/drafts")):
                with self.subTest(bypass=bypass, host=application.title), patch.object(settings, "remind_allow_local_bypass", bypass), \
                        patch("app.api.routes.notes.list_temporary_drafts", side_effect=AssertionError("Unexpected shared identity")) as backend, \
                        patch("api.notes.drafts.list_temporary_drafts", side_effect=AssertionError("Unexpected shared identity")) as wrapper:
                    response = TestClient(application, raise_server_exceptions=False).get(path,
                        headers={"X-Remind-Preview-Token": "synthetic-preview"})
                    self.assertEqual(401, response.status_code)
                    backend.assert_not_called()
                    wrapper.assert_not_called()

    def test_verified_bearer_remains_distinct_even_if_legacy_flags_are_set(self):
        actors = []
        for owner in ("synthetic-A", "synthetic-B"):
            with patch.object(security, "urlopen", return_value=io.BytesIO(json.dumps({"id": owner}).encode())) as auth:
                actor = security.require_preview_access("synthetic-preview", f"Bearer {owner}-jwt")
                self.assertIsInstance(actor, security.AuthenticatedActor)
                self.assertEqual(owner, str(actor))
                self.assertEqual(f"{owner}-jwt", actor.access_token)
                self.assertEqual("synthetic-public", auth.call_args.args[0].headers["Apikey"])
                actors.append(actor)
        self.assertNotEqual(*actors)

    def test_poc_auth_has_no_service_key_fallback(self):
        with patch.object(settings, "supabase_publishable_key", None), patch.object(security, "urlopen",
                return_value=io.BytesIO(b'{"id":"synthetic-owner"}')) as send:
            with self.assertRaises(HTTPException) as caught:
                security._require_supabase_user("Bearer synthetic-jwt")
            self.assertEqual(503, caught.exception.status_code)
            send.assert_not_called()

    def test_startup_rejects_poc_shared_identity_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "PoC"):
            validate_runtime_security()

    def test_startup_accepts_real_identity_and_rejects_missing_public_config(self):
        with patch.object(settings, "enable_real_user_auth", True):
            validate_runtime_security()
            for name, value in (("supabase_url", None), ("supabase_publishable_key", None)):
                with self.subTest(field=name), patch.object(settings, name, value), self.assertRaisesRegex(RuntimeError, "PoC"):
                    validate_runtime_security()

    def test_non_poc_synthetic_preview_behavior_is_explicitly_preserved(self):
        with patch.object(settings, "poc_mode", False), patch.object(security, "urlopen") as auth:
            self.assertEqual(settings.remind_preview_actor, security.require_preview_access(None, None))
            with patch.object(settings, "remind_allow_local_bypass", False):
                self.assertEqual(settings.remind_preview_actor, security.require_preview_access("synthetic-preview", None))
            auth.assert_not_called()
