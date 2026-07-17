import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowLeft,
  Bookmark,
  Check,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  Download,
  Edit3,
  FileText,
  FolderOpen,
  History,
  Info,
  List,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  PenLine,
  Plus,
  RefreshCcw,
  Save,
  Search,
  Send,
  ShieldCheck,
  User,
  Workflow,
  X,
  type LucideIcon,
} from 'lucide-react'
import {
  downloadDocumentExport,
  extractDocumentMaterial,
  getAudioCapabilities,
  getDocumentCapabilities,
  generateNoteDraft,
  generateSupervisionReport,
  recomposeNoteDraft,
  saveTemporaryDraft,
  transcribeAudio,
} from '../api/client'
import type {
  AudioCapabilitiesResponse,
  AudioSegment,
  DocumentCapabilitiesResponse,
  DocumentExportFormat,
  DocumentExportRequest,
  DocumentExportSection,
  EvidenceCheckItem,
  EvidenceConfidence,
  EvidenceSourceType,
  GenerateNoteResponse,
  NoteDraftResponse,
  SessionInput,
  SupervisionAiReviewPanel,
  SupervisionContentBlock,
  SupervisionReportDraft,
  SupervisionReportSection,
} from '../types/session'

const workflowSteps = ['회기입력', '요약초안', '문서변환', '최종문서'] as const
const processSteps = ['입력 정제', 'RAG 컨텍스트 검색', '상담 내용 구조화', '근거 연결', '회기요약 생성', '검증 리포트 생성']
const PLACEHOLDER_TEXT = '[상담사 확인 필요]'
const reviewStatusSymbol: Record<'done' | 'partial' | 'missing', string> = {
  done: '✓',
  partial: '△',
  missing: '·',
}

type WorkflowStep = (typeof workflowSteps)[number]
type AppScreen = 'case_list' | 'session_input' | 'summary_draft' | 'document_transform' | 'final_document'
type FinalDocumentType = 'session_note' | 'supervision_report' | 'termination_report'
type MaterialModalMode =
  | 'add'
  | 'basic_info'
  | 'paste_text'
  | 'file_upload'
  | 'document_upload'
  | 'audio_upload'
  | 'document_preview'
  | 'material_apply'
  | 'audio_review'
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

type SourceBadgeKind =
  | 'memo'
  | 'transcript'
  | 'previous'
  | 'case_memory'
  | 'template'
  | 'privacy'
  | 'attachment'
  | 'ai'
  | 'editable'
  | 'needs_review'

type UploadedMaterialKind = 'document' | 'audio'
type UploadedMaterialStatus =
  | 'uploading'
  | 'completed'
  | 'warning'
  | 'selected'
  | 'transcribing'
  | 'transcribed'
  | 'failed'
type MaterialApplyTarget =
  | 'transcript_text'
  | 'counselor_memo'
  | 'previous_session_summary'
  | 'psychological_test_summary'
type MaterialApplyMode = 'append' | 'replace'

