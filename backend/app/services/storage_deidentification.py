"""De-identify counseling text before it is saved: mask personal names and generalize occupations.

Rules (product decision, 2026-10-16):
- Names keep their first and last character and hide the middle: 홍길동 → 홍O동, 홍길동삼 → 홍OO삼,
  two-character names hide the second character (민지 → 민O).
- Occupations are replaced with a broad category that keeps the field but not the job, for example
  초등학교 교사 / 교수 → 교육자, 연예인 → 예술가.

Names and occupations in free text are found with the OpenAI model (structured output). The model
only returns the mentions; the replacement itself is deterministic and applies only to text that
actually occurs in the input. When the model is unavailable (stub mode, missing key, timeout, or
error), the deterministic fallback still masks the client alias and its given name and maps the
profile occupation field through a keyword table; other free-text names and occupations are then
left as they are and the report says so. Saving never fails because of this step.

The extraction request sends the text as entered to the model provider; the generation pipeline
afterwards receives the de-identified text.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import settings

NAME_MASK_CHAR = "O"
FALLBACK_OCCUPATION = "기타 직업군"

# Broad occupation groups: specific enough to keep the field, too broad to identify a person.
OCCUPATION_CATEGORIES: tuple[str, ...] = (
    "교육자",
    "의료인",
    "법률 전문가",
    "예술가",
    "체육인",
    "공공 부문 종사자",
    "사무직 종사자",
    "금융 종사자",
    "IT·기술직 종사자",
    "연구자",
    "자영업자",
    "서비스직 종사자",
    "생산·현장직 종사자",
    "농림어업 종사자",
    "종교인",
    "학생",
    "가사 종사자",
    "구직자·무직",
    FALLBACK_OCCUPATION,
)
OccupationCategory = Literal[
    "교육자", "의료인", "법률 전문가", "예술가", "체육인", "공공 부문 종사자", "사무직 종사자",
    "금융 종사자", "IT·기술직 종사자", "연구자", "자영업자", "서비스직 종사자", "생산·현장직 종사자",
    "농림어업 종사자", "종교인", "학생", "가사 종사자", "구직자·무직", "기타 직업군",
]

# Keyword table for the profile occupation field only (a whole field value, never free text, so
# words like 의사소통 cannot be hit). Longer keywords are checked first.
_OCCUPATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "교육자": ("교사", "교수", "강사", "교육자", "교직원", "보육교사", "유치원", "학원", "튜터", "선생님", "교원"),
    "의료인": ("의사", "간호", "약사", "한의사", "치과", "의료", "물리치료", "임상", "간병", "의사선생님"),
    "법률 전문가": ("변호사", "판사", "검사", "법무사", "노무사", "변리사", "법조"),
    "예술가": ("연예인", "가수", "배우", "작가", "화가", "디자이너", "음악", "작곡", "싱어송라이터", "예술", "유튜버",
             "크리에이터", "모델", "댄서", "무용", "사진작가", "웹툰", "연기자", "방송인"),
    "체육인": ("운동선수", "선수", "코치", "트레이너", "체육"),
    "공공 부문 종사자": ("공무원", "군인", "경찰", "소방", "공공기관", "공기업", "직업군인"),
    "사무직 종사자": ("회사원", "직장인", "사무직", "사무원", "회계", "인사팀", "마케터", "기획자", "영업"),
    "금융 종사자": ("은행", "증권", "보험설계", "금융"),
    "IT·기술직 종사자": ("개발자", "엔지니어", "프로그래머", "IT", "데이터"),
    "연구자": ("연구원", "연구자", "과학자"),
    "자영업자": ("자영업", "사장", "사업자", "창업", "대표"),
    "서비스직 종사자": ("서비스", "판매", "점원", "아르바이트", "알바", "요리", "조리", "바리스타", "미용", "상담원", "승무원"),
    "생산·현장직 종사자": ("생산", "공장", "건설", "현장", "기술자", "운전", "배달", "택배", "기사"),
    "농림어업 종사자": ("농업", "농부", "어업", "어부", "축산", "임업"),
    "종교인": ("목사", "신부", "스님", "수녀", "전도사", "종교"),
    "학생": ("학생", "대학생", "고등학생", "중학생", "초등학생", "대학원생", "수험생", "취준생"),
    "가사 종사자": ("주부", "가사", "전업"),
    "구직자·무직": ("무직", "구직", "백수", "실업", "휴직", "은퇴"),
}

_KEYWORDS_LONGEST_FIRST = sorted(
    ((keyword, category) for category, keywords in _OCCUPATION_KEYWORDS.items() for keyword in keywords),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

_HANGUL = re.compile(r"[가-힣]")
_NAME_TOKEN = re.compile(r"^[가-힣]{2,5}$|^[A-Za-z][A-Za-z.'-]{1,20}$")


def mask_name(name: str) -> str:
    """홍길동 → 홍O동, 홍길동삼 → 홍OO삼, 민지 → 민O; anything shorter than two characters is unchanged."""
    value = name.strip()
    if len(value) < 2:
        return value
    if len(value) == 2:
        return value[0] + NAME_MASK_CHAR
    return value[0] + NAME_MASK_CHAR * (len(value) - 2) + value[-1]


def is_masked_name(value: str) -> bool:
    return len(value) >= 2 and NAME_MASK_CHAR in value[1:]


def occupation_category(value: str | None) -> str | None:
    """Category for a profile occupation field; None stays None, unknown values become 기타 직업군."""
    text = (value or "").strip()
    if not text:
        return None
    if text in OCCUPATION_CATEGORIES:
        return text
    lowered = text.lower()
    for keyword, category in _KEYWORDS_LONGEST_FIRST:
        if keyword.lower() in lowered:
            return category
    return FALLBACK_OCCUPATION


class _OccupationMention(BaseModel):
    text: str = Field(description="The occupation exactly as written in the input, without particles.")
    category: OccupationCategory


class _StorageEntities(BaseModel):
    person_names: list[str] = Field(
        default_factory=list,
        description="Every personal name exactly as written (full names, given names, nicknames), without particles.",
    )
    occupations: list[_OccupationMention] = Field(default_factory=list)


_EXTRACTION_PROMPT = """You prepare Korean counseling records for storage. Find identifying mentions in the text below.

