"""De-identify counseling documents before they are saved or exported.

What is replaced (product decision 2026-10-16, extended 2026-10-22 after reviewing the sources below):
- Personal names keep the first and last character: 홍길동 → 홍O동, 홍길동삼 → 홍OO삼, 민지 → 민O.
- Occupations become one of the broad categories below (초등학교 교사 → 교육자, 연예인 → 예술가).
- Names of schools, workplaces, hospitals and other organizations become their type (OO고등학교 → 고등학교).
- A person's current age becomes a 10-year band (28세 → 20대, 80세 이상 top-coded); school grades become
  the school level (고2 → 고등학생).
- Specific places of residence, work or study (addresses, neighborhoods, apartment names) → [지역].
- Birth dates → [생년월일]; phone numbers, e-mail, accounts/URLs, resident or student numbers and
  street addresses → the existing counselor-readable "비공개" labels.

Sources: 개인정보 보호법 제2조 제1호 나목 (information identifiable when easily combined with other
information is personal information); 개인정보보호위원회 「가명정보 처리 가이드라인」(2024.2) — text data:
names, addresses, phone numbers and context-identifying information are deleted or replaced (p.55),
identifiable-in-combination information is judged in context (p.48), ages are generalized to 10-year
bands with top coding and addresses to 시군구 level (pp.29-32), character data is categorized to a
higher concept (p.94); 한국상담심리학회 상담심리사 윤리규정 5-가-4, 5-가-5, 5-마-1, 7-라-6 (no
identifiable client information in reports, lectures or consultations; change or delete personal
details for education, research and publication).

Mentions in free text are found with the OpenAI model (structured output). The model only returns the
mentions; replacement is deterministic and applies only to text that occurs in the input. Contact
details, explicit ages ("(28세)", "나이: 28") and school grades are also handled by regular expressions.
When the model is unavailable (stub mode, missing key, timeout, or error), the deterministic rules still
apply and the client alias and its given name are masked; other free-text mentions then stay unchanged
and the report says so. Saving never fails because of this step.

The extraction request sends the text as entered to the model provider; the generation pipeline
afterwards receives the de-identified text. Sensitive content that is the subject of counseling
(health, sexual life, beliefs; 개인정보 보호법 제23조) is not removed, because it is the record itself.
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


OrganizationKind = Literal[
    "초등학교", "중학교", "고등학교", "대학교", "대학원", "학원", "회사", "병원", "상담기관", "공공기관",
    "종교기관", "군부대", "기관",
]
AgeBand = Literal["10세 미만", "10대", "20대", "30대", "40대", "50대", "60대", "70대", "80세 이상"]


class _OrganizationMention(BaseModel):
    text: str = Field(description="The organization's proper name exactly as written, without particles.")
    kind: OrganizationKind


class _AgeMention(BaseModel):
    text: str = Field(description="The age expression exactly as written, for example '28세' or '스물여덟 살'.")
    band: AgeBand


class _StorageEntities(BaseModel):
    person_names: list[str] = Field(
        default_factory=list,
        description="Every personal name exactly as written (full names, given names, nicknames), without particles.",
    )
    occupations: list[_OccupationMention] = Field(default_factory=list)
    organizations: list[_OrganizationMention] = Field(default_factory=list)
    ages: list[_AgeMention] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    birth_dates: list[str] = Field(default_factory=list)


_EXTRACTION_PROMPT = """You prepare Korean counseling records for storage. Find identifying mentions in the text below.
Copy every mention verbatim, without particles. Return empty lists when there is nothing to report.

person_names: every name of a real person (client, family members, friends, counselor, any third party).
Include full names, given names and nicknames as separate entries (for example "김민지" and "민지").
Remove trailing particles (민지가 → 민지). Do not include role words (엄마, 선생님, 내담자, 상담사),
placeholders such as [PERSON], or names already masked with "O" (홍O동).

occupations: every job or occupation of a person (for example "초등학교 교사", "싱어송라이터", "간호사"),
each with the broadest fitting category from the allowed list. Use "기타 직업군" only when no other
category fits. Do not include workplaces, school names or hobbies.

organizations: proper names of schools, academies, companies, hospitals, counseling centers, public
offices, churches/temples, military units or other organizations a person belongs to (for example
"가상고등학교", "한빛전자", "서울OO병원"), each with its kind. Do not include generic words such as
"학교" or "회사" without a proper name.

