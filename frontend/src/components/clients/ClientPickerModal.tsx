import { useEffect, useState } from 'react'
import { Search, UserPlus } from 'lucide-react'

import ModalShell from '../app-shell/ModalShell'
import { Pagination, PrimaryButton, SelectField } from '../app-shell/ui'
import { ClientRow } from '../../pages/ClientListPage'
import { AGE_BAND_OPTIONS, DEFAULT_CLIENT_FILTER, GENDER_OPTIONS, filterClients, paginate, type AgeBand, type ClientFilter } from '../../lib/caseList'
import type { CaseListItem } from '../../types/session'

const PAGE_SIZE = 5

/** 새 회기 기록 1단계: 내담자 선택 (Figma "내담자를 선택해주세요"). */
export default function ClientPickerModal({
  cases,
  onClose,
  onNext,
  onAddClient,
}: {
  cases: CaseListItem[]
  onClose: () => void
  onNext: (caseId: string) => void
  onAddClient: () => void
}) {
  const [filter, setFilter] = useState<ClientFilter>(DEFAULT_CLIENT_FILTER)
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const filtered = filterClients(cases, filter)
  const paged = paginate(filtered, page, PAGE_SIZE)
  useEffect(() => setPage(1), [filter.search, filter.gender, filter.age])

  return (
    <ModalShell
      ariaLabel="내담자 선택"
      title="내담자를 선택해주세요"
      description="회기를 기록할 내담자를 선택해주세요."
      onClose={onClose}
      width={740}
      footer={
        <PrimaryButton className="w-full" disabled={!selected} onClick={() => selected && onNext(selected)}>다음으로</PrimaryButton>
      }
    >
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap items-center gap-2.5">
          <label className="flex h-11 min-w-[200px] flex-1 items-center gap-2 rounded-[10px] border border-grey-200 bg-white px-3.5 text-sm text-grey-500">
            <Search className="h-4 w-4 shrink-0" />
            <input
              className="min-w-0 flex-1 bg-transparent text-grey-900 outline-none placeholder:text-grey-400"
              placeholder="내담자 이름을 검색해주세요"
              aria-label="내담자 이름 검색"
              value={filter.search}
              onChange={(event) => setFilter({ ...filter, search: event.target.value })}
            />
          </label>
          <SelectField ariaLabel="성별 필터" value={filter.gender} onChange={(gender) => setFilter({ ...filter, gender })} options={GENDER_OPTIONS} className="w-[132px]" />
          <SelectField ariaLabel="나이 필터" value={filter.age} onChange={(age) => setFilter({ ...filter, age: age as AgeBand })} options={AGE_BAND_OPTIONS} className="w-[132px]" />
        </div>

        {paged.items.length === 0 ? (
          <div className="rounded-[12px] border border-dashed border-grey-200 px-6 py-10 text-center">
            <p className="text-sm font-semibold text-grey-700">{cases.length ? '조건에 맞는 내담자가 없어요.' : '아직 등록된 내담자가 없어요.'}</p>
            <button type="button" onClick={onAddClient} className="mt-3 inline-flex items-center gap-1.5 text-sm font-bold text-primary-400 hover:underline"><UserPlus className="h-4 w-4" />새 내담자 만들기</button>
          </div>
        ) : (
          <ul className="space-y-3">
            {paged.items.map((item) => (
              <li key={item.case_id}>
                <ClientRow item={item} compact selected={selected === item.case_id} onOpen={() => setSelected(item.case_id)} />
              </li>
            ))}
          </ul>
        )}

        {filtered.length > 0 && (
          <Pagination page={paged.page} pageCount={paged.pageCount} onChange={setPage} unit={`· ${filtered.length}명`} />
        )}
      </div>
    </ModalShell>
  )
}
