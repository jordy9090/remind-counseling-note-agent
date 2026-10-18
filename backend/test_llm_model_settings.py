"""Model-specific request compatibility without sending provider requests."""
import unittest
from unittest.mock import patch
from app.core.config import settings
from app.services.llm import get_llm


class ModelSettingsTests(unittest.TestCase):
    def test_evaluated_model_defaults_to_low_reasoning_and_bounded_call(self):
        with patch.object(settings, "openai_api_key", "synthetic-key"), patch.object(settings, "openai_model", "gpt-5.4"), patch.object(settings, "openai_reasoning_effort", None), patch.object(settings, "openai_timeout_seconds", 60), patch("app.services.llm.ChatOpenAI") as client:
            get_llm()
        kwargs = client.call_args.kwargs
        self.assertEqual("low", kwargs["reasoning_effort"])
        self.assertEqual(60, kwargs["timeout"])
        self.assertEqual(0, kwargs["max_retries"])
        self.assertNotIn("temperature", kwargs)

    def test_reasoning_request_omits_temperature(self):
        with patch.object(settings, "openai_api_key", "synthetic-key"), patch.object(settings, "openai_model", "gpt-5.4"), patch.object(settings, "openai_reasoning_effort", "low"), patch("app.services.llm.ChatOpenAI") as client:
            get_llm(timeout=90, max_retries=0)
        kwargs = client.call_args.kwargs
        self.assertEqual("low", kwargs["reasoning_effort"])
        self.assertNotIn("temperature", kwargs)
        self.assertEqual(90, kwargs["timeout"])
        self.assertEqual(0, kwargs["max_retries"])

    def test_nonreasoning_request_preserves_sampling(self):
        with patch.object(settings, "openai_api_key", "synthetic-key"), patch.object(settings, "openai_model", "gpt-4.1"), patch.object(settings, "openai_reasoning_effort", None), patch("app.services.llm.ChatOpenAI") as client:
            get_llm()
        kwargs = client.call_args.kwargs
        self.assertEqual(0.3, kwargs["temperature"])
        self.assertNotIn("reasoning_effort", kwargs)

    def test_openai_compatible_provider_uses_only_the_configured_endpoint(self):
        with patch.object(settings, "llm_provider", "openai_compatible"), patch.object(
            settings, "openai_compatible_base_url", "http://127.0.0.1:9000/v1"
        ), patch.object(settings, "openai_compatible_api_key", None), patch.object(
            settings, "openai_reasoning_effort", None
        ), patch("app.services.llm.ChatOpenAI") as client:
            get_llm()

        kwargs = client.call_args.kwargs
        self.assertEqual("http://127.0.0.1:9000/v1", kwargs["base_url"])
        self.assertEqual("local-openai-compatible", kwargs["api_key"])

    def test_unconfigured_openai_provider_fails_before_client_creation(self):
        with patch.object(settings, "llm_provider", "openai"), patch.object(
            settings, "openai_api_key", None
        ), patch("app.services.llm.ChatOpenAI") as client:
            with self.assertRaises(RuntimeError):
                get_llm()
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
