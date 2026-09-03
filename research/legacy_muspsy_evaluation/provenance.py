"""Canonical MusPsy demo input provenance used by evaluation v4."""
from __future__ import annotations

from fnmatch import fnmatch
from typing import Any, Iterable

CASE_ID = "CASE-MUSPSY-1416"
PROVENANCE_CLASSES = {
    "muspsy_original",
    "synthetic_demo_supplement",
    "derived_from_source",
    "retrieved_context",
}


INPUT_PROVENANCE: list[dict[str, Any]] = [
    {
        "field": "original_source.dialogues_1416",
        "source_class": "muspsy_original",
        "source": "sample_data/muspsy_demo/original_source/dialogues_1416.txt",
        "allowed_for_demo": True,
        "notes": "MusPsy dialogue source; sessions are separated by #######.",
    },
    {
        "field": "original_source.memories_1416",
        "source_class": "muspsy_original",
        "source": "sample_data/muspsy_demo/original_source/memories_1416.txt",
        "allowed_for_demo": True,
        "notes": "MusPsy counseling memory source used for traceable sessions 1-4 retrieval chunks.",
    },
    {
        "field": "original_source.usercards_1416",
        "source_class": "muspsy_original",
        "source": "sample_data/muspsy_demo/original_source/usercards_1416.txt",
        "allowed_for_demo": True,
        "notes": "MusPsy user-card source; not used to fill unsupported counselor-facing facts.",
    },
    {
        "field": "case_id",
        "source_class": "derived_from_source",
        "source": "MusPsy public case identifier 1416",
        "allowed_for_demo": True,
    },
    {
        "field": "session_number",
        "source_class": "derived_from_source",
        "source": "dialogues_1416.txt session ordering",
        "allowed_for_demo": True,
    },
    {
        "field": "session_date",
        "source_class": "synthetic_demo_supplement",
        "source": "demo supplementary input",
        "allowed_for_demo": True,
    },
    {
        "field": "counselor_name",
        "source_class": "synthetic_demo_supplement",
        "source": "demo display label",
        "allowed_for_demo": True,
    },
    {
        "field": "counselor_memo",
        "source_class": "synthetic_demo_supplement",
        "source": "demo memo assembled from source-derived session content plus explicit supplementary observations",
        "allowed_for_demo": True,
        "notes": "Conservatively classified as supplementary because the field mixes source-derived and demo-only material.",
    },
    {
        "field": "counselor_memo.current_session_content",
        "source_class": "derived_from_source",
        "source": "dialogues_1416.txt session 5, Korean adaptation",
        "allowed_for_demo": True,
    },
    {
        "field": "counselor_memo.risk_screening",
        "source_class": "synthetic_demo_supplement",
        "source": "demo supplementary input",
        "allowed_for_demo": True,
    },
    {
        "field": "counselor_memo.mse_style_observation",
        "source_class": "synthetic_demo_supplement",
        "source": "demo supplementary input",
        "allowed_for_demo": True,
    },
    {
        "field": "transcript_text",
        "source_class": "derived_from_source",
        "source": "dialogues_1416.txt session 5, Korean adaptation",
        "allowed_for_demo": True,
    },
    {
        "field": "previous_session_summary",
        "source_class": "derived_from_source",
        "source": "memories_1416.txt sessions 1-4, Korean summaries",
        "allowed_for_demo": True,
    },
    {
        "field": "counseling_goal",
        "source_class": "derived_from_source",
        "source": "dialogues_1416.txt and memories_1416.txt counseling goals",
        "allowed_for_demo": True,
    },
    {
        "field": "psychological_test_summary",
        "source_class": "synthetic_demo_supplement",
        "source": "demo supplementary input",
        "allowed_for_demo": True,
        "notes": "SIAS 46, BAI 18, PHQ-9 7 and related screening interpretation are not MusPsy original facts.",
    },
    {
        "field": "psychological_test_summary.risk_screening",
        "source_class": "synthetic_demo_supplement",
        "source": "demo supplementary input",
        "allowed_for_demo": True,
    },
    {
        "field": "key_issue_tags",
        "source_class": "derived_from_source",
        "source": "source-derived demo taxonomy",
        "allowed_for_demo": True,
    },
    {
        "field": "nonverbal_notes",
        "source_class": "synthetic_demo_supplement",
        "source": "demo supplementary observation input",
        "allowed_for_demo": True,
        "notes": "Includes nonverbal and MSE-style observations created for the demo.",
    },
    {
        "field": "retrieved_context",
        "source_class": "retrieved_context",
        "source": "Supabase case memory or authoritative KB",
        "allowed_for_demo": True,
    },
]


