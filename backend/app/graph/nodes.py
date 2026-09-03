"""Node functions for the Re:mind V1 retrieval-aware pipeline."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from app.core.config import settings
from app.schemas.grounding import (
    EvidenceNeed,
    GroundedGenerationDraft,
    GroundedGenerationResult,
    GroundingContext,
)
from app.schemas.note import (
    CounselorReviewField,
    DocumentTransformPreview,
    EvidenceItem,
    EvidenceMappedData,
    EvidenceMappedItem,
    GeneratedDocumentDraft,
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
from app.services.deidentification import deidentify_sources, render_counselor_text
from app.services.supabase_storage import _storage_for_actor
from app.services.grounded_generation import (
    assemble_grounding_context,
    formulate_evidence_needs,
    generate_grounded_claims,
    retrieve_raw_regions_for_needs,
    validate_evidence_ids,
)
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
    masked_sources, sensitive_candidates = deidentify_sources(
        {
            "counselor_memo": session_input.counselor_memo.strip(),
            "transcript_text": session_input.transcript_text.strip(),
            "previous_session_summary": session_input.previous_session_summary.strip(),
            "counseling_goal": session_input.counseling_goal.strip(),
            "psychological_test_summary": session_input.psychological_test_summary.strip(),
            "nonverbal_notes": session_input.nonverbal_notes.strip(),
        }
    )
    sanitized = SanitizedInput(
        case_id=session_input.case_id,
        client_alias=session_input.client_alias,
        session_number=session_input.session_number,
        session_date=session_input.session_date,
        counselor_name=session_input.counselor_name,
        sources=InputSources(
            counselor_memo=masked_sources["counselor_memo"],
            transcript_text=masked_sources["transcript_text"],
            previous_session_summary=masked_sources["previous_session_summary"],
            counseling_goal=masked_sources["counseling_goal"],
            psychological_test_summary=masked_sources["psychological_test_summary"],
            key_issue_tags=session_input.key_issue_tags,
            nonverbal_notes=masked_sources["nonverbal_notes"],
        ),
        sensitive_info_candidates=sensitive_candidates,
    )
    return {"sanitized_input": sanitized, "stub": settings.stub_mode}


def formulate_retrieval_query(state: dict[str, Any]) -> dict[str, Any]:
    """Build one retrieval query from sanitized session materials."""
    sanitized: SanitizedInput = state["sanitized_input"]
    session_input: SessionInput = state["session_input"]
    actor_storage = _storage_for_actor(state.get("actor") or settings.remind_preview_actor)
    report = RetrievalReport(enabled=settings.enable_rag)
    if not settings.enable_rag:
        report.notices.append("ENABLE_RAG is false; retrieval skipped.")
    elif not actor_storage.configured:
        report.notices.append("Supabase credentials are missing; retrieval continued with empty context.")
    if settings.enable_rag and not settings.enable_dense_retrieval:
        report.notices.append("ENABLE_DENSE_RETRIEVAL is false; using lightweight retrieval only.")
    return {
        "retrieval_query": retrieval_query_from_input(session_input.target_document_type, sanitized.sources),
        "retrieval_report": report,
    }


def formulate_grounding_needs(state: dict[str, Any]) -> dict[str, Any]:
    """Create small document-field retrieval intents only for the opt-in PR4 path."""
    if not settings.enable_raw_region_grounding:
        return {"evidence_needs": []}
    sanitized: SanitizedInput = state["sanitized_input"]
    session_input: SessionInput = state["session_input"]
    needs = formulate_evidence_needs(sanitized, session_input.target_document_type)
    return {"evidence_needs": needs}


def retrieve_raw_evidence_regions(state: dict[str, Any]) -> dict[str, Any]:
    """Retrieve existing PR3 raw regions for raw-factual EvidenceNeeds."""
    if not settings.enable_raw_region_grounding:
        return {"raw_regions_by_need": {}}
    report: RetrievalReport = state.get("retrieval_report") or RetrievalReport(enabled=settings.enable_rag)
    if not settings.enable_rag or not settings.enable_dense_retrieval:
        report.notices.append("Raw-region grounding requires ENABLE_RAG and ENABLE_DENSE_RETRIEVAL.")
        return {"raw_regions_by_need": {}, "retrieval_report": report}
    actor = state.get("actor") or settings.remind_preview_actor
    actor_storage = _storage_for_actor(actor)
    if not actor_storage.configured:
        report.notices.append("Raw-region grounding skipped because Supabase credentials are missing.")
        return {"raw_regions_by_need": {}, "retrieval_report": report}
    sanitized: SanitizedInput = state["sanitized_input"]
    user_id = str(actor or "")
    try:
        regions = retrieve_raw_regions_for_needs(
            needs=state.get("evidence_needs") or [],
            user_id=user_id,
            case_id=sanitized.case_id,
            current_session_number=sanitized.session_number,
            top_k=settings.raw_region_top_k,
            storage_client=actor_storage,
        )
        return {"raw_regions_by_need": regions, "retrieval_report": report}
    except Exception as error:
        report.failures.append(f"raw_regions: {error}")
        return {"raw_regions_by_need": {}, "retrieval_report": report}


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
        actor = state.get("actor") or settings.remind_preview_actor
        counselor_id = str(actor)
        actor_storage = _storage_for_actor(actor)
        if settings.enable_dense_retrieval and counselor_id:
            chunks = retrieve_case_memory_chunks(
                query_text=query_text,
                counselor_id=counselor_id,
                case_id=sanitized.case_id,
                max_chunks=5,
                storage_client=actor_storage,
            )
            case_context = chunks_to_case_context(chunks)
        elif settings.enable_dense_retrieval:
            report.notices.append("Dense case-memory retrieval skipped because counselor_id is missing.")

        if not case_context:
            case_context = retrieve_case_context(
                sanitized.case_id,
                max_sessions=3,
                user_id=counselor_id,
                storage_client=actor_storage,
            )
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
    actor = state.get("actor") or settings.remind_preview_actor
    actor_storage = _storage_for_actor(actor)

    if not settings.enable_rag:
        return {
            "retrieved_template_context": template_context,
            "retrieved_privacy_context": privacy_context,
            "retrieved_authoritative_kb_chunks": chunks,
            "retrieval_report": report,
        }

    try:
        fallback_template = retrieve_document_template(
            session_input.target_document_type,
            storage_client=actor_storage,
        )
    except Exception as error:
        report.failures.append(f"document_template: {error}")
        fallback_template = None

    try:
        fallback_privacy = retrieve_privacy_rules(storage_client=actor_storage)
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
                storage_client=actor_storage,
                user_id=str(actor),
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
    """Aggregate retrieval metrics while preserving the existing API fields."""
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
    for chunks in (state.get("retrieved_case_memory_chunks") or [], state.get("retrieved_authoritative_kb_chunks") or []):
        if not chunks:
            continue
        first_chunk = chunks[0]
        report.embedding_latency_ms += int(getattr(first_chunk, "embedding_latency_ms", 0) or 0)
        report.rpc_latency_ms += int(getattr(first_chunk, "rpc_latency_ms", 0) or 0)
        report.retrieval_latency_ms += int(getattr(first_chunk, "total_latency_ms", 0) or 0)
    if settings.enable_rag:
        if not case_context:
            report.notices.append("No prior case-memory context was retrieved.")
        if template_context is None or not report.template_context_found:
            report.notices.append("No document-template KB context was retrieved.")
        if not privacy_context:
            report.notices.append("No privacy or ethics KB context was retrieved.")
    return {"retrieval_report": report}


def assemble_generation_grounding(state: dict[str, Any]) -> dict[str, Any]:
    """Deduplicate retrieved regions and assign request-local evidence IDs."""
    if not settings.enable_raw_region_grounding:
        return {"grounding_context": None}
    context = assemble_grounding_context(
        needs=state.get("evidence_needs") or [],
        raw_regions_by_need=state.get("raw_regions_by_need") or {},
        counselor_memory_chunks=state.get("retrieved_case_memory_chunks") or [],
        authoritative_kb_chunks=state.get("retrieved_authoritative_kb_chunks") or [],
    )
    return {"grounding_context": context}


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
    sanitized: SanitizedInput = state["sanitized_input"]
    catalog = _source_catalog(sanitized, state.get("retrieved_case_context") or [])
    mapped_items: list[EvidenceMappedItem] = []

    for field_name, items in structured:
        for item in items:
            item.source_refs = _resolve_source_refs(item.content, item.source_refs, catalog)
            evidence_type = item.evidence_type
            mapped_items.append(
                EvidenceMappedItem(
                    field=field_name,
                    content=item.content,
                    evidence_type=evidence_type,
                    source_refs=item.source_refs,
                    requires_review=evidence_type
                    in {"inferred", "model_inference", "needs_review", "counselor_input", "prior_context_based"},
                )
            )

    return {"structured_case_data": structured, "evidence_mapped_data": EvidenceMappedData(items=mapped_items)}


def generate_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Generate an editable session summary draft."""
    sanitized: SanitizedInput = state["sanitized_input"]
    structured: StructuredCaseData = state["structured_case_data"]
    evidence_mapped: EvidenceMappedData = state["evidence_mapped_data"]
    requested_section_ids: list[str] = state.get("requested_section_ids") or []
    session_topic: str = state.get("session_topic") or ""
    case_context: list[RetrievedCaseContextItem] = state.get("retrieved_case_context") or []
    template_context: RetrievedTemplateContext | None = state.get("retrieved_template_context")
    report: RetrievalReport = state.get("retrieval_report") or RetrievalReport(enabled=settings.enable_rag)
    started = time.perf_counter()
    fallback = _mock_summary(sanitized, structured)
    if settings.stub_mode:
        report.generation_latency_ms += _elapsed_ms(started)
        return {"session_summary_draft": fallback, "retrieval_report": report}

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
    _normalize_summary_refs(summary, sanitized, case_context)
    if not re.search(r"(상담자\s*성찰|상담자의\s*(?:내적|정서적)\s*(?:반응|경험)|역전이)", sanitized.sources.counselor_memo):
        summary.reflection = SummarySection(
            text="[상담사 확인 필요]", evidence_type="counselor_input",
            source_refs=[], requires_review=True,
        )
    report.generation_latency_ms += _elapsed_ms(started)
    return {"session_summary_draft": summary, "retrieval_report": report}


