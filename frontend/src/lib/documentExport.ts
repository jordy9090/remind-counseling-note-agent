import { downloadDocumentExport, getDocumentCapabilities } from '../api/client'
import type { DocumentCapabilitiesResponse, DocumentExportRequest, DocumentExportSection } from '../types/session'
import type { DemoClientInfo, DemoDraftSection } from '../data/counselorDemoFixture'

export interface DocumentExportCapabilityStatus {
  docx: boolean
  pdfServer: boolean
  pdfReason: string | null
  hwpx: boolean
  hwpxReason: string | null
}

export async function checkExportCapabilities(): Promise<DocumentExportCapabilityStatus> {
  try {
    const caps: DocumentCapabilitiesResponse = await getDocumentCapabilities()
    return {
      docx: Boolean(caps.docx?.available),
      pdfServer: Boolean(caps.pdf?.available),
      pdfReason: caps.pdf?.reason || '서버 PDF 엔진 미설치 (브라우저 PDF 인쇄 가능)',
      hwpx: Boolean(caps.hwpx?.available),
      hwpxReason: caps.hwpx?.reason || 'HWPX 템플릿 준비 중',
    }
  } catch {
    return {
      docx: true,
      pdfServer: false,
      pdfReason: '백엔드 연결 실패 - 브라우저 PDF 저장 기능을 사용합니다.',
      hwpx: false,
      hwpxReason: 'HWPX 미지원',
    }
  }
}

export function buildExportRequestFromDemo(
  clientInfo: DemoClientInfo,
  sections: DemoDraftSection[],
  format: 'docx' | 'pdf' | 'hwpx',
  documentType: 'session_note' | 'supervision_report' | 'termination_report' = 'session_note',
): DocumentExportRequest {
  const documentSections: DocumentExportSection[] = sections.map((s, index) => ({
    id: s.id,
    title: s.title,
    level: 1,
    content: s.content,
  }))

  const typeTitle =
    documentType === 'supervision_report'
      ? '수퍼비전 보고서'
      : documentType === 'termination_report'
        ? '종결 보고서'
        : '상담일지'

  return {
    document_type: documentType,
    format,
    case_id: clientInfo.caseId,
    session_number: clientInfo.sessionNumber,
    session_date: clientInfo.sessionDate,
    title: `${clientInfo.name} ${clientInfo.sessionNumber}회기 ${typeTitle}`,
    metadata: {
      client_alias: clientInfo.name,
      counselor_name: clientInfo.counselorName,
      institution: clientInfo.institution,
      counseling_goal: clientInfo.counselingGoal,
    },
    sections: documentSections,
  }
}

export async function executeDocxExport(
  clientInfo: DemoClientInfo,
  sections: DemoDraftSection[],
  documentType: 'session_note' | 'supervision_report' | 'termination_report' = 'session_note',
): Promise<string> {
  const request = buildExportRequestFromDemo(clientInfo, sections, 'docx', documentType)
  const { blob, filename } = await downloadDocumentExport(request)

  const url = window.URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  window.URL.revokeObjectURL(url)

  return filename
}

export function triggerBrowserPrint(): void {
  window.print()
}
