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
  History,
  Loader2,
  Plus,
  RefreshCcw,
  Save,
  Search,
  Send,
  ShieldCheck,
  User,
  X,
} from 'lucide-react'
import { generateNoteDraft } from '../api/client'
import type {
  EvidenceCheckItem,
  EvidenceConfidence,
  EvidenceSourceType,
  GenerateNoteResponse,
  NoteDraftResponse,
  SessionInput,
} from '../types/session'

const workflowSteps = ['회기입력', '회기요약', '문서변환', '최종문서'] as const
const processSteps = ['입력 정제', '상담 내용 구조화', '근거 연결', '회기요약 생성', '검증 리포트 생성']

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
  | 'write_test'
  | 'edit_transcript'
  | 'edit_memo'
  | 'edit_previous'
  | 'edit_test'

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

interface PreviousSessionOption {
  id: string
  label: string
  date: string
  summary: string
  detail: string
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
  { id: 'psychological_test', title: '심리검사 요약' },
  { id: 'risk_signal', title: '위험 신호' },
  { id: 'supervision_memo', title: '슈퍼비전 메모' },
]

const defaultVisibleSectionIds = new Set<DraftSectionId>(defaultChecklistItems.map((item) => item.id))

const previousSessionOptions: PreviousSessionOption[] = [
  {
    id: 'session-1',
    label: '1회기',
    date: '2026. 04. 26',
    summary: "진로 결정과 졸업 준비 불안을 주호소로 보고. '남들보다 늦은 것 같다'는 걱정 확인.",
    detail:
      "내담자는 대학 4학년으로 진로 결정과 졸업 준비 과정에서 불안이 높아졌다고 보고함. 주호소는 '남들보다 늦은 것 같다', '결정을 잘못하면 끝날 것 같다'는 걱정이었음. 상담 목표는 진로 선택 과정에서 자기비난을 줄이고 실행 가능한 준비 행동을 세우는 것으로 잠정 합의함.",
  },
  {
    id: 'session-2',
    label: '2회기',
    date: '2026. 05. 03',
    summary: "채용 공고를 볼 때 떠오르는 '자격이 부족하다'는 자동사고와 회피 행동 탐색.",
    detail:
      "취업 준비 상황에서 반복되는 자동사고를 탐색함. 내담자는 채용 공고를 볼 때 '나는 자격이 부족하다', '지원해도 떨어질 것이다'라는 생각이 빠르게 떠오른다고 말함. 상담자는 생각기록지 형식으로 상황, 자동사고, 감정 강도, 행동을 구분하도록 안내함.",
  },
  {
    id: 'session-3',
    label: '3회기',
    date: '2026. 05. 10',
    summary: "가족 기대와 비교 경험을 다룸. '잘해야 사랑받는다'는 기준과 불안의 연결 확인.",
    detail:
      "가족의 기대와 비교 경험을 다룸. 내담자는 부모가 직접 압박하지 않아도 가족 모임에서 친척의 취업 이야기가 나오면 위축된다고 표현함. 어린 시절부터 '잘해야 사랑받는다'는 기준이 강했다고 말함. 상담자는 완벽주의적 기준과 현재 진로 불안의 연결 가능성을 조심스럽게 확인함.",
  },
  {
    id: 'session-4',
    label: '4회기',
    date: '2026. 05. 17',
    summary: '회피 행동과 수면 리듬 점검. 작은 과제 실행 전후 불안 점수를 기록하기로 함.',
    detail:
      '회피 행동과 수면 리듬을 다룸. 내담자는 불안이 높을 때 채용 사이트와 팀 프로젝트 단톡을 피하고, 밤늦게 유튜브를 보다가 잠드는 일이 늘었다고 보고함. 상담자는 회피가 단기적으로 불안을 낮추지만 다음 날 부담을 키울 수 있음을 함께 정리함. 다음 회기까지 작은 과제 하나를 정해 실행 전후 불안 점수를 기록해보기로 함.',
  },
]

const defaultPreviousSessionIds = ['session-1', 'session-2', 'session-3', 'session-4']
const demoClientName = '가명 은하'

function buildPreviousSessionSummary(selectedIds: string[]): string {
  return previousSessionOptions
    .filter((session) => selectedIds.includes(session.id))
    .map((session) => `${session.label} (${session.date}): ${session.detail}`)
    .join('\n')
}