def generate_grounded_document(state: dict[str, Any]) -> dict[str, Any]:
    """Generate claim-level provenance using the existing structured LLM service."""
    if not settings.enable_raw_region_grounding:
        return {"grounded_generation_draft": None}
    context: GroundingContext | None = state.get("grounding_context")
    if context is None:
        return {"grounded_generation_draft": GroundedGenerationDraft()}
    draft = generate_grounded_claims(state["sanitized_input"], context)
    return {"grounded_generation_draft": draft}


def validate_claim_sources(state: dict[str, Any]) -> dict[str, Any]:
    """Reject invented or source-hierarchy-incompatible evidence IDs."""
    if not settings.enable_raw_region_grounding:
        return {"grounding": None}
    context: GroundingContext | None = state.get("grounding_context")
    draft: GroundedGenerationDraft | None = state.get("grounded_generation_draft")
    if context is None:
        return {"grounding": None}
    return {"grounding": validate_evidence_ids(draft or GroundedGenerationDraft(), context)}


def verify_output(state: dict[str, Any]) -> dict[str, Any]:
    """Verify support, sensitivity, and counselor-review boundaries."""
    sanitized: SanitizedInput = state["sanitized_input"]
    structured: StructuredCaseData = state["structured_case_data"]
    evidence_mapped: EvidenceMappedData = state["evidence_mapped_data"]
    summary: SessionSummaryDraft = state["session_summary_draft"]
    privacy_context: list[RetrievedPrivacyRule] = state.get("retrieved_privacy_context") or []
    fallback = _mock_verification(sanitized, evidence_mapped, privacy_context)
    if settings.stub_mode:
        _merge_grounding_verification(fallback, state.get("grounding"))
        return {"verification_report": fallback}

    prompt = _build_verification_prompt(sanitized, structured, evidence_mapped, summary, privacy_context)
    verification = get_structured_llm(VerificationReport).invoke(prompt)
    initial: VerificationReport | None = state.get("initial_verification_report")
    if initial:
        verification.unsupported_or_risky_claims = _unique_review_claims(
            [*initial.unsupported_or_risky_claims, *verification.unsupported_or_risky_claims]
        )
        verification.weakly_grounded_items = _unique_review_claims(
            [*initial.weakly_grounded_items, *verification.weakly_grounded_items]
        )
    _reconcile_verification_claims(verification, sanitized, state.get("retrieved_case_context") or [])
    _merge_grounding_verification(verification, state.get("grounding"))
    _apply_verification_consistency(summary, verification)
    return {"verification_report": verification}


