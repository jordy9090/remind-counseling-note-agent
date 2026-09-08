import type { GeneratedNoteRecord, NoteDraftResponse } from '../types/session'

export interface StoredSection {
  id: string
  title: string
  content: string
  visible: boolean
}

const fieldMap: Record<string, string> = {
  main_issue: 'presenting_problem',
  supervision_memo: 'reflection',
}

export function sectionFingerprint(sections: StoredSection[]): string {
  return JSON.stringify(sections.map(({ id, title, content, visible }) => ({ id, title, content, visible })))
}

export function confirmedPayload(original: Record<string, unknown>, sections: StoredSection[]): Record<string, unknown> {
  const payload = { ...original }
  // The canonical summary fields serve dashboard readers; sections serves case memory.
  const textSections: Record<string, string> = {}
  for (const section of sections) {
    const field = fieldMap[section.id] || section.id
    textSections[field] = section.content
    const metadata = original[field]
    payload[field] = {
      ...(isObject(metadata) ? metadata : {}),
      text: section.content,
    }
  }
  // Grounding belongs to the AI draft, not to newly edited assertions.
  delete payload.grounding
  return {
    ...payload,
    sections: textSections,
    workspace_sections: sections.map(({ id, title, content, visible }) => ({ id, title, content, visible })),
  }
}

export function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

export function readStoredSections(value: unknown): StoredSection[] | null {
  if (!Array.isArray(value) || !value.length) return null
  if (!value.every((section) => isObject(section) && typeof section.id === 'string'
    && typeof section.title === 'string' && typeof section.content === 'string'
    && typeof section.visible === 'boolean')) return null
  return value as StoredSection[]
}

export function recordPayload(record: GeneratedNoteRecord): Record<string, unknown> {
  const confirmed = record.confirmation_status === 'confirmed' || record.confirmation_status === 'demo_confirmed'
  const payload = confirmed ? record.confirmed_json : record.draft_json
  if (!isObject(payload) || !Object.keys(payload).length) throw new Error('저장된 기록 내용이 비어 있어 복원할 수 없습니다.')
  return payload
}

export function noteFromRecord(record: GeneratedNoteRecord): NoteDraftResponse {
  const payload = recordPayload(record)
  const text = (field: string) => {
    const section = payload[field]
    if (isObject(section) && typeof section.text === 'string') return section.text
    const sections = payload.sections
    return isObject(sections) && typeof sections[field] === 'string' ? sections[field] as string : ''
  }
  return {
    case_id: record.case_id,
    session_number: record.session_number,
    main_issue: text('presenting_problem'),
    session_summary: text('session_content'),
    counselor_intervention: text('counselor_intervention'),
    client_response: text('client_response'),
    next_plan: text('next_plan'),
    evidence_check: [],
    missing_items: [],
    warnings: ['저장된 기록을 불러왔습니다. 근거 검토 정보는 임시저장 작업에서 확인할 수 있습니다.'],
  }
}
