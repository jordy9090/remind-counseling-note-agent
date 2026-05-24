import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  ClipboardList,
  Edit3,
  FileText,
  FolderOpen,
  Loader2,
  Plus,
  Save,
  Search,
  Send,
  ShieldCheck,
  Wand2,
  X,
} from 'lucide-react'
import { generateNoteDraft } from '../api/client'
import type {
  EvidenceCheckItem,
  EvidenceConfidence,
  EvidenceSourceType,
  NoteDraftResponse,
  SessionInput,
} from '../types/session'

const today = new Intl.DateTimeFormat('en-CA', {
  day: '2-digit',
  month: '2-digit',
  timeZone: 'Asia/Seoul',
  year: 'numeric',
}).format(new Date())

const workflowSteps = ['회기입력', '요약초안', '문서변환', '최종문서'] as const
const processSteps = ['입력 정제', '상담 내용 구조화', '근거 연결', '회기요약 초안 생성', '검증 리포트 생성']

type WorkflowStep = (typeof workflowSteps)[number]
type AppScreen = 'case_list' | 'session_input' | 'summary_draft' | 'document_transform' | 'final_document'
type FinalDocumentType = 'session_note' | 'supervision_report' | 'termination_report'
type MaterialModalMode =
  | 'add'
  | 'basic_info'
  | 'paste_text'
  | 'file_upload'
  | 'load_previous'
  | 'write_memo'
  | 'edit_transcript'
  | 'edit_memo'
  | 'edit_previous'

type DraftSectionId =
  | 'client_info'
  | 'main_issue'
  | 'session_theme'
  | 'session_content'
  | 'counselor_intervention'
  | 'client_response'
  | 'next_plan'
  | 'risk_signal'
  | 'supervision_memo'
  | string

type SourceBadgeKind = 'memo' | 'transcript' | 'previous' | 'attachment' | 'ai' | 'editable' | 'needs_review'

interface AttachmentItem {
  id: string
  name: string
}

interface CompactEvidence {
  label: string
  excerpt: string
  confidence: EvidenceConfidence
  needsReview: boolean
}

interface DraftSection {
  id: DraftSectionId
  title: string
  content: string
  sourceBadges: SourceBadgeKind[]
  confidence: EvidenceConfidence
  evidence: CompactEvidence[]
  visible: boolean
  editable: boolean
  toggleable: boolean
}

interface ChecklistItem {
  id: DraftSectionId
  title: string
}

interface CaseSummary {
  id: string
  name: string
  type: string
  lastDate: string
  counselor: string
  mainIssue: string
  status: '진행중' | '종결' | '대기중'
  sessionCount: number
  progressLabel: string
  progress: number
}

const defaultChecklistItems: ChecklistItem[] = [
  { id: 'main_issue', title: '주호소' },
  { id: 'session_theme', title: '회기 주제' },
  { id: 'session_content', title: '상담 내용' },
  { id: 'counselor_intervention', title: '상담자 개입' },
  { id: 'client_response', title: '내담자 반응' },
  { id: 'next_plan', title: '다음 계획' },
  { id: 'risk_signal', title: '위험 신호' },
  { id: 'supervision_memo', title: '슈퍼비전 메모' },
]

const defaultVisibleSectionIds = new Set<DraftSectionId>(defaultChecklistItems.map((item) => item.id))

const caseSummaries: CaseSummary[] = [
  {
    id: 'C-2024-001',
    name: '홍길동',
    type: '청소년 상담',
    lastDate: '2026. 05. 24',
    counselor: '박상담사',
    mainIssue: '불안 증가, 수면 문제, 대인 갈등',
    status: '진행중',
    sessionCount: 5,
    progressLabel: '12회 목표',
    progress: 42,
  },
  {
    id: 'C-2024-002',
    name: '신데렐라',
    type: '직장인 상담',
    lastDate: '2026. 04. 21',
    counselor: '박상담사',
    mainIssue: '직무 스트레스, 번아웃',
    status: '진행중',
    sessionCount: 3,
    progressLabel: '12회 목표',
    progress: 25,
  },
  {
    id: 'C-2023-018',
    name: '흥부',
    type: '성인 개인상담',
    lastDate: '2026. 03. 10',
    counselor: '박상담사',
    mainIssue: '우울, 자존감 하락',
    status: '종결',
    sessionCount: 12,
    progressLabel: '종결 완료',
    progress: 100,
  },
  {
    id: 'C-2024-009',
    name: '팥쥐',
    type: '성인 개인 상담',
    lastDate: '2026. 04. 15',
    counselor: '미배정',
    mainIssue: '초기 면접 진행 중',
    status: '대기중',
    sessionCount: 1,
    progressLabel: '진행 예정',
    progress: 18,
  },
]

