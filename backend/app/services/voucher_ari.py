"""Fill the center's supplied HWPX cells and their matching print backgrounds."""
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json
from zipfile import ZipFile

from lxml import etree as ET
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from app.services.voucher_original import ROOT, original_file
from app.services.voucher_renderer import NS, VoucherError, font

EDITION = "ari-2026"
COMPILED = ROOT / "filled"
# HWPX cell addresses are (row, column). The agreement fields are body paragraphs.
PLAN_CELLS = {"purpose": (4, 1), "content": (5, 1), "schedule": (6, 1), "price": (7, 1),
              "contract_period": (9, 1), "plan_left": (11, 0)}
RECORD_CELLS = {"period": (1, 5), "tier": (2, 6), "general_comment": (13, 0)}
for _n in range(1, 9):
    RECORD_CELLS[f"date{_n}"] = (_n + 3, 0)
    RECORD_CELLS[f"row{_n}_left"] = (_n + 3, 1)


@lru_cache(maxsize=1)
def metadata():
    result = json.loads((COMPILED / "layout.json").read_text("utf-8"))
    if result["sourceHash"] != sha256(original_file("hwpx")).hexdigest():
        raise VoucherError("TEMPLATE_BINDING_MISMATCH", "센터 원본과 출력 기준이 일치하지 않습니다.", 503)
    return result


def fingerprint(template):
    return metadata()["versions"][template]


def _tag(name):
    return "{%s}%s" % (NS["hp"], name)


def _section(template):
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    with ZipFile(BytesIO(original_file("hwpx"))) as source:
        section = ET.fromstring(source.read("Contents/section0.xml"), parser)
        header = ET.fromstring(source.read("Contents/header.xml"), parser)
    paragraphs = list(section)
    ranges = {"form10": (0, 1), "form25": (3, 76), "form26": (76, 77)}
    start, stop = ranges[template]
    if start:
        runs = paragraphs[0].find("hp:run", NS)
        first_run = paragraphs[start].find("hp:run", NS)
        for node in reversed([e for e in runs if e.tag in (_tag("secPr"), _tag("ctrl"))]):
            first_run.insert(0, deepcopy(node))
    for i, p in enumerate(paragraphs):
        if not start <= i < stop:
            section.remove(p)
    return section, header


def _text_style(header):
    """Keep all source styles; add one explicit font and spacing for typed text."""
    ch = "{%s}" % NS["hh"]
    font_ids = {}
    for group in header.findall(".//hh:fontface", NS):
        fonts = group.findall("hh:font", NS)
        entry = next((f for f in fonts if f.get("face") == "나눔고딕"), None)
        if entry is None:
            entry = deepcopy(fonts[0])
            entry.set("id", str(max(int(f.get("id")) for f in fonts) + 1))
            entry.set("face", "나눔고딕")
            group.append(entry)
            group.set("fontCnt", str(len(fonts) + 1))
        font_ids[group.get("lang").lower()] = entry.get("id")
    chars = header.find(".//hh:charProperties", NS)
    char = deepcopy(chars[0])
    char_id = str(max(int(c.get("id")) for c in chars) + 1)
    char.attrib.update({"id": char_id, "height": "900", "textColor": "#000000", "shadeColor": "none"})
    for k in char.find(ch+"fontRef").attrib:
        if k in font_ids:
            char.find(ch+"fontRef").set(k,font_ids[k])
    chars.append(char)
    chars.set("itemCnt", str(len(chars)))
    paras = header.find(".//hh:paraProperties", NS)
    para = deepcopy(paras[0])
    para_id = str(max(int(p.get("id")) for p in paras) + 1)
    para.attrib.update({"id": para_id, "snapToGrid": "0"})
    para.find("hh:align", NS).set("horizontal", "LEFT")
    for e in para.findall(".//hh:margin/*", NS):
        if "value" in e.attrib:
            e.set("value", "0")
    for e in para.findall(".//hh:lineSpacing", NS):
        e.attrib.update({"type": "FIXED", "value": "1200", "unit": "HWPUNIT"})
    paras.append(para)
    paras.set("itemCnt", str(len(paras)))
    return char_id, para_id


def _set_cell(cell, lines, styles):
    sub = cell.find("hp:subList", NS)
    base = sub.find("hp:p", NS)
    attrs = dict(base.attrib)
    attrs.update({"paraPrIDRef": styles[1], "pageBreak": "0", "columnBreak": "0"})
    for p in list(sub):
        sub.remove(p)
    for line in lines or [""]:
        p = ET.SubElement(sub, _tag("p"), attrs)
        run = ET.SubElement(p, _tag("run"), charPrIDRef=styles[0])
        ET.SubElement(run, _tag("t")).text = line


def _replace_body_text(paragraph, value):
    # Preserve paragraph position, section properties and the existing agreement font.
    texts = paragraph.findall("./hp:run/hp:t", NS)
    if not texts:
        texts = [ET.SubElement(paragraph.find("hp:run", NS), _tag("t"))]
    for node in texts:
        for child in list(node):
            node.remove(child)
        node.text = ""
    texts[0].text = value


