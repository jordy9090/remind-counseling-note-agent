import axios from 'axios'
import { AudioChunkRequestError, transcribeHostedAudio, type SpeakerReference } from '../lib/hostedAudio'
import type {
  AudioCapabilitiesResponse,
  AudioTranscriptionResponse,
  DocumentCapabilitiesResponse,
  ConfirmGeneratedNoteRequest,
  ConfirmGeneratedNoteResponse,
  EvidenceCheckItem,
  EvidenceConfidence,
  EvidenceSourceType,
  DocumentExtractionResponse,
  DocumentExportRequest,
  EvidenceType,
  GenerateNoteResponse,
  NoteDraftResponse,
  RecomposeNoteRequest,
  RecomposeNoteResponse,
  SessionInput,
  SupervisionReportDraft,
  SupervisionReportRequest,
  CaseCreateRequest,
  CaseDashboardResponse,
  CaseListResponse,
  CaseProfileUpdateRequest,
  CaseScheduleUpdateRequest,
  TemporaryDraftSaveRequest,
  TemporaryDraftSaveResponse,
  TemporaryDraftRecord,
  GeneratedNoteRecord,
  QuickSummarySessionResponse,
  SessionInputDeletionResponse,
} from '../types/session'
import { getAccessToken, supabase } from '../lib/supabase'
import { cleanQuickSummarySections } from '../lib/quickSummary'
import type { QuickSummaryResult } from '../lib/quickSummary'
import type { StoredPerson } from '../lib/personMapping'
import { reviewForAI, type ReviewPurpose, type ReviewTask, type ReviewedPayload } from '../lib/aiReview'
import type { DeidSource } from '../lib/deidentificationReview'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
// Audio goes directly to the configured self-hosted FastAPI origin.
const AUDIO_API_BASE_URL = import.meta.env.VITE_AUDIO_API_BASE_URL || API_BASE_URL

declare module 'axios' {
  interface AxiosRequestConfig { expectedOwnerId?: string | null }
}

export interface RequestScope { ownerId?: string | null; signal?: AbortSignal }
const requestScope = (scope?: RequestScope) => ({ signal: scope?.signal, expectedOwnerId: scope?.ownerId })

export function isRetryableRequestError(error: unknown): boolean {
  if (!axios.isAxiosError(error) || axios.isCancel(error)) return false
  const status = error.response?.status
  return status === undefined || status === 408 || status === 429 || status >= 500
}

async function scopedSession(owner: string | null) {
  const session = (await supabase?.auth.getSession())?.data.session
  if ((session?.user.id || null) !== owner) throw new Error('로그인 상태가 변경되었습니다. 현재 계정에서 다시 시작해주세요.')
  return session
}

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 90000,
})

client.interceptors.request.use(async (config) => {
  const accessToken = config.expectedOwnerId !== undefined
    ? (await scopedSession(config.expectedOwnerId))?.access_token || null
    : await getAccessToken()
  const needsPersistenceToken = /^\/api\/notes\/(drafts|confirm|records)(\/|$)/.test(config.url || '')
    || (config.url === '/api/notes/generate' && config.data?.persist === true)
  if (needsPersistenceToken && !accessToken) {
    throw new Error('로그인이 필요하거나 로그인 세션이 만료되었습니다. 다시 로그인해주세요.')
  }
  if (accessToken) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  const reviewPurposes: Record<string, ReviewPurpose> = {
    '/api/notes/generate': 'generate', '/api/notes/quick-summary': 'quick',
    '/api/notes/recompose': 'recompose', '/api/notes/supervision-report': 'supervision',
    '/api/notes/confirm': 'memory',
  }
  const purpose = reviewPurposes[config.url || '']
  if (purpose && (purpose !== 'memory' || config.data?.create_case_memory !== false)) {
    const session = (await supabase?.auth.getSession())?.data.session
    const ownerId = config.expectedOwnerId !== undefined ? config.expectedOwnerId : session?.user.id || null
    await scopedSession(ownerId)
    const reviewed = await reviewForAI(purpose, config.data, ownerId, config.signal as AbortSignal | undefined)
    const currentSession = await scopedSession(ownerId)
    if (currentSession?.access_token) config.headers.Authorization = `Bearer ${currentSession.access_token}`
    config.data = reviewed.payload
    config.headers['X-Review-Receipt'] = reviewed.receipt
  }
  return config
})

