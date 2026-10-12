"""Separate explicitly headed transcripts pasted into the memo input.

The returned strings are derived analysis sources. Callers retain the original
SessionInput for persistence and editing; this parser never modifies that object.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


_TRANSCRIPT_TITLES = {"축어록", "합성 축어록", "상담 축어록", "상담내용 축어록", "상담 내용 축어록"}
_OTHER_TITLES = {"사례 소개", "상담 직후 메모", "상담 후 메모", "상담후 메모", "상담자 메모"}
_MARKDOWN_HEADING = re.compile(r"^#{1,6}[ \t]+")
_SECTION_PREFIX = re.compile(r"^(?:[A-Za-z]+-\d+|\d+)[.)]?[ \t]+")
_SPEAKER_LINE = re.compile(
    r"^[ \t]*(?:(?:[A-Za-z]+\d+|\d+)[.)]?[ \t]+)?"
    r"(?:상담자|상담사|내담자)[ \t]*[:：]",
    re.MULTILINE,
)


@dataclass(frozen=True)
class SessionMaterials:
    counselor_memo: str
    transcript_text: str


def _heading_title(line: str) -> str | None:
    title = line.strip()
    if _SPEAKER_LINE.match(title):
        return None
    markdown = _MARKDOWN_HEADING.match(title)
    if markdown:
        title = title[markdown.end():].rstrip("#").strip()
    prefix = _SECTION_PREFIX.match(title)
    if prefix:
        title = title[prefix.end():].strip()
    title = title.removesuffix(":").removesuffix("：").strip()
    if markdown or prefix or title in _TRANSCRIPT_TITLES | _OTHER_TITLES:
        return title
    return None


def _contains_transcript(existing: str, candidate: str) -> bool:
    """Ignore surrounding whitespace only when checking a complete duplicate."""
    existing_lines = [line.strip() for line in existing.splitlines() if line.strip()]
    candidate_lines = [line.strip() for line in candidate.splitlines() if line.strip()]
    count = len(candidate_lines)
    return any(existing_lines[index:index + count] == candidate_lines
               for index in range(len(existing_lines) - count + 1))


def separate_session_materials(counselor_memo: str, transcript_text: str) -> SessionMaterials:
    """Move explicit, speaker-labelled transcript sections to analysis sources.

    Ordinary prose and unlabelled blocks remain memo content. Section boundaries
    come only from headings, and dialogue text (including turn IDs) is preserved.
    A separately supplied transcript is never overwritten. Complete duplicates
    are removed from the memo without adding another copy to the transcript.
    """
    headings: list[tuple[int, int, str]] = []
    offset = 0
    for line in counselor_memo.splitlines(keepends=True):
        title = _heading_title(line)
        if title is not None:
            headings.append((offset, offset + len(line), title))
        offset += len(line)

    removed: list[tuple[int, int]] = []
    derived_transcript = transcript_text
    for index, (start, body_start, title) in enumerate(headings):
        if title not in _TRANSCRIPT_TITLES:
            continue
        end = headings[index + 1][0] if index + 1 < len(headings) else len(counselor_memo)
        body = counselor_memo[body_start:end].strip()
        if not _SPEAKER_LINE.search(body):
            continue
        if not _contains_transcript(derived_transcript, body):
            derived_transcript += ("\n\n" if derived_transcript else "") + body
        removed.append((start, end))

    if not removed:
        return SessionMaterials(counselor_memo, transcript_text)

    remaining: list[str] = []
    cursor = 0
    for start, end in removed:
        remaining.append(counselor_memo[cursor:start])
        cursor = end
    remaining.append(counselor_memo[cursor:])
    return SessionMaterials("".join(remaining).strip(), derived_transcript)
