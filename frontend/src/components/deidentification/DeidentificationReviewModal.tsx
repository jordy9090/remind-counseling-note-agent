import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, Loader2, PenLine, Plus, Sparkles, X } from 'lucide-react'

import ModalShell from '../app-shell/ModalShell'
import { OutlineButton, PrimaryButton } from '../app-shell/ui'
import {
  applyDeidItems,
  deidSegments,
  detectDeidentificationItems,
  newDeidItemId,
  sourcesContaining,
  type DeidDetectionContext,
  type DeidItem,
  type DeidSource,
} from '../../lib/deidentificationReview'

export interface DeidReviewResult {
  /** Text per source key, as it will be sent to the AI. */
  texts: Record<string, string>
  skipped: boolean
}

type FormMode = { mode: 'add' } | { mode: 'edit'; itemId: string }

const HIGHLIGHT = {
  auto: 'bg-primary-100',
  review: 'bg-[#FBDADC]',
} as const

const DOT = {
  auto: 'bg-primary-400',
  review: 'bg-[#F4A7AC]',
} as const

/**
 * "AI로 보내기 전 내용을 확인해주세요" (designer's review step before summary generation).
 * Left: 원문 / AI 전달용 per source with highlights. Right: detected items to edit, remove or add.
 * Generation is enabled once the counselor confirms, or when the step is skipped.
 */
