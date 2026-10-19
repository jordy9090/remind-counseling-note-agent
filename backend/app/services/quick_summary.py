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
아래 상담 내용을 읽고 상담사가 검토·수정할 수 있는 간결한 3인칭 기록체로 다음 네 항목을 작성하세요.

- main_content (주요 상담 내용): 주요 사건, 회기에서 실제로 탐색한 내용, 남아 있는 어려움을 1~3문장으로 통합
- client_response (내담자 반응): 입력에서 확인되는 내담자의 정서·인지·행동 반응과, 기록된 경우 상담자 개입에 대한 반응을 1~2문장으로 정리
- counselor_intervention (상담자 개입): 상담자가 실제로 한 질문·반영·탐색·역할연습 등 개입의 대상과 내용을 1~2문장으로 정리
- next_plan (다음 회기 계획): 입력에서 실제로 제안하거나 합의한 계획만 1문장으로 정리

규칙:
- 입력에 근거한 내용만 쓰고, 자료가 적으면 짧게 쓰세요. 분량을 채우기 위해 사실을 보충하지 마세요.
- 각 항목에 해당하는 내용이 입력에 없으면 "입력 내용에서 확인되지 않음"이라고 쓰세요.
- 상담자의 질문·반영과 내담자의 표현·반응을 구분하고, 누가 누구의 반응을 살폈는지 보존하세요.
- 관찰된 사실과 내담자의 예상·지각을 구분하세요. 상대의 의도, 반복되는 관계 패턴, 호전이나 목표 달성을 확대 해석하지 마세요.
- 입력에 명시된 반대 근거, 관계·장면 사이의 차이, 불확실성, 여전히 남은 어려움을 생략해 뜻을 바꾸지 마세요.
- 이미 회기에서 수행한 탐색을 다음 회기 계획으로 바꾸지 마세요. 상담자의 제안은 "제안함"으로,
  명시적으로 합의한 계획만 "하기로 함"으로 기록하세요. 별도 과제나 계획을 새로 만들지 마세요.
- 다음 회기 계획이 입력에 없으면 next_plan에 "입력 내용에서 확인되지 않음"이라고 쓰세요.
- 발화를 그대로 이어 붙이거나 화자 표지가 붙은 대화문으로 출력하지 말고 의미를 압축해 재서술하세요.
- 진단, 위험도 판정, 치료 권고를 하지 마세요.
- [PERSON], [PHONE] 같은 가림 표시는 그대로 두세요.

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
    main_content: str = Field(description="근거가 있는 주요 사건·탐색·남은 어려움을 압축한 상담 기록")
    client_response: str = Field(description="입력에서 확인되는 내담자의 정서·인지·행동 반응과 기록된 개입에 대한 반응")
    counselor_intervention: str = Field(description="상담자가 실제로 한 질문·반영·탐색·역할연습 등 개입")
    next_plan: str = Field(description="실제로 제안하거나 합의한 계획, 없으면 입력 내용에서 확인되지 않음")


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
