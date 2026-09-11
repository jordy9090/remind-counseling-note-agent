"""Allowlisted temporary workspace fields, independent of transcript evidence storage."""
from __future__ import annotations

from typing import Any


def _fields(names: str) -> dict[str, Any]:
    return dict.fromkeys(names.split(), "scalar")


# Mirrored by frontend/src/lib/temporaryDraft.ts; round-trip fixtures cover both boundaries.
_STRINGS = ["scalar"]
_BLOCK = {
    **_fields("id type text aiGenerated demoValue reviewStatus label evidenceStatus"),
    "rows": [{"*": "scalar"}], "speakerTurns": [_fields("turnId speaker text silenceSeconds")],
    "evidenceIds": _STRINGS, "warnings": _STRINGS, "guidance": _STRINGS, "missingInputs": _STRINGS,
}
_SHAPE = {
    **_fields("draft_id saved_at case_id session_number session_date counselor_name screen session_topic is_deidentified final_document_type"),
    "selected_previous_session_ids": _STRINGS, "visible_section_ids": _STRINGS,
    "form": {
        **_fields("case_id client_alias session_number session_date counselor_name counselor_memo transcript_text previous_session_summary counseling_goal psychological_test_summary nonverbal_notes target_document_type persist"),
        "key_issue_tags": _STRINGS,
    },
    "attachments": [{
        **_fields("id kind filename mediaType status characterCount pageCount durationSeconds language runtimeMode diarizationStatus languageProbability dirtySinceApply expectedSpeakers lastAppliedMode requiresReattachment"),
        "appliedTargets": _STRINGS,
    }],
    "draft_sections": [_fields("id title content visible")],
    "final_document_sections": [_fields("id title content contentKind")],
    "result": {
        **_fields("case_id session_number session_summary main_issue counselor_intervention client_response next_plan workspace_note_id"),
        "missing_items": _STRINGS, "warnings": _STRINGS,
    },
    "supervision_report_draft": {
        **_fields("reportId caseId reportType title"),
        "meta": _fields("clientAlias sessionNumber reportDate counselorName institution supervisor supervisionDatePlace"),
        "sections": [{**_fields("id title level status"), "guidance": _STRINGS, "contentBlocks": [_BLOCK]}],
        "aiReview": {
            "completionChecklist": [_fields("label status reason")], "missingFields": _STRINGS, "demoInputs": _STRINGS,
            "needsHumanReview": [_fields("sectionId message severity")], "unsupportedClaims": [_fields("blockId claim reason")],
            "suggestedSupervisionQuestions": _STRINGS, "caution": "scalar",
        },
    },
}
_OMIT = object()


def _project(value: Any, allowed: Any) -> Any:
    if value is None:
        return None
    if allowed == "scalar":
        return value if isinstance(value, (str, int, float, bool)) else _OMIT
    if isinstance(allowed, list):
        return [item for entry in value if (item := _project(entry, allowed[0])) is not _OMIT] if isinstance(value, list) else _OMIT
    if not isinstance(value, dict):
        return _OMIT
    return {
        key: projected for key, item in value.items()
        if (rule := allowed.get(key, allowed.get("*"))) is not None
        and (projected := _project(item, rule)) is not _OMIT
    }


def temporary_draft_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Project saves and legacy reads without modifying existing stored rows."""
    data = _project(value, _SHAPE)
    data["attachments"] = [
        {**material, "requiresReattachment": True, "warnings": []}
        for material in data.get("attachments", []) if isinstance(material, dict)
    ]
    if isinstance(data.get("result"), dict):
        data["result"]["evidence_check"] = []
    if isinstance(data.get("supervision_report_draft"), dict):
        data["supervision_report_draft"]["evidenceIndex"] = {}
    return data
