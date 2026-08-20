import canonicalCase from '../../../sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json'
import candidate05SessionSummary from '../../../counselor_demo_ready/blind_comparison/문서_A_회기요약.txt?raw'
import candidate05SessionNote from '../../../counselor_demo_ready/blind_comparison/문서_A_상담일지.txt?raw'
import candidate05SupervisionReport from '../../../counselor_demo_ready/blind_comparison/문서_A_수퍼비전보고서.txt?raw'
import session1Source from '../../../counselor_demo_ready/reference_raw/session_1_source.txt?raw'
import session2Source from '../../../counselor_demo_ready/reference_raw/session_2_source.txt?raw'
import session3Source from '../../../counselor_demo_ready/reference_raw/session_3_source.txt?raw'
import session4Source from '../../../counselor_demo_ready/reference_raw/session_4_source.txt?raw'
import type { RetrievedTemplateContext, SessionInput } from '../types/session'

export type DemoDocumentType = 'session_summary' | 'session_note' | 'supervision_report'

export interface DemoEvidenceItem {
  id: string
  sourceType: 'transcript' | 'counselor_memo' | 'previous_summary' | 'ai_inference'
  sourceLabel: string
  excerpt: string
  rationale: string
  warning?: string | null
}

export interface DemoDraftSection {
  id: string
  title: string
  content: string
  status: 'connected' | 'needs_review'
  evidenceIds: string[]
  missingNotice?: string
}

export interface DemoClientInfo {
  name: string
  caseId: string
  sessionNumber: number
  sessionDate: string
  counselorName: string
  counselingGoal: string
  institution: string
  supervisor?: string
  supervisionDatePlace?: string
}

export interface DemoDocumentFixture {
  type: DemoDocumentType
  label: string
  sections: DemoDraftSection[]
}

export interface DemoHistorySession {
  sessionNumber: number
  summary: string
  rawSource: string
}

export interface DemoSessionSources {
  transcript: string
  counselorMemo: string
  history: DemoHistorySession[]
}

export interface CounselorDemoFixtureData {
  clientInfo: DemoClientInfo
  sections: DemoDraftSection[]
  documents: Record<DemoDocumentType, DemoDocumentFixture>
  sessionSources: DemoSessionSources
  evidences: Record<string, DemoEvidenceItem>
  missingItems: string[]
  warnings: string[]
  templateContext?: RetrievedTemplateContext
}

export const DEMO_DOCUMENT_ORDER: DemoDocumentType[] = [
  'session_summary',
  'session_note',
  'supervision_report',
]

export const DEMO_DOCUMENT_LABELS: Record<DemoDocumentType, string> = {
  session_summary: '회기요약',
  session_note: '상담일지',
  supervision_report: '수퍼비전 보고서',
}

const input = canonicalCase as SessionInput
const transcriptEvidence = Object.fromEntries(
  input.transcript_text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => /^(C|Cl):/.test(line))
    .map((line, index) => {
      const id = `transcript.turn_${index + 1}`
      return [
        id,
        {
          id,
          sourceType: 'transcript' as const,
          sourceLabel: `5회기 축어록 ${index + 1}번 발화`,
          excerpt: line,
          rationale: 'MusPsy CASE-MUSPSY-1416 축어록 원문',
        },
      ]
    }),
)

const evidences: Record<string, DemoEvidenceItem> = {
  counselor_memo: {
    id: 'counselor_memo',
    sourceType: 'counselor_memo',
    sourceLabel: '5회기 상담자 메모',
    excerpt: input.counselor_memo,
    rationale: 'MusPsy CASE-MUSPSY-1416 5회기 입력',
  },
  nonverbal_notes: {
    id: 'nonverbal_notes',
    sourceType: 'counselor_memo',
    sourceLabel: '5회기 비언어 관찰',
    excerpt: input.nonverbal_notes || '',
    rationale: 'MusPsy CASE-MUSPSY-1416 5회기 입력',
  },
  psychological_test_summary: {
    id: 'psychological_test_summary',
    sourceType: 'counselor_memo',
    sourceLabel: '심리검사 입력 요약',
    excerpt: input.psychological_test_summary || '',
    rationale: '비식별 데모 보조 입력이며 해석은 상담사 확인 필요',
  },
  counseling_goal: {
    id: 'counseling_goal',
    sourceType: 'counselor_memo',
    sourceLabel: '상담 목표',
    excerpt: input.counseling_goal || '',
    rationale: 'MusPsy CASE-MUSPSY-1416 5회기 입력',
  },
  previous_session_summary: {
    id: 'previous_session_summary',
    sourceType: 'previous_summary',
    sourceLabel: '1~4회기 요약',
    excerpt: input.previous_session_summary,
    rationale: 'MusPsy CASE-MUSPSY-1416 기존 회기 기록',
  },
  ...transcriptEvidence,
}

