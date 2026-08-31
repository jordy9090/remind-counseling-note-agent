"""Final counselor-demo preparation and longitudinal retrieval benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_evaluation_harness_v3 as v3  # noqa: E402
from app.core.config import settings  # noqa: E402
from research.legacy_muspsy_evaluation.provenance import (  # noqa: E402
    CASE_ID,
    PROVENANCE_CLASSES,
    map_source_refs,
    provenance_document,
    provenance_markdown,
)
from app.graph import nodes  # noqa: E402
from app.graph.supervision_report import run_supervision_report_pipeline  # noqa: E402
from app.schemas.note import SessionInput, SupervisionReportRequest  # noqa: E402
from app.services.deidentification import COUNSELOR_PLACEHOLDER_LABELS  # noqa: E402
from app.services.supabase_storage import storage  # noqa: E402

OUTPUT = ROOT / "eval_outputs_v4"
CANONICAL = ROOT / "sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json"
RICH_INPUT = ROOT / "sample_data/muspsy_demo/session_input_005_muspsy_1416_demo_rich.json"
RETRIEVAL_INPUT = ROOT / "sample_data/muspsy_demo/session_input_005_muspsy_1416_retrieval_eval.json"
MEMORIES = ROOT / "sample_data/muspsy_demo/original_source/memories_1416.txt"
CONDITIONS = v3.CONDITIONS
CONDITION_FOLDERS = {item[0]: item[1] for item in CONDITIONS}
INTERNAL_PLACEHOLDERS = sorted(COUNSELOR_PLACEHOLDER_LABELS)
LEGACY_TERMS = [
    "CASE-" + "DEMO-001",
    "가명 " + "은하",
    "김" + "민서",
    "이" + "수진",
    "마음연결 " + "심리" + "상담센터",
]
DOCUMENT_NAMES = {
    "01_session_summary": "session_summary.txt",
    "02_session_note": "session_note.txt",
    "03_supervision_report": "supervision_report.txt",
    "04_termination_report": "termination_report.txt",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if OUTPUT.exists():
        if not args.overwrite:
            raise SystemExit(f"{OUTPUT} already exists; use --overwrite to replace v4 artifacts.")
        if OUTPUT.parent != ROOT or OUTPUT.name != "eval_outputs_v4":
            raise SystemExit("Refusing to remove an unexpected output path.")
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)

    rich_payload, retrieval_payload = prepare_inputs_and_provenance()
    benchmark = run_retrieval_benchmark(retrieval_payload)
    results = run_demo_quality(rich_payload)
    build_review_packet(rich_payload, results)
    write_demo_summary(results)
    write_benchmark_summary(benchmark)
    return 0 if all(item["quality_gate_pass"] for item in results) else 2


def prepare_inputs_and_provenance() -> tuple[dict[str, Any], dict[str, Any]]:
    rich = json.loads(CANONICAL.read_text(encoding="utf-8"))
    if rich.get("case_id") != CASE_ID or int(rich.get("session_number") or 0) != 5:
        raise RuntimeError("Canonical CASE-MUSPSY-1416 session 5 input is required.")
    rich["persist"] = False
    retrieval_eval = json.loads(json.dumps(rich, ensure_ascii=False))
    retrieval_eval["previous_session_summary"] = ""
    old_recap = (
        "지난 회기에서 계획한 룸메이트와의 소규모 외출은 아직 구체적인 날짜를 정하지 못했으나, "
        "사회적 상황을 앞두고 불안이 높아질 때 초대를 미루거나 거절하고 이후 고립감과 자기비난이 "
        "커지는 자신의 반복 패턴을 비교적 명확하게 설명하였다."
    )
    current_only = (
        "사회적 상황을 앞두고 불안이 높아질 때 초대를 미루거나 거절하고 이후 고립감과 자기비난이 "
        "커지는 자신의 반복 패턴을 비교적 명확하게 설명하였다."
    )
    memo = str(retrieval_eval["counselor_memo"])
    if old_recap not in memo:
        raise RuntimeError("Expected prior-session recap was not found; retrieval input was not rewritten.")
    retrieval_eval["counselor_memo"] = memo.replace(old_recap, current_only, 1)

    RICH_INPUT.write_text(json.dumps(rich, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RETRIEVAL_INPUT.write_text(json.dumps(retrieval_eval, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    provenance_dir = OUTPUT / "provenance"
    provenance_dir.mkdir()
    (provenance_dir / "input_provenance.json").write_text(
        json.dumps(provenance_document(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (provenance_dir / "INPUT_PROVENANCE.md").write_text(provenance_markdown(), encoding="utf-8")
    return rich, retrieval_eval


@contextmanager
def capture_rpc_calls():
    calls: list[dict[str, Any]] = []
    original = storage.rpc

    def traced(function_name: str, params: dict[str, Any]):
        started = time.perf_counter()
        try:
            result = original(function_name, params)
            calls.append({"rpc": function_name, "latency_ms": int((time.perf_counter() - started) * 1000), "result_count": len(result or []) if isinstance(result, list) else None, "failure": None})
            return result
        except Exception as error:
            calls.append({"rpc": function_name, "latency_ms": int((time.perf_counter() - started) * 1000), "result_count": 0, "failure": str(error)})
            raise

    storage.rpc = traced
    try:
        yield calls
    finally:
        storage.rpc = original


def run_retrieval_benchmark(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = OUTPUT / "retrieval_benchmark"
    root.mkdir()
    runs = [
        ("D", "D_lightweight", False, False, "lightweight"),
        ("E", "E_dense", True, False, "dense"),
        ("F", "F_hybrid", True, True, "hybrid"),
    ]
    results = []
    original = MEMORIES.read_text(encoding="utf-8")
    for label, folder_name, dense, hybrid, mode in runs:
        folder = root / folder_name
        folder.mkdir()
        session_input = SessionInput(**{**payload, "target_document_type": "session_note", "persist": False})
        started = time.perf_counter()
        error = None
        try:
            with capture_rpc_calls() as rpc_calls, v3.condition_settings(True, dense, hybrid):
                state, trace, generation_latency = v3.trace_graph(v3.note_graph, session_input)
            response = v3.response_from_state(state)
            if response.stub:
                raise RuntimeError("stub=true rejected by retrieval benchmark")
            retrieval = detailed_retrieval(state, response, mode, rpc_calls)
            validation = validate_retrieval(label, retrieval, original)
            status = "PASS" if validation["pass"] else "FAIL"
            summary = v3.summary_text(response)
            (folder / "trace.json").write_text(_json(trace), encoding="utf-8")
            (folder / "retrieval.json").write_text(_json(retrieval), encoding="utf-8")
            (folder / "retrieval_validation.json").write_text(_json(validation), encoding="utf-8")
            (folder / "generated_summary.txt").write_text(summary, encoding="utf-8")
        except Exception as exc:
            generation_latency = int((time.perf_counter() - started) * 1000)
            retrieval = {"retrieval_query": "", "case_retrieval": {"items": []}, "kb_retrieval": {"items": []}, "notices": []}
            validation = {"pass": False, "status": "RETRIEVAL_ENV_BLOCKED", "failures": [str(exc)]}
            status = "RETRIEVAL_ENV_BLOCKED"
            error = {"exception_type": type(exc).__name__, "exception_message": str(exc)}
            (folder / "trace.json").write_text("[]\n", encoding="utf-8")
            (folder / "retrieval.json").write_text(_json(retrieval), encoding="utf-8")
            (folder / "retrieval_validation.json").write_text(_json(validation), encoding="utf-8")
            (folder / "generated_summary.txt").write_text("", encoding="utf-8")
        metadata = {
            "benchmark_id": label,
            "status": status,
            "case_id": CASE_ID,
            "session_number": 5,
            "input_track": "retrieval_benchmark",
            "model": settings.openai_model,
            "temperature": 0.3,
            "persist": False,
            "stub": False if status != "RETRIEVAL_ENV_BLOCKED" else None,
            "case_retrieval_method": retrieval.get("case_retrieval", {}).get("method", ""),
            "kb_retrieval_method": retrieval.get("kb_retrieval", {}).get("method", ""),
            "retrieved_case_memory_count": len(retrieval.get("case_retrieval", {}).get("items", [])),
            "generation_latency_ms": generation_latency,
            **(error or {}),
        }
        (folder / "metadata.json").write_text(_json(metadata), encoding="utf-8")
        results.append({**metadata, "validation": validation})
    return results


def detailed_retrieval(state: dict[str, Any], response: Any, mode: str, rpc_calls: list[dict[str, Any]]) -> dict[str, Any]:
    dense_chunks = list(state.get("retrieved_case_memory_chunks") or [])
    kb_chunks = list(state.get("retrieved_authoritative_kb_chunks") or [])
    case_items = []
    if dense_chunks:
        for rank, chunk in enumerate(dense_chunks, 1):
            case_items.append({
                "rank": rank,
                "case_id": CASE_ID,
                "session_number": chunk.session_number,
                "chunk_id": chunk.chunk_id,
                "field_type": chunk.field_type,
                "source_ref": chunk.source_ref,
                "chunk_text": chunk.chunk_text,
                "score": chunk.similarity_score,
                "latency_ms": chunk.total_latency_ms,
                "rpc": "match_case_memory_chunks",
                "retrieval_method": chunk.retrieval_method,
                "metadata": chunk.metadata,
            })
    else:
        for rank, item in enumerate(response.retrieved_case_context, 1):
            case_items.append({
                "rank": rank,
                "case_id": CASE_ID,
                "session_number": item.session_number,
                "chunk_id": item.session_id,
                "field_type": "confirmed_session_note",
                "source_ref": item.source_ref,
                "chunk_text": item.summary,
                "score": None,
                "latency_ms": None,
                "rpc": None,
                "retrieval_method": "supabase_table_lookup",
            })
    kb_items = [
        {
            "rank": rank,
            "chunk_id": chunk.chunk_id,
            "field_type": chunk.field_type,
            "source_ref": chunk.source_ref,
            "chunk_text": chunk.chunk_text,
            "score": chunk.similarity_score,
            "latency_ms": chunk.total_latency_ms,
            "rpc": "hybrid_search_kb" if mode == "hybrid" else "match_kb_chunks",
            "retrieval_method": chunk.retrieval_method,
            "metadata": chunk.metadata,
        }
        for rank, chunk in enumerate(kb_chunks, 1)
    ]
    case_method = "case_memory_dense" if dense_chunks else ("supabase_table_lookup" if case_items else "none")
    kb_method = "hybrid" if mode == "hybrid" and kb_items else ("dense" if mode == "dense" and kb_items else ("lightweight" if mode == "lightweight" else "none"))
    refs = [item["source_ref"] for item in [*case_items, *kb_items]]
    return {
        "retrieval_query": state.get("retrieval_query", ""),
        "case_retrieval": {"method": case_method, "rpc": "match_case_memory_chunks" if dense_chunks else None, "items": case_items},
        "kb_retrieval": {"method": kb_method, "rpc": "hybrid_search_kb" if mode == "hybrid" and kb_items else ("match_kb_chunks" if mode == "dense" and kb_items else None), "items": kb_items},
        "rpc_calls": rpc_calls,
        "notices": response.retrieval_report.notices,
        "failures": response.retrieval_report.failures,
        "source_ref_provenance": map_source_refs(refs),
    }


def validate_retrieval(label: str, retrieval: dict[str, Any], original: str) -> dict[str, Any]:
    case_items = retrieval["case_retrieval"]["items"]
    kb_items = retrieval["kb_retrieval"]["items"]
    failures = []
    if not case_items:
        failures.append("No longitudinal case context was retrieved.")
    for item in case_items:
        if item.get("case_id") != CASE_ID:
            failures.append(f"Cross-case source: {item.get('case_id')}")
        if item.get("session_number") not in {1, 2, 3, 4}:
            failures.append(f"Invalid prior session: {item.get('session_number')}")
        if not item.get("source_ref") or not item.get("chunk_text"):
            failures.append("Unresolved source ref or empty retrieved text.")
        if item.get("chunk_text") and item["chunk_text"] not in original:
            failures.append(f"Retrieved text is not an exact MusPsy original substring: {item.get('source_ref')}")
    if label == "D" and retrieval["case_retrieval"]["method"] != "supabase_table_lookup":
        failures.append("D did not use lightweight recent-session retrieval.")
    if label in {"E", "F"}:
        if retrieval["case_retrieval"]["method"] != "case_memory_dense":
            failures.append(f"{label} did not use dense case-memory retrieval.")
        if not all(item.get("retrieval_method") == "case_memory_dense" for item in case_items):
            failures.append(f"{label} case-memory method mismatch.")
    if label == "F":
        if retrieval["kb_retrieval"]["method"] != "hybrid":
            failures.append("F KB retrieval method is not hybrid.")
        if not any(call.get("rpc") == "hybrid_search_kb" and not call.get("failure") for call in retrieval["rpc_calls"]):
            failures.append("F did not successfully call hybrid_search_kb.")
        if not kb_items or not all(str(item.get("retrieval_method", "")).startswith("hybrid") for item in kb_items):
            failures.append("F KB results do not report hybrid retrieval.")
    return {
        "pass": not failures,
        "failures": failures,
        "case_context_count": len(case_items),
        "retrieved_case_memory_count": len(case_items) if label in {"E", "F"} else 0,
        "retrieved_session_numbers": sorted({item.get("session_number") for item in case_items if item.get("session_number") is not None}),
        "source_refs_resolve": not any("source ref" in item.lower() for item in failures),
        "retrieved_text_matches_original": not any("original substring" in item for item in failures),
        "kb_result_count": len(kb_items),
    }


def run_demo_quality(payload: dict[str, Any]) -> list[dict[str, Any]]:
    root = OUTPUT / "demo_quality"
    root.mkdir()
    graph7 = v3._seven_node_graph()
    prompt_schema_version = hashlib.sha256(
        (ROOT / "backend/app/graph/nodes.py").read_bytes() + (ROOT / "backend/app/schemas/note.py").read_bytes()
    ).hexdigest()
    input_hash = _hash_payload(payload)
    results = []
    for label, folder_name, node_count, rag, dense, hybrid, rag_mode in CONDITIONS:
        folder = root / folder_name
        folder.mkdir()
        graph = graph7 if node_count == 7 else v3.note_graph
        session_input = SessionInput(**{**payload, "target_document_type": "session_note", "persist": False})
        started = time.perf_counter()
        error = None
        try:
            with capture_rpc_calls() as rpc_calls, v3.condition_settings(rag, dense, hybrid):
                state, trace, latency = v3.trace_graph(graph, session_input)
            response = v3.response_from_state(state)
            if response.stub:
                raise RuntimeError("stub=true rejected by demo-quality evaluation")
            report = run_supervision_report_pipeline(SupervisionReportRequest(session_input=session_input, session_summary_draft=response.session_summary_draft, demo_mode=False))
            retrieval = detailed_retrieval(state, response, rag_mode, rpc_calls) if rag else {
                "retrieval_query": state.get("retrieval_query", ""),
                "case_retrieval": {"method": "none", "rpc": None, "items": []},
                "kb_retrieval": {"method": "none", "rpc": None, "items": []},
                "rpc_calls": [], "notices": response.retrieval_report.notices, "failures": response.retrieval_report.failures, "source_ref_provenance": {},
            }
            texts = {
                "01_session_summary": v3.summary_text(response),
                "02_session_note": v3.document_text("상담일지 초안", response.session_note_draft),
                "03_supervision_report": v3.supervision_text(report),
                "04_termination_report": v3.document_text("종결보고서 초안", response.termination_report_draft),
            }
            quality, quality_metadata, provenance_map = quality_check(response, report, retrieval, rag, texts, payload, latency)
            (folder / "trace.json").write_text(_json(trace), encoding="utf-8")
            (folder / "retrieval.json").write_text(_json(retrieval), encoding="utf-8")
            (folder / "raw_generate_response.json").write_text(_json(response.model_dump(mode="json")), encoding="utf-8")
            (folder / "source_ref_provenance.json").write_text(_json(provenance_map), encoding="utf-8")
            for name, data, text in (
                ("01_session_summary", response.session_summary_draft, texts["01_session_summary"]),
                ("02_session_note", response.session_note_draft, texts["02_session_note"]),
                ("03_supervision_report", report, texts["03_supervision_report"]),
                ("04_termination_report", response.termination_report_draft, texts["04_termination_report"]),
            ):
                (folder / f"{name}.json").write_text(_json(v3.jsonable(data)), encoding="utf-8")
                (folder / f"{name}.txt").write_text(text, encoding="utf-8")
            (folder / "quality_check.json").write_text(_json(quality), encoding="utf-8")
            (folder / "quality_metadata.json").write_text(_json(quality_metadata), encoding="utf-8")
            status = "PASS" if quality["pass"] else "QUALITY_GATE_FAIL"
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            response = report = None
            quality = {"pass": False, "unsupported_claims": [], "source_ref_errors": [], "placeholder_leakage": [], "legacy_contamination": [], "verification_consistency": False, "supplementary_claims_used": [], "termination_overclaim": False}
            quality_metadata = {}
            status = "FAILED_GENERATION"
            error = {"exception_type": type(exc).__name__, "exception_message": str(exc)}
            (folder / "quality_check.json").write_text(_json(quality), encoding="utf-8")
            (folder / "quality_metadata.json").write_text(_json(quality_metadata), encoding="utf-8")
        metadata = {
            "condition": label,
            "status": status,
            "graph_version": f"{node_count}-node",
            "rag_mode": rag_mode,
            "input_track": "demo_quality",
            "model": settings.openai_model,
            "temperature": 0.3,
            "stub": response.stub if response else None,
            "case_id": CASE_ID,
            "session_number": 5,
            "persist": False,
            "input_sha256": input_hash,
            "prompt_schema_version": prompt_schema_version,
            "generation_latency_ms": latency,
            "quality_gate_pass": quality.get("pass", False),
            "document_success": {"session_summary": response is not None, "session_note": bool(response and response.session_note_draft), "supervision_report": report is not None, "termination_report": bool(response and response.termination_report_draft)},
            "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **(error or {}),
        }
        (folder / "metadata.json").write_text(_json(metadata), encoding="utf-8")
        results.append({**metadata, "folder": folder_name, "quality_metadata": quality_metadata})
    return results


def quality_check(response: Any, report: Any, retrieval: dict[str, Any], rag: bool, texts: dict[str, str], payload: dict[str, Any], latency: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    full_text = "\n".join(texts.values())
    catalog = nodes._source_catalog(response.sanitized_input, response.retrieved_case_context)
    for scope in ("case_retrieval", "kb_retrieval"):
        for item in retrieval.get(scope, {}).get("items", []):
            if item.get("source_ref"):
                catalog[item["source_ref"]] = item.get("chunk_text", "")
    refs = collect_source_refs(response)
    provenance_map = map_source_refs(refs)
    source_ref_errors = sorted(ref for ref in refs if ref not in catalog or provenance_map.get(ref) is None)
    source_type_mismatches = sorted({
        item.content
        for item in response.evidence_mapped_data.items
        if item.source_refs and not any(nodes._text_similarity(item.content, catalog.get(ref, "")) >= 0.02 for ref in item.source_refs)
    })
    unsupported = [item.claim for item in response.verification_report.unsupported_or_risky_claims] + list(report.aiReview.unsupportedClaims)
    unsupported.extend(item.content for item in response.evidence_mapped_data.items if item.evidence_type == "direct" and not item.source_refs)
    placeholder_leakage = sorted(token for token in INTERNAL_PLACEHOLDERS if token in full_text)
    legacy = sorted(term for term in LEGACY_TERMS if term in full_text)
    empty_sections = []
    for name, text in texts.items():
        if not text.strip():
            empty_sections.append(name)
    for draft_name, draft in (("session_note", response.session_note_draft), ("termination_report", response.termination_report_draft)):
        for section, value in draft.sections.items():
            if not str(value).strip():
                empty_sections.append(f"{draft_name}.{section}")
    debug_exposure = sorted(token for token in ("source_refs", "retrieval_method", "graph_nodes", "raw_generate_response", "structured_case_data", '{"') if token in full_text)
    termination_text = texts["04_termination_report"]
    termination_overclaim = bool(re.search(r"(?:종결되었|상담을\s*종결함|종결\s*확정|성공적으로\s*종결)", termination_text))
    concrete_fact_errors = unsupported_concrete_facts(full_text, payload)
    verification_consistency = all(
        section.requires_review
        for section in (response.session_summary_draft.reflection,)
        if section.evidence_type != "direct"
    )
    rag_off_error = not rag and bool(retrieval.get("case_retrieval", {}).get("items") or retrieval.get("kb_retrieval", {}).get("items"))
    supplementary_refs = sorted(ref for ref, item in provenance_map.items() if item and item.get("source_class") == "synthetic_demo_supplement")
    document_checks = {
        name: {
            "word_count": len(text.split()),
            "empty": not bool(text.strip()),
            "placeholder_leakage": [token for token in INTERNAL_PLACEHOLDERS if token in text],
            "legacy_contamination": [term for term in LEGACY_TERMS if term in text],
            "debug_metadata_exposure": [token for token in debug_exposure if token in text],
        }
        for name, text in texts.items()
    }
    failures = [
        *unsupported,
        *source_ref_errors,
        *source_type_mismatches,
        *placeholder_leakage,
        *legacy,
        *empty_sections,
        *debug_exposure,
        *concrete_fact_errors,
    ]
    if response.stub:
        failures.append("stub=true")
    if termination_overclaim:
        failures.append("termination_overclaim")
    if not verification_consistency:
        failures.append("verification_inconsistency")
    if rag_off_error:
        failures.append("rag_off_retrieval_nonzero")
    quality = {
        "pass": not failures,
        "unsupported_claims": sorted(set(unsupported + concrete_fact_errors)),
        "source_ref_errors": source_ref_errors,
        "source_type_mismatches": source_type_mismatches,
        "placeholder_leakage": placeholder_leakage,
        "legacy_contamination": legacy,
        "verification_consistency": verification_consistency,
        "supplementary_claims_used": supplementary_refs,
        "termination_overclaim": termination_overclaim,
        "counselor_output_empty": empty_sections,
        "internal_metadata_exposure": debug_exposure,
        "rag_off_zero_retrieval": not rag_off_error,
        "stub": response.stub,
        "document_checks": document_checks,
    }
    classes = [item.get("source_class") for item in provenance_map.values() if item]
    summary_sections = [
        response.session_summary_draft.session_theme, response.session_summary_draft.presenting_problem,
        response.session_summary_draft.session_content, response.session_summary_draft.counselor_intervention,
        response.session_summary_draft.client_response, response.session_summary_draft.reflection,
        response.session_summary_draft.next_plan,
    ]
    quality_metadata = {
        "word_count": {name: len(text.split()) for name, text in texts.items()},
        "empty_section_count": len(empty_sections),
        "review_required_count": sum(section.requires_review for section in summary_sections),
        "unsupported_claim_count": len(quality["unsupported_claims"]),
        "weak_grounding_count": len(response.verification_report.weakly_grounded_items),
        "supplementary_input_claim_count": classes.count("synthetic_demo_supplement"),
        "original_source_claim_count": classes.count("muspsy_original") + classes.count("derived_from_source"),
        "previous_session_claim_count": sum(ref.startswith("previous_session") for ref in refs),
        "retrieved_context_claim_count": classes.count("retrieved_context"),
        "quality_gate": quality["pass"],
        "latency_ms": latency,
    }
    return quality, quality_metadata, provenance_map


def collect_source_refs(response: Any) -> list[str]:
    refs = [ref for item in response.evidence_mapped_data.items for ref in item.source_refs]
    for section in (
        response.session_summary_draft.session_theme, response.session_summary_draft.presenting_problem,
        response.session_summary_draft.session_content, response.session_summary_draft.counselor_intervention,
        response.session_summary_draft.client_response, response.session_summary_draft.reflection,
        response.session_summary_draft.next_plan,
    ):
        refs.extend(section.source_refs)
    for draft in (response.session_note_draft, response.termination_report_draft):
        for item in draft.source_refs.values():
            refs.extend(item)
    return sorted(set(refs))


def unsupported_concrete_facts(text: str, payload: dict[str, Any]) -> list[str]:
    allowed = "\n".join(str(payload.get(key, "")) for key in ("counselor_memo", "transcript_text", "previous_session_summary", "counseling_goal", "psychological_test_summary", "nonverbal_notes"))
    errors = []
    for match in re.finditer(r"\b(SIAS|BAI|PHQ-?9)\D{0,12}(\d{1,3})", text, re.IGNORECASE):
        if match.group(0) not in allowed and not re.search(rf"{re.escape(match.group(1))}\D{{0,12}}{match.group(2)}", allowed, re.IGNORECASE):
            errors.append(f"unattributed psychological score: {match.group(0)}")
    for sentence in re.split(r"(?<=[.!?다])\s+|\n+", text):
        if re.search(r"(어머니|아버지|부모|형제|자매|가족관계)", sentence) and not re.search(r"(확인 필요|제공된 자료에 없는|정보는 생성하지)", sentence):
            if not any(term in allowed for term in re.findall(r"어머니|아버지|부모|형제|자매|가족관계", sentence)):
                errors.append(f"unattributed family claim: {sentence.strip()}")
        if re.search(r"(진단되었|진단명|확진|사회불안장애)", sentence) and not re.search(r"(확정하지|진단하지|확인 필요)", sentence):
            if sentence.strip() not in allowed:
                errors.append(f"unattributed diagnosis claim: {sentence.strip()}")
        if re.search(r"(급성\s*위험도는?\s*(?:중간|높|고위험)|자살\s*계획이\s*있|자해\s*충동이\s*있)", sentence):
            if sentence.strip() not in allowed:
                errors.append(f"unattributed acute-risk claim: {sentence.strip()}")
    return sorted(set(errors))


def build_review_packet(payload: dict[str, Any], results: list[dict[str, Any]]) -> None:
    review_root = OUTPUT / "gpt_review"
    review_root.mkdir()
    internal = OUTPUT / "internal"
    internal.mkdir()
    passing = [item for item in results if item["quality_gate_pass"]]
    if len(passing) != 6:
        raise RuntimeError("Blind packet requires six quality-gate-passing candidates.")
    shuffled = list(passing)
    random.Random(int(_hash_payload(payload)[:16], 16)).shuffle(shuffled)
    mapping = {}
    for index, item in enumerate(shuffled, 1):
        candidate_id = f"Candidate-{index:02d}"
        mapping[candidate_id] = {"condition": item["condition"], "source_folder": item["folder"]}
        candidate = review_root / candidate_id
        candidate.mkdir()
        source = OUTPUT / "demo_quality" / item["folder"]
        for source_stem, target_name in DOCUMENT_NAMES.items():
            shutil.copyfile(source / f"{source_stem}.txt", candidate / target_name)
        neutral_metadata = dict(item["quality_metadata"])
        (candidate / "quality_metadata.json").write_text(_json(neutral_metadata), encoding="utf-8")
    (internal / "blind_condition_map.json").write_text(_json(mapping), encoding="utf-8")
    (review_root / "CHATGPT_REVIEW_PROMPT.md").write_text(review_prompt(), encoding="utf-8")
    (review_root / "SOURCE_GROUND_TRUTH.md").write_text(source_ground_truth(payload), encoding="utf-8")
    (review_root / "INPUT_PROVENANCE.md").write_text(provenance_markdown(), encoding="utf-8")
    zip_path = OUTPUT / "gpt_review_packet.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(review_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(OUTPUT))
    verify_blind_zip(zip_path)


def verify_blind_zip(zip_path: Path) -> None:
    forbidden = ["blind_condition_map", "7node", "11node", "7-node", "11-node", "no_rag", "lightweight", "dense", "hybrid"]
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            lowered = name.lower()
            if any(token in lowered for token in forbidden):
                raise RuntimeError(f"Blind ZIP filename exposes a condition: {name}")
            if name.endswith((".txt", ".md", ".json")):
                content = archive.read(name).decode("utf-8")
                if any(token in content for token in INTERNAL_PLACEHOLDERS):
                    raise RuntimeError(f"Blind ZIP contains internal placeholder in {name}")


def review_prompt() -> str:
    return """# ChatGPT Blind Review Prompt

