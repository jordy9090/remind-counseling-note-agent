import { useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardList, Loader2, Send } from 'lucide-react'
import { API_BASE_URL, postGenerateNote } from '../api/client'
import type {
  DocumentTransformPreview,
  EvidenceItem,
  EvidenceMappedItem,
  EvidenceType,
  GenerateNoteResponse,
  ReviewableClaim,
  SensitiveInfoCandidate,
  SessionInput,
  SessionSummaryDraft,
  SummarySection,
} from '../types/session'

type TabKey = 'structured' | 'summary' | 'verification' | 'documents' | 'raw'
type SummaryField = keyof Omit<SessionSummaryDraft, 'session_info'>

const today = new Date().toISOString().slice(0, 10)

const processSteps = [
  '입력 정제 중',
  '상담 내용 구조화 중',
  '근거 연결 중',
  '회기요약 초안 생성 중',
  '검증 리포트 생성 중',
  '문서 변환 Preview 생성 중',
]

const structuredGroups: Array<{ key: keyof GenerateNoteResponse['structured_case_data']; label: string }> = [
  { key: 'presenting_problem', label: '주호소 / 주요 이슈' },
  { key: 'session_theme', label: '회기 주제' },
  { key: 'session_content', label: '상담 내용' },
  { key: 'counselor_interventions', label: '상담자 개입' },
  { key: 'client_responses', label: '내담자 반응' },
  { key: 'key_client_utterances', label: '중요한 발화' },
  { key: 'nonverbal_observations', label: '비언어/반언어 메모' },
  { key: 'reflection_candidates', label: 'Reflection 후보' },
  { key: 'next_plan', label: '추후 계획' },
]

const summaryFields: Array<{ key: SummaryField; label: string }> = [
  { key: 'session_theme', label: '회기 주제' },
  { key: 'presenting_problem', label: '주호소 / 주요 문제' },
  { key: 'session_content', label: '상담 내용 요약' },
  { key: 'counselor_intervention', label: '상담자 개입' },
  { key: 'client_response', label: '내담자 반응 및 변화' },
  { key: 'reflection', label: 'Reflection' },
  { key: 'next_plan', label: '추후 개입 계획' },
]

const tabItems: Array<{ key: TabKey; label: string }> = [
  { key: 'structured', label: '구조화 결과' },
  { key: 'summary', label: '회기요약 초안' },
  { key: 'verification', label: '검증 리포트' },
  { key: 'documents', label: '문서 변환 Preview' },
  { key: 'raw', label: 'Raw JSON' },
]

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
  counseling_goal: '진로 선택 과정에서 자기이해를 높이고 실행 가능한 준비 계획을 세움.',
  psychological_test_summary: '',
  key_issue_tags: ['진로불안', '자기비난', '취업준비'],
  nonverbal_notes: '',
}

