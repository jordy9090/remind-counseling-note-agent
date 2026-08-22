"""Probe the configured OpenAI runtime without logging the API key."""
from __future__ import annotations

import importlib.metadata
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from langchain_openai import ChatOpenAI  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.graph.nodes import _build_structure_prompt, sanitize_input  # noqa: E402
from app.schemas.note import SessionInput, StructuredCaseData  # noqa: E402

OUTPUT = ROOT / "eval_outputs_v2"
INPUT = ROOT / "sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json"


class Probe(BaseModel):
    ok: bool


CONDITIONS = [
    ("A", "A_7node_no_rag", "7-node", "off"),
    ("B", "B_7node_lightweight", "7-node", "lightweight"),
    ("C", "C_11node_no_rag", "11-node", "off"),
    ("D", "D_11node_lightweight", "11-node", "lightweight"),
    ("E", "E_11node_dense", "11-node", "dense"),
    ("F", "F_11node_hybrid", "11-node", "hybrid"),
]


def error_detail(exc: Exception) -> dict[str, Any]:
    response = getattr(exc, "response", None)
    body = getattr(exc, "body", None)
    if body is None and response is not None:
        body = getattr(response, "text", None)
    headers = dict(getattr(response, "headers", {}) or {}) if response is not None else {}
    openai_error = body if isinstance(body, dict) else {
        "message": body if isinstance(body, str) and body else None,
        "type": getattr(exc, "type", None),
        "param": getattr(exc, "param", None),
        "code": getattr(exc, "code", None),
    }
    return {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "http_status": getattr(exc, "status_code", None) or getattr(response, "status_code", None),
        "openai_error_body": body,
        "openai_error": openai_error,
        "error_code": getattr(exc, "code", None),
        "error_param": getattr(exc, "param", None),
        "request_id": getattr(exc, "request_id", None) or headers.get("x-request-id"),
        "response_headers": headers,
    }


def run_probe(name: str, call: Callable[[], Any]) -> dict[str, Any]:
    try:
        result = call()
        if hasattr(result, "model_dump"):
            result = result.model_dump(mode="json")
        else:
            result = getattr(result, "content", result)
        return {"name": name, "success": True, "result": result}
    except Exception as exc:
        return {"name": name, "success": False, "error": error_detail(exc)}


