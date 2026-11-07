from io import BytesIO
from unittest import TestCase
from zipfile import ZipFile

from lxml import etree as ET
from pydantic import ValidationError
from pypdf import PdfReader

from app.schemas.voucher import VoucherForm
from app.services import voucher_ari
from app.services.voucher_renderer import NS, VoucherError
from app.services.voucher_original import original_file


class CenterFormTests(TestCase):
    def record(self, text, edition="ari-2026"):
        return VoucherForm(template="form10", edition=edition, report_month="2026-10",
                           rows=[dict(voucher_session_no=8, actual_service_date="2026-10-01",
                                      delivered_attested=True, content_left=text)])

    def test_direct_entry_uses_center_cell_and_keeps_signature_blank(self):
        value = "첫째 줄\n둘째 줄\n셋째 줄\n넷째 줄"
        doc = self.record(value)
        with ZipFile(BytesIO(voucher_ari.render(doc, "hwpx"))) as z:
            section = ET.fromstring(z.read("Contents/section0.xml"))
        with ZipFile(BytesIO(original_file("hwpx"))) as z:
            original = ET.fromstring(z.read("Contents/section0.xml")).find(".//hp:tbl", NS)
        table = section.find(".//hp:tbl", NS)
        signature = lambda t: [(e.get("rowAddr"),e.get("colAddr"),e.getparent().find("hp:cellSz", NS).attrib)
                               for e in t.findall(".//hp:cellAddr", NS)]
        self.assertEqual(signature(original),signature(table))
        row = table.findall("hp:tr", NS)[11].findall("hp:tc", NS)
        self.assertEqual(row[1].xpath(".//hp:t/text()", namespaces=NS),value.splitlines())
        self.assertFalse(row[2].xpath(".//hp:t/text()", namespaces=NS))
        pdf = PdfReader(BytesIO(voucher_ari.render(doc, "pdf")))
        self.assertEqual(len(pdf.pages), 1)
        self.assertIn("넷째 줄", pdf.pages[0].extract_text())
        with self.assertRaises(VoucherError) as ctx:
            voucher_ari.lines_for(self.record(value+"\n다섯째"))
        self.assertEqual((ctx.exception.code,ctx.exception.field),("LAYOUT_OVERFLOW","row8_left"))
        with self.assertRaises(ValidationError):
            self.record(value, edition="standard")

    def test_contract_preserves_every_fixed_clause_in_the_center_original(self):
        form = VoucherForm(template="form25",edition="ari-2026",report_month="2026-10",
                           contract_period="합성 계약기간",other_terms="별도 합의")
        def body(hwpx):
            with ZipFile(BytesIO(hwpx)) as z:
                root = ET.fromstring(z.read("Contents/section0.xml"))
            return ["".join(p.xpath("./hp:run/hp:t//text()", namespaces=NS)) for p in root]
        source = body(original_file("hwpx"))[3:76]
        result = body(voucher_ari.render(form,"hwpx"))
        self.assertEqual(source[:20],result[:20])
        self.assertEqual(source[23:],result[23:])
        self.assertIn(form.contract_period,result[20])
        self.assertIn(form.other_terms,result[22])
        self.assertEqual(len(PdfReader(BytesIO(voucher_ari.render(form,"pdf"))).pages),2)

    def test_plan_keeps_one_full_width_plan_cell_and_no_other_packet_pages(self):
        form = VoucherForm(template="form26",edition="ari-2026",report_month="2026-10",
                           purpose="목적",content="내용",plan_left="함께 정한 계획")
        with ZipFile(BytesIO(voucher_ari.render(form,"hwpx"))) as z:
            doc = ET.fromstring(z.read("Contents/section0.xml"))
            self.assertEqual(len(doc.findall(".//hp:tbl",NS)),1)
            row = doc.findall(".//hp:tbl/hp:tr",NS)[11].findall("hp:tc",NS)
            self.assertEqual(len(row),1)
            self.assertEqual(row[0].xpath(".//hp:t/text()",namespaces=NS),[form.plan_left])
        self.assertEqual(len(PdfReader(BytesIO(voucher_ari.render(form,"pdf"))).pages),1)
