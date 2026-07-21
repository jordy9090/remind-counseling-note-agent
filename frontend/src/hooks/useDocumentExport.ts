import { useCallback, useEffect, useState } from 'react'
import {
  checkExportCapabilities,
  executeDocxExport,
  triggerBrowserPrint,
  type DocumentExportCapabilityStatus,
} from '../lib/documentExport'
import type { DemoClientInfo, DemoDraftSection } from '../data/counselorDemoFixture'

export interface UseDocumentExportReturn {
  capabilities: DocumentExportCapabilityStatus | null
  isExportingDocx: boolean
  exportSuccessMessage: string | null
  exportErrorMessage: string | null
  exportDocx: (
    clientInfo: DemoClientInfo,
    sections: DemoDraftSection[],
    docType?: 'session_note' | 'supervision_report' | 'termination_report',
  ) => Promise<void>
  printDocument: () => void
  clearMessages: () => void
}

export function useDocumentExport(): UseDocumentExportReturn {
  const [capabilities, setCapabilities] = useState<DocumentExportCapabilityStatus | null>(null)
  const [isExportingDocx, setIsExportingDocx] = useState(false)
  const [exportSuccessMessage, setExportSuccessMessage] = useState<string | null>(null)
  const [exportErrorMessage, setExportErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    checkExportCapabilities().then(setCapabilities).catch(() => {
      setCapabilities({
        docx: true,
        pdfServer: false,
        pdfReason: '서버 PDF 렌더링 라이브러리 미설치 (브라우저 PDF 인쇄를 이용해주세요)',
        hwpx: false,
        hwpxReason: 'HWPX 기능 준비 중',
      })
    })
  }, [])

  const exportDocx = useCallback(
    async (
      clientInfo: DemoClientInfo,
      sections: DemoDraftSection[],
      docType: 'session_note' | 'supervision_report' | 'termination_report' = 'session_note',
    ) => {
      setIsExportingDocx(true)
      setExportErrorMessage(null)
      setExportSuccessMessage(null)

      try {
        const filename = await executeDocxExport(clientInfo, sections, docType)
        setExportSuccessMessage(`상담일지 파일 (${filename}) 다운로드를 시작했습니다.`)
      } catch (error) {
        const msg = error instanceof Error ? error.message : 'DOCX 내보내기 중 오류가 발생했습니다.'
        setExportErrorMessage(msg)
      } finally {
        setIsExportingDocx(false)
      }
    },
    [],
  )

  const printDocument = useCallback(() => {
    triggerBrowserPrint()
  }, [])

  const clearMessages = useCallback(() => {
    setExportSuccessMessage(null)
    setExportErrorMessage(null)
  }, [])

  return {
    capabilities,
    isExportingDocx,
    exportSuccessMessage,
    exportErrorMessage,
    exportDocx,
    printDocument,
    clearMessages,
  }
}