너는 심리상담사 대상 AI 문서화 제품의 출력 품질 reviewer다.

6개의 Candidate는 동일한 CASE-MUSPSY-1416 입력에서 생성되었다. SOURCE_GROUND_TRUTH.md와 INPUT_PROVENANCE.md를 기준으로 각 Candidate의 문서를 비교한다.

MusPsy original과 synthetic_demo_supplement는 모두 허용된 입력이다. 단 입력이나 retrieved source에 없는 새로운 구체적 사실을 생성하면 hallucination으로 판단한다.

평가 목표는 **실제 상담사가 가장 적은 수정으로 사용할 가능성이 높은 출력 2개**를 고르는 것이다.

평가 기준:

1. Factual grounding / hallucination
2. 핵심 상담 내용 보존
3. 상담자 개입과 내담자 반응 구분
4. 과도한 임상적 추론 여부
5. 이전 회기 맥락 사용의 적절성
6. 문서 구조와 가독성
7. 상담사가 실제 기록으로 사용하기 위한 수정 부담
8. 수퍼비전 보고서의 유용성
9. 내부 placeholder / 시스템 표현 노출 여부
10. 전체 counselor-demo readiness

quality_metadata의 PASS 여부만 믿지 말고 실제 문장과 source를 직접 비교한다. 현재 사례는 진행 중이므로 termination report의 비중은 낮게 본다.

