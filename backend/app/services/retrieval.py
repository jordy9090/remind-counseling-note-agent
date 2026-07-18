"""Lightweight retrieval for case memory, document templates, and privacy guardrails."""
from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.schemas.note import (
    RetrievedCaseContextItem,
    RetrievedEvidenceItem,
    RetrievedPrivacyRule,
    RetrievedTemplateContext,
    TargetDocumentType,
)
from app.services.embeddings import embed_query
from app.services.supabase_storage import storage


@dataclass
class RetrievalChunk:
    chunk_id: str
    chunk_text: str
    source_ref: str
    retrieval_method: str
    similarity_score: float = 0.0
    document_id: str | None = None
    session_id: str | None = None
    source_note_id: str | None = None
    source_url: str = ""
    title: str = ""
    doc_category: str = ""
    document_type: str = ""
    allowed_use: str = ""
    authority_level: str = ""
    field_type: str = ""
    session_number: int | None = None
    session_date: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


TEMPLATE_CATEGORIES: dict[str, str] = {
    "session_note": "session_note_template",
    "supervision_report": "supervision_report_template",
    "termination_report": "termination_report_template",
}
WARNING_CATEGORIES = [
    "counseling_ethics",
    "privacy_law",
    "deidentification_guideline",
    "internal_security_policy",
    "ethics_rule",
    "privacy_rule",
    "security_rule",
]


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


def retrieve_case_memory_chunks(
    *,
    query_text: str,
    counselor_id: str,
    case_id: str,
    field_types: list[str] | None = None,
    max_chunks: int = 5,
) -> list[RetrievalChunk]:
    """Retrieve dense prior-session memory with mandatory counselor/case filters."""
    if not _can_dense_retrieve() or not query_text or not counselor_id or not case_id:
        return []
    started = time.perf_counter()
    vector = embed_query(query_text)
    rows = storage.rpc(
        "match_case_memory_chunks",
        {
            "query_embedding": vector,
            "filter_counselor_id": counselor_id,
            "filter_case_id": case_id,
            "filter_field_types": field_types,
            "match_count": max_chunks,
        },
    )
    chunks = [_case_memory_row_to_chunk(row) for row in rows or []]
    _log_retrieval(
        counselor_id=counselor_id,
        case_id=case_id,
        retrieval_scope="case_memory",
        query_text=query_text,
        retrieval_method="case_memory_dense",
        source_refs=[chunk.source_ref for chunk in chunks],
        latency_ms=_elapsed_ms(started),
    )
    return chunks


def retrieve_authoritative_kb_chunks(
    *,
    query_text: str,
    target_document_type: TargetDocumentType,
    include_warning_rules: bool = True,
    max_chunks: int = 8,
) -> list[RetrievalChunk]:
    """Retrieve source-aware KB chunks using pgvector/full-text RPCs."""
    if not _can_dense_retrieve() or not query_text:
        return []

    started = time.perf_counter()
    categories = [TEMPLATE_CATEGORIES[target_document_type], "document_template"]
    if include_warning_rules:
        categories.extend(WARNING_CATEGORIES)

    vector = embed_query(query_text)
    rpc_name = "hybrid_search_kb" if settings.enable_hybrid_retrieval else "match_kb_chunks"
    params: dict[str, Any] = {
        "query_embedding": vector,
        "match_count": max_chunks,
        "filter_doc_categories": _unique(categories),
        "filter_document_type": target_document_type,
        "filter_allowed_uses": None,
        "filter_authority_levels": None,
    }
    if settings.enable_hybrid_retrieval:
        params["query_text"] = query_text
    rows = storage.rpc(rpc_name, params)
    chunks = [_kb_row_to_chunk(row) for row in rows or []]
    _log_retrieval(
        counselor_id=None,
        case_id=None,
        retrieval_scope="authoritative_kb",
        query_text=query_text,
        retrieval_method=rpc_name,
        source_refs=[chunk.source_ref for chunk in chunks],
        latency_ms=_elapsed_ms(started),
    )
    return chunks


def chunks_to_case_context(chunks: list[RetrievalChunk]) -> list[RetrievedCaseContextItem]:
    """Project dense case-memory chunks into the existing response shape."""
    context: list[RetrievedCaseContextItem] = []
    for chunk in chunks[:5]:
        if not chunk.session_id:
            continue
        context.append(
            RetrievedCaseContextItem(
                source_ref=chunk.source_ref,
                session_id=chunk.session_id,
                session_number=chunk.session_number,
                session_date=chunk.session_date,
                summary=chunk.chunk_text,
                confirmed_note={},
                evidence_items=[
                    RetrievedEvidenceItem(
                        id=chunk.chunk_id,
                        source_type=chunk.field_type or "case_memory",
                        source_ref=chunk.source_ref,
                        source_text=chunk.chunk_text,
                        linked_field=chunk.field_type,
                    )
                ],
            )
        )
    return context


