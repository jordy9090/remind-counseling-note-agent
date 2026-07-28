"""Constrained structural evaluation of a fine-tuned counseling-note model.

The evaluator generates one schema-constrained JSON object per validation
example, writes detailed JSONL results, and reports structural/repetition
metrics without an LLM judge.

Example:
  python finetuning/eval/quick_eval.py \
      --base Qwen/Qwen3-14B \
      --adapter finetuning/output/qwen3-14b-remind-note-qlora \
      --limit 10
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import re
from pathlib import Path
from typing import Any, Callable, Iterable

from jsonschema import Draft7Validator

try:
    from .note_schema import (
        COUNSELING_NOTE_SCHEMA,
        NOTE_SECTIONS,
        REVIEW_EVIDENCE_TYPES,
        VALID_EVIDENCE_TYPES,
    )
except ImportError:  # Direct script execution adds this directory to sys.path.
    from note_schema import (  # type: ignore[no-redef]
        COUNSELING_NOTE_SCHEMA,
        NOTE_SECTIONS,
        REVIEW_EVIDENCE_TYPES,
        VALID_EVIDENCE_TYPES,
    )

HANGUL_RE = re.compile(r"[가-힣]")
SENTENCE_SPLIT_RE = re.compile(r"[.!?。！？\n]+")
GENERATION_INSTRUCTION = """출력 지침:
- 정확히 하나의 JSON 객체만 출력하세요.
- 긴 축어록 구절을 복사하지 말고 요약하세요.
- 같은 문장을 반복하지 마세요.
- 직접 인용은 짧게 유지하세요."""


def extract_json(text: str) -> dict[str, Any] | None:
    """Parse the complete output, rejecting prefixes, suffixes, and extra brackets."""
    try:
        value = json.loads(text.strip())
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def check_note(note: dict[str, Any]) -> list[str]:
    """Return concise JSON Schema validation errors for a generated note."""
    errors = sorted(
        Draft7Validator(COUNSELING_NOTE_SCHEMA).iter_errors(note),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    problems = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path)
        problems.append(f"{location}: {error.message}" if location else error.message)

    for section_name in NOTE_SECTIONS:
        section = note.get(section_name)
        if not isinstance(section, dict):
            continue
        evidence_type = section.get("evidence_type")
        requires_review = section.get("requires_review")
        if evidence_type in VALID_EVIDENCE_TYPES and isinstance(requires_review, bool):
            expected_review = evidence_type in REVIEW_EVIDENCE_TYPES
            if requires_review != expected_review:
                problems.append(
                    f"{section_name}: requires_review inconsistent with evidence_type"
                )
    return problems


def _content_text(value: dict[str, Any] | str) -> str:
    if isinstance(value, str):
        return value
    texts = []
    for section_name in NOTE_SECTIONS:
        if section_name == "reflection":
            continue
        section = value.get(section_name)
        if isinstance(section, dict) and isinstance(section.get("text"), str):
            texts.append(section["text"])
    return "\n".join(texts)


def korean_ratio(value: dict[str, Any] | str) -> float:
    """Return the Hangul share among alphabetic characters in generated content."""
    letters = [character for character in _content_text(value) if character.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for character in letters if HANGUL_RE.fullmatch(character)) / len(letters)


def detect_repetition(value: dict[str, Any] | str) -> bool:
    """Detect a substantive sentence repeated at least three times."""
    sentences = []
    for sentence in SENTENCE_SPLIT_RE.split(_content_text(value)):
        normalized = re.sub(r"\s+", " ", sentence).strip(" \t\r\"'“”‘’,:;[]{}")
        if len(normalized) >= 10 and HANGUL_RE.search(normalized):
            sentences.append(normalized)
    return any(count >= 3 for count in Counter(sentences).values())


def prepare_prompt_messages(example: dict[str, Any]) -> list[dict[str, str]]:
    """Copy the source prompt and append the concise generation instruction."""
    messages = [dict(message) for message in example["messages"][:-1]]
    for message in reversed(messages):
        if message.get("role") == "user":
            message["content"] = f"{message['content'].rstrip()}\n\n{GENERATION_INSTRUCTION}"
            return messages
    raise ValueError("validation example has no user message")


def json_string_alphabet(tokenizer_alphabet: str) -> str:
    """Exclude raw C0 controls; JSON strings must represent them as escapes."""
    return "".join(character for character in tokenizer_alphabet if ord(character) >= 0x20)


def build_constraint_factory(tokenizer: Any) -> Callable[[], Any]:
    """Precompute tokenizer data and return a fresh schema enforcer per example."""
    from lmformatenforcer import CharacterLevelParserConfig, JsonSchemaParser
    from lmformatenforcer.integrations.transformers import (
        build_token_enforcer_tokenizer_data,
        build_transformers_prefix_allowed_tokens_fn,
    )

    tokenizer_data = build_token_enforcer_tokenizer_data(tokenizer)
    tokenizer_data.tokenizer_alphabet = json_string_alphabet(tokenizer_data.tokenizer_alphabet)
    parser_config = CharacterLevelParserConfig(alphabet=tokenizer_data.tokenizer_alphabet)

    def factory() -> Any:
        parser = JsonSchemaParser(COUNSELING_NOTE_SCHEMA, config=parser_config)
        return build_transformers_prefix_allowed_tokens_fn(tokenizer_data, parser)

    return factory


def generate_note_text(
    model: Any,
    tokenizer: Any,
    prompt_messages: list[dict[str, str]],
    *,
    max_new_tokens: int,
    prefix_allowed_tokens_fn: Any,
) -> tuple[str, bool]:
    """Generate one constrained note; returns (text, truncated_at_max_tokens)."""
    prompt_text = tokenizer.apply_chat_template(
        prompt_messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    encoded = tokenizer(prompt_text, return_tensors="pt")
    if "attention_mask" not in encoded:
        raise RuntimeError("tokenizer did not return an attention_mask")

    input_ids = encoded["input_ids"].to(model.device)
    attention_mask = encoded["attention_mask"].to(model.device)
    generation_args = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "max_new_tokens": max_new_tokens,
        "do_sample": False,
        "prefix_allowed_tokens_fn": prefix_allowed_tokens_fn,
    }
    pad_token_id = getattr(tokenizer, "pad_token_id", None)
    if pad_token_id is None:
        pad_token_id = getattr(tokenizer, "eos_token_id", None)
    if pad_token_id is not None:
        generation_args["pad_token_id"] = pad_token_id

    output = model.generate(**generation_args)
    prompt_length = input_ids.shape[1]
    generated_ids = output[0][prompt_length:]
    truncated = len(generated_ids) >= max_new_tokens
    return tokenizer.decode(generated_ids, skip_special_tokens=True).strip(), truncated


def missing_sections(note: dict[str, Any] | None) -> list[str]:
    if not isinstance(note, dict):
        return list(NOTE_SECTIONS)
    return [name for name in NOTE_SECTIONS if not isinstance(note.get(name), dict)]


def evaluate_text(text: str, truncated: bool = False) -> dict[str, Any]:
    note = extract_json(text)
    repeated = detect_repetition(note if note is not None else text)
    ratio = korean_ratio(note if note is not None else text)
    missing = missing_sections(note)
    if note is None:
        return {
            "parse_status": "invalid",
            "schema_status": "not_checked",
            "truncated": truncated,
            "missing_sections": missing,
            "repetition_detected": repeated,
            "korean_ratio": ratio,
            "generated_note": None,
            "raw_output": text,
            "error": "output is not exactly one valid JSON object"
            + (" (hit max_new_tokens)" if truncated else ""),
        }

    problems = check_note(note)
    return {
        "parse_status": "valid",
        "schema_status": "invalid" if problems else "valid",
        "truncated": truncated,
        "missing_sections": missing,
        "repetition_detected": repeated,
        "korean_ratio": ratio,
        "generated_note": note,
        "raw_output": text,
        "error": "; ".join(problems[:5]) if problems else None,
    }


def generation_error_result(error: Exception) -> dict[str, Any]:
    return {
        "parse_status": "invalid",
        "schema_status": "not_checked",
        "truncated": False,
        "missing_sections": list(NOTE_SECTIONS),
        "repetition_detected": False,
        "korean_ratio": 0.0,
        "generated_note": None,
        "raw_output": "",
        "error": f"generation failed: {type(error).__name__}: {error}",
    }


def summarize_results(results: Iterable[dict[str, Any]]) -> dict[str, float | int]:
    result_list = list(results)
    total = len(result_list)
    json_valid = sum(result["parse_status"] == "valid" for result in result_list)
    schema_valid = sum(result["schema_status"] == "valid" for result in result_list)
    repeated = sum(bool(result["repetition_detected"]) for result in result_list)
    truncated = sum(bool(result.get("truncated")) for result in result_list)
    with_missing = sum(bool(result.get("missing_sections")) for result in result_list)
    return {
        "total": total,
        "json_valid": json_valid,
        "json_valid_rate": json_valid / total if total else 0.0,
        "schema_valid": schema_valid,
        "schema_valid_rate": schema_valid / total if total else 0.0,
        "repetition_count": repeated,
        "repetition_rate": repeated / total if total else 0.0,
        "truncated_count": truncated,
        "truncated_rate": truncated / total if total else 0.0,
        "missing_section_count": with_missing,
        "missing_section_rate": with_missing / total if total else 0.0,
        "korean_ratio": (
            sum(float(result["korean_ratio"]) for result in result_list) / total if total else 0.0
        ),
    }


def load_model_and_tokenizer(base: str, adapter: str | None) -> tuple[Any, Any]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base,
        quantization_config=quantization,
        device_map="auto",
    )
    tokenizer = AutoTokenizer.from_pretrained(base)
    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    return model, tokenizer


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--adapter", default=None, help="LoRA adapter dir; omit to eval the base model")
    parser.add_argument(
        "--val",
        default="finetuning/data/processed/sft_test.jsonl",
        help="평가 데이터 (기본: held-out test set)",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=2048,
        help="타깃 노트가 900~1,400 토큰이라 1024는 정상 출력도 잘림 — 2048 이상 권장",
    )
    parser.add_argument(
        "--results-jsonl",
        default="finetuning/eval/results/quick_eval.jsonl",
        help="per-example evaluation output",
    )
    args = parser.parse_args()

    examples = [
        json.loads(line)
        for line in Path(args.val).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ][: args.limit]
    if not examples:
        raise SystemExit("No validation examples found.")

    model, tokenizer = load_model_and_tokenizer(args.base, args.adapter)
    constraint_factory = build_constraint_factory(tokenizer)
    results_path = Path(args.results_jsonl)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results = []

    with results_path.open("w", encoding="utf-8") as output_file:
        for index, example in enumerate(examples, 1):
            try:
                text, truncated = generate_note_text(
                    model,
                    tokenizer,
                    prepare_prompt_messages(example),
                    max_new_tokens=args.max_new_tokens,
                    prefix_allowed_tokens_fn=constraint_factory(),
                )
                result = evaluate_text(text, truncated)
            except Exception as error:
                result = generation_error_result(error)

            meta = example.get("meta") or {}
            reference_note = extract_json(example["messages"][-1]["content"])
            result = {
                "example_index": index,
                "example_id": meta.get("id"),
                "case_id": meta.get("case_id"),
                # 근거 대조(환각 확인)용: 참조 노트 원문. 축어록 원문은 example_id로
                # sft_*.jsonl에서 찾아 대조한다.
                "reference_note": reference_note,
                **result,
            }
            results.append(result)
            output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            output_file.flush()

            if result["error"]:
                print(f"[{index}] {result['error']}")
            else:
                print(f"[{index}] valid JSON and schema")

    metrics = summarize_results(results)
    total = int(metrics["total"])
    print(f"\nJSON-valid rate:     {metrics['json_valid']}/{total} ({metrics['json_valid_rate']:.1%})")
    print(f"Schema-valid rate:   {metrics['schema_valid']}/{total} ({metrics['schema_valid_rate']:.1%})")
    print(f"Repetition rate:     {metrics['repetition_count']}/{total} ({metrics['repetition_rate']:.1%})")
    print(f"Truncated rate:      {metrics['truncated_count']}/{total} ({metrics['truncated_rate']:.1%})")
    print(f"Missing-section rate:{metrics['missing_section_count']}/{total} ({metrics['missing_section_rate']:.1%})")
    print(f"Mean Korean ratio:   {metrics['korean_ratio']:.2f}")
    print(f"Results JSONL:       {results_path}")


if __name__ == "__main__":
    main()
