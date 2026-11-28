"""Write native, editable HWPX from our internally rendered DOCX document.

This is deliberately not an arbitrary DOCX upload converter. The trusted blank
package supplies the OWPML manifest and defaults; only our paragraphs and tables
are translated. Text is serialized by lxml, never interpolated into XML.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from lxml import etree as ET

TEMPLATE = Path(__file__).resolve().parents[1] / "templates/vouchers/2026/source/form25-blank.hwpx"
NS = {key: f"http://www.hancom.co.kr/hwpml/2011/{value}" for key, value in
      (("hp", "paragraph"), ("hh", "head"), ("hc", "core"))}


def element(parent, qualified_name, **attributes):
    prefix, tag = qualified_name.split(":")
    return ET.SubElement(parent, "{" + NS[prefix] + "}" + tag,
                         {key: str(value) for key, value in attributes.items()})


def inherited(obj, attribute, default=None):
    value = getattr(obj, attribute)
    return default if value is None else value


class HwpxWriter:
    def __init__(self, source, document):
        parser = ET.XMLParser(resolve_entities=False, no_network=True)
        self.header = ET.fromstring(source.read("Contents/header.xml"), parser)
        self.section = ET.fromstring(source.read("Contents/section0.xml"), parser)
        self.first_run = deepcopy(self.section[0][0])
        self.section.clear(keep_tail=True)
        self.chars = self.header.find(".//hh:charProperties", NS)
        self.paras = self.header.find(".//hh:paraProperties", NS)
        self.borders = self.header.find(".//hh:borderFills", NS)
        self.char_cache, self.para_cache, self.border_cache = {}, {}, {}
        self.next_id = 0
        self.preview = []
        self.list_number = 0
        page = document.sections[0]
        units = lambda length: round(length / 127)
        self.width = units(page.page_width - page.left_margin - page.right_margin)
        self.first_run.find(".//hp:pagePr", NS).attrib.update(
            {"width": str(units(page.page_width)), "height": str(units(page.page_height))})
        self.first_run.find(".//hp:margin", NS).attrib.update(
            {key: str(units(value)) for key, value in {
                "left": page.left_margin, "right": page.right_margin,
                "top": page.top_margin, "bottom": page.bottom_margin,
                "header": 0, "footer": 0,
            }.items() if value})
        # No running header/footer is copied from the blank template.
        self.first_run.find(".//hp:margin", NS).attrib.update({"header": "0", "footer": "0"})
        for font in self.header.findall(".//hh:font", NS):
            font.set("face", "맑은 고딕")

    def identifier(self):
        self.next_id += 1
        return str(self.next_id)

    def border(self, fill=None):
        if fill not in self.border_cache:
            border = deepcopy(self.borders[0])
            identifier = str(max(int(item.get("id")) for item in self.borders) + 1)
            border.set("id", identifier)
            for side in ("left", "right", "top", "bottom"):
                border.find(f"hh:{side}Border", NS).set("type", "SOLID")
            if fill:
                brush = element(border, "hc:fillBrush")
                element(brush, "hc:winBrush", faceColor="#" + fill, hatchColor="#000000", alpha="0")
            self.borders.append(border)
            self.border_cache[fill] = identifier
        return self.border_cache[fill]

    def char_style(self, run, paragraph):
        base = paragraph.style.font
        size = inherited(run.font, "size", base.size)
        color = run.font.color.rgb or base.color.rgb
        shading = run._r.find("w:rPr/w:shd", run._r.nsmap)
        fill = shading.get(qn("w:fill")) if shading is not None else None
        if fill and not re.fullmatch(r"[0-9A-Fa-f]{6}", fill):
            fill = None
        key = (round(size.pt * 100) if size else 1050,
               inherited(run, "bold", base.bold), inherited(run, "italic", base.italic),
               inherited(run, "underline", base.underline), str(color or "000000"), fill)
        if key not in self.char_cache:
            char = deepcopy(self.chars[0])
            identifier = str(len(self.chars))
            char.attrib.update({"id": identifier, "height": str(key[0]), "textColor": "#" + key[4],
                                "shadeColor": "#" + fill if fill else "none"})
            underline = char.find("hh:underline", NS)
            for flag, tag in ((key[1], "bold"), (key[2], "italic")):
                if flag:
                    char.insert(char.index(underline), ET.Element("{" + NS["hh"] + "}" + tag))
            if key[3]:
                underline.set("type", "BOTTOM")
            self.chars.append(char)
            self.char_cache[key] = identifier
        return self.char_cache[key]

    def para_style(self, paragraph):
        fmt, base = paragraph.paragraph_format, paragraph.style.paragraph_format
        alignment = inherited(fmt, "alignment", base.alignment)
        keep = inherited(fmt, "keep_with_next", base.keep_with_next)
        before, after = inherited(fmt, "space_before", base.space_before), inherited(fmt, "space_after", base.space_after)
        boxed = paragraph._p.find("w:pPr/w:pBdr", paragraph._p.nsmap) is not None
        key = (str(alignment), bool(keep), round(before.pt * 200) if before else 0,
               round(after.pt * 200) if after else 0, boxed)
        if key not in self.para_cache:
            para = deepcopy(self.paras[0])
            identifier = str(len(self.paras))
            para.attrib.update({"id": identifier, "snapToGrid": "0"})
            para.find("hh:align", NS).set("horizontal", {"CENTER (1)": "CENTER", "RIGHT (2)": "RIGHT"}.get(key[0], "LEFT"))
            para.find("hh:breakSetting", NS).set("keepWithNext", "1" if keep else "0")
            for margin in para.findall(".//hh:margin", NS):
                margin.find("hc:prev", NS).set("value", str(key[2]))
                margin.find("hc:next", NS).set("value", str(key[3]))
            if boxed:
                para.find("hh:border", NS).attrib.update({"borderFillIDRef": self.border(), "offsetTop": "700", "offsetBottom": "700"})
            self.paras.append(para)
            self.para_cache[key] = identifier
        return self.para_cache[key]

    def paragraph(self, paragraph, parent):
        p = element(parent, "hp:p", id=self.identifier(), paraPrIDRef=self.para_style(paragraph),
                    styleIDRef="0", pageBreak="0", columnBreak="0", merged="0")
        if len(self.section) == 1 and parent is self.section:
            p.append(self.first_run)
        prefix = ""
        if paragraph.style.name == "List Bullet":
            prefix = "• "
        elif paragraph.style.name == "List Number":
            self.list_number += 1
            prefix = f"{self.list_number}. "
        else:
            self.list_number = 0
        visible = []
        for run in paragraph.runs:
            if run.font.hidden:
                continue
            text = prefix + run.text
            prefix = ""
            visible.append(text)
            r = element(p, "hp:run", charPrIDRef=self.char_style(run, paragraph))
            t = element(r, "hp:t")
            for index, line in enumerate(text.replace("\t", "    ").split("\n")):
                if index == 0:
                    t.text = line
                else:
                    element(t, "hp:lineBreak").tail = line
        if not p.findall("hp:run", NS):
            element(element(p, "hp:run", charPrIDRef="0"), "hp:t")
        self.preview.append("".join(visible))
        return p

    def table(self, table):
        anchor = element(self.section, "hp:p", id=self.identifier(), paraPrIDRef="0", styleIDRef="0",
                         pageBreak="0", columnBreak="0", merged="0")
        r = element(anchor, "hp:run", charPrIDRef="0")
        widths = [float(cell.width or 1) for cell in table.rows[0].cells]
        widths = [round(self.width * width / sum(widths)) for width in widths]
        widths[-1] += self.width - sum(widths)
        t = element(r, "hp:tbl", id=self.identifier(), zOrder="0", numberingType="TABLE",
                    textWrap="TOP_AND_BOTTOM", textFlow="BOTH_SIDES", lock="0", dropcapstyle="None",
                    pageBreak="CELL", repeatHeader="1", rowCnt=len(table.rows), colCnt=len(widths),
                    cellSpacing="0", borderFillIDRef=self.border(), noAdjust="0")
        size = element(t, "hp:sz", width=self.width, widthRelTo="ABSOLUTE", height="0", heightRelTo="ABSOLUTE", protect="0")
        element(t, "hp:pos", treatAsChar="0", affectLSpacing="0", flowWithText="1", allowOverlap="0",
                holdAnchorAndSO="0", vertRelTo="PARA", horzRelTo="COLUMN", vertAlign="TOP",
                horzAlign="LEFT", vertOffset="0", horzOffset="0")
        element(t, "hp:outMargin", left="0", right="0", top="300", bottom="300")
        element(t, "hp:inMargin", left="500", right="500", top="300", bottom="300")
        height = 0
        for row_index, row in enumerate(table.rows):
            tr = element(t, "hp:tr")
            is_header = row._tr.find("w:trPr/w:tblHeader", row._tr.nsmap) is not None
            row_height = 2200
            cells = []
            for col_index, cell in enumerate(row.cells):
                shd = cell._tc.find("w:tcPr/w:shd", cell._tc.nsmap)
                fill = shd.get(qn("w:fill")) if shd is not None else None
                tc = element(tr, "hp:tc", name="", header=int(is_header), hasMargin="1", protect="0",
                             editable="0", dirty="0", borderFillIDRef=self.border(fill))
                sub = element(tc, "hp:subList", id=self.identifier(), textDirection="HORIZONTAL", lineWrap="BREAK",
                              vertAlign="TOP", linkListIDRef="0", linkListNextIDRef="0", textWidth="0",
                              textHeight="0", hasTextRef="0", hasNumRef="0")
                for paragraph in cell.paragraphs:
                    self.paragraph(paragraph, sub)
                element(tc, "hp:cellAddr", colAddr=col_index, rowAddr=row_index)
                element(tc, "hp:cellSpan", colSpan="1", rowSpan="1")
                cells.append(element(tc, "hp:cellSz", width=widths[col_index], height="0"))
                element(tc, "hp:cellMargin", left="500", right="500", top="300", bottom="300")
                # A minimum estimate only: the editor lays out the full text and paginates cells.
                lines = sum(max(1, (sum(2 if ord(c) > 127 else 1 for c in line) * 530 + widths[col_index] - 1001)
                                    // max(1, widths[col_index] - 1000)) for line in cell.text.split("\n"))
                row_height = max(row_height, lines * 1700 + 600)
            for cell_size in cells:
                cell_size.set("height", str(row_height))
            height += row_height
        size.set("height", str(height))
        element(r, "hp:t")


def docx_to_hwpx(content: bytes) -> bytes:
    document = Document(BytesIO(content))
    with ZipFile(TEMPLATE) as source:
        writer = HwpxWriter(source, document)
        for child in document.element.body:
            if child.tag == qn("w:p"):
                writer.paragraph(Paragraph(child, document), writer.section)
            elif child.tag == qn("w:tbl"):
                writer.table(Table(child, document))
        for paragraph in document.sections[0].footer.paragraphs:
            if paragraph.text:
                writer.paragraph(paragraph, writer.section)
        for group in (writer.chars, writer.paras, writer.borders):
            group.set("itemCnt", str(len(group)))
        replacements = {
            "Contents/header.xml": ET.tostring(writer.header, encoding="UTF-8", xml_declaration=True),
            "Contents/section0.xml": ET.tostring(writer.section, encoding="UTF-8", xml_declaration=True),
            "Preview/PrvText.txt": "\n".join(writer.preview).encode("utf-8"),
        }
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            for entry in source.infolist():
                if entry.filename == "Preview/PrvImage.png":
                    continue
                archive.writestr(entry.filename, replacements.get(entry.filename, source.read(entry.filename)),
                                 compress_type=ZIP_STORED if entry.filename == "mimetype" else ZIP_DEFLATED)
        return output.getvalue()
