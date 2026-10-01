export type InsightLens = 'none' | 'psychodynamic_relational'

export type RelationalInsightFocus =
  | 'relationship_pattern'
  | 'here_and_now'
  | 'intervention_response'
  | 'counselor_reflection'

export interface TheorySource {
  id: string
  title: string
  organization: string
  url: string
  locator: string
  principle: string
  concepts: string[]
  limitations: string
}

export interface RelationalInsightCard {
  id: string
  focus: RelationalInsightFocus
  observation: string
  hypothesis: string
  alternative_explanation: string
  counterevidence_or_missing: string
  brief_text?: string
  supervision_questions: string[]
  evidence: Array<{ source_ref: string; quote: string }>
  theory_source_ids: string[]
  requires_review: true
}

export interface RelationalInsights {
  status: 'generated' | 'insufficient_evidence' | 'unavailable' | 'demo'
  lens: 'psychodynamic_relational'
  cards: RelationalInsightCard[]
  theory_sources: TheorySource[]
  notices: string[]
  supervision_memo?: string
}
