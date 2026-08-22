"""Run A-F with canonical MusPsy input, full drafts, traces, and quality gates."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from langgraph.graph import END, StateGraph

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.core.config import settings  # noqa: E402
from app.graph import nodes  # noqa: E402
from app.graph.graph import NoteGraphState, _build_confirmed_session_note, note_graph  # noqa: E402
from app.graph.supervision_report import run_supervision_report_pipeline  # noqa: E402
from app.schemas.note import GenerateNoteResponse, RetrievalReport, SessionInput, SupervisionReportRequest  # noqa: E402
from app.services import retrieval  # noqa: E402
from app.services.supabase_storage import storage  # noqa: E402

GRAPH_7_NODES = ["sanitize_input", "retrieve_context", "structure_session", "map_evidence", "generate_summary", "verify_output", "transform_document_preview"]
GRAPH_11_NODES = ["sanitize_input", "formulate_retrieval_query", "retrieve_case_memory", "retrieve_authoritative_kb", "fuse_and_rerank", "structure_session", "map_evidence", "generate_summary", "verify_output", "conditional_revision", "transform_document_preview"]


def _seven_node_graph():
    workflow = StateGraph(NoteGraphState)
    for name in GRAPH_7_NODES:
        workflow.add_node(name, getattr(nodes, name))
    workflow.set_entry_point(GRAPH_7_NODES[0])
    for left, right in zip(GRAPH_7_NODES, GRAPH_7_NODES[1:]):
        workflow.add_edge(left, right)
    workflow.add_edge(GRAPH_7_NODES[-1], END)
    return workflow.compile()

OUTPUT = ROOT / "eval_outputs_v3"
INPUT = ROOT / "sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json"
CONDITIONS = [
    ("A", "A_7node_no_rag", 7, False, False, False, "off"),
    ("B", "B_7node_lightweight", 7, True, False, False, "lightweight"),
    ("C", "C_11node_no_rag", 11, False, False, False, "off"),
    ("D", "D_11node_lightweight", 11, True, False, False, "lightweight"),
    ("E", "E_11node_dense", 11, True, True, False, "dense"),
    ("F", "F_11node_hybrid", 11, True, True, True, "hybrid"),
]
LEGACY_TERMS = [
    "CASE-" + "DEMO-001", "가명 " + "은하", "김" + "민서", "이" + "수진",
    "마음연결 " + "심리" + "상담센터", "대형 " + "공" + "기업", "공채 " + "취" + "업",
    "24세 " + "대학 " + "4학년", "팀 프로젝트 " + "발" + "표",
]


def jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value):
        return {key: jsonable(item) for key, item in dataclasses.asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


@contextmanager
def condition_settings(rag: bool, dense: bool, hybrid: bool):
    old = (settings.enable_rag, settings.enable_dense_retrieval, settings.enable_hybrid_retrieval, settings.enable_persistence, settings.enable_case_memory)
    original_log = retrieval._log_retrieval
    settings.enable_rag, settings.enable_dense_retrieval, settings.enable_hybrid_retrieval = rag, dense, hybrid
    settings.enable_persistence = settings.enable_case_memory = False
    retrieval._log_retrieval = lambda **_: None
    nodes.retrieve_case_memory_chunks.__globals__["_log_retrieval"] = retrieval._log_retrieval
    try:
        yield
    finally:
        settings.enable_rag, settings.enable_dense_retrieval, settings.enable_hybrid_retrieval, settings.enable_persistence, settings.enable_case_memory = old
        retrieval._log_retrieval = original_log
        nodes.retrieve_case_memory_chunks.__globals__["_log_retrieval"] = original_log


def trace_graph(graph: Any, session_input: SessionInput) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    state: dict[str, Any] = {"session_input": session_input}
    trace: list[dict[str, Any]] = []
    started = time.perf_counter()
    for event in graph.stream(state, stream_mode="updates"):
        for node_name, update in event.items():
            state.update(update or {})
            trace.append({"node": node_name, "output": jsonable(update or {})})
    return state, trace, int((time.perf_counter() - started) * 1000)


def response_from_state(state: dict[str, Any]) -> GenerateNoteResponse:
    return GenerateNoteResponse(
        sanitized_input=state["sanitized_input"], structured_case_data=state["structured_case_data"],
        evidence_mapped_data=state["evidence_mapped_data"], session_summary_draft=state["session_summary_draft"],
        verification_report=state["verification_report"], document_transform_preview=state["document_transform_preview"],
        session_note_draft=state.get("session_note_draft"), termination_report_draft=state.get("termination_report_draft"),
        confirmed_session_note=state.get("confirmed_session_note") or _build_confirmed_session_note(state),
        retrieved_case_context=state.get("retrieved_case_context") or [],
        retrieved_template_context=state.get("retrieved_template_context"),
        retrieved_privacy_context=state.get("retrieved_privacy_context") or [],
        retrieval_report=state.get("retrieval_report") or RetrievalReport(), stub=bool(state.get("stub", False)),
    )


def retrieval_payload(state: dict[str, Any], response: GenerateNoteResponse, rag_mode: str) -> dict[str, Any]:
    case_chunks = state.get("retrieved_case_memory_chunks") or []
    kb_chunks = state.get("retrieved_authoritative_kb_chunks") or []
    template_refs = response.retrieved_template_context.source_refs if response.retrieved_template_context else []
    privacy_refs = [item.source_ref for item in response.retrieved_privacy_context]
    methods = sorted({str(getattr(item, "retrieval_method", "")) for item in [*case_chunks, *kb_chunks] if getattr(item, "retrieval_method", "")})
    if rag_mode == "lightweight" and (template_refs or privacy_refs or response.retrieved_case_context):
        methods.append("supabase_table_lookup")
    return {
        "retrieval_query": state.get("retrieval_query", ""), "rag_mode": rag_mode,
        "methods": sorted(set(methods)), "case_context_count": len(response.retrieved_case_context),
        "case_memory_chunk_count": len(case_chunks), "kb_dense_chunk_count": len(kb_chunks),
        "template_source_refs": template_refs, "privacy_source_refs": privacy_refs,
        "case_memory_chunks": jsonable(case_chunks), "kb_chunks": jsonable(kb_chunks),
        "report": response.retrieval_report.model_dump(mode="json"),
    }


def summary_text(response: GenerateNoteResponse) -> str:
    summary = response.session_summary_draft
    pairs = [("회기 주제", summary.session_theme), ("주호소 / 핵심 문제", summary.presenting_problem), ("상담 내용", summary.session_content), ("상담자 개입", summary.counselor_intervention), ("내담자 반응", summary.client_response), ("상담자 성찰", summary.reflection), ("다음 회기 계획", summary.next_plan)]
    return "\n\n".join(f"[{title}]\n{section.text}" for title, section in pairs) + "\n"


def document_text(title: str, draft: Any) -> str:
    return title + "\n\n" + "\n\n".join(f"[{key}]\n{value}" for key, value in draft.sections.items()) + f"\n\n[검토 안내]\n{draft.notice}\n"


def supervision_text(report: Any) -> str:
    lines = [report.title, f"사례 ID: {report.caseId}", ""]
    for section in report.sections:
        lines.append(section.title)
        for block in section.contentBlocks:
            if block.text:
                lines.append(block.text)
            for row in block.rows or []:
                lines.append(" | ".join(f"{key}: {value}" for key, value in row.items()))
            for turn in block.speakerTurns or []:
                lines.append(f"{'내담자' if turn.speaker == 'client' else '상담자'}: {turn.text}")
        lines.append("")
    lines += ["[상담사 검토 안내]", report.aiReview.caution]
    return "\n".join(lines) + "\n"


def quality_check(response: GenerateNoteResponse, report: Any, retrieval_data: dict[str, Any], rag: bool, texts: list[str]) -> dict[str, Any]:
    full_text = "\n".join(texts)
    legacy = [term for term in LEGACY_TERMS if term in full_text]
    catalog = nodes._source_catalog(response.sanitized_input, response.retrieved_case_context)
    for ref in retrieval_data["template_source_refs"] + retrieval_data["privacy_source_refs"]:
        catalog.setdefault(ref, "retrieved KB context")
    for chunk in [*retrieval_data["case_memory_chunks"], *retrieval_data["kb_chunks"]]:
        if chunk.get("source_ref"):
            catalog[chunk["source_ref"]] = chunk.get("chunk_text", "")
    refs = [ref for item in response.evidence_mapped_data.items for ref in item.source_refs]
    for section in (response.session_summary_draft.session_theme, response.session_summary_draft.presenting_problem, response.session_summary_draft.session_content, response.session_summary_draft.counselor_intervention, response.session_summary_draft.client_response, response.session_summary_draft.reflection, response.session_summary_draft.next_plan):
        refs.extend(section.source_refs)
    orphan = sorted({ref for ref in refs if ref not in catalog})
    unsupported_direct = [item.content for item in response.evidence_mapped_data.items if item.evidence_type == "direct" and not item.source_refs]
    source_mismatch = [item.content for item in response.evidence_mapped_data.items if item.source_refs and not any(nodes._text_similarity(item.content, catalog.get(ref, "")) >= 0.02 for ref in item.source_refs)]
    verification_consistency = all(section.requires_review for section in (response.session_summary_draft.reflection,) if section.evidence_type != "direct")
    retrieval_success = bool(retrieval_data["case_context_count"] or retrieval_data["case_memory_chunk_count"] or retrieval_data["kb_dense_chunk_count"] or retrieval_data["template_source_refs"] or retrieval_data["privacy_source_refs"])
    empty_sections = [key for draft in (response.session_note_draft, response.termination_report_draft) if draft for key, value in draft.sections.items() if not str(value).strip()]
    checks = {
        "legacy_contamination_terms": legacy, "orphan_source_refs": orphan,
        "unsupported_direct_claims": unsupported_direct, "source_type_mismatches": source_mismatch,
        "verification_consistency_pass": verification_consistency,
        "unsupported_claim_count": len(response.verification_report.unsupported_or_risky_claims) + len(report.aiReview.unsupportedClaims),
        "stub": response.stub, "retrieval_required": rag, "retrieval_success": retrieval_success,
        "empty_document_sections": empty_sections,
        "invented_termination_claim": "종결 확정" in (response.termination_report_draft.sections.get("종결 시 상태", "") if response.termination_report_draft else ""),
        "internal_debug_exposed": any(token in full_text for token in ('{"', "source_refs", "retrieval_method", "graph_nodes")),
    }
    checks["pass"] = not any((legacy, orphan, unsupported_direct, source_mismatch, empty_sections)) and verification_consistency and checks["unsupported_claim_count"] == 0 and not response.stub and (retrieval_success or not rag) and not checks["invented_termination_claim"] and not checks["internal_debug_exposed"]
    return checks


def main() -> int:
    OUTPUT.mkdir(exist_ok=True)
    blind = OUTPUT / "blind_review"
    blind.mkdir(exist_ok=True)
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    payload["persist"] = False
    if payload.get("case_id") != "CASE-MUSPSY-1416":
        raise RuntimeError("Canonical MusPsy input required")
    input_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    graph7 = _seven_node_graph()
    results: list[dict[str, Any]] = []
    for label, folder_name, count, rag, dense, hybrid, rag_mode in CONDITIONS:
        folder = OUTPUT / folder_name
        folder.mkdir(exist_ok=True)
        for old in folder.iterdir():
            if old.is_file(): old.unlink()
        candidate = blind / f"candidate_{label}"
        candidate.mkdir(exist_ok=True)
        for old in candidate.iterdir():
            if old.is_file(): old.unlink()
        graph = graph7 if count == 7 else note_graph
        session_input = SessionInput(**{**payload, "target_document_type": "session_note", "persist": False})
        error = None
        started = time.perf_counter()
        try:
            with condition_settings(rag, dense, hybrid):
                state, trace, latency = trace_graph(graph, session_input)
            response = response_from_state(state)
            if response.stub:
                raise RuntimeError("stub=true rejected by evaluation")
            report = run_supervision_report_pipeline(SupervisionReportRequest(session_input=session_input, session_summary_draft=response.session_summary_draft, demo_mode=False))
            retrieval_data = retrieval_payload(state, response, rag_mode)
            texts = [summary_text(response), document_text("상담일지 초안", response.session_note_draft), supervision_text(report), document_text("종결보고서 초안", response.termination_report_draft)]
            quality = quality_check(response, report, retrieval_data, rag, texts)
            (folder / "trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            (folder / "retrieval.json").write_text(json.dumps(retrieval_data, ensure_ascii=False, indent=2), encoding="utf-8")
            (folder / "raw_generate_response.json").write_text(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
            for name, data, text in (
                ("01_session_summary", response.session_summary_draft, texts[0]),
                ("02_session_note", response.session_note_draft, texts[1]),
                ("03_supervision_report", report, texts[2]),
                ("04_termination_report", response.termination_report_draft, texts[3]),
            ):
                (folder / f"{name}.json").write_text(json.dumps(jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")
                (folder / f"{name}.txt").write_text(text, encoding="utf-8")
            (folder / "quality_check.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
            if quality["pass"]:
                for index, text in enumerate(texts, 1):
                    (candidate / f"{index:02d}.txt").write_text(text, encoding="utf-8")
            status = "PASS" if quality["pass"] else "QUALITY_GATE_FAIL"
        except Exception as exc:
            latency = int((time.perf_counter() - started) * 1000)
            response = report = None
            retrieval_data = {"case_context_count": 0, "case_memory_chunk_count": 0, "kb_dense_chunk_count": 0, "methods": []}
            quality = {"pass": False, "stub": None, "retrieval_success": False}
            status = "FAILED_GENERATION"
            error = {"exception_type": type(exc).__name__, "exception_message": str(exc), "http_status": getattr(exc, "status_code", None), "openai_error": getattr(exc, "body", None)}
        metadata = {
            "condition": label, "status": status, "graph_version": f"{count}-node",
            "graph_nodes": GRAPH_7_NODES if count == 7 else GRAPH_11_NODES,
            "rag_mode": rag_mode, "model": settings.openai_model, "temperature": 0.3,
            "stub": response.stub if response else None, "input_sha256": input_hash,
            "case_id": payload["case_id"], "persist": False, "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "timestamp": datetime.now(timezone.utc).isoformat(), "generation_latency_ms": latency,
            "retrieval_success": quality.get("retrieval_success", False),
            "case_context_count": retrieval_data.get("case_context_count", 0),
            "kb_context_count": retrieval_data.get("kb_dense_chunk_count", 0) + len(retrieval_data.get("template_source_refs", [])) + len(retrieval_data.get("privacy_source_refs", [])),
            "retrieval_methods": retrieval_data.get("methods", []),
            "document_success": {"session_summary": response is not None, "session_note": bool(response and response.session_note_draft), "supervision": report is not None, "termination": bool(response and response.termination_report_draft)},
            "quality_gate_pass": quality.get("pass", False),
            "verification_consistency_pass": quality.get("verification_consistency_pass", False),
            **(error or {}),
        }
        (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(metadata)
    write_summary(results)
    return 0


def write_summary(results: list[dict[str, Any]]) -> None:
    headers = ["Condition", "Graph", "RAG mode", "Status", "Model", "Stub", "Retrieval success", "Case context", "KB context", "Session summary", "Session note", "Supervision", "Termination", "Quality gate", "Verification consistency", "Latency", "Error"]
    lines = ["# Evaluation v3 Run Summary", "", "| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for item in results:
        docs = item["document_success"]
        values = [item["condition"], item["graph_version"], item["rag_mode"], item["status"], item["model"], item["stub"], item["retrieval_success"], item["case_context_count"], item["kb_context_count"], docs["session_summary"], docs["session_note"], docs["supervision"], docs["termination"], item["quality_gate_pass"], item["verification_consistency_pass"], f"{item['generation_latency_ms']} ms", item.get("exception_message", "")]
        lines.append("| " + " | ".join(str(value).replace("|", "/") for value in values) + " |")
    (OUTPUT / "RUN_SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
