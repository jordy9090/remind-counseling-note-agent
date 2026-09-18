import { useEffect, useState } from 'react'
import { AlertTriangle, ChevronRight, LayoutGrid, List, Loader2, Search, UserPlus } from 'lucide-react'

import {
  AGE_BAND_OPTIONS,
  GENDER_OPTIONS,
  caseStatusKind,
  caseStatusLabel,
  clientMetaLine,
  filterClients,
  formatKoreanDate,
  paginate,
  type AgeBand,
  type CaseStatusFilter,
  type ClientFilter,
} from '../lib/caseList'
import type { CaseListItem } from '../types/session'
import { ClientAvatar, EmptyState, Pagination, PrimaryButton, SelectField, StatusChip } from '../components/app-shell/ui'

const STATUS_OPTIONS: { id: CaseStatusFilter; label: string }[] = [
  { id: 'all', label: '케이스 유형' },
  { id: 'active', label: '진행중' },
  { id: 'closed', label: '종결' },
]
const PAGE_SIZE = 10

/** 내담자 리스트 (Figma): 검색, 리스트/그리드 토글, 성별·나이·케이스 유형 필터, 페이지네이션. */
export default function ClientListPage({
  cases,
  loading,
  error,
  filter,
  onChangeFilter,
  onRetry,
  onAddClient,
  onOpenClient,
}: {
  cases: CaseListItem[]
  loading: boolean
  error: string | null
  filter: ClientFilter
  onChangeFilter: (filter: ClientFilter) => void
  onRetry: () => void
  onAddClient: () => void
  onOpenClient: (caseId: string) => void
}) {
  const [view, setView] = useState<'list' | 'grid'>('list')
  const [page, setPage] = useState(1)
  const filtered = filterClients(cases, filter)
  const paged = paginate(filtered, page, PAGE_SIZE)
  useEffect(() => setPage(1), [filter.search, filter.status, filter.gender, filter.age])
  const isFiltered = filter.status !== 'all' || filter.gender !== 'all' || filter.age !== 'all' || filter.search.trim().length > 0

  return (
    <section aria-label="내담자 리스트" className="mx-auto w-full max-w-[1240px] px-4 py-6 md:px-6 md:py-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-extrabold text-grey-900">내담자 리스트</h1>
        <PrimaryButton onClick={onAddClient}><UserPlus className="h-4 w-4" />내담자 추가</PrimaryButton>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <label className="flex h-11 min-w-[220px] flex-1 items-center gap-2 rounded-[10px] border border-grey-200 bg-white px-3.5 text-sm text-grey-500">
          <Search className="h-4 w-4 shrink-0" />
          <input
            className="min-w-0 flex-1 bg-transparent text-grey-900 outline-none placeholder:text-grey-400"
            placeholder="검색"
            aria-label="내담자/케이스 검색"
            value={filter.search}
            onChange={(event) => onChangeFilter({ ...filter, search: event.target.value })}
          />
        </label>
        <div className="inline-flex h-11 items-center rounded-[10px] border border-grey-200 bg-white p-1" role="group" aria-label="보기 방식">
          <button type="button" aria-pressed={view === 'grid'} aria-label="그리드 보기" onClick={() => setView('grid')} className={`inline-flex h-8 w-9 items-center justify-center rounded-[7px] ${view === 'grid' ? 'bg-grey-100 text-grey-900' : 'text-grey-500'}`}><LayoutGrid className="h-4 w-4" /></button>
          <button type="button" aria-pressed={view === 'list'} aria-label="리스트 보기" onClick={() => setView('list')} className={`inline-flex h-8 w-9 items-center justify-center rounded-[7px] ${view === 'list' ? 'bg-grey-100 text-grey-900' : 'text-grey-500'}`}><List className="h-4 w-4" /></button>
        </div>
        <SelectField ariaLabel="성별 필터" value={filter.gender} onChange={(gender) => onChangeFilter({ ...filter, gender })} options={GENDER_OPTIONS} className="w-[96px]" />
        <SelectField ariaLabel="나이 필터" value={filter.age} onChange={(age) => onChangeFilter({ ...filter, age: age as AgeBand })} options={AGE_BAND_OPTIONS} className="w-[112px]" />
        <SelectField ariaLabel="케이스 유형 필터" value={filter.status} onChange={(status) => onChangeFilter({ ...filter, status: status as CaseStatusFilter })} options={STATUS_OPTIONS} className="w-[136px]" />
      </div>

      {error && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-2 rounded-[10px] border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <p className="min-w-0 flex-1">{error}</p>
          <button type="button" onClick={onRetry} className="font-bold underline">다시 시도</button>
        </div>
      )}

      {loading && !cases.length ? (
        <p role="status" className="mt-10 flex items-center justify-center gap-2 text-sm text-grey-500"><Loader2 className="h-4 w-4 animate-spin" />내담자 목록을 불러오는 중입니다…</p>
      ) : paged.items.length === 0 && !error ? (
        <div className="rm-card mt-4">
          <EmptyState
            title={isFiltered ? '조건에 맞는 내담자가 없어요.' : '아직 등록된 내담자가 없어요.'}
            description={isFiltered ? '필터나 검색어를 바꿔보세요.' : '내담자를 추가하고 첫 회기를 기록해보세요.'}
            action={!isFiltered ? <PrimaryButton onClick={onAddClient}><UserPlus className="h-4 w-4" />내담자 추가</PrimaryButton> : undefined}
          />
        </div>
      ) : view === 'list' ? (
        <ul className="mt-4 space-y-3">
          {paged.items.map((item) => (
            <li key={item.case_id}>
              <ClientRow item={item} onOpen={() => onOpenClient(item.case_id)} />
            </li>
          ))}
        </ul>
      ) : (
        <ul className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {paged.items.map((item) => (
            <li key={item.case_id}>
              <ClientCard item={item} onOpen={() => onOpenClient(item.case_id)} />
            </li>
          ))}
        </ul>
      )}

      {filtered.length > 0 && (
        <div className="mt-8">
          <Pagination page={paged.page} pageCount={paged.pageCount} onChange={setPage} />
        </div>
      )}
    </section>
  )
}

