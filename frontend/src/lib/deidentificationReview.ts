/**
 * Pre-generation de-identification review ("AI로 보내기 전 내용을 확인해주세요").
 *
 * The counselor reviews which expressions are replaced before the text is sent to the AI.
 * Detection here is a local rule set (known names, contacts, exact dates, current ages).
 * Context-based suspicions (e.g. a job implied by duties) will come from a backend model
 * later; `detectDeidentificationItems` is the single place to swap in that call.
 */

export type DeidItemKind = 'auto' | 'review'
export type DeidItemOrigin = 'detected' | 'manual'

export interface DeidItem {
  id: string
  original: string
  replacement: string
  /** auto: clear identifier. review: the counselor should decide (확인 필요). */
  kind: DeidItemKind
  origin: DeidItemOrigin
}

export interface DeidSource {
  key: string
  label: string
  text: string
}

/** Session input fields that are sent to the AI, in display order. */
export const SESSION_REVIEW_FIELDS = [
  ['transcript_text', '축어록'],
  ['counselor_memo', '상담사 메모'],
  ['nonverbal_notes', '비언어 관찰'],
  ['previous_session_summary', '이전 회기 요약'],
  ['psychological_test_summary', '심리검사 요약'],
] as const

export type SessionReviewField = (typeof SESSION_REVIEW_FIELDS)[number][0]

/** Non-empty session fields as review sources. The transcript chip shows its file name when there is one. */
export function sessionReviewSources(input: Partial<Record<SessionReviewField, string | undefined>>, transcriptLabel?: string): DeidSource[] {
  return SESSION_REVIEW_FIELDS
    .filter(([key]) => (input[key] ?? '').trim())
    .map(([key, label]) => ({ key, label: key === 'transcript_text' && transcriptLabel ? transcriptLabel : label, text: input[key] ?? '' }))
}

export interface DeidMatch {
  start: number
  end: number
  itemId: string
}

export interface DeidDetectionContext {
  clientName?: string
  counselorName?: string
}

let idCounter = 0
export function newDeidItemId(): string {
  idCounter += 1
  return `deid-${Date.now().toString(36)}-${idCounter}`
}

const PHONE = /(?<!\d)(01[016789]|0\d{1,2})[-.\s]?(\d{3,4})[-.\s]?(\d{4})(?!\d)/g
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g
const RESIDENT_NUMBER = /(?<!\d)\d{6}-?[1-8]\d{6}(?!\d)/g
const KOREAN_DATE = /(?:\d{4}\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일/g
const NUMERIC_DATE = /(?<!\d)\d{4}[-./](\d{1,2})[-./](\d{1,2})(?!\d)/g
/** Two-digit current ages ("32세", "32살"); "7살 때" style past-event ages are left alone. */
const CURRENT_AGE = /(?<!\d)([1-9]\d)\s*(세|살)(?!\s*때)/g

/** 010-1212-3434 → 010******** (the design's partial mask); only the mobile/area prefix stays. */
export function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, '')
  const prefix = /^(01[016789]|02|0\d{2})/.exec(digits)?.[0] ?? ''
  return `${prefix}${'*'.repeat(Math.max(0, digits.length - prefix.length))}`
}

export function maskEmail(email: string): string {
  const [local, domain] = email.split('@')
  return `${local.slice(0, 1)}${'*'.repeat(Math.max(3, local.length - 1))}@${domain}`
}

/** Day of month → 초순 / 중순 / 하순, so the exact date is not sent. */
export function generalizeDate(month: number, day: number): string {
  const part = day <= 10 ? '초순' : day <= 20 ? '중순' : '하순'
  return `${month}월 ${part}`
}

export function ageBand(age: number): string {
  return `${Math.floor(age / 10) * 10}대`
}

function countOf(text: string, needle: string): number {
  return needle ? text.split(needle).length - 1 : 0
}

/** The name, plus its given-name form when that also appears on its own ("길동이", "길동 씨"). */
function personNameForms(name: string, text: string): string[] {
  const trimmed = name.trim()
  if (trimmed.length < 2) return []
  const forms = [trimmed]
  if (/^[가-힣]{3}$/.test(trimmed) && countOf(text, trimmed.slice(1)) > countOf(text, trimmed)) forms.push(trimmed.slice(1))
  return forms
}

/** Model-detected item from the server (names of anyone, organizations, places, occupations, ...). */
export interface RemoteDeidItem {
  original: string
  replacement: string
}

export type RemoteDeidDetector = (texts: string[], context: DeidDetectionContext) => Promise<RemoteDeidItem[]>

export interface DeidDetection {
  items: DeidItem[]
  /** The server detection failed; only the local rules ran. */
  remoteFailed: boolean
}

/**
 * Local rules plus, when given, the server's model detection. Each distinct expression becomes one
 * item (local rules win on duplicates); the same expression in several sources shares the item.
 */
export async function detectDeidentificationItems(
  texts: string[],
  context: DeidDetectionContext = {},
  remote?: RemoteDeidDetector,
): Promise<DeidDetection> {
  const items = detectLocalDeidItems(texts, context)
  if (!remote) return { items, remoteFailed: false }
  try {
    const joined = texts.join('\n')
    const known = new Set(items.map((item) => item.original))
    for (const found of await remote(texts, context)) {
      const original = found.original.trim()
      if (original.length < 2 || known.has(original) || !joined.includes(original) || !found.replacement.trim()) continue
      known.add(original)
      items.push({ id: newDeidItemId(), original, replacement: found.replacement.trim(), kind: 'auto', origin: 'detected' })
    }
    return { items, remoteFailed: false }
  } catch {
    return { items, remoteFailed: true }
  }
}

