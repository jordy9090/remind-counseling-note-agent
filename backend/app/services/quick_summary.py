"""Quick summary: a four-item session summary that works without signing in.

Guarantees for this public path:
- The input is never stored (no DB, disk, or log writes of the text).
- PII patterns are masked before the text leaves the server for the LLM.
- Input length is capped and requests are rate limited per client IP
  (or per user when a valid session is present).

The rate limiter is in-memory, so on serverless platforms it is best-effort
per warm instance rather than a global quota.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import deque

from pydantic import BaseModel, Field

from app.core.config import settings
from app.graph.summary_core import PUBLIC_QUICK_POLICY, run_summary_core
from app.schemas.note import SessionInput
from app.services.deidentification import render_counselor_text
from app.services.llm import estimate_generation_cost_usd
from app.services.transcript_chunking import estimate_korean_tokens

QUICK_SUMMARY_MAX_CHARS = 20_000
QUICK_SUMMARY_MIN_CHARS = 20
ANONYMOUS_LIMIT = (5, 60 * 60)  # 5 requests per hour per IP
AUTHENTICATED_LIMIT = (60, 60 * 60)  # 60 requests per hour per user
_concurrency_guard = threading.BoundedSemaphore(settings.quick_summary_max_concurrent)

class QuickSummaryRequest(BaseModel):
    text: str = Field(default="", max_length=QUICK_SUMMARY_MAX_CHARS + 1000)


class QuickSummaryResponse(BaseModel):
    main_content: str
    client_response: str
    counselor_intervention: str
    next_plan: str
    masked_categories: list[str] = Field(default_factory=list)
    stub: bool = False


class QuickSummaryInputError(ValueError):
    """Input that cannot be summarized (empty, too short, or too long)."""


class QuickSummaryRateLimited(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__("rate limited")
        self.retry_after = retry_after


class QuickSummaryBusy(RuntimeError):
    """This server instance has no public-summary execution slot available."""


class QuickSummaryCostLimit(RuntimeError):
    """The conservative request estimate exceeds the configured public budget."""


class _SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: int, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= window:
                hits.popleft()
            if len(hits) >= limit:
                raise QuickSummaryRateLimited(max(1, int(window - (now - hits[0]))))
            hits.append(now)
            if len(self._hits) > 10_000:
                # Drop idle keys so the map cannot grow without bound.
                for stale in [k for k, v in self._hits.items() if not v]:
                    del self._hits[stale]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


rate_limiter = _SlidingWindowLimiter()


def rate_limit_key(*, client_ip: str, actor: str | None) -> tuple[str, int, int]:
    """Return a hashed limiter key plus (limit, window) for this caller."""
    if actor:
        limit, window = AUTHENTICATED_LIMIT
        raw = f"user:{actor}"
    else:
        limit, window = ANONYMOUS_LIMIT
        raw = f"ip:{client_ip or 'unknown'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), limit, window


def validate_quick_summary_text(text: str) -> str:
    cleaned = re.sub(r"[ \t]+\n", "\n", (text or "").strip())
    if len(cleaned) < QUICK_SUMMARY_MIN_CHARS:
        raise QuickSummaryInputError(f"요약할 상담 내용을 {QUICK_SUMMARY_MIN_CHARS}자 이상 입력해주세요.")
    if len(cleaned) > QUICK_SUMMARY_MAX_CHARS:
        raise QuickSummaryInputError(
            f"간편 요약은 {QUICK_SUMMARY_MAX_CHARS:,}자까지 입력할 수 있어요. 현재 {len(cleaned):,}자입니다."
        )
    return cleaned


def generate_quick_summary(text: str) -> QuickSummaryResponse:
    """Run the public shared core and render its four-item compatibility response."""
    cleaned = validate_quick_summary_text(text)
    _enforce_estimated_cost_limit(cleaned)
    acquired = _concurrency_guard.acquire(timeout=settings.quick_summary_concurrency_wait_seconds)
    if not acquired:
        raise QuickSummaryBusy("public summary capacity exhausted")
    try:
        core = run_summary_core(
            {
                "session_input": SessionInput(
                    case_id="public-quick-summary",
                    session_number=1,
                    counselor_memo="",
                    transcript_text=cleaned,
                    persist=False,
                    insight_lens="none",
                )
            },
            policy=PUBLIC_QUICK_POLICY,
        )
    finally:
        _concurrency_guard.release()
    sanitized = core["sanitized_input"]
    summary = core["session_summary_draft"]
    categories = sorted({candidate.category for candidate in sanitized.sensitive_info_candidates})

    return QuickSummaryResponse(
        main_content=render_counselor_text(summary.session_content.text.strip()),
        client_response=render_counselor_text(summary.client_response.text.strip()),
        counselor_intervention=render_counselor_text(summary.counselor_intervention.text.strip()),
        next_plan=render_counselor_text(summary.next_plan.text.strip()),
        masked_categories=categories,
        stub=settings.stub_mode,
    )


def _enforce_estimated_cost_limit(text: str) -> None:
    estimated_source_tokens = estimate_korean_tokens(text)
    estimated_cost = estimate_generation_cost_usd(
        input_tokens=(estimated_source_tokens + 4_000) * PUBLIC_QUICK_POLICY.max_core_provider_calls,
        output_tokens=2_500 * PUBLIC_QUICK_POLICY.max_core_provider_calls,
    )
    if estimated_cost is not None and estimated_cost > settings.quick_summary_max_estimated_cost_usd:
        raise QuickSummaryCostLimit("public summary estimated cost exceeds the configured maximum")
