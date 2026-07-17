"""Node functions for the Re:mind V1 retrieval-aware pipeline."""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import settings
from app.schemas.note import (
    CounselorReviewField,
    DocumentTransformPreview,
    EvidenceItem,
    EvidenceMappedData,
    EvidenceMappedItem,
    GroundedItem,
    InputSources,
    RetrievedCaseContextItem,
    RetrievedPrivacyRule,
    RetrievedTemplateContext,
    RetrievalReport,
    ReviewableClaim,
    SanitizedInput,
    SensitiveInfoCandidate,
    SessionInfo,
    SessionInput,
    SessionSummaryDraft,
    StructuredCaseData,
    SummarySection,
    VerificationReport,
)
from app.services.llm import get_structured_llm
from app.services.retrieval import (
    chunks_to_case_context,
    chunks_to_privacy_rules,
    chunks_to_template_context,
    retrieval_query_from_input,
    retrieve_authoritative_kb_chunks,
    retrieve_case_context,
    retrieve_case_memory_chunks,
    retrieve_document_template,
    retrieve_privacy_rules,
)


PHONE_RE = re.compile(r"(?:010[-.\s]?\d{4}[-.\s]?\d{4}|\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4})")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
SCHOOL_RE = re.compile(r"[가-힣A-Za-z0-9]+(?:초등학교|중학교|고등학교|대학교|대학|학교)")
NAME_HINT_RE = re.compile(r"\b[가-힣]{2,4}(?:님|씨)\b")
NONVERBAL_RE = re.compile(
    r"(눈물|침묵|목소리\s*떨림|목소리[^.?!\n]{0,12}떨|한숨|말(?:의\s*속도)?가\s*느려지|말[^.?!\n]{0,12}느려지|울먹임)"
)
NEXT_PLAN_RE = re.compile(r"(다음\s*회기|추후|다음에는|검토하기로|보기로|계획)")


def sanitize_input(state: dict[str, Any]) -> dict[str, Any]:
    """Detect sensitive candidates and normalize input sources."""
    session_input: SessionInput = state["session_input"]
    sanitized = SanitizedInput(
        case_id=session_input.case_id,
        session_number=session_input.session_number,
        session_date=session_input.session_date,
        counselor_name=session_input.counselor_name,
        sources=InputSources(
            counselor_memo=session_input.counselor_memo.strip(),
            transcript_text=session_input.transcript_text.strip(),
            previous_session_summary=session_input.previous_session_summary.strip(),
            counseling_goal=session_input.counseling_goal.strip(),
            psychological_test_summary=session_input.psychological_test_summary.strip(),
            key_issue_tags=session_input.key_issue_tags,
            nonverbal_notes=session_input.nonverbal_notes.strip(),
        ),
        sensitive_info_candidates=_detect_sensitive_info(session_input),
    )
    return {"sanitized_input": sanitized, "stub": settings.stub_mode}


def retrieve_context(state: dict[str, Any]) -> dict[str, Any]:
    """Collect optional case-memory, template, and privacy context for downstream nodes."""
    sanitized: SanitizedInput = state["sanitized_input"]
    session_input: SessionInput = state["session_input"]
    report = RetrievalReport(enabled=settings.enable_rag)
    if not settings.enable_rag:
        report.notices.append("ENABLE_RAG is false; retrieval skipped.")
        return _empty_retrieval_state(report)
    if not settings.supabase_configured:
        report.notices.append("Supabase credentials are missing; retrieval continued with empty context.")

    case_context: list[RetrievedCaseContextItem] = []
    template_context: RetrievedTemplateContext | None = None
    privacy_context: list[RetrievedPrivacyRule] = []

    try:
        case_context = retrieve_case_context(sanitized.case_id, max_sessions=3)
    except Exception as error:
        report.failures.append(f"case_context: {error}")

    try:
        template_context = retrieve_document_template(session_input.target_document_type)
    except Exception as error:
        report.failures.append(f"document_template: {error}")

    try:
        privacy_context = retrieve_privacy_rules()
    except Exception as error:
        report.failures.append(f"privacy_rules: {error}")

    report.case_context_count = len(case_context)
    report.template_context_found = bool(
        template_context
        and (
            template_context.required_fields
            or template_context.optional_fields
            or template_context.counselor_review_fields
            or template_context.source_refs
        )
    )
    report.privacy_rule_count = len(privacy_context)
    if not case_context:
        report.notices.append("No prior case-memory context was retrieved.")
    if template_context is None or not report.template_context_found:
        report.notices.append("No document-template KB context was retrieved.")
    if not privacy_context:
        report.notices.append("No privacy or ethics KB context was retrieved.")

    return {
        "retrieved_case_context": case_context,
        "retrieved_template_context": template_context,
        "retrieved_privacy_context": privacy_context,
        "retrieval_report": report,
    }


