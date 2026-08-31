"""Semantic validation of a claim against only its directly cited source text."""
from __future__ import annotations

from app.core.config import settings
from app.schemas.grounding import ClaimSupportValidation, GroundedClaim, GroundingSource
from app.services.llm import get_structured_llm


def build_claim_support_prompt(
    *,
    claim: GroundedClaim,
    evidence_by_id: dict[str, GroundingSource],
) -> str:
    """Build a deliberately closed prompt with no retrieval or case-history context."""
    cited = [
        evidence_by_id[evidence_id]
        for evidence_id in claim.evidence_ids
        if evidence_id in evidence_by_id
    ]
    rendered_sources = "\n\n".join(
        f"[{source.evidence_id}]\n{source.source_text}" for source in cited
    ) or "(none)"
    return f"""
Determine whether the CLAIM is semantically supported by the CITED SOURCES only.
Return only ClaimSupportValidation.

Rules:
- supported: every material atomic fact in the claim is directly stated or unambiguously entailed.
- partial: at least one material atomic fact is supported, but another is missing or stronger than the source.
- unsupported: the claim is not supported, describes a different event/session/state, or contradicts the source.
- Semantic similarity, a shared counseling goal, or a related topic is not support for a different event.
- Temporal state matters: an earlier setback does not support a later success, and vice versa.
- Counts, repetition, frequency, totality, immediacy, and degree require explicit support. One event never supports
  claims such as repeated, three times, always, completely, immediately, or greatly.
- If one material atom is supported but another is missing, exaggerated, or contradicted, use partial.
- Use unsupported when no material claim atom is supported or the central event/state is a different one.
- supported_evidence_ids may contain only cited IDs that actually support the claim.
- For partial or unsupported, category may be one of missing_fact, contradiction, wrong_event,
  wrong_session, or over_inference. Do not provide free-text reasoning.

CLAIM
{claim.text}

CITED SOURCES
{rendered_sources}
""".strip()


def validate_claim_support(
    *,
    claim: GroundedClaim,
    evidence_by_id: dict[str, GroundingSource],
) -> ClaimSupportValidation:
    """Validate one claim without access to queries, other sources, memo, or history."""
    cited_ids = [evidence_id for evidence_id in claim.evidence_ids if evidence_id in evidence_by_id]
    if not cited_ids:
        return ClaimSupportValidation(
            verdict="unsupported",
            supported_evidence_ids=[],
            category="missing_fact",
        )
    if settings.stub_mode:
        return _stub_claim_support(claim=claim, evidence_by_id=evidence_by_id)

    try:
        raw = get_structured_llm(ClaimSupportValidation).invoke(
            build_claim_support_prompt(claim=claim, evidence_by_id=evidence_by_id)
        )
    except Exception:
        return ClaimSupportValidation(
            verdict="unsupported",
            supported_evidence_ids=[],
            category="missing_fact",
        )
    allowed_ids = set(cited_ids)
    supported_ids = [
        evidence_id for evidence_id in raw.supported_evidence_ids if evidence_id in allowed_ids
    ]
    verdict = raw.verdict
    category = raw.category
    if verdict == "supported" and not supported_ids:
        verdict = "unsupported"
        category = category or "missing_fact"
    if verdict == "supported":
        category = None
    return ClaimSupportValidation(
        verdict=verdict,
        supported_evidence_ids=_unique(supported_ids),
        category=category,
    )


def _stub_claim_support(
    *,
    claim: GroundedClaim,
    evidence_by_id: dict[str, GroundingSource],
) -> ClaimSupportValidation:
    """Offline stub approves only literal source-contained text, never semantic guesses."""
    normalized_claim = _normalize(claim.text)
    supported_ids = [
        evidence_id
        for evidence_id in claim.evidence_ids
        if evidence_id in evidence_by_id
        and normalized_claim
        and normalized_claim in _normalize(evidence_by_id[evidence_id].source_text)
    ]
    if supported_ids:
        return ClaimSupportValidation(verdict="supported", supported_evidence_ids=supported_ids)
    return ClaimSupportValidation(
        verdict="unsupported",
        supported_evidence_ids=[],
        category="missing_fact",
    )


def _normalize(value: str) -> str:
    return "".join(value.split()).casefold()


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
