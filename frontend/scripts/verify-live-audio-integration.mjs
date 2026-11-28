import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

function extract(file, variableNames, functionNames = []) {
  const source = fs.readFileSync(file, 'utf8')
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true,
    file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const parts = []
  function walk(node) {
    if (ts.isVariableDeclaration(node) && variableNames.includes(node.name.getText(ast))) {
      parts.push(`const ${node.name.getText(ast)} = ${node.initializer.getText(ast)}`)
    }
    if (ts.isFunctionDeclaration(node) && functionNames.includes(node.name?.text)) parts.push(node.getText(ast))
    ts.forEachChild(node, walk)
  }
  walk(ast)
  assert.equal(parts.length, variableNames.length + functionNames.length)
  return ts.transpileModule(parts.join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
}

const source = extract('src/api/client.ts', ['requestScope', 'getAudioCapabilities', 'transcribeLiveAudioChunk'])
const origin = 'https://synthetic-audio.invalid'
const calls = []
let reply = { runtime_mode: 'real', transcription_engine: 'clova', segments: [] }
const client = {
  async get(url, config) { calls.push({ url, config }); return { data: { provider: 'clova' } } },
  async post(url, body, config) { calls.push({ url, body, config }); return { data: reply } },
}
const api = new Function('client', 'AUDIO_API_BASE_URL', 'normalizeApiError',
  `${source}; return {getAudioCapabilities, transcribeLiveAudioChunk}`)(client, origin, error => error)
const abort = new AbortController()
await api.getAudioCapabilities({ ownerId: 'synthetic-owner', signal: abort.signal })
assert.equal(calls[0].config.expectedOwnerId, 'synthetic-owner')
assert.equal(calls[0].config.signal, abort.signal)
assert.equal(calls[0].config.baseURL, origin)
const file = new File([new Uint8Array(32044)], 'synthetic.wav', { type: 'audio/wav' })
await api.transcribeLiveAudioChunk(file, 'synthetic-owner', abort.signal)
const call = calls.at(-1)
assert.equal(call.url, '/api/audio/transcribe')
assert.equal(call.config.baseURL, origin, 'audio must use the dedicated audio origin')
assert.equal(call.config.expectedOwnerId, 'synthetic-owner', 'both auth interceptors must enforce the starting owner')
assert.equal(call.config.signal, abort.signal, 'logout/disposal must cancel the real HTTP request')
assert.equal(call.body.get('cloud_audio_consent'), 'true')
assert.equal(call.body.get('cloud_audio_provider'), 'clova')
assert.equal(call.body.get('language'), 'ko')
assert.equal(call.body.get('task'), 'transcribe')
assert.equal(call.body.get('speaker_references'), '[]')
assert.equal(call.body.get('file').size, file.size)
for (const bad of [{ runtime_mode: 'stub', transcription_engine: 'clova' },
  { runtime_mode: 'real', transcription_engine: 'openai' }]) {
  reply = bad
  await assert.rejects(api.transcribeLiveAudioChunk(file, 'synthetic-owner', abort.signal), /CLOVA/)
}

const workflowSource = fs.readFileSync('src/lib/audioTranscriptWorkflow.ts', 'utf8')
const workflow = await import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(workflowSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText).toString('base64')}`)
const handoffSource = extract('src/pages/SessionDraftPage.tsx', ['acceptLiveRecording'],
  ['buildTranscribedAudioMaterial', 'buildInitialSpeakerRoleMap'])
let materials = [{ id: 'existing-material', kind: 'document', appliedTargets: ['counselor_memo'] }]
let active = true, selected = null, modal = null
const urls = { current: new Set() }
const bindings = {
  objectUrlsRef: urls, makeMaterialId: () => 'live-synthetic',
  setMaterials: update => { materials = update(materials) },
  setLiveAudioActive: next => { active = next },
  setSelectedMaterialId: next => { selected = next }, setMaterialModal: next => { modal = next },
  refreshAudioCapabilities: async () => {},
  buildTranscriptText: workflow.buildTranscriptText, buildNonverbalNotes: workflow.buildNonverbalNotes,
  getSegmentSpeakerKey: workflow.getSegmentSpeakerKey, AUDIO_APPLY_TARGETS: ['transcript_text', 'nonverbal_notes'],
  setForm: () => { throw new Error('Unreviewed audio must not enter the note input') },
}
const accept = new Function(...Object.keys(bindings), `${handoffSource}; return acceptLiveRecording`)(...Object.values(bindings))
try {
  accept({ file, transcription: { filename: file.name, runtime_mode: 'real', transcription_engine: 'clova',
    status: 'partial', segments: [{ id: 1, segment_id: 'live_0_1', start: 0, end: 1,
      speaker: 'live_0_A', text: '합성 발화입니다.' }], transcript_text: '합성 발화입니다.',
    failed_ranges: [{ start: 1, end: 2, code: 'asr_failed' }], warnings: ['합성 미처리 구간'],
    duration_seconds: 2, nonverbal_notes: '', diarization_status: 'fallback',
  } })
  assert.equal(materials.length, 2)
  assert.equal(materials[1].id, 'existing-material', 'existing source material must survive the handoff')
  const result = materials[0]
  assert.equal(result.file, file, 'original audio remains available to the review editor')
  assert.deepEqual(result.appliedTargets, [], 'raw live transcript must never be auto-applied to an AI input')
  assert.equal(result.dirtySinceApply, true)
  assert.equal(result.speakerRoleMap.live_0_A, 'unassigned')
  assert.equal(result.failedRanges.length, 1, 'the review editor must retain the missing-audio gate')
  assert.equal(result.rawSegments[0].text, '합성 발화입니다.')
  assert.equal(modal, 'audio_review')
  assert.equal(selected, result.id)
  assert.equal(active, false)
  console.log('Live integration: owner scope, abort signal, named consent, provider guard and unreviewed handoff PASS')
} finally {
  for (const url of urls.current) URL.revokeObjectURL(url)
}