person_names: every name of a real person (client, family members, friends, counselor, any third party),
exactly as it appears. Include full names, given names and nicknames as separate entries (for example
"김민지" and "민지"). Remove trailing particles (민지가 → 민지, 철수는 → 철수). Do not include role words
(엄마, 선생님, 내담자, 상담사), placeholders such as [PERSON], or names already masked with "O" (홍O동).

occupations: every job or occupation of a person, exactly as written (for example "초등학교 교사",
"싱어송라이터", "간호사"), each with the broadest fitting category from the allowed list. Use
"기타 직업군" only when no other category fits. Do not include workplaces, school names or hobbies.

Return empty lists when there is nothing to report. Do not paraphrase; copy the mentions verbatim.

Text:
{text}
"""


@dataclass(frozen=True)
class StorageDeidentificationReport:
    llm_used: bool
    names_masked: int
    occupations_generalized: int


def _extract_entities(text: str) -> _StorageEntities | None:
    """Ask the model for name and occupation mentions; None when the model is unavailable."""
    if settings.stub_mode or not text.strip():
        return None
    try:
        from app.services.llm import get_structured_llm

        llm = get_structured_llm(_StorageEntities, timeout=min(settings.openai_timeout_seconds, 30))
        result = llm.invoke(_EXTRACTION_PROMPT.format(text=text))
        return result if isinstance(result, _StorageEntities) else _StorageEntities.model_validate(result)
    except Exception:
        # Never surface provider errors or input text; the deterministic fallback still applies.
        return None


def _name_pattern(name: str) -> re.Pattern[str]:
    # A Korean name starts a word: the preceding character must not be Hangul. Particles may follow.
    if _HANGUL.match(name):
        return re.compile(rf"(?<![가-힣]){re.escape(name)}")
    return re.compile(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])")


def _alias_names(known_names: Iterable[str]) -> set[str]:
    """Deterministic names: each known alias that looks like a personal name, plus its given name."""
    names: set[str] = set()
    for raw in known_names:
        value = (raw or "").strip()
        if not value or is_masked_name(value) or not re.fullmatch(r"[가-힣]{2,5}", value):
            continue
        names.add(value)
        if len(value) >= 3:
            names.add(value[1:])  # 김민지 → 민지
    return names


def deidentify_texts(
    texts: Mapping[str, str],
    *,
    known_names: Iterable[str] = (),
) -> tuple[dict[str, str], StorageDeidentificationReport]:
    """Return the texts with names masked and occupations generalized, plus a value-free report."""
    joined = "\n\n".join(f"[{key}]\n{value}" for key, value in texts.items() if value and value.strip())
    entities = _extract_entities(joined)
    names = _alias_names(known_names)
    occupations: dict[str, str] = {}
    if entities is not None:
        for name in entities.person_names:
            value = name.strip()
            if _NAME_TOKEN.match(value) and not is_masked_name(value) and value in joined:
                names.add(value)
        for mention in entities.occupations:
            value = mention.text.strip()
            if len(value) >= 2 and value in joined and value not in OCCUPATION_CATEGORIES:
                occupations[value] = mention.category

    names_masked = 0
    occupations_generalized = 0
    result: dict[str, str] = {}
    for key, value in texts.items():
        text = value or ""
        # Longest first, so 김민지 is handled before 민지 and 초등학교 교사 before 교사.
        for occupation in sorted(occupations, key=len, reverse=True):
            count = text.count(occupation)
            if count:
                text = text.replace(occupation, occupations[occupation])
                occupations_generalized += count
        for name in sorted(names, key=len, reverse=True):
            text, count = _name_pattern(name).subn(mask_name(name), text)
            names_masked += count
        result[key] = text
    return result, StorageDeidentificationReport(
        llm_used=entities is not None,
        names_masked=names_masked,
        occupations_generalized=occupations_generalized,
    )


# --- JSON payloads (confirmed notes, temporary drafts, supervision reports) ------------------------

# Keys whose string values are identifiers, enums or timestamps, never counseling text.
_STRUCTURAL_KEYS = frozenset({
    "id", "draft_id", "note_id", "case_id", "session_id", "saved_at", "created_at", "updated_at",
    "session_date", "screen", "type", "status", "reviewStatus", "evidenceStatus", "evidence_type",
    "final_document_type", "speaker", "turnId", "reportId", "caseId", "reportType", "mediaType", "kind",
    "language", "runtimeMode", "diarizationStatus", "lastAppliedMode", "contentKind", "source_type",
    "source_ref", "source_refs", "evidenceIds", "visible_section_ids", "selected_previous_session_ids",
    "appliedTargets", "confidence", "severity", "sectionId", "blockId", "reportDate", "sessionNumber",
    "workspace_note_id", "confirmation_status", "note_type", "field", "category",
})


def deidentify_json(value: Any, *, known_names: Iterable[str] = ()) -> tuple[Any, StorageDeidentificationReport]:
    """Apply deidentify_texts to every counseling-text string inside a JSON-like value."""
    strings: dict[str, str] = {}

    def collect(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if key not in _STRUCTURAL_KEYS:
                    collect(item, f"{path}/{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                collect(item, f"{path}/{index}")
        elif isinstance(node, str) and node.strip():
            strings[path] = node

    collect(value, "")
    if not strings:
        return value, StorageDeidentificationReport(llm_used=False, names_masked=0, occupations_generalized=0)
    replaced, report = deidentify_texts(strings, known_names=known_names)

    def rebuild(node: Any, path: str) -> Any:
        if isinstance(node, dict):
            return {key: item if key in _STRUCTURAL_KEYS else rebuild(item, f"{path}/{key}") for key, item in node.items()}
        if isinstance(node, list):
            return [rebuild(item, f"{path}/{index}") for index, item in enumerate(node)]
        if isinstance(node, str) and path in replaced:
            return replaced[path]
        return node

    return rebuild(value, ""), report


# --- Storage entry points ----------------------------------------------------------------------

SESSION_TEXT_FIELDS = (
    "client_alias",
    "counselor_name",
    "counselor_memo",
    "transcript_text",
    "previous_session_summary",
    "counseling_goal",
    "psychological_test_summary",
    "nonverbal_notes",
)


def deidentify_session_input(session_input):
    """Session input with names masked and occupations generalized in every free-text field and tag."""
    texts = {field: getattr(session_input, field) or "" for field in SESSION_TEXT_FIELDS}
    tags = list(session_input.key_issue_tags or [])
    texts.update({f"key_issue_tags/{index}": tag for index, tag in enumerate(tags)})
    replaced, report = deidentify_texts(
        texts, known_names=[session_input.client_alias or "", session_input.counselor_name or ""],
    )
    update = {field: replaced[field] for field in SESSION_TEXT_FIELDS}
    update["key_issue_tags"] = [replaced[f"key_issue_tags/{index}"] for index in range(len(tags))]
    return session_input.model_copy(update=update), report


def deidentify_case_profile(
    *,
    case_alias: str | None,
    client_occupation: str | None,
    client_notes: str | None,
) -> tuple[str | None, str | None, str | None, StorageDeidentificationReport]:
    """Client name and notes masked; the occupation field becomes its broad category."""
    texts = {"case_alias": case_alias or "", "client_occupation": client_occupation or "", "client_notes": client_notes or ""}
    known = [case_alias or ""]
    entities_texts, report = deidentify_texts(texts, known_names=known)
    alias = entities_texts["case_alias"] if case_alias is not None else None
    notes = entities_texts["client_notes"] if client_notes is not None else None
    occupation = None
    if client_occupation is not None:
        # The model may already have replaced the whole field with a category; otherwise use the table.
        occupation = occupation_category(entities_texts["client_occupation"])
    return alias, occupation, notes, report
