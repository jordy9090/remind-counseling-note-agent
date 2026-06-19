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


class TemporaryDraftSaveRequest(BaseModel):
    """Frontend workspace state saved by the counselor before final confirmation."""

    draft_id: str | None = None
    case_id: str
    session_number: int
    session_date: str = ""
    counselor_name: str = ""
    screen: str = "session_input"
    form: dict[str, Any] = Field(default_factory=dict)
    session_topic: str = ""
    is_deidentified: bool = True
    selected_previous_session_ids: list[str] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    visible_section_ids: list[str] = Field(default_factory=list)
    draft_sections: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    final_document_type: str = "session_note"
    supervision_report_draft: dict[str, Any] | None = None


class TemporaryDraftRecord(TemporaryDraftSaveRequest):
    saved_at: str


class TemporaryDraftSaveResponse(BaseModel):
    draft_id: str
    case_id: str
    session_number: int
    saved_at: str
    message: str = "임시저장되었습니다."


class RecomposeNoteRequest(BaseModel):
    """Request a regenerated AI draft for a specific checklist configuration."""

    session_input: SessionInput
    session_topic: str = ""
    visible_section_ids: list[str] = Field(default_factory=list)


class RecomposeNoteResponse(BaseModel):
    result: GenerateNoteResponse
    visible_section_ids: list[str] = Field(default_factory=list)
    cache_key: str
    cache_hit: bool = False


class SupervisionReportRequest(BaseModel):
    """Request a personal counseling case supervision report draft."""

    session_input: SessionInput
    session_summary_draft: SessionSummaryDraft | None = None
    demo_mode: bool = False
    report_date: str = ""
    client_alias: str = ""
    institution: str = ""
    supervisor: str = ""
    supervision_date_place: str = ""


class SupervisionSpeakerTurn(BaseModel):
    turnId: str
    speaker: Literal["client", "counselor"]
    text: str
    silenceSeconds: int | None = None


class SupervisionContentBlock(BaseModel):
    id: str
    type: Literal["paragraph", "table", "transcript", "reflection_box", "placeholder"]
    text: str | None = None
    rows: list[dict[str, str]] | None = None
    speakerTurns: list[SupervisionSpeakerTurn] | None = None
    evidenceIds: list[str] = Field(default_factory=list)
    aiGenerated: bool = True
    demoValue: bool = False
    reviewStatus: Literal["unchecked", "confirmed", "edited", "needs_human_input"] = "unchecked"
    warnings: list[str] = Field(default_factory=list)


class SupervisionReportSection(BaseModel):
    id: str
    title: str
    level: Literal[1, 2, 3]
    contentBlocks: list[SupervisionContentBlock] = Field(default_factory=list)
    status: Literal["complete", "partial", "missing", "needs_review"] = "partial"


class SupervisionCompletionChecklistItem(BaseModel):
    label: str
    status: Literal["done", "partial", "missing"]
    reason: str | None = None


class SupervisionNeedsHumanReviewItem(BaseModel):
    sectionId: str
    message: str
    severity: Literal["low", "medium", "high"] = "medium"


class SupervisionUnsupportedClaim(BaseModel):
    blockId: str
    claim: str
    reason: str


class SupervisionAiReviewPanel(BaseModel):
    completionChecklist: list[SupervisionCompletionChecklistItem] = Field(default_factory=list)
    missingFields: list[str] = Field(default_factory=list)
    demoInputs: list[str] = Field(default_factory=list)
    needsHumanReview: list[SupervisionNeedsHumanReviewItem] = Field(default_factory=list)
    unsupportedClaims: list[SupervisionUnsupportedClaim] = Field(default_factory=list)
    suggestedSupervisionQuestions: list[str] = Field(default_factory=list)
    caution: str = (
        "AI 초안은 상담사의 검토 전 최종 수퍼비전 자료로 사용되지 않습니다. "
        "사례개념화, 위험 판단, 심리검사 해석, 상담목표 확정은 상담사가 확인해야 합니다."
    )


class SupervisionReportMeta(BaseModel):
    clientAlias: str
    sessionNumber: int
    reportDate: str
    counselorName: str | None = None
    institution: str | None = None
    supervisor: str | None = None
    supervisionDatePlace: str | None = None


class SupervisionReportDraft(BaseModel):
    reportId: str
    caseId: str
    reportType: Literal["personal_counseling_supervision"] = "personal_counseling_supervision"
    title: str = "개인상담 사례 수퍼비전 보고서 초안"
    meta: SupervisionReportMeta
    sections: list[SupervisionReportSection]
    aiReview: SupervisionAiReviewPanel
    evidenceIndex: dict[str, dict[str, str]] = Field(default_factory=dict)
