import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
const { outputText } = ts.transpileModule(fs.readFileSync('src/lib/hostedAudio.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
const { planAudioChunks, encodeWav, transcribePcmChunks, transcribeHostedAudio } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const duration = 3661
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
  if (calls++) throw new Error('synthetic timeout')
  return result('A')
})
assert.equal(partial.status, 'partial')
assert.equal(partial.segments.length, 1)
assert.equal(partial.failed_ranges.at(-1).end, 240)
assert.equal(calls, 3)
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
