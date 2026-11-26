"""Fresh, case-bound processing permission checks for the registered PoC cohort.

The RPC reads operator-managed Auth app metadata and the existing beta lifecycle.
Neither a browser checkbox nor a masking-review receipt grants this permission.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException

from app.api.security import AuthenticatedActor
from app.core.config import settings


_scope: ContextVar[tuple | None] = ContextVar("case_processing_scope", default=None)


def _authorization_rpc(actor: AuthenticatedActor, params: dict) -> bool:
    from app.services.supabase_storage import SupabaseStorage
    return SupabaseStorage(access_token=actor.access_token).rpc("case_processing_allowed", params)


def require_case_processing(actor: str, case_id: str, purpose: str, provider: str) -> None:
    if not settings.poc_mode:
        return
    if not isinstance(actor, AuthenticatedActor) or not actor.access_token:
        raise HTTPException(401, "로그인 후 다시 시도해주세요.")
    policy = settings.processing_authorization_policy
    if not policy:
        raise HTTPException(503, "자료 처리 승인 절차를 준비 중입니다.")
    if not case_id or not isinstance(case_id, str):
        raise HTTPException(403, "처리가 승인된 사례를 선택해주세요.")
    try:
        allowed = _authorization_rpc(actor, {
            "p_case_id": case_id, "p_policy_version": policy,
            "p_purpose": purpose, "p_provider": provider,
        })
    except Exception:
        raise HTTPException(503, "자료 처리 권한을 확인하지 못했습니다. 잠시 후 다시 시도해주세요.") from None
    if allowed is not True:
        raise HTTPException(403, "이 사례의 처리 동의 범위와 유효기간을 확인해주세요.")


def processing_case(purpose: str, payload: dict, actor: str) -> str:
    if purpose == "memory" and settings.poc_mode:
        # Resolve only ownership metadata through the caller's JWT, not note bodies.
        from app.services.supabase_storage import _storage_for_actor
        try:
            row = _storage_for_actor(actor).maybe_single("generated_notes", {
                "id": f"eq.{payload['note_id']}", "user_id": f"eq.{actor}",
                "select": "case_id,user_id", "limit": 1,
            })
        except Exception:
            raise HTTPException(503, "사례의 처리 권한을 확인하지 못했습니다.") from None
        if not row or row.get("user_id") != str(actor):
            raise HTTPException(403, "처리가 승인된 사례를 선택해주세요.")
        return row.get("case_id", "")
    return payload.get("session_input", payload).get("case_id", "")


@contextmanager
def authorized_processing(actor: str, case_id: str, purpose: str, provider: str):
    require_case_processing(actor, case_id, purpose, provider)
    token = _scope.set((actor, case_id, purpose))
    try:
        yield
        # A withdrawn/expired request must not return a newly generated result.
        require_case_processing(actor, case_id, purpose, provider)
    finally:
        _scope.reset(token)


def require_processing_egress(provider: str) -> None:
    if not settings.poc_mode:
        return
    scope = _scope.get()
    if scope is None:
        raise HTTPException(403, "사례별 처리 권한을 먼저 확인해주세요.")
    require_case_processing(*scope, provider)
