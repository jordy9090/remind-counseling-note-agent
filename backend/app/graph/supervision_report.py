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

SECTION_GUIDANCE = {
    "A-1": ["호소문제와 연결된 성별·나이·학력·거주형태 등 사실정보만 기록하고 식별 가능한 세부정보는 제거합니다."],
    "A-2": ["자발·비자발 여부, 의뢰 경로, 상담 필요성에 대한 동의 여부를 구분해 기록합니다."],
    "A-3": ["가능하면 내담자가 실제로 표현한 언어를 보존합니다."],
    "A-4": ["시기, 상담 계기, 주요 내용, 성과에 대한 내담자의 인식을 구분합니다."],
    "A-5": ["가족 구성, 주요 인물의 특징과 영향을 구분하며 근거가 없으면 가계도나 관계를 만들지 않습니다."],
    "A-6": ["관찰된 행동·외양과 상담자의 인상 또는 해석을 분리합니다."],
    "A-7": ["검사명, 기관·장소, 실시일·해석일, 점수, 주요 해석과 과거 검사 대비 변화를 확인합니다."],
    "A-8": ["면담·행동관찰·검사에서 확인된 개인 및 환경 보호요인만 기록합니다."],
    "B-1": ["유발·유지요인과 기존 대처, 대처의 효과성을 확인된 근거 중심으로 기술합니다."],
    "B-2": ["합의된 목표, 상담자의 임상적 목표, 목표 달성을 위한 구체적 전략을 각각 구분합니다."],
    "B-3": ["상담사가 수퍼비전에서 도움받고 싶은 점을 구체적으로 직접 수정합니다."],
    "C-1": ["최대 회기 수와 상담일·시간·주제, 취소·지각·결석 및 이전 수퍼비전을 시간순으로 기록합니다."],
    "C-2": ["완전 축어록은 원문과 침묵시간을 보존하고, 축약 요약은 사건·인지·감정·행동·개입·반응을 구분합니다."],
}


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
        evidence[f"previous_session.{item['session_number']}"] = {"label": f"{item['session_number']}회기 이전 요약", "text": item["summary"], "sourceType": "회기요약", "sessionNumber": str(item["session_number"])}
    for turn in normalized["transcript_turns"]:
        evidence[turn["turnId"]] = {"label": f"{context['session_number']}회기 축어록", "text": turn["text"], "sourceType": "축어록", "sessionNumber": str(context["session_number"])}
    for index, text in enumerate(normalized["memo_items"], 1):
        evidence[f"counselor_memo.{index}"] = {"label": "상담자 메모", "text": text, "sourceType": "상담자 메모", "sessionNumber": str(context["session_number"])}
    for index, text in enumerate(normalized["nonverbal_items"], 1):
        evidence[f"nonverbal_notes.{index}"] = {"label": "비언어 관찰", "text": text, "sourceType": "기본정보", "sessionNumber": str(context["session_number"])}
    for key, label, text in (
        ("psychological_test_summary", "심리검사 입력 요약", normalized["psychological_test_summary"]),
        ("counseling_goal", "상담 목표", normalized["counseling_goal"]),
        ("key_issue_tags", "핵심 이슈 태그", ", ".join(normalized["key_issue_tags"])),
    ):
        if text:
            evidence[key] = {"label": label, "text": text, "sourceType": "심리검사" if key == "psychological_test_summary" else "기본정보", "sessionNumber": str(context["session_number"])}
    if summary:
        for key in ("session_theme", "presenting_problem", "session_content", "counselor_intervention", "client_response", "reflection", "next_plan"):
            evidence[f"current_summary.{key}"] = {"label": "현재 회기 생성 요약", "text": getattr(summary, key).text, "sourceType": "회기요약", "sessionNumber": str(context["session_number"])}
    return {"evidence_index": evidence}


