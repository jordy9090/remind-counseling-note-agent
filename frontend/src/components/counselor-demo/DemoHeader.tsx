import React from 'react'
import { ArrowLeft, CheckCircle2, Clock, AlertCircle, RotateCcw, ShieldCheck } from 'lucide-react'
import type { ReviewStatus } from '../../hooks/useCounselorDemo'
import type { DemoClientInfo } from '../../data/counselorDemoFixture'

interface DemoHeaderProps {
  clientInfo: DemoClientInfo
  reviewStatus: ReviewStatus
  isDirty: boolean
  lastSavedAt: string | null
  onResetDemo: () => void
  onBackToMain?: () => void
}

export const DemoHeader: React.FC<DemoHeaderProps> = ({
  clientInfo,
  reviewStatus,
  isDirty,
  lastSavedAt,
  onResetDemo,
  onBackToMain,
}) => {
  return (
    <header className="print:hidden sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur-sm shadow-xs px-4 lg:px-6 py-3">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-3">
        {/* Left side: Back, Title, Client Info */}
        <div className="flex items-center gap-4 flex-wrap">
          {onBackToMain && (
            <button
              type="button"
              onClick={onBackToMain}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-slate-900 bg-slate-100 hover:bg-slate-200 px-2.5 py-1.5 rounded-md transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              전체 목록
            </button>
          )}

          <div className="flex items-center gap-2.5">
            <img src="/remind-logo.png" alt="Re:mind" className="h-5 w-auto object-contain" />
            <span className="text-slate-300 font-light">|</span>
            <span className="text-xs font-semibold px-2 py-0.5 rounded bg-blue-50 text-blue-700 border border-blue-200">
              가상 사례 · 데모 데이터
            </span>
          </div>

          <div className="flex items-center gap-2 bg-slate-50 border border-slate-200 px-3 py-1 rounded-md text-sm">
            <span className="font-bold text-slate-900">{clientInfo.name}</span>
            <span className="text-slate-400 text-xs font-mono">{clientInfo.caseId}</span>
            <span className="text-slate-300">·</span>
            <span className="font-semibold text-blue-700">{clientInfo.sessionNumber}회기</span>
            <span className="text-slate-500 text-xs">({clientInfo.sessionDate})</span>
          </div>
        </div>

        {/* Right side: Review Status & Actions */}
        <div className="flex items-center gap-3">
          {/* Save Status indicator */}
          <div className="text-xs flex items-center gap-1.5 text-slate-500">
            {isDirty ? (
              <span className="inline-flex items-center gap-1 text-amber-700 font-medium bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                <AlertCircle className="w-3.5 h-3.5" />
                수정 중 (미저장)
              </span>
            ) : lastSavedAt ? (
              <span className="inline-flex items-center gap-1 text-slate-600 font-medium">
                <Clock className="w-3.5 h-3.5 text-slate-400" />
                {lastSavedAt} 저장됨
              </span>
            ) : null}
          </div>

          {/* Workflow Status Badge */}
          <div>
            {reviewStatus === 'ai_draft' && (
              <span className="inline-flex items-center gap-1 text-xs font-bold bg-blue-50 text-blue-700 border border-blue-200 px-2.5 py-1 rounded-full">
                <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
                AI 초안 (검토 대기)
              </span>
            )}
            {reviewStatus === 'in_review' && (
              <span className="inline-flex items-center gap-1 text-xs font-bold bg-amber-50 text-amber-800 border border-amber-200 px-2.5 py-1 rounded-full">
                <span className="w-2 h-2 rounded-full bg-amber-500" />
                상담사 검토 중
              </span>
            )}
            {reviewStatus === 'reviewed' && (
              <span className="inline-flex items-center gap-1 text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 px-2.5 py-1 rounded-full">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />
                상담사 검토 완료
              </span>
            )}
          </div>

          {/* Reset Demo button */}
          <button
            type="button"
            onClick={onResetDemo}
            title="데모 초기 상태로 다시 시작합니다"
            className="inline-flex items-center gap-1 text-xs font-medium text-slate-500 hover:text-slate-800 border border-slate-200 hover:bg-slate-50 px-2.5 py-1 rounded-md transition-colors"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            데모 초기화
          </button>
        </div>
      </div>
    </header>
  )
}