export default function DeidentificationReviewModal({
  sources,
  context,
  onBack,
  onConfirm,
  onAddMaterial,
}: {
  sources: DeidSource[]
  context: DeidDetectionContext
  onBack: () => void
  onConfirm: (result: DeidReviewResult) => void
  /** "+ 자료 추가": returns to the input screen. Hidden when absent. */
  onAddMaterial?: () => void
}) {
  const [items, setItems] = useState<DeidItem[]>([])
  const [detecting, setDetecting] = useState(true)
  const [tab, setTab] = useState<'original' | 'ai'>('original')
  const [activeKey, setActiveKey] = useState(sources[0]?.key ?? '')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [form, setForm] = useState<FormMode | null>(null)
  const [draftOriginal, setDraftOriginal] = useState('')
  const [draftReplacement, setDraftReplacement] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [confirmed, setConfirmed] = useState(false)
  const [skip, setSkip] = useState(false)
  const textRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)

  useEffect(() => {
    let cancelled = false
    detectDeidentificationItems(sources.map((source) => source.text), context)
      .then((detected) => { if (!cancelled) setItems(detected) })
      .catch(() => { if (!cancelled) setItems([]) })
      .finally(() => { if (!cancelled) setDetecting(false) })
    return () => { cancelled = true }
    // Detect once per opening; later edits are the counselor's.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const activeSource = sources.find((source) => source.key === activeKey) ?? sources[0]
  const segments = useMemo(
    () => (activeSource ? deidSegments(activeSource.text, items, tab === 'ai') : []),
    [activeSource, items, tab],
  )
  const detectedCount = items.filter((item) => item.origin === 'detected').length
  const reviewCount = items.filter((item) => item.kind === 'review').length

  /** Scroll the first highlight of an item into view (after the tab/source switch renders). */
  const revealInText = (itemId: string) => {
    window.requestAnimationFrame(() => {
      textRef.current?.querySelector(`[data-item="${itemId}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  }

  const selectItem = (item: DeidItem, from: 'list' | 'text') => {
    setSelectedId(item.id)
    if (from === 'list') {
      if (!activeSource?.text.includes(item.original)) {
        const holder = sourcesContaining(sources, item.original)[0]
        if (holder) setActiveKey(holder.key)
      }
      revealInText(item.id)
    } else {
      listRef.current?.querySelector(`[data-row="${item.id}"]`)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }

  const openForm = (next: FormMode, original = '', replacement = '') => {
    setForm(next)
    setDraftOriginal(original)
    setDraftReplacement(replacement)
    setFormError(null)
  }

  const closeForm = () => {
    setForm(null)
    setFormError(null)
  }

  /** Dragging over the original text pre-fills a new item with the selection. */
  const captureSelection = () => {
    if (tab !== 'original') return
    const selection = window.getSelection()
    const text = selection?.toString().trim() ?? ''
    if (!text || !selection?.anchorNode || !textRef.current?.contains(selection.anchorNode)) return
    if (text.length > 200) return
    const existing = items.find((item) => item.original === text)
    if (existing) {
      selectItem(existing, 'text')
      openForm({ mode: 'edit', itemId: existing.id }, existing.original, existing.replacement)
      return
    }
    openForm({ mode: 'add' }, text, '')
  }

  const saveForm = (event: FormEvent) => {
    event.preventDefault()
    if (!form) return
    const original = draftOriginal.trim()
    const replacement = draftReplacement.trim()
    if (!original || !replacement) return setFormError('원문 표현과 대체 표현을 모두 입력해주세요.')
    if (!sourcesContaining(sources, original).length) return setFormError('원문에서 찾을 수 없는 표현이에요. 원문과 똑같이 입력해주세요.')
    const editingId = form.mode === 'edit' ? form.itemId : null
    if (items.some((item) => item.original === original && item.id !== editingId)) return setFormError('이미 등록된 표현이에요.')

    if (editingId) {
      setItems((current) => current.map((item) => (item.id === editingId ? { ...item, original, replacement } : item)))
      setSelectedId(editingId)
    } else {
      const item: DeidItem = { id: newDeidItemId(), original, replacement, kind: 'auto', origin: 'manual' }
      setItems((current) => [...current, item])
      setSelectedId(item.id)
    }
    window.getSelection()?.removeAllRanges()
    closeForm()
  }

  const removeItem = (itemId: string) => {
    setItems((current) => current.filter((item) => item.id !== itemId))
    if (selectedId === itemId) setSelectedId(null)
    if (form?.mode === 'edit' && form.itemId === itemId) closeForm()
  }

  const submit = () => {
    const texts = Object.fromEntries(sources.map((source) => [source.key, skip ? source.text : applyDeidItems(source.text, items)]))
    onConfirm({ texts, skipped: skip })
  }

  const canSubmit = !detecting && (skip || confirmed)

  return (
    <ModalShell
      ariaLabel="AI로 보내기 전 내용 확인"
      title="AI로 보내기 전 내용을 확인해주세요"
      description="상담 자료에서 식별될 수 있는 정보를 확인하고, AI에 전달할 내용을 검토해주세요."
      onClose={onBack}
      width={1170}
      footer={(
        <div className="flex w-full flex-col gap-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <label className={`flex items-center gap-3 text-sm font-semibold ${skip ? 'text-grey-400' : 'text-grey-800'}`}>
              <input
                type="checkbox"
                className="h-6 w-6 shrink-0 cursor-pointer rounded-[6px] border-grey-200 accent-primary-400 disabled:cursor-not-allowed"
                checked={confirmed}
                disabled={skip}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              표시된 항목과 AI에 전달할 내용을 모두 확인했어요.
            </label>
            <label className="flex cursor-pointer items-center gap-2.5 text-sm text-grey-500">
              건너뛰기
              <button
                type="button"
                role="switch"
                aria-checked={skip}
                aria-label="비식별화 검토 건너뛰기"
                title="켜면 항목을 바꾸지 않고 입력한 내용 그대로 요약해요. 이름·연락처 등은 서버에서 자동으로 가려져요."
                onClick={() => setSkip((value) => !value)}
                className={`relative h-7 w-[50px] rounded-full transition ${skip ? 'bg-primary-400' : 'bg-primary-100'}`}
              >
                <span className={`absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all ${skip ? 'left-[26px]' : 'left-1'}`} />
              </button>
            </label>
          </div>
          <div className="flex gap-3">
            <OutlineButton className="h-[52px] w-[120px] rounded-[12px] text-[15px] sm:w-[182px]" onClick={onBack}>
              <ArrowLeft className="h-5 w-5" />뒤로가기
            </OutlineButton>
            <PrimaryButton className="h-[52px] flex-1 rounded-[12px] text-[15px]" disabled={!canSubmit} onClick={submit}>
              <Sparkles className="h-5 w-5" />AI 요약 생성하기
            </PrimaryButton>
          </div>
        </div>
      )}
    >
      <div className="flex flex-col gap-6">
        <div className="flex flex-wrap gap-3">
          <span className="inline-flex h-9 items-center rounded-[10px] bg-primary-50 px-3 text-sm font-bold text-primary-400">
            {detecting ? '항목을 찾는 중…' : `자동 탐지된 항목 총 ${detectedCount}건`}
          </span>
          {!detecting && reviewCount > 0 && (
            <span className="inline-flex h-9 items-center rounded-[10px] bg-danger-50 px-3 text-sm font-bold text-danger-500">확인 필요 {reviewCount}건</span>
          )}
        </div>

        <div className={`grid grid-cols-1 gap-6 lg:grid-cols-2 ${skip ? 'opacity-60' : ''}`}>
          <section aria-label="상담 자료" className="flex h-[440px] min-h-0 flex-col rounded-card border border-grey-200 lg:h-[min(560px,56vh)]">
            <div role="tablist" className="grid shrink-0 grid-cols-2 border-b border-grey-200 px-1">
              {([['original', '원문'], ['ai', 'AI 전달용']] as const).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  onClick={() => setTab(key)}
                  className={`-mb-px h-[52px] border-b-2 text-base ${tab === key ? 'border-primary-400 font-bold text-grey-900' : 'border-transparent text-grey-400 hover:text-grey-600'}`}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="flex shrink-0 flex-wrap gap-2 px-6 pt-5">
              {sources.map((source) => (
                <button
                  key={source.key}
                  type="button"
                  onClick={() => setActiveKey(source.key)}
                  aria-pressed={source.key === activeSource?.key}
                  className={`h-7 max-w-[180px] truncate rounded-full border px-3 text-xs font-semibold ${source.key === activeSource?.key ? 'border-primary-400 bg-primary-50 text-primary-400' : 'border-primary-100 bg-white text-primary-400 hover:bg-primary-50'}`}
                >
                  {source.label}
                </button>
              ))}
              {onAddMaterial && (
                <button type="button" onClick={onAddMaterial} className="inline-flex h-7 items-center gap-1 rounded-full border border-dashed border-primary-100 px-3 text-xs font-semibold text-primary-400 hover:bg-primary-50">
                  <Plus className="h-3 w-3" />자료 추가
                </button>
              )}
            </div>

            <div
              ref={textRef}
              onMouseUp={captureSelection}
              aria-label={tab === 'ai' ? 'AI에 전달할 내용' : '원문'}
              className="rm-scroll m-6 mt-4 min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words rounded-[10px] border border-grey-200 bg-[#F8FAFC] px-3.5 py-3 text-sm leading-7 text-grey-800"
            >
              {segments.map((segment, index) => {
                if (segment.type === 'text') return <span key={index}>{segment.text}</span>
                if (segment.type === 'speaker') return <strong key={index} className="font-bold text-grey-900">{segment.text}</strong>
                const item = items.find((candidate) => candidate.id === segment.itemId)
                if (!item) return <span key={index}>{segment.text}</span>
                return (
                  <mark
                    key={index}
                    data-item={item.id}
                    role="button"
                    tabIndex={0}
                    title={`${item.original} → ${item.replacement}`}
                    onClick={() => selectItem(item, 'text')}
                    onKeyDown={(event) => { if (event.key === 'Enter') selectItem(item, 'text') }}
                    className={`cursor-pointer rounded-[3px] px-px text-grey-900 ${HIGHLIGHT[item.kind]} ${selectedId === item.id ? 'outline outline-2 outline-offset-1 outline-primary-400' : ''}`}
                  >
                    {segment.text}
                  </mark>
                )
              })}
            </div>
          </section>

          <section aria-label="비식별화 항목 검토" className="flex h-[440px] min-h-0 flex-col rounded-card border border-grey-200 lg:h-[min(560px,56vh)]">
            <div className="flex h-[62px] shrink-0 items-center justify-between gap-3 border-b border-grey-200 px-6">
              <h3 className="text-base font-bold text-grey-900">비식별화 항목 검토</h3>
              <button
                type="button"
                onClick={() => openForm({ mode: 'add' })}
                className="inline-flex h-10 items-center gap-1.5 rounded-full border border-primary-400 px-4 text-sm font-bold text-primary-400 hover:bg-primary-50"
              >
                <Plus className="h-4 w-4" />항목 추가하기
              </button>
            </div>

            {detecting ? (
              <div className="flex flex-1 items-center justify-center gap-2 text-sm text-grey-500"><Loader2 className="h-4 w-4 animate-spin" />식별 정보를 찾고 있어요</div>
            ) : (
              <ul ref={listRef} className="rm-scroll min-h-0 flex-1 space-y-3 overflow-y-auto px-6 py-5">
                {items.length === 0 && (
                  <li className="rounded-[12px] border border-dashed border-grey-200 px-4 py-8 text-center text-sm leading-6 text-grey-500">
                    자동으로 찾은 항목이 없어요.<br />원문에서 드래그하거나 항목 추가하기로 직접 등록할 수 있어요.
                  </li>
                )}
                {items.map((item) => (
                  <li key={item.id} data-row={item.id} className="flex items-center gap-3">
                    <span aria-label={item.kind === 'review' ? '확인 필요' : '자동 탐지'} className={`h-2.5 w-2.5 shrink-0 rounded-full ${DOT[item.kind]}`} />
                    <button
                      type="button"
                      onClick={() => selectItem(item, 'list')}
                      className={`grid h-11 min-w-0 flex-1 grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 rounded-[10px] border px-3 text-sm ${selectedId === item.id ? 'border-primary-400 bg-primary-50' : 'border-transparent bg-grey-100 hover:bg-primary-50/60'}`}
                    >
                      <span className="truncate text-center text-grey-600" title={item.original}>{item.original}</span>
                      <ArrowRight className="h-4 w-4 text-grey-400" strokeWidth={1.5} />
                      <span className="truncate text-center font-bold text-grey-900" title={item.replacement}>{item.replacement}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => { selectItem(item, 'list'); openForm({ mode: 'edit', itemId: item.id }, item.original, item.replacement) }}
                      className="h-10 shrink-0 rounded-full border border-primary-400 px-4 text-sm font-bold text-primary-400 hover:bg-primary-50 sm:px-6"
                    >
                      수정
                    </button>
                    <button type="button" onClick={() => removeItem(item.id)} aria-label={`${item.original} 항목 삭제`} className="shrink-0 text-grey-500 hover:text-grey-900">
                      <X className="h-5 w-5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {form && (
              <form onSubmit={saveForm} className="shrink-0 border-t border-grey-200 px-6 pb-6 pt-4">
                <div className="rounded-[12px] border border-primary-100 bg-primary-50/40 p-4">
                  <p className="flex items-center gap-1.5 text-sm font-bold text-grey-900">
                    {form.mode === 'add' ? <Plus className="h-4 w-4" /> : <PenLine className="h-4 w-4" />}
                    {form.mode === 'add' ? '비식별화 항목 추가' : '선택한 표현 수정'}
                  </p>
                  <p className="mt-1 text-xs text-grey-500">원문에서 드래그해서 하이라이트하면 정보를 등록할 수 있어요.</p>
                  <label className="mt-3 block text-sm text-grey-700">
                    원문 표현
                    <input
                      className="mt-1.5 h-11 w-full rounded-[10px] border border-grey-200 bg-white px-3 text-sm text-grey-900 outline-none placeholder:text-grey-400 focus:border-primary-400"
                      placeholder="축어록에 포함된 문구"
                      value={draftOriginal}
                      onChange={(event) => setDraftOriginal(event.target.value)}
                    />
                  </label>
                  <label className="mt-3 block text-sm text-grey-700">
                    대체 표현
                    <input
                      autoFocus
                      className="mt-1.5 h-11 w-full rounded-[10px] border border-grey-200 bg-white px-3 text-sm text-grey-900 outline-none placeholder:text-grey-400 focus:border-primary-400"
                      placeholder="예: 회사 내 관리자"
                      value={draftReplacement}
                      onChange={(event) => setDraftReplacement(event.target.value)}
                    />
                  </label>
                  {formError && <p role="alert" className="mt-2 text-xs text-danger-500">{formError}</p>}
                  <div className="mt-3 flex justify-end gap-2">
                    <button type="button" onClick={closeForm} className="h-10 rounded-full border border-grey-200 bg-white px-4 text-sm font-bold text-grey-700 hover:bg-grey-100">취소</button>
                    <button type="submit" className="h-10 rounded-full bg-primary-400 px-4 text-sm font-bold text-white hover:bg-primary-500">{form.mode === 'add' ? '추가하기' : '저장하기'}</button>
                  </div>
                </div>
              </form>
            )}
          </section>
        </div>
      </div>
    </ModalShell>
  )
}
