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
const summaryFields = ['presenting_problem', 'session_theme', 'session_content', 'counselor_intervention',
  'client_response', 'next_plan', 'psychological_test', 'risk_signal', 'reflection']

export function sectionFingerprint(sections: StoredSection[]): string {
  return JSON.stringify(sections.map(({ id, title, content, visible }) => ({ id, title, content, visible })))
}

export function confirmedPayload(original: Record<string, unknown>, sections: StoredSection[]): Record<string, unknown> {
  const payload = { ...original }
  // Only the current counselor sections may populate summary fields on reconfirmation.
  for (const field of summaryFields) delete payload[field]
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
  if (!Array.isArray(value)) return null
  if (!value.every((section) => isObject(section) && typeof section.id === 'string'
    && typeof section.title === 'string' && typeof section.content === 'string'
    && typeof section.visible === 'boolean')) return null
  return value as StoredSection[]
}

export function isConfirmedRecord(record: GeneratedNoteRecord): boolean {
  return record.confirmation_status === 'confirmed' || record.confirmation_status === 'demo_confirmed'
}

export function recordPayload(record: GeneratedNoteRecord): Record<string, unknown> {
  const payload = isConfirmedRecord(record) ? record.confirmed_json : record.draft_json
  if (!isObject(payload) || !Object.keys(payload).length) throw new Error('저장된 기록 내용이 비어 있어 복원할 수 없습니다.')
  return payload
}

export function readStoredText(payload: Record<string, unknown>, field: string): string | undefined {
  const value = payload[field]
  if (typeof value === 'string') return value
  if (isObject(value) && typeof value.text === 'string') return value.text
  if (Object.prototype.hasOwnProperty.call(payload, field)) throw new Error('저장된 항목 형식을 확인할 수 없어 복원하지 않았습니다. 현재 화면을 유지합니다.')
  const sections = payload.sections
  if (isObject(sections) && Object.prototype.hasOwnProperty.call(sections, field)) {
    if (typeof sections[field] === 'string') return sections[field] as string
    throw new Error('저장된 항목 형식을 확인할 수 없어 복원하지 않았습니다. 현재 화면을 유지합니다.')
  }
  return undefined
}

export function restoreStoredSections<T extends StoredSection>(payload: Record<string, unknown>, bases: T[], confirmed: boolean): StoredSection[] {
  if (Object.prototype.hasOwnProperty.call(payload, 'workspace_sections')) {
    const saved = readStoredSections(payload.workspace_sections)
    if (!saved) throw new Error('저장된 요약 형식을 확인할 수 없어 복원하지 않았습니다. 현재 화면을 유지합니다.')
    return saved
  }
  const sections = bases.flatMap((section) => {
    const text = readStoredText(payload, fieldMap[section.id] || section.id)
    if (text !== undefined) return [{ ...section, content: text }]
    return confirmed ? [] : [section]
  })
  // This optional section has no input-derived template when opening a note without its form.
  const psychologicalTest = readStoredText(payload, 'psychological_test')
  if (psychologicalTest !== undefined && !sections.some(section => section.id === 'psychological_test')) {
    return [...sections, { id: 'psychological_test', title: '심리검사 요약', content: psychologicalTest, visible: true }]
  }
  if (confirmed && !sections.length) throw new Error('확정본에서 복원할 요약 항목을 찾지 못했습니다. 현재 화면을 유지합니다.')
  return sections
}

export function noteFromRecord(record: GeneratedNoteRecord): NoteDraftResponse {
  const payload = recordPayload(record)
  const text = (field: string) => readStoredText(payload, field) ?? ''
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
