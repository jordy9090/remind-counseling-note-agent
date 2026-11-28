import { encodeWav } from './hostedAudio'
import type { AudioSegment, AudioTranscriptionResponse } from '../types/session'

export const LIVE_AUDIO_RATE = 16000
export const LIVE_CHUNK_SECONDS = 10
export const LIVE_MAX_SECONDS = 60 * 60
const MAX_QUEUED_CHUNKS = 3

export type LiveAudioState = 'idle' | 'starting' | 'recording' | 'paused' | 'finishing' | 'finished'
export interface LiveAudioSnapshot {
  state: LiveAudioState
  duration: number
  segments: AudioSegment[]
  queued: number
  failed: number
  level: number
  message: string
}
export interface LiveRecordingResult { file: File; transcription: AudioTranscriptionResponse }
export interface AudioCapture {
  pause: () => void
  resume: () => Promise<void>
  stop: () => Promise<void>
  dispose: () => void
}
type CaptureFactory = (
  onSamples: (samples: Float32Array) => void,
  onError: (message: string) => void,
  stillActive: () => boolean,
) => Promise<AudioCapture>
interface Chunk {
  index: number
  start: number
  end: number
  file: File
  status: 'pending' | 'sending' | 'completed' | 'failed'
  result?: AudioTranscriptionResponse
}
interface Options {
  send: (file: File, signal: AbortSignal) => Promise<AudioTranscriptionResponse>
  onUpdate: (snapshot: LiveAudioSnapshot) => void
  onLimit: () => void
  capture?: CaptureFactory
  persistChunk?: (index: number, pcm: Blob) => Promise<void>
  onStorageError?: () => void
}

const emptySnapshot = (): LiveAudioSnapshot => ({
  state: 'idle', duration: 0, segments: [], queued: 0, failed: 0, level: 0, message: '',
})
export const initialLiveAudioSnapshot = emptySnapshot

/** Only explicit, owner-scoped CLOVA requests leave the browser. */
export class LiveAudioRecorder {
  private snapshot = emptySnapshot()
  private capture?: AudioCapture
  private aborted = false
  private abort = new AbortController()
  private chunks: Chunk[] = []
  private projectedSegments: AudioSegment[] = []
  private pending: Float32Array[] = []
  private pendingLength = 0
  private totalFrames = 0
  private pumpPromise?: Promise<void>
  private finishPromise?: Promise<LiveRecordingResult>
  private captureIssue = ''
  private storagePromise: Promise<void> = Promise.resolve()
  private storageFailed = false
  private filename = `상담-실시간-${new Date().toISOString().replace(/[:.]/g, '-')}.wav`

  constructor(private options: Options) {}

  get recordingFilename(): string { return this.filename }

  /** Restore PCM locally; retry is the only action that sends restored chunks. */
  restore(filename: string, parts: { index: number; pcm: Blob }[]): void {
    if (this.snapshot.state !== 'idle' || this.aborted || !parts.length) return
    this.filename = filename
    for (const part of parts) {
      const frames = part.pcm.size / 2
      if (part.index !== this.chunks.length || !Number.isInteger(frames) || frames <= 0
        || frames > LIVE_CHUNK_SECONDS * LIVE_AUDIO_RATE || this.totalFrames + frames > LIVE_MAX_SECONDS * LIVE_AUDIO_RATE) {
        throw new Error('보관된 녹음 형식을 확인하지 못했습니다.')
      }
      const header = encodeWav(new Float32Array())
      const view = new DataView(header.buffer)
      view.setUint32(4, 36 + part.pcm.size, true)
      view.setUint32(40, part.pcm.size, true)
      const start = this.totalFrames / LIVE_AUDIO_RATE
      this.totalFrames += frames
      this.chunks.push({ index: part.index, start, end: this.totalFrames / LIVE_AUDIO_RATE,
        file: new File([header as BlobPart, part.pcm], `live-${part.index}.wav`, { type: 'audio/wav' }), status: 'failed' })
    }
    this.snapshot = { ...emptySnapshot(), state: 'paused', duration: this.totalFrames / LIVE_AUDIO_RATE,
      message: '원음을 복구했습니다. 전사 텍스트는 저장하지 않습니다. 실패 구간 다시 처리를 누르면 원음을 전송해 다시 전사합니다.' }
    this.emit()
  }

