"""Original packets must remain unchanged, authenticated, and independent of notes."""
from hashlib import sha256
from io import BytesIO
import json
from unittest import TestCase, main
from unittest.mock import patch
from zipfile import ZipFile

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.api.routes.vouchers import router
from app.api.security import AuthenticatedActor, require_preview_access
from app.services.voucher_original import ROOT, original_file
from app.services.voucher_renderer import VoucherError


class OriginalVoucherTests(TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.dependency_overrides[require_preview_access] = lambda: AuthenticatedActor('synthetic-original', 'synthetic-token')
        self.client = TestClient(self.app)

    def test_original_hwpx_digest_and_pdf_pages(self):
        metadata = json.loads((ROOT / 'manifest.json').read_text('utf-8'))
        for format in ('pdf', 'hwpx'):
            self.assertEqual(sha256(original_file(format)).hexdigest(), metadata['assets'][format]['sha256'])
        with ZipFile(BytesIO(original_file('hwpx'))) as archive:
            self.assertIsNone(archive.testzip())
            self.assertIn('Contents/section0.xml', archive.namelist())
        pdf = PdfReader(BytesIO(original_file('pdf')))
        self.assertEqual(len(pdf.pages), 12)
        text = ''.join(page.extract_text() for page in pdf.pages)
        for title in ('서비스 제공기록지', '서비스 제공계획서', '심리상담종결확인서', '서비스만족도평가'):
            self.assertIn(title.replace(' ', ''), text.replace(' ', ''))

    def test_authenticated_original_without_case_or_review(self):
        with patch.dict('os.environ', {'ENABLE_VOUCHER_DOCUMENTS': '1'}):
            for format in ('pdf', 'hwpx'):
                response = self.client.get(f'/api/documents/vouchers/original/{format}')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, original_file(format))
                self.assertEqual(response.headers['cache-control'], 'private, no-store')
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertEqual(self.client.get('/api/documents/vouchers/original/docx').status_code, 422)
        with patch.dict('os.environ', {'ENABLE_VOUCHER_DOCUMENTS': '0'}):
            self.assertEqual(self.client.get('/api/documents/vouchers/original/pdf').status_code, 503)
        self.app.dependency_overrides[require_preview_access] = lambda: 'shared-preview'
        self.assertEqual(self.client.get('/api/documents/vouchers/original/pdf').status_code, 401)

    def test_vercel_wrapper_matches_local_route(self):
        from api.documents.export import app
        app.dependency_overrides[require_preview_access] = lambda: AuthenticatedActor('synthetic-original', 'synthetic-token')
        self.addCleanup(app.dependency_overrides.clear)
        with patch.dict('os.environ', {'ENABLE_VOUCHER_DOCUMENTS': '1'}):
            response = TestClient(app).get('/api/documents/export?voucher_path=original/pdf')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, original_file('pdf'))

    def test_changed_asset_fails_closed(self):
        metadata = json.loads((ROOT / 'manifest.json').read_text('utf-8'))
        metadata['assets']['pdf']['sha256'] = '0' * 64
        with patch('app.services.voucher_original.json.loads', return_value=metadata):
            with self.assertRaises(VoucherError):
                original_file('pdf')


if __name__ == '__main__':
    main()
