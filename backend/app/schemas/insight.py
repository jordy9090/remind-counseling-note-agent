"""Review-only relational hypotheses with separate session and theory provenance."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class TheorySource(BaseModel):
    """Canonical metadata from the curated corpus, never model-generated citations."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    organization: str
    url: str
    locator: str
    principle: str
    concepts: list[str] = Field(default_factory=list)
    limitations: str = ""


class InsightEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: Literal["transcript_text", "counselor_memo", "nonverbal_notes"]
    quote: str = Field(min_length=8, max_length=450)


class InsightCard(BaseModel):
    """A hypothesis for discussion; it is never an established clinical finding."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    focus: Literal["relationship_pattern", "here_and_now", "intervention_response", "counselor_reflection"]
    brief_text: str = Field(
        default="", max_length=240,
        description="화면에 표시할 1~2문장, 목표 120~180자. 잠정 가설과 중요한 반대 근거·한계를 자연스러운 문장 안에 포함. 약어·소제목·인용·문헌 목록 금지.",
    )
    observation: str = Field(min_length=8, max_length=700)
    hypothesis: str = Field(min_length=12, max_length=700)
    alternative_explanation: str = Field(min_length=8, max_length=600)
    counterevidence_or_missing: str = Field(min_length=8, max_length=600)
    supervision_questions: list[str] = Field(min_length=1, max_length=3)
    evidence: list[InsightEvidence] = Field(min_length=1, max_length=4)
    theory_source_ids: list[str] = Field(min_length=1, max_length=3)
    requires_review: Literal[True] = True


class RelationalInsights(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["generated", "insufficient_evidence", "unavailable", "demo"]
    lens: Literal["psychodynamic_relational"] = "psychodynamic_relational"
    cards: list[InsightCard] = Field(default_factory=list, max_length=4)
    theory_sources: list[TheorySource] = Field(default_factory=list)
    notices: list[str] = Field(default_factory=list)
    supervision_memo: str = ""


class RelationalInsightDraft(BaseModel):
    """Only hypotheses are model-authored; status and source metadata stay server-owned."""

    model_config = ConfigDict(extra="forbid")

    cards: list[InsightCard] = Field(default_factory=list, max_length=4)