def chunks_to_template_context(
    target_document_type: TargetDocumentType,
    chunks: list[RetrievalChunk],
    fallback: RetrievedTemplateContext | None = None,
) -> RetrievedTemplateContext | None:
    """Merge retrieved template chunks into the existing template context schema."""
    context = fallback or RetrievedTemplateContext(target_document_type=target_document_type)
    for chunk in chunks:
        if chunk.doc_category not in {TEMPLATE_CATEGORIES[target_document_type], "document_template"}:
            continue
        metadata = chunk.metadata
        context.required_fields.extend(_list(metadata.get("required_fields")))
        context.optional_fields.extend(_list(metadata.get("optional_fields")))
        context.counselor_review_fields.extend(_list(metadata.get("counselor_review_fields")))
        context.missing_field_checklist.extend(_list(metadata.get("missing_field_checklist")))
        section_path = str(metadata.get("section_path") or "").strip()
        if section_path:
            context.missing_field_checklist.append(section_path)
        context.source_refs.append(chunk.source_ref)

    context.required_fields = _unique(context.required_fields)
    context.optional_fields = _unique(context.optional_fields)
    context.counselor_review_fields = _unique(context.counselor_review_fields)
    context.missing_field_checklist = _unique(context.missing_field_checklist)
    context.source_refs = _unique(context.source_refs)
    if not (
        context.required_fields
        or context.optional_fields
        or context.counselor_review_fields
        or context.missing_field_checklist
        or context.source_refs
    ):
        return None
    return context


def chunks_to_privacy_rules(
    chunks: list[RetrievalChunk],
    fallback: list[RetrievedPrivacyRule] | None = None,
) -> list[RetrievedPrivacyRule]:
    rules = list(fallback or [])
    for chunk in chunks:
        if chunk.doc_category not in set(WARNING_CATEGORIES):
            continue
        metadata = chunk.metadata
        warning = str(metadata.get("warning") or metadata.get("allowed_use") or "").strip()
        if not warning:
            warning = "Review consent, deidentification, access control, and retention before storing or exporting."
        rules.append(
            RetrievedPrivacyRule(
                source_ref=chunk.source_ref,
                title=chunk.title or "Retrieved safety rule",
                category=chunk.doc_category or "privacy_rule",
                rule=chunk.chunk_text,
                warning=warning,
            )
        )
    by_ref: dict[str, RetrievedPrivacyRule] = {}
    for rule in rules:
        by_ref.setdefault(rule.source_ref, rule)
    return list(by_ref.values())[:8]


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


def _can_dense_retrieve() -> bool:
    return settings.enable_rag and settings.enable_dense_retrieval and storage.retrieval_enabled


def retrieval_query_from_input(target_document_type: TargetDocumentType, sources: Any) -> str:
    parts = [
        f"target_document_type:{target_document_type}",
        getattr(sources, "counseling_goal", ""),
        " ".join(getattr(sources, "key_issue_tags", []) or []),
        getattr(sources, "previous_session_summary", ""),
        getattr(sources, "counselor_memo", ""),
        getattr(sources, "transcript_text", ""),
    ]
    return " ".join(str(part).strip() for part in parts if str(part).strip())[:4000]


def _kb_row_to_chunk(row: dict[str, Any]) -> RetrievalChunk:
    metadata = row.get("metadata") or {}
    return RetrievalChunk(
        chunk_id=str(row.get("chunk_id") or ""),
        document_id=str(row.get("document_id") or "") or None,
        source_ref=str(row.get("source_ref") or ""),
        source_url=str(row.get("source_url") or ""),
        title=str(row.get("title") or ""),
        doc_category=str(row.get("doc_category") or ""),
        document_type=str(row.get("document_type") or ""),
        allowed_use=str(row.get("allowed_use") or ""),
        authority_level=str(row.get("authority_level") or ""),
        chunk_text=str(row.get("chunk_text") or ""),
        similarity_score=_as_float(row.get("similarity_score")),
        retrieval_method=str(row.get("retrieval_method") or "dense"),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _case_memory_row_to_chunk(row: dict[str, Any]) -> RetrievalChunk:
    metadata = row.get("metadata") or {}
    return RetrievalChunk(
        chunk_id=str(row.get("chunk_id") or ""),
        session_id=str(row.get("session_id") or "") or None,
        source_note_id=str(row.get("source_note_id") or "") or None,
        source_ref=str(row.get("source_ref") or ""),
        field_type=str(row.get("field_type") or ""),
        chunk_text=str(row.get("chunk_text") or ""),
        session_number=_as_int(row.get("session_number")),
        session_date=str(row.get("session_date") or ""),
        similarity_score=_as_float(row.get("similarity_score")),
        retrieval_method=str(row.get("retrieval_method") or "case_memory_dense"),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


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


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _log_retrieval(
    *,
    counselor_id: str | None,
    case_id: str | None,
    retrieval_scope: str,
    query_text: str,
    retrieval_method: str,
    source_refs: list[str],
    latency_ms: int,
) -> None:
    if not storage.retrieval_enabled:
        return
    try:
        storage.insert(
            "retrieval_logs",
            [
                {
                    "counselor_id": counselor_id,
                    "case_id": case_id,
                    "retrieval_scope": retrieval_scope,
                    "query_hash": hashlib.sha256(query_text.encode("utf-8")).hexdigest(),
                    "query_length": len(query_text),
                    "retrieval_method": retrieval_method,
                    "returned_source_refs": source_refs,
                    "result_count": len(source_refs),
                    "latency_ms": latency_ms,
                }
            ],
            return_representation=False,
        )
    except Exception:
        return


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
