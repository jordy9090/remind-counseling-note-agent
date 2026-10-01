"""Model-specific request compatibility without sending provider requests."""
import unittest
from unittest.mock import patch
from app.core.config import settings
from app.services.llm import get_llm


class ModelSettingsTests(unittest.TestCase):
    def test_reasoning_request_omits_temperature(self):
        with patch.object(settings, "openai_model", "gpt-5.4"), patch.object(settings, "openai_reasoning_effort", "low"), patch("app.services.llm.ChatOpenAI") as client:
            get_llm(timeout=90, max_retries=0)
        kwargs = client.call_args.kwargs
        self.assertEqual("low", kwargs["reasoning_effort"])
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(90, kwargs["timeout"])
        self.assertEqual(0, kwargs["max_retries"])

    def test_nonreasoning_request_preserves_sampling(self):
        with patch.object(settings, "openai_model", "gpt-4.1"), patch.object(settings, "openai_reasoning_effort", None), patch("app.services.llm.ChatOpenAI") as client:
            get_llm()
        kwargs = client.call_args.kwargs
        self.assertEqual(0.3, kwargs["temperature"])
        self.assertNotIn("reasoning_effort", kwargs)


if __name__ == "__main__":
    unittest.main()