def formulate_retrieval_query(state: dict[str, Any]) -> dict[str, Any]:
    """Build one retrieval query from sanitized session materials."""
    sanitized: SanitizedInput = state["sanitized_input"]
    session_input: SessionInput = state["session_input"]
    report = RetrievalReport(enabled=settings.enable_rag)
    if not settings.enable_rag:
        report.notices.append("ENABLE_RAG is false; retrieval skipped.")
    elif not settings.supabase_configured:
        report.notices.append("Supabase credentials are missing; retrieval continued with empty context.")
    if settings.enable_rag and not settings.enable_dense_retrieval:
        report.notices.append("ENABLE_DENSE_RETRIEVAL is false; using lightweight retrieval only.")
    return {
        "retrieval_query": retrieval_query_from_input(session_input.target_document_type, sanitized.sources),
        "retrieval_report": report,
    }


def retrieve_case_memory(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve prior-session context without crossing counselor/case boundaries."""
    sanitized: SanitizedInput = state["sanitized_input"]
    session_input: SessionInput = state["session_input"]
    report: RetrievalReport = state.get("retrieval_report") or RetrievalReport(enabled=settings.enable_rag)
    query_text = state.get("retrieval_query") or ""
    case_context: list[RetrievedCaseContextItem] = []
    chunks: list[Any] = []

    if not settings.enable_rag:
        return {"retrieved_case_context": case_context, "retrieved_case_memory_chunks": chunks, "retrieval_report": report}

    try:
        counselor_id = session_input.counselor_name.strip()
        if settings.enable_dense_retrieval and counselor_id:
            chunks = retrieve_case_memory_chunks(
                query_text=query_text,
                counselor_id=counselor_id,
                case_id=sanitized.case_id,
                max_chunks=5,
            )
            case_context = chunks_to_case_context(chunks)
        elif settings.enable_dense_retrieval:
            report.notices.append("Dense case-memory retrieval skipped because counselor_id is missing.")

        if not case_context:
            case_context = retrieve_case_context(sanitized.case_id, max_sessions=3)
    except Exception as error:
        report.failures.append(f"case_memory: {error}")

    return {
        "retrieved_case_context": case_context,
        "retrieved_case_memory_chunks": chunks,
        "retrieval_report": report,
    }


def retrieve_authoritative_kb(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve template KB and warning-only ethics/privacy/security KB."""
    session_input: SessionInput = state["session_input"]
    report: RetrievalReport = state.get("retrieval_report") or RetrievalReport(enabled=settings.enable_rag)
    query_text = state.get("retrieval_query") or ""
    template_context: RetrievedTemplateContext | None = None
    privacy_context: list[RetrievedPrivacyRule] = []
    chunks: list[Any] = []

    if not settings.enable_rag:
        return {
            "retrieved_template_context": template_context,
            "retrieved_privacy_context": privacy_context,
            "retrieved_authoritative_kb_chunks": chunks,
            "retrieval_report": report,
        }

    try:
        fallback_template = retrieve_document_template(session_input.target_document_type)
    except Exception as error:
        report.failures.append(f"document_template: {error}")
        fallback_template = None

    try:
        fallback_privacy = retrieve_privacy_rules()
    except Exception as error:
        report.failures.append(f"privacy_rules: {error}")
        fallback_privacy = []

    try:
        if settings.enable_dense_retrieval:
            chunks = retrieve_authoritative_kb_chunks(
                query_text=query_text,
                target_document_type=session_input.target_document_type,
                include_warning_rules=True,
                max_chunks=8,
            )
    except Exception as error:
        report.failures.append(f"authoritative_kb: {error}")

    template_context = chunks_to_template_context(
        session_input.target_document_type,
        chunks,
        fallback=fallback_template,
    )
    privacy_context = chunks_to_privacy_rules(chunks, fallback=fallback_privacy)

    return {
        "retrieved_template_context": template_context,
        "retrieved_privacy_context": privacy_context,
        "retrieved_authoritative_kb_chunks": chunks,
        "retrieval_report": report,
    }


def fuse_and_rerank(state: dict[str, Any]) -> dict[str, Any]:
    """Finalize retrieval report while preserving the existing API fields."""
    report: RetrievalReport = state.get("retrieval_report") or RetrievalReport(enabled=settings.enable_rag)
    case_context: list[RetrievedCaseContextItem] = state.get("retrieved_case_context") or []
    template_context: RetrievedTemplateContext | None = state.get("retrieved_template_context")
    privacy_context: list[RetrievedPrivacyRule] = state.get("retrieved_privacy_context") or []

    report.case_context_count = len(case_context)
    report.template_context_found = bool(
        template_context
        and (
            template_context.required_fields
            or template_context.optional_fields
            or template_context.counselor_review_fields
            or template_context.source_refs
        )
    )
    report.privacy_rule_count = len(privacy_context)
    if settings.enable_rag:
        if not case_context:
            report.notices.append("No prior case-memory context was retrieved.")
        if template_context is None or not report.template_context_found:
            report.notices.append("No document-template KB context was retrieved.")
        if not privacy_context:
            report.notices.append("No privacy or ethics KB context was retrieved.")
    return {"retrieval_report": report}


def structure_session(state: dict[str, Any]) -> dict[str, Any]:
    """Convert sanitized materials into counseling documentation fields."""
    sanitized: SanitizedInput = state["sanitized_input"]
    case_context: list[RetrievedCaseContextItem] = state.get("retrieved_case_context") or []
    template_context: RetrievedTemplateContext | None = state.get("retrieved_template_context")
    fallback = _mock_structured_case(sanitized, case_context)
    if settings.stub_mode:
        return {"structured_case_data": fallback}

    prompt = _build_structure_prompt(sanitized, case_context, template_context)
    structured = get_structured_llm(StructuredCaseData).invoke(prompt)
    return {"structured_case_data": structured}


def map_evidence(state: dict[str, Any]) -> dict[str, Any]:
    """Flatten structured items and mark review-sensitive evidence types."""
    structured: StructuredCaseData = state["structured_case_data"]
    mapped_items: list[EvidenceMappedItem] = []

    for field_name, items in structured.model_dump().items():
        for item in items:
            evidence_type = item["evidence_type"]
            mapped_items.append(
                EvidenceMappedItem(
                    field=field_name,
                    content=item["content"],
                    evidence_type=evidence_type,
                    source_refs=item["source_refs"],
                    requires_review=evidence_type
                    in {"inferred", "model_inference", "needs_review", "counselor_input", "prior_context_based"},
                )
            )

    return {"evidence_mapped_data": EvidenceMappedData(items=mapped_items)}


def generate_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Generate an editable session summary draft."""
    sanitized: SanitizedInput = state["sanitized_input"]
    structured: StructuredCaseData = state["structured_case_data"]
    evidence_mapped: EvidenceMappedData = state["evidence_mapped_data"]
    requested_section_ids: list[str] = state.get("requested_section_ids") or []
    session_topic: str = state.get("session_topic") or ""
    case_context: list[RetrievedCaseContextItem] = state.get("retrieved_case_context") or []
    template_context: RetrievedTemplateContext | None = state.get("retrieved_template_context")
    fallback = _mock_summary(sanitized, structured)
    if settings.stub_mode:
        return {"session_summary_draft": fallback}

    prompt = _build_summary_prompt(
        sanitized,
        structured,
        evidence_mapped,
        requested_section_ids,
        session_topic,
        case_context,
        template_context,
    )
    summary = get_structured_llm(SessionSummaryDraft).invoke(prompt)
    return {"session_summary_draft": summary}


def verify_output(state: dict[str, Any]) -> dict[str, Any]:
    """Verify support, sensitivity, and counselor-review boundaries."""
    sanitized: SanitizedInput = state["sanitized_input"]
    structured: StructuredCaseData = state["structured_case_data"]
    evidence_mapped: EvidenceMappedData = state["evidence_mapped_data"]
    summary: SessionSummaryDraft = state["session_summary_draft"]
    privacy_context: list[RetrievedPrivacyRule] = state.get("retrieved_privacy_context") or []
    fallback = _mock_verification(sanitized, evidence_mapped, privacy_context)
    if settings.stub_mode:
        return {"verification_report": fallback}

    prompt = _build_verification_prompt(sanitized, structured, evidence_mapped, summary, privacy_context)
    verification = get_structured_llm(VerificationReport).invoke(prompt)
    return {"verification_report": verification}


def transform_document_preview(state: dict[str, Any]) -> dict[str, Any]:
    """Preview later document transformations from a confirmed session note."""
    sanitized: SanitizedInput = state["sanitized_input"]
    summary: SessionSummaryDraft = state["session_summary_draft"]
    template_context: RetrievedTemplateContext | None = state.get("retrieved_template_context")
    preview_sections = {
        "session_summary": summary.session_content.text,
        "client_main_issue": summary.presenting_problem.text,
        "next_plan": summary.next_plan.text,
    }
    partially_available_fields: dict[str, str] = {}
    missing_required_fields = [
        "내담자 기본 정보",
        "상담신청경위",
        "이전 상담 경험",
        "가족관계",
        "사례개념화 및 상담방향성",
        "슈퍼비전 요청사항",
    ]

    if sanitized.sources.psychological_test_summary:
        preview_sections["psychological_test_summary"] = sanitized.sources.psychological_test_summary
        partially_available_fields["심리검사 결과"] = (
            "입력 요약은 있으나 검사명, 실시일, 세부 척도, 상담적 해석은 상담사 확인 필요"
        )
    else:
        missing_required_fields.append("심리검사 결과")

    if template_context:
        missing_required_fields = _unique_strings(
            missing_required_fields + template_context.missing_field_checklist
        )
        for field in template_context.counselor_review_fields:
            partially_available_fields.setdefault(field, "문서 양식 KB 기준으로 상담사 직접 확인이 필요한 항목")

    preview = DocumentTransformPreview(
        document_type="preview",
        available_transforms=["supervision_report", "termination_report"],
        preview_sections=preview_sections,
        partially_available_fields=partially_available_fields,
        missing_required_fields=missing_required_fields,
        notice="현재 MVP에서는 확정된 회기요약을 기반으로 일부 항목만 미리보기합니다.",
    )
    return {"document_transform_preview": preview}


def _empty_retrieval_state(report: RetrievalReport) -> dict[str, Any]:
    return {
        "retrieved_case_context": [],
        "retrieved_template_context": None,
        "retrieved_privacy_context": [],
        "retrieval_report": report,
    }


def _detect_sensitive_info(session_input: SessionInput) -> list[SensitiveInfoCandidate]:
    sources = {
        "counselor_memo": session_input.counselor_memo,
        "transcript_text": session_input.transcript_text,
        "previous_session_summary": session_input.previous_session_summary,
        "psychological_test_summary": session_input.psychological_test_summary,
        "nonverbal_notes": session_input.nonverbal_notes,
    }
    candidates: list[SensitiveInfoCandidate] = []

    patterns = [
        ("phone", PHONE_RE, "전화번호 후보"),
        ("email", EMAIL_RE, "이메일 후보"),
        ("school", SCHOOL_RE, "학교명 후보"),
        ("name_hint", NAME_HINT_RE, "실명 후보"),
    ]
    for source, text in sources.items():
        for category, pattern, label in patterns:
            for match in pattern.finditer(text or ""):
                candidates.append(
                    SensitiveInfoCandidate(
                        text=match.group(0),
                        source=source,
                        category=category,
                        recommendation=f"{label}입니다. 가명 또는 케이스 ID로 대체하세요.",
                    )
                )
    return candidates


def _mock_structured_case(
    sanitized: SanitizedInput,
    case_context: list[RetrievedCaseContextItem] | None = None,
) -> StructuredCaseData:
    tags = ", ".join(sanitized.sources.key_issue_tags) or "진로 불안과 자기비난 사고"
    transcript_ref = "transcript_text"
    memo_ref = "counselor_memo"
    prev_ref = "previous_session_summary"
    case_context = case_context or []
    session_content_refs = [memo_ref, transcript_ref, prev_ref]
    if case_context:
        session_content_refs.append(case_context[0].source_ref)

    return StructuredCaseData(
        presenting_problem=[
            EvidenceItem(
                content="내담자는 진로 불확실성과 취업 준비 과정에서의 불안을 호소함.",
                evidence_type="direct",
                source_refs=[transcript_ref, memo_ref],
            )
        ],
        session_theme=[
            EvidenceItem(
                content=f"주요 회기 주제: {tags}",
                evidence_type="direct",
                source_refs=[memo_ref],
            )
        ],
        session_content=[
            EvidenceItem(
                content=_build_session_content_summary(sanitized),
                evidence_type="mixed",
                source_refs=session_content_refs,
            )
        ],
        counselor_interventions=[
            EvidenceItem(
                content="상담자는 내담자의 표현을 구체화하고, 불안과 자기비난 사고를 탐색하도록 질문함.",
                evidence_type="direct",
                source_refs=[memo_ref, transcript_ref],
            )
        ],
        client_responses=[
            EvidenceItem(
                content="내담자는 진로 불확실성과 관련된 불안을 언어화하고 자신의 사고 흐름을 점검함.",
                evidence_type="inferred",
                source_refs=[transcript_ref],
            )
        ],
        key_client_utterances=[
            EvidenceItem(
                content=_extract_client_utterance(sanitized.sources.transcript_text),
                evidence_type="direct",
                source_refs=[transcript_ref],
            )
        ],
        nonverbal_observations=_extract_nonverbal_observations(sanitized),
        reflection_candidates=[
            EvidenceItem(
                content="상담자 reflection은 상담사가 직접 작성하거나 확인해야 함.",
                evidence_type="needs_review",
                source_refs=[],
            )
        ],
        next_plan=[
            _extract_next_plan(sanitized)
        ],
    )


def _mock_summary(sanitized: SanitizedInput, structured: StructuredCaseData) -> SessionSummaryDraft:
    return SessionSummaryDraft(
        session_info=SessionInfo(
            case_id=sanitized.case_id,
            session_number=sanitized.session_number,
            session_date=sanitized.session_date,
            counselor_name=sanitized.counselor_name,
        ),
        session_theme=_section_from_first(structured.session_theme, "회기 주제 확인 필요"),
        presenting_problem=_section_from_first(structured.presenting_problem, "주호소 확인 필요"),
        session_content=_section_from_first(structured.session_content, "상담 내용 확인 필요"),
        counselor_intervention=_section_from_first(
            structured.counselor_interventions,
            "상담자 개입 확인 필요",
        ),
        client_response=_section_from_first(
            structured.client_responses,
            "내담자 반응은 상담사가 확인해야 함",
        ),
        reflection=SummarySection(
            text="상담자 reflection은 상담사가 직접 작성하거나 확인해야 합니다.",
            evidence_type="counselor_input",
            source_refs=[],
            requires_review=True,
        ),
        next_plan=_section_from_first(structured.next_plan, "추후 계획 확인 필요"),
    )


def _mock_verification(
    sanitized: SanitizedInput,
    evidence_mapped: EvidenceMappedData,
    privacy_context: list[RetrievedPrivacyRule] | None = None,
) -> VerificationReport:
    grounded = [
        GroundedItem(claim=item.content, source_refs=item.source_refs)
        for item in evidence_mapped.items
        if item.evidence_type == "direct"
    ]
    weak = [
        ReviewableClaim(
            claim=item.content,
            reason="입력 근거는 있으나 일부 해석 또는 요약이 포함되어 상담사 확인이 필요함.",
            recommendation="상담사가 유지, 수정, 삭제 여부를 판단",
        )
        for item in evidence_mapped.items
        if item.evidence_type in {"mixed", "inferred", "prior_context_based"}
    ][:5]
    privacy_context = privacy_context or []
    counselor_review_fields = [
        CounselorReviewField(field="reflection", reason="상담자 내적 경험과 임상적 판단 영역"),
        CounselorReviewField(field="case_conceptualization", reason="현재 MVP 자동 생성 대상이 아님"),
        CounselorReviewField(field="goal_attainment", reason="목표 달성 정도는 상담사 확인 필요"),
    ]
    if sanitized.sources.psychological_test_summary:
        counselor_review_fields.append(
            CounselorReviewField(
                field="psychological_test_summary",
                reason="입력 요약은 있으나 검사명, 실시일, 세부 척도, 상담적 해석 확인 필요",
            )
        )
    return VerificationReport(
        grounded_items=grounded,
        weakly_grounded_items=weak,
        unsupported_or_risky_claims=[
            ReviewableClaim(
                claim="사례개념화, 위험 판단, 목표 달성 정도를 자동으로 확정하지 않음.",
                reason="현재 MVP의 자동 생성 대상이 아니며 상담사 임상 판단 영역임.",
                recommendation="상담사가 직접 작성하거나 별도 확인 필드로 분리",
            )
        ]
        + [
            ReviewableClaim(
                claim=rule.warning,
                reason=f"개인정보/윤리 KB 검토 항목: {rule.title}",
                recommendation="저장, 공유, export 전에 상담사가 동의와 비식별화 필요 여부를 확인",
            )
            for rule in privacy_context[:3]
        ],
        sensitive_info_items=sanitized.sensitive_info_candidates,
        requires_counselor_review=counselor_review_fields,
    )


def _build_session_content_summary(sanitized: SanitizedInput) -> str:
    transcript = sanitized.sources.transcript_text
    if "뒤처" in transcript or "잘못 선택" in transcript:
        return (
            "이번 회기에서는 취업 준비 과정에서 나타나는 진로 불안과 자기비난 사고를 다루었다. "
            "내담자는 주변 친구들의 진로 진행 상황과 자신을 비교하며 뒤처졌다는 느낌을 표현했고, "
            "선택을 잘못하면 끝이라는 생각이 불안을 키우는 흐름을 보고하였다."
        )

    tags = ", ".join(sanitized.sources.key_issue_tags) or "주요 상담 이슈"
    return (
        f"이번 회기에서는 다음 주제를 다루었다: {tags}. "
        "내담자는 회기에서 확인된 불안과 반복되는 사고 흐름을 표현했고, "
        "상담자는 이를 구체화하며 다음 회기에서 이어갈 계획을 정리하였다."
    )


def _extract_nonverbal_observations(sanitized: SanitizedInput) -> list[EvidenceItem]:
    observations: list[EvidenceItem] = []
    seen: set[tuple[str, str]] = set()
    sources = [
        ("counselor_memo", sanitized.sources.counselor_memo),
        ("nonverbal_notes", sanitized.sources.nonverbal_notes),
    ]

    for source_ref, text in sources:
        for sentence in _sentences(text):
            if not NONVERBAL_RE.search(sentence):
                continue
            key = (source_ref, sentence)
            if key in seen:
                continue
            seen.add(key)
            observations.append(
                EvidenceItem(
                    content=_ensure_sentence(sentence),
                    evidence_type="direct",
                    source_refs=[source_ref],
                )
            )

    if observations:
        return observations

    return [
        EvidenceItem(
            content="비언어/반언어 정보는 입력되지 않음.",
            evidence_type="needs_review",
            source_refs=[],
        )
    ]


def _extract_next_plan(sanitized: SanitizedInput) -> EvidenceItem:
    for sentence in _sentences(sanitized.sources.counselor_memo):
        if NEXT_PLAN_RE.search(sentence):
            return EvidenceItem(
                content=_ensure_sentence(sentence),
                evidence_type="direct",
                source_refs=["counselor_memo"],
            )

    return EvidenceItem(
        content="다음 회기에서는 자동사고 기록과 구체적인 행동 계획을 검토함.",
        evidence_type="inferred",
        source_refs=["counselor_memo"],
    )


def _section_from_first(items: list[EvidenceItem], fallback: str) -> SummarySection:
    if not items:
        return SummarySection(text=fallback, evidence_type="needs_review", source_refs=[], requires_review=True)
    item = items[0]
    return SummarySection(
        text=item.content,
        evidence_type=item.evidence_type,
        source_refs=item.source_refs,
        requires_review=item.evidence_type
        in {"inferred", "model_inference", "needs_review", "counselor_input", "prior_context_based"},
    )


def _extract_client_utterance(transcript_text: str) -> str:
    for line in transcript_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("Cl:", "내담자:", "Client:")):
            return stripped
    return "중요한 내담자 발화는 축어록에서 상담사가 확인해야 함."


def _sentences(text: str) -> list[str]:
    normalized = " ".join((text or "").split())
    if not normalized:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]


def _ensure_sentence(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if stripped.endswith((".", "!", "?")):
        return stripped
    return f"{stripped}."


def _json(data: Any) -> str:
    if hasattr(data, "model_dump"):
        data = data.model_dump()
    elif isinstance(data, list):
        data = [item.model_dump() if hasattr(item, "model_dump") else item for item in data]
    elif isinstance(data, dict):
        data = {
            key: value.model_dump() if hasattr(value, "model_dump") else value
            for key, value in data.items()
        }
    return json.dumps(data, ensure_ascii=False, indent=2)


def _build_structure_prompt(
    sanitized: SanitizedInput,
    case_context: list[RetrievedCaseContextItem],
    template_context: RetrievedTemplateContext | None,
) -> str:
    return f"""
You are generating structured counseling documentation data for Re:mind V1.
Return only fields allowed by the Pydantic schema.
Do not diagnose, evaluate risk, or replace counselor judgment.
If a claim is not directly grounded, mark it as inferred or needs_review.
Re:mind is not a diagnosis tool, treatment recommendation tool, or counselor evaluation tool.

Retrieved prior-session context is background only. Use it only when it is relevant to the current session.
Every claim must cite current input source_refs or retrieved prior-session source_refs.
If a claim depends on prior sessions, set evidence_type to prior_context_based and include the stored source_ref.
If support is weak, set needs_review or another review-sensitive evidence type.

Document template context can be used only to identify missing fields and counselor-review fields.

Sanitized input:
{_json(sanitized)}

Retrieved case context:
{_json(case_context)}

Retrieved document template context:
{_json(template_context)}
"""


def _build_summary_prompt(
    sanitized: SanitizedInput,
    structured: StructuredCaseData,
    evidence_mapped: EvidenceMappedData,
    requested_section_ids: list[str] | None = None,
    session_topic: str = "",
    case_context: list[RetrievedCaseContextItem] | None = None,
    template_context: RetrievedTemplateContext | None = None,
) -> str:
    requested_section_ids = requested_section_ids or []
    case_context = case_context or []
    return f"""
Generate an editable Korean counseling session summary draft.
Each section must include evidence_type and source_refs.
Reflection, case conceptualization, and goal attainment must remain counselor-review areas.
Do not generate diagnosis, clinical risk scoring, treatment recommendation, psychological test interpretation,
or counselor performance evaluation.
Retrieved prior sessions may be used only as traceable background context.
If a section uses prior-session context, set evidence_type to prior_context_based or mixed and include
stored_session_note:<session_id> or stored_evidence:<id> in source_refs.
Do not treat privacy/ethics/template rules as clinical evidence.
The frontend will display only these requested section ids:
{_json(requested_section_ids)}
If requested_section_ids is not empty, rewrite the requested sections as a coherent self-contained draft
for that exact checklist configuration. Avoid relying on omitted sections for essential context.
For non-requested sections, keep them brief and grounded because they may be hidden by the frontend.
Counselor-selected session topic, if provided: {session_topic or "not provided"}

Sanitized input:
{_json(sanitized)}

Structured case data:
{_json(structured)}

Evidence mapped data:
{_json(evidence_mapped)}

Retrieved case context:
{_json(case_context)}

Retrieved document template context:
{_json(template_context)}
"""


def _build_verification_prompt(
    sanitized: SanitizedInput,
    structured: StructuredCaseData,
    evidence_mapped: EvidenceMappedData,
    summary: SessionSummaryDraft,
    privacy_context: list[RetrievedPrivacyRule] | None = None,
) -> str:
    privacy_context = privacy_context or []
    return f"""
Verify the generated counseling note draft.
Separate grounded items, weakly grounded items, unsupported/risky claims,
sensitive information candidates, and counselor-review-required fields.
Do not make clinical judgments on behalf of the counselor.
Use retrieved privacy, ethics, and security rules only to flag review items.
Do not claim legal compliance. Flag sensitive data, consent issues, raw audio storage risk,
unsupported claims, and counselor-review-needed fields.

Sanitized input:
{_json(sanitized)}

Structured data:
{_json(structured)}

Evidence mapped data:
{_json(evidence_mapped)}

Summary draft:
{_json(summary)}

Retrieved privacy/ethics/security context:
{_json(privacy_context)}
"""


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