def generate_section_A(state: SupervisionReportState) -> dict[str, Any]:
    context, normalized = state["case_context"], state["normalized_inputs"]
    summary = context.get("current_summary")
    client_turns = [turn for turn in normalized["transcript_turns"] if turn["speaker"] == "client"]
    problem = (
        "\n".join(f"“{turn['text']}”" for turn in client_turns[:3])
        if client_turns else _soften_clinical_language(summary.presenting_problem.text) if summary else PLACEHOLDER
    )
    problem_refs = [turn["turnId"] for turn in client_turns[:3]] or _existing(state, "current_summary.presenting_problem")
    observations = " ".join(normalized["nonverbal_items"]) or PLACEHOLDER
    psych = normalized["psychological_test_summary"] or PLACEHOLDER
    return {"sections_a": [
        _heading("A", "A. 내담자 기본 정보"),
        _missing_section("A-1", "A-1. 인적사항", ["비식별 인적사항"]),
        _missing_section("A-2", "A-2. 상담신청경위", ["신청·의뢰 경로", "자발성 및 상담 동의"]),
        _section("A-3", "A-3. 주 호소문제", [_paragraph("A-3.p1", problem, problem_refs, evidence_status="direct" if client_turns else "ai_organized")], _complete(problem)),
        _missing_section("A-4", "A-4. 이전 상담 경험", ["이전 상담 시기·계기·내용·성과 인식"]),
        _missing_section("A-5", "A-5. 가족관계", ["가족 구성", "주요 인물 특징과 영향"]),
        _section("A-6", "A-6. 인상 및 행동특성", [_paragraph("A-6.p1", observations, _prefix(state, "nonverbal_notes."), review_status="needs_human_input" if observations == PLACEHOLDER else "unchecked", evidence_status="missing" if observations == PLACEHOLDER else "direct", missing_inputs=["행동관찰 기록"] if observations == PLACEHOLDER else [])], _complete(observations)),
        _section("A-7", "A-7. 심리검사 결과 및 주요 해석내용", [_paragraph("A-7.p1", psych, _existing(state, "psychological_test_summary"), ["검사 해석과 임상 판단은 상담사가 원자료와 대조해야 합니다."], "needs_human_input", evidence_status="clinical_review" if psych != PLACEHOLDER else "missing", missing_inputs=["검사명·점수·실시일·해석일·원자료"] if psych == PLACEHOLDER else [])], "partial" if psych != PLACEHOLDER else "missing"),
        _missing_section("A-8", "A-8. 내담자 강점 및 자원", ["근거가 확인된 개인·환경 보호요인"]),
    ]}


def generate_section_B(state: SupervisionReportState) -> dict[str, Any]:
    request, normalized = state["request"], state["normalized_inputs"]
    agreed_goal = request.agreed_counseling_goal or normalized["counseling_goal"] or PLACEHOLDER
    clinical_goal = request.clinical_counseling_goal or PLACEHOLDER
    strategy = request.counseling_strategy or PLACEHOLDER
    supervision_request = request.supervision_request or PLACEHOLDER
    return {"sections_b": [
        _heading("B", "B. 내담자 문제의 이해와 상담방향성"),
        _missing_section("B-1", "B-1. 내담자 이해 및 상담목표", ["유발·유지요인과 기존 대처의 효과성에 대한 확인된 자료"]),
        _section("B-2", "B-2. 상담목표와 전략", [
            _paragraph("B-2.agreed-goal", agreed_goal, _existing(state, "counseling_goal"), review_status="needs_human_input", label="내담자와 합의한 목표", evidence_status="clinical_review" if agreed_goal != PLACEHOLDER else "missing", missing_inputs=["내담자와 합의한 목표"] if agreed_goal == PLACEHOLDER else []),
            _paragraph("B-2.clinical-goal", clinical_goal, [], review_status="needs_human_input", label="상담자의 임상적 목표", evidence_status="clinical_review" if clinical_goal != PLACEHOLDER else "missing", missing_inputs=["상담자의 임상적 목표"] if clinical_goal == PLACEHOLDER else []),
            _paragraph("B-2.strategy", strategy, [], review_status="needs_human_input", label="상담전략", evidence_status="clinical_review" if strategy != PLACEHOLDER else "missing", missing_inputs=["목표 달성을 위한 구체적 개입 전략"] if strategy == PLACEHOLDER else []),
        ], "partial" if any(value != PLACEHOLDER for value in (agreed_goal, clinical_goal, strategy)) else "missing"),
        _section("B-3", "B-3. 수퍼비전을 통해 도움 받고 싶은 점", [_paragraph("B-3.p1", supervision_request, [], review_status="needs_human_input", evidence_status="clinical_review" if supervision_request != PLACEHOLDER else "missing", missing_inputs=["상담사가 직접 작성할 수퍼비전 요청"] if supervision_request == PLACEHOLDER else [])], _complete(supervision_request)),
    ]}


