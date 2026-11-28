import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import * as jsxRuntime from 'react/jsx-runtime'

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

const workflow = await import(pathToFileURL(outputPath).href)
const {
  assignAudioSegmentRole,
  buildNonverbalNotes,
  buildTranscriptText,
  formatTimestamp,
  getAudioSeekTarget,
  getNotableAcousticObservations,
  getSegmentSpeakerKey,
  getNextUnassignedAudioSegmentId,
  isAudioSpeakerUnassigned,
  replaceAppliedAudioBlock,
  mergeAudioSegments,
  splitAudioSegment,
  selectAudioSegmentIds,
} = workflow

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

// Nonconsecutive IDs ensure selection follows displayed order, including after edits.
const liveFixture = Array.from({ length: 40 }, (_, index) => ({
  id: index * 3 + 7, segment_id: `synthetic-live-${index}`, start: index * 10, end: index * 10 + 9,
  speaker: null, text: `합성 실시간 발화 ${index + 1}`, volume_level: 'low',
  review_flags: ['speaker_unassigned', 'speaker_reference_unmatched', 'live_chunk_boundary', 'low_confidence'],
}))
const liveBefore = JSON.stringify(liveFixture)
assert(liveFixture.filter(isAudioSpeakerUnassigned).length === 40, 'all 40 live rows need speaker assignment')
for (const speaker of [null, undefined, '', ' ', 'unknown']) {
  assert(isAudioSpeakerUnassigned({ speaker }), 'missing and unknown speakers need review without flags')
}
for (const flag of ['speaker_unassigned', 'speaker_reference_unmatched']) {
  assert(isAudioSpeakerUnassigned({ speaker: 'chunk_1_A', review_flags: [flag] }), 'flagged chunk speakers still need review')
}
assert(!isAudioSpeakerUnassigned({ speaker: 'speaker_1', review_flags: ['low_confidence'] }), 'unrelated warnings do not count as unassigned speakers')
const allAssigned = assignAudioSegmentRole(liveFixture, liveFixture.map(segment => segment.id), 'counselor')
const assignedRoles = { [allAssigned.speakerKey]: 'counselor' }
assert(allAssigned.segments.every(segment => !isAudioSpeakerUnassigned(segment)), 'assign all resolves every missing speaker')
assert((buildTranscriptText(allAssigned.segments, assignedRoles).match(/상담자:/g) || []).length === 40, 'all 40 rows receive the counselor role')
assert(allAssigned.segments.every(segment => segment.review_flags.join(',') === 'live_chunk_boundary,low_confidence'), 'assignment preserves unrelated review warnings')
assert(JSON.stringify(liveFixture) === liveBefore, 'bulk assignment must not mutate the original ASR fixture')
const rangeIds = selectAudioSegmentIds(liveFixture, [liveFixture[9].id], liveFixture[19].id, true, liveFixture[9].id)
assert(rangeIds.length === 11, 'Shift+click selects the inclusive forward range')
const reverseIds = selectAudioSegmentIds(liveFixture, [liveFixture[19].id], liveFixture[9].id, true, liveFixture[19].id)
assert(JSON.stringify(reverseIds) === JSON.stringify(rangeIds), 'backward ranges use the same display order')
assert(selectAudioSegmentIds(liveFixture, rangeIds, liveFixture[19].id, false, liveFixture[9].id).length === 0, 'Shift+click can deselect a range')
assert(selectAudioSegmentIds(liveFixture, [], liveFixture[9].id, true, -1).length === 1, 'a missing anchor selects only the clicked row')
const rangeAssigned = assignAudioSegmentRole(allAssigned.segments, rangeIds, 'client', assignedRoles)
assert(rangeAssigned.segments.filter(segment => segment.speaker === rangeAssigned.speakerKey).length === 11, 'only the selected range gets the client role')
assert(rangeAssigned.segments[0] === allAssigned.segments[0], 'unselected rows retain identity and contents')
const uploadedRoles = { speaker_1: 'client', speaker_2: 'counselor' }
const uploadedAssignment = assignAudioSegmentRole(segments, [segments[0].id], 'counselor', uploadedRoles)
assert(uploadedAssignment.speakerKey === 'speaker_2' && uploadedAssignment.segments[2] === segments[2], 'uploaded audio reuses the mapped role without reassigning other rows sharing the old speaker')
const collision = assignAudioSegmentRole([{ ...liveFixture[0], speaker: 'manual_client_1' }], [liveFixture[0].id], 'client', { manual_client: 'counselor' })
assert(collision.speakerKey === 'manual_client_2', 'manual keys must not collide with existing speakers or role mappings')
assert(assignAudioSegmentRole(liveFixture, [], 'client').segments === liveFixture, 'empty selection is a no-op')
assert(assignAudioSegmentRole(liveFixture, [-1], 'client').speakerKey === null, 'removed row IDs cannot cause assignment')
const partlyAssigned = assignAudioSegmentRole(liveFixture, rangeIds, 'client').segments
assert(getNextUnassignedAudioSegmentId(partlyAssigned, liveFixture[8].id) === liveFixture[20].id, 'navigation skips assigned rows')
assert(getNextUnassignedAudioSegmentId(partlyAssigned, liveFixture[39].id) === liveFixture[0].id, 'navigation wraps to the first unresolved row')
assert(getNextUnassignedAudioSegmentId(allAssigned.segments, null) === null, 'fully assigned transcripts have no navigation target')
assert(getNextUnassignedAudioSegmentId([], null) === null, 'empty transcripts have no navigation target')

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
    assert(!form.transcript_text.includes('Synthetic audio sentence'), 'unreviewed ASR must never enter summary input')
    assert(form.nonverbal_notes === 'Synthetic existing observation', 'unreviewed audio must not change observations')
    assert(!storedMaterials[0].appliedTargets.includes('transcript_text'), 'new ASR must remain unapplied')
    assert(storedMaterials[0].rawSegments[0].text === 'Synthetic audio sentence', 'raw ASR must be retained separately')
    assert(storedMaterials[0].dirtySinceApply === true, 'new ASR requires counselor review')
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
    assert(!form.transcript_text.includes('SYNTHETIC-PENDING-AUDIO'), 'completion must still wait for review')
    assert(materialsRef.current[0].transcriptText.includes('상담자: SYNTHETIC-PENDING-AUDIO'), 'review projection uses latest role')
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

