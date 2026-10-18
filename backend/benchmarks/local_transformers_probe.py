"""Probe cached local chat models with synthetic counseling transcripts.

The probe never downloads a model and never prints the transcript or generated
text. It reports only runtime metadata and deterministic evidence checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from benchmarks.long_transcript_benchmark import generate_synthetic_transcript


REQUIRED_FIELDS = (
    "main_content",
    "counselor_intervention",
    "client_response",
    "next_plan",
)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Return the first complete JSON object without logging model output."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    return None
                return value if isinstance(value, dict) else None
    return None


def score_summary(payload: dict[str, Any] | None) -> dict[str, bool]:
    """Check the synthetic evidence contract without exposing generated text."""
    if payload is None:
        return {
            "json_object": False,
            "required_fields": False,
            "client_evidence": False,
            "counselor_evidence": False,
            "no_plan_grounding": False,
        }
    values = {field: payload.get(field) for field in REQUIRED_FIELDS}
    required_fields = all(isinstance(value, str) and value.strip() for value in values.values())
    client_text = " ".join(str(values[field] or "") for field in ("main_content", "client_response"))
    counselor_text = str(values["counselor_intervention"] or "")
    plan_text = str(values["next_plan"] or "")
    return {
        "json_object": True,
        "required_fields": required_fields,
        "client_evidence": any(term in client_text for term in ("발표", "잠들", "걱정")),
        "counselor_evidence": any(term in counselor_text for term in ("상황", "신체 반응", "탐색")),
        "no_plan_grounding": any(term in plan_text for term in ("합의하지", "없", "확인 필요")),
    }


def build_prompt(transcript: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "당신은 상담 기록 보조자입니다. 입력에 없는 사실, 개입, 변화, 계획을 만들지 마세요. "
                "상담자와 내담자의 발화를 구분하고 설명이나 코드 펜스 없이 JSON 객체만 출력하세요."
            ),
        },
        {
            "role": "user",
            "content": (
                "다음 합성 축어록을 근거로 main_content, counselor_intervention, client_response, "
                "next_plan 네 문자열 필드를 작성하세요. 계획을 새로 합의하지 않았다는 근거가 있으면 "
                "구체적인 계획을 만들지 말고 그 사실을 유지하세요. 반드시 다음 키를 정확히 한 번씩 "
                "사용하세요: {\"main_content\":\"\",\"counselor_intervention\":\"\","
                "\"client_response\":\"\",\"next_plan\":\"\"}.\n\n"
                f"{transcript}"
            ),
        },
    ]


def model_identity(model_path: Path) -> tuple[str, str]:
    cache_directory = next(
        (parent.name for parent in model_path.parents if parent.name.startswith("models--")),
        "",
    )
    label = cache_directory.removeprefix("models--").replace("--", "/")
    return label or model_path.name, model_path.name


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--minutes", type=int, choices=(10, 20, 50, 60), default=10)
    parser.add_argument("--style", choices=("speakers", "timestamps"), default="speakers")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    args = parser.parse_args()

    model_path = Path(args.model_path).expanduser().resolve()
    if not model_path.is_dir():
        raise SystemExit("model path must be an existing local directory")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    transcript = generate_synthetic_transcript(args.minutes, args.style)
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path),
        local_files_only=True,
        trust_remote_code=False,
    )
    model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        local_files_only=True,
        trust_remote_code=False,
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    ).to("cuda")
    model.eval()

    rendered = tokenizer.apply_chat_template(
        build_prompt(transcript),
        tokenize=False,
        add_generation_prompt=True,
    )
    inputs = tokenizer(rendered, return_tensors="pt").to("cuda")
    torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            do_sample=False,
            max_new_tokens=args.max_new_tokens,
            pad_token_id=tokenizer.eos_token_id,
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    output_tokens = generated.shape[-1] - inputs["input_ids"].shape[-1]
    output = tokenizer.decode(generated[0, inputs["input_ids"].shape[-1]:], skip_special_tokens=True)
    parsed = extract_json_object(output)
    model_label, model_revision = model_identity(model_path)

    print(json.dumps({
        "success": parsed is not None,
        "model": model_label,
        "model_revision": model_revision,
        "minutes": args.minutes,
        "style": args.style,
        "characters": len(transcript),
        "input_tokens": int(inputs["input_ids"].shape[-1]),
        "output_tokens": int(output_tokens),
        "latency_ms": elapsed_ms,
        "peak_gpu_memory_mb": int(torch.cuda.max_memory_allocated() / 1024 / 1024),
        "checks": score_summary(parsed),
        "returned_fields": sorted(parsed) if parsed is not None else [],
        "field_string_flags": {
            field: isinstance(parsed.get(field), str) if parsed is not None else False
            for field in REQUIRED_FIELDS
        },
        "field_nonempty_flags": {
            field: bool(str(parsed.get(field) or "").strip()) if parsed is not None else False
            for field in REQUIRED_FIELDS
        },
        "response_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest(),
        "response_characters": len(output),
        "external_model_executed": False,
        "local_model_executed": True,
        "network_access_required": False,
        "estimated_cost_usd": 0.0,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
