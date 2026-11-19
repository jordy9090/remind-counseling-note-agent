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
  if (!preparation) return <div className="relative z-[70]"><ModalShell ariaLabel="탐지할 자료 준비" title="검토할 자료를 준비하고 있어요" onClose={cancel}>
    <p role={error ? 'alert' : 'status'}>{error || '현재 입력과 함께 처리할 이전 회기 자료를 준비합니다.'}</p>
    {error && <button type="button" className="mt-4 text-primary-500" onClick={() => setAttempt(value => value + 1)}>다시 시도</button>}
    <button type="button" className="ml-4 mt-4" onClick={cancel}>취소하고 입력으로 돌아가기</button>
  </ModalShell></div>
  if (!preview) return <div className="relative z-[70]"><ModalShell ariaLabel="식별정보 탐지 승인" title="탐지 서버에 전달할 원문을 확인해주세요" onClose={cancel}>
    <p className="mb-4 text-sm text-grey-700">아래 자료를 설정된 서버의 AI 식별정보 탐지 모델에 전달합니다. 탐지가 끝나면 가명 처리할 내용과 요약에 사용할 자료를 다시 확인합니다.</p>
    <div className="space-y-4">{preparation.sources.map(source => <section key={source.key}>
      <h3 className="mb-1 text-sm font-bold">{source.label}</h3>
      <p className="whitespace-pre-wrap break-words rounded border border-grey-200 bg-grey-50 p-3 text-sm">{source.text}</p>
    </section>)}</div>
    {error && <p role="alert" className="mt-4 text-sm text-danger-500">{error}</p>}
    {detecting ? <p role="status" className="mt-4 text-sm">자체 서버에서 식별정보를 찾고 있어요. 분량에 따라 시간이 걸릴 수 있습니다.</p>
      : <label className="mt-4 flex items-start gap-2 text-sm"><input type="checkbox" checked={detectionApproved}
        onChange={event => setDetectionApproved(event.target.checked)} />표시된 원문을 확인했으며 설정된 서버의 식별정보 탐지에 사용하도록 승인합니다.</label>}
    <div className="mt-4 flex flex-wrap gap-3">
      <button type="button" disabled={!detectionApproved || detecting} onClick={() => void approveDetection()}
        className="rounded bg-primary-500 px-4 py-2 text-sm font-bold text-white disabled:opacity-40">원문 식별정보 탐지 승인</button>
      <button type="button" onClick={cancel}>취소하고 입력으로 돌아가기</button>
    </div>
  </ModalShell></div>
  return <div className="relative z-[70]"><DeidentificationReviewModal sources={preview.sources} context={{}} initialItems={items}
    requireConfirmation onBack={cancel} onConfirm={value => void confirm(value)}
    submitting={submitting} error={error} submitLabel={task.purpose === 'memory' ? '확인한 내용으로 저장하기' : '확인한 내용으로 AI 처리하기'} /></div>
}