client.interceptors.response.use(async response => {
  if (response.config.expectedOwnerId !== undefined) await scopedSession(response.config.expectedOwnerId)
  return response
})

export const generateNoteDraft = async (
  input: SessionInput,
): Promise<NoteDraftResponse> => {
  try {
    const response = await client.post<GenerateNoteResponse>('/api/notes/generate', {
      case_id: input.case_id,
      client_alias: input.client_alias || '',
      session_number: input.session_number,
      session_date: input.session_date,
      counselor_name: input.counselor_name,
      counselor_memo: input.counselor_memo,
      transcript_text: input.transcript_text,
      previous_session_summary: input.previous_session_summary,
      counseling_goal: input.counseling_goal || '',
      psychological_test_summary: input.psychological_test_summary || '',
      key_issue_tags: input.key_issue_tags || [],
      nonverbal_notes: input.nonverbal_notes || '',
      target_document_type: input.target_document_type || 'session_note',
      insight_lens: 'psychodynamic_relational',
      persist: Boolean(input.persist),
    }, { timeout: 310000 })
    return toNoteDraftResponse(response.data)
  } catch (error) {
    throw normalizeApiError(error, '회기요약 초안을 생성하지 못했습니다.')
  }
}

export const postGenerateNote = generateNoteDraft

export const confirmGeneratedNote = async (
  request: ConfirmGeneratedNoteRequest,
): Promise<ConfirmGeneratedNoteResponse> => {
  const response = await client.post<ConfirmGeneratedNoteResponse>('/api/notes/confirm', request)
  return response.data
}

export const saveTemporaryDraft = async (
  draft: TemporaryDraftSaveRequest,
  scope?: RequestScope,
): Promise<TemporaryDraftSaveResponse> => {
  const response = await client.post<TemporaryDraftSaveResponse>('/api/notes/drafts', draft, requestScope(scope))
  return response.data
}

export const listTemporaryDrafts = async (caseId?: string, scope?: RequestScope): Promise<TemporaryDraftRecord[]> => {
  const response = await client.get<TemporaryDraftRecord[]>('/api/notes/drafts', {
    ...requestScope(scope),
    params: caseId ? { case_id: caseId } : undefined,
  })
  return response.data
}

export const loadTemporaryDraft = async (draftId: string): Promise<TemporaryDraftRecord> => {
  const response = await client.get<TemporaryDraftRecord>(`/api/notes/drafts/${encodeURIComponent(draftId)}`)
  return response.data
}

export const loadGeneratedNote = async (noteId: string): Promise<GeneratedNoteRecord> => {
  const response = await client.get<GeneratedNoteRecord>(`/api/notes/records/${encodeURIComponent(noteId)}`)
  return response.data
}

/** 회기별 원문 삭제: removes the stored input of the note's session; the summary is kept. */
export const deleteSessionInput = async (noteId: string): Promise<SessionInputDeletionResponse> => {
  const response = await client.post<SessionInputDeletionResponse>(`/api/notes/records/${encodeURIComponent(noteId)}/input-deletion`)
  return response.data
}

/** Do not expose storage diagnostics or counseling payloads in persistence errors. */
export function persistenceErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 401 || error.response?.status === 403) return '로그인 상태 또는 기록 접근 권한을 확인해주세요.'
    if (error.response?.status === 404) return '저장된 기록을 찾을 수 없습니다. 목록을 다시 조회해주세요.'
    return '저장소 요청을 완료하지 못했습니다. 현재 작성 내용은 유지됩니다. 잠시 후 다시 시도해주세요.'
  }
  return error instanceof Error ? error.message : '저장소 요청을 완료하지 못했습니다.'
}

