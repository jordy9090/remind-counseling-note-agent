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
      return `[${formatTimestamp(segment.start)}] ${role === 'unassigned' ? `화자 ${speakerKey}` : roleLabels[role]}: ${segment.text.trim()}`
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
  return segment.speaker || 'unknown'
}

export function getSpeakerRoleLabel(role: SpeakerRole): string {
  return roleLabels[role]
}

const unassignedSpeakerFlags = new Set(['speaker_unassigned', 'speaker_reference_unmatched'])

export function isAudioSpeakerUnassigned(segment: AudioSegment): boolean {
  return !segment.speaker?.trim() || segment.speaker === 'unknown'
    || Boolean(segment.review_flags?.some(flag => unassignedSpeakerFlags.has(flag)))
}

export function getNextUnassignedAudioSegmentId(segments: AudioSegment[], afterId: number | null): number | null {
  const start = segments.findIndex(segment => segment.id === afterId)
  for (let offset = 1; offset <= segments.length; offset++) {
    const segment = segments[(start + offset) % segments.length]
    if (isAudioSpeakerUnassigned(segment)) return segment.id
  }
  return null
}

export function selectAudioSegmentIds(
  segments: AudioSegment[], selectedIds: number[], id: number, checked: boolean, anchorId: number | null = null,
): number[] {
  const index = segments.findIndex(segment => segment.id === id)
  if (index < 0) return selectedIds
  const anchor = segments.findIndex(segment => segment.id === anchorId)
  const affected = segments.slice(Math.min(index, anchor < 0 ? index : anchor), Math.max(index, anchor) + 1)
  const selected = new Set(selectedIds)
  for (const segment of affected) {
    if (checked) selected.add(segment.id)
    else selected.delete(segment.id)
  }
  return segments.filter(segment => selected.has(segment.id)).map(segment => segment.id)
}

export function assignAudioSegmentRole(
  segments: AudioSegment[], selectedIds: number[], role: Exclude<SpeakerRole, 'unassigned'>,
  speakerRoleMap: SpeakerRoleMap = {},
): { segments: AudioSegment[]; speakerKey: string | null } {
  const selected = new Set(selectedIds)
  if (!segments.some(segment => selected.has(segment.id))) return { segments, speakerKey: null }

  // Reuse an explicitly mapped speaker without changing any other speaker's role.
  let speakerKey = Object.keys(speakerRoleMap).find(key => key.trim() && key !== 'unknown' && speakerRoleMap[key] === role)
  if (!speakerKey) {
    const occupied = new Set([...Object.keys(speakerRoleMap), ...segments.map(getSegmentSpeakerKey)])
    const base = `manual_${role}`
    speakerKey = base
    for (let suffix = 1; occupied.has(speakerKey); suffix++) speakerKey = `${base}_${suffix}`
  }
  return {
    speakerKey,
    segments: segments.map(segment => selected.has(segment.id) ? {
      ...segment, speaker: speakerKey,
      review_flags: segment.review_flags?.filter(flag => !unassignedSpeakerFlags.has(flag)),
    } : segment),
  }
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

function sourceRanges(segment: AudioSegment) {
  return segment.source_ranges || [{ start: segment.start, end: segment.end }]
}

export function mergeAudioSegments(segments: AudioSegment[], id: number): AudioSegment[] {
  const index = segments.findIndex(segment => segment.id === id)
  const first = segments[index]
  const second = segments[index + 1]
  if (!first || !second || first.speaker !== second.speaker) return segments
  const merged: AudioSegment = {
    ...first, start: Math.min(first.start, second.start), end: Math.max(first.end, second.end),
    text: `${first.text.trim()} ${second.text.trim()}`.trim(), words: [], confidence: null,
    source_ranges: [...sourceRanges(first), ...sourceRanges(second)],
    source_segment_ids: [...new Set([...(first.source_segment_ids || [first.segment_id || String(first.id)]),
      ...(second.source_segment_ids || [second.segment_id || String(second.id)])])],
    review_flags: [...new Set([...(first.review_flags || []), ...(second.review_flags || [])])],
  }
  return [...segments.slice(0, index), merged, ...segments.slice(index + 2)]
}

export function splitAudioSegment(segments: AudioSegment[], id: number, position: number, time: number): AudioSegment[] {
  const index = segments.findIndex(segment => segment.id === id)
  const segment = segments[index]
  if (!segment || !Number.isFinite(time) || time <= segment.start || time >= segment.end
    || position <= 0 || position >= segment.text.length) return segments
  const left = segment.text.slice(0, position).trim()
  const right = segment.text.slice(position).trim()
  if (!left || !right) return segments
  const nextId = Math.max(...segments.map(s => s.id)) + 1
  const common = { ...segment, words: [], confidence: null, source_ranges: sourceRanges(segment),
    source_segment_ids: segment.source_segment_ids || [segment.segment_id || String(segment.id)] }
  return [...segments.slice(0, index), { ...common, end: time, text: left },
    { ...common, id: nextId, segment_id: `edit-${nextId}`, start: time, text: right }, ...segments.slice(index + 1)]
}
