"""Items for the pre-generation review step ("AI로 보내기 전 내용을 확인해주세요").

Uses the same local discovery as storage de-identification, but returns
(original → replacement) items for the counselor to review instead of
rewriting the text. Replacement wording follows the review screen design:
the client is "내담자 A", other people "인물 B", "인물 C", ...

The input text is never stored or logged.
"""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field
from app.services.korean_person_names import discover_person_names, given_name, name_pattern

from app.services.storage_deidentification import (
    _NAME_TOKEN,
    OCCUPATION_CATEGORIES,
    _extract_entities,
    age_band,
    is_masked_name,
)

PREVIEW_MAX_CHARS = 200_000
CLIENT_LABEL = "내담자 A"
COUNSELOR_LABEL = "상담자"
LOCATION_LABEL = "지역"
BIRTH_DATE_LABEL = "생년월일"
# Rate limits for the preview are looser than the summary: the review modal can be reopened.
ANONYMOUS_PREVIEW_LIMIT = (20, 60 * 60)
AUTHENTICATED_PREVIEW_LIMIT = (200, 60 * 60)

PreviewCategory = Literal["name", "occupation", "organization", "age", "location", "birth_date"]


class DeidentificationPreviewRequest(BaseModel):
    texts: list[str] = Field(default_factory=list, max_length=10)
    client_name: str = Field(default="", max_length=100)
    counselor_name: str = Field(default="", max_length=100)


class DeidentificationPreviewItem(BaseModel):
    original: str
    replacement: str
    category: PreviewCategory


class DeidentificationPreviewResponse(BaseModel):
    items: list[DeidentificationPreviewItem]
    model_used: bool


class DeidentificationPreviewInputError(ValueError):
    pass


def _name_forms(name: str, text: str) -> list[str]:
    """The name, plus its given name when that also appears on its own (윤다온 → 다온 씨)."""
    value = (name or "").strip()
    if not re.fullmatch(r"[가-힣]{2,5}", value) or is_masked_name(value):
        return []
    given = given_name(value)
    return [value, given] if given and name_pattern(given).search(text) else [value]


def _person_label(index: int) -> str:
    # 인물 B, 인물 C, ... (A is the client).
    letter = chr(ord("B") + index) if index < 25 else str(index + 2)
    return f"인물 {letter}"


def preview_items(texts: list[str], *, client_name: str = "", counselor_name: str = "") -> DeidentificationPreviewResponse:
    joined = "\n\n".join(text for text in texts if text and text.strip())
    if len(joined) > PREVIEW_MAX_CHARS:
        raise DeidentificationPreviewInputError(f"확인할 내용은 {PREVIEW_MAX_CHARS:,}자까지 보낼 수 있어요.")
    if not joined:
        return DeidentificationPreviewResponse(items=[], model_used=False)

    items: dict[str, DeidentificationPreviewItem] = {}

    def add(original: str, replacement: str, category: PreviewCategory) -> None:
        value = original.strip()
        if len(value) >= 2 and value in joined and value not in items:
            items[value] = DeidentificationPreviewItem(original=value, replacement=replacement, category=category)

    for form in _name_forms(client_name, joined):
        add(form, CLIENT_LABEL, "name")
    for form in _name_forms(counselor_name, joined):
        add(form, COUNSELOR_LABEL, "name")

    entities = _extract_entities(joined)
    if entities is not None:
        # Other people: one label per person; a given name ("민지") shares the full name's label ("김민지").
        people: list[str] = []
        names = [name.strip() for name in entities.person_names]
        for name in sorted(names, key=len, reverse=True):
            if not _NAME_TOKEN.match(name) or is_masked_name(name) or name in items or name not in joined:
                continue
            owners = [full for full in people if given_name(full) == name]
            if len(owners) > 1:
                add(name, "인물 확인 필요", "name")
                continue
            owner = owners[0] if owners else None
            label = items[owner].replacement if owner else _person_label(len(people))
            if owner is None:
                people.append(name)
            add(name, label, "name")
        for mention in entities.organizations:
            add(mention.text, mention.kind, "organization")
        for mention in entities.occupations:
            if mention.text.strip() not in OCCUPATION_CATEGORIES:
                add(mention.text, mention.category, "occupation")
        for mention in entities.ages:
            digits = re.search(r"\d{1,3}", mention.text)
            add(mention.text, age_band(int(digits.group(0))) if digits else mention.band, "age")
        for location in entities.locations:
            add(location, LOCATION_LABEL, "location")
        for birth_date in entities.birth_dates:
            if len(birth_date.strip()) >= 4:
                add(birth_date, BIRTH_DATE_LABEL, "birth_date")

    # A registered client's given name is still ambiguous when another person shares it.
    for name, owner in discover_person_names(joined, (client_name, counselor_name)).items():
        if not owner:
            items[name] = DeidentificationPreviewItem(original=name, replacement="인물 확인 필요", category="name")
    return DeidentificationPreviewResponse(items=list(items.values()), model_used=False)
