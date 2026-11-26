"""Routes for client check-ins between sessions (내담자 수시 기록).

Counselor routes use the counselor guard (client accounts are refused). Client routes accept
only accounts that joined through an invite, except accepting the invite itself.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.security import AuthenticatedActor, require_client_user, require_preview_access, require_signed_in_user
from app.schemas.client_check_in import (
    AcceptInviteRequest,
    CheckIn,
    CheckInCreate,
    ClientInviteResponse,
    ClientLinkStatus,
    ClientMe,
)
from app.services import client_check_ins as service
from app.services.client_check_ins import ClientCheckInError

counselor_router = APIRouter(prefix="/api/cases", tags=["client-check-ins"])
client_router = APIRouter(prefix="/api/client", tags=["client-check-ins"])

Counselor = Annotated[str, Depends(require_preview_access)]
SignedIn = Annotated[AuthenticatedActor, Depends(require_signed_in_user)]
Client = Annotated[AuthenticatedActor, Depends(require_client_user)]


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ClientCheckInError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from None


@counselor_router.get("/{case_id}/client-link", response_model=ClientLinkStatus | None)
async def get_client_link(case_id: str, actor: Counselor) -> ClientLinkStatus | None:
    """현재 사용 전 초대 또는 연결된 내담자 상태 (없으면 null)."""
    return _run(service.get_case_client_link, case_id, actor=actor)


@counselor_router.post("/{case_id}/client-invites", response_model=ClientInviteResponse, status_code=201)
async def create_client_invite(case_id: str, actor: Counselor) -> ClientInviteResponse:
    """한 번만 쓸 수 있는 초대 링크 토큰을 만든다. 이전 미사용 초대는 취소된다."""
    return _run(service.create_client_invite, case_id, actor=actor)


@counselor_router.post("/{case_id}/client-link/end", status_code=204)
async def end_client_link(case_id: str, actor: Counselor) -> Response:
    """연결을 끊거나 사용 전 초대를 취소한다."""
    _run(service.end_case_client_link, case_id, actor=actor)
    return Response(status_code=204)


@counselor_router.get("/{case_id}/check-ins", response_model=list[CheckIn])
async def list_case_check_ins(case_id: str, actor: Counselor) -> list[CheckIn]:
    """내담자가 남긴 회기 사이 기록 (최신순, 읽기 전용)."""
    return _run(service.list_case_check_ins, case_id, actor=actor)


@client_router.post("/invites/accept", response_model=ClientMe)
async def accept_invite(request: AcceptInviteRequest, actor: SignedIn) -> ClientMe:
    """초대 링크와 동의로 이 계정을 내담자로 연결한다."""
    return _run(service.accept_invite, request.token, request.consent_version, actor=actor)


@client_router.get("/me", response_model=ClientMe)
async def get_me(actor: Client) -> ClientMe:
    return _run(service.client_me, actor=actor)


@client_router.get("/check-ins", response_model=list[CheckIn])
async def list_my_check_ins(actor: Client) -> list[CheckIn]:
    return _run(service.list_my_check_ins, actor=actor)


@client_router.post("/check-ins", response_model=CheckIn, status_code=201)
async def create_check_in(payload: CheckInCreate, actor: Client) -> CheckIn:
    return _run(service.create_check_in, payload, actor=actor)


@client_router.delete("/check-ins/{check_in_id}", status_code=204)
async def delete_check_in(check_in_id: UUID, actor: Client) -> Response:
    _run(service.delete_my_check_in, str(check_in_id), actor=actor)
    return Response(status_code=204)


@client_router.post("/link/end", status_code=204)
async def end_my_link(actor: Client) -> Response:
    _run(service.end_my_link, actor=actor)
    return Response(status_code=204)
