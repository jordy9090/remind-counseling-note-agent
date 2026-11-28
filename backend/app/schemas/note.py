"""Schemas for the Re:mind MVP note-generation workflows."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator, model_validator

from app.schemas.grounding import GroundedGenerationResult
from app.schemas.insight import RelationalInsights


EvidenceType = Literal[
    "direct",
    "inferred",
    "counselor_input",
    "previous_context",
    "prior_context_based",
    "needs_review",
    "mixed",
    "model_inference",
]

TargetDocumentType = Literal["session_note", "supervision_report", "termination_report"]


class ReviewedPriorSession(BaseModel):
    """A stored source included in the signed, counselor-reviewed payload."""

    source_ref: str
    session_id: str
    session_number: int
    session_date: str = ""
    summary: str = ""
    confirmed_note: dict[str, Any] = Field(default_factory=dict)


class SessionInput(BaseModel):
    """Raw session materials submitted by a counselor."""

    model_config = ConfigDict(populate_by_name=True)

    case_id: str
    client_alias: str = ""
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
    target_document_type: TargetDocumentType = Field(
        default="session_note",
        validation_alias=AliasChoices("target_document_type", "document_type"),
    )
    persist: bool = False
    insight_lens: Literal["none", "psychodynamic_relational"] = "psychodynamic_relational"
    prior_session_context: list[ReviewedPriorSession] = Field(default_factory=list, max_length=3)
    prior_context_revision: str = ""


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
    client_alias: str = ""
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
    client_alias: str = ""
    session_number: int
    session_date: str
    counselor_name: str = ""


class SummarySection(BaseModel):
    text: str
    evidence_type: EvidenceType
    source_refs: list[str] = Field(default_factory=list)
    requires_review: bool = False


class SessionSummaryDraft(BaseModel):
    @property
    def schema_version(self) -> Literal["v1"]:
        """Legacy responses retain their original shape; storage records the version."""
        return "v1"

    session_info: SessionInfo
    session_theme: SummarySection = Field(description="다음 회기 전에 기억할 구체적 사건·반응을 담은 주제 한 문장. 임상 범주만 남기지 않으며 짧은 핵심 원문 인용은 허용. 발언·제안·의향을 실제 수행이나 동의로 단정하지 않음.")
    presenting_problem: SummarySection = Field(description="이번 회기에 가져온 최근 사건에서 누구와 무슨 일이 있었고 어떤 반응이 이어졌는지 핵심 1문장으로 요약. 원인·진단 추정 금지.")
    session_content: SummarySection = Field(description="사건·탐색·남은 어려움을 3문장, 목표 160~240자로 통합. 화자와 반응의 대상을 정확히 구분하고 다른 항목과 중복 최소화.")
    counselor_intervention: SummarySection = Field(description="상담자가 무엇에 대해 실제로 어떤 질문·반영·제안을 했는지 1~2문장, 목표 90~140자로 요약. 제안·거절·실제 수행을 구분하고 목적·기법·효과를 추정하지 않음.")
    client_response: SummarySection = Field(description="개입에 대한 내담자의 반응과 남은 어려움을 1~2문장, 목표 90~140자로 통합. 발화를 이어 붙이지 않음.")
    reflection: SummarySection = Field(description="상담자가 직접 메모한 자신의 반응과 성찰만 1~2문장, 목표 90~150자로 요약. 내담자의 감정이나 추정을 상담자 감정으로 바꾸지 않음.")
    next_plan: SummarySection = Field(description="회기 이후 또는 다음 회기의 계획을 최대 350자로 요약. 서로 다른 계획이 여러 개면 1~4문장으로 구분. 별도 합의 행동과 다음 회기 일정·확인할 내용을 구분하며 시점·조건·횟수·선택 사항·보류 가능성을 빠뜨리지 않음. 적은 자료는 짧게 쓰되 여러 계획을 60~90자에 억지로 압축하지 않음. 현재 회기의 자세 유지·잠시 기다리기·개입 거절을 다음 계획으로 옮기지 않음. 별도 향후 계획이 없으면 미확인 및 검토 필요로 표시. 나중에 결정할 행동을 확정하거나 입력에 없는 대상·과제를 만들지 않음.")


class SummarySectionGroup(BaseModel):
    """Ordered evidence-linked items with a persistent group-level review flag."""

    items: list[SummarySection] = Field(default_factory=list)
    evidence_type: EvidenceType = "direct"
    source_refs: list[str] = Field(default_factory=list)
    requires_review: bool = False


class SessionSummaryV2(BaseModel):
    schema_version: Literal["v2"] = "v2"
    session_info: SessionInfo
    session_theme: SummarySection = Field(description=SessionSummaryDraft.model_fields["session_theme"].description)
    presenting_concern: SummarySection = Field(description="내담자의 주관적 호소와 원하는 것. 내담자 표현의 짧은 직접 인용 1~2개와 1문장. 사건 서술 금지.")
    episodes: SummarySectionGroup = Field(description="에피소드 1~3개를 items에 담음. 각각 언제·누구와·무슨 일과 그때 내담자 반응, 근거 줄. 원인·상대 의도 추정 금지. 자료가 없으면 빈 목록과 검토 표시.")
    session_content: SummarySection = Field(description="상담실에서 실제로 다룬 흐름 2~3문장. 에피소드 반복 금지.")
    counselor_intervention: SummarySection = Field(description=SessionSummaryDraft.model_fields["counselor_intervention"].description)
    client_reactions: SummarySectionGroup = Field(description="내담자가 실제로 한 말 그대로 3~4개 items. 각 text는 따옴표나 화자 표지를 추가하지 않은 원문의 연속 구절 한 줄, source_refs는 해당 transcript.turn_N 하나. 자료가 적으면 지어내지 않고 검토 표시.")
    client_understanding: SummarySection = Field(description="이런 모습이 있다(근거) → 그때 어떤 감정이었을 수 있다 → 그렇게 반응한 게 이해되는 지점. 정서·관계 패턴의 전체적 이해 2~4문장, 추정 어미. 진단명·단정적 원인 금지. requires_review는 항상 true.")
    reflection: SummarySection = Field(description=SessionSummaryDraft.model_fields["reflection"].description)
    next_plan: SummarySection = Field(description=SessionSummaryDraft.model_fields["next_plan"].description)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def retain_review_boundaries(self) -> "SessionSummaryV2":
        self.client_understanding.requires_review = True
        if len(self.episodes.items) > 3 or len(self.client_reactions.items) > 4:
            raise ValueError("Summary v2 item limits exceeded.")
        return self


def _summary_schema_version(value: Any) -> str:
    return value.get("schema_version", "v1") if isinstance(value, dict) else value.schema_version


SessionSummary = Annotated[
    Annotated[SessionSummaryV2, Tag("v2")] | Annotated[SessionSummaryDraft, Tag("v1")],
    Discriminator(_summary_schema_version),
]


def summary_v2_to_v1(summary: SessionSummary) -> SessionSummaryDraft:
    """Copy into the legacy document contract without losing review metadata."""
    if isinstance(summary, SessionSummaryDraft):
        return summary.model_copy(deep=True)

    def combine(items: list[SummarySection], *, requires_review: bool = False) -> SummarySection:
        return SummarySection(
            text="\n".join(item.text for item in items),
            evidence_type=(items[0].evidence_type if items and len({item.evidence_type for item in items}) == 1
                           else "mixed" if items else "needs_review"),
            source_refs=list(dict.fromkeys(ref for item in items for ref in item.source_refs)),
            requires_review=requires_review or not items or any(item.requires_review for item in items),
        )

    shared = {name: getattr(summary, name).model_copy(deep=True) for name in (
        "session_info", "session_theme", "session_content", "counselor_intervention", "reflection", "next_plan",
    )}
    return SessionSummaryDraft(
        **shared,
        presenting_problem=combine([summary.presenting_concern, *summary.episodes.items[:1]],
                                   requires_review=summary.episodes.requires_review),
        client_response=combine(summary.client_reactions.items, requires_review=summary.client_reactions.requires_review),
    )


def summary_sections(summary: SessionSummary) -> list[tuple[str, SummarySection]]:
    """Return only prose sections, including each ordered v2 item."""
    result = []
    for name, value in summary:
        if isinstance(value, SummarySection):
            result.append((name, value))
        elif isinstance(value, SummarySectionGroup):
            result.extend((f"{name}.items.{index}", item) for index, item in enumerate(value.items))
    return result


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


class GeneratedDocumentDraft(BaseModel):
    """Counselor-facing document assembled from grounded pipeline fields."""

    document_type: TargetDocumentType
    status: Literal["draft_requires_counselor_confirmation"] = "draft_requires_counselor_confirmation"
    sections: dict[str, str] = Field(default_factory=dict)
    source_refs: dict[str, list[str]] = Field(default_factory=dict)
    missing_or_review_fields: list[str] = Field(default_factory=list)
    notice: str = "AI 초안입니다. 상담사가 근거와 임상 판단을 확인해야 합니다."


class RetrievedEvidenceItem(BaseModel):
    id: str | None = None
    source_type: str = ""
    source_ref: str
    source_text: str
    linked_field: str = ""


class RetrievedCaseContextItem(BaseModel):
    source_ref: str
    session_id: str
    session_number: int | None = None
    session_date: str = ""
    summary: str = ""
    confirmed_note: dict[str, Any] = Field(default_factory=dict)
    evidence_items: list[RetrievedEvidenceItem] = Field(default_factory=list)


class RetrievedTemplateContext(BaseModel):
    target_document_type: TargetDocumentType = "session_note"
    required_fields: list[str] = Field(default_factory=list)
    optional_fields: list[str] = Field(default_factory=list)
    counselor_review_fields: list[str] = Field(default_factory=list)
    missing_field_checklist: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class RetrievedPrivacyRule(BaseModel):
    source_ref: str
    title: str
    category: str = "privacy_rule"
    rule: str
    warning: str


class RetrievalReport(BaseModel):
    enabled: bool = False
    case_context_count: int = 0
    template_context_found: bool = False
    privacy_rule_count: int = 0
    embedding_latency_ms: int = 0
    rpc_latency_ms: int = 0
    retrieval_latency_ms: int = 0
    generation_latency_ms: int = 0
    failures: list[str] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)


class PersistenceReport(BaseModel):
    enabled: bool = False
    requested: bool = False
    stored: bool = False
    case_id: str | None = None
    session_id: str | None = None
    note_id: str | None = None
    message: str = ""
    evidence_indexing_attempted: bool = False
    evidence_indexing_succeeded: bool = False
    evidence_indexing_message: str = ""


class ConfirmGeneratedNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_id: str
    confirmed_note: dict[str, Any] = Field(default_factory=dict)
    counselor_edited: bool = True
    create_case_memory: bool = True


class ConfirmGeneratedNoteResponse(BaseModel):
    note_id: str
    confirmation_status: Literal["confirmed", "demo_confirmed"]
    confirmed_at: str
    memory_chunk_count: int = 0
    memory_embedding_count: int = 0
    message: str = ""


class GenerateNoteResponse(BaseModel):
    structured_case_data: StructuredCaseData
    evidence_mapped_data: EvidenceMappedData
    session_summary_draft: SessionSummary
    verification_report: VerificationReport
    document_transform_preview: DocumentTransformPreview
    session_note_draft: GeneratedDocumentDraft | None = None
    termination_report_draft: GeneratedDocumentDraft | None = None
    confirmed_session_note: dict[str, Any] = Field(default_factory=dict)
    sanitized_input: SanitizedInput
    retrieved_case_context: list[RetrievedCaseContextItem] = Field(default_factory=list)
    retrieved_template_context: RetrievedTemplateContext | None = None
    retrieved_privacy_context: list[RetrievedPrivacyRule] = Field(default_factory=list)
    retrieval_report: RetrievalReport = Field(default_factory=RetrievalReport)
    # Additive provenance metadata. None while ENABLE_RAW_REGION_GROUNDING is false.
    grounding: GroundedGenerationResult | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    persistence_report: PersistenceReport = Field(default_factory=PersistenceReport)
    stub: bool = False
    relational_insights: RelationalInsights | None = None


class GeneratedNoteRecord(BaseModel):
    """Owned stored note, including the complete counselor-confirmed payload."""

    @field_validator("draft_json", mode="before")
    @classmethod
    def read_legacy_summary_version(cls, value: Any) -> Any:
        if isinstance(value, dict) and "session_info" in value and "session_theme" in value:
            return {"schema_version": "v1", **value}
        return value

    note_id: str
    case_id: str
    session_id: str
    session_number: int
    session_date: str
    note_type: str
    draft_json: dict[str, Any]
    confirmed_json: dict[str, Any]
    confirmation_status: str
    # Session input stored at generation time: the input as entered (session_input_is_original=True),
    # or, for sessions saved before that was stored, the copy in sessions.sanitized_input_text.
    # None for sessions without a readable stored input.
    session_input: InputSources | None = None
    session_input_is_original: bool = False


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
    final_document_sections: list[dict[str, Any]] = Field(default_factory=list)
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


class SupervisionSessionEvent(BaseModel):
    """A counseling appointment or exception shown in the progress table."""

    session_number: int | None = None
    session_date: str = ""
    duration_minutes: int | None = None
    topic: str = ""
    attendance_status: Literal["completed", "cancelled", "late", "absent", "no_show"] = "completed"
    attendance_reason: str = ""


class PreviousSupervisionEntry(BaseModel):
    supervision_date: str = ""
    feedback: str = ""


class SupervisionReportRequest(BaseModel):
    """Request a personal counseling case supervision report draft."""

    session_input: SessionInput
    session_summary_draft: SessionSummary | None = None
    demo_mode: bool = False
    report_date: str = ""
    client_alias: str = ""
    institution: str = ""
    supervisor: str = ""
    supervision_date_place: str = ""
    maximum_sessions: int | None = Field(default=None, ge=1)
    session_events: list[SupervisionSessionEvent] = Field(default_factory=list)
    previous_supervisions: list[PreviousSupervisionEntry] = Field(default_factory=list)
    agreed_counseling_goal: str = ""
    clinical_counseling_goal: str = ""
    counseling_strategy: str = ""
    supervision_request: str = ""
    transcript_mode: Literal["full", "summary"] = "summary"
    # true면 생성된 보고서를 generated_notes(note_type='supervision_report')에 저장해
    # 문서 목록/대시보드에서 조회할 수 있게 한다. 기본 false — 기존 호출 호환.
    persist: bool = False


class CaseDashboardSession(BaseModel):
    """Per-session row for the case dashboard."""

    session_id: str
    session_number: int
    session_date: str | None = None
    session_title: str = ""
    summary: str | None = None
    transcript_status: str = "none"
    note_confirmation_status: str | None = None


class CaseDashboardDocument(BaseModel):
    """Generated document row for the case dashboard."""

    document_id: str
    document_type: str
    title: str = ""
    status: str = "draft"
    session_number: int | None = None
    created_at: str | None = None


class CaseDashboardExport(BaseModel):
    """One document-export attempt (문서 변환 이력)."""

    export_id: str
    document_type: str
    format: str
    title: str = ""
    status: str = "completed"
    error: str | None = None
    session_number: int | None = None
    created_at: str | None = None


class SavedSummaryEvidence(BaseModel):
    """Bounded de-identified source excerpts; full source containers are excluded."""

    label: str = Field(min_length=1, max_length=60)
    excerpt: str = Field(min_length=1, max_length=2000)
    sourceRef: str = Field(pattern=r"^(transcript\.turn_[1-9]\d*|counselor_memo)$")
    sourceType: Literal["transcript", "counselor_memo"]
    confidence: Literal["high", "medium", "low"] = "low"
    needsReview: bool = True
    truncated: bool = False

    @field_validator("sourceType")
    @classmethod
    def match_source_type(cls, value: str, info) -> str:
        expected = "counselor_memo" if info.data.get("sourceRef") == "counselor_memo" else "transcript"
        if value != expected:
            raise ValueError("Source type must match its reference.")
        return value


class QuickSummarySection(BaseModel):
    """One summary item as shown in the summary screen (주요 호소, 회기 주제, ...)."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=60)
    content: str = Field(default="", max_length=8000)
    evidence: list[SavedSummaryEvidence] = Field(default_factory=list, max_length=40)
    requiresReview: bool = True


