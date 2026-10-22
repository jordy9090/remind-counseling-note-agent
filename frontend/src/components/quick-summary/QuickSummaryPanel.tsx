import { useRef, useState, type ReactNode } from 'react'
import { Check, Copy, Loader2, Plus, RotateCcw } from 'lucide-react'

import { extractDocumentMaterial, requestQuickSummary } from '../../api/client'
import {
  QUICK_SUMMARY_MAX_CHARS,
  QUICK_SUMMARY_MIN_CHARS,
  quickSummaryText,
  type QuickSummaryResult,
} from '../../lib/quickSummary'
import type { NoteDraftResponse } from '../../types/session'

const ACCEPTED_FILES = '.txt,.pdf,.docx'

/**
 * "간편 요약하기" body shared by the public landing and the signed-in workspace:
 * input (typing or file) → the regular AI summary (same items as the summary screen) → copy.
 * Signed-in summaries are saved automatically by the workspace; the landing offers
 * 로그인 후 저장하기 through `saveAction`.
 */
export default function QuickSummaryPanel({
  result,
  onResult,
  toResult,
  canExtractDocuments,
  privacyNote,
  resultStatus,
  saveAction,
  notice,
  below,
}: {
  result: QuickSummaryResult | null
  onResult: (result: QuickSummaryResult | null) => void
  /** Builds the summary items exactly as the regular summary screen does. */
  toResult: (note: NoteDraftResponse) => QuickSummaryResult
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
      onResult(toResult(await requestQuickSummary(text)))
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
    setError(null)
    setCopied(false)
  }

  return (
    <section className="mx-auto flex w-full min-w-0 max-w-[656px] flex-col items-center px-4 py-12 sm:py-16">
      <h1 className="text-center text-[26px] font-extrabold tracking-[-0.02em] text-[#0b1f5c] sm:text-[34px]">
        {result ? 'AI 요약이 완성됐어요' : '상담 내용을 빠르게 정리해보세요'}
      </h1>
      <p className="mt-2 text-center text-base text-[#1f2a4d] sm:text-lg">
        {result ? '입력 내용을 바탕으로 회기 요약과 같은 항목으로 정리했어요.' : '내담자를 등록하지 않아도 AI 요약을 할 수 있어요.'}
      </p>

      {notice && <div className="mt-6 w-full">{notice}</div>}

      {result ? (
        <article aria-label="AI 요약 결과" className="mt-10 w-full rounded-2xl border border-primary-100 bg-white p-5 shadow-card sm:p-6">
          <div className="divide-y divide-grey-100">
            {result.sections.map((section) => (
              <section key={section.id} className="py-4 first:pt-0 last:pb-0">
                {/* Same title box as the regular summary screen (주요 호소, 회기 주제, ...). */}
                <h2 className="inline-flex h-7 items-center rounded-[6px] bg-primary-50 px-2.5 text-sm font-bold text-primary-400">{section.title}</h2>
                <p className="mt-3 whitespace-pre-line px-2 text-sm leading-7 text-grey-800">{section.content}</p>
              </section>
            ))}
          </div>
          {result.deidentified && (
            <p className="mt-5 rounded-lg bg-primary-50 px-3 py-2 text-xs text-primary-900">이름·기관·나이·연락처 등 개인을 알아볼 수 있는 내용은 바꾼 뒤 AI에 보냈어요.</p>
          )}
          {result.stub && <p className="mt-3 text-xs text-grey-500">데모 모드로 생성된 요약입니다.</p>}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
            <button type="button" onClick={startOver} className="inline-flex items-center gap-1.5 text-sm font-semibold text-grey-500 hover:text-grey-900">
              <RotateCcw className="h-4 w-4" />새로 요약하기
            </button>
            <div className="flex items-center gap-3">
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
                <button type="button" onClick={() => saveAction.onSave(result)} className="inline-flex h-9 items-center gap-1.5 rounded-full bg-primary-400 px-5 text-sm font-bold text-white hover:bg-primary-500">
                  {saveAction.label}
                </button>
              )}
            </div>
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
