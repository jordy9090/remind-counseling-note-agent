"""Export the five bundled synthetic v2 cases; model mode is explicit and opt-in."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import settings
from app.graph.nodes import _mock_structured_case, _mock_summary, verify_output
from app.schemas.note import EvidenceMappedData, SanitizedInput, StructuredCaseData
from app.services.summary_skill import run_summary_skill


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stub", "model"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if settings.summary_schema_version != "v2":
        parser.error("Set SUMMARY_SCHEMA_VERSION=v2.")
    if (args.mode == "stub") != settings.stub_mode:
        parser.error("Stub mode requires USE_STUB=1; model mode requires USE_STUB=0 and a configured API key.")
    cases = sorted((Path(__file__).parent / "evaluation_cases" / "summary_v2").glob("*.input.json"))
    if len(cases) != 5:
        parser.error("Expected exactly five bundled synthetic cases.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path in cases:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        if fixture.get("synthetic") is not True:
            parser.error("Only explicitly synthetic bundled cases may be evaluated.")
        sanitized = SanitizedInput.model_validate(fixture["input"])
        if args.mode == "stub":
            summary = _mock_summary(sanitized, _mock_structured_case(sanitized))
        else:
            summary = run_summary_skill(sanitized).summary
        result = verify_output({
            "sanitized_input": sanitized, "session_summary_draft": summary,
            "structured_case_data": StructuredCaseData(), "evidence_mapped_data": EvidenceMappedData(),
        })
        output = args.output_dir / path.name.replace(".input.json", f".{args.mode}.json")
        output.write_text(json.dumps({
            "synthetic": True, "mode": args.mode,
            "session_summary_draft": result["session_summary_draft"].model_dump(mode="json"),
            "verification_report": result["verification_report"].model_dump(mode="json"),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {output.name}")


if __name__ == "__main__":
    main()
