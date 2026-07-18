"""Small Supabase REST helpers for optional Re:mind persistence."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings
from app.schemas.note import ConfirmGeneratedNoteRequest, ConfirmGeneratedNoteResponse, GenerateNoteResponse, PersistenceReport, SessionInput
from app.services.deidentification import deidentify_text
from app.services.embeddings import EmbeddingError, content_hash, get_embedding_provider


class SupabaseStorageError(RuntimeError):
    """Raised when Supabase returns an unsuccessful response."""


class SupabaseStorage:
    """Minimal REST client that avoids making Supabase a hard dependency."""

    def __init__(self, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return settings.supabase_configured

    @property
    def persistence_enabled(self) -> bool:
        return settings.enable_persistence and self.configured

    @property
    def retrieval_enabled(self) -> bool:
        return settings.enable_rag and self.configured

    def select(self, table: str, query: dict[str, str | int]) -> list[dict[str, Any]]:
        result = self._request("GET", table, query=query)
        return result if isinstance(result, list) else []

    def insert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        *,
        return_representation: bool = True,
    ) -> list[dict[str, Any]]:
        prefer = "return=representation" if return_representation else "return=minimal"
        result = self._request("POST", table, body=rows, prefer=prefer)
        return result if isinstance(result, list) else []

    def upsert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        *,
        on_conflict: str,
    ) -> list[dict[str, Any]]:
        result = self._request(
            "POST",
            table,
            query={"on_conflict": on_conflict},
            body=rows,
            prefer="resolution=merge-duplicates,return=representation",
        )
        return result if isinstance(result, list) else []

    def update(
        self,
        table: str,
        values: dict[str, Any],
        *,
        query: dict[str, str | int],
        return_representation: bool = True,
    ) -> list[dict[str, Any]]:
        prefer = "return=representation" if return_representation else "return=minimal"
        result = self._request("PATCH", table, query=query, body=values, prefer=prefer)
        return result if isinstance(result, list) else []

    def rpc(self, function_name: str, params: dict[str, Any]) -> Any:
        """Call a Supabase PostgREST RPC function."""
        return self._request("POST", f"rpc/{function_name}", body=params)

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str | int] | None = None,
        body: Any | None = None,
        prefer: str | None = None,
    ) -> Any:
        if not self.configured:
            raise SupabaseStorageError("Supabase is not configured.")

        query_string = f"?{urlencode(query)}" if query else ""
        url = f"{settings.normalized_supabase_url}/rest/v1/{path}{query_string}"
        key = settings.effective_supabase_key or ""
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if prefer:
            headers["Prefer"] = prefer

        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise SupabaseStorageError(f"Supabase {error.code}: {detail}") from error
        except URLError as error:
            raise SupabaseStorageError(f"Supabase network error: {error}") from error

        if not payload:
            return None
        return json.loads(payload)


storage = SupabaseStorage()


def persist_generated_note(session_input: SessionInput, result: GenerateNoteResponse) -> PersistenceReport:
    """Persist a generated note when explicitly requested by the API caller."""
    report = PersistenceReport(
        enabled=settings.enable_persistence,
        requested=session_input.persist,
        case_id=session_input.case_id,
    )
    if not session_input.persist:
        report.message = "Persistence was not requested for this generation."
        return report
    if not settings.enable_persistence:
        report.message = "ENABLE_PERSISTENCE is false; generation returned without storage."
        return report
    if not settings.supabase_configured:
        report.message = "Supabase credentials are missing; generation returned without storage."
        return report

    try:
        storage.upsert(
            "cases",
            [
                {
                    "id": session_input.case_id,
                    "case_alias": session_input.case_id,
                    "counselor_id": session_input.counselor_name or None,
                    "status": "active",
                }
            ],
            on_conflict="id",
        )
        session_rows = storage.upsert(
            "sessions",
            [_build_session_row(session_input, result)],
            on_conflict="case_id,session_number",
        )
        session_id = str(session_rows[0]["id"]) if session_rows else None
        report.session_id = session_id

        note_rows = storage.insert(
            "generated_notes",
            [
                {
                    "case_id": session_input.case_id,
                    "session_id": session_id,
                    "note_type": session_input.target_document_type,
                    "draft_json": result.session_summary_draft.model_dump(mode="json"),
                    "confirmed_json": result.confirmed_session_note,
                    "counselor_edited": False,
                }
            ],
        )
        report.note_id = str(note_rows[0]["id"]) if note_rows else None

        evidence_rows = [
            {
                "case_id": session_input.case_id,
                "session_id": session_id,
                "source_type": item.evidence_type,
                "source_ref": ",".join(item.source_refs),
                "source_text": item.content,
                "linked_field": item.field,
            }
            for item in result.evidence_mapped_data.items
        ]
        if evidence_rows:
            storage.insert("evidence_items", evidence_rows, return_representation=False)

        storage.insert(
            "verification_reports",
            [
                {
                    "case_id": session_input.case_id,
                    "session_id": session_id,
                    "note_id": report.note_id,
                    "report_json": result.verification_report.model_dump(mode="json"),
                }
            ],
            return_representation=False,
        )

        report.stored = True
        report.message = _stored_message()
    except Exception as error:
        report.message = f"Supabase persistence failed; generation response was preserved: {error}"
    return report


def confirm_generated_note(request: ConfirmGeneratedNoteRequest) -> ConfirmGeneratedNoteResponse:
    """Persist explicit counselor confirmation and create retrieval memory chunks."""
    confirmed_at = datetime.now(UTC).isoformat()
    status = "demo_confirmed" if request.demo_confirmed else "confirmed"
    if not settings.supabase_configured:
        return ConfirmGeneratedNoteResponse(
            note_id=request.note_id,
            confirmation_status=status,
            confirmed_at=confirmed_at,
            message="Supabase credentials are missing; confirmation was not stored.",
        )

    storage.update(
        "generated_notes",
        {
            "confirmed_json": request.confirmed_note,
            "counselor_edited": request.counselor_edited,
            "confirmation_status": status,
            "confirmed_at": confirmed_at,
            "confirmed_by": request.confirmed_by or "server_demo_actor",
            "updated_at": confirmed_at,
        },
        query={"id": f"eq.{request.note_id}"},
        return_representation=False,
    )

    chunks = _case_memory_rows_from_confirmed_note(request)
    embedding_count = _attach_embeddings(chunks)
    if request.create_case_memory and chunks:
        storage.insert("case_memory_chunks", chunks, return_representation=False)
        storage.update(
            "generated_notes",
            {"memory_indexed_at": datetime.now(UTC).isoformat()},
            query={"id": f"eq.{request.note_id}"},
            return_representation=False,
        )

    return ConfirmGeneratedNoteResponse(
        note_id=request.note_id,
        confirmation_status=status,
        confirmed_at=confirmed_at,
        memory_chunk_count=len(chunks) if request.create_case_memory else 0,
        memory_embedding_count=embedding_count if request.create_case_memory else 0,
        message="Confirmed note stored; case memory uses masked counselor-reviewed content only.",
    )


def _session_title(session_input: SessionInput) -> str:
    tags = ", ".join(session_input.key_issue_tags or [])
    if tags:
        return f"{session_input.session_number}회기: {tags}"
    return f"{session_input.session_number}회기 상담 기록"


def _raw_input_text(session_input: SessionInput) -> str:
    payload = {
        "counselor_memo": _masked(session_input.counselor_memo),
        "transcript_text": _masked(session_input.transcript_text),
        "previous_session_summary": _masked(session_input.previous_session_summary),
        "counseling_goal": _masked(session_input.counseling_goal),
        "psychological_test_summary": _masked(session_input.psychological_test_summary),
        "key_issue_tags": session_input.key_issue_tags,
        "nonverbal_notes": _masked(session_input.nonverbal_notes),
    }
    return json.dumps(payload, ensure_ascii=False)


def _build_session_row(session_input: SessionInput, result: GenerateNoteResponse) -> dict[str, Any]:
    return {
        "case_id": session_input.case_id,
        "session_number": session_input.session_number,
        "session_date": session_input.session_date or None,
        "session_title": _session_title(session_input),
        "raw_input_text": _raw_input_text(session_input) if settings.save_raw_input else None,
        "sanitized_input_text": json.dumps(
            result.sanitized_input.model_dump(mode="json"),
            ensure_ascii=False,
        ),
    }


def _stored_message() -> str:
    if settings.save_raw_input:
        return (
            "Generated note was stored in Supabase with masked raw_input_text because SAVE_RAW_INPUT=true. "
            "Use demo/synthetic data only unless consent, RLS, audit logging, and retention policy are in place."
        )
    return "Generated note was stored in Supabase without raw_input_text; sanitized input and metadata were stored."


def _masked(text: str) -> str:
    return deidentify_text(text)[0]


def _case_memory_rows_from_confirmed_note(request: ConfirmGeneratedNoteRequest) -> list[dict[str, Any]]:
    if not request.create_case_memory:
        return []
    sections = request.confirmed_note.get("sections") if isinstance(request.confirmed_note, dict) else {}
    if not isinstance(sections, dict):
        return []
    field_map = {
        "session_theme": "session_theme",
        "presenting_problem": "presenting_problem",
        "session_content": "session_content",
        "counselor_intervention": "counselor_intervention",
        "client_response": "client_response",
        "reflection": "reflection",
        "next_plan": "next_plan",
    }
    rows: list[dict[str, Any]] = []
    for field_name, field_type in field_map.items():
        text = _masked(str(sections.get(field_name) or "").strip())
        if not text:
            continue
        rows.append(
            {
                "counselor_id": request.counselor_id or request.confirmed_by or "server_demo_actor",
                "case_id": request.case_id,
                "session_id": request.session_id,
                "source_note_id": request.note_id,
                "session_number": request.session_number,
                "session_date": request.session_date or None,
                "field_type": field_type,
                "chunk_text": text,
                "source_ref": f"confirmed_note:{request.note_id}:{field_type}",
                "metadata_json": {
                    "confirmation_status": "demo_confirmed" if request.demo_confirmed else "confirmed",
                    "counselor_edited": request.counselor_edited,
                    "pii_masked": True,
                },
                "content_hash": content_hash(text, model=settings.embedding_model),
            }
        )
    return rows


def _attach_embeddings(rows: list[dict[str, Any]]) -> int:
    if not rows or not settings.enable_dense_retrieval:
        return 0
    try:
        provider = get_embedding_provider()
        embeddings = provider.embed([row["chunk_text"] for row in rows])
    except EmbeddingError:
        return 0
    for row, embedding in zip(rows, embeddings, strict=True):
        row["embedding"] = embedding
        row["embedding_model"] = settings.embedding_model
    return len(rows)
