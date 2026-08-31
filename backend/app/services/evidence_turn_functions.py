"""Turn-function classification and deterministic evidence-scene assembly."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.evidence import (
    EvidenceEpisodeSpan, EvidenceExtractionDiagnostic, EvidenceExtractionResult, StoredTranscriptTurn,
    TurnFunctionLabel, TurnFunctionLabelPayload,
)
from app.services.evidence_storage import (
    create_evidence_episode_from_span, get_transcript_turns, validate_episode_role_feasibility,
)
from app.services.llm import get_llm


DEFAULT_MAX_SCENE_TURNS = 12
TurnClassifier = Callable[[list[StoredTranscriptTurn]], TurnFunctionLabelPayload | dict[str, Any]]

_EXPECTED_ROLE = {
    "client_report": "client",
    "client_response": "client",
    "counselor_clarification": "counselor",
    "counselor_intervention": "counselor",
}


def label_turn_functions_with_diagnostics(
    *, turns: list[StoredTranscriptTurn], classifier: TurnClassifier | None = None,
) -> tuple[list[TurnFunctionLabel], list[EvidenceExtractionDiagnostic]]:
    if not turns:
        return [], [EvidenceExtractionDiagnostic(code="no_turns", message="No transcript turns were supplied.")]
    raw = classifier(turns) if classifier else _invoke_turn_function_classifier(turns)
    if isinstance(raw, TurnFunctionLabelPayload):
        candidates = [item.model_dump(mode="json") for item in raw.labels]
    elif isinstance(raw, dict) and set(raw) <= {"labels"} and isinstance(raw.get("labels", []), list):
        candidates = raw.get("labels", [])
    else:
        raise ValueError("Turn-function output must contain only a labels list")

    by_index = {turn.turn_index: turn for turn in turns}
    valid: list[TurnFunctionLabel] = []
    diagnostics: list[EvidenceExtractionDiagnostic] = []
    seen: set[int] = set()
    for candidate_index, candidate in enumerate(candidates):
        try:
            label = TurnFunctionLabel.model_validate(candidate)
        except ValidationError as error:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="invalid_turn_function", message=str(error),
            ))
            continue
        turn = by_index.get(label.turn_index)
        if turn is None:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="nonexistent_turn_label",
                message=f"Turn {label.turn_index} does not exist in the scoped transcript.",
            ))
            continue
        if label.turn_index in seen:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="duplicate_turn_label",
                message=f"Turn {label.turn_index} was labeled more than once.",
            ))
            continue
        expected_role = _EXPECTED_ROLE.get(label.function)
        if expected_role is not None and turn.speaker_role != expected_role:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="invalid_speaker_function",
                message=(f"{label.function} requires speaker_role={expected_role}; "
                         f"turn {label.turn_index} has speaker_role={turn.speaker_role}."),
            ))
            seen.add(label.turn_index)
            continue
        seen.add(label.turn_index)
        valid.append(label)
    for turn in turns:
        if turn.turn_index not in seen:
            diagnostics.append(EvidenceExtractionDiagnostic(
                code="missing_turn_label", message=f"Turn {turn.turn_index} received no function label.",
            ))
    return sorted(valid, key=lambda item: item.turn_index), diagnostics


def assemble_evidence_episodes_from_turn_functions(
    turns: list[StoredTranscriptTurn], labels: list[TurnFunctionLabel],
    *, max_scene_turns: int = DEFAULT_MAX_SCENE_TURNS,
) -> list[EvidenceEpisodeSpan]:
    spans, _ = assemble_evidence_episodes_with_diagnostics(
        turns, labels, max_scene_turns=max_scene_turns,
    )
    return spans


def assemble_evidence_episodes_with_diagnostics(
    turns: list[StoredTranscriptTurn], labels: list[TurnFunctionLabel],
    *, max_scene_turns: int = DEFAULT_MAX_SCENE_TURNS,
) -> tuple[list[EvidenceEpisodeSpan], list[EvidenceExtractionDiagnostic]]:
    """Assemble local scenes from validated labels without semantic inference or LLM calls."""
    if max_scene_turns < 2:
        raise ValueError("max_scene_turns must be at least 2")
    ordered_turns = sorted(turns, key=lambda item: item.turn_index)
    by_index = {turn.turn_index: turn for turn in ordered_turns}
    label_by_index = {label.turn_index: label.function for label in labels if label.turn_index in by_index}
    spans: list[EvidenceEpisodeSpan] = []
    diagnostics: list[EvidenceExtractionDiagnostic] = []
    active_type: str | None = None
    active_start: int | None = None
    active_end: int | None = None

    def flush() -> None:
        nonlocal active_type, active_start, active_end
        if active_type is None or active_start is None or active_end is None:
            active_type = active_start = active_end = None
            return
        span = EvidenceEpisodeSpan(
            episode_type=active_type, start_turn_index=active_start, end_turn_index=active_end,
        )
        try:
            validate_episode_role_feasibility(span, by_index.values())
        except ValueError as error:
            diagnostics.append(EvidenceExtractionDiagnostic(code="invalid_assembled_episode", message=str(error)))
        else:
            spans.append(span)
        active_type = active_start = active_end = None

    def can_append(index: int) -> bool:
        return (
            active_start is not None and active_end is not None
            and index == active_end + 1 and index - active_start + 1 <= max_scene_turns
        )

    previous_index: int | None = None
    for turn in ordered_turns:
        index = turn.turn_index
        function = label_by_index.get(index, "other")
        if previous_index is not None and index != previous_index + 1:
            flush()
        previous_index = index

        if function == "other":
            flush()
            continue

        if function == "client_report":
            if active_type == "intervention_response" or (active_type is not None and not can_append(index)):
                flush()
            if active_type is None:
                active_type, active_start, active_end = "client_event_state", index, index
            else:
                active_end = index
            continue

        if function == "counselor_intervention":
            if active_type == "client_event_state" or (active_type is not None and not can_append(index)):
                flush()
            if active_type is None:
                active_type, active_start, active_end = "intervention_response", index, index
            else:
                active_end = index
            continue

        if function == "counselor_clarification":
            if active_type is not None and can_append(index):
                active_end = index
            elif active_type is not None:
                flush()
            continue

        if function == "client_response":
            if active_type == "intervention_response" and can_append(index):
                active_end = index
            else:
                flush()
                diagnostics.append(EvidenceExtractionDiagnostic(
                    code="orphan_client_response",
                    message=f"Turn {index} has no active counselor intervention scene.",
                ))
    flush()
    return spans, diagnostics


def extract_evidence_episode_spans_from_turn_functions(
    *, turns: list[StoredTranscriptTurn], classifier: TurnClassifier | None = None,
    max_scene_turns: int = DEFAULT_MAX_SCENE_TURNS,
) -> tuple[list[EvidenceEpisodeSpan], list[TurnFunctionLabel], list[EvidenceExtractionDiagnostic]]:
    labels, label_diagnostics = label_turn_functions_with_diagnostics(turns=turns, classifier=classifier)
    spans, assembly_diagnostics = assemble_evidence_episodes_with_diagnostics(
        turns, labels, max_scene_turns=max_scene_turns,
    )
    return spans, labels, [*label_diagnostics, *assembly_diagnostics]


def extract_and_store_evidence_episodes_from_turn_functions(
    *, user_id: str, counselor_id: str, case_id: str, session_id: str,
    classifier: TurnClassifier | None = None,
    max_scene_turns: int = DEFAULT_MAX_SCENE_TURNS,
) -> EvidenceExtractionResult:
    """Opt-in PR2.7 path; deliberately not wired into any API, graph, or generation flow."""
    turns = get_transcript_turns(user_id=user_id, case_id=case_id, session_id=session_id)
    spans, _, diagnostics = extract_evidence_episode_spans_from_turn_functions(
        turns=turns, classifier=classifier, max_scene_turns=max_scene_turns,
    )
    episodes = [create_evidence_episode_from_span(
        user_id=user_id, counselor_id=counselor_id, case_id=case_id, session_id=session_id, span=span,
    ) for span in spans]
    return EvidenceExtractionResult(spans=spans, episodes=episodes, diagnostics=diagnostics, embedding_count=0)


def _invoke_turn_function_classifier(turns: list[StoredTranscriptTurn]) -> TurnFunctionLabelPayload:
    if settings.stub_mode:
        raise RuntimeError("Turn-function labeling requires an LLM or an explicit test classifier.")
    return _turn_function_llm().invoke(_build_turn_function_prompt(turns))


def _turn_function_llm():
    llm = get_llm().model_copy(update={"temperature": 0.0})
    return llm.with_structured_output(TurnFunctionLabelPayload, method="function_calling")


def _build_turn_function_prompt(turns: list[StoredTranscriptTurn]) -> str:
    transcript = "\n".join(f"{turn.turn_index} [{turn.speaker_role}] {turn.sanitized_text}" for turn in turns)
    return f"""Classify the local conversational function of every turn in this deidentified counseling transcript.
