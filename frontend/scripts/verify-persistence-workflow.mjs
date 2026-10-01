import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

async function loadModule(name) {
  let source = fs.readFileSync(`src/lib/${name}.ts`, 'utf8')
  if (name === 'persistenceWorkflow') {
    const dependency = ts.transpileModule(fs.readFileSync('src/lib/relationalInsights.ts', 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
    }).outputText
    source = source.replace("'./relationalInsights'", `'data:text/javascript;base64,${Buffer.from(dependency).toString('base64')}'`)
  }
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}
const workflow = await loadModule('persistenceWorkflow')
const record = (confirmed_json, confirmation_status = 'confirmed') => ({
  note_id: 'synthetic-note', case_id: 'SYNTHETIC', session_number: 1,
  session_date: '2026-09-11', confirmation_status,
  draft_json: { session_content: { text: 'AI original must remain separate' }, next_plan: { text: 'AI plan' } },
  confirmed_json,
})

for (const value of ['Counselor approved', '']) {
  for (const payload of [
    { session_content: value, sections: { session_content: 'stale secondary value' } },
    { session_content: { text: value }, sections: { session_content: 'stale secondary value' } },
    { sections: { session_content: value } },
  ]) {
    assert.equal(workflow.noteFromRecord(record(payload)).session_summary, value)
  }
}
assert.throws(() => workflow.noteFromRecord(record({})), /복원/)
console.log('Confirmed string/object/sections values and intentional empty strings: passed')

// Additional restore and serialization assertions use the same functions as the page.
{
  const bases = ['session_content', 'next_plan'].map(id => ({ id, title: id, content: 'placeholder', visible: true }))
  const approved = record({ session_content: 'Counselor approved', next_plan: '' })
  const sections = workflow.restoreStoredSections(workflow.recordPayload(approved), bases, true)
  assert.deepEqual(sections.map(s => s.content), ['Counselor approved', ''])
  assert.equal(workflow.readStoredText({}, 'next_plan'), undefined)
  assert.equal(workflow.readStoredText({ next_plan: '' }, 'next_plan'), '')
  assert.deepEqual(workflow.restoreStoredSections({ session_content: '' }, bases, true).map(s => s.id), ['session_content'])
  assert.throws(() => workflow.restoreStoredSections({ session_content: 123 }, bases, true), /복원/)
  assert.throws(() => workflow.restoreStoredSections({ unknown: 'not a note' }, bases, true), /복원/)
  assert.throws(() => workflow.restoreStoredSections({ workspace_sections: 'broken' }, bases, true), /복원/)
  const original = structuredClone(approved.draft_json)
  const unsaved = sections.map(s => ({ ...s, content: s.id === 'session_content' ? 'Unsaved counselor edit' : s.content }))
  assert.notEqual(workflow.sectionFingerprint(unsaved), workflow.sectionFingerprint(sections))
  const reconfirmed = workflow.confirmedPayload(approved.confirmed_json, unsaved)
  const reopened = workflow.restoreStoredSections(reconfirmed, bases, true)
  assert.deepEqual(reopened, unsaved)
  assert.equal(reconfirmed.next_plan.text, '')
  assert.deepEqual(approved.draft_json, original)
  const omitted = workflow.confirmedPayload(approved.draft_json, [sections[0]])
  assert.equal(omitted.next_plan, undefined, 'missing confirmed fields must not reappear from AI')
  assert.deepEqual(workflow.restoreStoredSections({ workspace_sections: [] }, bases, true), [])
  assert.equal(workflow.isConfirmedRecord(record({}, 'demo_confirmed')), true)
  for (const value of ['Approved test summary', '']) {
    const optional = workflow.restoreStoredSections({ session_content: 'Approved', psychological_test: value }, bases, true)
    assert.equal(optional.find(s => s.id === 'psychological_test').content, value)
    assert.equal(workflow.confirmedPayload({}, optional).psychological_test.text, value)
  }
  console.log('Restore -> edit -> reconfirm; missing/empty/malformed distinctions and AI immutability: passed')
}

{
  const stored = { counselor_memo: 'Stored memo', transcript_text: 'Stored transcript', previous_session_summary: '',
    counseling_goal: 'Goal', psychological_test_summary: 'Test', key_issue_tags: ['a', 1], nonverbal_notes: 'Notes' }
  const restored = workflow.sessionInputFromRecord({ ...record({}), session_input: stored })
  assert.deepEqual(restored, { ...stored, key_issue_tags: ['a'] })
  assert.equal(workflow.hasRestoredInput(restored), true)
  for (const missing of [undefined, null, 'broken', { transcript_text: 5 }]) {
    const empty = workflow.sessionInputFromRecord({ ...record({}), session_input: missing })
    assert.equal(empty.transcript_text, '')
    assert.equal(empty.counselor_memo, '')
    assert.deepEqual(empty.key_issue_tags, [])
    assert.equal(workflow.hasRestoredInput(empty), false)
  }
  console.log('Stored session input restore (present, missing, malformed): passed')
}

