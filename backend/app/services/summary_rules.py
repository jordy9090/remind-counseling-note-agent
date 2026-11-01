"""Share only session-summary writing rules, without changing pipeline scope."""
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "session-summary" / "SKILL.md"
WRITING_RULES_HEADER = "## 공통 회기요약 작성 규칙"


def labeled_transcript(text: str) -> str:
    """Expose physical line IDs without duplicating or changing source wording."""
    return "\n".join(
        f"[transcript.turn_{index}] {line}" if line.strip() else line
        for index, line in enumerate(text.splitlines(), 1)
    )


def labeled_summary_input(sanitized) -> dict:
    """Annotate a copy for generation/verifying; storage and UI keep original text."""
    payload = sanitized.model_dump(mode="json")
    payload["sources"]["transcript_text"] = labeled_transcript(sanitized.sources.transcript_text)
    return payload


def session_summary_writing_rules() -> str:
    """Exclude the quick-only input contract from the regular summary prompt."""
    document = SKILL_PATH.read_text(encoding="utf-8")
    _, separator, rules = document.partition(WRITING_RULES_HEADER)
    if not separator or not rules.strip():
        raise ValueError("Session-summary writing rules are unavailable.")
    return rules.strip()
