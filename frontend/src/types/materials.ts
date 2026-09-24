import type { AudioSegment } from './session'
import type { SpeakerRoleMap } from '../lib/audioTranscriptWorkflow'

export type UploadedMaterialKind = 'document' | 'audio'
export type UploadedMaterialStatus =
  | 'uploading'
  | 'completed'
  | 'warning'
  | 'selected'
  | 'transcribing'
  | 'transcribed'
  | 'failed'
export type MaterialApplyTarget =
  | 'transcript_text'
  | 'nonverbal_notes'
  | 'counselor_memo'
  | 'previous_session_summary'
  | 'psychological_test_summary'
export type MaterialApplyMode = 'append' | 'replace'
export const AUDIO_APPLY_TARGETS: MaterialApplyTarget[] = ['transcript_text', 'nonverbal_notes']

export const materialApplyTargetLabel: Record<MaterialApplyTarget, string> = {
  transcript_text: '축어록',
  nonverbal_notes: '비언어 관찰 메모',
  counselor_memo: '상담사 메모',
  previous_session_summary: '이전 회기 요약',
  psychological_test_summary: '심리검사 요약',
}

export interface UploadedMaterial {
  id: string
  kind: UploadedMaterialKind
  filename: string
  mediaType?: string
  status: UploadedMaterialStatus
  characterCount?: number
  pageCount?: number | null
  extractedText?: string
  warnings: string[]
  error?: string
  file?: File
  objectUrl?: string
  transcriptText?: string
  segments?: AudioSegment[]
  durationSeconds?: number | null
  language?: string | null
  speakerRoleMap?: SpeakerRoleMap
  runtimeMode?: 'real' | 'stub'
  diarizationStatus?: 'completed' | 'fallback' | 'disabled'
  languageProbability?: number | null
  nonverbalNotes?: string
  dirtySinceApply?: boolean
  expectedSpeakers?: number
  lastAppliedTranscriptText?: string
  lastAppliedNonverbalNotes?: string
  lastAppliedMode?: MaterialApplyMode
  requiresReattachment?: boolean
  appliedTargets: MaterialApplyTarget[]
}
