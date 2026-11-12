"""Stateless, actor/purpose/body-bound review receipts and external-call boundary."""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.schemas.note import ConfirmGeneratedNoteRequest, RecomposeNoteRequest, SessionInput, SupervisionReportRequest
from app.services.quick_summary import QuickSummaryRequest
from app.services.deidentification_preview import preview_items
from app.services.qwen_deidentification import DetectionUnavailable, PendingDetection, detect_entities

Purpose = Literal["quick", "generate", "recompose", "supervision", "memory"]
MODELS = {"quick": QuickSummaryRequest, "generate": SessionInput, "recompose": RecomposeNoteRequest,
          "supervision": SupervisionReportRequest, "memory": ConfirmGeneratedNoteRequest}
# These values control storage, evidence references, or rendering; they are not source material.
INTERNAL = {"case_id", "note_id", "session_id", "draft_id", "target_document_type", "insight_lens",
            "visible_section_ids", "evidence_type", "source_refs", "transcript_mode", "attendance_status",
            "client_alias", "counselor_name", "session_date"}
LABELS = {"text": "상담 자료", "transcript_text": "축어록", "counselor_memo": "상담사 메모",
          "previous_session_summary": "이전 회기 요약", "counseling_goal": "상담 목표",
          "psychological_test_summary": "심리검사 요약", "nonverbal_notes": "비언어 관찰",
          "key_issue_tags": "핵심 이슈", "client_alias": "내담자 별칭", "counselor_name": "상담사 이름",
          "session_topic": "회기 주제", "session_date": "상담일"}
_approved: ContextVar[tuple[str, ...] | None] = ContextVar("reviewed_ai_material", default=None)
_prior_approved: ContextVar[list | None] = ContextVar("reviewed_prior_sessions", default=None)
INTERNAL.update({"source_ref", "prior_context_revision"})
LABELS.update({"prior_session_context": "이전 확정 회기 (자동 검색)", "summary": "이전 회기 요약",
               "confirmed_note": "이전 확정 기록"})


def _history_session(purpose: Purpose, payload: dict) -> dict | None:
    if purpose == "generate":
        return payload
    if purpose == "recompose":
        return payload["session_input"]
    return None


def _history_snapshot(session: dict, actor: str) -> list[dict]:
    """Read only the authenticated owner's prior confirmed notes through RLS."""
    from app.services.retrieval import retrieve_case_context
    from app.services.supabase_storage import _storage_for_actor
    if not settings.enable_rag or not getattr(actor, "access_token", ""):
        return []
    try:
        items = retrieve_case_context(session["case_id"], user_id=str(actor),
            current_session_number=session["session_number"], confirmed_only=True,
            storage_client=_storage_for_actor(actor))
        return [item.model_dump(exclude={"evidence_items"}) for item in items]
    except Exception:
        raise HTTPException(503, "이전 확정 회기를 불러오지 못했어요. 잠시 후 다시 시도해주세요.") from None


def reviewed_prior_sessions() -> list | None:
    """Return the receipt-validated snapshot, never caller-supplied context."""
    return _prior_approved.get()


class ReviewStart(BaseModel):
    purpose: Purpose
    payload: dict[str, Any]
    job_token: str = Field(default="", max_length=2000)


class SpanEdit(BaseModel):
    path: str = Field(max_length=500)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    original: str = Field(min_length=1, max_length=200)
    replacement: str = Field(min_length=1, max_length=200)


class ReviewConfirm(ReviewStart):
    detection_token: str = Field(max_length=2000)
    edits: list[SpanEdit] = Field(default_factory=list, max_length=20_000)