const editable = [
  { id: 1, segment_id: 'a', start: 1.2, end: 4.5, speaker: 'speaker_0', text: '안 갔다. 네.' },
  { id: 2, segment_id: 'b', start: 5, end: 8, speaker: 'speaker_0', text: '12회입니다.' },
]
const beforeEdit = JSON.stringify(editable)
const split = splitAudioSegment(editable, 1, 6, 3)
assert(split.length === 3 && split[0].start === 1.2 && split[1].end === 4.5, 'split preserves outer timestamps')
assert(split[0].end === 3 && split[1].start === 3, 'split uses explicit user time')
assert(split[0].source_ranges[0].end === 4.5 && split[1].source_ranges[0].start === 1.2, 'original timestamps survive split')
assert(splitAudioSegment(editable, 1, 6, 8) === editable, 'invalid split time cannot change transcript')
const merged = mergeAudioSegments(editable, 1)
assert(merged.length === 1 && merged[0].text === '안 갔다. 네. 12회입니다.', 'merge must preserve negation and numbers')
assert(merged[0].start === 1.2 && merged[0].end === 8 && merged[0].source_ranges.length === 2, 'merge keeps source ranges')
assert(JSON.stringify(editable) === beforeEdit, 'edits cannot mutate original ASR data')
assert(mergeAudioSegments([editable[0], { ...editable[1], speaker: 'speaker_1' }], 1).length === 2, 'different speaker merge requires explicit reassignment')
assert(pageSource.includes('sourceText !== currentText'), 'stale privacy review cannot be applied')
assert(editorSource.includes('confirmedReviewKey === reviewKey'), 'privacy confirmation is bound to exact text, speakers and timestamps')
assert(clientSource.includes("import { API_BASE_URL, AUDIO_API_BASE_URL } from '../lib/apiOrigin'")
  && clientSource.includes('baseURL: AUDIO_API_BASE_URL'), 'audio uses the validated self-hosted origin')