export interface RecomposeNoteDraftResult {
  note: NoteDraftResponse
  cacheHit: boolean
  cacheKey: string
  visibleSectionIds: string[]
}

export const recomposeNoteDraft = async (
  request: RecomposeNoteRequest,
): Promise<RecomposeNoteDraftResult> => {
  const response = await client.post<RecomposeNoteResponse>('/api/notes/recompose', request)
  return {
    note: toNoteDraftResponse(response.data.result),
    cacheHit: response.data.cache_hit,
    cacheKey: response.data.cache_key,
    visibleSectionIds: response.data.visible_section_ids,
  }
}

export const generateSupervisionReport = async (
  request: SupervisionReportRequest,
): Promise<SupervisionReportDraft> => {
  const response = await client.post<SupervisionReportDraft>('/api/notes/supervision-report', request)
  return response.data
}

export const downloadDocumentExport = async (
  request: DocumentExportRequest,
): Promise<{ blob: Blob; filename: string }> => {
  try {
    const response = await client.post<Blob>('/api/documents/export', request, {
      responseType: 'blob',
    })
    return {
      blob: response.data,
      filename: extractFilename(response.headers['content-disposition']) || buildFallbackExportFilename(request),
    }
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.data instanceof Blob) {
      const bodyText = await error.response.data.text()
      let message = bodyText
      try {
        const parsed = JSON.parse(bodyText)
        message = parsed.detail || message
      } catch {
        message = bodyText
      }
      throw new Error(message || '문서 내보내기 중 오류가 발생했습니다.')
    }
    throw error
  }
}

export const getDocumentCapabilities = async (): Promise<DocumentCapabilitiesResponse> => {
  const response = await client.get<DocumentCapabilitiesResponse>('/api/documents/capabilities')
  return response.data
}

export const extractDocumentMaterial = async (file: File, scope?: RequestScope): Promise<DocumentExtractionResponse> => {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const response = await client.post<DocumentExtractionResponse>('/api/materials/documents/extract', formData, {
      ...requestScope(scope),
      timeout: 120000,
    })
    return response.data
  } catch (error) {
    throw normalizeApiError(error, '문서 내용을 추출하지 못했습니다.')
  }
}

/** Public quick summary: works without login; the server masks PII and stores nothing. */
/**
 * Public quick summary: the regular summary pipeline without login. The server de-identifies the
 * input, stores nothing, and returns the same response as a signed-in generation.
 */
export const requestQuickSummary = async (text: string, scope?: RequestScope): Promise<NoteDraftResponse> => {
  try {
    const response = await client.post<GenerateNoteResponse>('/api/notes/quick-summary', { text }, { ...requestScope(scope), timeout: 310000 })
    return toNoteDraftResponse(response.data)
  } catch (error) {
    throw normalizeApiError(error, '요약을 만들지 못했어요. 잠시 후 다시 시도해주세요.')
  }
}

export interface DeidPreviewItem {
  original: string
  replacement: string
  category: 'name' | 'occupation' | 'organization' | 'age' | 'location' | 'birth_date' | 'contact' | 'identifier'
}

export interface AIReviewPreview {
  payload: Record<string, unknown>
  sources: DeidSource[]
  items: DeidPreviewItem[]
  detection_token: string
  model_used: boolean
}