class QuickSummarySessionRequest(BaseModel):
    """A quick summary (간편 요약) saved as a client's next session, with every summary item."""

    sections: list[QuickSummarySection] = Field(min_length=1, max_length=20)
    # YYYY-MM-DD; empty means today in Asia/Seoul.
    session_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class QuickSummarySessionResponse(BaseModel):
    case_id: str
    session_id: str
    note_id: str
    session_number: int


class SessionInputDeletionResponse(BaseModel):
    """Result of deleting one session's stored input (회기별 원문 삭제)."""

    note_id: str
    session_id: str
    deleted: list[str]
    kept: list[str]


class ClientProfileFields(BaseModel):
    """내담자 프로필 (cases 테이블의 선택 컬럼). 모두 선택값이며 저장 시 RLS 소유자 범위에서만 읽힌다."""

    client_age: int | None = Field(default=None, ge=0, le=150)
    client_gender: str | None = Field(default=None, max_length=20)
    client_occupation: str | None = Field(default=None, max_length=100)
    marital_status: str | None = Field(default=None, max_length=30)
    family_composition: str | None = Field(default=None, max_length=50)
    # Phone and email are intentionally absent: the profile no longer collects contact details, and
    # unknown fields in a request (including client_phone/client_email) are ignored.
    client_notes: str | None = Field(default=None, max_length=4000)

    @field_validator(
        "client_gender", "client_occupation", "marital_status", "family_composition", "client_notes",
    )
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class CaseCreateRequest(ClientProfileFields):
    """새 내담자(케이스) 생성. case_id를 생략하면 서버가 생성한다."""

    case_id: str | None = Field(default=None, max_length=80)
    case_alias: str = Field(min_length=1, max_length=100)

    @field_validator("case_alias")
    @classmethod
    def _strip_alias(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("이름(가명)을 입력해주세요.")
        return value

    @field_validator("case_id")
    @classmethod
    def _validate_case_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not all(ch.isalnum() or ch in "-_." for ch in value):
            raise ValueError("케이스 ID는 영문·숫자·-_.만 사용할 수 있습니다.")
        return value


class CaseProfileUpdateRequest(ClientProfileFields):
    """내담자 프로필·이름·상태 수정 (설정한 필드만 반영)."""

    case_alias: str | None = Field(default=None, min_length=1, max_length=100)
    status: str | None = Field(default=None, max_length=30)

    @field_validator("case_alias", "status")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("빈 값으로 수정할 수 없습니다.")
        return value


PERSON_LABEL_PATTERN = r"^(?:내담자 A|상담자|인물 (?:[B-Z]|[1-9]\d{1,2}))$"
PERSON_EXPRESSION_MAX_LENGTH = 30


class CasePersonEntry(BaseModel):
    """One person in a client's 인물 사전: a stable label and the expressions that refer to them.

    names are hidden behind the label in later sessions (names, misheard names); relations keep
    their wording and gain the label (베프, 친구).
    """

    label: str = Field(pattern=PERSON_LABEL_PATTERN)
    names: list[str] = Field(default_factory=list, max_length=30)
    relations: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("names", "relations")
    @classmethod
    def _clean_expressions(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > PERSON_EXPRESSION_MAX_LENGTH or "[" in text or "]" in text:
                raise ValueError(f"인물 표현은 {PERSON_EXPRESSION_MAX_LENGTH}자 이하의 일반 문구여야 합니다.")
            if text not in cleaned:
                cleaned.append(text)
        return cleaned


class CasePersonDictionaryUpdate(BaseModel):
    """Replaces a client's whole 인물 사전."""

    people: list[CasePersonEntry] = Field(default_factory=list, max_length=60)

    @field_validator("people")
    @classmethod
    def _distinct_people(cls, people: list[CasePersonEntry]) -> list[CasePersonEntry]:
        labels = [person.label for person in people]
        if len(labels) != len(set(labels)):
            raise ValueError("같은 인물 라벨이 두 번 들어 있습니다.")
        names = [name for person in people for name in person.names]
        if len(names) != len(set(names)):
            raise ValueError("한 이름은 한 인물에만 연결할 수 있습니다.")
        return people


class CasePersonDictionaryResponse(BaseModel):
    case_id: str
    people: list[CasePersonEntry] = Field(default_factory=list)


class CaseDashboardResponse(ClientProfileFields):
    """Aggregated per-case view: profile, sessions, dates, and generated documents."""

    case_id: str
    case_alias: str | None = None
    status: str = "active"
    created_at: str | None = None
    total_session_count: int = 0
    first_consultation_date: str | None = None
    latest_consultation_date: str | None = None
    total_scheduled_session_count: int | None = None
    next_scheduled_date: str | None = None
    presenting_problem: str | None = None
    sessions: list[CaseDashboardSession] = Field(default_factory=list)
    documents: list[CaseDashboardDocument] = Field(default_factory=list)
    exports: list[CaseDashboardExport] = Field(default_factory=list)


class CaseListItem(ClientProfileFields):
    """One owned case with profile summary and aggregate counts for the case list screen."""

    case_id: str
    case_alias: str | None = None
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None
    total_session_count: int = 0
    latest_session_number: int | None = None
    first_consultation_date: str | None = None
    latest_consultation_date: str | None = None
    total_scheduled_session_count: int | None = None
    next_scheduled_date: str | None = None
    transcript_completed_count: int = 0
    confirmed_note_count: int = 0
    draft_note_count: int = 0
    document_count: int = 0
    export_count: int = 0
    temporary_draft_count: int = 0


class RecentDocumentItem(BaseModel):
    """최근 작업한 문서 (generated_notes 기준, 사용자 소유 케이스 전체)."""

    document_id: str
    case_id: str
    case_alias: str | None = None
    document_type: str
    title: str = ""
    status: str = "draft"
    session_number: int | None = None
    updated_at: str | None = None


class CaseListResponse(BaseModel):
    """All cases owned by the authenticated user, most recently active first."""

    cases: list[CaseListItem] = Field(default_factory=list)
    total_count: int = 0
    recent_documents: list[RecentDocumentItem] = Field(default_factory=list)


class CaseScheduleUpdateRequest(BaseModel):
    """Update scheduling metadata on a case (both fields optional)."""

    total_scheduled_session_count: int | None = Field(default=None, ge=0)
    next_scheduled_date: str | None = None

    @field_validator("next_scheduled_date")
    @classmethod
    def _validate_date(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        try:
            date.fromisoformat(value)
        except ValueError as error:
            raise ValueError("next_scheduled_date는 YYYY-MM-DD 형식이어야 합니다.") from error
        return value


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
    label: str | None = None
    guidance: list[str] = Field(default_factory=list)
    evidenceStatus: Literal["direct", "ai_organized", "clinical_review", "missing"] = "ai_organized"
    missingInputs: list[str] = Field(default_factory=list)


class SupervisionReportSection(BaseModel):
    id: str
    title: str
    level: Literal[1, 2, 3]
    contentBlocks: list[SupervisionContentBlock] = Field(default_factory=list)
    status: Literal["complete", "partial", "missing", "needs_review"] = "partial"
    guidance: list[str] = Field(default_factory=list)


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
    title: str = "개인상담(공개상담) 사례 수퍼비전 보고서"
    meta: SupervisionReportMeta
    sections: list[SupervisionReportSection]
    aiReview: SupervisionAiReviewPanel
    evidenceIndex: dict[str, dict[str, str]] = Field(default_factory=dict)
    # persist=true 요청 시 저장 결과(문서 목록 반영 여부)가 담긴다. 기존 응답 호환을 위해 optional.
    persistence: PersistenceReport | None = None
