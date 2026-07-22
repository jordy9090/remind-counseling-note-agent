import React, { useState } from 'react'
import { Check, Edit3, ShieldAlert, Sparkles, X } from 'lucide-react'
import type { DemoDraftSection } from '../../data/counselorDemoFixture'

interface DraftSectionEditorProps {
  section: DemoDraftSection
  isSelected: boolean
  onSelect: () => void
  onUpdateContent: (newContent: string) => void
}

export const DraftSectionEditor: React.FC<DraftSectionEditorProps> = ({
  section,
  isSelected,
  onSelect,
  onUpdateContent,
}) => {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState(section.content)

  const handleSave = () => {
    onUpdateContent(editValue)
    setIsEditing(false)
  }

  const handleCancel = () => {
    setEditValue(section.content)
    setIsEditing(false)
  }

  return (
    <div
      onClick={onSelect}
      className={`group relative rounded-xl border transition-all duration-150 ${
        isSelected
          ? 'border-blue-500 bg-white ring-2 ring-blue-500/20 shadow-md'
          : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-xs'
      }`}
    >
      {/* Header of Section */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100 bg-slate-50/50 rounded-t-xl">
        <div className="flex items-center gap-2.5">
          <span className="w-2 h-2 rounded-full bg-blue-600" />
          <h3 className="font-bold text-slate-900 text-base">{section.title}</h3>

          {/* Badge */}
          {section.status === 'needs_review' ? (
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
              <ShieldAlert className="w-3.5 h-3.5 text-amber-600" />
              상담사 확인 필요
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded bg-slate-100/80 text-slate-600 border border-slate-200/60">
              <Sparkles className="w-3 h-3 text-slate-500" />
              AI 초안
            </span>
          )}
        </div>

        {/* Action button */}
        {!isEditing && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onSelect()
              setIsEditing(true)
            }}
            className="inline-flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-blue-700 bg-white hover:bg-blue-50 border border-slate-200 hover:border-blue-200 px-2.5 py-1 rounded-md transition-colors"
          >
            <Edit3 className="w-3.5 h-3.5" />
            수정
          </button>
        )}
      </div>

      {/* Body Content */}
      <div className="p-6">
        {section.missingNotice && (
          <div className="mb-4 p-3.5 rounded-lg bg-amber-50/80 border border-amber-200/80 text-xs font-medium text-amber-900 flex items-start gap-2">
            <ShieldAlert className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-bold text-amber-950">임상적 확인 필요 항목</p>
              <p className="text-amber-900 mt-0.5">{section.missingNotice}</p>
            </div>
          </div>
        )}

        {isEditing ? (
          <div className="space-y-3" onClick={(e) => e.stopPropagation()}>
            <textarea
              value={editValue}
              onChange={(e) => setEditValue(e.target.value)}
              rows={4}
              className="w-full rounded-lg border border-blue-400 p-3.5 text-base text-slate-900 leading-8 focus:outline-none focus:ring-2 focus:ring-blue-500/20 bg-blue-50/20 font-normal"
              placeholder="내용을 입력하세요..."
            />
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={handleCancel}
                className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 text-xs font-semibold transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                취소
              </button>
              <button
                type="button"
                onClick={handleSave}
                className="inline-flex items-center gap-1 px-3.5 py-1.5 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold shadow-xs transition-colors"
              >
                <Check className="w-3.5 h-3.5" />
                저장
              </button>
            </div>
          </div>
        ) : (
          <p className="text-base text-slate-800 leading-8 font-normal whitespace-pre-line tracking-wide">
            {section.content}
          </p>
        )}
      </div>

      {/* Selection bottom bar indicator */}
      {isSelected && (
        <div className="px-5 py-2 bg-blue-50/60 rounded-b-xl border-t border-blue-100 flex items-center justify-between text-xs text-blue-700 font-medium">
          <span>오른쪽 영역에서 원문 근거와 비교 검토할 수 있습니다.</span>
          <span className="font-bold">선택됨</span>
        </div>
      )}
    </div>
  )
}
