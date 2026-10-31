"""Form 25: one line layout shared by PDF and editable HWPX output.

The KOGL Type 1 clauses are fixed assets. Only explicitly entered contract terms
are filled; parties and signatures remain blank for completion by the institution.
"""
from copy import deepcopy
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from lxml import etree as ET
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from app.services.voucher_renderer import ROOT, NS, VoucherError, font

SOURCE_URL = 'https://welfare.dobong.go.kr/dobongBokji/bbs/BMSR00004/view.do?boardId=1771&menuNo=200113'
ATTRIBUTION = '출처: 보건복지부, 2026년 정신건강 심리상담 바우처사업 안내, 서식 제25호 (156~158쪽).'
LICENSE = '도봉복지로 공개본(2026.4.27), 공공누리 제1유형(출처표시). 작성란·배치 재구성: 리마인드.'
FIELDS = {'contract_period': '계약기간', 'content': '서비스 종류·내용', 'schedule': '제공시간·횟수·일정',
          'price': '계약금액 (서비스가격·정부지원금·본인부담금)', 'additional_cost': '추가비용 발생여부·금액',
          'refund_terms': '계약 해제·해지에 따른 환불규정', 'other_terms': '기타 합의사항'}
ACKNOWLEDGEMENT = '이용자(또는 보호자)는 서비스 이용 결정 및 서비스 계약 체결하기 전에 위의 계약 내용과 서비스 기관 및 제공인력 정보, 서비스 내용, 서비스 거절 및 중단 가능에 대한 설명을 듣고 계약을 체결함'
WIDTH, HEIGHT, MARGIN = 595.28, 841.86, 50
BOTTOM = 755


def wrapped(text, size, field=None):
    # Nanum Gothic lacks the source's circled numbers and half-width middle dot.
    # Normalize typography consistently in both formats, retaining clause wording.
    text = text.translate(str.maketrans({'①': '(1)', '②': '(2)', '③': '(3)', '④': '(4)', '\uff65': '·'}))
    face = font().face
    if any(char not in '\n\t' and ord(char) not in face.charToGlyph for char in text):
        raise VoucherError('UNSUPPORTED_GLYPH', '지원하지 않는 문자를 수정해주세요.', field=field)
    result = []
    # Leave spare width for editor font substitution. Never omit input characters.
    for paragraph in text.replace('\t', '    ').split('\n'):
        line = ''
        for char in paragraph:
            if line and pdfmetrics.stringWidth(line + char, 'VoucherKorean', size) > WIDTH - 2*MARGIN - 20:
                result.append(line)
                line = ''
            line += char
        result.append(line)
    return result


def layout(form):
    """Return pages of (text, font size, line height); reject oversized fields."""
    pages = [[]]
    y = MARGIN

    def add(text, size=10, field=None, gap=0):
        nonlocal y
        leading = 20 if size == 15 else 16 if size == 11 else 14
        lines = wrapped(text, size, field)
        if field and len(lines) > 10:
            raise VoucherError('LAYOUT_OVERFLOW', '이 항목을 10줄 이내로 줄여주세요.', field=field)
        height = leading * len(lines) + gap
        if y + height > BOTTOM:
            pages.append([])
            y = MARGIN
        if height > BOTTOM - MARGIN:
            raise VoucherError('LAYOUT_OVERFLOW', '이 항목의 내용을 줄여주세요.', field=field)
        pages[-1].extend((line, size, leading) for line in lines)
        if gap:
            pages[-1].append(('', 10, gap))
        y += height

    add('[서식 제25호] 사업운영 자체 서식', 10)
    add('사회서비스 제공(이용)계약서(예시)', 15, gap=8)
    for text in [
        '○ 서비스 이용자', '성명:                            (인)       생년월일:', '주소:', '연락처:',
        '○ 대리인(보호자)', '성명:                            (인)       이용자와의 관계:', '주소:', '연락처:',
        '○ 서비스 제공기관', '기관명:                          대표자:                            (인)', '주소:',
    ]:
        add(text)
    add('', gap=4)
    for key, label in FIELDS.items():
        value = getattr(form, key)
        add('○ ' + label, 11)
        add(value if value else '기관에서 기입: __________________________________________', field=key, gap=4)
    add('서비스 종류, 내용, 제공시간, 제공횟수 등 구체적 사항은 서비스 제공기관과 이용자 간의 협의에 따른다.', gap=4)
    add('상기 당사자 또는 대리인은 다음 계약내용에 의거하여 사회서비스 제공(이용)계약서를 작성하고 기명날인 후, 각각 1통씩 보관한다.')
    pages.append([])
    y = MARGIN
    add('- 다 음 -', 11, gap=6)
    clauses = json.loads((ROOT / 'source/form25-clauses.json').read_text('utf-8'))
    for title, paragraphs in clauses:
        # Keep each heading with its first paragraph, and each clause paragraph intact.
        first_height = 16 + len(wrapped(paragraphs[0], 10))*14
        if y + first_height > BOTTOM:
            pages.append([])
            y = MARGIN
        add(title, 11)
        for paragraph in paragraphs:
            add(paragraph, gap=4)
    add(ACKNOWLEDGEMENT, gap=10)
    add('계약 체결일: 20      년      월      일', gap=8)
    add(ATTRIBUTION, 8)
    add(LICENSE, 8)
    add(SOURCE_URL, 8)
    return pages


