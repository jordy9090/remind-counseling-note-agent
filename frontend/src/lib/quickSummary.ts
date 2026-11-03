// Quick summary ("간편 요약하기"): shared types and helpers for the public and signed-in flows.
// The summary itself comes from the regular pipeline; a result is the list of summary items exactly
// as the regular summary screen builds them (주요 호소, 회기 주제, 상담 내용, ...).
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

export interface QuickSummarySection {
  id: string
  title: string
  content: string
  /** Ephemeral source excerpts; never included in saved summaries or login handoffs. */
  evidence?: { label: string; excerpt: string; needsReview: boolean }[]
  requiresReview?: boolean
}

export interface QuickSummaryResult {
  sections: QuickSummarySection[]
  /** True when identifying details were replaced before the AI request. */
  deidentified: boolean
  stub?: boolean
}

/** Plain text used for copying. */
export function quickSummaryText(result: QuickSummaryResult): string {
  return result.sections.map(({ title, content }) => `[${title}]\n${content.trim()}`).join('\n\n')
}

function isSection(value: unknown): value is QuickSummarySection {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return typeof item.id === 'string' && typeof item.title === 'string' && typeof item.content === 'string'
}

function cleanSections(value: unknown): QuickSummarySection[] {
  return Array.isArray(value)
    ? value.filter(isSection).map(({ id, title, content }) => ({ id, title, content }))
    : []
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
    draft_sections: result.sections.map(({ id, title, content }) => ({ id, title, content, visible: true })),
    final_document_sections: [],
    final_document_type: 'session_note',
  }
}

export function isQuickSummaryDraft(draft: Pick<TemporaryDraftRecord, 'session_topic'>): boolean {
  return draft.session_topic === QUICK_SUMMARY_TOPIC
}

// Records saved before quick summaries used the regular pipeline kept four items in `result`.
const LEGACY_FIELDS: { key: string; id: string; title: string }[] = [
  { key: 'session_summary', id: 'session_content', title: '상담 내용' },
  { key: 'client_response', id: 'client_response', title: '내담자 반응' },
  { key: 'counselor_intervention', id: 'counselor_intervention', title: '상담자 개입' },
  { key: 'next_plan', id: 'next_plan', title: '다음 계획' },
]

/** Summary stored in a quick-summary draft, or null when the draft does not hold one. */
export function quickSummaryFromDraft(draft: TemporaryDraftRecord): QuickSummaryResult | null {
  let sections = cleanSections(draft.draft_sections)
  if (!sections.length && draft.result && typeof draft.result === 'object') {
    const value = draft.result as Record<string, unknown>
    sections = LEGACY_FIELDS
      .filter(({ key }) => typeof value[key] === 'string' && (value[key] as string).trim())
      .map(({ key, id, title }) => ({ id, title, content: value[key] as string }))
  }
  return sections.some((section) => section.content.trim()) ? { sections, deidentified: true } : null
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

/** "10월 16일_상담 내역_요약" followed by the start of the session theme or content. */
export function quickSummaryRecordTitle(savedAt: string, result: QuickSummaryResult | null): string {
  const date = new Date(savedAt)
  const day = Number.isNaN(date.getTime()) ? '' : `${date.getMonth() + 1}월 ${date.getDate()}일_`
  const pick = (id: string) => result?.sections.find((section) => section.id === id)?.content || ''
  const lead = (pick('session_theme') || pick('session_content') || result?.sections[0]?.content || '').replace(/\s+/g, ' ').trim()
  return `${day}상담 내역_요약${lead ? ` · ${lead.slice(0, 40)}${lead.length > 40 ? '…' : ''}` : ''}`
}

// "로그인 후 저장하기": a guest's summary waits in this browser until the login (or the email
// confirmation link, which can open in a new tab) completes, then the workspace saves it like any
// signed-in summary. Only the summary items are kept, never the input, and they expire after 30 minutes.
const PENDING_KEY = 'remind.quickSummary.pending'
export const PENDING_TTL_MS = 30 * 60 * 1000

export function storePendingQuickSummary(result: QuickSummaryResult, now = Date.now()): void {
  try {
    window.localStorage.setItem(PENDING_KEY, JSON.stringify({ sections: cleanSections(result.sections), savedAt: now }))
  } catch {
    // Storage can be unavailable (private mode); the summary then cannot carry over the login.
  }
}

export function clearPendingQuickSummary(): void {
  try {
    window.localStorage.removeItem(PENDING_KEY)
  } catch {
    // Nothing to clean up when storage is unavailable.
  }
}

/** Read and remove the waiting summary; null when there is none, it expired, or it is malformed. */
export function takePendingQuickSummary(now = Date.now()): QuickSummaryResult | null {
  let raw: string | null = null
  try {
    raw = window.localStorage.getItem(PENDING_KEY)
  } catch {
    return null
  }
  clearPendingQuickSummary()
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as { sections?: unknown; savedAt?: unknown }
    if (typeof parsed.savedAt !== 'number' || now - parsed.savedAt > PENDING_TTL_MS || now < parsed.savedAt) return null
    const sections = cleanSections(parsed.sections)
    return sections.length ? { sections, deidentified: true } : null
  } catch {
    return null
  }
}
