"""Opt-in, single-call session-summary skill; not connected to production routes.

Callers must supply the same already-deidentified input used by the baseline.
This replaces only extraction and summary, not upstream masking, verification,
relational insights, authentication or persistence. Reference checks establish
valid identifiers, not semantic support for a claim.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ConfigDict, create_model

from app.core.config import settings
from app.graph.nodes import _normalize_summary_refs, _source_catalog
from app.schemas.note import SanitizedInput, SessionInfo, SessionSummaryDraft, SummarySection
from app.services.llm import get_llm
from app.services.relational_insights import has_documented_counselor_reflection
from app.services.summary_quality import SummaryQualityError, summary_quality_issues


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "session-summary" / "SKILL.md"
SUMMARY_FIELDS = tuple(name for name in SessionSummaryDraft.model_fields if name != "session_info")
# Keep the existing section schema/descriptions without asking the model to repeat
# session metadata. The application supplies that metadata deterministically.
SummarySkillFields = create_model(
    "SummarySkillFields",
    __config__=ConfigDict(extra="forbid"),
    **{
        name: (field.annotation, deepcopy(field))
        for name, field in SessionSummaryDraft.model_fields.items()
        if name in SUMMARY_FIELDS
    },
)


class SummarySkillError(RuntimeError):
    """Safe failure without provider messages, source text or mock substitution."""

    def __init__(self) -> None:
        super().__init__("회기요약 Skill을 실행하지 못했습니다. 설정과 입력을 확인해주세요.")


@dataclass(frozen=True)
class SummarySkillRequest:
    messages: tuple[SystemMessage, HumanMessage]
    skill_sha256: str


@dataclass(frozen=True)
class SummarySkillResult:
    summary: SessionSummaryDraft
    skill_sha256: str
    model_calls: int
    latency_ms: int
    usage: dict[str, Any] | None
    response_model: str | None
    status: str = "draft_requires_counselor_confirmation"
    verification: str = "deterministic_only; semantic_verification_not_run"


def build_summary_skill_request(sanitized: SanitizedInput) -> SummarySkillRequest:
    """Load only the selected skill and send current-session sources once."""
    if sanitized.sources.previous_session_summary.strip():
        raise SummarySkillError()
    if not (sanitized.sources.transcript_text.strip() or sanitized.sources.counselor_memo.strip()):
        raise SummarySkillError()
    document = SKILL_PATH.read_text(encoding="utf-8")
    parts = document.split("---", 2)
    if len(parts) != 3 or parts[0].strip() or "name: session-summary" not in parts[1].splitlines():
        raise SummarySkillError()
    instructions = parts[2].strip()
    if not instructions:
        raise SummarySkillError()
    # Do not transmit session identifiers, personal metadata, or sensitive-info
    # candidate excerpts. Those are not necessary for summary generation.
    sources = {key: value for key, value in sanitized.sources.model_dump().items() if value}
    payload = {"sources": sources, "allowed_source_refs": list(_source_catalog(sanitized, []))}
    return SummarySkillRequest(
        messages=(
            SystemMessage(content=instructions),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        ),
        skill_sha256=hashlib.sha256(document.encode("utf-8")).hexdigest(),
    )


def run_summary_skill(sanitized: SanitizedInput) -> SummarySkillResult:
    """Make exactly one structured call, with no repair, retry or mock fallback.

    Live callers are responsible for explicit authorization and identical upstream
    de-identification in comparison runs. This function neither reads raw input
    files nor connects to storage. Usage is provider-reported or unavailable.
    """
    if settings.use_stub or not settings.openai_api_key:
        raise SummarySkillError()
    request = build_summary_skill_request(sanitized)
    started = time.perf_counter()
    try:
        result = get_llm(max_retries=0).with_structured_output(
            SummarySkillFields, include_raw=True,
        ).invoke(list(request.messages))
        if result.get("parsing_error") or result.get("parsed") is None:
            raise SummarySkillError()
        fields = SummarySkillFields.model_validate(result["parsed"])
        summary = SessionSummaryDraft(
            session_info=SessionInfo(
                case_id=sanitized.case_id,
                client_alias=sanitized.client_alias,
                session_number=sanitized.session_number,
                session_date=sanitized.session_date,
                counselor_name=sanitized.counselor_name,
            ),
            **fields.model_dump(),
        )
        _normalize_summary_refs(summary, sanitized, [])
        if not has_documented_counselor_reflection(sanitized.sources.counselor_memo):
            summary.reflection = SummarySection(
                text="[상담사 확인 필요]", evidence_type="counselor_input",
                source_refs=[], requires_review=True,
            )
        else:
            summary.reflection.requires_review = True
        if summary_quality_issues(summary):
            raise SummaryQualityError()
        raw = result.get("raw")
        reported_usage = getattr(raw, "usage_metadata", None)
        metadata = getattr(raw, "response_metadata", {}) or {}
        # Preserve numeric usage only; never keep raw provider content or headers.
        usage = {
            key: value for key, value in (reported_usage or {}).items()
            if key in {"input_tokens", "output_tokens", "total_tokens"}
            and isinstance(value, int) and not isinstance(value, bool) and value >= 0
        }
        response_model = metadata.get("model_name") or metadata.get("model")
        return SummarySkillResult(
            summary=summary, skill_sha256=request.skill_sha256, model_calls=1,
            latency_ms=round((time.perf_counter() - started) * 1000),
            usage=usage or None,
            response_model=response_model if isinstance(response_model, str) else None,
        )
    except SummaryQualityError:
        raise
    except Exception:
        raise SummarySkillError() from None
