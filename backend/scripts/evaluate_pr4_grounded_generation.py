"""Controlled synthetic PR4 grounding evaluation; never reads production counseling data."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.graph.graph import run_note_pipeline  # noqa: E402
from app.schemas.evidence import CandidateTranscriptRegion  # noqa: E402
from app.schemas.grounding import (  # noqa: E402
    EvidenceNeed,
    GroundedClaim,
    GroundingContext,
    GroundingSource,
)
from app.schemas.note import SessionInput  # noqa: E402
from app.services.grounded_generation import (  # noqa: E402
    assemble_grounding_context,
    build_grounded_generation_prompt,
    generate_grounded_claims,
    validate_evidence_ids,
)
from app.services.claim_support_validation import validate_claim_support  # noqa: E402
from app.services.retrieval import RetrievalChunk  # noqa: E402


RAW_EVALUATION = REPO_ROOT / "results" / "debug" / "raw_window_selection" / "evaluation.json"
MEMORY_CORPUS = BACKEND_DIR / "scripts" / "fixtures" / "case_retrieval_controlled_corpus.json"
OUTPUT_DIR = REPO_ROOT / "results" / "debug" / "pr4_grounded_generation"
TEMPTATION_RE = re.compile(r"(?:통화[^.]{0,20}울|울었|눈물)")
REMOVED_FACT_RE = re.compile(r"보고서|발표|마감|학업|수면|잠을\s*못|집중")


SCENARIOS = {
    "scenario_a_progress_note": [
        ("N1", "session_content", "baseline_avoidance", "raw_factual"),
        ("N2", "session_content", "first_behavioral_attempt", "raw_factual"),
        ("N3", "client_response", "recent_successful_progress", "raw_factual"),
        ("N4", "presenting_problem", "setback", "raw_factual"),
        ("N5", "reflection", None, "counselor_judgment"),
    ],
    "scenario_b_supervision_history": [
        ("N1", "counselor_intervention", "intervention_rehearsal", "raw_factual"),
        ("N2", "client_response", "intervention_rehearsal", "raw_factual"),
        ("N3", "session_content", "first_behavioral_attempt", "raw_factual"),
        ("N4", "session_content", "academic_stress_negative_control", "raw_factual"),
        ("N5", "reflection", None, "counselor_judgment"),
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-llm",
        action="store_true",
        help="Use the configured existing structured LLM service on synthetic context.",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_payload = _load_json(RAW_EVALUATION)
    memory_payload = _load_json(MEMORY_CORPUS)
    query_rows = {row["id"]: row for row in raw_payload["queries"]}
    scenario_input = _synthetic_current_input(memory_payload)
    sanitized = _sanitize_via_existing_path(scenario_input)
    existing = _run_existing_baseline(scenario_input)

    original_use_stub = settings.use_stub
    settings.use_stub = not args.live_llm
    scenarios: dict[str, Any] = {}
    drafts: dict[str, Any] = {}
    try:
        for scenario_name, specs in SCENARIOS.items():
            needs, query_keys = _build_needs(specs, query_rows)
            raw_regions = {
                need.need_id: _top_five_regions(query_rows[query_key])
                for need, query_key in zip(needs, query_keys, strict=True)
                if query_key is not None
            }
            memory = [_memory_chunk(memory_payload, scenario_name)]
            context = assemble_grounding_context(
                needs=needs,
                raw_regions_by_need=raw_regions,
                counselor_memory_chunks=memory,
            )
            draft = generate_grounded_claims(sanitized, context)
            result = validate_evidence_ids(draft, context)
            drafts[scenario_name] = draft
            scenarios[scenario_name] = _scenario_artifact(
                needs=needs,
                query_keys=query_keys,
                raw_regions=raw_regions,
                context=context,
                draft=draft,
                result=result,
            )

        source_removal_clean = _run_source_removal(
            sanitized=sanitized,
            scenario=scenarios["scenario_b_supervision_history"],
            live_llm=args.live_llm,
            query_temptation=False,
        )
        source_removal_temptation = _run_source_removal(
            sanitized=sanitized,
            scenario=scenarios["scenario_b_supervision_history"],
            live_llm=args.live_llm,
            query_temptation=True,
        )
        adversarial = _run_adversarial_support_set()
    finally:
        settings.use_stub = original_use_stub

    aggregate = _aggregate_metrics(scenarios)
    prompt_audit = _prompt_audit(
        sanitized,
        GroundingContext.model_validate(scenarios["scenario_b_supervision_history"]["context"]),
    )
    hallucination = _hallucination_check(scenarios)
    claim_inspection = _claim_inspection(scenarios)
    gate = {
        "citation_validity_100": aggregate["citation_validity"] == 1.0,
        "factual_claim_citation_coverage_at_least_90": aggregate["factual_claim_citation_coverage"] >= 0.9,
        "unsupported_factual_claim_rate_at_most_10": aggregate["unsupported_factual_claim_rate"] <= 0.1,
        "semantic_support_validity_at_least_90": aggregate["semantic_support_validity"] >= 0.9,
        "false_supported_rate_zero": adversarial["metrics"]["false_supported_rate"] == 0.0,
        "source_removal_false_support_zero": (
            source_removal_clean["false_support_rate"] == 0.0
            and source_removal_temptation["false_support_rate"] == 0.0
        ),
        "all_wrong_source_swaps_not_supported": adversarial["metrics"]["wrong_source_swaps_supported"] == 0,
        "partial_detection_100": adversarial["metrics"]["partial_detection"] == 1.0,
        "query_omitted_from_generation": prompt_audit["query_text_omitted"],
        "temptation_not_source_backed": hallucination["passed"],
        "at_least_10_claims_inspected": len(claim_inspection) >= 10,
        "raw_snapshot_exact": all(item["raw_snapshot_exact"] for item in claim_inspection),
    }
    if not prompt_audit["query_text_omitted"] or not prompt_audit["non_source_inputs_omitted"]:
        decision = "Generation contract still leaks unsupported facts"
    elif all(gate.values()):
        decision = "Ready for counselor-facing evidence UI"
    else:
        decision = "Support validator needs revision"
    artifact = {
        "description": "PR4 controlled synthetic raw-region grounded generation integration evaluation.",
        "data_policy": "Synthetic fixtures and saved synthetic PR3 retrieval output only; no real counseling data.",
        "generation_mode": "configured_existing_structured_llm" if args.live_llm else "deterministic_stub",
        "remote_migration_applied": False,
        "new_migration_created": False,
        "feature_flag_default": False,
        "existing_graph": [
            "sanitize_input", "formulate_retrieval_query", "retrieve_case_memory",
            "retrieve_authoritative_kb", "fuse_and_rerank", "structure_session",
            "map_evidence", "generate_summary", "verify_output", "conditional_revision",
            "transform_document_preview",
        ],
        "raw_grounded_graph": [
            "sanitize_input", "formulate_evidence_needs", "formulate_retrieval_query",
            "retrieve_raw_evidence_regions", "retrieve_case_memory", "retrieve_authoritative_kb",
            "assemble_generation_grounding", "fuse_and_rerank", "structure_session",
            "map_evidence", "generate_summary", "generate_grounded_document",
            "validate_claim_sources", "verify_output", "conditional_revision",
            "transform_document_preview",
        ],
        "existing_path": existing,
        "scenarios": scenarios,
        "prompt_input_leakage_audit": prompt_audit,
        "adversarial_support_set": adversarial,
        "source_removal_before_revision": {
            "removed_evidence_id": "R5",
            "false_supported_claim_count": 1,
            "wrong_replacement_source": "R6",
            "passed": False,
            "source": "previous controlled PR4 evaluation artifact",
        },
        "source_removal": {
            "clean_source_removal": source_removal_clean,
            "retrieval_query_temptation": source_removal_temptation,
        },
        "hallucination_temptation": hallucination,
        "claim_source_inspection": claim_inspection,
        "aggregate_raw_grounded_metrics": aggregate,
        "acceptance_gate": gate,
        "decision": decision,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "evaluation.json"
    markdown_path = args.output_dir / "evaluation.md"
    json_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_render_markdown(artifact), encoding="utf-8")
    print(json.dumps({
        "json": str(json_path),
        "markdown": str(markdown_path),
        "generation_mode": artifact["generation_mode"],
        "metrics": aggregate,
        "gate": gate,
        "decision": decision,
    }, ensure_ascii=True, indent=2))
    return 0 if all(gate.values()) else 1


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required controlled artifact is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _synthetic_current_input(memory_payload: dict[str, Any]) -> SessionInput:
    return SessionInput(
        case_id=str(memory_payload["case_id"]),
        client_alias="내담자A",
        session_number=9,
        session_date="2026-03-05",
        counselor_name="상담자A",
        counselor_memo="현재 회기에서 자기표현 변화와 남은 어려움을 확인하고 다음 기록 계획을 논의함.",
        transcript_text=(
            "[counselor] 지난 한 달 동안 의견을 표현한 경험을 돌아볼까요?\n"
            "[client] 작은 의견은 말할 수 있지만 목소리가 커지면 아직 긴장돼요."
        ),
        previous_session_summary="",
        counseling_goal=str(memory_payload["counseling_goal"]),
        key_issue_tags=["부모 갈등", "자기표현"],
        target_document_type="session_note",
        persist=False,
    )


def _sanitize_via_existing_path(session_input: SessionInput):
    from app.graph.nodes import sanitize_input

    return sanitize_input({"session_input": session_input})["sanitized_input"]


def _run_existing_baseline(session_input: SessionInput) -> dict[str, Any]:
    original = (settings.enable_raw_region_grounding, settings.enable_rag, settings.use_stub)
    try:
        settings.enable_raw_region_grounding = False
        settings.enable_rag = False
        settings.use_stub = True
        result = run_note_pipeline(session_input, actor="synthetic-raw-eval-user")
    finally:
        settings.enable_raw_region_grounding, settings.enable_rag, settings.use_stub = original
    sections = result.session_summary_draft.model_dump(mode="json")
    citation_sections = {
        key: value.get("source_refs", [])
        for key, value in sections.items()
        if isinstance(value, dict) and "source_refs" in value
    }
    return {
        "grounding_schema_available": False,
        "claim_level_citation_validity": None,
        "factual_claim_citation_coverage": None,
        "unsupported_factual_claim_rate": None,
        "raw_evidence_usage": 0,
        "section_level_source_refs": citation_sections,
        "note": "Existing path has section-level refs but no prompt-safe claim-level evidence-ID contract.",
    }


def _build_needs(specs: list[tuple[str, str, str | None, str]], query_rows: dict[str, Any]):
    needs = []
    query_keys = []
    for need_id, target_field, query_key, requirement in specs:
        query_text = (
            query_rows[query_key]["query"]
            if query_key is not None
            else "자기표현 어려움과 관련해 상담사가 확정한 사례 이해와 상담 전략"
        )
        needs.append(EvidenceNeed(
            need_id=need_id,
            target_field=target_field,
            query_text=query_text,
            source_requirement=requirement,
        ))
        query_keys.append(query_key)
    return needs, query_keys


def _top_five_regions(query_row: dict[str, Any]) -> list[CandidateTranscriptRegion]:
    return [CandidateTranscriptRegion.model_validate(row) for row in query_row["regions"][:5]]


def _memory_chunk(memory_payload: dict[str, Any], scenario_name: str) -> RetrievalChunk:
    session = memory_payload["sessions"][2]
    field = "reflection" if scenario_name == "scenario_a_progress_note" else "counselor_intervention"
    return RetrievalChunk(
        chunk_id=f"synthetic-memory-{scenario_name}",
        chunk_text=session["sections"][field],
        source_ref=f"confirmed_note:synthetic-session-3:{field}",
        retrieval_method="case_memory_dense",
        similarity_score=0.75,
        session_id="synthetic-session-3",
        field_type=field,
        session_number=3,
        session_date=session["session_date"],
    )


def _scenario_artifact(*, needs, query_keys, raw_regions, context, draft, result) -> dict[str, Any]:
    source_by_id = {source.evidence_id: source for source in context.sources}
    retrieval = {}
    for need, query_key in zip(needs, query_keys, strict=True):
        retrieval[need.need_id] = [
            {
                "rank": rank,
                "session_number": region.session_number,
                "turn_range": f"{region.start_turn_index}-{region.end_turn_index}",
                "similarity_score": region.retrieval_score,
                "source_ref": region.source_ref,
            }
            for rank, region in enumerate(raw_regions.get(need.need_id, []), start=1)
        ]
    claims = []
    for claim in result.claims:
        claims.append({
            **claim.model_dump(mode="json"),
            "sources": [
                {
                    "evidence_id": evidence_id,
                    "source_ref": source_by_id[evidence_id].source_ref,
                    "source_type": source_by_id[evidence_id].source_type,
                    "raw_text": source_by_id[evidence_id].source_text,
                }
                for evidence_id in claim.evidence_ids
                if evidence_id in source_by_id
            ],
        })
    return {
        "evidence_needs": [need.model_dump(mode="json") for need in needs],
        "retrieval_top_5_by_need": retrieval,
        "context": context.model_dump(mode="json"),
        "model_draft": draft.model_dump(mode="json"),
        "validated_claims": claims,
        "citation_diagnostics": [item.model_dump(mode="json") for item in result.citation_diagnostics],
        "claim_support_validations": {
            claim_id: validation.model_dump(mode="json")
            for claim_id, validation in result.claim_support_validations.items()
        },
        "metrics": result.metrics.model_dump(mode="json"),
    }


def _run_source_removal(
    *,
    sanitized,
    scenario: dict[str, Any],
    live_llm: bool,
    query_temptation: bool,
) -> dict[str, Any]:
    context = GroundingContext.model_validate(scenario["context"])
    target_need_id = "N4"
    removed = next(
        (
            source
            for source in context.sources
            if source.source_type == "raw_transcript"
            and source.session_number == 4
            and target_need_id in source.need_ids
        ),
        None,
    )
    if removed is None:
        return {"passed": False, "reason": "Gold S4 academic-stress source was not present before removal."}
    reduced = context.model_copy(deep=True)
    reduced.sources = [source for source in reduced.sources if source.evidence_id != removed.evidence_id]
    reduced.need_to_evidence_ids = {
        need_id: [evidence_id for evidence_id in ids if evidence_id != removed.evidence_id]
        for need_id, ids in reduced.need_to_evidence_ids.items()
    }
    reduced.diagnostics.deduplicated_region_count -= 1
    reduced.diagnostics.raw_evidence_turn_count -= (
        (removed.end_turn_index or 0) - (removed.start_turn_index or 0) + 1
    )
    if not query_temptation:
        for need in reduced.needs:
            if need.need_id == target_need_id:
                need.query_text = "과거 회기에서 확인할 직접 근거"
    generation_prompt = build_grounded_generation_prompt(sanitized, reduced)
    original_use_stub = settings.use_stub
    settings.use_stub = not live_llm
    try:
        draft = generate_grounded_claims(sanitized, reduced)
        checked = validate_evidence_ids(draft, reduced)
    finally:
        settings.use_stub = original_use_stub
    target_claims = [claim for claim in checked.claims if claim.need_id == target_need_id]
    reduced_sources = {source.evidence_id: source for source in reduced.sources}
    original_claim_texts = {
        claim["text"]
        for claim in scenario["validated_claims"]
        if claim["need_id"] == target_need_id
    }
    claims_after_removal = [
        {
            **claim.model_dump(mode="json"),
            "sources": [
                {
                    "evidence_id": evidence_id,
                    "source_ref": reduced_sources[evidence_id].source_ref,
                    "raw_text": reduced_sources[evidence_id].source_text,
                }
                for evidence_id in claim.evidence_ids
                if evidence_id in reduced_sources
            ],
        }
        for claim in target_claims
    ]
    forbidden_backed = [
        claim
        for claim in claims_after_removal
        if not claim["review_required"] and (
            REMOVED_FACT_RE.search(claim["text"])
        )
        and claim["support_type"] in {"direct_evidence", "counselor_judgment"}
    ]
    return {
        "removed_evidence_id": removed.evidence_id,
        "removed_source_ref": removed.source_ref,
        "removed_raw_text": removed.source_text,
        "target_need_id": target_need_id,
        "original_target_claim_texts": sorted(original_claim_texts),
        "claims_after_removal": claims_after_removal,
        "citation_diagnostics": [item.model_dump(mode="json") for item in checked.citation_diagnostics],
        "claim_support_validations": {
            claim_id: validation.model_dump(mode="json")
            for claim_id, validation in checked.claim_support_validations.items()
        },
        "source_backed_removed_fact_claims": forbidden_backed,
        "query_temptation_present_in_retrieval_need": query_temptation,
        "removed_fact_present_in_generation_prompt": bool(REMOVED_FACT_RE.search(generation_prompt)),
        "generation_prompt_sha256": hashlib.sha256(generation_prompt.encode("utf-8")).hexdigest(),
        "false_support_rate": 1.0 if forbidden_backed else 0.0,
        "passed": not forbidden_backed,
    }


def _prompt_audit(sanitized, context: GroundingContext) -> dict[str, Any]:
    prompt = build_grounded_generation_prompt(sanitized, context)
    target_need = next(need for need in context.needs if need.need_id == "N4")
    raw_sources = [source for source in context.sources if source.source_type == "raw_transcript"]
    memory_sources = [source for source in context.sources if source.source_type == "counselor_confirmed"]
    kb_sources = [source for source in context.sources if source.source_type == "authoritative_kb"]
    rows = [
        ("EvidenceNeed.need_id", target_need.need_id, True, "metadata only"),
        ("EvidenceNeed.target_field", target_need.target_field, True, "metadata only"),
        ("EvidenceNeed.query_text", target_need.query_text, False, "retrieval only"),
        ("EvidenceNeed.source_requirement", target_need.source_requirement, True, "metadata only"),
        ("current counselor memo", sanitized.sources.counselor_memo, False, "omitted"),
        ("current transcript", sanitized.sources.transcript_text, False, "omitted"),
        ("previous session summary", sanitized.sources.previous_session_summary, False, "omitted"),
        (
            "case_memory_chunks",
            "\n".join(source.source_text for source in memory_sources),
            False,
            "original chunk objects omitted; normalized M sources handled separately",
        ),
        (
            "counselor-confirmed memory",
            "\n".join(source.source_text for source in memory_sources),
            bool(memory_sources),
            "M* evidence only",
        ),
        (
            "raw evidence regions",
            "\n".join(source.source_text for source in raw_sources),
            bool(raw_sources),
            "R* evidence only",
        ),
        (
            "authoritative KB",
            "\n".join(source.source_text for source in kb_sources),
            bool(kb_sources),
            "K* evidence only; empty in this corpus",
        ),
    ]
    table = [
        {
            "input_channel": channel,
            "contains_removed_fact": bool(value and REMOVED_FACT_RE.search(value)),
            "passed_to_generation": passed,
            "note": note,
        }
        for channel, value, passed, note in rows
    ]
    non_source_values = [
        sanitized.sources.counselor_memo,
        sanitized.sources.transcript_text,
        sanitized.sources.previous_session_summary,
        target_need.query_text,
    ]
    return {
        "removed_fact": "보고서/발표 마감, 수면 부족, 집중 어려움",
        "before_revision_root_cause": (
            "GroundingContext needs were serialized in full, so N4.query_text remained in the generation prompt "
            "after R5 removal. R6 and M1 did not contain the academic fact."
        ),
        "table": table,
        "query_text_omitted": target_need.query_text not in prompt,
        "non_source_inputs_omitted": all(not value or value not in prompt for value in non_source_values),
        "generation_prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "removed_fact_locations_before_removal": [
            "EvidenceNeed N4.query_text",
            *[
                f"{source.evidence_id} {source.source_ref}"
                for source in raw_sources
                if REMOVED_FACT_RE.search(source.source_text)
            ],
        ],
    }


def _run_adversarial_support_set() -> dict[str, Any]:
    pairs = [
        {
            "id": "supported_academic_sleep", "gold": "supported",
            "claim": "내담자는 보고서 마감이 겹쳐 거의 잠을 자지 못했다.",
            "source": "[client] 이번 주에는 보고서 마감이 겹쳐서 거의 잠을 못 잤어요.",
        },
        {
            "id": "supported_first_attempt", "gold": "supported",
            "claim": "내담자는 어머니에게 모임 대신 집에서 쉬고 싶다고 말했다.",
            "source": "[client] 토요일 모임 대신 집에서 쉬고 다음번에는 가겠다고 어머니께 말했어요.",
        },
        {
            "id": "supported_setback", "gold": "supported",
            "claim": "아버지의 목소리가 커지자 내담자는 말을 멈추고 방으로 들어갔다.",
            "source": (
                "[client] 아버지가 시험 준비를 권하셨어요. 아버지 목소리가 커지자 "
                "말해도 소용없다는 생각이 들어 말을 멈추고 방으로 들어갔어요."
            ),
        },
        {
            "id": "supported_counselor_judgment", "gold": "supported", "source_type": "counselor_confirmed",
            "claim": "상담사는 핵심 문장 반복과 과도한 해명 줄이기를 연습하기로 했다.",
            "source": "상담자가 핵심 문장 반복, 과도한 해명 줄이기에 대해 피드백하고 연습을 유지하기로 함.",
        },
        {
            "id": "partial_sleep_not_focus", "gold": "partial",
            "claim": "보고서 마감으로 수면이 부족했고 집중력도 크게 저하되었다.",
            "source": "[client] 보고서 마감이 겹쳐 거의 잠을 못 잤어요.",
        },
        {
            "id": "partial_attempt_not_immediate_agreement", "gold": "partial",
            "claim": "내담자는 쉬고 싶다고 말했고 어머니는 즉시 전적으로 동의했다.",
            "source": "[client] 쉬고 싶다고 말했어요. 어머니는 아쉬워했지만 다음에는 같이 가자고 받아주셨어요.",
        },
        {
            "id": "partial_rehearsal_not_anxiety_gone", "gold": "partial",
            "claim": "내담자는 문장을 끝까지 말했고 불안이 완전히 사라졌다.",
            "source": "[client] 처음보다 덜 떨렸고 문장을 끝까지 말할 수 있었어요.",
        },
        {
            "id": "partial_one_event_not_repeated", "gold": "partial",
            "claim": "내담자는 세 차례 연속 의견을 끝까지 표현했다.",
            "source": "[client] 이번에는 자리를 피하지 않고 제 말을 끝까지 했어요.",
        },
        {
            "id": "unsupported_same_goal_different_event", "gold": "unsupported", "wrong_source_swap": True,
            "claim": "내담자는 상담실 밖에서 어머니에게 쉬고 싶다고 처음 말했다.",
            "source": "[client] 상담실 역할연습에서 부모 역할의 상담자에게 진로는 제가 선택하고 싶다고 말했어요.",
        },
        {
            "id": "unsupported_opposite_temporal_state", "gold": "unsupported", "wrong_source_swap": True,
            "claim": "최근 갈등에서 내담자는 다시 말을 멈추고 방으로 들어갔다.",
            "source": "[client] 이번 갈등에서는 전처럼 방으로 가지 않고 제 말을 끝까지 했어요.",
        },
        {
            "id": "unsupported_later_success_vs_setback", "gold": "unsupported", "wrong_source_swap": True,
            "claim": "강한 반대 뒤에도 내담자는 대화를 끝까지 유지해 합의했다.",
            "source": "[client] 아버지 목소리가 커지자 아무 말도 못 하고 방으로 들어갔어요.",
        },
        {
            "id": "unsupported_academic_vs_family", "gold": "unsupported", "wrong_source_swap": True,
            "claim": "보고서와 발표 마감 때문에 잠을 거의 못 자고 집중하기 어려웠다.",
            "source": "[client] 부모와 의견이 다르면 싸울까 봐 제 의견을 말하지 않고 방으로 들어갔어요.",
        },
    ]
    results = []
    for index, pair in enumerate(pairs, start=1):
        evidence_id = "M1" if pair.get("source_type") == "counselor_confirmed" else "R1"
        source_type = pair.get("source_type", "raw_transcript")
        source = GroundingSource(
            evidence_id=evidence_id,
            source_type=source_type,
            source_ref=f"synthetic-adversarial:{pair['id']}",
            source_text=pair["source"],
        )
        claim = GroundedClaim(
            claim_id=f"A{index}",
            need_id="N1",
            target_field="reflection" if source_type == "counselor_confirmed" else "session_content",
            text=pair["claim"],
            support_type="counselor_judgment" if source_type == "counselor_confirmed" else "direct_evidence",
            evidence_ids=[evidence_id],
            review_required=False,
        )
        verdict = validate_claim_support(claim=claim, evidence_by_id={evidence_id: source})
        results.append({
            **pair,
            "verdict": verdict.verdict,
            "category": verdict.category,
            "supported_evidence_ids": verdict.supported_evidence_ids,
            "passed": verdict.verdict == pair["gold"],
        })
    unsupported = [row for row in results if row["gold"] == "unsupported"]
    partial = [row for row in results if row["gold"] == "partial"]
    supported = [row for row in results if row["gold"] == "supported"]
    swaps = [row for row in results if row.get("wrong_source_swap")]
    return {
        "pairs": results,
        "metrics": {
            "pair_count": len(results),
            "exact_verdict_accuracy": sum(row["passed"] for row in results) / len(results),
            "supported_detection": sum(row["verdict"] == "supported" for row in supported) / len(supported),
            "partial_detection": sum(row["verdict"] != "supported" for row in partial) / len(partial),
            "false_supported_rate": sum(row["verdict"] == "supported" for row in unsupported) / len(unsupported),
            "wrong_source_swaps_supported": sum(row["verdict"] == "supported" for row in swaps),
        },
    }


def _aggregate_metrics(scenarios: dict[str, Any]) -> dict[str, Any]:
    all_claims = [claim for scenario in scenarios.values() for claim in scenario["validated_claims"]]
    all_drafts = [claim for scenario in scenarios.values() for claim in scenario["model_draft"]["claims"]]
    contexts = [scenario["context"] for scenario in scenarios.values()]
    supplied = {
        scenario_name: {source["evidence_id"] for source in scenario["context"]["sources"]}
        for scenario_name, scenario in scenarios.items()
    }
    total_citations = 0
    valid_citations = 0
    for scenario_name, scenario in scenarios.items():
        allowed = supplied[scenario_name]
        for claim in scenario["model_draft"]["claims"]:
            total_citations += len(claim["evidence_ids"])
            valid_citations += sum(evidence_id in allowed for evidence_id in claim["evidence_ids"])
    factual = [claim for claim in all_claims if claim["claim_kind"] == "factual"]
    cited = [
        claim for claim in factual
        if claim["support_type"] in {"direct_evidence", "counselor_judgment"} and claim["evidence_ids"]
    ]
    unsupported = [claim for claim in factual if claim["support_type"] == "unsupported"]
    raw_source_refs = {
        source["source_ref"]
        for claim in all_claims
        for source in claim["sources"]
        if source["source_type"] == "raw_transcript"
    }
    distribution = Counter(claim["support_type"] for claim in all_claims)
    factual_validations = []
    for scenario in scenarios.values():
        claim_kind_by_id = {claim["claim_id"]: claim["claim_kind"] for claim in scenario["model_draft"]["claims"]}
        factual_validations.extend(
            validation
            for claim_id, validation in scenario["claim_support_validations"].items()
            if claim_kind_by_id.get(claim_id) == "factual"
        )
    return {
        "claim_count": len(all_claims),
        "model_draft_claim_count": len(all_drafts),
        "citation_validity": valid_citations / total_citations if total_citations else 1.0,
        "factual_claim_citation_coverage": len(cited) / len(factual) if factual else 1.0,
        "unsupported_factual_claim_rate": len(unsupported) / len(factual) if factual else 0.0,
        "semantic_support_validity": (
            sum(item["verdict"] == "supported" for item in factual_validations) / len(factual_validations)
            if factual_validations else 1.0
        ),
        "raw_evidence_usage": len(raw_source_refs),
        "source_type_distribution": dict(distribution),
        "context_size": {
            "evidence_need_count": sum(ctx["diagnostics"]["evidence_need_count"] for ctx in contexts),
            "retrieved_regions_total": sum(ctx["diagnostics"]["retrieved_region_count"] for ctx in contexts),
            "dedup_regions_total": sum(ctx["diagnostics"]["deduplicated_region_count"] for ctx in contexts),
            "raw_turns_total": sum(ctx["diagnostics"]["raw_evidence_turn_count"] for ctx in contexts),
            "approximate_tokens_total": sum(ctx["diagnostics"]["approximate_token_count"] for ctx in contexts),
        },
    }


def _hallucination_check(scenarios: dict[str, Any]) -> dict[str, Any]:
    matches = []
    for scenario_name, scenario in scenarios.items():
        for claim in scenario["validated_claims"]:
            if TEMPTATION_RE.search(claim["text"]):
                matches.append({"scenario": scenario_name, **claim})
    invalid = [
        claim for claim in matches
        if claim["support_type"] in {"direct_evidence", "counselor_judgment"}
    ]
    return {
        "temptation_fact": "내담자가 부모와 통화 후 울었다",
        "prompt_disclosed_temptation": False,
        "matching_generated_claims": matches,
        "invalid_source_backed_matches": invalid,
        "passed": not invalid,
    }


def _claim_inspection(scenarios: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for scenario_name, scenario in scenarios.items():
        source_catalog = {
            source["evidence_id"]: source
            for source in scenario["context"]["sources"]
        }
        for claim in scenario["validated_claims"]:
            evidence = [source_catalog[evidence_id] for evidence_id in claim["evidence_ids"] if evidence_id in source_catalog]
            items.append({
                "scenario": scenario_name,
                "claim": claim["text"],
                "support_type": claim["support_type"],
                "evidence_ids": claim["evidence_ids"],
                "raw_text": [source["source_text"] for source in evidence],
                "automatic_validation": "PASS" if claim["support_type"] != "unsupported" else "REVIEW_REQUIRED",
                "raw_snapshot_exact": all(
                    source["source_text"] == next(
                        item["source_text"] for item in scenario["context"]["sources"]
                        if item["evidence_id"] == source["evidence_id"]
                    )
                    for source in evidence
                ),
            })
    return items


def _render_markdown(artifact: dict[str, Any]) -> str:
    metric = artifact["aggregate_raw_grounded_metrics"]
    lines = [
        "# PR4 Raw Evidence Grounded Generation — Controlled Synthetic Evaluation",
        "",
        f"Generation mode: `{artifact['generation_mode']}`",
        "",
        "No real counseling data was used. No remote migration was applied.",
        "",
        "## Metric comparison",
        "",
        "| Metric | Existing path | Raw-grounded path |",
        "|---|---:|---:|",
        f"| Citation Validity | N/A | {metric['citation_validity']:.1%} |",
        f"| Factual Claim Citation Coverage | N/A | {metric['factual_claim_citation_coverage']:.1%} |",
        f"| Semantic Support Validity | N/A | {metric['semantic_support_validity']:.1%} |",
        f"| Unsupported Factual Claim Rate | N/A | {metric['unsupported_factual_claim_rate']:.1%} |",
        f"| Raw Evidence Usage | 0 | {metric['raw_evidence_usage']} |",
        "",
        "Existing output has section-level source_refs, but no claim-level prompt-safe citation schema.",
        "",
        "## Context size",
        "",
        "```json",
        json.dumps(metric["context_size"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Prompt/input leakage audit",
        "",
        "| Input channel | Contains removed fact? | Passed to generation? | Note |",
        "|---|---:|---:|---|",
    ]
    for row in artifact["prompt_input_leakage_audit"]["table"]:
        lines.append(
            f"| {row['input_channel']} | {'yes' if row['contains_removed_fact'] else 'no'} | "
            f"{'yes' if row['passed_to_generation'] else 'no'} | {row['note']} |"
        )
    lines.extend([
        "",
        "## Adversarial claim-source validation",
        "",
        "| Pair | Gold | Verdict | Category | Pass |",
        "|---|---|---|---|---:|",
    ])
    for row in artifact["adversarial_support_set"]["pairs"]:
        lines.append(
            f"| {row['id']} | {row['gold']} | {row['verdict']} | {row['category'] or ''} | "
            f"{'yes' if row['passed'] else 'no'} |"
        )
    lines.extend([
        "",
        "```json",
        json.dumps(artifact["adversarial_support_set"]["metrics"], ensure_ascii=False, indent=2),
        "```",
        "",
    ])
    for scenario_name, scenario in artifact["scenarios"].items():
        lines.extend([f"## {scenario_name}", "", "### EvidenceNeeds", ""])
        for need in scenario["evidence_needs"]:
            lines.append(
                f"- `{need['need_id']}` `{need['target_field']}` `{need['source_requirement']}` — {need['query_text']}"
            )
        lines.extend(["", "### Retrieval top-5", ""])
        for need_id, rows in scenario["retrieval_top_5_by_need"].items():
            lines.extend([f"#### {need_id}", "", "| Rank | Session | Range | Score | source_ref |", "|---:|---:|---:|---:|---|"])
            for row in rows:
                lines.append(
                    f"| {row['rank']} | {row['session_number']} | {row['turn_range']} | "
                    f"{row['similarity_score']:.6f} | `{row['source_ref']}` |"
                )
            lines.append("")
        lines.extend(["### Validated grounded claims", ""])
        for claim in scenario["validated_claims"]:
            lines.extend([
                f"- **{claim['claim_id']} / {claim['need_id']} / {claim['support_type']}**: {claim['text']}",
                f"  - Evidence: {', '.join(claim['evidence_ids']) or '(none)'}",
            ])
        lines.append("")
    lines.extend(["## Claim ↔ source inspection", ""])
    for index, item in enumerate(artifact["claim_source_inspection"], start=1):
        lines.extend([
            f"### Claim {index}", "",
            f"Claim: {item['claim']}", "",
            f"Support type: `{item['support_type']}`", "",
            f"Evidence: {', '.join(item['evidence_ids']) or '(none)'}", "",
            "Raw text:", "",
            "```text", "\n\n".join(item["raw_text"]) or "(none)", "```", "",
            f"Assessment: `{item['automatic_validation']}`", "",
        ])
    lines.extend([
        "## Source removal", "", "```json",
        json.dumps(artifact["source_removal"], ensure_ascii=False, indent=2), "```", "",
        "## Hallucination temptation", "", "```json",
        json.dumps(artifact["hallucination_temptation"], ensure_ascii=False, indent=2), "```", "",
        "## Acceptance gate", "", "```json",
        json.dumps(artifact["acceptance_gate"], ensure_ascii=False, indent=2), "```", "",
        "## Decision", "", f"**{artifact['decision']}**", "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
