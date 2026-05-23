"""Schemas for the Re:mind MVP V0 note generation pipeline."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


EvidenceType = Literal[
    "direct",
    "inferred",
    "counselor_input",
    "previous_context",
    "needs_review",
    "mixed",
    "model_inference",
]
SourceType = Literal["transcript", "counselor_memo", "previous_summary", "ai_inference"]
Confidence = Literal["high", "medium", "low"]


class SessionInput(BaseModel):
    """Raw session materials submitted by a counselor."""

    model_config = ConfigDict(populate_by_name=True)

    case_id: str
    session_number: int = Field(validation_alias=AliasChoices("session_number", "session_no"))
    session_date: str = ""
    counselor_name: str = ""
    counselor_memo: str
    transcript_text: str = Field(validation_alias=AliasChoices("transcript_text", "transcript"))
    previous_session_summary: str = Field(
        default="",
        validation_alias=AliasChoices("previous_session_summary", "previous_summary", "prev_summary"),
    )
    counseling_goal: str = ""
    psychological_test_summary: str = ""
    key_issue_tags: list[str] = Field(default_factory=list)
    nonverbal_notes: str = ""


class SensitiveInfoCandidate(BaseModel):
    text: str
    source: str
    category: str
    recommendation: str


class InputSources(BaseModel):
    counselor_memo: str
    transcript_text: str
    previous_session_summary: str = ""
    counseling_goal: str = ""
    psychological_test_summary: str = ""
    key_issue_tags: list[str] = Field(default_factory=list)
    nonverbal_notes: str = ""


class SanitizedInput(BaseModel):
    case_id: str
    session_number: int
    session_date: str
    counselor_name: str
    sources: InputSources
    sensitive_info_candidates: list[SensitiveInfoCandidate] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    content: str
    evidence_type: EvidenceType
    source_refs: list[str] = Field(default_factory=list)


class StructuredCaseData(BaseModel):
    presenting_problem: list[EvidenceItem] = Field(default_factory=list)
    session_theme: list[EvidenceItem] = Field(default_factory=list)
    session_content: list[EvidenceItem] = Field(default_factory=list)
    counselor_interventions: list[EvidenceItem] = Field(default_factory=list)
    client_responses: list[EvidenceItem] = Field(default_factory=list)
    key_client_utterances: list[EvidenceItem] = Field(default_factory=list)
    nonverbal_observations: list[EvidenceItem] = Field(default_factory=list)
    reflection_candidates: list[EvidenceItem] = Field(default_factory=list)
    next_plan: list[EvidenceItem] = Field(default_factory=list)


class EvidenceMappedItem(BaseModel):
    field: str
    content: str
    evidence_type: EvidenceType
    source_refs: list[str] = Field(default_factory=list)
    requires_review: bool = False


class EvidenceMappedData(BaseModel):
    items: list[EvidenceMappedItem] = Field(default_factory=list)


class SessionInfo(BaseModel):
    case_id: str
    session_number: int
    session_date: str
    counselor_name: str = ""


class SummarySection(BaseModel):
    text: str
    evidence_type: EvidenceType
    source_refs: list[str] = Field(default_factory=list)
    requires_review: bool = False


class SessionSummaryDraft(BaseModel):
    session_info: SessionInfo
    session_theme: SummarySection
    presenting_problem: SummarySection
    session_content: SummarySection
    counselor_intervention: SummarySection
    client_response: SummarySection
    reflection: SummarySection
    next_plan: SummarySection


class GroundedItem(BaseModel):
    claim: str
    source_refs: list[str] = Field(default_factory=list)


class ReviewableClaim(BaseModel):
    claim: str
    reason: str
    recommendation: str


class CounselorReviewField(BaseModel):
    field: str
    reason: str


class VerificationReport(BaseModel):
    grounded_items: list[GroundedItem] = Field(default_factory=list)
    weakly_grounded_items: list[ReviewableClaim] = Field(default_factory=list)
    unsupported_or_risky_claims: list[ReviewableClaim] = Field(default_factory=list)
    sensitive_info_items: list[SensitiveInfoCandidate] = Field(default_factory=list)
    requires_counselor_review: list[CounselorReviewField] = Field(default_factory=list)


class DocumentTransformPreview(BaseModel):
    document_type: str = "preview"
    available_transforms: list[str] = Field(default_factory=list)
    preview_sections: dict[str, str] = Field(default_factory=dict)
    partially_available_fields: dict[str, str] = Field(default_factory=dict)
    missing_required_fields: list[str] = Field(default_factory=list)
    notice: str


class GenerateNoteResponse(BaseModel):
    structured_case_data: StructuredCaseData
    evidence_mapped_data: EvidenceMappedData
    session_summary_draft: SessionSummaryDraft
    verification_report: VerificationReport
    document_transform_preview: DocumentTransformPreview
    confirmed_session_note: dict[str, Any] = Field(default_factory=dict)
    sanitized_input: SanitizedInput
    stub: bool = False


class EvidenceCheckItem(BaseModel):
    claim: str
    source_type: SourceType
    source_excerpt: str
    confidence: Confidence


class NoteDraftResponse(BaseModel):
    case_id: str
    session_number: int
    session_summary: str
    main_issue: str
    counselor_intervention: str
    client_response: str
    next_plan: str
    evidence_check: list[EvidenceCheckItem] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
