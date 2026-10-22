"""Quick summary: the regular session summary pipeline, available without signing in.

The only difference from the signed-in summary is where it is started. The same graph runs on the same
de-identified session input and returns the same response, with retrieval switched off (no case
memory, raw evidence or KB lookups, so a guest request never touches storage).

Guarantees for this public path:
- The input is never stored (no DB, disk, or log writes of the text).
- The input is de-identified (names, organizations, ages, places, contacts) before generation.
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

from app.schemas.note import GenerateNoteResponse, SessionInput
from app.services.storage_deidentification import deidentify_session_input

QUICK_SUMMARY_MAX_CHARS = 20_000
QUICK_SUMMARY_MIN_CHARS = 20
ANONYMOUS_LIMIT = (5, 60 * 60)  # 5 requests per hour per IP
AUTHENTICATED_LIMIT = (60, 60 * 60)  # 60 requests per hour per user
QUICK_SUMMARY_CASE_ID = "quick-summary"
# Two or more speaker-labelled lines ("내담자: ...", "상담자: ...") mean the text is a transcript.
_SPEAKER_LINE = re.compile(r"^\s*(?:내담자|상담자|상담사|Cl|Co|CL|CO)\s*\d*\s*[:：]", re.MULTILINE)


class QuickSummaryRequest(BaseModel):
    text: str = Field(default="", max_length=QUICK_SUMMARY_MAX_CHARS + 1000)


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


def quick_summary_session_input(text: str) -> SessionInput:
    """The pasted text as a one-off session: a transcript when it has speaker lines, otherwise a memo."""
    cleaned = validate_quick_summary_text(text)
    is_transcript = len(_SPEAKER_LINE.findall(cleaned)) >= 2
    return SessionInput(
        case_id=QUICK_SUMMARY_CASE_ID,
        session_number=1,
        counselor_memo="" if is_transcript else cleaned,
        transcript_text=cleaned if is_transcript else "",
        persist=False,
    )


def generate_quick_summary(text: str) -> GenerateNoteResponse:
    """Run the regular summary pipeline on the de-identified text, without retrieval or storage."""
    from app.graph.graph import run_note_pipeline

    session_input, _ = deidentify_session_input(quick_summary_session_input(text))
    return run_note_pipeline(session_input, actor="", allow_retrieval=False)
