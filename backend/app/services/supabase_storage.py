"""Small Supabase REST helpers for optional Re:mind persistence."""
from __future__ import annotations

import json
from dataclasses import dataclass
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


class NoteConfirmationError(RuntimeError):
    """Raised when a note confirmation request fails validation."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class ConfirmedNoteContext:
    note_id: str
    case_id: str
    session_id: str
    session_number: int
    session_date: str
    counselor_id: str
    confirmation_status: str = "confirmed"


class SupabaseStorage:
    """Minimal REST client that avoids making Supabase a hard dependency."""

    def __init__(self, timeout_seconds: int = 10, *, access_token: str | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.access_token = (access_token or "").strip()

    @property
    def configured(self) -> bool:
        if not settings.supabase_url:
            return False
        if self.access_token:
            return bool(settings.supabase_publishable_key or settings.supabase_anon_key)
        return bool(settings.effective_supabase_key)

    @property
    def persistence_enabled(self) -> bool:
        return settings.enable_persistence and self.configured

    @property
    def retrieval_enabled(self) -> bool:
        return settings.enable_rag and self.configured

    def select(self, table: str, query: dict[str, str | int]) -> list[dict[str, Any]]:
        result = self._request("GET", table, query=query)
        return result if isinstance(result, list) else []

    def maybe_single(self, table: str, query: dict[str, str | int]) -> dict[str, Any] | None:
        rows = self.select(table, {**query, "limit": 1})
        return rows[0] if rows else None

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
        if self.access_token:
            key = settings.supabase_publishable_key or settings.supabase_anon_key or ""
            bearer = self.access_token
        else:
            key = settings.effective_supabase_key or ""
            bearer = key
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {bearer}",
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


def _storage_for_actor(actor: str) -> SupabaseStorage:
    access_token = str(getattr(actor, "access_token", "") or "").strip()
    if not access_token:
        return storage
    return SupabaseStorage(timeout_seconds=storage.timeout_seconds, access_token=access_token)


def persist_generated_note(session_input: SessionInput, result: GenerateNoteResponse, *, actor: str = "server_demo_actor") -> PersistenceReport:
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
    actor_storage = _storage_for_actor(actor)
    if not getattr(actor_storage, "configured", settings.supabase_configured):
        report.message = "Supabase credentials are missing; generation returned without storage."
        return report

    try:
        existing_case = actor_storage.maybe_single(
            "cases",
            {"id": f"eq.{session_input.case_id}", "select": "id,user_id,counselor_id"},
        )
        if existing_case:
            owner = str(existing_case.get("user_id") or existing_case.get("counselor_id") or "").strip()
            if owner and owner != actor:
                raise SupabaseStorageError("동일한 케이스 ID가 다른 사용자에게 이미 등록되어 있습니다.")
        actor_storage.upsert(
            "cases",
            [
                {
                    "id": session_input.case_id,
                    "case_alias": session_input.case_id,
                    "counselor_id": actor or None,
                    "user_id": actor,
                    "status": "active",
                }
            ],
            on_conflict="id",
        )
        session_rows = actor_storage.upsert(
            "sessions",
            [_build_session_row(session_input, result, user_id=actor)],
            on_conflict="case_id,session_number",
        )
        session_id = str(session_rows[0]["id"]) if session_rows else None
        report.session_id = session_id

        note_rows = actor_storage.insert(
            "generated_notes",
            [
                {
                    "case_id": session_input.case_id,
                    "session_id": session_id,
                    "note_type": session_input.target_document_type,
                    "draft_json": result.session_summary_draft.model_dump(mode="json"),
                    "confirmed_json": {},
                    "counselor_edited": False,
                    "confirmation_status": "draft",
                    "user_id": actor,
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
                "user_id": actor,
            }
            for item in result.evidence_mapped_data.items
        ]
        if evidence_rows:
            actor_storage.insert("evidence_items", evidence_rows, return_representation=False)

        actor_storage.insert(
            "verification_reports",
            [
                {
                    "case_id": session_input.case_id,
                    "session_id": session_id,
                    "note_id": report.note_id,
                    "report_json": result.verification_report.model_dump(mode="json"),
                    "user_id": actor,
                }
            ],
            return_representation=False,
        )

        report.stored = True
        report.message = _stored_message()
    except Exception as error:
        report.message = f"Supabase persistence failed; generation response was preserved: {error}"
    return report


def confirm_generated_note(request: ConfirmGeneratedNoteRequest, *, actor: str = "server_demo_actor") -> ConfirmGeneratedNoteResponse:
    """Validate and persist explicit counselor confirmation from stored rows."""
    if not settings.enable_persistence:
        raise NoteConfirmationError(409, "ENABLE_PERSISTENCE is false; note confirmation is disabled.")
    actor_storage = _storage_for_actor(actor)
    if not getattr(actor_storage, "configured", settings.supabase_configured):
        raise NoteConfirmationError(503, "Supabase credentials are missing; note confirmation cannot be validated.")

    note = _fetch_generated_note(request.note_id, actor=actor, actor_storage=actor_storage)
    session = _fetch_session_for_note(note, actor=actor, actor_storage=actor_storage)
    case = _fetch_case_for_session(session, actor=actor, actor_storage=actor_storage)
    context = _confirmation_context(note=note, session=session, case_row=case, actor=actor)
    _validate_confirmation_status(note, request.confirmed_note, counselor_edited=request.counselor_edited)

    confirmed_at = datetime.now(UTC).isoformat()
    actor_storage.update(
        "generated_notes",
        {
            "confirmed_json": request.confirmed_note,
            "counselor_edited": request.counselor_edited,
            "confirmation_status": context.confirmation_status,
            "confirmed_at": confirmed_at,
            "confirmed_by": actor,
            "updated_at": confirmed_at,
        },
        query={"id": f"eq.{request.note_id}"},
        return_representation=False,
    )

    memory_chunk_count = 0
    embedding_count = 0
    if request.create_case_memory and settings.enable_case_memory:
        chunks = _case_memory_rows_from_confirmed_note(request, context)
        existing_chunks = _existing_memory_chunks_by_field(
            context.note_id,
            user_id=actor,
            actor_storage=actor_storage,
        )
        embedding_count = _attach_embeddings(chunks, existing_chunks=existing_chunks)
        if chunks:
            actor_storage.upsert("case_memory_chunks", chunks, on_conflict="source_note_id,field_type")
            actor_storage.update(
                "generated_notes",
                {"memory_indexed_at": datetime.now(UTC).isoformat()},
                query={"id": f"eq.{request.note_id}"},
                return_representation=False,
            )
        memory_chunk_count = len(chunks)

    if request.create_case_memory and not settings.enable_case_memory:
        message = "Confirmed note stored; case-memory indexing is disabled by ENABLE_CASE_MEMORY=0."
    else:
        message = "Confirmed note stored; case memory uses masked counselor-reviewed content only."

    return ConfirmGeneratedNoteResponse(
        note_id=request.note_id,
        confirmation_status="confirmed",
        confirmed_at=confirmed_at,
        memory_chunk_count=memory_chunk_count,
        memory_embedding_count=embedding_count,
        message=message,
    )


def _fetch_generated_note(
    note_id: str,
    *,
    actor: str,
    actor_storage: SupabaseStorage,
) -> dict[str, Any]:
    note = actor_storage.maybe_single(
        "generated_notes",
        {
            "id": f"eq.{note_id}",
            "user_id": f"eq.{actor}",
            "select": "id,case_id,session_id,note_type,draft_json,confirmed_json,confirmation_status,confirmed_by,user_id,created_at",
        },
    )
    if note is None:
        raise NoteConfirmationError(404, "Generated note was not found.")
    if not note.get("session_id"):
        raise NoteConfirmationError(409, "Generated note is missing a session_id and cannot be confirmed.")
    return note


def _fetch_session_for_note(
    note: dict[str, Any],
    *,
    actor: str,
    actor_storage: SupabaseStorage,
) -> dict[str, Any]:
    session_id = str(note.get("session_id") or "")
    session = actor_storage.maybe_single(
        "sessions",
        {
            "id": f"eq.{session_id}",
            "user_id": f"eq.{actor}",
            "select": "id,case_id,session_number,session_date,session_title,user_id",
        },
    )
    if session is None:
        raise NoteConfirmationError(409, "Generated note session was not found.")
    if str(note.get("case_id") or "") != str(session.get("case_id") or ""):
        raise NoteConfirmationError(409, "Generated note case_id does not match the stored session case_id.")
    return session


def _fetch_case_for_session(
    session: dict[str, Any],
    *,
    actor: str,
    actor_storage: SupabaseStorage,
) -> dict[str, Any]:
    case_id = str(session.get("case_id") or "")
    case = actor_storage.maybe_single(
        "cases",
        {
            "id": f"eq.{case_id}",
            "user_id": f"eq.{actor}",
            "select": "id,case_alias,counselor_id,user_id,status",
        },
    )
    if case is None:
        raise NoteConfirmationError(409, "Stored case for this note was not found.")
    return case


def _confirmation_context(
    *,
    note: dict[str, Any],
    session: dict[str, Any],
    case_row: dict[str, Any],
    actor: str,
) -> ConfirmedNoteContext:
    case_id = str(case_row.get("id") or "")
    if case_id != str(session.get("case_id") or ""):
        raise NoteConfirmationError(409, "Stored session does not belong to the fetched case.")
    stored_counselor_id = str(case_row.get("counselor_id") or "").strip()
    if stored_counselor_id and stored_counselor_id != actor:
        raise NoteConfirmationError(403, "This preview actor cannot confirm notes for the stored case.")
    return ConfirmedNoteContext(
        note_id=str(note["id"]),
        case_id=case_id,
        session_id=str(session["id"]),
        session_number=_as_int(session.get("session_number")) or 0,
        session_date=str(session.get("session_date") or ""),
        counselor_id=actor,
    )


def _validate_confirmation_status(
    note: dict[str, Any],
    confirmed_note: dict[str, Any],
    *,
    counselor_edited: bool,
) -> None:
    status = str(note.get("confirmation_status") or "draft")
    if status not in {"draft", "confirmed", "demo_confirmed"}:
        raise NoteConfirmationError(409, f"Generated note cannot be confirmed from status {status!r}.")
    if not isinstance(confirmed_note, dict) or not confirmed_note:
        raise NoteConfirmationError(422, "confirmed_note must contain the counselor-reviewed note sections.")
    if status in {"confirmed", "demo_confirmed"}:
        existing = note.get("confirmed_json") or {}
        if existing and _canonical_json(existing) != _canonical_json(confirmed_note) and not counselor_edited:
            raise NoteConfirmationError(
                409,
                "Generated note is already confirmed with different content; mark counselor_edited=true or use a revision flow.",
            )


def _canonical_json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _build_session_row(session_input: SessionInput, result: GenerateNoteResponse, *, user_id: str) -> dict[str, Any]:
    return {
        "case_id": session_input.case_id,
        "user_id": user_id,
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


def _case_memory_rows_from_confirmed_note(
    request: ConfirmGeneratedNoteRequest,
    context: ConfirmedNoteContext,
) -> list[dict[str, Any]]:
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
                "counselor_id": context.counselor_id,
                "user_id": context.counselor_id,
                "case_id": context.case_id,
                "session_id": context.session_id,
                "source_note_id": context.note_id,
                "session_number": context.session_number,
                "session_date": context.session_date or None,
                "field_type": field_type,
                "chunk_text": text,
                "source_ref": f"confirmed_note:{context.note_id}:{field_type}",
                "metadata_json": {
                    "confirmation_status": context.confirmation_status,
                    "counselor_edited": request.counselor_edited,
                    "pii_masked": True,
                },
                "content_hash": content_hash(text, model=settings.embedding_model),
            }
        )
    return rows


def _existing_memory_chunks_by_field(
    note_id: str,
    *,
    user_id: str,
    actor_storage: SupabaseStorage,
) -> dict[str, dict[str, Any]]:
    rows = actor_storage.select(
        "case_memory_chunks",
        {
            "source_note_id": f"eq.{note_id}",
            "user_id": f"eq.{user_id}",
            "select": "id,field_type,content_hash,embedding_model,embedding",
            "limit": 100,
        },
    )
    return {str(row.get("field_type") or ""): row for row in rows if row.get("field_type")}


def _attach_embeddings(
    rows: list[dict[str, Any]],
    *,
    existing_chunks: dict[str, dict[str, Any]] | None = None,
) -> int:
    if not rows or not settings.enable_dense_retrieval:
        return 0
    existing_chunks = existing_chunks or {}
    pending_rows = [
        row
        for row in rows
        if _memory_row_needs_embedding(row, existing_chunks.get(str(row.get("field_type") or "")))
    ]
    if not pending_rows:
        return 0
    try:
        provider = get_embedding_provider()
        embeddings = provider.embed([row["chunk_text"] for row in pending_rows])
    except EmbeddingError:
        return 0
    for row, embedding in zip(pending_rows, embeddings, strict=True):
        row["embedding"] = embedding
        row["embedding_model"] = settings.embedding_model
        row["embedding_updated_at"] = datetime.now(UTC).isoformat()
    return len(pending_rows)


def _memory_row_needs_embedding(row: dict[str, Any], existing: dict[str, Any] | None) -> bool:
    if not existing:
        return True
    return (
        existing.get("content_hash") != row.get("content_hash")
        or existing.get("embedding_model") != settings.embedding_model
        or not existing.get("embedding")
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
