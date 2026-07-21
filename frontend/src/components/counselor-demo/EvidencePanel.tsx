import React from 'react'
import { AlertTriangle, BookOpen, Quote, HelpCircle } from 'lucide-react'
import type { DemoEvidenceItem } from '../../data/counselorDemoFixture'
import { formatEvidence } from '../../lib/evidenceAdapter'

interface EvidencePanelProps {
  sectionTitle: string
  evidences: DemoEvidenceItem[]
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({ sectionTitle, evidences }) => {
  return (
    <aside className="w-full lg:w-[360px] shrink-0 bg-white rounded-xl border border-slate-200 shadow-xs flex flex-col h-full min-h-[500px]">
      {/* Evidence Panel Header */}
      <div className="px-5 py-4 border-b border-slate-200 bg-slate-50 rounded-t-xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BookOpen className="w-4 h-4 text-blue-600" />
            <h3 className="font-bold text-slate-900 text-sm">원문 근거 및 세션 자료</h3>
          </div>
          <span className="text-xs font-semibold px-2 py-0.5 rounded bg-blue-50 text-blue-700">
            {evidences.length}개 근거
          </span>
        </div>
        <p className="text-xs text-slate-500 mt-1 truncate">
          선택 항목: <span className="font-semibold text-slate-700">{sectionTitle}</span>
        </p>
      </div>

      {/* Evidence List */}
      <div className="p-4 space-y-4 overflow-y-auto flex-1 max-h-[calc(100vh-220px)]">
        {evidences.length === 0 ? (
          <div className="py-12 text-center text-slate-400 space-y-2">
            <HelpCircle className="w-8 h-8 mx-auto stroke-1" />
            <p className="text-xs">이 항목에 매핑된 직접 원문 근거가 없습니다.</p>
            <p className="text-[11px] text-slate-400">
              상담사의 직접 입력 또는 이전 회기 기록을 참고하세요.
            </p>
          </div>
        ) : (
          evidences.map((item) => {
            const visual = formatEvidence(item)
            return (
              <div
                key={item.id}
                className="p-4 rounded-lg border border-slate-200 bg-slate-50/50 hover:border-blue-200 hover:bg-blue-50/20 transition-all space-y-2.5"
              >
                {/* Source Badge & Label */}
                <div className="flex items-center justify-between flex-wrap gap-1">
                  <span
                    className={`text-[11px] font-bold px-2 py-0.5 rounded border ${visual.badgeBg} ${visual.badgeText}`}
                  >
                    {visual.badgeLabel}
                  </span>
                  <span className="text-xs font-mono font-medium text-slate-500">
                    {visual.sourceLabel}
                  </span>
                </div>

                {/* Excerpt Text */}
                <div className="relative pl-3 border-l-2 border-blue-400 bg-white p-2.5 rounded-r text-xs leading-relaxed font-normal text-slate-800 italic whitespace-pre-line">
                  <Quote className="w-3.5 h-3.5 text-blue-400 absolute -top-1 -left-2 bg-white rounded-full" />
                  {visual.excerpt}
                </div>

                {/* Connection Rationale */}
                <div className="text-xs text-slate-600 bg-slate-100/70 p-2 rounded">
                  <span className="font-semibold text-slate-700">근거 연결 이유:</span>{' '}
                  {visual.rationale}
                </div>

                {/* Clinical Warning if any */}
                {visual.warning && (
                  <div className="p-2 rounded bg-amber-50 border border-amber-200 text-xs text-amber-900 flex items-start gap-1.5 font-medium">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
                    <span>{visual.warning}</span>
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>

      {/* Footer Info */}
      <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 rounded-b-xl text-[11px] text-slate-500 leading-tight">
        💡 상담 문서는 회기 축어록 및 상담사 메모를 기반으로 추출되었습니다. 임상적 해석은 상담사의 판단을 우선합니다.
      </div>
    </aside>
  )
}