interface UploadedMaterial {
  id: string
  kind: UploadedMaterialKind
  filename: string
  mediaType?: string
  status: UploadedMaterialStatus
  characterCount?: number
  pageCount?: number | null
  extractedText?: string
  warnings: string[]
  error?: string
  file?: File
  objectUrl?: string
  transcriptText?: string
  segments?: AudioSegment[]
  durationSeconds?: number | null
  language?: string | null
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

interface FinalDocumentSection {
  id: string
  title: string
  content: string
  contentKind: 'paragraph' | 'list'
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
  client_alias: demoClientName,
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
  target_document_type: 'session_note',
  persist: false,
}

export default function SessionDraftPage() {
  const [currentScreen, setCurrentScreen] = useState<AppScreen>('session_input')
  const [form, setForm] = useState<SessionInput>(initialForm)
  const [sessionTopic, setSessionTopic] = useState('발표 이후 비교사고와 회피 행동 점검')
  const [finalDocumentType, setFinalDocumentType] = useState<FinalDocumentType>('session_note')
  const [isDeidentified, setIsDeidentified] = useState(true)
  const [materials, setMaterials] = useState<UploadedMaterial[]>([])
  const objectUrlsRef = useRef<Set<string>>(new Set())
  const [selectedPreviousSessionIds, setSelectedPreviousSessionIds] = useState<string[]>(defaultPreviousSessionIds)
  const [materialModal, setMaterialModal] = useState<MaterialModalMode | null>(null)
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [hasSubmitted, setHasSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<NoteDraftResponse | null>(null)
  const [draftSections, setDraftSections] = useState<DraftSection[]>([])
  const [finalDocumentSections, setFinalDocumentSections] = useState<FinalDocumentSection[]>([])
  const [visibleSectionIds, setVisibleSectionIds] = useState<Set<DraftSectionId>>(defaultVisibleSectionIds)
  const [editingSectionId, setEditingSectionId] = useState<DraftSectionId | null>(null)
  const [expandedEvidenceId, setExpandedEvidenceId] = useState<DraftSectionId | null>(null)
  const [temporaryDraftId, setTemporaryDraftId] = useState<string | null>(null)
  const [isSavingDraft, setIsSavingDraft] = useState(false)
  const [draftSaveMessage, setDraftSaveMessage] = useState<string | null>(null)
  const [isRecomposingDraft, setIsRecomposingDraft] = useState(false)
  const [draftRecomposeMessage, setDraftRecomposeMessage] = useState<string | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isGeneratingFinalDocument, setIsGeneratingFinalDocument] = useState(false)
  const [finalDocumentError, setFinalDocumentError] = useState<string | null>(null)
  const [supervisionReportDraft, setSupervisionReportDraft] = useState<SupervisionReportDraft | null>(null)
  const [editingSupervisionBlockId, setEditingSupervisionBlockId] = useState<string | null>(null)
  const [editingSupervisionText, setEditingSupervisionText] = useState('')
  const [expandedSupervisionEvidenceId, setExpandedSupervisionEvidenceId] = useState<string | null>(null)
  const [isExportingDocument, setIsExportingDocument] = useState(false)
  const [documentExportError, setDocumentExportError] = useState<string | null>(null)
  const [documentExportStatus, setDocumentExportStatus] = useState<string | null>(null)
  const [documentCapabilities, setDocumentCapabilities] = useState<DocumentCapabilitiesResponse | null>(null)
  const [documentCapabilitiesError, setDocumentCapabilitiesError] = useState<string | null>(null)
  const [audioCapabilities, setAudioCapabilities] = useState<AudioCapabilitiesResponse | null>(null)
  const [audioCapabilitiesError, setAudioCapabilitiesError] = useState<string | null>(null)

  const hasMaterials = Boolean(
    form.counselor_memo.trim() ||
      form.transcript_text.trim() ||
      form.psychological_test_summary?.trim() ||
      materials.length,
  )

  useEffect(() => {
    return () => {
      objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url))
      objectUrlsRef.current.clear()
    }
  }, [])

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

  const uploadDocumentFiles = async (files: FileList | null) => {
    if (!files?.length) return
    const selectedFiles = Array.from(files)
    const pendingMaterials: UploadedMaterial[] = selectedFiles.map((file) => ({
      id: makeMaterialId(file),
      kind: 'document',
      filename: file.name,
      mediaType: file.type,
      status: 'uploading',
      warnings: [],
    }))
    setMaterials((prev) => [...pendingMaterials, ...prev])

    await Promise.all(
      selectedFiles.map(async (file, index) => {
        const localId = pendingMaterials[index].id
        try {
          const extracted = await extractDocumentMaterial(file)
          setMaterials((prev) =>
            prev.map((material) =>
              material.id === localId
                ? {
                    ...material,
                    id: extracted.material_id || localId,
                    filename: extracted.filename,
                    mediaType: extracted.media_type,
                    status: extracted.warnings.length ? 'warning' : 'completed',
                    characterCount: extracted.character_count,
                    pageCount: extracted.page_count,
                    extractedText: extracted.extracted_text,
                    warnings: extracted.warnings,
                    error: undefined,
                  }
                : material,
            ),
          )
        } catch (err) {
          const message = err instanceof Error ? err.message : '문서 내용을 추출하지 못했습니다.'
          setMaterials((prev) =>
            prev.map((material) =>
              material.id === localId ? { ...material, status: 'failed', error: message } : material,
            ),
          )
        }
      }),
    )
  }

  const addAudioFiles = async (files: FileList | null) => {
    if (!files?.length) return
    await refreshAudioCapabilities()
    const nextMaterials = Array.from(files).map((file) => {
      const objectUrl = URL.createObjectURL(file)
      objectUrlsRef.current.add(objectUrl)
      return {
        id: makeMaterialId(file),
        kind: 'audio' as const,
        filename: file.name,
        mediaType: file.type,
        status: 'selected' as const,
        warnings: [],
        file,
        objectUrl,
      }
    })
    setMaterials((prev) => [...nextMaterials, ...prev])
  }

  const removeMaterial = (materialId: string) => {
    setMaterials((prev) => {
      const target = prev.find((material) => material.id === materialId)
      revokeObjectUrl(target?.objectUrl)
      return prev.filter((item) => item.id !== materialId)
    })
    if (selectedMaterialId === materialId) {
      setSelectedMaterialId(null)
    }
  }

  const refreshAudioCapabilities = async () => {
    setAudioCapabilitiesError(null)
    try {
      const capabilities = await getAudioCapabilities()
      setAudioCapabilities(capabilities)
      return capabilities
    } catch (err) {
      const message = err instanceof Error ? err.message : '음성 업로드 지원 상태를 확인하지 못했습니다.'
      setAudioCapabilitiesError(message)
      const fallback: AudioCapabilitiesResponse = {
        upload: { available: true },
        transcription: { available: false, reason: message },
        speaker_diarization: { available: false, reason: '화자 분리는 현재 지원하지 않습니다.' },
      }
      setAudioCapabilities(fallback)
      return fallback
    }
  }

  const transcribeAudioMaterial = async (materialId: string) => {
    const target = materials.find((material) => material.id === materialId)
    if (!target?.file) return
    setMaterials((prev) =>
      prev.map((material) => (material.id === materialId ? { ...material, status: 'transcribing', error: undefined } : material)),
    )
    try {
      const transcription = await transcribeAudio(target.file, 'ko', 'transcribe')
      setMaterials((prev) =>
        prev.map((material) =>
          material.id === materialId
            ? {
                ...material,
                status: 'transcribed',
                transcriptText: transcription.transcript_text,
                segments: transcription.segments,
                durationSeconds: transcription.duration_seconds,
                language: transcription.language,
                warnings: transcription.warnings,
                error: undefined,
                file: undefined,
              }
            : material,
        ),
      )
      setSelectedMaterialId(materialId)
      setMaterialModal('audio_review')
    } catch (err) {
      const message = err instanceof Error ? err.message : '음성 축어록을 생성하지 못했습니다.'
      setMaterials((prev) =>
        prev.map((material) =>
          material.id === materialId ? { ...material, status: 'failed', error: message } : material,
        ),
      )
    }
  }

  const updateAudioTranscript = (materialId: string, text: string) => {
    setMaterials((prev) =>
      prev.map((material) => (material.id === materialId ? { ...material, transcriptText: text } : material)),
    )
  }

  const updateAudioSegmentText = (materialId: string, segmentId: number, text: string) => {
    setMaterials((prev) =>
      prev.map((material) =>
        material.id === materialId
          ? {
              ...material,
              segments: (material.segments || []).map((segment) =>
                segment.id === segmentId ? { ...segment, text } : segment,
              ),
              transcriptText: (material.segments || [])
                .map((segment) => (segment.id === segmentId ? text : segment.text))
                .join('\n'),
            }
          : material,
      ),
    )
  }

  const openMaterialPreview = (materialId: string, mode: 'document_preview' | 'audio_review' | 'material_apply') => {
    setSelectedMaterialId(materialId)
    setMaterialModal(mode)
  }

  const applyMaterialToForm = (materialId: string, target: MaterialApplyTarget, mode: MaterialApplyMode) => {
    const material = materials.find((item) => item.id === materialId)
    const text = getMaterialText(material)
    if (!text.trim()) return
    setForm((prev) => ({
      ...prev,
      [target]: mergeMaterialText(String(prev[target] || ''), text, mode),
    }))
    setMaterialModal(null)
  }

  const revokeObjectUrl = (objectUrl?: string) => {
    if (!objectUrl) return
    URL.revokeObjectURL(objectUrl)
    objectUrlsRef.current.delete(objectUrl)
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setIsLoading(true)
    setHasSubmitted(true)
    setError(null)
    setResult(null)
    setSupervisionReportDraft(null)
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

  const toggleSectionVisibility = async (sectionId: DraftSectionId) => {
    const previousVisibleSectionIds = new Set(visibleSectionIds)
    const nextVisibleSectionIds = new Set(previousVisibleSectionIds)
    if (nextVisibleSectionIds.has(sectionId)) {
      nextVisibleSectionIds.delete(sectionId)
    } else {
      nextVisibleSectionIds.add(sectionId)
    }

    if (!result) {
      setVisibleSectionIds(nextVisibleSectionIds)
      return
    }

    setIsRecomposingDraft(true)
    setDraftRecomposeMessage('선택 항목 기준으로 AI 초안을 재구성 중입니다.')

    try {
      const recomposed = await recomposeNoteDraft({
        session_input: form,
        session_topic: sessionTopic,
        visible_section_ids: Array.from(nextVisibleSectionIds),
      })
      const nextVisibleSet = new Set<DraftSectionId>(recomposed.visibleSectionIds)
      setResult(recomposed.note)
      setVisibleSectionIds(nextVisibleSet)
      setDraftSections(buildDocumentSections(recomposed.note, form, sessionTopic, nextVisibleSet))
      setExpandedEvidenceId(null)
      setEditingSectionId(null)
      setDraftRecomposeMessage(recomposed.cacheHit ? '저장된 재구성 초안을 사용했습니다.' : 'AI 초안을 다시 재구성했습니다.')
    } catch (err) {
      const message = err instanceof Error ? err.message : '요약초안 재구성 중 오류가 발생했습니다.'
      setVisibleSectionIds(previousVisibleSectionIds)
      setDraftRecomposeMessage(`재구성 실패 · ${message}`)
    } finally {
      setIsRecomposingDraft(false)
    }
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
    setSupervisionReportDraft(null)
    setDraftSections([])
    setFinalDocumentSections([])
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

  const refreshDocumentCapabilities = async () => {
    setDocumentCapabilitiesError(null)
    try {
      const capabilities = await getDocumentCapabilities()
      setDocumentCapabilities(capabilities)
      return capabilities
    } catch (err) {
      const message = err instanceof Error ? err.message : '문서 내보내기 지원 상태를 확인하지 못했습니다.'
      setDocumentCapabilitiesError(message)
      const fallback: DocumentCapabilitiesResponse = {
        docx: { available: true },
        pdf: { available: false, reason: '문서 내보내기 지원 상태를 확인하지 못했습니다.' },
        hwpx: { available: false, reason: '검증된 HWPX 템플릿이 아직 설정되지 않았습니다.' },
      }
      setDocumentCapabilities(fallback)
      return fallback
    }
  }

  const openFinalDocument = async (documentType: FinalDocumentType = finalDocumentType) => {
    if (!result) return
    setFinalDocumentType(documentType)
    setFinalDocumentError(null)
    setDocumentExportError(null)
    setDocumentExportStatus(null)
    await refreshDocumentCapabilities()

    if (documentType === 'supervision_report') {
      setFinalDocumentSections([])
      setIsGeneratingFinalDocument(true)
      try {
        const report = await generateSupervisionReport({
          session_input: form,
          session_summary_draft: result.full_response?.session_summary_draft,
          demo_mode: form.case_id === 'CASE-DEMO-001',
          report_date: form.session_date,
          client_alias: getClientAlias(form),
        })
        setSupervisionReportDraft(report)
      } catch (err) {
        const message = err instanceof Error ? err.message : '수퍼비전 보고서 초안 생성 중 오류가 발생했습니다.'
        setFinalDocumentError(message)
      } finally {
        setIsGeneratingFinalDocument(false)
      }
    } else {
      setSupervisionReportDraft(null)
      setFinalDocumentSections(
        buildFinalDocumentSections(
          documentType,
          draftSections.filter((section) => section.visible),
          result.missing_items,
        ),
      )
    }

    setCurrentScreen('final_document')
  }

  const beginEditSupervisionBlock = (block: SupervisionContentBlock) => {
    setEditingSupervisionBlockId(block.id)
    setEditingSupervisionText(supervisionBlockToEditableText(block))
  }

  const commitEditSupervisionBlock = () => {
    if (!editingSupervisionBlockId) return
    const blockId = editingSupervisionBlockId
    const nextText = editingSupervisionText
    setSupervisionReportDraft((current) => {
      if (!current) return current
      return {
        ...current,
        sections: current.sections.map((section) => ({
          ...section,
          contentBlocks: section.contentBlocks.map((block) =>
            block.id === blockId ? updateSupervisionBlockFromText(block, nextText) : block,
          ),
        })),
      }
    })
    setEditingSupervisionBlockId(null)
    setEditingSupervisionText('')
  }

  const handleTemporarySave = async () => {
    setIsSavingDraft(true)
    setDraftSaveMessage(null)

    try {
      const response = await saveTemporaryDraft({
        draft_id: temporaryDraftId || undefined,
        case_id: form.case_id,
        session_number: form.session_number,
        session_date: form.session_date,
        counselor_name: form.counselor_name,
        screen: currentScreen,
        form,
        session_topic: sessionTopic,
        is_deidentified: isDeidentified,
        selected_previous_session_ids: selectedPreviousSessionIds,
        attachments: serializeMaterialsForDraft(materials),
        visible_section_ids: Array.from(visibleSectionIds),
        draft_sections: draftSections,
        final_document_sections: finalDocumentSections,
        result,
        final_document_type: finalDocumentType,
        supervision_report_draft: supervisionReportDraft,
      })
      setTemporaryDraftId(response.draft_id)
      setDraftSaveMessage(`임시저장 완료 · ${formatSavedTime(response.saved_at)}`)
    } catch (err) {
      const message = err instanceof Error ? err.message : '임시저장 중 오류가 발생했습니다.'
      setDraftSaveMessage(`임시저장 실패 · ${message}`)
    } finally {
      setIsSavingDraft(false)
    }
  }

  const handleDownloadDocument = async (format: DocumentExportFormat) => {
    if (!result) return
    if (format === 'pdf' && (!documentCapabilities || documentCapabilities.pdf.available === false)) {
      setDocumentExportError(
        documentCapabilities
          ? capabilityReasonToKorean(documentCapabilities.pdf.reason)
          : '문서 내보내기 지원 상태를 확인한 뒤 PDF를 사용할 수 있습니다.',
      )
      return
    }
    setIsExportingDocument(true)
    setDocumentExportError(null)
    setDocumentExportStatus(null)

    try {
      const request = buildDocumentExportRequest({
        documentType: finalDocumentType,
        editingSupervisionBlockId,
        editingSupervisionText,
        finalDocumentSections,
        form,
        format,
        supervisionReportDraft,
      })

      if (!request.sections.length) {
        throw new Error('내보낼 수 있는 문서 내용이 없습니다. 표시된 섹션에 내용을 입력해주세요.')
      }

      const { blob, filename } = await downloadDocumentExport(request)
      triggerBlobDownload(blob, filename)
      setDocumentExportStatus(`${format === 'pdf' ? 'PDF' : 'Word'} 다운로드를 시작했습니다.`)
    } catch (err) {
      const message = err instanceof Error ? err.message : '문서 내보내기 중 오류가 발생했습니다.'
      setDocumentExportError(message)
    } finally {
      setIsExportingDocument(false)
    }
  }

  const hasCompactSidePanel = currentScreen === 'session_input' || currentScreen === 'summary_draft' || currentScreen === 'final_document'

  return (
    <main className="min-h-screen bg-[#f1f2f4] text-slate-950">
      <AppSidebar
        activeScreen={currentScreen}
        collapsed={isSidebarCollapsed}
        onOpenCaseList={openCaseList}
        onOpenSessionInput={openSessionInput}
        onToggleCollapsed={() => setIsSidebarCollapsed((current) => !current)}
      />

      <div className={`min-h-screen ${isSidebarCollapsed ? 'md:pl-[56px]' : 'md:pl-[200px]'}`}>
        <TopWorkspaceBar
          activeStep={activeStep}
          currentScreen={currentScreen}
          draftSaveMessage={draftSaveMessage}
          isSavingDraft={isSavingDraft}
          resultReady={Boolean(result)}
          onGoToFinalDocument={() => openFinalDocument()}
          onGoToSummaryDraft={() => setCurrentScreen(result ? 'summary_draft' : currentScreen)}
          onGoToTransform={openDocumentTransform}
          onOpenCaseList={openCaseList}
          onOpenSessionInput={openSessionInput}
          onTemporarySave={handleTemporarySave}
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
                : hasCompactSidePanel
                  ? 'workspace-grid-compact'
                  : 'grid min-h-[calc(100vh-84px)] gap-4 pr-4 pt-4 md:grid-cols-[minmax(0,1fr)_320px]'
            }
          >
            <section
              className={
                currentScreen === 'document_transform'
                  ? 'min-w-0'
                  : hasCompactSidePanel
                    ? 'workspace-main-panel'
                    : 'min-w-0 pb-4'
              }
            >
              {currentScreen === 'session_input' && (
                <SessionInputWorkspace
                  completedSteps={completedSteps}
                  error={error}
                  form={form}
                  hasMaterials={hasMaterials}
                  hasSubmitted={hasSubmitted}
                  isDeidentified={isDeidentified}
                  isLoading={isLoading}
                  materials={materials}
                  audioCapabilities={audioCapabilities}
                  sessionTopic={sessionTopic}
                  onAddMaterial={() => setMaterialModal('add')}
                  onEditBasicInfo={() => setMaterialModal('basic_info')}
                  onEditMaterial={setMaterialModal}
                  onOpenMaterial={openMaterialPreview}
                  onRemoveMaterial={removeMaterial}
                  onSetIsDeidentified={setIsDeidentified}
                  onTranscribeAudio={transcribeAudioMaterial}
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
                  onBackToDraft={() => setCurrentScreen('summary_draft')}
                  onSelectType={setFinalDocumentType}
                  onCreateFinal={openFinalDocument}
                />
              )}

              {currentScreen === 'final_document' && result && (
                finalDocumentType === 'supervision_report' ? (
                  <SupervisionReportWorkspace
                    editingBlockId={editingSupervisionBlockId}
                    editingText={editingSupervisionText}
                    error={finalDocumentError}
                    expandedEvidenceId={expandedSupervisionEvidenceId}
                    isLoading={isGeneratingFinalDocument}
                    report={supervisionReportDraft}
                    onBeginEdit={beginEditSupervisionBlock}
                    onChangeEditingText={setEditingSupervisionText}
                    onCommitEdit={commitEditSupervisionBlock}
                    onToggleEvidence={setExpandedSupervisionEvidenceId}
                  />
                ) : (
                  <FinalDocumentWorkspace
                    documentType={finalDocumentType}
                    form={form}
                    sections={finalDocumentSections}
                    onChangeSectionContent={(sectionId, content) =>
                      setFinalDocumentSections((current) =>
                        current.map((section) => (section.id === sectionId ? { ...section, content } : section)),
                      )
                    }
                  />
                )
              )}
            </section>

            {currentScreen === 'document_transform' ? null : currentScreen === 'final_document' ? (
              finalDocumentType === 'supervision_report' && supervisionReportDraft ? (
                <SupervisionReviewPanel
                  aiReview={supervisionReportDraft.aiReview}
                  capabilities={documentCapabilities}
                  capabilitiesError={documentCapabilitiesError}
                  draftSaveMessage={draftSaveMessage}
                  exportError={documentExportError}
                  exportStatus={documentExportStatus}
                  isExporting={isExportingDocument}
                  isSavingDraft={isSavingDraft}
                  onBack={() => setCurrentScreen('document_transform')}
                  onDownload={handleDownloadDocument}
                  onTemporarySave={handleTemporarySave}
                />
              ) : (
                <FinalReviewPanel
                  documentType={finalDocumentType}
                  capabilities={documentCapabilities}
                  capabilitiesError={documentCapabilitiesError}
                  draftSaveMessage={draftSaveMessage}
                  exportError={documentExportError}
                  exportStatus={documentExportStatus}
                  isExporting={isExportingDocument}
                  isSavingDraft={isSavingDraft}
                  missingItems={result?.missing_items || []}
                  warnings={result?.warnings || []}
                  onBack={() => setCurrentScreen('document_transform')}
                  onDownload={handleDownloadDocument}
                  onTemporarySave={handleTemporarySave}
                />
              )
            ) : (
              <ReviewPanel
                activeStep={activeStep}
                checklistItems={checklistItems}
                currentScreen={currentScreen}
                draftRecomposeMessage={draftRecomposeMessage}
                fullResponse={result?.full_response}
                isLoading={isLoading}
                isRecomposingDraft={isRecomposingDraft}
                missingItems={result?.missing_items || []}
                selectedPreviousSessionIds={selectedPreviousSessionIds}
                resultReady={Boolean(result)}
                visibleSectionIds={visibleSectionIds}
                warnings={result?.warnings || []}
                onAddCustomSection={addCustomSection}
                onGoBack={goBackToInput}
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
          materials={materials}
          selectedMaterial={materials.find((material) => material.id === selectedMaterialId) || null}
          audioCapabilities={audioCapabilities}
          audioCapabilitiesError={audioCapabilitiesError}
          onAddAudioFiles={addAudioFiles}
          onApplyMaterial={applyMaterialToForm}
          onRefreshAudioCapabilities={refreshAudioCapabilities}
          onTranscribeAudio={transcribeAudioMaterial}
          onUpdateAudioSegmentText={updateAudioSegmentText}
          onUpdateAudioTranscript={updateAudioTranscript}
          onUploadDocumentFiles={uploadDocumentFiles}
        />
      )}
    </main>
  )
}

