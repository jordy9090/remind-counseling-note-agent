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
