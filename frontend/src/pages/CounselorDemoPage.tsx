import React, { useState } from 'react'
import { DemoHeader } from '../components/counselor-demo/DemoHeader'
import { DraftReviewPanel } from '../components/counselor-demo/DraftReviewPanel'
import { EvidencePanel } from '../components/counselor-demo/EvidencePanel'
import { SessionSourcePanel } from '../components/counselor-demo/SessionSourcePanel'
import { FinalDocumentPreview } from '../components/counselor-demo/FinalDocumentPreview'
import { ExportActions } from '../components/counselor-demo/ExportActions'
import { ReviewStatusBar } from '../components/counselor-demo/ReviewStatusBar'
import { TemplateKbStatusCard } from '../components/counselor-demo/TemplateKbStatusCard'

import { useCounselorDemo } from '../hooks/useCounselorDemo'
import { useDocumentExport } from '../hooks/useDocumentExport'
import { Edit3, FileText, Layers } from 'lucide-react'

interface CounselorDemoPageProps {
  onBackToMain?: () => void
}

export default function CounselorDemoPage({ onBackToMain }: CounselorDemoPageProps) {
  const {
    demoData,
    sections,
    selectedSectionId,
    activeEvidenceItems,
    reviewStatus,
    isDirty,
    lastSavedAt,
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
  } = useDocumentExport()

  const [isPreviewOpen, setIsPreviewOpen] = useState(false)
  const [centerMode, setCenterMode] = useState<'draft' | 'sources'>('draft')

  const selectedSection = sections.find((s) => s.id === selectedSectionId) || sections[0]

  const handleExportDocx = (docType: 'session_note' | 'supervision_report' | 'termination_report' = 'supervision_report') => {
    exportDocx(demoData.clientInfo, sections, docType)
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
              원문 전체 자료 (STT/메모)
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
              <TemplateKbStatusCard
                templateContext={demoData.templateContext}
                retrievalReport={{
                  enabled: true,
                  case_context_count: 3,
                  template_context_found: true,
                  privacy_rule_count: 2,
                  embedding_latency_ms: 10,
                  rpc_latency_ms: 5,
                  retrieval_latency_ms: 15,
                  generation_latency_ms: 120,
                  failures: [],
                  notices: [],
                }}
                isDemo={true}
              />
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
        onSaveTemporary={saveTemporary}
        onMarkAsReviewed={markAsReviewed}
        onOpenPreview={() => setIsPreviewOpen(true)}
        onExportDocx={() => handleExportDocx('supervision_report')}
        onPrintPDF={printDocument}
      />

      {/* Printable Final Document Preview Modal */}
      <FinalDocumentPreview
        clientInfo={demoData.clientInfo}
        sections={sections}
        isOpen={isPreviewOpen}
        onClose={() => setIsPreviewOpen(false)}
        onExportDocx={handleExportDocx}
        onPrintPDF={printDocument}
        isExporting={isExportingDocx}
      />
    </div>
  )
}
