"""Explicit opt-in live evaluation of historical synthetic model failures.

Run with an existing provider credential in the execution environment. Never
print credentials, prompts or counseling text. The output file contains only
the checked-in synthetic cases and their actual structured model responses.
This script is not an application route and never reads or writes user storage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.graph import nodes
from app.schemas.note import EvidenceMappedData, SanitizedInput, SessionSummaryDraft, StructuredCaseData
from app.services.summary_corrections import introduced_script_fields
from app.services.summary_quality import summary_quote_issues
from app.services.quick_summary import generate_quick_summary


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if settings.stub_mode or not settings.openai_api_key:
        raise SystemExit("Live provider configuration is required; no stub substitution.")
    fixtures = Path(__file__).parent / "fixtures/session_summary/correction_failures.json"
    examples = json.loads(fixtures.read_text(encoding="utf-8"))
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "model": settings.openai_model,
              "fixture_sha256": hashlib.sha256(fixtures.read_bytes()).hexdigest(), "cases": [],
              "cleanup": "Fixed synthetic fixtures only; no accounts or database rows created."}
    factory = nodes.get_structured_llm
    for example in examples:
        assessments = []

        def observed_model(schema, **kwargs):
            actual = factory(schema, **kwargs)

            class Observer:
                def invoke(self, prompt):
                    result = actual.invoke(prompt)
                    assessments.append(result.model_dump(mode="json"))
                    return result

            return Observer()

        state = {"sanitized_input": SanitizedInput.model_validate(example["sanitized_input"]),
                 "session_summary_draft": SessionSummaryDraft.model_validate(example["summary"]),
                 "structured_case_data": StructuredCaseData(), "evidence_mapped_data": EvidenceMappedData()}
        before = state["session_summary_draft"].model_dump(mode="json")
        started = time.perf_counter()
        item = {"case": example["case"], "before": before, "assessments": assessments}
        try:
            with patch.object(nodes, "get_structured_llm", side_effect=observed_model):
                result = nodes.verify_output(state)
            after = result["session_summary_draft"]
            catalog = nodes._source_catalog(state["sanitized_input"], [])
            assert 1 <= len(assessments) <= 2
            if len(assessments) == 2:
                assert assessments[-1]["correction_validated"]
            assert not introduced_script_fields(after, catalog)
            assert not summary_quote_issues(after, catalog)
            if example["case"] == "full_b_typo":
                assert len(assessments) == 2
                assert "अलग개로" in before["session_content"]["text"]
                assert "अलग" not in after.session_content.text
                assert after.session_content.text != before["session_content"]["text"]
                assert after.next_plan.text == before["next_plan"]["text"]
                assert any(set(section["source_refs"]) - set(getattr(after, field).source_refs)
                           for field, section in before.items() if field != "session_info")
            else:
                assert "transcript.turn_5" in before["session_theme"]["source_refs"]
                # Turn 5 supplies context, but does not directly establish the timing
                # of fear. It may remain as context or be pruned while the unchanged
                # overstatement stays reviewable. Neither forced pruning nor forced
                # retention is a semantic correctness oracle.
                assert {"transcript.turn_1", "transcript.turn_3"} <= set(after.session_theme.source_refs)
                assert set(after.session_theme.source_refs) <= set(before["session_theme"]["source_refs"])
                if "transcript.turn_5" not in after.session_theme.source_refs:
                    assert after.session_theme.requires_review
                assert after.session_theme.text == before["session_theme"]["text"]
                item["expectation"] = "Preserve quotation and fear evidence; distinguish context from support for unchanged overstatement."
            item.update(passed=True, after=after.model_dump(mode="json"),
                        verification=result["verification_report"].model_dump(mode="json"))
        except Exception as error:
            # Persist a safe failure class, never a provider exception body.
            item.update(passed=False, failure_type=type(error).__name__)
        item["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report["cases"].append(item)
    started = time.perf_counter()
    assessments = []
    try:
        raw = (fixtures.parent / "interview_case_b.txt").read_text(encoding="utf-8").strip()
        with patch.object(nodes, "get_structured_llm", side_effect=observed_model):
            response = generate_quick_summary(raw)
        assert not response.stub
        catalog = nodes._source_catalog(response.sanitized_input, [])
        assert not introduced_script_fields(response.session_summary_draft, catalog)
        assert not summary_quote_issues(response.session_summary_draft, catalog)
        report["fresh_full_b"] = {"passed": True, "response": response.model_dump(mode="json"),
                                  "input_characters": len(raw), "input_sha256": hashlib.sha256(raw.encode()).hexdigest()}
    except Exception as error:
        report["fresh_full_b"] = {"passed": False, "failure_type": type(error).__name__}
    report["fresh_full_b"]["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["fresh_full_b"]["assessments"] = assessments
    report["passed"] = all(item["passed"] for item in report["cases"]) and report["fresh_full_b"]["passed"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": [
        {key: item[key] for key in ("case", "passed", "elapsed_seconds")} for item in report["cases"]],
        "fresh_full_b_passed": report["fresh_full_b"]["passed"]}))


if __name__ == "__main__":
    run()