ages: expressions of a person's current age (for example "28세", "만 28세", "스물여덟 살"), each with its
10-year band. Do not include ages that describe when a past event happened ("7살 때").

locations: specific places that point to where a person lives, works or studies: street addresses,
neighborhoods (동, 읍, 면), apartment or building names, nearby stations or landmarks. Do not include
countries, provinces or large cities (서울, 부산, 경기도).

birth_dates: birth dates or birthdays of a person.

Text:
{text}
"""


@dataclass(frozen=True)
class StorageDeidentificationReport:
    llm_used: bool
    names_masked: int
    occupations_generalized: int
    organizations_generalized: int = 0
    ages_generalized: int = 0
    locations_masked: int = 0
    birth_dates_masked: int = 0
    contacts_masked: int = 0


LOCATION_LABEL = "[지역]"
BIRTH_DATE_LABEL = "[생년월일]"
_CONTACT_CATEGORIES = frozenset({"email", "url_or_account", "resident_registration_number", "student_id", "phone", "address"})
_EXPLICIT_AGE_PATTERNS = (
    re.compile(r"\(\s*만?\s*(\d{1,3})\s*세\s*\)"),
    re.compile(r"(?:나이|연령)\s*[:：]?\s*만?\s*(\d{1,3})(?:\s*(?:세|살))?"),
)
_GRADE_PATTERNS = (
    (re.compile(r"(?<![가-힣])(?:초등학교\s*[1-6]\s*학년|초\s?[1-6](?![0-9]))"), "초등학생"),
    (re.compile(r"(?<![가-힣])(?:중학교\s*[1-3]\s*학년|중\s?[1-3](?![0-9]))"), "중학생"),
    (re.compile(r"(?<![가-힣])(?:고등학교\s*[1-3]\s*학년|고\s?[1-3](?![0-9]))"), "고등학생"),
    (re.compile(r"(?<![가-힣])대학교?\s*[1-6]\s*학년"), "대학생"),
)


def age_band(age: int) -> str:
    """10-year band with top and bottom coding (가명정보 처리 가이드라인 p.32)."""
    if age < 10:
        return "10세 미만"
    if age >= 80:
        return "80세 이상"
    return f"{age // 10 * 10}대"


def _extract_entities(text: str) -> _StorageEntities | None:
    """Ask the model for identifying mentions; None when the model is unavailable."""
    if settings.stub_mode or not text.strip():
        return None
    try:
        from app.services.llm import get_structured_llm

        llm = get_structured_llm(_StorageEntities, timeout=min(settings.openai_timeout_seconds, 30))
        result = llm.invoke(_EXTRACTION_PROMPT.format(text=text))
        return result if isinstance(result, _StorageEntities) else _StorageEntities.model_validate(result)
    except Exception:
        # Never surface provider errors or input text; the deterministic rules still apply.
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


def _mask_contacts(text: str) -> tuple[str, int]:
    from app.services.deidentification import COUNSELOR_PLACEHOLDER_LABELS, MASK_RULES

    count = 0
    for rule in MASK_RULES:
        if rule.category in _CONTACT_CATEGORIES:
            label = COUNSELOR_PLACEHOLDER_LABELS.get(rule.placeholder, "비식별 처리됨")
            text, hits = rule.pattern.subn(label, text)
            count += hits
    return text, count


def _replace_all(text: str, mapping: Mapping[str, str]) -> tuple[str, int]:
    """Replace each mention with its label, longest mentions first."""
    count = 0
    for mention in sorted(mapping, key=len, reverse=True):
        hits = text.count(mention)
        if hits:
            text = text.replace(mention, mapping[mention])
            count += hits
    return text, count


def _generalize_explicit_ages(text: str) -> tuple[str, int]:
    """"(28세)" → "(20대)", "나이: 28세" → "나이: 20대"."""
    parenthesized, labeled = _EXPLICIT_AGE_PATTERNS
    text, first = parenthesized.subn(lambda match: f"({age_band(int(match.group(1)))})", text)

    def keep_label(match: re.Match[str]) -> str:
        prefix = match.group(0)[: match.start(1) - match.start(0)]
        return prefix + age_band(int(match.group(1)))

    text, second = labeled.subn(keep_label, text)
    return text, first + second


def _generalize_grades(text: str) -> tuple[str, int]:
    count = 0
    for pattern, label in _GRADE_PATTERNS:
        text, hits = pattern.subn(label, text)
        count += hits
    return text, count


def deidentify_texts(
    texts: Mapping[str, str],
    *,
    known_names: Iterable[str] = (),
) -> tuple[dict[str, str], StorageDeidentificationReport]:
    """Return the texts with identifying details replaced, plus a value-free report."""
    joined = "\n\n".join(f"[{key}]\n{value}" for key, value in texts.items() if value and value.strip())
    entities = _extract_entities(joined)
    names = _alias_names(known_names)
    occupations: dict[str, str] = {}
    organizations: dict[str, str] = {}
    ages: dict[str, str] = {}
    locations: dict[str, str] = {}
    birth_dates: dict[str, str] = {}
    if entities is not None:
        def present(value: str, minimum: int = 2) -> bool:
            return len(value) >= minimum and value in joined

        for name in entities.person_names:
            value = name.strip()
            if _NAME_TOKEN.match(value) and not is_masked_name(value) and value in joined:
                names.add(value)
        for mention in entities.occupations:
            value = mention.text.strip()
            if present(value) and value not in OCCUPATION_CATEGORIES:
                occupations[value] = mention.category
        for mention in entities.organizations:
            value = mention.text.strip()
            if present(value) and value != mention.kind:
                organizations[value] = mention.kind
        for mention in entities.ages:
            value = mention.text.strip()
            digits = re.search(r"\d{1,3}", value)
            if present(value):
                ages[value] = age_band(int(digits.group(0))) if digits else mention.band
        for value in (item.strip() for item in entities.locations):
            if present(value):
                locations[value] = LOCATION_LABEL
        for value in (item.strip() for item in entities.birth_dates):
            if present(value, 4):
                birth_dates[value] = BIRTH_DATE_LABEL

    totals = dict.fromkeys(("names", "occupations", "organizations", "ages", "locations", "birth_dates", "contacts"), 0)
    result: dict[str, str] = {}
    for key, value in texts.items():
        text = value or ""
        text, totals["contacts"] = _accumulate(totals["contacts"], _mask_contacts(text))
        text, totals["birth_dates"] = _accumulate(totals["birth_dates"], _replace_all(text, birth_dates))
        text, totals["locations"] = _accumulate(totals["locations"], _replace_all(text, locations))
        # Organizations before names and occupations: a proper name may contain either.
        text, totals["organizations"] = _accumulate(totals["organizations"], _replace_all(text, organizations))
        text, totals["occupations"] = _accumulate(totals["occupations"], _replace_all(text, occupations))
        text, totals["ages"] = _accumulate(totals["ages"], _replace_all(text, ages))
        text, totals["ages"] = _accumulate(totals["ages"], _generalize_explicit_ages(text))
        text, totals["ages"] = _accumulate(totals["ages"], _generalize_grades(text))
        for name in sorted(names, key=len, reverse=True):
            text, count = _name_pattern(name).subn(mask_name(name), text)
            totals["names"] += count
        result[key] = text
    return result, StorageDeidentificationReport(
        llm_used=entities is not None,
        names_masked=totals["names"],
        occupations_generalized=totals["occupations"],
        organizations_generalized=totals["organizations"],
        ages_generalized=totals["ages"],
        locations_masked=totals["locations"],
        birth_dates_masked=totals["birth_dates"],
        contacts_masked=totals["contacts"],
    )


def _accumulate(total: int, replaced: tuple[str, int]) -> tuple[str, int]:
    text, count = replaced
    return text, total + count


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
    # Source references (e.g. literature links in relational insights), not counseling text.
    "url", "href", "locator",
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


def deidentify_export_request(request):
    """An export request with names and other identifying details replaced in every document field.

    The editor keeps what the counselor typed; the downloaded document is de-identified.
    """
    metadata = dict(request.metadata or {})
    known = [str(metadata.get(key) or "") for key in ("client_alias", "counselor_name", "supervisor")]
    payload = {
        "title": request.title,
        "metadata": metadata,
        "sections": [section.model_dump() for section in request.sections],
    }
    replaced, _ = deidentify_json(payload, known_names=known)
    for key in ("client_alias", "counselor_name", "supervisor"):
        value = str(replaced["metadata"].get(key) or "").strip()
        if value and re.fullmatch(r"[가-힣]{2,5}", value):
            replaced["metadata"][key] = mask_name(value)
    return request.model_copy(update={
        "title": replaced["title"],
        "metadata": replaced["metadata"],
        "sections": [type(request.sections[0]).model_validate(item) for item in replaced["sections"]] if request.sections else [],
    })
