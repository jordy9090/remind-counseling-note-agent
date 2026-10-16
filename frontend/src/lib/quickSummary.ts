// Quick summary ("간편 요약하기"): shared types and helpers for the public and signed-in flows.

export const QUICK_SUMMARY_MAX_CHARS = 20000
export const QUICK_SUMMARY_MIN_CHARS = 20
/** Saved quick summaries are temporary drafts tagged with this session topic. */
export const QUICK_SUMMARY_TOPIC = '간편 요약'

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

/** Plain text used for copying and for the saved session memo. */
export function quickSummaryText(result: QuickSummaryResult): string {
  return QUICK_SUMMARY_SECTIONS.map(({ key, title }) => `[${title}]\n${result[key].trim()}`).join('\n\n')
}

// A summary made before login survives the login/signup round trip (including an email
// confirmation link opened in a new tab). Only the AI output is kept, never the input,
// and it expires quickly.
const PENDING_KEY = 'remind.quickSummary.pending'
const PENDING_TTL_MS = 30 * 60 * 1000

export function storePendingQuickSummary(result: QuickSummaryResult): void {
  try {
    window.localStorage.setItem(PENDING_KEY, JSON.stringify({ result, savedAt: Date.now() }))
  } catch {
    // Storage can be unavailable (private mode); the summary then simply does not carry over.
  }
}

export function readPendingQuickSummary(now = Date.now()): QuickSummaryResult | null {
  try {
    const raw = window.localStorage.getItem(PENDING_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { result?: QuickSummaryResult; savedAt?: number }
    if (!parsed.result || typeof parsed.savedAt !== 'number' || now - parsed.savedAt > PENDING_TTL_MS
      || !QUICK_SUMMARY_SECTIONS.every(({ key }) => typeof parsed.result?.[key] === 'string')) {
      window.localStorage.removeItem(PENDING_KEY)
      return null
    }
    return { ...parsed.result, masked_categories: Array.isArray(parsed.result.masked_categories) ? parsed.result.masked_categories : [] }
  } catch {
    return null
  }
}

export function clearPendingQuickSummary(): void {
  try {
    window.localStorage.removeItem(PENDING_KEY)
  } catch {
    // ignore
  }
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

export function quickSummaryRecordTitle(savedAt: string, clientName: string): string {
  const date = new Date(savedAt)
  const day = Number.isNaN(date.getTime()) ? '' : `${date.getMonth() + 1}월 ${date.getDate()}일_`
  return `${day}상담 내역_${clientName}`
}
