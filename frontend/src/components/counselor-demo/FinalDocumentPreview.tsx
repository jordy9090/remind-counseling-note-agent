import React, { useState } from 'react'
import { Download, Printer, X, FileCheck, ShieldCheck } from 'lucide-react'
import type { DemoClientInfo, DemoDraftSection } from '../../data/counselorDemoFixture'

interface FinalDocumentPreviewProps {
  clientInfo: DemoClientInfo
  sections: DemoDraftSection[]
  isOpen: boolean
  onClose: () => void
  onExportDocx: (docType: 'session_note' | 'supervision_report' | 'termination_report') => void
  onPrintPDF: () => void
  isExporting: boolean
}

export const FinalDocumentPreview: React.FC<FinalDocumentPreviewProps> = ({
  clientInfo,
  sections,
  isOpen,
  onClose,
  onExportDocx,
  onPrintPDF,
  isExporting,
}) => {
  const [docType, setDocType] = useState<'session_note' | 'supervision_report' | 'termination_report'>(
    'session_note',
  )

  if (!isOpen) return null

  const getTitle = () => {
    switch (docType) {
      case 'supervision_report':
        return '수퍼비전 제출 보고서'
      case 'termination_report':
        return '상담 종결 보고서'
      case 'session_note':
      default:
        return '심리상담 회기 일지'
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/60 backdrop-blur-xs flex items-center justify-center p-4 sm:p-6 print:p-0 print:bg-white print:static print:inset-auto">
      <div className="relative w-full max-w-4xl bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[92vh] print:max-h-none print:shadow-none print:border-none print:rounded-none">
        {/* Modal Top Header Bar */}
        <div className="print:hidden flex items-center justify-between px-6 py-4 bg-slate-900 text-white border-b border-slate-800">
          <div className="flex items-center gap-3">
            <FileCheck className="w-5 h-5 text-blue-400" />
            <h2 className="font-bold text-base">최종 문서 미리보기 & 내보내기</h2>
          </div>

          <div className="flex items-center gap-3">
            {/* Format type selector */}
            <div className="flex bg-slate-800 p-1 rounded-lg border border-slate-700 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setDocType('session_note')}
                className={`px-3 py-1 rounded-md transition-colors ${
                  docType === 'session_note' ? 'bg-blue-600 text-white shadow-xs' : 'text-slate-400 hover:text-white'
                }`}
              >
                기본 상담일지
              </button>
              <button
                type="button"
                onClick={() => setDocType('supervision_report')}
                className={`px-3 py-1 rounded-md transition-colors ${
                  docType === 'supervision_report'
                    ? 'bg-blue-600 text-white shadow-xs'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                수퍼비전 보고서
              </button>
              <button
                type="button"
                onClick={() => setDocType('termination_report')}
                className={`px-3 py-1 rounded-md transition-colors ${
                  docType === 'termination_report'
                    ? 'bg-blue-600 text-white shadow-xs'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                종결 보고서
              </button>
            </div>

            <button
              type="button"
              onClick={onClose}
              className="text-slate-400 hover:text-white p-1 rounded-md hover:bg-slate-800 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Modal Action Bar */}
        <div className="print:hidden px-6 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between flex-wrap gap-2 text-xs">
          <div className="flex items-center gap-1.5 text-slate-600 font-medium">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            상담사의 최종 검토 편집본이 반영된 정식 서식 문서입니다.
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onPrintPDF}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border border-slate-300 bg-white hover:bg-slate-100 text-slate-700 font-bold transition-colors shadow-2xs"
            >
              <Printer className="w-4 h-4 text-slate-600" />
              인쇄 / PDF로 저장
            </button>

            <button
              type="button"
              disabled={isExporting}
              onClick={() => onExportDocx(docType)}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-bold transition-colors shadow-xs disabled:opacity-50"
            >
              <Download className="w-4 h-4" />
              {isExporting ? 'DOCX 생성 중...' : 'DOCX 파일 다운로드'}
            </button>
          </div>
        </div>

        {/* Paper Document Preview Body */}
        <div className="p-8 sm:p-12 overflow-y-auto bg-slate-100 flex-1 print:p-0 print:bg-white">
          <div className="mx-auto max-w-[210mm] min-h-[297mm] bg-white border border-slate-300 print:border-none shadow-md print:shadow-none p-10 sm:p-14 text-slate-900 font-sans space-y-8">
            {/* Printable Document Title */}
            <div className="text-center border-b-2 border-slate-900 pb-5">
              <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-slate-950">
                {getTitle()}
              </h1>
              <p className="text-xs text-slate-500 font-medium mt-2">
                {clientInfo.institution} · Re:mind Counseling Workspace
              </p>
            </div>

            {/* Document Metadata Table */}
            <div className="border border-slate-300 rounded-sm overflow-hidden text-xs">
              <div className="grid grid-cols-2 sm:grid-cols-4 divide-x divide-y divide-slate-300 bg-slate-50 font-medium text-slate-700">
                <div className="p-2.5 bg-slate-100 font-bold text-slate-900">내담자 가명</div>
                <div className="p-2.5 bg-white font-bold">{clientInfo.name}</div>
                <div className="p-2.5 bg-slate-100 font-bold text-slate-900">사례 번호</div>
                <div className="p-2.5 bg-white font-mono">{clientInfo.caseId}</div>
                <div className="p-2.5 bg-slate-100 font-bold text-slate-900">회기 / 일시</div>
                <div className="p-2.5 bg-white">
                  {clientInfo.sessionNumber}회기 ({clientInfo.sessionDate})
                </div>
                <div className="p-2.5 bg-slate-100 font-bold text-slate-900">담당 상담사</div>
                <div className="p-2.5 bg-white">{clientInfo.counselorName}</div>
              </div>
            </div>

            {/* Document Sections */}
            <div className="space-y-6 text-slate-900">
              {sections.map((section, index) => (
                <div key={section.id} className="space-y-2">
                  <h3 className="text-sm font-bold text-slate-950 flex items-center gap-2 border-b border-slate-200 pb-1">
                    <span className="text-blue-700 font-mono">{index + 1}.</span> {section.title}
                  </h3>
                  <p className="text-xs sm:text-sm leading-relaxed text-slate-800 whitespace-pre-line font-normal pl-4">
                    {section.content}
                  </p>
                </div>
              ))}
            </div>

            {/* Official Footer Notice */}
            <div className="pt-10 border-t border-slate-200 text-[11px] text-slate-500 space-y-1 font-medium italic">
              <p>
                * 본 문서는 Re:mind AI가 생성한 요약 초안을 바탕으로 담당 상담사({clientInfo.counselorName})가 원문 근거 검토 및 직인/확인을 거쳐 직접 확정한 최종 회기 기록입니다.
              </p>
              <p className="text-right not-italic font-bold text-slate-700 pt-4">
                작성일: {new Date().toLocaleDateString('ko-KR')} | 담당 상담자: {clientInfo.counselorName} (인)
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
