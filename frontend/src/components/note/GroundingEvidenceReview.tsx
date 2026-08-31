import { AlertTriangle, CheckCircle2, ChevronRight, ClipboardCheck, Info, X } from 'lucide-react'
import {
  counselorSourceField,
  isInlineGroundingItem,
  parseTranscriptEvidence,
  supportStateLabel,
  type GroundingReviewItem,
} from '../../lib/groundingReview'
import type { GroundingSource, GroundingSupportType } from '../../types/session'

const stateStyle: Record<GroundingSupportType, string> = {
  direct_evidence: 'bg-blue-50 text-blue-700 ring-blue-200',
  counselor_judgment: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  clinical_inference: 'bg-amber-50 text-amber-800 ring-amber-200',
  unsupported: 'bg-rose-50 text-rose-700 ring-rose-200',
}

export default function GroundingEvidenceReview({ items, onSelect, renderedText, selectedClaimId }: {
  items: GroundingReviewItem[]
  onSelect: (claimId: string) => void
  renderedText: string
  selectedClaimId: string | null
}) {
  const reviewable = items.filter((item) => item.claim.support_type !== 'unsupported')
  const inlineItems = reviewable.filter((item) => isInlineGroundingItem(item, items, renderedText))
  const reviewRows = reviewable.filter((item) => !isInlineGroundingItem(item, items, renderedText))
  const unsupported = items.filter((item) => item.claim.support_type === 'unsupported')
  if (!items.length) return null

  return (
    <div className="mt-3 space-y-2" data-testid="grounding-evidence-review">
      {inlineItems.length > 0 ? (
        <div className="flex flex-wrap justify-end gap-1.5">
          {inlineItems.map((item) => (
            <EvidenceControl
              key={item.claim.claim_id}
              item={item}
              onSelect={onSelect}
              selected={selectedClaimId === item.claim.claim_id}
            />
          ))}
        </div>
      ) : null}
      {reviewRows.map((item) => (
        <GroundingClaimIndicator
          key={item.claim.claim_id}
          item={item}
          onSelect={onSelect}
          selected={selectedClaimId === item.claim.claim_id}
        />
      ))}
      {unsupported.length > 0 ? (
        <aside className="rounded-md border border-rose-200 bg-rose-50/70 p-3" aria-label="근거 부족 문장 검토">
          <div className="flex items-center gap-2 text-[11px] font-bold text-rose-800">
            <AlertTriangle className="h-3.5 w-3.5" /> 근거 부족 · 검토 필요
          </div>
          {unsupported.map((item) => (
            <p key={item.claim.claim_id} className="mt-1.5 text-[11px] leading-5 text-slate-700">{item.claim.text}</p>
          ))}
          <p className="mt-1.5 text-[10px] font-semibold text-rose-700">
            이 문장은 확정 문서 본문에 자동으로 추가되지 않습니다.
          </p>
        </aside>
      ) : null}
    </div>
  )
}

export function EvidenceSourcePanel({ item, onClose }: { item: GroundingReviewItem; onClose: () => void }) {
  return (
    <aside className="rounded-[7px] border border-slate-200 bg-white shadow-sm" aria-label="근거 원문">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <p className="text-sm font-extrabold text-slate-900">근거 원문</p>
          <p className="mt-0.5 text-[11px] font-semibold text-slate-500">
            {item.stale
              ? '수정된 AI 문장과 기존 근거를 다시 확인해주세요.'
              : '이 AI 문장을 뒷받침하는 과거 상담 원문입니다.'}
          </p>
        </div>
        <button type="button" aria-label="근거 원문 닫기" onClick={onClose}
          className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-200">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="p-4">
        <div className="rounded-md bg-amber-50 px-3 py-2 ring-1 ring-amber-200">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[10px] font-bold text-amber-800">선택한 문장</p>
            <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ${stateStyle[item.claim.support_type]}`}>
              {supportStateLabel[item.claim.support_type]}
            </span>
          </div>
          <p className="mt-1 text-xs font-semibold leading-5 text-slate-800">{item.claim.text}</p>
        </div>
        {item.stale ? (
          <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-[11px] font-bold text-amber-900">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>수정 후 근거 재확인 필요</span>
          </div>
        ) : null}
        <div className="mt-4 space-y-3">
          {item.missingSource ? <MissingEvidence /> : null}
          {item.sources.map((source) => (
            <EvidenceSourceItem key={source.evidence_id} source={source} stale={item.stale} />
          ))}
        </div>
      </div>
    </aside>
  )
}

export function EvidenceDrawer({ item, onClose }: { item: GroundingReviewItem; onClose: () => void }) {
  return (
    <div className="fixed inset-y-0 right-0 z-50 w-full max-w-[430px] overflow-y-auto border-l border-slate-200 bg-[#f8f9fb] p-4 shadow-[-18px_0_40px_rgba(15,23,42,0.18)] sm:top-[60px]">
      <EvidenceSourcePanel item={item} onClose={onClose} />
    </div>
  )
}

function GroundingClaimIndicator({ item, onSelect, selected }: {
  item: GroundingReviewItem
  onSelect: (claimId: string) => void
  selected: boolean
}) {
  const { claim, missingSource, sources, stale } = item
  const controlLabel = claim.support_type === 'clinical_inference'
    ? sources.length > 1 ? `참고 원문 ${sources.length}개` : '참고 원문'
    : claim.support_type === 'counselor_judgment'
      ? '상담사 확정 기록'
      : sources.length > 1 ? `근거 ${sources.length}개` : '근거 1'

  return (
    <article id={`grounding-claim-${claim.claim_id}`} className={`rounded-md border p-2.5 transition ${selected ? 'border-amber-300 bg-amber-100 ring-2 ring-amber-300/70' : 'border-slate-200 bg-slate-50/70'}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        {claim.support_type === 'clinical_inference' ? null : (
          <span className="text-[10px] font-bold text-slate-500">근거 검토</span>
        )}
        <SupportIcon supportType={claim.support_type} />
        <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ${stateStyle[claim.support_type]}`}>
          {supportStateLabel[claim.support_type]}
        </span>
        {stale ? (
          <span className="inline-flex rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-800 ring-1 ring-amber-200">
            수정 후 근거 재확인 필요
          </span>
        ) : null}
        <button type="button" aria-pressed={selected} onClick={() => onSelect(claim.claim_id)}
          data-claim-id={claim.claim_id}
          className={`ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold focus:outline-none focus:ring-2 focus:ring-blue-300 ${evidenceControlStyle(selected, stale)}`}>
          {missingSource && !sources.length ? '근거' : controlLabel}
          <ChevronRight className="h-3 w-3" />
        </button>
      </div>
      <p className="mt-1.5 text-[11px] font-semibold leading-5 text-slate-700">{claim.text}</p>
    </article>
  )
}

function EvidenceControl({ item, onSelect, selected }: {
  item: GroundingReviewItem
  onSelect: (claimId: string) => void
  selected: boolean
}) {
  const { claim, missingSource, sources, stale } = item
  const label = claim.support_type === 'counselor_judgment'
    ? '상담사 확정 기록'
    : sources.length > 1 ? `근거 ${sources.length}개` : '근거 1'

  return (
    <div className="inline-flex items-center gap-1.5">
      {stale ? (
        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-800 ring-1 ring-amber-200">
          수정 후 근거 재확인 필요
        </span>
      ) : null}
      <button
        type="button"
        aria-pressed={selected}
        data-claim-id={claim.claim_id}
        onClick={() => onSelect(claim.claim_id)}
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold focus:outline-none focus:ring-2 focus:ring-blue-300 ${evidenceControlStyle(selected, stale)}`}
      >
        {missingSource && !sources.length ? '근거' : label}
        <ChevronRight className="h-3 w-3" />
      </button>
    </div>
  )
}

