import type { AudioSegment, AudioTranscriptionResponse } from '../types/session'

export interface SpeakerReference { name: string; audio: string }
export interface AudioChunk { start: number; end: number }
const RATE = 16000

/** Contiguous chunks end at the quietest 100 ms window near the limit. */
export function planAudioChunks(samples: Float32Array, maxSeconds = 60): AudioChunk[] {
  const chunks: AudioChunk[] = []
  let start = 0
  while (start < samples.length) {
    let end = Math.min(samples.length, start + maxSeconds * RATE)
    if (end < samples.length) {
      let bestEnergy = Infinity
      const limit = end
      for (let i = start + Math.floor(maxSeconds * 0.75) * RATE; i + 1600 <= limit; i += 1600) {
        let energy = 0
        for (let j = i; j < i + 1600; j += 16) energy += samples[j] ** 2
        if (energy <= bestEnergy) { bestEnergy = energy; end = i + 800 }
      }
    }
    chunks.push({ start: start / RATE, end: end / RATE })
    start = end
  }
  return chunks
}

export function encodeWav(samples: Float32Array, start = 0, end = samples.length / RATE): Uint8Array {
  const first = Math.round(start * RATE), last = Math.min(samples.length, Math.round(end * RATE))
  const data = new Uint8Array(44 + (last - first) * 2)
  const view = new DataView(data.buffer)
  const label = (offset: number, value: string) => [...value].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)))
  label(0, 'RIFF'); view.setUint32(4, data.length - 8, true); label(8, 'WAVE'); label(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true)
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); label(36, 'data'); view.setUint32(40, data.length - 44, true)
  for (let i = first; i < last; i++) {
    const sample = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + (i - first) * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true)
  }
  return data
}

function referenceAudio(samples: Float32Array, start: number, end: number): string {
  const bytes = encodeWav(samples, start, end)
  let binary = ''
  for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  return `data:audio/wav;base64,${btoa(binary)}`
}

export async function transcribeHostedAudio(
  file: File,
  expectedSpeakers: number,
  send: (file: File, references: SpeakerReference[]) => Promise<AudioTranscriptionResponse>,
  onProgress?: (message: string) => void,
  stillActive: () => boolean = () => true,
): Promise<AudioTranscriptionResponse> {
  onProgress?.('음성을 준비하는 중…')
  const context = new AudioContext({ sampleRate: RATE })
  let samples: Float32Array
  try {
    const decoded = await context.decodeAudioData(await file.arrayBuffer())
    if (decoded.sampleRate !== RATE) throw new Error('이 브라우저에서는 음성 변환을 지원하지 않습니다.')
    samples = new Float32Array(decoded.length)
    for (let channel = 0; channel < decoded.numberOfChannels; channel++) {
      const data = decoded.getChannelData(channel)
      for (let i = 0; i < data.length; i++) samples[i] += data[i] / decoded.numberOfChannels
    }
  } finally { await context.close() }
  return transcribePcmChunks(samples, file.name, expectedSpeakers, send, onProgress, stillActive)
}

