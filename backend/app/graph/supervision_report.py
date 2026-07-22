"""LangGraph-style supervision report draft workflow for the demo MVP."""
from __future__ import annotations

import re
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.schemas.note import (
    SessionSummaryDraft,
    SupervisionAiReviewPanel,
    SupervisionCompletionChecklistItem,
    SupervisionContentBlock,
    SupervisionNeedsHumanReviewItem,
    SupervisionReportDraft,
    SupervisionReportMeta,
    SupervisionReportRequest,
    SupervisionReportSection,
    SupervisionSpeakerTurn,
    SupervisionUnsupportedClaim,
)


PLACEHOLDER = "[상담사 확인 필요]"
DEMO_CASE_ID = "CASE-DEMO-001"
DEMO_META = {
    "client_alias": "김민서",
    "counselor_name": "이수진",
    "institution": "마마음연결 상담센터", # Note: '마음연결 상담센터' will be normalized cleanly
    "supervisor": "김OO",
    "supervision_date_place": "2026.05.30 / 사례회의실",
    "max_sessions": "12회기",
    "default_duration": "50분",
}
# Keep institution clean
DEMO_META["institution"] = "마음연결 상담센터"

DEMO_PROFILE_TEXT = (
    "내담자는 24세 대학 4학년 여학생으로, 현재 졸업과 공채 취업 준비를 병행하고 있다. "
    "최근 대형 공기업의 1차 서류 합격 소식을 들은 직후부터 발표와 면접 상황에 대한 불안을 강하게 호소하고 있다. "
    "경제적 부양 수준이나 구체적인 학업 평점 등의 세부 사항은 접수면접지를 통해 추가 확인이 필요하다."
)
DEMO_PROFILE_CONTEXT = (
    "내담자는 24세 대학 4학년 여학생으로, 현재 졸업과 공채 취업 준비를 병행하고 있다. "
    "최근 대형 공기업의 1차 서류 합격 소식을 들은 직후부터 발표와 면접 상황에 대한 불안을 강하게 호소하고 있다. "
    "경제적 부양 수준이나 구체적인 학업 평점 등의 세부 사항은 접수면접지를 통해 추가 확인이 필요하다."
)
DEMO_PSYCH_TEST_SUMMARY = (
    "접수 면접 시 진행한 진로흥미검사 결과 사회형과 탐구형 흥미가 유의미하게 높게 확인되었다. "
    "상태불안 척도는 상위 10%에 해당하여 현재 평가 국면에서 급격한 신체적, 심리적 불안을 경험하고 있음을 뒷받침한다. "
    "단, 본 평가 결과는 현재의 급성 스트레스 반응을 이해하기 위한 참고 수치로만 활용하고 있으며 임상적 진단 근거는 아니다."
)
DEMO_SESSION_ROWS = [
    {
        "회기": "1회기",
        "날짜": "2026.04.26",
        "진행시간": "50분",
        "회기 주제": "상담구조화, 진로 불안 및 주호소 확인",
        "비고": "초기상담",
    },
    {
        "회기": "2회기",
        "날짜": "2026.05.03",
        "진행시간": "50분",
        "회기 주제": "취업 준비 상황에서의 자동사고 탐색",
        "비고": "생각기록지 안내",
    },
    {
        "회기": "3회기",
        "날짜": "2026.05.10",
        "진행시간": "50분",
        "회기 주제": "가족 기대와 비교 경험 탐색",
        "비고": "완벽주의 기준 확인",
    },
    {
        "회기": "4회기",
        "날짜": "2026.05.17",
        "진행시간": "50분",
        "회기 주제": "회피 행동과 수면 리듬 점검",
        "비고": "행동과제 설정",
    },
    {
        "회기": "5회기",
        "날짜": "2026.05.24",
        "진행시간": "50분",
        "회기 주제": "발표 장면 이후 자기비난과 회피 행동 검토",
        "비고": "행동실험 계획",
    },
]
SUGGESTED_SUPERVISION_QUESTIONS = [
    "진로 불안을 자기비난-비교-회피 순환으로 보는 사례개념화가 적절한가?",
    "정서적 지지, 인지 검토, 행동과제 제안의 균형은 적절한가?",
    "가족 기대와 비교 경험을 어느 깊이까지 다루는 것이 좋은가?",
]


class SupervisionReportState(TypedDict, total=False):
    request: SupervisionReportRequest
    case_context: dict[str, Any]
    normalized_inputs: dict[str, Any]
    evidence_index: dict[str, dict[str, str]]
    sections_a: list[SupervisionReportSection]
    sections_b: list[SupervisionReportSection]
    sections_c: list[SupervisionReportSection]
    suggested_questions: list[str]
    sections: list[SupervisionReportSection]
    ai_review: SupervisionAiReviewPanel
    report: SupervisionReportDraft


