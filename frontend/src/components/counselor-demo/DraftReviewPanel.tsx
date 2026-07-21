import React from 'react'
import { DraftSectionEditor } from './DraftSectionEditor'
import type { DemoDraftSection } from '../../data/counselorDemoFixture'
import { Info, ShieldAlert } from 'lucide-react'

interface DraftReviewPanelProps {
  sections: DemoDraftSection[]
  selectedSectionId: string
  onSelectSection: (id: string) => void
  onUpdateSectionContent: (id: string, newContent: string) => void
  missingItems: string[]
  warnings: string[]
}

export const DraftReviewPanel: React.FC<DraftReviewPanelProps> = ({
  sections,
  selectedSectionId,
  onSelectSection,
  onUpdateSectionContent,
  missingItems,
  warnings,
}) => {
  return (
    <div className="space-y-6">
      {/* Top Banner Notice */}
      <div className="rounded-xl border border-blue-100 bg-gradient-to-r from-blue-50/80 to-slate-50 p-4 text-xs leading-relaxed text-slate-700 shadow-2xs">
        <div className="flex items-start gap-2.5">
          <Info className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-bold text-slate-900 text-sm">
              상담사 전용 검토 워크스페이스
            </p>
            <p className="text-slate-600">
              AI가 세션 자료(축어록·메모·이전 기록)에서 추출하여 작성한 요약 초안입니다.
              각 항목을 클릭하면 오른쪽 원문 근거와 비교하며 자유롭게 수정하고 검토를 완료할 수 있습니다.
            </p>
          </div>
        </div>
      </div>

      {/* Warnings & Missing Checklist if present */}
      {(missingItems.length > 0 || warnings.length > 0) && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 text-xs space-y-2">
          <div className="flex items-center gap-1.5 font-bold text-amber-900 text-sm">
            <ShieldAlert className="w-4 h-4 text-amber-600" />
            상담사 검토 및 유의사항
          </div>
          <ul className="list-disc list-inside space-y-1 text-amber-900 font-medium pl-1">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
            {missingItems.map((m, i) => (
              <li key={`m-${i}`} className="text-amber-950 font-semibold">
                [확인 필요] {m}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Structured Sections */}
      <div className="space-y-4">
        {sections.map((section) => (
          <DraftSectionEditor
            key={section.id}
            section={section}
            isSelected={section.id === selectedSectionId}
            onSelect={() => onSelectSection(section.id)}
            onUpdateContent={(content) => onUpdateSectionContent(section.id, content)}
          />
        ))}
      </div>
    </div>
  )
}
