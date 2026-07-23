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
import type { SupervisionContentBlock, SupervisionReportDraft } from '../types/session'

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

export interface ResolvedSupervisionMeta {
  clientAlias: string
  counselorName: string
  institution: string
  supervisor: string
  supervisionDatePlace: string
}

function blockTextParagraphs(block: SupervisionContentBlock): Array<Paragraph | Table> {
  if (block.type === 'table' && block.rows?.length) {
    const headers = Object.keys(block.rows[0])
    return [new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      borders: { top: border, bottom: border, left: border, right: border, insideHorizontal: border, insideVertical: border },
      rows: [
        new TableRow({ children: headers.map((header) => new TableCell({
          shading: { fill: 'F1F5F9' },
          margins: { top: 80, right: 100, bottom: 80, left: 100 },
          children: [new Paragraph({ children: [text(header, true)] })],
        })) }),
        ...block.rows.map((row) => new TableRow({ children: headers.map((header) => new TableCell({
          margins: { top: 80, right: 100, bottom: 80, left: 100 },
          children: [new Paragraph({ children: [text(String(row[header] || ''))] })],
        })) })),
      ],
    })]
  }

  if (block.type === 'transcript' && block.speakerTurns?.length) {
    return block.speakerTurns.map((turn) => new Paragraph({
      spacing: { after: 100, line: 320 },
      children: [
        text(`${turn.speaker === 'client' ? '내담자' : '상담자'}: `, true),
        text(turn.text),
      ],
    }))
  }

  const rawText = (block.text || '').trim()
  if (!rawText || rawText === '[상담사 확인 필요]' || rawText.includes('상담사 확인 필요')) {
    return block.type === 'placeholder'
      ? [new Paragraph({ spacing: { after: 100 }, children: [text('추가 확인 필요')] })]
      : []
  }

  return rawText.split(/\r?\n/).filter(Boolean).map((line) => {
    const listMatch = line.match(/^\s*[-*•]\s+(.*)$/)
    return new Paragraph({
      spacing: { after: 100, line: 320 },
      ...(listMatch ? { bullet: { level: 0 } } : {}),
      children: [text((listMatch?.[1] || line).trim())],
    })
  })
}

export async function exportSupervisionReportDocx(
  report: SupervisionReportDraft,
  resolvedMeta: ResolvedSupervisionMeta,
): Promise<string> {
  const body = report.sections.flatMap((section) => [
    new Paragraph({
      heading: section.level === 1 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2,
      spacing: { before: section.level === 1 ? 360 : 240, after: 120 },
      children: [new TextRun({
        text: section.title,
        bold: true,
        font: FONT,
        size: section.level === 1 ? 30 : 26,
      })],
    }),
    ...section.contentBlocks.flatMap(blockTextParagraphs),
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
            metadataRow('내담자', resolvedMeta.clientAlias),
            metadataRow('회기', `${report.meta.sessionNumber}회기`),
            metadataRow('기준일', report.meta.reportDate),
            metadataRow('상담자', resolvedMeta.counselorName),
            metadataRow('소속 상담기관', resolvedMeta.institution),
            metadataRow('수퍼바이저', resolvedMeta.supervisor),
            metadataRow('수퍼비전 일시 및 장소', resolvedMeta.supervisionDatePlace),
          ],
        }),
        ...body,
      ],
    }],
  })

  const blob = await Packer.toBlob(doc)
  const safeAlias = resolvedMeta.clientAlias.replace(/\s+/g, '').replace(/[\\/:*?"<>|]/g, '_')
  const filename = `개인상담_수퍼비전_보고서_${safeAlias}_${report.meta.sessionNumber}회기.docx`
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
