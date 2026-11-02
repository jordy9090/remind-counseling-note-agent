"""Explicit non-stub evaluation of B's plan and sparse temporal-boundary cases.

Run only with an existing provider credential. The saved artifact contains fixed
synthetic inputs and actual outputs; stdout contains status metadata only.
No application route, authentication user or stored database row is created.
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
from app.services.quick_summary import generate_quick_summary
from app.services.summary_corrections import introduced_script_fields
from app.services.summary_quality import summary_quality_issues, summary_quote_issues
from app.services.summary_verification import cited_lines


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if settings.stub_mode or not settings.openai_api_key:
        raise SystemExit("Live provider configuration is required; no stub substitution.")
    fixture = Path(__file__).parent / "fixtures/session_summary/interview_case_b.txt"
    cases = {
        "B_full": fixture.read_text(encoding="utf-8").strip(),
        "C_in_session": "상담자: 잠깐 일어나서 해볼까요?\n내담자: 서서 하는 건 싫어요.\n상담자: 네. 앉아 있을게요.",
        "D_conditional": "내담자: 내일 수영 끝나고 다시 읽어볼게요.\n그때도 못 보내겠으면 안 보낼 수도 있어요.",
    }
    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "model": settings.openai_model,
              "mode": "Actual production quick-summary pipeline in Preview build; no HTTP wrapper or storage.",
              "cases": [], "cleanup": "Synthetic fixtures only; no accounts or stored rows."}
    factory = nodes.get_structured_llm
    for name, raw in cases.items():
        assessments = []

        def observe(schema, **kwargs):
            actual = factory(schema, **kwargs)

            class Observer:
                def invoke(self, prompt):
                    result = actual.invoke(prompt)
                    assessments.append(result.model_dump(mode="json"))
                    return result

            return Observer()

        started = time.perf_counter()
        item = {"case": name, "input_characters": len(raw),
                "input_sha256": hashlib.sha256(raw.encode()).hexdigest(), "assessments": assessments}
        try:
            with patch.object(nodes, "get_structured_llm", side_effect=observe):
                response = generate_quick_summary(raw)
            item["response"] = response.model_dump(mode="json")
            assert not response.stub
            summary = response.session_summary_draft
            catalog = nodes._source_catalog(response.sanitized_input, [])
            assert not summary_quality_issues(summary)
            assert not summary_quote_issues(summary, catalog)
            assert not introduced_script_fields(summary, catalog)
            plan = summary.next_plan
            if name == "C_in_session":
                assert plan.text == "[자료에서 확인되지 않음]" and not plan.source_refs
            else:
                assert plan.text and not plan.text.startswith("[")
                assessment = assessments[-1]["next_plan_assessment"]
                assert assessment["status"] == "supported_future"
                expected = list(dict.fromkeys(e["source_ref"] for e in assessment["evidence"]))
                assert expected and plan.source_refs == expected
                for evidence in assessment["evidence"]:
                    quote = " ".join(evidence["quote"].split())
                    assert quote and any(quote in line for line in cited_lines([evidence["source_ref"]], catalog))
                item["plan_review_reasons"] = [x.reason for x in response.verification_report.requires_counselor_review
                                               if x.field == "next_plan"]
            termination = response.termination_report_draft
            assert all(text == "[상담사 직접 작성 필요]" for text in termination.sections.values())
            assert all(not refs for refs in termination.source_refs.values())
            item["passed"] = True
        except Exception as error:
            item.update(passed=False, failure_type=type(error).__name__)
        item["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        report["cases"].append(item)
    report["passed"] = all(item["passed"] for item in report["cases"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "cases": [
        {k: item[k] for k in ("case", "passed", "elapsed_seconds")} for item in report["cases"]]}))


if __name__ == "__main__":
    run()
