"""Schemas used only by archived raw-evidence experiments."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.evidence import CandidateTranscriptRegion, RetrievedTranscriptWindow

EpisodeType = Literal["intervention_response", "client_event_state"]
TurnFunction = Literal[
    "client_report", "client_response", "counselor_clarification", "counselor_intervention", "other",
]


class EvidenceEpisodeSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_type: EpisodeType
    start_turn_index: int = Field(ge=0)
    end_turn_index: int = Field(ge=0)
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_span_semantics(self) -> "EvidenceEpisodeSpan":
        if self.start_turn_index > self.end_turn_index:
            raise ValueError("start_turn_index must be less than or equal to end_turn_index")
        return self


class EvidenceEpisode(EvidenceEpisodeSpan):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    user_id: str
    counselor_id: str
    case_id: str
    session_id: str
    source_ref: str
    episode_text: str
    content_hash: str
    embedding_model: str | None = None


class EpisodeSpanSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_type: EpisodeType
    start_turn_index: int
    end_turn_index: int


class EpisodeExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episodes: list[EpisodeSpanSelection] = Field(default_factory=list)


class TurnFunctionLabel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_index: int = Field(ge=0)
    function: TurnFunction


class TurnFunctionLabelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels: list[TurnFunctionLabel] = Field(default_factory=list)


class EvidenceExtractionDiagnostic(BaseModel):
    candidate_index: int | None = None
    code: str
    message: str


class EvidenceExtractionResult(BaseModel):
    spans: list[EvidenceEpisodeSpan] = Field(default_factory=list)
    episodes: list[EvidenceEpisode] = Field(default_factory=list)
    diagnostics: list[EvidenceExtractionDiagnostic] = Field(default_factory=list)
    embedding_count: int = 0


class RetrievedEvidenceEpisode(BaseModel):
    episode_id: str
    session_id: str
    session_number: int | None = None
    episode_type: EpisodeType
    start_turn_index: int
    end_turn_index: int
    source_ref: str
    episode_text: str
    similarity_score: float
    retrieval_method: str = "evidence_episode_dense"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSet(BaseModel):
    query_text: str
    candidates: list[RetrievedEvidenceEpisode] = Field(default_factory=list)
    results: list[RetrievedEvidenceEpisode] = Field(default_factory=list)


class EvidenceSpanSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_turn_index: int
    end_turn_index: int


class EvidenceSpanSelectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spans: list[EvidenceSpanSelection] = Field(default_factory=list)


class SelectedEvidenceSpan(BaseModel):
    session_id: str
    session_number: int | None = None
    start_turn_index: int
    end_turn_index: int
    source_ref: str
    evidence_text: str
    retrieval_score: float | None = None
    retrieval_rank: int | None = None


class RawEvidenceSelectionSet(BaseModel):
    query_text: str
    candidates: list[RetrievedTranscriptWindow] = Field(default_factory=list)
    regions: list[CandidateTranscriptRegion] = Field(default_factory=list)
    results: list[SelectedEvidenceSpan] = Field(default_factory=list)
    diagnostics: list[EvidenceExtractionDiagnostic] = Field(default_factory=list)
