import axios from 'axios'
import type { SessionInput, StructuredCase, SessionSummary, VerificationReport } from '../types/session'

const client = axios.create({
  baseURL: 'http://localhost:8000',
  timeout: 60000,
})

export interface SessionDraftResponse {
  structured: StructuredCase
  summary: SessionSummary
  verification: VerificationReport
}

// 세션 드래프트 생성
export const postSessionDraft = async (input: SessionInput): Promise<SessionDraftResponse> => {
  const response = await client.post<SessionDraftResponse>('/api/notes/session-draft', input)
  return response.data
}

export default client
