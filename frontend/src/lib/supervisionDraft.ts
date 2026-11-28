import type { SessionSummaryDraft, SummarySection, SupervisionReportDraft } from '../types/session'

/** Present legacy saved drafts using the reference form without dropping edited cells. */
export function normalizeSupervisionForm(report: SupervisionReportDraft): SupervisionReportDraft {
  return { ...report, sections: report.sections.map(section => ({
    ...section,
    title: section.title.replace(/^[ABC]-(\d+)\./, '$1.'),
    contentBlocks: section.contentBlocks.map(block => block.id !== 'C-1.table' ? block : ({
      ...block,
      rows: (block.rows || []).map(row => {
        if ('날짜(소요시간)' in row) return row
        if (!['회기', '상담일', '소요시간', '이전 수퍼비전'].some(key => key in row)) return row
        const value = (key: string) => {
          const text = String(row[key] || '').trim()
          return text === '[상담사 확인 필요]' ? '' : text
        }
        const present = (text: string) => text !== '' && text !== '-'
        let date = ['회기', '상담일'].map(value).filter(present).join(' ')
        if (present(value('소요시간'))) date += ` (${value('소요시간')})`
        const topic = ['회기 주제', '취소·지각·결석', '이전 수퍼비전'].map(value)
          .filter(text => present(text) && text !== '상담')
        for (const [key, text] of Object.entries(row)) {
          if (!['회기', '상담일', '소요시간', '회기 주제', '취소·지각·결석', '이전 수퍼비전'].includes(key) && text) topic.push(`${key}: ${text}`)
        }
        return { '날짜(소요시간)': date, '회기 주제': topic.join('\n') }
      }),
    })),
  })) }
}

export interface CounselorEditedSection {
  id: string
  content: string
}

/**
 * Apply the counselor's current visible draft text without discarding the
 * source metadata attached to the AI-generated summary sections.
 */
export function applyCounselorEditsToSummary(
  original: SessionSummaryDraft,
  sections: CounselorEditedSection[],
): SessionSummaryDraft {
  const editedText = Object.fromEntries(sections.map((section) => [section.id, section.content]))
  const edited = (section: SummarySection, text: string | undefined): SummarySection => (
    text === undefined || text === section.text ? { ...section }
      : { ...section, text, evidence_type: 'needs_review', requires_review: true }
  )

  return {
    ...original,
    session_theme: edited(original.session_theme, editedText.session_theme),
    presenting_problem: edited(original.presenting_problem, editedText.main_issue),
    session_content: edited(original.session_content, editedText.session_content),
    counselor_intervention: edited(original.counselor_intervention, editedText.counselor_intervention),
    client_response: edited(original.client_response, editedText.client_response),
    reflection: edited(original.reflection, editedText.supervision_memo),
    next_plan: edited(original.next_plan, editedText.next_plan),
  }
}

/**
 * Transcript labels as the supervision form numbers them: each speaker has its own count
 * ("상1", "내1", "상2", "내2", ...). Other speakers keep a plain "기타".
 */
export function transcriptTurnLabels(turns: { speaker: string }[]): string[] {
  let counselor = 0
  let client = 0
  return turns.map((turn) => {
    if (turn.speaker === 'client') return `내${++client}`
    if (turn.speaker === 'counselor') return `상${++counselor}`
    return '기타'
  })
}

/** Speaker of an edited transcript line: "내1", "내담자", "client" → client; everything else → counselor. */
export function transcriptLineSpeaker(label: string): 'client' | 'counselor' {
  const value = label.trim().toLowerCase()
  return value.startsWith('내') || value.includes('client') ? 'client' : 'counselor'
}
