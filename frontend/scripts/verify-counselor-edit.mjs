import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const source = fs.readFileSync(path.resolve('src/lib/supervisionDraft.ts'), 'utf8')
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'remind-counselor-edit-'))
const outputPath = path.join(outputDir, 'supervisionDraft.mjs')
const transpiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
fs.writeFileSync(outputPath, transpiled.outputText, 'utf8')

const { applyCounselorEditsToSummary, transcriptLineSpeaker, transcriptTurnLabels } = await import(pathToFileURL(outputPath).href)
const section = (text, sourceRefs) => ({
  text,
  evidence_type: 'mixed',
  source_refs: sourceRefs,
  requires_review: false,
})
const original = {
  session_info: {
    case_id: 'CASE-EDIT',
    client_alias: '가명',
    session_number: 3,
    session_date: '2026-09-03',
    counselor_name: '상담사',
  },
  session_theme: section('AI 회기 주제', ['counselor_memo']),
  presenting_problem: section('AI 주요 호소', ['transcript_text']),
  session_content: section('AI 회기 요약', ['transcript:s1:1-3']),
  counselor_intervention: section('AI 개입', ['counselor_memo']),
  client_response: section('AI 반응', ['transcript:s1:4-5']),
  reflection: section('AI 성찰', ['counselor_memo']),
  next_plan: section('AI 다음 계획', ['counselor_memo']),
}

const latest = applyCounselorEditsToSummary(original, [
  { id: 'session_content', content: '상담사가 수정한 최신 회기 요약' },
  { id: 'main_issue', content: '상담사가 수정한 주요 호소' },
  { id: 'supervision_memo', content: '상담사가 수정한 슈퍼비전 메모' },
])

assert(latest.session_content.text === '상담사가 수정한 최신 회기 요약', 'edited summary must be used')
assert(latest.presenting_problem.text === '상담사가 수정한 주요 호소', 'edited presenting problem must be used')
assert(latest.reflection.text === '상담사가 수정한 슈퍼비전 메모', 'edited supervision memo must be used')
assert(latest.session_content.source_refs[0] === 'transcript:s1:1-3', 'grounding source metadata must survive edit')
assert(latest.session_content.requires_review, 'old references cannot validate edited assertions')
assert(latest.session_content.evidence_type === 'needs_review', 'edited assertions need source review')
assert(latest.next_plan.requires_review === false, 'unchanged text keeps its original review state')
assert(original.session_content.text === 'AI 회기 요약', 'original AI response must remain immutable')

const pageSource = fs.readFileSync(path.resolve('src/pages/SessionDraftPage.tsx'), 'utf8')
assert(pageSource.includes('applyCounselorEditsToSummary(originalSummary, draftSections)'), 'supervision request must use current draftSections')
assert(pageSource.includes('markGroundingItemsStale(section.groundingItems)'), 'counselor edits must still mark grounding stale')
assert(pageSource.includes('rows: block.rows || []'), 'supervision export must normalize nullable rows')

// Supervision form C-2: transcript turns are numbered per speaker (내1, 상1, 내2).
const turnLabels = transcriptTurnLabels([{ speaker: 'counselor' }, { speaker: 'client' }, { speaker: 'counselor' }, { speaker: 'client' }, { speaker: 'other' }])
assert(turnLabels.join(',') === '상1,내1,상2,내2,기타', `per-speaker transcript labels: ${turnLabels.join(',')}`)
for (const label of ['내1', '내담자', 'client']) assert(transcriptLineSpeaker(label) === 'client', `client label: ${label}`)
for (const label of ['상1', '상담자', '상담사']) assert(transcriptLineSpeaker(label) === 'counselor', `counselor label: ${label}`)
assert(pageSource.includes('onChangeMeta={(field, value)'), 'supervision header cells must be editable')

console.log('Counselor edit -> supervision request regression verification passed.')
