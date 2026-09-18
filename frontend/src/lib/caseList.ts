import type {
  CaseDashboardDocument,
  CaseDashboardResponse,
  CaseDashboardSession,
  CaseListItem,
  TemporaryDraftRecord,
} from '../types/session'

/** 케이스 목록 필터. 'active'는 진행중·대기중을 함께 보여 준다. */
export type CaseStatusFilter = 'all' | 'active' | 'closed'
export type CaseStatusKind = 'active' | 'closed' | 'pending'

export const CASE_STATUS_FILTERS: { id: CaseStatusFilter; label: string }[] = [
  { id: 'all', label: '전체' },
  { id: 'active', label: '진행중' },
  { id: 'closed', label: '종결' },
]

const CLOSED_STATUSES = new Set(['closed', 'terminated', 'completed', 'ended', '종결'])
const PENDING_STATUSES = new Set(['pending', 'paused', 'on_hold', 'waiting', '대기중'])

export function caseStatusKind(status: string | null | undefined): CaseStatusKind {
  const normalized = (status || '').trim().toLowerCase()
  if (CLOSED_STATUSES.has(normalized)) return 'closed'
  if (PENDING_STATUSES.has(normalized)) return 'pending'
  return 'active'
}

export function caseStatusLabel(status: string | null | undefined): string {
  const kind = caseStatusKind(status)
  return kind === 'closed' ? '종결' : kind === 'pending' ? '대기중' : '진행중'
}

export function caseDisplayName(item: { case_id: string; case_alias: string | null }): string {
  const alias = (item.case_alias || '').trim()
  return alias && alias !== item.case_id ? alias : item.case_id
}

export function filterCases(cases: CaseListItem[], filter: CaseStatusFilter, search: string): CaseListItem[] {
  const needle = search.trim().toLowerCase()
  return cases.filter((item) => {
    const kind = caseStatusKind(item.status)
    if (filter === 'active' && kind === 'closed') return false
    if (filter === 'closed' && kind !== 'closed') return false
    if (!needle) return true
    return item.case_id.toLowerCase().includes(needle) || (item.case_alias || '').toLowerCase().includes(needle)
  })
}

/** 저장된 회기 번호 중 최댓값 + 1 (회기가 없으면 1). 임시저장만 있는 회기 번호도 포함한다. */
export function nextSessionNumber(sessions: { session_number: number }[], drafts: { session_number: number }[] = []): number {
  const numbers = [...sessions, ...drafts]
    .map((item) => Number(item.session_number))
    .filter((value) => Number.isInteger(value) && value > 0)
  return numbers.length ? Math.max(...numbers) + 1 : 1
}

export const TRANSCRIPT_STATUS_LABELS: Record<string, string> = {
  none: '축어록 없음',
  pending: '전사 대기',
  processing: '전사 중',
  completed: '축어록 완료',
  failed: '전사 실패',
}

export const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  session_note: '회기 기록',
  supervision_report: '수퍼비전 보고서',
  termination_report: '종결 보고서',
}

export function transcriptStatusLabel(status: string | null | undefined): string {
  return TRANSCRIPT_STATUS_LABELS[status || 'none'] || status || '축어록 없음'
}

export function isConfirmedStatus(status: string | null | undefined): boolean {
  return status === 'confirmed' || status === 'demo_confirmed'
}

/** 회기의 대표 요약 상태: 검토 완료 > AI 초안 > 요약 없음 */
export function summaryStatusLabel(note: { status: string } | null): { label: string; tone: 'confirmed' | 'draft' | 'none' } {
  if (!note) return { label: '요약 없음', tone: 'none' }
  return isConfirmedStatus(note.status) ? { label: '검토 완료', tone: 'confirmed' } : { label: 'AI 초안', tone: 'draft' }
}

export interface SessionRecordGroup {
  sessionNumber: number
  session: CaseDashboardSession | null
  /** 해당 회기의 가장 최근 회기 기록(session_note). 복원 가능한 저장 기록. */
  latestNote: CaseDashboardDocument | null
  documents: CaseDashboardDocument[]
  drafts: TemporaryDraftRecord[]
}

function byCreatedDesc(a: { created_at: string | null }, b: { created_at: string | null }): number {
  return (b.created_at || '').localeCompare(a.created_at || '')
}

/**
 * 케이스 대시보드의 회기·문서·임시저장을 회기 번호 기준으로 묶는다.
 * 회기 행이 아직 없는 임시저장(생성 전 저장)도 별도 그룹으로 노출해 이어서 작업할 수 있게 한다.
 */
export function groupSessionRecords(
  dashboard: Pick<CaseDashboardResponse, 'sessions' | 'documents'>,
  drafts: TemporaryDraftRecord[],
): SessionRecordGroup[] {
  const groups = new Map<number, SessionRecordGroup>()
  const ensure = (sessionNumber: number) => {
    let group = groups.get(sessionNumber)
    if (!group) {
      group = { sessionNumber, session: null, latestNote: null, documents: [], drafts: [] }
      groups.set(sessionNumber, group)
    }
    return group
  }
  for (const session of dashboard.sessions) ensure(session.session_number).session = session
  for (const document of [...dashboard.documents].sort(byCreatedDesc)) {
    if (document.session_number === null || document.session_number === undefined) continue
    const group = ensure(document.session_number)
    group.documents.push(document)
    if (!group.latestNote && document.document_type === 'session_note') group.latestNote = document
  }
  for (const draft of [...drafts].sort((a, b) => (b.saved_at || '').localeCompare(a.saved_at || ''))) {
    ensure(draft.session_number).drafts.push(draft)
  }
  return [...groups.values()].sort((a, b) => b.sessionNumber - a.sessionNumber)
}

export function caseRequestErrorMessage(error: unknown, fallback = '케이스 정보를 불러오지 못했습니다.'): string {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response
  const status = response?.status
  if (status === 401) return '로그인이 필요하거나 로그인 세션이 만료되었습니다. 다시 로그인해주세요.'
  if (status === 403) return '다른 사용자의 케이스에는 접근할 수 없습니다.'
  if (status === 404) return '해당 케이스로 저장된 기록이 없습니다.'
  if (status === 503) return '저장소(Supabase)가 설정되지 않아 케이스 정보를 조회할 수 없습니다.'
  if (typeof response?.data?.detail === 'string' && response.data.detail.trim()) return response.data.detail
  return error instanceof Error && !status ? error.message : fallback
}
