import {
  AlignmentType,
  BorderStyle,
  Document,
  HeadingLevel,
  Packer,
  Paragraph,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from 'docx'
import type { DemoClientInfo, DemoDraftSection } from '../data/counselorDemoFixture'

const FONT = 'Malgun Gothic'
const border = { style: BorderStyle.SINGLE, size: 4, color: 'CBD5E1' }

function text(value: string, bold = false): TextRun {
  return new TextRun({ text: value, bold, font: FONT, size: 21 })
}

function metadataRow(label: string, value: string): TableRow {
  return new TableRow({
    children: [
      new TableCell({
        width: { size: 25, type: WidthType.PERCENTAGE },
        shading: { fill: 'F1F5F9' },
        margins: { top: 100, right: 120, bottom: 100, left: 120 },
        children: [new Paragraph({ children: [text(label, true)] })],
      }),
      new TableCell({
        width: { size: 75, type: WidthType.PERCENTAGE },
        margins: { top: 100, right: 120, bottom: 100, left: 120 },
        children: [new Paragraph({ children: [text(value || '미입력')] })],
      }),
    ],
  })
}

export async function exportCounselorDemoDocx(
  clientInfo: DemoClientInfo,
  sections: DemoDraftSection[],
): Promise<string> {
  const body = sections.flatMap((section) => [
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 280, after: 120 },
      children: [new TextRun({ text: section.title, bold: true, font: FONT, size: 28 })],
    }),
    ...section.content.split(/\r?\n/).map(
      (line) => new Paragraph({
        spacing: { after: 120, line: 340 },
        children: [new TextRun({ text: line || ' ', font: FONT, size: 22 })],
      }),
    ),
  ])

  const doc = new Document({
    styles: { default: { document: { run: { font: FONT, size: 22 } } } },
    sections: [{
      properties: { page: { margin: { top: 1000, right: 1000, bottom: 1000, left: 1000 } } },
      children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 360 },
          children: [new TextRun({ text: '개인상담 사례 수퍼비전 보고서', bold: true, font: FONT, size: 36 })],
        }),
        new Table({
          width: { size: 100, type: WidthType.PERCENTAGE },
          borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
          rows: [
            metadataRow('내담자 가명', clientInfo.name),
            metadataRow('사례 ID', clientInfo.caseId),
            metadataRow('회기', `${clientInfo.sessionNumber}회기`),
            metadataRow('기준일', clientInfo.sessionDate),
            metadataRow('상담자', clientInfo.counselorName),
            metadataRow('소속 상담기관', clientInfo.institution),
            metadataRow('수퍼바이저', clientInfo.supervisor || ''),
            metadataRow('수퍼비전 일시 및 장소', clientInfo.supervisionDatePlace || ''),
          ],
        }),
        ...body,
      ],
    }],
  })

  const blob = await Packer.toBlob(doc)
  const safeName = clientInfo.name.replace(/\s*\(가명\)\s*/g, '').replace(/[\\/:*?"<>|]/g, '_')
  const filename = `개인상담_수퍼비전_보고서_${safeName}_${clientInfo.sessionNumber}회기.docx`
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
  return filename
}