export default function SessionDraftPage() {
  const [form, setForm] = useState<SessionInput>(initialForm)
  const [tagText, setTagText] = useState(initialForm.key_issue_tags?.join(', ') || '')
  const [isLoading, setIsLoading] = useState(false)
  const [hasSubmitted, setHasSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<GenerateNoteResponse | null>(null)
  const [editableDraft, setEditableDraft] = useState<SessionSummaryDraft | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>('structured')

  const completedSteps = useMemo(() => {
    if (isLoading) return 3
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
    setEditableDraft(null)
    setActiveTab('structured')

    const payload: SessionInput = {
      ...form,
      key_issue_tags: tagText
        .split(',')
        .map((tag) => tag.trim())
        .filter(Boolean),
    }

    try {
      const data = await postGenerateNote(payload)
      setResult(data)
      setEditableDraft(data.session_summary_draft)
    } catch (err) {
      const message = err instanceof Error ? err.message : '회기요약 초안 생성 중 오류가 발생했습니다.'
      setError(message)
    } finally {
      setIsLoading(false)
    }
  }

  const updateSummaryText = (field: SummaryField, text: string) => {
    setEditableDraft((prev) => {
      if (!prev) return prev
      const section = prev[field] as SummarySection
      return {
        ...prev,
        [field]: {
          ...section,
          text,
        },
      }
    })
  }

  return (
    <main className="min-h-screen bg-slate-50 text-slate-950">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl flex-col gap-2 px-6 py-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-sm font-medium text-blue-700">Re:mind MVP V0</p>
            <h1 className="text-2xl font-semibold tracking-normal">근거 추적형 회기요약 워크스페이스</h1>
          </div>
          <p className="text-sm text-slate-500">API: {API_BASE_URL}/api/notes/generate</p>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-6 py-6 lg:grid-cols-[420px_1fr]">
        <section className="space-y-4">
          <form onSubmit={handleSubmit} className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">1. 입력 영역</h2>
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
              <Field label="날짜" htmlFor="session_date">
                <input
                  id="session_date"
                  type="date"
                  value={form.session_date}
                  onChange={(event) => updateField('session_date', event.target.value)}
                  className={inputClass}
                  required
                />
              </Field>
              <Field label="상담자" htmlFor="counselor_name">
                <input
                  id="counselor_name"
                  value={form.counselor_name}
                  onChange={(event) => updateField('counselor_name', event.target.value)}
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
              <Field label="상담 목표" htmlFor="counseling_goal" optional>
                <input
                  id="counseling_goal"
                  value={form.counseling_goal || ''}
                  onChange={(event) => updateField('counseling_goal', event.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="심리검사 요약" htmlFor="psychological_test_summary" optional>
                <textarea
                  id="psychological_test_summary"
                  value={form.psychological_test_summary || ''}
                  onChange={(event) => updateField('psychological_test_summary', event.target.value)}
                  className={textareaClass}
                  rows={3}
                />
              </Field>
              <Field label="주요 키워드" htmlFor="key_issue_tags" optional>
                <input
                  id="key_issue_tags"
                  value={tagText}
                  onChange={(event) => setTagText(event.target.value)}
                  className={inputClass}
                  placeholder="진로불안, 자기비난, 취업준비"
                />
              </Field>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              회기요약 초안 생성
            </button>
          </form>

          {hasSubmitted && (
            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h2 className="text-lg font-semibold">2. 처리 상태</h2>
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
            <h2 className="text-lg font-semibold">3. 결과 탭</h2>
            <p className="mt-1 text-sm text-slate-500">구조화, 근거, 초안, 검증 결과를 한 번에 확인합니다.</p>
          </div>

          {!result && !isLoading && (
            <div className="px-5 py-16 text-center">
              <p className="text-sm text-slate-500">왼쪽 입력 영역에서 회기 자료를 넣고 초안을 생성하세요.</p>
            </div>
          )}

          {isLoading && (
            <div className="px-5 py-16 text-center">
              <Loader2 className="mx-auto h-7 w-7 animate-spin text-blue-700" />
              <p className="mt-3 text-sm text-slate-600">백엔드 6-agent pipeline을 실행하고 있습니다.</p>
            </div>
          )}

          {result && editableDraft && (
            <>
              <div className="flex gap-1 overflow-x-auto border-b border-slate-200 px-3 pt-3">
                {tabItems.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setActiveTab(tab.key)}
                    className={`whitespace-nowrap rounded-t-md px-3 py-2 text-sm font-medium ${
                      activeTab === tab.key
                        ? 'bg-slate-900 text-white'
                        : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              <div className="p-5">
                {activeTab === 'structured' && (
                  <StructuredTab
                    groups={structuredGroups.map((group) => ({
                      label: group.label,
                      items: result.structured_case_data[group.key],
                    }))}
                  />
                )}
                {activeTab === 'summary' && (
                  <SummaryTab draft={editableDraft} onChange={updateSummaryText} />
                )}
                {activeTab === 'verification' && <VerificationTab result={result} />}
                {activeTab === 'documents' && <DocumentPreviewTab preview={result.document_transform_preview} />}
                {activeTab === 'raw' && <RawJsonTab data={result} />}
              </div>
            </>
          )}
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
  optional = false,
}: {
  children: React.ReactNode
  htmlFor: string
  label: string
  optional?: boolean
}) {
  return (
    <label htmlFor={htmlFor} className="block">
      <span className="flex items-center gap-2 text-sm font-medium text-slate-700">
        {label}
        {optional && <span className="text-xs font-normal text-slate-400">선택</span>}
      </span>
      {children}
    </label>
  )
}

function StructuredTab({ groups }: { groups: Array<{ label: string; items: EvidenceItem[] }> }) {
  return (
    <div className="space-y-4">
      {groups.map((group) => (
        <section key={group.label} className="rounded-lg border border-slate-200 p-4">
          <h3 className="font-semibold text-slate-900">{group.label}</h3>
          <div className="mt-3 space-y-3">
            {group.items.length ? (
              group.items.map((item, index) => <EvidenceListItem key={`${group.label}-${index}`} item={item} />)
            ) : (
              <p className="text-sm text-slate-500">생성된 항목이 없습니다.</p>
            )}
          </div>
        </section>
      ))}
    </div>
  )
}

function EvidenceListItem({ item }: { item: EvidenceItem | EvidenceMappedItem }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <EvidenceBadge type={item.evidence_type} />
        {item.source_refs.map((source) => (
          <span key={source} className="rounded-full bg-white px-2 py-1 text-xs text-slate-500 ring-1 ring-slate-200">
            {source}
          </span>
        ))}
      </div>
      <p className="mt-2 text-sm leading-6 text-slate-800">{item.content}</p>
    </div>
  )
}

function SummaryTab({
  draft,
  onChange,
}: {
  draft: SessionSummaryDraft
  onChange: (field: SummaryField, text: string) => void
}) {
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 p-4">
        <h3 className="font-semibold text-slate-900">회기 정보</h3>
        <dl className="mt-3 grid gap-3 text-sm sm:grid-cols-4">
          <InfoTerm label="케이스" value={draft.session_info.case_id} />
          <InfoTerm label="회기" value={`${draft.session_info.session_number}회기`} />
          <InfoTerm label="날짜" value={draft.session_info.session_date || '미입력'} />
          <InfoTerm label="상담자" value={draft.session_info.counselor_name || '미입력'} />
        </dl>
      </section>

      {summaryFields.map((field) => {
        const section = draft[field.key]
        return (
          <section key={field.key} className="rounded-lg border border-slate-200 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-semibold text-slate-900">{field.label}</h3>
              <div className="flex flex-wrap gap-2">
                <EvidenceBadge type={section.evidence_type} />
                {section.requires_review && (
                  <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-700 ring-1 ring-amber-200">
                    상담사 확인 필요
                  </span>
                )}
              </div>
            </div>
            <textarea
              value={section.text}
              onChange={(event) => onChange(field.key, event.target.value)}
              className={`${textareaClass} min-h-[112px]`}
            />
            <SourceRefs refs={section.source_refs} />
          </section>
        )
      })}
    </div>
  )
}

function VerificationTab({ result }: { result: GenerateNoteResponse }) {
  const report = result.verification_report
  return (
    <div className="space-y-4">
      <VerificationGroup
        title="입력 근거 있음"
        tone="green"
        items={report.grounded_items.map((item) => ({
          main: item.claim,
          sub: item.source_refs.join(', ') || '출처 없음',
        }))}
      />
      <VerificationGroup
        title="입력 근거 부족 / 추론 가능성"
        tone="amber"
        items={[...report.weakly_grounded_items, ...report.unsupported_or_risky_claims].map(
          (item: ReviewableClaim) => ({
            main: item.claim,
            sub: `${item.reason} 권장: ${item.recommendation}`,
          }),
        )}
      />
      <VerificationGroup
        title="민감정보 후보"
        tone="red"
        items={report.sensitive_info_items.map((item: SensitiveInfoCandidate) => ({
          main: item.text,
          sub: `${item.source} · ${item.recommendation}`,
        }))}
        emptyText="탐지된 민감정보 후보가 없습니다."
      />
      <VerificationGroup
        title="상담사 직접 판단 필요"
        tone="blue"
        items={report.requires_counselor_review.map((item) => ({
          main: item.field,
          sub: item.reason,
        }))}
      />
    </div>
  )
}

function DocumentPreviewTab({ preview }: { preview: DocumentTransformPreview }) {
  const terminationFields = [
    '상담 목표 및 변화 요약',
    '회기별 진행 과정',
    '종결 사유',
    '목표 달성 정도',
    '향후 권고',
    '상담자 종합소견',
  ]

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
        <h3 className="font-semibold">문서 변환 Preview</h3>
        <p className="mt-1">{preview.notice}</p>
      </section>

      <section className="rounded-lg border border-slate-200 p-4">
        <h3 className="font-semibold text-slate-900">미리보기로 채울 수 있는 항목</h3>
        <div className="mt-3 grid gap-3">
          {Object.entries(preview.preview_sections).map(([key, value]) => (
            <div key={key} className="rounded-md bg-slate-50 p-3">
              <p className="text-xs font-semibold uppercase text-slate-500">{key}</p>
              <p className="mt-1 text-sm leading-6 text-slate-800">{value}</p>
            </div>
          ))}
        </div>
      </section>

      {Object.keys(preview.partially_available_fields).length > 0 && (
        <section className="rounded-lg border border-amber-200 bg-amber-50 p-4">
          <h3 className="font-semibold text-amber-900">부분 입력된 항목</h3>
          <div className="mt-3 grid gap-3">
            {Object.entries(preview.partially_available_fields).map(([key, value]) => (
              <div key={key} className="rounded-md bg-white/70 p-3">
                <p className="text-sm font-medium text-amber-900">{key}</p>
                <p className="mt-1 text-sm leading-6 text-amber-800">{value}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <MissingFields title="슈퍼비전 보고서에 추가로 필요한 필드" fields={preview.missing_required_fields} />
        <MissingFields title="종결 보고서에 추가로 필요한 필드" fields={terminationFields} />
      </div>
    </div>
  )
}

function RawJsonTab({ data }: { data: GenerateNoteResponse }) {
  return (
    <pre className="max-h-[680px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs leading-5 text-slate-100">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}

function VerificationGroup({
  emptyText = '표시할 항목이 없습니다.',
  items,
  title,
  tone,
}: {
  emptyText?: string
  items: Array<{ main: string; sub: string }>
  title: string
  tone: 'green' | 'amber' | 'red' | 'blue'
}) {
  const toneClass = {
    green: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    red: 'border-red-200 bg-red-50 text-red-800',
    blue: 'border-blue-200 bg-blue-50 text-blue-800',
  }[tone]

  return (
    <section className="rounded-lg border border-slate-200 p-4">
      <h3 className="font-semibold text-slate-900">{title}</h3>
      <div className="mt-3 space-y-3">
        {items.length ? (
          items.map((item, index) => (
            <div key={`${item.main}-${index}`} className={`rounded-md border p-3 ${toneClass}`}>
              <p className="text-sm font-medium">{item.main}</p>
              <p className="mt-1 text-xs opacity-80">{item.sub}</p>
            </div>
          ))
        ) : (
          <p className="text-sm text-slate-500">{emptyText}</p>
        )}
      </div>
    </section>
  )
}

function MissingFields({ fields, title }: { fields: string[]; title: string }) {
  return (
    <section className="rounded-lg border border-slate-200 p-4">
      <h3 className="font-semibold text-slate-900">{title}</h3>
      <ul className="mt-3 space-y-2">
        {fields.map((field) => (
          <li key={field} className="flex items-center gap-2 text-sm text-slate-700">
            <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
            {field}
          </li>
        ))}
      </ul>
    </section>
  )
}

function InfoTerm({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-1 font-medium text-slate-900">{value}</dd>
    </div>
  )
}

function SourceRefs({ refs }: { refs: string[] }) {
  if (!refs.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {refs.map((ref) => (
        <span key={ref} className="rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-500">
          출처: {ref}
        </span>
      ))}
    </div>
  )
}

function EvidenceBadge({ type }: { type: EvidenceType }) {
  const labelMap: Record<EvidenceType, string> = {
    direct: '근거 있음',
    inferred: '추론',
    counselor_input: '상담사 입력',
    previous_context: '이전 회기 기반',
    needs_review: '확인 필요',
    mixed: '혼합 근거',
    model_inference: 'AI 추론',
  }
  const classMap: Record<EvidenceType, string> = {
    direct: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
    inferred: 'bg-amber-50 text-amber-700 ring-amber-200',
    counselor_input: 'bg-blue-50 text-blue-700 ring-blue-200',
    previous_context: 'bg-sky-50 text-sky-700 ring-sky-200',
    needs_review: 'bg-rose-50 text-rose-700 ring-rose-200',
    mixed: 'bg-slate-100 text-slate-700 ring-slate-200',
    model_inference: 'bg-orange-50 text-orange-700 ring-orange-200',
  }

  return (
    <span className={`rounded-full px-2 py-1 text-xs font-medium ring-1 ${classMap[type]}`}>
      {labelMap[type]}
    </span>
  )
}