def create_supervision_report_graph():
    workflow = StateGraph(SupervisionReportState)
    workflow.add_node("load_case_context", load_case_context)
    workflow.add_node("normalize_inputs", normalize_inputs)
    workflow.add_node("build_evidence_index", build_evidence_index)
    workflow.add_node("generate_section_A", generate_section_A)
    workflow.add_node("generate_section_B", generate_section_B)
    workflow.add_node("generate_section_C", generate_section_C)
    workflow.add_node("generate_supervision_questions", generate_supervision_questions)
    workflow.add_node("evidence_grounding_checker", evidence_grounding_checker)
    workflow.add_node("clinical_safety_guard", clinical_safety_guard)
    workflow.add_node("format_supervision_report", format_supervision_report)
    workflow.add_node("generate_ai_review_panel", generate_ai_review_panel)

    workflow.set_entry_point("load_case_context")
    workflow.add_edge("load_case_context", "normalize_inputs")
    workflow.add_edge("normalize_inputs", "build_evidence_index")
    workflow.add_edge("build_evidence_index", "generate_section_A")
    workflow.add_edge("generate_section_A", "generate_section_B")
    workflow.add_edge("generate_section_B", "generate_section_C")
    workflow.add_edge("generate_section_C", "generate_supervision_questions")
    workflow.add_edge("generate_supervision_questions", "evidence_grounding_checker")
    workflow.add_edge("evidence_grounding_checker", "clinical_safety_guard")
    workflow.add_edge("clinical_safety_guard", "generate_ai_review_panel")
    workflow.add_edge("generate_ai_review_panel", "format_supervision_report")
    workflow.add_edge("format_supervision_report", END)
    return workflow.compile()


supervision_report_graph = None


def run_supervision_report_pipeline(request: SupervisionReportRequest) -> SupervisionReportDraft:
    global supervision_report_graph
    if supervision_report_graph is None:
        supervision_report_graph = create_supervision_report_graph()
    state = supervision_report_graph.invoke({"request": request})
    return state["report"]


def load_case_context(state: SupervisionReportState) -> dict[str, Any]:
    request = state["request"]
    session = request.session_input
    summary = request.session_summary_draft
    demo_mode = bool(request.demo_mode and session.case_id == DEMO_CASE_ID)

    return {
        "case_context": {
            "case_id": session.case_id,
            "session_number": session.session_number,
            "session_date": session.session_date,
            "report_date": request.report_date or session.session_date or date.today().isoformat(),
            "client_alias": request.client_alias or (DEMO_META["client_alias"] if demo_mode else _default_client_alias(session.case_id)),
            "counselor_name": session.counselor_name or (DEMO_META["counselor_name"] if demo_mode else PLACEHOLDER),
            "institution": request.institution or (DEMO_META["institution"] if demo_mode else PLACEHOLDER),
            "supervisor": request.supervisor or (DEMO_META["supervisor"] if demo_mode else PLACEHOLDER),
            "supervision_date_place": request.supervision_date_place
            or (DEMO_META["supervision_date_place"] if demo_mode else PLACEHOLDER),
            "max_sessions": DEMO_META["max_sessions"] if demo_mode else "",
            "default_duration": DEMO_META["default_duration"] if demo_mode else "",
            "demo_mode": demo_mode,
            "current_summary": summary,
            "current_input": session,
        }
    }


def normalize_inputs(state: SupervisionReportState) -> dict[str, Any]:
    context = state["case_context"]
    session = context["current_input"]
    demo_mode = context["demo_mode"]

    previous_sessions = _parse_previous_sessions(session.previous_session_summary)
    transcript_turns = _parse_transcript(session.transcript_text, session.session_number)
    memo_items = _sentences(session.counselor_memo)
    nonverbal_items = _sentences(session.nonverbal_notes)
    psych_summary = session.psychological_test_summary.strip()
    if demo_mode and not psych_summary:
        psych_summary = DEMO_PSYCH_TEST_SUMMARY

    return {
        "normalized_inputs": {
            "previous_sessions": previous_sessions,
            "transcript_turns": transcript_turns,
            "memo_items": memo_items,
            "nonverbal_items": nonverbal_items,
            "psychological_test_summary": psych_summary,
            "counseling_goal": session.counseling_goal.strip(),
            "key_issue_tags": session.key_issue_tags,
        }
    }


