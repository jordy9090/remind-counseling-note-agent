import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const sourcePath = path.resolve('src/lib/audioTranscriptWorkflow.ts')
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'remind-audio-transcript-workflow-'))
const outputPath = path.join(outputDir, 'audioTranscriptWorkflow.mjs')

const source = fs.readFileSync(sourcePath, 'utf8')
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2020,
  },
})
fs.writeFileSync(outputPath, transpiled.outputText, 'utf8')

const {
  buildNonverbalNotes,
  buildTranscriptText,
  formatTimestamp,
  getAudioSeekTarget,
  getNotableAcousticObservations,
  getSegmentSpeakerKey,
  replaceAppliedAudioBlock,
} = await import(pathToFileURL(outputPath).href)

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

const segments = [
  {
    id: 1,
    start: 1.2,
    end: 4.8,
    text: '편집된 첫 발화',
    speaker: 'speaker_1',
    pause_before_seconds: 0,
    speech_rate_level: 'typical',
    volume_level: 'typical',
  },
  {
    id: 2,
    start: 6.1,
    end: 9.3,
    text: '상담자의 반영',
    speaker: 'speaker_2',
    pause_before_seconds: 1.3,
    speech_rate_level: 'fast',
    volume_level: 'high',
  },
  {
    id: 3,
    start: 10,
    end: 13,
    text: '같은 화자 역할 적용',
    speaker: 'speaker_1',
    pause_before_seconds: 0.7,
    speech_rate_level: 'slow',
    volume_level: 'low',
  },
]
const speakerRoleMap = {
  speaker_1: 'client',
  speaker_2: 'counselor',
}

const transcript = buildTranscriptText(segments, speakerRoleMap)
assert(transcript.includes('편집된 첫 발화'), 'edited segment text must be reflected in transcript preview')
assert((transcript.match(/내담자:/g) || []).length === 2, 'speaker role change must apply to every utterance by the same speaker')
assert(transcript.includes('상담자: 상담자의 반영'), 'speaker role label must be used in transcript preview')
assert(formatTimestamp(65) === '1:05', 'timestamp formatting must preserve minute and second positions')
assert(getAudioSeekTarget(segments[0]) === 1.2, 'segment playback seek target must equal segment.start')
assert(getNotableAcousticObservations(segments[1]).includes('빠른 말속도'), 'fast speech badge must be detected')

const nonverbal = buildNonverbalNotes(segments, speakerRoleMap)
assert(nonverbal.includes('1.3초 멈춤 후 발화'), 'pause observation must be included in nonverbal notes')
assert(nonverbal.includes('낮은 음량'), 'low volume observation must be included in nonverbal notes')

const reapplied = replaceAppliedAudioBlock('상담사 메모\n\n이전 축어록', '이전 축어록', '수정된 축어록')
assert(reapplied === '상담사 메모\n\n수정된 축어록', 're-apply must replace the previous audio block')
assert(!reapplied.includes('이전 축어록'), 're-apply must not append duplicate transcript blocks')
assert(
  replaceAppliedAudioBlock('상담사 메모\n\n직접 수정한 축어록', '이전 축어록', '수정된 축어록') === null,
  're-apply must stop when the previous block was edited in the form',
)

const clientSource = fs.readFileSync(path.resolve('src/api/client.ts'), 'utf8')
assert(clientSource.includes('expectedSpeakers = 2'), 'transcribeAudio must default expectedSpeakers to 2')
assert(
  clientSource.includes("formData.append('expected_speakers', String(expectedSpeakers))"),
  'transcribeAudio must send expected_speakers multipart field',
)

