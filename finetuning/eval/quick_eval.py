"""Quick structural evaluation of a fine-tuned note-generation model.

Generates notes for the validation split and checks, without any LLM judge:
  - JSON parse rate
  - required section/key coverage (SessionSummaryDraft shape)
  - reflection kept as counselor_input (must never be auto-written)
  - evidence_type validity and requires_review consistency
  - Korean output ratio

  python finetuning/eval/quick_eval.py \
      --adapter finetuning/output/qwen25-7b-remind-note-qlora \
      --base Qwen/Qwen2.5-7B-Instruct --limit 50
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REQUIRED_SECTIONS = [
    "session_theme",
    "presenting_problem",
    "session_content",
    "counselor_intervention",
    "client_response",
    "reflection",
    "next_plan",
]
SECTION_KEYS = {"text", "evidence_type", "source_refs", "requires_review"}
VALID_EVIDENCE = {"direct", "inferred", "counselor_input", "needs_review", "mixed", "model_inference", "prior_context_based"}
REVIEW_TYPES = {"inferred", "model_inference", "needs_review", "counselor_input", "prior_context_based"}
HANGUL_RE = re.compile(r"[가-힣]")


def extract_json(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def check_note(note: dict) -> list[str]:
    problems = []
    for name in REQUIRED_SECTIONS:
        section = note.get(name)
        if not isinstance(section, dict):
            problems.append(f"missing section: {name}")
            continue
        if not SECTION_KEYS.issubset(section):
            problems.append(f"{name}: missing keys {SECTION_KEYS - set(section)}")
            continue
        if section["evidence_type"] not in VALID_EVIDENCE:
            problems.append(f"{name}: invalid evidence_type {section['evidence_type']!r}")
        if (section["evidence_type"] in REVIEW_TYPES) != bool(section["requires_review"]):
            problems.append(f"{name}: requires_review inconsistent with evidence_type")
    reflection = note.get("reflection") or {}
    if reflection.get("evidence_type") != "counselor_input":
        problems.append("reflection must stay counselor_input")
    return problems


def korean_ratio(note: dict) -> float:
    texts = " ".join(
        (note.get(name) or {}).get("text", "") for name in REQUIRED_SECTIONS if name != "reflection"
    )
    letters = [c for c in texts if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if HANGUL_RE.match(c)) / len(letters)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--adapter", default=None, help="LoRA adapter dir; omit to eval the base model")
    parser.add_argument("--val", default="finetuning/data/processed/sft_val.jsonl")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=quant, device_map="auto")
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if args.adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.adapter)

    examples = [json.loads(line) for line in Path(args.val).read_text(encoding="utf-8").splitlines()][: args.limit]
    parsed = valid = 0
    ko_ratios = []
    for i, example in enumerate(examples, 1):
        prompt_messages = example["messages"][:-1]  # system + user
        inputs = tokenizer.apply_chat_template(
            prompt_messages, add_generation_prompt=True, return_tensors="pt"
        ).to(model.device)
        output = model.generate(inputs, max_new_tokens=args.max_new_tokens, do_sample=False)
        text = tokenizer.decode(output[0][inputs.shape[1]:], skip_special_tokens=True)
        note = extract_json(text)
        if note is None:
            print(f"[{i}] JSON parse FAILED")
            continue
        parsed += 1
        problems = check_note(note)
        if not problems:
            valid += 1
        else:
            print(f"[{i}] " + "; ".join(problems[:3]))
        ko_ratios.append(korean_ratio(note))

    n = len(examples)
    print(f"\nJSON parse rate:      {parsed}/{n}")
    print(f"Schema-valid rate:    {valid}/{n}")
    if ko_ratios:
        print(f"Mean Korean ratio:    {sum(ko_ratios) / len(ko_ratios):.2f}")


if __name__ == "__main__":
    main()