def build_hwpx(template, fields):
    section, header = _section(template)
    if template == "form25":
        for index, key, label in [(20, "contract_period", "○ 계약기간 : "), (22, "other_terms", "○ 기타 : ")]:
            if len(fields.get(key, [])) > 1:
                raise VoucherError("LAYOUT_OVERFLOW", "원본의 한 줄을 벗어납니다.", field=key)
            _replace_body_text(section[index], label + "".join(fields.get(key, [])))
    else:
        styles = _text_style(header)
        cells = {(int(a.get("rowAddr")), int(a.get("colAddr"))): a.getparent()
                 for a in section.findall(".//hp:tbl/hp:tr/hp:tc/hp:cellAddr", NS)}
        for key, addr in (RECORD_CELLS if template == "form10" else PLAN_CELLS).items():
            _set_cell(cells[addr], fields.get(key, []), styles)
    output = BytesIO()
    with ZipFile(BytesIO(original_file("hwpx"))) as source, ZipFile(output, "w") as target:
        for item in source.infolist():
            if item.filename == "Preview/PrvImage.png":
                continue
            data = source.read(item.filename)
            if item.filename in ("Contents/section0.xml", "Contents/header.xml"):
                xml = section if item.filename.endswith("section0.xml") else header
                data = ET.tostring(xml, encoding="UTF-8", xml_declaration=True)
            elif item.filename == "Preview/PrvText.txt":
                data = "\n".join(section.xpath(".//hp:t/text()", namespaces=NS)).encode("utf-8")
            target.writestr(item, data)
    return output.getvalue()


@lru_cache(maxsize=1)
def font_profile():
    face = font().face
    # Group codepoints by advance width; the browser measures locally without sending drafts.
    groups = {}
    for code in sorted(face.charToGlyph):
        width = round(face.charWidths.get(code, face.defaultWidth), 4)
        ranges = groups.setdefault(width, [])
        if ranges and ranges[-1][1] == code - 1:
            ranges[-1][1] = code
        else:
            ranges.append([code, code])
    return [[width, ranges] for width, ranges in groups.items()]


def wrap(text, width, size, field):
    face = font().face
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").expandtabs(4).split("\n"):
        line, advance = "", 0
        for ch in paragraph:
            code = ord(ch)
            if code not in face.charToGlyph:
                raise VoucherError("UNSUPPORTED_GLYPH", "출력할 수 없는 문자를 바꿔주세요.", field=field)
            unit = round(face.charWidths.get(code, face.defaultWidth), 4) * size / 1000
            if line and advance + unit > width + 0.000001:
                lines.append(line)
                line, advance = "", 0
            line += ch
            advance += unit
        lines.append(line)
    return lines if text else []


def values(form):
    if form.template == "form25":
        return {k: getattr(form, k) for k in ("contract_period", "other_terms")}
    if form.template == "form26":
        return {k: getattr(form, k) for k in PLAN_CELLS}
    dates = [row.actual_service_date for row in form.rows]
    result = {"general_comment": form.general_comment,
              "period": f"{min(dates):%Y.%m.%d} ~ {max(dates):%Y.%m.%d}",
              "tier": ("■" if form.service_tier == "type_1" else "□") + " 1급 유형\n" +
                      ("■" if form.service_tier == "type_2" else "□") + " 2급 유형"}
    rows = {r.voucher_session_no: r for r in form.rows}
    for n in range(1, 9):
        row = rows.get(n)
        result[f"date{n}"] = f"{n}회차\n" + (row.actual_service_date.strftime("%m/%d") if row else "(    /    )")
        result[f"row{n}_left"] = row.content_left if row else ""
    return result


def lines_for(form):
    fields = metadata()["fields"][form.template]
    result = {}
    for key, text in values(form).items():
        p = fields[key]
        lines = wrap(text, p["width"], p["size"], key)
        if len(lines) > p["maxLines"]:
            raise VoucherError("LAYOUT_OVERFLOW", f"출력 칸보다 {len(lines)-p['maxLines']}줄 깁니다.", field=key)
        result[key] = lines
    return result


def render(form, file_format):
    lines = lines_for(form)
    if file_format == "hwpx":
        return build_hwpx(form.template, lines)
    path = COMPILED / f"{form.template}.pdf"
    data = path.read_bytes()
    if sha256(data).hexdigest() != metadata()["pdfHashes"][form.template]:
        raise VoucherError("TEMPLATE_BINDING_MISMATCH", "센터 원본 양식을 확인하지 못했습니다.", 503)
    writer = PdfWriter(clone_from=BytesIO(data))
    page = writer.pages[0]
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    overlay = BytesIO()
    canvas = Canvas(overlay, pagesize=(width, height), invariant=1)
    for key, content in lines.items():
        p = metadata()["fields"][form.template][key]
        if not content:
            continue
        canvas.setFont("VoucherKorean", p["size"])
        top = p["top"] + (p["height"] - len(content)*p["leading"])/2
        for i, line in enumerate(content):
            canvas.drawString(p["x"], height-top-p["size"]-i*p["leading"], line)
    canvas.save()
    page.merge_page(PdfReader(BytesIO(overlay.getvalue())).pages[0])
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
