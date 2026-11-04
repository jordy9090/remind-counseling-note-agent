"""No raw counseling text may reach a provider during PII discovery."""
import unittest
from unittest.mock import patch

from app.core.config import settings
from app.services.deidentification_preview import preview_items
from app.services.storage_deidentification import deidentify_texts


class LocalDiscoveryTests(unittest.TestCase):
    def test_live_configuration_does_not_send_raw_text_to_a_model(self):
        text = "이름: 윤다온, 가상누리병원에 안 갔다. 2회기, 010-1234-5678."
        with patch.object(settings, "use_stub", False), \
             patch.object(settings, "openai_api_key", "synthetic-not-a-key"), \
             patch("app.services.llm.get_structured_llm") as provider:
            preview = preview_items([text], client_name="윤다온")
            masked, report = deidentify_texts({"transcript": text}, known_names=["윤다온"])
        provider.assert_not_called()
        self.assertFalse(preview.model_used)
        self.assertFalse(report.llm_used)
        self.assertIn("가상누리병원", {item.original for item in preview.items})
        for identifier in ("윤다온", "가상누리병원", "010-1234-5678"):
            self.assertNotIn(identifier, masked["transcript"])
        self.assertIn("안 갔다. 2회기", masked["transcript"])

    def test_local_discovery_does_not_invent_unlabeled_names(self):
        response = preview_items(["내담자: 지원을 받았고, 7살 때 안 갔다. 2회기다."])
        self.assertFalse(response.model_used)
        self.assertEqual([], response.items)


if __name__ == "__main__":
    unittest.main()