// Execute the actual page callback: only the reviewed masked text may reach the
// summary form, and an obsolete review must not overwrite a later correction.
let applyNode
function findApply(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(pageAst) === 'applyAudioTranscriptToForm') applyNode = node
  ts.forEachChild(node, findApply)
}
findApply(pageAst)
assert(applyNode, 'reviewed apply callback must exist')
const applyJs = ts.transpileModule(`const apply = ${applyNode.initializer.getText(pageAst)}`, {
  compilerOptions: { target: ts.ScriptTarget.ES2020 },
}).outputText
const mergeTextNode = pageAst.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'mergeMaterialText')
assert(mergeTextNode, 'actual material merge helper must exist')
const mergeTextJs = ts.transpileModule(mergeTextNode.getText(pageAst), {
  compilerOptions: { target: ts.ScriptTarget.ES2020 },
}).outputText
const mergeText = new Function(`${mergeTextJs}; return mergeMaterialText`)()
let appliedMaterials = [{ id: 'reviewed', kind: 'audio', segments: editable, speakerRoleMap: { speaker_0: 'client' }, appliedTargets: [], dirtySinceApply: true }]
let appliedForm = { transcript_text: '상담사 메모', nonverbal_notes: '' }
const invokeApply = () => new Function('materials', 'form', 'buildTranscriptText', 'buildNonverbalNotes', 'replaceAppliedAudioBlock',
  'mergeMaterialText', 'setForm', 'setMaterials', 'setMaterialModal', 'AUDIO_APPLY_TARGETS', `${applyJs}; return apply`)(
  appliedMaterials, appliedForm, buildTranscriptText, buildNonverbalNotes, replaceAppliedAudioBlock, mergeText,
  update => { appliedForm = update(appliedForm) }, update => { appliedMaterials = update(appliedMaterials) }, () => {}, ['transcript_text', 'nonverbal_notes'])
const reviewedSource = buildTranscriptText(editable, { speaker_0: 'client' })
invokeApply()('reviewed', 'append', '내담자: [이름]에게 안 갔다. 12회입니다.', 'obsolete source')
assert(appliedForm.transcript_text === '상담사 메모', 'stale review must be rejected by the actual callback')
invokeApply()('reviewed', 'append', '내담자: [이름]에게 안 갔다. 12회입니다.', reviewedSource)
assert(appliedForm.transcript_text === '상담사 메모\n\n내담자: [이름]에게 안 갔다. 12회입니다.', 'only the counselor-reviewed masked text is summary input')
assert(appliedMaterials[0].dirtySinceApply === false, 'reviewed application clears the pending review marker')

// A second privacy review changes no ASR turn or role, so the material stays clean.
// It must still replace its prior block and preserve independently entered content.
for (const initialMode of ['append', 'replace']) {
  const reviewSegments = editable.map((segment, index) => index === 0 ? { ...segment, volume_level: 'low' } : segment)
  appliedMaterials = [{ id: 'reviewed', kind: 'audio', segments: reviewSegments,
    speakerRoleMap: { speaker_0: 'client' }, appliedTargets: [], dirtySinceApply: true }]
  appliedForm = { transcript_text: 'Synthetic existing memo', nonverbal_notes: 'Synthetic existing observation' }
  const sourceText = buildTranscriptText(reviewSegments, { speaker_0: 'client' })
  invokeApply()('reviewed', initialMode, 'Synthetic unmasked name', sourceText)
  assert(appliedMaterials[0].dirtySinceApply === false, 'initial review leaves no pending ASR edits')
  assert(appliedForm.transcript_text.includes('Synthetic existing memo') === (initialMode === 'append'), 'initial apply must honor append/replace mode')
  appliedForm = { ...appliedForm, transcript_text: `Synthetic prefix\n\n${appliedForm.transcript_text}\n\nSynthetic suffix` }
  const observations = appliedForm.nonverbal_notes
  const correctionMode = initialMode === 'append' ? 'replace' : 'append'
  invokeApply()('reviewed', correctionMode, 'Synthetic [PERSON]', sourceText)
  const expected = ['Synthetic prefix', ...(initialMode === 'append' ? ['Synthetic existing memo'] : []), 'Synthetic [PERSON]', 'Synthetic suffix'].join('\n\n')
  assert(appliedForm.transcript_text === expected, 'privacy-only reapplication must remove the unmasked prior block and preserve unrelated text')
  assert(appliedForm.nonverbal_notes === observations, 'privacy-only reapplication must not duplicate acoustic observations')
  assert(appliedMaterials[0].lastAppliedTranscriptText === 'Synthetic [PERSON]', 'the revised masked block becomes the next replacement baseline')
  assert(appliedMaterials[0].lastAppliedMode === initialMode, 'reapplication retains the original apply mode')
  const stableForm = structuredClone(appliedForm)
  invokeApply()('reviewed', correctionMode, 'Synthetic [PERSON]', sourceText)
  assert(JSON.stringify(appliedForm) === JSON.stringify(stableForm), 'repeating the same reviewed application is idempotent')

  const stableMaterials = structuredClone(appliedMaterials)
  for (const conflict of ['edited', 'missing', 'ambiguous', 'observation-edited']) {
    appliedForm = structuredClone(stableForm)
    appliedMaterials = structuredClone(stableMaterials)
    if (conflict === 'edited') appliedForm.transcript_text = appliedForm.transcript_text.replace('Synthetic [PERSON]', 'Synthetic independent correction')
    if (conflict === 'missing') appliedForm.transcript_text = 'Synthetic unrelated replacement'
    if (conflict === 'ambiguous') appliedForm.transcript_text += '\n\nSynthetic [PERSON]'
    if (conflict === 'observation-edited') appliedForm.nonverbal_notes = 'Synthetic independent observation'
    const beforeConflict = JSON.stringify(appliedForm)
    invokeApply()('reviewed', correctionMode, 'Synthetic [PERSON-2]', sourceText)
    assert(JSON.stringify(appliedForm) === beforeConflict, `${conflict}: rejection must preserve both form fields atomically`)
    assert(Boolean(appliedMaterials[0].error), `${conflict}: rejection must explain the conflict`)
    assert(appliedMaterials[0].lastAppliedTranscriptText === 'Synthetic [PERSON]', `${conflict}: rejection must preserve the prior replacement baseline`)
  }
}

