import React, { useEffect, useState } from 'react'
import { DemoHeader } from '../components/counselor-demo/DemoHeader'
import { DraftReviewPanel } from '../components/counselor-demo/DraftReviewPanel'
import { EvidencePanel } from '../components/counselor-demo/EvidencePanel'
import { SessionSourcePanel } from '../components/counselor-demo/SessionSourcePanel'
import { FinalDocumentPreview } from '../components/counselor-demo/FinalDocumentPreview'
import { ExportActions } from '../components/counselor-demo/ExportActions'
import { ReviewStatusBar } from '../components/counselor-demo/ReviewStatusBar'

import { useCounselorDemo } from '../hooks/useCounselorDemo'
import { useDocumentExport } from '../hooks/useDocumentExport'
import {
  DEMO_DOCUMENT_LABELS,
  DEMO_DOCUMENT_ORDER,
  type DemoDocumentType,
} from '../data/counselorDemoFixture'
import { Edit3, FileText, Layers } from 'lucide-react'

interface CounselorDemoPageProps {
  onBackToMain?: () => void
}

export default function CounselorDemoPage({ onBackToMain }: CounselorDemoPageProps) {
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0 })
  }, [])

  const {
    demoData,
    sections,
    activeDocumentType,
    selectedSectionId,
    activeEvidenceItems,
    reviewStatus,
    isDirty,
    lastSavedAt,
    confirmationStatus,
    confirmationMessage,
    setActiveDocumentType,
    setSelectedSectionId,
    updateSectionContent,
    markAsReviewed,
    saveTemporary,
    resetDemo,
  } = useCounselorDemo()

  const {
    isExportingDocx,
    exportSuccessMessage,
    exportErrorMessage,
    exportDocx,
    printDocument,
    clearMessages,
  } = useDocumentExport({ localOnly: true })

  const [isPreviewOpen, setIsPreviewOpen] = useState(false)
  const [centerMode, setCenterMode] = useState<'draft' | 'sources'>('draft')

  const selectedSection = sections.find((s) => s.id === selectedSectionId) || sections[0]

  const handleExportDocx = (docType: DemoDocumentType = activeDocumentType) => {
    const exportType = docType === 'supervision_report' ? 'supervision_report' : 'session_note'
    exportDocx(demoData.clientInfo, sections, exportType, true)
  }

  return (
    <div className="min-h-screen bg-slate-100/70 text-slate-900 flex flex-col font-sans selection:bg-blue-100">
      {/* Top Notification Toast Bar */}
      <ReviewStatusBar
        successMessage={exportSuccessMessage}
        errorMessage={exportErrorMessage}
        onClear={clearMessages}
      />

      {/* Persistent Workspace Header */}
      <DemoHeader
        clientInfo={demoData.clientInfo}
        reviewStatus={reviewStatus}
        isDirty={isDirty}
        lastSavedAt={lastSavedAt}
        onResetDemo={resetDemo}
        onBackToMain={onBackToMain}
      />

      {/* Sub-header Controls / View Switcher */}
      <div className="print:hidden bg-white border-b border-slate-200 px-4 lg:px-6 py-2">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg text-xs font-bold">
            <button
              type="button"
              onClick={() => setCenterMode('draft')}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-colors ${
                centerMode === 'draft'
                  ? 'bg-white text-blue-700 shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Edit3 className="w-3.5 h-3.5" />
              1. AI 초안 검토 & 수정
            </button>
            <button
              type="button"
              onClick={() => setCenterMode('sources')}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md transition-colors ${
                centerMode === 'sources'
                  ? 'bg-white text-blue-700 shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              원문 자료 · 1~4회기
            </button>
          </div>

          <button
            type="button"
            onClick={() => setIsPreviewOpen(true)}
            className="inline-flex items-center gap-1.5 text-xs font-bold text-slate-700 hover:text-blue-700 bg-slate-50 hover:bg-blue-50 border border-slate-200 px-3 py-1.5 rounded-lg transition-colors"
          >
            <FileText className="w-3.5 h-3.5 text-blue-600" />
            2. 최종 상담일지 서식 보기
          </button>
        </div>
      </div>

      {/* Main Content Workspace Layout */}
      <main className="flex-1 max-w-7xl w-full mx-auto p-4 lg:p-6 flex flex-col lg:flex-row gap-6 items-start">
        {/* Center Panel (Draft or Raw Sources) */}
        <div className="flex-1 min-w-0 w-full">
          {centerMode === 'draft' ? (
            <>
              <div className="mb-4 rounded-xl border border-blue-200 bg-white p-3 shadow-2xs">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <p className="text-xs font-bold text-slate-900">사전 생성된 5회기 문서</p>
                    <p className="mt-0.5 text-[11px] text-slate-500">
                      이 화면은 저장된 MusPsy 결과를 불러오며 생성·저장 API를 호출하지 않습니다.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1">
                    {DEMO_DOCUMENT_ORDER.map((documentType) => (
                      <button
                        key={documentType}
                        type="button"
                        aria-pressed={activeDocumentType === documentType}
                        onClick={() => setActiveDocumentType(documentType)}
                        className={`rounded-md px-3 py-1.5 text-xs font-bold transition-colors ${
                          activeDocumentType === documentType
                            ? 'bg-white text-blue-700 shadow-2xs'
                            : 'text-slate-600 hover:text-slate-900'
                        }`}
                      >
                        {DEMO_DOCUMENT_LABELS[documentType]}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              {confirmationMessage && (
                <p
                  className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
                    confirmationStatus === 'confirmed'
                      ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                      : 'border-red-200 bg-red-50 text-red-900'
                  }`}
                >
                  {confirmationMessage}
                </p>
              )}
              <DraftReviewPanel
                sections={sections}
                selectedSectionId={selectedSectionId}
                onSelectSection={setSelectedSectionId}
                onUpdateSectionContent={updateSectionContent}
                missingItems={demoData.missingItems}
                warnings={demoData.warnings}
              />
            </>
          ) : (
            <SessionSourcePanel demoData={demoData} />
          )}
        </div>

        {/* Right Side Evidence Panel (Persistent Sidebar ~360px) */}
        <EvidencePanel
          sectionTitle={selectedSection?.title || '주호소'}
          evidences={activeEvidenceItems}
        />
      </main>

      {/* Bottom Sticky Action Bar */}
      <ExportActions
        reviewStatus={reviewStatus}
        isDirty={isDirty}
        isExportingDocx={isExportingDocx}
        isConfirming={false}
        onSaveTemporary={saveTemporary}
        onMarkAsReviewed={markAsReviewed}
        onOpenPreview={() => setIsPreviewOpen(true)}
        onExportDocx={() => handleExportDocx(activeDocumentType)}
        onPrintPDF={printDocument}
      />

      {/* Printable Final Document Preview Modal */}
      <FinalDocumentPreview
        clientInfo={demoData.clientInfo}
        sections={sections}
        documentType={activeDocumentType}
        onDocumentTypeChange={setActiveDocumentType}
        isOpen={isPreviewOpen}
        onClose={() => setIsPreviewOpen(false)}
        onExportDocx={handleExportDocx}
        onPrintPDF={printDocument}
        isExporting={isExportingDocx}
      />
    </div>
  )
}