export async function startAIReview(task: ReviewTask, signal: AbortSignal): Promise<AIReviewPreview> {
  let jobToken = ''
  const deadline = Date.now() + 20 * 60 * 1000
  while (Date.now() < deadline) {
    const response = await client.post<AIReviewPreview & { status?: string; job_token?: string }>('/api/notes/deidentification-preview',
      { purpose: task.purpose, payload: task.payload, job_token: jobToken }, { timeout: 30000, signal, expectedOwnerId: task.ownerId })
    if (response.data.status !== 'pending') {
      if (!response.data.model_used) throw new Error('자체 서버 탐지를 완료하지 못했습니다.')
      return response.data
    }
    jobToken = response.data.job_token || ''
    if (!jobToken) throw new Error('탐지 작업을 확인하지 못했습니다.')
    await new Promise<void>((resolve, reject) => {
      if (signal.aborted) return reject(new Error('요청이 취소되었습니다.'))
      const abort = () => { clearTimeout(timer); reject(new Error('요청이 취소되었습니다.')) }
      const timer = window.setTimeout(() => { signal.removeEventListener('abort', abort); resolve() }, 5000)
      signal.addEventListener('abort', abort, { once: true })
    })
  }
  throw new Error('탐지 시간이 초과되었습니다. 분량을 나누어 다시 시도해주세요.')
}

export async function confirmAIReview(task: ReviewTask, preview: AIReviewPreview, edits: {
  path: string; start: number; end: number; original: string; replacement: string
}[]): Promise<ReviewedPayload> {
  const response = await client.post<ReviewedPayload>('/api/notes/deidentification-confirm', {
    purpose: task.purpose, payload: preview.payload, detection_token: preview.detection_token, edits,
  }, { signal: task.signal, expectedOwnerId: task.ownerId })
  return response.data
}

export const getAudioCapabilities = async (): Promise<AudioCapabilitiesResponse> => {
  const response = await client.get<AudioCapabilitiesResponse>('/api/audio/capabilities', { baseURL: AUDIO_API_BASE_URL })
  return response.data
}

export const transcribeAudio = async (
  file: File,
  language = 'ko',
  task = 'transcribe',
  expectedSpeakers = 2,
  onProgress?: (message: string) => void,
  stillActive?: () => boolean,
): Promise<AudioTranscriptionResponse> => {
  const capabilities = await getAudioCapabilities()
  if (!capabilities.transcription.available) throw new Error(capabilities.transcription.reason || '음성 인식 연결 설정이 필요합니다.')
  // The current UI consent names CLOVA. A stale provider configuration must never
  // silently send the recording to a different company.
  if (capabilities.provider === 'openai') throw new Error('CLOVA Speech로 전환 중입니다. 잠시 후 다시 시도해주세요.')
  if (capabilities.provider === 'clova') {
    const session = (await supabase?.auth.getSession())?.data.session
    if (!session) throw new AudioChunkRequestError('로그인이 필요하거나 로그인 세션이 만료되었습니다.', false)
    const owner = session.user.id
    return transcribeHostedAudio(file, expectedSpeakers, async (chunk, references) => {
      if ((await supabase?.auth.getSession())?.data.session?.user.id !== owner) {
        throw new AudioChunkRequestError('로그인 계정이 변경되었습니다. 음성을 다시 선택해주세요.', false)
      }
      return sendAudioChunk(chunk, language, task, expectedSpeakers, references)
    }, onProgress, stillActive, `${owner}:${language}:${task}:${AUDIO_API_BASE_URL}`)
  }
  return sendAudioChunk(file, language, task, expectedSpeakers)
}

const sendAudioChunk = async (file: File, language: string, task: string, expectedSpeakers: number,
  references?: SpeakerReference[]): Promise<AudioTranscriptionResponse> => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('language', language)
  formData.append('task', task)
  formData.append('expected_speakers', String(expectedSpeakers))
  if (references) {
    formData.append('cloud_audio_consent', 'true')
    formData.append('cloud_audio_provider', 'clova')
    formData.append('speaker_references', JSON.stringify(references))
  }
  try {
    const response = await client.post<AudioTranscriptionResponse>('/api/audio/transcribe', formData, {
      baseURL: AUDIO_API_BASE_URL,
      timeout: references ? 120000 : 7200000,
    })
    return response.data
  } catch (error) {
    const status = axios.isAxiosError(error) ? error.response?.status : undefined
    const retryable = axios.isAxiosError(error) && !axios.isCancel(error)
      && (status === undefined || status === 408 || status === 429 || status >= 500)
    throw new AudioChunkRequestError(normalizeApiError(error, '음성 축어록을 생성하지 못했습니다.').message, retryable)
  }
}