def conditional_revision(state: dict[str, Any]) -> dict[str, Any]:
    """Mark risky draft sections for counselor review and allow one re-verification pass."""
    if state.get("revision_attempted"):
        return {"revision_needs_reverify": False}
    verification: VerificationReport = state["verification_report"]
    if not verification.unsupported_or_risky_claims:
        return {"revision_attempted": False, "revision_needs_reverify": False}

    summary: SessionSummaryDraft = state["session_summary_draft"].model_copy(deep=True)
    for section in (
        summary.session_theme,
        summary.presenting_problem,
        summary.session_content,
        summary.counselor_intervention,
        summary.client_response,
        summary.reflection,
        summary.next_plan,
    ):
        if section.evidence_type != "direct":
            section.requires_review = True
    return {
        "session_summary_draft": summary,
        "initial_verification_report": verification.model_copy(deep=True),
        "revision_attempted": True,
        "revision_needs_reverify": True,
        "revision_reason": "Unsupported or risky claims were marked for counselor review.",
    }


def transform_document_preview(state: dict[str, Any]) -> dict[str, Any]:
    """Assemble complete, evidence-grounded counselor-facing document drafts."""
    sanitized: SanitizedInput = state["sanitized_input"]
    structured: StructuredCaseData = state["structured_case_data"]
    summary: SessionSummaryDraft = state["session_summary_draft"].model_copy(deep=True)
    template_context: RetrievedTemplateContext | None = state.get("retrieved_template_context")
    session_input: SessionInput = state["session_input"]
    client_alias = sanitized.client_alias
    for section in (
        summary.session_theme,
        summary.presenting_problem,
        summary.session_content,
        summary.counselor_intervention,
        summary.client_response,
        summary.reflection,
        summary.next_plan,
    ):
        section.text = render_counselor_text(section.text, client_alias=client_alias)
    observations = render_counselor_text(
        " ".join(item.content for item in structured.nonverbal_observations if item.evidence_type != "needs_review"),
        client_alias=client_alias,
    )
    risk_text, risk_refs = _extract_risk_information(sanitized)
    risk_text = render_counselor_text(risk_text, client_alias=client_alias)
    session_sections = {
        "기본 회기정보": f"사례 ID: {sanitized.case_id}\n회기: {sanitized.session_number}회기\n회기일: {sanitized.session_date or '[상담사 확인 필요]'}\n상담자: {sanitized.counselor_name or '[상담사 확인 필요]'}",
        "주호소/핵심 문제": summary.presenting_problem.text,
        "주요 상담내용": summary.session_content.text,
        "상담자 개입": summary.counselor_intervention.text,
        "내담자 반응": summary.client_response.text,
        "관찰사항": observations or "[상담사 확인 필요]",
        "위험 관련 확인 가능 정보": risk_text,
        "다음 회기 계획": summary.next_plan.text,
    }
    session_refs = {
        "주호소/핵심 문제": summary.presenting_problem.source_refs,
        "주요 상담내용": summary.session_content.source_refs,
        "상담자 개입": summary.counselor_intervention.source_refs,
        "내담자 반응": summary.client_response.source_refs,
        "관찰사항": _unique_strings([ref for item in structured.nonverbal_observations for ref in item.source_refs]),
        "위험 관련 확인 가능 정보": risk_refs,
        "다음 회기 계획": summary.next_plan.source_refs,
    }
    session_note = GeneratedDocumentDraft(
        document_type="session_note", sections=session_sections, source_refs=session_refs,
        missing_or_review_fields=[key for key, value in session_sections.items() if value == "[상담사 확인 필요]"],
    )
    first_previous = _first_previous_session_text(sanitized.sources.previous_session_summary)
    termination_sections = {
        "상담 시작 시 주요 문제": first_previous or "[상담사 확인 필요]",
        "상담 목표": render_counselor_text(sanitized.sources.counseling_goal, client_alias=client_alias) or "[상담사 확인 필요]",
        "주요 진행 내용": summary.session_content.text,
        "관찰된 변화/진전": summary.client_response.text,
        "남은 어려움": summary.presenting_problem.text,
        "상담자 개입": summary.counselor_intervention.text,
        "종결 시 상태": "현재 제공된 자료만으로 종결 여부와 종결 시 상태는 상담사 확인이 필요함.",
        "추후 계획": summary.next_plan.text,
    }
    termination_refs = {
        "상담 시작 시 주요 문제": ["previous_session_summary"] if first_previous else [],
        "상담 목표": ["counseling_goal"] if sanitized.sources.counseling_goal else [],
        "주요 진행 내용": summary.session_content.source_refs,
        "관찰된 변화/진전": summary.client_response.source_refs,
        "남은 어려움": summary.presenting_problem.source_refs,
        "상담자 개입": summary.counselor_intervention.source_refs,
        "종결 시 상태": [],
        "추후 계획": summary.next_plan.source_refs,
    }
    termination = GeneratedDocumentDraft(
        document_type="termination_report", sections=termination_sections, source_refs=termination_refs,
        missing_or_review_fields=["종결 여부", "종결 시 상태"],
        notice="종결 근거가 없는 진행 중 사례의 검토용 초안입니다. 종결 여부는 상담사가 확인해야 합니다.",
    )
    selected = termination if session_input.target_document_type == "termination_report" else session_note
    missing_required_fields = list(selected.missing_or_review_fields)
    if template_context:
        missing_required_fields = _unique_strings(
            missing_required_fields + template_context.missing_field_checklist
        )
    preview = DocumentTransformPreview(
        document_type=selected.document_type,
        available_transforms=["supervision_report", "termination_report"],
        preview_sections=selected.sections,
        partially_available_fields={field: "상담사 직접 확인 필요" for field in selected.missing_or_review_fields},
        missing_required_fields=missing_required_fields,
        notice=selected.notice,
    )
    return {
        "session_summary_draft": summary,
        "document_transform_preview": preview,
        "session_note_draft": session_note,
        "termination_report_draft": termination,
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
    tags = ", ".join(sanitized.sources.key_issue_tags) or "주요 상담 이슈"
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
                content=_first_source_sentence(sanitized.sources.counselor_memo, "주호소는 상담사 확인이 필요함."),
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
                content=_first_source_sentence(sanitized.sources.counselor_memo, "상담자 개입은 상담사 확인이 필요함."),
                evidence_type="direct",
                source_refs=[memo_ref, transcript_ref],
            )
        ],
        client_responses=[
            EvidenceItem(
                content=_extract_client_utterance(sanitized.sources.transcript_text),
                evidence_type="direct",
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
            client_alias=sanitized.client_alias,
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
        content="[상담사 확인 필요]",
        evidence_type="needs_review",
        source_refs=[],
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


def _first_source_sentence(text: str, fallback: str) -> str:
    return next(iter(_sentences(text)), fallback)


def _extract_risk_information(sanitized: SanitizedInput) -> tuple[str, list[str]]:
    patterns = re.compile(r"(자살|자해|타해|위험도|급성\s*위험|(?:자신|타인)에게\s*위해|위해를\s*가)")
    found: list[str] = []
    refs: list[str] = []
    for ref, text in (
        ("counselor_memo", sanitized.sources.counselor_memo),
        ("psychological_test_summary", sanitized.sources.psychological_test_summary),
    ):
        matched = [sentence for sentence in _sentences(text) if patterns.search(sentence)]
        if matched:
            found.extend(matched)
            refs.append(ref)
    if not found:
        return "[상담사 확인 필요]", []
    return " ".join(_unique_strings(found)), refs


def _first_previous_session_text(text: str) -> str:
    match = re.search(r"(?:^|\n)\s*1회기(?:\s*\([^)]*\))?\s*:\s*(.*?)(?=\n\s*2회기(?:\s*\(|\s*:)|$)", text or "", re.DOTALL)
    return " ".join(match.group(1).split()) if match else ""


def _source_catalog(
    sanitized: SanitizedInput,
    case_context: list[RetrievedCaseContextItem],
) -> dict[str, str]:
    catalog = {
        "counselor_memo": sanitized.sources.counselor_memo,
        "transcript_text": sanitized.sources.transcript_text,
        "previous_session_summary": sanitized.sources.previous_session_summary,
        "counseling_goal": sanitized.sources.counseling_goal,
        "psychological_test_summary": sanitized.sources.psychological_test_summary,
        "key_issue_tags": ", ".join(sanitized.sources.key_issue_tags),
        "nonverbal_notes": sanitized.sources.nonverbal_notes,
    }
    for index, line in enumerate(sanitized.sources.transcript_text.splitlines(), 1):
        if line.strip():
            catalog[f"transcript.turn_{index}"] = line.strip()
    previous_pattern = re.compile(
        r"(?:^|\n)\s*(\d+)회기(?:\s*\([^)]*\))?\s*:\s*(.*?)(?=\n\s*\d+회기(?:\s*\(|\s*:)|$)",
        re.DOTALL,
    )
    for match in previous_pattern.finditer(sanitized.sources.previous_session_summary):
        catalog[f"previous_session.{match.group(1)}"] = " ".join(match.group(2).split())
    for item in case_context:
        catalog[item.source_ref] = item.summary or json.dumps(item.confirmed_note, ensure_ascii=False)
        for evidence in item.evidence_items:
            catalog[evidence.source_ref] = evidence.source_text
    return {ref: text for ref, text in catalog.items() if text}


def _resolve_source_refs(content: str, refs: list[str], catalog: dict[str, str]) -> list[str]:
    resolved = [ref for ref in refs if ref in catalog]
    aliases = {
        "transcript": "transcript_text", "transcript_text": "transcript_text",
        "memo": "counselor_memo", "counselor_memo": "counselor_memo",
        "previous_summary": "previous_session_summary", "previous_session_summary": "previous_session_summary",
        "psychological_test": "psychological_test_summary", "psychological_test_summary": "psychological_test_summary",
        "nonverbal": "nonverbal_notes", "nonverbal_notes": "nonverbal_notes",
    }
    for ref in refs:
        normalized = aliases.get(ref.lower())
        if normalized and normalized in catalog:
            resolved.append(normalized)
    best = sorted(
        ((ref, _text_similarity(content, text)) for ref, text in catalog.items()),
        key=lambda pair: pair[1], reverse=True,
    )
    granular = [pair for pair in best if pair[0].startswith(("transcript.turn_", "previous_session."))]
    if granular and granular[0][1] >= 0.08:
        resolved.insert(0, granular[0][0])
    if best and best[0][1] >= 0.08:
        best_ref = best[0][0]
        # Prefer a granular transcript/prior-session ref when it carries the claim.
        if best_ref.startswith(("transcript.turn_", "previous_session.")):
            resolved.insert(0, best_ref)
        elif not resolved:
            resolved.append(best_ref)
    return _unique_strings(resolved)


def _text_similarity(left: str, right: str) -> float:
    def grams(value: str) -> set[str]:
        compact = re.sub(r"\s+", "", value or "")
        return {compact[index:index + 2] for index in range(max(0, len(compact) - 1))}
    a, b = grams(left), grams(right)
    return len(a & b) / max(1, len(a))


def _normalize_summary_refs(
    summary: SessionSummaryDraft,
    sanitized: SanitizedInput,
    case_context: list[RetrievedCaseContextItem],
) -> None:
    catalog = _source_catalog(sanitized, case_context)
    for section in (
        summary.session_theme, summary.presenting_problem, summary.session_content,
        summary.counselor_intervention, summary.client_response, summary.reflection,
        summary.next_plan,
    ):
        section.source_refs = _resolve_source_refs(section.text, section.source_refs, catalog)
        section.requires_review = section.requires_review or section.evidence_type in {
            "inferred", "model_inference", "needs_review", "counselor_input", "prior_context_based",
        }


def _unique_review_claims(items: list[ReviewableClaim]) -> list[ReviewableClaim]:
    seen: set[str] = set()
    result: list[ReviewableClaim] = []
    for item in items:
        key = item.claim.strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _reconcile_verification_claims(
    verification: VerificationReport,
    sanitized: SanitizedInput,
    case_context: list[RetrievedCaseContextItem],
) -> None:
    """Keep verifier findings only when the input catalog cannot support them.

    The LLM verifier occasionally labels verbatim counselor input as unsupported
    despite valid refs in the final draft. This deterministic pass never invents
    support: it requires measurable overlap with an existing source.
    """
    catalog = _source_catalog(sanitized, case_context)
    remaining: list[ReviewableClaim] = []
    for item in verification.unsupported_or_risky_claims:
        refs = _resolve_source_refs(item.claim, [], catalog)
        supported = [ref for ref in refs if _text_similarity(item.claim, catalog.get(ref, "")) >= 0.08]
        if supported:
            verification.grounded_items.append(GroundedItem(claim=item.claim, source_refs=supported))
        else:
            remaining.append(item)
    verification.unsupported_or_risky_claims = remaining


def _apply_verification_consistency(
    summary: SessionSummaryDraft,
    verification: VerificationReport,
) -> None:
    review_claims = [
        item.claim for item in [
            *verification.weakly_grounded_items,
            *verification.unsupported_or_risky_claims,
        ]
    ]
    for section in (
        summary.session_theme, summary.presenting_problem, summary.session_content,
        summary.counselor_intervention, summary.client_response, summary.reflection,
        summary.next_plan,
    ):
        if section.evidence_type != "direct" or any(
            _text_similarity(section.text, claim) >= 0.35 for claim in review_claims
        ):
            section.requires_review = True


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
Role: documentation assistant for a counselor, not a clinician and not a supervisor.
Task: extract and structure only what is supported by allowed sources.
Language: write every content field in natural Korean; preserve direct Korean client quotations in Korean.
Output schema: return only fields allowed by the Pydantic schema.
Source precedence:
1. current-session counselor-confirmed input
2. current-session transcript or memo
3. counselor-confirmed prior-session memory
4. document-template KB
5. ethics/privacy/security KB for warnings only
Required source_refs: every factual claim must cite current input source_refs or retrieved prior-session source_refs.
Prior-session rule: if a claim depends on prior sessions, set evidence_type to prior_context_based and include the stored source_ref.
Template rule: document template context can identify missing fields and counselor-review fields only.
Prohibited actions: diagnosis, psychiatric labels, treatment prescriptions, psychological-test interpretation,
automatic suicide/self-harm conclusions, counselor scoring, invented client statements, invented nonverbal behavior,
invented interventions, or unsupported progress claims.
Uncertainty behavior: if evidence is missing or weak, return needs_review and identify the missing field.
Failure behavior: prefer a brief needs_review item over a plausible guess.

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
Role: Korean counseling documentation drafting assistant.
Task: draft editable text, not final clinical judgment.
Each section must include evidence_type and source_refs.
Source precedence:
1. current-session counselor-confirmed input
2. current-session transcript or memo
3. counselor-confirmed prior-session memory
4. document-template KB
5. ethics/privacy/security KB for warnings only
Counselor-review boundaries: reflection, case conceptualization, goal attainment, risk interpretation, and
psychological-test interpretation must remain counselor-review areas.
Prohibited actions: diagnosis, clinical risk scoring, treatment recommendation, counselor evaluation,
invented client statements, invented interventions, invented nonverbal behavior, and unsupported progress claims.
Prior-session rule: retrieved prior sessions may be used only as traceable background context. If a section uses
prior-session context, set evidence_type to prior_context_based or mixed and include stored source_refs.
KB rule: do not treat privacy/ethics/template rules as clinical evidence.
Uncertainty behavior: if evidence is missing, return needs_review and state the missing field instead of guessing.
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
Role: safety and evidence verifier for a counseling documentation draft.
Task: separate grounded items, weakly grounded items, unsupported/risky claims,
sensitive information candidates, and counselor-review-required fields.
Allowed sources: current input, evidence map, generated draft, and retrieved privacy/ethics/security KB for warnings only.
Required behavior: every factual generated claim should have valid source_refs. Flag missing source_refs.
Prohibited actions: do not make clinical judgments, legal-compliance claims, diagnoses, treatment recommendations,
psychological-test interpretations, or counselor performance evaluations.
Warning behavior: use retrieved privacy, ethics, and security rules only to flag sensitive data, consent issues,
raw audio storage risk, access-control risk, unsupported claims, and counselor-review-needed fields.
Failure behavior: when uncertain, add a reviewable claim instead of approving the claim.

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


def _merge_grounding_verification(
    verification: VerificationReport,
    grounding: GroundedGenerationResult | None,
) -> None:
    if grounding is None:
        return
    for diagnostic in grounding.citation_diagnostics:
        verification.unsupported_or_risky_claims.append(
            ReviewableClaim(
                claim=diagnostic.claim_id,
                reason=f"Invalid grounded citation: {diagnostic.reason}",
                recommendation="상담사가 claim과 실제 raw/counselor-confirmed source를 다시 확인",
            )
        )
    for claim in grounding.claims:
        if claim.support_type != "unsupported":
            continue
        verification.unsupported_or_risky_claims.append(
            ReviewableClaim(
                claim=claim.text,
                reason="제공된 source로 지지되지 않는 factual claim",
                recommendation="근거를 추가하거나 문장을 삭제하고 상담사 검토 상태로 유지",
            )
        )
    verification.unsupported_or_risky_claims = _unique_review_claims(
        verification.unsupported_or_risky_claims
    )


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


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
