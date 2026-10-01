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
  cards: [{
    id: 'synthetic-card', focus: 'relationship_pattern', observation: 'Synthetic observation',
    hypothesis: 'Synthetic possibility', alternative_explanation: 'Synthetic alternative',
    counterevidence_or_missing: 'Synthetic missing context', supervision_questions: ['Synthetic question?'],
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
  assert.ok(memo.startsWith(originalMemo), 'existing reflection is preserved when analysis is unavailable')
  assert.ok(memo.includes('보류'), 'failed analysis explicitly abstains')
  assert.ok(!memo.includes('Synthetic possibility'), 'non-generated payloads must not surface hypotheses')
}
assert.ok(formatRelationalSupervisionMemo({}, originalMemo).startsWith(originalMemo))
const generatedMemo = formatRelationalSupervisionMemo(valid, originalMemo)
assert.ok(generatedMemo.startsWith(`${originalMemo}\n\n`))
for (const expected of [
  '관찰: Synthetic observation', '잠정 가설: Synthetic possibility',
  '대안 설명: Synthetic alternative', '반대 근거·미확인: Synthetic missing context',
  '수퍼비전 질문: Synthetic question?', '축어록: “Synthetic quote”',
  '[1] Synthetic source', 'https://example.org',
]) assert.ok(generatedMemo.includes(expected), `memo must preserve ${expected}`)

const excessive = structuredClone(valid)
excessive.cards = Array.from({ length: 6 }, (_, index) => ({ ...valid.cards[0], id: `synthetic-${index}`, observation: `Observation ${index}` }))
const cappedMemo = formatRelationalSupervisionMemo(excessive, '')
assert.ok(cappedMemo.includes('Observation 3'))
assert.ok(!cappedMemo.includes('Observation 4'), 'at most four cards enter the existing memo')
assert.equal(cappedMemo.split('https://example.org').length - 1, 1, 'shared theory references are listed once')

for (const invalidEvidence of [
  { ...valid, cards: [{ ...valid.cards[0], evidence: [] }] },
  { ...valid, cards: [{ ...valid.cards[0], evidence: [{ source_ref: 'unknown_source', quote: 'Synthetic quote' }] }] },
  { ...valid, cards: [{ ...valid.cards[0], theory_source_ids: ['unknown-theory'] }] },
  { ...valid, theory_sources: [{ ...valid.theory_sources[0], url: 'javascript:alert(1)' }] },
]) {
  const memo = formatRelationalSupervisionMemo(invalidEvidence, originalMemo)
  assert.ok(memo.includes('보류'), 'unconnected session or theory evidence must trigger abstention')
  assert.ok(!memo.includes('Synthetic possibility'))
}
console.log('Relational insight restoration and existing-memo content checks passed.')
