import type { AudioSegment } from '../types/session'

export type SpeakerRole = 'counselor' | 'client' | 'unassigned'
export type SpeakerRoleMap = Record<string, SpeakerRole>

const roleLabels: Record<SpeakerRole, string> = {
  counselor: '상담자',
  client: '내담자',
  unassigned: '화자 미배정',
}

export function buildTranscriptText(segments: AudioSegment[], speakerRoleMap: SpeakerRoleMap = {}): string {
  return segments
    .filter((segment) => segment.text.trim())
    .map((segment) => {
      const speakerKey = getSegmentSpeakerKey(segment)
      const role = speakerRoleMap[speakerKey] || 'unassigned'
      return `[${formatTimestamp(segment.start)}] ${roleLabels[role]}: ${segment.text.trim()}`
    })
    .join('\n')
}

export function buildNonverbalNotes(segments: AudioSegment[], speakerRoleMap: SpeakerRoleMap = {}): string {
  return segments
    .map((segment) => {
      const observations = getNotableAcousticObservations(segment)
      if (!observations.length) return ''
      const speakerKey = getSegmentSpeakerKey(segment)
      const role = speakerRoleMap[speakerKey] || 'unassigned'
      return `[${formatTimestamp(segment.start)}] ${roleLabels[role]}: ${observations.join(', ')}`
    })
    .filter(Boolean)
    .join('\n')
}

export function formatTimestamp(seconds: number): string {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0
  const hours = Math.floor(safeSeconds / 3600)
  const minutes = Math.floor((safeSeconds % 3600) / 60)
  const remainingSeconds = safeSeconds % 60
  if (hours > 0) {
    return `${hours}:${minutes.toString().padStart(2, '0')}:${remainingSeconds.toString().padStart(2, '0')}`
  }
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

export function getAudioSeekTarget(segment: AudioSegment): number | null {
  return Number.isFinite(segment.start) && segment.start >= 0 ? segment.start : null
}

export function getNotableAcousticObservations(segment: AudioSegment): string[] {
  const observations: string[] = []
  if ((segment.pause_before_seconds || 0) >= 0.8) {
    observations.push(`${roundOneDecimal(segment.pause_before_seconds || 0)}초 멈춤 후 발화`)
  }
  if (segment.speech_rate_level === 'slow') {
    observations.push('느린 말속도')
  }
  if (segment.speech_rate_level === 'fast') {
    observations.push('빠른 말속도')
  }
  if (segment.volume_level === 'low') {
    observations.push('낮은 음량')
  }
  if (segment.volume_level === 'high') {
    observations.push('높은 음량')
  }
  return observations
}

export function getSegmentSpeakerKey(segment: AudioSegment): string {
  return segment.speaker || `segment_${segment.id}`
}

export function getSpeakerRoleLabel(role: SpeakerRole): string {
  return roleLabels[role]
}

export function replaceAppliedAudioBlock(current: string, previous: string, next: string): string | null {
  const currentText = current.trim()
  const previousText = previous.trim()
  const nextText = next.trim()
  if (!previousText) {
    if (!nextText) return currentText
    return currentText ? `${currentText}\n\n${nextText}` : nextText
  }

  const matches: number[] = []
  let searchFrom = 0
  while (searchFrom <= currentText.length - previousText.length) {
    const index = currentText.indexOf(previousText, searchFrom)
    if (index < 0) break
    const end = index + previousText.length
    const startsAtBoundary = index === 0 || currentText.slice(index - 2, index) === '\n\n'
    const endsAtBoundary = end === currentText.length || currentText.slice(end, end + 2) === '\n\n'
    if (startsAtBoundary && endsAtBoundary) matches.push(index)
    searchFrom = index + previousText.length
  }
  if (matches.length !== 1) return null

  const index = matches[0]
  const before = currentText.slice(0, index).trim()
  const after = currentText.slice(index + previousText.length).trim()
  return [before, nextText, after].filter(Boolean).join('\n\n')
}

function roundOneDecimal(value: number): string {
  return (Math.round(value * 10) / 10).toFixed(1)
}
