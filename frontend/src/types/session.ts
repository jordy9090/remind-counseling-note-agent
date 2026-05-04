// 백엔드 스키마와 1:1 미러링
export interface SessionInput {
  case_id: string
  session_no: number
  counselor_memo: string
  transcript: string
  prev_summary?: string
}

export interface StructuredCase {
  basic_info: string
  presenting_problem: string
  goals: string
  session_content: string
  counselor_intervention: string
  client_response: string
  assessment: string
  next_plan: string
}

export interface SessionSummary {
  session_content: string
  counselor_opinion: string
  session_summary: string
  next_counseling_plan: string
}

export interface VerificationItem {
  content: string
  source: string
}

export interface VerificationReport {
  grounded: VerificationItem[]
  ungrounded: VerificationItem[]
  sensitive: VerificationItem[]
  needs_human_judgment: VerificationItem[]
}