function AppSidebar({
  activeScreen,
  collapsed,
  onOpenCaseList,
  onOpenSessionInput,
  onToggleCollapsed,
}: {
  activeScreen: AppScreen
  collapsed: boolean
  onOpenCaseList: () => void
  onOpenSessionInput: () => void
  onToggleCollapsed: () => void
}) {
  const caseAreaActive = activeScreen !== 'session_input'

  return (
    <aside
      className={`border-slate-200 bg-white transition-[width] duration-200 md:fixed md:inset-y-0 md:left-0 md:z-40 md:border-r ${
        collapsed ? 'md:w-[56px]' : 'md:w-[200px]'
      }`}
    >
      <div className="flex h-full flex-col">
        <div
          className={`flex min-h-[var(--workspace-header-height)] items-center border-b border-slate-100 ${
            collapsed ? 'justify-center px-2' : 'justify-between px-6'
          }`}
        >
          {!collapsed && (
            <img
              src="/remind-logo.png"
              alt="Re:mind"
              className="h-7 max-w-[104px] object-contain"
            />
          )}
          <button
            type="button"
            onClick={onToggleCollapsed}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100 hover:text-slate-900"
            aria-label={collapsed ? '사이드바 열기' : '사이드바 닫기'}
            title={collapsed ? '사이드바 열기' : '사이드바 닫기'}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>

        <div className={`${collapsed ? 'hidden' : 'space-y-4 px-3 py-3'}`}>
          <label className="flex h-[30px] items-center gap-2 rounded-[5px] border border-slate-200 bg-slate-50 px-3 text-[11px] text-slate-500 shadow-sm">
            <Search className="h-4 w-4" />
            <input
              className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-slate-400"
              placeholder="내담자/케이스 검색"
            />
          </label>

          <nav className="space-y-2 text-xs">
            <p className="px-1 text-[10px] font-medium text-slate-400">메뉴</p>
            <SidebarButton
              active={caseAreaActive}
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

          <div className="space-y-2 border-t border-slate-200 pt-4">
            <p className="px-1 text-[10px] font-medium text-slate-400">최근 케이스</p>
            <CaseListItem name="가명 은하" status="진행중" meta="대학생 · 5회기" active />
            <CaseListItem name="신데렐라" status="진행중" meta="직장인 · 3회기" />
            <CaseListItem name="흥부" status="종결" meta="직장인 · 12회기" tone="green" />
            <CaseListItem name="팥쥐" status="대기중" meta="성인 · 1회기" tone="orange" />
          </div>
        </div>

        <div className={`${collapsed ? 'hidden' : 'mt-auto border-t border-slate-200 px-3 py-3'}`}>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-blue-600 font-semibold text-white">
              박
            </div>
            <div>
              <p className="text-xs font-semibold text-slate-900">박상담사</p>
              <p className="text-[11px] text-slate-500">2급 심리상담사</p>
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
      className={`flex h-[26px] w-full items-center gap-2 rounded-[5px] px-2 text-left font-semibold ${
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
      className={`w-full rounded-[6px] px-3 py-2 text-left text-xs ${
        active ? 'bg-blue-50' : 'border-b border-slate-100 hover:bg-slate-50'
      }`}
    >
      <p className="font-semibold text-slate-900">{name}</p>
      <div className="mt-2 flex items-center gap-1.5 text-[10px] text-slate-500">
        <span className={`rounded-full px-2 py-0.5 font-medium ${toneClass}`}>{status}</span>
        <span>{meta}</span>
      </div>
    </button>
  )
}

function TopWorkspaceBar({
  activeStep,
  currentScreen,
  draftSaveMessage,
  isSavingDraft,
  onGoToFinalDocument,
  onGoToSummaryDraft,
  onGoToTransform,
  onOpenCaseList,
  onOpenSessionInput,
  onTemporarySave,
  resultReady,
}: {
  activeStep: WorkflowStep
  currentScreen: AppScreen
  draftSaveMessage: string | null
  isSavingDraft: boolean
  onGoToFinalDocument: () => void
  onGoToSummaryDraft: () => void
  onGoToTransform: () => void
  onOpenCaseList: () => void
  onOpenSessionInput: () => void
  onTemporarySave: () => void
  resultReady: boolean
}) {
  const activeIndex = workflowSteps.indexOf(activeStep)
  const showTemporarySave = currentScreen === 'session_input' || currentScreen === 'summary_draft'
  const goToWorkflowStep = (step: WorkflowStep) => {
    if (step === '회기입력') {
      onOpenSessionInput()
      return
    }
    if (!resultReady) return
    if (step === '요약초안') onGoToSummaryDraft()
    if (step === '문서변환') onGoToTransform()
    if (step === '최종문서') onGoToFinalDocument()
  }
  const canOpenWorkflowStep = (step: WorkflowStep) => step === '회기입력' || resultReady

  return (
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white">
      <div className="flex min-h-[var(--workspace-header-height)] items-center justify-between gap-4 px-[clamp(16px,2vw,28px)]">
        {currentScreen === 'case_list' ? (
          <div />
        ) : (
          <nav className="flex flex-wrap items-center gap-3 text-xs">
            {workflowSteps.map((step, index) => {
              const StepIcon = step === '회기입력' ? Edit3 : step === '요약초안' ? ClipboardList : step === '문서변환' ? FolderOpen : FileText
              const enabled = canOpenWorkflowStep(step)
              return (
                <button
                  key={step}
                  type="button"
                  disabled={!enabled}
                  className={`flex items-center gap-3 ${enabled ? 'cursor-pointer' : 'cursor-not-allowed opacity-45'}`}
                  onClick={() => goToWorkflowStep(step)}
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
                    <StepIcon className="h-4 w-4" />
                    {step}
                  </span>
                  {index < workflowSteps.length - 1 && <ChevronRight className="h-3 w-3 text-slate-500" />}
                </button>
              )
            })}
          </nav>
        )}

        <div className="flex items-center gap-2">
          {showTemporarySave && (
            <>
              {draftSaveMessage && (
                <span className="hidden max-w-[168px] truncate text-[11px] font-semibold text-slate-500 xl:inline">
                  {draftSaveMessage}
                </span>
              )}
              <button
                type="button"
                onClick={onTemporarySave}
                disabled={isSavingDraft}
                className="inline-flex h-8 items-center gap-1.5 rounded-[6px] border border-dashed border-slate-400 bg-white px-3 text-xs font-bold text-slate-500 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
              >
                {isSavingDraft ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                {isSavingDraft ? '저장중' : '임시저장'}
              </button>
            </>
          )}
          <button
            type="button"
            onClick={onOpenCaseList}
            className="inline-flex h-8 items-center gap-2 rounded-[6px] border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
          >
            <List className="h-4 w-4" />
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
    <section className="px-6 py-5">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-extrabold tracking-normal text-black">케이스 목록</h2>
        </div>
        <div className="flex items-center gap-3">
        <div className="flex gap-2 text-[11px]">
          {['전체', '진행중', '종결', '대기중'].map((filter, index) => (
            <button
              key={filter}
              type="button"
              className={`h-8 rounded-full px-3.5 font-bold shadow-sm ${
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
          className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-bold text-white shadow-sm hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          새 회기 생성
        </button>
        </div>
      </div>

      <div className="grid max-w-[790px] gap-3 md:grid-cols-2 lg:grid-cols-3">
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
      className="min-h-[190px] rounded-[10px] border border-slate-200 bg-white p-3.5 text-left shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-extrabold text-black">{caseItem.name}</h3>
          <p className="mt-0.5 text-[9px] text-slate-500">케이스 ID: {caseItem.id}</p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[9px] font-bold ${statusTone}`}>{caseItem.status}</span>
      </div>

      <dl className="mt-2.5 grid gap-1 text-[10px] leading-4">
        <CaseMeta label="상담 유형" value={caseItem.type} />
        <CaseMeta label="최근 회기" value={caseItem.lastDate} />
        <CaseMeta label="담당 상담사" value={caseItem.counselor} />
        <CaseMeta label="주요 이슈" value={caseItem.mainIssue} />
      </dl>

      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between text-[11px] font-bold text-slate-500">
          <span>{caseItem.sessionCount}회기</span>
          <span className="text-blue-700">{caseItem.progressLabel}</span>
        </div>
        <div className="h-2.5 rounded-full bg-slate-100">
          <div className={`h-2.5 rounded-full ${progressColor}`} style={{ width: `${caseItem.progress}%` }} />
        </div>
      </div>
    </button>
  )
}

function CaseMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[62px_minmax(0,1fr)] items-center gap-2">
      <dt className="whitespace-nowrap text-slate-500">{label}</dt>
      <dd className="truncate font-extrabold text-black">{value}</dd>
    </div>
  )
}

function SessionInputWorkspace({
  audioCapabilities,
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
  onOpenMaterial,
  onRemoveMaterial,
  onSetIsDeidentified,
  onTranscribeAudio,
  onSubmit,
  materials,
  sessionTopic,
}: {
  audioCapabilities: AudioCapabilitiesResponse | null
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
  onOpenMaterial: (materialId: string, mode: 'document_preview' | 'audio_review' | 'material_apply') => void
  onRemoveMaterial: (materialId: string) => void
  onSetIsDeidentified: (value: boolean) => void
  onTranscribeAudio: (materialId: string) => void
  onSubmit: (event: FormEvent<HTMLFormElement>) => void
  materials: UploadedMaterial[]
  sessionTopic: string
}) {
  return (
    <form id="session-input-form" onSubmit={onSubmit} className="session-input-form">
      <section className="session-card rounded-[12px] border border-slate-200 bg-white shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <User className="h-4 w-4 text-blue-700" />
              <p className="text-base font-bold tracking-normal text-slate-950">내담자 / 회기 기본 정보</p>
            </div>
            <h1 className="mt-3 text-xl font-bold tracking-normal text-slate-950">{getClientDisplayName(form)}</h1>
          </div>
          <button
            type="button"
            onClick={onEditBasicInfo}
            className="inline-flex h-7 items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
          >
            <Edit3 className="h-3.5 w-3.5" />
            수정하기
          </button>
        </div>
        <dl className="mt-3 grid gap-4 sm:grid-cols-[120px_minmax(0,1fr)_120px]">
          <InfoRow label="회기" value={`${form.session_number}회기`} />
          <InfoRow label="회기 주제" value={sessionTopic || '미정'} />
          <InfoRow label="날짜" value={form.session_date || '미정'} />
        </dl>
      </section>

      <section className="session-card session-material-card rounded-[12px] border border-slate-200 bg-white shadow-sm">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <FolderOpen className="h-4 w-4 text-blue-700" />
              <h2 className="text-lg font-bold tracking-normal">상담 자료</h2>
            </div>
            <p className="mt-2 text-xs text-slate-500">이번 회기 요약에 사용할 자료를 한 곳에서 관리합니다.</p>
          </div>
        </div>

        {!hasMaterials ? (
          <div className="session-material-content mt-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-6 text-center">
            <FileText className="mx-auto h-7 w-7 text-slate-400" aria-hidden="true" />
            <p className="mt-3 text-sm font-medium text-slate-700">이번 회기요약에 사용할 자료를 추가해주세요.</p>
          </div>
        ) : (
          <div className="session-material-content mt-3 divide-y divide-slate-200 rounded-lg border border-slate-300 bg-white">
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
            {materials.map((material) => (
              <UploadedMaterialRow
                key={material.id}
                material={material}
                transcriptionAvailable={Boolean(audioCapabilities?.transcription.available)}
                transcriptionReason={audioCapabilities?.transcription.reason || null}
                onApply={() => onOpenMaterial(material.id, 'material_apply')}
                onDelete={() => onRemoveMaterial(material.id)}
                onPreview={() => onOpenMaterial(material.id, material.kind === 'audio' ? 'audio_review' : 'document_preview')}
                onTranscribe={() => onTranscribeAudio(material.id)}
              />
            ))}
          </div>
        )}

        <div className="session-material-actions grid gap-3 sm:grid-cols-[minmax(0,1fr)_210px]">
          <button
            type="button"
            onClick={onAddMaterial}
            className="inline-flex h-8 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-xs font-bold text-white shadow-sm hover:bg-blue-700"
          >
            <Plus className="h-3.5 w-3.5" />
            상담 자료 업로드
          </button>

          <label className="inline-flex h-8 items-center justify-between gap-3 rounded-md bg-blue-50 px-3 text-blue-700">
            <span className="flex items-center gap-2 text-xs font-semibold text-blue-700">
              <ShieldCheck className="h-3.5 w-3.5 text-blue-700" />
              개인정보 비식별화
            </span>
            <input
              type="checkbox"
              checked={isDeidentified}
              onChange={(event) => onSetIsDeidentified(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-slate-300 text-blue-700 focus:ring-blue-600"
            />
          </label>
        </div>
      </section>

      <section className="session-card session-process-card rounded-[12px] border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center gap-2">
          <RefreshCcw className="h-4 w-4 text-blue-700" />
          <h2 className="text-lg font-bold">처리 상태</h2>
        </div>
        {isLoading && <p className="mt-2 text-xs font-medium text-blue-700">구조화 → 회기요약 → 검증 진행 중...</p>}
        <div className="mt-3 grid gap-2 md:grid-cols-5">
          {processSteps.map((step, index) => {
            const isDone = index < completedSteps
            const isActive = isLoading && index === completedSteps
            return (
              <div
                key={step}
                className={`process-step flex items-center gap-1.5 rounded-md border px-2 text-xs font-semibold ${
                  isDone || isActive ? 'border-blue-600 bg-blue-50 text-blue-800' : 'border-slate-200 bg-slate-50 text-slate-500'
                }`}
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                    isDone
                      ? 'border-blue-200 bg-blue-600 text-white'
                      : isActive
                        ? 'border-blue-200 bg-blue-50 text-blue-700'
                        : 'border-slate-200 bg-white text-slate-400'
                  }`}
                >
                  {isDone ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : isActive ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
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
    <section className="space-y-3">
      <div className="rounded-[8px] border border-slate-200 bg-white px-4 py-3 shadow-sm">
        <div className="flex items-center gap-3">
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-slate-900 text-[10px] font-bold text-white">i</span>
          <div>
            <p className="text-xs font-bold text-slate-900">AI 초안이 생성되었습니다.</p>
            <p className="mt-1 text-xs font-semibold text-slate-700">
              근거가 연결된 항목을 확인하고, 상담사 판단이 필요한 문장을 검토해 주세요.
            </p>
          </div>
        </div>
      </div>

      <article className="relative rounded-[7px] border border-slate-200 bg-white shadow-sm">
      <div className="rounded-t-[7px] bg-blue-600 px-4 py-3 text-white">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <ChevronRight className="h-6 w-6 rotate-180" />
              <h1 className="text-xl font-bold tracking-normal">요약 초안</h1>
            </div>
            <p className="mt-1.5 text-xs font-bold text-blue-50">
              {getClientDisplayName(form)} · {form.session_number}회기 · {formatCompactDate(form.session_date)}
            </p>
          </div>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-2 rounded-[5px] bg-white px-5 text-xs font-bold text-blue-700 shadow-sm hover:bg-blue-50"
          >
            <Edit3 className="h-4 w-4" />
            수정하기
          </button>
        </div>
      </div>

      <div className="space-y-0 px-4 py-3">
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
    <section className="relative border-b border-[#c7d0df] py-5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <Bookmark className="h-4 w-4 text-blue-700" />
        <h2 className="mr-1.5 text-base font-bold text-blue-700">{section.title}</h2>
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

      {isEvidenceExpanded && (
        <div className="absolute right-4 top-10 z-20 w-[190px] rounded-[6px] border border-slate-100 bg-white p-3 shadow-[0_14px_32px_rgba(15,23,42,0.18)] sm:right-16">
          <EvidencePreview evidence={section.evidence} />
        </div>
      )}

      {isEditing ? (
        <textarea
          autoFocus
          value={section.content}
          onBlur={() => onEditSection(null)}
          onChange={(event) => onChangeContent(section.id, event.target.value)}
          className="mt-4 min-h-[110px] w-full resize-y rounded-md border border-blue-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
      ) : (
        <button
          type="button"
          onClick={() => section.editable && onEditSection(section.id)}
          className="mt-4 block w-full rounded-[4px] px-2 py-1 text-left text-[13px] font-semibold leading-6 text-slate-900 hover:bg-slate-50"
        >
          <span className="whitespace-pre-wrap">{section.content || '내용을 입력해주세요.'}</span>
        </button>
      )}
    </section>
  )
}

function EvidencePreview({ evidence }: { evidence: CompactEvidence[] }) {
  if (!evidence.length) {
    return (
      <div className="flex gap-2 text-[10px] leading-4 text-amber-800">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <p>직접 연결된 원문 근거가 부족합니다. 상담사 확인 후 유지, 수정, 삭제 여부를 결정해주세요.</p>
      </div>
    )
  }

  const firstEvidence = evidence[0]

  return (
    <div className="text-[10px] leading-4">
      <div className="flex items-center justify-between gap-2 text-slate-500">
        <span className="font-extrabold text-slate-900">{firstEvidence.label} 원문</span>
        <span>{confidenceLabel[firstEvidence.confidence]}</span>
      </div>
      <p className="mt-2 max-h-[74px] overflow-hidden text-slate-700">
        {firstEvidence.excerpt || '표시할 원문 일부가 없습니다.'}
      </p>
      {firstEvidence.needsReview && <p className="mt-2 font-semibold text-amber-700">상담사 확인 필요</p>}
      {evidence.length > 1 && <p className="mt-2 font-semibold text-blue-700">근거 {evidence.length}개 연결</p>}
    </div>
  )
}

function DocumentTransformWorkspace({
  onBackToDraft,
  onCreateFinal,
  onSelectType,
  preview,
  sections,
  selectedType,
}: {
  onBackToDraft: () => void
  onCreateFinal: (documentType: FinalDocumentType) => void
  onSelectType: (documentType: FinalDocumentType) => void
  preview?: GenerateNoteResponse['document_transform_preview']
  sections: DraftSection[]
  selectedType: FinalDocumentType
}) {
  return (
    <section className="min-h-[calc(100vh-var(--workspace-header-height))] px-10 py-20">
      <div className="mx-auto max-w-[760px] text-center">
        <h1 className="text-2xl font-extrabold leading-tight tracking-normal text-black">어떤 문서로 변환할까요?</h1>
        <p className="mt-3 text-sm font-bold text-slate-500">회기 요약을 원하는 문서 양식대로 변환해드려요</p>
      </div>

      <div className="mx-auto mt-12 grid max-w-[730px] gap-6 md:grid-cols-3">
        {transformOptions.map((option) => (
          <button
            key={option.id}
            type="button"
            onClick={() => onSelectType(option.id)}
            className={`h-[226px] rounded-[8px] border bg-white p-6 text-center transition hover:-translate-y-0.5 hover:shadow-md ${
              selectedType === option.id ? 'border-blue-600 bg-blue-50' : 'border-slate-300'
            }`}
          >
            <div className="mx-auto flex h-[52px] w-[52px] items-center justify-center rounded-[12px] bg-blue-50 text-blue-700">
              <FileText className="h-7 w-7" />
            </div>
            <h2 className="mt-5 text-base font-extrabold text-black">{option.title}</h2>
            <p className="mt-3 overflow-hidden text-xs font-semibold leading-4 text-slate-500 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:3]">
              {option.description}
            </p>
            <span className="mt-4 inline-flex rounded-full bg-blue-50 px-3 py-1 text-[10px] font-bold text-blue-600">
              {getTransformOptionBadge(option.id)}
            </span>
          </button>
        ))}
      </div>

      <section className="mx-auto mt-10 max-w-[730px]">
        <div className="flex justify-center gap-4">
          <button
            type="button"
            onClick={onBackToDraft}
            className="inline-flex h-9 items-center justify-center rounded-md border border-blue-600 bg-white px-6 text-sm font-bold text-blue-700 hover:bg-blue-50"
          >
            초안으로 돌아가기
          </button>
          <button
            type="button"
            onClick={() => onCreateFinal(selectedType)}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-blue-600 px-7 text-sm font-bold text-white shadow-sm hover:bg-blue-700"
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
  onChangeSectionContent,
  sections,
}: {
  documentType: FinalDocumentType
  form: SessionInput
  onChangeSectionContent: (sectionId: string, content: string) => void
  sections: FinalDocumentSection[]
}) {
  const documentMeta = finalDocumentMeta[documentType]

  return (
    <section className="rounded-[7px] border border-slate-200 bg-white shadow-sm">
      <div className="rounded-t-[7px] bg-blue-600 px-4 py-3 text-white">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold tracking-normal">{documentMeta.title}</h1>
            <p className="mt-1.5 text-xs font-bold text-blue-50">
              내담자: {getClientDisplayName(form)} / 회기:{form.session_number}회기 / 날짜:{form.session_date}
            </p>
          </div>
        </div>
      </div>

      <div className="px-4 py-3">
        <p className="flex items-center gap-2 rounded-md bg-blue-50 px-3 py-2 text-xs font-semibold text-slate-600">
          <Info className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          아래 내용은 최종 파일에 그대로 반영됩니다.
        </p>
      </div>

      <div className="space-y-0 px-4 pb-5">
        {sections.map((section) => {
          const SectionIcon = getFinalDocumentSectionIcon(section.title)

          return (
            <section key={section.id} className="border-b border-[#c7d0df] py-5 last:border-b-0">
              <label htmlFor={`final-section-${section.id}`} className="flex items-center gap-1.5 pb-2 text-base font-bold text-blue-700">
                <SectionIcon className="h-4 w-4 shrink-0" />
                {section.title}
              </label>
              <textarea
                id={`final-section-${section.id}`}
                value={section.content}
                onChange={(event) => onChangeSectionContent(section.id, event.target.value)}
                className="mt-3 min-h-[110px] w-full resize-y rounded-md border border-slate-300 bg-white px-3 py-2 text-[13px] font-semibold leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </section>
          )
        })}
        {!sections.length && (
          <p className="py-10 text-center text-sm font-semibold text-slate-500">표시할 최종문서 섹션이 없습니다.</p>
        )}
      </div>
    </section>
  )
}

function getFinalDocumentSectionIcon(title: string): LucideIcon {
  if (title.includes('심리검사')) return ClipboardCheck
  if (title.includes('강점') || title.includes('자원')) return PenLine
  if (title.includes('상담자') || title.includes('개입')) return Edit3
  if (title.includes('내용') || title.includes('계획') || title.includes('요청')) return FileText
  return Bookmark
}

function SupervisionReportWorkspace({
  editingBlockId,
  editingText,
  error,
  expandedEvidenceId,
  isLoading,
  onBeginEdit,
  onChangeEditingText,
  onCommitEdit,
  onToggleEvidence,
  report,
}: {
  editingBlockId: string | null
  editingText: string
  error: string | null
  expandedEvidenceId: string | null
  isLoading: boolean
  onBeginEdit: (block: SupervisionContentBlock) => void
  onChangeEditingText: (value: string) => void
  onCommitEdit: () => void
  onToggleEvidence: (blockId: string | null) => void
  report: SupervisionReportDraft | null
}) {
  if (isLoading) {
    return (
      <div className="flex min-h-[420px] items-center justify-center rounded-[8px] border border-slate-200 bg-white shadow-sm">
        <div className="text-center">
          <Loader2 className="mx-auto h-8 w-8 animate-spin text-blue-700" />
          <p className="mt-4 text-sm font-bold text-slate-900">개인상담 사례 수퍼비전 보고서 초안을 생성 중입니다.</p>
          <p className="mt-2 text-xs font-semibold text-slate-500">회기요약, 축어록, 상담자 메모의 근거를 연결하고 있습니다.</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-[8px] border border-red-200 bg-red-50 p-5 text-sm font-semibold text-red-800">
        {error}
      </div>
    )
  }

  if (!report) {
    return (
      <div className="rounded-[8px] border border-slate-200 bg-white p-6 text-center text-sm font-semibold text-slate-500 shadow-sm">
        수퍼비전 보고서 초안이 아직 생성되지 않았습니다.
      </div>
    )
  }

  const tocSections = report.sections.filter((section) => section.level === 1)
  const editableSections = report.sections.filter((section) => section.level !== 1)

  return (
    <section className="rounded-[7px] border border-slate-200 bg-white shadow-sm">
      <div className="rounded-t-[7px] bg-blue-600 px-4 py-3 text-white">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold tracking-normal">{report.title}</h1>
            <p className="mt-1.5 text-xs font-bold text-blue-50">
              내담자: {report.meta.clientAlias || PLACEHOLDER_TEXT} / 회기:{report.meta.sessionNumber}회기 / 기준일:{formatCompactDate(report.meta.reportDate)}
            </p>
          </div>
          <button
            type="button"
            className="inline-flex h-8 items-center gap-2 rounded-[5px] bg-white px-5 text-xs font-bold text-blue-700 shadow-sm hover:bg-blue-50"
          >
            <Edit3 className="h-4 w-4" />
            수정하기
          </button>
        </div>
      </div>

      <div className="grid gap-3 px-4 py-3 sm:grid-cols-2">
        {[
          ['상담자', report.meta.counselorName],
          ['소속 상담기관', report.meta.institution],
          ['수퍼바이저', report.meta.supervisor],
          ['수퍼비전 일시 및 장소', report.meta.supervisionDatePlace],
        ].map(([label, value]) => (
          <div key={label} className="rounded-[8px] bg-slate-50 px-3 py-2">
            <p className="text-xs font-bold text-slate-500">{label}</p>
            <p className="mt-1 text-sm font-bold text-slate-950">{value || PLACEHOLDER_TEXT}</p>
          </div>
        ))}
      </div>

      <div className="px-4 pb-3">
        <p className="flex items-center gap-2 rounded-md bg-blue-50 px-3 py-2 text-xs font-semibold text-slate-600">
          <Info className="h-3.5 w-3.5 shrink-0 text-slate-500" />
          하이라이트된 문장은 AI가 생성한 문장입니다.
        </p>
      </div>

      <div className="border-y border-slate-100 bg-slate-50/70 px-4 py-3">
        <div className="flex flex-wrap gap-2">
          {tocSections.map((section) => (
            <span key={section.id} className="rounded-full border border-blue-100 bg-white px-3 py-1 text-xs font-bold text-blue-700">
              {section.title}
            </span>
          ))}
        </div>
      </div>

      <div className="px-4 pb-5">
        {report.sections.map((section) => (
          <SupervisionReportSectionView
            key={section.id}
            editingBlockId={editingBlockId}
            editingText={editingText}
            evidenceIndex={report.evidenceIndex}
            expandedEvidenceId={expandedEvidenceId}
            section={section}
            onBeginEdit={onBeginEdit}
            onChangeEditingText={onChangeEditingText}
            onCommitEdit={onCommitEdit}
            onToggleEvidence={onToggleEvidence}
          />
        ))}
        {!editableSections.length && (
          <p className="py-10 text-center text-sm font-semibold text-slate-500">표시할 보고서 섹션이 없습니다.</p>
        )}
      </div>
    </section>
  )
}

function SupervisionReportSectionView({
  editingBlockId,
  editingText,
  evidenceIndex,
  expandedEvidenceId,
  onBeginEdit,
  onChangeEditingText,
  onCommitEdit,
  onToggleEvidence,
  section,
}: {
  editingBlockId: string | null
  editingText: string
  evidenceIndex: SupervisionReportDraft['evidenceIndex']
  expandedEvidenceId: string | null
  onBeginEdit: (block: SupervisionContentBlock) => void
  onChangeEditingText: (value: string) => void
  onCommitEdit: () => void
  onToggleEvidence: (blockId: string | null) => void
  section: SupervisionReportSection
}) {
  if (section.level === 1) {
    return (
      <section className="border-b border-[#c7d0df] py-5">
        <h2 className="text-lg font-extrabold text-slate-950">{section.title}</h2>
      </section>
    )
  }

  const SectionIcon = getFinalDocumentSectionIcon(section.title)

  return (
    <section className="border-b border-[#c7d0df] py-5 last:border-b-0">
      <div className="flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-base font-bold text-blue-700">
          <SectionIcon className="h-4 w-4 shrink-0" />
          {section.title}
        </h2>
        <SupervisionStatusBadge status={section.status} />
      </div>

      <div className="mt-3 space-y-3">
        {section.contentBlocks.map((block) => (
          <SupervisionContentBlockView
            key={block.id}
            block={block}
            editing={editingBlockId === block.id}
            editingText={editingText}
            evidenceIndex={evidenceIndex}
            evidenceOpen={expandedEvidenceId === block.id}
            onBeginEdit={onBeginEdit}
            onChangeEditingText={onChangeEditingText}
            onCommitEdit={onCommitEdit}
            onToggleEvidence={() => onToggleEvidence(expandedEvidenceId === block.id ? null : block.id)}
          />
        ))}
      </div>
    </section>
  )
}

function SupervisionContentBlockView({
  block,
  editing,
  editingText,
  evidenceIndex,
  evidenceOpen,
  onBeginEdit,
  onChangeEditingText,
  onCommitEdit,
  onToggleEvidence,
}: {
  block: SupervisionContentBlock
  editing: boolean
  editingText: string
  evidenceIndex: SupervisionReportDraft['evidenceIndex']
  evidenceOpen: boolean
  onBeginEdit: (block: SupervisionContentBlock) => void
  onChangeEditingText: (value: string) => void
  onCommitEdit: () => void
  onToggleEvidence: () => void
}) {
  return (
    <div className="relative rounded-[8px] border border-slate-200 bg-white p-3 shadow-sm">
      <div className="mb-2 flex flex-wrap gap-1.5">
        <SupervisionBlockChip label="초안" tone="slate" />
        {block.aiGenerated && <SupervisionBlockChip label="AI 생성" tone="blue" />}
        {(block.reviewStatus === 'needs_human_input' || Boolean(block.warnings?.length)) && (
          <SupervisionBlockChip label="확인 필요" tone="rose" />
        )}
        {block.reviewStatus === 'edited' && <SupervisionBlockChip label="수정됨" tone="amber" />}
        {block.demoValue && <SupervisionBlockChip label="데모값" tone="amber" />}
        {Boolean(block.evidenceIds.length) && (
          <button type="button" onClick={onToggleEvidence} className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-700">
            근거 확인
          </button>
        )}
      </div>

      {editing ? (
        <textarea
          autoFocus
          value={editingText}
          onBlur={onCommitEdit}
          onChange={(event) => onChangeEditingText(event.target.value)}
          onKeyDown={(event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
              onCommitEdit()
            }
          }}
          className="min-h-[120px] w-full resize-y rounded-md border border-blue-200 bg-white px-3 py-2 text-[13px] font-semibold leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        />
      ) : (
        <button
          type="button"
          onClick={() => onBeginEdit(block)}
          className="block w-full rounded-[6px] px-1 py-1 text-left hover:bg-slate-50"
        >
          <SupervisionBlockContent block={block} />
        </button>
      )}

      {Boolean(block.warnings?.length) && (
        <ul className="mt-2 space-y-1 text-[11px] font-semibold leading-4 text-amber-700">
          {block.warnings?.map((warning) => <li key={warning}>· {warning}</li>)}
        </ul>
      )}

      {evidenceOpen && (
        <div className="absolute right-3 top-9 z-20 max-h-[240px] w-[260px] overflow-auto rounded-[8px] border border-slate-100 bg-white p-3 text-left shadow-[0_14px_32px_rgba(15,23,42,0.18)]">
          <p className="text-xs font-extrabold text-slate-950">연결 근거</p>
          {block.evidenceIds.length ? (
            <div className="mt-2 space-y-2">
              {block.evidenceIds.map((evidenceId) => {
                const evidence = evidenceIndex[evidenceId]
                return (
                  <div key={evidenceId} className="rounded-md bg-slate-50 p-2">
                    <p className="text-[10px] font-bold text-blue-700">{evidence?.label || evidenceId}</p>
                    <p className="mt-1 text-[11px] font-semibold leading-4 text-slate-700">
                      {evidence?.text || evidenceId}
                    </p>
                  </div>
                )
              })}
            </div>
          ) : (
            <p className="mt-2 text-[11px] font-semibold text-slate-500">연결된 근거가 없어 상담사 확인이 필요합니다.</p>
          )}
        </div>
      )}
    </div>
  )
}

function SupervisionBlockContent({ block }: { block: SupervisionContentBlock }) {
  if (block.type === 'table' && block.rows?.length) {
    const headers = Object.keys(block.rows[0])
    return (
      <div className="overflow-hidden rounded-[7px] border border-slate-200">
        <table className="w-full border-collapse text-left text-[12px] font-semibold">
          <thead className="bg-slate-50 text-slate-500">
            <tr>
              {headers.map((header) => (
                <th key={header} className="border-b border-slate-200 px-2 py-2">
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-slate-900">
            {block.rows.map((row, index) => (
              <tr key={`${block.id}-${index}`} className="border-b border-slate-100 last:border-b-0">
                {headers.map((header) => (
                  <td key={header} className="px-2 py-2 align-top">
                    {row[header]}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )
  }

  if (block.type === 'transcript' && block.speakerTurns?.length) {
    return (
      <div className="space-y-2">
        {block.speakerTurns.map((turn) => (
          <div key={turn.turnId} className="grid gap-2 rounded-md bg-slate-50 px-3 py-2 text-[13px] font-semibold leading-5 sm:grid-cols-[52px_minmax(0,1fr)]">
            <span className="text-blue-700">{turn.speaker === 'client' ? '내담자' : '상담자'}</span>
            <span className="text-slate-900">{turn.text}</span>
          </div>
        ))}
      </div>
    )
  }

  if (block.type === 'reflection_box') {
    return (
      <div className="rounded-[8px] border border-blue-100 bg-blue-50/70 px-3 py-2 text-[13px] font-semibold leading-6 text-slate-900">
        {block.text || PLACEHOLDER_TEXT}
      </div>
    )
  }

  return (
    <p className={`whitespace-pre-wrap text-[13px] font-semibold leading-6 ${block.type === 'placeholder' ? 'text-rose-700' : 'text-slate-900'}`}>
      {block.text || PLACEHOLDER_TEXT}
    </p>
  )
}

function SupervisionReviewPanel({
  aiReview,
  capabilities,
  capabilitiesError,
  draftSaveMessage,
  exportError,
  exportStatus,
  isExporting,
  isSavingDraft,
  onBack,
  onDownload,
  onTemporarySave,
}: {
  aiReview: SupervisionAiReviewPanel
  capabilities: DocumentCapabilitiesResponse | null
  capabilitiesError: string | null
  draftSaveMessage: string | null
  exportError: string | null
  exportStatus: string | null
  isExporting: boolean
  isSavingDraft: boolean
  onBack: () => void
  onDownload: (format: DocumentExportFormat) => void
  onTemporarySave: () => void
}) {
  return (
    <aside className="review-panel-compact flex flex-col rounded-[8px] border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div className="flex items-center gap-2">
          <Workflow className="h-4 w-4 text-blue-700" />
          <p className="text-lg font-extrabold text-slate-950">AI 검토</p>
        </div>
        <p className="mt-2 text-xs font-semibold leading-5 text-slate-500">
          AI가 문서 검토 후 보완이 필요한 항목을 확인했습니다.
        </p>
        <button
          type="button"
          onClick={onBack}
          className="mt-4 inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-[6px] border border-blue-600 bg-white px-3 text-sm font-bold text-blue-700 hover:bg-blue-50"
        >
          <ArrowLeft className="h-4 w-4" />
          이전 단계
        </button>
      </div>

      <SupervisionReviewGroup
        title="양식 충족도"
        items={aiReview.completionChecklist.map((item) => `${reviewStatusSymbol[item.status]} ${item.label}${item.reason ? ` · ${item.reason}` : ''}`)}
      />
      <SupervisionReviewGroup title="상담사 확인 필요" items={aiReview.needsHumanReview.map((item) => item.message)} />
      <SupervisionReviewGroup title="데모 입력값" items={aiReview.demoInputs} />
      <SupervisionReviewGroup title="누락된 내용" items={aiReview.missingFields} />
      <SupervisionReviewGroup
        title="근거 부족 문장"
        items={aiReview.unsupportedClaims.map((item) => `${item.claim} → ${item.reason}`)}
        emptyLabel="근거 부족 문장 없음"
      />
      <SupervisionReviewGroup title="수퍼비전 질문 후보" items={aiReview.suggestedSupervisionQuestions} numbered />
      <section className="mt-4">
        <h3 className="flex items-center gap-1.5 text-sm font-bold text-slate-900">
          <Info className="h-3.5 w-3.5" />
          주의 문구
        </h3>
        <p className="mt-2 rounded-[8px] border border-slate-200 bg-slate-50 p-3 text-xs font-semibold leading-5 text-slate-700">
          {aiReview.caution}
        </p>
      </section>

      <div className="mt-auto space-y-3 pt-8">
        {draftSaveMessage && <p className="text-xs font-semibold text-slate-500">{draftSaveMessage}</p>}
        <button
          type="button"
          onClick={onTemporarySave}
          disabled={isSavingDraft}
          className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-[6px] border border-dashed border-slate-400 bg-white px-3 text-sm font-bold text-slate-500 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
        >
          {isSavingDraft ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {isSavingDraft ? '저장중' : '임시저장'}
        </button>
        <DownloadControls
          capabilities={capabilities}
          capabilitiesError={capabilitiesError}
          error={exportError}
          isExporting={isExporting}
          status={exportStatus}
          onDownload={onDownload}
        />
      </div>
    </aside>
  )
}

function SupervisionReviewGroup({
  emptyLabel = '현재 표시할 항목이 없습니다.',
  items,
  numbered = false,
  title,
}: {
  emptyLabel?: string
  items: string[]
  numbered?: boolean
  title: string
}) {
  return (
    <section className="mt-4">
      <h3 className="flex items-center gap-1.5 text-sm font-bold text-slate-900">
        <Info className="h-3.5 w-3.5 shrink-0" />
        {title}
      </h3>
      <div className="mt-2 rounded-[8px] border border-slate-200 bg-white p-3 shadow-sm">
        {items.length ? (
          <ul className="space-y-1 text-xs font-semibold leading-5 text-slate-900">
            {items.map((item, index) => (
              <li key={`${title}-${item}`}>{numbered ? `${index + 1}. ` : '· '}{item}</li>
            ))}
          </ul>
        ) : (
          <p className="text-xs font-semibold text-slate-500">{emptyLabel}</p>
        )}
      </div>
    </section>
  )
}

function SupervisionBlockChip({ label, tone }: { label: string; tone: 'amber' | 'blue' | 'rose' | 'slate' }) {
  const className =
    tone === 'blue'
      ? 'bg-blue-50 text-blue-700'
      : tone === 'rose'
        ? 'bg-rose-50 text-rose-700'
        : tone === 'slate'
          ? 'bg-slate-100 text-slate-700'
        : 'bg-amber-50 text-amber-700'
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${className}`}>{label}</span>
}

function SupervisionStatusBadge({ status }: { status: SupervisionReportSection['status'] }) {
  const label = status === 'complete' ? '완료' : status === 'partial' ? '부분작성' : status === 'missing' ? '누락' : '확인필요'
  const className =
    status === 'complete'
      ? 'bg-emerald-50 text-emerald-700'
      : status === 'missing'
        ? 'bg-rose-50 text-rose-700'
        : 'bg-amber-50 text-amber-700'
  return <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${className}`}>{label}</span>
}

function ReviewPanel({
  activeStep,
  checklistItems,
  currentScreen,
  draftRecomposeMessage,
  fullResponse,
  isLoading,
  isRecomposingDraft,
  missingItems,
  onAddCustomSection,
  onGoBack,
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
  draftRecomposeMessage: string | null
  fullResponse?: GenerateNoteResponse
  isLoading: boolean
  isRecomposingDraft: boolean
  missingItems: string[]
  onAddCustomSection: () => void
  onGoBack: () => void
  onGoToTransform: () => void
  onTogglePreviousSession: (sessionId: string) => void
  onToggleSection: (sectionId: DraftSectionId) => void
  resultReady: boolean
  selectedPreviousSessionIds: string[]
  visibleSectionIds: Set<DraftSectionId>
  warnings: string[]
}) {
  const isSummaryDraft = currentScreen === 'summary_draft'
  const isSessionInput = currentScreen === 'session_input'

  return (
    <aside
      className={`review-panel-compact flex flex-col rounded-[8px] border border-slate-200 bg-white shadow-sm ${
        isSummaryDraft ? 'p-5' : isSessionInput ? 'p-3.5' : 'p-6'
      }`}
    >
      {currentScreen === 'session_input' ? (
        <PreviousSessionLinkPanel
          selectedIds={selectedPreviousSessionIds}
          onToggle={onTogglePreviousSession}
        />
      ) : (
        <>
          <div>
            {!isSummaryDraft && <p className="text-xs font-semibold uppercase tracking-wide text-blue-600">{activeStep}</p>}
            <h2 className={`${isSummaryDraft ? 'text-lg' : 'mt-2 text-lg'} font-bold`}>요약에 포함할 항목</h2>
            {draftRecomposeMessage && (
              <p className="mt-2 text-[11px] font-semibold leading-4 text-slate-500">{draftRecomposeMessage}</p>
            )}
          </div>

          <div className={isSummaryDraft ? 'mt-4 space-y-2.5' : 'mt-4 space-y-2'}>
            {checklistItems.map((item) => {
              const checked = visibleSectionIds.has(item.id)
              return (
                <label
                  key={item.id}
                  className={`flex cursor-pointer items-center rounded-[8px] font-semibold ${
                    isSummaryDraft ? 'h-8 gap-3 px-3.5 text-sm' : 'gap-2.5 px-3 py-2 text-sm'
                  } ${checked ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-500'}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={isRecomposingDraft}
                    onChange={() => onToggleSection(item.id)}
                    className="sr-only"
                  />
                  <span
                    className={`flex shrink-0 items-center justify-center rounded-full ${isSummaryDraft ? 'h-[18px] w-[18px]' : 'h-4 w-4'} ${
                      checked ? 'bg-blue-600' : 'bg-slate-300'
                    }`}
                  >
                    <Check className={`${isSummaryDraft ? 'h-3.5 w-3.5' : 'h-3 w-3'} text-white`} />
                  </span>
                  <span className="truncate">{item.title}</span>
                </label>
              )
            })}
          </div>

          <button
            type="button"
            onClick={onAddCustomSection}
            disabled={!resultReady || isRecomposingDraft}
            className={`mt-2 inline-flex w-full items-center justify-center gap-2 border bg-white font-semibold hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300 ${
              isSummaryDraft
                ? 'h-8 rounded-[8px] border-slate-950 px-3 text-sm text-slate-950'
                : 'rounded-md border-slate-300 px-3 py-2 text-sm text-slate-700'
            }`}
          >
            <Plus className="h-4 w-4" />
            항목 추가
          </button>

          {isSummaryDraft && fullResponse && <RetrievalContextPanel fullResponse={fullResponse} />}
        </>
      )}

      <div className="mt-auto pt-5">
        <div className="grid grid-cols-2 gap-2.5">
          <button
            type="button"
            onClick={onGoBack}
            disabled={isSessionInput}
            className="inline-flex h-12 items-center justify-center gap-1.5 rounded-[6px] border border-blue-600 bg-white px-3 text-sm font-bold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:border-slate-200 disabled:text-slate-300"
          >
            <ArrowLeft className="h-4 w-4" />
            이전 단계
          </button>
          {isSessionInput ? (
            <button
              type="submit"
              form="session-input-form"
              disabled={isLoading}
              className="inline-flex h-12 items-center justify-center gap-1.5 rounded-[6px] bg-blue-600 px-3 text-sm font-bold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              요약초안
            </button>
          ) : (
            <button
              type="button"
              onClick={onGoToTransform}
              disabled={!resultReady || isRecomposingDraft}
              className="inline-flex h-12 items-center justify-center gap-1.5 rounded-[6px] bg-blue-600 px-3 text-sm font-bold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
            >
              문서 변환
              <ChevronRight className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </aside>
  )
}

function RetrievalContextPanel({ fullResponse }: { fullResponse: GenerateNoteResponse }) {
  const caseContext = fullResponse.retrieved_case_context || []
  const template = fullResponse.retrieved_template_context
  const privacyRules = fullResponse.retrieved_privacy_context || []
  const report = fullResponse.retrieval_report
  const templateMissing = template?.missing_field_checklist || []
  const notices = report?.notices || []

  return (
    <div className="mt-5 space-y-4 border-t border-slate-200 pt-4">
      <RetrievalMiniSection
        icon={<History className="h-4 w-4 text-blue-700" />}
        title="이전 회기에서 참고된 근거"
        items={
          caseContext.length
            ? caseContext.slice(0, 3).map((item) =>
                `${item.session_number ? `${item.session_number}회기` : '이전 회기'} · ${
                  item.summary || '저장된 회기 기록'
                }`,
              )
            : ['연결된 이전 회기 근거 없음']
        }
      />
      <RetrievalMiniSection
        icon={<ClipboardList className="h-4 w-4 text-blue-700" />}
        title="문서 양식 기준 누락 항목"
        items={
          templateMissing.length
            ? templateMissing.slice(0, 5)
            : template
              ? ['현재 양식 KB에서 추가 누락 항목 없음']
              : ['문서 양식 KB 미연결']
        }
      />
      <RetrievalMiniSection
        icon={<ShieldCheck className="h-4 w-4 text-blue-700" />}
        title="개인정보/윤리 검토 경고"
        items={
          privacyRules.length
            ? privacyRules.slice(0, 4).map((item) => item.warning)
            : ['개인정보/윤리 KB 미연결']
        }
      />
      {Boolean(notices.length) && (
        <p className="text-[11px] font-semibold leading-4 text-slate-500">{notices.slice(0, 2).join(' · ')}</p>
      )}
    </div>
  )
}

function RetrievalMiniSection({
  icon,
  items,
  title,
}: {
  icon: ReactNode
  items: string[]
  title: string
}) {
  return (
    <section>
      <div className="flex items-center gap-2">
        {icon}
        <h3 className="text-xs font-extrabold text-slate-950">{title}</h3>
      </div>
      <ul className="mt-2 space-y-1.5">
        {items.map((item) => (
          <li key={item} className="text-[11px] font-semibold leading-4 text-slate-600">
            {item}
          </li>
        ))}
      </ul>
    </section>
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
      <div className="flex items-start gap-2.5">
        <History className="mt-0.5 h-6 w-6 shrink-0 text-blue-700" />
        <div>
          <h2 className="text-lg font-bold text-slate-950">이전 회기 기록</h2>
          <p className="mt-1.5 whitespace-nowrap text-xs leading-5 text-slate-500">클릭하면 이전 회기 내용을 불러옵니다.</p>
        </div>
      </div>

      <div className="mt-4 space-y-3">
        {previousSessionOptions.map((session) => {
          const selected = selectedIds.includes(session.id)
          return (
            <button
              key={session.id}
              type="button"
              aria-pressed={selected}
              onClick={() => onToggle(session.id)}
              className={`min-h-[110px] w-full rounded-[9px] border p-3.5 text-left transition ${
                selected
                  ? 'border-blue-600 bg-blue-50 shadow-sm'
                  : 'border-slate-300 bg-white hover:border-blue-300 hover:bg-blue-50/40'
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-bold text-blue-700">{session.label}</p>
                  <p className="mt-1 text-[11px] font-medium text-slate-500">{session.date}</p>
                </div>
                {selected && <CheckCircle2 className="h-4 w-4 shrink-0 text-blue-700" />}
              </div>
              <p className="mt-3 overflow-hidden text-[12.5px] font-semibold leading-5 text-slate-900 [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2]">
                {session.summary}
              </p>
            </button>
          )
        })}
      </div>

    </section>
  )
}

function FinalReviewPanel({
  documentType,
  capabilities,
  capabilitiesError,
  draftSaveMessage,
  exportError,
  exportStatus,
  isExporting,
  isSavingDraft,
  missingItems,
  onBack,
  onDownload,
  onTemporarySave,
  warnings,
}: {
  documentType: FinalDocumentType
  capabilities: DocumentCapabilitiesResponse | null
  capabilitiesError: string | null
  draftSaveMessage: string | null
  exportError: string | null
  exportStatus: string | null
  isExporting: boolean
  isSavingDraft: boolean
  missingItems: string[]
  onBack: () => void
  onDownload: (format: DocumentExportFormat) => void
  onTemporarySave: () => void
  warnings: string[]
}) {
  return (
    <aside className="review-panel-compact flex flex-col rounded-[8px] border border-slate-200 bg-white p-5 shadow-sm">
      <div>
        <div className="flex items-center gap-2">
          <Workflow className="h-4 w-4 text-blue-700" />
          <p className="text-lg font-extrabold text-slate-950">AI 검토</p>
        </div>
        <p className="mt-3 text-xs font-semibold leading-5 text-slate-500">
          {finalDocumentMeta[documentType].title}에서 상담사 확인이 필요한 항목입니다.
        </p>
        <button
          type="button"
          onClick={onBack}
          className="mt-4 inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-[6px] border border-blue-600 bg-white px-3 text-sm font-bold text-blue-700 hover:bg-blue-50"
        >
          <ArrowLeft className="h-4 w-4" />
          이전 단계
        </button>
      </div>

      <FinalReviewCard
        title="수정 필요"
        items={['상담 목표 표현 구체화 필요', '내담자 반응 서술 보완 권장', '다음 회기 계획 구체화 필요']}
      />
      <FinalReviewCard
        title="누락 가능"
        items={
          missingItems.length
            ? missingItems.slice(0, 3)
            : ['과제 수행 여부 추가 확인 필요', '감정 변화 정도 보완 필요', '상담자 개입 내용 추가 기록 권장']
        }
      />
      <FinalReviewCard
        title="근거 확인"
        items={
          warnings.length
            ? warnings.slice(0, 3)
            : ['요약 문장의 원문 근거 확인 필요', '해석 표현의 근거 보강 필요', '이전 회기와의 연결 근거 확인 필요']
        }
      />

      <div className="mt-auto space-y-3 pt-8">
        {draftSaveMessage && <p className="text-xs font-semibold text-slate-500">{draftSaveMessage}</p>}
        <button
          type="button"
          onClick={onTemporarySave}
          disabled={isSavingDraft}
          className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-[6px] border border-dashed border-slate-400 bg-white px-3 text-sm font-bold text-slate-500 hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-300"
        >
          {isSavingDraft ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {isSavingDraft ? '저장중' : '임시저장'}
        </button>
        <DownloadControls
          capabilities={capabilities}
          capabilitiesError={capabilitiesError}
          error={exportError}
          isExporting={isExporting}
          status={exportStatus}
          onDownload={onDownload}
        />
      </div>
    </aside>
  )
}

function DownloadControls({
  capabilities,
  capabilitiesError,
  error,
  isExporting,
  onDownload,
  status,
}: {
  capabilities: DocumentCapabilitiesResponse | null
  capabilitiesError: string | null
  error: string | null
  isExporting: boolean
  onDownload: (format: DocumentExportFormat) => void
  status: string | null
}) {
  const pdfUnavailableReason = !capabilities
    ? '문서 내보내기 지원 상태를 확인한 뒤 PDF를 사용할 수 있습니다.'
    : capabilities.pdf.available === false
      ? capabilityReasonToKorean(capabilities.pdf.reason)
      : capabilitiesError
        ? '문서 내보내기 지원 상태를 확인하지 못해 PDF 다운로드를 비활성화했습니다.'
        : null
  const pdfDisabled = isExporting || Boolean(pdfUnavailableReason)

  return (
    <div className="rounded-[8px] border border-slate-200 bg-slate-50 p-3">
      <div className="flex items-center gap-2 text-sm font-extrabold text-slate-950">
        <Download className="h-4 w-4 text-blue-700" />
        다운로드
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => onDownload('docx')}
          disabled={isExporting}
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-[6px] bg-blue-600 px-2 text-xs font-bold text-white shadow-sm hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {isExporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
          Word(.docx)
        </button>
        <button
          type="button"
          onClick={() => onDownload('pdf')}
          disabled={pdfDisabled}
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-[6px] border border-blue-600 bg-white px-2 text-xs font-bold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:border-slate-300 disabled:text-slate-400"
        >
          {isExporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ClipboardList className="h-3.5 w-3.5" />}
          PDF(.pdf)
        </button>
      </div>
      {pdfUnavailableReason && <p className="mt-2 text-xs font-semibold leading-5 text-slate-500">{pdfUnavailableReason}</p>}
      {status && <p className="mt-2 text-xs font-semibold text-emerald-700">{status}</p>}
      {error && <p className="mt-2 text-xs font-semibold leading-5 text-red-700">{error}</p>}
    </div>
  )
}

function FinalReviewCard({ items, title }: { items: string[]; title: string }) {
  return (
    <section className="mt-4">
      <h3 className="flex items-center gap-1.5 text-sm font-bold text-slate-900">
        <Info className="h-3.5 w-3.5 shrink-0 text-slate-900" />
        {title}
      </h3>
      <div className="mt-2 rounded-[8px] border border-slate-200 bg-white p-3 shadow-sm">
        <ul className="space-y-1 text-xs font-semibold leading-5 text-slate-900">
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
    <div className="rounded-[8px] bg-slate-50 px-3 py-2">
      <dt className="text-xs font-bold text-slate-950">{label}</dt>
      <dd className="mt-1 truncate text-xs font-semibold text-blue-700">{value}</dd>
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
    <div className="material-row flex items-center justify-between gap-3 px-3 py-1">
      <div className="min-w-0">
        <p className="text-sm font-bold text-slate-950">{label}</p>
        <p className="mt-0.5 truncate text-xs text-slate-500">{meta}</p>
      </div>
      <button
        type="button"
        onClick={onAction}
        className="h-7 shrink-0 rounded-md border border-slate-200 px-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
      >
        {actionLabel}
      </button>
    </div>
  )
}

function UploadedMaterialRow({
  material,
  onApply,
  onDelete,
  onPreview,
  onTranscribe,
  transcriptionAvailable,
  transcriptionReason,
}: {
  material: UploadedMaterial
  onApply: () => void
  onDelete: () => void
  onPreview: () => void
  onTranscribe: () => void
  transcriptionAvailable: boolean
  transcriptionReason: string | null
}) {
  const isDocumentReady = material.kind === 'document' && ['completed', 'warning'].includes(material.status)
  const isAudioReady = material.kind === 'audio' && material.status === 'transcribed'
  const canApply = isDocumentReady || isAudioReady
  const canPreview = canApply
  const canTranscribe =
    material.kind === 'audio' &&
    material.status !== 'transcribed' &&
    material.status !== 'transcribing' &&
    transcriptionAvailable

  return (
    <div className="material-row px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-950">
            {material.kind === 'document' ? '📄' : '🎧'} {material.filename}
          </p>
          <p className="mt-0.5 text-xs text-slate-500">{materialMetaText(material)}</p>
          {material.error && <p className="mt-1 text-xs font-semibold text-rose-600">{material.error}</p>}
          {material.kind === 'audio' && !transcriptionAvailable && material.status !== 'transcribed' && (
            <p className="mt-1 text-xs text-slate-500">{transcriptionReason || '음성 자동 축어록은 현재 비활성화되어 있습니다.'}</p>
          )}
        </div>
        {material.status === 'uploading' || material.status === 'transcribing' ? (
          <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin text-blue-600" />
        ) : material.status === 'failed' ? (
          <AlertTriangle className="mt-1 h-4 w-4 shrink-0 text-rose-600" />
        ) : (
          <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-emerald-600" />
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        {canPreview && (
          <button
            type="button"
            onClick={onPreview}
            className="h-7 rounded-md border border-slate-200 px-2.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
          >
            {material.kind === 'audio' ? '축어록 확인' : '내용 확인'}
          </button>
        )}
        {canApply && (
          <button
            type="button"
            onClick={onApply}
            className="h-7 rounded-md border border-blue-200 bg-blue-50 px-2.5 text-xs font-bold text-blue-700 hover:bg-blue-100"
          >
            자료에 반영
          </button>
        )}
        {material.kind === 'audio' && material.status !== 'transcribed' && (
          <button
            type="button"
            onClick={onTranscribe}
            disabled={!canTranscribe}
            className="h-7 rounded-md border border-slate-200 px-2.5 text-xs font-medium text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            축어록 생성
          </button>
        )}
        <button
          type="button"
          onClick={onDelete}
          className="h-7 rounded-md border border-slate-200 px-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
        >
          삭제
        </button>
      </div>
    </div>
  )
}

function MaterialUploadList({ materials }: { materials: UploadedMaterial[] }) {
  if (!materials.length) {
    return <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">아직 선택된 파일이 없습니다.</p>
  }
  return (
    <div className="divide-y divide-slate-200 rounded-lg border border-slate-200">
      {materials.map((material) => (
        <div key={material.id} className="px-3 py-2">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-bold text-slate-900">{material.filename}</p>
              <p className="mt-0.5 text-xs text-slate-500">{materialMetaText(material)}</p>
            </div>
            {material.status === 'uploading' || material.status === 'transcribing' ? (
              <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
            ) : material.status === 'failed' ? (
              <AlertTriangle className="h-4 w-4 text-rose-600" />
            ) : (
              <CheckCircle2 className="h-4 w-4 text-emerald-600" />
            )}
          </div>
          {material.error && <p className="mt-1 text-xs font-semibold text-rose-600">{material.error}</p>}
          {material.warnings.length > 0 && (
            <p className="mt-1 text-xs text-amber-700">{material.warnings.join(' ')}</p>
          )}
        </div>
      ))}
    </div>
  )
}

function MaterialSummary({ material }: { material: UploadedMaterial }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <p className="truncate text-sm font-bold text-slate-950">{material.filename}</p>
      <p className="mt-1 text-xs text-slate-500">{materialMetaText(material)}</p>
      {material.warnings.length > 0 && (
        <p className="mt-2 text-xs font-medium text-amber-700">{material.warnings.join(' ')}</p>
      )}
    </div>
  )
}

function MaterialModal({
  audioCapabilities,
  audioCapabilitiesError,
  form,
  materials,
  mode,
  onAddAudioFiles,
  onApplyMaterial,
  onClose,
  onModeChange,
  onRefreshAudioCapabilities,
  onTranscribeAudio,
  onUpdateAudioSegmentText,
  onUpdateAudioTranscript,
  onUpdateField,
  onUpdateSessionTopic,
  onUploadDocumentFiles,
  selectedMaterial,
  sessionTopic,
}: {
  audioCapabilities: AudioCapabilitiesResponse | null
  audioCapabilitiesError: string | null
  form: SessionInput
  materials: UploadedMaterial[]
  mode: MaterialModalMode
  onAddAudioFiles: (files: FileList | null) => void
  onApplyMaterial: (materialId: string, target: MaterialApplyTarget, mode: MaterialApplyMode) => void
  onClose: () => void
  onModeChange: (mode: MaterialModalMode) => void
  onRefreshAudioCapabilities: () => Promise<AudioCapabilitiesResponse>
  onTranscribeAudio: (materialId: string) => void
  onUpdateAudioSegmentText: (materialId: string, segmentId: number, text: string) => void
  onUpdateAudioTranscript: (materialId: string, text: string) => void
  onUpdateField: (field: keyof SessionInput, value: string | number) => void
  onUpdateSessionTopic: (value: string) => void
  onUploadDocumentFiles: (files: FileList | null) => Promise<void>
  selectedMaterial: UploadedMaterial | null
  sessionTopic: string
}) {
  const textModalConfig = getTextModalConfig(mode)
  const [audioConsent, setAudioConsent] = useState(false)
  const [applyTarget, setApplyTarget] = useState<MaterialApplyTarget>('counselor_memo')
  const [applyMode, setApplyMode] = useState<MaterialApplyMode>('append')
  const selectedText = getMaterialText(selectedMaterial)
  const transcriptionAvailable = Boolean(audioCapabilities?.transcription.available)

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
                title="문서 업로드"
                description="문서 내용을 추출해 상담 자료에 반영합니다."
                onClick={() => onModeChange('document_upload')}
              />
              <AddOption
                title="음성 업로드"
                description="상담 음성을 축어록 초안으로 변환합니다."
                onClick={() => {
                  onModeChange('audio_upload')
                  void onRefreshAudioCapabilities()
                }}
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
              <Field label="내담자 가명" htmlFor="modal_client_alias">
                <input
                  id="modal_client_alias"
                  value={form.client_alias || ''}
                  onChange={(event) => onUpdateField('client_alias', event.target.value)}
                  className={inputClass}
                  placeholder="비워두면 케이스 ID로 표시됩니다."
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

          {mode === 'document_upload' && (
            <div className="space-y-4">
              <label className="block rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-8 text-center">
                <FileText className="mx-auto h-7 w-7 text-slate-400" />
                <span className="mt-3 block text-sm font-medium text-slate-700">PDF, DOCX, TXT 문서 선택</span>
                <span className="mt-1 block text-xs text-slate-500">추출된 내용은 미리보기 후 원하는 입력칸에 반영합니다.</span>
                <input
                  type="file"
                  multiple
                  accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                  className="sr-only"
                  onChange={(event) => {
                    void onUploadDocumentFiles(event.target.files)
                    event.target.value = ''
                  }}
                />
              </label>
              <MaterialUploadList materials={materials.filter((material) => material.kind === 'document')} />
              <ModalDoneButton onClick={onClose} />
            </div>
          )}

          {mode === 'file_upload' && (
            <div className="space-y-4">
              <button
                type="button"
                onClick={() => onModeChange('document_upload')}
                className="w-full rounded-lg border border-slate-300 px-4 py-3 text-left text-sm font-bold hover:bg-slate-50"
              >
                문서 업로드
              </button>
              <button
                type="button"
                onClick={() => {
                  onModeChange('audio_upload')
                  void onRefreshAudioCapabilities()
                }}
                className="w-full rounded-lg border border-slate-300 px-4 py-3 text-left text-sm font-bold hover:bg-slate-50"
              >
                음성 업로드
              </button>
            </div>
          )}

          {mode === 'audio_upload' && (
            <div className="space-y-4">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
                원본 음성은 저장하지 않으며, 자동 축어록은 서버 런타임이 활성화된 경우에만 실행됩니다.
              </div>
              <label className="flex items-start gap-3 rounded-lg border border-slate-200 p-3 text-sm text-slate-700">
                <input
                  type="checkbox"
                  checked={audioConsent}
                  onChange={(event) => setAudioConsent(event.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-600"
                />
                상담 음성 업로드 및 임시 처리에 필요한 동의를 확인했습니다.
              </label>
              <label
                className={`block rounded-lg border border-dashed px-4 py-8 text-center ${
                  audioConsent ? 'border-slate-300 bg-slate-50' : 'border-slate-200 bg-slate-100 opacity-70'
                }`}
              >
                <FileText className="mx-auto h-7 w-7 text-slate-400" />
                <span className="mt-3 block text-sm font-medium text-slate-700">MP3, M4A, WAV 음성 선택</span>
                <input
                  type="file"
                  multiple
                  accept=".mp3,.m4a,.wav,audio/mpeg,audio/mp4,audio/wav,audio/x-wav"
                  disabled={!audioConsent}
                  className="sr-only"
                  onChange={(event) => {
                    void onAddAudioFiles(event.target.files)
                    event.target.value = ''
                  }}
                />
              </label>
              {audioCapabilitiesError && <p className="text-xs font-semibold text-rose-600">{audioCapabilitiesError}</p>}
              {audioCapabilities && (
                <p className="text-xs text-slate-500">
                  자동 축어록: {transcriptionAvailable ? '사용 가능' : audioCapabilities.transcription.reason || '비활성화'}
                </p>
              )}
              <MaterialUploadList materials={materials.filter((material) => material.kind === 'audio')} />
              <ModalDoneButton onClick={onClose} />
            </div>
          )}

          {mode === 'document_preview' && selectedMaterial && (
            <div className="space-y-4">
              <MaterialSummary material={selectedMaterial} />
              <textarea value={selectedText} readOnly className={`${textareaClass} min-h-[320px] bg-slate-50`} />
              <ModalDoneButton onClick={onClose} />
            </div>
          )}

          {mode === 'material_apply' && selectedMaterial && (
            <div className="space-y-4">
              <MaterialSummary material={selectedMaterial} />
              <Field label="반영 대상" htmlFor="material_apply_target">
                <select
                  id="material_apply_target"
                  value={applyTarget}
                  onChange={(event) => setApplyTarget(event.target.value as MaterialApplyTarget)}
                  className={inputClass}
                >
                  <option value="transcript_text">축어록</option>
                  <option value="counselor_memo">상담사 메모</option>
                  <option value="previous_session_summary">이전 회기 요약</option>
                  <option value="psychological_test_summary">심리검사 요약</option>
                </select>
              </Field>
              <div className="grid gap-2 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={() => setApplyMode('append')}
                  className={`rounded-md border px-3 py-2 text-sm font-semibold ${
                    applyMode === 'append' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'
                  }`}
                >
                  기존 내용 뒤에 추가
                </button>
                <button
                  type="button"
                  onClick={() => setApplyMode('replace')}
                  className={`rounded-md border px-3 py-2 text-sm font-semibold ${
                    applyMode === 'replace' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'
                  }`}
                >
                  기존 내용 교체
                </button>
              </div>
              <textarea value={selectedText} readOnly className={`${textareaClass} min-h-[220px] bg-slate-50`} />
              <button
                type="button"
                onClick={() => onApplyMaterial(selectedMaterial.id, applyTarget, applyMode)}
                className="inline-flex w-full items-center justify-center rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800"
              >
                자료에 반영
              </button>
            </div>
          )}

          {mode === 'audio_review' && selectedMaterial && (
            <div className="space-y-4">
              <MaterialSummary material={selectedMaterial} />
              {selectedMaterial.objectUrl && <audio controls src={selectedMaterial.objectUrl} className="w-full" />}
              {selectedMaterial.status !== 'transcribed' && (
                <button
                  type="button"
                  disabled={!transcriptionAvailable || selectedMaterial.status === 'transcribing'}
                  onClick={() => onTranscribeAudio(selectedMaterial.id)}
                  className="inline-flex w-full items-center justify-center rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {selectedMaterial.status === 'transcribing' ? '축어록 생성 중' : '축어록 생성'}
                </button>
              )}
              {(selectedMaterial.segments || []).length > 0 && (
                <div className="space-y-2">
                  {(selectedMaterial.segments || []).map((segment) => (
                    <label key={segment.id} className="block rounded-md border border-slate-200 p-3">
                      <span className="text-xs font-semibold text-slate-500">
                        {formatSeconds(segment.start)} - {formatSeconds(segment.end)}
                      </span>
                      <input
                        value={segment.text}
                        onChange={(event) => onUpdateAudioSegmentText(selectedMaterial.id, segment.id, event.target.value)}
                        className={inputClass}
                      />
                    </label>
                  ))}
                </div>
              )}
              <Field label="전체 축어록" htmlFor="audio_transcript_text">
                <textarea
                  id="audio_transcript_text"
                  value={selectedMaterial.transcriptText || ''}
                  onChange={(event) => onUpdateAudioTranscript(selectedMaterial.id, event.target.value)}
                  className={`${textareaClass} min-h-[220px]`}
                />
              </Field>
              {selectedMaterial.status === 'transcribed' && (
                <button
                  type="button"
                  onClick={() => onApplyMaterial(selectedMaterial.id, 'transcript_text', 'append')}
                  className="inline-flex w-full items-center justify-center rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800"
                >
                  축어록에 반영
                </button>
              )}
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
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ring-1 ${
        interactive ? 'transition hover:-translate-y-px hover:bg-white' : ''
      } ${badge.className}`}
    >
      {badge.label}
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
      id: 'main_issue',
      title: '주요 호소',
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

function formatCompactDate(value: string): string {
  if (!value) return '날짜 미정'
  return value.replace(/-/g, '.')
}

function getClientAlias(form: SessionInput): string {
  return (form.client_alias || '').trim()
}

function getClientDisplayName(form: SessionInput): string {
  return getClientAlias(form) || form.case_id
}

function formatSavedTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '방금'
  return date.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit' })
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
): FinalDocumentSection[] {
  const getSection = (id: DraftSectionId, fallback: string) =>
    sections.find((section) => section.id === id)?.content || fallback
  const makeSection = (
    id: string,
    title: string,
    content: string | string[],
  ): FinalDocumentSection => ({
    id,
    title,
    content: Array.isArray(content) ? content.join('\n') : content,
    contentKind: Array.isArray(content) ? 'list' : 'paragraph',
  })

  if (documentType === 'supervision_report') {
    return [
      makeSection(
        'main_issue',
        '주요 호소',
        [
          getSection('main_issue', '주요 호소 내용을 상담사가 확인해야 합니다.'),
          '진로 및 취업 준비 과정에서의 불안과 자기비난 사고를 중심으로 보고함.',
        ],
      ),
      makeSection('session_content', '상담 내용', getSection('session_content', '상담 내용을 확인해야 합니다.')),
      makeSection(
        'counselor_intervention',
        '상담사 개입',
        [
          getSection('counselor_intervention', '상담자 개입 내용을 확인해야 합니다.'),
          '자동사고와 감정 반응의 연결을 탐색하는 방향으로 진행함.',
        ],
      ),
      makeSection('psychological_test', '심리검사 결과 및 해석', getSection('psychological_test', '심리검사 결과와 상담적 해석은 상담사가 확인해야 합니다.')),
      makeSection('supervision_request', '슈퍼비전 요청사항', '내담자의 자기비난 사고를 다룰 때 정서 확인과 행동 계획 사이의 균형을 어떻게 잡을지 슈퍼비전에서 논의가 필요합니다.'),
      makeSection('additional_review', '추가 확인 필요', missingItems.length ? missingItems : ['가족관계, 심리검사 결과, 상담 목표 달성 정도 확인 필요']),
    ]
  }

  if (documentType === 'termination_report') {
    return [
      makeSection('termination_goal_process', '상담 목표 및 진행 과정', getSection('session_content', '상담 진행 과정을 확인해야 합니다.')),
      makeSection('termination_changes', '주요 변화', getSection('client_response', '내담자 변화 내용을 상담사가 확인해야 합니다.')),
      makeSection('termination_reason', '종결 사유', '종결 사유는 상담사가 직접 입력해야 합니다.'),
      makeSection('termination_recommendation', '향후 권고', getSection('next_plan', '향후 권고 사항을 확인해야 합니다.')),
      makeSection('termination_counselor_opinion', '상담자 종합소견', '상담자 종합소견은 임상 판단 영역이므로 직접 작성이 필요합니다.'),
    ]
  }

  return [
    makeSection('main_issue', '주요 호소', getSection('main_issue', '주요 호소 내용을 확인해야 합니다.')),
    makeSection('session_content', '상담 내용', getSection('session_content', '상담 내용을 확인해야 합니다.')),
    makeSection('counselor_intervention', '상담사 개입', getSection('counselor_intervention', '상담자 개입 내용을 확인해야 합니다.')),
    makeSection('client_response', '내담자 반응', getSection('client_response', '내담자 반응을 확인해야 합니다.')),
    makeSection('next_plan', '다음 계획', getSection('next_plan', '다음 계획을 확인해야 합니다.')),
  ]
}

function supervisionBlockToEditableText(block: SupervisionContentBlock): string {
  if (block.type === 'table' && block.rows?.length) {
    const headers = Object.keys(block.rows[0])
    return [headers.join('\t'), ...block.rows.map((row) => headers.map((header) => row[header] || '').join('\t'))].join('\n')
  }
  if (block.type === 'transcript' && block.speakerTurns?.length) {
    return block.speakerTurns
      .map((turn) => `${turn.speaker === 'client' ? '내담자' : '상담자'}: ${turn.text}`)
      .join('\n')
  }
  return block.text || ''
}

function updateSupervisionBlockFromText(block: SupervisionContentBlock, text: string): SupervisionContentBlock {
  if (block.type === 'table') {
    return {
      ...block,
      rows: parseSupervisionTableText(text, block.rows || []),
      reviewStatus: 'edited',
    }
  }

  if (block.type === 'transcript') {
    return {
      ...block,
      speakerTurns: parseSupervisionTranscriptText(text, block.id),
      reviewStatus: 'edited',
    }
  }

  return {
    ...block,
    text,
    reviewStatus: 'edited',
  }
}

function parseSupervisionTableText(text: string, fallbackRows: Record<string, string>[]): Record<string, string>[] {
  const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  if (lines.length < 2) return fallbackRows

  const headers = lines[0].split('\t').map((header) => header.trim()).filter(Boolean)
  if (!headers.length) return fallbackRows

  return lines.slice(1).map((line) => {
    const values = line.split('\t')
    return headers.reduce<Record<string, string>>((row, header, index) => {
      row[header] = values[index]?.trim() || ''
      return row
    }, {})
  })
}

function parseSupervisionTranscriptText(text: string, blockId: string) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const [speakerRaw, ...rest] = line.split(':')
      const textValue = rest.join(':').trim() || line
      const speaker = speakerRaw.includes('내담') || speakerRaw.toLowerCase().includes('client') ? 'client' : 'counselor'
      return {
        turnId: `${blockId}.edited_${index + 1}`,
        speaker,
        text: textValue,
      } as const
    })
}

function splitEditableList(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*[-*•]\s+/, '').trim())
    .filter(Boolean)
}

function cleanExportMetadata(metadata: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(metadata).filter(([, value]) => {
      if (value === null || value === undefined) return false
      if (typeof value === 'string') return value.trim().length > 0
      if (Array.isArray(value)) return value.length > 0
      return true
    }),
  )
}

function capabilityReasonToKorean(reason?: string | null): string {
  if (!reason) return 'PDF 내보내기를 사용할 수 없습니다.'
  if (reason.includes('WeasyPrint native runtime')) {
    return '이 서버에는 PDF 생성을 위한 WeasyPrint 네이티브 런타임이 없어 PDF 다운로드를 사용할 수 없습니다.'
  }
  if (reason.includes('HWPX')) {
    return '검증된 HWPX 템플릿이 아직 설정되지 않았습니다.'
  }
  return reason
}

function buildDocumentExportRequest({
  documentType,
  editingSupervisionBlockId,
  editingSupervisionText,
  finalDocumentSections,
  form,
  format,
  supervisionReportDraft,
}: {
  documentType: FinalDocumentType
  editingSupervisionBlockId: string | null
  editingSupervisionText: string
  finalDocumentSections: FinalDocumentSection[]
  form: SessionInput
  format: DocumentExportFormat
  supervisionReportDraft: SupervisionReportDraft | null
}): DocumentExportRequest {
  if (documentType === 'supervision_report') {
    if (!supervisionReportDraft) {
      throw new Error('수퍼비전 보고서 초안이 아직 준비되지 않았습니다.')
    }
    const report = applyPendingSupervisionEdit(
      supervisionReportDraft,
      editingSupervisionBlockId,
      editingSupervisionText,
    )

    return {
      format,
      document_type: documentType,
      case_id: report.caseId || form.case_id,
      session_number: report.meta.sessionNumber || form.session_number,
      session_date: report.meta.reportDate || form.session_date,
      title: report.title,
      metadata: cleanExportMetadata({
        client_alias: getClientAlias(form),
        counselor_name: report.meta.counselorName || form.counselor_name,
        institution: report.meta.institution,
        supervisor: report.meta.supervisor,
        supervision_date_place: report.meta.supervisionDatePlace,
      }),
      sections: buildSupervisionExportSections(report),
    }
  }

  return {
    format,
    document_type: documentType,
    case_id: form.case_id,
    session_number: form.session_number,
    session_date: form.session_date,
    title: finalDocumentMeta[documentType].title,
    metadata: cleanExportMetadata({
      client_alias: getClientAlias(form),
      counselor_name: form.counselor_name,
    }),
    sections: buildGeneralExportSections(finalDocumentSections),
  }
}

function buildGeneralExportSections(sections: FinalDocumentSection[]): DocumentExportSection[] {
  return sections
    .filter((section) => section.content.trim())
    .map((section) => ({
      id: section.id,
      title: section.title,
      content: section.contentKind === 'list' ? splitEditableList(section.content) : section.content,
      level: 2,
    }))
}

function buildSupervisionExportSections(report: SupervisionReportDraft): DocumentExportSection[] {
  return report.sections
    .map((section) => {
      const contentBlocks = section.contentBlocks
        .filter(supervisionBlockHasExportableContent)
        .map((block) => ({
          id: block.id,
          type: block.type,
          text: block.text || null,
          rows: block.rows,
          speaker_turns: block.speakerTurns?.map((turn) => ({
            turn_id: turn.turnId,
            speaker: turn.speaker,
            text: turn.text,
            silence_seconds: turn.silenceSeconds ?? null,
          })),
          warnings: block.warnings || [],
        }))

      return {
        id: section.id,
        title: section.title,
        content_blocks: contentBlocks,
        level: section.level,
      }
    })
    .filter((section) => section.level <= 1 || Boolean(section.content_blocks?.length))
}

function supervisionBlockHasExportableContent(block: SupervisionContentBlock): boolean {
  if (block.text?.trim()) return true
  if (block.rows?.length) return true
  return Boolean(block.speakerTurns?.some((turn) => turn.text.trim()))
}

function applyPendingSupervisionEdit(
  report: SupervisionReportDraft,
  editingBlockId: string | null,
  editingText: string,
): SupervisionReportDraft {
  if (!editingBlockId) return report

  return {
    ...report,
    sections: report.sections.map((section) => ({
      ...section,
      contentBlocks: section.contentBlocks.map((block) =>
        block.id === editingBlockId ? updateSupervisionBlockFromText(block, editingText) : block,
      ),
    })),
  }
}

function triggerBlobDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

function makeMaterialId(file: File): string {
  return `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`
}

function getMaterialText(material: UploadedMaterial | null | undefined): string {
  if (!material) return ''
  if (material.kind === 'audio') {
    if (material.transcriptText) return material.transcriptText
    if (material.segments?.length) {
      return material.segments.map((segment) => segment.text).filter(Boolean).join('\n')
    }
    return ''
  }
  return material.extractedText || ''
}

function mergeMaterialText(current: string, incoming: string, mode: MaterialApplyMode): string {
  const cleanIncoming = incoming.trim()
  if (mode === 'replace' || !current.trim()) return cleanIncoming
  return `${current.trim()}\n\n${cleanIncoming}`
}

function materialMetaText(material: UploadedMaterial): string {
  if (material.status === 'uploading') return '텍스트 추출 중'
  if (material.status === 'selected') return '음성 파일 선택 완료'
  if (material.status === 'transcribing') return '축어록 생성 중'
  if (material.status === 'failed') return '처리 실패'
  if (material.kind === 'audio') {
    const duration = material.durationSeconds ? ` · ${formatSeconds(material.durationSeconds)}` : ''
    const count = countCharacters(material.transcriptText || '')
    return material.status === 'transcribed' ? `축어록 생성 완료 · ${count}자${duration}` : `음성 자료${duration}`
  }
  const count = material.characterCount ?? countCharacters(material.extractedText || '')
  const pageCount = material.pageCount ? ` · ${material.pageCount}쪽` : ''
  return `텍스트 추출 완료 · ${count.toLocaleString('ko-KR')}자${pageCount}`
}

function formatSeconds(value: number): string {
  const totalSeconds = Math.max(0, Math.round(value))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

function serializeMaterialsForDraft(materials: UploadedMaterial[]) {
  return materials.map((material) => ({
    id: material.id,
    kind: material.kind,
    filename: material.filename,
    mediaType: material.mediaType,
    status: material.status,
    characterCount: material.characterCount,
    pageCount: material.pageCount,
    warnings: material.warnings,
    error: material.error,
    durationSeconds: material.durationSeconds,
    language: material.language,
  }))
}

interface TextModalConfig {
  field: keyof Pick<
    SessionInput,
    'transcript_text' | 'counselor_memo' | 'previous_session_summary' | 'psychological_test_summary'
  >
  label: string
}

const modalTitle: Record<MaterialModalMode, string> = {
  add: '상담 자료 업로드',
  basic_info: '회기 기본 정보 수정',
  paste_text: '텍스트 붙여넣기',
  file_upload: '파일 업로드',
  document_upload: '문서 업로드',
  audio_upload: '음성 업로드',
  document_preview: '문서 내용 확인',
  material_apply: '자료에 반영',
  audio_review: '축어록 확인',
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

function getTransformOptionBadge(documentType: FinalDocumentType): string {
  if (documentType === 'session_note') return '상담 진행 기록'
  if (documentType === 'supervision_report') return '회기 기록 기반'
  return '케이스 전체 요약'
}

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
  retrieved_context: 'case_memory',
  template_context: 'template',
  privacy_context: 'privacy',
  ai_inference: 'ai',
}

const sourceTypeLabel: Record<EvidenceSourceType, string> = {
  transcript: '축어록/STT',
  counselor_memo: '상담사 메모',
  previous_summary: '이전 회기 요약',
  retrieved_context: '저장된 이전 회기',
  template_context: '문서 양식 KB',
  privacy_context: '개인정보/윤리 KB',
  ai_inference: 'AI 추론',
}

const sourceBadgeMeta: Record<SourceBadgeKind, { className: string; label: string }> = {
  memo: { label: '메모 기반', className: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  transcript: { label: '축어록 기반', className: 'bg-blue-50 text-blue-700 ring-blue-200' },
  previous: { label: '이전 회기 기반', className: 'bg-sky-50 text-sky-700 ring-sky-200' },
  case_memory: { label: '저장 회기 기반', className: 'bg-cyan-50 text-cyan-700 ring-cyan-200' },
  template: { label: '양식 기준', className: 'bg-indigo-50 text-indigo-700 ring-indigo-200' },
  privacy: { label: '윤리 검토', className: 'bg-teal-50 text-teal-700 ring-teal-200' },
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