export const reviewAudioPrivacy = async (text: string): Promise<{ text: string; candidates: { category: string }[] }> => {
  const response = await client.post('/api/audio/deidentify', { text }, { baseURL: AUDIO_API_BASE_URL })
  return response.data
}

export { API_BASE_URL }
export default client

function normalizeApiError(error: unknown, fallback: string): Error {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) {
      return new Error(detail)
    }
    if (Array.isArray(detail) && detail.length) {
      return new Error(detail.map((item) => item?.msg || String(item)).join('\n'))
    }
    if (error.response?.status === 401) {
      return new Error('로그인이 필요하거나 로그인 세션이 만료되었습니다.')
    }
    if (error.response?.status === 413) {
      return new Error('파일 용량이 서버 업로드 제한을 초과했습니다.')
    }
    if (error.response?.status === 415) {
      return new Error('지원하지 않는 파일 형식입니다. TXT, PDF 또는 DOCX 파일을 선택해주세요.')
    }
    if (error.response?.status === 404) {
      return new Error('업로드 API를 찾을 수 없습니다. 배포 상태를 확인해주세요.')
    }
    if (error.response && error.response.status >= 500) {
      return new Error('서버에서 파일을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.')
    }
    if (typeof error.message === 'string' && error.message.trim()) {
      return new Error(error.message)
    }
  }
  return error instanceof Error ? error : new Error(fallback)
}

export function toNoteDraftResponse(fullResponse: GenerateNoteResponse): NoteDraftResponse {
  const draft = fullResponse.session_summary_draft
  const verification = fullResponse.verification_report

  return {
    case_id: fullResponse.sanitized_input.case_id,
    session_number: fullResponse.sanitized_input.session_number,
    session_summary: draft.session_content.text,
    main_issue: draft.presenting_problem.text,
    counselor_intervention: draft.counselor_intervention.text,
    client_response: draft.client_response.text,
    next_plan: draft.next_plan.text,
    evidence_check: buildEvidenceCheck(fullResponse),
    missing_items: unique([
      ...fullResponse.document_transform_preview.missing_required_fields,
      ...(fullResponse.retrieved_template_context?.missing_field_checklist || []),
      ...verification.requires_counselor_review.map((item) => item.field),
    ]),
    warnings: unique([
      'AI 초안은 상담사의 검토 전 최종 회기 기록으로 사용되지 않습니다.',
      ...verification.unsupported_or_risky_claims.map((item) => item.claim),
      ...verification.sensitive_info_items.map((item) => `민감정보 후보: ${item.text}`),
      ...(fullResponse.retrieved_privacy_context || []).map((item) => item.warning),
      ...(fullResponse.retrieval_report?.failures || []).map((item) => `검색 실패: ${item}`),
      ...(fullResponse.persistence_report?.requested && !fullResponse.persistence_report?.stored
        ? ['AI 초안은 생성되었지만 기록 저장에 실패했습니다. 임시저장으로 작성 내용을 보관해주세요.']
        : []),
    ]),
    grounding: fullResponse.grounding,
    relational_insights: fullResponse.relational_insights,
    full_response: fullResponse,
  }
}

