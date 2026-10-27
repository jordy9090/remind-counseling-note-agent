import type { SessionSummaryDraft } from '../types/session'

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

  return {
    ...original,
    session_theme: {
      ...original.session_theme,
      text: editedText.session_theme ?? original.session_theme.text,
    },
    presenting_problem: {
      ...original.presenting_problem,
      text: editedText.main_issue ?? original.presenting_problem.text,
    },
    session_content: {
      ...original.session_content,
      text: editedText.session_content ?? original.session_content.text,
    },
    counselor_intervention: {
      ...original.counselor_intervention,
      text: editedText.counselor_intervention ?? original.counselor_intervention.text,
    },
    client_response: {
      ...original.client_response,
      text: editedText.client_response ?? original.client_response.text,
    },
    reflection: {
      ...original.reflection,
      text: editedText.supervision_memo ?? original.reflection.text,
    },
    next_plan: {
      ...original.next_plan,
      text: editedText.next_plan ?? original.next_plan.text,
    },
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