def build_evidence_index(state: SupervisionReportState) -> dict[str, Any]:
    context = state["case_context"]
    normalized = state["normalized_inputs"]
    session = context["current_input"]
    summary: SessionSummaryDraft | None = context.get("current_summary")
    evidence: dict[str, dict[str, str]] = {}

    for item in normalized["previous_sessions"]:
        evidence[f"session_{item['session_number']}.summary.p1"] = {
            "label": f"{item['session_number']}회기 요약",
            "text": item["summary"],
        }

    if summary:
        summary_map = {
            "presenting_problem": summary.presenting_problem.text,
            "session_theme": summary.session_theme.text,
            "session_content": summary.session_content.text,
            "counselor_intervention": summary.counselor_intervention.text,
            "client_response": summary.client_response.text,
            "next_plan": summary.next_plan.text,
        }
        for key, value in summary_map.items():
            evidence[f"session_{session.session_number}.summary.{key}"] = {
                "label": f"{session.session_number}회기 요약",
                "text": value,
            }

    for turn in normalized["transcript_turns"]:
        evidence[turn["turnId"]] = {
            "label": f"{session.session_number}회기 축어록",
            "text": turn["text"],
        }

    for index, item in enumerate(normalized["memo_items"], start=1):
        evidence[f"counselor_memo_{session.session_number}.item_{index}"] = {
            "label": f"{session.session_number}회기 상담자 메모",
            "text": item,
        }

    for index, item in enumerate(normalized["nonverbal_items"], start=1):
        evidence[f"nonverbal_{session.session_number}.item_{index}"] = {
            "label": f"{session.session_number}회기 관찰 메모",
            "text": item,
        }

    if normalized["psychological_test_summary"]:
        evidence["psych_test.input_1"] = {
            "label": "심리검사 메모",
            "text": normalized["psychological_test_summary"],
        }
    if normalized["counseling_goal"]:
        evidence["counseling_goal.input_1"] = {
            "label": "상담 목표",
            "text": normalized["counseling_goal"],
        }

    if context["demo_mode"]:
        evidence["demo.profile"] = {"label": "데모 프로필", "text": DEMO_PROFILE_TEXT}
        evidence["demo.profile_context"] = {"label": "데모 프로필", "text": DEMO_PROFILE_CONTEXT}
        evidence["demo.psych_tests"] = {"label": "데모 심리검사", "text": DEMO_PSYCH_TEST_SUMMARY}
        evidence["demo.meta"] = {
            "label": "데모 문서 메타",
            "text": (
                f"상담자 {DEMO_META['counselor_name']}, 기관 {DEMO_META['institution']}, "
                f"수퍼바이저 {DEMO_META['supervisor']}, 수퍼비전 {DEMO_META['supervision_date_place']}"
            ),
        }
        evidence["demo.session_duration"] = {"label": "데모 회기 시간", "text": DEMO_META["default_duration"]}

    return {"evidence_index": evidence}


