import { useEffect, useState } from 'react'
import { History } from 'lucide-react'

import { listTemporaryDrafts } from '../../api/client'
import { caseDisplayName } from '../../lib/caseList'
import { QUICK_SUMMARY_TOPIC, quickSummaryRecordTitle, relativeTimeLabel, type QuickSummaryResult } from '../../lib/quickSummary'
import type { CaseListItem, TemporaryDraftRecord } from '../../types/session'
import QuickSummaryPanel from './QuickSummaryPanel'

const RECENT_LIMIT = 3

/** Signed-in "간편 요약하기" screen: the quick summary plus the counselor's previously saved quick summaries. */
export default function QuickSummaryWorkspace({
  result,
  onResult,
  onSave,
  saving,
  notice,
  cases,
  refreshKey,
  onOpenRecord,
}: {
  result: QuickSummaryResult | null
  onResult: (result: QuickSummaryResult | null) => void
  onSave: (result: QuickSummaryResult) => void
  saving: boolean
  notice?: string | null
  cases: CaseListItem[]
  refreshKey: number
  onOpenRecord: (draftId: string, caseId: string) => void
}) {
  const [records, setRecords] = useState<TemporaryDraftRecord[]>([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    let cancelled = false
    listTemporaryDrafts()
      .then((drafts) => {
        if (cancelled) return
        setRecords(drafts
          .filter((draft) => draft.session_topic === QUICK_SUMMARY_TOPIC)
          .sort((a, b) => b.saved_at.localeCompare(a.saved_at))
          .slice(0, RECENT_LIMIT))
      })
      .catch(() => { if (!cancelled) setRecords([]) })
      .finally(() => { if (!cancelled) setLoaded(true) })
    return () => { cancelled = true }
  }, [refreshKey])

  const clientName = (draft: TemporaryDraftRecord) => {
    const item = cases.find((entry) => entry.case_id === draft.case_id)
    return item ? caseDisplayName(item) : draft.form?.client_alias || draft.case_id
  }

  const history = loaded && records.length > 0 && !result ? (
    <section aria-label="이전 요약한 기록" className="rounded-2xl bg-[#dfe6f6] p-4">
      <h2 className="flex items-center gap-1.5 text-sm font-bold text-grey-800"><History className="h-4 w-4" />이전 요약한 기록</h2>
      <ul className="mt-2 divide-y divide-[#c7d2ea]">
        {records.map((draft) => (
          <li key={draft.draft_id}>
            <button
              type="button"
              onClick={() => onOpenRecord(draft.draft_id, draft.case_id)}
              className="flex w-full items-center gap-4 rounded-md px-1 py-2.5 text-left text-sm hover:bg-white/50"
            >
              <span className="w-14 shrink-0 text-xs text-grey-500">{relativeTimeLabel(draft.saved_at)}</span>
              <span className="min-w-0 flex-1 truncate text-grey-800">
                {quickSummaryRecordTitle(draft.saved_at, clientName(draft))} · {draft.session_number}회기
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  ) : null

  return (
    <div className="quick-summary-bg flex min-h-screen flex-col justify-center">
      <QuickSummaryPanel
        result={result}
        onResult={onResult}
        onSave={onSave}
        saving={saving}
        canExtractDocuments
        notice={notice ? <p role="status" className="rounded-lg bg-primary-50 px-4 py-3 text-center text-sm text-primary-900">{notice}</p> : undefined}
        below={history}
      />
    </div>
  )
}
