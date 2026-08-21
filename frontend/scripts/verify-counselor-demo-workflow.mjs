import fs from 'node:fs'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const app = fs.readFileSync('src/App.tsx', 'utf8')
const sessionPage = fs.readFileSync('src/pages/SessionDraftPage.tsx', 'utf8')
const fixture = fs.readFileSync('src/data/counselorDemoFixture.ts', 'utf8')
const activeDemoSource = [app, sessionPage, fixture].join('\n')

assert(!app.includes('CounselorDemoPage'), 'production flow must not render the counselor-review workspace')
assert(!app.includes('isCounselorDemoRoute'), 'production flow must not intercept /demo routes')
assert(app.includes('<LandingPage'), 'existing landing flow must remain active')
assert(app.includes('<SessionDraftPage'), 'existing session flow must remain active')

assert(
  sessionPage.includes("import { COUNSELOR_DEMO_FIXTURE } from '../data/counselorDemoFixture'"),
  'existing SessionDraftPage must load the MusPsy fixture',
)
assert(
  sessionPage.includes('buildStaticDemoDraftSections()'),
  'existing summary flow must load the pre-generated Candidate-05 summary',
)
assert(
  sessionPage.includes('buildStaticFinalDocumentSections(documentType)'),
  'existing document flow must load the pre-generated Candidate-05 session note',
)
assert(
  sessionPage.includes('buildStaticSupervisionReport()'),
  'existing report flow must load the pre-generated Candidate-05 supervision report',
)
assert(
  sessionPage.includes('정적 데모 모드에서는 서버나 DB에 저장하지 않습니다.'),
  'static demo save action must remain local-only',
)

for (const apiSymbol of [
  'generateNoteDraft',
  'generateSupervisionReport',
  'recomposeNoteDraft',
  'saveTemporaryDraft',
]) {
  assert(!sessionPage.includes(apiSymbol), `static production demo must not reference ${apiSymbol}`)
}

for (const selectedDocument of [
  '문서_A_회기요약.txt?raw',
  '문서_A_상담일지.txt?raw',
  '문서_A_수퍼비전보고서.txt?raw',
]) {
  assert(fixture.includes(selectedDocument), `missing selected Candidate-05 fixture: ${selectedDocument}`)
}

for (let sessionNumber = 1; sessionNumber <= 4; sessionNumber += 1) {
  assert(
    fixture.includes(`session_${sessionNumber}_source.txt?raw`),
    `missing MusPsy session ${sessionNumber} history source`,
  )
}

assert(sessionPage.includes('[회기 요약]'), 'sessions 1-4 must expose their summary in the existing history panel')
assert(sessionPage.includes('[상담 원문]'), 'sessions 1-4 must expose their raw source in the existing history panel')
assert(!sessionPage.includes("id: 'termination_report',\n    title: '종결 보고서'"), 'counselor demo must not expose a termination report option')
assert(fixture.includes("'session_summary'"), 'session summary fixture is required')
assert(fixture.includes("'session_note'"), 'session note fixture is required')
assert(fixture.includes("'supervision_report'"), 'supervision report fixture is required')

for (const legacyMarker of [
  'CASE-DEMO-001',
  'CASE-2026-05',
  '가명 은하',
  '김민서',
  '민서 씨',
  '취업 면접',
  'Synthetic 자료',
  '[PERSON]',
]) {
  assert(!activeDemoSource.includes(legacyMarker), `legacy counselor demo marker exposed: ${legacyMarker}`)
}

const canonicalCase = JSON.parse(
  fs.readFileSync('../sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json', 'utf8'),
)
assert(canonicalCase.case_id === 'CASE-MUSPSY-1416', 'canonical demo case must be CASE-MUSPSY-1416')
assert(canonicalCase.persist !== true, 'canonical demo must not enable persistence')

console.log('existing Re:mind UI + MusPsy static fixture verification passed')