  async start(): Promise<void> {
    if (this.snapshot.state !== 'idle' || this.aborted) return
    this.snapshot.state = 'starting'
    this.emit()
    try {
      const capture = await (this.options.capture || captureMicrophone)(
        samples => this.acceptSamples(samples),
        message => { this.pause(message); },
        () => !this.aborted,
      )
      if (this.aborted) { capture.dispose(); return }
      this.capture = capture
      this.snapshot.state = 'recording'
      await capture.resume()
      this.emit()
    } catch (error) {
      if (this.aborted) return
      this.capture?.dispose()
      this.capture = undefined
      this.snapshot.state = 'idle'
      this.snapshot.message = error instanceof Error ? error.message : '마이크를 시작하지 못했습니다.'
      this.emit()
      throw error
    }
  }

  private acceptSamples(samples: Float32Array): void {
    if (this.aborted || !samples.length || this.snapshot.state === 'finished') return
    // Worklet messages already queued before pause/stop still belong to this recording.
    const remaining = LIVE_MAX_SECONDS * LIVE_AUDIO_RATE - this.totalFrames
    const accepted = samples.subarray(0, Math.max(0, remaining))
    let offset = 0
    while (offset < accepted.length) {
      const size = Math.min(accepted.length - offset, LIVE_CHUNK_SECONDS * LIVE_AUDIO_RATE - this.pendingLength)
      this.pending.push(accepted.slice(offset, offset + size))
      this.pendingLength += size
      this.totalFrames += size
      offset += size
      if (this.pendingLength === LIVE_CHUNK_SECONDS * LIVE_AUDIO_RATE) this.flushChunk()
    }
    this.snapshot.duration = this.totalFrames / LIVE_AUDIO_RATE
    let energy = 0
    for (let i = 0; i < accepted.length; i++) energy += accepted[i] ** 2
    this.snapshot.level = accepted.length ? Math.min(1, Math.sqrt(energy / accepted.length) * 6) : 0
    this.emit()
    if (this.totalFrames >= LIVE_MAX_SECONDS * LIVE_AUDIO_RATE && this.snapshot.state === 'recording') {
      this.pause('60분 녹음을 마쳤습니다. 마지막 구간을 처리하고 검토 화면으로 이동합니다.')
      this.options.onLimit()
    }
  }

  private pendingSamples(): Float32Array {
    const result = new Float32Array(this.pendingLength)
    let offset = 0
    for (const part of this.pending) { result.set(part, offset); offset += part.length }
    return result
  }

  private flushChunk(): void {
    if (!this.pendingLength) return
    const end = this.totalFrames / LIVE_AUDIO_RATE
    const start = end - this.pendingLength / LIVE_AUDIO_RATE
    const bytes = encodeWav(this.pendingSamples())
    const file = new File([bytes as BlobPart], `live-${this.chunks.length}.wav`, { type: 'audio/wav' })
    const index = this.chunks.length
    if (this.options.persistChunk && !this.storageFailed) {
      this.storagePromise = this.storagePromise.then(async () => {
        if (!this.storageFailed) await this.options.persistChunk!(index, file.slice(44))
      }).catch(() => { this.storageFailed = true; this.options.onStorageError?.() })
    }
    this.chunks.push({ index: this.chunks.length, start, end, file, status: 'pending' })
    this.pending = []
    this.pendingLength = 0
    if (this.queuedCount() >= MAX_QUEUED_CHUNKS && this.snapshot.state === 'recording') {
      this.pause('전사 대기 구간이 쌓여 녹음을 잠시 멈췄습니다. 처리가 끝나면 녹음을 계속해주세요.')
    }
    this.startPump()
  }

  private queuedCount(): number { return this.chunks.filter(c => c.status === 'pending' || c.status === 'sending').length }

  private startPump(): void {
    if (this.pumpPromise || this.aborted || this.chunks.some(c => c.status === 'failed')) return
    this.pumpPromise = this.pump().finally(() => { this.pumpPromise = undefined })
  }

