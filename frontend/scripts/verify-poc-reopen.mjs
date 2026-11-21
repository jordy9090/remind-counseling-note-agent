// Exercise saved-record projections with synthetic data; no app, account, or service.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { test } from 'node:test'
const require = createRequire(import.meta.url)
const ts = require('typescript')

function moduleUrl(name) {
  let source = readFileSync(`src/lib/${name}.ts`, 'utf8')
  source = source.replace(/from '(\.\/[^']+)'/g, (_, dependency) => `from '${moduleUrl(dependency.slice(2))}'`)
  const js = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext,
  } }).outputText
  return 'data:text/javascript;base64,' + Buffer.from(js).toString('base64')
}

const workflow = await import(moduleUrl('persistenceWorkflow'))
const { noteFromRecord, sessionInputFromRecord, confirmedPayload } = workflow
const { buildGroundingReviewItems } = await import(moduleUrl('groundingReview'))
const summary = 'Synthetic unchanged confirmed observation.'
const excerpt = '[client] Synthetic retained excerpt.'
const grounding = {
  enabled: true,
  context: {
    needs: [], need_to_evidence_ids: { N1: ['R1'] }, diagnostics: {},
    sources: [{ evidence_id: 'R1', source_type: 'raw_transcript', source_ref: 'transcript:synthetic-prior:0-0',
      session_id: 'synthetic-prior', session_number: 1, source_text: excerpt, retrieval_method: 'synthetic', need_ids: ['N1'] }],
  },
  claims: [{ claim_id: 'C1', need_id: 'N1', target_field: 'session_content', text: summary,
    claim_kind: 'factual', support_type: 'direct_evidence', evidence_ids: ['R1'], review_required: false }],
  claim_support_validations: { C1: { verdict: 'supported', supported_evidence_ids: ['R1'] } },
  citation_diagnostics: [], metrics: {},
}
const saved = {
  note_id: 'synthetic-note', case_id: 'SYNTHETIC', session_id: 'synthetic-current', session_number: 2,
  session_date: '2026-11-19', note_type: 'session_note', confirmation_status: 'confirmed',
  draft_json: { session_info: { case_id: 'SYNTHETIC', session_number: 2 }, session_content: { text: summary }, grounding },
  confirmed_json: { session_content: { text: summary } },
  session_input: { transcript_text: 'Synthetic input to remove.' },
}
const afterDeletion = { ...saved, session_input: null }
const items = record => buildGroundingReviewItems(noteFromRecord(record).grounding, 'session_content')
const copy = () => structuredClone(afterDeletion)

test('deleted input stays absent while the exact final note remains readable', () => {
  assert.equal(noteFromRecord(afterDeletion).session_summary, summary)
  assert.equal(sessionInputFromRecord(afterDeletion).transcript_text, '')
})

test('reopening after deletion clears every input field without reusing a prior record or saved excerpt', () => {
  const record = copy()
  const original = 'SYNTHETIC-DELETED-INPUT-ONLY'
  const input = { counselor_memo: original, transcript_text: original, previous_session_summary: original,
    counseling_goal: original, psychological_test_summary: original, key_issue_tags: [original], nonverbal_notes: original }
  const before = { ...record, session_input: input }
  assert.equal(sessionInputFromRecord(before).transcript_text, original)
  // Legacy payload copies must not become an alternative input restoration source.
  record.draft_json.session_input = input
  record.draft_json.sources = input
  record.confirmed_json.session_input = input
  const restored = sessionInputFromRecord(record)
  for (const field of Object.keys(input)) assert.deepEqual(restored[field], field === 'key_issue_tags' ? [] : '')
  assert.equal(JSON.stringify(restored).includes(original), false)
  assert.equal(JSON.stringify(restored).includes(excerpt), false)
  assert.equal(noteFromRecord(record).session_summary, summary)
})

test('unchanged owned final and draft records retain the exact saved excerpt before and after deletion', () => {
  assert.equal(buildGroundingReviewItems(grounding, 'session_content')[0].sources[0].source_text, excerpt)
  for (const record of [saved, afterDeletion, { ...afterDeletion, confirmation_status: 'draft' }]) {
    const reopened = items(record)
    assert.equal(reopened.length, 1)
    assert.deepEqual(reopened[0].sources, grounding.context.sources)
    assert.equal(reopened[0].stale, false)
    assert.equal(reopened[0].missingSource, false)
  }
})

