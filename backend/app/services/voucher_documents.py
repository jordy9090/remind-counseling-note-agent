"""Owned, immutable review snapshots for voucher exports.

Edits create a new candidate rather than modifying a reviewed document. The server
reads confirmed notes, sanitizes only narrative fields, and renders stored values.
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
import unicodedata
from uuid import uuid4

from app.schemas.voucher import VoucherForm
from app.services import supabase_storage as db
from app.services.storage_deidentification import deidentify_texts
from app.services.voucher_renderer import VoucherError, manifest, paragraphs, render_pdf, render_hwpx, verify_assets

TABLE = 'voucher_documents'
POLICY = 'storage-deidentification-v1'


def digest(value):
    return sha256(unicodedata.normalize('NFC', json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))).encode()).hexdigest()


def confirmed_fields(note):
    if note.confirmation_status != 'confirmed' or note.note_type != 'session_note':
        raise VoucherError('SOURCE_NOT_CONFIRMED', '검토 완료된 회기 요약만 가져올 수 있습니다.')
    payload = note.confirmed_json
    allowed = ('session_content', 'counselor_intervention', 'client_response')
    if not isinstance(payload, dict):
        raise VoucherError('SOURCE_MALFORMED', '확정 기록의 항목 형식을 확인해주세요.')
    if 'workspace_sections' in payload:
        rows = payload['workspace_sections']
        if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('content'), str) or not isinstance(r.get('visible'), bool) for r in rows):
            raise VoucherError('SOURCE_MALFORMED', '확정 기록의 항목 형식을 확인해주세요.')
        ids = [r.get('id') for r in rows]
        if any(not isinstance(key, str) for key in ids) or len(ids) != len(set(ids)):
            raise VoucherError('SOURCE_MALFORMED', '확정 기록의 항목 형식을 확인해주세요.')
        return {key: next((r['content'] for r in rows if r.get('id') == key and r['visible']), '') for key in allowed}
    fields = {}
    for key in allowed:
        if key in payload:
            value = payload[key]
        else:
            legacy = payload.get('sections', {})
            if not isinstance(legacy, dict):
                raise VoucherError('SOURCE_MALFORMED', '확정 기록의 항목 형식을 확인해주세요.')
            value = legacy.get(key, '')
        if isinstance(value, dict):
            value = value.get('text')
        if not isinstance(value, str):
            raise VoucherError('SOURCE_MALFORMED', '확정 기록의 항목 형식을 확인해주세요.')
        fields[key] = value
    return fields


class VoucherDocuments:
    def owned_case(self, actor, case_id):
        row = db._require_owned_case(db._storage_for_actor(actor), case_id, actor)
        if str(row.get('user_id') or row.get('counselor_id') or '') != str(actor):
            raise VoucherError('DOCUMENT_NOT_FOUND', '내담자를 찾을 수 없습니다.', 404)
        return row

    def sources(self, actor, case_id, selections):
        fields, hashes = {}, {}
        for source in selections:
            note = db.fetch_generated_note(str(source.note_id), actor=actor, include_input=False)
            if note.case_id != case_id:
                raise VoucherError('DOCUMENT_NOT_FOUND', '같은 내담자의 회기만 선택해주세요.', 404)
            used = confirmed_fields(note)
            fields[str(source.note_id)] = used
            hashes[str(source.note_id)] = digest({'note': note.note_id, 'session': note.session_id, 'case': case_id, 'fields': used, 'adapter': 1})
        return fields, hashes

    def map_sources(self, actor, request):
        self.owned_case(actor, request.case_id)
        fields, hashes = self.sources(actor, request.case_id, request.sources)
        rows = []
        for source in request.sources:
            used = fields[str(source.note_id)]
            rows.append({**source.model_dump(mode='json'), 'content_left': used['session_content'],
                         'content_right': '\n'.join(value for key, value in used.items() if key != 'session_content' and value)})
        return {'rows': rows, 'source_hashes': hashes}

    def get(self, actor, document_id):
        row = db.storage.maybe_single(TABLE, {'id': f'eq.{document_id}', 'user_id': f'eq.{actor}'})
        if not row:
            raise VoucherError('DOCUMENT_NOT_FOUND', '문서를 찾을 수 없습니다.', 404)
        self.owned_case(actor, row['case_id'])
        return row

    def list(self, actor, case_id):
        self.owned_case(actor, case_id)
        return db.storage.select(TABLE, {'case_id': f'eq.{case_id}', 'user_id': f'eq.{actor}', 'select': 'id,template,created_at,reviewed_at', 'order': 'created_at.desc', 'limit': 100})

    def prepare(self, actor, request):
        case = self.owned_case(actor, request.case_id)
        request_hash = digest(request.model_dump(mode='json'))
        query = {'user_id': f'eq.{actor}', 'operation_key': f'eq.{request.operation_key}'}
        previous = db.storage.maybe_single(TABLE, query)
        if previous:
            if previous['request_hash'] != request_hash:
                raise VoucherError('IDEMPOTENCY_KEY_REUSED', '변경된 내용은 새로 미리보기를 만들어주세요.', 409)
            return previous
        _, hashes = self.sources(actor, request.case_id, request.form.rows)
        if hashes != request.source_hashes:
            raise VoucherError('SOURCE_CHANGED', '확정 기록이 바뀌었습니다. 회기를 다시 가져와주세요.', 409)
        data = request.form.model_dump(mode='json')
        # Never transform ids, dates, explicit voucher numbers, or service tier.
        texts = {key: value for key, value in data.items() if isinstance(value, str) and key not in {'template', 'report_month', 'service_tier'}}
        for index, row in enumerate(data['rows']):
            for key in ('content_left', 'content_right'):
                texts[f'rows/{index}/{key}'] = row[key]
        sanitized, report = deidentify_texts(texts, known_names=[case.get('case_alias') or ''])
        for key, value in sanitized.items():
            if key.startswith('rows/'):
                _, index, field = key.split('/')
                data['rows'][int(index)][field] = value
            else:
                data[key] = value
        form = VoucherForm.model_validate(data)
        verify_assets()
        paragraphs(form)
        snapshot = {'form': form.model_dump(mode='json'), 'sources': hashes, 'policy': POLICY, 'template_bundle': digest(manifest())}
        row = {'id': str(uuid4()), 'case_id': request.case_id, 'user_id': str(actor), 'operation_key': str(request.operation_key),
               'request_hash': request_hash, 'template': form.template, 'snapshot': snapshot, 'fingerprint': digest(snapshot),
               'privacy_status': 'applied' if report.llm_used else 'degraded'}
        try:
            return db.storage.insert(TABLE, [row])[0]
        except db.SupabaseStorageError:
            # Concurrent identical requests may race on the durable unique key.
            existing = db.storage.maybe_single(TABLE, query)
            if existing and existing['request_hash'] == request_hash:
                return existing
            raise

    def review(self, actor, document_id, request):
        row = self.get(actor, document_id)
        if row['fingerprint'] != request.fingerprint or digest(row['snapshot']) != request.fingerprint:
            raise VoucherError('REVIEW_CHANGED', '출력 내용을 다시 확인해주세요.', 409)
        if row.get('reviewed_at'):
            return row
        if row['snapshot']['policy'] != POLICY or row['snapshot']['template_bundle'] != digest(manifest()):
            raise VoucherError('POLICY_VERSION_CHANGED', '출력 정책이 바뀌었습니다. 새 미리보기를 만들어주세요.', 409)
        form = VoucherForm.model_validate(row['snapshot']['form'])
        _, hashes = self.sources(actor, row['case_id'], form.rows)
        if hashes != row['snapshot']['sources']:
            raise VoucherError('SOURCE_CHANGED', '확정 기록이 바뀌었습니다. 새 미리보기를 만들어주세요.', 409)
        values = {'reviewed_at': datetime.now(timezone.utc).isoformat(), 'reviewed_by': str(actor)}
        rows = db.storage.update(TABLE, values, query={'id': f'eq.{document_id}', 'user_id': f'eq.{actor}', 'reviewed_at': 'is.null'})
        return rows[0] if rows else self.get(actor, document_id)

    def export(self, actor, document_id, format, preview=False):
        row = self.get(actor, document_id)
        if not preview and not row.get('reviewed_at'):
            raise VoucherError('REVIEW_REQUIRED', '먼저 출력 내용 검토를 완료해주세요.', 409)
        snapshot = row['snapshot']
        if digest(snapshot) != row['fingerprint'] or snapshot['template_bundle'] != digest(manifest()):
            raise VoucherError('TEMPLATE_VERSION_UNAVAILABLE', '이 문서 버전의 서식을 확인할 수 없습니다.', 409)
        if format == 'hwpx' and not manifest()['qualification']['hwpx']:
            raise VoucherError('FORMAT_NOT_QUALIFIED', '한글 앱 호환성 확인 후 제공할 예정입니다.', 503)
        form = VoucherForm.model_validate(snapshot['form'])
        return render_pdf(form) if format == 'pdf' else render_hwpx(form)

    def delete(self, actor, document_id):
        self.get(actor, document_id)
        db.storage.delete(TABLE, query={'id': f'eq.{document_id}', 'user_id': f'eq.{actor}'})


service = VoucherDocuments()
