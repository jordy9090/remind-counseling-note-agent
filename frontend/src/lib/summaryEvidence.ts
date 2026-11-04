import type { EvidenceCheckItem, EvidenceConfidence, EvidenceSourceType, GenerateNoteResponse, NoteDraftResponse, SummarySection } from '../types/session'

export interface SavedSummaryEvidence {
  label: string
  excerpt: string
  sourceRef: string
  sourceType: 'transcript' | 'counselor_memo'
  confidence: EvidenceConfidence
  needsReview: boolean
  truncated?: boolean
}

/** Persist only bounded, attributed excerpts, never source containers or extraction caches. */
export function savedSummaryEvidence(value: unknown): SavedSummaryEvidence[] {
  if (!Array.isArray(value)) return []
  return value.slice(0, 40).flatMap(item => {
    if (!item || typeof item !== 'object' || typeof item.label !== 'string' || !item.label.trim()
      || typeof item.excerpt !== 'string' || !item.excerpt.trim()
      || typeof item.sourceRef !== 'string'
      || !/^(transcript\.turn_[1-9]\d*|counselor_memo)$/.test(item.sourceRef)
      || item.sourceType !== (item.sourceRef === 'counselor_memo' ? 'counselor_memo' : 'transcript')) return []
    return [{ label: item.label.slice(0, 60), excerpt: item.excerpt.slice(0, 2000),
      sourceRef: item.sourceRef, sourceType: item.sourceType,
      confidence: ['high', 'medium', 'low'].includes(item.confidence) ? item.confidence : 'low',
      needsReview: item.needsReview !== false,
      ...(item.truncated || item.excerpt.length > 2000 ? { truncated: true } : {}),
    }]
  })
}

/** Quotes come from attributed source text even when generated prose chooses no quotation marks. */
export function clientMemoryQuotes(evidence: unknown): string[] {
  const quotes = savedSummaryEvidence(evidence).flatMap(item => {
    if (item.sourceType !== 'transcript' || item.truncated) return []
    return item.excerpt.split(/\r?\n/).filter(line => /^\s*내담자\s*[:：]/.test(line))
      .map(line => line.replace(/^\s*내담자\s*[:：]\s*/, '').trim())
      .filter(line => line.length >= 12)
  })
  return [...new Set(quotes)].slice(0, 2)
}

const summaryFields = {
  main_issue: 'presenting_problem',
  session_theme: 'session_theme',
  session_content: 'session_content',
  counselor_intervention: 'counselor_intervention',
  client_response: 'client_response',
  next_plan: 'next_plan',
} as const

export function riskInformation(result: NoteDraftResponse): SummarySection {
  const document = result.full_response?.session_note_draft
  const field = '위험 관련 확인 가능 정보'
  const text = document?.sections?.[field]?.trim()
  const refs = document?.source_refs?.[field] || []
  return {
    text: text || '위험 관련 정보는 상담사가 별도로 확인해 주세요.',
    source_refs: refs,
    evidence_type: text && refs.length ? 'direct' : 'needs_review',
    requires_review: true,
  }
}