test('prior counselor note references and clinical inference preserve their distinct review states', () => {
  const record = copy()
  record.draft_json.grounding.context.sources[0] = { ...grounding.context.sources[0],
    source_type: 'counselor_confirmed', source_ref: 'confirmed_note:synthetic-prior-note:reflection' }
  record.draft_json.grounding.claims[0].support_type = 'counselor_judgment'
  assert.equal(items(record)[0].sources[0].session_id, 'synthetic-prior')
  assert.equal(items(record)[0].claim.support_type, 'counselor_judgment')
  record.draft_json.grounding.claims[0].support_type = 'clinical_inference'
  record.draft_json.grounding.claim_support_validations = {}
  assert.equal(items(record)[0].sources.length, 1)
  assert.equal(items(record)[0].claim.support_type, 'clinical_inference')
})

test('changed canonical and workspace text marks the historical claim stale', () => {
  for (const confirmed_json of [
    { session_content: 'Synthetic counselor edit.' },
    { sections: { session_content: 'Synthetic counselor edit.' } },
    { session_content: { text: summary }, workspace_sections: [
      { id: 'session_content', title: '상담 내용', content: 'Synthetic counselor edit.', visible: true },
    ] },
  ]) {
    const reopened = items({ ...afterDeletion, confirmed_json })
    assert.equal(reopened.length, 1)
    assert.equal(reopened[0].stale, true)
    assert.equal(reopened[0].sources[0].source_text, excerpt, 'historical evidence remains available for re-review')
  }
  const draftOverlay = copy()
  draftOverlay.confirmation_status = 'draft'
  draftOverlay.draft_json.workspace_sections = [
    { id: 'session_content', title: '상담 내용', content: 'Synthetic edited draft overlay.', visible: true },
  ]
  assert.equal(items(draftOverlay)[0].stale, true, 'a draft workspace overlay is not the original validated AI text')
})

test('reconfirmation preserves original evidence only as stale history after an edit', () => {
  const confirmed_json = confirmedPayload(saved.draft_json, [
    { id: 'session_content', title: '상담 내용', content: 'Synthetic edited assertion.', visible: true },
  ])
  assert.equal(confirmed_json.grounding, undefined)
  const reopened = items({ ...afterDeletion, confirmed_json })
  assert.equal(reopened[0]?.stale, true)
  assert.equal(noteFromRecord({ ...afterDeletion, confirmed_json }).session_summary, 'Synthetic edited assertion.')
})

test('reopened claims must occur within both saved AI and displayed text in one direction', () => {
  for (const claimText of ['Synthetic unrelated observation.', summary + ' Synthetic unsupported extension.', '', ' ... ']) {
    const record = copy()
    record.draft_json.grounding.claims[0].text = claimText
    assert.equal(items(record)[0].stale, true, 'an unchanged field does not validate an unrelated or longer claim')
  }
  const normalized = copy()
  normalized.draft_json.grounding.claims[0].text = 'synthetic unchanged\nconfirmed observation'
  assert.equal(items(normalized)[0].stale, false, 'formatting normalization preserves an actually contained claim')
  const removed = copy()
  removed.confirmed_json.session_content.text = 'Synthetic unchanged'
  assert.equal(items(removed)[0].stale, true, 'a shorter displayed field must not inherit support from the longer claim')
})

test('direct and counselor claims without evidence IDs remain explicitly unavailable', () => {
  for (const supportType of ['direct_evidence', 'counselor_judgment']) {
    const record = copy()
    record.draft_json.grounding.claims[0].support_type = supportType
    record.draft_json.grounding.claims[0].evidence_ids = []
    record.draft_json.grounding.claim_support_validations.C1.supported_evidence_ids = []
    assert.deepEqual(items(record)[0].sources, [])
    assert.equal(items(record)[0].missingSource, true)
  }
})

test('missing or blank retained sources remain explicitly unavailable without input reconstruction', () => {
  for (const sources of [[], [{ ...grounding.context.sources[0], source_text: '' }]]) {
    const record = copy()
    record.draft_json.grounding.context.sources = sources
    const reopened = items(record)
    assert.equal(reopened.length, 1)
    assert.equal(reopened[0].missingSource, true)
    assert.deepEqual(reopened[0].sources, [])
  }
})