def canonical(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(payload: Any) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def normalize(purpose: Purpose, payload: dict) -> dict:
    try:
        normalized = MODELS[purpose].model_validate(payload).model_dump(mode="json")
        if len(canonical(normalized)) > 1_200_000:
            raise ValueError("Input too large")
        return normalized
    except (ValidationError, ValueError):
        raise HTTPException(422, "검토할 입력 형식을 확인해주세요.") from None


def sources(payload: Any, path: str = "", label: str = "상담 자료") -> list[dict[str, str]]:
    result = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key not in INTERNAL:
                escaped = key.replace("~", "~0").replace("/", "~1")
                result.extend(sources(value, f"{path}/{escaped}", LABELS.get(key, label)))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            result.extend(sources(value, f"{path}/{index}", label))
    elif isinstance(payload, str) and payload.strip():
        result.append({"key": path, "label": label, "text": payload})
    return result


def _key() -> bytes:
    if len(settings.deid_review_signing_key) < 32:
        raise HTTPException(503, "식별정보 검토 서비스 연결을 준비 중입니다.")
    return settings.deid_review_signing_key.encode()


def _sign(stage: str, purpose: Purpose, payload: dict, actor: str, *, job_id: str = "") -> str:
    claims = {"v": 1, "stage": stage, "purpose": purpose, "hash": digest(payload),
              "actor": hashlib.sha256(actor.encode()).hexdigest(), "exp": int(time.time()) + 3600, "job_id": job_id}
    encoded = base64.urlsafe_b64encode(canonical(claims)).decode().rstrip("=")
    signature = hmac.new(_key(), encoded.encode(), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _verify(token: str, stage: str, purpose: Purpose, payload: dict, actor: str):
    key = _key()
    try:
        encoded, signature = token.split(".")
        expected = hmac.new(key, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if (claims["v"] != 1 or claims["stage"] != stage or claims["purpose"] != purpose
                or claims["hash"] != digest(payload) or claims["exp"] < time.time()
                or claims["actor"] != hashlib.sha256(actor.encode()).hexdigest()):
            raise ValueError()
        return claims
    except (ValueError, KeyError, TypeError):
        raise HTTPException(409, "입력이 변경되었거나 확인 시간이 지났어요. AI 전달 내용을 다시 확인해주세요.") from None


def start_review(request: ReviewStart, actor: str) -> dict:
    _key()  # Do not start expensive work when receipts cannot be issued.
    payload = normalize(request.purpose, request.payload)
    session = _history_session(request.purpose, payload)
    if session is not None:
        # Re-read on pending-job polls too; a changed source invalidates that job's receipt.
        context = _history_snapshot(session, actor)
        session["prior_session_context"] = context
        session["prior_context_revision"] = digest(context) if settings.enable_rag else ""
    material = sources(payload)
    texts = [source["text"] for source in material]
    if len(material) > 500 or sum(map(len, texts)) > 200_000:
        raise HTTPException(422, "한 번에 확인할 수 있는 분량은 200,000자입니다.")
    session = payload.get("session_input", payload)
    job_id = None
    if request.job_token:
        job_id = _verify(request.job_token, "pending", request.purpose, payload, actor)["job_id"]
    try:
        model = detect_entities(texts, job_id=job_id)
    except DetectionUnavailable:
        raise HTTPException(503, "자체 서버에서 식별정보를 확인하지 못했어요. 입력은 유지됩니다. 잠시 후 다시 시도해주세요.") from None
    if isinstance(model, PendingDetection):
        return {"status": "pending", "job_token": _sign("pending", request.purpose, payload, actor, job_id=model.job_id)}
    local = preview_items(texts, client_name=session.get("client_alias", ""), counselor_name=session.get("counselor_name", ""))
    items = {item.original: item.model_dump() for item in local.items}
    labels = {"organization": "기관 정보 비공개", "location": "지역 정보 비공개", "birth_date": "생년월일 비공개",
              "contact": "연락처 비공개", "identifier": "식별번호 비공개"}
    person_index = 1
    used_labels = {item["replacement"] for item in items.values()}
    from app.services.korean_person_names import given_name
    for entity in sorted(model.entities, key=lambda value: len(value.original), reverse=True):
        if entity.original in items:
            continue
        if entity.category == "name":
            owners = {item["replacement"] for original, item in items.items()
                      if item["category"] == "name" and given_name(original) == entity.original}
            if len(owners) == 1:
                replacement = next(iter(owners))
            elif len(owners) > 1:
                replacement = "인물 확인 필요"
            else:
                while f"인물 {person_index}" in used_labels:
                    person_index += 1
                replacement = f"인물 {person_index}"
            used_labels.add(replacement)
        else:
            replacement = labels[entity.category]
        items[entity.original] = {"original": entity.original, "replacement": replacement, "category": entity.category}
    return {"payload": payload, "sources": material, "items": list(items.values()), "model_used": True,
            "detection_token": _sign("detected", request.purpose, payload, actor)}


def confirm_review(request: ReviewConfirm, actor: str) -> dict:
    payload = normalize(request.purpose, request.payload)
    _verify(request.detection_token, "detected", request.purpose, payload, actor)
    material = {source["key"]: source["text"] for source in sources(payload)}
    grouped: dict[str, list[SpanEdit]] = {}
    for edit in request.edits:
        if edit.path not in material:
            raise HTTPException(422, "확인 대상에 없는 항목입니다.")
        grouped.setdefault(edit.path, []).append(edit)
    output = copy.deepcopy(payload)
    for path, edits in grouped.items():
        text = material[path]
        end = 0
        for edit in sorted(edits, key=lambda value: value.start):
            if edit.start < end or edit.end <= edit.start or text[edit.start:edit.end] != edit.original:
                raise HTTPException(422, "치환할 원문 위치를 다시 확인해주세요.")
            end = edit.end
        for edit in sorted(edits, key=lambda value: value.start, reverse=True):
            text = text[:edit.start] + edit.replacement + text[edit.end:]
        parts = [part.replace("~1", "/").replace("~0", "~") for part in path.split("/")[1:]]
        parent = output
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        parent[int(parts[-1]) if isinstance(parent, list) else parts[-1]] = text
    output = normalize(request.purpose, output)
    return {"payload": output, "receipt": _sign("reviewed", request.purpose, output, actor)}


@contextmanager
def reviewed_request(purpose: Purpose, payload: BaseModel, receipt: str, actor: str):
    normalized = payload.model_dump(mode="json")
    prior = None
    if settings.require_deid_review:
        _verify(receipt, "reviewed", purpose, normalized, actor)
        session = _history_session(purpose, normalized)
        if settings.enable_rag and session is not None:
            # A receipt cannot resurrect a deleted or edited historical source.
            if session["prior_context_revision"] != digest(_history_snapshot(session, actor)):
                raise HTTPException(409, "이전 회기 기록이 변경되었어요. AI 전달 내용을 다시 확인해주세요.")
            from app.schemas.note import RetrievedCaseContextItem
            prior = [RetrievedCaseContextItem.model_validate(item) for item in session["prior_session_context"]]
    token = _approved.set(tuple(source["text"] for source in sources(normalized)))
    prior_token = _prior_approved.set(prior)
    try:
        yield
    finally:
        _prior_approved.reset(prior_token)
        _approved.reset(token)


def require_reviewed_egress():
    if settings.require_deid_review and _approved.get() is None:
        raise HTTPException(409, "AI에 전달할 내용을 먼저 확인해주세요.")


def prompt_material(value: Any) -> Any:
    """Metadata needed for local display/storage is unnecessary in external prompts."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return {key: prompt_material(item) for key, item in value.items()
                if key not in {"case_id", "client_alias", "counselor_name", "session_date", "sensitive_info_candidates"}}
    if isinstance(value, list):
        return [prompt_material(item) for item in value]
    return value


def embedding_is_reviewed(text: str) -> bool:
    if not settings.require_deid_review:
        return True
    # Stored legacy windows and arbitrary jobs have no implicit review authority.
    from app.services.storage_deidentification import deidentify_texts
    approved = _approved.get()
    if approved is None:
        return False
    masked, _ = deidentify_texts({str(index): text for index, text in enumerate(approved)})
    return any(text in source for source in [*approved, *masked.values()])