export function summarySectionEvidence(result: NoteDraftResponse, sectionId: string): {
  evidence: EvidenceCheckItem[]
  requiresReview: boolean
  inferred: boolean
} | undefined {
  const response = result.full_response
  if (!response) return undefined
  const field = summaryFields[sectionId as keyof typeof summaryFields]
  if (!field && sectionId !== 'risk_signal') return undefined
  const section = sectionId === 'risk_signal' ? riskInformation(result) : response.session_summary_draft?.[field]
  if (!section) return { evidence: [], requiresReview: true, inferred: false }
  // An explicitly absent plan is not a fabricated claim that the counselor must repair.
  if (field === 'next_plan' && section.text.trim() === '[자료에서 확인되지 않음]' && !section.source_refs?.length) {
    return { evidence: [], requiresReview: false, inferred: false }
  }
  const inferred = ['inferred', 'model_inference'].includes(section.evidence_type)
  const confidence: EvidenceConfidence = section.evidence_type === 'direct' ? 'high'
    : inferred || section.evidence_type === 'needs_review' ? 'low' : 'medium'
  const evidence = new Map<string, EvidenceCheckItem>()
  const refs = section.source_refs || []
  const preciseTypes = new Set(refs.filter(ref => ref.startsWith('transcript.turn_') || /^previous_session\.\d+$/.test(ref))
    .filter(ref => resolveSource(response, ref)?.text.trim())
    .map(ref => resolveSource(response, ref)!.type))
  for (const ref of refs) {
    const source = resolveSource(response, ref)
    if (!source) continue
    const excerpt = source.text.replace(/\s+/g, ' ').trim()
    if (!excerpt) continue
    if ((ref === 'transcript_text' || ref === 'previous_session_summary') && preciseTypes.has(source.type)) continue
    const precise = ref.startsWith('transcript.turn_') || /^previous_session\.\d+$/.test(ref)
    const item = { claim: section.text, source_type: source.type, source_ref: ref,
      source_excerpt: !precise && excerpt.length > 180 ? `${excerpt.slice(0, 180)}...` : excerpt, confidence }
    // Keep every cited turn so an intervention and its response remain readable together.
    evidence.set(ref, item)
  }
  return {
    evidence: [...evidence.values()],
    requiresReview: section.requires_review || inferred || section.evidence_type === 'needs_review' || !evidence.size,
    inferred,
  }
}

function resolveSource(response: GenerateNoteResponse, ref: string): { type: EvidenceSourceType; text: string } | undefined {
  const sources = response.sanitized_input?.sources
  if (ref === 'transcript_text') return { type: 'transcript', text: sources?.transcript_text || '' }
  if (ref.startsWith('transcript.turn_')) {
    const line = Number(ref.slice('transcript.turn_'.length)) - 1
    return { type: 'transcript', text: sources?.transcript_text?.split(/\r?\n/)[line] || '' }
  }
  if (ref === 'counselor_memo' || ref === 'nonverbal_notes') {
    return { type: 'counselor_memo', text: sources?.[ref] || '' }
  }
  if (ref === 'counseling_goal') return { type: 'counselor_input', text: sources?.counseling_goal || '' }
  if (ref === 'key_issue_tags') return { type: 'counselor_input', text: sources?.key_issue_tags?.join(', ') || '' }
  if (ref === 'psychological_test_summary') return { type: 'psychological_test', text: sources?.psychological_test_summary || '' }
  if (ref === 'previous_session_summary') {
    return { type: 'previous_summary', text: sources?.previous_session_summary || '' }
  }
  const previousSession = /^previous_session\.(\d+)$/.exec(ref)
  if (previousSession) {
    const blocks = (sources?.previous_session_summary || '').matchAll(/(?:^|\n)\s*(\d+)회기(?:\s*\([^)]*\))?\s*:\s*(.*?)(?=\n\s*\d+회기(?:\s*\(|\s*:)|$)/gs)
    for (const block of blocks) {
      if (block[1] === previousSession[1]) return { type: 'previous_summary', text: block[2] }
    }
    return undefined
  }
  for (const context of response.retrieved_case_context || []) {
    if (ref === context.source_ref) return { type: 'retrieved_context', text: context.summary }
    const item = context.evidence_items?.find(item => item.source_ref === ref)
    if (item) return { type: 'retrieved_context', text: item.source_text }
  }
  const grounded = response.grounding?.context.sources.find(source => source.source_ref === ref)
  if (grounded) return { type: 'retrieved_context', text: grounded.source_text }
  if (ref.startsWith('kb_template:')) return { type: 'template_context', text: '문서 양식 기준을 참고했습니다.' }
  const privacy = response.retrieved_privacy_context?.find(item => item.source_ref === ref)
  if (privacy) return { type: 'privacy_context', text: `${privacy.rule} ${privacy.warning}` }
  return undefined
}
