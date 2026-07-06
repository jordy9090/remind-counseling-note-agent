"""Lightweight retrieval for case memory, document templates, and privacy guardrails."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.core.config import settings
from app.schemas.note import (
    RetrievedCaseContextItem,
    RetrievedEvidenceItem,
    RetrievedPrivacyRule,
    RetrievedTemplateContext,
    TargetDocumentType,
)
from app.services.supabase_storage import storage


def retrieve_case_context(
    case_id: str,
    current_session_id: str | None = None,
    max_sessions: int = 3,
) -> list[RetrievedCaseContextItem]:
    """Retrieve recent prior sessions for the same case id.

    V1 intentionally uses recency-based retrieval. V2 can add pgvector search over
    field-aware chunks once row-level isolation, audit logging, and retention rules
    are established.
    """
    if not _can_retrieve() or not case_id:
        return []

    query: dict[str, str | int] = {
        "case_id": f"eq.{case_id}",
        "select": "id,case_id,session_number,session_date,session_title,created_at",
        "order": "session_number.desc,created_at.desc",
        "limit": max_sessions,
    }
    if current_session_id:
        query["id"] = f"neq.{current_session_id}"

    sessions = storage.select("sessions", query)
    if not sessions:
        return []

    session_ids = [str(row["id"]) for row in sessions if row.get("id")]
    notes_by_session = _latest_notes_by_session(session_ids)
    evidence_by_session = _evidence_by_session(session_ids)

    context: list[RetrievedCaseContextItem] = []
    for session in sessions:
        session_id = str(session.get("id") or "")
        if not session_id:
            continue
        note = notes_by_session.get(session_id, {})
        context.append(
            RetrievedCaseContextItem(
                source_ref=f"stored_session_note:{session_id}",
                session_id=session_id,
                session_number=_as_int(session.get("session_number")),
                session_date=str(session.get("session_date") or ""),
                summary=_summary_from_note(note),
                confirmed_note=note.get("confirmed_json") or {},
                evidence_items=evidence_by_session.get(session_id, []),
            )
        )
    return context


def retrieve_document_template(target_document_type: TargetDocumentType) -> RetrievedTemplateContext | None:
    """Retrieve a document-template checklist from Supabase KB chunks."""
    if not _can_retrieve():
        return None

    documents = storage.select(
        "kb_documents",
        {
            "doc_category": "eq.document_template",
            "select": "id,title,source_type,doc_category,authority_level",
            "limit": 50,
        },
    )
    matching_docs = [
        doc
        for doc in documents
        if str(doc.get("source_type") or "").lower() in {target_document_type, ""}
        or target_document_type in str(doc.get("title") or "").lower()
    ]
    if not matching_docs:
        return RetrievedTemplateContext(target_document_type=target_document_type)

    chunks = _chunks_for_documents([str(doc["id"]) for doc in matching_docs if doc.get("id")])
    context = RetrievedTemplateContext(target_document_type=target_document_type)
    for chunk in chunks:
        metadata = _metadata(chunk)
        context.required_fields.extend(_list(metadata.get("required_fields")))
        context.optional_fields.extend(_list(metadata.get("optional_fields")))
        context.counselor_review_fields.extend(_list(metadata.get("counselor_review_fields")))
        context.missing_field_checklist.extend(_list(metadata.get("missing_field_checklist")))
        chunk_type = str(chunk.get("chunk_type") or "")
        chunk_text = str(chunk.get("chunk_text") or "").strip()
        if chunk_text and chunk_type == "required_field":
            context.required_fields.append(chunk_text)
        elif chunk_text and chunk_type == "optional_field":
            context.optional_fields.append(chunk_text)
        elif chunk_text and chunk_type == "counselor_review_field":
            context.counselor_review_fields.append(chunk_text)
        elif chunk_text and chunk_type == "missing_field_check":
            context.missing_field_checklist.append(chunk_text)
        if chunk.get("id"):
            context.source_refs.append(f"kb_template:{chunk['id']}")

    context.required_fields = _unique(context.required_fields)
    context.optional_fields = _unique(context.optional_fields)
    context.counselor_review_fields = _unique(context.counselor_review_fields)
    context.missing_field_checklist = _unique(
        context.missing_field_checklist or context.required_fields + context.counselor_review_fields
    )
    context.source_refs = _unique(context.source_refs)
    return context


def retrieve_privacy_rules() -> list[RetrievedPrivacyRule]:
    """Retrieve privacy, ethics, and security rules for verification warnings only."""
    if not _can_retrieve():
        return []

    documents = storage.select(
        "kb_documents",
        {
            "doc_category": "in.(privacy_rule,ethics_rule,security_rule)",
            "select": "id,title,source_type,doc_category,authority_level",
            "limit": 30,
        },
    )
    if not documents:
        return []

    titles = {str(doc.get("id")): str(doc.get("title") or "KB rule") for doc in documents if doc.get("id")}
    categories = {str(doc.get("id")): str(doc.get("doc_category") or "privacy_rule") for doc in documents if doc.get("id")}
    chunks = _chunks_for_documents(list(titles))
    rules: list[RetrievedPrivacyRule] = []
    for chunk in chunks[:8]:
        metadata = _metadata(chunk)
        document_id = str(chunk.get("document_id") or "")
        chunk_text = str(chunk.get("chunk_text") or "").strip()
        if not chunk_text:
            continue
        rules.append(
            RetrievedPrivacyRule(
                source_ref=f"kb_privacy:{chunk.get('id') or document_id}",
                title=titles.get(document_id, "Privacy rule"),
                category=categories.get(document_id, "privacy_rule"),
                rule=chunk_text,
                warning=str(metadata.get("warning") or "상담사가 저장, 공유, export 전 검토해야 합니다."),
            )
        )
    return rules


def _can_retrieve() -> bool:
    return settings.enable_rag and storage.retrieval_enabled


def _latest_notes_by_session(session_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not session_ids:
        return {}
    rows = storage.select(
        "generated_notes",
        {
            "session_id": f"in.({','.join(session_ids)})",
            "select": "id,session_id,note_type,draft_json,confirmed_json,created_at",
            "order": "created_at.desc",
            "limit": 50,
        },
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        session_id = str(row.get("session_id") or "")
        if session_id and session_id not in latest:
            latest[session_id] = row
    return latest


def _evidence_by_session(session_ids: list[str]) -> dict[str, list[RetrievedEvidenceItem]]:
    if not session_ids:
        return {}
    rows = storage.select(
        "evidence_items",
        {
            "session_id": f"in.({','.join(session_ids)})",
            "select": "id,session_id,source_type,source_ref,source_text,linked_field,created_at",
            "order": "created_at.desc",
            "limit": 100,
        },
    )
    grouped: dict[str, list[RetrievedEvidenceItem]] = defaultdict(list)
    for row in rows:
        session_id = str(row.get("session_id") or "")
        if not session_id:
            continue
        grouped[session_id].append(
            RetrievedEvidenceItem(
                id=str(row.get("id")) if row.get("id") else None,
                source_type=str(row.get("source_type") or ""),
                source_ref=f"stored_evidence:{row.get('id')}" if row.get("id") else str(row.get("source_ref") or ""),
                source_text=str(row.get("source_text") or ""),
                linked_field=str(row.get("linked_field") or ""),
            )
        )
    return grouped


def _chunks_for_documents(document_ids: list[str]) -> list[dict[str, Any]]:
    if not document_ids:
        return []
    return storage.select(
        "kb_chunks",
        {
            "document_id": f"in.({','.join(document_ids)})",
            "select": "id,document_id,chunk_text,chunk_type,metadata_json",
            "order": "id.asc",
            "limit": 100,
        },
    )


def _summary_from_note(note: dict[str, Any]) -> str:
    confirmed = note.get("confirmed_json") or {}
    sections = confirmed.get("sections") if isinstance(confirmed, dict) else None
    if isinstance(sections, dict):
        for key in ("session_content", "session_theme", "presenting_problem"):
            if sections.get(key):
                return str(sections[key])

    draft = note.get("draft_json") or {}
    if isinstance(draft, dict):
        for key in ("session_content", "session_theme", "presenting_problem"):
            value = draft.get(key)
            if isinstance(value, dict) and value.get("text"):
                return str(value["text"])
    return ""


def _metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    metadata = chunk.get("metadata_json") or {}
    return metadata if isinstance(metadata, dict) else {}


def _list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
