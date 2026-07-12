"""Fill missing `note` targets with an LLM (distillation for SFT).

Reads data/processed/intermediate_<source>.jsonl, generates a Korean
SessionSummaryDraft-shaped note for each record whose `note` is null, and writes
data/processed/synthesized_<source>.jsonl. Already-synthesized ids are skipped,
so the script can be re-run to resume after interruption.

Requires OPENAI_API_KEY in the environment (same key the backend uses).
Rough cost with gpt-4o-mini: KMI 1,000 dialogues ~= 3M input + 0.5M output
tokens ~= $0.75. Verify a small batch first:

  python data/synthesize_notes.py --source kmi --limit 20
  python data/synthesize_notes.py --source kmi
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROCESSED = Path(__file__).parent / "processed"

SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "evidence_type": {
            "type": "string",
            "enum": ["direct", "inferred", "counselor_input", "needs_review", "mixed"],
        },
        "source_refs": {"type": "array", "items": {"type": "string"}},
        "requires_review": {"type": "boolean"},
    },
    "required": ["text", "evidence_type", "source_refs", "requires_review"],
    "additionalProperties": False,
}

NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        field: SECTION_SCHEMA
        for field in [
            "session_theme",
            "presenting_problem",
            "session_content",
            "counselor_intervention",
            "client_response",
            "reflection",
            "next_plan",
        ]
    },
    "required": [
        "session_theme",
        "presenting_problem",
        "session_content",
        "counselor_intervention",
        "client_response",
        "reflection",
        "next_plan",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """당신은 심리상담 회기 축어록을 구조화된 한국어 회기요약으로 변환하는 전문가입니다.
Re:mind 서비스의 원칙을 따르세요.

- 입력에 없는 정보를 확정적으로 쓰지 않습니다. 축어록에 직접 근거가 있으면 evidence_type="direct",
  요약/해석이 섞이면 "mixed", 추론이면 "inferred", 근거가 부족하면 "needs_review"로 표시합니다.
- source_refs는 근거가 있는 섹션이면 ["transcript_text"], 근거가 없으면 []로 둡니다.
- reflection은 항상 상담사 직접 작성 영역입니다: text="상담자 reflection은 상담사가 직접 작성하거나
  확인해야 합니다.", evidence_type="counselor_input", source_refs=[], requires_review=true.
- 진단, 위험도 평가, 치료 권고, 심리검사 해석을 생성하지 않습니다.
- requires_review는 evidence_type이 direct가 아니면 true입니다.
- 각 섹션 text는 자연스러운 한국어 문어체 1~4문장으로 작성합니다.
- next_plan은 축어록에 다음 회기/과제 언급이 있을 때만 direct로 쓰고, 없으면
  "다음 회기 계획이 명시되지 않아 상담사 확인이 필요합니다."를 needs_review로 씁니다."""


def dialogue_to_transcript(dialogue: list[dict]) -> str:
    role = {"counselor": "상담사", "client": "내담자"}
    return "\n".join(f"{role[t['speaker']]}: {t['text']}" for t in dialogue)


def synthesize(client, model: str, record: dict) -> dict:
    transcript = dialogue_to_transcript(record["dialogue"])
    if record["lang"] != "ko":
        transcript = f"(다음 축어록은 {record['lang']} 원문입니다. 회기요약은 한국어로 작성하세요.)\n{transcript}"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"다음 상담 축어록을 회기요약 JSON으로 변환하세요.\n\n{transcript}"},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "session_summary_draft", "strict": True, "schema": NOTE_SCHEMA},
        },
        temperature=0.2,
    )
    return json.loads(response.choices[0].message.content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="e.g. kmi, cpsycoun")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"))
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set. Export it (or put it in backend/.env and source it) first.")
    from openai import OpenAI  # imported late so --help works without the package

    client = OpenAI()

    in_path = PROCESSED / f"intermediate_{args.source}.jsonl"
    out_path = PROCESSED / f"synthesized_{args.source}.jsonl"
    records = [json.loads(line) for line in in_path.read_text(encoding="utf-8").splitlines()]

    done_ids = set()
    if out_path.exists():
        done_ids = {json.loads(line)["id"] for line in out_path.read_text(encoding="utf-8").splitlines()}

    todo = [r for r in records if r["note"] is None and r["id"] not in done_ids]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} records to synthesize ({len(done_ids)} already done)")

    with out_path.open("a", encoding="utf-8") as f:
        for i, record in enumerate(todo, 1):
            try:
                record["note"] = synthesize(client, args.model, record)
                record["note_origin"] = f"synthesized:{args.model}"
            except Exception as error:
                print(f"  {record['id']}: FAILED ({error})")
                continue
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            if i % 20 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} done")


if __name__ == "__main__":
    main()