/** Deterministic rules only (registered names, contacts, exact dates, current ages). */
export function detectLocalDeidItems(texts: string[], context: DeidDetectionContext = {}): DeidItem[] {
  const found = new Map<string, DeidItem>()
  const add = (original: string, replacement: string, kind: DeidItemKind) => {
    const key = original.trim()
    if (!key || found.has(key)) return
    found.set(key, { id: newDeidItemId(), original: key, replacement, kind, origin: 'detected' })
  }
  const joined = texts.join('\n')

  for (const form of personNameForms(context.clientName ?? '', joined)) {
    if (joined.includes(form)) add(form, '내담자 A', 'auto')
  }
  for (const form of personNameForms(context.counselorName ?? '', joined)) {
    if (joined.includes(form)) add(form, '상담자', 'auto')
  }
  for (const match of joined.matchAll(RESIDENT_NUMBER)) add(match[0], '******-*******', 'auto')
  for (const match of joined.matchAll(PHONE)) add(match[0], maskPhone(match[0]), 'auto')
  for (const match of joined.matchAll(EMAIL)) add(match[0], maskEmail(match[0]), 'auto')
  for (const match of joined.matchAll(KOREAN_DATE)) add(match[0], generalizeDate(Number(match[1]), Number(match[2])), 'review')
  for (const match of joined.matchAll(NUMERIC_DATE)) add(match[0], generalizeDate(Number(match[1]), Number(match[2])), 'review')
  for (const match of joined.matchAll(CURRENT_AGE)) add(match[0], ageBand(Number(match[1])), 'auto')

  return Array.from(found.values())
}

/**
 * Non-overlapping occurrences of every item in `text`, longest expressions first so a full
 * name wins over the given-name form inside it. Sorted by position.
 */
export function findDeidMatches(text: string, items: DeidItem[]): DeidMatch[] {
  const taken: DeidMatch[] = []
  const ordered = [...items].filter((item) => item.original).sort((a, b) => b.original.length - a.original.length)
  for (const item of ordered) {
    let from = 0
    while (from <= text.length) {
      const start = text.indexOf(item.original, from)
      if (start === -1) break
      const end = start + item.original.length
      if (!taken.some((match) => start < match.end && match.start < end)) taken.push({ start, end, itemId: item.id })
      from = start + 1
    }
  }
  return taken.sort((a, b) => a.start - b.start)
}

/** What the AI receives: each matched expression replaced by "[대체 표현]". */
export function applyDeidItems(text: string, items: DeidItem[]): string {
  const byId = new Map(items.map((item) => [item.id, item]))
  let out = ''
  let cursor = 0
  for (const match of findDeidMatches(text, items)) {
    out += text.slice(cursor, match.start) + `[${byId.get(match.itemId)?.replacement ?? ''}]`
    cursor = match.end
  }
  return out + text.slice(cursor)
}

export function sourcesContaining(sources: DeidSource[], expression: string): DeidSource[] {
  const needle = expression.trim()
  return needle ? sources.filter((source) => source.text.includes(needle)) : []
}

export type DeidSegment =
  | { type: 'text'; text: string }
  | { type: 'speaker'; text: string }
  | { type: 'item'; text: string; itemId: string; matchIndex: number }

const SPEAKER_LABEL = /^(상담자|상담사|내담자|보호자)\s*:/gm

/**
 * Splits a source into display segments: speaker labels (bold), matched expressions, plain text.
 * With `replaced`, matched expressions show "[대체 표현]" as the AI will receive them.
 */
export function deidSegments(text: string, items: DeidItem[], replaced: boolean): DeidSegment[] {
  const byId = new Map(items.map((item) => [item.id, item]))
  const matches = findDeidMatches(text, items)
  const speakers = Array.from(text.matchAll(SPEAKER_LABEL))
    .map((match) => ({ start: match.index ?? 0, end: (match.index ?? 0) + match[0].length }))
    .filter((speaker) => !matches.some((match) => speaker.start < match.end && match.start < speaker.end))
  const marks = [
    ...matches.map((match, index) => ({ ...match, kind: 'item' as const, matchIndex: index })),
    ...speakers.map((speaker) => ({ ...speaker, kind: 'speaker' as const, itemId: '', matchIndex: -1 })),
  ].sort((a, b) => a.start - b.start)

  const segments: DeidSegment[] = []
  let cursor = 0
  for (const mark of marks) {
    if (mark.start > cursor) segments.push({ type: 'text', text: text.slice(cursor, mark.start) })
    if (mark.kind === 'speaker') {
      segments.push({ type: 'speaker', text: text.slice(mark.start, mark.end) })
    } else {
      const shown = replaced ? `[${byId.get(mark.itemId)?.replacement ?? ''}]` : text.slice(mark.start, mark.end)
      segments.push({ type: 'item', text: shown, itemId: mark.itemId, matchIndex: mark.matchIndex })
    }
    cursor = mark.end
  }
  if (cursor < text.length) segments.push({ type: 'text', text: text.slice(cursor) })
  return segments
}
