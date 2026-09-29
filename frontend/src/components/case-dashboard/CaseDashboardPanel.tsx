import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  AlertTriangle,
  CalendarDays,
  CalendarPlus,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  FileText,
  History,
  List,
  Loader2,
  Mic,
  PenLine,
  Plus,
  Sparkles,
} from 'lucide-react'

import { fetchCaseDashboard, listTemporaryDrafts, updateCaseSchedule } from '../../api/client'
import {
  caseDisplayName,
  caseRequestErrorMessage,
  caseStatusKind,
  caseStatusLabel,
  clientMetaLine,
  formatKoreanDate,
  formatKoreanDateWithWeekday,
  groupSessionRecords,
  isConfirmedStatus,
  nextSessionNumber,
  paginate,
  summaryStatusLabel,
  type SessionRecordGroup,
} from '../../lib/caseList'
import type { CaseDashboardExport, CaseDashboardResponse, TemporaryDraftRecord } from '../../types/session'
import { ClientAvatar, EmptyState, GhostButton, Pagination, PrimaryButton, SelectField, StatusChip } from '../app-shell/ui'
import { DocumentIcon } from '../../pages/HomeDashboardPage'

export interface StartSessionInput {
  caseId: string
  caseAlias: string | null
  sessionNumber: number
}

interface CaseDashboardPanelProps {
  caseId: string
  /** Bumped by the parent after external edits (e.g. profile modal) to force a reload. */
  refreshKey?: number
  onBack: () => void
  onOpenNote: (noteId: string) => void
  onOpenDraft: (draftId: string) => void
  onStartSession: (input: StartSessionInput) => void
  onEditProfile: (dashboard: CaseDashboardResponse) => void
}

const PAGE_SIZE = 4

function formatDate(value: string | null): string {
  if (!value) return '-'
  return value.length > 10 ? value.slice(0, 10) : value
}

type TileState = 'done' | 'draft' | 'none'

interface ScheduleEntry {
  date: string
  label: string
  tone: 'done' | 'upcoming'
}

/**
 * Builds the schedule list from stored data only: dated sessions are "완료" and the case's
 * next scheduled date is "예정". Time slots and no-shows are not stored, so they are not shown.
 */
function buildScheduleEntries(dashboard: CaseDashboardResponse): ScheduleEntry[] {
  const entries: ScheduleEntry[] = dashboard.sessions
    .filter((session) => session.session_date)
    .map((session) => ({ date: String(session.session_date).slice(0, 10), label: `${session.session_number}회기 상담 완료`, tone: 'done' }))
  if (dashboard.next_scheduled_date) {
    const next = Math.max(0, ...dashboard.sessions.map((session) => session.session_number)) + 1
    entries.push({ date: dashboard.next_scheduled_date.slice(0, 10), label: `${next}회기 상담 예정`, tone: 'upcoming' })
  }
  return entries.sort((a, b) => a.date.localeCompare(b.date))
}

function exportDone(exports: CaseDashboardExport[], sessionNumber: number, documentType: string): boolean {
  return exports.some((item) => item.session_number === sessionNumber && item.document_type === documentType && item.status !== 'failed')
}

/**
 * Client profile page (Figma "목록으로 | 홍길동"). Reads the case's sessions, documents, exports and temporary
 * drafts with the user token and routes stored records into the existing restore flow (onOpenNote/onOpenDraft).
 */
