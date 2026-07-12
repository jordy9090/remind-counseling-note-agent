"""Build the final chat-format SFT dataset from converted/synthesized records.

Merges data/processed/synthesized_<source>.jsonl (preferred) and
intermediate_<source>.jsonl, keeps records that have a `note`, renders each as a
chat example that mirrors the production Re:mind summary task
(backend/app/graph/nodes.py::generate_summary), and writes:

  data/processed/sft_train.jsonl
  data/processed/sft_val.jsonl

Each line: {"messages": [{role, content} x3], "meta": {...}}
— the format expected by trl's SFTTrainer with a chat template.

Usage:
  python data/build_sft_dataset.py --sources kmi,cactus --max-per-source cactus=4000
"""
from __future__ import annotations

import argparse
import json
import random
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


def dialogue_to_transcript(dialogue: list[dict], lang: str) -> str:
    roles = {
        "ko": {"counselor": "상담사", "client": "내담자"},
        "en": {"counselor": "Counselor", "client": "Client"},
        "zh": {"counselor": "咨询师", "client": "来访者"},
    }[lang if lang in ("ko", "en", "zh") else "en"]
    return "\n".join(f"{roles[t['speaker']]}: {t['text']}" for t in dialogue)


def to_example(record: dict, rng: random.Random) -> dict:
    session_number = rng.randint(1, 12)
    session_info = {
        "case_id": f"case-{record['id']}",
        "session_number": session_number,
        "session_date": "",
        "counselor_name": "",
    }
    user = USER_TEMPLATE.format(
        session_info=json.dumps(session_info, ensure_ascii=False),
        counselor_memo=record.get("meta", {}).get("counselor_memo", "") or "(없음)",
        transcript=dialogue_to_transcript(record["dialogue"], record["lang"]),
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
            "source": record["source"],
            "lang": record["lang"],
            "license": record["license"],
            "note_origin": record.get("note_origin", "rule_based"),
        },
    }


def load_source(source: str) -> list[dict]:
    """Prefer synthesized records; fall back to intermediate ones with notes."""
    records: dict[str, dict] = {}
    for prefix in ("intermediate", "synthesized"):
        path = PROCESSED / f"{prefix}_{source}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("note"):
                records[record["id"]] = record  # synthesized pass overwrites
    return list(records.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="kmi,cactus")
    parser.add_argument("--max-per-source", default="", help="e.g. cactus=4000,kmi=1000")
    parser.add_argument("--val-ratio", type=float, default=0.05)
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
        converted = [to_example(r, rng) for r in records]
        if args.max_chars:
            kept = [e for e in converted if sum(len(m["content"]) for m in e["messages"]) <= args.max_chars]
            print(f"{source}: {len(kept)} examples ({len(converted) - len(kept)} dropped over {args.max_chars} chars)")
            converted = kept
        else:
            print(f"{source}: {len(converted)} examples")
        examples.extend(converted)

    rng.shuffle(examples)
    n_val = max(1, int(len(examples) * args.val_ratio)) if examples else 0
    splits = {"sft_val.jsonl": examples[:n_val], "sft_train.jsonl": examples[n_val:]}
    for name, split in splits.items():
        path = PROCESSED / name
        with path.open("w", encoding="utf-8") as f:
            for example in split:
                f.write(json.dumps(example, ensure_ascii=False) + "\n")
        print(f"{name}: {len(split)} examples -> {path}")


if __name__ == "__main__":
    main()
