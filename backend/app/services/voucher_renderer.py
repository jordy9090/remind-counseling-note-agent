"""Fixed-template rendering; never calls a model or truncates approved text."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
from xml.sax.saxutils import escape
from zipfile import ZipFile

from lxml import etree as ET
from pypdf import PdfReader, PdfWriter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1] / "templates/vouchers/2026"
NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph", "hh": "http://www.hancom.co.kr/hwpml/2011/head"}
PAYMENT = "□ 납부방법\n- 본인부담금: 서비스 개시 전 이용자가 제공기관에 사전 납부\n  (납부방법: 계좌이체, 카드결제, 현금)\n  ▶ 납부계좌: 기관에서 기입\n- 정부지원금(바우처 지원)\n  ▶ 실시간 결제 서비스: 서비스가 실제 제공된 경우만 결제 가능\n  (미출석 시 바우처카드 결제 불가)"


class VoucherError(Exception):
    def __init__(self, code, message, status=422, field=None):
        super().__init__(message)
        self.code, self.status, self.field = code, status, field


def bindings(template):
    # Rectangles use source PDF points, measured from the top-left, with cell addresses.
    if template == "form10":
        result = {"title": ((0, 0), (56.61, 103, 481.78, 24)),
                  "period": ((1, 6), (364.61, 127, 173.78, 19)),
                  "tier": ((2, 7), (418.21, 146.84, 120.18, 28.17)),
                  "general_comment": ((13, 0), (56.61, 697.16, 407.9, 44.95))}
        ys = [203.06, 259.88, 316.57, 373.27, 429.97, 486.79, 543.49, 600.18, 656.88]
        for n in range(1, 9):
            for field, col, x, width in [('date', 0, 56.61, 91.15), ('left', 1, 147.76, 159.99), ('right', 4, 307.75, 156.76)]:
                result[f"row{n}_{field}"] = ((n + 3, col), (x, ys[n-1], width, ys[n]-ys[n-1]))
        return result
    return {key: (addr, rect) for key, addr, rect in [
        ('purpose', (4, 1), (143.08, 205.58, 394.83, 42.31)),
        ('content', (5, 1), (143.08, 247.89, 394.83, 43.75)),
        ('schedule', (6, 1), (143.08, 291.64, 394.83, 47.35)),
        ('price', (7, 1), (143.08, 338.99, 394.83, 58.02)),
        ('payment', (8, 1), (143.08, 397.01, 394.83, 130.17)),
        ('contract_period', (9, 1), (143.08, 527.18, 394.83, 32.37)),
        ('plan_left', (11, 0), (56.61, 588.56, 238.43, 95.05)),
        ('plan_right', (11, 3), (295.04, 588.56, 242.87, 95.05)),
    ]}


def field_values(form):
    if form.template == 'form26':
        return {**{key: getattr(form, key) for key in bindings('form26') if key != 'payment'}, 'payment': PAYMENT}
    values = {'title': f'서비스 제공기록지({int(form.report_month[5:])}월)',
              'period': f'{min(r.actual_service_date for r in form.rows)} ~ {max(r.actual_service_date for r in form.rows)}',
              'tier': ('■' if form.service_tier == 'type_1' else '□') + ' 1급 유형\n' + ('■' if form.service_tier == 'type_2' else '□') + ' 2급 유형',
              'general_comment': form.general_comment}
    for n in range(1, 9):
        row = next((r for r in form.rows if r.voucher_session_no == n), None)
        values[f'row{n}_date'] = f'{n}회차\n' + (row.actual_service_date.strftime('%m/%d') if row else '(    /    )')
        values[f'row{n}_left'] = row.content_left if row else ''
        values[f'row{n}_right'] = row.content_right if row else ''
    return values


def manifest(template=None):
    name = 'form25-manifest.json' if template == 'form25' else 'manifest.json'
    return json.loads((ROOT / name).read_text('utf-8'))


def verify_assets(template=None):
    for name, digest in manifest(template)['assets'].items():
        if sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise VoucherError('TEMPLATE_BINDING_MISMATCH', '서식 파일을 확인할 수 없습니다.', 503)


def font():
    if 'VoucherKorean' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('VoucherKorean', str(ROOT / 'compiled/NanumGothic.ttf')))
    return pdfmetrics.getFont('VoucherKorean')


def paragraphs(form):
    if form.template == 'form25':
        from app.services.voucher_contract import layout
        return layout(form)
    face = font().face
    result = []
    for key, value in field_values(form).items():
        _, rect = bindings(form.template)[key]
        for char in value:
            if char not in '\n\t' and ord(char) not in face.charToGlyph:
                raise VoucherError('UNSUPPORTED_GLYPH', '지원하지 않는 문자를 수정해주세요.', field=key)
        # Fixed field-specific profiles, never shrink content to make it fit.
        size = 11 if key == 'title' else 8 if key in {'period', 'tier'} else 9
        style = ParagraphStyle('voucher', fontName='VoucherKorean', fontSize=size, leading=size*1.25, wordWrap='CJK')
        paragraph = Paragraph(escape(value).replace('\n', '<br/>'), style)
        _, height = paragraph.wrap(rect[2]-10, rect[3]-8)
        if height > rect[3]-8:
            raise VoucherError('LAYOUT_OVERFLOW', '이 항목의 내용을 줄여주세요. 서식 칸을 벗어납니다.', field=key)
        result.append((paragraph, rect, height))
    return result


def render_pdf(form):
    verify_assets(form.template)
    if form.template == 'form25':
        from app.services.voucher_contract import render_pdf as contract_pdf
        return contract_pdf(form)
    overlay = BytesIO()
    canvas = Canvas(overlay, pagesize=(595, 841), invariant=1)
    for paragraph, (x, y, _, _), height in paragraphs(form):
        paragraph.drawOn(canvas, x+5, 841-y-4-height)
    canvas.save()
    base = PdfReader(ROOT / f'compiled/{form.template}.pdf')
    writer = PdfWriter()
    writer.add_page(base.pages[0])
    writer.pages[0].merge_page(PdfReader(overlay).pages[0])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def render_hwpx(form):
    verify_assets(form.template)
    if form.template == 'form25':
        from app.services.voucher_contract import render_hwpx as contract_hwpx
        return contract_hwpx(form)
    paragraphs(form)
    source = ZipFile(ROOT / f'source/{form.template}.hwpx')
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    root = ET.fromstring(source.read('Contents/section0.xml'), parser)
    header = ET.fromstring(source.read('Contents/header.xml'), parser)
    properties = header.find('.//hh:charProperties', NS)
    style = deepcopy(properties[0])
    style_id = str(max(int(p.get('id')) for p in properties)+1)
    style.set('id', style_id)
    style.set('height', '900')
    properties.append(style)
    properties.set('itemCnt', str(len(properties)))
    cells = {}
    for cell in root.findall('.//hp:tc', NS):
        addr = cell.find('hp:cellAddr', NS)
        cells[(int(addr.get('rowAddr')), int(addr.get('colAddr')))] = cell
    values = field_values(form)
    for key, (addr, _) in bindings(form.template).items():
        if addr not in cells:
            raise VoucherError('TEMPLATE_BINDING_MISMATCH', '서식 항목 위치가 일치하지 않습니다.', 503)
        sub = cells[addr].find('hp:subList', NS)
        base_p = deepcopy(sub.find('hp:p', NS))
        for child in list(sub):
            sub.remove(child)
        for line in values[key].split('\n'):
            p = deepcopy(base_p)
            for child in list(p):
                p.remove(child)
            run = ET.SubElement(p, '{'+NS['hp']+'}run', charPrIDRef=style_id)
            ET.SubElement(run, '{'+NS['hp']+'}t').text = line
            sub.append(p)
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        for entry in source.infolist():
            # The source thumbnail predates the filled values; omit it instead of
            # presenting a blank or example form as the generated document.
            if entry.filename == 'Preview/PrvImage.png':
                continue
            data = source.read(entry.filename)
            if entry.filename == 'Contents/section0.xml':
                data = ET.tostring(root, encoding='UTF-8', xml_declaration=True)
            elif entry.filename == 'Contents/header.xml':
                data = ET.tostring(header, encoding='UTF-8', xml_declaration=True)
            elif entry.filename == 'Preview/PrvText.txt':
                data = '\n'.join(values.values()).encode('utf-8')
            archive.writestr(entry, data)
    return output.getvalue()
