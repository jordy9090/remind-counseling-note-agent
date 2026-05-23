import axios from 'axios'
import type { NoteDraftResponse, SessionInput } from '../types/session'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 90000,
})

export const generateNoteDraft = async (input: SessionInput): Promise<NoteDraftResponse> => {
  const response = await client.post<NoteDraftResponse>('/api/notes/generate', {
    case_id: input.case_id,
    session_number: input.session_number,
    counselor_memo: input.counselor_memo,
    transcript: input.transcript_text,
    previous_summary: input.previous_session_summary,
  })
  return response.data
}

export const postGenerateNote = generateNoteDraft

export { API_BASE_URL }
export default client
