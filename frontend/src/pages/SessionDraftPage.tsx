import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardList, Loader2, Send } from 'lucide-react'
import { API_BASE_URL, generateNoteDraft } from '../api/client'
import type { EvidenceCheckItem, NoteDraftResponse, SessionInput } from '../types/session'

const today = new Date().toISOString().slice(0, 10)

const processSteps = ['구조화', '회기요약', '검증']

const initialForm: SessionInput = {
  case_id: 'CASE001',
  session_number: 3,
  session_date: today,
  counselor_name: 'Counselor A',
  counselor_memo:
    '이번 회기는 진로 불안과 자기비난 사고를 중심으로 진행함. 다음 회기에는 자동사고 기록지를 함께 검토하기로 함.',
  transcript_text:
    'C: 지난 회기 이후 어떻게 지내셨나요?\nCl: 여전히 진로가 불확실해서 불안해요. 주변 친구들은 다 정한 것 같은데 저만 뒤처지는 느낌이에요.',
  previous_session_summary:
    '이전 회기에서는 자기이해와 진로 가치 탐색을 중심으로 다룸. 내담자는 강점은 확인했으나 적성에 대한 확신 부족을 어려움으로 언급함.',
  counseling_goal: '',
  psychological_test_summary: '',
  key_issue_tags: [],
  nonverbal_notes: '',
}

