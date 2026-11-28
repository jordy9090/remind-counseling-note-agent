"""Apply independent summary checks without changing the public response schema."""
from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field, create_model

from app.schemas.note import (CounselorReviewField, ReviewableClaim, SessionSummaryDraft,
                              SessionSummaryV2, VerificationReport, summary_v2_to_v1)
from app.services.summary_quality import QUOTED_TEXT, SECTION_LIMITS
from app.services.summary_corrections import SourceRefRestoration, SourceRefReview, TextCorrection
from app.services.summary_quality import enforce_summary_v2, REACTION_WARNING, UNDERSTANDING_WARNING


def apply_summary_v2_verification(
    summary: SessionSummaryV2, result: SummaryAssessment | None, catalog: dict[str, str],
) -> VerificationReport:
    """Validate the compatibility view and retain the original v2 item boundaries."""
    enforce_summary_v2(summary, catalog)
    report = VerificationReport()
    if result is not None:
        legacy = summary_v2_to_v1(summary)
        report = apply_summary_verification(legacy, result, catalog)
        for field in ("session_theme", "session_content", "counselor_intervention", "reflection", "next_plan"):
            setattr(summary, field, getattr(legacy, field))
        # A merged concern or reaction cannot safely be rewritten back into items.
        # Preserve the original, independently checked text and propagate review flags.
        summary.presenting_concern.requires_review |= legacy.presenting_problem.requires_review
        summary.client_reactions.requires_review |= legacy.client_response.requires_review
        for review in report.requires_counselor_review:
            if review.field == "presenting_problem":
                summary.episodes.requires_review = True
                review.field = "presenting_concern"
            elif review.field == "client_response":
                review.field = "client_reactions"
    report.requires_counselor_review.append(CounselorReviewField(
        field="client_understanding", reason="내담자 이해는 잠정적 해석이며 항상 상담사 확인이 필요합니다.",
    ))
    if summary.client_reactions.requires_review:
        report.requires_counselor_review.append(CounselorReviewField(
            field="client_reactions", reason="인용 원문과 내담자 반응의 수를 확인해주세요.",
        ))
    for warning in summary.warnings:
        field = "client_reactions" if warning == REACTION_WARNING else "client_understanding"
        report.requires_counselor_review.append(CounselorReviewField(field=field, reason=warning))
        if warning == UNDERSTANDING_WARNING:
            report.unsupported_or_risky_claims.append(ReviewableClaim(
                claim=summary.client_understanding.text, reason=warning,
                recommendation="근거와 추정 어미를 확인하고 단정적 표현을 수정해주세요.",
            ))
    return report


class PlanEvidence(BaseModel):
    source_ref: str
    quote: str


class PlanAssessment(BaseModel):
    status: Literal["supported_future", "in_session_only", "not_documented", "uncertain"] = "uncertain"
    evidence: list[PlanEvidence] = Field(default_factory=list)
    prior_context_evidence: list[PlanEvidence] = Field(default_factory=list, description=(
        "Exact prior-record quotes defining a method explicitly continued in the current plan. "
        "Only stored_session_note IDs; never evidence of current consent, timing or performance. "
        "Leave empty for discontinued, unrelated or ambiguously referenced methods."
    ))


class SummaryAssessment(VerificationReport):
    """Private semantic assessment shared by initial and final verification."""

    next_plan_assessment: PlanAssessment = Field(default_factory=PlanAssessment)
    correction_validated: bool = False


class SummaryCorrectionValidation(SummaryAssessment):
    """Validate corrections and cancel only removals that lose required evidence."""

    correction_validated: bool = Field(default=False, description=(
        "Whether the bounded edits are safe after the specified restorations. "
        "This does not certify the unchanged original draft as free of all semantic warnings."
    ))
    source_ref_restorations: list[SourceRefRestoration] = Field(default_factory=list, max_length=7)


class SummaryVerification(SummaryAssessment):
    """Private initial verifier output with bounded correction proposals."""

    text_corrections: list[TextCorrection] = Field(default_factory=list, max_length=14)
    source_ref_reviews: list[SourceRefReview] = Field(default_factory=list, max_length=7)