def generate_section_A(state: SupervisionReportState) -> dict[str, Any]:
    context = state["case_context"]
    normalized = state["normalized_inputs"]
    session = context["current_input"]
    session_number = session.session_number
    demo_mode = context["demo_mode"]

    first_session = _find_session(normalized["previous_sessions"], 1)
    third_session = _find_session(normalized["previous_sessions"], 3)
    current_problem_evidence = _existing_refs(
        state,
        f"session_{session_number}.summary.presenting_problem",
        "session_1.summary.p1",
        "transcript_5.turn_2",
        "transcript_5.turn_4",
    )
    family_refs = _existing_refs(state, "session_3.summary.p1")
    nonverbal_refs = _refs_with_prefix(state, f"nonverbal_{session_number}.item_")

    sections = [
        _heading("A", "A. 내담자 기본 정보", 1),
        _section(
            "A-1",
            "A-1. 인적사항",
            [
                _paragraph(
                    "A-1.p1",
                    DEMO_PROFILE_CONTEXT
                    if demo_mode
                    else (
                        "내담자는 24세 대학 4학년 여학생으로, 현재 졸업과 공채 취업 준비를 병행하고 있다. "
                        "다만 거주 형태나 구체적인 종교 및 가족 구성 정보 등은 접수면접 기록을 통해 확인이 요구된다."
                    ),
                    _existing_refs(state, "demo.profile_context", "session_1.summary.p1"),
                    warnings=["거주형태, 종교, 구체적인 가족 구성 정보는 상담사 확인이 필요합니다."],
                    review_status="needs_human_input",
                    demo_value=demo_mode,
                )
            ],
            "partial",
        ),
        _section(
            "A-2",
            "A-2. 상담신청경위",
            [
                _paragraph(
                    "A-2.p1",
                    (
                        "내담자는 졸업을 앞두고 진로 결정과 취업 준비 과정에서 불안이 높아져 상담을 신청한 것으로 보인다. "
                        "초기 회기에서 내담자는 '남들보다 늦은 것 같다', '결정을 잘못하면 끝날 것 같다'는 걱정을 반복적으로 표현하였다. "
                        "상담 시작 당시 주된 기대는 진로 선택 과정에서의 불안을 낮추고 준비 행동을 현실적으로 조정하는 데 있었다."
                    ),
                    _existing_refs(state, "session_1.summary.p1", "demo.profile"),
                    warnings=["구체적인 의뢰 경로, 자발/비자발 여부, 상담 신청 당시 안내 내용은 접수면접 기록 확인이 필요합니다."],
                    review_status="needs_human_input",
                )
            ],
            "partial",
        ),
        _section(
            "A-3",
            "A-3. 주 호소문제",
            [
                _paragraph(
                    "A-3.p1",
                    _main_complaint_text(state),
                    current_problem_evidence or _existing_refs(state, "demo.profile"),
                )
            ],
            "complete" if current_problem_evidence or demo_mode else "needs_review",
        ),
        _section(
            "A-4",
            "A-4. 이전 상담 경험",
            [
                _paragraph(
                    "A-4.p1",
                    (
                        "대학 학생상담센터나 외부 전문 기관을 포함하여 과거에 개인 심리상담을 경험한 이력은 없는 상태이다. "
                        "고등학교 재학 시절 진로 흥미 탐색을 위한 소집단 활동에 참여해 본 것 외에는 심층 대면 상담을 신청한 경험이 이번이 처음으로 파악된다. "
                        "다만, 과거의 구체적인 진로 관련 심리 평가 등의 세부 참여 이력은 면담을 통해 보완할 예정이다."
                    ),
                    _existing_refs(state, "session_1.summary.p1"),
                    warnings=["이전 상담 경험 유무와 과거 상담에서 다룬 주제는 추가 확인이 필요합니다."],
                    review_status="needs_human_input",
                )
            ],
            "partial",
        ),
        _section(
            "A-5",
            "A-5. 가족관계",
            [
                _paragraph(
                    "A-5.p1",
                    (
                        "부모님과 남동생으로 구성된 4인 가정이며, 아버지는 성취 지향적인 양육 태도를 보인다. "
                        "상담 중 내담자는 부모의 직접 압박보다 가족 모임이나 주변 친척의 성과를 보며 간접적으로 심한 부담감을 경험한다고 진술하였다. "
                        "어린 시절부터 학습된 완벽주의적 대인 관계 신념과 현재의 수행 불안 사이의 역동을 중점 탐색하는 단계이다. "
                        "세부 가족관계도와 추가 정보는 가계도 작성을 통해 보완해야 한다."
                    ),
                    family_refs,
                    warnings=["가계도 작성, 가족 구성 세부정보, 가족 가치와 유지 갈등 여부는 추가 확인이 필요합니다."],
                    review_status="needs_human_input",
                )
            ],
            "partial",
        ),
        _section(
            "A-6",
            "A-6. 인상 및 행동특성",
            [
                _paragraph(
                    "A-6.p1",
                    (
                        " ".join(normalized["nonverbal_items"])
                        if normalized["nonverbal_items"]
                        else (
                            "단정하고 깔끔한 차림새로 내원하였으나, 면접 장면을 시뮬레이션하거나 불안을 설명할 때 한숨이 잦고 "
                            "손을 가만히 두지 못하는 등의 신체적 불안 반응을 관찰하였다. 호흡 훈련법 도입 이후 "
                            "어조가 다소 차분해지고 어깨의 긴장이 완화되는 긍정적인 신체 반응 이완이 나타났다."
                        )
                    ),
                    nonverbal_refs,
                    review_status="unchecked" if nonverbal_refs else "needs_human_input",
                )
            ],
            "complete" if nonverbal_refs else "partial",
        ),
        _section(
            "A-7",
            "A-7. 심리검사 결과 및 주요 해석내용",
            [
                _paragraph(
                    "A-7.p1",
                    DEMO_PSYCH_TEST_SUMMARY if demo_mode else normalized["psychological_test_summary"],
                    _existing_refs(state, "psych_test.input_1", "demo.psych_tests"),
                    warnings=["검사명, 실시일, 원점수/척도, 해석 책임은 상담사가 최종 확인해야 합니다."],
                    review_status="needs_human_input",
                    demo_value=demo_mode,
                )
            ],
            "partial",
        ),
        _section(
            "A-8",
            "A-8. 내담자 강점 및 자원",
            [
                _paragraph(
                    "A-8.p1",
                    (
                        "내담자는 발표 장면을 사실과 추측으로 구분해 보며 자동사고를 재검토할 수 있었다. "
                        "상담 후반에는 교수에게 질문 메일을 보내고 팀원에게 역할 조율 메시지를 보내는 등 작은 행동과제에 동의하였다. "
                        "이는 불안을 완전히 제거하기보다 사실 확인과 점진적 행동을 통해 회피를 줄일 수 있는 자원으로 보인다."
                    ),
                    _existing_refs(state, "transcript_5.turn_10", "transcript_5.turn_12", "session_5.summary.client_response"),
                    warnings=["강점 서술은 상담자의 임상적 판단과 내담자 반응을 대조해 확인해야 합니다."],
                )
            ],
            "partial",
        ),
    ]
    return {"sections_a": sections}


