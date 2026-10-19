"""De-identify counseling text before it is saved: mask personal names and generalize occupations.

Rules (product decision, 2026-10-16):
- Names keep their first and last character and hide the middle: 홍길동 → 홍O동, 홍길동삼 → 홍OO삼,
  two-character names hide the second character (민지 → 민O).
- Occupations are replaced with a broad category that keeps the field but not the job, for example
  초등학교 교사 / 교수 → 교육자, 연예인 → 예술가.

Direct identifiers and known aliases are masked deterministically before any optional entity
extraction. External extraction is disabled by default. When an operator explicitly enables it,
the configured provider receives only that deterministic baseline and can identify remaining name
or occupation mentions. Saving never fails because of this optional step.
"""
from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.deidentification import deidentify_text, known_name_variants

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
_HIGH_CONFIDENCE_FREE_TEXT_OCCUPATIONS: dict[str, str] = {
    "초등학교 교사": "교육자",
    "중학교 교사": "교육자",
    "고등학교 교사": "교육자",
    "보육교사": "교육자",
    "간호사": "의료인",
    "약사": "의료인",
    "한의사": "의료인",
    "변호사": "법률 전문가",
    "법무사": "법률 전문가",
    "운동선수": "체육인",
    "공무원": "공공 부문 종사자",
    "소방관": "공공 부문 종사자",
    "직업군인": "공공 부문 종사자",
    "회사원": "사무직 종사자",
    "개발자": "IT·기술직 종사자",
    "프로그래머": "IT·기술직 종사자",
    "연구원": "연구자",
    "바리스타": "서비스직 종사자",
    "승무원": "서비스직 종사자",
    "대학생": "학생",
    "대학원생": "학생",
    "우주비행사": FALLBACK_OCCUPATION,
    "싱어송라이터": "예술가",
    "프로게이머": FALLBACK_OCCUPATION,
    "유명인": FALLBACK_OCCUPATION,
    "연예인": "예술가",
    "국회의원": "공공 부문 종사자",
    "외교관": "공공 부문 종사자",
}


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
    """Optionally extract residual mentions from a deterministically masked baseline."""
    if not settings.allow_external_storage_entity_extraction or settings.stub_mode or not text.strip():
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
        for value in known_name_variants(raw):
            if not is_masked_name(value) and re.fullmatch(r"[가-힣]{2,5}", value):
                names.add(value)
    return names


def _occupation_pattern(occupation: str) -> re.Pattern[str]:
    particles = r"은|는|이|가|을|를|과|와|로|으로|인|이며|이고|에서|에게|의|도|만|라고|라며"
    return re.compile(
        rf"(?<![가-힣]){re.escape(occupation)}(?P<particle>{particles})?(?=\s|[,.;!?]|$)"
    )


def _generalized_occupation(match: re.Match[str], category: str) -> str:
    particle = match.group("particle") or ""
    if particle in {"로", "으로"}:
        final_index = (ord(category[-1]) - 0xAC00) % 28 if category and "가" <= category[-1] <= "힣" else 0
        particle = "로" if final_index in {0, 8} else "으로"
    return category + particle


def _present_candidates(candidates: Iterable[str], text: str) -> set[str]:
    """Find literal candidates in one pass over text with an Aho-Corasick trie."""
    remaining = set(candidates)
    if not remaining or not text:
        return set()

    transitions: list[dict[str, int]] = [{}]
    failures = [0]
    outputs: list[set[str]] = [set()]
    for candidate in remaining:
        state = 0
        for character in candidate:
            next_state = transitions[state].get(character)
            if next_state is None:
                next_state = len(transitions)
                transitions[state][character] = next_state
                transitions.append({})
                failures.append(0)
                outputs.append(set())
            state = next_state
        outputs[state].add(candidate)

    queue = deque(transitions[0].values())
    while queue:
        state = queue.popleft()
        for character, next_state in transitions[state].items():
            queue.append(next_state)
            fallback = failures[state]
            while fallback and character not in transitions[fallback]:
                fallback = failures[fallback]
            failures[next_state] = transitions[fallback].get(character, 0)
            outputs[next_state].update(outputs[failures[next_state]])

    found: set[str] = set()
    state = 0
    for character in text:
        while state and character not in transitions[state]:
            state = failures[state]
        state = transitions[state].get(character, 0)
        if outputs[state]:
            found.update(outputs[state])
            if len(found) == len(remaining):
                break
    return found


