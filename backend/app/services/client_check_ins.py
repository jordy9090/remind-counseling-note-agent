"""Client check-ins between sessions (내담자 수시 기록).

Every request uses the caller's JWT, so the database policies in
20261122000100_client_check_ins.sql decide what each party can read or write. Invite acceptance
and ending a link go through SECURITY DEFINER functions. Check-in text is never sent to an AI model.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from app.schemas.client_check_in import (
    CLIENT_CONSENT_VERSION,
    INVITE_VALID_DAYS,
    CheckIn,
    CheckInCreate,
    ClientInviteResponse,
    ClientLinkStatus,
    ClientMe,
)
from app.services.supabase_storage import SupabaseStorage, SupabaseStorageError, _require_owned_case, _storage_for_actor

LINKS = "client_links"
CHECK_INS = "client_check_ins"
LINK_COLUMNS = "id,case_id,status,created_at,invite_expires_at,accepted_at,ended_at,consented_at"
CHECK_IN_COLUMNS = "id,mood,emotions,note,created_at"
LIST_LIMIT = 200
MIGRATION_HINT = "내담자 기록 테이블이 아직 준비되지 않았습니다. migration 20261122000100_client_check_ins.sql을 적용해주세요."


class ClientCheckInError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _storage(actor: str) -> SupabaseStorage:
    storage = _storage_for_actor(actor)
    if not getattr(storage, "configured", False):
        raise ClientCheckInError(503, "Supabase가 설정되지 않아 내담자 기록을 사용할 수 없습니다.")
    return storage


def _translate(error: SupabaseStorageError) -> ClientCheckInError:
    code = getattr(error, "error_code", None)
    if code in {"42P01", "PGRST205", "PGRST202"}:
        return ClientCheckInError(503, MIGRATION_HINT)
    if code == "22023":
        return ClientCheckInError(410, "초대 링크가 만료되었거나 이미 사용되었습니다. 상담사에게 새 링크를 요청해주세요.")
    if code == "42501":
        return ClientCheckInError(409, "상담사 계정으로는 내담자 연결을 할 수 없습니다. 다른 이메일로 가입해주세요.")
    if code == "23505":
        return ClientCheckInError(409, "이미 상담사와 연결된 계정입니다.")
    if code == "P0002":
        return ClientCheckInError(404, "연결 정보를 찾을 수 없습니다.")
    if code == "28000":
        return ClientCheckInError(401, "로그인이 필요합니다.")
    return ClientCheckInError(502, "내담자 기록 저장소 요청을 처리하지 못했습니다.")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except SupabaseStorageError as error:
        raise _translate(error) from None


def _link_status(row: dict[str, Any]) -> ClientLinkStatus:
    return ClientLinkStatus(
        link_id=str(row["id"]), status=row["status"], created_at=row.get("created_at"),
        invite_expires_at=row.get("invite_expires_at"), accepted_at=row.get("accepted_at"),
        ended_at=row.get("ended_at"),
    )


def _check_in(row: dict[str, Any]) -> CheckIn:
    return CheckIn(id=str(row["id"]), mood=int(row["mood"]), emotions=list(row.get("emotions") or []),
                   note=str(row.get("note") or ""), created_at=str(row.get("created_at") or ""))


def _owned_case(storage: SupabaseStorage, case_id: str, actor: str) -> None:
    try:
        _require_owned_case(storage, case_id, actor)
    except SupabaseStorageError as error:
        if getattr(error, "error_code", None):
            raise _translate(error) from None
        # Missing and foreign cases look the same to the caller.
        raise ClientCheckInError(404, "해당 내담자를 찾을 수 없습니다.") from None


def _open_link(storage: SupabaseStorage, case_id: str) -> dict[str, Any] | None:
    rows = _call(storage.select, LINKS, {"select": LINK_COLUMNS, "case_id": f"eq.{case_id}",
                                         "status": "neq.ended", "order": "created_at.desc", "limit": 1})
    return rows[0] if rows else None


# --- Counselor -----------------------------------------------------------------------------------

def get_case_client_link(case_id: str, *, actor: str) -> ClientLinkStatus | None:
    storage = _storage(actor)
    _owned_case(storage, case_id, actor)
    row = _open_link(storage, case_id)
    return _link_status(row) if row else None


def create_client_invite(case_id: str, *, actor: str) -> ClientInviteResponse:
    """A new single-use invite. An unused earlier invite is revoked; an active link must end first."""
    storage = _storage(actor)
    _owned_case(storage, case_id, actor)
    existing = _open_link(storage, case_id)
    if existing and existing["status"] == "active":
        raise ClientCheckInError(409, "이미 연결된 내담자가 있습니다. 연결을 끊은 뒤 다시 초대해주세요.")
    if existing:
        _call(storage.rpc, "end_client_link", {"p_link_id": str(existing["id"])})
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(UTC) + timedelta(days=INVITE_VALID_DAYS)).isoformat()
    rows = _call(storage.insert, LINKS, [{
        "case_id": case_id, "user_id": str(actor), "status": "invited",
        "invite_token_hash": token_hash(token), "invite_expires_at": expires_at,
    }])
    if not rows:
        raise ClientCheckInError(502, "초대 링크를 만들지 못했습니다.")
    return ClientInviteResponse(link_id=str(rows[0]["id"]), token=token, expires_at=expires_at)


def end_case_client_link(case_id: str, *, actor: str) -> None:
    storage = _storage(actor)
    _owned_case(storage, case_id, actor)
    existing = _open_link(storage, case_id)
    if not existing:
        raise ClientCheckInError(404, "연결된 내담자나 사용 전 초대가 없습니다.")
    _call(storage.rpc, "end_client_link", {"p_link_id": str(existing["id"])})


def list_case_check_ins(case_id: str, *, actor: str) -> list[CheckIn]:
    """Entries from every link of this case (current and ended), newest first."""
    storage = _storage(actor)
    _owned_case(storage, case_id, actor)
    links = _call(storage.select, LINKS, {"select": "id", "case_id": f"eq.{case_id}"})
    ids = [str(row["id"]) for row in links]
    if not ids:
        return []
    rows = _call(storage.select, CHECK_INS, {"select": CHECK_IN_COLUMNS, "link_id": f"in.({','.join(ids)})",
                                             "order": "created_at.desc", "limit": LIST_LIMIT})
    return [_check_in(row) for row in rows]


# --- Client --------------------------------------------------------------------------------------

def accept_invite(token: str, consent_version: str, *, actor: str) -> ClientMe:
    if consent_version != CLIENT_CONSENT_VERSION:
        raise ClientCheckInError(409, "동의서가 바뀌었습니다. 화면을 새로고침한 뒤 다시 동의해주세요.")
    storage = _storage(actor)
    _call(storage.rpc, "accept_client_invite", {"p_token_hash": token_hash(token), "p_consent_version": consent_version})
    return client_me(actor=actor)


def _active_link(storage: SupabaseStorage, actor: str) -> dict[str, Any] | None:
    rows = _call(storage.select, LINKS, {"select": LINK_COLUMNS, "client_user_id": f"eq.{actor}",
                                         "status": "eq.active", "limit": 1})
    return rows[0] if rows else None


def client_me(*, actor: str) -> ClientMe:
    storage = _storage(actor)
    rows = _call(storage.select, LINKS, {"select": LINK_COLUMNS, "client_user_id": f"eq.{actor}",
                                         "order": "created_at.desc", "limit": 1})
    if not rows:
        return ClientMe(linked=False)
    row = rows[0]
    return ClientMe(linked=row["status"] == "active", status=row["status"], consented_at=row.get("consented_at"))


def create_check_in(payload: CheckInCreate, *, actor: str) -> CheckIn:
    storage = _storage(actor)
    link = _active_link(storage, actor)
    if not link:
        raise ClientCheckInError(409, "상담사와 연결되어 있지 않아 기록을 남길 수 없습니다.")
    rows = _call(storage.insert, CHECK_INS, [{
        "link_id": str(link["id"]), "client_user_id": str(actor),
        "mood": payload.mood, "emotions": payload.emotions, "note": payload.note,
    }])
    if not rows:
        raise ClientCheckInError(502, "기록을 저장하지 못했습니다.")
    return _check_in(rows[0])


def list_my_check_ins(*, actor: str) -> list[CheckIn]:
    storage = _storage(actor)
    rows = _call(storage.select, CHECK_INS, {"select": CHECK_IN_COLUMNS, "client_user_id": f"eq.{actor}",
                                             "order": "created_at.desc", "limit": LIST_LIMIT})
    return [_check_in(row) for row in rows]


def delete_my_check_in(check_in_id: str, *, actor: str) -> None:
    storage = _storage(actor)
    deleted = _call(storage.delete, CHECK_INS, query={"id": f"eq.{check_in_id}", "client_user_id": f"eq.{actor}"},
                    return_representation=True)
    if not deleted:
        raise ClientCheckInError(404, "기록을 찾을 수 없습니다.")


def end_my_link(*, actor: str) -> None:
    storage = _storage(actor)
    link = _active_link(storage, actor)
    if not link:
        raise ClientCheckInError(404, "연결된 상담사가 없습니다.")
    _call(storage.rpc, "end_client_link", {"p_link_id": str(link["id"])})