const initialForm: SessionInput = {
  case_id: '홍길동',
  session_number: 6,
  session_date: today,
  counselor_name: '박상담사',
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
  const [currentScreen, setCurrentScreen] = useState<AppScreen>('case_list')
  const [form, setForm] = useState<SessionInput>(initialForm)
  const [sessionTopic, setSessionTopic] = useState('진로 불안과 자기비난 사고')
  const [finalDocumentType, setFinalDocumentType] = useState<FinalDocumentType>('session_note')
  const [isDeidentified, setIsDeidentified] = useState(true)
  const [attachments, setAttachments] = useState<AttachmentItem[]>([])
  const [materialModal, setMaterialModal] = useState<MaterialModalMode | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [hasSubmitted, setHasSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<NoteDraftResponse | null>(null)
  const [draftSections, setDraftSections] = useState<DraftSection[]>([])
  const [visibleSectionIds, setVisibleSectionIds] = useState<Set<DraftSectionId>>(defaultVisibleSectionIds)
  const [editingSectionId, setEditingSectionId] = useState<DraftSectionId | null>(null)
  const [expandedEvidenceId, setExpandedEvidenceId] = useState<DraftSectionId | null>(null)

  const hasMaterials = Boolean(
    form.counselor_memo.trim() ||
      form.transcript_text.trim() ||
      form.previous_session_summary.trim() ||
      attachments.length,
  )

  const activeStep = getActiveStep(currentScreen)
  const completedSteps = useMemo(() => {
    if (isLoading) return 1
    if (result) return processSteps.length
    return 0
  }, [isLoading, result])

  const checklistItems = result
    ? draftSections.filter((section) => section.toggleable).map((section) => ({ id: section.id, title: section.title }))
    : defaultChecklistItems

  const updateField = (field: keyof SessionInput, value: string | number) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const addAttachments = (files: FileList | null) => {
    if (!files?.length) return
    const nextFiles = Array.from(files).map((file) => ({
      id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      name: file.name,
    }))
    setAttachments((prev) => [...prev, ...nextFiles])
  }

  const removeAttachment = (attachmentId: string) => {
    setAttachments((prev) => prev.filter((item) => item.id !== attachmentId))
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsLoading(true)
    setHasSubmitted(true)
    setError(null)
    setResult(null)
    setExpandedEvidenceId(null)
    setEditingSectionId(null)

    try {
      const data = await generateNoteDraft(form)
      setResult(data)
      setDraftSections(buildDocumentSections(data, form, sessionTopic, visibleSectionIds))
      setCurrentScreen('summary_draft')
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

  const toggleSectionVisibility = (sectionId: DraftSectionId) => {
    setVisibleSectionIds((prev) => {
      const next = new Set(prev)
      if (next.has(sectionId)) {
        next.delete(sectionId)
      } else {
        next.add(sectionId)
      }
      return next
    })

    setDraftSections((prev) =>
      prev.map((section) => (section.id === sectionId ? { ...section, visible: !section.visible } : section)),
    )
  }

  const updateDraftSectionContent = (sectionId: DraftSectionId, content: string) => {
    setDraftSections((prev) =>
      prev.map((section) => (section.id === sectionId ? { ...section, content } : section)),
    )
  }

  const addCustomSection = () => {
    if (!result) return
    const id = `custom_${Date.now()}`
    const newSection: DraftSection = {
      id,
      title: '추가 항목',
      content: '상담사가 직접 내용을 작성해주세요.',
      sourceBadges: ['editable', 'needs_review'],
      confidence: 'low',
      evidence: [],
      visible: true,
      editable: true,
      toggleable: true,
    }
    setDraftSections((prev) => [...prev, newSection])
    setVisibleSectionIds((prev) => new Set(prev).add(id))
  }

  const goBackToInput = () => {
    setCurrentScreen('session_input')
    setResult(null)
    setDraftSections([])
    setExpandedEvidenceId(null)
    setEditingSectionId(null)
  }

  const openCaseList = () => {
    setCurrentScreen('case_list')
  }

  const openSessionInput = () => {
    setCurrentScreen('session_input')
  }

  const openDocumentTransform = () => {
    if (!result) return
    setCurrentScreen('document_transform')
  }

  const openFinalDocument = (documentType: FinalDocumentType = finalDocumentType) => {
    if (!result) return
    setFinalDocumentType(documentType)
    setCurrentScreen('final_document')
  }

  return (
    <main className="min-h-screen bg-[#f5f7fb] text-slate-950">
      <AppSidebar activeScreen={currentScreen} onOpenCaseList={openCaseList} onOpenSessionInput={openSessionInput} />

      <div className="min-h-screen lg:pl-[232px]">
        <TopWorkspaceBar
          activeStep={activeStep}
          currentScreen={currentScreen}
          onOpenCaseList={openCaseList}
          onOpenSessionInput={openSessionInput}
        />

        {currentScreen === 'case_list' ? (
          <CaseListWorkspace
            cases={caseSummaries}
            onCreateSession={openSessionInput}
            onOpenCase={() => {
              setForm((prev) => ({ ...prev, case_id: '홍길동', session_number: 6 }))
              setCurrentScreen(result ? 'summary_draft' : 'session_input')
            }}
          />
        ) : (
          <div className="grid gap-6 px-5 py-6 xl:grid-cols-[minmax(0,1fr)_300px]">
            <section className="min-w-0">
              {currentScreen === 'session_input' && (
                <SessionInputWorkspace
                  completedSteps={completedSteps}
                  error={error}
                  form={form}
                  hasMaterials={hasMaterials}
                  hasSubmitted={hasSubmitted}
                  isDeidentified={isDeidentified}
                  isLoading={isLoading}
                  attachments={attachments}
                  sessionTopic={sessionTopic}
                  onAddMaterial={() => setMaterialModal('add')}
                  onEditBasicInfo={() => setMaterialModal('basic_info')}
                  onEditMaterial={setMaterialModal}
                  onRemoveAttachment={removeAttachment}
                  onSetIsDeidentified={setIsDeidentified}
                  onSubmit={handleSubmit}
                />
              )}

              {currentScreen === 'summary_draft' && result && (
                <SummaryDraftWorkspace
                  editingSectionId={editingSectionId}
                  expandedEvidenceId={expandedEvidenceId}
                  form={form}
                  sections={draftSections.filter((section) => section.visible)}
                  onChangeContent={updateDraftSectionContent}
                  onEditSection={setEditingSectionId}
                  onToggleEvidence={(sectionId) =>
                    setExpandedEvidenceId((current) => (current === sectionId ? null : sectionId))
                  }
                />
              )}

              {currentScreen === 'document_transform' && result && (
                <DocumentTransformWorkspace
                  selectedType={finalDocumentType}
                  sections={draftSections}
                  onSelectType={setFinalDocumentType}
                  onCreateFinal={openFinalDocument}
                />
              )}

              {currentScreen === 'final_document' && result && (
                <FinalDocumentWorkspace
                  documentType={finalDocumentType}
                  form={form}
                  missingItems={result.missing_items}
                  sections={draftSections.filter((section) => section.visible)}
                />
              )}
            </section>

            {currentScreen === 'final_document' ? (
              <FinalReviewPanel
                documentType={finalDocumentType}
                missingItems={result?.missing_items || []}
                warnings={result?.warnings || []}
                onBack={() => setCurrentScreen('document_transform')}
              />
            ) : (
              <ReviewPanel
                activeStep={activeStep}
                checklistItems={checklistItems}
                currentScreen={currentScreen}
                isLoading={isLoading}
                missingItems={result?.missing_items || []}
                resultReady={Boolean(result)}
                visibleSectionIds={visibleSectionIds}
                warnings={result?.warnings || []}
                onAddCustomSection={addCustomSection}
                onGoBack={currentScreen === 'document_transform' ? () => setCurrentScreen('summary_draft') : goBackToInput}
                onGoToFinal={() => openFinalDocument()}
                onGoToTransform={openDocumentTransform}
                onToggleSection={toggleSectionVisibility}
              />
            )}
          </div>
        )}
      </div>

      {materialModal && (
        <MaterialModal
          mode={materialModal}
          form={form}
          sessionTopic={sessionTopic}
          onClose={() => setMaterialModal(null)}
          onModeChange={setMaterialModal}
          onUpdateField={updateField}
          onUpdateSessionTopic={setSessionTopic}
          onAddAttachments={addAttachments}
        />
      )}
    </main>
  )
}

function AppSidebar({
  activeScreen,
  onOpenCaseList,
  onOpenSessionInput,
}: {
  activeScreen: AppScreen
  onOpenCaseList: () => void
  onOpenSessionInput: () => void
}) {
  return (
    <aside className="border-slate-200 bg-white lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:w-[232px] lg:border-r">
      <div className="flex h-full flex-col">
        <div className="border-b border-slate-100 px-5 py-5">
          <p className="text-2xl font-bold tracking-normal text-sky-300">Re:mind</p>
        </div>

        <div className="space-y-5 px-4 py-4">
          <label className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
            <Search className="h-4 w-4" />
            <input
              className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-slate-400"
              placeholder="내담자/케이스 검색"
            />
          </label>

          <nav className="space-y-2 text-sm">
            <p className="px-2 text-xs font-medium text-slate-400">메뉴</p>
            <SidebarButton
              active={activeScreen === 'case_list'}
              icon={<FolderOpen className="h-4 w-4" />}
              onClick={onOpenCaseList}
            >
              케이스 목록
            </SidebarButton>
            <SidebarButton
              active={activeScreen === 'session_input'}
              icon={<Plus className="h-4 w-4" />}
              onClick={onOpenSessionInput}
            >
              새 회기 입력
            </SidebarButton>
          </nav>

          <div className="space-y-3 border-t border-slate-100 pt-4">
            <p className="px-2 text-xs font-medium text-slate-400">최근 케이스</p>
            <CaseListItem name="홍길동" status="진행중" meta="청소년 · 5회기" active />
            <CaseListItem name="신데렐라" status="진행중" meta="직장인 · 3회기" />
            <CaseListItem name="흥부" status="종결" meta="직장인 · 12회기" tone="green" />
            <CaseListItem name="팥쥐" status="대기중" meta="성인 · 1회기" tone="orange" />
          </div>
        </div>

        <div className="mt-auto border-t border-slate-200 px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 font-semibold text-white">
              박
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-900">박상담사</p>
              <p className="text-xs text-slate-500">2급 심리상담사</p>
            </div>
          </div>
        </div>
      </div>
    </aside>
  )
}

function SidebarButton({
  active = false,
  children,
  icon,
  onClick,
}: {
  active?: boolean
  children: ReactNode
  icon: ReactNode
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left font-medium ${
        active ? 'bg-blue-50 text-blue-700' : 'text-slate-700 hover:bg-slate-50'
      }`}
    >
      {icon}
      {children}
    </button>
  )
}

function CaseListItem({
  active = false,
  meta,
  name,
  status,
  tone = 'blue',
}: {
  active?: boolean
  meta: string
  name: string
  status: string
  tone?: 'blue' | 'green' | 'orange'
}) {
  const toneClass =
    tone === 'green'
      ? 'bg-emerald-50 text-emerald-700'
      : tone === 'orange'
        ? 'bg-orange-50 text-orange-700'
        : 'bg-blue-50 text-blue-700'

  return (
    <button
      type="button"
      className={`w-full rounded-md px-3 py-3 text-left text-sm ${
        active ? 'bg-blue-50' : 'border-b border-slate-100 hover:bg-slate-50'
      }`}
    >
      <p className="font-semibold text-slate-900">{name}</p>
      <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
        <span className={`rounded-full px-2 py-0.5 font-medium ${toneClass}`}>{status}</span>
        <span>{meta}</span>
      </div>
    </button>
  )
}

function TopWorkspaceBar({
  activeStep,
  currentScreen,
  onOpenCaseList,
  onOpenSessionInput,
}: {
  activeStep: WorkflowStep
  currentScreen: AppScreen
  onOpenCaseList: () => void
  onOpenSessionInput: () => void
}) {
  const activeIndex = workflowSteps.indexOf(activeStep)

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="flex min-h-[68px] items-center justify-between gap-4 px-5">
        {currentScreen === 'case_list' ? (
          <div>
            <h1 className="text-xl font-semibold tracking-normal text-slate-950">케이스 목록</h1>
            <p className="mt-1 text-sm text-slate-500">최근 상담 케이스와 회기 진행 상태를 확인합니다.</p>
          </div>
        ) : (
          <nav className="flex flex-wrap items-center gap-2 text-sm">
            {workflowSteps.map((step, index) => (
              <button
                key={step}
                type="button"
                className="flex items-center gap-2"
                onClick={() => {
                  if (step === '회기입력') onOpenSessionInput()
                }}
              >
                <span
                  className={`inline-flex items-center gap-1 rounded-md px-2 py-1 font-medium ${
                    index === activeIndex
                      ? 'bg-blue-50 text-blue-700'
                      : index < activeIndex
                        ? 'text-slate-700'
                        : 'text-slate-400'
                  }`}
                >
                  {step}
                </span>
                {index < workflowSteps.length - 1 && <ChevronRight className="h-4 w-4 text-slate-300" />}
              </button>
            ))}
          </nav>
        )}

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenCaseList}
            className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <ClipboardList className="h-4 w-4" />
            목록으로
          </button>
          {currentScreen === 'case_list' && (
            <button
              type="button"
              onClick={onOpenSessionInput}
              className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
            >
              <Plus className="h-4 w-4" />새 회기 생성
            </button>
          )}
        </div>
      </div>
    </header>
  )
}

function CaseListWorkspace({
  cases,
  onCreateSession,
  onOpenCase,
}: {
  cases: CaseSummary[]
  onCreateSession: () => void
  onOpenCase: (caseItem: CaseSummary) => void
}) {
  return (
    <section className="px-5 py-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-normal text-slate-950">케이스 목록</h2>
          <p className="mt-1 text-sm text-slate-500">상담 기록, 요약 초안, 문서 변환 상태를 한 곳에서 관리합니다.</p>
        </div>
        <div className="flex rounded-full bg-white p-1 text-sm shadow-sm ring-1 ring-slate-200">
          {['전체', '진행중', '종결', '대기중'].map((filter, index) => (
            <button
              key={filter}
              type="button"
              className={`rounded-full px-3 py-1.5 font-medium ${
                index === 0 ? 'bg-blue-600 text-white' : 'text-slate-600 hover:bg-slate-50'
              }`}
            >
              {filter}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {cases.map((caseItem) => (
          <CaseCard key={caseItem.id} caseItem={caseItem} onOpen={() => onOpenCase(caseItem)} />
        ))}
        <button
          type="button"
          onClick={onCreateSession}
          className="flex min-h-[220px] flex-col items-center justify-center rounded-lg border border-dashed border-blue-200 bg-blue-50/50 p-6 text-center text-blue-700 hover:bg-blue-50"
        >
          <Plus className="h-8 w-8" />
          <span className="mt-3 text-sm font-semibold">새 회기 생성</span>
          <span className="mt-1 text-xs text-blue-500">자료 입력부터 요약초안 생성까지 시작합니다.</span>
        </button>
      </div>
    </section>
  )
}

function CaseCard({ caseItem, onOpen }: { caseItem: CaseSummary; onOpen: () => void }) {
  const statusTone =
    caseItem.status === '종결'
      ? 'bg-emerald-50 text-emerald-700'
      : caseItem.status === '대기중'
        ? 'bg-orange-50 text-orange-700'
        : 'bg-blue-50 text-blue-700'
  const progressColor =
    caseItem.status === '종결' ? 'bg-emerald-500' : caseItem.status === '대기중' ? 'bg-orange-500' : 'bg-blue-600'

  return (
    <button
      type="button"
      onClick={onOpen}
      className="rounded-lg border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-slate-950">{caseItem.name}</h3>
          <p className="mt-1 text-xs text-slate-500">케이스 ID: {caseItem.id}</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusTone}`}>{caseItem.status}</span>
      </div>

      <dl className="mt-5 grid gap-3 text-sm">
        <CaseMeta label="상담 유형" value={caseItem.type} />
        <CaseMeta label="최근 회기" value={caseItem.lastDate} />
        <CaseMeta label="담당 상담사" value={caseItem.counselor} />
        <CaseMeta label="주요 이슈" value={caseItem.mainIssue} />
      </dl>

      <div className="mt-5 border-t border-slate-100 pt-4">
        <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
          <span>{caseItem.sessionCount}회기</span>
          <span className="font-medium text-blue-700">{caseItem.progressLabel}</span>
        </div>
        <div className="h-1.5 rounded-full bg-slate-100">
          <div className={`h-1.5 rounded-full ${progressColor}`} style={{ width: `${caseItem.progress}%` }} />
        </div>
      </div>
    </button>
  )
}

function CaseMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium text-slate-900">{value}</dd>
    </div>
  )
}

