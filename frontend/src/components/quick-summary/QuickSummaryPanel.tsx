import { useRef, useState, type ReactNode } from 'react'
import { Check, Copy, Loader2, PenLine, Plus, RotateCcw, X } from 'lucide-react'

import { extractDocumentMaterial, requestQuickSummary } from '../../api/client'
import {
  QUICK_SUMMARY_MAX_CHARS,
  QUICK_SUMMARY_MIN_CHARS,
  QUICK_SUMMARY_SECTIONS,
  quickSummaryText,
  type QuickSummaryResult,
} from '../../lib/quickSummary'

const ACCEPTED_FILES = '.txt,.pdf,.docx'

/**
 * "간편 요약하기" body shared by the public landing and the signed-in workspace:
 * input (typing or file) → AI four-item summary → copy. Signed-in summaries are saved
 * automatically by the workspace; the landing offers 로그인 후 저장하기 through `saveAction`.
 */
export default function QuickSummaryPanel({
  result,
  onResult,
  onEditResult,
  editDisabled = false,
  canExtractDocuments,
  privacyNote,
  resultStatus,
  saveAction,
  notice,
  below,
}: {
  result: QuickSummaryResult | null
  onResult: (result: QuickSummaryResult | null) => void
  /** Commits a counselor-reviewed result without starting another AI generation. */
  onEditResult: (result: QuickSummaryResult) => void
  /** Prevents editing while the signed-in workspace is still assigning the summary's draft id. */
  editDisabled?: boolean
  /** PDF/DOCX extraction is a protected API, so only signed-in users can upload those. */
  canExtractDocuments: boolean
  /** What happens to the input and the summary, shown under the input box. */
  privacyNote: ReactNode
  /** Save state shown in the result card (signed-in auto-save). */
  resultStatus?: ReactNode
  /** Primary action next to 복사하기 (the landing's 로그인 후 저장하기). */
  saveAction?: { label: string; onSave: (result: QuickSummaryResult) => void }
  notice?: ReactNode
  below?: ReactNode
}) {
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(false)
  const [extracting, setExtracting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editDraft, setEditDraft] = useState<QuickSummaryResult | null>(null)
  // Kept only in this mounted component so a fresh AI result can be checked against its input.
  const [sourceText, setSourceText] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const length = text.trim().length
  const overLimit = length > QUICK_SUMMARY_MAX_CHARS

  const summarize = async () => {
    if (loading) return
    if (length < QUICK_SUMMARY_MIN_CHARS) return setError(`요약할 상담 내용을 ${QUICK_SUMMARY_MIN_CHARS}자 이상 입력해주세요.`)
    if (overLimit) return setError(`간편 요약은 ${QUICK_SUMMARY_MAX_CHARS.toLocaleString()}자까지 입력할 수 있어요.`)
    setError(null)
    setLoading(true)
    try {
      const summary = await requestQuickSummary(text)
      setSourceText(text)
      setEditing(false)
      setEditDraft(null)
      onResult(summary)
      setCopied(false)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '요약을 만들지 못했어요. 잠시 후 다시 시도해주세요.')
    } finally {
      setLoading(false)
    }
  }

  const addFile = async (file: File | undefined) => {
    if (!file) return
    setError(null)
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    try {
      let content = ''
      if (extension === '.txt') {
        content = await file.text()
      } else if (extension === '.pdf' || extension === '.docx') {
        if (!canExtractDocuments) {
          setError('PDF·DOCX 파일은 로그인 후 올릴 수 있어요. 텍스트(.txt) 파일은 바로 올릴 수 있어요.')
          return
        }
        setExtracting(true)
        content = (await extractDocumentMaterial(file)).extracted_text
      } else {
        setError('TXT, PDF, DOCX 파일만 올릴 수 있어요.')
        return
      }
      if (!content.trim()) return setError('파일에서 읽을 수 있는 내용이 없어요.')
      setText((current) => (current.trim() ? `${current.trimEnd()}\n\n${content.trim()}` : content.trim()))
    } catch (fileError) {
      setError(fileError instanceof Error ? fileError.message : '파일을 읽지 못했어요.')
    } finally {
      setExtracting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const copy = async () => {
    if (!result) return
    try {
      await navigator.clipboard.writeText(quickSummaryText(result))
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      setError('복사하지 못했어요. 요약 내용을 직접 선택해 복사해주세요.')
    }
  }

  const startOver = () => {
    onResult(null)
    setSourceText(null)
    setEditing(false)
    setEditDraft(null)
    setError(null)
    setCopied(false)
  }

  const beginEditing = () => {
    if (!result) return
    setEditDraft({ ...result })
    setEditing(true)
    setError(null)
  }

  const cancelEditing = () => {
    setEditDraft(null)
    setEditing(false)
    setError(null)
  }

  const finishEditing = () => {
    if (!editDraft) return
    const edited = {
      ...editDraft,
      main_content: editDraft.main_content.trim(),
      client_response: editDraft.client_response.trim(),
      counselor_intervention: editDraft.counselor_intervention.trim(),
      next_plan: editDraft.next_plan.trim(),
    }
    if (QUICK_SUMMARY_SECTIONS.some(({ key }) => !edited[key])) {
      setError('내용이 없는 항목이 있어요. 각 항목을 확인한 뒤 수정 완료를 눌러주세요.')
      return
    }
    onEditResult(edited)
    setEditDraft(null)
    setEditing(false)
    setError(null)
    setCopied(false)
  }

  return (
    <section className="mx-auto flex w-full min-w-0 max-w-[656px] flex-col items-center px-4 py-12 sm:py-16">
      <h1 className="text-center text-[26px] font-extrabold tracking-[-0.02em] text-[#0b1f5c] sm:text-[34px]">
        {result ? 'AI 요약이 완성됐어요' : '상담 내용을 빠르게 정리해보세요'}
      </h1>
      <p className="mt-2 text-center text-base text-[#1f2a4d] sm:text-lg">
        {result ? '입력 내용을 바탕으로 회기 내용을 4가지 항목으로 정리했어요.' : '내담자를 등록하지 않아도 AI 요약을 할 수 있어요.'}
      </p>

      {notice && <div className="mt-6 w-full">{notice}</div>}

      {result ? (
        <article aria-label="AI 요약 결과" className="mt-10 w-full rounded-2xl border border-primary-100 bg-white p-5 shadow-card sm:p-6">
          <div className="mb-5 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs leading-5 text-grey-500">AI가 정리한 초안이에요. 원문과 비교한 뒤 필요한 내용을 직접 고쳐주세요.</p>
            {!editing && (
              <button type="button" onClick={beginEditing} disabled={editDisabled} className="inline-flex h-8 items-center gap-1.5 rounded-full border border-grey-200 px-3 text-xs font-semibold text-grey-700 hover:bg-grey-100 disabled:cursor-wait disabled:opacity-50">
                <PenLine className="h-3.5 w-3.5" />요약 수정하기
              </button>
            )}
          </div>
          <div className="space-y-5">
            {QUICK_SUMMARY_SECTIONS.map(({ key, title }) => (
              <section key={key}>
                {editing && editDraft ? (
                  <>
                    <label htmlFor={`quick-summary-${key}`} className="text-sm font-bold text-grey-900">{title}</label>
                    <textarea
                      id={`quick-summary-${key}`}
                      aria-label={`${title} 수정`}
                      value={editDraft[key]}
                      onChange={(event) => {
                        setEditDraft((current) => current ? { ...current, [key]: event.target.value } : current)
                        setError(null)
                      }}
                      rows={3}
                      className="mt-1.5 block w-full resize-y rounded-lg border border-grey-200 px-3 py-2 text-sm leading-6 text-grey-900 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
                    />
                  </>
                ) : (
                  <>
                    <h2 className="text-sm font-bold text-grey-900">{title}</h2>
                    <p className="mt-1.5 whitespace-pre-line text-sm leading-6 text-grey-700">{result[key]}</p>
                  </>
                )}
              </section>
            ))}
          </div>
          {sourceText && (
            <details className="mt-5 rounded-lg border border-grey-200 bg-grey-50 px-3 py-2.5">
              <summary className="cursor-pointer text-sm font-semibold text-grey-700">입력 원문과 비교하기</summary>
              <p className="mt-3 max-h-64 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-6 text-grey-700">{sourceText}</p>
              <p className="mt-2 text-xs text-grey-500">입력 원문은 이 화면에서 비교할 때만 사용되며 저장되지 않아요.</p>
            </details>
          )}
          {result.masked_categories.length > 0 && (
            <p className="mt-5 rounded-lg bg-primary-50 px-3 py-2 text-xs text-primary-900">연락처·이름 등 개인정보로 보이는 내용은 가린 뒤 AI에 보냈어요.</p>
          )}
          {result.stub && <p className="mt-3 text-xs text-grey-500">데모 모드로 생성된 요약입니다.</p>}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <button type="button" onClick={startOver} disabled={editDisabled} className="inline-flex items-center gap-1.5 text-sm font-semibold text-grey-500 hover:text-grey-900 disabled:cursor-wait disabled:opacity-50">
              <RotateCcw className="h-4 w-4" />새로 요약하기
            </button>
            {editing ? (
              <div className="flex items-center gap-3">
                <button type="button" onClick={cancelEditing} className="inline-flex h-9 items-center gap-1.5 rounded-full border border-grey-200 bg-white px-4 text-sm font-semibold text-grey-700 hover:bg-grey-100">
                  <X className="h-4 w-4" />취소
                </button>
                <button type="button" onClick={finishEditing} className="inline-flex h-9 items-center gap-1.5 rounded-full bg-primary-400 px-5 text-sm font-bold text-white hover:bg-primary-500">
                  <Check className="h-4 w-4" />수정 완료
                </button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center justify-end gap-3">
                {resultStatus}
                <button
                  type="button"
                  onClick={() => void copy()}
                  className={saveAction
                    ? 'inline-flex h-9 items-center gap-1.5 rounded-full border border-grey-200 bg-white px-4 text-sm font-semibold text-grey-700 hover:bg-grey-100'
                    : 'inline-flex h-9 items-center gap-1.5 rounded-full bg-primary-400 px-5 text-sm font-bold text-white hover:bg-primary-500'}
                >
                  {copied ? <Check className={`h-4 w-4 ${saveAction ? 'text-success-500' : ''}`} /> : <Copy className="h-4 w-4" />}{copied ? '복사했어요' : '복사하기'}
                </button>
                {saveAction && (
                  <button type="button" onClick={() => saveAction.onSave(result)} disabled={editDisabled} className="inline-flex h-9 items-center gap-1.5 rounded-full bg-primary-400 px-5 text-sm font-bold text-white hover:bg-primary-500 disabled:cursor-wait disabled:opacity-50">
                    {saveAction.label}
                  </button>
                )}
              </div>
            )}
          </div>
        </article>
      ) : (
        <div className="mt-10 w-full rounded-2xl border border-[#8fb0f5] bg-white p-4 shadow-card focus-within:border-primary-400 focus-within:ring-4 focus-within:ring-primary-100">
          <label htmlFor="quick-summary-input" className="sr-only">요약할 상담 내용</label>
          <textarea
            id="quick-summary-input"
            value={text}
            onChange={(event) => { setText(event.target.value); setError(null) }}
            placeholder="요약할 내용을 입력해주세요"
            rows={text ? 8 : 2}
            className="block w-full resize-none bg-transparent text-sm leading-6 text-grey-900 outline-none placeholder:text-grey-400"
          />
          <div className="mt-3 flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={extracting}
                className="inline-flex h-9 items-center gap-1.5 rounded-full border border-grey-200 bg-white px-4 text-sm text-grey-600 hover:bg-grey-100 disabled:opacity-60"
              >
                {extracting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}파일 올리기
              </button>
              <input ref={fileInputRef} type="file" accept={ACCEPTED_FILES} className="hidden" aria-label="상담 내용 파일 선택" onChange={(event) => void addFile(event.target.files?.[0])} />
              {length > 0 && (
                <span className={`text-xs ${overLimit ? 'font-bold text-danger-500' : 'text-grey-400'}`}>
                  {length.toLocaleString()} / {QUICK_SUMMARY_MAX_CHARS.toLocaleString()}자
                </span>
              )}
            </div>
            <button
              type="button"
              onClick={() => void summarize()}
              disabled={loading || extracting}
              className="inline-flex h-9 items-center gap-1.5 rounded-full bg-primary-400 px-6 text-sm font-bold text-white hover:bg-primary-500 disabled:opacity-60"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}{loading ? '요약하는 중' : '요약하기'}
            </button>
          </div>
        </div>
      )}

      {error && <p role="alert" className="mt-4 w-full rounded-lg bg-danger-50 px-4 py-3 text-sm text-danger-500">{error}</p>}
      {!result && <p className="mt-4 w-full text-center text-xs leading-5 text-grey-500">{privacyNote}</p>}

      {below && <div className="mt-6 w-full">{below}</div>}
    </section>
  )
}
