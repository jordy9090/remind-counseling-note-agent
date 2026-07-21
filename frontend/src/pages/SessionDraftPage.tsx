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
import { AudioTranscriptEditor } from '../components/audio/AudioTranscriptEditor'
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
import {
  buildNonverbalNotes,
  buildTranscriptText,
  getSegmentSpeakerKey,
  replaceAppliedAudioBlock,
  type SpeakerRole,
  type SpeakerRoleMap,
} from '../lib/audioTranscriptWorkflow'
import { getMaterialText, getUnappliedReadyMaterials } from '../lib/materialWorkflow'
import type {
  AudioCapabilitiesResponse,
  AudioSegment,
  AudioTranscriptionResponse,
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
  | 'nonverbal_notes'
  | 'counselor_memo'
  | 'previous_session_summary'
  | 'psychological_test_summary'
type MaterialApplyMode = 'append' | 'replace'
const AUDIO_APPLY_TARGETS: MaterialApplyTarget[] = ['transcript_text', 'nonverbal_notes']

const DOCUMENT_UPLOAD_MAX_BYTES = 20 * 1024 * 1024
const AUDIO_UPLOAD_MAX_BYTES = 500 * 1024 * 1024
const DOCUMENT_UPLOAD_EXTENSIONS = new Set(['.pdf', '.docx', '.txt'])
const AUDIO_UPLOAD_EXTENSIONS = new Set(['.mp3', '.m4a', '.wav'])

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
  speakerRoleMap?: SpeakerRoleMap
  runtimeMode?: 'real' | 'stub'
  diarizationStatus?: 'completed' | 'fallback' | 'disabled'
  languageProbability?: number | null
  nonverbalNotes?: string
  dirtySinceApply?: boolean
  expectedSpeakers?: number
  lastAppliedTranscriptText?: string
  lastAppliedNonverbalNotes?: string
  lastAppliedMode?: MaterialApplyMode
  appliedTargets: MaterialApplyTarget[]
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
    id: "session-1",
    label: "1회기",
    date: "2026. 04. 26",
    summary: "사회적 모임 회피 이후 반복되는 고립감과 죄책감을 탐색하고, 부담이 낮은 소규모 모임을 시도하기로 함.",
    detail: "내담자는 사람들과의 모임을 자주 피하면서 고립감과 죄책감을 경험한다고 보고함. 혼자 있는 시간을 선호하지만, 초대를 거절한 뒤 타인이 자신을 부정적으로 볼 것이라고 걱정하는 패턴을 확인함. 익숙한 사람들과의 소규모 모임부터 시도하고, 긴장을 낮추기 위해 주 1~2회 스케치 시간을 마련하기로 함.",
  },
  {
    id: "session-2",
    label: "2회기",
    date: "2026. 05. 03",
    summary: "타인이 자신을 부정적으로 평가할 것이라는 추측과 사회적 회피의 연결을 확인함.",
    detail: "내담자는 자신이 자리에 없을 때 사람들이 자신을 부정적으로 평가하거나 이야기할 것이라고 추측하며 사회적 상황을 회피한다고 설명함. 이러한 생각이 사실로 확인된 내용인지 점검하고, 스케치 시작 전 부정적 생각을 알아차리는 연습을 함께 적용하기로 함. 주말마다 스케치 또는 독서 시간을 확보하는 과제를 계획함.",
  },
  {
    id: "session-3",
    label: "3회기",
    date: "2026. 05. 10",
    summary: "평가에 대한 두려움을 점검하고, 룸메이트와 함께 부담이 낮은 사회적 상황에 참여하기로 함.",
    detail: "내담자는 타인의 평가에 대한 두려움이 실제 근거보다 자신의 예상에 가깝다는 점을 인식함. 룸메이트와 함께 부담이 낮은 모임에 참석해 예상했던 두려움이 실제로 발생하는지 확인해 보기로 함. 모임 전 짧게 스케치하며 긴장을 낮추고, 작은 참여도 변화의 과정으로 인정하기로 함.",
  },
  {
    id: "session-4",
    label: "4회기",
    date: "2026. 05. 17",
    summary: "소규모 모임 참여 계획을 구체화하고, 룸메이트의 지원과 스케치를 활용한 불안 조절 전략을 마련함.",
    detail: "내담자는 룸메이트와 함께 소규모 모임이나 카페 방문을 계획함. 모임에 들어가는 첫 순간과 대화를 시작해야 하는 상황에서 불안이 커질 것으로 예상함. 룸메이트가 사람을 소개하거나 기존 대화에 참여하도록 돕는 방안을 마련함. 모임 전 스케치와 호흡 조절을 활용하고, 참여 후 작은 성취를 함께 확인하기로 함.",
  },
]

const defaultPreviousSessionIds = ['session-1', 'session-2', 'session-3', 'session-4']
const demoClientName = '가명 다은'

function buildPreviousSessionSummary(selectedIds: string[]): string {
  return previousSessionOptions
    .filter((session) => selectedIds.includes(session.id))
    .map((session) => `${session.label} (${session.date}): ${session.detail}`)
    .join('\n')
}

