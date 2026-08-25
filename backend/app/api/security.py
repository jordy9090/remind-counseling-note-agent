"""Temporary API access controls for public preview deployments."""
from __future__ import annotations

import secrets
import json
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import Header, HTTPException

from app.core.config import settings


PreviewTokenHeader = Annotated[str | None, Header(alias="X-Remind-Preview-Token")]
AuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]


class AuthenticatedActor(str):
    """User id that also carries the verified JWT for downstream RLS requests."""

    access_token: str

    def __new__(cls, user_id: str, access_token: str):
        actor = super().__new__(cls, user_id)
        actor.access_token = access_token
        return actor


def require_preview_access(
    x_remind_preview_token: PreviewTokenHeader = None,
    authorization: AuthorizationHeader = None,
) -> str:
    """Return the authenticated user id, or use the explicitly enabled legacy guard."""
    if settings.enable_real_user_auth:
        return _require_supabase_user(authorization)
    if settings.local_preview_bypass_enabled:
        return settings.remind_preview_actor

    if not settings.allow_legacy_preview_token:
        raise HTTPException(status_code=503, detail="사용자 인증이 아직 설정되지 않았습니다.")

    configured_token = settings.remind_preview_api_token or ""
    if not configured_token:
        raise HTTPException(status_code=401, detail="Preview API token is not configured.")
    if not x_remind_preview_token:
        raise HTTPException(status_code=401, detail="Missing preview API token.")
    if not secrets.compare_digest(configured_token, x_remind_preview_token):
        raise HTTPException(status_code=401, detail="Invalid preview API token.")
    return settings.remind_preview_actor


def _require_supabase_user(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    api_key = settings.effective_supabase_auth_key
    if not settings.supabase_url or not api_key:
        raise HTTPException(status_code=503, detail="인증 서버 환경변수가 설정되지 않았습니다.")

    request = Request(
        f"{settings.normalized_supabase_url}/auth/v1/user",
        headers={"apikey": api_key, "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=8) as response:  # noqa: S310 - configured Supabase HTTPS origin
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code in {401, 403}:
            raise HTTPException(status_code=401, detail="로그인 세션이 만료되었거나 유효하지 않습니다.") from error
        raise HTTPException(status_code=503, detail="인증 서버 응답을 확인할 수 없습니다.") from error
    except (URLError, TimeoutError, ValueError) as error:
        raise HTTPException(status_code=503, detail="인증 서버에 연결할 수 없습니다.") from error

    user_id = str(payload.get("id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="유효한 사용자 정보를 확인하지 못했습니다.")
    return AuthenticatedActor(user_id, token)
