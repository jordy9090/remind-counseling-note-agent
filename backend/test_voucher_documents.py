"""Synthetic voucher contract tests. No external auth, database or model calls."""
from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
from unittest import TestCase, main
from unittest.mock import patch
from zipfile import ZipFile

from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfReader
from lxml import etree as ET

from app.api.security import AuthenticatedActor, require_preview_access
from app.schemas.voucher import VoucherForm, MapRequest, PrepareRequest, ReviewRequest
from app.services.voucher_documents import service, confirmed_fields, digest
from app.services.voucher_renderer import VoucherError, render_pdf, render_hwpx, paragraphs, manifest, NS

NOTE = '00000000-0000-4000-8000-000000000010'
OWNER = AuthenticatedActor('00000000-0000-4000-8000-000000000001', 'synthetic-only')
CASE = 'SYNTHETIC-VOUCHER'


def selection(**changes):
    return dict(note_id=NOTE, voucher_session_no=1, actual_service_date='2026-10-01', delivered_attested=True, **changes)


def record():
    return VoucherForm(template='form10', report_month='2026-10', rows=[{**selection(), 'content_left': '합성사례: 업무 중 긴장을 탐색함.', 'content_right': '감정을 구분하고 호흡을 연습함.'}])


def plan():
    return VoucherForm(template='form26', report_month='2026-10', purpose='정서 이해를 돕는다.', content='감정과 대처방식을 탐색한다.', plan_left='상담 목표를 함께 정한다.')


def note(payload=None):
    return SimpleNamespace(note_id=NOTE, session_id='synthetic-session', case_id=CASE, note_type='session_note', confirmation_status='confirmed',
                           confirmed_json=payload if payload is not None else {'session_content': '합성사례: 업무 중 긴장을 탐색함.', 'counselor_intervention': '감정을 구분함.', 'client_response': '호흡을 연습함.'})


class MemoryStorage:
    """HTTP/service test double, not evidence that PostgreSQL policies passed."""
    def __init__(self):
        self.rows = []

    def select(self, table, query):
        assert table == 'voucher_documents'
        def matches(row):
            return all((row.get(k) is None if v == 'is.null' else str(row.get(k)) == v[3:]) for k, v in query.items() if isinstance(v, str) and (v.startswith('eq.') or v == 'is.null'))
        return deepcopy([r for r in self.rows if matches(r)])

    def maybe_single(self, table, query):
        rows = self.select(table, query)
        return rows[0] if rows else None

    def insert(self, table, rows):
        for row in rows:
            self.rows.append({**deepcopy(row), 'created_at': '2026-10-30T00:00:00Z', 'reviewed_at': None, 'reviewed_by': None})
        return deepcopy(self.rows[-len(rows):])

    def update(self, table, values, query):
        ids = {r['id'] for r in self.select(table, query)}
        for row in self.rows:
            if row['id'] in ids:
                row.update(values)
        return deepcopy([r for r in self.rows if r['id'] in ids])

    def delete(self, table, query):
        ids = {r['id'] for r in self.select(table, query)}
        self.rows[:] = [r for r in self.rows if r['id'] not in ids]


class MappingTests(TestCase):
    def test_authoritative_sections_do_not_restore_hidden_deleted_or_empty_content(self):
        payload = {'session_content': 'stale', 'client_response': 'stale', 'reflection': 'private', 'workspace_sections': [
            {'id': 'session_content', 'content': '', 'visible': True},
            {'id': 'counselor_intervention', 'content': 'hidden', 'visible': False},
            {'id': 'reflection', 'content': 'private', 'visible': True},
        ]}
        self.assertEqual(confirmed_fields(note(payload)), dict(session_content='', counselor_intervention='', client_response=''))

    def test_legacy_payload_and_explicit_empty(self):
        result = confirmed_fields(note({'session_content': '', 'sections': {'session_content': 'stale', 'client_response': {'text': '확인된 반응'}}}))
        self.assertEqual(result['session_content'], '')
        self.assertEqual(result['client_response'], '확인된 반응')

    def test_unconfirmed_and_malformed_sources_fail_closed(self):
        source = note(); source.confirmation_status = 'draft'
        with self.assertRaises(VoucherError): confirmed_fields(source)
        for value in [[], {'sections': []}, {'session_content': None}, {'workspace_sections': None}, {'workspace_sections': [{'id': 'session_content', 'content': 'x'}]}]:
            with self.subTest(value=value), self.assertRaises(VoucherError): confirmed_fields(note(value))

    def test_duplicate_wrong_month_future_and_unattested_dates_rejected(self):
        base = record().model_dump(mode='json')
        variants = [dict(base, rows=base['rows'] * 2), dict(base, report_month='2026-09')]
        for field, value in [('delivered_attested', False), ('actual_service_date', (date.today()+timedelta(days=3)).isoformat()), ('voucher_session_no', 9)]:
            variants.append({**base, 'rows': [{**base['rows'][0], field: value}]})
        for value in variants:
            with self.assertRaises(ValidationError): VoucherForm.model_validate(value)

    def test_unrendered_fields_cannot_be_hidden_in_snapshot(self):
        for value in [{**record().model_dump(mode='json'), 'purpose': 'not rendered'}, {**plan().model_dump(mode='json'), 'general_comment': 'not rendered'}]:
            with self.assertRaises(ValidationError): VoucherForm.model_validate(value)