{
  const generated = (text) => ({ full_response: { session_summary_draft: { session_theme: { text } } } })
  assert.equal(workflow.sessionThemeText('', generated(' AI drafted theme ')), 'AI drafted theme')
  assert.equal(workflow.sessionThemeText('Counselor topic', generated('AI drafted theme')), 'Counselor topic')
  // A restored record has no generation response, and a malformed theme must not reach the section.
  for (const result of [{}, { full_response: {} }, generated(undefined), generated(7)]) {
    assert.equal(workflow.sessionThemeText('  ', result), '')
  }
  console.log('Session theme falls back to the generated theme, counselor topic wins: passed')
}

const { temporaryDraftPayload } = await loadModule('temporaryDraft')
const fixture = JSON.parse(fs.readFileSync('scripts/fixtures/temporary-draft.json', 'utf8'))
const originalFixture = structuredClone(fixture)
const saved = temporaryDraftPayload(fixture)
assert(!JSON.stringify(saved).includes('SYNTHETIC-RAW-CACHE'), 'raw caches must not reach the request, even through nested fields')
assert.equal(saved.form.transcript_text, fixture.form.transcript_text)
assert.equal(saved.form.psychological_test_summary, fixture.form.psychological_test_summary)
assert.equal(saved.draft_sections[0].content, fixture.draft_sections[0].content)
assert.equal(saved.final_document_sections[0].content, fixture.final_document_sections[0].content)
assert.equal(saved.final_document_sections[0].contentHtml, fixture.final_document_sections[0].contentHtml)
assert.equal(saved.result.session_summary, 'AI summary')
assert.equal(saved.result.workspace_note_id, 'synthetic-note')
assert.equal(saved.attachments[0].requiresReattachment, true)
assert.equal(saved.attachments[0].dirtySinceApply, true)
assert.deepEqual(saved.attachments[0].appliedTargets, ['transcript_text'])
const block = saved.supervision_report_draft.sections[0].contentBlocks[0]
assert.equal(block.text, 'Counselor report edit')
assert.equal(block.textHtml, '<div><u>Counselor</u> report edit</div>')
assert.deepEqual(block.rows, [{ column: 'Edited table cell' }])
assert.equal(block.speakerTurns[0].text, 'Counselor-selected report excerpt')
assert.deepEqual(temporaryDraftPayload(saved), saved, 'save/read projection must be idempotent')
assert.deepEqual(fixture, originalFixture, 'saving must not mutate in-memory edits or caches on failure')
console.log('Temporary request allowlist, nested caches, applied input, edited reports, and non-mutating serialization: passed')

{
  const insights = { status: 'generated', lens: 'psychodynamic_relational', notices: [],
    cards: [{ id: 'synthetic', focus: 'counselor_reflection', observation: 'Recorded wish to reassure.',
      hypothesis: 'A tentative relational hypothesis.', alternative_explanation: 'An ordinary wish to comfort.',
      counterevidence_or_missing: 'No causal effect is established.', requires_review: true,
      supervision_questions: ['What shaped the next intervention?'],
      evidence: [{ source_ref: 'counselor_memo', quote: 'Synthetic counselor reflection.' }],
      theory_source_ids: ['synthetic-source'] }],
    theory_sources: [{ id: 'synthetic-source', title: 'Synthetic reference', organization: 'Test',
      url: 'https://example.org/synthetic', locator: 'Test', principle: 'Reflection', concepts: [], limitations: 'Test only' }] }
  const draft = { reflection: { text: 'Counselor reflection.' }, relational_insights: insights }
  const bases = [{ id: 'supervision_memo', title: '슈퍼비전 메모', content: '', visible: true }]
  const reopened = workflow.restoreStoredSections(draft, bases, false)
  assert(reopened[0].content.includes('잠정 가설'))
  assert(reopened[0].content.includes('Counselor reflection.'))
  const confirmed = workflow.confirmedPayload(draft, reopened)
  assert.equal(confirmed.relational_insights, undefined)
  assert.equal(confirmed.reflection.text, reopened[0].content, 'explicit confirmation preserves tentative labels')
  assert.deepEqual(workflow.restoreStoredSections(confirmed, bases, true), reopened)
  const savedInsights = temporaryDraftPayload({ form: {}, result: { relational_insights: insights } })
  assert.deepEqual(savedInsights.result.relational_insights, insights)
  assert.deepEqual(temporaryDraftPayload(savedInsights), savedInsights)
  assert.equal(draft.reflection.text, 'Counselor reflection.', 'draft source must not be mutated')
  console.log('Insight draft restore, explicit confirmation, and temporary-save metadata round trip: passed')
}