최종 선정 가중치:

1. session_note가 가장 중요
2. session_summary가 두 번째
3. supervision_report가 세 번째
4. termination_report는 보조 평가

다음 형식으로 출력한다.

## Overall ranking

1~6위

## Best two

Candidate-XX
Candidate-YY

## Why these two

각 후보의 구체적 장점

## Risks to mention during counselor demo

각 후보에서 상담사에게 꼭 확인할 부분

## Rejected candidates

나머지가 떨어진 핵심 이유 1~2줄

마지막 줄은 반드시 정확히 다음 형식으로 작성한다.

SELECTED_CANDIDATES=["Candidate-XX","Candidate-YY"]
"""


def source_ground_truth(payload: dict[str, Any]) -> str:
    sections = [
        ("Current transcript — derived_from_source", payload["transcript_text"]),
        ("Previous sessions 1-4 — derived_from_source", payload["previous_session_summary"]),
        ("Counselor memo — mixed, conservatively synthetic_demo_supplement", payload["counselor_memo"]),
        ("Counseling goal — derived_from_source", payload["counseling_goal"]),
        ("Psychological tests and risk screening — synthetic_demo_supplement", payload["psychological_test_summary"]),
        ("Nonverbal/MSE-style observations — synthetic_demo_supplement", payload["nonverbal_notes"]),
        ("Key issue tags — derived_from_source", ", ".join(payload["key_issue_tags"])),
    ]
    lines = ["# Source Ground Truth", "", f"Case: {CASE_ID}", "Current session: 5", ""]
    for title, text in sections:
        lines.extend([f"## {title}", "", str(text).strip(), ""])
    lines.extend(["## Review boundary", "", "인구학, 가족관계, 확정 진단, 추가 검사 점수 또는 새로운 위험정보를 빈칸 보완 목적으로 생성하면 안 된다.", ""])
    return "\n".join(lines)


def write_demo_summary(results: list[dict[str, Any]]) -> None:
    lines = ["# Demo Quality v4 Summary", "", "Winner selection is intentionally deferred to ChatGPT blind review.", "", "| Condition | Status | Stub | Four documents | Quality gate | Model | Latency |", "| --- | --- | ---: | ---: | ---: | --- | ---: |"]
    for item in results:
        docs = item["document_success"]
        lines.append(f"| {item['condition']} | {item['status']} | {item['stub']} | {all(docs.values())} | {item['quality_gate_pass']} | {item['model']} | {item['generation_latency_ms']} ms |")
    (OUTPUT / "demo_quality" / "DEMO_QUALITY_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_benchmark_summary(results: list[dict[str, Any]]) -> None:
    lines = ["# Longitudinal Retrieval Benchmark", "", "Track 2 uses session 5 input with previous_session_summary removed. It is separate from counselor demo-quality generation.", "", "| Benchmark | Status | Case method | KB method | Retrieved case count | Sessions |", "| --- | --- | --- | --- | ---: | --- |"]
    for item in results:
        sessions = ", ".join(map(str, item["validation"].get("retrieved_session_numbers", [])))
        lines.append(f"| {item['benchmark_id']} | {item['status']} | {item['case_retrieval_method']} | {item['kb_retrieval_method']} | {item['retrieved_case_memory_count']} | {sessions} |")
    lines.extend(["", "F uses dense case-memory retrieval and hybrid authoritative-KB retrieval; it is not described as hybrid case-memory retrieval.", ""])
    (OUTPUT / "retrieval_benchmark" / "RETRIEVAL_BENCHMARK_SUMMARY.md").write_text("\n".join(lines), encoding="utf-8")


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(v3.jsonable(value), ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
