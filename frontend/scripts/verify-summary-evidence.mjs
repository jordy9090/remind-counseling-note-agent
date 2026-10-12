import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source = fs.readFileSync('src/lib/summaryEvidence.ts', 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
const { summarySectionEvidence, riskInformation } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const relationalSource = ts.transpileModule(fs.readFileSync('src/lib/relationalInsights.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText
const { formatRelationalSupervisionMemo } = await import(`data:text/javascript;base64,${Buffer.from(relationalSource).toString('base64')}`)
const section = (text, refs, review = false, type = 'direct') => ({
  text, source_refs: refs, requires_review: review, evidence_type: type,
})
const note = { full_response: {
  session_summary_draft: {
    presenting_problem: section('Synthetic issue summary', ['counselor_memo']),
    session_content: section('A paraphrased summary with no extraction-text match.', ['transcript.turn_2', 'counselor_memo'], true, 'mixed'),
    counselor_intervention: section('Paraphrased intervention', ['transcript.turn_1']),
    client_response: section('Paraphrased response', ['transcript.turn_2']),
    next_plan: section('A tentative plan', ['counselor_memo'], true, 'model_inference'),
    reflection: section('Synthetic counselor reflection', ['counselor_memo'], true, 'counselor_input'),
  },
  sanitized_input: { sources: { transcript_text: 'Counselor: Synthetic question\nClient: Synthetic response', counselor_memo: 'Synthetic session memo' } },
  evidence_mapped_data: { items: Array.from({ length: 12 }, () => ({ content: 'Unrelated extracted item', source_refs: ['counselor_memo'] })) },
  session_note_draft: { sections: { '위험 관련 확인 가능 정보': 'Synthetic risk information requiring counselor review' }, source_refs: { '위험 관련 확인 가능 정보': ['transcript.turn_2'] } },
} }

const content = summarySectionEvidence(note, 'session_content')
assert.deepEqual(content.evidence.map(item => item.source_type), ['transcript', 'counselor_memo'])
assert.equal(content.evidence[0].source_excerpt, 'Client: Synthetic response')
assert.equal(content.requiresReview, true)
assert.equal(content.inferred, false)
assert.deepEqual(summarySectionEvidence(note, 'main_issue').evidence.map(item => item.source_type), ['counselor_memo'])
assert.deepEqual(summarySectionEvidence(note, 'counselor_intervention').evidence.map(item => item.source_type), ['transcript'])
assert.equal(summarySectionEvidence(note, 'client_response').requiresReview, false)
assert.equal(summarySectionEvidence(note, 'next_plan').inferred, true)
assert.equal(summarySectionEvidence(note, 'next_plan').requiresReview, true)
assert.equal(summarySectionEvidence(note, 'session_theme').requiresReview, true)
assert.equal(summarySectionEvidence({}, 'session_content'), undefined, 'legacy responses must retain their fallback path')
for (const refs of [['unknown_ref'], ['transcript.turn_999'], ['nonverbal_notes'], []]) {
  const missingSource = structuredClone(note)
  missingSource.full_response.session_summary_draft.client_response.source_refs = refs
  const review = summarySectionEvidence(missingSource, 'client_response')
  assert.deepEqual(review.evidence, [], 'unknown or empty source references cannot count as supporting evidence')
  assert.equal(review.requiresReview, true)
}
for (const type of ['inferred', 'model_inference']) {
  const inference = structuredClone(note)
  inference.full_response.session_summary_draft.client_response.evidence_type = type
  assert.equal(summarySectionEvidence(inference, 'client_response').requiresReview, true, 'inferences require review even when the response flag is false')
}
const additionalSources = structuredClone(note)
Object.assign(additionalSources.full_response.sanitized_input.sources, {
  previous_session_summary: '1회기 (2026-09-01): First synthetic session\nAdditional first-session text\n5회기 (2026-09-05): Fifth synthetic session\nAdditional fifth-session text\n6회기: Sixth synthetic session',
  psychological_test_summary: 'Synthetic counselor-entered test summary',
  key_issue_tags: ['Synthetic issue A', 'Synthetic issue B'],
  counseling_goal: 'Synthetic counselor-entered goal',
})
for (const refs of [['previous_session.5'], ['previous_session_summary', 'previous_session.5'], ['previous_session.5', 'previous_session_summary']]) {
  additionalSources.full_response.session_summary_draft.session_content.source_refs = refs
  assert.equal(summarySectionEvidence(additionalSources, 'session_content').evidence[0].source_excerpt,
    'Fifth synthetic session Additional fifth-session text', 'a numbered prior-session ref must display that session only')
}
additionalSources.full_response.session_summary_draft.session_content.source_refs = ['previous_session.99']
assert.deepEqual(summarySectionEvidence(additionalSources, 'session_content').evidence, [], 'absent prior-session refs must not fall back to another session')
for (const [ref, type, excerpt] of [
  ['psychological_test_summary', 'psychological_test', 'Synthetic counselor-entered test summary'],
  ['key_issue_tags', 'counselor_input', 'Synthetic issue A, Synthetic issue B'],
  ['counseling_goal', 'counselor_input', 'Synthetic counselor-entered goal'],
]) {
  additionalSources.full_response.session_summary_draft.client_response.source_refs = [ref]
  const review = summarySectionEvidence(additionalSources, 'client_response')
  assert.equal(review.evidence[0].source_type, type)
  assert.equal(review.evidence[0].source_excerpt, excerpt)
  assert.equal(review.requiresReview, false)
}

assert.equal(riskInformation(note).text, note.full_response.session_note_draft.sections['위험 관련 확인 가능 정보'])
assert.deepEqual(summarySectionEvidence(note, 'risk_signal').evidence.map(item => item.source_type), ['transcript'])
assert.equal(summarySectionEvidence(note, 'risk_signal').requiresReview, true)
for (const missing of [{}, { full_response: {} }, { full_response: { session_note_draft: { sections: {} } } }]) {
  assert.equal(riskInformation(missing).text, '위험 관련 정보는 상담사가 별도로 확인해 주세요.')
  assert.equal(riskInformation(missing).requires_review, true)
}
const page = fs.readFileSync('src/pages/SessionDraftPage.tsx', 'utf8')
assert(page.includes('summarySectionEvidence(result, id)'), 'rendered sections must consume final summary metadata')
assert(page.includes('content: riskInformation(result).text'), 'rendered risk section must use the backend risk text')
assert(!page.includes('입력 자료에서 직접 확인된 위험 신호는 없습니다.'), 'UI must not manufacture an absence-of-risk statement')

// Exercise the page's actual section assembly without booting a browser or creating records.
const parsedPage = ts.createSourceFile('SessionDraftPage.tsx', page, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const functionNames = new Set(['buildDocumentSections', 'findEvidenceForSection', 'buildSourceBadges', 'buildSectionConfidence', 'toCompactEvidence', 'normalizeText'])
const constantNames = new Set(['sourceTypeToBadge', 'sourceTypeLabel'])
const sectionSource = parsedPage.statements.filter(statement => (
  ts.isFunctionDeclaration(statement) && functionNames.has(statement.name?.text)
) || (
  ts.isVariableStatement(statement) && statement.declarationList.declarations.some(declaration => constantNames.has(declaration.name.getText(parsedPage)))
)).map(statement => statement.getText(parsedPage)).join('\n')
const sectionJs = ts.transpileModule(sectionSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText
const buildDocumentSections = new Function('summarySectionEvidence', 'riskInformation', 'buildGroundingReviewItems', 'sessionThemeText', 'formatRelationalSupervisionMemo', `${sectionJs}\nreturn buildDocumentSections`)(
  summarySectionEvidence, riskInformation, () => [], () => 'Synthetic theme', formatRelationalSupervisionMemo,
)
const renderedNote = { ...note, session_summary: note.full_response.session_summary_draft.session_content.text,
  evidence_check: [{ claim: 'Unrelated extraction', source_type: 'previous_summary', source_excerpt: 'Old context', confidence: 'high' }] }
const sections = buildDocumentSections(renderedNote, { counselor_memo: 'Synthetic session memo' }, '', new Set())
const getSection = id => sections.find(section => section.id === id)
assert.deepEqual(getSection('session_content').sourceBadges, ['needs_review', 'transcript', 'memo', 'editable'])
assert.equal(getSection('session_content').evidence.length, 2, 'unrelated extraction evidence must not leak into the summary')
assert(getSection('session_content').evidence.every(item => item.needsReview), 'final requires_review must survive the display transformation')
assert.deepEqual(getSection('counselor_intervention').sourceBadges, ['transcript', 'editable'])
assert.deepEqual(getSection('client_response').sourceBadges, ['transcript', 'editable'], 'review should follow the final response, not a hardcoded badge')
assert(getSection('next_plan').sourceBadges.includes('ai'), 'inference must remain visible even when its source is a memo')
assert.equal(getSection('risk_signal').content, riskInformation(note).text)
assert.deepEqual(getSection('risk_signal').sourceBadges, ['needs_review', 'transcript', 'editable'])
const legacySections = buildDocumentSections({ session_summary: 'Legacy summary', evidence_check: renderedNote.evidence_check }, { counselor_memo: '' }, '', new Set())
assert.deepEqual(legacySections.find(section => section.id === 'session_content').sourceBadges, ['previous', 'editable'])
assert.equal(legacySections.find(section => section.id === 'risk_signal').content, '위험 관련 정보는 상담사가 별도로 확인해 주세요.')
console.log('Final summary source/review metadata and backend risk information: passed')
