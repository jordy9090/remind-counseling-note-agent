export type EvidenceType =
  | 'direct'
  | 'inferred'
  | 'counselor_input'
  | 'previous_context'
  | 'needs_review'
  | 'mixed'
  | 'model_inference'

export interface SessionInput {
  case_id: string
  session_number: number
  session_date: string
  counselor_name: string
  counselor_memo: string
  transcript_text: string
  previous_session_summary: string
  counseling_goal?: string
  psychological_test_summary?: string
  key_issue_tags?: string[]
  nonverbal_notes?: string
}

export interface SensitiveInfoCandidate {
  text: string
  source: string
  category: string
  recommendation: string
}

export interface InputSources {
  counselor_memo: string
  transcript_text: string
  previous_session_summary: string
  counseling_goal: string
  psychological_test_summary: string
  key_issue_tags: string[]
  nonverbal_notes: string
}

export interface SanitizedInput {
  case_id: string
  session_number: number
  session_date: string
  counselor_name: string
  sources: InputSources
  sensitive_info_candidates: SensitiveInfoCandidate[]
}

export interface EvidenceItem {
  content: string
  evidence_type: EvidenceType
  source_refs: string[]
}

export interface StructuredCaseData {
  presenting_problem: EvidenceItem[]
  session_theme: EvidenceItem[]
  session_content: EvidenceItem[]
  counselor_interventions: EvidenceItem[]
  client_responses: EvidenceItem[]
  key_client_utterances: EvidenceItem[]
  nonverbal_observations: EvidenceItem[]
  reflection_candidates: EvidenceItem[]
  next_plan: EvidenceItem[]
}

export interface EvidenceMappedItem {
  field: string
  content: string
  evidence_type: EvidenceType
  source_refs: string[]
  requires_review: boolean
}

export interface EvidenceMappedData {
  items: EvidenceMappedItem[]
}

export interface SessionInfo {
  case_id: string
  session_number: number
  session_date: string
  counselor_name: string
}

export interface SummarySection {
  text: string
  evidence_type: EvidenceType
  source_refs: string[]
  requires_review: boolean
}

export interface SessionSummaryDraft {
  session_info: SessionInfo
  session_theme: SummarySection
  presenting_problem: SummarySection
  session_content: SummarySection
  counselor_intervention: SummarySection
  client_response: SummarySection
  reflection: SummarySection
  next_plan: SummarySection
}

export interface GroundedItem {
  claim: string
  source_refs: string[]
}

export interface ReviewableClaim {
  claim: string
  reason: string
  recommendation: string
}

export interface CounselorReviewField {
  field: string
  reason: string
}

export interface VerificationReport {
  grounded_items: GroundedItem[]
  weakly_grounded_items: ReviewableClaim[]
  unsupported_or_risky_claims: ReviewableClaim[]
  sensitive_info_items: SensitiveInfoCandidate[]
  requires_counselor_review: CounselorReviewField[]
}

export interface DocumentTransformPreview {
  document_type: string
  available_transforms: string[]
  preview_sections: Record<string, string>
  missing_required_fields: string[]
  notice: string
}

export interface GenerateNoteResponse {
  structured_case_data: StructuredCaseData
  evidence_mapped_data: EvidenceMappedData
  session_summary_draft: SessionSummaryDraft
  verification_report: VerificationReport
  document_transform_preview: DocumentTransformPreview
  confirmed_session_note: Record<string, unknown>
  sanitized_input: SanitizedInput
  stub: boolean
}