const editorAst = ts.createSourceFile('AudioTranscriptEditor.tsx', editorSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const gateExpressions = {}
function collectGates(node) {
  if (ts.isVariableDeclaration(node) && ['reviewKey', 'hasIncompleteAudio', 'canEditTranscript', 'canApply', 'preparePrivacyReview'].includes(node.name.getText(editorAst))) {
    gateExpressions[node.name.getText(editorAst)] = node.initializer.getText(editorAst)
  }
  ts.forEachChild(node, collectGates)
}
collectGates(editorAst)
const keyFor = new Function('material', 'segments', 'speakerRoleMap', `return ${gateExpressions.reviewKey}`)
const editGates = `const hasIncompleteAudio = ${gateExpressions.hasIncompleteAudio}; const canEditTranscript = ${gateExpressions.canEditTranscript};`
const gateFor = new Function('material', 'privacy', 'reviewKey', 'confirmedReviewKey', `${editGates} return ${gateExpressions.canApply}`)
const material = { id: 'gate', status: 'transcribed' }
const key = keyFor(material, editable, {})
const privacy = { key, text: '검토할 텍스트' }
assert(!gateFor(material, privacy, key, null), 'a PII proposal alone does not permit application')
assert(gateFor(material, privacy, key, key), 'explicit confirmation of current revision permits application')
for (const changed of [{ ...editable[0], text: '갔다' }, { ...editable[0], speaker: 'speaker_1' }, { ...editable[0], end: 4.2 }]) {
  assert(!gateFor(material, privacy, keyFor(material, [changed, editable[1]], {}), key), 'text, speaker, or time edits invalidate prior confirmation')
}
assert(!gateFor(material, privacy, keyFor(material, editable, { speaker_0: 'counselor' }), key), 'global role assignment invalidates confirmation')
assert(!gateFor(material, privacy, keyFor({ ...material, reviewRanges: [{ start: 2, end: 3 }] }, editable, {}), key), 'new omission candidates invalidate confirmation')

// Even a matching privacy confirmation cannot permit a partial transcript.
const partialMaterial = { ...material, failedRanges: [{ start: 60, end: 3600, code: 'not_processed' }] }
const partialKey = keyFor(partialMaterial, editable, {})
assert(!gateFor(partialMaterial, { key: partialKey, text: 'Synthetic partial transcript' }, partialKey, partialKey), 'failed audio ranges must block summary application')
assert(!gateFor({ ...material, status: 'transcribing' }, privacy, key, key), 'retry in progress must block summary application')
let partialPrivacyCalls = 0
const privacyAction = new Function('material', 'reviewAudioPrivacy', 'setPrivacyBusy', 'setPrivacyError', 'setConfirmedReviewKey', 'setPrivacy', 'transcriptPreview', 'reviewKey',
  `${editGates} return ${gateExpressions.preparePrivacyReview}`)(partialMaterial, () => { partialPrivacyCalls++; return { text: 'Synthetic', candidates: [] } },
  () => {}, () => {}, () => {}, () => {}, 'Synthetic partial transcript', partialKey)
await privacyAction()
assert(partialPrivacyCalls === 0, 'incomplete audio must not reach privacy or summary preparation')

// Execute the actual upload consent callbacks; no file may be sent before approval.
const inputSource = fs.readFileSync(path.resolve('src/components/session-input/SessionInputPage.tsx'), 'utf8')
const inputAst = ts.createSourceFile('SessionInputPage.tsx', inputSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const consentCallbacks = {}
function collectConsent(node) {
  if (ts.isVariableDeclaration(node) && ['upload', 'resolveAudioConsent'].includes(node.name.getText(inputAst))) {
    consentCallbacks[node.name.getText(inputAst)] = node.initializer.getText(inputAst)
  }
  ts.forEachChild(node, collectConsent)
}
collectConsent(inputAst)
let pendingFiles = null
let uploadCalls = []
const consentJs = ts.transpileModule(Object.entries(consentCallbacks).map(([name, body]) => `const ${name} = ${body}`).join('\n'), {
  compilerOptions: { target: ts.ScriptTarget.ES2020 },
}).outputText
const consentActions = (liveActive = false) => new Function('pendingAudioFiles', 'setPendingAudioFiles', 'onUploadFiles', 'AUDIO_EXTENSION', 'toFileList', 'liveActive',
  `${consentJs}; return {upload, resolveAudioConsent}`)(pendingFiles, value => { pendingFiles = value },
  (files, approved) => uploadCalls.push({ files, approved }), /\.(mp3|m4a|wav)$/i, files => files, liveActive)
const syntheticAudio = { name: 'synthetic.wav' }
const syntheticText = { name: 'synthetic.txt' }
consentActions(true).upload([syntheticAudio, syntheticText])
assert(uploadCalls.length === 0 && pendingFiles === null, 'active live capture must block overlapping file selection and upload')
consentActions().upload([syntheticAudio])
assert(uploadCalls.length === 0 && pendingFiles[0] === syntheticAudio, 'selection must wait for explicit consent')
consentActions().resolveAudioConsent(false)
assert(uploadCalls.length === 0 && pendingFiles === null, 'cancel must discard the pending audio without upload')
consentActions().upload([syntheticAudio, syntheticText])
consentActions().resolveAudioConsent(false)
assert(uploadCalls.length === 1 && uploadCalls[0].files[0] === syntheticText && !uploadCalls[0].approved, 'declining audio must preserve non-audio uploads')
uploadCalls = []
consentActions().upload([syntheticAudio])
consentActions().resolveAudioConsent(true)
assert(uploadCalls.length === 1 && uploadCalls[0].approved && uploadCalls[0].files[0] === syntheticAudio, 'approval uploads only the selected files')
consentActions().resolveAudioConsent(true)
assert(uploadCalls.length === 1, 'a resolved consent cannot upload again')

const dirtyHelperSource = pageAst.statements.filter(node => ts.isFunctionDeclaration(node)
  && ['buildInitialSpeakerRoleMap', 'markAudioMaterialDirty'].includes(node.name?.text)).map(node => node.getText(pageAst)).join('\n')
const dirtyHelperJs = ts.transpileModule(dirtyHelperSource, { compilerOptions: { target: ts.ScriptTarget.ES2020 } }).outputText
const markDirty = new Function('getSegmentSpeakerKey', 'buildTranscriptText', 'buildNonverbalNotes', 'AUDIO_APPLY_TARGETS',
  `${dirtyHelperJs}; return markAudioMaterialDirty`)(getSegmentSpeakerKey, buildTranscriptText, buildNonverbalNotes, ['transcript_text', 'nonverbal_notes'])
const roleMaterial = { kind: 'audio', segments: [{ id: 1, start: 0, end: 3, text: '합성 발화', speaker: 'speaker_1' }],
  speakerRoleMap: { speaker_0: 'counselor', speaker_1: 'client' }, appliedTargets: [] }
const temporarilyAbsent = markDirty({ ...roleMaterial, segments: [{ ...roleMaterial.segments[0], speaker: 'speaker_0' }] })
const restoredSpeaker = markDirty({ ...temporarilyAbsent, segments: roleMaterial.segments })
assert(temporarilyAbsent.speakerRoleMap.speaker_1 === 'client', 'temporary absence must preserve the counselor-assigned speaker role')
assert(restoredSpeaker.transcriptText.includes('내담자: 합성 발화'), 'restoring a speaker must restore its existing role automatically')

// Render the actual editor with persistent hook state and invoke its JSX handlers.
// Parent updates use the real upload helper so role and segment updates compose.
const editorJs = ts.transpileModule(editorSource, { compilerOptions: {
  target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
} }).outputText
function editorHarness(initialMaterial) {
  let currentMaterial = initialMaterial, cursor = 0, tree, updates = 0
  const hooks = [], rowActions = []
  const react = {
    useState(initial) {
      const slot = cursor++
      if (!(slot in hooks)) hooks[slot] = initial
      return [hooks[slot], next => { hooks[slot] = typeof next === 'function' ? next(hooks[slot]) : next }]
    },
    useRef(initial) {
      const slot = cursor++
      return hooks[slot] ||= { current: initial }
    },
    useMemo: compute => compute(),
  }
  const imports = {
    react, 'react/jsx-runtime': jsxRuntime, 'lucide-react': { Play: () => null, RefreshCcw: () => null },
    '../../lib/audioTranscriptWorkflow': workflow,
    '../../api/client': { reviewAudioPrivacy: () => { throw Error('Unexpected network call') } },
  }
  const exported = {}
  new Function('require', 'exports', editorJs)(name => {
    assert(name in imports, `unexpected editor import: ${name}`)
    return imports[name]
  }, exported)
  const update = change => { updates++; currentMaterial = markDirty({ ...currentMaterial, ...change }) }
  const props = {
    applyMode: 'append', transcriptionAvailable: true, transcriptionReason: null,
    onUpdateSegments: segments => update({ segments }),
    onUpdateSpeakerRole: (key, role) => update({ speakerRoleMap: { ...currentMaterial.speakerRoleMap, [key]: role } }),
    onUpdateSegmentText: (id, text) => update({ segments: currentMaterial.segments.map(segment => segment.id === id ? { ...segment, text } : segment) }),
    onApply: () => {}, onApplyModeChange: () => {}, onExpectedSpeakersChange: () => {}, onTranscribe: () => {},
  }
  function nodes(node) {
    if (!node || typeof node !== 'object') return []
    if (Array.isArray(node)) return node.flatMap(item => nodes(item))
    return [node, ...nodes(node.props?.children)]
  }
  function text(node) {
    if (node == null || typeof node === 'boolean') return ''
    if (typeof node !== 'object') return String(node)
    if (Array.isArray(node)) return node.map(text).join('')
    return text(node.props?.children)
  }
  const find = predicate => {
    const node = nodes(tree).find(predicate)
    assert(node, 'expected editor control is rendered')
    return node
  }
  const label = value => find(node => node.props?.['aria-label'] === value)
  const button = value => find(node => node.type === 'button' && text(node) === value)
  function render() {
    cursor = 0
    tree = exported.AudioTranscriptEditor({ ...props, material: currentMaterial })
    for (const node of nodes(tree)) {
      if (typeof node.ref === 'function') node.ref({
        scrollIntoView: () => rowActions.push(['scroll', node.props['aria-label']]),
        focus: () => { rowActions.push(['focus', node.props['aria-label']]); node.props.onFocus?.() },
      })
    }
  }
  render()
  return {
    render, label, button, rowActions,
    material: () => currentMaterial, updates: () => updates,
    replace: material => { currentMaterial = material; render() },
    includes: value => text(tree).includes(value),
    selectAll(checked) {
      const control = find(node => node.type === 'label' && text(node) === '전체 선택').props.children[0]
      assert(!control.props.disabled, 'select all must be editable')
      control.props.onChange({ target: { checked } }); render()
    },
    select(index, checked = true, shiftKey = false) {
      const control = label(`${index + 1}번째 발화 선택`)
      assert(!control.props.disabled, 'row selection must be editable')
      control.props.onChange({ target: { checked }, nativeEvent: { shiftKey } }); render()
    },
    click(value) {
      const control = button(value)
      assert(!control.props.disabled, `${value} must be enabled`)
      control.props.onClick(); render()
    },
  }
}
const syntheticMaterial = { id: 'synthetic-live', kind: 'audio', filename: 'synthetic-live.wav', status: 'transcribed',
  warnings: [], appliedTargets: ['transcript_text'], segments: liveFixture, rawSegments: structuredClone(liveFixture), speakerRoleMap: {} }
const editor = editorHarness(syntheticMaterial)
assert(editor.includes('화자 미지정 40줄') && editor.button('상담자로 지정').props.disabled, 'initial UI counts all missing speakers and blocks empty assignment')
editor.selectAll(true)
assert(editor.includes('40줄 선택'), 'select all reaches all 40 checkboxes')
editor.click('상담자로 지정')
assert(editor.includes('화자 미지정 0줄') && editor.includes('0줄 선택'), 'assign all clears unresolved count and selection')
assert(editor.button('다음 미지정 줄로').props.disabled, 'navigation disables once all speakers are assigned')
assert((editor.material().transcriptText.match(/상담자:/g) || []).length === 40, 'parent receives all 40 assigned rows with their mapped role')
assert(editor.material().dirtySinceApply && editor.material().appliedTargets.length === 0, 'bulk assignment requires reviewing and reapplying the edited transcript')
assert(JSON.stringify(editor.material().rawSegments) === liveBefore, 'editor assignment preserves the ASR original')
editor.select(9)
editor.select(19, true, true)
assert(editor.includes('11줄 선택'), 'actual Shift handler selects an inclusive range')
editor.click('내담자로 지정')
assert((editor.material().transcriptText.match(/내담자:/g) || []).length === 11, 'range assignment changes exactly 11 roles')
assert((editor.material().transcriptText.match(/상담자:/g) || []).length === 29, 'range assignment preserves all other roles')
editor.select(19)
editor.select(9, true, true)
editor.select(9, false, true)
assert(editor.includes('0줄 선택'), 'backward Shift range deselection is wired to the editor')
editor.selectAll(true)
editor.selectAll(false)
assert(editor.includes('0줄 선택'), 'select all can also clear selection')
editor.replace(syntheticMaterial)
editor.click('다음 미지정 줄로')
editor.click('다음 미지정 줄로')
assert(editor.rowActions.at(-1).join(':') === 'focus:2번째 발화', 'navigation scrolls and focuses successive unresolved rows')
editor.label('40번째 발화').props.onFocus()
editor.click('다음 미지정 줄로')
assert(editor.rowActions.at(-1).join(':') === 'focus:1번째 발화', 'navigation wraps after the focused last row')
editor.select(0)
editor.replace({ ...syntheticMaterial, id: 'synthetic-upload', segments, speakerRoleMap })
assert(editor.includes('0줄 선택'), 'switching materials clears selection even if IDs overlap')
editor.select(0)
editor.replace({ ...editor.material(), segments: splitAudioSegment(segments, 1, 3, 2) })
assert(editor.includes('0줄 선택'), 'splitting a row resets stale selection')
editor.replace({ ...syntheticMaterial, id: 'synthetic-upload', segments, speakerRoleMap })
editor.label('1번 발화 화자').props.onChange({ target: { value: 'speaker_2' } })
editor.render()
assert(editor.material().segments[0].speaker === 'speaker_2' && editor.material().segments[2].speaker === 'speaker_1', 'existing single-row upload assignment still changes only that row')
assert(editor.material().transcriptText.includes('상담자: 편집된 첫 발화'), 'single-row upload assignment preserves role-map behavior')
const uploadKey = keyFor(editor.material(), editor.material().segments, editor.material().speakerRoleMap)
editor.select(1)
editor.click('내담자로 지정')
assert(uploadKey !== keyFor(editor.material(), editor.material().segments, editor.material().speakerRoleMap), 'bulk upload edits invalidate the previous privacy review')
for (const locked of [{ status: 'transcribing' }, { failedRanges: [{ start: 10, end: 20 }] }]) {
  editor.replace({ ...syntheticMaterial, ...locked })
  const before = editor.updates()
  assert(editor.label('1번째 발화 선택').props.disabled && editor.button('내담자로 지정').props.disabled, 'incomplete audio disables bulk editing')
  editor.button('내담자로 지정').props.onClick()
  assert(editor.updates() === before, 'disabled transcript cannot be changed by the assignment handler')
}

fs.rmSync(outputDir, { recursive: true, force: true })
console.log('audio transcript workflow verification passed')
