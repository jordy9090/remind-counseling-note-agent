import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const ts = require(process.env.TYPESCRIPT_MODULE || 'typescript')
const source = fs.readFileSync(new URL('../src/pages/SessionDraftPage.tsx', import.meta.url), 'utf8')
const ast = ts.createSourceFile('SessionDraftPage.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

function callback(name, dependencies) {
  let declaration
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name) declaration = node
    ts.forEachChild(node, visit)
  }
  visit(ast)
  assert.ok(declaration?.initializer, `Expected the real ${name} page callback`)
  const compiled = ts.transpileModule(`const handler = ${declaration.initializer.getText(ast)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText
  return new Function(...Object.keys(dependencies), `${compiled}; return handler`)(...Object.values(dependencies))
}

function harness({ failure = false, failuresBeforeSuccess = 0, accepted = true, noteId = 'synthetic-note', originalPresent = true } = {}) {
  const finalNote = { sections: { session_content: 'Synthetic confirmed note, preserved exactly.' } }
  const originals = { counselor_memo: 'Synthetic private memo', transcript_text: 'Synthetic private transcript',
    previous_session_summary: 'Synthetic previous input', counseling_goal: 'Synthetic goal',
    psychological_test_summary: 'Synthetic test', nonverbal_notes: 'Synthetic observation', key_issue_tags: ['synthetic'] }
  const state = { form: { case_id: 'synthetic-case', session_number: 1, ...originals },
    storedNote: { note_id: noteId, confirmed_json: finalNote,
      session_input: originalPresent ? { ...originals } : null, session_input_is_original: originalPresent },
    finalDocumentSections: [{ id: 'summary', content: finalNote.sections.session_content }],
    materials: [{ file: { name: 'synthetic.wav' } }], message: null, error: null, busy: false }
  const preserved = structuredClone({ note: finalNote, sections: state.finalDocumentSections })
  const deleted = ['sessions.raw_input_text (입력 원문)', 'sessions.sanitized_input_text (가린 입력 사본)',
    'transcript_turns (발화)', 'transcript_windows (검색 구간과 임베딩)']
  const kept = ['generated_notes (AI 요약 초안과 상담사 확정본)', 'evidence_items (요약 근거 문장)',
    'case_memory (확정본에서 만든 회기 기억)', 'counseling_drafts (상담사가 임시저장한 작업)',
    'future_copy (서버가 추가로 알려준 보관 자료)']
  const calls = [], confirmations = [], cleared = [], revoked = []
  const setter = key => value => { state[key] = typeof value === 'function' ? value(state[key]) : value }
  const runPersistence = callback('runPersistence', {
    persistenceLock: { current: false }, isLoading: false, setIsPersistenceBusy: setter('busy'),
    setPersistenceError: setter('error'), setDraftSaveMessage: setter('message'),
    persistenceErrorMessage: () => 'Synthetic deletion failure',
  })
  let pending
  const remove = callback('deleteStoredInput', {
    storedNoteId: noteId, window: { confirm: message => { confirmations.push(message); return accepted } },
    runPersistence: operation => { pending = runPersistence(operation); return pending },
    deleteSessionInput: async id => {
      calls.push(id)
      if (failure || failuresBeforeSuccess-- > 0) throw new Error('Synthetic private backend failure')
      return { note_id: id, session_id: 'synthetic-session', deleted, kept }
    },
    setForm: setter('form'), materialsRef: { current: state.materials },
    clearHostedAudioCheckpoint: file => cleared.push(file), objectUrlsRef: { current: new Set(['blob:synthetic']) },
    URL: { revokeObjectURL: value => revoked.push(value) }, setMaterials: setter('materials'),
    setStoredNote: setter('storedNote'), setDraftSaveMessage: setter('message'),
  })
  return { state, preserved, calls, confirmations, cleared, revoked, kept,
    async remove() { remove(); await pending } }
}

test('confirmation and completion disclose retained drafts and memory using the backend scope', async () => {
  const h = harness()
  await h.remove()
  assert.match(h.confirmations[0], /임시저장/)
  assert.match(h.confirmations[0], /회기 기억/)
  assert.match(h.confirmations[0], /입력 내용/)
  assert.match(h.confirmations[0], /새 입력은 새 회기에 저장/)
  for (const entry of h.kept) assert.ok(h.state.message.includes(entry.match(/\((.+)\)$/)[1]))
  assert.match(h.state.message, /입력 원문/)
  assert.match(h.state.message, /가린 입력 사본/)
  assert.match(h.state.message, /새 입력은 새 회기에 저장/)
  assert.doesNotMatch(h.state.message, /sessions\.|counseling_drafts|future_copy|Synthetic private/)
  assert.deepEqual(h.calls, ['synthetic-note'])
})

test('successful deletion clears current source copies and preserves the confirmed and final note', async () => {
  for (const originalPresent of [true, false]) {
    const h = harness({ originalPresent })
    await h.remove()
    for (const field of ['counselor_memo', 'transcript_text', 'previous_session_summary', 'counseling_goal',
      'psychological_test_summary', 'nonverbal_notes']) assert.equal(h.state.form[field], '')
    assert.deepEqual(h.state.form.key_issue_tags, [])
    assert.equal(h.state.form.case_id, 'synthetic-case')
    assert.equal(h.state.storedNote.session_input, null)
    assert.equal(h.state.storedNote.session_input_is_original, false)
    assert.deepEqual(h.state.storedNote.confirmed_json, h.preserved.note)
    assert.deepEqual(h.state.finalDocumentSections, h.preserved.sections)
    assert.deepEqual(h.state.materials, [])
    assert.equal(h.cleared.length, 1)
    assert.deepEqual(h.revoked, ['blob:synthetic'])
    assert.equal(h.state.error, null)
    assert.equal(h.state.busy, false)
  }
})

test('failed deletion never claims success or clears the current input', async () => {
  const h = harness({ failure: true })
  const before = structuredClone(h.state)
  await h.remove()
  assert.equal(h.state.message, null)
  assert.equal(h.state.error, 'Synthetic deletion failure')
  assert.deepEqual(h.state.form, before.form)
  assert.deepEqual(h.state.storedNote, before.storedNote)
  assert.deepEqual(h.state.finalDocumentSections, before.finalDocumentSections)
  assert.equal(h.cleared.length, 0)
  assert.equal(h.revoked.length, 0)
  assert.equal(h.state.busy, false)
})

test('cancelled confirmation and missing notes do not issue a deletion', async () => {
  for (const options of [{ accepted: false }, { noteId: null }]) {
    const h = harness(options)
    const before = structuredClone(h.state)
    await h.remove()
    assert.deepEqual(h.calls, [])
    assert.deepEqual(h.state, before)
  }
})

test('retry after an uncertain deletion failure clears sources only on confirmation', async () => {
  const h = harness({ failuresBeforeSuccess: 1 })
  const before = structuredClone(h.state)
  await h.remove()
  assert.deepEqual(h.state.form, before.form)
  assert.equal(h.state.message, null)
  assert.equal(h.state.error, 'Synthetic deletion failure')
  await h.remove()
  assert.deepEqual(h.calls, ['synthetic-note', 'synthetic-note'])
  assert.equal(h.state.error, null)
  assert.equal(h.state.busy, false)
  assert.equal(h.state.storedNote.session_input, null)
  assert.equal(h.state.form.transcript_text, '')
  assert.deepEqual(h.state.storedNote.confirmed_json, h.preserved.note)
  assert.deepEqual(h.state.finalDocumentSections, h.preserved.sections)
  assert.equal(h.cleared.length, 1)
  assert.deepEqual(h.revoked, ['blob:synthetic'])
})
