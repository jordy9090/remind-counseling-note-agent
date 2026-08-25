"""Schemas for document export requests."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


DocumentExportFormat = Literal["docx", "pdf", "hwpx"]
DocumentExportType = Literal["session_note", "supervision_report", "termination_report"]
DocumentBlockType = Literal["paragraph", "table", "transcript", "reflection_box", "placeholder"]


class DocumentFormatCapability(BaseModel):
    available: bool
    reason: str | None = None


class DocumentCapabilitiesResponse(BaseModel):
    docx: DocumentFormatCapability
    pdf: DocumentFormatCapability
    hwpx: DocumentFormatCapability


class DocumentTranscriptTurn(BaseModel):
    """One speaker turn in an exported transcript block."""

    model_config = ConfigDict(populate_by_name=True)

    turn_id: str = Field(default="", validation_alias=AliasChoices("turn_id", "turnId"))
    speaker: Literal["client", "counselor", "other"] = "other"
    text: str = ""
    silence_seconds: int | None = Field(
        default=None,
        validation_alias=AliasChoices("silence_seconds", "silenceSeconds"),
    )


class DocumentContentBlock(BaseModel):
    """Rich content block used by supervision reports and future templates."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    type: DocumentBlockType = "paragraph"
    text: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    speaker_turns: list[DocumentTranscriptTurn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("speaker_turns", "speakerTurns"),
    )
    warnings: list[str] = Field(default_factory=list)
    label: str | None = None


class DocumentSection(BaseModel):
    """A visible section from the final document workspace."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    content: str | list[str] | None = None
    content_blocks: list[DocumentContentBlock] = Field(
        default_factory=list,
        validation_alias=AliasChoices("content_blocks", "contentBlocks"),
    )
    level: int = 2

    @field_validator("title")
    @classmethod
    def title_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("section title must not be blank")
        return value


class DocumentExportRequest(BaseModel):
    """Request body for generating a downloadable counseling document."""

    format: DocumentExportFormat
    document_type: DocumentExportType
    case_id: str
    session_number: int = Field(ge=0)
    session_date: str = ""
    title: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[DocumentSection] = Field(min_length=1)

    @field_validator("case_id", "title")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value
