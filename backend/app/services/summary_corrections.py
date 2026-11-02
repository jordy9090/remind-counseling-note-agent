"""Bounded lexical corrections and complete citation decisions for summary drafts."""
from __future__ import annotations

import unicodedata
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.note import SessionSummaryDraft
from app.services.summary_quality import QUOTED_TEXT, SECTION_LIMITS, SummaryQualityError, summary_quality_issues, summary_quote_issues

SummaryField = Literal["session_theme", "presenting_problem", "session_content", "counselor_intervention", "client_response", "reflection", "next_plan"]


class TextCorrection(BaseModel):
    field: SummaryField
    original: str = Field(min_length=1, max_length=24)
    replacement: str = Field(min_length=1, max_length=24)


class SourceRefReview(BaseModel):
    field: SummaryField
    keep_source_refs: list[str] = Field(default_factory=list)


class SourceRefRestoration(BaseModel):
    field: SummaryField
    source_refs: list[str] = Field(default_factory=list)


def retain_required_refs(original: SessionSummaryDraft, candidate: SessionSummaryDraft,
                         restorations: list[SourceRefRestoration], catalog: dict[str, str]) -> SessionSummaryDraft:
    """Cancel only reviewed removals; final verification cannot invent new references."""
    result = candidate.model_copy(deep=True)
    seen: set[str] = set()
    for decision in restorations:
        before = getattr(original, decision.field).source_refs
        section = getattr(result, decision.field)
        removed = set(before) - set(section.source_refs)
        if (decision.field in seen or len(set(decision.source_refs)) != len(decision.source_refs)
                or not set(decision.source_refs) <= removed
                or any(ref not in catalog for ref in decision.source_refs)):
            raise SummaryQualityError()
        seen.add(decision.field)
        keep = set(section.source_refs) | set(decision.source_refs)
        section.source_refs = [ref for ref in before if ref in keep]
    return result


def introduced_script_fields(summary: SessionSummaryDraft, catalog: dict[str, str]) -> list[str]:
    """Detect generated foreign-script fragments absent from the supplied sources.

    This is not a language ban: source wording in any script stays admissible.
    Ordinary Korean, Latin abbreviations and Hanja are valid record prose.
    """
    def scripts(text: str) -> set[str]:
        return {unicodedata.name(char, "").split(" ")[0] for char in text if char.isalpha()}

    allowed = {"HANGUL", "LATIN", "CJK"} | scripts("\n".join(catalog.values()))
    return [field for field in SECTION_LIMITS if scripts(getattr(summary, field).text) - allowed]


def correct_summary(
    summary: SessionSummaryDraft,
    text_corrections: list[TextCorrection],
    source_ref_reviews: list[SourceRefReview],
    catalog: dict[str, str],
) -> tuple[SessionSummaryDraft, list[str]]:
    """Apply an atomic candidate edit; callers must reverify every changed draft."""
    candidate = summary.model_copy(deep=True)
    decisions = {item.field: item.keep_source_refs for item in source_ref_reviews}
    required = {field for field in SECTION_LIMITS if getattr(summary, field).source_refs}
    if len(decisions) != len(source_ref_reviews) or not required <= decisions.keys():
        raise SummaryQualityError()
    for field, keep in decisions.items():
        section = getattr(candidate, field)
        if len(keep) != len(set(keep)) or not set(keep) <= set(section.source_refs) or any(ref not in catalog for ref in keep):
            raise SummaryQualityError()
        # Removing all evidence is not a correction of an otherwise supported claim.
        if section.source_refs and not keep:
            raise SummaryQualityError()
        section.source_refs = [ref for ref in section.source_refs if ref in keep]

    spans: dict[str, list[tuple[int, int, str]]] = {}
    for edit in text_corrections:
        text = getattr(summary, edit.field).text
        if edit.original == edit.replacement or text.count(edit.original) != 1:
            raise SummaryQualityError()
        # Only a lexical token can change, never a sentence, number or punctuation.
        if any(not (char.isalpha() or unicodedata.category(char).startswith("M"))
               for char in edit.original + edit.replacement):
            raise SummaryQualityError()
        start = text.index(edit.original)
        end = start + len(edit.original)
        if any(start < quote.end() and end > quote.start() for quote in QUOTED_TEXT.finditer(text)):
            raise SummaryQualityError()
        if any(start < prior_end and end > prior_start for prior_start, prior_end, _ in spans.get(edit.field, [])):
            raise SummaryQualityError()
        spans.setdefault(edit.field, []).append((start, end, edit.replacement))
    for field, edits in spans.items():
        section = getattr(candidate, field)
        for start, end, replacement in sorted(edits, reverse=True):
            section.text = section.text[:start] + replacement + section.text[end:]

    if introduced_script_fields(candidate, catalog) or summary_quality_issues(candidate):
        raise SummaryQualityError()
    # A reference deletion must not break a previously supported direct quote.
    if set(summary_quote_issues(candidate, catalog)) - set(summary_quote_issues(summary, catalog)):
        raise SummaryQualityError()
    changed = [field for field in SECTION_LIMITS
               if getattr(candidate, field).model_dump() != getattr(summary, field).model_dump()]
    return candidate, changed
