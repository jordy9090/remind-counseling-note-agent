"""Share only session-summary writing rules, without changing pipeline scope."""
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "session-summary" / "SKILL.md"
WRITING_RULES_HEADER = "## 공통 회기요약 작성 규칙"
V2_RULES_HEADER = "## 회기요약 v2 작성 규칙"
V2_RULES_END = "<!-- END SUMMARY V2 -->"


def summary_skill_instructions(document: str, version: str = "v1") -> str:
    """Select versioned instructions without altering the legacy prompt body."""
    body = document.split("---", 2)[2].strip()
    legacy, separator, v2 = body.partition(V2_RULES_HEADER)
    v2, _, shared_tail = v2.partition(V2_RULES_END)
    if version == "v2":
        if not separator or not v2.strip():
            raise ValueError("Session-summary v2 writing rules are unavailable.")
        return (v2.rstrip() + shared_tail).strip()
    return (legacy.rstrip() + shared_tail).strip()


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
    _, separator, rules = summary_skill_instructions(document).partition(WRITING_RULES_HEADER)
    if not separator or not rules.strip():
        raise ValueError("Session-summary writing rules are unavailable.")
    return rules.strip()
