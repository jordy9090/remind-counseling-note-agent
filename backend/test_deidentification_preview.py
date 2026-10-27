"""Pre-generation review items (/api/notes/deidentification-preview). Synthetic data only."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.services import deidentification_preview as preview
from app.services import storage_deidentification as deid
from app.services.quick_summary import rate_limiter
from test_quick_summary import _load_vercel_generate

TEXT = (
    "상담자: 지난주는 어땠어요?\n"
    "내담자: 저 윤다온이고 34세예요. 다온 씨라고 불러요. 동료 김민지랑 다퉜는데 민지가 먼저 사과했어요. "
    "한빛소프트에서 개발자로 일하고 역삼동에 살아요. 친구 박서준도 같이 있었어요."
)
ENTITIES = deid._StorageEntities(
    person_names=["윤다온", "다온", "김민지", "민지", "박서준", "없는사람", "홍O동"],
    occupations=[deid._OccupationMention(text="개발자", category="IT·기술직 종사자")],
    organizations=[deid._OrganizationMention(text="한빛소프트", kind="회사")],
    ages=[deid._AgeMention(text="34세", band="30대")],
    locations=["역삼동"],
)


def model_returns(entities):
    return patch.object(preview, "_extract_entities", return_value=entities)


class PreviewItemTests(unittest.TestCase):
    def items(self, **kwargs):
        return {item.original: (item.replacement, item.category) for item in preview.preview_items([TEXT], **kwargs).items}

    def test_client_and_other_people_get_review_screen_labels(self):
        with model_returns(ENTITIES):
            items = self.items(client_name="윤다온")
        self.assertEqual(items["윤다온"], ("내담자 A", "name"))
        self.assertEqual(items["다온"], ("내담자 A", "name"))
        # A given name shares its full name's label; each other person gets the next letter.
        self.assertEqual(items["김민지"][0], items["민지"][0])
        self.assertNotEqual(items["김민지"][0], items["박서준"][0])
        self.assertEqual({items["김민지"][0], items["박서준"][0]}, {"인물 B", "인물 C"})
        self.assertNotIn("없는사람", items)  # not in the text
        self.assertNotIn("홍O동", items)  # already masked
        self.assertEqual(items["한빛소프트"], ("회사", "organization"))
        self.assertEqual(items["개발자"], ("IT·기술직 종사자", "occupation"))
        self.assertEqual(items["34세"], ("30대", "age"))
        self.assertEqual(items["역삼동"], ("지역", "location"))

    def test_without_the_model_only_known_names_are_returned(self):
        with model_returns(None):
            response = preview.preview_items([TEXT], client_name="윤다온")
        self.assertFalse(response.model_used)
        self.assertEqual({item.original for item in response.items}, {"윤다온", "다온"})

    def test_input_is_capped(self):
        with self.assertRaises(preview.DeidentificationPreviewInputError):
            preview.preview_items(["가" * (preview.PREVIEW_MAX_CHARS + 1)])


class PreviewRouteTests(unittest.TestCase):
    def setUp(self):
        rate_limiter.reset()
        self.addCleanup(rate_limiter.reset)

    def test_guest_route_and_vercel_rewrite(self):
        body = {"texts": [TEXT], "client_name": "윤다온"}
        with model_returns(ENTITIES):
            direct = TestClient(app).post("/api/notes/deidentification-preview", json=body)
            rewritten = TestClient(_load_vercel_generate().app).post("/api/notes/generate?scope=deid-preview", json=body)
        for response in (direct, rewritten):
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(response.json()["model_used"])
            items = {item["original"]: item for item in response.json()["items"]}
            self.assertEqual(items["윤다온"]["replacement"], "내담자 A")
            self.assertEqual(items["박서준"]["category"], "name")
            self.assertTrue(items["박서준"]["replacement"].startswith("인물 "))

    def test_vercel_rewrite_is_configured(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "vercel.json").read_text(encoding="utf-8"))
        self.assertIn({"source": "/api/notes/deidentification-preview",
                       "destination": "/api/notes/generate?scope=deid-preview"}, config["rewrites"])

    def test_guests_are_rate_limited_separately_from_the_summary(self):
        client = TestClient(app)
        headers = {"x-real-ip": "203.0.113.21"}
        with model_returns(None):
            for _ in range(preview.ANONYMOUS_PREVIEW_LIMIT[0]):
                self.assertEqual(client.post("/api/notes/deidentification-preview", json={"texts": ["안녕하세요"]}, headers=headers).status_code, 200)
            blocked = client.post("/api/notes/deidentification-preview", json={"texts": ["안녕하세요"]}, headers=headers)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)

    def test_errors_do_not_echo_the_input(self):
        with patch.object(preview, "_extract_entities", side_effect=RuntimeError(TEXT)):
            response = TestClient(app).post("/api/notes/deidentification-preview", json={"texts": [TEXT]})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("윤다온", response.text)


if __name__ == "__main__":
    unittest.main()
