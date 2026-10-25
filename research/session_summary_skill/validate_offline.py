"""Validate the summary Skill without network, credentials or .env loading.

Comparison replays a captured synthetic response through both code paths. It
measures request text/schema size, never generation quality or billed tokens.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]


def isolate() -> None:
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
    for key in list(os.environ):
        if key.startswith(("OPENAI", "SUPABASE", "ENABLE_", "SAVE_", "REMIND_", "ALLOW_EXTERNAL_")):
            os.environ.pop(key, None)
    os.environ["USE_STUB"] = "1"
    os.environ["RUNTIME_ENVIRONMENT"] = "test"
    from pydantic_settings import BaseSettings
    original = BaseSettings.__init__

    def no_env(self, **kwargs):
        return original(self, **{**kwargs, "_env_file": None})

    BaseSettings.__init__ = no_env

    def deny_network(*args, **kwargs):
        raise RuntimeError("Networking is disabled for offline Skill validation")

    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    socket.create_connection = deny_network
    socket.getaddrinfo = deny_network


def run_tests(output: Path) -> dict:
    modules = ["test_summary_skill", "test_summary_quality", "test_source_refs", "test_llm_model_settings"]
    suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
    with (output / "tests.txt").open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return {
        "modules": modules, "tests_run": result.testsRun,
        "failures": len(result.failures), "errors": len(result.errors),
        "result": "PASS" if result.wasSuccessful() else "FAIL",
    }


def compare(response_path: Path) -> dict:
    from app.core.config import settings
    from app.graph import nodes
    from app.schemas.note import SanitizedInput, SessionSummaryDraft, StructuredCaseData
    from app.services import summary_skill

    response = json.loads(response_path.read_text(encoding="utf-8"))
    sanitized = SanitizedInput.model_validate(response["sanitized_input"])
    structured = StructuredCaseData.model_validate(response["structured_case_data"])
    summary = SessionSummaryDraft.model_validate(response["session_summary_draft"])
    captured_calls = []

    def replay(schema, **kwargs):
        def invoke(prompt):
            captured_calls.append((schema, prompt))
            return (structured if schema is StructuredCaseData else summary).model_copy(deep=True)
        return Mock(invoke=invoke)

    # Execute the existing core, including any actual quality-repair branch. Mock
    # only its provider transport; do not rewrite baseline prompts for comparison.
    state = {"sanitized_input": sanitized}
    with patch.multiple(settings, use_stub=False, openai_api_key="synthetic-offline-placeholder"), patch(
        "app.graph.nodes.get_structured_llm", side_effect=replay,
    ):
        state.update(nodes.structure_session(state))
        state.update(nodes.map_evidence(state))
        state.update(nodes.generate_summary(state))
    fields = summary_skill.SummarySkillFields.model_validate(
        summary.model_dump(exclude={"session_info"}),
    )
    transport = Mock()
    transport.with_structured_output.return_value.invoke.return_value = {
        "parsed": fields, "raw": None, "parsing_error": None,
    }
    with patch.multiple(settings, use_stub=False, openai_api_key="synthetic-offline-placeholder"), patch(
        "app.services.summary_skill.get_llm", return_value=transport,
    ):
        candidate = summary_skill.run_summary_skill(sanitized)
    messages = transport.with_structured_output.return_value.invoke.call_args.args[0]
    candidate_text = "\n".join(message.content for message in messages)

    encoding = None
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("o200k_base")
        token_status = "local o200k_base text estimates; not provider usage"
    except Exception:
        token_status = "BLOCKED: tokenizer or cached vocabulary unavailable; no download allowed"

    def measure(schema, text):
        schema_text = json.dumps(schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"))
        return {
            "prompt_characters": len(text), "schema_characters": len(schema_text),
            "prompt_tokens_estimate": len(encoding.encode(text, disallowed_special=())) if encoding else None,
            "schema_tokens_estimate": len(encoding.encode(schema_text, disallowed_special=())) if encoding else None,
        }

    baseline_stages = [measure(schema, prompt) for schema, prompt in captured_calls]
    candidate_size = measure(summary_skill.SummarySkillFields, candidate_text)
    baseline_total = sum(item["prompt_tokens_estimate"] + item["schema_tokens_estimate"] for item in baseline_stages) if encoding else None
    candidate_total = candidate_size["prompt_tokens_estimate"] + candidate_size["schema_tokens_estimate"] if encoding else None
    return {
        "comparison_scope": "extraction+summary core only; identical captured sanitized input",
        "execution": "replayed synthetic outputs; no new model output or quality measurement",
        "response_sha256": hashlib.sha256(response_path.read_bytes()).hexdigest(),
        "skill_sha256": candidate.skill_sha256,
        "input_characters": len(sanitized.sources.transcript_text),
        "baseline_core": {"replayed_calls": len(captured_calls), "stages": baseline_stages},
        "skill_core": {"replayed_calls": candidate.model_calls, **candidate_size},
        "tokenizer": token_status,
        "input_plus_schema_tokens_estimate": {"baseline": baseline_total, "skill": candidate_total},
        "estimated_input_reduction_percent": round((1 - candidate_total / baseline_total) * 100, 1) if baseline_total else None,
        "output_token_usage": None, "actual_cost": None, "quality_comparison": "NOT RUN",
        "excluded_from_both_arms": [
            "upstream entity-detection/de-identification", "semantic verifier",
            "relational insight", "grounded document", "authentication", "persistence",
        ],
        "limits": "Schema serialization and message framing may differ on the wire. Excludes output/reasoning/cached tokens, upstream calls and any quality difference.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("tests", "compare"), required=True)
    parser.add_argument("--baseline-response", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "compare" and args.baseline_response is None:
        parser.error("--baseline-response is required for compare mode")
    isolate()
    args.output.mkdir(parents=True, exist_ok=True)
    report = run_tests(args.output) if args.mode == "tests" else compare(args.baseline_response)
    report.update(timestamp=datetime.now(timezone.utc).isoformat(), network="disabled", new_model_calls=0)
    destination = args.output / ("tests.json" if args.mode == "tests" else "comparison.json")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return int(report.get("result") == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