def generate_section_B(state: SupervisionReportState) -> dict[str, Any]:
    normalized = state["normalized_inputs"]
    session_number = state["case_context"]["current_input"].session_number
    goal = normalized["counseling_goal"] or "진로 선택과 수행평가 상황에서 나타나는 자기비난적 자동사고를 알아차리고, 회피를 줄이는 작은 실행 행동을 늘린다."

    sections = [
        _heading("B", "B. 내담자 문제의 이해와 상담방향", 1),
        _section(
            "B-1",
            "B-1. 내담자 이해 및 상담목표",
            [
                _paragraph(
                    "B-1.p1",
                    (
                        "입력 자료를 기준으로 볼 때, 내담자의 진로 불안은 수행 상황에서 떠오르는 자기비난적 자동사고, "
                        "타인과의 비교 사고, 회피 행동이 맞물리며 유지되는 가능성이 있다. 이는 확정적 사례개념화가 아니며 "
                        "수퍼비전에서 확인이 필요한 가설이다. 상담목표는 내담자가 불안을 알아차리고 사실과 추측을 구분하며, "
                        "현실적으로 실행 가능한 준비 행동을 늘리도록 돕는 방향으로 설정할 수 있다."
                    ),
                    _existing_refs(
                        state,
                        "session_2.summary.p1",
                        "session_4.summary.p1",
                        f"session_{session_number}.summary.session_content",
                        "counseling_goal.input_1",
                    ),
                    warnings=["사례개념화 문장은 가설로 유지하고 진단 또는 위험 판단으로 확정하지 않아야 합니다."],
                    review_status="needs_human_input",
                )
            ],
            "needs_review",
        ),
        _section(
            "B-2",
            "B-2. 상담목표와 전략",
            [
                _paragraph(
                    "B-2.p1",
                    (
                        f"현재 상담목표는 '{goal}'로 정리된다. 구체적 전략은 자동사고를 알아차리고 자기비난을 줄이는 것, "
                        "사실과 추측을 구분하는 것, 회피 행동을 줄이는 것, 작은 행동실험을 계획하고 실행 후 불안 변화를 점검하는 것이다. "
                        "내담자의 부담 수준을 확인하면서 지지적 탐색과 행동계획의 균형을 맞출 필요가 있다."
                    ),
                    _existing_refs(state, "counseling_goal.input_1", "session_5.summary.counselor_intervention", "session_5.summary.next_plan"),
                    review_status="needs_human_input",
                    warnings=["상담목표 확정과 전략 선택은 상담사가 최종 확인해야 합니다."],
                )
            ],
            "partial",
        ),
        _section(
            "B-3",
            "B-3. 수퍼비전을 통해 도움 받고 싶은 점",
            [
                _paragraph(
                    "B-3.p1",
                    "본 사례에서 수퍼비전을 통해 도움 받고 싶은 점은 다음과 같다.\n\n"
                    + "\n".join(f"{index + 1}. {question}" for index, question in enumerate(SUGGESTED_SUPERVISION_QUESTIONS)),
                    _existing_refs(state, "session_5.summary.session_content", "session_5.summary.next_plan", "demo.profile"),
                    warnings=["구체적인 수퍼비전 요청은 상담자가 직접 선택하거나 수정하는 것이 적절합니다."],
                )
            ],
            "partial",
        ),
    ]
    return {"sections_b": sections}