const caseSummaries: CaseSummary[] = [
  {
    id: 'CASE-MUSPSY-1416',
    name: '가명 다은',
    type: '성인 개인상담',
    lastDate: '2026. 05. 24',
    counselor: '데모 상담사',
    mainIssue: '사회적 상황 불안, 평가 우려, 사회적 회피',
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
  case_id: "CASE-MUSPSY-1416",
  client_alias: demoClientName,
  session_number: 5,
  session_date: "2026-05-24",
  counselor_name: "데모 상담사",
  counselor_memo: "5회기. 내담자는 예정된 시간에 참여하였으며 전반적으로 협조적인 태도를 보였다. 지난 회기에서 계획한 룸메이트와의 소규모 외출은 아직 구체적인 날짜를 정하지 못했으나, 사회적 상황을 앞두고 불안이 높아질 때 초대를 미루거나 거절하고 이후 고립감과 자기비난이 커지는 자신의 반복 패턴을 비교적 명확하게 설명하였다. 내담자는 “사람들이 나를 이상하게 볼 것 같다”는 생각이 사실로 확인된 내용보다 자신의 예상에 가깝다는 점은 이해하고 있으나, 실제 상황에서는 해당 생각의 영향력이 여전히 크게 느껴진다고 보고하였다.\n\n이번 회기에서는 내담자가 이미 안정감을 경험하고 있는 스케치 활동을 일상적인 정서조절 전략으로 구체화하고, 사회적 평가와 관련된 자동사고를 보다 객관적으로 점검하는 방법을 탐색하였다. 내담자는 자연 풍경을 그릴 때 걱정에서 잠시 거리를 둘 수 있고 마음이 차분해진다고 설명하였다. 이에 상담자는 주말마다 한 시간의 정기적인 스케치 시간을 확보하고, 스트레스가 급격히 높아지는 상황에서는 5분 내외의 짧은 스케치를 활용해 주의를 전환해 보도록 제안하였다. 내담자는 이 방법이 현실적으로 실행 가능하며, 스케치 시간을 ‘머릿속을 정리하는 시간’으로 활용해 보고 싶다고 반응하였다.\n\n부정적인 생각을 다루기 위해 상황, 자동사고, 해당 생각을 뒷받침하는 근거, 반대 근거, 보다 균형 잡힌 생각을 구분하여 기록하는 방법을 안내하였다. 내담자는 이를 “생각의 대차대조표를 만드는 것 같다”고 표현하였고, 머릿속에서 반복되는 생각을 종이에 적으면 자신의 추측을 한 걸음 떨어져서 볼 수 있을 것 같다고 말했다. 특히 “사람들이 나를 부정적으로 평가할 것이다”라는 생각이 떠오를 때 실제로 확인된 사실과 자신이 예상한 내용을 구분하여 기록해 보기로 하였다.\n\n정서조절 자원을 확장하는 과정에서 내담자는 스케치할 때 잔잔한 음악을 들으면 집중과 안정에 도움이 된다고 보고하였다. 집안일을 하거나 잠들기 전에도 비슷한 음악을 활용해 보고, 기존의 연필 스케치 외에 수채화나 점토 등 감각을 다양하게 사용하는 창작 활동도 시도해 보기로 하였다. 내담자는 새로운 재료를 탐색하는 태도를 사회적 상황에도 적용할 수 있을 것 같다고 말하며, 향후 초대를 받았을 때 즉시 거절하기보다 참석 가능성을 한 번 더 검토하고, 모임에서는 미술이나 창작 활동처럼 자신이 편안하게 이야기할 수 있는 공통 관심사를 활용해 먼저 대화를 시작해 보겠다고 하였다.\n\n상담자는 내담자의 사회적 불안이 타인의 부정적 평가를 예상하는 사고, 사회적 상황에 대한 예기불안, 회피 이후의 자기비난으로 이어지는 순환 구조와 관련되어 있다고 판단하였다. 다만 이전 회기보다 자신의 사고 패턴을 언어로 설명하는 능력과 대안 행동을 계획하려는 태도가 향상되었으며, 변화 가능성에 대한 기대도 증가한 것으로 보인다. 내담자의 현실검증력과 사고 과정은 양호하였고, 면담 중 사고의 비약이나 지각 이상은 관찰되지 않았다.\n\n현재 자살사고, 자해 충동, 타해사고 및 구체적인 계획은 보고하지 않았으며 급성 위험도는 낮은 수준으로 판단하였다. 다음 회기에서는 주말 스케치 루틴의 실행 여부, 활동 전후 불안 및 긴장 수준의 변화, 생각 기록지 작성 경험을 확인할 예정이다. 또한 사회적 초대에 반응하는 방식과 룸메이트와 계획한 소규모 외출의 진행 상황을 점검하고, 실제 사회적 상황에서 사용할 수 있는 대화 시작 문장과 불안 조절 방법을 구체화할 계획이다.",
  transcript_text: "C: 최근에 즐거움을 느끼거나 스트레스를 조절하는 데 도움이 되는 활동을 찾은 것이 있나요?\nCl: 네, 저는 원래 스케치하는 걸 좋아해요. 그림을 그리면 걱정이 많은 상태에서 잠시 벗어날 수 있어요.\n\nC: 좋아하는 활동을 하는 건 에너지를 회복하는 데 도움이 될 수 있어요. 스케치 시간을 규칙적인 일과로 만들어 보는 건 어떨까요?\nCl: 좋아요. 주말처럼 비교적 조용한 시간에 정기적으로 시간을 내볼까 생각했어요.\n\nC: 정해진 시간을 마련하면 활동을 더 즐기고 성취감도 느낄 수 있을 것 같아요. 우선 주말마다 한 시간 정도로 시작해 보는 건 어떨까요?\nCl: 그 정도면 할 수 있을 것 같아요. 저한테 중심을 잡아주는 시간이 될 것 같고요.\n\nC: 스케치를 일과에 넣으면서 그림에서 반복적으로 나타나는 소재나 주제를 살펴보는 것도 도움이 될 수 있어요. 현재 상태를 이해할 단서가 될 수도 있고요.\nCl: 흥미로운 생각이네요. 저는 자연 풍경을 자주 그리는데, 그런 그림을 그리면 평온해져요. 제가 평화를 원해서 그런 것 같기도 해요.\n\nC: 자연 풍경이 내담자에게 원하는 평온함을 느끼게 해주는군요. 스케치할 때의 평온함을 다른 생활 영역으로 확장한다면 어떤 방법이 있을까요?\nCl: 마음챙김을 연습해 볼 수 있을 것 같아요. 주변을 실제로 그리듯이 자세히 바라보는 거예요.\n\nC: 마음챙김은 그림을 그릴 때 세부적인 부분을 관찰하는 것처럼, 일상에서도 현재의 경험에 집중하는 연습이 될 수 있어요.\nCl: 네. 일상에서 작은 부분에 집중하면 현재에 머물면서 스트레스를 줄이는 데 도움이 될 것 같아요.\n\nC: 이런 알아차림을 연습하면 일상의 어려움을 경험하는 방식에는 어떤 변화가 생길까요?\nCl: 부정적인 생각이나 불안에 완전히 휩쓸리지 않고, 지금 일어나고 있는 일에 집중할 수 있을 것 같아요.\n\nC: 생각에 휩쓸리지 않으면 상황을 더 분명하게 볼 수 있겠네요. 부정적인 생각이 떠올랐을 때 현실적인 걱정과 왜곡된 생각을 어떻게 구분할 수 있을까요?\nCl: 그 생각이 사실인지, 아니면 제가 추측하고 있는 건지 질문해 볼 수 있을 것 같아요. 전에 이야기했던 것처럼요.\n\nC: 그런 방식으로 추측을 점검하면 상황을 조금 더 현실적으로 바라볼 수 있겠어요. 그 생각이 나타났을 때 점검하도록 알려주는 장치로는 무엇이 있을까요?\nCl: 스케치하기 전에 장면을 메모하듯이 생각을 적을 수 있을 것 같아요. 한쪽에는 제가 한 추측을 쓰고, 다른 쪽에는 조금 더 긍정적이거나 현실적인 관점을 쓰는 거예요.\n\nC: 생각을 종이에 적으면 머릿속의 막연한 내용을 눈에 보이는 형태로 바꿀 수 있고, 생각이 덜 위협적으로 느껴질 수도 있겠어요.\nCl: 생각에 대한 대차대조표를 만드는 것 같겠네요. 그러면 조금 더 객관적으로 볼 수 있을 것 같아요.\n\nC: 객관적인 관점은 즉각적인 느낌에 끌려가는 것을 줄이는 데 도움이 될 수 있어요. 생각을 기록하는 과정은 스케치할 때의 진정 효과와 어떤 점에서 비슷할까요?\nCl: 머릿속에 엉켜 있는 걸 빈 종이에 옮기는 것처럼 느껴져서 후련할 것 같아요.\n\nC: 복잡한 내용을 밖으로 꺼내 정리하면 감정을 안정시키는 데도 도움이 될 수 있겠네요. 스케치할 때 함께 사용하는 다른 진정 방법도 있나요?\nCl: 저는 항상 잔잔한 배경음악을 틀어요. 그러면 집중도 잘되고 마음도 편안해져요.\n\nC: 그 음악을 스케치 시간 외의 일상에도 활용한다면 어떤 방식이 가능할까요?\nCl: 집안일을 할 때나 저녁에 쉬기 전에 들을 수 있을 것 같아요. 일상에 계속 깔리는 배경처럼요.\n\nC: 하루의 분위기를 조금 더 안정적으로 만드는 데 도움이 될 수 있겠어요. 스트레스가 특히 심할 때 창작 활동을 활용해 기분을 전환한다면 어떻게 해볼 수 있을까요?\nCl: 너무 벅찰 때 5분 정도라도 잠깐 스케치할 수 있을 것 같아요. 간단한 모양만 그려도 되고요.\n\nC: 짧은 창작 휴식도 스트레스 상황에서 잠시 떨어져 균형을 되찾는 전환점이 될 수 있어요.\nCl: 네. 걱정에 계속 빠져 있지 않고 머리를 잠깐 초기화할 수 있을 것 같아요.\n\nC: 수채화나 점토처럼 다른 재료를 사용해 보는 것은 다양성과 감정적 유연성을 높이는 데 어떤 도움이 될까요?\nCl: 수채화나 점토를 시도해 볼 수 있을 것 같아요. 손으로 직접 만지는 활동이 다른 감각도 사용하게 하고 즐거움을 줄 수도 있을 것 같아요.\n\nC: 다양한 재료를 사용하면 더 많은 감각을 자극하고 창작 표현을 넓힐 수 있겠어요. 예상하지 못한 즐거움을 발견할 수도 있고요.\nCl: 저는 가끔 새로운 걸 탐색하면서 스스로 놀라는 걸 좋아해서, 재미있을 것 같아요.\n\nC: 창작 활동에서 보이는 탐색적인 태도가 다른 생활 영역에는 어떤 영향을 줄 수 있을까요?\nCl: 새로운 경험에 좀 더 열려 있거나, 익숙하지 않은 걸 시도할 때 덜 무서워할 수 있을 것 같아요.\n\nC: 낯선 경험을 두려움보다 호기심으로 바라보면 사회적 상황에서도 새로운 경험으로 이어질 수 있겠네요.\nCl: 초대를 받았을 때 이전보다 조금 더 자주 “네”라고 말해보고, 상황을 너무 미리 판단하지 않아 볼 수 있을 것 같아요.\n\nC: 사회적 상황에 조금 더 참여하면 새로운 관계를 만들고 경험의 폭을 넓힐 기회가 생길 수 있어요. 새롭게 시작된 관계를 이어가기 위해 어떤 방법을 사용할 수 있을까요?\nCl: 새로 만난 사람과 미술처럼 서로 관심 있는 주제로 제가 먼저 이야기를 시작해 볼 수 있을 것 같아요.\n\nC: 공통 관심사에 관해 대화하면 관계를 형성하는 데 도움이 될 수 있겠어요.\nCl: 이런 노력들이 앞으로 제 사회적 관계에 좋은 영향을 줄 수 있을 것 같아서 기대돼요.\n\nC: 오늘 이야기를 마무리하기 전에 추가로 마음에 남는 내용이 있나요?\nCl: 아니요. 지금 이야기한 변화와 아이디어를 계속 실천해 볼 준비가 된 것 같고, 조금 희망적이에요.\n\nC: 변화를 시도하려는 태도와 자신의 패턴을 살펴보려는 노력이 확인됩니다. 다음 회기에는 스케치와 마음챙김 기록을 실제로 사용해 본 경험, 그리고 사회적 초대에 반응하는 방식에 어떤 변화가 있었는지 함께 살펴보겠습니다.",
  previous_session_summary: buildPreviousSessionSummary(defaultPreviousSessionIds),
  counseling_goal: "사회적 상황에서 타인이 자신을 부정적으로 평가할 것이라는 자동적 추측을 알아차리고 사실 여부를 점검한다. 스케치와 마음챙김을 일상적인 정서조절 활동으로 구조화하고, 부담이 낮은 사회적 참여를 점진적으로 늘린다.",
  psychological_test_summary: "초기면접 시 현재의 정서 상태와 사회적 상황에서의 어려움을 파악하기 위해 자기보고식 선별검사를 실시하였다. 사회적 상호작용 불안 척도(SIAS)는 46점으로 나타났으며, 새로운 사람과 대화를 시작하는 상황, 여러 사람이 있는 장소에 들어가는 상황, 자신의 말이나 행동이 타인에게 어떻게 보였는지를 반복적으로 되짚는 상황에서 불편감이 두드러졌다. 검사 결과는 내담자가 면담에서 보고한 타인의 평가에 대한 걱정, 사회적 상황 이전의 예기불안, 모임 초대를 회피하는 행동과 대체로 일치하였다.\n\n불안 증상의 전반적인 수준을 확인하기 위해 실시한 Beck 불안척도(BAI)는 18점으로 확인되었다. 내담자는 긴장감, 쉽게 편안해지지 못하는 느낌, 불안한 일이 생길 것 같은 두려움 등을 주로 보고하였다. 심박 증가나 호흡곤란처럼 급격한 신체 증상은 상대적으로 두드러지지 않았으며, 현재의 불안은 공황 증상보다 사회적 평가 상황과 대인관계에서의 긴장에 더 밀접하게 연결되어 있는 것으로 보인다.\n\n우울 증상 선별을 위한 PHQ-9은 7점으로 경미한 수준이었다. 피로감, 활동에 대한 의욕 저하, 자신에 대한 부정적인 평가 문항에서 일부 어려움이 보고되었으나, 지속적인 우울감이나 전반적인 흥미 상실이 주된 호소로 나타나지는 않았다. 현재 관찰되는 기분 저하는 사회적 회피 이후의 고립감과 자기비난, 대인관계에서 느끼는 긴장에 영향을 받는 것으로 이해할 수 있다.\n\n자살위험 선별 면담에서 현재의 자살사고, 자살 계획, 자해 행동 및 과거 자살 시도는 모두 부인하였다. 자신이나 타인에게 위해를 가하려는 사고도 보고하지 않았다. 보호요인으로는 안정적인 주거 환경, 지지적인 룸메이트와의 관계, 창작 활동에 대한 지속적인 관심, 상담 과정에 대한 협조적인 태도, 자신의 상태를 개선하려는 동기가 확인되었다. 현재 급성 위험도는 낮은 수준으로 평가되며, 향후 정서 상태가 급격히 악화되거나 사회적 고립이 증가할 경우 위험도를 다시 확인할 필요가 있다.\n\n검사 문항에 대한 무응답은 없었고 반응의 일관성은 전반적으로 양호하였다. 검사 결과와 면담 내용을 종합하면 사회적 평가에 대한 민감성, 예기불안, 회피적 대처가 현재 어려움의 핵심으로 보인다. 현재 단계에서는 사회불안 관련 증상과 기능 손상 정도를 지속적으로 확인하는 작업가설을 유지한다. 검사 결과만으로 진단을 확정하지 않으며, 실제 사회적 상황에서의 기능 수준, 증상의 지속 기간, 직업 및 대인관계에 미치는 영향을 추가로 관찰할 필요가 있다.\n\n5회기에는 심리검사 재검사를 실시하지 않았다. 초기검사 결과는 상담 목표 설정과 변화 경과를 확인하기 위한 기준 자료로 활용한다. 향후 8회기 전후에 SIAS와 BAI를 재실시하여 사회적 상황에 대한 불안, 회피 행동, 일상 기능의 변화를 초기 결과와 비교할 예정이다.",
  key_issue_tags: ["사회적 상황 불안", "평가에 대한 추측", "사회적 회피", "창작 활동", "마음챙김", "점진적 참여"],
  nonverbal_notes: "내담자는 정시에 참여하였고 복장과 위생 상태는 단정하였다. 의식은 명료하였으며 시간, 장소, 사람에 대한 지남력은 양호하였다. 회기 초반 사회적 초대와 타인의 평가에 대한 걱정을 이야기할 때 시선이 잠시 아래로 향하고 손가락을 만지는 모습이 관찰되었으며, 목소리 크기가 다소 작아지고 발화 속도가 느려졌다. 질문에는 관련성 있게 답하였고 사고 과정은 논리적이고 목표 지향적이었다.\n\n스케치와 자연 풍경을 이야기할 때에는 표정이 부드러워지고 미소가 증가하였으며, 상담자와의 눈맞춤도 비교적 자연스럽게 유지되었다. 생각을 사실과 추측으로 나누는 방법을 설명한 뒤 내담자가 “생각의 대차대조표”라고 표현할 때 자발적인 웃음이 나타났고, 기록 방법을 구체적으로 질문하는 등 참여도가 높아졌다. 회기 후반 사회적 초대에 조금 더 열린 태도로 반응해 보겠다는 계획을 말할 때 자세가 곧아지고 목소리 크기와 말의 속도가 안정되었다. 뚜렷한 정신운동성 초조나 지연, 지각 이상을 시사하는 행동은 관찰되지 않았다.",
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

  const hasUsableNoteInput = Boolean(
    form.counselor_memo.trim() ||
      form.transcript_text.trim() ||
      form.previous_session_summary.trim() ||
      form.psychological_test_summary?.trim() ||
      form.counseling_goal?.trim() ||
      form.nonverbal_notes?.trim(),
  )

  const hasMaterialRows = Boolean(
    hasUsableNoteInput ||
      materials.length,
  )
  const unappliedReadyMaterials = useMemo(() => getUnappliedReadyMaterials(materials), [materials])

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
    if (selectedFiles.length > 5) {
      setError('문서는 한 번에 최대 5개까지 선택할 수 있습니다.')
      return
    }

    const invalidMaterials = selectedFiles
      .map((file) => validateSelectedFile(file, 'document'))
      .filter((material): material is UploadedMaterial => Boolean(material))
    if (invalidMaterials.length) {
      setMaterials((prev) => [...invalidMaterials, ...prev])
      return
    }

    const pendingMaterials: UploadedMaterial[] = selectedFiles.map((file) => ({
      id: makeMaterialId(file),
      kind: 'document',
      filename: file.name,
      mediaType: file.type,
      status: 'uploading',
      warnings: [],
      appliedTargets: [],
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
                    appliedTargets: material.appliedTargets,
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
    const selectedFiles = Array.from(files)
    if (selectedFiles.length > 1) {
      setError('음성은 한 번에 1개만 선택할 수 있습니다.')
      return
    }
    const invalidMaterial = validateSelectedFile(selectedFiles[0], 'audio')
    if (invalidMaterial) {
      setMaterials((prev) => [invalidMaterial, ...prev])
      return
    }
    await refreshAudioCapabilities()
    const nextMaterials = selectedFiles.map((file) => {
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
        expectedSpeakers: 2,
        appliedTargets: [],
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
        runtime_mode: 'disabled',
      }
      setAudioCapabilities(fallback)
      return fallback
    }
  }

  const transcribeAudioMaterial = async (materialId: string) => {
    const target = materials.find((material) => material.id === materialId)
    if (!target?.file) return
    setMaterials((prev) =>
      prev.map((material) =>
        material.id === materialId
          ? {
              ...material,
              status: 'transcribing',
              error: undefined,
              dirtySinceApply: material.status === 'transcribed' ? true : material.dirtySinceApply,
              appliedTargets: material.appliedTargets.filter((target) => !AUDIO_APPLY_TARGETS.includes(target)),
            }
          : material,
      ),
    )
    try {
      const transcription = await transcribeAudio(target.file, 'ko', 'transcribe', target.expectedSpeakers || 2)
      setMaterials((prev) =>
        prev.map((material) =>
          material.id === materialId
            ? buildTranscribedAudioMaterial(material, transcription)
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

  const updateAudioSegmentText = (materialId: string, segmentId: number, text: string) => {
    setMaterials((prev) =>
      prev.map((material) =>
        material.id === materialId
          ? markAudioMaterialDirty({
              ...material,
              segments: (material.segments || []).map((segment) =>
                segment.id === segmentId ? { ...segment, text } : segment,
              ),
            })
          : material,
      ),
    )
  }

  const updateAudioSpeakerRole = (materialId: string, speakerKey: string, role: SpeakerRole) => {
    setMaterials((prev) =>
      prev.map((material) =>
        material.id === materialId
          ? markAudioMaterialDirty({
              ...material,
              speakerRoleMap: {
                ...(material.speakerRoleMap || {}),
                [speakerKey]: role,
              },
            })
          : material,
      ),
    )
  }

  const updateAudioExpectedSpeakers = (materialId: string, value: number) => {
    const safeValue = Math.min(4, Math.max(1, value))
    setMaterials((prev) =>
      prev.map((material) =>
        material.id === materialId
          ? markAudioMaterialDirty({
              ...material,
              expectedSpeakers: safeValue,
            })
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
    if (mode === 'append' && material?.appliedTargets.includes(target)) {
      setMaterials((prev) =>
        prev.map((item) =>
          item.id === materialId
            ? {
                ...item,
                error: `${materialApplyTargetLabel[target]}에 이미 반영된 자료입니다. 다시 넣으려면 기존 내용 교체를 선택해주세요.`,
              }
            : item,
        ),
      )
      return
    }
    setForm((prev) => ({
      ...prev,
      [target]: mergeMaterialText(String(prev[target] || ''), text, mode),
    }))
    setMaterials((prev) =>
      prev.map((item) =>
        item.id === materialId
          ? {
              ...item,
              appliedTargets: Array.from(new Set([...item.appliedTargets, target])),
              error: undefined,
            }
          : item,
      ),
    )
    setMaterialModal(null)
  }

  const applyAudioTranscriptToForm = (materialId: string, mode: MaterialApplyMode) => {
    const material = materials.find((item) => item.id === materialId)
    if (!material || material.kind !== 'audio') return
    const speakerRoleMap = material.speakerRoleMap || {}
    const transcriptText = buildTranscriptText(material.segments || [], speakerRoleMap) || material.transcriptText || ''
    const nonverbalNotes = buildNonverbalNotes(material.segments || [], speakerRoleMap) || material.nonverbalNotes || ''
    if (!transcriptText.trim()) return

    const isReapply =
      Boolean(material.dirtySinceApply) &&
      (material.lastAppliedTranscriptText !== undefined || material.lastAppliedNonverbalNotes !== undefined)
    const nextTranscriptText = isReapply
      ? replaceAppliedAudioBlock(form.transcript_text, material.lastAppliedTranscriptText || '', transcriptText)
      : mergeMaterialText(form.transcript_text, transcriptText, mode)
    const nextNonverbalNotes = isReapply
      ? replaceAppliedAudioBlock(
          form.nonverbal_notes || '',
          material.lastAppliedNonverbalNotes || '',
          nonverbalNotes,
        )
      : mergeMaterialText(form.nonverbal_notes || '', nonverbalNotes, mode)

    if (nextTranscriptText === null || nextNonverbalNotes === null) {
      setMaterials((prev) =>
        prev.map((item) =>
          item.id === materialId
            ? {
                ...item,
                error: '이전에 반영한 오디오 블록이 회기 입력에서 수정되어 자동으로 교체할 수 없습니다. 현재 입력을 확인한 뒤 다시 반영해주세요.',
              }
            : item,
        ),
      )
      return
    }

    setForm((prev) => ({
      ...prev,
      transcript_text: nextTranscriptText,
      nonverbal_notes: nextNonverbalNotes,
    }))
    setMaterials((prev) =>
      prev.map((item) =>
        item.id === materialId
          ? {
              ...item,
              transcriptText,
              nonverbalNotes,
              appliedTargets: Array.from(new Set([...item.appliedTargets, ...AUDIO_APPLY_TARGETS])),
              dirtySinceApply: false,
              lastAppliedTranscriptText: transcriptText,
              lastAppliedNonverbalNotes: nonverbalNotes,
              lastAppliedMode: isReapply ? item.lastAppliedMode || mode : mode,
              error: undefined,
            }
          : item,
      ),
    )
    setMaterialModal(null)
  }

  const revokeObjectUrl = (objectUrl?: string) => {
    if (!objectUrl) return
    URL.revokeObjectURL(objectUrl)
    objectUrlsRef.current.delete(objectUrl)
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (unappliedReadyMaterials.length > 0) {
      setHasSubmitted(true)
      setError('아직 회기 입력에 반영되지 않은 업로드 자료가 있습니다. 자료에 반영하거나 삭제한 뒤 요약초안을 생성해주세요.')
      return
    }
    if (materials.length && !hasUsableNoteInput) {
      setHasSubmitted(true)
      setError('업로드한 자료가 아직 회기 입력에 반영되지 않았습니다. 자료에 반영할 항목을 선택해주세요.')
      return
    }
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
          demo_mode: form.case_id === 'CASE-MUSPSY-1416',
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
              setForm((prev) => ({ ...prev, case_id: 'CASE-MUSPSY-1416', session_number: 5 }))
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
                  hasMaterialRows={hasMaterialRows}
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
          onApplyAudioTranscript={applyAudioTranscriptToForm}
          onApplyMaterial={applyMaterialToForm}
          onRefreshAudioCapabilities={refreshAudioCapabilities}
          onTranscribeAudio={transcribeAudioMaterial}
          onUpdateAudioExpectedSpeakers={updateAudioExpectedSpeakers}
          onUpdateAudioSegmentText={updateAudioSegmentText}
          onUpdateAudioSpeakerRole={updateAudioSpeakerRole}
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
            <CaseListItem name="가명 다은" status="진행중" meta="성인 · 5회기" active />
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
  hasMaterialRows,
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
  hasMaterialRows: boolean
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

        {!hasMaterialRows ? (
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
                onApply={() => onOpenMaterial(material.id, material.kind === 'audio' ? 'audio_review' : 'material_apply')}
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
  const hasText = Boolean(getMaterialText(material).trim())
  const isDocumentReady = material.kind === 'document' && ['completed', 'warning'].includes(material.status) && hasText
  const isAudioReady = material.kind === 'audio' && material.status === 'transcribed' && hasText
  const canApply = isDocumentReady || isAudioReady
  const needsApply = canApply && (material.appliedTargets.length === 0 || material.dirtySinceApply)
  const canPreview = canApply
  const canTranscribe =
    material.kind === 'audio' &&
    material.status !== 'transcribed' &&
    material.status !== 'transcribing' &&
    transcriptionAvailable

  return (
    <div className={`material-row px-3 py-2 ${needsApply ? 'bg-amber-50' : ''}`}>
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
          {material.kind === 'document' && ['completed', 'warning'].includes(material.status) && !hasText && (
            <p className="mt-1 text-xs text-amber-700">텍스트를 추출하지 못했습니다. 현재 스캔 이미지 PDF의 OCR은 지원하지 않습니다.</p>
          )}
        </div>
        {material.status === 'uploading' || material.status === 'transcribing' ? (
          <Loader2 className="mt-1 h-4 w-4 shrink-0 animate-spin text-blue-600" />
        ) : material.status === 'failed' ? (
          <AlertTriangle className="mt-1 h-4 w-4 shrink-0 text-rose-600" />
        ) : needsApply ? (
          <AlertTriangle className="mt-1 h-4 w-4 shrink-0 text-amber-600" />
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
      {material.error && <p className="mt-2 text-xs font-semibold text-rose-600">{material.error}</p>}
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
  onApplyAudioTranscript,
  onApplyMaterial,
  onClose,
  onModeChange,
  onRefreshAudioCapabilities,
  onTranscribeAudio,
  onUpdateAudioExpectedSpeakers,
  onUpdateAudioSegmentText,
  onUpdateAudioSpeakerRole,
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
  onApplyAudioTranscript: (materialId: string, mode: MaterialApplyMode) => void
  onApplyMaterial: (materialId: string, target: MaterialApplyTarget, mode: MaterialApplyMode) => void
  onClose: () => void
  onModeChange: (mode: MaterialModalMode) => void
  onRefreshAudioCapabilities: () => Promise<AudioCapabilitiesResponse>
  onTranscribeAudio: (materialId: string) => void
  onUpdateAudioExpectedSpeakers: (materialId: string, value: number) => void
  onUpdateAudioSegmentText: (materialId: string, segmentId: number, text: string) => void
  onUpdateAudioSpeakerRole: (materialId: string, speakerKey: string, role: SpeakerRole) => void
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

  useEffect(() => {
    if (mode !== 'material_apply' || !selectedMaterial) return
    const target = selectedMaterial.kind === 'audio' ? 'transcript_text' : 'counselor_memo'
    setApplyTarget(target)
    setApplyMode(String(form[target] || '').trim() ? 'append' : 'replace')
  }, [form, mode, selectedMaterial])

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
              {selectedText.trim() ? (
                <textarea value={selectedText} readOnly className={`${textareaClass} min-h-[320px] bg-slate-50`} />
              ) : (
                <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-800">
                  텍스트를 추출하지 못했습니다. 현재 스캔 이미지 PDF의 OCR은 지원하지 않습니다.
                </p>
              )}
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
              <AudioTranscriptEditor
                material={selectedMaterial}
                applyMode={applyMode}
                transcriptionAvailable={transcriptionAvailable}
                transcriptionReason={audioCapabilities?.transcription.reason || null}
                onApply={() => onApplyAudioTranscript(selectedMaterial.id, applyMode)}
                onApplyModeChange={setApplyMode}
                onExpectedSpeakersChange={(value) => onUpdateAudioExpectedSpeakers(selectedMaterial.id, value)}
                onTranscribe={() => onTranscribeAudio(selectedMaterial.id)}
                onUpdateSegmentText={(segmentId, text) => onUpdateAudioSegmentText(selectedMaterial.id, segmentId, text)}
                onUpdateSpeakerRole={(speakerKey, role) => onUpdateAudioSpeakerRole(selectedMaterial.id, speakerKey, role)}
              />
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

function validateSelectedFile(file: File, kind: UploadedMaterialKind): UploadedMaterial | null {
  const extension = getFileExtension(file.name)
  const allowed = kind === 'document' ? DOCUMENT_UPLOAD_EXTENSIONS : AUDIO_UPLOAD_EXTENSIONS
  const maxBytes = kind === 'document' ? DOCUMENT_UPLOAD_MAX_BYTES : AUDIO_UPLOAD_MAX_BYTES
  const defaultLimitLabel = kind === 'document' ? '20MB' : '500MB'

  if (!allowed.has(extension)) {
    return buildFailedMaterial(file, kind, `지원하지 않는 파일 형식입니다. ${Array.from(allowed).join(', ')} 파일을 선택해주세요.`)
  }
  if (file.size > maxBytes) {
    return buildFailedMaterial(file, kind, `기본 업로드 제한(${defaultLimitLabel})을 초과했습니다.`)
  }
  if (file.size === 0) {
    return buildFailedMaterial(file, kind, '빈 파일은 업로드할 수 없습니다.')
  }
  return null
}

function buildFailedMaterial(file: File, kind: UploadedMaterialKind, error: string): UploadedMaterial {
  return {
    id: makeMaterialId(file),
    kind,
    filename: file.name,
    mediaType: file.type,
    status: 'failed',
    warnings: [],
    error,
    appliedTargets: [],
  }
}

function getFileExtension(filename: string): string {
  const index = filename.lastIndexOf('.')
  return index >= 0 ? filename.slice(index).toLowerCase() : ''
}

function mergeMaterialText(current: string, incoming: string, mode: MaterialApplyMode): string {
  const cleanIncoming = incoming.trim()
  if (!cleanIncoming) return mode === 'replace' ? '' : current.trim()
  if (mode === 'replace' || !current.trim()) return cleanIncoming
  return `${current.trim()}\n\n${cleanIncoming}`
}

function buildTranscribedAudioMaterial(
  material: UploadedMaterial,
  transcription: AudioTranscriptionResponse,
): UploadedMaterial {
  const speakerRoleMap = buildInitialSpeakerRoleMap(transcription.segments, material.speakerRoleMap)
  const transcriptText = buildTranscriptText(transcription.segments, speakerRoleMap) || transcription.transcript_text
  const nonverbalNotes = buildNonverbalNotes(transcription.segments, speakerRoleMap) || transcription.nonverbal_notes
  return {
    ...material,
    status: 'transcribed',
    transcriptText,
    segments: transcription.segments,
    durationSeconds: transcription.duration_seconds,
    language: transcription.language,
    runtimeMode: transcription.runtime_mode,
    diarizationStatus: transcription.diarization_status,
    languageProbability: transcription.language_probability,
    nonverbalNotes,
    speakerRoleMap,
    warnings: transcription.warnings,
    error: undefined,
    dirtySinceApply: true,
    appliedTargets: material.appliedTargets.filter((target) => !AUDIO_APPLY_TARGETS.includes(target)),
  }
}

function buildInitialSpeakerRoleMap(segments: AudioSegment[], previous: SpeakerRoleMap = {}): SpeakerRoleMap {
  return segments.reduce<SpeakerRoleMap>((map, segment) => {
    const speakerKey = getSegmentSpeakerKey(segment)
    map[speakerKey] = previous[speakerKey] || 'unassigned'
    return map
  }, {})
}

function markAudioMaterialDirty(material: UploadedMaterial): UploadedMaterial {
  if (material.kind !== 'audio') return material
  const speakerRoleMap = buildInitialSpeakerRoleMap(material.segments || [], material.speakerRoleMap)
  return {
    ...material,
    speakerRoleMap,
    transcriptText: buildTranscriptText(material.segments || [], speakerRoleMap) || material.transcriptText,
    nonverbalNotes: buildNonverbalNotes(material.segments || [], speakerRoleMap),
    dirtySinceApply: true,
    appliedTargets: material.appliedTargets.filter((target) => !AUDIO_APPLY_TARGETS.includes(target)),
  }
}

function materialMetaText(material: UploadedMaterial): string {
  if (material.kind === 'audio' && material.dirtySinceApply && getMaterialText(material).trim()) {
    return '축어록 수정사항이 회기 입력에 아직 다시 반영되지 않았습니다.'
  }
  if (material.appliedTargets.length) {
    return `${material.appliedTargets.map((target) => materialApplyTargetLabel[target]).join(', ')}에 반영 완료`
  }
  if (material.status === 'uploading') return '텍스트 추출 중'
  if (material.status === 'selected') return '음성 파일 선택 완료'
  if (material.status === 'transcribing') return '축어록 생성 중'
  if (material.status === 'failed') return '처리 실패'
  if (material.kind === 'audio') {
    const duration = material.durationSeconds ? ` · ${formatSeconds(material.durationSeconds)}` : ''
    const count = countCharacters(getMaterialText(material))
    return material.status === 'transcribed'
      ? `축어록 생성 완료 · 아직 요약에 미반영 · ${count}자${duration}`
      : `음성 자료${duration}`
  }
  if (!material.extractedText?.trim() && ['completed', 'warning'].includes(material.status)) {
    return '텍스트를 추출하지 못했습니다. 현재 스캔 이미지 PDF의 OCR은 지원하지 않습니다.'
  }
  const count = material.characterCount ?? countCharacters(material.extractedText || '')
  const pageCount = material.pageCount ? ` · ${material.pageCount}쪽` : ''
  return `추출 완료 · 아직 요약에 미반영 · ${count.toLocaleString('ko-KR')}자${pageCount}`
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
    runtimeMode: material.runtimeMode,
    diarizationStatus: material.diarizationStatus,
    languageProbability: material.languageProbability,
    speakerRoleMap: material.speakerRoleMap,
    nonverbalNotes: material.nonverbalNotes,
    dirtySinceApply: material.dirtySinceApply,
    expectedSpeakers: material.expectedSpeakers,
    appliedTargets: material.appliedTargets,
  }))
}

const materialApplyTargetLabel: Record<MaterialApplyTarget, string> = {
  transcript_text: '축어록',
  nonverbal_notes: '비언어 관찰 메모',
  counselor_memo: '상담사 메모',
  previous_session_summary: '이전 회기 요약',
  psychological_test_summary: '심리검사 요약',
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
