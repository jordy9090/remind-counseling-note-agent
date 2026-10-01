"""Conservative checks for dialogue dumps in counselor-facing session summaries."""
from __future__ import annotations

import re

from app.schemas.note import SessionSummaryDraft


class SummaryQualityError(ValueError):
    """A bounded rewrite could not produce a usable summary; contains no source text."""

    def __init__(self) -> None:
        super().__init__("회기요약을 충분히 정리하지 못했습니다. 잠시 후 다시 생성해주세요. 입력 자료는 유지됩니다.")


# These are rejection ceilings, not required lengths. Sparse evidence stays short.
SECTION_LIMITS = {
    "presenting_problem": (450, 4),
    "session_theme": (350, 3),
    "session_content": (1400, 8),
    "counselor_intervention": (800, 5),
    "client_response": (800, 5),
    "reflection": (800, 5),
    "next_plan": (600, 4),
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


def summary_quality_issues(summary: SessionSummaryDraft) -> dict[str, list[str]]:
    """Return field-only feedback without retaining or emitting counseling text."""
    issues: dict[str, list[str]] = {}
    for field_name, (max_chars, max_sentences) in SECTION_LIMITS.items():
        text = getattr(summary, field_name).text.strip()
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


def _without_supporting_quotes(text: str) -> str:
    """Ignore brief quotations only when they are embedded in explanatory prose."""
    unquoted = QUOTED_TEXT.sub("", text)
    if len(re.sub(r"[\s.!?。]", "", unquoted)) < 8:
        return text
    return QUOTED_TEXT.sub(lambda match: "[인용]" if len(match.group()) <= 100 else match.group(), text)