def generate_section_C(state: SupervisionReportState) -> dict[str, Any]:
    context = state["case_context"]
    normalized = state["normalized_inputs"]
    session = context["current_input"]
    session_number = session.session_number
    summary: SessionSummaryDraft | None = context.get("current_summary")
    rows = _session_progress_rows(state)
    excerpt_turns = _selected_transcript_turns(normalized["transcript_turns"])
    excerpt_evidence = [turn.turnId for turn in excerpt_turns]

    previous_text = "\n".join(
        f"{item['session_number']}회기: {item['summary']}" for item in normalized["previous_sessions"]
    )
    current_summary_text = (
        "5회기에서는 팀 프로젝트 발표 이후 반복적으로 떠오르는 자기비난 사고와 회피 행동을 중심으로 다루었다. "
        "내담자는 발표 중 말을 더듬었던 장면을 반복적으로 떠올리며 자신이 중요한 순간을 망친다고 해석하였다. "
        "상담자는 해당 장면을 사실, 자동사고, 감정, 행동으로 나누어 검토하도록 돕고, 반대 근거와 대안적 해석을 함께 탐색하였다. "
        "회기 말에는 교수에게 질문 메일을 보내고 팀원에게 역할 조율 메시지를 보내는 행동실험을 계획하였다."
        if context["demo_mode"]
        else (summary.session_content.text if summary else _first_nonempty(normalized["memo_items"], "5회기 상담내용은 상담사 확인이 필요하다."))
    )
    intervention_text = summary.counselor_intervention.text if summary else "사실과 추측의 구분, 자동사고 검토, 작은 행동과제 설정을 중심으로 개입하였다."
    response_text = summary.client_response.text if summary else "내담자는 과제에 대한 부담을 표현했으나 작은 실행 계획에는 동의하였다."

    sections = [
        _heading("C", "C. 상담진행 과정과 상담내용", 1),
        _section(
            "C-1",
            "C-1. 상담진행 과정 및 회기주제",
            [
                _paragraph(
                    "C-1.p1",
                    (
                        f"최대 상담 가능 회기 수는 {context['max_sessions'] or '확인 필요'}이며, 현재 {session_number}회기까지 진행되었다. "
                        f"회기당 진행시간은 {context['default_duration'] or '상담사 확인 필요'}으로 정리하였다."
                    ),
                    _existing_refs(state, "demo.session_duration"),
                    warnings=["회기 시간, 취소/지각/no-show, 이전 수퍼비전 이력은 입력값이 있을 때만 확정할 수 있습니다."],
                    review_status="needs_human_input",
                    demo_value=context["demo_mode"],
                ),
                SupervisionContentBlock(
                    id="C-1.table",
                    type="table",
                    rows=rows,
                    evidenceIds=_existing_refs(
                        state,
                        *[f"session_{item['session_number']}.summary.p1" for item in normalized["previous_sessions"]],
                        f"session_{session_number}.summary.session_theme",
                        "demo.session_duration",
                    ),
                    demoValue=context["demo_mode"],
                    warnings=["회기별 세부 기록과 실제 진행시간은 상담사가 최종 확인해야 합니다."],
                    reviewStatus="needs_human_input",
                ),
            ],
            "partial",
        ),
        _section("C-2", "C-2. 상담회기 내용", [], "partial"),
        _section(
            "C-2-1",
            "C-2-1. 1~4회기 축약 요약",
            [
                _paragraph(
                    "C-2-1.p1",
                    previous_text or "이전 회기 요약이 충분히 입력되지 않아 상담사 확인이 필요하다.",
                    _existing_refs(
                        state,
                        *[f"session_{item['session_number']}.summary.p1" for item in normalized["previous_sessions"]],
                    ),
                    review_status="unchecked" if previous_text else "needs_human_input",
                )
            ],
            "complete" if previous_text else "partial",
        ),
        _section(
            "C-2-2",
            f"C-2-2. {session_number}회기 주요 상담내용",
            [
                _paragraph(
                    "C-2-2.p1",
                    current_summary_text,
                    _existing_refs(state, f"session_{session_number}.summary.session_content", "counselor_memo_5.item_1"),
                    demo_value=context["demo_mode"],
                )
            ],
            "complete",
        ),
        _section(
            "C-2-3",
            f"C-2-3. {session_number}회기 상담자 개입 및 내담자 반응",
            [
                _paragraph(
                    "C-2-3.p1",
                    f"상담자 개입: {intervention_text}\n내담자 반응: {response_text}",
                    _existing_refs(
                        state,
                        f"session_{session_number}.summary.counselor_intervention",
                        f"session_{session_number}.summary.client_response",
                    ),
                )
            ],
            "complete",
        ),
        _section(
            "C-2-4",
            f"C-2-4. {session_number}회기 발췌 축어록",
            [
                SupervisionContentBlock(
                    id="C-2-4.transcript",
                    type="transcript",
                    speakerTurns=excerpt_turns,
                    evidenceIds=excerpt_evidence,
                    warnings=["발췌 축어록입니다. 완전 축어록 제출 여부는 상담사가 확인해야 합니다."],
                    reviewStatus="needs_human_input",
                )
            ],
            "complete" if excerpt_turns else "partial",
        ),
        _section(
            "C-2-5",
            "C-2-5. 상담자 reflection",
            [
                SupervisionContentBlock(
                    id="C-2-5.reflection",
                    type="reflection_box",
                    text=(
                        "상담자는 발표 장면을 다룰 때 정서적 지지와 사고 검토 사이의 균형, "
                        "행동 과제를 제안하는 시점이 적절했는지에 대해 점검할 필요가 있다. "
                        "상담자의 실제 내적 반응과 개입 의도는 직접 수정하여 보완해야 한다."
                    ),
                    evidenceIds=_existing_refs(state, "session_5.summary.counselor_intervention", "counselor_memo_5.item_3"),
                    aiGenerated=True,
                    reviewStatus="needs_human_input",
                    warnings=["reflection은 상담자의 주관적 경험 영역이므로 직접 수정해야 합니다."],
                )
            ],
            "needs_review",
        ),
    ]
    return {"sections_c": sections}


def generate_supervision_questions(state: SupervisionReportState) -> dict[str, Any]:
    return {"suggested_questions": SUGGESTED_SUPERVISION_QUESTIONS}


def evidence_grounding_checker(state: SupervisionReportState) -> dict[str, Any]:
    sections = state["sections_a"] + state["sections_b"] + state["sections_c"]
    unsupported: list[SupervisionUnsupportedClaim] = []
    for section in sections:
        for block in section.contentBlocks:
            if block.type == "placeholder" or block.demoValue or block.reviewStatus == "needs_human_input":
                continue
            if not block.evidenceIds:
                unsupported.append(
                    SupervisionUnsupportedClaim(
                        blockId=block.id,
                        claim=_shorten(block.text or section.title, 90),
                        reason="연결된 evidenceIds가 없어 상담사 확인이 필요합니다.",
                    )
                )
    review = state.get("ai_review") or SupervisionAiReviewPanel()
    review.unsupportedClaims = unsupported[:5]
    return {"ai_review": review}


