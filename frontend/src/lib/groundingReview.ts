import type {
  GroundedClaim,
  GroundedGenerationResult,
  GroundingSource,
  GroundingSupportType,
} from '../types/session'

export interface GroundingReviewItem {
  claim: GroundedClaim
  sources: GroundingSource[]
  missingSource: boolean
  stale: boolean
}

export interface TranscriptEvidenceLine {
  role: '상담자' | '내담자' | '원문'
  text: string
}

const sectionTargetField: Record<string, string> = {
  main_issue: 'presenting_problem',
  session_theme: 'session_theme',
  session_content: 'session_content',
  counselor_intervention: 'counselor_intervention',
  client_response: 'client_response',
  next_plan: 'next_plan',
  supervision_memo: 'reflection',
}

export const supportStateLabel: Record<GroundingSupportType, string> = {
  direct_evidence: '근거 확인',
  counselor_judgment: '상담사 확정 기록',
  clinical_inference: 'AI 해석 · 확인 필요',
  unsupported: '근거 부족 · 검토 필요',
}

export function targetFieldForSection(sectionId: string): string | null {
  return sectionTargetField[sectionId] || null
}

export function buildGroundingReviewItems(
  grounding: GroundedGenerationResult | null | undefined,
  sectionId: string,
): GroundingReviewItem[] {
  if (!grounding?.enabled) return []
  const targetField = targetFieldForSection(sectionId)
  if (!targetField) return []

  const sourceById = new Map(grounding.context.sources.map((source) => [source.evidence_id, source]))
  return grounding.claims
    .filter((claim) => claim.target_field === targetField)
    .map((claim) => {
      const permittedIds = validatedEvidenceIds(claim, grounding)
      const sources = permittedIds.flatMap((evidenceId) => {
        const source = sourceById.get(evidenceId)
        return source ? [source] : []
      })
      return {
        claim,
        sources,
        missingSource: permittedIds.length > sources.length || expectsEvidence(claim) && !permittedIds.length,
        stale: false,
      }
    })
}

export function markGroundingItemsStale(items: GroundingReviewItem[]): GroundingReviewItem[] {
  return items.map((item) => ({ ...item, stale: true }))
}

export function isInlineGroundingItem(
  item: GroundingReviewItem,
  items: GroundingReviewItem[],
  renderedText: string,
): boolean {
  if (!['direct_evidence', 'counselor_judgment'].includes(item.claim.support_type)) return false

  const normalizedClaim = normalizeForMatch(item.claim.text)
  const normalizedRendered = normalizeForMatch(renderedText)
  if (normalizedClaim && normalizedRendered
    && (normalizedClaim === normalizedRendered
      || normalizedRendered.includes(normalizedClaim)
      || normalizedClaim.includes(normalizedRendered))) {
    return true
  }

  const factualItems = items.filter(({ claim }) => (
    claim.support_type === 'direct_evidence' || claim.support_type === 'counselor_judgment'
  ))
  return factualItems.length === 1
}

export function parseTranscriptEvidence(sourceText: string): TranscriptEvidenceLine[] {
  return sourceText.split(/\r?\n/).filter(Boolean).map((line) => {
    const client = line.match(/^\[client\]\s?(.*)$/i)
    if (client) return { role: '내담자', text: client[1] }
    const counselor = line.match(/^\[counselor\]\s?(.*)$/i)
    if (counselor) return { role: '상담자', text: counselor[1] }
    return { role: '원문', text: line }
  })
}

export function counselorSourceField(sourceRef: string): string | null {
  const parts = sourceRef.split(':')
  const field = parts[parts.length - 1]?.trim()
  if (!field || field === sourceRef) return null
  return field
}

function validatedEvidenceIds(
  claim: GroundedClaim,
  grounding: GroundedGenerationResult,
): string[] {
  if (claim.support_type === 'unsupported') return []
  if (claim.support_type === 'clinical_inference') return claim.evidence_ids

  const validation = grounding.claim_support_validations[claim.claim_id]
  if (validation?.verdict !== 'supported') return []
  const supportedIds = new Set(validation.supported_evidence_ids)
  return claim.evidence_ids.filter((evidenceId) => supportedIds.has(evidenceId))
}

function expectsEvidence(claim: GroundedClaim): boolean {
  return claim.support_type !== 'unsupported' && claim.evidence_ids.length > 0
}

function normalizeForMatch(value: string): string {
  return value
    .replace(/\s+/g, '')
    .replace(/[.,!?·ㆍ:;"'“”‘’()\[\]{}]/g, '')
    .toLocaleLowerCase('ko-KR')
}