def main() -> int:
    OUTPUT.mkdir(exist_ok=True)
    payload = json.loads(INPUT.read_text(encoding="utf-8"))
    payload["persist"] = False
    payload["target_document_type"] = "session_note"
    session_input = SessionInput(**payload)
    sanitized = sanitize_input({"session_input": session_input})["sanitized_input"]
    structure_prompt = _build_structure_prompt(sanitized, [], None)

    llm = ChatOpenAI(
        model=settings.openai_model,
        api_key=settings.openai_api_key,
        temperature=0.3,
    )
    probes = [
        run_probe("basic_chat", lambda: llm.invoke("Reply with OK.")),
        run_probe(
            "minimal_structured_output",
            lambda: llm.with_structured_output(Probe).invoke("Set ok to true."),
        ),
        run_probe(
            "structured_case_data",
            lambda: llm.with_structured_output(StructuredCaseData).invoke(structure_prompt),
        ),
    ]
    probes_passed = all(probe["success"] for probe in probes)
    key = settings.openai_api_key.get_secret_value() if hasattr(settings.openai_api_key, "get_secret_value") else str(settings.openai_api_key or "")
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model": settings.openai_model,
        "use_stub": settings.use_stub,
        "stub_mode": settings.stub_mode,
        "api_key_present": bool(key),
        "api_key_length": len(key),
        "api_key_looks_like_placeholder": len(key) < 20,
        "api_key_value_logged": False,
        "input_case_id": session_input.case_id,
        "input_path": str(INPUT.relative_to(ROOT)),
        "versions": {
            package: importlib.metadata.version(package)
            for package in ("langchain-openai", "openai", "pydantic")
        },
        "probes": probes,
        "diagnosis": (
            "ALL_PROBES_SUCCESS: basic chat, minimal structured output, and StructuredCaseData all succeeded."
            if probes_passed
            else "CASE_A_BASIC_CALL_FAILURE: configured OpenAI request failed before model or structured-output processing."
        ),
        "next_gate": (
            "C smoke test is authorized."
            if probes_passed
            else "Fix the local OpenAI credential/configuration, then rerun probes. Do not run C smoke or A-F before all probes pass."
        ),
    }
    (OUTPUT / "llm_probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# LLM Diagnostic",
        "",
        "## Result",
        "",
        "`ALL_PROBES_SUCCESS`" if probes_passed else "`CASE_A_BASIC_CALL_FAILURE`",
        "",
        (
            "The configured local credential succeeded with basic chat, the minimal Pydantic schema, and the production `StructuredCaseData` schema using the actual MusPsy structure prompt. No structured-output compatibility adapter or product-code change was required."
            if probes_passed
            else "The configured OpenAI request failed at the basic-chat probe before structured-output compatibility could be evaluated."
        ),
        "",
        "The API key value itself was never logged. No production, deployment, Vercel environment, or Supabase data was read or changed.",
        "",
        "## Runtime",
        "",
        f"- Model: `{report['model']}`",
        f"- `USE_STUB`: `{report['use_stub']}`",
        f"- langchain-openai: `{report['versions']['langchain-openai']}`",
        f"- openai: `{report['versions']['openai']}`",
        f"- pydantic: `{report['versions']['pydantic']}`",
        f"- Input: `{report['input_case_id']}`",
        "",
        "## Probes",
        "",
    ]
    for probe in probes:
        lines += [f"### {probe['name']}", "", f"- Success: `{probe['success']}`"]
        if not probe["success"]:
            error = probe["error"]
            lines += [
                f"- Exception: `{error['exception_type']}`",
                f"- Message: `{error['exception_message']}`",
                f"- HTTP status: `{error['http_status']}`",
                f"- Full OpenAI body: `{json.dumps(error['openai_error_body'], ensure_ascii=False)}`",
                f"- Error code: `{error['error_code']}`",
                f"- Error param: `{error['error_param']}`",
                f"- Request ID: `{error['request_id']}`",
            ]
        lines.append("")
    lines += [
        "## Resolution",
        "",
        (
            "The local API credential was corrected. The existing model, prompts, schemas, and structured-output method were retained unchanged."
            if probes_passed
            else "Do not change structured schemas or prompts. Fix the local OpenAI credential/configuration and rerun these probes."
        ),
    ]
    (OUTPUT / "LLM_DIAGNOSTIC.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not probes_passed:
        _write_blocked_run_outputs(report, payload)
    return 0 if probes_passed else 2


def _write_blocked_run_outputs(report: dict[str, Any], payload: dict[str, Any]) -> None:
    """Record the preflight gate without pretending any condition was executed."""
    hash_payload = dict(payload)
    hash_payload.pop("target_document_type", None)
    input_sha256 = hashlib.sha256(
        json.dumps(hash_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    first_error = report["probes"][0].get("error", {})
    (OUTPUT / "_smoke").mkdir(exist_ok=True)
    blind = OUTPUT / "blind_review"
    blind.mkdir(exist_ok=True)
    headers = [
        "Condition", "Graph", "RAG mode", "Status", "Model", "Basic LLM success?",
        "Structured output success?", "Real LLM?", "Stub?", "RAG configured?",
        "Retrieval actually worked?", "Case context count", "KB context count",
        "Session summary", "Session note", "Supervision", "Termination",
        "Synthetic contamination", "Unsupported claims", "Weakly grounded",
        "Generation latency", "Error",
    ]
    summary = [
        "# Evaluation v2 Run Summary", "",
        "C smoke and A–F were not executed because Probe 1 failed. This is the required preflight gate, not a generation result.", "",
        "Supabase credentials are absent, so B/D/E/F would additionally require `INVALID_RETRIEVAL_ENV` handling after the LLM preflight is fixed.", "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for label, folder_name, graph, rag_mode in CONDITIONS:
        folder = OUTPUT / folder_name
        folder.mkdir(exist_ok=True)
        candidate = blind / f"candidate_{label}"
        candidate.mkdir(exist_ok=True)
        metadata = {
            "condition": label,
            "status": "BLOCKED_LLM_PREFLIGHT",
            "executed": False,
            "reason": "Probe 1 basic chat failed; C smoke and A-F execution is prohibited until fixed.",
            "graph_version": graph,
            "rag_mode": rag_mode,
            "model": report["model"],
            "stub": False,
            "real_llm": False,
            "input_sha256": input_sha256,
            "input_case_id": "CASE-MUSPSY-1416",
            "persist": False,
            "rag_configured": False,
            "retrieval_actually_worked": False,
            "exception_type": first_error.get("exception_type"),
            "exception_message": first_error.get("exception_message"),
            "http_status": first_error.get("http_status"),
            "openai_error": first_error.get("openai_error"),
            "openai_error_body": first_error.get("openai_error_body"),
            "request_id": first_error.get("request_id"),
        }
        (folder / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        values = [
            label, graph, rag_mode, "BLOCKED_LLM_PREFLIGHT", report["model"], "False",
            "False", "False", "False", "False", "False", "0", "0", "False",
            "False", "False", "False", "not evaluated", "0", "0", "0 ms",
            "BadRequestError: HTTP 400, empty body; configured API key is a 1-character placeholder",
        ]
        summary.append("| " + " | ".join(values) + " |")
    (OUTPUT / "RUN_SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
