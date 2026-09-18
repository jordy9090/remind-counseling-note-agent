import { useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  CalendarDays,
  ClipboardCheck,
  FileText,
  Loader2,
  Plus,
  RefreshCcw,
  Save,
} from 'lucide-react'

import { fetchCaseDashboard, listTemporaryDrafts, updateCaseSchedule } from '../../api/client'
import {
  DOCUMENT_TYPE_LABELS,
  caseDisplayName,
  caseRequestErrorMessage,
  caseStatusKind,
  caseStatusLabel,
  groupSessionRecords,
  nextSessionNumber,
  summaryStatusLabel,
  transcriptStatusLabel,
  type SessionRecordGroup,
} from '../../lib/caseList'
import type { CaseDashboardResponse, TemporaryDraftRecord } from '../../types/session'

export interface StartSessionInput {
  caseId: string
  caseAlias: string | null
  sessionNumber: number
}

interface CaseDashboardPanelProps {
  caseId: string
  onBack: () => void
  onOpenNote: (noteId: string) => void
  onOpenDraft: (draftId: string) => void
  onStartSession: (input: StartSessionInput) => void
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return value.length > 10 ? value.slice(0, 10) : value
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return formatDate(value)
  return date.toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const STATUS_TONE: Record<ReturnType<typeof caseStatusKind>, string> = {
  active: 'bg-blue-50 text-blue-700',
  closed: 'bg-emerald-50 text-emerald-700',
  pending: 'bg-orange-50 text-orange-700',
}

const SUMMARY_TONE = {
  confirmed: 'bg-emerald-50 text-emerald-700',
  draft: 'bg-blue-50 text-blue-700',
  none: 'bg-slate-100 text-slate-500',
} as const

/**
 * 개별 내담자(케이스) 대시보드. 케이스 목록에서 선택한 케이스의 회기·문서·임시저장을
 * 사용자 토큰으로 조회하고, 저장 기록을 기존 복원 흐름(onOpenNote/onOpenDraft)으로 연결한다.
 */
export default function CaseDashboardPanel({ caseId, onBack, onOpenNote, onOpenDraft, onStartSession }: CaseDashboardPanelProps) {
  const [dashboard, setDashboard] = useState<CaseDashboardResponse | null>(null)
  const [drafts, setDrafts] = useState<TemporaryDraftRecord[]>([])
  const [draftsError, setDraftsError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
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
      if (dashboardResult.status === 'fulfilled') {
        applyDashboard(dashboardResult.value)
      } else {
        setDashboard(null)
        setError(caseRequestErrorMessage(dashboardResult.reason))
      }
      if (draftsResult.status === 'fulfilled') {
        setDrafts(draftsResult.value)
      } else {
        setDrafts([])
        setDraftsError('임시저장 목록을 불러오지 못했습니다. 회기 기록만 표시합니다.')
      }
      setIsLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [caseId, reloadKey])

  const groups = useMemo<SessionRecordGroup[]>(
    () => (dashboard ? groupSessionRecords(dashboard, drafts) : []),
    [dashboard, drafts],
  )

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
      applyDashboard(
        await updateCaseSchedule(dashboard.case_id, {
          total_scheduled_session_count: parsedCount,
          next_scheduled_date: scheduleDate.trim() || null,
        }),
      )
      setScheduleMessage('일정 정보를 저장했습니다.')
    } catch (requestError) {
      setScheduleMessage(caseRequestErrorMessage(requestError, '일정 정보를 저장하지 못했습니다.'))
    } finally {
      setIsSavingSchedule(false)
    }
  }

  const remainingSessions =
    dashboard && dashboard.total_scheduled_session_count !== null
      ? Math.max(dashboard.total_scheduled_session_count - dashboard.total_session_count, 0)
      : null

  const startSession = () => {
    onStartSession({
      caseId,
      caseAlias: dashboard?.case_alias || null,
      sessionNumber: nextSessionNumber(dashboard?.sessions || [], drafts),
    })
  }

  return (
    <section aria-label="내담자 대시보드" className="mx-auto w-full max-w-[960px] px-4 py-5 md:px-6">
      <button type="button" onClick={onBack} className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-slate-500 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" />
        케이스 목록
      </button>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-extrabold text-black">
              {dashboard ? caseDisplayName({ case_id: dashboard.case_id, case_alias: dashboard.case_alias }) : caseId}
            </h2>
            {dashboard && (
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${STATUS_TONE[caseStatusKind(dashboard.status)]}`}>
                {caseStatusLabel(dashboard.status)}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">케이스 ID: {caseId}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            disabled={isLoading}
            className="inline-flex h-9 items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 text-xs font-bold text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />}
            새로고침
          </button>
          <button
            type="button"
            onClick={startSession}
            disabled={isLoading || Boolean(error)}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-bold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            <Plus className="h-4 w-4" />
            새 회기 입력
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="mt-4 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <p>{error}</p>
        </div>
      )}
      {isLoading && !dashboard && (
        <p role="status" className="mt-6 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          케이스 현황을 불러오는 중입니다…
        </p>
      )}

      {dashboard && (
        <div className="mt-5 space-y-5">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
            {[
              ['진행 회기', `${dashboard.total_session_count}회`],
              ['남은 회기', remainingSessions === null ? '—' : `${remainingSessions}회`],
              ['최초 상담일', formatDate(dashboard.first_consultation_date)],
              ['최근 상담일', formatDate(dashboard.latest_consultation_date)],
              ['다음 예정일', formatDate(dashboard.next_scheduled_date)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[8px] border border-slate-200 bg-white px-3 py-2">
                <p className="text-[11px] font-bold text-slate-500">{label}</p>
                <p className="mt-0.5 truncate text-sm font-bold text-slate-950">{value}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-end gap-2 rounded-[8px] border border-slate-200 bg-white px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-xs font-extrabold text-slate-950">
              <CalendarDays className="h-4 w-4 text-blue-700" />
              일정
            </div>
            <div>
              <p className="text-[11px] font-bold text-slate-500">전체 예정 회기 수</p>
              <input
                value={scheduleCount}
                onChange={(event) => setScheduleCount(event.target.value)}
                inputMode="numeric"
                placeholder="예: 10"
                aria-label="전체 예정 회기 수"
                className="mt-1 h-8 w-24 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs text-slate-700 focus:border-blue-400 focus:outline-none"
              />
            </div>
            <div>
              <p className="text-[11px] font-bold text-slate-500">다음 상담 예정일</p>
              <input
                type="date"
                value={scheduleDate}
                onChange={(event) => setScheduleDate(event.target.value)}
                aria-label="다음 상담 예정일"
                className="mt-1 h-8 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs text-slate-700 focus:border-blue-400 focus:outline-none"
              />
            </div>
            <button
              type="button"
              onClick={saveSchedule}
              disabled={isSavingSchedule}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-blue-600 bg-white px-3 text-xs font-bold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSavingSchedule ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              일정 저장
            </button>
            {scheduleMessage && <p role="status" className="text-[11px] font-semibold text-slate-500">{scheduleMessage}</p>}
          </div>

          <div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-extrabold text-slate-950">회기별 기록</p>
              <p className="text-[11px] text-slate-400">회기를 눌러 저장된 요약·임시저장을 이어서 작업할 수 있습니다.</p>
            </div>
            {draftsError && <p role="status" className="mt-2 text-[11px] text-amber-700">{draftsError}</p>}
            {groups.length === 0 ? (
              <div className="mt-2 rounded-[8px] border border-dashed border-slate-300 bg-white px-4 py-8 text-center text-sm text-slate-500">
                아직 저장된 회기가 없습니다. 새 회기를 입력해 첫 요약을 생성해주세요.
              </div>
            ) : (
              <ul className="mt-2 divide-y divide-slate-100 rounded-[8px] border border-slate-200 bg-white">
                {groups.map((group) => (
                  <SessionRecordRow key={group.sessionNumber} group={group} onOpenNote={onOpenNote} onOpenDraft={onOpenDraft} />
                ))}
              </ul>
            )}
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <p className="text-xs font-extrabold text-slate-950">생성 문서</p>
              <div className="mt-1.5 space-y-1">
                {dashboard.documents.length === 0 && <p className="text-[11px] text-slate-400">생성된 문서가 없습니다.</p>}
                {dashboard.documents.slice(0, 10).map((doc) => (
                  <div key={doc.document_id} className="flex items-center gap-2 text-[11px] text-slate-600">
                    <FileText className="h-3 w-3 shrink-0 text-blue-600" />
                    <span className="truncate">{doc.title || DOCUMENT_TYPE_LABELS[doc.document_type] || doc.document_type}</span>
                    <span className="shrink-0 text-slate-400">{summaryStatusLabel(doc).label}</span>
                    <span className="ml-auto shrink-0 text-slate-400">{formatDateTime(doc.created_at)}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs font-extrabold text-slate-950">문서 변환 이력</p>
              <div className="mt-1.5 space-y-1">
                {dashboard.exports.length === 0 && <p className="text-[11px] text-slate-400">변환 이력이 없습니다.</p>}
                {dashboard.exports.slice(0, 10).map((exportItem) => (
                  <div key={exportItem.export_id} className="flex items-center gap-2 text-[11px] text-slate-600">
                    <span className="truncate">
                      {exportItem.title || DOCUMENT_TYPE_LABELS[exportItem.document_type] || exportItem.document_type} ·{' '}
                      {exportItem.format.toUpperCase()}
                    </span>
                    <span className={`shrink-0 font-bold ${exportItem.status === 'failed' ? 'text-rose-600' : 'text-emerald-600'}`}>
                      {exportItem.status === 'failed' ? '변환 오류' : '변환 완료'}
                    </span>
                    <span className="ml-auto shrink-0 text-slate-400">{formatDateTime(exportItem.created_at)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

function SessionRecordRow({
  group,
  onOpenNote,
  onOpenDraft,
}: {
  group: SessionRecordGroup
  onOpenNote: (noteId: string) => void
  onOpenDraft: (draftId: string) => void
}) {
  const summary = summaryStatusLabel(group.latestNote)
  const otherDocuments = group.documents.filter((doc) => doc.document_type !== 'session_note')
  return (
    <li className="px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-bold text-slate-800">
            {group.sessionNumber}회기 · {group.session ? formatDate(group.session.session_date) : '회기 생성 전'}
          </p>
          {group.session?.summary && <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{group.session.summary}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-bold">
          {group.session && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">{transcriptStatusLabel(group.session.transcript_status)}</span>
          )}
          <span className={`rounded-full px-2 py-0.5 ${SUMMARY_TONE[summary.tone]}`}>{summary.label}</span>
          {otherDocuments.length > 0 && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-600">
              {otherDocuments.map((doc) => DOCUMENT_TYPE_LABELS[doc.document_type] || doc.document_type).join(' · ')}
            </span>
          )}
          {group.drafts.length > 0 && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-700">임시저장 {group.drafts.length}</span>
          )}
        </div>
      </div>
      {(group.latestNote || group.drafts.length > 0) && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {group.latestNote && (
            <button
              type="button"
              onClick={() => onOpenNote(group.latestNote!.document_id)}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-blue-200 bg-blue-50 px-2.5 text-[11px] font-bold text-blue-700 hover:bg-blue-100"
            >
              <ClipboardCheck className="h-3 w-3" />
              {summary.tone === 'confirmed' ? '검토 완료본 열기' : 'AI 초안 열기'}
            </button>
          )}
          {group.drafts.slice(0, 3).map((draft) => (
            <button
              key={draft.draft_id}
              type="button"
              onClick={() => onOpenDraft(draft.draft_id)}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2.5 text-[11px] font-bold text-amber-800 hover:bg-amber-100"
            >
              <Save className="h-3 w-3" />
              임시저장 열기 · {formatDateTime(draft.saved_at)}
            </button>
          ))}
        </div>
      )}
    </li>
  )
}