This is NOT clinical interpretation and does not evaluate treatment outcome. Return one label for every supplied turn.
Each label may contain ONLY turn_index and function. Never return transcript text, summaries, explanations, spans, or diagnoses.

Allowed functions:
- client_report: a client independently describes an outside event, attempt, setback, state, feeling, experience, or recurring problem.
- client_response: a client's direct response to the counselor's preceding intervention, practice, strategy, or therapeutic question.
- counselor_clarification: confirmation, detail question, or simple reflection that continues understanding an existing client report.
- counselor_intervention: starts or advances a therapeutic action/direction such as rehearsal, strategy, task, reframing,
  structured pattern exploration, planning, or a new therapeutic focus. No counseling-theory terminology is required.
- other: greeting, administration, small talk, acknowledgement, or a turn not needed for evidence assembly.

Use the actual speaker role. Client functions require [client]; counselor functions require [counselor].
Unknown speakers must be other. Distinguish client_report from client_response by interaction function, not merely speaker.

Few-shot 1 — long event with clarification:
0 [client] 동아리 회의에서 제 차례를 넘겼어요.
1 [counselor] 그때 어떤 상황이었나요?
2 [client] 반대 의견이 나올까 봐 준비한 말을 접었어요.
3 [counselor] 이후에는 어떤 기분이 들었나요?
4 [client] 후회가 오래 남았어요.
Labels: 0 client_report; 1 counselor_clarification; 2 client_report; 3 counselor_clarification; 4 client_report.