def summary_verification_schema(summary: SessionSummaryDraft) -> type[SummaryVerification]:
    """Constrain model citation choices to existing IDs in the same draft field."""
    reviews = []
    for field in SECTION_LIMITS:
        refs = list(dict.fromkeys(getattr(summary, field).source_refs))
        if not refs:
            continue
        reviews.append(create_model(
            f"{field.title().replace('_', '')}SourceReview", __base__=SourceRefReview,
            field=(Literal[field], field),
            keep_source_refs=(list[Literal[tuple(refs)]], Field(default_factory=list)),
        ))
    review_type = Union[tuple(reviews)] if reviews else SourceRefReview
    return create_model(
        "DraftBoundSummaryVerification", __base__=SummaryVerification,
        source_ref_reviews=(list[review_type], Field(default_factory=list, max_length=len(reviews))),
    )


def _literal(value: str) -> str:
    return " ".join(value.split())


def cited_lines(refs: list[str], catalog: dict[str, str]) -> list[str]:
    has_turns = any(ref.startswith("transcript.turn_") for ref in refs)
    return [
        _literal(line)
        for ref in refs if ref in catalog and not (has_turns and ref == "transcript_text")
        for line in catalog[ref].splitlines() if line.strip()
    ]


def apply_summary_verification(
    summary: SessionSummaryDraft,
    result: SummaryAssessment,
    catalog: dict[str, str],
) -> VerificationReport:
    """Keep unsafe wording out of the displayed draft, retaining findings for review.

    Literal evidence is an anchor, not a semantic approval. The independent model
    must also support future scope, speaker, action, conditions and agreement.
    """
    report = VerificationReport.model_validate(result.model_dump(include=set(VerificationReport.model_fields)))

    def flag(field: str, reason: str) -> None:
        section = getattr(summary, field)
        report.unsupported_or_risky_claims.append(ReviewableClaim(
            claim=section.text, reason=reason, recommendation="연결된 원문을 확인한 뒤 직접 수정해주세요.",
        ))
        report.requires_counselor_review.append(CounselorReviewField(field=field, reason=reason))
        # Grounding from before a correction must not approve changed wording.
        report.grounded_items = [item for item in report.grounded_items
                                 if not set(item.source_refs) & set(section.source_refs)
                                 and item.claim not in section.text and section.text not in item.claim]
        section.requires_review = True
        section.evidence_type = "needs_review"

    plan = summary.next_plan
    assessment = result.next_plan_assessment
    placeholders = {"", "[자료에서 확인되지 않음]", "[상담사 확인 필요]", "[다음 계획은 원문 확인 필요]"}
    if plan.text.strip() not in placeholders:
        # Only current-session sources can establish a new plan; an old plan cannot.
        supported = assessment.status == "supported_future" and bool(assessment.evidence) and all(
            (item.source_ref.startswith("transcript.turn_") or item.source_ref == "counselor_memo")
            and item.source_ref in catalog
            and bool(_literal(item.quote))
            and any(_literal(item.quote) in line for line in cited_lines([item.source_ref], catalog))
            for item in assessment.evidence
        )
        # Historical definitions supplement, but never replace, current agreement.
        supported = supported and all(
            item.source_ref.startswith("stored_session_note:")
            and item.source_ref in catalog
            and bool(_literal(item.quote))
            and any(_literal(item.quote) in line for line in cited_lines([item.source_ref], catalog))
            for item in assessment.prior_context_evidence
        )
        if supported:
            # The dedicated assessment validates the entire plan against current
            # sources, including consent and conditions. Generic citation pruning
            # cannot veto its exact anchors or turn a supported plan into a blank.
            plan.source_refs = list(dict.fromkeys(item.source_ref for item in
                [*assessment.evidence, *assessment.prior_context_evidence]))
            if assessment.prior_context_evidence:
                plan.evidence_type = "mixed"
        if not supported:
            flag("next_plan", "회기 이후 계획의 시점·조건·합의와 원문 근거를 확인할 수 없습니다.")
            plan.text = ("[자료에서 확인되지 않음]" if assessment.status in {"in_session_only", "not_documented"}
                         else "[다음 계획은 원문 확인 필요]")
            plan.source_refs = []

    for field in SECTION_LIMITS:
        section = getattr(summary, field)
        lines = cited_lines(section.source_refs, catalog)
        invalid = [match.group() for match in QUOTED_TEXT.finditer(section.text)
                   if not any(_literal(match.group()[1:-1]) in line for line in lines)]
        if invalid:
            flag(field, "직접 인용이 연결된 원문과 일치하지 않아 인용 표현을 표시하지 않았습니다.")
            section.text = QUOTED_TEXT.sub(
                lambda match: "[인용 원문 확인 필요]" if match.group() in invalid else match.group(), section.text,
            )
    return report
