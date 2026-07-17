"""Schemas for audio upload capabilities and transcription."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AudioCapability(BaseModel):
    available: bool
    reason: str | None = None


class AudioCapabilitiesResponse(BaseModel):
    upload: AudioCapability
    transcription: AudioCapability
    speaker_diarization: AudioCapability


class AudioSegment(BaseModel):
    id: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


AudioTranscriptionStatus = Literal["completed"]


class AudioTranscriptionResponse(BaseModel):
    transcription_id: str
    filename: str
    status: AudioTranscriptionStatus = "completed"
    duration_seconds: float | None = Field(default=None, ge=0)
    language: str | None = None
    segments: list[AudioSegment] = Field(default_factory=list)
    transcript_text: str
    nonverbal_notes: str = ""
    warnings: list[str] = Field(default_factory=list)