Few-shot 2 — event to intervention transition:
0 [client] 친구에게 부탁을 거절하지 못해 주말 일정이 바뀌었어요.
1 [counselor] 실제로는 무엇을 원했나요?
2 [client] 이번 주는 쉬고 싶었어요.
3 [counselor] 이제 짧은 거절 문장을 함께 만들어보죠.
4 [client] 이번 주는 어렵다고 먼저 말해볼게요.
Labels: 0 client_report; 1 counselor_clarification; 2 client_report; 3 counselor_intervention; 4 client_response.

Few-shot 3 — role rehearsal chain:
0 [counselor] 제가 팀장 역할을 할 테니 일정 조정을 요청해보세요.
1 [client] 하루만 더 필요하다고 말하겠습니다.
2 [counselor] 이유보다 가능한 완료일을 먼저 말해볼까요?
3 [client] 금요일 오후까지 마칠 수 있습니다.
4 [counselor] 말한 뒤 긴장은 어떤가요?
5 [client] 처음보다 덜 부담스럽습니다.
Labels: 0 counselor_intervention; 1 client_response; 2 counselor_intervention; 3 client_response;
4 counselor_clarification; 5 client_response.

Few-shot 4 — other:
0 [counselor] 오늘 녹음 상태를 먼저 확인하겠습니다.
1 [client] 네.
2 [counselor] 다음 예약은 화요일 오후입니다.
Labels: 0 other; 1 other; 2 other.

Transcript:
{transcript}
"""