  private async pump(): Promise<void> {
    for (;;) {
      const chunk = this.chunks.find(c => c.status === 'pending')
      if (!chunk || this.aborted) return
      chunk.status = 'sending'
      this.emit()
      try {
        const result = await this.options.send(chunk.file, this.abort.signal)
        if (this.aborted) return
        if (result.runtime_mode !== 'real' || result.transcription_engine !== 'clova') {
          throw new Error('CLOVA Speech의 실제 전사 결과를 확인하지 못했습니다. 녹음은 이 화면에 보관됩니다.')
        }
        chunk.result = result
        this.projectedSegments = this.segments()
        chunk.status = result.status === 'partial' || result.failed_ranges?.length ? 'failed' : 'completed'
        if (chunk.status === 'failed') {
          this.pause('일부 음성을 처리하지 못했습니다. 다시 처리하거나 녹음을 종료한 뒤 검토해주세요.')
          return
        }
      } catch (error) {
        if (this.aborted) return
        chunk.status = 'failed'
        this.pause(error instanceof Error ? error.message : '연결이 끊어졌습니다. 녹음된 음성은 보관되어 있습니다.')
        return
      } finally { this.emit() }
    }
  }

  pause(message = ''): void {
    if (this.aborted || this.snapshot.state === 'finished') return
    this.capture?.pause()
    if (this.snapshot.state !== 'finishing') this.snapshot.state = 'paused'
    this.snapshot.message = message
    this.snapshot.level = 0
    this.emit()
  }

  async resume(): Promise<void> {
    if (this.aborted || this.snapshot.state !== 'paused' || !this.capture) return
    if (this.chunks.some(c => c.status === 'failed')) {
      this.snapshot.message = '실패한 구간을 먼저 다시 처리해주세요. 녹음된 음성은 유지됩니다.'
      this.emit()
      return
    }
    if (this.queuedCount() >= MAX_QUEUED_CHUNKS) return
    this.snapshot.message = ''
    this.snapshot.state = 'recording'
    try { await this.capture?.resume() }
    catch { this.pause('마이크를 다시 시작하지 못했습니다. 녹음을 종료해 원음을 보관해주세요.') }
    this.emit()
  }

  async retry(): Promise<void> {
    if (this.aborted || this.snapshot.state === 'finishing' || this.snapshot.state === 'finished') return
    if (this.pumpPromise) await this.pumpPromise
    if (this.aborted) return
    for (const chunk of this.chunks) if (chunk.status === 'failed') { chunk.status = 'pending'; chunk.result = undefined }
    this.projectedSegments = this.segments()
    this.snapshot.message = '보관된 음성 구간을 다시 처리하고 있습니다.'
    this.startPump()
    this.emit()
    await this.pumpPromise
    if (!this.aborted && !this.chunks.some(c => c.status === 'failed')) {
      this.snapshot.message = '전사를 복구했습니다. 녹음을 계속하거나 종료할 수 있습니다.'
      this.emit()
    }
  }

  /** Compose immutable PCM Blob parts without allocating an hour-long Float32Array. */
  recordingFile(): File {
    const header = encodeWav(new Float32Array())
    const view = new DataView(header.buffer)
    view.setUint32(4, 36 + this.totalFrames * 2, true)
    view.setUint32(40, this.totalFrames * 2, true)
    const parts: BlobPart[] = [header as BlobPart, ...this.chunks.map(c => c.file.slice(44))]
    if (this.pendingLength) parts.push(encodeWav(this.pendingSamples()).slice(44) as BlobPart)
    return new File(parts, this.filename, { type: 'audio/wav' })
  }

  finish(): Promise<LiveRecordingResult> {
    if (this.finishPromise) return this.finishPromise
    this.finishPromise = this.finishRecording()
    return this.finishPromise
  }