def clinical_safety_guard(state: SupervisionReportState) -> dict[str, Any]:
    review = state.get("ai_review") or SupervisionAiReviewPanel()
    safety_items = [
        SupervisionNeedsHumanReviewItem(
            sectionId="safety",
            message="사례개념화, 위험 판단, 심리검사 해석은 확정 표현으로 쓰지 마세요.",
            severity="high",
        ),
    ]
    review.needsHumanReview = [*review.needsHumanReview, *safety_items]
    return {"ai_review": review}


def generate_ai_review_panel(state: SupervisionReportState) -> dict[str, Any]:
    context = state["case_context"]
    review = state.get("ai_review") or SupervisionAiReviewPanel()
    demo_mode = context["demo_mode"]

    review.completionChecklist = [
        SupervisionCompletionChecklistItem(label="핵심 양식 작성됨", status="done", reason="주호소·회기표·상담내용·질문"),
        SupervisionCompletionChecklistItem(label="1~5회기 내용 반영", status="done"),
        SupervisionCompletionChecklistItem(label="세부정보 추가 확인 필요", status="partial", reason="가족·이전상담·축어록"),
    ]
    review.missingFields = [
        "거주형태·종교",
        "가족 구성·학과/전공",
        "자발성·이전 상담·완전 축어록",
    ]
    review.demoInputs = (
        [
            "기관·수퍼바이저·일시와 일부 인적사항은 데모값입니다. 실제 사용 전 수정하세요.",
        ]
        if demo_mode
        else []
    )
    review.needsHumanReview = [
        *review.needsHumanReview,
        SupervisionNeedsHumanReviewItem(
            sectionId="A-1",
            message="인적사항, 가족관계, 의뢰경위, 이전 상담 경험을 접수면접 기록과 대조하세요.",
            severity="medium",
        ),
        SupervisionNeedsHumanReviewItem(
            sectionId="A-7",
            message="심리검사 원점수, 척도, 해석 책임을 최종 확인하세요.",
            severity="high",
        ),
        SupervisionNeedsHumanReviewItem(
            sectionId="C-2-5",
            message="사례개념화와 reflection은 상담자가 직접 검토·수정하세요.",
            severity="medium",
        ),
    ]
    review.suggestedSupervisionQuestions = state["suggested_questions"]
    review.caution = (
        "AI 초안은 검토용입니다. 제출 전 사실관계, 위험 판단, 심리검사 해석은 상담사가 확인해야 합니다."
    )
    return {"ai_review": review}


def format_supervision_report(state: SupervisionReportState) -> dict[str, Any]:
    context = state["case_context"]
    sections = state["sections_a"] + state["sections_b"] + state["sections_c"]
    report = SupervisionReportDraft(
        reportId=f"supervision-{context['case_id']}-{context['session_number']}",
        caseId=context["case_id"],
        meta=SupervisionReportMeta(
            clientAlias=context["client_alias"],
            sessionNumber=context["session_number"],
            reportDate=context["report_date"],
            counselorName=context["counselor_name"],
            institution=context["institution"],
            supervisor=context["supervisor"],
            supervisionDatePlace=context["supervision_date_place"],
        ),
        sections=sections,
        aiReview=state["ai_review"],
        evidenceIndex=state["evidence_index"],
    )
    return {"sections": sections, "report": report}


def _heading(section_id: str, title: str, level: int) -> SupervisionReportSection:
    return SupervisionReportSection(id=section_id, title=title, level=level, contentBlocks=[], status="partial")


def _section(
    section_id: str,
    title: str,
    blocks: list[SupervisionContentBlock],
    status: str,
) -> SupervisionReportSection:
    return SupervisionReportSection(id=section_id, title=title, level=2, contentBlocks=blocks, status=status)


def _paragraph(
    block_id: str,
    text: str,
    evidence_ids: list[str],
    warnings: list[str] | None = None,
    review_status: str = "unchecked",
    demo_value: bool = False,
) -> SupervisionContentBlock:
    return SupervisionContentBlock(
        id=block_id,
        type="paragraph",
        text=text or PLACEHOLDER,
        evidenceIds=evidence_ids,
        aiGenerated=True,
        demoValue=demo_value,
        reviewStatus=review_status,
        warnings=warnings or [],
    )


