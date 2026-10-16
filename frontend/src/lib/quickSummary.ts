// Quick summary ("간편 요약하기"): shared types and helpers for the public and signed-in flows.
import type { SessionInput, TemporaryDraftRecord, TemporaryDraftSaveRequest } from '../types/session'

export const QUICK_SUMMARY_MAX_CHARS = 20000
export const QUICK_SUMMARY_MIN_CHARS = 20
/** Saved quick summaries are temporary drafts tagged with this session topic. */
export const QUICK_SUMMARY_TOPIC = '간편 요약'
/**
 * Quick summaries do not belong to a client. They are stored under this reserved case ID, which
 * never matches a real case, so client lists and profiles ignore them.
 */
export const QUICK_SUMMARY_CASE_ID = 'quick-summary'

export interface QuickSummaryResult {
  main_content: string
  client_response: string
  counselor_intervention: string
  next_plan: string
  masked_categories: string[]
  stub?: boolean
}

export const QUICK_SUMMARY_SECTIONS: { key: keyof Pick<QuickSummaryResult, 'main_content' | 'client_response' | 'counselor_intervention' | 'next_plan'>; title: string }[] = [
  { key: 'main_content', title: '주요 상담 내용' },
  { key: 'client_response', title: '내담자 반응' },
  { key: 'counselor_intervention', title: '상담자 개입' },
  { key: 'next_plan', title: '다음 회기 계획' },
]

/** Plain text used for copying. */
export function quickSummaryText(result: QuickSummaryResult): string {
  return QUICK_SUMMARY_SECTIONS.map(({ key, title }) => `[${title}]\n${result[key].trim()}`).join('\n\n')
}

/** Temporary-draft payload for a signed-in quick summary. Only the AI output is stored, never the input. */
export function quickSummaryDraftPayload(result: QuickSummaryResult): TemporaryDraftSaveRequest {
  return {
    case_id: QUICK_SUMMARY_CASE_ID,
    session_number: 0,
    session_date: '',
    counselor_name: '',
    screen: 'quick_summary',
    // The draft API requires a form object; a quick summary keeps no session input.
    form: {} as SessionInput,
    session_topic: QUICK_SUMMARY_TOPIC,
    is_deidentified: true,
    selected_previous_session_ids: [],
    attachments: [],
    visible_section_ids: [],
    draft_sections: [],
    final_document_sections: [],
    result: {
      case_id: QUICK_SUMMARY_CASE_ID,
      session_number: 0,
      session_summary: result.main_content,
      client_response: result.client_response,
      counselor_intervention: result.counselor_intervention,
      next_plan: result.next_plan,
    },
    final_document_type: 'session_note',
  }
}

export function isQuickSummaryDraft(draft: Pick<TemporaryDraftRecord, 'session_topic'>): boolean {
  return draft.session_topic === QUICK_SUMMARY_TOPIC
}

/** Summary stored in a quick-summary draft, or null when the draft does not hold one. */
export function quickSummaryFromDraft(draft: TemporaryDraftRecord): QuickSummaryResult | null {
  const stored = draft.result
  if (!stored || typeof stored !== 'object') return null
  const value = stored as Record<string, unknown>
  const text = (key: string) => (typeof value[key] === 'string' ? (value[key] as string) : '')
  const result: QuickSummaryResult = {
    main_content: text('session_summary'),
    client_response: text('client_response'),
    counselor_intervention: text('counselor_intervention'),
    next_plan: text('next_plan'),
    masked_categories: [],
  }
  return QUICK_SUMMARY_SECTIONS.some(({ key }) => result[key].trim()) ? result : null
}

export function relativeTimeLabel(value: string, now = Date.now()): string {
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return ''
  const minutes = Math.max(0, Math.floor((now - time) / 60000))
  if (minutes < 1) return '방금 전'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}일 전`
  const date = new Date(time)
  return `${date.getMonth() + 1}월 ${date.getDate()}일`
}

/** "10월 16일_상담 내역_요약" followed by the start of the main content. */
export function quickSummaryRecordTitle(savedAt: string, result: QuickSummaryResult | null): string {
  const date = new Date(savedAt)
  const day = Number.isNaN(date.getTime()) ? '' : `${date.getMonth() + 1}월 ${date.getDate()}일_`
  const lead = (result?.main_content || '').replace(/\s+/g, ' ').trim()
  return `${day}상담 내역_요약${lead ? ` · ${lead.slice(0, 40)}${lead.length > 40 ? '…' : ''}` : ''}`
}

// Earlier builds kept a pre-login summary in local storage for the save-after-login flow.
const LEGACY_PENDING_KEY = 'remind.quickSummary.pending'

/** Remove a summary left in this browser by the removed save-after-login flow. */
export function clearLegacyPendingSummary(): void {
  try {
    window.localStorage.removeItem(LEGACY_PENDING_KEY)
  } catch {
    // Storage can be unavailable (private mode); nothing to clean up then.
  }
}