  private async finishRecording(): Promise<LiveRecordingResult> {
    if (this.aborted) throw new Error('녹음 작업이 종료되었습니다.')
    this.snapshot.state = 'finishing'
    this.emit()
    try { await this.capture?.stop() }
    catch {
      this.captureIssue = '마이크 종료 응답을 확인하지 못했습니다. 마지막 발화가 빠졌을 수 있으므로 원음을 확인해주세요.'
      this.capture?.dispose()
    }
    this.capture = undefined
    if (this.aborted) throw new Error('녹음 작업이 종료되었습니다.')
    this.flushChunk()
    await this.storagePromise
    if (this.pumpPromise) await this.pumpPromise
    // A flush may have joined a pump just as its last request completed.
    if (!this.chunks.some(c => c.status === 'failed') && this.chunks.some(c => c.status === 'pending')) {
      this.startPump()
      if (this.pumpPromise) await this.pumpPromise
    }
    if (this.aborted) throw new Error('녹음 작업이 종료되었습니다.')
    if (!this.totalFrames) {
      this.snapshot.state = 'idle'
      this.snapshot.message = '녹음된 음성이 없습니다. 마이크를 확인하고 다시 시작해주세요.'
      this.emit()
      throw new Error(this.snapshot.message)
    }
    const file = this.recordingFile()
    const segments = this.projectedSegments
    const failed = this.chunks.flatMap(chunk => {
      if (chunk.status === 'completed') return []
      const ranges = chunk.result?.failed_ranges
      return ranges?.length ? ranges.map(range => ({ ...range, start: range.start + chunk.start, end: range.end + chunk.start }))
        : [{ start: chunk.start, end: chunk.end, code: chunk.status === 'failed' ? 'asr_failed' : 'not_processed' }]
    })
    if (this.captureIssue) failed.push({ start: this.chunks[this.chunks.length - 1]?.start || 0,
      end: this.totalFrames / LIVE_AUDIO_RATE, code: 'capture_interrupted' })
    const providerReviewRanges = this.chunks.flatMap(chunk => [
      ...(chunk.result?.review_ranges || []).map(range => ({ ...range, start: range.start + chunk.start, end: range.end + chunk.start })),
      ...(chunk.result?.error_codes?.includes('no_speech') ? [{ start: chunk.start, end: chunk.end, code: 'no_speech' }] : []),
    ])
    const transcription: AudioTranscriptionResponse = {
      transcription_id: `live-${Date.now()}`, filename: file.name,
      status: failed.length ? 'partial' : 'completed', runtime_mode: 'real', transcription_engine: 'clova',
      duration_seconds: this.totalFrames / LIVE_AUDIO_RATE, language: 'ko', diarization_status: 'fallback',
      segments, raw_segments: this.segments(true), transcript_text: segments.map(s => s.text).join('\n'),
      nonverbal_notes: '', failed_ranges: failed,
      review_ranges: [...providerReviewRanges, ...segments.map(s => ({ start: s.start, end: s.end, code: 'live_speaker_review' }))],
      warnings: [...new Set([...this.chunks.flatMap(chunk => chunk.result?.warnings || []),
        '실시간 전사는 10초 단위로 처리했습니다. 구간 경계의 발화와 화자 역할을 원음으로 확인해주세요.',
        ...(this.captureIssue ? [this.captureIssue] : []),
        ...(failed.length ? ['전사하지 못한 음성이 있습니다. 원음이 보관되어 있으므로 축어록 검토 화면에서 다시 처리해주세요.'] : [])])],
      error_codes: [...new Set([...this.chunks.flatMap(chunk => chunk.result?.error_codes || []),
        ...(failed.length ? ['partial_transcription'] : []), ...(this.captureIssue ? ['capture_interrupted'] : [])])],
    }
    this.snapshot.state = 'finished'
    this.snapshot.level = 0
    this.emit()
    return { file, transcription }
  }

  private segments(raw = false): AudioSegment[] {
    return this.chunks.flatMap(chunk => ((raw && chunk.result?.raw_segments?.length ? chunk.result.raw_segments : chunk.result?.segments) || []).map((segment, index) => ({
      ...segment, id: chunk.index * 10000 + index, segment_id: `live_${chunk.index}_${segment.segment_id || index}`,
      start: segment.start + chunk.start, end: segment.end + chunk.start,
      speaker: `live_${chunk.index}_${segment.speaker || `unknown_${index}`}`,
      words: segment.words?.map(word => ({ ...word,
        start: word.start == null ? word.start : word.start + chunk.start,
        end: word.end == null ? word.end : word.end + chunk.start })),
      review_flags: [...(segment.review_flags || []), 'speaker_reference_unmatched', 'live_chunk_boundary'],
      source_segment_ids: [`live_${chunk.index}_${segment.segment_id || index}`],
      source_ranges: segment.source_ranges?.map(range => ({ start: range.start + chunk.start, end: range.end + chunk.start })),
    })))
  }

