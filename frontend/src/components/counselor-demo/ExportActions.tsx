import React from 'react'
import { CheckCircle2, Download, Eye, Save, Printer } from 'lucide-react'
import type { ReviewStatus } from '../../hooks/useCounselorDemo'

interface ExportActionsProps {
  reviewStatus: ReviewStatus
  isDirty: boolean
  isExportingDocx: boolean
  onSaveTemporary: () => void
  onMarkAsReviewed: () => void
  onOpenPreview: () => void
  onExportDocx: () => void
  onPrintPDF: () => void
}

export const ExportActions: React.FC<ExportActionsProps> = ({
  reviewStatus,
  isDirty,
  isExportingDocx,
  onSaveTemporary,
  onMarkAsReviewed,
  onOpenPreview,
  onExportDocx,
  onPrintPDF,
}) => {
  return (
    <div className="print:hidden sticky bottom-0 z-20 bg-white/95 backdrop-blur-sm border-t border-slate-200 px-4 lg:px-6 py-3.5 shadow-lg">
      <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
        {/* Left Status & Save */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onSaveTemporary}
            disabled={!isDirty}
            className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-semibold border transition-all ${
              isDirty
                ? 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100 shadow-2xs'
                : 'bg-slate-50 text-slate-400 border-slate-200 cursor-not-allowed'
            }`}
          >
            <Save className="w-3.5 h-3.5" />
            {isDirty ? '수정사항 임시저장' : '저장 완료됨'}
          </button>

          {reviewStatus !== 'reviewed' ? (
            <button
              type="button"
              onClick={onMarkAsReviewed}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-xs font-bold bg-emerald-50 text-emerald-800 border border-emerald-300 hover:bg-emerald-100 transition-colors shadow-2xs"
            >
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              검토 완료 처리
            </button>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs font-bold text-emerald-700 bg-emerald-50 px-3 py-1.5 rounded-lg border border-emerald-200">
              <CheckCircle2 className="w-4 h-4 text-emerald-600" />
              상담사 검토 완료됨
            </span>
          )}
        </div>

        {/* Right Preview & Export Buttons */}
        <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
          <button
            type="button"
            onClick={onOpenPreview}
            className="inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-800 text-xs font-bold transition-all shadow-2xs"
          >
            <Eye className="w-4 h-4 text-blue-600" />
            상담일지 미리보기
          </button>

          <button
            type="button"
            onClick={onPrintPDF}
            className="inline-flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-lg border border-slate-300 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold transition-all shadow-2xs"
            title="브라우저 인쇄 창에서 PDF로 저장할 수 있습니다"
          >
            <Printer className="w-4 h-4 text-slate-600" />
            인쇄 / PDF
          </button>

          <button
            type="button"
            disabled={isExportingDocx}
            onClick={onExportDocx}
            className="inline-flex items-center justify-center gap-1.5 px-5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition-all shadow-xs disabled:opacity-50"
          >
            <Download className="w-4 h-4" />
            {isExportingDocx ? '내보내는 중...' : 'DOCX 다운로드'}
          </button>
        </div>
      </div>
    </div>
  )
}
