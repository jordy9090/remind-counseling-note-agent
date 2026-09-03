"""Schemas for opt-in raw-region grounded document generation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SourceRequirement = Literal["raw_factual", "counselor_judgment"]
GroundingSourceType = Literal["raw_transcript", "counselor_confirmed", "authoritative_kb"]
SupportType = Literal["direct_evidence", "counselor_judgment", "clinical_inference", "unsupported"]
ClaimKind = Literal["factual", "clinical_inference", "administrative"]
ClaimSupportVerdict = Literal["supported", "partial", "unsupported"]
ClaimSupportCategory = Literal[
    "missing_fact",
    "contradiction",
    "wrong_event",
    "wrong_session",
    "over_inference",
]


class EvidenceNeed(BaseModel):
    """A retrieval intent for one document field, not a clinical assessment."""

    model_config = ConfigDict(extra="forbid")

    need_id: str
    target_field: str
    query_text: str
    source_requirement: SourceRequirement


class GroundingSource(BaseModel):
    """One prompt-safe source with a canonical backend source_ref."""

    evidence_id: str
    source_type: GroundingSourceType
    source_ref: str
    source_text: str
    session_id: str | None = None
    session_number: int | None = None
    start_turn_index: int | None = None
    end_turn_index: int | None = None
    similarity_score: float | None = None
    retrieval_method: str = ""
    need_ids: list[str] = Field(default_factory=list)


class GroundingContextDiagnostics(BaseModel):
    evidence_need_count: int = 0
    retrieved_region_count: int = 0
    deduplicated_region_count: int = 0
    counselor_memory_count: int = 0
    authoritative_kb_count: int = 0
    raw_evidence_turn_count: int = 0
    approximate_token_count: int = 0


class GroundingContext(BaseModel):
    needs: list[EvidenceNeed] = Field(default_factory=list)
    sources: list[GroundingSource] = Field(default_factory=list)
    need_to_evidence_ids: dict[str, list[str]] = Field(default_factory=dict)
    diagnostics: GroundingContextDiagnostics = Field(default_factory=GroundingContextDiagnostics)


class GroundedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    need_id: str
    target_field: str
    text: str
    claim_kind: ClaimKind = "factual"
    support_type: SupportType
    evidence_ids: list[str] = Field(default_factory=list)
    review_required: bool = False


class GroundedGenerationDraft(BaseModel):
    """Structured model output before backend evidence-ID validation."""

    model_config = ConfigDict(extra="forbid")

    claims: list[GroundedClaim] = Field(default_factory=list)


class CitationDiagnostic(BaseModel):
    claim_id: str
    invalid_evidence_ids: list[str] = Field(default_factory=list)
    reason: str


class ClaimSupportValidation(BaseModel):
    """Minimal semantic verdict for one claim and its directly cited sources."""

    model_config = ConfigDict(extra="forbid")

    verdict: ClaimSupportVerdict
    supported_evidence_ids: list[str] = Field(default_factory=list)
    category: ClaimSupportCategory | None = None


class GroundingMetrics(BaseModel):
    citation_validity: float = 1.0
    factual_claim_citation_coverage: float = 1.0
    unsupported_factual_claim_rate: float = 0.0
    semantic_support_validity: float = 1.0
    raw_evidence_usage: int = 0
    source_type_distribution: dict[str, int] = Field(default_factory=dict)


class GroundedGenerationResult(BaseModel):
    enabled: bool = True
    context: GroundingContext
    claims: list[GroundedClaim] = Field(default_factory=list)
    citation_diagnostics: list[CitationDiagnostic] = Field(default_factory=list)
    claim_support_validations: dict[str, ClaimSupportValidation] = Field(default_factory=dict)
    metrics: GroundingMetrics = Field(default_factory=GroundingMetrics)
