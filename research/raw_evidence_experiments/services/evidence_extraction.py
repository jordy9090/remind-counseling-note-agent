"""Standalone LLM span extraction and raw-grounded episode orchestration."""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.evidence import StoredTranscriptTurn
from app.services.embeddings import EmbeddingError, get_embedding_provider
from app.services.llm import get_llm
from app.services.supabase_storage import storage
from app.services.transcript_storage import get_transcript_turns
from research.raw_evidence_experiments.schemas import (
    EpisodeExtractionPayload,
    EpisodeSpanSelection,
    EvidenceEpisodeSpan,
    EvidenceExtractionDiagnostic,
    EvidenceExtractionResult,
)
from research.raw_evidence_experiments.storage import (
    create_evidence_episode_from_span,
    validate_episode_role_feasibility,
)


Extractor = Callable[[list[StoredTranscriptTurn]], EpisodeExtractionPayload | dict[str, Any]]


def extract_evidence_episode_spans(*, turns: list[StoredTranscriptTurn], extractor: Extractor | None = None) -> list[EvidenceEpisodeSpan]:
    """Backward-compatible PR2.6 direct-span extraction path."""
    return extract_evidence_episode_spans_direct(turns=turns, extractor=extractor)


def extract_evidence_episode_spans_direct(
    *, turns: list[StoredTranscriptTurn], extractor: Extractor | None = None,
) -> list[EvidenceEpisodeSpan]:
    """PR2.6 baseline retained for controlled comparison; not replaced in production."""
    spans, _ = _extract_with_diagnostics(turns=turns, extractor=extractor, consolidate_fragments=False)
    return spans


def extract_and_store_evidence_episodes(
    *, user_id: str, counselor_id: str, case_id: str, session_id: str,
    extractor: Extractor | None = None,
) -> EvidenceExtractionResult:
    turns = get_transcript_turns(user_id=user_id, case_id=case_id, session_id=session_id)
    spans, diagnostics = _extract_with_diagnostics(turns=turns, extractor=extractor, consolidate_fragments=False)
    episodes = []
    embedding_count = 0
    for span in spans:
        episode = create_evidence_episode_from_span(
            user_id=user_id, counselor_id=counselor_id, case_id=case_id, session_id=session_id, span=span,
        )
        episodes.append(episode)
        try:
            if _ensure_episode_embedding(episode.model_dump(mode="json")):
                embedding_count += 1
        except EmbeddingError as error:
            diagnostics.append(EvidenceExtractionDiagnostic(code="embedding_failed", message=str(error)))
    return EvidenceExtractionResult(
        spans=spans, episodes=episodes, diagnostics=diagnostics, embedding_count=embedding_count,
    )


def _extract_with_diagnostics(
    *, turns: list[StoredTranscriptTurn], extractor: Extractor | None,
    consolidate_fragments: bool = True,
) -> tuple[list[EvidenceEpisodeSpan], list[EvidenceExtractionDiagnostic]]:
    if not turns:
        return [], [EvidenceExtractionDiagnostic(code="no_turns", message="No scoped transcript turns were found.")]
    raw = extractor(turns) if extractor else _invoke_structured_extractor(turns)
    if isinstance(raw, EpisodeExtractionPayload):
        raw_candidates = [candidate.model_dump(mode="json") for candidate in raw.episodes]
    elif isinstance(raw, dict) and set(raw) <= {"episodes"} and isinstance(raw.get("episodes", []), list):
        raw_candidates = raw.get("episodes", [])
    else:
        raise ValueError("Extractor output must contain only an episodes list")
    by_index = {turn.turn_index: turn for turn in turns}
    valid: list[EvidenceEpisodeSpan] = []
    diagnostics: list[EvidenceExtractionDiagnostic] = []
    seen: set[tuple[str, int, int]] = set()
    for candidate_index, candidate in enumerate(raw_candidates):
        try:
            # Apply the public LLM contract even to injected/debug extractors. Internal
            # metadata belongs to the deterministic backend, never to model output.
            selection = EpisodeSpanSelection.model_validate(candidate)
            span = EvidenceEpisodeSpan(**selection.model_dump(mode="json"))
            _validate_turn_existence_and_roles(span, by_index)
        except (ValidationError, ValueError) as error:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="invalid_episode", message=str(error),
            ))
            continue
        key = (span.episode_type, span.start_turn_index, span.end_turn_index)
        if key in seen:
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="duplicate_episode", message=f"Duplicate episode ignored: {key}",
            ))
            continue
        if any(_spans_overlap(span, current) for current in valid):
            diagnostics.append(EvidenceExtractionDiagnostic(
                candidate_index=candidate_index, code="overlapping_episode",
                message="Overlapping episode retained for later retrieval diversification.",
            ))
        seen.add(key)
        valid.append(span)
    if consolidate_fragments:
        valid, merge_diagnostics = consolidate_episode_fragments(valid, turns=turns)
        diagnostics.extend(merge_diagnostics)
    return valid, diagnostics