const caseSummaries: CaseSummary[] = [
  {
    id: 'CASE-DEMO-001',
    name: '가명 은하',
    type: '대학생 상담',
    lastDate: '2026. 05. 24',
    counselor: '박상담사',
    mainIssue: '진로불안, 자기비난, 회피행동',
    status: '진행중',
    sessionCount: 5,
    progressLabel: '8회 목표',
    progress: 62,
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
  case_id: 'CASE-DEMO-001',
  session_number: 5,
  session_date: '2026-05-24',
  counselor_name: '박상담사',
  counselor_memo:
    "5회기는 지난주 팀 프로젝트 발표 이후 악화된 비교 사고와 회피 행동을 중심으로 진행함. 내담자는 발표에서 말을 더듬은 장면을 반복적으로 떠올리며 '나는 항상 중요한 순간에 망친다'고 표현함. 상담자는 사건-생각-감정-행동을 분리해서 확인하고, 자동사고의 근거와 반대 근거를 함께 탐색함. 내담자는 초반에는 눈물이 있었고 시선 회피가 많았으나, 후반에는 이번 주에 교수님께 질문 하나를 이메일로 보내고 팀원 한 명에게 역할 조율 메시지를 보내보겠다고 말함. 다음 회기에는 실제 실행 여부와 실행 전후 불안 강도 변화를 확인하기로 함.",
  transcript_text:
    "C: 지난 회기 이후 가장 많이 마음에 남았던 장면이 있었나요?\nCl: 팀 프로젝트 발표요. 제가 중간에 말을 버벅였는데 그 장면이 계속 떠올라요. 다른 사람들은 그냥 넘어갔을 수도 있는데 저는 계속 망했다는 생각이 들어요.\nC: 그때 머릿속에 가장 먼저 떠오른 문장은 뭐였나요?\nCl: '나는 항상 중요한 순간에 망친다'였어요. 그리고 교수님도 제가 준비 안 된 사람이라고 생각했을 것 같았어요.\nC: 그 생각이 들었을 때 감정은 어느 정도였나요?\nCl: 불안이 80 정도였고 창피함도 컸어요. 집에 와서는 팀원 단톡도 안 봤어요.\nC: 단톡을 안 봤을 때 잠깐은 불안이 줄었나요?\nCl: 네. 근데 다음 날 더 커졌어요. 제가 또 피하고 있다는 생각이 들었어요.\nC: 오늘은 그 장면을 사건, 생각, 감정, 행동으로 나눠서 보겠습니다. 실제로 확인된 사실과 추측이 섞인 부분을 구분해볼게요.\nCl: 사실은 제가 한 문장을 다시 말한 거고, 사람들이 뭐라고 한 건 없었어요. 추측은 교수님이 실망했을 거라는 거네요.\nC: 그렇게 구분해보니 문장이 조금 달라지나요?\nCl: '완전히 망했다'까지는 아닐 수도 있겠어요. 그냥 긴장해서 잠깐 멈춘 정도였을 수도요.\nC: 이번 주에는 회피를 조금 줄이는 작은 행동을 정해볼까요?\nCl: 교수님께 질문 하나 이메일로 보내보고, 팀원 한 명에게 제가 맡은 부분 다시 확인하겠다고 말해볼게요.\nC: 실행 전후 불안 점수를 적어오면 다음 회기에서 같이 확인해볼 수 있겠습니다.",
  previous_session_summary: buildPreviousSessionSummary(defaultPreviousSessionIds),
  counseling_goal:
    '진로 선택과 수행평가 상황에서 나타나는 자기비난적 자동사고를 알아차리고, 회피를 줄이는 작은 실행 행동을 늘린다.',
  psychological_test_summary:
    '초기 면담 단계에서 실시한 간이 진로흥미검사 메모상 사회형/탐구형 흥미가 상대적으로 높았고, 자기보고식 불안 체크에서는 수행평가 상황과 비교 상황에서 불안이 높게 보고됨. 정식 진단 목적의 검사는 아니며 상담 목표 설정을 위한 참고 자료로 기록함.',
  key_issue_tags: ['진로불안', '자기비난', '비교사고', '회피행동', '수행불안'],
  nonverbal_notes:
    "발표 장면을 말할 때 눈물이 고였고 시선을 아래로 둠. '완전히 망했다'고 말할 때 목소리가 작아졌음. 후반부에 실행 과제를 정할 때는 고개를 끄덕이고 말의 속도가 안정됨.",
}

export default function SessionDraftPage() {
  const [currentScreen, setCurrentScreen] = useState<AppScreen>('session_input')
  const [form, setForm] = useState<SessionInput>(initialForm)
  const [sessionTopic, setSessionTopic] = useState('발표 이후 비교사고와 회피 행동 점검')
  const [finalDocumentType, setFinalDocumentType] = useState<FinalDocumentType>('session_note')
  const [isDeidentified, setIsDeidentified] = useState(true)
  const [attachments, setAttachments] = useState<AttachmentItem[]>([])
  const [selectedPreviousSessionIds, setSelectedPreviousSessionIds] = useState<string[]>(defaultPreviousSessionIds)
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
      form.psychological_test_summary?.trim() ||
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

  const togglePreviousSession = (sessionId: string) => {
    setSelectedPreviousSessionIds((prev) => {
      const next = prev.includes(sessionId)
        ? prev.filter((id) => id !== sessionId)
        : [...prev, sessionId]
      setForm((current) => ({
        ...current,
        previous_session_summary: buildPreviousSessionSummary(next),
      }))
      return next
    })
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
    <main className="min-h-screen bg-[#f3f5f9] text-slate-950">
      <AppSidebar activeScreen={currentScreen} onOpenCaseList={openCaseList} onOpenSessionInput={openSessionInput} />

      <div className="min-h-screen lg:pl-[260px]">
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
              setForm((prev) => ({ ...prev, case_id: 'CASE-DEMO-001', session_number: 5 }))
              setCurrentScreen(result ? 'summary_draft' : 'session_input')
            }}
          />
        ) : (
          <div
            className={
              currentScreen === 'document_transform'
                ? 'px-0 py-0'
                : 'grid min-h-[calc(100vh-68px)] xl:grid-cols-[minmax(0,1fr)_354px]'
            }
          >
            <section className={currentScreen === 'document_transform' ? 'min-w-0' : 'min-w-0 px-5 py-5'}>
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
                  preview={result.full_response?.document_transform_preview}
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

            {currentScreen === 'document_transform' ? null : currentScreen === 'final_document' ? (
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
                fullResponse={result?.full_response}
                isLoading={isLoading}
                missingItems={result?.missing_items || []}
                selectedPreviousSessionIds={selectedPreviousSessionIds}
                resultReady={Boolean(result)}
                visibleSectionIds={visibleSectionIds}
                warnings={result?.warnings || []}
                onAddCustomSection={addCustomSection}
                onGoBack={goBackToInput}
                onGoToFinal={() => openFinalDocument()}
                onGoToTransform={openDocumentTransform}
                onTogglePreviousSession={togglePreviousSession}
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
    <aside className="border-slate-200 bg-white lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:w-[260px] lg:border-r">
      <div className="flex h-full flex-col">
        <div className="border-b border-slate-100 px-8 py-5">
          <p className="text-[32px] font-extrabold leading-none tracking-normal text-transparent bg-clip-text bg-gradient-to-r from-sky-300 to-blue-700">
            Re:mind
          </p>
        </div>

        <div className="space-y-5 px-5 py-4">
          <label className="flex h-11 items-center gap-3 rounded-md border border-slate-200 bg-white px-4 text-sm text-slate-500 shadow-sm">
            <Search className="h-5 w-5" />
            <input
              className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-slate-400"
              placeholder="내담자/케이스 검색"
            />
          </label>

          <nav className="space-y-2 text-sm">
            <p className="px-1 text-xs font-medium text-slate-400">메뉴</p>
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

          <div className="space-y-3 border-t border-slate-200 pt-5">
            <p className="px-1 text-xs font-medium text-slate-400">최근 케이스</p>
            <CaseListItem name="가명 은하" status="진행중" meta="대학생 · 5회기" active />
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
      className={`flex h-10 w-full items-center gap-2 rounded-md px-3 text-left font-semibold ${
        active ? 'bg-blue-50 text-blue-700' : 'text-slate-800 hover:bg-slate-50'
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
      className={`w-full rounded-md px-4 py-3 text-left text-sm ${
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
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
      <div className="flex min-h-[68px] items-center justify-between gap-4 px-10">
        {currentScreen === 'case_list' ? (
          <div />
        ) : (
          <nav className="flex flex-wrap items-center gap-4 text-sm">
            {workflowSteps.map((step, index) => {
              const StepIcon =
                step === '회기입력' ? Edit3 : step === '회기요약' ? ClipboardList : step === '문서변환' ? FolderOpen : FileText
              return (
                <button
                  key={step}
                  type="button"
                  className="flex items-center gap-4"
                  onClick={() => {
                    if (step === '회기입력') onOpenSessionInput()
                  }}
                >
                  <span
                    className={`inline-flex items-center gap-1.5 font-semibold ${
                      index === activeIndex
                        ? 'text-blue-700'
                        : index < activeIndex
                          ? 'text-slate-600'
                          : 'text-slate-500'
                    }`}
                  >
                    <StepIcon className="h-5 w-5" />
                    {step}
                  </span>
                  {index < workflowSteps.length - 1 && <ChevronRight className="h-4 w-4 text-slate-500" />}
                </button>
              )
            })}
          </nav>
        )}

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenCaseList}
            className="inline-flex h-11 items-center gap-2 rounded-md border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <ClipboardList className="h-4 w-4" />
            목록으로
          </button>
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
    <section className="px-9 py-7">
      <div className="mb-9 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-extrabold tracking-normal text-black">케이스 목록</h2>
        </div>
        <div className="flex items-center gap-5">
        <div className="flex gap-5 text-sm">
          {['전체', '진행중', '종결', '대기중'].map((filter, index) => (
            <button
              key={filter}
              type="button"
              className={`h-9 rounded-full px-5 font-bold shadow-sm ${
                index === 0 ? 'bg-blue-600 text-white' : 'bg-white text-black hover:bg-slate-50'
              }`}
            >
              {filter}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onCreateSession}
          className="inline-flex h-11 items-center gap-2 rounded-md bg-blue-600 px-5 text-base font-bold text-white shadow-sm hover:bg-blue-700"
        >
          <Plus className="h-5 w-5" />
          새 회기 생성
        </button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-2 2xl:grid-cols-3">
        {cases.map((caseItem) => (
          <CaseCard key={caseItem.id} caseItem={caseItem} onOpen={() => onOpenCase(caseItem)} />
        ))}
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
      className="min-h-[292px] rounded-[16px] border border-slate-200 bg-white p-8 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-2xl font-extrabold text-black">{caseItem.name}</h3>
          <p className="mt-1 text-xs text-slate-500">케이스 ID: {caseItem.id}</p>
        </div>
        <span className={`rounded-full px-3 py-1 text-sm font-bold ${statusTone}`}>{caseItem.status}</span>
      </div>

      <dl className="mt-5 grid gap-4 text-base">
        <CaseMeta label="상담 유형" value={caseItem.type} />
        <CaseMeta label="최근 회기" value={caseItem.lastDate} />
        <CaseMeta label="담당 상담사" value={caseItem.counselor} />
        <CaseMeta label="주요 이슈" value={caseItem.mainIssue} />
      </dl>

      <div className="mt-7 border-t border-slate-200 pt-5">
        <div className="mb-2 flex items-center justify-between text-base font-bold text-slate-500">
          <span>{caseItem.sessionCount}회기</span>
          <span className="text-blue-700">{caseItem.progressLabel}</span>
        </div>
        <div className="h-4 rounded-full bg-slate-100">
          <div className={`h-4 rounded-full ${progressColor}`} style={{ width: `${caseItem.progress}%` }} />
        </div>
      </div>
    </button>
  )
}

function CaseMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[88px_1fr] gap-5">
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-extrabold text-black">{value}</dd>
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
      <section className="rounded-[16px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <User className="h-5 w-5 text-blue-700" />
              <p className="text-xl font-bold tracking-normal text-slate-950">내담자 / 회기 기본 정보</p>
            </div>
            <h1 className="mt-5 text-2xl font-bold tracking-normal text-slate-950">{demoClientName}</h1>
          </div>
          <button
            type="button"
            onClick={onEditBasicInfo}
            className="inline-flex h-9 items-center gap-1 rounded-md border border-slate-200 bg-white px-3 text-sm font-medium text-slate-500 hover:bg-slate-50"
          >
            <Edit3 className="h-4 w-4" />
            수정하기
          </button>
        </div>
        <dl className="mt-5 grid gap-7 sm:grid-cols-[180px_minmax(0,1fr)_180px]">
          <InfoRow label="회기" value={`${form.session_number}회기`} />
          <InfoRow label="회기 주제" value={sessionTopic || '미정'} />
          <InfoRow label="날짜" value={form.session_date || '미정'} />
        </dl>
      </section>

      <section className="rounded-[16px] border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <FolderOpen className="h-5 w-5 text-blue-700" />
              <h2 className="text-xl font-bold tracking-normal">상담 자료</h2>
            </div>
            <p className="mt-4 text-sm text-slate-500">이번 회기 요약에 사용할 자료를 한 곳에서 관리합니다.</p>
          </div>
        </div>

        {!hasMaterials ? (
          <div className="mt-6 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-12 text-center">
            <FileText className="mx-auto h-8 w-8 text-slate-400" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium text-slate-700">이번 회기요약에 사용할 자료를 추가해주세요.</p>
          </div>
        ) : (
          <div className="mt-6 divide-y divide-slate-200 rounded-lg border border-slate-300 bg-white">
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
            {form.psychological_test_summary?.trim() && (
              <MaterialRow
                label="심리검사 메모"
                meta={`${countCharacters(form.psychological_test_summary || '')}자 입력됨`}
                actionLabel="열어서 수정"
                onAction={() => onEditMaterial('edit_test')}
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
          className="mt-6 inline-flex h-12 w-[58%] items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-base font-bold text-white shadow-sm hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          상담 자료 추가
        </button>

        <label className="mt-6 inline-flex h-12 w-[38%] items-center justify-between gap-3 rounded-md bg-blue-50 px-5 align-top text-blue-700 ml-5">
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
        <section className="rounded-[16px] border border-slate-200 bg-white p-6 shadow-sm">
          <div className="flex items-center gap-2">
            <RefreshCcw className="h-5 w-5 text-blue-700" />
            <h2 className="text-xl font-bold">처리 상태</h2>
          </div>
          {isLoading && <p className="mt-2 text-sm font-medium text-blue-700">구조화 → 회기요약 → 검증 진행 중...</p>}
          <div className="mt-5 grid gap-3 md:grid-cols-5">
            {processSteps.map((step, index) => {
              const isDone = index < completedSteps
              const isActive = isLoading && index === completedSteps
              return (
                <div
                  key={step}
                  className={`flex h-10 items-center gap-2 rounded-md border px-3 text-sm font-semibold ${
                    isDone || isActive ? 'border-blue-600 bg-blue-50 text-blue-800' : 'border-slate-200 bg-slate-50 text-slate-500'
                  }`}
                >
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${
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
                  <span className="truncate">{step}</span>
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
    <section className="space-y-4">
      <div className="rounded-[12px] border border-slate-200 bg-white px-5 py-4 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-900 text-sm font-bold text-white">i</span>
          <div>
            <p className="font-bold text-slate-900">AI 초안이 생성되었습니다.</p>
            <p className="mt-1 text-sm font-semibold text-slate-700">
              근거가 연결된 항목을 확인하고, 상담사 판단이 필요한 문장을 검토해 주세요.
            </p>
          </div>
        </div>
      </div>

      <article className="overflow-hidden rounded-[12px] border border-slate-200 bg-white shadow-sm">
      <div className="bg-blue-600 px-6 py-5 text-white">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <ChevronRight className="h-8 w-8 rotate-180" />
              <h1 className="text-3xl font-bold tracking-normal">회기 요약</h1>
            </div>
            <p className="mt-3 text-base font-bold text-blue-50">
              {form.case_id} · {form.session_number}회기 · {form.session_date}
            </p>
          </div>
          <button
            type="button"
            className="inline-flex h-11 items-center gap-2 rounded-md bg-white px-8 text-lg font-bold text-blue-700 shadow-sm hover:bg-blue-50"
          >
            <Edit3 className="h-4 w-4" />
            수정하기
          </button>
        </div>
      </div>

      <div className="space-y-1 px-7 py-7">
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
      </article>
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
    <section className="border-b border-slate-300 py-6 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <FileText className="h-5 w-5 text-blue-700" />
        <h2 className="mr-2 text-2xl font-bold text-blue-700">{section.title}</h2>
        {section.sourceBadges.map((badge) =>
          badge === 'editable' ? null : (
            <button
              key={`${section.id}-${badge}`}
              type="button"
              aria-expanded={isEvidenceExpanded}
              title={`${sourceBadgeMeta[badge].label} 원문 보기`}
              onClick={() => onToggleEvidence(section.id)}
              className="rounded-full outline-none focus:ring-2 focus:ring-blue-300"
            >
              <SourceBadge type={badge} interactive />
            </button>
          ),
        )}
      </div>

      {section.sourceBadges.includes('needs_review') && (
        <div className="mt-3 flex items-start gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            AI 검토: 근거가 약하거나 상담사 판단이 필요한 문장입니다. 원문 칩을 열어 유지, 수정, 삭제 여부를
            확인하세요.
          </span>
        </div>
      )}

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
          className="mt-5 min-h-[140px] w-full resize-y rounded-md border border-blue-200 bg-white px-4 py-3 text-lg leading-8 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
      ) : (
        <button
          type="button"
          onClick={() => section.editable && onEditSection(section.id)}
          className="mt-5 block w-full rounded-md px-2 py-2 text-left text-lg font-semibold leading-8 text-slate-900 hover:bg-slate-50"
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
      <div className="flex gap-2 text-xs leading-5 text-amber-800">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <p>직접 연결된 원문 근거가 부족합니다. 상담사 확인 후 유지, 수정, 삭제 여부를 결정해주세요.</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-semibold text-blue-900">
        <Search className="h-3.5 w-3.5" />
        연결된 원문 근거
      </div>
      {evidence.map((item, index) => (
        <div key={`${section.id}-${item.label}-${index}`} className="text-xs leading-5 text-slate-700">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900">{item.label}</span>
            <span className="rounded-full bg-white px-2 py-0.5 text-slate-600 ring-1 ring-blue-100">
              신뢰도 {confidenceLabel[item.confidence]}
            </span>
            {item.needsReview && <span className="font-medium text-amber-700">상담사 확인 필요</span>}
          </div>
          <p className="mt-2 rounded-md bg-white px-3 py-2 text-slate-700 ring-1 ring-blue-100">
            {item.excerpt || '표시할 원문 일부가 없습니다.'}
          </p>
        </div>
      ))}
    </div>
  )
}

function DocumentTransformWorkspace({
  onCreateFinal,
  onSelectType,
  preview,
  sections,
  selectedType,
}: {
  onCreateFinal: (documentType: FinalDocumentType) => void
  onSelectType: (documentType: FinalDocumentType) => void
  preview?: GenerateNoteResponse['document_transform_preview']
  sections: DraftSection[]
  selectedType: FinalDocumentType
}) {
  return (
    <section className="min-h-[calc(100vh-68px)] px-16 py-28">
      <div className="mx-auto max-w-[1120px] text-center">
        <h1 className="text-[40px] font-extrabold leading-tight tracking-normal text-black">어떤 문서로 변환할까요?</h1>
        <p className="mt-5 text-2xl font-bold text-slate-500">회기 요약을 원하는 문서 양식대로 변환해드려요</p>
      </div>

      <div className="mx-auto mt-20 grid max-w-[1120px] gap-9 lg:grid-cols-3">
        {transformOptions.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => onSelectType(option.id)}
            className={`min-h-[340px] rounded-[12px] border bg-white p-10 text-center transition hover:-translate-y-0.5 hover:shadow-md ${
              selectedType === option.id ? 'border-blue-600 bg-blue-50' : 'border-slate-300'
            }`}
          >
            <div className="mx-auto flex h-[74px] w-[74px] items-center justify-center rounded-[18px] bg-blue-50 text-blue-700">
              <FileText className="h-10 w-10" />
            </div>
            <h2 className="mt-10 text-2xl font-extrabold text-black">{option.title}</h2>
            <p className="mt-7 text-base font-semibold leading-6 text-slate-500">{option.description}</p>
          </button>
        ))}
      </div>

      <section className="mx-auto mt-16 max-w-[1120px]">
        <div className="flex justify-center gap-7">
          <button
            type="button"
            className="inline-flex h-[50px] items-center justify-center rounded-md border border-blue-600 bg-white px-8 text-xl font-bold text-blue-700 hover:bg-blue-50"
          >
            초안으로 돌아가기
          </button>
          <button
            type="button"
            onClick={() => onCreateFinal(selectedType)}
            className="inline-flex h-[50px] items-center gap-2 rounded-md bg-blue-600 px-9 text-xl font-bold text-white shadow-sm hover:bg-blue-700"
          >
            변환하기
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </section>
    </section>
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
                  <li key={item}>
                    <HighlightedText text={item} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-slate-800">
                <HighlightedText text={section.content} />
              </p>
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
  fullResponse,
  isLoading,
  missingItems,
  onAddCustomSection,
  onGoBack,
  onGoToFinal,
  onGoToTransform,
  onTogglePreviousSession,
  onToggleSection,
  resultReady,
  selectedPreviousSessionIds,
  visibleSectionIds,
  warnings,
}: {
  activeStep: WorkflowStep
  checklistItems: ChecklistItem[]
  currentScreen: AppScreen
  fullResponse?: GenerateNoteResponse
  isLoading: boolean
  missingItems: string[]
  onAddCustomSection: () => void
  onGoBack: () => void
  onGoToFinal: () => void
  onGoToTransform: () => void
  onTogglePreviousSession: (sessionId: string) => void
  onToggleSection: (sectionId: DraftSectionId) => void
  resultReady: boolean
  selectedPreviousSessionIds: string[]
  visibleSectionIds: Set<DraftSectionId>
  warnings: string[]
}) {
  return (
    <aside className="flex min-h-[calc(100vh-68px)] flex-col border-l border-slate-200 bg-white p-6 xl:sticky xl:top-[68px]">
      {currentScreen === 'session_input' ? (
        <PreviousSessionLinkPanel
          selectedIds={selectedPreviousSessionIds}
          onToggle={onTogglePreviousSession}
        />
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

      <div className="mt-auto space-y-3 pt-8">
        {resultReady && currentScreen === 'summary_draft' && (
          <p className="flex items-center gap-2 text-xs font-semibold text-slate-400">
            <AlertTriangle className="h-4 w-4" />
            하이라이트된 문장은 AI가 생성한 문장입니다.
          </p>
        )}
        <button
          type="button"
          className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-md border border-dashed border-slate-400 bg-white px-3 text-base font-bold text-slate-500 hover:bg-slate-50"
        >
          <Save className="h-4 w-4" />
          임시저장
        </button>
        <div className="grid grid-cols-2 gap-3">
          <button
            type="button"
            onClick={onGoBack}
            disabled={!resultReady}
            className="inline-flex h-12 items-center justify-center gap-1 rounded-md border border-blue-600 bg-white px-3 text-base font-bold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-300"
          >
            <ArrowLeft className="h-4 w-4" />
            이전 단계
          </button>
          {currentScreen === 'document_transform' ? (
            <button
              type="button"
              onClick={onGoToFinal}
              className="inline-flex h-12 items-center justify-center gap-1 rounded-md bg-blue-600 px-3 text-base font-bold text-white shadow-sm hover:bg-blue-700"
            >
              다음 단계
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : resultReady ? (
            <button
              type="button"
              onClick={onGoToTransform}
              className="inline-flex h-12 items-center justify-center gap-1 rounded-md bg-blue-600 px-3 text-base font-bold text-white shadow-sm hover:bg-blue-700"
            >
              문서 변환
              <ChevronRight className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="submit"
              form="session-input-form"
              disabled={isLoading}
              className="inline-flex h-12 items-center justify-center gap-1 rounded-md bg-blue-600 px-3 text-base font-bold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              회기요약 생성하기
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}

function PreviousSessionLinkPanel({
  onToggle,
  selectedIds,
}: {
  onToggle: (sessionId: string) => void
  selectedIds: string[]
}) {
  return (
    <section>
      <div className="flex items-start gap-3">
        <History className="mt-0.5 h-8 w-8 shrink-0 text-blue-700" />
        <div>
          <h2 className="text-2xl font-bold text-slate-950">이전 회기 기록</h2>
          <p className="mt-3 text-base leading-6 text-slate-500">클릭하면 이전 회기 내용을 불러옵니다.</p>
        </div>
      </div>

      <div className="mt-7 space-y-5">
        {previousSessionOptions.map((session) => {
          const selected = selectedIds.includes(session.id)
          return (
            <button
              key={session.id}
              type="button"
              aria-pressed={selected}
              onClick={() => onToggle(session.id)}
              className={`w-full rounded-[12px] border p-5 text-left transition ${
                selected
                  ? 'border-blue-600 bg-blue-50 shadow-sm'
                  : 'border-slate-300 bg-white hover:border-blue-300 hover:bg-blue-50/40'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-lg font-bold text-blue-700">{session.label}</p>
                  <p className="mt-1 text-sm font-medium text-slate-500">{session.date}</p>
                </div>
                {selected && <CheckCircle2 className="h-4 w-4 shrink-0 text-blue-700" />}
              </div>
              <p className="mt-4 text-sm font-semibold leading-6 text-slate-900">{session.summary}</p>
            </button>
          )
        })}
      </div>

    </section>
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
    <aside className="flex min-h-[calc(100vh-68px)] flex-col border-l border-slate-200 bg-white p-6 xl:sticky xl:top-[68px]">
      <div>
        <p className="text-2xl font-extrabold text-slate-950">AI 검토</p>
        <p className="mt-4 text-sm leading-6 text-slate-500">
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

      <div className="mt-auto space-y-3 pt-8">
        <button
          type="button"
          className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-md border border-dashed border-slate-400 bg-white px-3 text-base font-bold text-slate-500 hover:bg-slate-50"
        >
          <Save className="h-4 w-4" />
          임시저장
        </button>
        <div className="grid grid-cols-2 gap-3">
          <button
            type="button"
            onClick={onBack}
            className="inline-flex h-12 items-center justify-center gap-1 rounded-md border border-blue-600 bg-white px-3 text-base font-bold text-blue-700 hover:bg-blue-50"
          >
            <ArrowLeft className="h-4 w-4" />
            이전 단계
          </button>
          <button
            type="button"
            className="inline-flex h-12 items-center justify-center gap-1 rounded-md bg-blue-600 px-3 text-base font-bold text-white shadow-sm hover:bg-blue-700"
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

const highlightPhrases = [
  '진로 및 취업 준비 과정',
  '진로 및 취업 준비 과정에서 지속적인 불안과 압박감을 경험함',
  '또래와의 비교',
  '자기비난',
  '자동사고와 감정 반응',
  '자신의 가치를 평가하는 경향이 확인되었다',
  '회피를 조금 줄이는 작은 행동',
  '실행 전후 불안 점수',
  '불안이 높을 때',
  '단기적으로 불안을 낮추지만 다음 날 부담을 키울 수 있음',
  '상담자가 직접 입력해야 합니다',
]

function HighlightedText({ text }: { text: string }) {
  const matches = highlightPhrases
    .filter((phrase) => text.includes(phrase))
    .sort((a, b) => text.indexOf(a) - text.indexOf(b))

  if (!matches.length) return <>{text}</>

  const parts: ReactNode[] = []
  let cursor = 0

  matches.forEach((phrase) => {
    const index = text.indexOf(phrase, cursor)
    if (index < 0) return
    if (index > cursor) parts.push(text.slice(cursor, index))
    parts.push(
      <mark key={`${phrase}-${index}`} className="rounded bg-amber-100 px-1 text-slate-900">
        {phrase}
      </mark>,
    )
    cursor = index + phrase.length
  })

  if (cursor < text.length) parts.push(text.slice(cursor))
  return <>{parts}</>
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-4 py-3">
      <dt className="text-sm font-bold text-slate-950">{label}</dt>
      <dd className="mt-2 truncate text-base font-semibold text-blue-700">{value}</dd>
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
    <div className="flex min-h-[80px] items-center justify-between gap-3 px-5 py-3">
      <div className="min-w-0">
        <p className="text-lg font-bold text-slate-950">{label}</p>
        <p className="mt-2 truncate text-base text-slate-500">{meta}</p>
      </div>
      <button
        type="button"
        onClick={onAction}
        className="shrink-0 rounded-md border border-slate-200 px-3 py-2 text-sm font-medium text-slate-500 hover:bg-slate-50"
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/55 px-4 py-6">
      <section className="max-h-[92vh] w-full max-w-[680px] overflow-auto rounded-[10px] bg-white shadow-2xl">
        <div className="flex items-center justify-between gap-4 border-b border-slate-200 px-6 py-5">
          <h2 className="text-2xl font-extrabold text-slate-950">{modalTitle[mode]}</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            aria-label="닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-7">
          {mode === 'add' && (
            <div className="grid gap-5">
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
                title="심리검사 메모"
                description="검사 결과 요약과 상담적 해석 메모를 추가합니다."
                onClick={() => onModeChange('write_test')}
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
      className="flex min-h-[130px] items-center gap-7 rounded-[8px] border border-slate-300 bg-white px-6 py-5 text-left hover:border-blue-300 hover:bg-blue-50"
    >
      <span className="flex h-12 w-12 shrink-0 items-center justify-center text-blue-700">
        <Edit3 className="h-10 w-10" />
      </span>
      <span>
        <span className="block text-2xl font-extrabold text-black">{title}</span>
        <span className="mt-3 block text-xl font-semibold leading-7 text-slate-500">{description}</span>
      </span>
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

function SourceBadge({ interactive = false, type }: { interactive?: boolean; type: SourceBadgeKind }) {
  const badge = sourceBadgeMeta[type]
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ring-1 ${
        interactive ? 'shadow-sm transition hover:-translate-y-px hover:bg-white' : ''
      } ${badge.className}`}
    >
      {interactive && <Search className="h-3 w-3" />}
      {badge.label}
      {interactive && <span className="font-semibold">원문</span>}
    </span>
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
    ...(form.psychological_test_summary?.trim()
      ? [
          makeSection({
            id: 'psychological_test',
            title: '심리검사 요약',
            content: form.psychological_test_summary,
            baseEvidence: [],
            forceBadges: ['attachment', 'needs_review'],
          }),
        ]
      : []),
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
  if (screen === 'summary_draft') return '회기요약'
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
        title: '심리검사 결과 및 해석',
        content: getSection('psychological_test', '심리검사 결과와 상담적 해석은 상담사가 확인해야 합니다.'),
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
  field: keyof Pick<
    SessionInput,
    'transcript_text' | 'counselor_memo' | 'previous_session_summary' | 'psychological_test_summary'
  >
  label: string
}

const modalTitle: Record<MaterialModalMode, string> = {
  add: '상담 자료 추가',
  basic_info: '회기 기본 정보 수정',
  paste_text: '텍스트 붙여넣기',
  file_upload: '파일 업로드',
  load_previous: '이전 회기 불러오기',
  write_memo: '상담사 메모 작성',
  write_test: '심리검사 메모 작성',
  edit_transcript: '축어록/STT 수정',
  edit_memo: '상담사 메모 수정',
  edit_previous: '이전 회기 요약 변경',
  edit_test: '심리검사 메모 수정',
}

const transformOptions: Array<{
  description: string
  id: FinalDocumentType
  requiredFields: string[]
  title: string
}> = [
  {
    id: 'session_note',
    title: '상담일지',
    description: '확정된 회기요약을 상담 일지 형태로 정리합니다.',
    requiredFields: ['위험 신호 확인', '목표 달성 정도', '상담자 최종 확인'],
  },
  {
    id: 'supervision_report',
    title: '슈퍼비전 보고서',
    description: '회기요약을 바탕으로 슈퍼비전 보고서 초안을 구성합니다.',
    requiredFields: ['내담자 기본 정보', '상담신청경위', '가족관계', '사례개념화', '슈퍼비전 요청사항'],
  },
  {
    id: 'termination_report',
    title: '종결 보고서',
    description: '여러 회기 요약을 종결 보고서 형식으로 정리하는 화면입니다.',
    requiredFields: ['전체 회기 목록', '종결 사유', '목표 달성 정도', '향후 권고'],
  },
]

const documentPreviewLabel: Record<string, string> = {
  session_summary: '상담 내용 요약',
  client_main_issue: '주요 호소',
  next_plan: '다음 계획',
  psychological_test_summary: '심리검사 요약',
}

const finalDocumentMeta: Record<FinalDocumentType, { title: string }> = {
  session_note: { title: '상담일지' },
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
  if (mode === 'write_test' || mode === 'edit_test') {
    return { field: 'psychological_test_summary', label: '심리검사 결과 및 해석 메모' }
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
  editable: { label: '', className: '' },
  needs_review: { label: '확인 필요', className: 'bg-rose-50 text-rose-700 ring-rose-200' },
}

const confidenceLabel: Record<EvidenceConfidence, string> = {
  high: '높음',
  medium: '중간',
  low: '낮음',
}