test('unsupported and unvalidated claims never inherit a validated link', () => {
  for (const verdict of ['unsupported', 'partial', undefined]) {
    const record = copy()
    record.draft_json.grounding.claim_support_validations = verdict
      ? { C1: { verdict, supported_evidence_ids: ['R1'] } } : {}
    const reopened = items(record)
    assert.equal(reopened.length, 1)
    assert.deepEqual(reopened[0].sources, [])
    assert.equal(reopened[0].missingSource, true)
  }
  const record = copy()
  record.draft_json.grounding.claims[0].support_type = 'unsupported'
  assert.deepEqual(items(record)[0].sources, [])
})

test('confirmed payload grounding cannot replace the original authorized snapshot', () => {
  const record = copy()
  record.confirmed_json.grounding = structuredClone(grounding)
  record.confirmed_json.grounding.context.sources[0].source_text = 'SYNTHETIC-FOREIGN-SNAPSHOT'
  assert.equal(items(record)[0]?.sources[0].source_text, excerpt)
})

test('mismatched record identity and foreign or duplicate source IDs fail closed', () => {
  for (const change of [
    record => { record.draft_json.session_info.case_id = 'SYNTHETIC-FOREIGN' },
    record => { record.draft_json.session_info.session_number = 99 },
    record => { record.draft_json.grounding.session_id = 'synthetic-foreign' },
  ]) {
    const record = copy()
    change(record)
    assert.deepEqual(items(record), [])
  }
  for (const change of [
    source => ({ ...source, case_id: 'SYNTHETIC-FOREIGN' }),
    source => ({ ...source, session_id: 'synthetic-foreign' }),
  ]) {
    const record = copy()
    record.draft_json.grounding.context.sources = [change(grounding.context.sources[0])]
    assert.deepEqual(items(record)[0]?.sources, [])
    assert.equal(items(record)[0]?.missingSource, true)
  }
  const duplicate = copy()
  duplicate.draft_json.grounding.context.sources.push({ ...grounding.context.sources[0], source_text: 'SYNTHETIC-AMBIGUOUS' })
  assert.deepEqual(items(duplicate)[0]?.sources, [])
})

test('malformed or absent grounding does not prevent reading the saved final note', () => {
  for (const value of [undefined, null, {}, { enabled: true }, { ...grounding, claims: [null] }]) {
    const record = copy()
    record.draft_json.grounding = value
    assert.equal(noteFromRecord(record).session_summary, summary)
    assert.doesNotThrow(() => items(record))
  }
})

