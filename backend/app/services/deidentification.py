"""Deterministic deidentification helpers for storage and embedding boundaries."""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.schemas.note import SensitiveInfoCandidate


@dataclass(frozen=True)
class MaskRule:
    category: str
    placeholder: str
    pattern: re.Pattern[str]
    recommendation: str


MASK_RULES = [
    MaskRule(
        "email",
        "[EMAIL]",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
        "Review whether email addresses are needed; store a client alias when possible.",
    ),
    MaskRule(
        "url_or_account",
        "[ACCOUNT]",
        re.compile(r"(?:https?://\S+|@[A-Za-z0-9_.-]{3,}|(?:카톡|계정|아이디|ID)\s*[:=]?\s*[A-Za-z0-9_.-]{3,})"),
        "Remove account identifiers and URLs unless there is a documented purpose.",
    ),
    MaskRule(
        "resident_registration_number",
        "[RRN]",
        re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)"),
        "Resident-registration-number-like values must not be stored in counseling notes.",
    ),
    MaskRule(
        "student_id",
        "[STUDENT_ID]",
        re.compile(r"(?:학번|학생번호|student\s*id)\s*[:#-]?\s*\d{6,12}", re.IGNORECASE),
        "Student IDs should be removed or replaced with a case alias.",
    ),
    MaskRule(
        "phone",
        "[PHONE]",
        re.compile(r"(?<!\d)(?:01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}|\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4})(?!\d)"),
        # Digit lookarounds instead of \b: Korean particles ("010-...로") are word characters.
        "Replace phone numbers with a placeholder before storage.",
    ),
    MaskRule(
        "address",
        "[ADDRESS]",
        re.compile(
            r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)[^\n,.]{0,30}"
            r"(?:시|군|구)[^\n,.]{0,40}(?:동|로|길|번지|아파트|빌라)"
        ),
        "Addresses should be generalized unless essential for the counseling purpose.",
    ),
    MaskRule(
        "institution",
        "[INSTITUTION]",
        re.compile(r"[가-힣A-Za-z0-9]{2,30}(?:초등학교|중학교|고등학교|대학교|대학원|병원|센터|상담소|회사|기관)"),
        "Institution names can re-identify a client; review and generalize them.",
    ),
    MaskRule(
        "occupation",
        "[OCCUPATION]",
        re.compile(
            r"(?<![가-힣])(?:초등학교\s+교사|중학교\s+교사|고등학교\s+교사|보육교사|간호사|약사|한의사|"
            r"변호사|법무사|운동선수|공무원|소방관|직업군인|회사원|개발자|프로그래머|연구원|바리스타|"
            r"승무원|대학생|대학원생)"
            r"(?=(?:은|는|이|가|을|를|과|와|로|으로|인|이며|이고|에서|에게|의|도|만|라고|라며)?"
            r"(?:\s|[,.;!?]|$))"
        ),
        "Occupations can re-identify a client; generalize them before external processing.",
    ),
    MaskRule(
        "rare_occupation",
        "[OCCUPATION]",
        re.compile(r"(?:우주비행사|싱어송라이터|프로게이머|유명인|연예인|국회의원|외교관)"),
        "Rare occupations can re-identify a client; generalize them before external processing.",
    ),
    MaskRule(
        "specific_event",
        "[UNIQUE_EVENT]",
        re.compile(
            r"[가-힣A-Za-z0-9]{2,40}(?:대회|공모전|올림피아드)[^\n,.]{0,40}"
            r"(?:수상|입상|금메달|은메달|동메달|최우수상|우승)"
        ),
        "Distinctive events can re-identify a client; remove unnecessary event detail.",
    ),
    MaskRule(
        "person_name",
        "[PERSON]",
        # Role nouns such as "내담자는 예정된 시간에..." are ordinary
        # counseling prose, not name labels.  Only explicit identity labels or
        # role + name constructions are masked here.
        re.compile(
            r"(?:(?:이름|성명)\s*[:은는이가]?\s*[가-힣]{2,4}|"
            r"(?:학생|담임|보호자|어머니|아버지)\s*[:은는이가]\s*[가-힣]{2,4}(?=\s*(?:님|씨|$|[,.;])))"
        ),
        "Explicit names should be replaced with aliases.",
    ),
]

_CONTEXTUAL_PERSON_NAME = re.compile(
    r"(?P<role>친구|동생|형|누나|언니|오빠|어머니|아버지|엄마|아빠|배우자|남편|아내|동료|상사|담임|보호자)"
    r"(?P<spacing>\s+)(?P<name>[가-힣]{2,4}?)"
    r"(?=(?:은|는|이|가|을|를|과|와|에게|한테|씨|님)?(?:[^가-힣]|$))"
)
_GENERIC_PERSON_LABELS = frozenset({
    "내담자", "상담자", "상담사", "상담", "보호자", "어머니", "아버지", "엄마", "아빠", "선생님",
    "client", "counselor",
})
_CONTEXTUAL_NON_NAMES = frozenset({
    "가정", "갈등", "고민", "관계", "대화", "도움", "문제", "반응", "상담", "상태", "생각",
    "소식", "약속", "연락", "이야기", "직장", "표현", "학교", "행동", "계획",
})


