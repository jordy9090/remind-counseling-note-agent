"""Supabase(PostgREST) 기반 상담 내용(임시저장 초안) 영구 저장소.

`draft_store` 가 Supabase 설정이 켜져 있을 때 위임해서 사용한다.
전체 초안 레코드는 `data` jsonb 컬럼에 그대로 저장하고, 조회/정렬용으로
draft_id / case_id / session_number / saved_at 컬럼을 함께 둔다.
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings
from app.schemas.note import TemporaryDraftRecord


@lru_cache(maxsize=1)
def _client():
    """Supabase 클라이언트(서비스 키 사용). 최초 호출 시에만 생성한다."""
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)


def _table():
    return _client().table(settings.supabase_drafts_table)


def _to_row(record: TemporaryDraftRecord) -> dict:
    return {
        "draft_id": record.draft_id,
        "case_id": record.case_id,
        "session_number": record.session_number,
        "saved_at": record.saved_at,
        "data": record.model_dump(mode="json"),
    }


def upsert_draft_row(record: TemporaryDraftRecord) -> None:
    """draft_id 기준으로 상담 초안을 생성하거나 갱신한다."""
    _table().upsert(_to_row(record), on_conflict="draft_id").execute()


def get_draft_row(draft_id: str) -> TemporaryDraftRecord | None:
    """draft_id 로 상담 초안 하나를 불러온다."""
    response = _table().select("data").eq("draft_id", draft_id).limit(1).execute()
    rows = response.data or []
    if not rows:
        return None
    return TemporaryDraftRecord(**rows[0]["data"])


def list_draft_rows(case_id: str | None = None) -> list[TemporaryDraftRecord]:
    """저장된 상담 초안을 최신순으로 반환한다. case_id 로 필터링 가능."""
    query = _table().select("data").order("saved_at", desc=True)
    if case_id:
        query = query.eq("case_id", case_id)
    response = query.execute()
    return [TemporaryDraftRecord(**row["data"]) for row in (response.data or [])]