class RendererTests(TestCase):
    def test_pdf_is_one_page_contains_input_and_no_example_account(self):
        for form in [record(), plan()]:
            with self.subTest(template=form.template):
                data = render_pdf(form)
                pdf = PdfReader(BytesIO(data))
                self.assertEqual(len(pdf.pages), 1)
                text = pdf.pages[0].extract_text()
                self.assertIn(form.rows[0].content_left if form.rows else form.purpose, text)
                self.assertNotIn('000-0000-000-00', text)
                self.assertNotIn('0000제공기관', text)

    def test_length_and_unsupported_glyph_rejected_without_truncation(self):
        form = record(); form.rows[0].content_left = '긴 합성 문장 ' * 150
        with self.assertRaises(VoucherError) as error: paragraphs(form)
        self.assertEqual(error.exception.code, 'LAYOUT_OVERFLOW')
        form.rows[0].content_left = '합성 😀'
        with self.assertRaises(VoucherError) as error: paragraphs(form)
        self.assertEqual(error.exception.code, 'UNSUPPORTED_GLYPH')

    def test_eight_rows_and_blank_admin_fields(self):
        form = record()
        form.rows = [form.rows[0].model_copy(update={'voucher_session_no': n}) for n in range(1, 9)]
        self.assertEqual(len(PdfReader(BytesIO(render_pdf(form))).pages), 1)

    def test_hwpx_xml_binding_and_no_example_text(self):
        for form in [record(), plan()]:
            with ZipFile(BytesIO(render_hwpx(form))) as archive:
                self.assertEqual(archive.read('mimetype'), b'application/hwp+zip')
                root = ET.fromstring(archive.read('Contents/section0.xml'))
                text = '\n'.join(root.xpath('//hp:t/text()', namespaces=NS))
                self.assertIn(form.rows[0].content_left if form.rows else form.purpose, text)
                self.assertNotIn('000-0000-000-00', text)
                self.assertNotIn('0000제공기관', text)

    def test_hwpx_omits_stale_source_thumbnail_and_keeps_current_preview_text(self):
        for form in [record(), plan()]:
            with self.subTest(template=form.template), ZipFile(BytesIO(render_hwpx(form))) as archive:
                self.assertNotIn('Preview/PrvImage.png', archive.namelist())
                expected = form.rows[0].content_left if form.rows else form.purpose
                self.assertIn(expected, archive.read('Preview/PrvText.txt').decode('utf-8'))
                for name in archive.namelist():
                    if name.endswith(('.xml', '.hpf', '.rdf')):
                        self.assertNotIn(b'PrvImage.png', archive.read(name), name)


