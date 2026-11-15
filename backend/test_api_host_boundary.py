"""Verify the standalone API's browser, authentication, and review boundaries."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.qwen_deidentification import DetectionUnavailable


class ApiHostBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for key, value in {
            "enable_real_user_auth": True, "enable_persistence": False,
            "enable_case_memory": False, "require_deid_review": True,
            "deid_review_signing_key": "synthetic-review-key-" * 4,
        }.items():
            self.stack.enter_context(patch.object(settings, key, value))
        self.client = self.stack.enter_context(TestClient(app))

    def test_browser_preflight_accepts_review_headers_only_for_known_origin(self):
        for origin, expected in [("https://remind.ai.kr", 200), ("https://untrusted.invalid", 400)]:
            response = self.client.options("/api/notes/generate", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type,x-review-receipt",
            })
            self.assertEqual(expected, response.status_code)
            self.assertEqual("no-store", response.headers["cache-control"])
            self.assertEqual(origin if expected == 200 else None,
                             response.headers.get("access-control-allow-origin"))

    def test_protected_routes_preserve_authentication_without_vercel(self):
        for method, path in [("GET", "/api/notes/drafts"), ("GET", "/api/cases"),
                             ("GET", "/api/audio/capabilities"), ("POST", "/api/notes/recompose")]:
            response = self.client.request(method, path, headers={"Origin": "https://remind.ai.kr"})
            self.assertEqual(401, response.status_code, path)
            self.assertEqual("no-store", response.headers["cache-control"])
            self.assertEqual("https://remind.ai.kr", response.headers["access-control-allow-origin"])
            self.assertIn("Content-Disposition", response.headers["access-control-expose-headers"])

    def test_unreviewed_or_failed_detection_cannot_reach_generation(self):
        payload = {"text": "가상 내담자 윤가온은 2주 동안 약을 복용하지 않았습니다."}
        with patch("app.api.routes.notes.generate_quick_summary") as generate:
            response = self.client.post("/api/notes/quick-summary", json=payload)
            self.assertEqual(409, response.status_code)
            generate.assert_not_called()
        with patch("app.services.deid_review.detect_entities", side_effect=DetectionUnavailable("private-detail")):
            response = self.client.post("/api/notes/deidentification-preview",
                                        json={"purpose": "quick", "payload": payload})
        self.assertEqual(503, response.status_code)
        self.assertNotIn("detection_token", response.text)
        self.assertNotIn("private-detail", response.text)

    def test_registered_routes_cover_existing_browser_operations(self):
        paths = {route.path for route in app.routes}
        for path in ["/api/audio/transcribe", "/api/materials/documents/extract",
                     "/api/notes/deidentification-preview", "/api/notes/deidentification-confirm",
                     "/api/notes/generate", "/api/notes/confirm", "/api/notes/drafts/{draft_id}",
                     "/api/notes/records/{note_id}", "/api/documents/export",
                     "/api/cases/{case_id}/dashboard"]:
            self.assertIn(path, paths)


if __name__ == "__main__":
    unittest.main()
