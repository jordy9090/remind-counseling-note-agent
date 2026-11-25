import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'

const moduleUrl = (source) => `data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText).toString('base64')}`
const wav = moduleUrl(fs.readFileSync('src/lib/wavSource.ts', 'utf8'))
const hosted = moduleUrl(fs.readFileSync('src/lib/hostedAudio.ts', 'utf8').replace("'./wavSource'", JSON.stringify(wav)))
const live = moduleUrl(fs.readFileSync('src/lib/liveAudio.ts', 'utf8').replace("'./hostedAudio'", JSON.stringify(hosted)))
const { LiveAudioRecorder, LIVE_AUDIO_RATE } = await import(live)
const tick = async () => { for (let i = 0; i < 8; i++) await Promise.resolve() }
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const reply = (text = '합성 발화 원문입니다.') => ({
  transcription_id: 'synthetic', filename: 'synthetic.wav', status: 'completed', runtime_mode: 'real',
  transcription_engine: 'clova', diarization_status: 'completed', warnings: [], nonverbal_notes: '',
  transcript_text: text, segments: [{ id: 0, start: 0, end: 1, speaker: 'A', text,
    words: [{ start: 0, end: 1, text }] }],
})

function harness(send, options = {}) {
  const snapshots = [], stats = { pauses: 0, resumes: 0, stopped: 0, disposed: 0 }
  let feed, interrupt, recorder
  const capture = async (onSamples, onError) => {
    feed = onSamples; interrupt = onError
    if (options.startGate) await options.startGate.promise
    return {
      pause: () => { stats.pauses++ },
      resume: async () => { stats.resumes++; if (options.resumeFail) throw Error('synthetic resume failure') },
      stop: async () => { stats.stopped++; if (options.tail) feed(options.tail); if (options.stopFail) throw Error('synthetic stop timeout') },
      dispose: () => { stats.disposed++ },
    }
  }
  recorder = new LiveAudioRecorder({ send, capture, onUpdate: snapshot => snapshots.push(snapshot),
    onLimit: () => { throw Error('Unexpected limit in this fixture') } })
  return { recorder, snapshots, stats, feed: samples => feed(samples), interrupt: message => interrupt(message),
    latest: () => snapshots.at(-1) }
}

// The full WAV retains every captured sample, including the final worklet flush.
{
  const lengths = []
  const fixture = harness(async file => {
    const bytes = await file.arrayBuffer()
    const header = new DataView(bytes)
    assert.equal(header.getUint32(24, true), 16000)
    lengths.push(header.getUint32(40, true) / 2)
    return reply()
  }, { tail: new Float32Array(2048).fill(0.25) })
  await fixture.recorder.start()
  fixture.feed(new Float32Array(10 * LIVE_AUDIO_RATE).fill(0.5))
  await tick()
  fixture.recorder.pause()
  assert.equal(fixture.latest().state, 'paused')
  await fixture.recorder.resume()
  fixture.feed(new Float32Array(2 * LIVE_AUDIO_RATE).fill(-0.5))
  const ending = fixture.recorder.finish()
  assert.equal(ending, fixture.recorder.finish(), 'repeated end requests share one handoff')
  const result = await ending
  assert.equal(fixture.stats.stopped, 1)
  assert.deepEqual(lengths, [160000, 34048])
  assert.equal(result.file.size, 44 + 194048 * 2)
  const bytes = new DataView(await result.file.arrayBuffer())
  assert.equal(bytes.getUint32(40, true), 194048 * 2)
  assert.equal(bytes.getInt16(44, true), Math.round(0.5 * 32767))
  assert.equal(bytes.getInt16(44 + 160000 * 2, true), -16384)
  assert.equal(bytes.getInt16(result.file.size - 2, true), Math.round(0.25 * 32767))
  assert.equal(result.transcription.segments[1].start, 10)
  assert.equal(result.transcription.segments[1].words[0].start, 10)
  assert.notEqual(result.transcription.segments[0].speaker, result.transcription.segments[1].speaker,
    'provider speaker A cannot imply a stable identity across chunks')
  assert.equal(result.transcription.status, 'completed')
  fixture.recorder.dispose()
}