class ServiceTests(TestCase):
    def setUp(self):
        self.memory = MemoryStorage()
        self.source = note()
        self.patches = [
            patch('app.services.voucher_documents.db._storage_for_actor', side_effect=lambda actor: self.memory if str(actor) == str(OWNER) else self.fail_owner()),
            patch.object(service, 'owned_case', side_effect=lambda actor, case_id: {'case_alias': '합성내담자'} if str(actor) == str(OWNER) and case_id == CASE else self.fail_owner()),
            patch('app.services.voucher_documents.db.fetch_generated_note', side_effect=lambda *a, **kw: deepcopy(self.source)),
            patch('app.services.storage_deidentification._extract_entities', return_value=None),
        ]
        for item in self.patches: item.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    def fail_owner(self):
        raise VoucherError('DOCUMENT_NOT_FOUND', '문서를 찾을 수 없습니다.', 404)

    def prepared(self, form=None, key=None):
        form = form or record()
        _, hashes = service.sources(OWNER, CASE, form.rows)
        req = PrepareRequest(case_id=CASE, operation_key=key or uuid4(), form=form, source_hashes=hashes)
        return service.prepare(OWNER, req), req

    def review(self, row):
        return service.review(OWNER, row['id'], ReviewRequest(fingerprint=row['fingerprint'], human_privacy_reviewed=True, acknowledged_offline_completion=True))

    def test_prepare_review_reopen_export_keeps_exact_snapshot(self):
        row, req = self.prepared()
        self.assertEqual(service.prepare(OWNER, req)['id'], row['id'])
        before = service.export(OWNER, row['id'], 'pdf', preview=True)
        with self.assertRaises(VoucherError): service.export(OWNER, row['id'], 'pdf')
        reviewed = self.review(row)
        self.assertTrue(reviewed['reviewed_at'])
        with patch('app.services.voucher_documents.deidentify_texts', side_effect=AssertionError('must not rerun privacy at export')):
            after = service.export(OWNER, row['id'], 'pdf')
        self.assertEqual(before, after)
        self.assertEqual(service.get(OWNER, row['id'])['snapshot'], row['snapshot'])
        self.assertEqual(len(self.memory.rows), 1)

    def test_released_snapshots_remain_reviewable_and_exportable_after_qualification(self):
        # Fingerprint from the manifest shipped in 12d5fcc, before HWPX qualification.
        released_bundle = '1d19fc6fb00cf7e604d8d718f56a4ede711feda5a41b604a94d9ab5cdced9641'
        for form in [record(), plan()]:
            with self.subTest(template=form.template):
                row, _ = self.prepared(form)
                self.assertEqual(row['snapshot']['template_bundle'], released_bundle)
                before = service.export(OWNER, row['id'], 'pdf', preview=True)
                self.review(row)
                self.assertEqual(service.export(OWNER, row['id'], 'pdf'), before)
                with ZipFile(BytesIO(service.export(OWNER, row['id'], 'hwpx'))) as archive:
                    self.assertNotIn('Preview/PrvImage.png', archive.namelist())
                    expected = form.rows[0].content_left if form.rows else form.purpose
                    self.assertIn(expected, archive.read('Preview/PrvText.txt').decode('utf-8'))
                self.assertEqual(service.get(OWNER, row['id'])['fingerprint'], row['fingerprint'])

    def test_disabling_hwpx_does_not_invalidate_reviewed_pdf(self):
        row, _ = self.prepared()
        self.review(row)
        before = service.export(OWNER, row['id'], 'pdf')
        disabled = manifest()
        disabled['qualification']['hwpx'] = False
        with patch('app.services.voucher_documents.manifest', return_value=disabled):
            self.assertEqual(service.export(OWNER, row['id'], 'pdf'), before)
            with self.assertRaises(VoucherError) as error:
                service.export(OWNER, row['id'], 'hwpx')
            self.assertEqual(error.exception.code, 'FORMAT_NOT_QUALIFIED')

    def test_rendering_bundle_changes_still_invalidate_saved_snapshot(self):
        row, _ = self.prepared()
        for field in ['assets', 'version', 'layout']:
            changed = manifest()
            if field == 'assets':
                changed['assets']['compiled/form10.pdf'] = '0' * 64
            else:
                changed[field] += '-changed'
            with self.subTest(field=field), patch('app.services.voucher_documents.manifest', return_value=changed):
                with self.assertRaises(VoucherError) as error:
                    self.review(row)
                self.assertEqual(error.exception.code, 'POLICY_VERSION_CHANGED')
                with self.assertRaises(VoucherError) as error:
                    service.export(OWNER, row['id'], 'pdf', preview=True)
                self.assertEqual(error.exception.code, 'TEMPLATE_VERSION_UNAVAILABLE')

    def test_no_raw_input_read_and_no_other_case_mapping(self):
        req = MapRequest(case_id=CASE, sources=[selection()])
        with patch('app.services.voucher_documents.db.fetch_generated_note', return_value=self.source) as fetch:
            service.map_sources(OWNER, req)
            fetch.assert_called_once_with(NOTE, actor=OWNER, include_input=False)
        self.source.case_id = 'other'
        with self.assertRaises(VoucherError): service.map_sources(OWNER, req)

    def test_all_snapshot_operations_forward_user_token_without_admin_key(self):
        from app.services import supabase_storage as db
        self.patches[0].stop()
        calls = []

        def request(client, method, path, *, query=None, body=None, **kwargs):
            self.assertEqual(client.access_token, OWNER.access_token)
            calls.append(method)
            if method == 'GET': return self.memory.select(path, query)
            if method == 'POST': return self.memory.insert(path, body)
            if method == 'PATCH': return self.memory.update(path, body, query)
            if method == 'DELETE': return self.memory.delete(path, query)
            self.fail(method)

        with patch.object(db.SupabaseStorage, '_request', request):
            row, _ = self.prepared()
            self.review(row)
            self.assertEqual(len(service.list(OWNER, CASE)), 1)
            service.export(OWNER, row['id'], 'pdf')
            service.delete(OWNER, row['id'])
        self.assertEqual(set(calls), {'GET', 'POST', 'PATCH', 'DELETE'})

    def test_source_mutation_and_wrong_actor_and_fingerprint_fail(self):
        row, req = self.prepared()
        for actor in ['other', '']:
            with self.assertRaises(VoucherError): service.get(actor, row['id'])
        with self.assertRaises(VoucherError): service.review(OWNER, row['id'], ReviewRequest(fingerprint='0'*64, human_privacy_reviewed=True, acknowledged_offline_completion=True))
        self.source.confirmed_json['session_content'] = '변경된 확정 내용'
        with self.assertRaises(VoucherError): self.review(row)
        with self.assertRaises(VoucherError): service.prepare(OWNER, req.model_copy(update={'operation_key': uuid4()}))

    def test_privacy_before_preview_plan_without_notes_and_delete(self):
        form = plan(); form.purpose = '연락처 010-1234-5678'
        row, req = self.prepared(form)
        self.assertNotIn('010-1234-5678', str(row['snapshot']))
        self.assertEqual(row['privacy_status'], 'degraded')
        self.review(row)
        self.assertTrue(service.export(OWNER, row['id'], 'pdf'))
        self.assertTrue(service.export(OWNER, row['id'], 'hwpx'))
        service.delete(OWNER, row['id'])
        self.assertEqual(self.memory.rows, [])

    def test_idempotency_reuse_with_different_content_fails(self):
        row, req = self.prepared()
        req.form.general_comment = '수정됨'
        with self.assertRaises(VoucherError): service.prepare(OWNER, req)

    def test_fastapi_and_vercel_route_flow_and_auth_parity(self):
        from app.main import app as local_app
        from api.documents.export import app as vercel_app
        for app, prefix in [(local_app, '/api/documents/vouchers/'), (vercel_app, '/api/documents/export?voucher_path=')]:
            client = TestClient(app)
            app.dependency_overrides[require_preview_access] = lambda: OWNER
            self.addCleanup(app.dependency_overrides.clear)
            with patch.dict('os.environ', {'ENABLE_VOUCHER_DOCUMENTS': '1'}):
                self.assertTrue(client.get(prefix+'capabilities').json()['formats']['hwpx'])
                request = PrepareRequest(case_id=CASE, operation_key=uuid4(), form=plan()).model_dump(mode='json')
                row = client.post(prefix+'prepare', json=request)
                self.assertEqual(row.status_code, 200, row.text)
                row = row.json(); base = prefix+'saved/'+row['id']
                preview = client.get(base+'/preview')
                self.assertEqual(preview.status_code, 200)
                self.assertEqual(preview.headers['cache-control'], 'private, no-store')
                self.assertEqual(client.post(base+'/export', json={'format': 'hwpx'}).status_code, 409)
                review = client.post(base+'/review', json={'fingerprint': row['fingerprint'], 'human_privacy_reviewed': True, 'acknowledged_offline_completion': True})
                self.assertEqual(review.status_code, 200)
                download = client.post(base+'/export', json={'format': 'pdf'})
                self.assertEqual(download.content, preview.content)
                hwpx = client.post(base+'/export', json={'format': 'hwpx'})
                self.assertEqual(hwpx.status_code, 200)
                self.assertEqual(hwpx.headers['content-type'], 'application/hwp+zip')
                self.assertEqual(hwpx.headers['cache-control'], 'private, no-store')
                self.assertIn('.hwpx', hwpx.headers['content-disposition'])
                with ZipFile(BytesIO(hwpx.content)) as archive:
                    self.assertIn('정서 이해를 돕는다.', archive.read('Preview/PrvText.txt').decode('utf-8'))
                self.assertEqual(client.delete(base).status_code, 204)
                self.assertEqual(client.get(base).status_code, 404)
                app.dependency_overrides[require_preview_access] = lambda: 'shared-preview'
                self.assertEqual(client.get(prefix+'capabilities').status_code, 401)


if __name__ == '__main__':
    main()
