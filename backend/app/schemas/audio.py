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
    runtime_mode: Literal["disabled", "stub", "real"]


class AudioWord(BaseModel):
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, ge=0)
    text: str
    speaker: str | None = None
    probability: float | None = Field(default=None, ge=0, le=1)


class AudioSegment(BaseModel):
    id: int
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str
    speaker: str | None = None
    pause_before_seconds: float | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0)
    speech_rate_wps: float | None = Field(default=None, ge=0)
    speech_rate_level: Literal["slow", "typical", "fast"] | None = None
    volume_level: Literal["low", "typical", "high"] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    words: list[AudioWord] = Field(default_factory=list)


AudioTranscriptionStatus = Literal["completed"]


class AudioTranscriptionResponse(BaseModel):
    transcription_id: str
    filename: str
    status: AudioTranscriptionStatus = "completed"
    runtime_mode: Literal["stub", "real"]
    transcription_engine: Literal["whisperx", "stub"] | None = None
    alignment_model: str | None = None
    diarization_model: str | None = None
    alignment_status: Literal["completed", "fallback", "disabled"] = "disabled"
    diarization_status: Literal["completed", "fallback", "disabled"] = "disabled"
    duration_seconds: float | None = Field(default=None, ge=0)
    language: str | None = None
    language_probability: float | None = Field(default=None, ge=0, le=1)
    segments: list[AudioSegment] = Field(default_factory=list)
    transcript_text: str
    nonverbal_notes: str = ""
    warnings: list[str] = Field(default_factory=list)
