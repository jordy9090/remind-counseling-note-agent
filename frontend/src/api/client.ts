import axios from 'axios'
import type { GenerateNoteResponse, SessionInput } from '../types/session'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 90000,
})

export const postGenerateNote = async (input: SessionInput): Promise<GenerateNoteResponse> => {
  const response = await client.post<GenerateNoteResponse>('/api/notes/generate', input)
  return response.data
}

export { API_BASE_URL }
export default client
