"""Native HWPX, rich text, reference-form layout, and route regressions; synthetic data only."""
from io import BytesIO
from zipfile import ZipFile, ZIP_STORED
import unittest
from unittest.mock import patch

from docx import Document
from fastapi import FastAPI
from fastapi.testclient import TestClient
from lxml import etree as ET

from app.api.routes.documents import router
from app.api.security import require_preview_access
from app.core.config import settings
from app.schemas.document import DocumentExportRequest
from app.services.document_export import (
    DocumentExportService, DocxDocumentExporter, HwpxDocumentExporter,
    _reportlab_block, render_pdf_html,
)
from app.services.hwpx_export import NS
from test_document_rich_text import MARKUP, export_request


def supervision_request():
    return DocumentExportRequest.model_validate({
        "format": "hwpx", "document_type": "supervision_report", "case_id": "SYNTHETIC-FORM",
        "session_number": 1, "title": "개인상담(공개상담) 사례 수퍼비전 보고서",
        "sections": [
            {"id": "C", "title": "C. 상담진행 과정과 상담내용", "level": 1},
            {"id": "C-1", "title": "C-1. 상담진행 과정 및 회기주제", "level": 2,
             "content_blocks": [
                 {"id": "C-1.maximum", "type": "paragraph", "text": "12회기"},
                 {"id": "C-1.table", "type": "table", "rows": [
                     {"회기 주제": "합성 주제", "상담일": "2026-11-29", "회기": "1회기",
                      "소요시간": "40분", "취소·지각·결석": "지각: 교통 지연", "이전 수퍼비전": "합성 피드백"},
                 ]},
             ]},
            {"id": "C-2", "title": "C-2. 상담회기 내용", "level": 2, "content_blocks": [
                {"type": "transcript", "speaker_turns": [
                    {"speaker": "client", "text": "합성 발화", "silence_seconds": 5},
                    {"speaker": "counselor", "text": "합성 응답"},
                    {"speaker": "client", "text": "합성 후속 발화"},
                ]},
                {"type": "reflection_box", "text": "합성 내적 경험"},
            ]},
        ],
    })