def consolidate_episode_fragments(
    spans: list[EvidenceEpisodeSpan], *, turns: list[StoredTranscriptTurn],
    max_scene_turns: int = 12, max_gap_turns: int = 1,
) -> tuple[list[EvidenceEpisodeSpan], list[EvidenceExtractionDiagnostic]]:
    """Conservatively merge adjacent validated fragments without creating evidence text."""
    if len(spans) < 2:
        return spans, []
    by_index = {turn.turn_index: turn for turn in turns}
    ordered = sorted(spans, key=lambda span: (span.start_turn_index, span.end_turn_index, span.episode_type))
    diagnostics: list[EvidenceExtractionDiagnostic] = []
    changed = True
    while changed:
        changed = False
        merged: list[EvidenceEpisodeSpan] = []
        index = 0
        while index < len(ordered):
            current = ordered[index]
            if index + 1 >= len(ordered):
                merged.append(current)
                break
            following = ordered[index + 1]
            candidate = _merge_candidate(
                current, following, all_spans=ordered, by_index=by_index,
                max_scene_turns=max_scene_turns, max_gap_turns=max_gap_turns,
            )
            if candidate is None:
                merged.append(current)
                index += 1
                continue
            merged.append(candidate)
            diagnostics.append(EvidenceExtractionDiagnostic(
                code="fragments_consolidated",
                message=(f"Merged {current.episode_type} fragments "
                         f"{current.start_turn_index}-{current.end_turn_index} and "
                         f"{following.start_turn_index}-{following.end_turn_index}."),
            ))
            index += 2
            changed = True
        ordered = sorted(merged, key=lambda span: (span.start_turn_index, span.end_turn_index, span.episode_type))
    return ordered, diagnostics


def extract_uncovered_client_event_spans(
    *, turns: list[StoredTranscriptTurn], first_pass_spans: list[EvidenceEpisodeSpan],
    extractor: Extractor | None = None,
) -> tuple[list[EvidenceEpisodeSpan], list[EvidenceExtractionDiagnostic]]:
    """Experimental coverage pass over substantive uncovered client-heavy ranges only."""
    ranges = _substantive_uncovered_client_ranges(turns, first_pass_spans)
    if not ranges:
        return [], []
    scoped_turns = [turn for turn in turns if any(start <= turn.turn_index <= end for start, end in ranges)]
    raw_extractor = extractor or _invoke_coverage_structured_extractor
    spans, diagnostics = _extract_with_diagnostics(
        turns=scoped_turns, extractor=raw_extractor, consolidate_fragments=False,
    )
    accepted: list[EvidenceEpisodeSpan] = []
    for span in spans:
        if span.episode_type != "client_event_state":
            diagnostics.append(EvidenceExtractionDiagnostic(
                code="invalid_coverage_episode", message="Coverage recovery accepts client_event_state only.",
            ))
            continue
        if not any(start <= span.start_turn_index and span.end_turn_index <= end for start, end in ranges):
            diagnostics.append(EvidenceExtractionDiagnostic(
                code="invalid_coverage_episode", message="Recovered span crossed an uncovered-range boundary.",
            ))
            continue
        accepted.append(span)
    return accepted, diagnostics