def generate_section_C(state: SupervisionReportState) -> dict[str, Any]:
    request, context, normalized = state["request"], state["case_context"], state["normalized_inputs"]
    summary = context.get("current_summary")
    rows = _progress_rows(request, context, normalized, summary)
    transcript = [SupervisionSpeakerTurn(**turn) for turn in normalized["transcript_turns"]]
    max_sessions = f"{request.maximum_sessions}회기" if request.maximum_sessions else PLACEHOLDER
    content_blocks: list[SupervisionContentBlock] = []
    if request.transcript_mode == "full" and transcript:
        content_blocks.append(SupervisionContentBlock(id="C-2.transcript", type="transcript", label="완전 축어록", speakerTurns=transcript, evidenceIds=[turn.turnId for turn in transcript], reviewStatus="needs_human_input", evidenceStatus="direct", warnings=["원문 발화와 침묵시간을 제출 전 대조하세요."]))
    else:
        content_blocks.append(SupervisionContentBlock(id="C-2.summary", type="table", label="회기 축약 요약", rows=[{
            "주요 사건": _soften_clinical_language(summary.session_content.text) if summary else PLACEHOLDER,
            "인지적 평가": PLACEHOLDER,
            "관련 감정": PLACEHOLDER,
            "행동 반응": PLACEHOLDER,
            "상담자의 개입": _soften_clinical_language(summary.counselor_intervention.text) if summary else PLACEHOLDER,
            "내담자의 반응": _soften_clinical_language(summary.client_response.text) if summary else PLACEHOLDER,
        }], evidenceIds=_existing(state, "current_summary.session_content", "current_summary.counselor_intervention", "current_summary.client_response"), reviewStatus="needs_human_input", evidenceStatus="ai_organized" if summary else "missing", missingInputs=[] if summary else ["회기요약 또는 축어록"]))
    content_blocks.append(SupervisionContentBlock(id="C-2.reflection", type="reflection_box", label="상담자 reflection", text=_soften_clinical_language(summary.reflection.text) if summary else PLACEHOLDER, evidenceIds=_existing(state, "current_summary.reflection"), reviewStatus="needs_human_input", evidenceStatus="clinical_review" if summary and summary.reflection.text != PLACEHOLDER else "missing", missingInputs=["상담자의 실제 내적 경험과 개입 의도"] if not summary or summary.reflection.text == PLACEHOLDER else [], warnings=["상담자의 내적 경험과 개입 방향은 회기 본문과 분리해 검토합니다."]))
    return {"sections_c": [
        _heading("C", "C. 상담진행 과정과 상담내용"),
        _section("C-1", "C-1. 상담진행 과정 및 회기주제", [
            _paragraph("C-1.maximum", max_sessions, [], review_status="needs_human_input", label="최대 상담 가능 회기 수", evidence_status="direct" if request.maximum_sessions else "missing", missing_inputs=["최대 상담 가능 회기 수"] if not request.maximum_sessions else []),
            SupervisionContentBlock(id="C-1.table", type="table", label="회기 진행표", rows=rows, evidenceIds=[*_prefix(state, "previous_session."), *_existing(state, "current_summary.session_theme")], reviewStatus="needs_human_input", evidenceStatus="ai_organized" if rows else "missing", missingInputs=["회기별 상담일·소요시간·출결 사유"] if rows else ["회기 진행 기록"]),
        ], "partial" if rows else "missing"),
        _section("C-2", "C-2. 상담회기 내용", content_blocks, "partial" if summary or transcript else "missing"),
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
            if block.text and block.text != PLACEHOLDER and not block.evidenceIds and block.evidenceStatus == "ai_organized":
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
    return SupervisionReportSection(
        id=section_id,
        title=title,
        level=2,
        contentBlocks=blocks,
        status=status,
        guidance=SECTION_GUIDANCE.get(section_id, []),
    )


def _paragraph(
    block_id: str,
    text: str,
    refs: list[str],
    warnings: list[str] | None = None,
    review_status: str = "unchecked",
    *,
    label: str | None = None,
    evidence_status: str = "ai_organized",
    missing_inputs: list[str] | None = None,
) -> SupervisionContentBlock:
    return SupervisionContentBlock(
        id=block_id,
        type="placeholder" if text == PLACEHOLDER else "paragraph",
        text=text or PLACEHOLDER,
        evidenceIds=refs,
        aiGenerated=True,
        demoValue=False,
        reviewStatus=review_status,
        warnings=warnings or [],
        label=label,
        evidenceStatus=evidence_status,
        missingInputs=missing_inputs or [],
    )


def _missing_section(section_id: str, title: str, missing_inputs: list[str]) -> SupervisionReportSection:
    return _section(
        section_id,
        title,
        [_paragraph(
            f"{section_id}.p1",
            PLACEHOLDER,
            [],
            [f"부족한 입력: {', '.join(missing_inputs)}", "제공된 자료에 없는 내용은 생성하지 않았습니다."],
            "needs_human_input",
            evidence_status="missing",
            missing_inputs=missing_inputs,
        )],
        "missing",
    )


def _progress_rows(request: SupervisionReportRequest, context: dict[str, Any], normalized: dict[str, Any], summary: SessionSummaryDraft | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if request.session_events:
        for event in request.session_events:
            status_labels = {"completed": "상담", "cancelled": "취소", "late": "지각", "absent": "결석", "no_show": "No-show"}
            status = status_labels[event.attendance_status]
            if event.attendance_reason:
                status = f"{status}: {event.attendance_reason}"
            rows.append({
                "회기": f"{event.session_number}회기" if event.session_number else "-",
                "상담일": event.session_date or PLACEHOLDER,
                "소요시간": f"{event.duration_minutes}분" if event.duration_minutes else PLACEHOLDER,
                "회기 주제": event.topic or PLACEHOLDER,
                "취소·지각·결석": status,
                "이전 수퍼비전": "",
            })
    else:
        for item in normalized["previous_sessions"]:
            rows.append({
                "회기": f"{item['session_number']}회기",
                "상담일": item.get("date") or PLACEHOLDER,
                "소요시간": PLACEHOLDER,
                "회기 주제": _soften_clinical_language(item["summary"]),
                "취소·지각·결석": "",
                "이전 수퍼비전": "",
            })
        current_topic = _soften_clinical_language(summary.session_theme.text) if summary else _first(normalized["memo_items"])
        rows.append({
            "회기": f"{context['session_number']}회기",
            "상담일": context["session_date"] or PLACEHOLDER,
            "소요시간": PLACEHOLDER,
            "회기 주제": current_topic,
            "취소·지각·결석": "",
            "이전 수퍼비전": "",
        })
    for previous in request.previous_supervisions:
        rows.append({
            "회기": "수퍼비전",
            "상담일": previous.supervision_date or PLACEHOLDER,
            "소요시간": "-",
            "회기 주제": "-",
            "취소·지각·결석": "-",
            "이전 수퍼비전": previous.feedback or PLACEHOLDER,
        })
    return sorted(rows, key=lambda row: (row["상담일"] == PLACEHOLDER, row["상담일"], row["회기"]))


def _existing(state: SupervisionReportState, *refs: str) -> list[str]:
    return [ref for ref in refs if ref in state["evidence_index"]]


def _prefix(state: SupervisionReportState, prefix: str) -> list[str]:
    return [ref for ref in state["evidence_index"] if ref.startswith(prefix)]


def _parse_previous_sessions(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"(?:^|\n)\s*(\d+)회기(?:\s*\(([^)]*)\))?\s*:\s*(.*?)(?=\n\s*\d+회기(?:\s*\(|\s*:)|$)", re.DOTALL)
    return [{"session_number": int(match.group(1)), "date": (match.group(2) or "").strip(), "summary": " ".join(match.group(3).split())} for match in pattern.finditer(text or "")]


def _parse_transcript(text: str) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(("Cl:", "내담자:", "Client:")):
            speaker = "client"
        elif stripped.startswith(("C:", "상담자:", "Counselor:")):
            speaker = "counselor"
        else:
            continue
        body = stripped.split(":", 1)[1].strip()
        silence_match = re.search(r"\(\s*침묵\s*(\d+)\s*초\s*\)", body)
        turn: dict[str, Any] = {
            "turnId": f"transcript.turn_{len(turns) + 1}",
            "speaker": speaker,
            "text": body,
        }
        if silence_match:
            turn["silenceSeconds"] = int(silence_match.group(1))
        turns.append(turn)
    return turns


def _sentences(text: str) -> list[str]:
    compact = " ".join((text or "").split())
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+", compact) if part.strip()]


def _soften_clinical_language(text: str) -> str:
    """Keep AI-organized clinical prose tentative without altering direct transcript quotes."""
    softened = text or ""
    replacements = {
        "관련되어 있다고 판단하였다.": "관련되어 있을 가능성이 있으며 추후 탐색이 필요하다.",
        "급성 위험도는 낮은 수준으로 판단하였다.": "현재 입력 자료에서는 급성 위험 신호가 직접 확인되지 않았으나 상담자의 위험도 확인이 필요하다.",
        "패턴을 확인하였다": "패턴일 가능성이 있어 추후 탐색이 필요하다",
        "판단하였다": "가능성을 고려하였으며 추후 확인이 필요하다",
    }
    for source, replacement in replacements.items():
        softened = softened.replace(source, replacement)
    return softened


def _first(items: list[str]) -> str:
    return next((item for item in items if item.strip()), PLACEHOLDER)


def _complete(text: str) -> str:
    return "complete" if text and text != PLACEHOLDER else "missing"
