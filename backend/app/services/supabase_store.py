"""RLS-aware Supabase storage for temporary counseling drafts.

Production requests use the authenticated user's verified JWT with the public
Supabase key. A service-role key is only an optional server-side fallback for
legacy/local workflows and is never required by the browser-facing deployment.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings
from app.schemas.note import TemporaryDraftRecord


class DraftStorageError(RuntimeError):
    """Raised when the user-scoped Supabase draft request fails."""


def configured_for(actor: str) -> bool:
    """Return whether this request has credentials suitable for persistence."""
    return bool(
        settings.supabase_url
        and (
            (getattr(actor, "access_token", "") and _public_key())
            or settings.effective_supabase_key
        )
    )


def _public_key() -> str | None:
    return settings.supabase_publishable_key or settings.supabase_anon_key


def _credentials(actor: str) -> tuple[str, str]:
    user_token = str(getattr(actor, "access_token", "") or "").strip()
    if user_token and _public_key():
        return str(_public_key()), user_token
    service_key = str(settings.effective_supabase_key or "").strip()
    if service_key:
        return service_key, service_key
    raise DraftStorageError("Supabase draft storage credentials are not configured.")


def _request(
    method: str,
    actor: str,
    *,
    query: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    prefer: str | None = None,
) -> Any:
    api_key, bearer = _credentials(actor)
    query_string = f"?{urlencode(query)}" if query else ""
    url = f"{settings.normalized_supabase_url}/rest/v1/{settings.supabase_drafts_table}{query_string}"
    headers = {
        "apikey": api_key,
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
        with urlopen(request, timeout=10) as response:  # noqa: S310 - configured Supabase HTTPS origin
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise DraftStorageError(f"Supabase draft request failed with {error.code}: {detail}") from error
    except (URLError, TimeoutError) as error:
        raise DraftStorageError("Supabase draft storage is temporarily unavailable.") from error
    return json.loads(payload) if payload else None


def _to_row(record: TemporaryDraftRecord, *, user_id: str) -> dict[str, Any]:
    return {
        "draft_id": _scoped_draft_id(record.draft_id, user_id=user_id),
        "case_id": record.case_id,
        "session_number": record.session_number,
        "saved_at": record.saved_at,
        "data": record.model_dump(mode="json"),
        "user_id": user_id,
    }


def upsert_draft_row(record: TemporaryDraftRecord, *, actor: str) -> None:
    """Create or update a draft through the authenticated user's RLS context."""
    _request(
        "POST",
        actor,
        query={"on_conflict": "draft_id"},
        body=_to_row(record, user_id=str(actor)),
        prefer="resolution=merge-duplicates,return=minimal",
    )


def get_draft_row(draft_id: str, *, actor: str) -> TemporaryDraftRecord | None:
    """Load one draft using both its tenant-scoped key and RLS owner."""
    rows = _request(
        "GET",
        actor,
        query={
            "select": "data",
            "draft_id": f"eq.{_scoped_draft_id(draft_id, user_id=str(actor))}",
            "user_id": f"eq.{str(actor)}",
            "limit": "1",
        },
    ) or []
    if not rows:
        return None
    return TemporaryDraftRecord(**rows[0]["data"])


def list_draft_rows(*, actor: str, case_id: str | None = None) -> list[TemporaryDraftRecord]:
    """List only drafts visible to the authenticated user's RLS context."""
    query = {
        "select": "data",
        "user_id": f"eq.{str(actor)}",
        "order": "saved_at.desc",
    }
    if case_id:
        query["case_id"] = f"eq.{case_id}"
    rows = _request("GET", actor, query=query) or []
    return [TemporaryDraftRecord(**row["data"]) for row in rows]


def _scoped_draft_id(draft_id: str, *, user_id: str) -> str:
    """Make a stable database key that cannot collide across users."""
    digest = hashlib.sha256(f"{user_id}:{draft_id}".encode("utf-8")).hexdigest()
    return f"draft_{digest}"
