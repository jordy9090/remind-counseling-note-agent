import { useEffect, useRef, useState } from 'react'
import { Check, History, Loader2 } from 'lucide-react'

import { listTemporaryDrafts, saveTemporaryDraft } from '../../api/client'
import { temporaryDraftPayload } from '../../lib/temporaryDraft'
import {
  isQuickSummaryDraft,
  quickSummaryDraftPayload,
  quickSummaryFromDraft,
  quickSummaryRecordTitle,
  relativeTimeLabel,
  takePendingQuickSummary,
  type QuickSummaryResult,
} from '../../lib/quickSummary'
import type { NoteDraftResponse, TemporaryDraftRecord } from '../../types/session'
import QuickSummaryPanel from './QuickSummaryPanel'

const RECENT_LIMIT = 3

type SaveState = 'saving' | 'saved' | 'failed' | null

/**
 * Signed-in "간편 요약하기" screen. Every new summary is saved automatically (AI output only) and
 * listed under the input as 이전 요약한 기록. 내담자에 저장하기 saves it as a client's next session
 * (a regular session record). A summary a guest sent here with 로그인 후 저장하기 is auto-saved the
 * same way right after login, and the client picker opens for it.
 */
export default function QuickSummaryWorkspace({
  result,
  onResult,
  toResult,
  onSaveToClient,
  saveError,
}: {
  result: QuickSummaryResult | null
  toResult: (note: NoteDraftResponse) => QuickSummaryResult
  onResult: (result: QuickSummaryResult | null) => void
  /** Opens the client picker for this summary. */
  onSaveToClient: (result: QuickSummaryResult) => void
  saveError?: string | null
}) {
  const [records, setRecords] = useState<TemporaryDraftRecord[]>([])
  const [loaded, setLoaded] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [saveState, setSaveState] = useState<SaveState>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // Ignores a save that finishes after the counselor already moved on to another summary.
  const saveRun = useRef(0)

  useEffect(() => {
    let cancelled = false
    listTemporaryDrafts()
      .then((drafts) => {
        if (cancelled) return
        setRecords(drafts
          .filter(isQuickSummaryDraft)
          .sort((a, b) => b.saved_at.localeCompare(a.saved_at))
          .slice(0, RECENT_LIMIT))
      })
      .catch(() => { if (!cancelled) setRecords([]) })
      .finally(() => { if (!cancelled) setLoaded(true) })
    return () => { cancelled = true }
  }, [refreshKey])

  const handleResult = (next: QuickSummaryResult | null) => {
    onResult(next)
    const run = ++saveRun.current
    setSaveState(next ? 'saving' : null)
    if (!next) return
    saveTemporaryDraft(temporaryDraftPayload(quickSummaryDraftPayload(next)))
      .then(() => {
        if (run !== saveRun.current) return
        setSaveState('saved')
        setRefreshKey((value) => value + 1)
      })
      .catch(() => { if (run === saveRun.current) setSaveState('failed') })
  }

  useEffect(() => {
    // Taking the summary also removes it, so it is saved once even if this effect runs twice.
    const pending = takePendingQuickSummary()
    if (!pending) return
    setNotice('로그인 전에 만든 요약이에요. 저장할 내담자를 선택하면 그 내담자의 다음 회기로 저장돼요.')
    handleResult(pending)
    onSaveToClient(pending)
  // Runs once after login; handleResult only uses refs and state setters.
  }, [])

  const openRecord = (draft: TemporaryDraftRecord) => {
    const summary = quickSummaryFromDraft(draft)
    if (!summary) return
    saveRun.current += 1
    setSaveState('saved')
    setNotice(null)
    onResult(summary)
  }

  const resultStatus = saveState === 'saving'
    ? <span role="status" className="inline-flex items-center gap-1 text-xs text-grey-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />저장 중</span>
    : saveState === 'saved'
      ? <span role="status" className="inline-flex items-center gap-1 text-xs text-grey-500"><Check className="h-3.5 w-3.5 text-success-500" />이전 요약한 기록에 저장됨</span>
      : saveState === 'failed'
        ? <span role="alert" className="text-xs text-danger-500">저장하지 못했어요. 복사해서 보관해주세요.</span>
        : null

  const history = loaded && records.length > 0 && !result ? (
    <section aria-label="이전 요약한 기록" className="rounded-2xl bg-[#dfe6f6] p-4">
      <h2 className="flex items-center gap-1.5 text-sm font-bold text-grey-800"><History className="h-4 w-4" />이전 요약한 기록</h2>
      <ul className="mt-2 divide-y divide-[#c7d2ea]">
        {records.map((draft) => {
          const summary = quickSummaryFromDraft(draft)
          return (
            <li key={draft.draft_id}>
              <button
                type="button"
                onClick={() => openRecord(draft)}
                disabled={!summary}
                className="flex w-full items-center gap-4 rounded-md px-1 py-2.5 text-left text-sm hover:bg-white/50 disabled:cursor-default disabled:hover:bg-transparent"
              >
                <span className="w-14 shrink-0 text-xs text-grey-500">{relativeTimeLabel(draft.saved_at)}</span>
                <span className="min-w-0 flex-1 truncate text-grey-800">{quickSummaryRecordTitle(draft.saved_at, summary)}</span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  ) : null

  return (
    <div className="quick-summary-bg flex min-h-screen flex-col justify-center">
      <QuickSummaryPanel
        result={result}
        toResult={toResult}
        onResult={(next) => {
          setNotice(null)
          handleResult(next)
        }}
        canExtractDocuments
        notice={saveError
          ? <p role="alert" className="rounded-lg bg-danger-50 px-4 py-3 text-center text-sm text-danger-500">{saveError}</p>
          : notice ? <p role="status" className="rounded-lg bg-primary-50 px-4 py-3 text-center text-sm text-primary-900">{notice}</p> : undefined}
        saveAction={{ label: '내담자에 저장하기', onSave: onSaveToClient }}
        privacyNote="입력한 내용은 저장되지 않고, AI 요약 결과만 이전 요약한 기록에 자동 저장돼요. 이름·연락처 등 개인정보로 보이는 내용은 가린 뒤 AI에 보내요."
        resultStatus={resultStatus}
        below={history}
      />
    </div>
  )
}
