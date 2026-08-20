import fs from 'node:fs'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const hook = fs.readFileSync('src/hooks/useCounselorDemo.ts', 'utf8')
const page = fs.readFileSync('src/pages/CounselorDemoPage.tsx', 'utf8')
const fixture = fs.readFileSync('src/data/counselorDemoFixture.ts', 'utf8')
const sourcePanel = fs.readFileSync('src/components/counselor-demo/SessionSourcePanel.tsx', 'utf8')
const demoSource = [hook, page, fixture, sourcePanel].join('\n')

for (const apiSymbol of [
  'generateNoteDraft',
  'generateSupervisionReport',
  'confirmGeneratedNote',
  'create_case_memory',
]) {
  assert(!demoSource.includes(apiSymbol), `counselor demo must not reference ${apiSymbol}`)
}

assert(page.includes('useDocumentExport({ localOnly: true })'), 'demo export capability check must stay local')
assert(page.includes('생성·저장 API를 호출하지 않습니다'), 'pre-generated mode must be visible in the UI')

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

assert(fixture.includes("'session_summary'"), 'session summary fixture is required')
assert(fixture.includes("'session_note'"), 'session note fixture is required')
assert(fixture.includes("'supervision_report'"), 'supervision report fixture is required')
assert(sourcePanel.includes('demoData.sessionSources.history.map'), 'sessions 1-4 must be selectable')
assert(sourcePanel.includes('MusPsy 원문 보기'), 'prior session source must be accessible')

for (const legacyMarker of [
  'CASE-DEMO-001',
  'CASE-2026-05',
  '김민서',
  '민서 씨',
  '취업 면접',
  'Synthetic 자료',
]) {
  assert(!demoSource.includes(legacyMarker), `legacy counselor demo marker exposed: ${legacyMarker}`)
}

const canonicalCase = JSON.parse(
  fs.readFileSync('../sample_data/muspsy_demo/session_input_005_muspsy_1416_ko.json', 'utf8'),
)
assert(canonicalCase.case_id === 'CASE-MUSPSY-1416', 'canonical demo case must be CASE-MUSPSY-1416')

console.log('counselor demo pre-generated fixture verification passed')
