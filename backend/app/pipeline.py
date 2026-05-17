"""Compatibility entry point used by the existing Streamlit demo UI.

The FastAPI backend now uses the MVP V0 six-agent pipeline in
``app.graph.graph``. This module keeps the older Streamlit result shape alive
without changing ``streamlit_app.py``.
"""
from __future__ import annotations

from app.graph.graph import run_note_pipeline
from app.schemas.note import SessionInput as NoteSessionInput
from app.schemas.session import SessionInput as LegacySessionInput
from app.schemas.structured_case import StructuredCase
from app.schemas.summary import SessionSummary
from app.schemas.verification import VerificationItem, VerificationReport


class PipelineResult:
    """Legacy three-part result consumed by the Streamlit demo."""

    def __init__(
        self,
        structured: StructuredCase,
        summary: SessionSummary,
        verification: VerificationReport,
        stub: bool,
    ) -> None:
        self.structured = structured
        self.summary = summary
        self.verification = verification
        self.stub = stub


def run_pipeline(session_input: LegacySessionInput) -> PipelineResult:
    """Run the current six-agent pipeline and adapt it to the legacy UI shape."""
    note_input = NoteSessionInput(
        case_id=session_input.case_id,
        session_number=session_input.session_no,
        counselor_memo=session_input.counselor_memo,
        transcript_text=session_input.transcript,
        previous_session_summary=session_input.prev_summary or "",
    )
    response = run_note_pipeline(note_input)
    draft = response.session_summary_draft

    structured = StructuredCase(
        basic_info=(
            f"케이스ID: {draft.session_info.case_id} | "
            f"회기번호: {draft.session_info.session_number} | "
            f"일자: {draft.session_info.session_date or '미입력'}"
        ),
        presenting_problem=draft.presenting_problem.text,
        goals=note_input.counseling_goal or "상담 목표는 상담사가 확인 후 입력해야 합니다.",
        session_content=draft.session_content.text,
        counselor_intervention=draft.counselor_intervention.text,
        client_response=draft.client_response.text,
        assessment="사례개념화와 목표 달성 정도는 상담사 직접 판단 영역입니다.",
        next_plan=draft.next_plan.text,
    )
    summary = SessionSummary(
        session_content=draft.session_content.text,
        counselor_opinion="상담자 소견과 reflection은 상담사가 직접 검토 및 수정해야 합니다.",
        session_summary=draft.presenting_problem.text,
        next_counseling_plan=draft.next_plan.text,
    )
    verification = VerificationReport(
        grounded=[
            VerificationItem(content=item.claim, source=", ".join(item.source_refs))
            for item in response.verification_report.grounded_items
        ],
        ungrounded=[
            VerificationItem(content=item.claim, source=item.reason)
            for item in response.verification_report.weakly_grounded_items
            + response.verification_report.unsupported_or_risky_claims
        ],
        sensitive=[
            VerificationItem(content=item.text, source=item.source)
            for item in response.verification_report.sensitive_info_items
        ],
        needs_human_judgment=[
            VerificationItem(content=item.field, source=item.reason)
            for item in response.verification_report.requires_counselor_review
        ],
    )
    return PipelineResult(
        structured=structured,
        summary=summary,
        verification=verification,
        stub=response.stub,
    )
