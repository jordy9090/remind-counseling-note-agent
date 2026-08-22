"""Export the canonical MusPsy demo input and a locally generated response."""
from __future__ import annotations

import json
from pathlib import Path

from app.graph.graph import run_note_pipeline
from app.schemas.note import SessionInput

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_INPUT = ROOT / "sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json"


def main() -> None:
    payload = json.loads(CANONICAL_INPUT.read_text(encoding="utf-8"))
    payload["persist"] = False
    result = run_note_pipeline(SessionInput(**payload))
    if result.stub:
        raise RuntimeError("Canonical demo export rejects stub output")
    output = ROOT / "sample_data/muspsy_demo/session_output_005_muspsy_1416_ko.json"
    output.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
