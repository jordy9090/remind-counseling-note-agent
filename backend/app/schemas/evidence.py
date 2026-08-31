"""Production schemas for raw transcript windows and candidate regions."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SpeakerRole = Literal["counselor", "client", "unknown"]


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
