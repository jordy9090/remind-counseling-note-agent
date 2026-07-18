"""JSON Schema shared by constrained generation and quick evaluation."""
from __future__ import annotations

from typing import Any

NOTE_SECTIONS = (
    "session_theme",
    "presenting_problem",
    "session_content",
    "counselor_intervention",
    "client_response",
    "reflection",
    "next_plan",
)

VALID_EVIDENCE_TYPES = (
    "direct",
    "inferred",
    "counselor_input",
    "needs_review",
    "mixed",
    "model_inference",
    "prior_context_based",
)
REVIEW_EVIDENCE_TYPES = (
    "inferred",
    "counselor_input",
    "needs_review",
    "model_inference",
    "prior_context_based",
)
SECTION_TEXT_MAX_LENGTHS = {
    "session_theme": 200,
    "presenting_problem": 400,
    "session_content": 600,
    "counselor_intervention": 450,
    "client_response": 400,
    "reflection": 200,
    "next_plan": 350,
}


def _section_schema(max_text_length: int, *, reflection: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "text": {"type": "string", "minLength": 1, "maxLength": max_text_length},
        "evidence_type": {"type": "string", "enum": list(VALID_EVIDENCE_TYPES)},
        "source_refs": {
            "type": "array",
            "items": {"type": "string", "maxLength": 80},
            "maxItems": 8,
        },
        "requires_review": {"type": "boolean"},
    }
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": ["text", "evidence_type", "source_refs", "requires_review"],
        "additionalProperties": False,
    }
    if reflection:
        properties["evidence_type"] = {"const": "counselor_input"}
    return schema


COUNSELING_NOTE_SCHEMA: dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "session_info": {
            "type": "object",
            "properties": {
                "case_id": {"type": "string", "maxLength": 128},
                "session_number": {"type": "integer", "minimum": 1, "maximum": 9999},
                "session_date": {"type": "string", "maxLength": 32},
                "counselor_name": {"type": "string", "maxLength": 128},
            },
            "required": ["case_id", "session_number", "session_date", "counselor_name"],
            "additionalProperties": False,
        },
        **{
            section: _section_schema(
                SECTION_TEXT_MAX_LENGTHS[section], reflection=section == "reflection"
            )
            for section in NOTE_SECTIONS
        },
    },
    "required": ["session_info", *NOTE_SECTIONS],
    "additionalProperties": False,
}