function buildEvidenceCheck(fullResponse: GenerateNoteResponse): EvidenceCheckItem[] {
  return fullResponse.evidence_mapped_data.items
    .filter((item) => item.field !== 'reflection_candidates')
    .slice(0, 10)
    .map((item) => {
      const sourceType = getSourceType(item.evidence_type, item.source_refs)
      return {
        claim: item.content,
        source_type: sourceType,
        source_excerpt: getSourceExcerpt(fullResponse, sourceType, item.source_refs),
        confidence: getConfidence(item.evidence_type),
      }
    })
}

function getSourceType(evidenceType: EvidenceType, refs: string[]): EvidenceSourceType {
  if (refs.some((ref) => ref.startsWith('stored_session_note:') || ref.startsWith('stored_evidence:'))) {
    return 'retrieved_context'
  }
  if (refs.some((ref) => ref.startsWith('kb_template:'))) return 'template_context'
  if (refs.some((ref) => ref.startsWith('kb_privacy:'))) return 'privacy_context'
  if (['inferred', 'model_inference', 'needs_review'].includes(evidenceType)) {
    return 'ai_inference'
  }
  if (refs.includes('transcript_text')) return 'transcript'
  if (refs.includes('counselor_memo') || refs.includes('nonverbal_notes')) return 'counselor_memo'
  if (refs.includes('previous_session_summary')) return 'previous_summary'
  return 'ai_inference'
}

function getSourceExcerpt(fullResponse: GenerateNoteResponse, sourceType: EvidenceSourceType, refs: string[]): string {
  const sources = fullResponse.sanitized_input.sources
  const sourceText = sourceType === 'retrieved_context'
    ? getRetrievedContextExcerpt(fullResponse, refs)
    : sourceType === 'template_context'
      ? getTemplateContextExcerpt(fullResponse)
      : sourceType === 'privacy_context'
        ? getPrivacyContextExcerpt(fullResponse, refs)
        : refs.includes('nonverbal_notes')
    ? sources.nonverbal_notes
    : sourceType === 'transcript'
      ? sources.transcript_text
      : sourceType === 'counselor_memo'
        ? sources.counselor_memo
        : sourceType === 'previous_summary'
          ? sources.previous_session_summary
          : '입력 자료를 바탕으로 한 AI 요약/추론입니다. 상담사 확인이 필요합니다.'

  const compact = sourceText.replace(/\s+/g, ' ').trim()
  return compact.length > 180 ? `${compact.slice(0, 180)}...` : compact
}

function getConfidence(evidenceType: EvidenceType): EvidenceConfidence {
  if (evidenceType === 'direct') return 'high'
  if (['mixed', 'counselor_input', 'previous_context', 'prior_context_based'].includes(evidenceType)) return 'medium'
  return 'low'
}

function getRetrievedContextExcerpt(fullResponse: GenerateNoteResponse, refs: string[]): string {
  const contexts = fullResponse.retrieved_case_context || []
  const sessionRef = refs.find((ref) => ref.startsWith('stored_session_note:'))
  if (sessionRef) {
    const context = contexts.find((item) => item.source_ref === sessionRef)
    if (context?.summary) return context.summary
  }

  const evidenceRef = refs.find((ref) => ref.startsWith('stored_evidence:'))
  if (evidenceRef) {
    for (const context of contexts) {
      const evidence = context.evidence_items.find((item) => item.source_ref === evidenceRef)
      if (evidence?.source_text) return evidence.source_text
    }
  }
  return '저장된 이전 회기 기록을 참고한 문장입니다. 원문 연결을 확인해주세요.'
}

function getTemplateContextExcerpt(fullResponse: GenerateNoteResponse): string {
  const template = fullResponse.retrieved_template_context
  if (!template) return '문서 양식 KB에서 가져온 기준입니다.'
  return [
    template.required_fields.length ? `필수: ${template.required_fields.join(', ')}` : '',
    template.counselor_review_fields.length ? `상담사 확인: ${template.counselor_review_fields.join(', ')}` : '',
  ].filter(Boolean).join(' / ') || '문서 양식 KB에서 가져온 기준입니다.'
}