// Meter/timer frames keep the transcript identity stable throughout a long session.
{
  const fixture = harness(async () => reply())
  await fixture.recorder.start()
  const empty = fixture.latest().segments
  fixture.feed(new Float32Array(LIVE_AUDIO_RATE))
  assert.equal(fixture.latest().segments, empty)
  fixture.feed(new Float32Array(9 * LIVE_AUDIO_RATE))
  await tick()
  const completed = fixture.latest().segments
  assert.notEqual(completed, empty)
  fixture.feed(new Float32Array(2048))
  assert.equal(fixture.latest().segments, completed)
  await fixture.recorder.finish()
  fixture.recorder.dispose()
}

// Slow network pauses at a bounded three-chunk backlog and retains audio for recovery.
{
  const gates = [deferred(), deferred(), deferred()]
  let calls = 0
  const fixture = harness(async () => { const index = calls++; await gates[index].promise; return reply() })
  await fixture.recorder.start()
  for (let i = 0; i < 3; i++) fixture.feed(new Float32Array(10 * LIVE_AUDIO_RATE))
  assert.equal(fixture.latest().state, 'paused')
  assert.equal(fixture.latest().queued, 3)
  assert.equal(fixture.stats.pauses, 1)
  await fixture.recorder.resume()
  assert.equal(fixture.latest().state, 'paused')
  for (const gate of gates) { gate.resolve(); await tick() }
  assert.equal(fixture.latest().queued, 0)
  await fixture.recorder.resume()
  assert.equal(fixture.latest().state, 'recording')
  const result = await fixture.recorder.finish()
  assert.equal(result.transcription.duration_seconds, 30)
  assert.equal(calls, 3)
  fixture.recorder.dispose()
}

// Retry only failed/pending chunks, preserve source audio, and never claim failed gaps complete.
{
  let fail = true, calls = 0
  const fixture = harness(async () => { calls++; if (fail) throw Error('synthetic network failure'); return reply() })
  await fixture.recorder.start()
  fixture.feed(new Float32Array(10 * LIVE_AUDIO_RATE))
  await tick()
  assert.equal(fixture.latest().failed, 1)
  assert.equal(fixture.latest().state, 'paused')
  const savedSize = fixture.recorder.recordingFile().size
  fail = false
  await fixture.recorder.retry()
  assert.equal(fixture.latest().failed, 0)
  assert.equal(calls, 2)
  assert.equal(fixture.recorder.recordingFile().size, savedSize)
  assert.equal((await fixture.recorder.finish()).transcription.status, 'completed')
  fixture.recorder.dispose()

  const failed = harness(async () => { throw Error('synthetic permanent failure') })
  await failed.recorder.start()
  failed.feed(new Float32Array(10 * LIVE_AUDIO_RATE))
  await tick()
  const partial = await failed.recorder.finish()
  assert.equal(partial.transcription.status, 'partial')
  assert.deepEqual(partial.transcription.failed_ranges, [{ start: 0, end: 10, code: 'asr_failed' }])
  assert.equal(partial.file.size, 320044)
  failed.recorder.dispose()
}

// Disposal aborts in-flight requests and late responses cannot repopulate a different login.
{
  const gate = deferred()
  let requestSignal
  const fixture = harness(async (_file, signal) => { requestSignal = signal; await gate.promise; return reply() })
  await fixture.recorder.start()
  fixture.feed(new Float32Array(10 * LIVE_AUDIO_RATE))
  fixture.recorder.dispose()
  const count = fixture.snapshots.length
  assert.equal(requestSignal.aborted, true)
  gate.resolve()
  await tick()
  assert.equal(fixture.snapshots.length, count)
  assert.equal(fixture.stats.disposed, 1)

  const startup = deferred(), delayed = harness(async () => reply(), { startGate: startup })
  const starting = delayed.recorder.start()
  delayed.recorder.dispose()
  startup.resolve()
  await starting
  assert.equal(delayed.stats.disposed, 1)
  assert.equal(delayed.stats.resumes, 0)
}

