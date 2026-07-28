"""Build the final chat-format SFT dataset from converted/synthesized records.

Merges data/processed/synthesized_<source>.jsonl (preferred) and
intermediate_<source>.jsonl, keeps records that have a `note`, renders each as a
chat example mirroring the production Re:mind summary task, and writes:

  data/processed/sft_train.jsonl
  data/processed/sft_val.jsonl
  data/processed/sft_test.jsonl

Split policy: **group split by case_id** — all sessions of the same client/case
land in exactly one split (no case leakage between train/val/test). Row-level
random split is forbidden. Duplicate record ids are a hard error.

Usage:
  python data/build_sft_dataset.py --sources aihub_71806,cactus --max-per-source cactus=1000 --max-chars 28000
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

PROCESSED = Path(__file__).parent / "processed"

SYSTEM_PROMPT = """당신은 심리상담사를 위한 상담 문서화 보조 AI입니다. 상담 회기 자료를 입력받아
편집 가능한 한국어 회기요약 초안을 JSON으로 생성합니다.

규칙:
- 각 섹션은 text, evidence_type, source_refs, requires_review를 포함해야 합니다.
- 입력에 직접 근거가 없는 내용은 확정적으로 쓰지 않고 inferred 또는 needs_review로 표시합니다.
- reflection, 사례개념화, 목표 달성 평가는 상담사 확인 영역으로 남깁니다.
- 진단, 임상적 위험도 점수화, 치료 권고, 심리검사 해석, 상담사 평가를 생성하지 않습니다.
- 출력은 JSON만 포함합니다."""

USER_TEMPLATE = """다음 회기 자료로 회기요약 초안을 생성하세요.

회기 정보:
{session_info}

상담사 메모:
{counselor_memo}

축어록:
{transcript}"""


def dialogue_to_transcript(dialogue: list[dict], language: str) -> str:
    roles = {
        "ko": {"counselor": "상담사", "client": "내담자"},
        "en": {"counselor": "Counselor", "client": "Client"},
        "zh": {"counselor": "咨询师", "client": "来访者"},
    }[language if language in ("ko", "en", "zh") else "en"]
    return "\n".join(f"{roles[t['speaker']]}: {t['text']}" for t in dialogue)


def to_example(record: dict) -> dict:
    meta = record.get("meta", {})
    session_info = {
        "case_id": record.get("case_id", record["id"]),
        "session_number": int(meta.get("session_number") or 1),
        "session_date": "",
        "counselor_name": "",
    }
    user = USER_TEMPLATE.format(
        session_info=json.dumps(session_info, ensure_ascii=False),
        counselor_memo=meta.get("counselor_memo", "") or "(없음)",
        transcript=dialogue_to_transcript(record["dialogue"], record.get("language", record.get("lang", "en"))),
    )
    note = {"session_info": session_info, **record["note"]}
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(note, ensure_ascii=False, indent=2)},
        ],
        "meta": {
            "id": record["id"],
            "case_id": record.get("case_id", record["id"]),
            "source": record["source"],
            "language": record.get("language", record.get("lang", "")),
            "license": record["license"],
            "note_origin": record.get("note_origin", "rule_based"),
        },
    }


def load_source(source: str) -> list[dict]:
    """Prefer synthesized records; fall back to intermediate ones with notes."""
    records: dict[str, dict] = {}
    seen_per_file: dict[str, int] = {}
    for prefix in ("intermediate", "synthesized"):
        path = PROCESSED / f"{prefix}_{source}.jsonl"
        if not path.exists():
            continue
        file_ids: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("note"):
                file_ids.append(record["id"])
                records[record["id"]] = record  # synthesized pass overwrites intermediate
        duplicate_count = len(file_ids) - len(set(file_ids))
        if duplicate_count:
            worst = Counter(file_ids).most_common(5)
            raise SystemExit(
                f"FATAL: {path.name} contains {duplicate_count} duplicate ids "
                f"(records would be silently dropped). Worst: {worst}"
            )
        seen_per_file[path.name] = len(file_ids)
    for name, n in seen_per_file.items():
        print(f"  {name}: {n} records with note")
    return list(records.values())


def group_split(
    examples: list[dict], val_ratio: float, test_ratio: float, seed: int
) -> dict[str, list[dict]]:
    """Split by case_id so that every case's sessions stay in one split."""
    rng = random.Random(seed)
    cases: dict[str, list[dict]] = {}
    for example in examples:
        cases.setdefault(example["meta"]["case_id"], []).append(example)
    case_ids = sorted(cases)
    rng.shuffle(case_ids)

    total = len(examples)
    target_val = total * val_ratio
    target_test = total * test_ratio
    splits: dict[str, list[dict]] = {"train": [], "val": [], "test": []}
    counts = {"val": 0, "test": 0}
    for case_id in case_ids:
        bucket = "train"
        if counts["test"] < target_test:
            bucket = "test"
        elif counts["val"] < target_val:
            bucket = "val"
        splits[bucket].extend(cases[case_id])
        if bucket in counts:
            counts[bucket] += len(cases[case_id])

    # --- validation: case overlap between splits must be zero ---
    case_sets = {name: {e["meta"]["case_id"] for e in items} for name, items in splits.items()}
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        overlap = case_sets[a] & case_sets[b]
        if overlap:
            raise SystemExit(f"FATAL: case overlap between {a} and {b}: {sorted(overlap)[:5]}")
    print(
        "split cases  : "
        + " / ".join(f"{name}={len(case_sets[name])}" for name in ("train", "val", "test"))
        + " (overlap 0 verified)"
    )
    return splits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="aihub_71806,cactus")
    parser.add_argument("--max-per-source", default="", help="e.g. cactus=1000")
    parser.add_argument("--val-ratio", type=float, default=0.10)
    parser.add_argument("--test-ratio", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="전체 메시지 문자 수 상한. 초과 예시는 제외 (truncation은 타깃 JSON을 자르므로 사용하지 않음). "
        "한국어 기준 chars*0.7 ≈ tokens. 0이면 무제한.",
    )
    args = parser.parse_args()

    caps = {}
    for pair in filter(None, args.max_per_source.split(",")):
        key, value = pair.split("=")
        caps[key.strip()] = int(value)

    rng = random.Random(args.seed)
    examples: list[dict] = []
    for source in args.sources.split(","):
        source = source.strip()
        records = load_source(source)
        rng.shuffle(records)
        if source in caps:
            records = records[: caps[source]]
        converted = [to_example(r) for r in records]
        if args.max_chars:
            kept = [e for e in converted if sum(len(m["content"]) for m in e["messages"]) <= args.max_chars]
            print(f"{source}: {len(kept)} examples ({len(converted) - len(kept)} dropped over {args.max_chars} chars)")
            converted = kept
        else:
            print(f"{source}: {len(converted)} examples")
        examples.extend(converted)

    all_ids = [e["meta"]["id"] for e in examples]
    if len(set(all_ids)) != len(all_ids):
        raise SystemExit("FATAL: duplicate example ids across sources.")

    splits = group_split(examples, args.val_ratio, args.test_ratio, args.seed)
    for name, split_examples in splits.items():
        rng.shuffle(split_examples)
        path = PROCESSED / f"sft_{name}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for example in split_examples:
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
        by_source = Counter(e["meta"]["source"] for e in split_examples)
        print(f"sft_{name}.jsonl: {len(split_examples)} examples {dict(by_source)} -> {path}")


if __name__ == "__main__":
    main()
