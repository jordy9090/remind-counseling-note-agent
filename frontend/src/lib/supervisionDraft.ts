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