export async function transcribePcmChunks(
  samples: Float32Array, filename: string, expectedSpeakers: number,
  send: (file: File, references: SpeakerReference[]) => Promise<AudioTranscriptionResponse>,
  onProgress?: (message: string) => void, stillActive: () => boolean = () => true,
): Promise<AudioTranscriptionResponse> {
  const started = performance.now(), chunks = planAudioChunks(samples)
  const references: SpeakerReference[] = [], segments: AudioSegment[] = [], raw: AudioSegment[] = []
  const failed: { start: number; end: number; code: string }[] = []
  const noSpeech: { start: number; end: number; code: string }[] = []
  let last: AudioTranscriptionResponse | undefined, consecutiveFailures = 0, lastError: unknown
  let fallback = false
  for (let index = 0; index < chunks.length; index++) {
    if (!stillActive()) throw new Error('음성 처리가 취소되었습니다.')
    const chunk = chunks[index]
    onProgress?.(`축어록 생성 중 ${index + 1}/${chunks.length} 구간`)
    try {
      const audio = new File([encodeWav(samples, chunk.start, chunk.end) as BlobPart], 'chunk.wav', { type: 'audio/wav' })
      const result = await send(audio, references)
      if (result.error_codes?.includes('no_speech')) {
        noSpeech.push({ ...chunk, code: 'no_speech' })
        consecutiveFailures = 0
        continue
      }
      last = result
      for (const range of result.failed_ranges || []) {
        failed.push({ start: range.start + chunk.start, end: range.end + chunk.start, code: range.code || 'asr_failed' })
      }
      fallback ||= result.diarization_status !== 'completed'
      consecutiveFailures = 0
      const names = new Map<string, string>(references.map(ref => [ref.name, ref.name]))
      for (const speaker of new Set(result.segments.map(s => s.speaker).filter(Boolean) as string[])) {
        if (names.has(speaker)) continue
        const clean = result.segments.find(s => s.speaker === speaker && s.end - s.start >= 2.4 &&
          !s.review_flags?.some(flag => ['speaker_reference_unmatched', 'speaker_unassigned', 'low_confidence'].includes(flag)) &&
          !result.segments.some(other => other !== s && other.speaker !== speaker && other.start < s.end && other.end > s.start))
        if (clean && references.length < expectedSpeakers) {
          const name = `speaker_${references.length}`
          references.push({ name, audio: referenceAudio(samples, chunk.start + clean.start + 0.2,
            chunk.start + Math.min(clean.end - 0.2, clean.start + 4.2)) })
          names.set(speaker, name)
        } else names.set(speaker, `chunk_${index}_${speaker}`)
      }
      for (const segment of result.raw_segments || result.segments) {
        raw.push({ ...segment, id: raw.length, segment_id: `chunk_${index}_${segment.segment_id || segment.id}`,
          start: segment.start + chunk.start, end: segment.end + chunk.start,
          words: segment.words?.map(word => ({ ...word, start: word.start == null ? word.start : word.start + chunk.start,
            end: word.end == null ? word.end : word.end + chunk.start })) })
      }
      for (const segment of result.segments) {
        const speaker = segment.speaker ? names.get(segment.speaker) : undefined
        const flags = [...(segment.review_flags || [])]
        if (!speaker || speaker.startsWith('chunk_')) flags.push('speaker_reference_unmatched')
        if ((index > 0 && segment.start < 1) || (index < chunks.length - 1 && segment.end > chunk.end - chunk.start - 1)) flags.push('chunk_boundary')
        segments.push({ ...segment, id: segments.length, segment_id: `chunk_${index}_${segment.segment_id || segment.id}`,
          start: segment.start + chunk.start, end: segment.end + chunk.start, speaker,
          words: segment.words?.map(word => ({ ...word, start: word.start == null ? word.start : word.start + chunk.start,
            end: word.end == null ? word.end : word.end + chunk.start })),
          review_flags: flags, source_segment_ids: [`chunk_${index}_${segment.segment_id || segment.id}`] })
      }
    } catch (error) {
      lastError = error
      failed.push({ ...chunk, code: 'asr_failed' })
      if (++consecutiveFailures >= 2) {
        if (index + 1 < chunks.length) failed.push({ start: chunks[index + 1].start, end: samples.length / RATE, code: 'not_processed' })
        break
      }
    }
  }
  if (!last || !segments.length) throw lastError || new Error('음성에서 발화를 찾지 못했습니다.')
  return { ...last, filename, segments, raw_segments: raw, duration_seconds: samples.length / RATE,
    status: failed.length ? 'partial' : 'completed', failed_ranges: failed,
    diarization_status: fallback ? 'fallback' : 'completed',
    transcript_text: segments.map(s => s.text).join('\n'),
    review_ranges: [...noSpeech, ...segments.filter(s => s.review_flags?.length).map(s => ({ start: s.start, end: s.end, code: s.review_flags!.join(',') }))],
    warnings: [...last.warnings, '구간 경계와 화자 참조가 일치하지 않는 발화를 원음으로 확인해주세요.',
      ...(noSpeech.length ? ['발화가 감지되지 않은 구간은 원음으로 확인해주세요.'] : []),
      ...(failed.length ? ['일부 구간을 처리하지 못했습니다. 누락 구간을 확인해주세요.'] : [])],
    stage_metrics: { total_seconds: (performance.now() - started) / 1000, chunks: chunks.length },
    error_codes: [...(last.error_codes || []), ...(failed.length ? ['partial_transcription'] : [])] }
}
