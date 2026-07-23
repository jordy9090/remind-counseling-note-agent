import React, { useState } from 'react'
import { BookOpen, ChevronDown, ChevronUp, CheckCircle } from 'lucide-react'
import { RetrievedTemplateContext, RetrievalReport } from '../../types/session'

interface TemplateKbStatusCardProps {
  templateContext: RetrievedTemplateContext | null | undefined
  retrievalReport: RetrievalReport | null | undefined
  isDemo?: boolean
}

const FIELD_LABELS: Record<string, string> = {
  session_metadata: '회기 기본정보',
  case_id: '사례 ID',
  session_number: '회기 번호',
  session_date: '상담 일자',
  presenting_problem: '주 호소문제',
  family_relations: '가족관계',
  counseling_goal: '상담목표',
  session_content: '상담 진행내용',
  counselor_reflection: '상담자 평가 및 성찰',
  next_plan: '향후 계획',
  nonverbal_observation: '비언어적 관찰',
  psychological_tests: '심리검사 결과',
  case_conceptualization: '사례개념화',
  supervision_questions: '수퍼비전 질문',
  'family genogram outline': '가계도 및 가족관계',
  'direct client quotes': '내담자 주요 진술',
  'prior counseling details': '이전 상담 경험',
  'suicide risk screening': '위험도 확인',
}

const fieldLabel = (field: string) => FIELD_LABELS[field] || field

export const TemplateKbStatusCard: React.FC<TemplateKbStatusCardProps> = ({
  templateContext,
  retrievalReport,
  isDemo = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(false)

  const templateFound = retrievalReport?.template_context_found || (isDemo && !!templateContext)

  if (!templateFound) {
    return null
  }

  const {
    target_document_type = 'session_note',
    required_fields = [],
    optional_fields = [],
    counselor_review_fields = [],
    missing_field_checklist = [],
    source_refs = [],
  } = templateContext || {}

  // Determine standard subtitle based on document type
  let kbSubtitle = '회기 기록 양식 체크리스트'
  if (target_document_type === 'supervision_report') {
    kbSubtitle = '한국상담심리학회 수퍼비전 기본양식 기반'
  } else if (target_document_type === 'termination_report') {
    kbSubtitle = '종결 보고서 표준 양식 기반'
  }

  return (
    <div className="w-full bg-slate-900 text-white rounded-xl border border-slate-800 p-4 mb-4 shadow-md transition-all duration-200">
      <div className="flex items-start justify-between">
        <div className="flex gap-3">
          <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-lg shrink-0">
            <BookOpen className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h4 className="text-xs font-semibold text-slate-300">
                {isDemo ? '문서 양식 KB 적용됨 (데모 스냅샷)' : '문서 양식 KB 적용됨'}
              </h4>
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/15 text-emerald-400">
                <CheckCircle className="w-2.5 h-2.5 mr-1" />
                적용 완료
              </span>
            </div>
            <p className="text-sm font-bold text-white mt-0.5">{kbSubtitle}</p>
            {!isExpanded && (
              <p className="text-xs text-slate-400 mt-1">
                필수 항목 {required_fields.length}개 · 상담사 확인 {counselor_review_fields.length}개 · 근거 항목 {source_refs.length}개
              </p>
            )}
          </div>
        </div>
        <button
          type="button"
          aria-label={isExpanded ? 'KB 상세 접기' : 'KB 상세 펼치기'}
          onClick={() => setIsExpanded(!isExpanded)}
          className="text-slate-400 hover:text-white p-1 rounded-lg transition-colors"
        >
          {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>

      {isExpanded && <div className="grid grid-cols-3 gap-2 mt-4 bg-slate-950/60 p-3 rounded-lg border border-slate-800 text-center">
        <div>
          <div className="text-[10px] text-slate-400">필수 항목</div>
          <div className="text-sm font-bold text-white mt-0.5">{required_fields.length}개</div>
        </div>
        <div>
          <div className="text-[10px] text-slate-400">상담사 직접 확인</div>
          <div className="text-sm font-bold text-white mt-0.5">{counselor_review_fields.length}개</div>
        </div>
        <div>
          <div className="text-[10px] text-slate-400">근거 항목</div>
          <div className="text-sm font-bold text-white mt-0.5">{source_refs.length}개</div>
        </div>
      </div>}

      {isExpanded && (
        <div className="mt-4 pt-4 border-t border-slate-850 space-y-3.5 text-xs text-slate-300">
          {required_fields.length > 0 && (
            <div>
              <h5 className="font-semibold text-slate-200 mb-1">✓ 필수 항목</h5>
              <div className="flex flex-wrap gap-1.5">
                {required_fields.map((field) => (
                  <span key={field} className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                    {fieldLabel(field)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {optional_fields.length > 0 && (
            <div>
              <h5 className="font-semibold text-slate-200 mb-1">✓ 선택 항목</h5>
              <div className="flex flex-wrap gap-1.5">
                {optional_fields.map((field) => (
                  <span key={field} className="px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-400">
                    {fieldLabel(field)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {counselor_review_fields.length > 0 && (
            <div>
              <h5 className="font-semibold text-amber-400 mb-1">⚠ 상담사 직접 확인 필요 항목</h5>
              <div className="flex flex-wrap gap-1.5">
                {counselor_review_fields.map((field) => (
                  <span key={field} className="px-2 py-0.5 rounded bg-amber-500/10 border border-amber-500/20 text-amber-300">
                    {fieldLabel(field)}
                  </span>
                ))}
              </div>
            </div>
          )}

          {missing_field_checklist.length > 0 && (
            <div>
              <h5 className="font-semibold text-red-400 mb-1">✕ 현재 누락 또는 검토 필요 항목</h5>
              <div className="flex flex-wrap gap-1.5">
                {missing_field_checklist.map((field) => (
                  <span key={field} className="px-2 py-0.5 rounded bg-red-500/10 border border-red-500/20 text-red-300">
                    {fieldLabel(field)}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
