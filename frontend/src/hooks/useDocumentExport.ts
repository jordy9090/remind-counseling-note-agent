import { useCallback, useEffect, useState } from 'react'
import {
  checkExportCapabilities,
  executeDocxExport,
  triggerBrowserPrint,
  type DocumentExportCapabilityStatus,
} from '../lib/documentExport'
import type { DemoClientInfo, DemoDraftSection } from '../data/counselorDemoFixture'
import { exportCounselorDemoDocx } from '../lib/clientDocxExport'

export interface UseDocumentExportReturn {
  capabilities: DocumentExportCapabilityStatus | null
  isExportingDocx: boolean
  exportSuccessMessage: string | null
  exportErrorMessage: string | null
  exportDocx: (
    clientInfo: DemoClientInfo,
    sections: DemoDraftSection[],
    docType?: 'session_note' | 'supervision_report' | 'termination_report',
    isDemo?: boolean,
  ) => Promise<void>
  printDocument: () => void
  clearMessages: () => void
}

interface UseDocumentExportOptions {
  localOnly?: boolean
}

const LOCAL_EXPORT_CAPABILITIES: DocumentExportCapabilityStatus = {
  docx: true,
  pdfServer: false,
  pdfReason: '브라우저 PDF 인쇄를 사용합니다.',
  hwpx: false,
  hwpxReason: 'HWPX 미지원',
}

export function useDocumentExport({ localOnly = false }: UseDocumentExportOptions = {}): UseDocumentExportReturn {
  const [capabilities, setCapabilities] = useState<DocumentExportCapabilityStatus | null>(
    localOnly ? LOCAL_EXPORT_CAPABILITIES : null,
  )
  const [isExportingDocx, setIsExportingDocx] = useState(false)
  const [exportSuccessMessage, setExportSuccessMessage] = useState<string | null>(null)
  const [exportErrorMessage, setExportErrorMessage] = useState<string | null>(null)

  useEffect(() => {
    if (localOnly) return
    checkExportCapabilities().then(setCapabilities).catch(() => {
      setCapabilities({
        docx: true,
        pdfServer: false,
        pdfReason: '서버 PDF 렌더링 라이브러리 미설치 (브라우저 PDF 인쇄를 이용해주세요)',
        hwpx: false,
        hwpxReason: 'HWPX 기능 준비 중',
      })
    })
  }, [localOnly])

  const exportDocx = useCallback(
    async (
      clientInfo: DemoClientInfo,
      sections: DemoDraftSection[],
      docType: 'session_note' | 'supervision_report' | 'termination_report' = 'session_note',
      isDemo: boolean = false,
    ) => {
      setIsExportingDocx(true)
      setExportErrorMessage(null)
      setExportSuccessMessage(null)

      try {
        if (isDemo) {
          const filename = await exportCounselorDemoDocx(clientInfo, sections)
          setExportSuccessMessage(`문서 파일 (${filename}) 다운로드를 시작했습니다.`)
        } else {
          const filename = await executeDocxExport(clientInfo, sections, docType)
          setExportSuccessMessage(`상담일지 파일 (${filename}) 다운로드를 시작했습니다.`)
        }
      } catch (error) {
        console.error('Document export error:', error)
        if (isDemo) {
          setExportErrorMessage('문서 파일을 생성하지 못했습니다. 다시 시도해주세요.')
        } else {
          setExportErrorMessage('문서 다운로드에 실패했습니다. 잠시 후 다시 시도해주세요.')
        }
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
