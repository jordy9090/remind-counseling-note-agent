import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const source = fs.readFileSync('src/lib/relationalInsights.ts', 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
})
const { readRelationalInsights, formatRelationalSupervisionMemo } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const valid = {
  status: 'generated', lens: 'psychodynamic_relational', notices: [],
  supervision_memo: 'A tentative possibility remains to be checked against the recorded interaction.',
  cards: [{
    id: 'synthetic-card', focus: 'relationship_pattern', observation: 'Synthetic observation',
    hypothesis: 'Synthetic possibility', alternative_explanation: 'Synthetic alternative',
    counterevidence_or_missing: 'Synthetic missing context', supervision_questions: ['Synthetic question?'],
    brief_text: 'A tentative possibility remains to be checked against the recorded interaction.',
    evidence: [{ source_ref: 'transcript_text', quote: 'Synthetic quote' }],
    theory_source_ids: ['synthetic-source'], requires_review: true,
  }],
  theory_sources: [{
    id: 'synthetic-source', title: 'Synthetic source', organization: 'Synthetic publisher',
    url: 'https://example.org', locator: 'Synthetic section', principle: 'Synthetic principle',
    concepts: ['relationship_pattern'], limitations: 'Synthetic limit',
  }],
}

assert.equal(readRelationalInsights(undefined), null, 'legacy notes without insights remain readable')
assert.equal(readRelationalInsights(null), null)
assert.deepEqual(readRelationalInsights(valid), valid, 'valid stored evidence and source text are preserved')
for (const malformed of [
  {}, [], 'invalid', { ...valid, cards: null }, { ...valid, theory_sources: {} },
  { ...valid, notices: [null] },
  { ...valid, cards: [{ ...valid.cards[0], evidence: [null] }] },
  { ...valid, cards: [{ ...valid.cards[0], supervision_questions: {} }] },
  { ...valid, cards: [{ ...valid.cards[0], observation: {} }] },
  { ...valid, cards: [{ ...valid.cards[0], brief_text: 42 }] },
  { ...valid, supervision_memo: [] },
  { ...valid, cards: [{ ...valid.cards[0], requires_review: false }] },
  { ...valid, theory_sources: [{ ...valid.theory_sources[0], title: {} }] },
  { ...valid, theory_sources: [{ ...valid.theory_sources[0], limitations: [] }] },
]) {
  const result = readRelationalInsights(malformed)
  assert.equal(result.status, 'unavailable', 'malformed drafts degrade to unavailable analysis')
  assert.deepEqual(result.cards, [], 'unvalidated hypotheses cannot appear in the memo')
}
assert.equal(readRelationalInsights({ ...valid, status: 'demo', cards: [] }).status, 'demo', 'demo state must not be reported as an actual generation result')

const originalMemo = 'Counselor-authored reflection.\nKeep its original wording.'
assert.equal(formatRelationalSupervisionMemo(undefined, originalMemo), originalMemo, 'legacy memo is preserved exactly')
assert.equal(formatRelationalSupervisionMemo({ ...valid, status: 'demo' }, originalMemo), originalMemo, 'demo hypotheses never become a session memo')
for (const status of ['unavailable', 'insufficient_evidence']) {
  const memo = formatRelationalSupervisionMemo({ ...valid, status }, originalMemo)
  assert.equal(memo, originalMemo, 'failed analysis preserves reflection without technical messages in the clinical body')
}
assert.equal(formatRelationalSupervisionMemo({}, originalMemo), originalMemo)
const originalData = structuredClone(valid)
const generatedMemo = formatRelationalSupervisionMemo(valid, originalMemo)
assert.equal(generatedMemo, valid.supervision_memo, 'the existing memo shows only server-authored compact prose')
for (const hidden of ['Synthetic observation', 'Synthetic quote', 'Synthetic source', 'https://example.org', '관찰:', '참고 문헌']) {
  assert.ok(!generatedMemo.includes(hidden), 'review metadata must not be serialized into the editable memo')
}
assert.deepEqual(valid, originalData, 'rendering must retain the original evidence, questions and source metadata')
assert.equal(formatRelationalSupervisionMemo({ ...valid, supervision_memo: '' }, originalMemo), originalMemo)
const legacy = structuredClone(valid)
delete legacy.supervision_memo
delete legacy.cards[0].brief_text
assert.deepEqual(readRelationalInsights(legacy), legacy, 'older metadata remains readable without compact fields')
assert.equal(formatRelationalSupervisionMemo(legacy, originalMemo), originalMemo, 'older verbose cards are not expanded into the note')
assert.equal(formatRelationalSupervisionMemo({ ...valid, supervision_memo: 'Unconnected replacement text.' }, originalMemo), originalMemo, 'stale compact text must not bypass its accepted cards')
const fallbackReflection = `${valid.supervision_memo}\n\n${originalMemo}`
assert.equal(formatRelationalSupervisionMemo({ ...valid, supervision_memo: fallbackReflection }, originalMemo), fallbackReflection, 'server-preserved recorded reflection stays intact')

const twoCards = structuredClone(valid)
twoCards.cards.push({ ...valid.cards[0], id: 'counselor-card', focus: 'counselor_reflection', brief_text: 'Consider how the recorded wish to reassure shaped the next question.' })
twoCards.supervision_memo = `${valid.supervision_memo}\n\n${twoCards.cards[1].brief_text}`
assert.equal(formatRelationalSupervisionMemo(twoCards, originalMemo), twoCards.supervision_memo, 'both the tentative hypothesis and counselor reflection survive without truncation')
twoCards.cards[1].brief_text = ''
twoCards.supervision_memo = fallbackReflection
assert.equal(formatRelationalSupervisionMemo(twoCards, originalMemo), fallbackReflection, 'a legacy card without compact prose must not suppress the server-preserved reflection')

for (const invalidEvidence of [
  { ...valid, cards: [{ ...valid.cards[0], evidence: [] }] },
  { ...valid, cards: [{ ...valid.cards[0], evidence: [{ source_ref: 'unknown_source', quote: 'Synthetic quote' }] }] },
  { ...valid, cards: [{ ...valid.cards[0], theory_source_ids: ['unknown-theory'] }] },
  { ...valid, theory_sources: [{ ...valid.theory_sources[0], url: 'javascript:alert(1)' }] },
]) {
  const memo = formatRelationalSupervisionMemo(invalidEvidence, originalMemo)
  assert.equal(memo, originalMemo, 'unconnected session or theory evidence must preserve the original reflection')
}
console.log('Relational insight restoration and existing-memo content checks passed.')
