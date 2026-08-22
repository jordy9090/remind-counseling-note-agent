"""Evidence-only supervision report workflow."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.schemas.note import (
    SessionSummaryDraft, SupervisionAiReviewPanel, SupervisionCompletionChecklistItem,
    SupervisionContentBlock, SupervisionNeedsHumanReviewItem, SupervisionReportDraft,
    SupervisionReportMeta, SupervisionReportRequest, SupervisionReportSection,
    SupervisionSpeakerTurn, SupervisionUnsupportedClaim,
)
from app.services.deidentification import render_counselor_value

PLACEHOLDER = "[상담사 확인 필요]"


class SupervisionReportState(TypedDict, total=False):
    request: SupervisionReportRequest
    case_context: dict[str, Any]
    normalized_inputs: dict[str, Any]
    evidence_index: dict[str, dict[str, str]]
    sections_a: list[SupervisionReportSection]
    sections_b: list[SupervisionReportSection]
    sections_c: list[SupervisionReportSection]
    suggested_questions: list[str]
    ai_review: SupervisionAiReviewPanel
    report: SupervisionReportDraft


def create_supervision_report_graph():
    workflow = StateGraph(SupervisionReportState)
    for name, fn in (
        ("load_case_context", load_case_context), ("normalize_inputs", normalize_inputs),
        ("build_evidence_index", build_evidence_index), ("generate_section_A", generate_section_A),
        ("generate_section_B", generate_section_B), ("generate_section_C", generate_section_C),
        ("generate_supervision_questions", generate_supervision_questions),
        ("evidence_grounding_checker", evidence_grounding_checker),
        ("clinical_safety_guard", clinical_safety_guard),
        ("generate_ai_review_panel", generate_ai_review_panel),
        ("format_supervision_report", format_supervision_report),
    ):
        workflow.add_node(name, fn)
    order = [
        "load_case_context", "normalize_inputs", "build_evidence_index", "generate_section_A",
        "generate_section_B", "generate_section_C", "generate_supervision_questions",
        "evidence_grounding_checker", "clinical_safety_guard", "generate_ai_review_panel",
        "format_supervision_report",
    ]
    workflow.set_entry_point(order[0])
    for left, right in zip(order, order[1:]):
        workflow.add_edge(left, right)
    workflow.add_edge(order[-1], END)
    return workflow.compile()


supervision_report_graph = None


def run_supervision_report_pipeline(request: SupervisionReportRequest) -> SupervisionReportDraft:
    global supervision_report_graph
    if supervision_report_graph is None:
        supervision_report_graph = create_supervision_report_graph()
    report = supervision_report_graph.invoke({"request": request})["report"]
    rendered = render_counselor_value(
        report.model_dump(mode="python"),
        client_alias=request.client_alias or request.session_input.client_alias,
    )
    return SupervisionReportDraft.model_validate(rendered)


def load_case_context(state: SupervisionReportState) -> dict[str, Any]:
    request, session = state["request"], state["request"].session_input
    return {"case_context": {
        "case_id": session.case_id, "session_number": session.session_number,
        "session_date": session.session_date,
        "report_date": request.report_date or session.session_date or date.today().isoformat(),
        "client_alias": request.client_alias or session.client_alias or session.case_id,
        "counselor_name": session.counselor_name or PLACEHOLDER,
        "institution": request.institution or PLACEHOLDER,
        "supervisor": request.supervisor or PLACEHOLDER,
        "supervision_date_place": request.supervision_date_place or PLACEHOLDER,
        "current_summary": request.session_summary_draft, "current_input": session,
        "demo_mode": False,
    }}


def normalize_inputs(state: SupervisionReportState) -> dict[str, Any]:
    session = state["case_context"]["current_input"]
    return {"normalized_inputs": {
        "previous_sessions": _parse_previous_sessions(session.previous_session_summary),
        "transcript_turns": _parse_transcript(session.transcript_text),
        "memo_items": _sentences(session.counselor_memo),
        "nonverbal_items": _sentences(session.nonverbal_notes),
        "psychological_test_summary": session.psychological_test_summary.strip(),
        "counseling_goal": session.counseling_goal.strip(),
        "key_issue_tags": list(session.key_issue_tags),
    }}


def build_evidence_index(state: SupervisionReportState) -> dict[str, Any]:
    context, normalized = state["case_context"], state["normalized_inputs"]
    summary: SessionSummaryDraft | None = context.get("current_summary")
    evidence: dict[str, dict[str, str]] = {}
    for item in normalized["previous_sessions"]:
        evidence[f"previous_session.{item['session_number']}"] = {"label": f"{item['session_number']}회기 이전 요약", "text": item["summary"]}
    for turn in normalized["transcript_turns"]:
        evidence[turn["turnId"]] = {"label": f"{context['session_number']}회기 축어록", "text": turn["text"]}
    for index, text in enumerate(normalized["memo_items"], 1):
        evidence[f"counselor_memo.{index}"] = {"label": "상담자 메모", "text": text}
    for index, text in enumerate(normalized["nonverbal_items"], 1):
        evidence[f"nonverbal_notes.{index}"] = {"label": "비언어 관찰", "text": text}
    for key, label, text in (
        ("psychological_test_summary", "심리검사 입력 요약", normalized["psychological_test_summary"]),
        ("counseling_goal", "상담 목표", normalized["counseling_goal"]),
        ("key_issue_tags", "핵심 이슈 태그", ", ".join(normalized["key_issue_tags"])),
    ):
        if text:
            evidence[key] = {"label": label, "text": text}
    if summary:
        for key in ("session_theme", "presenting_problem", "session_content", "counselor_intervention", "client_response", "reflection", "next_plan"):
            evidence[f"current_summary.{key}"] = {"label": "현재 회기 생성 요약", "text": getattr(summary, key).text}
    return {"evidence_index": evidence}


def generate_section_A(state: SupervisionReportState) -> dict[str, Any]:
    context, normalized = state["case_context"], state["normalized_inputs"]
    summary = context.get("current_summary")
    info = f"사례 ID: {context['case_id']}\n현재 회기: {context['session_number']}회기\n회기일: {context['session_date'] or PLACEHOLDER}\n내담자 표기: {context['client_alias']}"
    problem = summary.presenting_problem.text if summary else _first(normalized["memo_items"])
    observations = " ".join(normalized["nonverbal_items"]) or PLACEHOLDER
    psych = normalized["psychological_test_summary"] or PLACEHOLDER
    return {"sections_a": [
        _heading("A", "A. 사례 기본 정보"),
        _section("A-1", "A-1. 확인된 회기 정보", [_paragraph("A-1.p1", info, [])], "complete"),
        _section("A-2", "A-2. 주호소 및 핵심 문제", [_paragraph("A-2.p1", problem, _existing(state, "current_summary.presenting_problem", "counselor_memo.1"))], _complete(problem)),
        _section("A-3", "A-3. 관찰 정보", [_paragraph("A-3.p1", observations, _prefix(state, "nonverbal_notes."), review_status="needs_human_input" if observations == PLACEHOLDER else "unchecked")], _complete(observations)),
        _section("A-4", "A-4. 심리검사 입력 요약", [_paragraph("A-4.p1", psych, _existing(state, "psychological_test_summary"), ["검사 해석과 임상 판단은 상담사가 원자료와 대조해야 합니다."], "needs_human_input")], "partial" if psych != PLACEHOLDER else "missing"),
        _section("A-5", "A-5. 인구학·가족·이전 상담 정보", [_paragraph("A-5.p1", PLACEHOLDER, [], ["제공된 자료에 없는 정보는 생성하지 않았습니다."], "needs_human_input")], "missing"),
    ]}


def generate_section_B(state: SupervisionReportState) -> dict[str, Any]:
    context, normalized = state["case_context"], state["normalized_inputs"]
    summary = context.get("current_summary")
    goal = normalized["counseling_goal"] or PLACEHOLDER
    theme = summary.session_theme.text if summary else _first(normalized["memo_items"])
    plan = summary.next_plan.text if summary else PLACEHOLDER
    return {"sections_b": [
        _heading("B", "B. 상담 목표와 수퍼비전 초점"),
        _section("B-1", "B-1. 상담 목표", [_paragraph("B-1.p1", goal, _existing(state, "counseling_goal"), review_status="needs_human_input")], _complete(goal)),
        _section("B-2", "B-2. 현재 회기 초점", [_paragraph("B-2.p1", theme, _existing(state, "current_summary.session_theme", "counselor_memo.1"))], _complete(theme)),
        _section("B-3", "B-3. 다음 회기 계획", [_paragraph("B-3.p1", plan, _existing(state, "current_summary.next_plan"), review_status="needs_human_input")], _complete(plan)),
    ]}


def generate_section_C(state: SupervisionReportState) -> dict[str, Any]:
    context, normalized = state["case_context"], state["normalized_inputs"]
    summary = context.get("current_summary")
    rows = [{"회기": f"{item['session_number']}회기", "날짜": item.get("date") or "확인 필요", "근거 요약": item["summary"]} for item in normalized["previous_sessions"]]
    if summary:
        rows.append({"회기": f"{context['session_number']}회기", "날짜": context["session_date"] or "확인 필요", "근거 요약": summary.session_theme.text})
    transcript = [SupervisionSpeakerTurn(**turn) for turn in normalized["transcript_turns"][:12]]
    return {"sections_c": [
        _heading("C", "C. 상담 진행 및 현재 회기"),
        _section("C-1", "C-1. 회기 진행 요약", [SupervisionContentBlock(id="C-1.table", type="table", rows=rows, evidenceIds=[*_prefix(state, "previous_session."), *_existing(state, "current_summary.session_theme")], reviewStatus="needs_human_input")], "complete" if rows else "missing"),
        _section("C-2", "C-2. 주요 상담 내용", [_paragraph("C-2.p1", summary.session_content.text if summary else PLACEHOLDER, _existing(state, "current_summary.session_content"))], "complete" if summary else "missing"),
        _section("C-3", "C-3. 상담자 개입과 내담자 반응", [_paragraph("C-3.p1", f"상담자 개입: {summary.counselor_intervention.text}\n내담자 반응: {summary.client_response.text}" if summary else PLACEHOLDER, _existing(state, "current_summary.counselor_intervention", "current_summary.client_response"))], "complete" if summary else "missing"),
        _section("C-4", "C-4. 발췌 축어록", [SupervisionContentBlock(id="C-4.transcript", type="transcript", speakerTurns=transcript, evidenceIds=[turn.turnId for turn in transcript], reviewStatus="needs_human_input", warnings=["발췌 축어록이며 제출 전 원문 대조가 필요합니다."])], "complete" if transcript else "missing"),
        _section("C-5", "C-5. 상담자 성찰", [_paragraph("C-5.p1", summary.reflection.text if summary else PLACEHOLDER, _existing(state, "current_summary.reflection"), ["상담자의 실제 내적 경험과 개입 의도는 직접 확인해야 합니다."], "needs_human_input")], "needs_review"),
    ]}


def generate_supervision_questions(state: SupervisionReportState) -> dict[str, Any]:
    tags = state["normalized_inputs"]["key_issue_tags"]
    questions = [f"{tag}와 관련하여 현재 개입의 근거와 다음 회기 관찰 지표를 어떻게 구체화할 것인가?" for tag in tags[:3]]
    return {"suggested_questions": questions or [PLACEHOLDER]}


def evidence_grounding_checker(state: SupervisionReportState) -> dict[str, Any]:
    evidence = state["evidence_index"]
    unsupported: list[SupervisionUnsupportedClaim] = []
    for section in state["sections_a"] + state["sections_b"] + state["sections_c"]:
        for block in section.contentBlocks:
            missing = [ref for ref in block.evidenceIds if ref not in evidence]
            if missing:
                unsupported.append(SupervisionUnsupportedClaim(blockId=block.id, claim=(block.text or section.title)[:100], reason=f"존재하지 않는 evidenceIds: {', '.join(missing)}"))
            if block.text and block.text != PLACEHOLDER and not block.evidenceIds and section.id != "A-1":
                unsupported.append(SupervisionUnsupportedClaim(blockId=block.id, claim=block.text[:100], reason="연결된 근거가 없습니다."))
    return {"ai_review": SupervisionAiReviewPanel(unsupportedClaims=unsupported)}


def clinical_safety_guard(state: SupervisionReportState) -> dict[str, Any]:
    review = state.get("ai_review") or SupervisionAiReviewPanel()
    review.needsHumanReview.append(SupervisionNeedsHumanReviewItem(sectionId="clinical-boundary", message="진단, 위험 판단, 검사 해석, 종결 판단은 상담사가 원자료와 함께 확인해야 합니다.", severity="high"))
    return {"ai_review": review}


def generate_ai_review_panel(state: SupervisionReportState) -> dict[str, Any]:
    review = state.get("ai_review") or SupervisionAiReviewPanel()
    sections = state["sections_a"] + state["sections_b"] + state["sections_c"]
    review.completionChecklist = [
        SupervisionCompletionChecklistItem(label="입력 근거 연결", status="done" if not review.unsupportedClaims else "partial"),
        SupervisionCompletionChecklistItem(label="현재 회기 요약 반영", status="done" if state["case_context"].get("current_summary") else "missing"),
        SupervisionCompletionChecklistItem(label="상담사 확인 항목 표시", status="done"),
    ]
    review.missingFields = [section.title for section in sections if section.status == "missing"]
    review.demoInputs = []
    review.suggestedSupervisionQuestions = state["suggested_questions"]
    review.caution = "근거 기반 AI 초안입니다. 제출 전 사실관계와 임상 판단을 상담사가 확인해야 합니다."
    return {"ai_review": review}


def format_supervision_report(state: SupervisionReportState) -> dict[str, Any]:
    context = state["case_context"]
    sections = state["sections_a"] + state["sections_b"] + state["sections_c"]
    report = SupervisionReportDraft(
        reportId=f"supervision-{context['case_id']}-{context['session_number']}", caseId=context["case_id"],
        meta=SupervisionReportMeta(clientAlias=context["client_alias"], sessionNumber=context["session_number"], reportDate=context["report_date"], counselorName=context["counselor_name"], institution=context["institution"], supervisor=context["supervisor"], supervisionDatePlace=context["supervision_date_place"]),
        sections=sections, aiReview=state["ai_review"], evidenceIndex=state["evidence_index"],
    )
    return {"report": report}


def _heading(section_id: str, title: str) -> SupervisionReportSection:
    return SupervisionReportSection(id=section_id, title=title, level=1, contentBlocks=[], status="partial")


def _section(section_id: str, title: str, blocks: list[SupervisionContentBlock], status: str) -> SupervisionReportSection:
    return SupervisionReportSection(id=section_id, title=title, level=2, contentBlocks=blocks, status=status)


def _paragraph(block_id: str, text: str, refs: list[str], warnings: list[str] | None = None, review_status: str = "unchecked") -> SupervisionContentBlock:
    return SupervisionContentBlock(id=block_id, type="paragraph", text=text or PLACEHOLDER, evidenceIds=refs, aiGenerated=True, demoValue=False, reviewStatus=review_status, warnings=warnings or [])


def _existing(state: SupervisionReportState, *refs: str) -> list[str]:
    return [ref for ref in refs if ref in state["evidence_index"]]


def _prefix(state: SupervisionReportState, prefix: str) -> list[str]:
    return [ref for ref in state["evidence_index"] if ref.startswith(prefix)]


def _parse_previous_sessions(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"(?:^|\n)\s*(\d+)회기(?:\s*\(([^)]*)\))?\s*:\s*(.*?)(?=\n\s*\d+회기(?:\s*\(|\s*:)|$)", re.DOTALL)
    return [{"session_number": int(match.group(1)), "date": (match.group(2) or "").strip(), "summary": " ".join(match.group(3).split())} for match in pattern.finditer(text or "")]


def _parse_transcript(text: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("Cl:", "내담자:", "Client:")):
            speaker = "client"
        elif stripped.startswith(("C:", "상담자:", "Counselor:")):
            speaker = "counselor"
        else:
            continue
        turns.append({"turnId": f"transcript.turn_{len(turns) + 1}", "speaker": speaker, "text": stripped.split(":", 1)[1].strip()})
    return turns


def _sentences(text: str) -> list[str]:
    compact = " ".join((text or "").split())
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+", compact) if part.strip()]


def _first(items: list[str]) -> str:
    return next((item for item in items if item.strip()), PLACEHOLDER)


def _complete(text: str) -> str:
    return "complete" if text and text != PLACEHOLDER else "missing"