def _substantive_uncovered_client_ranges(
    turns: list[StoredTranscriptTurn], spans: list[EvidenceEpisodeSpan],
    *, min_client_characters: int = 20,
) -> list[tuple[int, int]]:
    covered = {
        index for span in spans for index in range(span.start_turn_index, span.end_turn_index + 1)
    }
    uncovered = [turn for turn in sorted(turns, key=lambda item: item.turn_index) if turn.turn_index not in covered]
    groups: list[list[StoredTranscriptTurn]] = []
    for turn in uncovered:
        if not groups or turn.turn_index != groups[-1][-1].turn_index + 1:
            groups.append([turn])
        else:
            groups[-1].append(turn)
    ranges = []
    for group in groups:
        client_turns = [turn for turn in group if turn.speaker_role == "client"]
        counselor_turns = [turn for turn in group if turn.speaker_role == "counselor"]
        if len(client_turns) < len(counselor_turns):
            continue
        if sum(len(turn.sanitized_text.strip()) for turn in client_turns) < min_client_characters:
            continue
        ranges.append((group[0].turn_index, group[-1].turn_index))
    return ranges


def _merge_candidate(
    left: EvidenceEpisodeSpan, right: EvidenceEpisodeSpan, *,
    all_spans: list[EvidenceEpisodeSpan], by_index: dict[int, StoredTranscriptTurn],
    max_scene_turns: int, max_gap_turns: int,
) -> EvidenceEpisodeSpan | None:
    if left.episode_type != right.episode_type:
        return None
    gap = right.start_turn_index - left.end_turn_index - 1
    if gap > max_gap_turns:
        return None
    start, end = min(left.start_turn_index, right.start_turn_index), max(left.end_turn_index, right.end_turn_index)
    if end - start + 1 > max_scene_turns:
        return None
    if any(index not in by_index for index in range(start, end + 1)):
        return None
    # A different-type episode occupying the bridge is evidence of a scene/topic boundary.
    bridge_start, bridge_end = left.end_turn_index + 1, right.start_turn_index - 1
    if bridge_start <= bridge_end and any(
        span.episode_type != left.episode_type
        and span.start_turn_index <= bridge_end and span.end_turn_index >= bridge_start
        for span in all_spans
    ):
        return None
    try:
        candidate = EvidenceEpisodeSpan(
            episode_type=left.episode_type, start_turn_index=start, end_turn_index=end,
            metadata_json={"consolidated_fragments": 2},
        )
        _validate_turn_existence_and_roles(candidate, by_index)
    except (ValidationError, ValueError):
        return None
    return candidate


def _validate_turn_existence_and_roles(span: EvidenceEpisodeSpan, by_index: dict[int, StoredTranscriptTurn]) -> None:
    missing = [index for index in range(span.start_turn_index, span.end_turn_index + 1) if index not in by_index]
    if missing:
        raise ValueError(f"Missing transcript turns in episode span: {missing}")
    validate_episode_role_feasibility(span, by_index.values())


def _invoke_structured_extractor(turns: list[StoredTranscriptTurn]) -> EpisodeExtractionPayload:
    if settings.stub_mode:
        raise RuntimeError("Evidence episode extraction requires an LLM or an explicit test extractor.")
    prompt = _build_extraction_prompt(turns)
    return _episode_extractor_llm().invoke(prompt)


def _invoke_legacy_structured_extractor(turns: list[StoredTranscriptTurn]) -> EpisodeExtractionPayload:
    if settings.stub_mode:
        raise RuntimeError("Evidence episode extraction requires an LLM or an explicit test extractor.")
    return _episode_extractor_llm().invoke(_build_legacy_extraction_prompt(turns))


def _invoke_coverage_structured_extractor(turns: list[StoredTranscriptTurn]) -> EpisodeExtractionPayload:
    if settings.stub_mode:
        raise RuntimeError("Evidence episode coverage recovery requires an LLM or an explicit test extractor.")
    return _episode_extractor_llm().invoke(_build_coverage_prompt(turns))


def _episode_extractor_llm():
    # Function calling keeps the standalone extractor schema isolated from
    # production note-generation LLM wiring.
    # Span selection is a deterministic boundary task, so this standalone path
    # pins temperature to zero without changing generation-model settings.
    llm = get_llm().model_copy(update={"temperature": 0.0})
    return llm.with_structured_output(EpisodeExtractionPayload, method="function_calling")


