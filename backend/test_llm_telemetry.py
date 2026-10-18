"""Metadata-only LLM telemetry and provider-budget regression tests."""
from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import BaseModel

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings
from app.services.llm import (
    LLMCallBudgetExceeded,
    _InstrumentedStructuredRunnable,
    observe_llm_request,
)
from api.notes import recompose as vercel_recompose


vercel_supervision = importlib.import_module("api.notes.supervision-report")


class _Answer(BaseModel):
    value: str


class LLMTelemetryTests(unittest.TestCase):
    def test_usage_and_estimated_cost_are_collected_without_content(self) -> None:
        raw = SimpleNamespace(
            usage_metadata={
                "input_tokens": 100,
                "output_tokens": 20,
                "input_token_details": {"cache_read": 40},
            },
            response_metadata={"model_name": "synthetic-model"},
        )
        runnable = Mock()
        runnable.invoke.return_value = {
            "parsed": _Answer(value="PRIVATE_SYNTHETIC_OUTPUT"),
            "raw": raw,
            "parsing_error": None,
        }
        instrumented = _InstrumentedStructuredRunnable(runnable, stage="synthetic_stage", max_retries=0)

        with patch.object(settings, "llm_input_cost_per_million_usd", 1.0), patch.object(
            settings, "llm_output_cost_per_million_usd", 2.0
        ), self.assertLogs("remind.llm_metrics", level="INFO") as logs:
            with observe_llm_request("synthetic_request", max_calls=2) as observation:
                result = instrumented.invoke("PRIVATE_SYNTHETIC_PROMPT")

        self.assertEqual("PRIVATE_SYNTHETIC_OUTPUT", result.value)
        metric = observation.calls[0]
        self.assertEqual(100, metric.input_tokens)
        self.assertEqual(20, metric.output_tokens)
        self.assertEqual(40, metric.cached_input_tokens)
        self.assertEqual(0.00014, metric.estimated_cost_usd)
        rendered_log = "\n".join(logs.output)
        self.assertNotIn("PRIVATE_SYNTHETIC_PROMPT", rendered_log)
        self.assertNotIn("PRIVATE_SYNTHETIC_OUTPUT", rendered_log)

    def test_missing_provider_usage_is_unknown_not_zero(self) -> None:
        runnable = Mock()
        runnable.invoke.return_value = {"parsed": _Answer(value="ok"), "raw": SimpleNamespace(), "parsing_error": None}
        instrumented = _InstrumentedStructuredRunnable(runnable, stage="unknown_usage", max_retries=0)

        with observe_llm_request("synthetic_request") as observation:
            instrumented.invoke("content")

        metric = observation.calls[0]
        self.assertIsNone(metric.input_tokens)
        self.assertIsNone(metric.output_tokens)
        self.assertIsNone(metric.cached_input_tokens)
        self.assertIsNone(metric.estimated_cost_usd)
        self.assertIsNone(observation.summary()["input_tokens"])

    def test_request_call_budget_blocks_without_provider_fallback(self) -> None:
        runnable = Mock()
        runnable.invoke.return_value = {"parsed": _Answer(value="ok"), "raw": SimpleNamespace(), "parsing_error": None}
        instrumented = _InstrumentedStructuredRunnable(runnable, stage="bounded", max_retries=0)

        with observe_llm_request("public_quick_summary", max_calls=1):
            instrumented.invoke("first")
            with self.assertRaises(LLMCallBudgetExceeded):
                instrumented.invoke("second")

        self.assertEqual(1, runnable.invoke.call_count)

    def test_provider_failure_is_recorded_once_and_propagated(self) -> None:
        runnable = Mock()
        runnable.invoke.side_effect = RuntimeError("provider unavailable")
        instrumented = _InstrumentedStructuredRunnable(runnable, stage="bounded", max_retries=0)

        with observe_llm_request("synthetic_request") as observation:
            with self.assertRaises(RuntimeError):
                instrumented.invoke("content")

        self.assertEqual(1, runnable.invoke.call_count)
        self.assertEqual(1, len(observation.calls))
        self.assertFalse(observation.calls[0].success)
        self.assertEqual("RuntimeError", observation.calls[0].error_type)

    def test_vercel_wrappers_apply_request_call_budgets(self) -> None:
        with patch.object(vercel_recompose, "observe_llm_request", return_value=nullcontext()) as guard, patch.object(
            vercel_recompose,
            "recompose_note_with_cache",
            return_value="recomposed",
        ):
            result = asyncio.run(vercel_recompose.recompose_note_draft(object(), actor="synthetic-owner"))
        self.assertEqual("recomposed", result)
        guard.assert_called_once_with("recompose_summary", max_calls=16)

        with patch.object(vercel_supervision, "observe_llm_request", return_value=nullcontext()) as guard, patch.object(
            vercel_supervision,
            "run_supervision_report_pipeline",
            return_value="supervision",
        ):
            result = asyncio.run(vercel_supervision.generate_supervision_report(object(), actor="synthetic-owner"))
        self.assertEqual("supervision", result)
        guard.assert_called_once_with("supervision_report", max_calls=4)


if __name__ == "__main__":
    unittest.main()