const documents: Record<DemoDocumentType, DemoDocumentFixture> = {
  session_summary: {
    type: 'session_summary',
    label: DEMO_DOCUMENT_LABELS.session_summary,
    sections: parseBracketedDocument(candidate05SessionSummary, 'summary'),
  },
  session_note: {
    type: 'session_note',
    label: DEMO_DOCUMENT_LABELS.session_note,
    sections: parseBracketedDocument(candidate05SessionNote, 'note'),
  },
  supervision_report: {
    type: 'supervision_report',
    label: DEMO_DOCUMENT_LABELS.supervision_report,
    sections: parseSupervisionDocument(candidate05SupervisionReport),
  },
}

const historySources = [session1Source, session2Source, session3Source, session4Source]
const history = parsePreviousSessionSummaries(input.previous_session_summary).map((item, index) => ({
  ...item,
  rawSource: historySources[index],
}))

export const COUNSELOR_DEMO_FIXTURE: CounselorDemoFixtureData = {
  clientInfo: {
    name: input.client_alias || input.case_id,
    caseId: input.case_id,
    sessionNumber: input.session_number,
    sessionDate: input.session_date,
    counselorName: input.counselor_name,
    counselingGoal: input.counseling_goal || '',
    institution: 'Re:mind 상담 기록 데모',
  },
  sections: documents.session_note.sections,
  documents,
  sessionSources: {
    transcript: input.transcript_text,
    counselorMemo: input.counselor_memo,
    history,
  },
  evidences,
  missingItems: ['인구학 정보', '가족관계', '이전 상담 경험', '기관 및 수퍼바이저 정보'],
  warnings: ['사전 생성된 AI 초안입니다. 제출 전 사실관계와 임상 판단을 상담사가 확인해야 합니다.'],
}

function parseBracketedDocument(raw: string, idPrefix: string): DemoDraftSection[] {
  const normalized = normalizeNewlines(raw)
  const matches = [...normalized.matchAll(/^\[([^\]]+)\]\s*$/gm)]

  return matches.map((match, index) => {
    const contentStart = (match.index || 0) + match[0].length
    const contentEnd = matches[index + 1]?.index ?? normalized.length
    const title = match[1].trim()
    const content = normalized.slice(contentStart, contentEnd).trim()

    return createSection(`${idPrefix}-${index + 1}`, title, content)
  })
}

function parseSupervisionDocument(raw: string): DemoDraftSection[] {
  const normalized = normalizeNewlines(raw)
  const matches = [...normalized.matchAll(/^([A-Z](?:-\d+)?)\.\s+(.+)$/gm)]

  return matches
    .map((match, index) => {
      const contentStart = (match.index || 0) + match[0].length
      const contentEnd = matches[index + 1]?.index ?? normalized.length
      return createSection(
        `supervision-${match[1].toLowerCase()}`,
        `${match[1]}. ${match[2].trim()}`,
        normalized.slice(contentStart, contentEnd).trim(),
      )
    })
    .filter((section) => section.content.length > 0 || /-[0-9]+\./.test(section.title))
}

function createSection(id: string, title: string, content: string): DemoDraftSection {
  return {
    id,
    title,
    content,
    status: content.includes('[상담사 확인 필요]') ? 'needs_review' : 'connected',
    evidenceIds: evidenceIdsFor(title),
  }
}

function evidenceIdsFor(title: string): string[] {
  if (/발췌 축어록/.test(title)) return Object.keys(transcriptEvidence).slice(0, 12)
  if (/이전|회기 진행/.test(title)) return ['previous_session_summary']
  if (/관찰/.test(title)) return ['nonverbal_notes']
  if (/심리검사|위험/.test(title)) return ['psychological_test_summary']
  if (/상담 목표/.test(title)) return ['counseling_goal']
  return ['counselor_memo']
}

function parsePreviousSessionSummaries(previousSummary: string): Omit<DemoHistorySession, 'rawSource'>[] {
  const normalized = normalizeNewlines(previousSummary)
  const matches = [...normalized.matchAll(/(?:^|\n\n)([1-4])회기:\s*([\s\S]*?)(?=\n\n[1-4]회기:|$)/g)]
  return matches.map((match) => ({
    sessionNumber: Number(match[1]),
    summary: match[2].trim(),
  }))
}

function normalizeNewlines(value: string): string {
  return value.replace(/\r\n/g, '\n').trim()
}