def _build_extraction_prompt(turns: list[StoredTranscriptTurn]) -> str:
    transcript = "\n".join(f"{turn.turn_index} [{turn.speaker_role}] {turn.sanitized_text}" for turn in turns)
    return f"""Select SCENE-LEVEL source spans from this deidentified counseling transcript.
Return structured data only in the supplied schema. Each episode dictionary may contain ONLY:
episode_type, start_turn_index, end_turn_index.
Never return episode text, summary, interpretation, clinical meaning, progress labels, diagnosis, or rewritten speech.

Episode types:
- intervention_response: ONE local interaction chain serving one counseling purpose. A client cue, counselor clarification,
  meaningful intervention, client response, counselor follow-up, and client elaboration belong to ONE episode when they
  continue the same purpose. Do NOT split at every counselor/client speaker change or into separate Q/A pairs.
- client_event_state: ONE complete report of an outside event/behavior/state, including what happened, what the client did,
  the other person's response, and the client's result when these continue one report. Counselor clarification may remain
  inside this scene; if the counselor begins a new therapeutic intervention, that can become a separate episode.

Type priority: if meaningful counselor intervention and its response are central, use intervention_response. If the reported
event/state is central and counselor turns mainly clarify details, use client_event_state. Avoid emitting the same scene as both types.
End a scene only when the topic clearly changes, a new independent counseling purpose begins, or the exchange naturally closes.
Do not omit a complete outside-event report merely because a later intervention occurs. When a client first reports what happened,
their action, the other person's response, or the result, and the counselor then shifts into a new skill, plan, rehearsal, or task,
emit the event report as client_event_state and the subsequent therapeutic exchange as a separate intervention_response scene.
Questions that only ask who/what happened/how the client felt remain clarification inside client_event_state; questions that introduce
a new coping method, practice, plan, or task mark the start of intervention_response.
Select observable/reportable scenes independent of counseling theory. Exclude small talk, acknowledgements, and administration.
Coverage requirement: do NOT select only the few most important scenes. Return every independent meaningful scene that would be
worth reopening as raw evidence for later counseling documentation or longitudinal review. In particular, retain outside-session
attempts, failures/setbacks, conflicts, state changes, and important events; also retain counselor practice, strategy discussion,
reframing, planning, or another new intervention when a client response follows.

Hard validity rules:
- Use only existing indices and continuous spans.
- intervention_response span MUST include >=1 actual counselor turn AND >=1 actual client turn.
- client_event_state span MUST include >=1 actual client evidence turn.
- Never relabel unknown speakers or silently repair malformed indices.
- Not every turn needs an episode.

Few-shot A — one long intervention chain (do not split Q/A pairs):
Input:
0 [client] 동료에게 부탁을 거절하지 못해서 일이 계속 늘어요.
1 [counselor] 여기서 실제 상황처럼 한 문장으로 거절해볼까요?
2 [client] 바로 하려니 어렵네요.
3 [counselor] 제가 동료 역할을 할게요. 가능한 범위를 먼저 말해보세요.
4 [client] 오늘은 어렵고 금요일에는 도울 수 있어요.
5 [counselor] 말한 뒤 느낌을 확인해볼까요?
6 [client] 긴장되지만 생각보다 무례하게 느껴지지는 않아요.
Output: one intervention_response span 0-6.

Few-shot B — complete client event report:
Input:
0 [client] 지난주 친구에게 약속 시간을 바꾸자고 먼저 말했어요.
1 [counselor] 친구는 어떻게 반응했나요?
2 [client] 괜찮다고 했고 다른 시간을 같이 정했어요.
3 [counselor] 그 결과 본인은 어땠나요?
4 [client] 미안하기만 할 줄 알았는데 오히려 마음이 편해졌어요.
Output: one client_event_state span 0-4.

Few-shot C — close one scene and start another topic:
Input:
0 [client] 팀장에게 일정 조정을 요청했고 하루를 더 받았어요.
1 [counselor] 요청 뒤 부담은 달라졌나요?
2 [client] 급한 마음이 조금 줄었어요.
3 [counselor] 이제 지난번에 말한 수면 문제를 따로 살펴보죠. 어제는 몇 시에 잤나요?
4 [client] 새벽 두 시쯤 잠들었어요.
Output: client_event_state 0-2 AND intervention_response 3-4.

Few-shot D — preserve an event report before a new intervention on the same topic:
Input:
0 [client] 동생에게 빌려준 물건을 돌려달라고 말하지 못하고 그냥 새로 샀어요.
1 [counselor] 말하려던 순간에는 무엇이 걱정됐나요?
2 [client] 사이가 불편해질까 봐 포기했어요.
3 [counselor] 그 사건은 여기까지 정리하고, 다음에는 요청 문장을 짧게 만드는 연습을 해보죠.
4 [client] 돌려받을 날짜를 먼저 물어보면 될 것 같아요.
Output: client_event_state 0-2 AND intervention_response 3-4. The shared topic does not erase the interaction-function boundary.

Transcript:
{transcript}
"""


