import type { RelationalInsightCard, RelationalInsightFocus, RelationalInsights, TheorySource } from '../types/insight'

const focusLabels: Record<RelationalInsightFocus, string> = {
  relationship_pattern: '관계 패턴',
  here_and_now: '지금-여기 관계 경험',
  intervention_response: '개입과 내담자 반응',
  counselor_reflection: '상담자 성찰',
}

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
    || !isStringArray(value.notices)) return unavailableInsights
  return value as unknown as RelationalInsights
}

/** Add reviewable analysis to the existing memo text without changing the screen structure. */
export function formatRelationalSupervisionMemo(value: unknown, originalReflection: string): string {
  const insights = readRelationalInsights(value)
  if (!insights || insights.status === 'demo') return originalReflection

  const append = (text: string) => originalReflection.trim() ? `${originalReflection}\n\n${text}` : text
  if (insights.status === 'unavailable') {
    return append('정신역동·관계 관점의 분석을 생성하거나 확인하지 못했습니다. 가설 제시는 보류합니다.')
  }
  if (insights.status === 'insufficient_evidence' || insights.cards.length === 0) {
    return append('정신역동·관계 관점의 가설을 제시할 회기 근거가 충분하지 않아 해석을 보류합니다.')
  }

  const sourcesById = new Map(insights.theory_sources
    .filter((source) => isHttpsUrl(source.url) && source.title.trim())
    .map((source) => [source.id, source]))
  const cards = insights.cards.filter((card) =>
    card.evidence.some((evidence) => evidenceLabels[evidence.source_ref] && evidence.quote.trim())
    && card.theory_source_ids.some((id) => sourcesById.has(id)),
  ).slice(0, 4)
  if (cards.length === 0) {
    return append('인사이트의 회기 근거 또는 문헌 연결을 확인할 수 없어 해석을 보류합니다.')
  }

  const citedIds = Array.from(new Set(cards.flatMap((card) => card.theory_source_ids.filter((id) => sourcesById.has(id)))))
  const citationNumbers = new Map(citedIds.map((id, index) => [id, index + 1]))
  const cardText = cards.map((card, index) => {
    const evidence = card.evidence
      .filter((item) => evidenceLabels[item.source_ref] && item.quote.trim())
      .slice(0, 2)
      .map((item) => `${evidenceLabels[item.source_ref]}: “${item.quote}”`)
      .join('\n')
    const citations = Array.from(new Set(card.theory_source_ids))
      .flatMap((id) => citationNumbers.has(id) ? [`[${citationNumbers.get(id)}]`] : [])
      .join(' ')
    const questions = card.supervision_questions.filter((question) => question.trim()).slice(0, 2).join(' / ')
    return [
      `${index + 1}. ${focusLabels[card.focus]}`,
      `관찰: ${card.observation}`,
      `잠정 가설: ${card.hypothesis}`,
      `대안 설명: ${card.alternative_explanation}`,
      `반대 근거·미확인: ${card.counterevidence_or_missing}`,
      `수퍼비전 질문: ${questions || '추가 질문은 상담사가 직접 검토해 주세요.'}`,
      `회기 근거\n${evidence}`,
      `참고 문헌: ${citations}`,
    ].join('\n')
  }).join('\n\n')

  const bibliography = citedIds.map((id) => {
    const source = sourcesById.get(id)!
    return `[${citationNumbers.get(id)}] ${source.title}\n${source.url}`
  }).join('\n')

  return append([
    '정신역동·관계 관점 — 상담사 검토가 필요한 잠정 가설',
    cardText,
    `참고 문헌\n${bibliography}\n문헌은 성찰의 관점을 제공하며, 이 내담자에 대한 가설을 입증하지 않습니다.`,
  ].join('\n\n'))
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
