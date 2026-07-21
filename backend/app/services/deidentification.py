"""Deterministic deidentification helpers for storage and embedding boundaries."""
from __future__ import annotations

import re
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
        re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b"),
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
        re.compile(r"(?:\b01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}\b|\b\d{2,3}[-.\s]?\d{3,4}[-.\s]?\d{4}\b)"),
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
        "person_name",
        "[PERSON]",
        re.compile(r"(?:이름|성명|내담자|학생|담임|보호자|어머니|아버지)\s*[:은는이가]?\s*([가-힣]{2,4})"),
        "Explicit names should be replaced with aliases.",
    ),
]


def deidentify_text(text: str, source: str = "") -> tuple[str, list[SensitiveInfoCandidate]]:
    """Mask supported PII patterns and return review candidates.

    Candidate text intentionally contains placeholders rather than raw PII so
    persisted sanitized payloads and retrieval logs do not retain identifiers.
    """
    masked = text or ""
    candidates: list[SensitiveInfoCandidate] = []
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


def deidentify_sources(sources: dict[str, str]) -> tuple[dict[str, str], list[SensitiveInfoCandidate]]:
    masked_sources: dict[str, str] = {}
    candidates: list[SensitiveInfoCandidate] = []
    for source, text in sources.items():
        masked, found = deidentify_text(text, source=source)
        masked_sources[source] = masked
        candidates.extend(found)
    return masked_sources, candidates