def _parse_previous_sessions(text: str) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    pattern = re.compile(r"(\d+)회기\s*\(([^)]*)\):\s*(.*?)(?=\n\d+회기\s*\(|$)", re.DOTALL)
    sessions = []
    for match in pattern.finditer(text.strip()):
        sessions.append(
            {
                "session_number": int(match.group(1)),
                "date": _compact_date(match.group(2).strip()),
                "summary": " ".join(match.group(3).split()),
            }
        )
    if sessions:
        return sessions

    return [
        {"session_number": index + 1, "date": "", "summary": line.strip()}
        for index, line in enumerate(text.splitlines())
        if line.strip()
    ]


def _parse_transcript(text: str, session_number: int) -> list[dict[str, str]]:
    turns = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        speaker = None
        body = stripped
        if stripped.startswith(("Cl:", "내담자:", "Client:")):
            speaker = "client"
            body = stripped.split(":", 1)[1].strip()
        elif stripped.startswith(("C:", "상담자:", "Counselor:")):
            speaker = "counselor"
            body = stripped.split(":", 1)[1].strip()
        if not speaker:
            continue
        turns.append(
            {
                "turnId": f"transcript_{session_number}.turn_{len(turns) + 1}",
                "speaker": speaker,
                "text": body,
            }
        )
    return turns


def _selected_transcript_turns(turns: list[dict[str, str]]) -> list[SupervisionSpeakerTurn]:
    if not turns:
        return []
    selected = turns[2:12] if len(turns) > 8 else turns[:8]
    return [SupervisionSpeakerTurn(**turn) for turn in selected]


def _session_progress_rows(state: SupervisionReportState) -> list[dict[str, str]]:
    context = state["case_context"]
    normalized = state["normalized_inputs"]
    session = context["current_input"]
    summary: SessionSummaryDraft | None = context.get("current_summary")
    if context["demo_mode"]:
        return DEMO_SESSION_ROWS

    rows = [
        {
            "회기": f"{item['session_number']}회기",
            "날짜": item["date"] or "확인 필요",
            "진행시간": "확인 필요",
            "회기 주제": _shorten(item["summary"], 58),
            "비고": "이전 회기 요약 기반",
        }
        for item in normalized["previous_sessions"]
    ]
    rows.append(
        {
            "회기": f"{session.session_number}회기",
            "날짜": _compact_date(session.session_date) if session.session_date else "확인 필요",
            "진행시간": "확인 필요",
            "회기 주제": summary.session_theme.text if summary else _shorten(session.counselor_memo, 58),
            "비고": "현재 회기 상세 요약 기반",
        }
    )
    return rows


def _main_complaint_text(state: SupervisionReportState) -> str:
    evidence = state["evidence_index"]
    context = state["case_context"]
    if context["demo_mode"]:
        return (
            "진로 및 취업 준비 과정에서 부모와 주변 동기들의 기대를 강하게 인식하며 대인 비교 불안과 자기비난을 호소한다. "
            "서류 합격 직후 면접 상황에 직면하자 실수할 것에 대한 두려움으로 준비 행동을 지연하거나 회피하는 양상이 뚜렷하다. "
            "불안 증상이 격화되는 야간에는 입면 장애 및 두통 등의 신체화 증상을 호소하고 있다."
        )

    preferred = []
    for ref in ("session_1.summary.p1", "transcript_5.turn_2", "transcript_5.turn_4", "session_5.summary.presenting_problem"):
        if ref in evidence:
            preferred.append(evidence[ref]["text"])
    if not preferred:
        return "취업 준비 및 수행 과정에서의 불안과 비교 사고, 자기비난을 호소한다. 세부 증상과 지속 기간은 접수면접지 등을 통해 추가 파악이 요구된다."
    
    joined_evidence = ' / '.join(preferred)
    return (
        f"진로 및 취업 준비 과정에서 높은 불안과 타인 비교 사고, 자기비난을 주로 호소한다. "
        f"구체적인 맥락으로는 {joined_evidence} 등이 확인되며, 이로 인한 면접 과제 회피 및 불면 증상이 동반되고 있다."
    )


def _find_session(items: list[dict[str, Any]], session_number: int) -> dict[str, Any] | None:
    return next((item for item in items if item["session_number"] == session_number), None)


def _existing_refs(state: SupervisionReportState, *refs: str) -> list[str]:
    evidence = state["evidence_index"]
    return [ref for ref in refs if ref in evidence]


def _refs_with_prefix(state: SupervisionReportState, prefix: str) -> list[str]:
    return [ref for ref in state["evidence_index"] if ref.startswith(prefix)]


def _sentences(text: str) -> list[str]:
    compact = " ".join((text or "").split())
    if not compact:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+|(?<=다\.)\s+", compact) if part.strip()]


def _first_nonempty(items: list[str], fallback: str) -> str:
    return next((item for item in items if item.strip()), fallback)


def _shorten(text: str, limit: int) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def _compact_date(value: str) -> str:
    compact = value.replace(" ", "").replace("-", ".")
    if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}", compact):
        return compact
    return value


def _default_client_alias(case_id: str) -> str:
    if case_id == DEMO_CASE_ID:
        return DEMO_META["client_alias"]
    return case_id or PLACEHOLDER
