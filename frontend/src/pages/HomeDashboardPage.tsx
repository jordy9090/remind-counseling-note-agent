import { AlertTriangle, CalendarDays, ChevronRight, FileText, Loader2, Plus, UserPlus, Users } from 'lucide-react'

import { displayNameFromEmail, useAuthSession } from '../lib/authSession'
import {
  buildScheduleRows,
  caseDisplayName,
  caseStatusKind,
  clientMetaLine,
  formatKoreanDate,
  isConfirmedStatus,
  relativeTime,
} from '../lib/caseList'
import type { CaseListItem, RecentDocumentItem } from '../types/session'
import { ClientAvatar, EmptyState, LinkAction, OutlineButton, PrimaryButton, ScheduleChip } from '../components/app-shell/ui'

/**
 * 홈 대시보드 (Figma). 데이터 축소: 상담 일정은 케이스별 "다음 상담 예정일" 기준, 시간 컬럼은 없음.
 */
export default function HomeDashboardPage({
  cases,
  recentDocuments,
  loading,
  error,
  onRetry,
  onNewSession,
  onAddClient,
  onOpenClient,
  onOpenDocument,
  onViewClients,
  onViewDocuments,
}: {
  cases: CaseListItem[]
  recentDocuments: RecentDocumentItem[]
  loading: boolean
  error: string | null
  onRetry: () => void
  onNewSession: () => void
  onAddClient: () => void
  onOpenClient: (caseId: string) => void
  onOpenDocument: (document: RecentDocumentItem) => void
  onViewClients: () => void
  onViewDocuments: () => void
}) {
  const { email } = useAuthSession()
  const schedule = buildScheduleRows(cases).slice(0, 5)
  const activeClients = cases.filter((item) => caseStatusKind(item.status) !== 'closed').slice(0, 6)
  const recent = recentDocuments.slice(0, 5)

  return (
    <section aria-label="대시보드" className="mx-auto w-full max-w-[1200px] px-4 py-6 md:px-8 md:py-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-extrabold leading-tight text-grey-900">안녕하세요, {displayNameFromEmail(email)}님!</h1>
          <p className="mt-1.5 text-sm text-grey-600">오늘도 따뜻한 상담으로 함께 하세요.</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <OutlineButton onClick={onNewSession} disabled={loading && cases.length === 0}><Plus className="h-4 w-4" />새 회기 기록</OutlineButton>
          <PrimaryButton onClick={onAddClient}><UserPlus className="h-4 w-4" />내담자 추가</PrimaryButton>
        </div>
      </div>

      {error && (
        <div role="alert" className="mt-5 flex flex-wrap items-center gap-2 rounded-[10px] border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <p className="min-w-0 flex-1">{error}</p>
          <button type="button" onClick={onRetry} className="font-bold underline">다시 시도</button>
        </div>
      )}

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="rm-card p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-bold text-grey-900"><CalendarDays className="h-5 w-5 text-grey-700" />나의 상담 일정</h2>
            <LinkAction onClick={onViewClients}>전체보기</LinkAction>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="rm-table w-full min-w-[420px]">
              <thead><tr><th>이름</th><th>날짜</th><th className="text-right">상태</th></tr></thead>
              <tbody>
                {schedule.map((row) => (
                  <tr key={row.case_id} className="cursor-pointer hover:bg-grey-100/60" onClick={() => onOpenClient(row.case_id)}>
                    <td className="font-semibold text-grey-800">{row.name}</td>
                    <td>{row.date.replace(/-/g, '.')}</td>
                    <td className="text-right"><ScheduleChip label={row.status.label} tone={row.status.tone} /></td>
                  </tr>
                ))}
                {!schedule.length && (
                  <tr><td colSpan={3} className="py-8 text-center text-sm text-grey-500">{loading ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : '등록된 상담 예정일이 없습니다. 내담자 페이지에서 일정을 추가해보세요.'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rm-card p-6">
          <div className="flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-lg font-bold text-grey-900"><FileText className="h-5 w-5 text-grey-700" />최근 작업한 문서</h2>
            <LinkAction onClick={onViewDocuments}>전체보기</LinkAction>
          </div>
          <div className="mt-3 overflow-x-auto">
            <table className="rm-table w-full min-w-[420px]">
              <thead><tr><th>이름</th><th>문서 제목</th><th className="text-right">최종 수정</th></tr></thead>
              <tbody>
                {recent.map((doc) => (
                  <tr key={doc.document_id} className="cursor-pointer hover:bg-grey-100/60" onClick={() => onOpenDocument(doc)}>
                    <td className="font-semibold text-grey-800">{doc.case_alias || doc.case_id}</td>
                    <td>
                      <span className="inline-flex items-center gap-2">
                        <DocumentIcon type={doc.document_type} confirmed={isConfirmedStatus(doc.status)} />
                        <span className="truncate">{doc.title} - {doc.case_alias || doc.case_id}</span>
                      </span>
                    </td>
                    <td className="whitespace-nowrap text-right text-grey-500">{relativeTime(doc.updated_at)}</td>
                  </tr>
                ))}
                {!recent.length && (
                  <tr><td colSpan={3} className="py-8 text-center text-sm text-grey-500">{loading ? <Loader2 className="mx-auto h-4 w-4 animate-spin" /> : '아직 생성된 문서가 없습니다.'}</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="rm-card mt-5 p-6">
        <div className="flex items-center justify-between gap-3">
          <h2 className="flex items-center gap-2 text-lg font-bold text-grey-900"><Users className="h-5 w-5 text-grey-700" />진행중인 내담자 목록</h2>
          <LinkAction onClick={onViewClients}>전체보기</LinkAction>
        </div>
        <div className="mt-4 space-y-3">
          {activeClients.map((item) => (
            <button
              key={item.case_id}
              type="button"
              onClick={() => onOpenClient(item.case_id)}
              className="flex w-full items-center gap-4 rounded-[12px] border border-grey-200 bg-white px-4 py-3.5 text-left transition hover:border-primary-100 hover:bg-primary-50/40"
            >
              <ClientAvatar size={40} />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-bold text-grey-900">{clientMetaLine(item)}</span>
                <span className="mt-0.5 block text-xs text-grey-500">최근 상담일: {formatKoreanDate(item.latest_consultation_date)}</span>
              </span>
              <ChevronRight className="h-5 w-5 shrink-0 text-grey-700" />
            </button>
          ))}
          {!activeClients.length && !loading && (
            <EmptyState
              title="진행중인 내담자가 없어요."
              description="내담자를 추가하고 첫 회기를 기록해보세요."
              action={<PrimaryButton onClick={onAddClient}><UserPlus className="h-4 w-4" />내담자 추가</PrimaryButton>}
            />
          )}
          {loading && !activeClients.length && <p className="py-6 text-center text-sm text-grey-500"><Loader2 className="mx-auto h-4 w-4 animate-spin" /></p>}
        </div>
      </section>
    </section>
  )
}

export function DocumentIcon({ type, confirmed }: { type: string; confirmed: boolean }) {
  const tone = type === 'supervision_report' ? 'bg-success-50 text-success-500' : type === 'termination_report' ? 'bg-danger-50 text-danger-500' : confirmed ? 'bg-primary-50 text-primary-400' : 'bg-primary-50 text-primary-400/70'
  return <span className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[6px] ${tone}`}><FileText className="h-4 w-4" /></span>
}

export { caseDisplayName }