export default function CaseDashboardPanel({ caseId, refreshKey = 0, onBack, onOpenNote, onOpenDraft, onStartSession, onEditProfile }: CaseDashboardPanelProps) {
  const [dashboard, setDashboard] = useState<CaseDashboardResponse | null>(null)
  const [drafts, setDrafts] = useState<TemporaryDraftRecord[]>([])
  const [draftsError, setDraftsError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'sessions' | 'documents'>('sessions')
  const [sort, setSort] = useState<'newest' | 'oldest'>('newest')
  const [page, setPage] = useState(1)
  const [checked, setChecked] = useState<Set<number>>(new Set())
  const [scheduleOpen, setScheduleOpen] = useState(false)
  const [scheduleView, setScheduleView] = useState<'calendar' | 'list'>('list')
  const [scheduleCount, setScheduleCount] = useState('')
  const [scheduleDate, setScheduleDate] = useState('')
  const [isSavingSchedule, setIsSavingSchedule] = useState(false)
  const [scheduleMessage, setScheduleMessage] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  const applyDashboard = (data: CaseDashboardResponse) => {
    setDashboard(data)
    setScheduleCount(data.total_scheduled_session_count === null ? '' : String(data.total_scheduled_session_count))
    setScheduleDate(data.next_scheduled_date || '')
  }

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    setError(null)
    setDraftsError(null)
    setScheduleMessage(null)
    void Promise.allSettled([fetchCaseDashboard(caseId), listTemporaryDrafts(caseId)]).then(([dashboardResult, draftsResult]) => {
      if (cancelled) return
      if (dashboardResult.status === 'fulfilled') applyDashboard(dashboardResult.value)
      else {
        setDashboard(null)
        setError(caseRequestErrorMessage(dashboardResult.reason))
      }
      if (draftsResult.status === 'fulfilled') setDrafts(draftsResult.value)
      else {
        setDrafts([])
        setDraftsError('임시저장 목록을 불러오지 못했습니다. 회기 기록만 표시합니다.')
      }
      setIsLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [caseId, reloadKey, refreshKey])

  const groups = useMemo<SessionRecordGroup[]>(() => {
    const grouped = dashboard ? groupSessionRecords(dashboard, drafts) : []
    return sort === 'newest' ? grouped : [...grouped].reverse()
  }, [dashboard, drafts, sort])
  const pagedGroups = paginate(groups, page, PAGE_SIZE)
  useEffect(() => setPage(1), [sort, tab, caseId])

  const saveSchedule = async () => {
    if (!dashboard || isSavingSchedule) return
    const parsedCount = scheduleCount.trim() === '' ? null : Number(scheduleCount)
    if (parsedCount !== null && (!Number.isInteger(parsedCount) || parsedCount < 0)) {
      setScheduleMessage('전체 예정 회기 수는 0 이상의 정수여야 합니다.')
      return
    }
    setIsSavingSchedule(true)
    setScheduleMessage(null)
    try {
      applyDashboard(await updateCaseSchedule(dashboard.case_id, { total_scheduled_session_count: parsedCount, next_scheduled_date: scheduleDate.trim() || null }))
      setScheduleMessage('일정을 저장했습니다.')
      setScheduleOpen(false)
    } catch (requestError) {
      setScheduleMessage(caseRequestErrorMessage(requestError, '일정 정보를 저장하지 못했습니다.'))
    } finally {
      setIsSavingSchedule(false)
    }
  }

  const startSession = () => {
    onStartSession({ caseId, caseAlias: dashboard?.case_alias || null, sessionNumber: nextSessionNumber(dashboard?.sessions || [], drafts) })
  }

  const toggleChecked = (sessionNumber: number) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(sessionNumber)) next.delete(sessionNumber)
      else next.add(sessionNumber)
      return next
    })
  }

  const name = dashboard ? caseDisplayName({ case_id: dashboard.case_id, case_alias: dashboard.case_alias }) : caseId
  const sessionDates = new Set((dashboard?.sessions || []).map((session) => (session.session_date || '').slice(0, 10)).filter(Boolean))
  const scheduled = dashboard?.total_scheduled_session_count ?? null
  const remaining = dashboard && scheduled !== null ? Math.max(scheduled - dashboard.total_session_count, 0) : null
  const scheduleEntries = dashboard ? buildScheduleEntries(dashboard) : []
  const scheduleByMonth = scheduleEntries.reduce<Record<string, ScheduleEntry[]>>((acc, entry) => {
    const key = entry.date.slice(0, 7)
    ;(acc[key] ||= []).push(entry)
    return acc
  }, {})

  return (
    <section aria-label="내담자 프로필" className="mx-auto w-full max-w-[1240px] px-4 py-5 md:px-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button type="button" onClick={onBack} className="inline-flex items-center gap-2 text-lg text-grey-500 hover:text-grey-900">
          <ChevronLeft className="h-5 w-5" />
          <span>목록으로</span>
          <span className="text-grey-300">|</span>
          <span className="font-extrabold text-grey-900">{name}</span>
        </button>
        <PrimaryButton onClick={startSession} disabled={isLoading || Boolean(error)}><Plus className="h-4 w-4" />새 회기 기록</PrimaryButton>
      </div>

      {error && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-2 rounded-[10px] border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <p className="min-w-0 flex-1">{error}</p>
          <button type="button" onClick={() => setReloadKey((value) => value + 1)} className="font-bold underline">다시 시도</button>
        </div>
      )}
      {isLoading && !dashboard && (
        <p role="status" className="mt-8 flex items-center justify-center gap-2 text-sm text-grey-500"><Loader2 className="h-4 w-4 animate-spin" />내담자 정보를 불러오는 중입니다…</p>
      )}

      {dashboard && (
        <div className="mt-5 grid gap-5 lg:grid-cols-[316px_minmax(0,1fr)]">
          <div className="space-y-5">
            <section className="rm-card p-4" aria-label="프로필">
              <div className="flex items-start gap-3">
                <ClientAvatar size={40} />
                <div className="min-w-0 flex-1">
                  <h2 className="text-lg font-extrabold text-grey-900">{name}</h2>
                  <p className="mt-0.5 text-xs text-grey-500">{clientMetaLine(dashboard, false) || '프로필 정보를 입력해주세요'}</p>
                </div>
                <button type="button" onClick={() => onEditProfile(dashboard)} className="inline-flex shrink-0 items-center gap-1 text-xs text-grey-500 hover:text-grey-900"><PenLine className="h-3.5 w-3.5" />수정하기</button>
              </div>

              <div className="mt-4 grid grid-cols-3 rounded-[12px] bg-grey-100 px-2 py-3 text-center">
                <Stat label="진행 회기">
                  {dashboard.total_session_count}
                  <span className="font-semibold text-grey-500">{scheduled !== null ? `/${scheduled}회` : '회'}</span>
                </Stat>
                <Stat label="남은 회기" divider>
                  <span className="text-primary-400">{remaining !== null ? `${remaining}회` : '-'}</span>
                </Stat>
                <Stat label="진행 상태" divider>
                  <StatusChip kind={caseStatusKind(dashboard.status)} label={caseStatusLabel(dashboard.status)} />
                </Stat>
              </div>

              <div className="mt-3 grid grid-cols-2 rounded-[12px] border border-grey-200 px-3 py-3">
                <DateStat icon={<CalendarDays className="h-4 w-4" />} label="최초 상담일" value={formatDate(dashboard.first_consultation_date)} />
                <DateStat icon={<History className="h-4 w-4" />} label="최근 상담일" value={formatDate(dashboard.latest_consultation_date)} divider />
              </div>

              {dashboard.presenting_problem && (
                <div className="mt-3 rounded-[12px] border border-primary-400/60 p-3.5">
                  <p className="flex items-center gap-2 text-xs text-grey-600">주 호소 문제 <span className="inline-flex items-center gap-1 font-bold text-primary-400"><Sparkles className="h-3.5 w-3.5" />AI 요약</span></p>
                  <p className="mt-2 text-sm leading-6 text-grey-800">{dashboard.presenting_problem}</p>
                </div>
              )}
              {dashboard.client_notes && (
                <div className="mt-3 rounded-[12px] bg-grey-100 p-3.5">
                  <p className="text-xs font-bold text-grey-600">특이사항</p>
                  <p className="mt-1.5 whitespace-pre-wrap text-sm leading-6 text-grey-800">{dashboard.client_notes}</p>
                </div>
              )}
            </section>

            <section className="rm-card p-4" aria-label="상담 일정">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-lg font-bold text-grey-900">상담 일정</h3>
                <GhostButton onClick={() => setScheduleOpen((open) => !open)}><CalendarPlus className="h-4 w-4" />{scheduleOpen ? '닫기' : '일정 추가하기'}</GhostButton>
              </div>
              {scheduleOpen && (
                <div className="mt-3 flex flex-wrap items-end gap-2 rounded-[10px] border border-grey-200 bg-grey-100/60 p-3">
                  <label className="block">
                    <span className="rm-label mb-1 text-xs">다음 상담 예정일</span>
                    <input type="date" value={scheduleDate} onChange={(event) => setScheduleDate(event.target.value)} className="rm-input h-9 w-[150px] text-xs" aria-label="다음 상담 예정일" />
                  </label>
                  <label className="block">
                    <span className="rm-label mb-1 text-xs">전체 예정 회기 수</span>
                    <input inputMode="numeric" value={scheduleCount} onChange={(event) => setScheduleCount(event.target.value)} placeholder="예: 10" className="rm-input h-9 w-[90px] text-xs" aria-label="전체 예정 회기 수" />
                  </label>
                  <PrimaryButton className="h-9 px-4 text-xs" onClick={() => void saveSchedule()} loading={isSavingSchedule}>일정 저장</PrimaryButton>
                </div>
              )}
              {scheduleMessage && <p role="status" className="mt-2 text-xs font-semibold text-grey-500">{scheduleMessage}</p>}
              <div className="mt-3 inline-flex rounded-[8px] border border-grey-200 p-0.5" role="group" aria-label="일정 보기 방식">
                <button type="button" aria-pressed={scheduleView === 'calendar'} aria-label="달력 보기" onClick={() => setScheduleView('calendar')} className={`inline-flex h-7 w-8 items-center justify-center rounded-[6px] ${scheduleView === 'calendar' ? 'bg-grey-100 text-grey-900' : 'text-grey-400'}`}><CalendarDays className="h-4 w-4" /></button>
                <button type="button" aria-pressed={scheduleView === 'list'} aria-label="목록 보기" onClick={() => setScheduleView('list')} className={`inline-flex h-7 w-8 items-center justify-center rounded-[6px] ${scheduleView === 'list' ? 'bg-grey-100 text-grey-900' : 'text-grey-400'}`}><List className="h-4 w-4" /></button>
              </div>
              {scheduleView === 'calendar' ? (
                <MiniCalendar highlight={dashboard.next_scheduled_date} marks={sessionDates} />
              ) : scheduleEntries.length === 0 ? (
                <p className="mt-4 text-sm text-grey-500">등록된 상담 일정이 없습니다. "일정 추가하기"로 다음 상담 예정일을 입력해보세요.</p>
              ) : (
                <div className="mt-3 space-y-3">
                  {Object.entries(scheduleByMonth).map(([month, entries]) => (
                    <div key={month}>
                      <p className="text-sm font-bold text-grey-800">{Number(month.slice(0, 4))}년 {Number(month.slice(5, 7))}월</p>
                      <ul className="mt-1 divide-y divide-grey-100">
                        {entries.map((entry) => (
                          <li key={`${entry.date}-${entry.label}`} className="flex items-center gap-3 py-2.5 text-xs">
                            {entry.tone === 'done'
                              ? <CheckCircle2 className="h-5 w-5 shrink-0 text-success-500" aria-label="완료" />
                              : <Clock className="h-5 w-5 shrink-0 text-primary-400" aria-label="예정" />}
                            <span className="w-[92px] shrink-0 font-bold text-grey-800">{formatKoreanDateWithWeekday(entry.date, false)}</span>
                            <span className={`font-bold ${entry.tone === 'done' ? 'text-success-500' : 'text-primary-400'}`}>{entry.label}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>

          <section className="rm-card flex min-h-[560px] flex-col" aria-label="회기와 문서">
            <div className="flex items-center gap-2 border-b border-grey-200 px-3">
              {([['sessions', `상담 회기 (${groups.length})`], ['documents', `생성된 문서 (${dashboard.documents.length})`]] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={tab === id}
                  onClick={() => setTab(id)}
                  className={`-mb-px border-b-2 px-4 py-4 text-[15px] font-bold ${tab === id ? 'border-primary-400 text-grey-900' : 'border-transparent text-grey-500 hover:text-grey-800'}`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="flex flex-1 flex-col p-4 md:p-5">
              {tab === 'sessions' ? (
                groups.length === 0 ? (
                  <EmptyState title="아직 기록된 회기가 없어요." description="새 회기를 시작해 첫 상담 기록을 남겨보세요." action={<PrimaryButton onClick={startSession}><Plus className="h-4 w-4" />새 회기 기록</PrimaryButton>} />
                ) : (
                  <>
                    <div className="flex items-center justify-end gap-2">
                      <SelectField ariaLabel="정렬" value={sort} onChange={(value) => setSort(value as 'newest' | 'oldest')} options={[{ id: 'newest', label: '최신순' }, { id: 'oldest', label: '오래된순' }]} className="h-9 w-[104px] text-xs" />
                      <button type="button" disabled title="여러 회기를 묶어 요약하는 기능은 준비 중입니다." className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-grey-200 px-3 text-xs font-bold text-grey-400">
                        <Sparkles className="h-3.5 w-3.5" />요약하기
                      </button>
                    </div>
                    {draftsError && <p role="status" className="mt-2 text-[11px] text-amber-700">{draftsError}</p>}
                    <ul className="mt-3 space-y-3">
                      {pagedGroups.items.map((group) => (
                        <SessionCard
                          key={group.sessionNumber}
                          group={group}
                          exports={dashboard.exports}
                          checked={checked.has(group.sessionNumber)}
                          onToggleChecked={() => toggleChecked(group.sessionNumber)}
                          onOpenNote={onOpenNote}
                          onOpenDraft={onOpenDraft}
                        />
                      ))}
                    </ul>
                    <div className="mt-auto pt-6">
                      <Pagination page={pagedGroups.page} pageCount={pagedGroups.pageCount} onChange={setPage} />
                    </div>
                  </>
                )
              ) : dashboard.documents.length === 0 ? (
                <EmptyState title="아직 변환된 문서가 없어요." description="회기 요약을 원하는 문서 형식으로 변환해보세요." />
              ) : (
                <ul className="space-y-2">
                  {dashboard.documents.map((doc) => (
                    <li key={doc.document_id}>
                      <button
                        type="button"
                        onClick={() => doc.document_type === 'session_note' && onOpenNote(doc.document_id)}
                        disabled={doc.document_type !== 'session_note'}
                        className="flex w-full items-center gap-3 rounded-[12px] border border-grey-200 px-4 py-3 text-left hover:bg-grey-100/60 disabled:cursor-default disabled:hover:bg-transparent"
                      >
                        <DocumentIcon type={doc.document_type} confirmed={isConfirmedStatus(doc.status)} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-bold text-grey-900">{doc.title}</span>
                          <span className="block text-xs text-grey-500">{doc.document_type === 'session_note' ? summaryStatusLabel(doc).label : '보고서 초안'} · {formatKoreanDate(doc.created_at ? doc.created_at.slice(0, 10) : null)}</span>
                        </span>
                        {doc.document_type === 'session_note' && <ChevronRight className="h-4 w-4 shrink-0 text-grey-500" />}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>
        </div>
      )}
    </section>
  )
}

function Stat({ label, children, divider = false }: { label: string; children: ReactNode; divider?: boolean }) {
  return (
    <div className={`flex flex-col items-center justify-center gap-1 ${divider ? 'border-l border-grey-200' : ''}`}>
      <p className="text-xs text-grey-500">{label}</p>
      <div className="text-base font-extrabold text-grey-900">{children}</div>
    </div>
  )
}

function DateStat({ icon, label, value, divider = false }: { icon: ReactNode; label: string; value: string; divider?: boolean }) {
  return (
    <div className={`flex items-center gap-2.5 ${divider ? 'border-l border-grey-200 pl-3' : ''}`}>
      <span className="text-grey-600">{icon}</span>
      <div className="min-w-0">
        <p className="text-xs text-grey-500">{label}</p>
        <p className="mt-0.5 text-sm font-extrabold text-grey-900">{value}</p>
      </div>
    </div>
  )
}

const TILE_TONE: Record<TileState, string> = {
  done: 'bg-primary-50 text-grey-800',
  draft: 'bg-primary-50/60 text-grey-800',
  none: 'bg-grey-100 text-grey-400',
}
const TILE_STATUS: Record<TileState, { label: string; className: string }> = {
  done: { label: '완료', className: 'text-success-500' },
  draft: { label: '초안', className: 'text-primary-400' },
  none: { label: '미작성', className: 'text-grey-400' },
}

function StatusTile({ icon, label, state }: { icon: ReactNode; label: string; state: TileState }) {
  return (
    <span className={`inline-flex min-w-[76px] items-center gap-2 rounded-[8px] px-2.5 py-1.5 ${TILE_TONE[state]}`}>
      <span className={state === 'none' ? 'text-grey-400' : 'text-primary-400'}>{icon}</span>
      <span className="leading-tight">
        <span className="block text-[11px] font-bold">{label}</span>
        <span className={`block text-[11px] font-bold ${TILE_STATUS[state].className}`}>{TILE_STATUS[state].label}</span>
      </span>
    </span>
  )
}

/**
 * One session card: 회기 요약 (latest session note), and three tiles —
 * 축어록 (transcript_status), 상담일지 (session_note export or confirmed summary), 슈퍼비전 (supervision report or export).
 */
function SessionCard({ group, exports, checked, onToggleChecked, onOpenNote, onOpenDraft }: {
  group: SessionRecordGroup
  exports: CaseDashboardExport[]
  checked: boolean
  onToggleChecked: () => void
  onOpenNote: (noteId: string) => void
  onOpenDraft: (draftId: string) => void
}) {
  const openable = Boolean(group.latestNote || group.drafts.length)
  const open = () => {
    if (group.latestNote) onOpenNote(group.latestNote.document_id)
    else if (group.drafts.length) onOpenDraft(group.drafts[0].draft_id)
  }
  const transcript: TileState = group.session?.transcript_status === 'completed' ? 'done' : 'none'
  const note: TileState = exportDone(exports, group.sessionNumber, 'session_note') || isConfirmedStatus(group.latestNote?.status)
    ? 'done'
    : group.latestNote ? 'draft' : 'none'
  const supervisionDoc = group.documents.some((doc) => doc.document_type === 'supervision_report')
  const supervision: TileState = exportDone(exports, group.sessionNumber, 'supervision_report') ? 'done' : supervisionDoc ? 'draft' : 'none'
  const summary = group.session?.summary

  return (
    <li className={`rounded-[12px] border border-grey-200 bg-white ${openable ? 'hover:border-primary-100' : ''}`}>
      <div className="flex items-start gap-3 p-4">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggleChecked}
          aria-label={`${group.sessionNumber}회기 선택`}
          className="mt-0.5 h-5 w-5 shrink-0 rounded-md border-grey-200 text-primary-400 focus:ring-primary-100"
        />
        <button type="button" onClick={open} disabled={!openable} className="flex min-w-0 flex-1 flex-col gap-3 text-left disabled:cursor-default xl:flex-row">
          <span className="w-full shrink-0 xl:w-[124px]">
            <span className="block text-[15px] font-bold text-grey-900">{group.sessionNumber} 회기</span>
            <span className="mt-1 block text-xs text-grey-500">
              {group.session?.session_date ? formatKoreanDateWithWeekday(group.session.session_date) : '회기 생성 전'}
            </span>
            {group.drafts.length > 0 && <span className="mt-1 inline-block rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-bold text-amber-700">임시저장 {group.drafts.length}</span>}
          </span>
          <span className="min-w-0 flex-1 border-grey-200 xl:border-l xl:pl-4">
            <span className="flex items-center gap-1 text-sm font-bold text-grey-900"><Sparkles className="h-3.5 w-3.5 text-primary-400" />회기 요약</span>
            <span className="mt-1 line-clamp-2 block text-xs leading-5 text-grey-600">
              {summary || (group.latestNote ? '요약 내용을 불러오려면 눌러서 열어주세요.' : '아직 생성된 회기 요약이 없습니다.')}
            </span>
            <span className="mt-3 flex flex-wrap gap-2">
              <StatusTile icon={<Mic className="h-4 w-4" />} label="축어록" state={transcript} />
              <StatusTile icon={<FileText className="h-4 w-4" />} label="상담일지" state={note} />
              <StatusTile icon={<FileText className="h-4 w-4" />} label="슈퍼비전" state={supervision} />
            </span>
          </span>
        </button>
        <button type="button" onClick={open} disabled={!openable} aria-label={`${group.sessionNumber}회기 열기`} className="shrink-0 self-center text-grey-700 disabled:text-grey-200"><ChevronRight className="h-5 w-5" /></button>
      </div>
    </li>
  )
}

function MiniCalendar({ highlight, marks }: { highlight: string | null; marks: Set<string> }) {
  const initial = (highlight && /^\d{4}-\d{2}/.test(highlight) ? highlight : new Date().toISOString()).slice(0, 7)
  const [month, setMonth] = useState(initial)
  useEffect(() => setMonth(initial), [initial])
  const [year, monthIndex] = month.split('-').map(Number)
  const first = new Date(Date.UTC(year, monthIndex - 1, 1))
  const startWeekday = first.getUTCDay()
  const daysInMonth = new Date(Date.UTC(year, monthIndex, 0)).getUTCDate()
  const daysInPrev = new Date(Date.UTC(year, monthIndex - 1, 0)).getUTCDate()
  const cells: { key: string; day: number; inMonth: boolean; iso: string }[] = []
  for (let i = startWeekday - 1; i >= 0; i -= 1) {
    const d = daysInPrev - i
    const date = new Date(Date.UTC(year, monthIndex - 2, d))
    cells.push({ key: `p${d}`, day: d, inMonth: false, iso: date.toISOString().slice(0, 10) })
  }
  for (let d = 1; d <= daysInMonth; d += 1) {
    cells.push({ key: `c${d}`, day: d, inMonth: true, iso: `${year}-${String(monthIndex).padStart(2, '0')}-${String(d).padStart(2, '0')}` })
  }
  let next = 1
  while (cells.length % 7 !== 0) {
    const date = new Date(Date.UTC(year, monthIndex, next))
    cells.push({ key: `n${next}`, day: next, inMonth: false, iso: date.toISOString().slice(0, 10) })
    next += 1
  }
  const shift = (delta: number) => {
    const date = new Date(Date.UTC(year, monthIndex - 1 + delta, 1))
    setMonth(date.toISOString().slice(0, 7))
  }
  const today = new Date().toISOString().slice(0, 10)

  return (
    <div className="mt-3 rounded-[12px] bg-grey-100/70 p-4" aria-label="상담 일정 달력">
      <div className="flex items-center justify-between">
        <p className="text-sm font-bold text-grey-800">{year}년 {monthIndex}월</p>
        <div className="flex gap-1">
          <button type="button" aria-label="이전 달" onClick={() => shift(-1)} className="inline-flex h-7 w-7 items-center justify-center rounded-md text-grey-700 hover:bg-white"><ChevronLeft className="h-4 w-4" /></button>
          <button type="button" aria-label="다음 달" onClick={() => shift(1)} className="inline-flex h-7 w-7 items-center justify-center rounded-md text-grey-700 hover:bg-white"><ChevronRight className="h-4 w-4" /></button>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-7 gap-y-1 text-center text-[11px] text-grey-400">
        {['일', '월', '화', '수', '목', '금', '토'].map((day) => <span key={day} className="py-1">{day}</span>)}
        {cells.map((cell) => {
          const isHighlight = highlight?.slice(0, 10) === cell.iso
          const isMark = marks.has(cell.iso)
          return (
            <span
              key={cell.key}
              title={isHighlight ? '다음 상담 예정일' : isMark ? '상담 회기' : undefined}
              className={`relative mx-auto flex h-8 w-8 items-center justify-center rounded-full text-xs ${
                isHighlight ? 'bg-primary-400 font-bold text-white' : cell.inMonth ? 'text-grey-800' : 'text-grey-300'
              } ${cell.iso === today && !isHighlight ? 'ring-1 ring-primary-400' : ''}`}
            >
              {cell.day}
              {isMark && !isHighlight && <span className="absolute bottom-0.5 h-1 w-1 rounded-full bg-primary-400" aria-hidden="true" />}
            </span>
          )
        })}
      </div>
      <p className="mt-2 text-[10px] text-grey-500">● 상담 회기 · 파란 원: 다음 상담 예정일</p>
    </div>
  )
}