test('the real restore callback replaces stale input and carries reopened evidence through current main', async () => {
  const source = readFileSync('src/pages/SessionDraftPage.tsx', 'utf8')
  const ast = ts.createSourceFile('SessionDraftPage.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let declaration
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'restoreNote') declaration = node
    ts.forEachChild(node, visit)
  }
  visit(ast)
  assert.ok(declaration?.initializer, 'exercise the actual saved-note restore callback')
  const compiled = ts.transpileModule(`const restore = ${declaration.initializer.getText(ast)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText
  for (const scenario of ['unchanged', 'edited', 'missing', 'foreign']) {
    const record = copy()
    const oldInput = 'SYNTHETIC-PREVIOUS-SCREEN-INPUT'
    if (scenario === 'edited') record.confirmed_json.session_content.text = 'Synthetic edited final assertion.'
    if (scenario === 'missing') record.draft_json.grounding.context.sources = []
    if (scenario === 'foreign') record.draft_json.grounding.context.sources[0].case_id = 'SYNTHETIC-FOREIGN'
    const state = { form: { transcript_text: oldInput }, result: { old: true }, sections: [], materials: ['synthetic.wav'] }
    const set = key => value => { state[key] = value }
    const noop = () => {}
    let pending
    let cleared = 0
    const dependencies = {
      ...workflow, storedNoteId: null, confirmedFingerprint: null, draftSections: [], allowRestore: () => true,
      runPersistence: operation => { pending = operation() },
      loadGeneratedNote: async id => { assert.equal(id, record.note_id); return record },
      initialForm: { transcript_text: oldInput, counselor_memo: oldInput, key_issue_tags: [oldInput] },
      registeredClientName: () => '', defaultVisibleSectionIds: new Set(['session_content']),
      // Layout/rendering has separate coverage; this boundary checks the callback's real projection and state writes.
      buildDocumentSections: data => [{ id: 'session_content', title: '상담 내용', content: data.session_summary,
        visible: true, groundingItems: buildGroundingReviewItems(data.grounding, 'session_content') }],
      emptyRestoredSection: id => { throw new Error(`Unexpected synthetic section ${id}`) },
      buildSourceBadges: () => [], setForm: set('form'), setResult: set('result'), setDraftSections: set('sections'),
      setStoredNote: set('record'), setMaterials: set('materials'),
      setSessionTopic: noop, setVisibleSectionIds: noop, setStoredNoteId: noop, setConfirmedFingerprint: noop,
      setSavedDraft: noop, setSelectedPreviousSessionIds: noop, setFinalDocumentSections: noop,
      setSupervisionReportDraft: noop, setCurrentScreen: noop, resetRestoredUi: noop, setDraftSaveMessage: noop,
      materialsRef: { current: [{ file: 'synthetic.wav' }] }, clearHostedAudioCheckpoint: () => { cleared++ },
      objectUrlsRef: { current: new Set(['blob:synthetic']) }, URL: { revokeObjectURL: noop }, window: { scrollTo: noop },
    }
    const restore = new Function(...Object.keys(dependencies), `${compiled}; return restore`)(...Object.values(dependencies))
    restore(record.note_id)
    await pending
    assert.equal(state.record, record)
    assert.equal(state.form.transcript_text, '')
    assert.equal(state.form.counselor_memo, '')
    assert.deepEqual(state.form.key_issue_tags, [])
    assert.equal(JSON.stringify(state.form).includes(oldInput), false)
    assert.equal(JSON.stringify(state.form).includes(excerpt), false)
    assert.deepEqual(state.materials, [])
    assert.equal(cleared, 1)
    assert.equal(state.sections[0].content, record.confirmed_json.session_content.text)
    const item = state.sections[0].groundingItems[0]
    assert.equal(item.stale, scenario === 'edited')
    assert.equal(item.missingSource, ['missing', 'foreign'].includes(scenario))
    assert.equal(item.sources.length, ['missing', 'foreign'].includes(scenario) ? 0 : 1)
  }
})

test('rendered evidence panels never show a valid badge for changed or unavailable sources', async () => {
  const component = readFileSync('src/components/note/GroundingEvidenceReview.tsx', 'utf8')
  const js = ts.transpileModule(component, { compilerOptions: {
    target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText.replace(/from ["']([^"']+)["']/g, (_, name) => `from '${name === '../../lib/groundingReview'
    ? moduleUrl('groundingReview') : pathToFileURL(require.resolve(name)).href}'`)
  const { EvidenceSourcePanel } = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))
  const { createElement } = require('react')
  const { renderToStaticMarkup } = require('react-dom/server')
  const render = item => renderToStaticMarkup(createElement(EvidenceSourcePanel, { item, onClose() {} }))
  const valid = items(afterDeletion)[0]
  assert.match(render(valid), /근거 확인/)
  assert.match(render(valid), /Synthetic retained excerpt/)
  const edited = items({ ...afterDeletion, confirmed_json: { session_content: 'Synthetic edit.' } })[0]
  assert.doesNotMatch(render(edited), /근거 확인/)
  assert.match(render(edited), /수정 후 근거 재확인 필요/)
  for (const change of [
    record => { record.draft_json.grounding.context.sources = [] },
    record => { record.draft_json.grounding.claim_support_validations = {} },
    record => { record.draft_json.grounding.context.sources[0].case_id = 'SYNTHETIC-FOREIGN' },
    record => { record.draft_json.grounding.claims[0].evidence_ids = [] },
  ]) {
    const record = copy()
    change(record)
    assert.doesNotMatch(render(items(record)[0]), /근거 확인/)
    assert.match(render(items(record)[0]), /근거 정보를 불러올 수 없습니다/)
    assert.doesNotMatch(render(items(record)[0]), /Synthetic retained excerpt/)
  }
  const unrelated = copy()
  unrelated.draft_json.grounding.claims[0].text = 'Synthetic unrelated observation.'
  assert.doesNotMatch(render(items(unrelated)[0]), /근거 확인/)
  assert.match(render(items(unrelated)[0]), /수정 후 근거 재확인 필요/)
})