function SupportIcon({ supportType }: { supportType: GroundingSupportType }) {
  if (supportType === 'direct_evidence') return <CheckCircle2 className="h-3.5 w-3.5 text-blue-700" />
  if (supportType === 'counselor_judgment') return <ClipboardCheck className="h-3.5 w-3.5 text-emerald-700" />
  if (supportType === 'unsupported') return <AlertTriangle className="h-3.5 w-3.5 text-rose-700" />
  return <Info className="h-3.5 w-3.5 text-amber-700" />
}

function EvidenceSourceItem({ source, stale }: { source: GroundingSource; stale: boolean }) {
  const sessionLabel = source.session_number == null ? '이전 기록' : `${source.session_number}회기`
  return (
    <section
      className={`rounded-md border p-3 transition ${
        stale
          ? 'border-slate-300 bg-slate-50'
          : 'border-amber-300 bg-amber-50 ring-1 ring-amber-200 shadow-sm'
      }`}
      data-evidence-state={stale ? 'stale' : 'selected'}
      data-source-ref={source.source_ref}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-extrabold text-slate-900">
          {sessionLabel} · {source.source_type === 'raw_transcript' ? '상담 원문' : '상담사 확정 기록'}
        </p>
        {source.source_type === 'counselor_confirmed' && counselorSourceField(source.source_ref) ? (
          <span className="text-[10px] font-semibold text-slate-500">
            확정 기록 필드 · {counselorFieldLabel(counselorSourceField(source.source_ref))}
          </span>
        ) : null}
      </div>
      {source.source_type === 'raw_transcript' ? (
        <div className="mt-2 space-y-2">
          {parseTranscriptEvidence(source.source_text).map((line, index) => (
            <div key={`${source.evidence_id}-${index}`} className="grid grid-cols-[48px_1fr] gap-2 text-xs leading-5">
              <span className="font-bold text-slate-500">{line.role}</span>
              <p className="whitespace-pre-wrap text-slate-800">{line.text}</p>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-xs leading-5 text-slate-800">{source.source_text}</p>
      )}
    </section>
  )
}

function evidenceControlStyle(selected: boolean, stale: boolean): string {
  if (!selected) return 'bg-blue-50 text-blue-700 ring-1 ring-blue-200 hover:bg-blue-100'
  if (stale) return 'bg-amber-50 text-amber-900 ring-2 ring-dashed ring-amber-400'
  return 'bg-amber-100 text-amber-950 ring-2 ring-amber-400 shadow-sm'
}

function counselorFieldLabel(field: string | null): string {
  const labels: Record<string, string> = {
    session_theme: '회기 주제',
    presenting_problem: '주요 호소 문제',
    session_content: '상담 내용',
    counselor_intervention: '상담자 개입',
    client_response: '내담자 반응',
    reflection: '상담자 성찰',
    next_plan: '다음 계획',
  }
  return field ? labels[field] || field : '기록 항목'
}

function MissingEvidence() {
  return (
    <div className="flex items-start gap-2 rounded-md bg-amber-50 p-2 text-[11px] font-semibold text-amber-800">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span>근거 정보를 불러올 수 없습니다.</span>
    </div>
  )
}