function SessionInputWorkspace({
  attachments,
  completedSteps,
  error,
  form,
  hasMaterials,
  hasSubmitted,
  isDeidentified,
  isLoading,
  onAddMaterial,
  onEditBasicInfo,
  onEditMaterial,
  onRemoveAttachment,
  onSetIsDeidentified,
  onSubmit,
  sessionTopic,
}: {
  attachments: AttachmentItem[]
  completedSteps: number
  error: string | null
  form: SessionInput
  hasMaterials: boolean
  hasSubmitted: boolean
  isDeidentified: boolean
  isLoading: boolean
  onAddMaterial: () => void
  onEditBasicInfo: () => void
  onEditMaterial: (mode: MaterialModalMode) => void
  onRemoveAttachment: (attachmentId: string) => void
  onSetIsDeidentified: (value: boolean) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  sessionTopic: string
}) {
  return (
    <form id="session-input-form" onSubmit={onSubmit} className="space-y-5">
      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-slate-500">회기 기본 정보</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-normal text-slate-950">{form.case_id}</h1>
          </div>
          <button
            type="button"
            onClick={onEditBasicInfo}
            className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <Edit3 className="h-4 w-4" />
            수정
          </button>
        </div>
        <dl className="mt-5 grid gap-3 sm:grid-cols-3">
          <InfoRow label="회기" value={`${form.session_number}회기`} />
          <InfoRow label="주제" value={sessionTopic || '미정'} />
          <InfoRow label="상담자" value={form.counselor_name || '미정'} />
        </dl>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-xl font-semibold tracking-normal">상담 자료</h2>
            <p className="mt-1 text-sm text-slate-500">이번 회기요약에 사용할 자료를 한 곳에서 관리합니다.</p>
          </div>
          <FileText className="h-5 w-5 text-blue-700" aria-hidden="true" />
        </div>

        {!hasMaterials ? (
          <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-12 text-center">
            <FileText className="mx-auto h-8 w-8 text-slate-400" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium text-slate-700">이번 회기요약에 사용할 자료를 추가해주세요.</p>
          </div>
        ) : (
          <div className="mt-6 divide-y divide-slate-100 rounded-lg border border-slate-200">
            {form.transcript_text.trim() && (
              <MaterialRow
                label="축어록/STT"
                meta={`${countCharacters(form.transcript_text)}자 입력됨`}
                actionLabel="열어서 수정"
                onAction={() => onEditMaterial('edit_transcript')}
              />
            )}
            {form.counselor_memo.trim() && (
              <MaterialRow
                label="상담사 메모"
                meta={`${countCharacters(form.counselor_memo)}자 입력됨`}
                actionLabel="열어서 수정"
                onAction={() => onEditMaterial('edit_memo')}
              />
            )}
            {form.previous_session_summary.trim() && (
              <MaterialRow
                label="이전 회기 요약"
                meta={`${Math.max(form.session_number - 1, 1)}회기 연결됨`}
                actionLabel="변경"
                onAction={() => onEditMaterial('edit_previous')}
              />
            )}
            {attachments.map((attachment) => (
              <MaterialRow
                key={attachment.id}
                label="첨부 파일"
                meta={attachment.name}
                actionLabel="삭제"
                onAction={() => onRemoveAttachment(attachment.id)}
              />
            ))}
          </div>
        )}

        <button
          type="button"
          onClick={onAddMaterial}
          className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          상담 자료 추가
        </button>

        <label className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-blue-100 bg-blue-50/70 px-3 py-3">
          <span className="flex items-center gap-2 text-sm font-medium text-slate-700">
            <ShieldCheck className="h-4 w-4 text-blue-700" />
            개인정보 비식별화
          </span>
          <input
            type="checkbox"
            checked={isDeidentified}
            onChange={(event) => onSetIsDeidentified(event.target.checked)}
            className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-600"
          />
        </label>
      </section>

      {hasSubmitted && (
        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-lg font-semibold">처리 상태</h2>
          {isLoading && <p className="mt-2 text-sm font-medium text-blue-700">구조화 → 회기요약 → 검증 진행 중...</p>}
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            {processSteps.map((step, index) => {
              const isDone = index < completedSteps
              const isActive = isLoading && index === completedSteps
              return (
                <div key={step} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm">
                  <span
                    className={`mb-2 flex h-7 w-7 items-center justify-center rounded-full border ${
                      isDone
                        ? 'border-blue-200 bg-blue-600 text-white'
                        : isActive
                          ? 'border-blue-200 bg-blue-50 text-blue-700'
                          : 'border-slate-200 bg-white text-slate-400'
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
                  <span className={isDone || isActive ? 'font-medium text-slate-900' : 'text-slate-500'}>{step}</span>
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
    </form>
  )
}

function SummaryDraftWorkspace({
  editingSectionId,
  expandedEvidenceId,
  form,
  onChangeContent,
  onEditSection,
  onToggleEvidence,
  sections,
}: {
  editingSectionId: DraftSectionId | null
  expandedEvidenceId: DraftSectionId | null
  form: SessionInput
  onChangeContent: (sectionId: DraftSectionId, content: string) => void
  onEditSection: (sectionId: DraftSectionId | null) => void
  onToggleEvidence: (sectionId: DraftSectionId) => void
  sections: DraftSection[]
}) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="rounded-t-lg bg-blue-600 px-6 py-5 text-white">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-blue-100">AI 초안 · 상담사 검토 전</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-normal">회기 요약 초안</h1>
            <p className="mt-2 text-sm text-blue-50">
              {form.case_id} / {form.session_number}회기 / {form.session_date} / 상담사: {form.counselor_name}
            </p>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-md bg-white px-3 py-2 text-sm font-semibold text-blue-700 shadow-sm hover:bg-blue-50"
          >
            <Edit3 className="h-4 w-4" />
            수정하기
          </button>
        </div>
      </div>

      <div className="px-6 py-4">
        <div className="rounded-lg bg-blue-50 px-4 py-3 text-sm text-slate-700">
          <Wand2 className="mr-2 inline h-4 w-4 text-blue-700" />
          각 항목을 클릭하면 바로 수정할 수 있습니다. 배지를 누르면 연결된 근거를 작게 확인할 수 있습니다.
        </div>
      </div>

      <div className="space-y-1 px-6 pb-8">
        {sections.length ? (
          sections.map((section) => (
            <DraftSectionBlock
              key={section.id}
              isEditing={editingSectionId === section.id}
              isEvidenceExpanded={expandedEvidenceId === section.id}
              section={section}
              onChangeContent={onChangeContent}
              onEditSection={onEditSection}
              onToggleEvidence={onToggleEvidence}
            />
          ))
        ) : (
          <div className="px-2 py-12 text-center text-sm text-slate-500">오른쪽 체크리스트에서 표시할 항목을 선택하세요.</div>
        )}
      </div>
    </section>
  )
}

function DraftSectionBlock({
  isEditing,
  isEvidenceExpanded,
  onChangeContent,
  onEditSection,
  onToggleEvidence,
  section,
}: {
  isEditing: boolean
  isEvidenceExpanded: boolean
  onChangeContent: (sectionId: DraftSectionId, content: string) => void
  onEditSection: (sectionId: DraftSectionId | null) => void
  onToggleEvidence: (sectionId: DraftSectionId) => void
  section: DraftSection
}) {
  return (
    <section className="border-b border-slate-200 py-5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="mr-1 text-base font-semibold text-blue-700">{section.title}</h2>
        {section.sourceBadges.map((badge) =>
          badge === 'editable' ? (
            <SourceBadge key={`${section.id}-${badge}`} type={badge} />
          ) : (
            <button key={`${section.id}-${badge}`} type="button" onClick={() => onToggleEvidence(section.id)}>
              <SourceBadge type={badge} />
            </button>
          ),
        )}
      </div>

      {isEvidenceExpanded && (
        <div className="mt-3 rounded-lg border border-blue-100 bg-blue-50/70 p-3">
          <EvidencePreview evidence={section.evidence} section={section} />
        </div>
      )}

      {isEditing ? (
        <textarea
          autoFocus
          value={section.content}
          onBlur={() => onEditSection(null)}
          onChange={(event) => onChangeContent(section.id, event.target.value)}
          className="mt-3 min-h-[120px] w-full resize-y rounded-md border border-blue-200 bg-white px-3 py-2 text-sm leading-6 text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
      ) : (
        <button
          type="button"
          onClick={() => section.editable && onEditSection(section.id)}
          className="mt-3 block w-full rounded-md px-2 py-2 text-left text-sm leading-6 text-slate-800 hover:bg-slate-50"
        >
          <span className="whitespace-pre-wrap">{section.content || '내용을 입력해주세요.'}</span>
        </button>
      )}
    </section>
  )
}

function EvidencePreview({ evidence, section }: { evidence: CompactEvidence[]; section: DraftSection }) {
  if (!evidence.length) {
    return (
      <p className="text-xs leading-5 text-amber-800">
        직접 연결된 원문 근거가 부족합니다. 이 항목은 상담사 확인 후 유지, 수정, 삭제 여부를 결정해주세요.
      </p>
    )
  }

  return (
    <div className="space-y-2">
      {evidence.map((item, index) => (
        <div key={`${section.id}-${item.label}-${index}`} className="text-xs leading-5 text-slate-700">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900">{item.label}</span>
            <span className="rounded-full bg-white px-2 py-0.5 text-slate-600 ring-1 ring-blue-100">
              신뢰도 {confidenceLabel[item.confidence]}
            </span>
            {item.needsReview && <span className="font-medium text-amber-700">상담사 확인 필요</span>}
          </div>
          <p className="mt-1 text-slate-600">{item.excerpt || '표시할 원문 일부가 없습니다.'}</p>
        </div>
      ))}
    </div>
  )
}

function DocumentTransformWorkspace({
  onCreateFinal,
  onSelectType,
  sections,
  selectedType,
}: {
  onCreateFinal: (documentType: FinalDocumentType) => void
  onSelectType: (documentType: FinalDocumentType) => void
  sections: DraftSection[]
  selectedType: FinalDocumentType
}) {
  const selectedTransform = transformOptions.find((option) => option.id === selectedType) || transformOptions[0]
  const availableCount = sections.filter((section) => section.visible && section.content.trim()).length

  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <p className="text-sm font-medium text-blue-700">확정된 회기요약 기반</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-normal text-slate-950">문서 변환</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
          요약초안에서 확인한 내용을 목적별 문서 초안으로 재구성합니다. V0에서는 부족한 정보와 상담사 직접 작성
          영역을 함께 표시합니다.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {transformOptions.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => onSelectType(option.id)}
            className={`rounded-lg border bg-white p-5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md ${
              selectedType === option.id ? 'border-blue-300 ring-2 ring-blue-100' : 'border-slate-200'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <FileText className="h-5 w-5" />
              </div>
              <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600">
                {option.badge}
              </span>
            </div>
            <h2 className="mt-4 text-lg font-semibold text-slate-950">{option.title}</h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">{option.description}</p>
          </button>
        ))}
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">{selectedTransform.title} 미리보기</h2>
            <p className="mt-1 text-sm text-slate-500">
              현재 요약초안에서 {availableCount}개 항목을 활용할 수 있습니다.
            </p>
          </div>
          <button
            type="button"
            onClick={() => onCreateFinal(selectedType)}
            className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
          >
            최종문서 생성
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <TransformInfoCard
            title="자동 반영 가능"
            items={sections
              .filter((section) => section.visible && section.id !== 'client_info')
              .slice(0, 5)
              .map((section) => section.title)}
          />
          <TransformInfoCard title="추가 확인 필요" items={selectedTransform.requiredFields} tone="warning" />
        </div>
      </section>
    </section>
  )
}

function TransformInfoCard({
  items,
  title,
  tone = 'default',
}: {
  items: string[]
  title: string
  tone?: 'default' | 'warning'
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        tone === 'warning' ? 'border-amber-200 bg-amber-50' : 'border-blue-100 bg-blue-50/70'
      }`}
    >
      <h3 className={`text-sm font-semibold ${tone === 'warning' ? 'text-amber-900' : 'text-blue-900'}`}>
        {title}
      </h3>
      <ul className={`mt-3 space-y-2 text-sm ${tone === 'warning' ? 'text-amber-800' : 'text-slate-700'}`}>
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function FinalDocumentWorkspace({
  documentType,
  form,
  missingItems,
  sections,
}: {
  documentType: FinalDocumentType
  form: SessionInput
  missingItems: string[]
  sections: DraftSection[]
}) {
  const documentMeta = finalDocumentMeta[documentType]
  const bodySections = buildFinalDocumentSections(documentType, sections, missingItems)

  return (
    <section className="rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="rounded-t-lg bg-blue-600 px-6 py-6 text-white">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-normal">{documentMeta.title}</h1>
            <p className="mt-2 text-sm text-blue-50">
              내담자: {form.case_id} / 회기:{form.session_number}회기 / 날짜:{form.session_date}
            </p>
          </div>
          <button
            type="button"
            className="inline-flex items-center gap-2 rounded-md bg-white px-3 py-2 text-sm font-semibold text-blue-700 shadow-sm hover:bg-blue-50"
          >
            <Edit3 className="h-4 w-4" />
            수정하기
          </button>
        </div>
      </div>

      <div className="px-6 py-4">
        <p className="rounded-md bg-blue-50 px-3 py-2 text-xs text-slate-600">
          하이라이트된 문장은 AI가 생성한 문장입니다. 상담사가 검토한 뒤 최종 문서로 사용하세요.
        </p>
      </div>

      <div className="space-y-7 px-6 pb-8">
        {bodySections.map((section) => (
          <section key={section.title}>
            <h2 className="border-b border-slate-200 pb-2 text-lg font-semibold text-blue-700">{section.title}</h2>
            {Array.isArray(section.content) ? (
              <ul className="mt-4 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-800">
                {section.content.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-800">{section.content}</p>
            )}
          </section>
        ))}
      </div>
    </section>
  )
}

function ReviewPanel({
  activeStep,
  checklistItems,
  currentScreen,
  isLoading,
  missingItems,
  onAddCustomSection,
  onGoBack,
  onGoToFinal,
  onGoToTransform,
  onToggleSection,
  resultReady,
  visibleSectionIds,
  warnings,
}: {
  activeStep: WorkflowStep
  checklistItems: ChecklistItem[]
  currentScreen: AppScreen
  isLoading: boolean
  missingItems: string[]
  onAddCustomSection: () => void
  onGoBack: () => void
  onGoToFinal: () => void
  onGoToTransform: () => void
  onToggleSection: (sectionId: DraftSectionId) => void
  resultReady: boolean
  visibleSectionIds: Set<DraftSectionId>
  warnings: string[]
}) {
  return (
    <aside className="h-fit rounded-lg border border-slate-200 bg-white p-5 shadow-sm xl:sticky xl:top-[92px]">
      {currentScreen === 'document_transform' ? (
        <DocumentTransformSidePanel />
      ) : (
        <>
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">{activeStep}</p>
            <h2 className="mt-2 text-lg font-semibold">요약에 포함할 항목</h2>
          </div>

          <div className="mt-4 space-y-2">
            {checklistItems.map((item) => {
              const checked = visibleSectionIds.has(item.id)
              return (
                <label
                  key={item.id}
                  className={`flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm font-medium ${
                    checked ? 'bg-blue-50 text-blue-700' : 'bg-slate-50 text-slate-500'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleSection(item.id)}
                    className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-600"
                  />
                  {item.title}
                </label>
              )
            })}
          </div>

          <button
            type="button"
            onClick={onAddCustomSection}
            disabled={!resultReady}
            className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
          >
            <Plus className="h-4 w-4" />
            항목 추가
          </button>
        </>
      )}

      {(missingItems.length > 0 || warnings.length > 0) && (
        <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 p-3">
          <h3 className="text-sm font-semibold text-amber-900">검토 필요</h3>
          <ul className="mt-2 space-y-1 text-xs leading-5 text-amber-800">
            {missingItems.slice(0, 3).map((item) => (
              <li key={`missing-${item}`}>· {item}</li>
            ))}
            {warnings.slice(0, 2).map((item) => (
              <li key={`warning-${item}`}>· {item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-10 space-y-2 border-t border-slate-100 pt-4">
        <button
          type="button"
          className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-500 hover:bg-slate-50"
        >
          <Save className="h-4 w-4" />
          임시저장
        </button>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={onGoBack}
            disabled={!resultReady}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-300"
          >
            <ArrowLeft className="h-4 w-4" />
            이전 단계
          </button>
          {currentScreen === 'document_transform' ? (
            <button
              type="button"
              onClick={onGoToFinal}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
            >
              다음 단계
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : resultReady ? (
            <button
              type="button"
              onClick={onGoToTransform}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
            >
              문서 변환
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="submit"
              form="session-input-form"
              disabled={isLoading}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              요약 초안 생성하기
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}

function DocumentTransformSidePanel() {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">문서변환</p>
      <h2 className="mt-2 text-lg font-semibold">변환 전 확인</h2>
      <div className="mt-4 space-y-3 text-sm">
        <div className="rounded-lg border border-blue-100 bg-blue-50 p-3">
          <p className="font-semibold text-blue-900">사용 가능한 자료</p>
          <ul className="mt-2 space-y-1 text-slate-700">
            <li>· 확정 전 회기요약 초안</li>
            <li>· 상담사 메모 기반 다음 계획</li>
            <li>· 근거 배지가 연결된 주요 항목</li>
          </ul>
        </div>
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="font-semibold text-amber-900">상담사 작성 필요</p>
          <ul className="mt-2 space-y-1 text-amber-800">
            <li>· 사례개념화</li>
            <li>· 슈퍼비전 요청사항</li>
            <li>· 목표 달성 정도</li>
          </ul>
        </div>
      </div>
    </div>
  )
}

function FinalReviewPanel({
  documentType,
  missingItems,
  onBack,
  warnings,
}: {
  documentType: FinalDocumentType
  missingItems: string[]
  onBack: () => void
  warnings: string[]
}) {
  return (
    <aside className="h-fit rounded-lg border border-slate-200 bg-white p-5 shadow-sm xl:sticky xl:top-[92px]">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">AI 검토</p>
        <h2 className="mt-2 text-lg font-semibold">보완 확인</h2>
        <p className="mt-1 text-sm leading-6 text-slate-500">
          {finalDocumentMeta[documentType].title}에서 상담사 확인이 필요한 항목입니다.
        </p>
      </div>

      <FinalReviewCard
        title="수정된 내용"
        items={['과제 수행 여부 확인 필요', '감정 변화 정도 추가 기록 권장', '다음 회기 목표 구체화 필요']}
      />
      <FinalReviewCard title="누락된 내용 확인" items={missingItems.slice(0, 3)} />
      <FinalReviewCard
        title="조언"
        items={warnings.length ? warnings.slice(0, 3) : ['상담사 검토 후 최종 기록으로 확정하세요.']}
      />

      <div className="mt-10 space-y-2 border-t border-slate-100 pt-4">
        <button
          type="button"
          className="inline-flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-500 hover:bg-slate-50"
        >
          <Save className="h-4 w-4" />
          임시저장
        </button>
        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex items-center justify-center gap-1 rounded-md border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-700 hover:bg-blue-50"
          >
            <ArrowLeft className="h-4 w-4" />
            이전 단계
          </button>
          <button
            type="button"
            className="inline-flex items-center justify-center gap-1 rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-700"
          >
            다운로드
          </button>
        </div>
      </div>
    </aside>
  )
}

function FinalReviewCard({ items, title }: { items: string[]; title: string }) {
  return (
    <section className="mt-5">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      <div className="mt-2 rounded-lg border border-slate-200 bg-white p-3">
        <ul className="space-y-1 text-sm leading-6 text-slate-700">
          {(items.length ? items : ['현재 표시할 항목이 없습니다.']).map((item) => (
            <li key={item}>· {item}</li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 truncate text-sm font-semibold text-slate-900">{value}</dd>
    </div>
  )
}

function MaterialRow({
  actionLabel,
  label,
  meta,
  onAction,
}: {
  actionLabel: string
  label: string
  meta: string
  onAction: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-900">{label}</p>
        <p className="mt-1 truncate text-xs text-slate-500">{meta}</p>
      </div>
      <button
        type="button"
        onClick={onAction}
        className="shrink-0 rounded-md border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
      >
        {actionLabel}
      </button>
    </div>
  )
}

function MaterialModal({
  form,
  mode,
  onAddAttachments,
  onClose,
  onModeChange,
  onUpdateField,
  onUpdateSessionTopic,
  sessionTopic,
}: {
  form: SessionInput
  mode: MaterialModalMode
  onAddAttachments: (files: FileList | null) => void
  onClose: () => void
  onModeChange: (mode: MaterialModalMode) => void
  onUpdateField: (field: keyof SessionInput, value: string | number) => void
  onUpdateSessionTopic: (value: string) => void
  sessionTopic: string
}) {
  const textModalConfig = getTextModalConfig(mode)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 px-4 py-6">
      <section className="max-h-[92vh] w-full max-w-lg overflow-auto rounded-lg bg-white shadow-xl">
        <div className="flex items-center justify-between gap-4 border-b border-slate-200 px-5 py-4">
          <h2 className="text-lg font-semibold text-slate-950">{modalTitle[mode]}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            aria-label="닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5">
          {mode === 'add' && (
            <div className="grid gap-3">
              <AddOption
                title="텍스트 붙여넣기"
                description="축어록이나 STT 텍스트를 붙여넣습니다."
                onClick={() => onModeChange('paste_text')}
              />
              <AddOption
                title="파일 업로드"
                description="상담 자료나 검사 결과 파일을 연결합니다."
                onClick={() => onModeChange('file_upload')}
              />
              <AddOption
                title="이전 회기 불러오기"
                description="이전 회기 요약을 현재 회기에 연결합니다."
                onClick={() => onModeChange('load_previous')}
              />
              <AddOption
                title="상담사 메모 작성"
                description="상담자가 직접 작성한 메모를 추가합니다."
                onClick={() => onModeChange('write_memo')}
              />
            </div>
          )}

          {mode === 'basic_info' && (
            <div className="space-y-4">
              <Field label="내담자 / 케이스" htmlFor="modal_case_id">
                <input
                  id="modal_case_id"
                  value={form.case_id}
                  onChange={(event) => onUpdateField('case_id', event.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="회기 번호" htmlFor="modal_session_number">
                <input
                  id="modal_session_number"
                  type="number"
                  min={1}
                  value={form.session_number}
                  onChange={(event) => onUpdateField('session_number', Number(event.target.value))}
                  className={inputClass}
                />
              </Field>
              <Field label="날짜" htmlFor="modal_session_date">
                <input
                  id="modal_session_date"
                  type="date"
                  value={form.session_date}
                  onChange={(event) => onUpdateField('session_date', event.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="상담자" htmlFor="modal_counselor_name">
                <input
                  id="modal_counselor_name"
                  value={form.counselor_name}
                  onChange={(event) => onUpdateField('counselor_name', event.target.value)}
                  className={inputClass}
                />
              </Field>
              <Field label="회기 주제" htmlFor="modal_session_topic">
                <input
                  id="modal_session_topic"
                  value={sessionTopic}
                  onChange={(event) => onUpdateSessionTopic(event.target.value)}
                  className={inputClass}
                />
              </Field>
              <ModalDoneButton onClick={onClose} />
            </div>
          )}

          {textModalConfig && (
            <TextMaterialEditor
              config={textModalConfig}
              form={form}
              onClose={onClose}
              onUpdateField={onUpdateField}
            />
          )}

          {mode === 'file_upload' && (
            <div className="space-y-4">
              <label className="block rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center">
                <FileText className="mx-auto h-7 w-7 text-slate-400" />
                <span className="mt-3 block text-sm font-medium text-slate-700">첨부할 파일 선택</span>
                <input
                  type="file"
                  multiple
                  className="sr-only"
                  onChange={(event) => {
                    onAddAttachments(event.target.files)
                    event.target.value = ''
                  }}
                />
              </label>
              <ModalDoneButton onClick={onClose} />
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

function AddOption({
  description,
  onClick,
  title,
}: {
  description: string
  onClick: () => void
  title: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-lg border border-slate-200 p-4 text-left hover:border-blue-200 hover:bg-blue-50"
    >
      <p className="font-semibold text-slate-900">{title}</p>
      <p className="mt-1 text-sm text-slate-500">{description}</p>
    </button>
  )
}

function TextMaterialEditor({
  config,
  form,
  onClose,
  onUpdateField,
}: {
  config: TextModalConfig
  form: SessionInput
  onClose: () => void
  onUpdateField: (field: keyof SessionInput, value: string | number) => void
}) {
  return (
    <div className="space-y-4">
      <Field label={config.label} htmlFor={`modal_${config.field}`}>
        <textarea
          id={`modal_${config.field}`}
          value={String(form[config.field] || '')}
          onChange={(event) => onUpdateField(config.field, event.target.value)}
          className={`${textareaClass} min-h-[260px]`}
          rows={10}
        />
      </Field>
      <ModalDoneButton onClick={onClose} />
    </div>
  )
}

function ModalDoneButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex w-full items-center justify-center rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800"
    >
      완료
    </button>
  )
}

function Field({ children, htmlFor, label }: { children: ReactNode; htmlFor: string; label: string }) {
  return (
    <label htmlFor={htmlFor} className="block">
      <span className="text-sm font-medium text-slate-700">{label}</span>
      {children}
    </label>
  )
}

function SourceBadge({ type }: { type: SourceBadgeKind }) {
  const badge = sourceBadgeMeta[type]
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-medium ring-1 ${badge.className}`}>{badge.label}</span>
  )
}

function buildDocumentSections(
  result: NoteDraftResponse,
  form: SessionInput,
  sessionTopic: string,
  visibleSectionIds: Set<DraftSectionId>,
): DraftSection[] {
  const evidenceItems = Array.isArray(result.evidence_check) ? result.evidence_check : []
  const makeSection = ({
    content,
    id,
    title,
    baseEvidence = findEvidenceForSection(content, evidenceItems),
    forceBadges = [],
    toggleable = true,
  }: {
    baseEvidence?: EvidenceCheckItem[]
    content: string
    forceBadges?: SourceBadgeKind[]
    id: DraftSectionId
    title: string
    toggleable?: boolean
  }): DraftSection => {
    const compactEvidence = baseEvidence.map(toCompactEvidence)
    const sourceBadges = buildSourceBadges(baseEvidence, forceBadges)
    const confidence = buildSectionConfidence(baseEvidence)

    return {
      id,
      title,
      content,
      sourceBadges,
      confidence,
      evidence: compactEvidence,
      visible: !toggleable || visibleSectionIds.has(id),
      editable: true,
      toggleable,
    }
  }

  const sessionThemeEvidence: EvidenceCheckItem[] = form.counselor_memo
    ? [
        {
          claim: sessionTopic,
          source_type: 'counselor_memo',
          source_excerpt: form.counselor_memo,
          confidence: 'medium',
        },
      ]
    : []

  return [
    makeSection({
      id: 'client_info',
      title: '내담자 정보',
      content: `${form.case_id} / ${form.session_number}회기 / ${form.session_date} / 상담사: ${form.counselor_name}`,
      baseEvidence: [],
      forceBadges: ['editable'],
      toggleable: false,
    }),
    makeSection({
      id: 'main_issue',
      title: '주호소 / 주요 이슈',
      content: result.main_issue || '입력 자료에서 주호소를 확인해 주세요.',
    }),
    makeSection({
      id: 'session_theme',
      title: '회기 주제',
      content: sessionTopic || '회기 주제를 입력해 주세요.',
      baseEvidence: sessionThemeEvidence,
    }),
    makeSection({
      id: 'session_content',
      title: '상담 내용',
      content: result.session_summary || '생성된 상담 내용 요약이 없습니다.',
      baseEvidence: evidenceItems.length ? evidenceItems : [],
    }),
    makeSection({
      id: 'counselor_intervention',
      title: '상담자 개입',
      content: result.counselor_intervention || '상담자 개입 내용을 확인해 주세요.',
    }),
    makeSection({
      id: 'client_response',
      title: '내담자 반응',
      content: result.client_response || '내담자 반응을 상담사가 확인해 주세요.',
      forceBadges: ['needs_review'],
    }),
    makeSection({
      id: 'next_plan',
      title: '다음 계획',
      content: result.next_plan || '다음 회기 계획을 입력해 주세요.',
    }),
    makeSection({
      id: 'risk_signal',
      title: '위험 신호',
      content: '입력 자료에서 직접 확인된 위험 신호는 없습니다. 필요 시 상담사가 별도로 확인해 주세요.',
      baseEvidence: [],
      forceBadges: ['ai', 'needs_review'],
    }),
    makeSection({
      id: 'supervision_memo',
      title: '슈퍼비전 메모',
      content: '슈퍼비전 메모는 상담사가 직접 작성하거나 확정해야 합니다.',
      baseEvidence: [],
      forceBadges: ['ai', 'needs_review'],
    }),
  ]
}

function findEvidenceForSection(content: string, evidenceItems: EvidenceCheckItem[]): EvidenceCheckItem[] {
  const normalizedContent = normalizeText(content)
  if (!normalizedContent) return []

  const exactMatches = evidenceItems.filter((item) => normalizeText(item.claim) === normalizedContent)
  if (exactMatches.length) return exactMatches

  return evidenceItems.filter((item) => {
    const claim = normalizeText(item.claim)
    return claim.length > 12 && (normalizedContent.includes(claim) || claim.includes(normalizedContent))
  })
}

function buildSourceBadges(evidence: EvidenceCheckItem[], forceBadges: SourceBadgeKind[] = []): SourceBadgeKind[] {
  const badges = new Set<SourceBadgeKind>(forceBadges)

  evidence.forEach((item) => {
    badges.add(sourceTypeToBadge[item.source_type])
    if (item.source_type === 'ai_inference' || item.confidence === 'low') {
      badges.add('needs_review')
    }
  })

  if (!evidence.length && !forceBadges.length) {
    badges.add('ai')
  }
  badges.add('editable')

  return Array.from(badges)
}

function buildSectionConfidence(evidence: EvidenceCheckItem[]): EvidenceConfidence {
  if (!evidence.length) return 'low'
  if (evidence.some((item) => item.confidence === 'low' || item.source_type === 'ai_inference')) return 'low'
  if (evidence.some((item) => item.confidence === 'medium')) return 'medium'
  return 'high'
}

function toCompactEvidence(item: EvidenceCheckItem): CompactEvidence {
  return {
    label: sourceTypeLabel[item.source_type],
    excerpt: item.source_excerpt,
    confidence: item.confidence,
    needsReview: item.source_type === 'ai_inference' || item.confidence !== 'high',
  }
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function countCharacters(value: string): number {
  return value.replace(/\s/g, '').length
}

function getActiveStep(screen: AppScreen): WorkflowStep {
  if (screen === 'document_transform') return '문서변환'
  if (screen === 'final_document') return '최종문서'
  if (screen === 'summary_draft') return '요약초안'
  return '회기입력'
}

function buildFinalDocumentSections(
  documentType: FinalDocumentType,
  sections: DraftSection[],
  missingItems: string[],
): Array<{ title: string; content: string | string[] }> {
  const getSection = (id: DraftSectionId, fallback: string) =>
    sections.find((section) => section.id === id)?.content || fallback

  if (documentType === 'supervision_report') {
    return [
      {
        title: '주요 호소',
        content: [
          getSection('main_issue', '주요 호소 내용을 상담사가 확인해야 합니다.'),
          '진로 및 취업 준비 과정에서의 불안과 자기비난 사고를 중심으로 보고함.',
        ],
      },
      {
        title: '상담 내용',
        content: getSection('session_content', '상담 내용을 확인해야 합니다.'),
      },
      {
        title: '상담사 개입',
        content: [
          getSection('counselor_intervention', '상담자 개입 내용을 확인해야 합니다.'),
          '자동사고와 감정 반응의 연결을 탐색하는 방향으로 진행함.',
        ],
      },
      {
        title: '슈퍼비전 요청사항',
        content:
          '내담자의 자기비난 사고를 다룰 때 정서 확인과 행동 계획 사이의 균형을 어떻게 잡을지 슈퍼비전에서 논의가 필요합니다.',
      },
      {
        title: '추가 확인 필요',
        content: missingItems.length ? missingItems : ['가족관계, 심리검사 결과, 상담 목표 달성 정도 확인 필요'],
      },
    ]
  }

  if (documentType === 'termination_report') {
    return [
      { title: '상담 목표 및 진행 과정', content: getSection('session_content', '상담 진행 과정을 확인해야 합니다.') },
      { title: '주요 변화', content: getSection('client_response', '내담자 변화 내용을 상담사가 확인해야 합니다.') },
      { title: '종결 사유', content: '종결 사유는 상담사가 직접 입력해야 합니다.' },
      { title: '향후 권고', content: getSection('next_plan', '향후 권고 사항을 확인해야 합니다.') },
      { title: '상담자 종합소견', content: '상담자 종합소견은 임상 판단 영역이므로 직접 작성이 필요합니다.' },
    ]
  }

  return [
    { title: '주요 호소', content: getSection('main_issue', '주요 호소 내용을 확인해야 합니다.') },
    { title: '상담 내용', content: getSection('session_content', '상담 내용을 확인해야 합니다.') },
    { title: '상담사 개입', content: getSection('counselor_intervention', '상담자 개입 내용을 확인해야 합니다.') },
    { title: '내담자 반응', content: getSection('client_response', '내담자 반응을 확인해야 합니다.') },
    { title: '다음 계획', content: getSection('next_plan', '다음 계획을 확인해야 합니다.') },
  ]
}

interface TextModalConfig {
  field: keyof Pick<SessionInput, 'transcript_text' | 'counselor_memo' | 'previous_session_summary'>
  label: string
}

const modalTitle: Record<MaterialModalMode, string> = {
  add: '상담 자료 추가',
  basic_info: '회기 기본 정보 수정',
  paste_text: '텍스트 붙여넣기',
  file_upload: '파일 업로드',
  load_previous: '이전 회기 불러오기',
  write_memo: '상담사 메모 작성',
  edit_transcript: '축어록/STT 수정',
  edit_memo: '상담사 메모 수정',
  edit_previous: '이전 회기 요약 변경',
}

const transformOptions: Array<{
  badge: string
  description: string
  id: FinalDocumentType
  requiredFields: string[]
  title: string
}> = [
  {
    id: 'session_note',
    title: '회기 기록지',
    badge: '즉시 생성',
    description: '확정된 회기요약 초안을 상담 기록지 형태로 정리합니다.',
    requiredFields: ['위험 신호 확인', '목표 달성 정도', '상담자 최종 확인'],
  },
  {
    id: 'supervision_report',
    title: '슈퍼비전 보고서',
    badge: '일부 미리보기',
    description: '회기요약을 바탕으로 슈퍼비전 보고서 초안을 구성합니다.',
    requiredFields: ['내담자 기본 정보', '상담신청경위', '가족관계', '사례개념화', '슈퍼비전 요청사항'],
  },
  {
    id: 'termination_report',
    title: '종결 보고서',
    badge: '확장 후보',
    description: '여러 회기 요약을 종결 보고서 형식으로 정리하는 화면입니다.',
    requiredFields: ['전체 회기 목록', '종결 사유', '목표 달성 정도', '향후 권고'],
  },
]

const finalDocumentMeta: Record<FinalDocumentType, { title: string }> = {
  session_note: { title: '회기 기록지' },
  supervision_report: { title: '슈퍼비전 보고서' },
  termination_report: { title: '종결 보고서' },
}

function getTextModalConfig(mode: MaterialModalMode): TextModalConfig | null {
  if (mode === 'paste_text' || mode === 'edit_transcript') {
    return { field: 'transcript_text', label: '축어록/STT 텍스트' }
  }
  if (mode === 'write_memo' || mode === 'edit_memo') {
    return { field: 'counselor_memo', label: '상담사 메모' }
  }
  if (mode === 'load_previous' || mode === 'edit_previous') {
    return { field: 'previous_session_summary', label: '이전 회기 요약' }
  }
  return null
}

const inputClass =
  'mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100'

const textareaClass =
  'mt-1 w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-100'

const sourceTypeToBadge: Record<EvidenceSourceType, SourceBadgeKind> = {
  transcript: 'transcript',
  counselor_memo: 'memo',
  previous_summary: 'previous',
  ai_inference: 'ai',
}

const sourceTypeLabel: Record<EvidenceSourceType, string> = {
  transcript: '축어록/STT',
  counselor_memo: '상담사 메모',
  previous_summary: '이전 회기 요약',
  ai_inference: 'AI 추론',
}

const sourceBadgeMeta: Record<SourceBadgeKind, { className: string; label: string }> = {
  memo: { label: '메모 기반', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  transcript: { label: '축어록 기반', className: 'bg-blue-50 text-blue-700 ring-blue-200' },
  previous: { label: '이전 회기 기반', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  attachment: { label: '첨부자료 기반', className: 'bg-violet-50 text-violet-700 ring-violet-200' },
  ai: { label: 'AI 생성', className: 'bg-amber-50 text-amber-700 ring-amber-200' },
  editable: { label: '수정 가능', className: 'bg-slate-100 text-slate-600 ring-slate-200' },
  needs_review: { label: '확인 필요', className: 'bg-rose-50 text-rose-700 ring-rose-200' },
}

const confidenceLabel: Record<EvidenceConfidence, string> = {
  high: '높음',
  medium: '중간',
  low: '낮음',
}