SOURCE_REF_RULES: list[dict[str, str]] = [
    {"pattern": "transcript.turn_*", "field": "transcript_text"},
    {"pattern": "transcript_text", "field": "transcript_text"},
    {"pattern": "previous_session.*", "field": "previous_session_summary"},
    {"pattern": "previous_session_summary", "field": "previous_session_summary"},
    {"pattern": "counselor_memo*", "field": "counselor_memo"},
    {"pattern": "counseling_goal", "field": "counseling_goal"},
    {"pattern": "psychological_test_summary", "field": "psychological_test_summary"},
    {"pattern": "key_issue_tags", "field": "key_issue_tags"},
    {"pattern": "nonverbal_notes*", "field": "nonverbal_notes"},
    {"pattern": "current_summary.*", "field": "transcript_text"},
    {"pattern": "muspsy:memories_1416:*", "field": "retrieved_context"},
    {"pattern": "stored_session_note:*", "field": "retrieved_context"},
    {"pattern": "stored_evidence:*", "field": "retrieved_context"},
    {"pattern": "confirmed_note:*", "field": "retrieved_context"},
    {"pattern": "kb:*", "field": "retrieved_context"},
]


def provenance_document() -> dict[str, Any]:
    return {
        "version": "v4",
        "case_id": CASE_ID,
        "valid_source_classes": sorted(PROVENANCE_CLASSES),
        "input_fields": INPUT_PROVENANCE,
        "source_ref_rules": SOURCE_REF_RULES,
    }


def field_provenance(field: str) -> dict[str, Any] | None:
    return next((item for item in INPUT_PROVENANCE if item["field"] == field), None)


def source_ref_provenance(source_ref: str) -> dict[str, Any] | None:
    for rule in SOURCE_REF_RULES:
        if fnmatch(source_ref, rule["pattern"]):
            item = field_provenance(rule["field"])
            if item is None:
                return None
            result = {
                "source_ref": source_ref,
                "field": item["field"],
                "source_class": item["source_class"],
                "source": item["source"],
                "allowed_for_demo": item["allowed_for_demo"],
            }
            if source_ref.startswith("muspsy:memories_1416:"):
                result["upstream_source_class"] = "muspsy_original"
                result["upstream_source"] = "sample_data/muspsy_demo/original_source/memories_1416.txt"
            return result
    return None


def map_source_refs(source_refs: Iterable[str]) -> dict[str, dict[str, Any] | None]:
    return {ref: source_ref_provenance(ref) for ref in sorted(set(source_refs)) if ref}


def provenance_markdown() -> str:
    lines = [
        "# CASE-MUSPSY-1416 Input Provenance",
        "",
        "MusPsy 원본, 원본에서 파생된 한국어 입력, 시연용 supplementary 입력, 검색 문맥을 구분한다.",
        "Supplementary 입력은 시연에서 허용되지만 MusPsy 원본 사실로 표시하지 않는다.",
        "",
        "| Field | Source class | Source | Demo allowed | Notes |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in INPUT_PROVENANCE:
        lines.append(
            "| {field} | {source_class} | {source} | {allowed} | {notes} |".format(
                field=item["field"],
                source_class=item["source_class"],
                source=item["source"],
                allowed=str(item["allowed_for_demo"]).lower(),
                notes=item.get("notes", ""),
            )
        )
    lines.extend(["", "## Source-ref mapping", "", "| Pattern | Provenance field |", "| --- | --- |"])
    for rule in SOURCE_REF_RULES:
        lines.append(f"| `{rule['pattern']}` | `{rule['field']}` |")
    return "\n".join(lines) + "\n"