def render_pdf(form):
    pages = layout(form)
    output = BytesIO()
    canvas = Canvas(output, pagesize=(WIDTH, HEIGHT), invariant=1)
    canvas.setTitle('사회서비스 제공(이용)계약서 · 제25호')
    canvas.setAuthor('리마인드')
    for number, lines in enumerate(pages, 1):
        y = HEIGHT - MARGIN
        for text, size, leading in lines:
            canvas.setFont('VoucherKorean', size)
            canvas.drawString(MARGIN, y-size, text)
            if text == SOURCE_URL:
                canvas.linkURL(SOURCE_URL, (MARGIN, y-leading, WIDTH-MARGIN, y), relative=0)
            y -= leading
        canvas.setStrokeColorRGB(.75, .78, .82)
        canvas.line(MARGIN, 65, WIDTH-MARGIN, 65)
        canvas.setFont('VoucherKorean', 8)
        canvas.drawString(MARGIN, 50, '제25호 이용계약서 · 인적사항·서명은 기관에서 보완')
        canvas.drawRightString(WIDTH-MARGIN, 50, f'{number} / {len(pages)}')
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def render_hwpx(form):
    pages = layout(form)
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    with ZipFile(ROOT / 'source/form25-blank.hwpx') as source:
        section = ET.fromstring(source.read('Contents/section0.xml'), parser)
        header = ET.fromstring(source.read('Contents/header.xml'), parser)
        first = deepcopy(section[0][0])
        section.clear(keep_tail=True)
        margin = first.find('.//hp:margin', NS)
        margin.attrib.update({'left': '5000', 'right': '5000', 'top': '5000', 'bottom': '7000', 'header': '0', 'footer': '0'})
        page = first.find('.//hp:pagePr', NS)
        page.attrib.update({'width': '59528', 'height': '84186'})
        chars = header.find('.//hh:charProperties', NS)
        paras = header.find('.//hh:paraProperties', NS)
        char_base, para_base = deepcopy(chars[0]), deepcopy(paras[0])
        styles = {}
        for lines in pages:
            for _, size, leading in lines:
                if (size, leading) in styles:
                    continue
                char_id, para_id = str(len(chars)), str(len(paras))
                char = deepcopy(char_base)
                char.attrib.update({'id': char_id, 'height': str(size*100)})
                chars.append(char)
                para = deepcopy(para_base)
                para.attrib.update({'id': para_id, 'snapToGrid': '0'})
                para.find('hh:align', NS).set('horizontal', 'LEFT')
                for spacing in para.findall('.//hh:lineSpacing', NS):
                    # The compatibility branch uses half-sized line-spacing units
                    # in Hancom/Polaris; 2800 is displayed as 14 pt.
                    spacing.attrib.update({'type': 'FIXED', 'value': str(leading*200), 'unit': 'HWPUNIT'})
                paras.append(para)
                styles[(size, leading)] = (char_id, para_id)
        chars.set('itemCnt', str(len(chars)))
        paras.set('itemCnt', str(len(paras)))
        for face in header.findall('.//hh:font', NS):
            face.set('face', '나눔고딕')
        index = 0
        for number, lines in enumerate(pages):
            for line_index, (text, size, leading) in enumerate(lines):
                char_id, para_id = styles[(size, leading)]
                p = ET.SubElement(section, '{'+NS['hp']+'}p', id=str(index), paraPrIDRef=para_id,
                                  styleIDRef='0', pageBreak='1' if number and line_index == 0 else '0', columnBreak='0', merged='0')
                if index == 0:
                    p.append(first)
                run = ET.SubElement(p, '{'+NS['hp']+'}run', charPrIDRef=char_id)
                ET.SubElement(run, '{'+NS['hp']+'}t').text = text
                index += 1
        replacements = {'Contents/section0.xml': ET.tostring(section, encoding='UTF-8', xml_declaration=True),
                        'Contents/header.xml': ET.tostring(header, encoding='UTF-8', xml_declaration=True),
                        'Preview/PrvText.txt': '\n'.join(line[0] for page in pages for line in page).encode('utf-8')}
        output = BytesIO()
        with ZipFile(output, 'w') as archive:
            for entry in source.infolist():
                if entry.filename == 'Preview/PrvImage.png':
                    continue
                archive.writestr(entry.filename, replacements.get(entry.filename, source.read(entry.filename)),
                                 compress_type=ZIP_STORED if entry.filename == 'mimetype' else ZIP_DEFLATED)
        return output.getvalue()
