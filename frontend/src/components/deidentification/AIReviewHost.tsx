import { useEffect, useRef, useState } from 'react'
import { confirmAIReview, startAIReview, type AIReviewPreview } from '../../api/client'
import { registerAIReview, type ReviewTask } from '../../lib/aiReview'
import { useAuthSession } from '../../lib/authSession'
import { detectLocalDeidItems, findDeidMatches, newDeidItemId, type DeidItem } from '../../lib/deidentificationReview'
import ModalShell from '../app-shell/ModalShell'
import DeidentificationReviewModal, { type DeidReviewResult } from './DeidentificationReviewModal'

export default function AIReviewHost() {
  const { userId } = useAuthSession()
  const [task, setTask] = useState<ReviewTask | null>(null)
  const active = useRef<ReviewTask | null>(null)
  const [preview, setPreview] = useState<AIReviewPreview | null>(null)
  const [items, setItems] = useState<DeidItem[]>([])
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [submitting, setSubmitting] = useState(false)
  const owner = useRef(userId)
  owner.current = userId

  const cancel = () => {
    active.current?.reject(new Error('AI 전달을 취소했습니다. 입력 내용은 유지됩니다.'))
    active.current = null
    setTask(null)
  }

  useEffect(() => registerAIReview(next => {
    if (active.current) return next.reject(new Error('진행 중인 내용 확인을 먼저 마쳐주세요.'))
    if (next.ownerId !== owner.current) return next.reject(new Error('로그인 상태가 변경되었습니다. 다시 시작해주세요.'))
    active.current = next
    setPreview(null)
    setError('')
    setTask(next)
  }), [])

  useEffect(() => {
    if (active.current && active.current.ownerId !== userId) cancel()
  }, [userId])
  useEffect(() => () => {
    active.current?.reject(new Error('검토 화면이 닫혔습니다. 다시 시작해주세요.'))
    active.current = null
  }, [])

  useEffect(() => {
    if (!task) return
    if (task.signal?.aborted) { cancel(); return }
    const controller = new AbortController()
    const abort = () => { controller.abort(); cancel() }
    task.signal?.addEventListener('abort', abort, { once: true })
    setPreview(null)
    setError('')
    setSubmitting(false)
    void startAIReview(task, controller.signal).then(value => {
      if (controller.signal.aborted || active.current !== task) return
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
    }).catch(() => {
      if (!controller.signal.aborted && active.current === task) setError('자체 서버의 식별정보 탐지를 완료하지 못했어요. 입력은 유지됩니다. 잠시 후 다시 시도해주세요.')
    })
    return () => { controller.abort(); task.signal?.removeEventListener('abort', abort) }
  }, [task, attempt])

  const confirm = async (review: DeidReviewResult) => {
    if (!task || !preview || submitting || !review.fullItems) return
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
      const value = await confirmAIReview(task, preview, edits)
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
  if (!preview) return <div className="relative z-[70]"><ModalShell ariaLabel="식별정보 탐지" title="자체 서버에서 식별정보를 찾고 있어요" onClose={cancel}>
    <p role={error ? 'alert' : 'status'}>{error || '분량에 따라 시간이 걸릴 수 있어요. 완료 후 AI에 전달할 내용을 직접 확인할 수 있습니다.'}</p>
    {error && <button type="button" className="mt-4 text-primary-500" onClick={() => setAttempt(value => value + 1)}>다시 시도</button>}
    <button type="button" className="ml-4 mt-4" onClick={cancel}>취소하고 입력으로 돌아가기</button>
  </ModalShell></div>
  return <div className="relative z-[70]"><DeidentificationReviewModal sources={preview.sources} context={{}} initialItems={items}
    requireConfirmation onBack={cancel} onConfirm={value => void confirm(value)}
    submitting={submitting} error={error} submitLabel={task.purpose === 'memory' ? '확인한 내용으로 저장하기' : '확인한 내용으로 AI 처리하기'} /></div>
}
