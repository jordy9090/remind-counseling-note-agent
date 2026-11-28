"""Bounded prose checks and literal quotation checks for session summaries."""
from __future__ import annotations

import re

from app.schemas.note import SessionSummary, SessionSummaryV2, summary_sections


class SummaryQualityError(ValueError):
    """A bounded rewrite could not produce a usable summary; contains no source text."""

    def __init__(self) -> None:
        super().__init__("회기요약을 충분히 정리하지 못했습니다. 잠시 후 다시 생성해주세요. 입력 자료는 유지됩니다.")


# These are rejection ceilings, not required lengths. Sparse evidence stays short.
SECTION_LIMITS = {
    "presenting_problem": (200, 2),
    "session_theme": (160, 2),
    "session_content": (600, 5),
    "counselor_intervention": (350, 3),
    "client_response": (350, 3),
    "reflection": (350, 3),
    "next_plan": (350, 4),
}
SPEAKER_LABEL = re.compile(
    r"(?:^|\n|(?<=[.!?])\s+)(?:[-*]\s*)?"
    r"(?:(?:내담자|상담자|상담사|client|counselor|therapist|Cl|Co|C|T)\s*[:：]"
    r"|\[(?:내담자|상담자|상담사|client|counselor|therapist)\])",
    re.IGNORECASE,
)
QUOTED_TEXT = re.compile(r"\"[^\"\n]+\"|'[^'\n]+'|“[^”\n]+”|「[^」\n]+」|‘[^’\n]+’")
# Exclude common record nouns ending in the same syllable: 필요, 중요, 개요.
CONVERSATIONAL_ENDING = re.compile(
    r"(?:(?<!필)(?<!중)(?<!개)요|죠)\s*[.!?。]*$"
)
FIRST_PERSON = re.compile(r"(?:^|\s)(?:저는|제가|저도|저를|제게|나는|내가|저희|제\s|내\s)")


def summary_quality_issues(summary: SessionSummary) -> dict[str, list[str]]:
    """Return field-only feedback without retaining or emitting counseling text."""
    issues: dict[str, list[str]] = {}
    for field_name, section in summary_sections(summary):
        if field_name.startswith("client_reactions.items."):
            continue
        max_chars, max_sentences = SECTION_LIMITS.get(field_name, (600, 4))
        text = section.text.strip()
        field_issues: list[str] = []
        if SPEAKER_LABEL.search(text):
            field_issues.append("화자 표지가 있는 대화문을 역할이 분명한 3인칭 기록체로 요약하세요.")
        quotations = QUOTED_TEXT.findall(text)
        if len(quotations) >= 3 and sum(map(len, quotations)) > len(text) / 2:
            field_issues.append("인용문이 항목 대부분을 차지합니다. 핵심 인용만 짧게 남기고 의미를 요약하세요.")
        narrative = re.sub(r"[\"'“”「」‘’]", "", _without_supporting_quotes(text))
        sentences = [part.strip() for part in re.split(r"(?<=[.!?。])\s+|[\r\n]+", narrative) if part.strip()]
        dialogue_count = sum(
            bool(CONVERSATIONAL_ENDING.search(sentence))
            or (bool(FIRST_PERSON.search(sentence)) and sentence.endswith("?"))
            for sentence in sentences
        )
        if dialogue_count >= 2:
            field_issues.append("대화체 발화를 나열하지 말고 사건·개입·반응의 의미를 기록체로 압축하세요.")
        if len(text) > max_chars or len(sentences) > max_sentences:
            field_issues.append("항목의 분량이 지나칩니다. 반복과 주변 발화를 줄이고 핵심만 요약하세요.")
        if field_issues:
            issues[field_name] = field_issues
    return issues