// Failed microphone resume releases tracks; missing stop ACK stays visibly partial.
{
  const rejected = harness(async () => reply(), { resumeFail: true })
  await assert.rejects(rejected.recorder.start(), /resume failure/)
  assert.equal(rejected.stats.disposed, 1)
  const stopped = harness(async () => reply(), { stopFail: true })
  await stopped.recorder.start()
  stopped.feed(new Float32Array(LIVE_AUDIO_RATE))
  const result = await stopped.recorder.finish()
  assert.equal(result.transcription.status, 'partial')
  assert.equal(result.transcription.failed_ranges.at(-1).code, 'capture_interrupted')
  assert.ok(result.transcription.warnings.some(message => message.includes('마지막 발화')))
  stopped.recorder.dispose()
}

// Stub or unexpected provider output is never represented as a real live transcript.
{
  const fixture = harness(async () => ({ ...reply(), runtime_mode: 'stub' }))
  await fixture.recorder.start()
  fixture.feed(new Float32Array(LIVE_AUDIO_RATE))
  const result = await fixture.recorder.finish()
  assert.equal(result.transcription.status, 'partial')
  assert.equal(result.transcription.segments.length, 0)
  fixture.recorder.dispose()
}

// Provider diagnostics and empty-speech review coverage survive the final handoff.
{
  let calls = 0
  const fixture = harness(async () => {
    if (calls++) return { ...reply(), segments: [], error_codes: ['no_speech'], warnings: ['합성 무발화 확인'],
      review_ranges: [{ start: 0, end: 1, code: 'provider_check' }] }
    return { ...reply(), raw_segments: [{ id: 0, start: 0, end: 1, speaker: 'A', text: '수정 전 합성 원문' }] }
  })
  await fixture.recorder.start()
  fixture.feed(new Float32Array(10 * LIVE_AUDIO_RATE))
  await tick()
  fixture.feed(new Float32Array(10 * LIVE_AUDIO_RATE))
  const result = await fixture.recorder.finish()
  assert.equal(result.transcription.raw_segments[0].text, '수정 전 합성 원문')
  assert.ok(result.transcription.warnings.includes('합성 무발화 확인'))
  assert.ok(result.transcription.error_codes.includes('no_speech'))
  assert.ok(result.transcription.review_ranges.some(range => range.code === 'no_speech' && range.start === 10 && range.end === 20))
  assert.ok(result.transcription.review_ranges.some(range => range.code === 'provider_check' && range.start === 10 && range.end === 11))
  fixture.recorder.dispose()
}

// Exercise the actual worklet: resampling across render quanta, pause, final flush, silence.
{
  let Processor
  const messages = []
  class Base {
    constructor() { this.port = { postMessage: message => messages.push(message), onmessage: null } }
  }
  vm.runInNewContext(fs.readFileSync('public/live-audio-processor.js', 'utf8'), {
    AudioWorkletProcessor: Base, sampleRate: 48000, Float32Array,
    registerProcessor: (name, value) => { assert.equal(name, 'remind-live-audio'); Processor = value },
  })
  const processor = new Processor()
  processor.port.onmessage({ data: { type: 'resume' } })
  for (let i = 0; i < 375; i++) {
    const output = new Float32Array(128).fill(1)
    processor.process([[new Float32Array(128).fill(0.5)]], [[output]])
    assert.ok(output.every(value => value === 0), 'microphone must never play through speakers')
  }
  processor.port.onmessage({ data: { type: 'pause' } })
  assert.equal(messages.filter(m => m.type === 'samples').reduce((sum, item) => sum + item.samples.length, 0), 16000)
  const pausedCount = messages.length
  processor.process([[new Float32Array(128).fill(1)]], [[new Float32Array(128)]])
  assert.equal(messages.length, pausedCount)
  processor.port.onmessage({ data: { type: 'resume' } })
  processor.process([[new Float32Array(126).fill(-0.5)]], [[new Float32Array(126)]])
  processor.port.onmessage({ data: { type: 'stop' } })
  assert.equal(messages.at(-1).type, 'stopped')
  assert.equal(messages.at(-2).samples.length, 42)
  assert.ok(messages.at(-2).samples.every(value => value === -0.5))
}

console.log('Live audio: PCM continuity, final flush, bounded queue, retry, partial recovery, owner cancellation and worklet lifecycle PASS')
