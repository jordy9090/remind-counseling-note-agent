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
from app.services.deidentification import deidentify_text, render_counselor_text

QUICK_SUMMARY_MAX_CHARS = 20_000
QUICK_SUMMARY_MIN_CHARS = 20
ANONYMOUS_LIMIT = (5, 60 * 60)  # 5 requests per hour per IP
AUTHENTICATED_LIMIT = (60, 60 * 60)  # 60 requests per hour per user

QUICK_SUMMARY_PROMPT = """당신은 심리상담사의 상담 기록 정리를 돕는 보조자입니다.
아래 상담 내용을 읽고 다음 네 항목으로 간결하게 정리하세요.

- main_content (주요 상담 내용): 이번 회기에서 다룬 핵심 주제와 호소 내용
- client_response (내담자 반응): 내담자가 보인 정서·인지·행동 반응
- counselor_intervention (상담자 개입): 상담자가 사용한 개입과 그 의도
- next_plan (다음 회기 계획): 다음 회기에 이어갈 과제나 계획

규칙:
- 입력에 근거한 내용만 쓰고, 입력에 없는 내용은 "입력 내용에서 확인되지 않음"이라고 쓰세요.
- 진단, 위험도 판정, 치료 권고를 하지 마세요.
- [PERSON], [PHONE] 같은 가림 표시는 그대로 두세요.
- 각 항목은 2~4문장의 한국어 서술형으로 작성하세요.

상담 내용:
{text}
"""


class QuickSummaryRequest(BaseModel):
    text: str = Field(default="", max_length=QUICK_SUMMARY_MAX_CHARS + 1000)


class QuickSummaryResponse(BaseModel):
    main_content: str
    client_response: str
    counselor_intervention: str
    next_plan: str
    masked_categories: list[str] = Field(default_factory=list)
    stub: bool = False


class _QuickSummaryDraft(BaseModel):
    main_content: str = Field(description="주요 상담 내용")
    client_response: str = Field(description="내담자 반응")
    counselor_intervention: str = Field(description="상담자 개입")
    next_plan: str = Field(description="다음 회기 계획")


class QuickSummaryInputError(ValueError):
    """Input that cannot be summarized (empty, too short, or too long)."""


class QuickSummaryRateLimited(RuntimeError):
    def __init__(self, retry_after: int):
        super().__init__("rate limited")
        self.retry_after = retry_after


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
    """Mask PII, summarize into four items, and render placeholders for counselors."""
    cleaned = validate_quick_summary_text(text)
    masked, candidates = deidentify_text(cleaned, source="quick_summary")
    categories = sorted({candidate.category for candidate in candidates})

    if settings.stub_mode:
        draft = _stub_summary(masked)
    else:
        from app.services.llm import get_structured_llm

        llm = get_structured_llm(_QuickSummaryDraft)
        draft = llm.invoke(QUICK_SUMMARY_PROMPT.format(text=masked))

    return QuickSummaryResponse(
        main_content=render_counselor_text(draft.main_content.strip()),
        client_response=render_counselor_text(draft.client_response.strip()),
        counselor_intervention=render_counselor_text(draft.counselor_intervention.strip()),
        next_plan=render_counselor_text(draft.next_plan.strip()),
        masked_categories=categories,
        stub=settings.stub_mode,
    )


def _stub_summary(masked: str) -> _QuickSummaryDraft:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。])\s+|\n+", masked) if part.strip()]
    lead = " ".join(sentences[:2]) or masked[:200]
    return _QuickSummaryDraft(
        main_content=f"(데모 요약) {lead[:300]}",
        client_response="(데모 요약) 내담자 반응은 실제 AI 연결 후 정리됩니다.",
        counselor_intervention="(데모 요약) 상담자 개입은 실제 AI 연결 후 정리됩니다.",
        next_plan="(데모 요약) 다음 회기 계획은 실제 AI 연결 후 정리됩니다.",
    )