def summary_quote_issues(summary: SessionSummary, catalog: dict[str, str]) -> dict[str, list[str]]:
    """Check quoted wording against cited sources, never semantic support.

    Normalize whitespace only. Do not repair words, punctuation or speaker labels,
    stitch different turns together, or let a whole-transcript ref hide a wrong
    precise turn. The result contains field names and safe feedback, not source text.
    """
    issues: dict[str, list[str]] = {}
    for field, section in summary_sections(summary):
        if field.startswith("client_reactions.items."):
            continue
        quotes = [" ".join(match.group()[1:-1].split()) for match in QUOTED_TEXT.finditer(section.text)]
        if not quotes:
            continue
        refs = section.source_refs
        has_turns = any(ref.startswith("transcript.turn_") for ref in refs)
        excerpts = [
            " ".join(line.split())
            for ref in refs if ref in catalog and not (has_turns and ref == "transcript_text")
            for line in catalog[ref].splitlines() if line.strip()
        ]
        if any(not any(quote in excerpt for excerpt in excerpts) for quote in quotes):
            issues[field] = ["직접 인용이 연결된 원문과 일치하지 않습니다. 원문 표현과 인용 범위를 확인해주세요."]
    return issues


CLIENT_LINE = re.compile(
    r"^\s*(?:\[[^\]\r\n]+\]\s*|[A-Z]\d+\s+)?(?:내담자|client|Cl|C)\s*[:：]\s*(.*)$",
    re.IGNORECASE,
)
UNDERSTANDING_PROHIBITED = re.compile(
    r"때문\s*(?:이다|입니다|임)|성격\s*(?:이다|입니다|임)|장애|"
    r"우울증|조현병|조울증|자폐증|강박증|신경증|정신병|ADHD|PTSD|"
    r"depression|schizophrenia|bipolar|disorder|autism",
    re.IGNORECASE,
)
REACTION_WARNING = "내담자 반응 중 연결된 내담자 원문 한 줄과 정확히 일치하지 않는 인용을 제외했습니다."
UNDERSTANDING_WARNING = "내담자 이해에 진단명 또는 단정적 원인·성격 표현이 있습니다. 상담사가 확인해주세요."


def enforce_summary_v2(summary: SessionSummary, catalog: dict[str, str]) -> None:
    """Drop unsupported reaction lines; never rewrite a quote to make it match."""
    if not isinstance(summary, SessionSummaryV2):
        return
    reactions = summary.client_reactions
    retained = []
    for item in reactions.items:
        refs = item.source_refs
        original = catalog.get(refs[0], "") if len(refs) == 1 else ""
        speaker = CLIENT_LINE.fullmatch(original)
        if (len(refs) == 1 and re.fullmatch(r"transcript\.turn_[1-9]\d*", refs[0])
                and speaker and item.text.strip() and not re.search(r"[\r\n]", item.text)
                and item.text in speaker.group(1)):
            retained.append(item)
        else:
            reactions.requires_review = True
            if REACTION_WARNING not in summary.warnings:
                summary.warnings.append(REACTION_WARNING)
    reactions.items = retained
    reactions.requires_review |= len(retained) < 3
    for group in (summary.episodes, reactions):
        group.source_refs = list(dict.fromkeys(ref for item in group.items for ref in item.source_refs))
        group.requires_review |= not group.items or any(item.requires_review for item in group.items)
        types = {item.evidence_type for item in group.items}
        group.evidence_type = next(iter(types)) if len(types) == 1 else "mixed" if types else "needs_review"
    understanding = summary.client_understanding
    understanding.requires_review = True
    if understanding.evidence_type == "direct":
        understanding.evidence_type = "inferred"
    if UNDERSTANDING_PROHIBITED.search(understanding.text) and UNDERSTANDING_WARNING not in summary.warnings:
        summary.warnings.append(UNDERSTANDING_WARNING)


def _without_supporting_quotes(text: str) -> str:
    """Ignore brief quotations only when they are embedded in explanatory prose."""
    unquoted = QUOTED_TEXT.sub("", text)
    if len(re.sub(r"[\s.!?。]", "", unquoted)) < 8:
        return text
    return QUOTED_TEXT.sub(lambda match: "[인용]" if len(match.group()) <= 100 else match.group(), text)
