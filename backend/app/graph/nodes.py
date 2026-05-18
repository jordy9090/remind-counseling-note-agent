"""Node functions for the Re:mind MVP V0 six-agent pipeline."""
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


def structure_session(state: dict[str, Any]) -> dict[str, Any]:
    """Convert sanitized materials into counseling documentation fields."""
    sanitized: SanitizedInput = state["sanitized_input"]
    fallback = _mock_structured_case(sanitized)
    if settings.stub_mode:
        return {"structured_case_data": fallback}

    prompt = _build_structure_prompt(sanitized)
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
                    in {"inferred", "model_inference", "needs_review", "counselor_input"},
                )
            )

    return {"evidence_mapped_data": EvidenceMappedData(items=mapped_items)}


def generate_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Generate an editable session summary draft."""
    sanitized: SanitizedInput = state["sanitized_input"]
    structured: StructuredCaseData = state["structured_case_data"]
    evidence_mapped: EvidenceMappedData = state["evidence_mapped_data"]
    fallback = _mock_summary(sanitized, structured)
    if settings.stub_mode:
        return {"session_summary_draft": fallback}

    prompt = _build_summary_prompt(sanitized, structured, evidence_mapped)
    summary = get_structured_llm(SessionSummaryDraft).invoke(prompt)
    return {"session_summary_draft": summary}


def verify_output(state: dict[str, Any]) -> dict[str, Any]:
    """Verify support, sensitivity, and counselor-review boundaries."""
    sanitized: SanitizedInput = state["sanitized_input"]
    structured: StructuredCaseData = state["structured_case_data"]
    evidence_mapped: EvidenceMappedData = state["evidence_mapped_data"]
    summary: SessionSummaryDraft = state["session_summary_draft"]
    fallback = _mock_verification(sanitized, evidence_mapped)
    if settings.stub_mode:
        return {"verification_report": fallback}

    prompt = _build_verification_prompt(sanitized, structured, evidence_mapped, summary)
    verification = get_structured_llm(VerificationReport).invoke(prompt)
    return {"verification_report": verification}


def transform_document_preview(state: dict[str, Any]) -> dict[str, Any]:
    """Preview later document transformations from a confirmed session note."""
    sanitized: SanitizedInput = state["sanitized_input"]
    summary: SessionSummaryDraft = state["session_summary_draft"]
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

    preview = DocumentTransformPreview(
        document_type="preview",
        available_transforms=["supervision_report", "termination_report"],
        preview_sections=preview_sections,
        partially_available_fields=partially_available_fields,
        missing_required_fields=missing_required_fields,
        notice="MVP V0에서는 확정된 회기요약을 기반으로 일부 항목만 미리보기합니다.",
    )
    return {"document_transform_preview": preview}


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


def _mock_structured_case(sanitized: SanitizedInput) -> StructuredCaseData:
    tags = ", ".join(sanitized.sources.key_issue_tags) or "진로 불안과 자기비난 사고"
    transcript_ref = "transcript_text"
    memo_ref = "counselor_memo"
    prev_ref = "previous_session_summary"

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
                content=f"{tags}를 중심으로 한 회기 내용 정리",
                evidence_type="direct",
                source_refs=[memo_ref],
            )
        ],
        session_content=[
            EvidenceItem(
                content=_build_session_content_summary(sanitized),
                evidence_type="mixed",
                source_refs=[memo_ref, transcript_ref, prev_ref],
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
        if item.evidence_type in {"mixed", "inferred"}
    ][:5]
    counselor_review_fields = [
        CounselorReviewField(field="reflection", reason="상담자 내적 경험과 임상적 판단 영역"),
        CounselorReviewField(field="case_conceptualization", reason="MVP V0 자동 생성 대상이 아님"),
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
                reason="MVP V0의 자동 생성 대상이 아니며 상담사 임상 판단 영역임.",
                recommendation="상담사가 직접 작성하거나 별도 확인 필드로 분리",
            )
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
        f"이번 회기에서는 {tags}와 관련된 내담자의 어려움을 다루었다. "
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
        in {"inferred", "model_inference", "needs_review", "counselor_input"},
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
    return json.dumps(data, ensure_ascii=False, indent=2)


def _build_structure_prompt(sanitized: SanitizedInput) -> str:
    return f"""
You are generating structured counseling documentation data for Re:mind MVP V0.
Return only fields allowed by the Pydantic schema.
Do not diagnose, evaluate risk, or replace counselor judgment.
If a claim is not directly grounded, mark it as inferred or needs_review.

Sanitized input:
{_json(sanitized)}
"""


def _build_summary_prompt(
    sanitized: SanitizedInput,
    structured: StructuredCaseData,
    evidence_mapped: EvidenceMappedData,
) -> str:
    return f"""
Generate an editable Korean counseling session summary draft.
Each section must include evidence_type and source_refs.
Reflection, case conceptualization, and goal attainment must remain counselor-review areas.

Sanitized input:
{_json(sanitized)}

Structured case data:
{_json(structured)}

Evidence mapped data:
{_json(evidence_mapped)}
"""


def _build_verification_prompt(
    sanitized: SanitizedInput,
    structured: StructuredCaseData,
    evidence_mapped: EvidenceMappedData,
    summary: SessionSummaryDraft,
) -> str:
    return f"""
Verify the generated counseling note draft.
Separate grounded items, weakly grounded items, unsupported/risky claims,
sensitive information candidates, and counselor-review-required fields.
Do not make clinical judgments on behalf of the counselor.

Sanitized input:
{_json(sanitized)}

Structured data:
{_json(structured)}

Evidence mapped data:
{_json(evidence_mapped)}

Summary draft:
{_json(summary)}
"""
