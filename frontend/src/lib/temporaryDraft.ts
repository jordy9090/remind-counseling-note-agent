import type { TemporaryDraftSaveRequest } from '../types/session'

// Keep this projection in sync with backend/app/services/temporary_draft_payload.py.
// Only workspace content is persisted; extraction and evidence caches are not workspace content.
type Shape = 'scalar' | { [key: string]: Shape } | [Shape]
const fields = (names: string): Record<string, Shape> => Object.fromEntries(names.split(' ').map(name => [name, 'scalar']))
const strings: Shape = ['scalar']
const section = fields('id title content visible')
const block: Shape = {
  ...fields('id type text aiGenerated demoValue reviewStatus label evidenceStatus'),
  rows: [{ '*': 'scalar' }], speakerTurns: [fields('turnId speaker text silenceSeconds')],
  evidenceIds: strings, warnings: strings, guidance: strings, missingInputs: strings,
}
const shape: Shape = {
  ...fields('draft_id saved_at case_id session_number session_date counselor_name screen session_topic is_deidentified final_document_type'),
  selected_previous_session_ids: strings, visible_section_ids: strings,
  form: {
    ...fields('case_id client_alias session_number session_date counselor_name counselor_memo transcript_text previous_session_summary counseling_goal psychological_test_summary nonverbal_notes target_document_type persist'),
    key_issue_tags: strings,
  },
  attachments: [{
    ...fields('id kind filename mediaType status characterCount pageCount durationSeconds language runtimeMode diarizationStatus languageProbability dirtySinceApply expectedSpeakers lastAppliedMode requiresReattachment'),
    appliedTargets: strings,
  }],
  draft_sections: [section],
  final_document_sections: [fields('id title content contentKind')],
  result: {
    ...fields('case_id session_number session_summary main_issue counselor_intervention client_response next_plan workspace_note_id'),
    missing_items: strings, warnings: strings,
  },
  supervision_report_draft: {
    ...fields('reportId caseId reportType title'),
    meta: fields('clientAlias sessionNumber reportDate counselorName institution supervisor supervisionDatePlace'),
    sections: [{ ...fields('id title level status'), guidance: strings, contentBlocks: [block] }],
    aiReview: {
      completionChecklist: [fields('label status reason')], missingFields: strings, demoInputs: strings,
      needsHumanReview: [fields('sectionId message severity')], unsupportedClaims: [fields('blockId claim reason')],
      suggestedSupervisionQuestions: strings, caution: 'scalar',
    },
  },
}

function project(value: unknown, allowed: Shape): unknown {
  if (value === null) return null
  if (allowed === 'scalar') return ['string', 'number', 'boolean'].includes(typeof value) ? value : undefined
  if (Array.isArray(allowed)) return Array.isArray(value)
    ? value.map(item => project(item, allowed[0])).filter(item => item !== undefined) : undefined
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  return Object.fromEntries(Object.entries(value).flatMap(([key, item]) => {
    const rule = Object.prototype.hasOwnProperty.call(allowed, key) ? allowed[key] : allowed['*']
    const projected = rule ? project(item, rule) : undefined
    return projected === undefined ? [] : [[key, projected]]
  }))
}

export function temporaryDraftPayload<T extends TemporaryDraftSaveRequest>(draft: T): T {
  const data = project(draft, shape) as T
  data.attachments = (data.attachments || []).map(material => ({
    ...(material as object), requiresReattachment: true, warnings: [],
  }))
  if (data.result && typeof data.result === 'object') data.result = { ...data.result, evidence_check: [] }
  if (data.supervision_report_draft && typeof data.supervision_report_draft === 'object') {
    data.supervision_report_draft = { ...data.supervision_report_draft, evidenceIndex: {} }
  }
  return data
}

export const REATTACHMENT_NOTICE = '첨부 원문·추출 텍스트·음성 축어록 미리보기는 복원되지 않습니다. 다시 확인하려면 파일을 재첨부해주세요. 회기 입력에 반영한 내용은 유지됩니다.'
