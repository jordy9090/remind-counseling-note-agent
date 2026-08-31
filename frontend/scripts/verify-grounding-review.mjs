import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const sourcePath = path.resolve('src/lib/groundingReview.ts')
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'remind-grounding-review-'))
const outputPath = path.join(outputDir, 'groundingReview.mjs')
const source = fs.readFileSync(sourcePath, 'utf8')
const transpiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
fs.writeFileSync(outputPath, transpiled.outputText, 'utf8')

const {
  buildGroundingReviewItems,
  counselorSourceField,
  isInlineGroundingItem,
  markGroundingItemsStale,
  parseTranscriptEvidence,
  supportStateLabel,
} = await import(pathToFileURL(outputPath).href)

const draftGenerationSource = fs.readFileSync(path.resolve('src/lib/draftGeneration.ts'), 'utf8')
const draftGenerationOutputPath = path.join(outputDir, 'draftGeneration.mjs')
const draftGenerationTranspiled = ts.transpileModule(draftGenerationSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
fs.writeFileSync(draftGenerationOutputPath, draftGenerationTranspiled.outputText, 'utf8')
const { runDraftGeneration } = await import(pathToFileURL(draftGenerationOutputPath).href)

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const rawText = '[counselor] 오늘은 연습해볼까요?\n[client] 부모에게 제 의견을 말했어요.'
const grounding = {
  enabled: true,
  context: {
    sources: [
      { evidence_id: 'R1', source_type: 'raw_transcript', source_ref: 'transcript:s5:0-1', source_text: rawText },
      { evidence_id: 'R2', source_type: 'raw_transcript', source_ref: 'transcript:s3:0-1', source_text: '[client] 문장을 연습했어요.' },
      { evidence_id: 'M1', source_type: 'counselor_confirmed', source_ref: 'confirmed_note:s3:reflection', source_text: '자기표현 연습을 유지하기로 판단함.' },
      { evidence_id: 'R9', source_type: 'raw_transcript', source_ref: 'transcript:uncited:0-1', source_text: 'UNVALIDATED_TOP5_CANDIDATE' },
    ],
  },
  claims: [
    { claim_id: 'C1', target_field: 'session_content', support_type: 'direct_evidence', evidence_ids: ['R1', 'R2'], text: '의견을 말했다.' },
    { claim_id: 'C2', target_field: 'counselor_intervention', support_type: 'counselor_judgment', evidence_ids: ['M1'], text: '연습을 유지하기로 했다.' },
    { claim_id: 'C3', target_field: 'reflection', support_type: 'clinical_inference', evidence_ids: ['R1'], text: '연습이 촉진했을 수 있다.' },
    { claim_id: 'C4', target_field: 'client_response', support_type: 'unsupported', evidence_ids: [], text: '불안이 완전히 해소됐다.' },
    { claim_id: 'C5', target_field: 'next_plan', support_type: 'direct_evidence', evidence_ids: ['R404'], text: '누락 source.' },
  ],
  claim_support_validations: {
    C1: { verdict: 'supported', supported_evidence_ids: ['R1', 'R2'] },
    C2: { verdict: 'supported', supported_evidence_ids: ['M1'] },
    C5: { verdict: 'supported', supported_evidence_ids: ['R404'] },
  },
}

const direct = buildGroundingReviewItems(grounding, 'session_content')
assert(direct.length === 1, 'direct claim must map beside its target field')
assert(direct[0].sources.length === 2, 'multiple cited evidence sources must remain separate')
assert(direct[0].sources[0].source_text === rawText, 'raw source snapshot must remain byte-for-byte unchanged')
assert(!direct[0].sources.some((sourceItem) => sourceItem.evidence_id === 'R9'), 'uncited retrieval candidate must not reach UI')
assert(
  isInlineGroundingItem(direct[0], direct, '내담자는 이번 회기에 의견을 표현했다.'),
  'one factual claim mapped to one section paragraph must use an inline control',
)
assert(
  isInlineGroundingItem(direct[0], [...direct, { ...direct[0], claim: { ...direct[0].claim, claim_id: 'C1-copy' } }], '의견을 말했다.'),
  'an exact rendered-text match must remain inline even with multiple mapped claims',
)
assert(
  !isInlineGroundingItem(
    direct[0],
    [...direct, { ...direct[0], claim: { ...direct[0].claim, claim_id: 'C1-copy' } }],
    '서로 다른 요약 문장',
  ),
  'ambiguous multi-claim mapping must fall back to a compact review row',
)

const counselor = buildGroundingReviewItems(grounding, 'counselor_intervention')
assert(counselor[0].sources[0].source_type === 'counselor_confirmed', 'counselor judgment must use M source')
assert(counselorSourceField(counselor[0].sources[0].source_ref) === 'reflection', 'confirmed source field must come from metadata')

const clinical = buildGroundingReviewItems(grounding, 'supervision_memo')
assert(clinical[0].claim.support_type === 'clinical_inference', 'clinical inference must retain its review state')
assert(clinical[0].sources[0].evidence_id === 'R1', 'clinical inference may expose cited raw text only as reference')
assert(!isInlineGroundingItem(clinical[0], clinical, clinical[0].claim.text), 'clinical inference must remain a review item')

const unsupported = buildGroundingReviewItems(grounding, 'client_response')
assert(unsupported[0].sources.length === 0, 'unsupported claim must not expose evidence as validated')
assert(supportStateLabel.unsupported === '근거 부족 · 검토 필요', 'unsupported label must be explicit')

const missing = buildGroundingReviewItems(grounding, 'next_plan')
assert(missing[0].missingSource && missing[0].sources.length === 0, 'missing source must fail safely without a fake panel')

const speakers = parseTranscriptEvidence(rawText)
assert(speakers[0].role === '상담자' && speakers[1].role === '내담자', 'raw transcript speakers must be distinguished')
assert(speakers[1].text === '부모에게 제 의견을 말했어요.', 'speaker formatting must not rewrite utterance text')

const stale = markGroundingItemsStale(direct)
assert(stale.every((item) => item.stale), 'edited grounded field must mark every linked claim stale')
assert(buildGroundingReviewItems(undefined, 'session_content').length === 0, 'missing grounding must preserve flag-false UI')
assert(buildGroundingReviewItems({ ...grounding, enabled: false }, 'session_content').length === 0, 'disabled grounding must preserve existing UI')

const componentSource = fs.readFileSync(path.resolve('src/components/note/GroundingEvidenceReview.tsx'), 'utf8')
assert(componentSource.includes('근거 정보를 불러올 수 없습니다.'), 'missing source fail-safe must be rendered')
assert(componentSource.includes('수정 후 근거 재확인 필요'), 'stale state must be rendered')
assert(componentSource.includes('이 문장은 확정 문서 본문에 자동으로 추가되지 않습니다.'), 'unsupported must be separated from confirmed body')
assert(componentSource.includes('EvidenceSourcePanel'), 'claim click must use the right-side evidence source view')
assert(componentSource.includes('bg-amber-100 text-amber-950 ring-2 ring-amber-400'), 'selected evidence control must use a clear amber state')
assert(componentSource.includes("data-evidence-state={stale ? 'stale' : 'selected'}"), 'source cards must distinguish selected and stale evidence states')
assert(componentSource.includes('이 AI 문장을 뒷받침하는 과거 상담 원문입니다.'), 'source panel must explain the selected evidence relationship')
assert(componentSource.includes("stale\n          ? 'border-slate-300 bg-slate-50'"), 'stale source cards must not retain verified amber emphasis')
assert(componentSource.includes('EvidenceDrawer'), 'generated document must use a closable evidence drawer')
assert(componentSource.includes('`근거 ${sources.length}개`'), 'multiple evidence indicator must report its source count')
assert(componentSource.includes('EvidenceControl'), 'clearly mapped factual claims must render control-only evidence UI')
assert(!componentSource.includes('similarity_score'), 'UI must not display retrieval score as confidence')
assert(!componentSource.includes('R404'), 'missing source internal ID must never be hard-coded into counselor UI')

const fixtureSource = fs.readFileSync(path.resolve('src/fixtures/groundingDemo.ts'), 'utf8')
assert(fixtureSource.includes("evidence_id: 'R9'"), 'demo fixture must retain an intentionally uncited retrieval candidate')
assert(fixtureSource.includes("evidence_ids: ['R404']"), 'demo fixture must include a missing-source fail-safe scenario')
assert(fixtureSource.includes("support_type: 'clinical_inference'"), 'demo fixture must include clinical inference')
assert(fixtureSource.includes("support_type: 'unsupported'"), 'demo fixture must include unsupported review content')

const fixtureOutputPath = path.join(outputDir, 'groundingDemo.mjs')
const fixtureTranspiled = ts.transpileModule(fixtureSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
fs.writeFileSync(fixtureOutputPath, fixtureTranspiled.outputText, 'utf8')
const { groundingDemo } = await import(pathToFileURL(fixtureOutputPath).href)
const provenanceExpectations = [
  ['C1', 'session_content', 'R1', 'transcript:synthetic-session-5:0-3'],
  ['C2', 'counselor_intervention', 'M1', 'confirmed_note:synthetic-session-3:counselor_intervention'],
  ['C3', 'supervision_memo', 'R2', 'transcript:synthetic-session-3:0-3'],
]
for (const [claimId, sectionId, evidenceId, expectedSourceRef] of provenanceExpectations) {
  const reviewItem = buildGroundingReviewItems(groundingDemo, sectionId)
    .find((item) => item.claim.claim_id === claimId)
  const uiSource = reviewItem?.sources.find((item) => item.evidence_id === evidenceId)
  const fixtureSourceItem = groundingDemo.context.sources.find((item) => item.evidence_id === evidenceId)
  assert(uiSource?.source_ref === expectedSourceRef, `${claimId} UI source must preserve canonical source_ref`)
  assert(uiSource?.source_text === fixtureSourceItem?.source_text, `${claimId} UI source text must exactly equal fixture source text`)
  if (uiSource?.source_type === 'raw_transcript') {
    const displayedText = parseTranscriptEvidence(uiSource.source_text)
      .map((line) => `[${line.role === '상담자' ? 'counselor' : line.role === '내담자' ? 'client' : 'unknown'}] ${line.text}`)
      .join('\n')
    assert(displayedText === fixtureSourceItem.source_text, `${claimId} displayed transcript must not summarize or rewrite source text`)
  }
  console.log(`provenance ${claimId}: ${evidenceId} -> ${expectedSourceRef} -> exact text equality`)
}

const appSource = fs.readFileSync(path.resolve('src/App.tsx'), 'utf8')
assert(appSource.includes('import.meta.env.DEV'), 'auth bypass for the synthetic preview must be DEV-only')
assert(appSource.includes("get('grounding-demo') === '1'"), 'synthetic preview must require its explicit query flag')
const pageSource = fs.readFileSync(path.resolve('src/pages/SessionDraftPage.tsx'), 'utf8')
assert(pageSource.includes('localGroundingDemoStale'), 'demo fixture must expose an edited/stale review scenario')
assert(pageSource.includes('hasSelectedInlineGrounding'), 'selected inline evidence must highlight the rendered summary paragraph')
assert(pageSource.includes('bg-amber-100 ring-2 ring-amber-300'), 'selected summary paragraph must use the stronger Figma amber state')
assert(pageSource.includes('? Promise.resolve(groundingDemoNote)'), 'DEV demo submit must resolve the synthetic fixture locally')
assert(pageSource.includes(': generateNoteDraft({ ...form, persist: false })'), 'normal submit must retain the production API call')

const loadingTransitions = []
let mockFailure
await runDraftGeneration({
  setLoading: (loading) => loadingTransitions.push(loading),
  generate: async () => { throw new Error('mock generation failure') },
  onSuccess: () => { throw new Error('mock failure must not call success') },
  onError: (error) => { mockFailure = error },
})
assert(mockFailure?.message === 'mock generation failure', 'generation error must reach the user-facing error callback')
assert(
  JSON.stringify(loadingTransitions) === JSON.stringify([true, false]),
  'mock generation failure must always clear loading in finally',
)

let normalGenerateCalls = 0
let normalResult
await runDraftGeneration({
  setLoading: () => {},
  generate: async () => {
    normalGenerateCalls += 1
    return 'normal API result'
  },
  onSuccess: (result) => { normalResult = result },
  onError: (error) => { throw error },
})
assert(normalGenerateCalls === 1, 'normal mode generator must still be invoked exactly once')
assert(normalResult === 'normal API result', 'normal mode result must still reach the existing success state path')

fs.rmSync(outputDir, { recursive: true, force: true })
console.log('grounding review verification passed')
