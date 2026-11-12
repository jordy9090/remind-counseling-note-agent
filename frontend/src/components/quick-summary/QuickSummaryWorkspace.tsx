import { useEffect, useRef, useState } from 'react'
import { Check, History, Loader2 } from 'lucide-react'

import { isRetryableRequestError, listTemporaryDrafts, persistenceErrorMessage, saveTemporaryDraft } from '../../api/client'
import { useAuthSession } from '../../lib/authSession'
import { useUnsavedWork } from '../../lib/unsavedWork'
import { createSummarySaveJob, saveSummaryWithRetry, type SummarySaveJob } from '../../lib/quickSummarySave'
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
 * Signed-in "간편 요약하기" screen. Summaries and de-identified supporting excerpts are saved and
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
  const { userId } = useAuthSession()
  const ownerRef = useRef(userId)
  ownerRef.current = userId
  const mounted = useRef(true)
  const saveJob = useRef<SummarySaveJob | null>(null)
  const [saveFailure, setSaveFailure] = useState('')
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [records, setRecords] = useState<TemporaryDraftRecord[]>([])
  const [loaded, setLoaded] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)
  const [saveState, setSaveState] = useState<SaveState>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const hasUnsavedResult = saveState === 'saving' || saveState === 'failed'
  useUnsavedWork(hasUnsavedResult)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      // StrictMode immediately reattaches this instance; real unmounts still cancel its requests.
      queueMicrotask(() => { if (!mounted.current) saveJob.current?.controller.abort() })
    }
  }, [])

  useEffect(() => {
    if (saveJob.current && saveJob.current.ownerId !== userId) {
      saveJob.current.controller.abort()
      saveJob.current = null
      setSaveState(null)
    }
    const controller = new AbortController()
    setHistoryError(null)
    setLoaded(false)
    listTemporaryDrafts(undefined, { ownerId: userId, signal: controller.signal })
      .then((drafts) => {
        if (controller.signal.aborted || ownerRef.current !== userId) return
        setRecords(drafts
          .filter(isQuickSummaryDraft)
          .sort((a, b) => b.saved_at.localeCompare(a.saved_at))
          .slice(0, RECENT_LIMIT))
      })
      .catch(() => {
        if (!controller.signal.aborted && ownerRef.current === userId) {
          setHistoryError('이전 요약 기록을 불러오지 못했어요. 다시 시도해주세요.')
        }
      })
      .finally(() => { if (!controller.signal.aborted && ownerRef.current === userId) setLoaded(true) })
    return () => { controller.abort() }
  }, [refreshKey, userId])

  const attemptSave = async (job: SummarySaveJob) => {
    if (job.running || job.controller.signal.aborted || ownerRef.current !== job.ownerId) return
    setSaveState('saving')
    setSaveFailure('')
    const isCurrent = () => mounted.current && saveJob.current === job
      && !job.controller.signal.aborted && ownerRef.current === job.ownerId
    try {
      const saved = await saveSummaryWithRetry(job, saveTemporaryDraft, isRetryableRequestError)
      if (!saved || !isCurrent()) return
      setSaveState('saved')
      setRefreshKey((value) => value + 1)
    } catch (error) {
      if (!isCurrent()) return
      setSaveFailure(persistenceErrorMessage(error))
      setSaveState('failed')
    }
  }

  const handleResult = (next: QuickSummaryResult | null) => {
    saveJob.current?.controller.abort()
    saveJob.current = null
    onResult(next)
    setSaveState(null)
    setSaveFailure('')
    if (!next || !userId) return
    const job = createSummarySaveJob(temporaryDraftPayload(quickSummaryDraftPayload(next)), userId)
    saveJob.current = job
    void attemptSave(job)
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
    saveJob.current?.controller.abort()
    saveJob.current = null
    setSaveState('saved')
    setNotice(null)
    onResult(summary)
  }

  const resultStatus = saveState === 'saving'
    ? <span role="status" className="inline-flex items-center gap-1 text-xs text-grey-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />저장 중</span>
    : saveState === 'saved'
      ? <span role="status" className="inline-flex items-center gap-1 text-xs text-grey-500"><Check className="h-3.5 w-3.5 text-success-500" />이전 요약한 기록에 저장됨</span>
      : saveState === 'failed'
        ? <div className="flex flex-wrap items-center gap-2">
          <span role="alert" className="text-xs text-danger-500">{saveFailure || '저장하지 못했어요. 현재 요약은 유지됩니다.'}</span>
          <button type="button" onClick={() => { if (saveJob.current) void attemptSave(saveJob.current) }}
            className="rounded border border-primary-400 px-3 py-2 text-xs font-bold text-primary-400">다시 저장</button>
        </div>
        : null

  const history = loaded && (historyError || records.length > 0) && !result ? (
    <section aria-label="이전 요약한 기록" className="rounded-2xl bg-[#dfe6f6] p-4">
      <h2 className="flex items-center gap-1.5 text-sm font-bold text-grey-800"><History className="h-4 w-4" />이전 요약한 기록</h2>
      {historyError && <div className="mt-2 space-y-2">
        <p role="alert" className="text-sm text-danger-500">{historyError}</p>
        <button type="button" onClick={() => setRefreshKey(value => value + 1)}
          className="rounded border border-primary-400 px-3 py-2 text-sm font-bold text-primary-400">기록 다시 불러오기</button>
      </div>}
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
        hasUnsavedResult={hasUnsavedResult}
        notice={saveError
          ? <p role="alert" className="rounded-lg bg-danger-50 px-4 py-3 text-center text-sm text-danger-500">{saveError}</p>
          : notice ? <p role="status" className="rounded-lg bg-primary-50 px-4 py-3 text-center text-sm text-primary-900">{notice}</p> : undefined}
        saveAction={{ label: '내담자에 저장하기', onSave: onSaveToClient }}
        privacyNote="입력 전문은 저장하지 않고, 요약과 개인정보를 가린 연결 원문 일부를 이전 요약한 기록에 자동 저장해요. 이름·연락처 등 개인정보로 보이는 내용은 가린 뒤 AI에 보내요."
        resultStatus={resultStatus}
        below={history}
      />
    </div>
  )
}
