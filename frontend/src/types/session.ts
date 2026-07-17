export type EvidenceType =
  | 'direct'
  | 'inferred'
  | 'counselor_input'
  | 'previous_context'
  | 'prior_context_based'
  | 'needs_review'
  | 'mixed'
  | 'model_inference'

export type TargetDocumentType = 'session_note' | 'supervision_report' | 'termination_report'

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
  target_document_type?: TargetDocumentType
  persist?: boolean
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
  partially_available_fields: Record<string, string>
  missing_required_fields: string[]
  notice: string
}

export interface RetrievedEvidenceItem {
  id?: string | null
  source_type: string
  source_ref: string
  source_text: string
  linked_field: string
}

export interface RetrievedCaseContextItem {
  source_ref: string
  session_id: string
  session_number?: number | null
  session_date: string
  summary: string
  confirmed_note: Record<string, unknown>
  evidence_items: RetrievedEvidenceItem[]
}

export interface RetrievedTemplateContext {
  target_document_type: TargetDocumentType
  required_fields: string[]
  optional_fields: string[]
  counselor_review_fields: string[]
  missing_field_checklist: string[]
  source_refs: string[]
}

export interface RetrievedPrivacyRule {
  source_ref: string
  title: string
  category: string
  rule: string
  warning: string
}

export interface RetrievalReport {
  enabled: boolean
  case_context_count: number
  template_context_found: boolean
  privacy_rule_count: number
  failures: string[]
  notices: string[]
}

export interface PersistenceReport {
  enabled: boolean
  requested: boolean
  stored: boolean
  case_id?: string | null
  session_id?: string | null
  note_id?: string | null
  message: string
}

export interface GenerateNoteResponse {
  structured_case_data: StructuredCaseData
  evidence_mapped_data: EvidenceMappedData
  session_summary_draft: SessionSummaryDraft
  verification_report: VerificationReport
  document_transform_preview: DocumentTransformPreview
  confirmed_session_note: Record<string, unknown>
  sanitized_input: SanitizedInput
  retrieved_case_context: RetrievedCaseContextItem[]
  retrieved_template_context?: RetrievedTemplateContext | null
  retrieved_privacy_context: RetrievedPrivacyRule[]
  retrieval_report: RetrievalReport
  persistence_report: PersistenceReport
  stub: boolean
}

export type EvidenceSourceType =
  | 'transcript'
  | 'counselor_memo'
  | 'previous_summary'
  | 'retrieved_context'
  | 'template_context'
  | 'privacy_context'
  | 'ai_inference'
export type EvidenceConfidence = 'high' | 'medium' | 'low'

export interface EvidenceCheckItem {
  claim: string
  source_type: EvidenceSourceType
  source_excerpt: string
  confidence: EvidenceConfidence
}

export interface NoteDraftResponse {
  case_id: string
  session_number: number
  session_summary: string
  main_issue: string
  counselor_intervention: string
  client_response: string
  next_plan: string
  evidence_check: EvidenceCheckItem[]
  missing_items: string[]
  warnings: string[]
  full_response?: GenerateNoteResponse
}

export interface TemporaryDraftSaveRequest {
  draft_id?: string
  case_id: string
  session_number: number
  session_date: string
  counselor_name: string
  screen: string
  form: SessionInput
  session_topic: string
  is_deidentified: boolean
  selected_previous_session_ids: string[]
  attachments: unknown[]
  visible_section_ids: string[]
  draft_sections: unknown[]
  result?: unknown
  final_document_type: string
  supervision_report_draft?: unknown
}

export interface TemporaryDraftSaveResponse {
  draft_id: string
  case_id: string
  session_number: number
  saved_at: string
  message: string
}

export interface RecomposeNoteRequest {
  session_input: SessionInput
  session_topic: string
  visible_section_ids: string[]
}

export interface RecomposeNoteResponse {
  result: GenerateNoteResponse
  visible_section_ids: string[]
  cache_key: string
  cache_hit: boolean
}

export type SupervisionReportStatus = 'complete' | 'partial' | 'missing' | 'needs_review'
export type SupervisionReviewStatus = 'unchecked' | 'confirmed' | 'edited' | 'needs_human_input'
export type SupervisionContentBlockType = 'paragraph' | 'table' | 'transcript' | 'reflection_box' | 'placeholder'

export interface SupervisionSpeakerTurn {
  turnId: string
  speaker: 'client' | 'counselor'
  text: string
  silenceSeconds?: number
}

export interface SupervisionContentBlock {
  id: string
  type: SupervisionContentBlockType
  text?: string
  rows?: Record<string, string>[]
  speakerTurns?: SupervisionSpeakerTurn[]
  evidenceIds: string[]
  aiGenerated: boolean
  demoValue: boolean
  reviewStatus: SupervisionReviewStatus
  warnings?: string[]
}

export interface SupervisionReportSection {
  id: string
  title: string
  level: 1 | 2 | 3
  contentBlocks: SupervisionContentBlock[]
  status: SupervisionReportStatus
}

export interface SupervisionAiReviewPanel {
  completionChecklist: Array<{
    label: string
    status: 'done' | 'partial' | 'missing'
    reason?: string
  }>
  missingFields: string[]
  demoInputs: string[]
  needsHumanReview: Array<{
    sectionId: string
    message: string
    severity: 'low' | 'medium' | 'high'
  }>
  unsupportedClaims: Array<{
    blockId: string
    claim: string
    reason: string
  }>
  suggestedSupervisionQuestions: string[]
  caution: string
}

export interface SupervisionReportDraft {
  reportId: string
  caseId: string
  reportType: 'personal_counseling_supervision'
  title: string
  meta: {
    clientAlias: string
    sessionNumber: number
    reportDate: string
    counselorName?: string
    institution?: string
    supervisor?: string
    supervisionDatePlace?: string
  }
  sections: SupervisionReportSection[]
  aiReview: SupervisionAiReviewPanel
  evidenceIndex: Record<string, { label: string; text: string }>
}

export interface SupervisionReportRequest {
  session_input: SessionInput
  session_summary_draft?: SessionSummaryDraft
  demo_mode?: boolean
  report_date?: string
  client_alias?: string
  institution?: string
  supervisor?: string
  supervision_date_place?: string
}

export type DocumentExportFormat = 'docx' | 'pdf' | 'hwpx'

export interface DocumentExportTranscriptTurn {
  turn_id?: string
  turnId?: string
  speaker: 'client' | 'counselor' | 'other'
  text: string
  silence_seconds?: number | null
  silenceSeconds?: number | null
}

export interface DocumentExportContentBlock {
  id: string
  type: SupervisionContentBlockType
  text?: string | null
  rows?: Record<string, unknown>[]
  speaker_turns?: DocumentExportTranscriptTurn[]
  speakerTurns?: DocumentExportTranscriptTurn[]
  warnings?: string[]
}

export interface DocumentExportSection {
  id: string
  title: string
  content?: string | string[] | null
  content_blocks?: DocumentExportContentBlock[]
  contentBlocks?: DocumentExportContentBlock[]
  level?: number
}

export interface DocumentExportRequest {
  format: DocumentExportFormat
  document_type: TargetDocumentType
  case_id: string
  session_number: number
  session_date: string
  title: string
  metadata: Record<string, unknown>
  sections: DocumentExportSection[]
}
