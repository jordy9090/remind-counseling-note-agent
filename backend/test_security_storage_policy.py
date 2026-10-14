"""Observe effective input-storage policy without data or credential disclosure."""
from __future__ import annotations

from contextlib import ExitStack
import importlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from app.api import security
from app.core.config import settings
from app.main import app
from app.schemas.note import SessionInput
from app.services.supabase_storage import _session_raw_input, persist_generated_note

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
wrapper = importlib.import_module("api.notes.record")


class StoragePolicyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(settings,
            enable_real_user_auth=True, supabase_url="https://synthetic.invalid",
            supabase_publishable_key="synthetic-public-key",
            supabase_service_key="SYNTHETIC-SECRET-SERVICE-KEY",
            openai_api_key="SYNTHETIC-SECRET-MODEL-KEY"))
        self.auth = self.stack.enter_context(patch.object(security, "urlopen", side_effect=lambda *a, **kw: io.BytesIO(json.dumps({"id":"synthetic-owner"}).encode())))
        self.headers = {"Authorization":"Bearer synthetic-valid-token"}
        self.hosts = [(app,"/api/notes/storage-policy"), (wrapper.app,"/api/notes/storage-policy"), (wrapper.app,"/api/notes/record?scope=storage-policy"), (wrapper.app,"/?scope=storage-policy")]

    def test_runtime_flags_match_new_generated_note_storage(self):
        session = SessionInput(case_id="synthetic",session_number=1,counselor_memo="Synthetic 010-1111-2222",transcript_text="Synthetic only",persist=True)
        for enabled in (False,True):
            for original in (False,True):
                for raw in (False,True):
                    with self.subTest(enabled=enabled,original=original,raw=raw), patch.multiple(settings,enable_persistence=enabled,save_original_input=original,save_raw_input=raw):
                        stored = _session_raw_input(session)
                        expected = "disabled" if not enabled else "omitted" if stored is None else "original" if json.loads(stored).get("masked") is False else "masked"
                        if not enabled:
                            with patch("app.services.supabase_storage._storage_for_actor",side_effect=AssertionError("Disabled persistence must not access storage")):
                                self.assertFalse(persist_generated_note(session,object(),actor="synthetic-owner").stored)
                        for host,path in self.hosts:
                            response=TestClient(host).get(path,headers=self.headers)
                            self.assertEqual(response.status_code,200)
                            data=response.json()
                            self.assertEqual(data,{"persistence_enabled":enabled,"save_original_input":original,"save_raw_input":raw,"generated_note_raw_input_mode":expected,"temporary_drafts_apply_input_policy":False,"existing_records_deleted":False})
                            self.assertEqual(response.headers["cache-control"],"private, no-store")
                            self.assertEqual(response.headers["vary"],"Authorization")
                            self.assertNotIn("SECRET",response.text)
                            self.assertNotIn("synthetic-owner",response.text)
                            self.assertNotIn("synthetic-valid-token",response.text)

    def test_missing_and_invalid_auth_are_rejected_on_both_hosts(self):
        for host,path in self.hosts:
            self.auth.reset_mock()
            response=TestClient(host).get(path)
            self.assertEqual(response.status_code,401)
            self.auth.assert_not_called()
            with patch.object(security,"urlopen",side_effect=HTTPError("https://synthetic.invalid",401,"synthetic",{},None)):
                response=TestClient(host).get(path,headers=self.headers)
                self.assertEqual(response.status_code,401)
                self.assertNotIn("save_original_input",response.text)

    def test_policy_does_not_read_records_or_invoke_generation(self):
        with patch("app.services.supabase_storage.SupabaseStorage._request",side_effect=AssertionError("Policy must not access records")), patch("app.api.routes.notes.run_note_pipeline",side_effect=AssertionError("Policy must not invoke a model")):
            for host,path in self.hosts:
                self.assertEqual(TestClient(host).get(path,headers=self.headers).status_code,200)

    def test_vercel_record_contract_remains_distinct(self):
        client=TestClient(wrapper.app)
        self.assertEqual(client.get("/api/notes/record",headers=self.headers).status_code,422)
        self.assertEqual(client.get("/api/notes/record?scope=unexpected",headers=self.headers).status_code,422)
        self.assertEqual(client.get("/api/notes/record?scope=storage-policy&note_id=synthetic",headers=self.headers).status_code,422)
        with patch.object(wrapper,"get_note_record",side_effect=security.HTTPException(status_code=404,detail="Synthetic missing record")) as get_record:
            self.assertEqual(client.get("/api/notes/record?note_id=synthetic",headers=self.headers).status_code,404)
            self.assertEqual(get_record.call_args.args[0],"synthetic")
            self.assertEqual(client.get("/api/notes/records/synthetic",headers=self.headers).status_code,404)
        routes=json.loads((ROOT/"vercel.json").read_text(encoding="utf-8"))["rewrites"]
        self.assertIn({"source":"/api/notes/storage-policy","destination":"/api/notes/record?scope=storage-policy"},routes)


if __name__=="__main__":
    unittest.main(verbosity=2)
