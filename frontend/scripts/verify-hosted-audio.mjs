import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
const wavModule = ts.transpileModule(fs.readFileSync('src/lib/wavSource.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText
const wavUrl = `data:text/javascript;base64,${Buffer.from(wavModule).toString('base64')}`
const { openWavSource } = await import(wavUrl)
const { outputText } = ts.transpileModule(fs.readFileSync('src/lib/hostedAudio.ts', 'utf8').replace("'./wavSource'", JSON.stringify(wavUrl)), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
const { planAudioChunks, encodeWav, transcribePcmChunks, transcribeHostedAudio, AudioChunkRequestError, clearHostedAudioCheckpoint } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const duration = 7200
const pcm = new Float32Array(duration * 16000)
const chunks = planAudioChunks(pcm)
assert.equal(chunks[0].start, 0)
assert.equal(chunks.at(-1).end, duration)
chunks.forEach((c, i) => {
  assert.ok(c.end > c.start && c.end - c.start <= 60)
  if (i) assert.equal(c.start, chunks[i - 1].end)
  assert.ok(encodeWav(pcm, c.start, c.end).length < 2000000)
})
const result = (speaker) => ({ transcription_id: 'synthetic', filename: 'chunk.wav', runtime_mode: 'real',
  status: 'completed', diarization_status: 'completed', warnings: [], transcript_text: '안 갔다. 3회기.',
  segments: [{ id: 0, start: 1, end: 5, speaker, text: '안 갔다. 3회기.' }] })
let decoderClosed = false, longRequests = 0
globalThis.AudioContext = class {
  async decodeAudioData() { return { duration, length: pcm.length, sampleRate: 16000, numberOfChannels: 1, getChannelData: () => pcm } }
  async close() { decoderClosed = true }
}
const long = await transcribeHostedAudio(new File(['synthetic decoder input'], 'long.wav'), 2, async file => {
  longRequests++
  assert.ok(file.size < 2000000)
  return result('speaker_0')
})
assert.equal(long.duration_seconds, duration)
assert.equal(long.status, 'completed')
assert.equal(longRequests, chunks.length)
assert.ok(long.segments.at(-1).start > 3600)
assert.equal(decoderClosed, true)
delete globalThis.AudioContext
let requests = 0
const joined = await transcribePcmChunks(pcm.subarray(0, 120 * 16000), 'synthetic.wav', 2, async (file, refs) => {
  assert.ok(file.size < 2000000)
  if (requests++) {
    assert.equal(refs[0].name, 'speaker_0')
    assert.ok(refs[0].audio.startsWith('data:audio/wav;base64,'))
    return result('speaker_0')
  }
  return result('A')
})
assert.equal(new Set(joined.segments.map(s => s.speaker)).size, 1)
assert.ok(joined.segments[1].start > 59)
assert.equal(joined.raw_segments[0].speaker, 'A')
assert.equal(joined.segments[0].text, '안 갔다. 3회기.')
let calls = 0
const partial = await transcribePcmChunks(pcm.subarray(0, 240 * 16000), 'synthetic.wav', 2, async () => {
  if (calls++) throw new AudioChunkRequestError('synthetic timeout', true)
  return result('A')
})
assert.equal(partial.status, 'partial')
assert.equal(partial.segments.length, 1)
assert.equal(partial.failed_ranges.at(-1).end, 240)
assert.equal(calls, 4)
let silenceCalls = 0
const withSilence = await transcribePcmChunks(pcm.subarray(0, 240 * 16000), 'silence.wav', 2, async () => {
  const index = silenceCalls++
  return index === 1 || index === 2 ? { ...result('A'), segments: [], error_codes: ['no_speech'] } : result('speaker_0')
})
assert.equal(withSilence.status, 'completed')
assert.equal(withSilence.failed_ranges.length, 0)
assert.equal(withSilence.review_ranges.filter(r => r.code === 'no_speech').length, 2)
assert.ok(withSilence.segments.at(-1).start > 170)
let clovaCalls = 0
const clova = await transcribePcmChunks(pcm.subarray(0, 120 * 16000), 'clova.wav', 2, async () => {
  const index = clovaCalls++
  return { ...result(index ? 'unmatched_1' : 'clova_1'), transcription_engine: 'clova',
    status: index ? 'partial' : 'completed',
    failed_ranges: index ? [{ start: 0, end: 0.5, code: 'timestamp_unavailable' }] : [],
    segments: [{ ...result('unused').segments[0], speaker: index ? 'unmatched_1' : 'clova_1',
      review_flags: index ? ['speaker_reference_unmatched'] : [],
      words: [{start: 1, end: 2, text: '안 갔다.'}] }] }
})
assert.equal(clova.status, 'partial')
assert.equal(clova.segments[0].speaker, 'speaker_0')
assert.ok(clova.segments[1].speaker.startsWith('chunk_'))
assert.ok(clova.segments[1].words[0].start > 59)
assert.ok(clova.failed_ranges[0].start > 58)
assert.equal(clova.raw_segments[1].words[0].start, clova.segments[1].words[0].start)
console.log('Hosted audio: >60-minute decode/chunk coverage, payload limits, speaker references, raw preservation and partial failure PASS')

// A virtual 2-hour 48 kHz, stereo, 24-bit WAV is >500 MB. No full-file allocation/read is allowed.
const frames = 7200 * 48000, sourceBytes = frames * 6
const header = Buffer.alloc(44)
header.write('RIFF'); header.writeUInt32LE(36 + sourceBytes, 4); header.write('WAVEfmt ', 8)
header.writeUInt32LE(16, 16); header.writeUInt16LE(1, 20); header.writeUInt16LE(2, 22)
header.writeUInt32LE(48000, 24); header.writeUInt32LE(48000 * 6, 28)
header.writeUInt16LE(6, 32); header.writeUInt16LE(24, 34); header.write('data', 36); header.writeUInt32LE(sourceBytes, 40)
let maxRead = 0, readBytes = 0, decodeCalls = 0, streamedCalls = 0, streamClosed = false
const virtual = {
  name: 'two-hour-stereo.wav', size: 44 + sourceBytes,
  async arrayBuffer() { throw new Error('Must never read a complete long WAV') },
  slice(start, end) {
    const size = end - start
    assert.ok(size <= 61 * 48000 * 6)
    maxRead = Math.max(maxRead, size); readBytes += size
    return { async arrayBuffer() {
      const bytes = new Uint8Array(size)
      if (start < 44) bytes.set(header.subarray(start, Math.min(end, 44)))
      return bytes.buffer
    } }
  },
}
const wav = await openWavSource(virtual)
assert.equal(wav.duration, 7200)
assert.ok(virtual.size > 500 * 1024 * 1024)
await assert.rejects(wav.read(0, 62 * 48000))
globalThis.AudioContext = class {
  async decodeAudioData(buffer) {
    decodeCalls++
    const count = new DataView(buffer).getUint32(40, true) / 6 / 3
    assert.ok(count <= 61 * 16000)
    const channel = new Float32Array(count)
    return { length: count, sampleRate: 16000, numberOfChannels: 1, getChannelData: () => channel }
  }
  async close() { streamClosed = true }
}
const streamed = await transcribeHostedAudio(virtual, 2, async file => {
  streamedCalls++
  assert.ok(file.size < 2000000)
  return result(streamedCalls === 1 ? 'A' : 'speaker_0')
})
assert.equal(streamed.duration_seconds, 7200)
assert.equal(streamed.status, 'completed')
assert.equal(streamedCalls, decodeCalls)
assert.ok(streamed.segments.at(-1).start > 7140)
assert.equal(streamClosed, true)
assert.ok(maxRead <= 61 * 48000 * 6)
// Only the one-second lookahead is reread; the whole source was visited.
assert.ok(readBytes >= sourceBytes && readBytes < sourceBytes * 1.04)
assert.ok(streamed.segments.every((s, i, all) => !i || s.start > all[i - 1].end))

decodeCalls = 0; streamedCalls = 0; streamClosed = false
globalThis.AudioContext = class {
  async decodeAudioData() {
    if (decodeCalls++) throw new Error('Synthetic decoder failure')
    const channel = new Float32Array(61 * 16000)
    return { sampleRate: 16000, numberOfChannels: 1, getChannelData: () => channel }
  }
  async close() { streamClosed = true }
}
const decodePartial = await transcribeHostedAudio(virtual, 2, async () => { streamedCalls++; return result('A') })
assert.equal(decodePartial.status, 'partial')
assert.equal(decodePartial.failed_ranges.at(-1).code, 'decode_failed')
assert.equal(decodePartial.failed_ranges.at(-1).end, 7200)
assert.equal(streamedCalls, 1)
assert.equal(streamClosed, true)
delete globalThis.AudioContext

const malformed = new File([header], 'truncated.wav')
await assert.rejects(openWavSource(malformed))
console.log('Two-hour WAV: bounded 61-second reads, 2 GB stereo source, tail coverage, decoder failure retention and cleanup PASS')

// Retry the exact payload, then reuse only the contiguous successful prefix on manual resume.
const retryPcm = pcm.subarray(0, 180 * 16000)
const retryChunks = planAudioChunks(retryPcm)
let retryCalls = 0
const automatic = await transcribePcmChunks(retryPcm, 'retry.wav', 2, async () => {
  if (retryCalls++ === 1) throw new AudioChunkRequestError('Synthetic network error', true)
  return result('speaker_0')
})
assert.equal(automatic.status, 'completed')
assert.equal(retryCalls, retryChunks.length + 1)
assert.equal(automatic.segments.length, retryChunks.length)

let resumeCalls = 0, failTail = true
const retryFile = new File(['synthetic'], 'resume.m4a')
globalThis.AudioContext = class {
  async decodeAudioData() { return { sampleRate: 16000, numberOfChannels: 1, getChannelData: () => retryPcm } }
  async close() {}
}
const resumedSend = async () => {
  const call = resumeCalls++
  if (call > 0 && failTail) throw new AudioChunkRequestError('Synthetic network error', true)
  return result('speaker_0')
}
const interrupted = await transcribeHostedAudio(retryFile, 2, resumedSend, undefined, undefined, 'owner-a')
assert.equal(interrupted.status, 'partial')
assert.equal(interrupted.segments.length, 1)
assert.equal(resumeCalls, 4)
failTail = false
const resumed = await transcribeHostedAudio(retryFile, 2, resumedSend, undefined, undefined, 'owner-a')
assert.equal(resumed.status, 'completed')
assert.equal(resumeCalls, 4 + retryChunks.length - 1)
assert.deepEqual(resumed.segments[0], interrupted.segments[0])
assert.equal(resumed.segments.length, retryChunks.length)
assert.equal(new Set(resumed.segments.map(s => s.segment_id)).size, retryChunks.length)

for (const [file, speakers, scope] of [[retryFile, 2, 'owner-b'], [retryFile, 3, 'owner-b'],
  [new File(['synthetic'], 'resume.m4a'), 3, 'owner-b']]) {
  let freshCalls = 0
  await transcribeHostedAudio(file, speakers, async () => { freshCalls++; return result('speaker_0') }, undefined, undefined, scope)
  assert.equal(freshCalls, retryChunks.length, 'Different user, speaker count or File must never replay cached content')
}
clearHostedAudioCheckpoint(retryFile)
let clearedCalls = 0
await transcribeHostedAudio(retryFile, 3, async () => { clearedCalls++; return result('speaker_0') }, undefined, undefined, 'owner-b')
assert.equal(clearedCalls, retryChunks.length)
delete globalThis.AudioContext

for (const status of [401, 403, 413, 422]) {
  let deniedCalls = 0
  await assert.rejects(transcribePcmChunks(retryPcm, 'denied.wav', 2, async () => {
    deniedCalls++
    if (deniedCalls === 1) return result('speaker_0')
    throw new AudioChunkRequestError(`Synthetic ${status}`, false)
  }), /Synthetic/)
  assert.equal(deniedCalls, 2, 'Permanent errors must stop immediately, including after earlier successful chunks')
}
let active = true, cancelledCalls = 0
await assert.rejects(transcribePcmChunks(retryPcm, 'cancel.wav', 2, async () => {
  cancelledCalls++
  throw new AudioChunkRequestError('Synthetic network error', true)
}, () => { if (cancelledCalls) active = false }, () => active), /취소/)
assert.equal(cancelledCalls, 1)
console.log('Hosted recovery: bounded retry, exact prefix resume, cancellation, tenant/File/speaker isolation and permanent rejection PASS')
