import { useState } from 'react'
import { AlertTriangle, CalendarDays, FileText, Loader2, RefreshCcw, Search } from 'lucide-react'

import { fetchCaseDashboard, updateCaseSchedule } from '../../api/client'
import type { CaseDashboardResponse } from '../../types/session'

const TRANSCRIPT_STATUS_LABELS: Record<string, string> = {
  none: '축어록 없음',
  pending: '전사 대기',
  processing: '전사 중',
  completed: '축어록 완료',
  failed: '전사 실패',
}

const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  session_note: '회기 기록',
  supervision_report: '수퍼비전 보고서',
  termination_report: '종결 보고서',
}

function formatDate(value: string | null): string {
  if (!value) return '—'
  return value.length > 10 ? value.slice(0, 10) : value
}

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { status?: number; data?: { detail?: string } } })?.response
  if (detail?.status === 503) return '저장소(Supabase)가 설정되지 않아 케이스 현황을 조회할 수 없습니다.'
  if (detail?.status === 404) return '해당 케이스 ID로 저장된 기록이 없습니다.'
  if (detail?.status === 403) return '다른 사용자의 케이스입니다.'
  if (detail?.status === 401) return '로그인이 필요합니다.'
  return detail?.data?.detail || '케이스 현황 조회 중 오류가 발생했습니다.'
}

