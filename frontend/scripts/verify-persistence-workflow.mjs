import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

async function loadModule(name) {
  const source = fs.readFileSync(`src/lib/${name}.ts`, 'utf8')
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

const { temporaryDraftPayload } = await loadModule('temporaryDraft')
const fixture = JSON.parse(fs.readFileSync('scripts/fixtures/temporary-draft.json', 'utf8'))
const originalFixture = structuredClone(fixture)
const saved = temporaryDraftPayload(fixture)
assert(!JSON.stringify(saved).includes('SYNTHETIC-RAW-CACHE'), 'raw caches must not reach the request, even through nested fields')
assert.equal(saved.form.transcript_text, fixture.form.transcript_text)
assert.equal(saved.form.psychological_test_summary, fixture.form.psychological_test_summary)
assert.equal(saved.draft_sections[0].content, fixture.draft_sections[0].content)
assert.equal(saved.final_document_sections[0].content, fixture.final_document_sections[0].content)
assert.equal(saved.result.session_summary, 'AI summary')
assert.equal(saved.result.workspace_note_id, 'synthetic-note')
assert.equal(saved.attachments[0].requiresReattachment, true)
assert.equal(saved.attachments[0].dirtySinceApply, true)
assert.deepEqual(saved.attachments[0].appliedTargets, ['transcript_text'])
const block = saved.supervision_report_draft.sections[0].contentBlocks[0]
assert.equal(block.text, 'Counselor report edit')
assert.deepEqual(block.rows, [{ column: 'Edited table cell' }])
assert.equal(block.speakerTurns[0].text, 'Counselor-selected report excerpt')
assert.deepEqual(temporaryDraftPayload(saved), saved, 'save/read projection must be idempotent')
assert.deepEqual(fixture, originalFixture, 'saving must not mutate in-memory edits or caches on failure')
console.log('Temporary request allowlist, nested caches, applied input, edited reports, and non-mutating serialization: passed')