class HwpxExportTests(unittest.TestCase):
    def test_real_auth_boundary_rejects_guest_and_accepts_verified_actor(self):
        app = FastAPI()
        app.include_router(router)
        with patch.object(settings, "enable_real_user_auth", True), \
             patch.object(settings, "supabase_url", "https://synthetic.invalid"), \
             patch.object(settings, "supabase_publishable_key", "synthetic-public-key"), \
             patch("app.api.security.urlopen") as auth, \
             patch("app.api.routes.documents.record_document_export") as record, TestClient(app) as client:
            payload = supervision_request().model_dump()
            self.assertEqual(client.post("/api/documents/export", json=payload).status_code, 401)
            self.assertEqual(client.get("/api/documents/capabilities").status_code, 401)
            auth.assert_not_called()
            record.assert_not_called()
            auth.return_value.__enter__.return_value.read.return_value = b'{"id":"synthetic-owner"}'
            response = client.post("/api/documents/export", json=payload, headers={"Authorization": "Bearer synthetic-token"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(record.call_args.kwargs["actor"], "synthetic-owner")

    def test_package_and_rich_text_are_native_and_editable(self):
        data = HwpxDocumentExporter().export(export_request("hwpx", content="plain", content_html=MARKUP))
        with ZipFile(BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.infolist()[0].filename, "mimetype")
            self.assertEqual(archive.getinfo("mimetype").compress_type, ZIP_STORED)
            self.assertEqual(archive.read("mimetype"), b"application/hwp+zip")
            self.assertNotIn("word/document.xml", archive.namelist())
            self.assertNotIn("Preview/PrvImage.png", archive.namelist())
            for name in archive.namelist():
                if name.endswith((".xml", ".hpf", ".rdf")):
                    ET.fromstring(archive.read(name))
            header = ET.fromstring(archive.read("Contents/header.xml"))
            section = ET.fromstring(archive.read("Contents/section0.xml"))
            chars = {item.get("id"): item for item in header.findall(".//hh:charPr", NS)}
            paras = {item.get("id"): item for item in header.findall(".//hh:paraPr", NS)}
            by_text = {''.join(run.itertext()): chars[run.get("charPrIDRef")]
                       for run in section.findall(".//hp:run", NS)}
            self.assertIsNotNone(by_text["굵게"].find("hh:bold", NS))
            self.assertIsNotNone(by_text["기울임"].find("hh:italic", NS))
            self.assertEqual(by_text["밑줄"].find("hh:underline", NS).get("type"), "BOTTOM")
            self.assertEqual(by_text["빨강"].get("textColor"), "#DC2626")
            self.assertEqual(by_text["형광"].get("shadeColor"), "#FEF08A")
            for p in section.findall(".//hp:p", NS):
                style = paras[p.get("paraPrIDRef")]
                if ''.join(p.itertext()) == "빨강형광":
                    self.assertEqual(style.find("hh:align", NS).get("horizontal"), "CENTER")
            preview = archive.read("Preview/PrvText.txt").decode()
            self.assertIn("• 첫째", preview)
            self.assertIn("1. 하나", preview)
            self.assertIn("2. 둘", preview)

    def test_reference_table_and_transcript_in_all_formats(self):
        request = supervision_request()
        document = Document(BytesIO(DocxDocumentExporter().export(request)))
        progress = document.tables[1]
        self.assertEqual(len(progress.columns), 2)
        self.assertEqual([c.text for c in progress.rows[0].cells], ["최대 상담 가능 회기 수", "12회기"])
        self.assertEqual([c.text for c in progress.rows[1].cells], ["날짜(소요시간)", "회기 주제"])
        self.assertEqual(progress.cell(2, 0).text, "1회기 2026-11-29 (40분)")
        self.assertIn("교통 지연", progress.cell(2, 1).text)
        self.assertIn("합성 피드백", progress.cell(2, 1).text)
        self.assertIn("1. 상담진행 과정 및 회기주제", [p.text for p in document.paragraphs])
        with ZipFile(BytesIO(HwpxDocumentExporter().export(request))) as archive:
            root = ET.fromstring(archive.read("Contents/section0.xml"))
            tables = root.findall(".//hp:tbl", NS)
            self.assertEqual([int(t.get("colCnt")) for t in tables], [4, 2, 1])
            preview = archive.read("Preview/PrvText.txt").decode()
            for text in ("내1:", "상1:", "내2:", "침묵 5초", "12회기", "합성 내적 경험"):
                self.assertIn(text, preview)
        rendered = render_pdf_html(request)
        self.assertIn("1. 상담진행 과정 및 회기주제", rendered)
        self.assertLess(rendered.index("최대 상담 가능 회기 수"), rendered.index("날짜(소요시간)"))
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Table
        body = getSampleStyleSheet()["BodyText"]
        box = request.sections[-1].content_blocks[-1]
        self.assertTrue(any(isinstance(item, Table) for item in _reportlab_block(box, body, body)))

    def test_text_is_escaped_and_long_content_is_not_truncated(self):
        text = "합성 <내용> & 따옴표 \" ' " + "긴 본문 " * 4000
        with ZipFile(BytesIO(HwpxDocumentExporter().export(export_request("hwpx", content=text)))) as archive:
            root = ET.fromstring(archive.read("Contents/section0.xml"))
            self.assertTrue(text.rstrip() in ''.join(root.itertext()), "Long text must remain complete after whitespace cleanup")
        request = export_request("hwpx", content_html='<div>안전<script>secret()</script><img src="http://127.0.0.1/secret"> &lt;xml&gt;</div>')
        with ZipFile(BytesIO(HwpxDocumentExporter().export(request))) as archive:
            text = archive.read("Preview/PrvText.txt").decode()
            self.assertIn("안전 <xml>", text)
            self.assertNotIn("secret", text)

    def test_authenticated_api_download_and_capability(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[require_preview_access] = lambda: "synthetic-export-user"
        with patch("app.api.routes.documents.record_document_export") as record, TestClient(app) as client:
            self.assertTrue(client.get("/api/documents/capabilities").json()["hwpx"]["available"])
            for kind in ("session_note", "supervision_report", "termination_report"):
                request = supervision_request().model_copy(update={"document_type": kind})
                response = client.post("/api/documents/export", json=request.model_dump())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], "application/hwp+zip")
                self.assertIn(".hwpx", response.headers["content-disposition"])
                with ZipFile(BytesIO(response.content)) as archive:
                    self.assertIsNone(archive.testzip())
            self.assertEqual(record.call_count, 3)


if __name__ == "__main__":
    unittest.main()