export default function CaseDashboardPanel({ initialCaseId }: { initialCaseId: string }) {
  const [caseId, setCaseId] = useState(initialCaseId)
  const [dashboard, setDashboard] = useState<CaseDashboardResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scheduleCount, setScheduleCount] = useState('')
  const [scheduleDate, setScheduleDate] = useState('')
  const [isSavingSchedule, setIsSavingSchedule] = useState(false)
  const [scheduleMessage, setScheduleMessage] = useState<string | null>(null)

  const applyDashboard = (data: CaseDashboardResponse) => {
    setDashboard(data)
    setScheduleCount(
      data.total_scheduled_session_count === null ? '' : String(data.total_scheduled_session_count),
    )
    setScheduleDate(data.next_scheduled_date || '')
  }

  const loadDashboard = async () => {
    if (!caseId.trim() || isLoading) return
    setIsLoading(true)
    setError(null)
    setScheduleMessage(null)
    try {
      applyDashboard(await fetchCaseDashboard(caseId.trim()))
    } catch (requestError) {
      setDashboard(null)
      setError(errorMessage(requestError))
    } finally {
      setIsLoading(false)
    }
  }

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
      setScheduleMessage(errorMessage(requestError))
    } finally {
      setIsSavingSchedule(false)
    }
  }

  const remainingSessions =
    dashboard && dashboard.total_scheduled_session_count !== null
      ? Math.max(dashboard.total_scheduled_session_count - dashboard.total_session_count, 0)
      : null

  return (
    <section className="mb-5 max-w-[790px] rounded-[12px] border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <CalendarDays className="h-4 w-4 text-blue-700" />
          <h3 className="text-sm font-extrabold text-slate-950">케이스 현황</h3>
          <span className="text-[11px] text-slate-400">저장된 회기·문서·일정을 케이스 ID로 조회합니다</span>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={caseId}
            onChange={(event) => setCaseId(event.target.value)}
            placeholder="케이스 ID"
            className="h-8 w-44 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs text-slate-700 focus:border-blue-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={loadDashboard}
            disabled={isLoading || !caseId.trim()}
            className="inline-flex h-8 items-center gap-1.5 rounded-md bg-blue-600 px-3 text-xs font-bold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          >
            {isLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
            조회
          </button>
        </div>
      </div>

      {error && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      {dashboard && (
        <div className="mt-4 space-y-4">
          <div className="grid gap-2 sm:grid-cols-5">
            {[
              ['진행 회기', `${dashboard.total_session_count}회`],
              ['남은 회기', remainingSessions === null ? '—' : `${remainingSessions}회`],
              ['최초 상담일', formatDate(dashboard.first_consultation_date)],
              ['최근 상담일', formatDate(dashboard.latest_consultation_date)],
              ['다음 예정일', formatDate(dashboard.next_scheduled_date)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-[8px] bg-slate-50 px-3 py-2">
                <p className="text-[11px] font-bold text-slate-500">{label}</p>
                <p className="mt-0.5 truncate text-sm font-bold text-slate-950">{value}</p>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap items-end gap-2 rounded-[8px] border border-slate-200 px-3 py-2.5">
            <div>
              <p className="text-[11px] font-bold text-slate-500">전체 예정 회기 수</p>
              <input
                value={scheduleCount}
                onChange={(event) => setScheduleCount(event.target.value)}
                inputMode="numeric"
                placeholder="예: 10"
                className="mt-1 h-8 w-24 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs text-slate-700 focus:border-blue-400 focus:outline-none"
              />
            </div>
            <div>
              <p className="text-[11px] font-bold text-slate-500">다음 상담 예정일</p>
              <input
                type="date"
                value={scheduleDate}
                onChange={(event) => setScheduleDate(event.target.value)}
                className="mt-1 h-8 rounded-md border border-slate-200 bg-slate-50 px-2.5 text-xs text-slate-700 focus:border-blue-400 focus:outline-none"
              />
            </div>
            <button
              type="button"
              onClick={saveSchedule}
              disabled={isSavingSchedule}
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-blue-600 bg-white px-3 text-xs font-bold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isSavingSchedule ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCcw className="h-3.5 w-3.5" />}
              일정 저장
            </button>
            {scheduleMessage && <p className="text-[11px] font-semibold text-slate-500">{scheduleMessage}</p>}
          </div>

          {dashboard.sessions.length > 0 && (
            <div>
              <p className="text-xs font-extrabold text-slate-950">회기 기록</p>
              <div className="mt-1.5 divide-y divide-slate-100 rounded-[8px] border border-slate-200">
                {dashboard.sessions.map((session) => (
                  <div key={session.session_id} className="flex items-center justify-between gap-3 px-3 py-1.5">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-bold text-slate-800">
                        {session.session_number}회기 · {formatDate(session.session_date)}
                      </p>
                      {session.summary && <p className="truncate text-[11px] text-slate-500">{session.summary}</p>}
                    </div>
                    <span className="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-bold text-blue-700">
                      {TRANSCRIPT_STATUS_LABELS[session.transcript_status] || session.transcript_status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(dashboard.documents.length > 0 || dashboard.exports.length > 0) && (
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="text-xs font-extrabold text-slate-950">생성 문서</p>
                <div className="mt-1.5 space-y-1">
                  {dashboard.documents.length === 0 && <p className="text-[11px] text-slate-400">생성된 문서가 없습니다.</p>}
                  {dashboard.documents.slice(0, 5).map((doc) => (
                    <div key={doc.document_id} className="flex items-center gap-2 text-[11px] text-slate-600">
                      <FileText className="h-3 w-3 shrink-0 text-blue-600" />
                      <span className="truncate">{doc.title || DOCUMENT_TYPE_LABELS[doc.document_type] || doc.document_type}</span>
                      <span className="shrink-0 text-slate-400">{doc.status}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs font-extrabold text-slate-950">문서 변환 이력</p>
                <div className="mt-1.5 space-y-1">
                  {dashboard.exports.length === 0 && <p className="text-[11px] text-slate-400">변환 이력이 없습니다.</p>}
                  {dashboard.exports.slice(0, 5).map((exportItem) => (
                    <div key={exportItem.export_id} className="flex items-center gap-2 text-[11px] text-slate-600">
                      <span className="truncate">
                        {exportItem.title || DOCUMENT_TYPE_LABELS[exportItem.document_type] || exportItem.document_type} ·{' '}
                        {exportItem.format.toUpperCase()}
                      </span>
                      <span
                        className={`shrink-0 font-bold ${exportItem.status === 'failed' ? 'text-rose-600' : 'text-emerald-600'}`}
                      >
                        {exportItem.status === 'failed' ? '변환 오류' : '변환 완료'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
