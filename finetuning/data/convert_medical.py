"""Converters for medical dialogue→document datasets (MTS-Dialog, ACI-Bench).

이 두 데이터셋은 "대화 → 구조화 임상 문서" 형식이 Re:mind 태스크와 같아
형식 학습 후보입니다. 단, 문서 스키마가 상담일지(SessionSummaryDraft)와 다르므로
**아직 SFT 믹스에 넣지 않습니다**: 원본 문서는 `meta.native_note`에 보존하고
`note`는 null로 둡니다. Re:mind 스키마로의 매핑을 확정한 뒤에만 note를 채워
build_sft_dataset의 소스로 추가하세요. 라이선스/출처는 DATASETS.md 참고.

사전 준비 (data/raw 에 클론):
  git clone --depth 1 https://github.com/abachaa/MTS-Dialog data/raw/MTS-Dialog
  git clone --depth 1 https://github.com/wyim/aci-bench data/raw/aci-bench

Usage:
  python data/convert_medical.py --source all
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path

RAW = Path(__file__).parent / "raw"
OUT = Path(__file__).parent / "processed"

SPEAKER_LINE_RE = re.compile(r"^(?:\[(?P<bracket>[a-z_0-9 ]+)\]|(?P<plain>[A-Za-z_][A-Za-z_0-9 ]*):)\s*", re.I)
COUNSELOR_ROLES = {"doctor", "doctor_2", "clinician"}


def parse_dialogue(text: str) -> list[dict]:
    """Parse 'Doctor: ...' or '[doctor] ...' style scripts into speaker turns."""
    turns: list[dict] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = SPEAKER_LINE_RE.match(stripped)
        if match:
            role = (match.group("bracket") or match.group("plain") or "").strip().lower()
            speaker = "counselor" if role in COUNSELOR_ROLES else "client"
            turns.append({"speaker": speaker, "text": stripped[match.end():].strip(), "label": role})
        elif turns:
            turns[-1]["text"] += " " + stripped
    return [t for t in turns if t["text"]]


def convert_mts_dialog() -> list[dict]:
    files = {
        "train": "MTS-Dialog-TrainingSet.csv",
        "val": "MTS-Dialog-ValidationSet.csv",
        "test1": "MTS-Dialog-TestSet-1-MEDIQA-Chat-2023.csv",
        "test2": "MTS-Dialog-TestSet-2-MEDIQA-Sum-2023.csv",
    }
    records = []
    for subset, filename in files.items():
        path = RAW / "MTS-Dialog" / "Main-Dataset" / filename
        if not path.exists():
            print(f"  skip (not found): {path}")
            continue
        for row in csv.DictReader(path.open(encoding="utf-8")):
            dialogue = parse_dialogue(row["dialogue"])
            if len(dialogue) < 2:
                continue
            record_id = f"mts-{subset}-{row['ID']}"
            records.append(
                {
                    "id": record_id,
                    "case_id": record_id,  # 각 row가 독립 스니펫 — 회기 연속성 없음
                    "source": "mts_dialog",
                    "language": "en",
                    "license": "CC-BY-4.0",
                    "dialogue": dialogue,
                    "meta": {
                        "subset": subset,
                        "native_note": {
                            "section_header": row["section_header"],
                            "section_text": row["section_text"],
                        },
                    },
                    "note": None,  # Re:mind 스키마 매핑 확정 전까지 SFT 미사용
                }
            )
    return records


def convert_aci_bench() -> list[dict]:
    data_dir = RAW / "aci-bench" / "data" / "challenge_data"
    records = []
    for path in sorted(data_dir.glob("*.csv")):
        if path.name.endswith("_metadata.csv"):
            continue
        subset = path.stem
        for row in csv.DictReader(path.open(encoding="utf-8")):
            dialogue = parse_dialogue(row["dialogue"])
            if len(dialogue) < 4:
                continue
            records.append(
                {
                    "id": f"aci-{subset}-{row['encounter_id']}",
                    "case_id": f"aci-{row['encounter_id']}",
                    "source": "aci_bench",
                    "language": "en",
                    "license": "CC-BY-4.0",
                    "dialogue": dialogue,
                    "meta": {"subset": subset, "dataset": row.get("dataset", ""), "native_note": row["note"]},
                    "note": None,  # Re:mind 스키마 매핑 확정 전까지 SFT 미사용
                }
            )
    return records


CONVERTERS = {"mts_dialog": convert_mts_dialog, "aci_bench": convert_aci_bench}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="all", choices=["all", *CONVERTERS])
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    for source in list(CONVERTERS) if args.source == "all" else [args.source]:
        records = CONVERTERS[source]()
        ids = [r["id"] for r in records]
        if len(set(ids)) != len(ids):
            raise SystemExit(f"FATAL: duplicate ids in {source}")
        path = OUT / f"intermediate_{source}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        with_native = sum(1 for r in records if r["meta"].get("native_note"))
        print(f"{source}: {len(records)} records (native notes {with_native}, duplicate ids 0) -> {path}")


if __name__ == "__main__":
    main()