COUNSELOR_PLACEHOLDER_LABELS = {
    "[PERSON]": "내담자",
    "[NAME]": "내담자",
    "[CLIENT]": "내담자",
    "[COUNSELOR]": "상담자",
    "[LOCATION]": "장소 정보 비공개",
    "[ADDRESS]": "장소 정보 비공개",
    "[INSTITUTION]": "기관 정보 비공개",
    "[OCCUPATION]": "직업 정보 비공개",
    "[UNIQUE_EVENT]": "구체적 사건 정보 비공개",
    "[EMAIL]": "연락처 정보 비공개",
    "[PHONE]": "연락처 정보 비공개",
    "[ACCOUNT]": "계정 정보 비공개",
    "[RRN]": "식별정보 비공개",
    "[STUDENT_ID]": "식별정보 비공개",
    "[REDACTED]": "비식별 처리됨",
}


def render_counselor_text(text: str, *, client_alias: str = "") -> str:
    """Render internal privacy tokens into counselor-readable Korean labels."""
    rendered = text or ""
    person_label = client_alias.strip() or "내담자"
    particle_pairs = {
        "은": ("은", "는"),
        "는": ("은", "는"),
        "이": ("이", "가"),
        "가": ("이", "가"),
        "을": ("을", "를"),
        "를": ("을", "를"),
        "과": ("과", "와"),
        "와": ("과", "와"),
    }
    person_labels = {
        "[PERSON]": person_label,
        "[NAME]": person_label,
        "[CLIENT]": person_label,
        "[COUNSELOR]": "상담자",
    }
    for placeholder, replacement in person_labels.items():
        for supplied, (with_final, without_final) in particle_pairs.items():
            rendered = rendered.replace(
                placeholder + supplied,
                replacement + (with_final if _has_final_consonant(replacement) else without_final),
            )
    for placeholder, label in COUNSELOR_PLACEHOLDER_LABELS.items():
        rendered = rendered.replace(
            placeholder,
            person_labels.get(placeholder, label),
        )
    return rendered


def _has_final_consonant(value: str) -> bool:
    if not value:
        return False
    code = ord(value[-1])
    return 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0


def render_counselor_value(value, *, client_alias: str = ""):
    """Recursively render strings while preserving JSON-compatible shapes."""
    if isinstance(value, str):
        return render_counselor_text(value, client_alias=client_alias)
    if isinstance(value, dict):
        return {
            key: render_counselor_value(item, client_alias=client_alias)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [render_counselor_value(item, client_alias=client_alias) for item in value]
    if isinstance(value, tuple):
        return tuple(render_counselor_value(item, client_alias=client_alias) for item in value)
    return value


def deidentify_text(text: str, source: str = "") -> tuple[str, list[SensitiveInfoCandidate]]:
    """Mask supported PII patterns and return review candidates.

    Candidate text intentionally contains placeholders rather than raw PII so
    persisted sanitized payloads and retrieval logs do not retain identifiers.
    """
    masked = text or ""
    candidates: list[SensitiveInfoCandidate] = []
    contextual_name_count = 0

    def replace_contextual_name(match: re.Match[str]) -> str:
        nonlocal contextual_name_count
        if match.group("name") in _CONTEXTUAL_NON_NAMES:
            return match.group(0)
        contextual_name_count += 1
        return f"{match.group('role')}{match.group('spacing')}[PERSON]"

    masked = _CONTEXTUAL_PERSON_NAME.sub(replace_contextual_name, masked)
    if contextual_name_count:
        candidates.append(
            SensitiveInfoCandidate(
                text="[PERSON]",
                source=source,
                category="person_name",
                recommendation="Explicit names should be replaced with aliases.",
            )
        )
    for rule in MASK_RULES:
        seen_in_rule = False

        def replace(match: re.Match[str]) -> str:
            nonlocal seen_in_rule
            seen_in_rule = True
            return rule.placeholder

        masked = rule.pattern.sub(replace, masked)
        if seen_in_rule:
            candidates.append(
                SensitiveInfoCandidate(
                    text=rule.placeholder,
                    source=source,
                    category=rule.category,
                    recommendation=rule.recommendation,
                )
            )
    return masked, candidates


def known_name_variants(raw_name: str) -> set[str]:
    """Return safe-to-mask variants for an explicitly supplied personal name or alias."""
    value = (raw_name or "").strip()
    if len(value) < 2 or value.casefold() in _GENERIC_PERSON_LABELS:
        return set()
    variants = {value}
    if re.fullmatch(r"[가-힣]{3,5}", value):
        given_name = value[1:]
        if given_name not in _GENERIC_PERSON_LABELS:
            variants.add(given_name)
    return variants


def mask_known_names(text: str, replacements: Mapping[str, str]) -> str:
    """Replace explicitly supplied names before material reaches an external processor."""
    masked = text or ""
    variants = {
        variant: placeholder
        for raw_name, placeholder in replacements.items()
        for variant in known_name_variants(raw_name)
    }
    for variant in sorted(variants, key=len, reverse=True):
        if re.fullmatch(r"[가-힣]{2,5}", variant):
            particles = r"은|는|이|가|을|를|과|와|에게|한테|씨|님|의|도|만"
            pattern = re.compile(
                rf"(?<![가-힣]){re.escape(variant)}(?=(?:{particles})?(?:[^가-힣]|$))"
            )
        else:
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(variant)}(?![A-Za-z0-9])", re.IGNORECASE)
        masked = pattern.sub(variants[variant], masked)
    return masked


def deidentify_sources(
    sources: dict[str, str],
    *,
    known_name_replacements: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], list[SensitiveInfoCandidate]]:
    masked_sources: dict[str, str] = {}
    candidates: list[SensitiveInfoCandidate] = []
    for source, text in sources.items():
        masked, found = deidentify_text(text, source=source)
        masked_sources[source] = mask_known_names(masked, known_name_replacements or {})
        candidates.extend(found)
    return masked_sources, candidates
