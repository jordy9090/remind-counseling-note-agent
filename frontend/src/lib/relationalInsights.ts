import type { RelationalInsightCard, RelationalInsights, TheorySource } from '../types/insight'

const evidenceLabels: Record<string, string> = {
  transcript_text: '축어록',
  counselor_memo: '상담자 메모',
  nonverbal_notes: '비언어 관찰 메모',
}

const unavailableInsights: RelationalInsights = {
  status: 'unavailable',
  lens: 'psychodynamic_relational',
  cards: [],
  theory_sources: [],
  notices: ['저장된 인사이트의 형식을 확인하지 못했습니다. 회기 요약은 유지되며, 인사이트는 다시 생성한 뒤 검토해 주세요.'],
}

/** Stored drafts can predate this contract; malformed insight data must not break the note. */
export function readRelationalInsights(value: unknown): RelationalInsights | null {
  if (value === null || value === undefined) return null
  if (!isRecord(value)
    || value.lens !== 'psychodynamic_relational'
    || !['generated', 'insufficient_evidence', 'unavailable', 'demo'].includes(String(value.status))
    || !Array.isArray(value.cards) || !value.cards.every(isInsightCard)
    || !Array.isArray(value.theory_sources) || !value.theory_sources.every(isTheorySource)
    || (value.supervision_memo !== undefined && typeof value.supervision_memo !== 'string')
    || !isStringArray(value.notices)) return unavailableInsights
  return value as unknown as RelationalInsights
}

/** Show the validated compact draft; detailed provenance remains separate from editable prose. */
export function formatRelationalSupervisionMemo(value: unknown, originalReflection: string): string {
  const insights = readRelationalInsights(value)
  if (!insights || insights.status !== 'generated') return originalReflection
  const memo = insights.supervision_memo?.trim()
  if (!memo || insights.cards.length === 0) return originalReflection

  const sourcesById = new Map(insights.theory_sources
    .filter((source) => isHttpsUrl(source.url) && source.title.trim())
    .map((source) => [source.id, source]))
  const connected = insights.cards.every((card) =>
    card.evidence.some((evidence) => evidenceLabels[evidence.source_ref] && evidence.quote.trim())
    && card.theory_source_ids.some((id) => sourcesById.has(id)),
  )
  // The server builds this text only from accepted cards. Stale or mixed payloads abstain.
  const briefs = Array.from(new Set(insights.cards.map((card) => card.brief_text?.trim() ?? ''))).filter(Boolean)
  if (briefs.length === 0) return originalReflection
  const acceptedBriefs = briefs.join('\n\n')
  const withRecordedReflection = Array.from(new Set([...briefs, originalReflection.trim()])).filter(Boolean).join('\n\n')
  return connected && (memo === acceptedBriefs || memo === withRecordedReflection) ? memo : originalReflection
}

function isHttpsUrl(value: string): boolean {
  try {
    return new URL(value).protocol === 'https:'
  } catch {
    return false
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

function hasStrings(value: Record<string, unknown>, keys: string[]): boolean {
  return keys.every((key) => typeof value[key] === 'string')
}

function isInsightCard(value: unknown): value is RelationalInsightCard {
  return isRecord(value)
    && hasStrings(value, ['id', 'observation', 'hypothesis', 'alternative_explanation', 'counterevidence_or_missing'])
    && (value.brief_text === undefined || typeof value.brief_text === 'string')
    && ['relationship_pattern', 'here_and_now', 'intervention_response', 'counselor_reflection'].includes(String(value.focus))
    && value.requires_review === true
    && isStringArray(value.supervision_questions)
    && isStringArray(value.theory_source_ids)
    && Array.isArray(value.evidence)
    && value.evidence.every((item) => isRecord(item) && hasStrings(item, ['source_ref', 'quote']))
}

function isTheorySource(value: unknown): value is TheorySource {
  return isRecord(value)
    && hasStrings(value, ['id', 'title', 'organization', 'url', 'locator', 'principle', 'limitations'])
    && isStringArray(value.concepts)
}
