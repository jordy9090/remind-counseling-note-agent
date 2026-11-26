import { useEffect, useRef, useState } from 'react'
import { confirmAIReview, prepareAIReview, startAIReview, type AIReviewPreparation, type AIReviewPreview } from '../../api/client'
import { registerAIReview, type ReviewTask } from '../../lib/aiReview'
import { useAuthSession } from '../../lib/authSession'
import { detectLocalDeidItems, findDeidMatches, newDeidItemId, type DeidItem } from '../../lib/deidentificationReview'
import ModalShell from '../app-shell/ModalShell'
import DeidentificationReviewModal, { type DeidReviewResult } from './DeidentificationReviewModal'

export default function AIReviewHost() {
  const { userId } = useAuthSession()
  const [task, setTask] = useState<ReviewTask | null>(null)
  const active = useRef<ReviewTask | null>(null)
  const controller = useRef<AbortController | null>(null)
  const detectionRunning = useRef(false)
  const [preparation, setPreparation] = useState<AIReviewPreparation | null>(null)
  const [detectionApproved, setDetectionApproved] = useState(false)
  const [detecting, setDetecting] = useState(false)
  const [preview, setPreview] = useState<AIReviewPreview | null>(null)
  const [items, setItems] = useState<DeidItem[]>([])
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const owner = useRef(userId)
  owner.current = userId

  const cancel = () => {
    controller.current?.abort()
    active.current?.reject(new Error('AI 전달을 취소했습니다. 입력 내용은 유지됩니다.'))
    active.current = null
    setTask(null)
  }

  useEffect(() => registerAIReview(next => {
    if (active.current) return next.reject(new Error('진행 중인 내용 확인을 먼저 마쳐주세요.'))
    if (next.ownerId !== owner.current) return next.reject(new Error('로그인 상태가 변경되었습니다. 다시 시작해주세요.'))
    active.current = next
    setPreparation(null)
    setDetectionApproved(false)
    setPreview(null)
    setError('')
    setTask(next)
  }), [])

  useEffect(() => {
    if (active.current && active.current.ownerId !== userId) cancel()
  }, [userId])
  useEffect(() => () => {
    controller.current?.abort()
    active.current?.reject(new Error('검토 화면이 닫혔습니다. 다시 시작해주세요.'))
    active.current = null
  }, [])

  useEffect(() => {
    if (!task) return
    if (task.signal?.aborted) { cancel(); return }
    const requestController = new AbortController()
    controller.current = requestController
    const abort = () => { requestController.abort(); cancel() }
    task.signal?.addEventListener('abort', abort, { once: true })
    setPreview(null)
    setPreparation(null)
    setDetectionApproved(false)
    setDetecting(false)
    detectionRunning.current = false
    setError('')
    setSubmitting(false)
    void prepareAIReview(task, requestController.signal).then(value => {
      if (requestController.signal.aborted || active.current !== task) return
      setPreparation(value)
    }).catch(() => {
      if (!requestController.signal.aborted && active.current === task) setError('검토할 자료를 준비하지 못했어요. 로그인 상태를 확인한 뒤 다시 시도해주세요.')
    })
    return () => { requestController.abort(); task.signal?.removeEventListener('abort', abort) }
  }, [task, attempt])

  const approveDetection = async () => {
    const requestController = controller.current
    if (!task || !preparation || !detectionApproved || detectionRunning.current || !requestController
      || requestController.signal.aborted || active.current !== task || owner.current !== task.ownerId) return
    detectionRunning.current = true
    setDetecting(true)
    setError('')
    try {
      const value = await startAIReview({ ...task, payload: preparation.payload }, requestController.signal, preparation.preparation_token)
      if (requestController.signal.aborted || active.current !== task || owner.current !== task.ownerId) return
      const local = detectLocalDeidItems(value.sources.map(source => source.text))
      const known = new Set(local.map(item => item.original))
      for (const item of value.items) {
        const existing = local.find(candidate => candidate.original === item.original)
        if (existing) existing.replacement = item.replacement
        if (!known.has(item.original)) {
          known.add(item.original)
          local.push({ id: newDeidItemId(), original: item.original, replacement: item.replacement,
            origin: 'detected', kind: 'review', ...(item.category === 'name' ? { matchMode: 'name', nameIsIdentity: true } as const : {}) })
        }
      }
      setItems(local)
      setPreview(value)
    } catch {
      if (!requestController.signal.aborted && active.current === task) {
        setDetectionApproved(false)
        setError('자체 서버의 식별정보 탐지를 완료하지 못했어요. 입력은 유지됩니다. 내용을 다시 확인하고 승인해주세요.')
      }
    } finally {
      if (active.current === task) {
        detectionRunning.current = false
        setDetecting(false)
      }
    }
  }

  const confirm = async (review: DeidReviewResult) => {
    if (!task || !preparation || !preview || submitting || !review.fullItems
      || active.current !== task || owner.current !== task.ownerId || controller.current?.signal.aborted) return
    setSubmitting(true)
    setError('')
    const byId = new Map(review.fullItems.map(item => [item.id, item]))
    const edits = preview.sources.flatMap(source => findDeidMatches(source.text, review.fullItems!).map(match => ({
      path: source.key,
      // Python indexes Unicode code points; JS string offsets count UTF-16 units.
      start: Array.from(source.text.slice(0, match.start)).length,
      end: Array.from(source.text.slice(0, match.end)).length,
      original: source.text.slice(match.start, match.end), replacement: `[${byId.get(match.itemId)!.replacement}]`,
    })))
    try {
      const value = await confirmAIReview({ ...task, payload: preparation.payload, signal: controller.current?.signal }, preview, edits)
      if (active.current !== task || owner.current !== task.ownerId || task.signal?.aborted) return
      active.current = null
      setTask(null)
      task.resolve(value)
    } catch {
      if (active.current === task) setError('확인을 완료하지 못했어요. 입력은 유지됩니다. 다시 확인하거나 취소 후 재시도해주세요.')
    } finally {
      setSubmitting(false)
    }
  }

  if (!task) return null
  if (!preparation) return <div className="relative z-[70]"><ModalShell ariaLabel="탐지할 자료 준비" title="개인정보 확인" onClose={cancel}>
    <p role={error ? 'alert' : 'status'}>{error || '원문을 불러오는 중…'}</p>
    {error && <button type="button" className="mt-4 text-primary-500" onClick={() => setAttempt(value => value + 1)}>다시 시도</button>}
  </ModalShell></div>
  if (!preview) return <div className="relative z-[70]"><ModalShell ariaLabel="식별정보 탐지 승인" title="개인정보 확인" onClose={cancel}
    footer={detecting ? <p role="status" className="text-sm text-grey-600">개인정보를 찾고 있어요…</p> : <div className="w-full space-y-4">
      <label className="flex cursor-pointer items-start gap-2 text-sm text-grey-800"><input type="checkbox" checked={detectionApproved}
        className="mt-0.5 h-4 w-4 shrink-0 accent-primary-400"
        onChange={event => setDetectionApproved(event.target.checked)} />이 원문을 Re:mind 자체 서버에서 분석하는 데 동의합니다.</label>
      <button type="button" disabled={!detectionApproved || detecting} onClick={() => void approveDetection()}
        className="h-11 w-full rounded-xl bg-primary-400 text-sm font-bold text-white hover:bg-primary-500 disabled:opacity-40">개인정보 찾기</button>
    </div>}>
    <div className="space-y-3">{preparation.sources.map(source => <section key={source.key}>
      {preparation.sources.length > 1 && <h3 className="mb-1.5 text-sm font-semibold">{source.label}</h3>}
      <p className="rm-scroll max-h-[35vh] overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-grey-50 px-4 py-3 text-sm leading-7 text-grey-800">{source.text}</p>
    </section>)}</div>
    {error && <p role="alert" className="mt-4 text-sm text-danger-500">{error}</p>}
  </ModalShell></div>
  return <div className="relative z-[70]"><DeidentificationReviewModal sources={preview.sources} context={{}} initialItems={items}
    requireConfirmation onBack={cancel} onConfirm={value => void confirm(value)}
    submitting={submitting} error={error} submitLabel={task.purpose === 'memory' ? '저장하기' : task.purpose === 'quick' || task.purpose === 'generate' ? '요약하기' : 'AI로 보내기'} /></div>
}
