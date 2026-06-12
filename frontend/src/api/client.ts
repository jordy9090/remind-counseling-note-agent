import axios from 'axios'
import type {
  EvidenceCheckItem,
  EvidenceConfidence,
  EvidenceSourceType,
  EvidenceType,
  GenerateNoteResponse,
  NoteDraftResponse,
  SessionInput,
} from '../types/session'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 90000,
})

export const generateNoteDraft = async (input: SessionInput): Promise<NoteDraftResponse> => {
  const response = await client.post<GenerateNoteResponse>('/api/notes/generate', {
    case_id: input.case_id,
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
  })
  return toNoteDraftResponse(response.data)
}

export const postGenerateNote = generateNoteDraft

export { API_BASE_URL }
export default client

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
      ...verification.requires_counselor_review.map((item) => item.field),
    ]),
    warnings: unique([
      'AI 초안은 상담사의 검토 전 최종 회기 기록으로 사용되지 않습니다.',
      ...verification.unsupported_or_risky_claims.map((item) => item.claim),
      ...verification.sensitive_info_items.map((item) => `민감정보 후보: ${item.text}`),
    ]),
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
  const sourceText = refs.includes('nonverbal_notes')
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
  if (['mixed', 'counselor_input', 'previous_context'].includes(evidenceType)) return 'medium'
  return 'low'
}

function unique(items: string[]): string[] {
  return Array.from(new Set(items.filter(Boolean)))
}