  private emit(): void {
    if (this.aborted) return
    this.options.onUpdate({ ...this.snapshot, segments: this.projectedSegments, queued: this.queuedCount(),
      failed: this.chunks.filter(c => c.status === 'failed').length })
  }

  dispose(): void {
    this.aborted = true
    this.abort.abort()
    this.capture?.dispose()
    this.capture = undefined
    this.pending = []
    this.chunks = []
    this.projectedSegments = []
  }
}

/** The worklet resamples any device rate to mono 16 kHz PCM and never emits sound. */
async function captureMicrophone(
  onSamples: (samples: Float32Array) => void,
  onError: (message: string) => void,
  stillActive: () => boolean,
): Promise<AudioCapture> {
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
    throw new Error('HTTPS 연결과 마이크를 지원하는 브라우저에서 녹음해주세요.')
  }
  let stream: MediaStream
  try { stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false }) }
  catch { throw new Error('마이크 권한을 허용했는지, 다른 앱이 마이크를 사용 중인지 확인해주세요.') }
  if (!stillActive()) { stream.getTracks().forEach(track => track.stop()); throw new Error('녹음 작업이 종료되었습니다.') }
  let context: AudioContext | undefined
  let node: AudioWorkletNode | undefined
  let source: MediaStreamAudioSourceNode | undefined
  let stopped = false
  let stopResolve: (() => void) | undefined
  const dispose = () => {
    if (stopped) return
    stopped = true
    if (node) { node.port.onmessage = null; node.disconnect() }
    source?.disconnect()
    stream.getTracks().forEach(track => track.stop())
    if (context && context.state !== 'closed') void context.close().catch(() => {})
    stopResolve?.()
  }
  try {
    context = new AudioContext()
    if (!context.audioWorklet) throw new Error('이 브라우저는 실시간 녹음을 지원하지 않습니다. 최신 Chrome 또는 Safari를 사용해주세요.')
    await context.audioWorklet.addModule('/live-audio-processor.js')
    if (!stillActive()) throw new Error('녹음 작업이 종료되었습니다.')
    source = context.createMediaStreamSource(stream)
    node = new AudioWorkletNode(context, 'remind-live-audio', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] })
    node.port.onmessage = event => {
      if (stopped || !stillActive()) return
      if (event.data?.type === 'samples' && event.data.samples instanceof Float32Array) onSamples(event.data.samples)
      if (event.data?.type === 'stopped') { stopResolve?.(); stopResolve = undefined }
    }
    node.onprocessorerror = () => { if (!stopped) onError('음성 처리가 중단되었습니다. 녹음을 종료해 지금까지의 원음을 보관해주세요.') }
    source.connect(node)
    node.connect(context.destination)
    for (const track of stream.getAudioTracks()) track.onended = () => { if (!stopped) onError('마이크 연결이 끊어졌습니다. 녹음을 종료해 지금까지의 원음을 보관해주세요.') }
    context.onstatechange = () => {
      if (!stopped && context?.state === 'suspended') onError('브라우저가 마이크 처리를 멈췄습니다. 화면으로 돌아와 녹음을 계속해주세요.')
    }
    return {
      pause: () => { if (!stopped) { node!.port.postMessage({ type: 'pause' }); stream.getAudioTracks().forEach(t => { t.enabled = false }) } },
      resume: async () => {
        if (stopped) throw new Error('마이크가 종료되었습니다.')
        if (!stream.getAudioTracks().length || stream.getAudioTracks().some(track => track.readyState !== 'live')) {
          throw new Error('마이크 연결이 끊어졌습니다.')
        }
        await context!.resume()
        stream.getAudioTracks().forEach(t => { t.enabled = true })
        node!.port.postMessage({ type: 'resume' })
      },
      stop: async () => {
        if (stopped) return
        try {
          await new Promise<void>((resolve, reject) => {
            const timer = window.setTimeout(() => reject(new Error('마이크 종료 응답을 확인하지 못했습니다.')), 1500)
            stopResolve = () => { window.clearTimeout(timer); resolve() }
            node!.port.postMessage({ type: 'stop' })
          })
        } finally { dispose() }
      },
      dispose,
    }
  } catch (error) { dispose(); throw error }
}