const pageSource = fs.readFileSync(path.resolve('src/pages/SessionDraftPage.tsx'), 'utf8')
const pageAst = ts.createSourceFile('SessionDraftPage.tsx', pageSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const helperNames = new Set(['buildTranscribedAudioMaterial', 'buildInitialSpeakerRoleMap', 'mergeMaterialText'])
const callbackParts = []
function findTranscriptionCallback(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(pageAst) === 'transcribeAudioMaterial') {
    callbackParts.push(`const transcribeAudioMaterial = ${node.initializer.getText(pageAst)}`)
  }
  if (ts.isFunctionDeclaration(node) && helperNames.has(node.name?.text)) callbackParts.push(node.getText(pageAst))
  ts.forEachChild(node, findTranscriptionCallback)
}
findTranscriptionCallback(pageAst)
assert(callbackParts.length === 4, 'transcription callback and its current projection helpers must be found')
const callbackJs = ts.transpileModule(callbackParts.join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2020 },
}).outputText
const makeTranscribe = new Function('materials', 'setMaterials', 'setForm', 'setDraftSaveMessage', 'transcribeAudio', 'buildTranscriptText', 'buildNonverbalNotes', 'getSegmentSpeakerKey', 'AUDIO_APPLY_TARGETS', 'objectUrlsRef', 'materialsRef', `${callbackJs}; return transcribeAudioMaterial`)
for (const deferred of [false, true]) {
  for (const initialUpload of [false, true]) {
    const syntheticFile = { name: 'synthetic.wav' }
    const initialMaterial = { id: 'audio-queued', kind: 'audio', status: 'selected', file: syntheticFile, objectUrl: 'blob:synthetic-audio', appliedTargets: [], speakerRoleMap: { SPEAKER_00: 'client' } }
    let storedMaterials = [initialMaterial]
    let form = { transcript_text: 'Synthetic existing document', nonverbal_notes: 'Synthetic existing observation' }
    const queuedUpdates = []
    const setMaterials = (update) => {
      if (deferred) queuedUpdates.push(update)
      else storedMaterials = update(storedMaterials)
    }
    const transcription = {
      segments: [{ id: 1, start: 0, end: 2, speaker: 'SPEAKER_00', text: 'Synthetic audio sentence' }],
      transcript_text: 'Synthetic fallback', nonverbal_notes: 'Synthetic acoustic observation', warnings: [],
    }
    let requestCount = 0
    const invoke = makeTranscribe(
      initialUpload ? [] : [initialMaterial], setMaterials, (update) => { form = update(form) }, () => {},
      async (file) => { assert(file === syntheticFile, 'transcription must use the selected file'); requestCount += 1; return transcription },
      buildTranscriptText, buildNonverbalNotes, getSegmentSpeakerKey, ['transcript_text', 'nonverbal_notes'],
      { current: new Set([initialMaterial.objectUrl]) }, { current: storedMaterials },
    )
    await invoke(initialMaterial.id, initialUpload ? syntheticFile : undefined, undefined, initialUpload ? initialMaterial.objectUrl : undefined)
    for (const update of queuedUpdates) {
      // React may invoke updater functions twice; discarded evaluation must not apply text again.
      update(storedMaterials)
      storedMaterials = update(storedMaterials)
    }
    assert(requestCount === 1, 'transcription must make one API call')
    assert(form.transcript_text.startsWith('Synthetic existing document'), 'transcription must preserve existing document input')
    assert(form.transcript_text.includes('Synthetic audio sentence'), `audio must reach session input with deferred=${deferred}, initialUpload=${initialUpload}`)
    assert(form.transcript_text.split('Synthetic audio sentence').length === 2, 'updater replay must not duplicate audio input')
    assert(form.nonverbal_notes.includes('Synthetic existing observation') && form.nonverbal_notes.includes('Synthetic acoustic observation'), 'acoustic input must preserve existing observations and apply transcription')
    assert(storedMaterials[0].appliedTargets.includes('transcript_text'), 'material must record successful application')
    assert(form.transcript_text.includes(storedMaterials[0].lastAppliedTranscriptText), 'saved applied block must match actual session input')
    assert(storedMaterials[0].dirtySinceApply === false, 'successfully applied audio must be clean')
  }
}
for (const transition of ['delete', 'new-workspace', 'restored-workspace', 'restored-error', 'speaker-edit']) {
  const material = { id: 'audio-pending', kind: 'audio', status: 'selected', file: {}, objectUrl: 'blob:synthetic-pending', appliedTargets: [], speakerRoleMap: { SPEAKER_00: 'client' } }
  const materialsRef = { current: [material] }
  const objectUrlsRef = { current: new Set([material.objectUrl]) }
  let form = { case_id: 'synthetic-initial', transcript_text: 'Synthetic current input', nonverbal_notes: '' }
  let finish
  let fail
  const response = new Promise((resolve, reject) => { finish = resolve; fail = reject })
  const invoke = makeTranscribe([material], (update) => { materialsRef.current = update(materialsRef.current) },
    (update) => { form = update(form) }, () => {}, async () => response,
    buildTranscriptText, buildNonverbalNotes, getSegmentSpeakerKey, ['transcript_text', 'nonverbal_notes'], objectUrlsRef, materialsRef)
  const pending = invoke(material.id)
  if (transition === 'speaker-edit') {
    materialsRef.current = [{ ...materialsRef.current[0], speakerRoleMap: { SPEAKER_00: 'counselor' } }]
  } else {
    objectUrlsRef.current.delete(material.objectUrl)
    materialsRef.current = transition.startsWith('restored-') ? [{ ...material, objectUrl: undefined, file: undefined, requiresReattachment: true }] : []
    form = { case_id: 'synthetic-next', transcript_text: 'Synthetic replacement input', nonverbal_notes: '' }
  }
  const before = JSON.stringify(form)
  const beforeMaterials = JSON.stringify(materialsRef.current)
  if (transition === 'restored-error') fail(new Error('Synthetic delayed transcription failure'))
  else finish({ segments: [{ id: 1, start: 0, end: 2, speaker: 'SPEAKER_00', text: 'SYNTHETIC-PENDING-AUDIO' }], transcript_text: '', nonverbal_notes: '', warnings: [] })
  await pending
  if (transition === 'speaker-edit') {
    assert(form.transcript_text.includes('상담자: SYNTHETIC-PENDING-AUDIO'), 'completion must use the latest speaker role')
    assert(materialsRef.current[0].speakerRoleMap.SPEAKER_00 === 'counselor', 'completion must preserve updated speaker role')
  } else {
    assert(JSON.stringify(form) === before, `pending audio must not enter replacement input after ${transition}`)
    assert(JSON.stringify(materialsRef.current) === beforeMaterials, `pending response must not change replacement material after ${transition}`)
  }
}
assert(pageSource.includes('applyAudioTranscriptToForm'), 'audio must use a dedicated atomic apply function')
assert(pageSource.includes('transcript_text: nextTranscriptText'), 'audio apply must update transcript_text')
assert(pageSource.includes('nonverbal_notes: nextNonverbalNotes'), 'audio apply must update nonverbal_notes')
assert(pageSource.includes("...AUDIO_APPLY_TARGETS"), 'audio apply must mark transcript and nonverbal targets together')
assert(pageSource.includes('dirtySinceApply: true'), 'audio edits and re-runs must mark material stale')
assert(pageSource.includes('lastAppliedTranscriptText'), 'audio re-apply must remember the previous transcript block')
assert(pageSource.includes('lastAppliedNonverbalNotes'), 'audio re-apply must remember the previous acoustic block')
assert(pageSource.includes('lastAppliedMode'), 'audio re-apply must remember the original apply mode')
assert(pageSource.includes('replaceAppliedAudioBlock'), 'audio re-apply must replace the previous block safely')
assert(pageSource.includes('축어록 수정사항이 회기 입력에 아직 다시 반영되지 않았습니다.'), 'stale audio warning must be visible')
assert(!pageSource.includes('file: undefined'), 'audio File reference must be kept after transcription success')
assert(pageSource.includes('URL.revokeObjectURL'), 'object URLs must be revoked on delete and unmount')
assert(!pageSource.includes('onUpdateAudioTranscript'), 'full transcript textarea must not be the editable source of truth')

const editorSource = fs.readFileSync(path.resolve('src/components/audio/AudioTranscriptEditor.tsx'), 'utf8')
assert(editorSource.includes('useRef<HTMLAudioElement | null>(null)'), 'audio editor must keep an audio ref')
assert(editorSource.includes('currentTime = seekTarget'), 'segment play must seek to the segment start')
assert(editorSource.includes('readOnly'), 'full transcript preview must be read-only')
assert(editorSource.includes('onUpdateSpeakerRole'), 'speaker role edits must be wired through the editor')

fs.rmSync(outputDir, { recursive: true, force: true })
console.log('audio transcript workflow verification passed')
