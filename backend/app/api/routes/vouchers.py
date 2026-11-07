"""Shared FastAPI/Vercel voucher routes; fail closed until qualification and migration."""
import os
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.security import require_preview_access, AuthenticatedActor
from app.schemas.voucher import MapRequest, PrepareRequest, ReviewRequest, ExportRequest
from app.services.voucher_documents import service
from app.services.voucher_renderer import VoucherError, bindings, manifest
from app.services import voucher_ari
from app.services.voucher_contract import FIELDS, WIDTH, MARGIN
from app.services.voucher_original import original_file
from app.services.supabase_storage import SupabaseStorageError, NoteConfirmationError

def private_response(response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'


router = APIRouter(prefix='/api/documents/vouchers', dependencies=[Depends(require_preview_access), Depends(private_response)])
def require_voucher_actor(actor: Annotated[str, Depends(require_preview_access)]):
    if not isinstance(actor, AuthenticatedActor):
        raise HTTPException(401, detail='로그인이 필요합니다.')
    return actor


Actor = Annotated[str, Depends(require_voucher_actor)]


async def call(fn, *args, **kwargs):
    if os.getenv('ENABLE_VOUCHER_DOCUMENTS', '0') != '1':
        raise HTTPException(503, detail={'code': 'NOT_ENABLED', 'message': '바우처 서식 내보내기를 준비하고 있습니다.'})
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except VoucherError as error:
        raise HTTPException(error.status, detail={'code': error.code, 'message': str(error), 'field': error.field}) from None
    except NoteConfirmationError:
        raise HTTPException(404, detail={'code': 'DOCUMENT_NOT_FOUND', 'message': '회기를 찾을 수 없습니다.'}) from None
    except ValidationError:
        raise HTTPException(422, detail={'code': 'INVALID_OUTPUT', 'message': '개인정보 처리 후 비어 있는 필수 항목을 수정해주세요.'}) from None
    except SupabaseStorageError:
        raise HTTPException(503, detail={'code': 'STORAGE_UNAVAILABLE', 'message': '문서를 저장하거나 불러오지 못했습니다.'}) from None


@router.get('/capabilities')
async def capabilities(actor: Actor):
    enabled = os.getenv('ENABLE_VOUCHER_DOCUMENTS', '0') == '1'
    standard = {}
    for template in ("form10", "form26"):
        standard[template] = {key: {"width": rect[2]-10, "size": 9, "maxLines": int((rect[3]-8)//11.25)}
                              for key, (_, rect) in bindings(template).items()}
    standard["form25"] = {key: {"width": WIDTH-2*MARGIN-20, "size": 10, "maxLines": 10} for key in FIELDS}
    return {"enabled": enabled, "formats": manifest()["qualification"],
            "layout": {"standard": standard, voucher_ari.EDITION: voucher_ari.metadata()["fields"]},
            "fontWidths": voucher_ari.font_profile()}


@router.get('/original/{format}')
async def original(format: Literal['pdf', 'hwpx'], actor: Actor):
    data = await call(original_file, format)
    return binary(data, 'original', format, inline=format == 'pdf')


@router.post('/map')
async def map_sources(request: MapRequest, actor: Actor):
    return await call(service.map_sources, actor, request)


@router.post('/prepare')
async def prepare(request: PrepareRequest, actor: Actor):
    return await call(service.prepare, actor, request)


@router.get('/saved')
async def list_documents(case_id: str, actor: Actor):
    return await call(service.list, actor, case_id)


@router.get('/saved/{document_id}')
async def get_document(document_id: UUID, actor: Actor):
    return await call(service.get, actor, str(document_id))


@router.delete('/saved/{document_id}', status_code=204)
async def delete_document(document_id: UUID, actor: Actor):
    await call(service.delete, actor, str(document_id))
    return Response(status_code=204)


def binary(data, document_id, format, inline=False):
    media = 'application/pdf' if format == 'pdf' else 'application/hwp+zip'
    disposition = 'inline' if inline else 'attachment'
    return Response(data, media_type=media, headers={'Content-Disposition': f'{disposition}; filename="remind_voucher_{document_id}.{format}"', 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/saved/{document_id}/preview')
async def preview(document_id: UUID, actor: Actor):
    data = await call(service.export, actor, str(document_id), 'pdf', preview=True)
    return binary(data, document_id, 'pdf', inline=True)


@router.post('/saved/{document_id}/review')
async def review(document_id: UUID, request: ReviewRequest, actor: Actor):
    return await call(service.review, actor, str(document_id), request)


@router.post('/saved/{document_id}/export')
async def export(document_id: UUID, request: ExportRequest, actor: Actor):
    data = await call(service.export, actor, str(document_id), request.format)
    return binary(data, document_id, request.format)