function getPrivacyContextExcerpt(fullResponse: GenerateNoteResponse, refs: string[]): string {
  const ref = refs.find((item) => item.startsWith('kb_privacy:'))
  const rule = (fullResponse.retrieved_privacy_context || []).find((item) => item.source_ref === ref)
  return rule ? `${rule.rule} ${rule.warning}` : '개인정보/윤리 KB에서 가져온 검토 기준입니다.'
}

function unique(items: string[]): string[] {
  return Array.from(new Set(items.filter(Boolean)))
}

function extractFilename(contentDisposition: string | undefined): string | null {
  if (!contentDisposition) return null
  const encodedMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1])
    } catch {
      return encodedMatch[1]
    }
  }
  const fallbackMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
  return fallbackMatch?.[1] || null
}

function buildFallbackExportFilename(request: DocumentExportRequest): string {
  const extension = request.format === 'pdf' ? 'pdf' : request.format === 'hwpx' ? 'hwpx' : 'docx'
  return `${request.document_type}_${request.case_id}_${request.session_number}회기_${request.session_date || 'date'}.${extension}`
}


/** 로그인 사용자가 소유한 케이스 목록. 서버가 사용자 JWT(RLS)로만 조회하므로 다른 계정의 케이스는 포함되지 않는다. */
export const fetchCaseList = async (): Promise<CaseListResponse> => {
  const response = await client.get<CaseListResponse>('/api/cases')
  return response.data
}

/** 새 내담자(케이스) 생성. 서버가 케이스 ID를 만들고 소유자를 로그인 사용자로 기록한다. */
export const createCase = async (payload: CaseCreateRequest, scope?: RequestScope): Promise<CaseDashboardResponse> => {
  const response = await client.post<CaseDashboardResponse>('/api/cases', payload, requestScope(scope))
  return response.data
}

/** Save the summary and de-identified supporting excerpts as the client's next AI draft. */
export const saveQuickSummaryToClient = async (
  caseId: string,
  summary: Pick<QuickSummaryResult, 'sections'>,
  scope?: RequestScope,
): Promise<QuickSummarySessionResponse> => {
  const sections = cleanQuickSummarySections(summary.sections)
  const response = await client.post<QuickSummarySessionResponse>(`/api/cases/${encodeURIComponent(caseId)}/quick-summary`, { sections }, requestScope(scope))
  return response.data
}

export const updateCaseProfile = async (
  caseId: string,
  payload: CaseProfileUpdateRequest,
): Promise<CaseDashboardResponse> => {
  const response = await client.patch<CaseDashboardResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/profile`,
    payload,
  )
  return response.data
}

/** The client's 인물 사전 (person labels with their names and relation words). */
export const fetchCasePersonDictionary = async (caseId: string): Promise<StoredPerson[]> => {
  const response = await client.get<{ case_id: string; people: StoredPerson[] }>(
    `/api/cases/${encodeURIComponent(caseId)}/person-dictionary`,
  )
  return response.data.people
}

export const saveCasePersonDictionary = async (caseId: string, people: StoredPerson[]): Promise<StoredPerson[]> => {
  const response = await client.put<{ case_id: string; people: StoredPerson[] }>(
    `/api/cases/${encodeURIComponent(caseId)}/person-dictionary`,
    { people },
  )
  return response.data.people
}

export const fetchCaseDashboard = async (caseId: string): Promise<CaseDashboardResponse> => {
  const response = await client.get<CaseDashboardResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/dashboard`,
  )
  return response.data
}

export const updateCaseSchedule = async (
  caseId: string,
  payload: CaseScheduleUpdateRequest,
): Promise<CaseDashboardResponse> => {
  const response = await client.patch<CaseDashboardResponse>(
    `/api/cases/${encodeURIComponent(caseId)}/schedule`,
    payload,
  )
  return response.data
}
