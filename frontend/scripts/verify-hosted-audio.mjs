import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'
const { outputText } = ts.transpileModule(fs.readFileSync('src/lib/hostedAudio.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
const { planAudioChunks, encodeWav, transcribePcmChunks } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const pcm = new Float32Array(3600 * 16000)
const chunks = planAudioChunks(pcm)
assert.equal(chunks[0].start, 0)
assert.equal(chunks.at(-1).end, 3600)
chunks.forEach((c, i) => {
  assert.ok(c.end > c.start && c.end - c.start <= 60)
  if (i) assert.equal(c.start, chunks[i - 1].end)
  assert.ok(encodeWav(pcm, c.start, c.end).length < 2000000)
})
const result = (speaker) => ({ transcription_id: 'synthetic', filename: 'chunk.wav', runtime_mode: 'real',
  status: 'completed', diarization_status: 'completed', warnings: [], transcript_text: '안 갔다. 3회기.',
  segments: [{ id: 0, start: 1, end: 5, speaker, text: '안 갔다. 3회기.' }] })
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
console.log('Hosted audio: 60-minute coverage, payload limits, speaker references, raw preservation and partial failure PASS')