def _name_trie(names: Iterable[str]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = [{"next": {}, "name": None}]
    for name in names:
        state = 0
        for character in name:
            transitions: dict[str, int] = nodes[state]["next"]
            state = transitions.setdefault(character, len(nodes))
            if state == len(nodes):
                nodes.append({"next": {}, "name": None})
        nodes[state]["name"] = name
    return nodes


def _longest_name_at(text: str, start: int, trie: list[dict[str, Any]]) -> str | None:
    first = text[start]
    korean = bool(_HANGUL.match(first))
    if korean:
        if start and _HANGUL.match(text[start - 1]):
            return None
    elif first.isascii() and first.isalpha():
        if start and text[start - 1].isascii() and text[start - 1].isalpha():
            return None
    else:
        return None

    state = 0
    longest: str | None = None
    index = start
    while index < len(text):
        next_state = trie[state]["next"].get(text[index])
        if next_state is None:
            break
        state = next_state
        index += 1
        name = trie[state]["name"]
        if name is not None and (
            korean
            or index == len(text)
            or not (text[index].isascii() and text[index].isalpha())
        ):
            longest = name
    return longest


def _mask_names_once(text: str, trie: list[dict[str, Any]]) -> tuple[str, int]:
    chunks: list[str] = []
    cursor = 0
    index = 0
    count = 0
    while index < len(text):
        name = _longest_name_at(text, index, trie)
        if name is None:
            index += 1
            continue
        end = index + len(name)
        chunks.extend((text[cursor:index], mask_name(name)))
        cursor = end
        index = end
        count += 1
    if not count:
        return text, 0
    chunks.append(text[cursor:])
    return "".join(chunks), count


def _mask_extracted_names(
    text: str,
    names: set[str],
    *,
    trie: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """Mask many extracted names with bounded scans while retaining legacy overlap behavior."""
    if not names or not text:
        return text, 0

    trie = trie or _name_trie(names)
    masked, count = _mask_names_once(text, trie)
    _, remaining = _mask_names_once(masked, trie)
    if not remaining:
        return masked, count

    # A replacement can expose an overlapping name (for example 가나다 + 다라). Keep the
    # established longest-first sequential behavior for that uncommon ambiguous case.
    masked = text
    count = 0
    for name in sorted(names, key=len, reverse=True):
        masked, matches = _name_pattern(name).subn(mask_name(name), masked)
        count += matches
    return masked, count


def _occupation_trie(occupations: Iterable[str]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = [{"next": {}, "occupation": None, "failure": 0, "output": None}]
    for occupation in occupations:
        state = 0
        for character in occupation:
            transitions: dict[str, int] = nodes[state]["next"]
            state = transitions.setdefault(character, len(nodes))
            if state == len(nodes):
                nodes.append({"next": {}, "occupation": None, "failure": 0, "output": None})
        nodes[state]["occupation"] = occupation

    queue = deque(nodes[0]["next"].values())
    while queue:
        state = queue.popleft()
        for character, next_state in nodes[state]["next"].items():
            queue.append(next_state)
            fallback = nodes[state]["failure"]
            while fallback and character not in nodes[fallback]["next"]:
                fallback = nodes[fallback]["failure"]
            nodes[next_state]["failure"] = nodes[fallback]["next"].get(character, 0)
            failure = nodes[next_state]["failure"]
            nodes[next_state]["output"] = (
                failure if nodes[failure]["occupation"] is not None else nodes[failure]["output"]
            )
    return nodes


def _occupation_matches(
    text: str,
    trie: list[dict[str, Any]],
) -> Iterable[tuple[int, int, str]]:
    state = 0
    for index, character in enumerate(text):
        while state and character not in trie[state]["next"]:
            state = trie[state]["failure"]
        state = trie[state]["next"].get(character, 0)
        output_state: int | None = state
        while output_state:
            occupation: str | None = trie[output_state]["occupation"]
            if occupation is not None:
                yield index - len(occupation) + 1, index + 1, occupation
            output_state = trie[output_state]["output"]


def _generalize_occupations_once(
    text: str,
    occupations: Mapping[str, str],
    trie: list[dict[str, Any]],
) -> tuple[str, int, bool, list[tuple[int, int, str]]]:
    chunks: list[str] = []
    cursor = 0
    selected_end = 0
    count = 0
    crossing_overlap = False
    selected: list[tuple[int, int, str]] = []
    for start, end, occupation in _occupation_matches(text, trie):
        if start < selected_end:
            crossing_overlap = True
            continue
        selected_end = end
        chunks.extend((text[cursor:start], occupations[occupation]))
        cursor = end
        count += 1
        selected.append((start, end, occupation))
    if not count:
        return text, 0, crossing_overlap, selected
    chunks.append(text[cursor:])
    return "".join(chunks), count, crossing_overlap, selected


def _introduces_later_occupation(
    text: str,
    occupations: Mapping[str, str],
    trie: list[dict[str, Any]],
    selected: list[tuple[int, int, str]],
) -> bool:
    if not selected:
        return False

    width = max(map(len, occupations))
    priority = {occupation: index for index, occupation in enumerate(occupations)}

    def rendered_occurrence(index: int, current_priority: int) -> str:
        occupation = selected[index][2]
        return occupations[occupation] if priority[occupation] <= current_priority else occupation

    for selected_index, (start, end, occupation) in enumerate(selected):
        current_priority = priority[occupation]
        remaining = width - 1
        left = ""
        position = start
        neighbor = selected_index - 1
        while remaining and position:
            gap_start = selected[neighbor][1] if neighbor >= 0 else 0
            piece = text[gap_start:position]
            take = piece[-remaining:]
            left = take + left
            remaining -= len(take)
            if remaining == 0 or neighbor < 0:
                break
            piece = rendered_occurrence(neighbor, current_priority)
            take = piece[-remaining:]
            left = take + left
            remaining -= len(take)
            position = selected[neighbor][0]
            neighbor -= 1

        remaining = width - 1
        right = ""
        position = end
        neighbor = selected_index + 1
        while remaining and position < len(text):
            gap_end = selected[neighbor][0] if neighbor < len(selected) else len(text)
            piece = text[position:gap_end]
            take = piece[:remaining]
            right += take
            remaining -= len(take)
            if remaining == 0 or neighbor >= len(selected):
                break
            piece = rendered_occurrence(neighbor, current_priority)
            take = piece[:remaining]
            right += take
            remaining -= len(take)
            position = selected[neighbor][1]
            neighbor += 1

        replacement = occupations[occupation]
        local = left + replacement + right
        replacement_start = len(left)
        replacement_end = replacement_start + len(replacement)
        for match_start, match_end, matched in _occupation_matches(local, trie):
            if (
                match_start < replacement_end
                and match_end > replacement_start
                and priority[matched] > current_priority
            ):
                return True
    return False


def _replacement_can_introduce_occupation(occupations: Mapping[str, str]) -> bool:
    candidate_characters = {
        character
        for occupation in occupations
        for character in occupation
    }
    return any(
        any(character in candidate_characters for character in category)
        for category in occupations.values()
    )


def _generalize_prioritized_occupations(
    text: str,
    occupations: Mapping[str, str],
    trie: list[dict[str, Any]],
) -> tuple[str, int] | None:
    """Resolve bounded overlaps by global priority when replacements cannot create later matches."""
    match_limit = max(len(text) * 2, len(occupations))
    matches: dict[str, list[tuple[int, int]]] = {occupation: [] for occupation in occupations}
    match_count = 0
    for start, end, occupation in _occupation_matches(text, trie):
        match_count += 1
        if match_count > match_limit:
            return None
        matches[occupation].append((start, end))

    prioritized = dict(sorted(occupations.items(), key=lambda item: len(item[0]), reverse=True))
    # A Fenwick tree keeps each overlap query logarithmic while selected spans cover at most
    # the original input once.
    coverage = [0] * (len(text) + 1)

    def covered(end: int) -> int:
        total = 0
        while end:
            total += coverage[end]
            end -= end & -end
        return total

    def mark(start: int, end: int) -> None:
        for position in range(start + 1, end + 1):
            index = position
            while index < len(coverage):
                coverage[index] += 1
                index += index & -index

    selected: list[tuple[int, int, str]] = []
    for occupation in prioritized:
        for start, end in matches[occupation]:
            if covered(end) != covered(start):
                continue
            selected.append((start, end, occupation))
            mark(start, end)

    if not selected:
        return text, 0

    selected.sort()
    max_width = len(next(iter(prioritized)))
    if len(selected) * max_width > max(len(text) * 4, len(occupations)):
        return None
    if _replacement_can_introduce_occupation(prioritized) and _introduces_later_occupation(
        text, prioritized, trie, selected
    ):
        return None

    chunks: list[str] = []
    cursor = 0
    for start, end, occupation in selected:
        chunks.extend((text[cursor:start], occupations[occupation]))
        cursor = end
    chunks.append(text[cursor:])
    generalized = "".join(chunks)
    if next(iter(_occupation_matches(generalized, trie)), None) is not None:
        return None
    return generalized, len(selected)


def _generalize_non_overlapping_occupations(
    text: str,
    occupations: Mapping[str, str],
    trie: list[dict[str, Any]],
) -> tuple[str, int] | None:
    """Apply all lengths together when replacements cannot make rule order observable."""
    chunks: list[str] = []
    cursor = 0
    selected_end = 0
    count = 0
    selected: list[tuple[int, int, str]] = []
    for start, end, occupation in _occupation_matches(text, trie):
        if start < selected_end:
            return None
        selected_end = end
        chunks.extend((text[cursor:start], occupations[occupation]))
        cursor = end
        count += 1
        selected.append((start, end, occupation))
    if not count:
        return text, 0

    chunks.append(text[cursor:])
    generalized = "".join(chunks)
    prioritized = dict(sorted(occupations.items(), key=lambda item: len(item[0]), reverse=True))
    if _replacement_can_introduce_occupation(prioritized) and _introduces_later_occupation(
        text, prioritized, trie, selected
    ):
        return None
    if next(iter(_occupation_matches(generalized, trie)), None) is not None:
        return None
    return generalized, count


def _generalize_extracted_occupations(
    text: str,
    occupations: Mapping[str, str],
    *,
    trie: list[dict[str, Any]] | None = None,
    groups: list[tuple[dict[str, str], list[dict[str, Any]]]] | None = None,
) -> tuple[str, int]:
    """Generalize occupations with bounded scans while retaining legacy cascade behavior."""
    if not occupations or not text:
        return text, 0

    trie = trie or _occupation_trie(occupations)
    generalized = _generalize_non_overlapping_occupations(text, occupations, trie)
    if generalized is not None:
        return generalized
    generalized = _generalize_prioritized_occupations(text, occupations, trie)
    if generalized is not None:
        return generalized

    if groups is None:
        by_length: dict[int, dict[str, str]] = {}
        for occupation, category in occupations.items():
            by_length.setdefault(len(occupation), {})[occupation] = category
        groups = [
            (group, _occupation_trie(group))
            for _, group in sorted(by_length.items(), reverse=True)
        ]

    total = 0
    for group, trie in groups:
        before_group = text
        generalized, count, crossing_overlap, selected = _generalize_occupations_once(text, group, trie)
        if crossing_overlap or _introduces_later_occupation(text, group, trie, selected):
            # A category can expose another candidate of the same length, and shifted overlaps
            # can make stable ordering significant. Preserve the sequential behavior for those
            # uncommon ambiguous cases.
            generalized = before_group
            count = 0
            for occupation in group:
                matches = generalized.count(occupation)
                if matches:
                    generalized = generalized.replace(occupation, group[occupation])
                    count += matches
        text = generalized
        total += count
    return text, total


def deidentify_texts(
    texts: Mapping[str, str],
    *,
    known_names: Iterable[str] = (),
) -> tuple[dict[str, str], StorageDeidentificationReport]:
    """Return the texts with names masked and occupations generalized, plus a value-free report."""
    names = _alias_names(known_names)
    names_masked = 0
    occupations_generalized = 0
    baseline: dict[str, str] = {}
    for key, value in texts.items():
        text = value or ""
        for occupation, category in _HIGH_CONFIDENCE_FREE_TEXT_OCCUPATIONS.items():
            text, count = _occupation_pattern(occupation).subn(
                lambda match, category=category: _generalized_occupation(match, category),
                text,
            )
            if count:
                occupations_generalized += count
        text = deidentify_text(text, source=key)[0]
        for name in sorted(names, key=len, reverse=True):
            text, count = _name_pattern(name).subn(mask_name(name), text)
            names_masked += count
        baseline[key] = text

    joined = "\n\n".join(f"[{key}]\n{value}" for key, value in baseline.items() if value and value.strip())
    entities = _extract_entities(joined)
    if entities is None:
        return baseline, StorageDeidentificationReport(
            llm_used=False,
            names_masked=names_masked,
            occupations_generalized=occupations_generalized,
        )

    name_candidates: set[str] = set()
    for name in entities.person_names:
        value = name.strip()
        if _NAME_TOKEN.match(value) and not is_masked_name(value):
            name_candidates.add(value)
    extracted_names = _present_candidates(name_candidates, joined)

    occupation_candidates: dict[str, str] = {}
    for mention in entities.occupations:
        value = mention.text.strip()
        if len(value) >= 2 and value not in OCCUPATION_CATEGORIES:
            occupation_candidates[value] = mention.category
    present_occupations = _present_candidates(occupation_candidates, joined)
    occupations = {value: occupation_candidates[value] for value in present_occupations}
    extracted_name_trie = _name_trie(extracted_names) if extracted_names else None
    occupations_by_length: dict[int, dict[str, str]] = {}
    for occupation, category in occupations.items():
        occupations_by_length.setdefault(len(occupation), {})[occupation] = category
    extracted_occupation_groups = [
        (group, _occupation_trie(group))
        for _, group in sorted(occupations_by_length.items(), reverse=True)
    ]
    extracted_occupation_trie = _occupation_trie(occupations) if occupations else None

    result: dict[str, str] = {}
    for key, text in baseline.items():
        # Longest first, so 김민지 is handled before 민지 and 초등학교 교사 before 교사.
        text, count = _generalize_extracted_occupations(
            text,
            occupations,
            trie=extracted_occupation_trie,
            groups=extracted_occupation_groups,
        )
        occupations_generalized += count
        text, count = _mask_extracted_names(text, extracted_names, trie=extracted_name_trie)
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
_CURATED_THEORY_SOURCE_URL = re.compile(
    r"^/result/relational_insights/theory_sources/\d+/url$"
)


def _is_structural_string(path: str, key: str) -> bool:
    child_path = f"{path}/{key}"
    return key in _STRUCTURAL_KEYS or bool(_CURATED_THEORY_SOURCE_URL.fullmatch(child_path))


def deidentify_json(value: Any, *, known_names: Iterable[str] = ()) -> tuple[Any, StorageDeidentificationReport]:
    """Apply deidentify_texts to every counseling-text string inside a JSON-like value."""
    strings: dict[str, str] = {}

    def collect(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                if not _is_structural_string(path, key):
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
            return {
                key: item if _is_structural_string(path, key) else rebuild(item, f"{path}/{key}")
                for key, item in node.items()
            }
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
