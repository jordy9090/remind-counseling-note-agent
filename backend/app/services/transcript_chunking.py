"""Deterministic, position-preserving chunks for long counseling materials."""
from __future__ import annotations

import re
from dataclasses import dataclass


_SENTENCE_END = re.compile(r"[.!?。！？](?:[\"'”’」』])?\s+")


class TranscriptLimitError(ValueError):
    """The complete input cannot fit within the configured request budget."""


@dataclass(frozen=True)
class SourceChunk:
    source_field: str
    source_ref: str
    text: str
    start_char: int
    end_char: int
    index: int
    total: int


def split_source_text(
    text: str,
    *,
    source_field: str,
    target_chars: int,
    max_chunks: int,
) -> list[SourceChunk]:
    """Split at line or sentence boundaries while preserving exact offsets."""
    if target_chars < 100:
        raise ValueError("target_chars must be at least 100")
    if max_chunks < 1:
        raise ValueError("max_chunks must be positive")
    if not text:
        return []
    if len(text) > target_chars * max_chunks:
        raise TranscriptLimitError(
            f"입력 전체를 처리하려면 {max_chunks}개보다 많은 청크가 필요합니다."
        )

    ranges: list[tuple[int, int]] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        if len(ranges) >= max_chunks:
            raise TranscriptLimitError(
                f"입력 전체를 처리하려면 {max_chunks}개보다 많은 청크가 필요합니다."
            )
        proposed_end = min(length, cursor + target_chars)
        end = length if proposed_end == length else _preferred_boundary(text, cursor, proposed_end)
        remaining_slots = max_chunks - len(ranges) - 1
        if length - end > target_chars * remaining_slots:
            end = proposed_end
        if end <= cursor:
            end = proposed_end
        while end < length and text[end].isspace():
            end += 1
        ranges.append((cursor, end))
        cursor = end

    total = len(ranges)
    return [
        SourceChunk(
            source_field=source_field,
            source_ref=f"{source_field}.chars_{start}_{end}",
            text=text[start:end],
            start_char=start,
            end_char=end,
            index=index,
            total=total,
        )
        for index, (start, end) in enumerate(ranges, 1)
    ]


def _preferred_boundary(text: str, start: int, proposed_end: int) -> int:
    minimum = start + int((proposed_end - start) * 0.6)
    line_end = text.rfind("\n", minimum, proposed_end + 1)
    if line_end >= minimum:
        return line_end + 1

    sentence_end = -1
    for match in _SENTENCE_END.finditer(text, minimum, proposed_end + 1):
        sentence_end = match.end()
    if sentence_end >= minimum:
        return sentence_end

    space_end = text.rfind(" ", minimum, proposed_end + 1)
    return space_end + 1 if space_end >= minimum else proposed_end


def estimate_korean_tokens(text: str) -> int:
    """Return a conservative offline estimate when provider usage is unavailable."""
    return len(text or "")