export function ClientRow({ item, onOpen, selected = false, compact = false }: { item: CaseListItem; onOpen: () => void; selected?: boolean; compact?: boolean }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-pressed={selected}
      aria-label={`${clientMetaLine(item)} 열기`}
      className={`flex w-full items-center gap-4 rounded-[12px] border bg-white text-left transition ${compact ? 'px-4 py-3' : 'px-4 py-4'} ${
        selected ? 'border-primary-400 bg-primary-50/60 ring-1 ring-primary-400' : 'border-grey-200 hover:border-primary-100 hover:bg-primary-50/40'
      }`}
    >
      <ClientAvatar size={compact ? 40 : 44} />
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[15px] font-bold text-grey-900">{clientMetaLine(item)}</span>
          {!compact && <StatusChip kind={caseStatusKind(item.status)} label={caseStatusLabel(item.status)} />}
        </span>
        <span className="mt-0.5 block text-xs text-grey-500">최근 상담일: {formatKoreanDate(item.latest_consultation_date)}</span>
      </span>
      {!compact && <ChevronRight className="h-5 w-5 shrink-0 text-grey-700" />}
    </button>
  )
}

function ClientCard({ item, onOpen }: { item: CaseListItem; onOpen: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={`${clientMetaLine(item)} 열기`}
      className="flex h-full w-full flex-col gap-3 rounded-[12px] border border-grey-200 bg-white p-4 text-left transition hover:border-primary-100 hover:bg-primary-50/40"
    >
      <span className="flex items-center gap-3">
        <ClientAvatar size={44} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[15px] font-bold text-grey-900">{clientMetaLine(item)}</span>
          <span className="mt-0.5 block text-xs text-grey-500">케이스 ID: {item.case_id}</span>
        </span>
        <StatusChip kind={caseStatusKind(item.status)} label={caseStatusLabel(item.status)} />
      </span>
      <span className="grid grid-cols-2 gap-2 text-xs text-grey-500">
        <span>회기 <b className="text-grey-900">{item.total_session_count}회</b></span>
        <span>문서 <b className="text-grey-900">{item.document_count}</b></span>
        <span className="col-span-2">최근 상담일: {formatKoreanDate(item.latest_consultation_date)}</span>
      </span>
    </button>
  )
}
