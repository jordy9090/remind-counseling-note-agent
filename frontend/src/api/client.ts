import axios from 'axios'
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
  CaseDashboardResponse,
  CaseScheduleUpdateRequest,
  TemporaryDraftSaveRequest,
  TemporaryDraftSaveResponse,
} from '../types/session'
import { getAccessToken } from '../lib/supabase'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 90000,
})

client.interceptors.request.use(async (config) => {
  const accessToken = await getAccessToken()
  if (accessToken) {
    config.headers = config.headers ?? {}
    config.headers.Authorization = `Bearer ${accessToken}`
  }
  return config
})

export const generateNoteDraft = async (input: SessionInput): Promise<NoteDraftResponse> => {
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
      persist: Boolean(input.persist),
    })
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
): Promise<TemporaryDraftSaveResponse> => {
  const response = await client.post<TemporaryDraftSaveResponse>('/api/notes/drafts', draft)
  return response.data
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

export const extractDocumentMaterial = async (file: File): Promise<DocumentExtractionResponse> => {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const response = await client.post<DocumentExtractionResponse>('/api/materials/documents/extract', formData, {
      timeout: 120000,
    })
    return response.data
  } catch (error) {
    throw normalizeApiError(error, '문서 내용을 추출하지 못했습니다.')
  }
}

export const getAudioCapabilities = async (): Promise<AudioCapabilitiesResponse> => {
  const response = await client.get<AudioCapabilitiesResponse>('/api/audio/capabilities')
  return response.data
}

export const transcribeAudio = async (
  file: File,
  language = 'ko',
  task = 'transcribe',
  expectedSpeakers = 2,
): Promise<AudioTranscriptionResponse> => {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('language', language)
  formData.append('task', task)
  formData.append('expected_speakers', String(expectedSpeakers))
  try {
    const response = await client.post<AudioTranscriptionResponse>('/api/audio/transcribe', formData, {
      timeout: 900000,
    })
    return response.data
  } catch (error) {
    throw normalizeApiError(error, '음성 축어록을 생성하지 못했습니다.')
  }
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

function toNoteDraftResponse(fullResponse: GenerateNoteResponse): NoteDraftResponse {
  const draft = fullResponse.session_summary_draft
  const verification = fullResponse.verification_report

  return {
    case_id: draft.session_info.case_id,
    session_number: draft.session_info.session_number,
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
        ? [fullResponse.persistence_report.message]
        : []),
    ]),
    grounding: fullResponse.grounding,
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
