"""Generation-provider construction and content-free request telemetry."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core.config import settings


_METRICS_LOGGER = logging.getLogger("remind.llm_metrics")
_DEFAULT_OPENAI_PRICING_PER_MILLION = {
    "gpt-5.4": (2.50, 0.25, 15.00),
}
_STAGE_BY_SCHEMA = {
    "StructuredCaseData": "structure_session",
    "SessionSummaryDraft": "generate_summary",
    "VerificationReport": "verify_summary",
    "RelationalInsightDraft": "relational_insights",
    "ClaimSupportValidation": "claim_support_validation",
    "GroundedGenerationDraft": "grounded_generation",
    "_StorageEntities": "storage_deidentification_extraction",
}


@dataclass(frozen=True)
class LLMCallMetric:
    request_id: str
    request_type: str
    stage: str
    provider: str
    model: str
    latency_ms: int
    success: bool
    input_tokens: int | None
    output_tokens: int | None
    cached_input_tokens: int | None
    retry_count: int | None
    estimated_cost_usd: float | None
    error_type: str | None = None


@dataclass
class LLMRequestObservation:
    request_type: str
    max_calls: int | None = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    calls: list[LLMCallMetric] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "event": "llm_request_summary",
            "request_id": self.request_id,
            "request_type": self.request_type,
            "call_count": len(self.calls),
            "max_calls": self.max_calls,
            "successful_calls": sum(metric.success for metric in self.calls),
            "failed_calls": sum(not metric.success for metric in self.calls),
            "input_tokens": _known_sum(metric.input_tokens for metric in self.calls),
            "output_tokens": _known_sum(metric.output_tokens for metric in self.calls),
            "cached_input_tokens": _known_sum(metric.cached_input_tokens for metric in self.calls),
            "estimated_cost_usd": _known_float_sum(metric.estimated_cost_usd for metric in self.calls),
            "calls": [asdict(metric) for metric in self.calls],
        }


_CURRENT_OBSERVATION: ContextVar[LLMRequestObservation | None] = ContextVar(
    "llm_request_observation",
    default=None,
)


@contextmanager
def observe_llm_request(request_type: str, *, max_calls: int | None = None) -> Iterator[LLMRequestObservation]:
    """Collect provider metadata for one request without retaining its content."""
    observation = LLMRequestObservation(request_type=request_type, max_calls=max_calls)
    token = _CURRENT_OBSERVATION.set(observation)
    try:
        yield observation
    finally:
        _CURRENT_OBSERVATION.reset(token)
        _METRICS_LOGGER.info(json.dumps(observation.summary(), separators=(",", ":")))


def get_llm(*, timeout: float | None = None, max_retries: int = 0) -> ChatOpenAI:
    """Build exactly one configured provider client without fallback."""
    if not settings.llm_configured:
        raise RuntimeError("The configured generation provider is unavailable.")
    options: dict[str, Any] = {
        "model": settings.openai_model,
        "api_key": settings.effective_llm_api_key,
        "timeout": timeout if timeout is not None else settings.openai_timeout_seconds,
        "max_retries": max_retries,
    }
    if settings.llm_provider == "openai_compatible":
        options["base_url"] = settings.openai_compatible_base_url
    effort = settings.openai_reasoning_effort or ("low" if settings.openai_model == "gpt-5.4" else None)
    if effort:
        options["reasoning_effort"] = effort
    else:
        options["temperature"] = 0.3
    return ChatOpenAI(**options)


def get_structured_llm(
    schema: type[BaseModel],
    *,
    stage: str | None = None,
    timeout: float | None = None,
    max_retries: int = 0,
):
    """Return a Pydantic-output runnable instrumented with metadata-only metrics."""
    llm = get_llm(timeout=timeout, max_retries=max_retries)
    runnable = llm.with_structured_output(schema, include_raw=True)
    return _InstrumentedStructuredRunnable(
        runnable,
        stage=stage or _STAGE_BY_SCHEMA.get(schema.__name__, f"structured:{schema.__name__}"),
        max_retries=max_retries,
    )


class _InstrumentedStructuredRunnable:
    def __init__(self, runnable: Any, *, stage: str, max_retries: int) -> None:
        self._runnable = runnable
        self._stage = stage
        self._max_retries = max_retries

    def invoke(self, provider_input: Any, config: Any = None, **kwargs: Any) -> BaseModel:
        observation = _CURRENT_OBSERVATION.get()
        if observation and observation.max_calls is not None and len(observation.calls) >= observation.max_calls:
            raise LLMCallBudgetExceeded(
                f"Provider call budget exhausted for {observation.request_type}."
            )
        started = time.perf_counter()
        try:
            if config is None:
                result = self._runnable.invoke(provider_input, **kwargs)
            else:
                result = self._runnable.invoke(provider_input, config=config, **kwargs)
            parsed, raw, parsing_error = _structured_result(result)
            if parsing_error is not None:
                raise parsing_error
            if parsed is None:
                raise ValueError("Structured provider response did not contain a parsed result.")
        except Exception as error:
            _record_metric(
                stage=self._stage,
                latency_ms=_elapsed_ms(started),
                success=False,
                raw=None,
                max_retries=self._max_retries,
                error_type=type(error).__name__,
            )
            raise
        _record_metric(
            stage=self._stage,
            latency_ms=_elapsed_ms(started),
            success=True,
            raw=raw,
            max_retries=self._max_retries,
        )
        return parsed


class LLMCallBudgetExceeded(RuntimeError):
    """A request attempted more provider calls than its configured maximum."""


def _structured_result(result: Any) -> tuple[Any, Any, Exception | None]:
    if isinstance(result, dict) and {"parsed", "raw"}.issubset(result):
        return result.get("parsed"), result.get("raw"), result.get("parsing_error")
    return result, None, None


def _record_metric(
    *,
    stage: str,
    latency_ms: int,
    success: bool,
    raw: Any,
    max_retries: int,
    error_type: str | None = None,
) -> None:
    usage = _usage_metadata(raw)
    record_external_ai_call(
        stage=stage,
        provider=settings.llm_provider,
        model=_response_model(raw) or settings.openai_model,
        latency_ms=latency_ms,
        success=success,
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
        cached_input_tokens=usage["cached_input_tokens"],
        retry_count=0 if max_retries == 0 else None,
        estimated_cost_usd=_estimated_cost(
            usage["input_tokens"],
            usage["output_tokens"],
            usage["cached_input_tokens"],
        ),
        error_type=error_type,
    )


def record_external_ai_call(
    *,
    stage: str,
    provider: str,
    model: str,
    latency_ms: int,
    success: bool,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    retry_count: int | None = None,
    estimated_cost_usd: float | None = None,
    error_type: str | None = None,
) -> None:
    """Record only operational metadata for an external AI call."""
    observation = _CURRENT_OBSERVATION.get()
    request_id = observation.request_id if observation else uuid.uuid4().hex
    request_type = observation.request_type if observation else "unscoped"
    metric = LLMCallMetric(
        request_id=request_id,
        request_type=request_type,
        stage=stage,
        provider=provider,
        model=model,
        latency_ms=latency_ms,
        success=success,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        retry_count=retry_count,
        estimated_cost_usd=estimated_cost_usd,
        error_type=error_type,
    )
    if observation:
        observation.calls.append(metric)
    else:
        _METRICS_LOGGER.info(json.dumps({"event": "llm_call", **asdict(metric)}, separators=(",", ":")))


def estimate_generation_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float | None:
    """Estimate configured generation cost, or return unknown for unpriced providers."""
    return _estimated_cost(input_tokens, output_tokens, cached_input_tokens)


def _usage_metadata(raw: Any) -> dict[str, int | None]:
    usage = getattr(raw, "usage_metadata", None) or {}
    response_metadata = getattr(raw, "response_metadata", None) or {}
    provider_usage = response_metadata.get("token_usage") or response_metadata.get("usage") or {}
    input_details = usage.get("input_token_details") or {}
    prompt_details = provider_usage.get("prompt_tokens_details") or {}
    return {
        "input_tokens": _first_int(usage.get("input_tokens"), provider_usage.get("prompt_tokens")),
        "output_tokens": _first_int(usage.get("output_tokens"), provider_usage.get("completion_tokens")),
        "cached_input_tokens": _first_int(
            input_details.get("cache_read"),
            input_details.get("cached_tokens"),
            prompt_details.get("cached_tokens"),
        ),
    }


def _response_model(raw: Any) -> str | None:
    metadata = getattr(raw, "response_metadata", None) or {}
    value = metadata.get("model_name") or metadata.get("model")
    return str(value) if value else None


def _estimated_cost(
    input_tokens: int | None,
    output_tokens: int | None,
    cached_input_tokens: int | None,
) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None
    pricing = _effective_pricing()
    if pricing is None:
        return None
    input_rate, cached_rate, output_rate = pricing
    cached_tokens = min(cached_input_tokens or 0, input_tokens)
    uncached_tokens = input_tokens - cached_tokens
    return round(
        uncached_tokens * input_rate / 1_000_000
        + cached_tokens * cached_rate / 1_000_000
        + output_tokens * output_rate / 1_000_000,
        8,
    )


def _effective_pricing() -> tuple[float, float, float] | None:
    if (
        settings.llm_input_cost_per_million_usd is not None
        and settings.llm_output_cost_per_million_usd is not None
    ):
        return (
            settings.llm_input_cost_per_million_usd,
            settings.llm_cached_input_cost_per_million_usd
            if settings.llm_cached_input_cost_per_million_usd is not None
            else settings.llm_input_cost_per_million_usd,
            settings.llm_output_cost_per_million_usd,
        )
    if settings.llm_provider == "openai":
        return _DEFAULT_OPENAI_PRICING_PER_MILLION.get(settings.openai_model)
    return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _known_sum(values: Any) -> int | None:
    items = list(values)
    return sum(items) if items and all(value is not None for value in items) else None


def _known_float_sum(values: Any) -> float | None:
    items = list(values)
    return round(sum(items), 8) if items and all(value is not None for value in items) else None


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.perf_counter() - started) * 1000))