export default function SessionDraftPage() {
  const [form, setForm] = useState<SessionInput>(initialForm)
  const [isLoading, setIsLoading] = useState(false)
  const [hasSubmitted, setHasSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<NoteDraftResponse | null>(null)

  const completedSteps = useMemo(() => {
    if (isLoading) return 1
    if (result) return processSteps.length
    return 0
  }, [isLoading, result])

  const updateField = (field: keyof SessionInput, value: string | number) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsLoading(true)
    setHasSubmitted(true)
    setError(null)
    setResult(null)

    try {
      const data = await generateNoteDraft(form)
      setResult(data)
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : '회기요약 생성 중 오류가 발생했습니다. 백엔드 서버가 실행 중인지 확인해주세요.'
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-6 py-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm font-medium text-blue-700">Re:mind MVP V0-alpha</p>
            <h1 className="text-2xl font-semibold tracking-normal">회기요약 초안 생성 데모</h1>
          </div>
          <p className="text-sm text-slate-500">API: {API_BASE_URL}/api/notes/generate</p>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[420px_1fr]">
        <section className="space-y-4">
          <form onSubmit={handleSubmit} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">1. 회기 자료 입력</h2>
                <p className="mt-1 text-sm text-slate-500">상담사 메모, STT, 이전 회기 요약을 넣어주세요.</p>
              </div>
              <ClipboardList className="h-5 w-5 text-blue-700" aria-hidden="true" />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="케이스 ID / 가명" htmlFor="case_id">
                <input
                  id="case_id"
                  value={form.case_id}
                  onChange={(event) => updateField('case_id', event.target.value)}
                  className={inputClass}
                  required
                />
              </Field>
              <Field label="회기 번호" htmlFor="session_number">
                <input
                  id="session_number"
                  type="number"
                  min={1}
                  value={form.session_number}
                  onChange={(event) => updateField('session_number', Number(event.target.value))}
                  className={inputClass}
                  required
                />
              </Field>
            </div>

            <div className="mt-4 space-y-4">
              <Field label="상담사 메모" htmlFor="counselor_memo">
                <textarea
                  id="counselor_memo"
                  value={form.counselor_memo}
                  onChange={(event) => updateField('counselor_memo', event.target.value)}
                  className={textareaClass}
                  rows={5}
                  required
                />
              </Field>
              <Field label="축어록/STT 텍스트" htmlFor="transcript_text">
                <textarea
                  id="transcript_text"
                  value={form.transcript_text}
                  onChange={(event) => updateField('transcript_text', event.target.value)}
                  className={textareaClass}
                  rows={7}
                  required
                />
              </Field>
              <Field label="이전 회기 요약" htmlFor="previous_session_summary">
                <textarea
                  id="previous_session_summary"
                  value={form.previous_session_summary}
                  onChange={(event) => updateField('previous_session_summary', event.target.value)}
                  className={textareaClass}
                  rows={4}
                  required
                />
              </Field>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              {isLoading ? '요약 생성 중...' : '요약 생성'}
            </button>
          </form>

          {hasSubmitted && (
            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="text-lg font-semibold">2. 처리 상태</h2>
              {isLoading && (
                <p className="mt-2 text-sm font-medium text-blue-700">구조화 → 회기요약 → 검증 진행 중...</p>
              )}
              <div className="mt-4 space-y-3">
                {processSteps.map((step, index) => {
                  const isDone = index < completedSteps
                  const isActive = isLoading && index === completedSteps
                  return (
                    <div key={step} className="flex items-center gap-3 text-sm">
                      <span
                        className={`flex h-7 w-7 items-center justify-center rounded-full border ${
                          isDone
                            ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                            : isActive
                              ? 'border-blue-200 bg-blue-50 text-blue-700'
                              : 'border-slate-200 bg-slate-50 text-slate-400'
                        }`}
                      >
                        {isDone ? (
                          <CheckCircle2 className="h-4 w-4" />
                        ) : isActive ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          index + 1
                        )}
                      </span>
                      <span className={isDone || isActive ? 'text-slate-900' : 'text-slate-500'}>{step}</span>
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4" />
                <p>{error}</p>
              </div>
            </div>
          )}
        </section>

        <section className="min-w-0 rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-200 px-5 py-4">
            <h2 className="text-lg font-semibold">3. 생성 결과</h2>
            <p className="mt-1 text-sm text-slate-500">백엔드가 반환한 회기요약 JSON을 읽기 쉬운 섹션으로 표시합니다.</p>
          </div>

          {!result && !isLoading && (
            <div className="px-5 py-16 text-center">
              <p className="text-sm text-slate-500">왼쪽 입력 영역에서 회기 자료를 넣고 요약을 생성하세요.</p>
            </div>
          )}

          {isLoading && (
            <div className="px-5 py-16 text-center">
              <Loader2 className="mx-auto h-7 w-7 animate-spin text-blue-700" />
              <p className="mt-3 text-sm text-slate-600">구조화 → 회기요약 → 검증 진행 중...</p>
            </div>
          )}

          {result && <GeneratedResult result={result} />}
        </section>
      </div>
    </main>
  )
}

const inputClass =
  'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100'

const textareaClass =
  'mt-1 w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100'

function Field({
  children,
  htmlFor,
  label,
}: {
  children: React.ReactNode
  htmlFor: string
  label: string
}) {
  return (
    <label htmlFor={htmlFor} className="block">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  )
}

function GeneratedResult({ result }: { result: NoteDraftResponse }) {
  return (
    <div className="space-y-4 p-5">
      <div className="grid gap-4 xl:grid-cols-2">
        <ResultCard title="회기 핵심 요약" body={result.session_summary} wide />
        <ResultCard title="주요 호소 문제" body={result.main_issue} />
        <ResultCard title="상담사 개입" body={result.counselor_intervention} />
        <ResultCard title="내담자 반응" body={result.client_response} />
        <ResultCard title="다음 회기 계획" body={result.next_plan} />
      </div>

      <section className="rounded-lg border border-slate-200 p-4">
        <h3 className="font-semibold text-slate-900">근거 확인</h3>
        <div className="mt-3 space-y-3">
          {result.evidence_check.length ? (
            result.evidence_check.map((item, index) => <EvidenceItemView key={`${item.claim}-${index}`} item={item} />)
          ) : (
            <p className="text-sm text-slate-500">표시할 근거 항목이 없습니다.</p>
          )}
        </div>
      </section>

      <ListSection title="누락 가능 항목" items={result.missing_items} emptyText="누락 가능 항목이 없습니다." />
      <ListSection title="주의 문구" items={result.warnings} emptyText="표시할 주의 문구가 없습니다." tone="warning" />
    </div>
  )
}

function ResultCard({ body, title, wide = false }: { body: string; title: string; wide?: boolean }) {
  return (
    <section className={`rounded-lg border border-slate-200 p-4 ${wide ? 'xl:col-span-2' : ''}`}>
      <h3 className="font-semibold text-slate-900">{title}</h3>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{body || '생성된 내용이 없습니다.'}</p>
    </section>
  )
}

function EvidenceItemView({ item }: { item: EvidenceCheckItem }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{sourceLabel[item.source_type]}</Badge>
        <Badge>{confidenceLabel[item.confidence]}</Badge>
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-800">{item.claim}</p>
      <p className="mt-2 text-xs leading-5 text-slate-500">출처 일부: {item.source_excerpt}</p>
    </div>
  )
}

function ListSection({
  emptyText,
  items,
  title,
  tone = 'default',
}: {
  emptyText: string
  items: string[]
  title: string
  tone?: 'default' | 'warning'
}) {
  return (
    <section className="rounded-lg border border-slate-200 p-4">
      <h3 className="font-semibold text-slate-900">{title}</h3>
      {items.length ? (
        <ul className="mt-3 space-y-2">
          {items.map((item) => (
            <li
              key={item}
              className={`rounded-md px-3 py-2 text-sm ${
                tone === 'warning' ? 'bg-amber-50 text-amber-800' : 'bg-slate-50 text-slate-700'
              }`}
            >
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-slate-500">{emptyText}</p>
      )}
    </section>
  )
}

function Badge({ children }: { children: React.ReactNode }) {
  return <span className="rounded-full bg-white px-2 py-1 text-xs text-slate-600 ring-1 ring-slate-200">{children}</span>
}

const sourceLabel: Record<EvidenceCheckItem['source_type'], string> = {
  transcript: '축어록 기반',
  counselor_memo: '상담사 메모 기반',
  previous_summary: '이전 회기 기반',
  ai_inference: 'AI 추론',
}

const confidenceLabel: Record<EvidenceCheckItem['confidence'], string> = {
  high: '신뢰도 높음',
  medium: '신뢰도 중간',
  low: '신뢰도 낮음',
}
