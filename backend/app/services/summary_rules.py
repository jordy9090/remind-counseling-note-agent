"""Share only session-summary writing rules, without changing pipeline scope."""
from pathlib import Path


SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "session-summary" / "SKILL.md"
WRITING_RULES_HEADER = "## 공통 회기요약 작성 규칙"


def session_summary_writing_rules() -> str:
    """Exclude the quick-only input contract from the regular summary prompt."""
    document = SKILL_PATH.read_text(encoding="utf-8")
    _, separator, rules = document.partition(WRITING_RULES_HEADER)
    if not separator or not rules.strip():
        raise ValueError("Session-summary writing rules are unavailable.")
    return rules.strip()
