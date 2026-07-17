"""Schemas for uploaded counseling material extraction."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DocumentMaterialStatus = Literal["completed", "warning"]


class DocumentExtractionResponse(BaseModel):
    """Extracted text from a temporary document upload."""

    material_id: str
    filename: str
    media_type: str
    status: DocumentMaterialStatus = "completed"
    character_count: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=0)
    extracted_text: str
    warnings: list[str] = Field(default_factory=list)
