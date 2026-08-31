"""Schemas for deterministic, transcript-grounded evidence storage."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpeakerRole = Literal["counselor", "client", "unknown"]
EpisodeType = Literal["intervention_response", "client_event_state"]
TurnFunction = Literal[
    "client_report", "client_response", "counselor_clarification", "counselor_intervention", "other",
]


class TranscriptTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_index: int = Field(ge=0)
    speaker_role: SpeakerRole
    sanitized_text: str = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    source_type: str = "transcript"
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_timestamps(self) -> "TranscriptTurn":
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms must be greater than or equal to start_ms")
        return self


class StoredTranscriptTurn(TranscriptTurn):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    user_id: str
    counselor_id: str
    case_id: str
    session_id: str


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
    """LLM selection only; semantic/span validation happens independently afterward."""
    model_config = ConfigDict(extra="forbid")
    episode_type: EpisodeType
    start_turn_index: int
    end_turn_index: int


class EpisodeExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episodes: list[EpisodeSpanSelection] = Field(default_factory=list)


class TurnFunctionLabel(BaseModel):
    """Ephemeral LLM output; transcript text and clinical interpretation are forbidden."""
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


class TranscriptWindow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    user_id: str
    counselor_id: str
    case_id: str
    session_id: str
    start_turn_index: int = Field(ge=0)
    end_turn_index: int = Field(ge=0)
    window_text: str = Field(min_length=1)
    source_ref: str
    content_hash: str
    embedding_model: str | None = None

    @model_validator(mode="after")
    def validate_window_span(self) -> "TranscriptWindow":
        if self.start_turn_index > self.end_turn_index:
            raise ValueError("start_turn_index must be less than or equal to end_turn_index")
        return self


class RetrievedTranscriptWindow(BaseModel):
    window_id: str
    session_id: str
    session_number: int | None = None
    start_turn_index: int
    end_turn_index: int
    source_ref: str
    window_text: str
    similarity_score: float
    retrieval_method: str = "transcript_window_dense"


class CandidateTranscriptRegion(BaseModel):
    session_id: str
    session_number: int | None = None
    start_turn_index: int
    end_turn_index: int
    region_text: str
    source_ref: str
    retrieval_score: float
    retrieval_rank: int
    window_ids: list[str] = Field(default_factory=list)


class EvidenceSpanSelection(BaseModel):
    """Query-conditioned LLM output: source indices only."""
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
