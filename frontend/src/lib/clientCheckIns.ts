/**
 * Client check-ins between sessions (내담자 수시 기록): shared copy and helpers for the client
 * page and the counselor's case view. Records are never sent to an AI model.
 */

// Keep in sync with backend/app/schemas/client_check_in.py and the database check constraint.
export const CHECK_IN_EMOTIONS = ['불안', '슬픔', '화남', '무기력', '외로움', '긴장', '피곤함', '괜찮음', '편안함', '기쁨'] as const
export type CheckInEmotion = (typeof CHECK_IN_EMOTIONS)[number]
export const CLIENT_CONSENT_VERSION = '2026-11-22-draft'
export const NOTE_MAX_LENGTH = 1000

export interface CheckIn {
  id: string
  mood: number
  emotions: string[]
  note: string
  created_at: string
}

export interface ClientLinkStatus {
  link_id: string
  status: 'invited' | 'active' | 'ended'
  created_at: string | null
  invite_expires_at: string | null
  accepted_at: string | null
  ended_at: string | null
}

export interface ClientInvite {
  link_id: string
  token: string
  expires_at: string
}

export interface ClientMe {
  linked: boolean
  status: 'active' | 'ended' | null
  consented_at: string | null
  consent_version: string
}

/** Shown on every client screen: the records are not watched in real time. */
export const CRISIS_NOTICE = '이 기록은 실시간으로 확인되지 않아요. 위급한 상황이면 아래 번호로 바로 연락하세요.'
export const CRISIS_CONTACTS = [
  { label: '자살예방 상담전화', number: '109' },
  { label: '정신건강 위기상담', number: '1577-0199' },
  { label: '긴급 신고', number: '112 · 119' },
] as const

/**
 * Consent text the client agrees to before linking. Draft: needs legal and clinical review
 * before real use (the page shows that it is a draft).
 */
export const CONSENT_DRAFT_NOTICE = '검토 전 초안입니다. 실제 서비스 전에 법률·상담 전문가 검토를 거쳐 바뀔 수 있어요.'
export const CONSENT_ITEMS = [
  '내가 남긴 기분 점수, 감정, 메모는 나를 초대한 상담사만 볼 수 있어요. 상담사는 기록을 고칠 수 없어요.',
  '상담사는 다음 상담 전에 기록을 확인해요. 기록을 실시간으로 지켜보거나 바로 답하지 않아요.',
  '위급한 상황에서는 기록 대신 109(자살예방 상담전화), 112, 119로 바로 연락해야 해요.',
  '기록은 Re:mind 서버에 저장되고 AI 분석에 쓰이지 않아요.',
  '내 기록은 언제든 직접 지울 수 있고, 연결을 끊으면 새 기록을 남길 수 없어요. 이미 남긴 기록은 지우기 전까지 상담사가 볼 수 있어요.',
  '만 19세 미만은 이 기능을 이용할 수 없어요.',
] as const

// Words that make the page repeat the crisis contacts right after saving. This only shows help;
// it does not judge risk, and nobody is notified.
const CRISIS_WORDS = ['죽고 싶', '죽고싶', '자살', '사라지고 싶', '사라지고싶', '없어지고 싶', '자해', '끝내고 싶', '살기 싫', '살고 싶지 않', '해치고 싶']

export function needsCrisisSupport(mood: number, note: string): boolean {
  const compact = note.replace(/\s+/g, ' ')
  return mood <= 1 || CRISIS_WORDS.some((word) => compact.includes(word))
}

export function moodLabel(mood: number): string {
  if (mood <= 2) return '매우 힘듦'
  if (mood <= 4) return '힘듦'
  if (mood <= 6) return '보통'
  if (mood <= 8) return '괜찮음'
  return '좋음'
}

export function clientInviteUrl(token: string, origin: string = window.location.origin): string {
  return `${origin.replace(/\/+$/, '')}/client?invite=${encodeURIComponent(token)}`
}

/** The invite token from a /client URL, or ''. */
export function inviteTokenFrom(search: string): string {
  const token = new URLSearchParams(search).get('invite') || ''
  return /^[A-Za-z0-9_-]{20,200}$/.test(token) ? token : ''
}

export function isClientPath(pathname: string): boolean {
  return pathname === '/client' || pathname.startsWith('/client/')
}

/** Entries recorded after a given time (e.g. since the last session), newest first. */
export function entriesSince(entries: CheckIn[], since: string | null): CheckIn[] {
  if (!since) return entries
  return entries.filter((entry) => entry.created_at >= since)
}

export function formatCheckInTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit' })
}
