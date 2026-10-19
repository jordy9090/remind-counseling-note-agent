"""Generate synthetic Korean transcripts and measure offline request bounds.

This benchmark never calls an external model. Token counts use the runtime's
offline tokenizer when available and retain a separate measured field for
comparison.
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Literal

from app.services.transcript_chunking import estimate_korean_tokens, split_source_text


TranscriptStyle = Literal["memo", "speakers", "timestamps"]
EVENT_MARKERS = {
    "early": "[초반핵심] 발표 준비가 늦어질까 걱정되어 잠들기 어려웠다고 표현함.",
    "middle": "[중반핵심] 상담자는 걱정이 커지는 상황과 신체 반응을 구체적으로 탐색함.",
    "late": "[후반핵심] 내담자는 다음 회기 계획을 새로 합의하지 않았다고 확인함.",
}


def generate_synthetic_transcript(minutes: int, style: TranscriptStyle) -> str:
    """Create fully synthetic material at roughly 300 Korean characters/minute."""
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    target_chars = minutes * 300
    lines: list[str] = []
    turn = 0
    while len("\n".join(lines)) < target_chars:
        progress = len("\n".join(lines)) / target_chars
        marker = ""
        if not any(EVENT_MARKERS["early"] in line for line in lines) and progress >= 0.08:
            marker = EVENT_MARKERS["early"]
        elif not any(EVENT_MARKERS["middle"] in line for line in lines) and progress >= 0.48:
            marker = EVENT_MARKERS["middle"]
        elif not any(EVENT_MARKERS["late"] in line for line in lines) and progress >= 0.88:
            marker = EVENT_MARKERS["late"]
        speaker = "내담자" if turn % 2 == 0 else "상담자"
        base = marker or (
            "이번 주 학업과 발표 준비 일정을 돌아보며 걱정이 커진 장면을 설명함."
            if speaker == "내담자"
            else "상담자는 당시 상황과 내담자가 표현한 감정을 구분하여 확인함."
        )
        if style == "memo":
            line = base
        elif style == "speakers":
            line = f"{speaker}: {base}"
        else:
            elapsed_seconds = turn * 10
            line = f"[{elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}] {speaker}: {base}"
        lines.append(line)
        turn += 1
    return "\n".join(lines)


def measured_token_count(text: str, model: str = "gpt-5.4") -> int | None:
    try:
        import tiktoken

        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("o200k_base")
        return len(encoding.encode(text))
    except (ImportError, ValueError):
        return None


def benchmark(minutes: int, style: TranscriptStyle) -> dict[str, object]:
    started = time.perf_counter()
    text = generate_synthetic_transcript(minutes, style)
    chunks = split_source_text(
        text,
        source_field="transcript_text",
        target_chars=14_000,
        max_chunks=8,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "minutes": minutes,
        "style": style,
        "characters": len(text),
        "measured_tokens": measured_token_count(text),
        "estimated_tokens_upper_bound": estimate_korean_tokens(text),
        "chunks": len(chunks),
        "estimated_core_calls": len(chunks) + 1,
        "offline_preprocessing_latency_ms": elapsed_ms,
        "event_markers_preserved": {
            name: marker in "".join(chunk.text for chunk in chunks)
            for name, marker in EVENT_MARKERS.items()
        },
        "external_model_executed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    results = [
        benchmark(minutes, style)
        for minutes in (10, 20, 50, 60)
        for style in ("memo", "speakers", "timestamps")
    ]
    print(json.dumps(results, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