def _build_legacy_extraction_prompt(turns: list[StoredTranscriptTurn]) -> str:
    transcript = "\n".join(f"{turn.turn_index} [{turn.speaker_role}] {turn.sanitized_text}" for turn in turns)
    return f"""Select source spans from this deidentified counseling transcript.
Return structured data only in the supplied schema. Each episode dictionary may contain ONLY:
episode_type, start_turn_index, end_turn_index.
Never return episode text, summary, interpretation, clinical meaning, progress labels, diagnosis, or rewritten speech.

Episode types:
- intervention_response: a meaningful counselor question/reflection/clarification/role rehearsal/task discussion and the client's ensuing response.
- client_event_state: an important reported event, behavior, recurring difficulty, or state that can connect sessions; no counselor intervention is required.
Select observable/reportable scenes independent of counseling theory. Exclude small talk, acknowledgements, and administration.
Use only existing indices and choose spans that satisfy the actual speaker-role requirements.
Do not silently repair gaps or speaker roles. Not every turn needs an episode.

Transcript:
{transcript}
"""


def _build_coverage_prompt(turns: list[StoredTranscriptTurn]) -> str:
    transcript = "\n".join(f"{turn.turn_index} [{turn.speaker_role}] {turn.sanitized_text}" for turn in turns)
    return f"""This is a limited coverage check over substantive client-heavy transcript turns that were not included
in any first-pass evidence episode. Return every omitted client_event_state worth reopening for later documentation.
Return episode_type, start_turn_index, and end_turn_index only. episode_type must be client_event_state.
Do not return intervention_response, summaries, interpretations, rewritten text, or indices outside the supplied turns.
Do not bridge a missing turn-index gap. If no complete outside event/behavior/state report exists, return an empty episodes list.

Uncovered turns (original indices preserved):
{transcript}
"""


def _ensure_episode_embedding(episode: dict[str, Any]) -> bool:
    existing = storage.maybe_single("evidence_episodes", {
        "user_id": f'eq.{episode["user_id"]}', "case_id": f'eq.{episode["case_id"]}',
        "session_id": f'eq.{episode["session_id"]}', "source_ref": f'eq.{episode["source_ref"]}',
        "episode_type": f'eq.{episode["episode_type"]}',
        "select": "id,content_hash,embedding_model,embedding", "limit": 1,
    })
    if existing and existing.get("content_hash") == episode["content_hash"] and existing.get("embedding_model") == settings.embedding_model and existing.get("embedding"):
        return False
    vector = get_embedding_provider().embed([episode["episode_text"]])[0]
    storage.update("evidence_episodes", {
        "embedding": vector, "embedding_model": settings.embedding_model,
        "embedding_updated_at": datetime.now(UTC).isoformat(),
    }, query={
        "user_id": f'eq.{episode["user_id"]}', "case_id": f'eq.{episode["case_id"]}',
        "session_id": f'eq.{episode["session_id"]}', "source_ref": f'eq.{episode["source_ref"]}',
        "episode_type": f'eq.{episode["episode_type"]}',
    }, return_representation=False)
    return True


def _spans_overlap(left: EvidenceEpisodeSpan, right: EvidenceEpisodeSpan) -> bool:
    return left.start_turn_index <= right.end_turn_index and right.start_turn_index <= left.end_turn_index
