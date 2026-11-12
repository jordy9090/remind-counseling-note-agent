import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

// Synthetic data only. Exercises the pre-generation de-identification review helpers.
async function loadModule(name) {
  const source = fs.readFileSync(`src/lib/${name}.ts`, 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}
const lib = await loadModule('deidentificationReview')

for (const fixture of JSON.parse(fs.readFileSync('../backend/fixtures/korean_person_names.json', 'utf8'))) {
  assert.deepEqual(Object.fromEntries(lib.discoverPersonNames(fixture.text, fixture.known_names)), fixture.names)
  const items = lib.detectLocalDeidItems([fixture.text], { clientName: fixture.known_names?.[0] })
  // Only test name replacements here; institution/date rules have separate coverage below.
  const masked = lib.applyDeidItems(fixture.text, items.filter(item => item.matchMode === 'name'))
  for (const phrase of fixture.preserve ?? []) assert.ok(masked.includes(phrase), `ordinary phrase changed: ${phrase}`)
  for (const [name, owner] of Object.entries(fixture.names)) {
    const item = items.find(i => i.original === name)
    assert.ok(item, `name form missing: ${name}`)
    if (owner) assert.equal(item.replacement, items.find(i => i.original === owner)?.replacement)
    else assert.equal(item.replacement, '인물 확인 필요')
  }
}
{
  const registered = '지혜. 지혜는 안 갔다.'
  assert.equal(lib.applyDeidItems(registered, lib.detectLocalDeidItems([registered], { clientName: '지혜' })), '[내담자 A]. [내담자 A]는 안 갔다.')
  const explicit = '이름: 지원. 지원은 안 갔다. 이름: 사랑. 사랑도 말했다.'
  assert.equal(lib.applyDeidItems(explicit, lib.detectLocalDeidItems([explicit])), '이름: [인물 B]. [인물 B]은 안 갔다. 이름: [인물 C]. [인물 C]도 말했다.')
  const text = '친구 김하린에게 전화했어요. 하린이는 안 갔어요. 누나 김소윤이요. 소윤에게 2번 말했어요.'
  const first = lib.applyDeidItems(text, lib.detectLocalDeidItems([text]))
  assert.equal(first, '친구 [인물 B]에게 전화했어요. [인물 B]이는 안 갔어요. 누나 [인물 C]이요. [인물 C]에게 2번 말했어요.')
  assert.equal(lib.applyDeidItems(first, lib.detectLocalDeidItems([first])), first)
  const longText = '내담자: 지원을 받지 않았다. 2회기다.\n'.repeat(4000) + text
  const longMasked = lib.applyDeidItems(longText, lib.detectLocalDeidItems([longText]))
  assert.ok(longMasked.startsWith('내담자: 지원을 받지 않았다. 2회기다.'))
  assert.ok(!longMasked.includes('김하린') && !longMasked.includes('하린') && !longMasked.includes('김소윤'))
  console.log('shared Korean name/alias boundaries and long-input tail: passed')
}

{
  // Execute the component's real discovery effect: opening review must not send raw text.
  const source = fs.readFileSync('src/components/deidentification/DeidentificationReviewModal.tsx', 'utf8')
  const tree = ts.createSourceFile('modal.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const effects = []
  let submitNode
  function visit(node) {
    if (ts.isCallExpression(node) && node.expression.getText(tree) === 'useEffect') effects.push(node.arguments[0])
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === 'submit') submitNode = node.initializer
    ts.forEachChild(node, visit)
  }
  visit(tree)
  const execute = (node, scope) => new Function(...Object.keys(scope), `${ts.transpile(`const callback = ${node.getText(tree)}`, { target: ts.ScriptTarget.ES2020 })}; return callback()`)(...Object.values(scope))
  let detected
  let detecting = true
  let calls = 0
  const sources = [{ key: 'transcript_text', label: '합성', text: '이름: 윤다온, 가상누리병원에 안 갔다. 2회기다.' }]
  execute(effects[0], {
    initialItems: undefined,
    sources, context: { clientName: '윤다온' }, detectDeidentificationItems: lib.detectDeidentificationItems,
    requestDeidentificationPreview: () => { calls++; throw new Error('raw text left browser') },
    setItems: value => { detected = value }, setDetecting: value => { detecting = value },
  })
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(calls, 0)
  assert.equal(detecting, false)
  assert.ok(detected.some(item => item.original === '가상누리병원'))
  assert.ok(detected.some(item => item.original === '윤다온'))
  for (const confirmed of [false, true]) {
    let result
    execute(submitNode, { detecting: false, requireConfirmation: true, confirmed, skip: true,
      sources, items: detected, applyDeidItems: lib.applyDeidItems, onConfirm: value => { result = value } })
    assert.equal(Boolean(result), confirmed)
    if (result) {
      assert.equal(result.skipped, false, 'mandatory review ignores a stale skip toggle')
      assert.ok(!result.texts.transcript_text.includes('윤다온'))
      assert.ok(!result.texts.transcript_text.includes('가상누리병원'))
      assert.ok(result.texts.transcript_text.includes('안 갔다. 2회기'))
    }
  }
  let confirmed = true
  execute(effects[1], { setConfirmed: value => { confirmed = value } })
  assert.equal(confirmed, false, 'editing the replacement items invalidates confirmation')
  console.log('browser-only review and mandatory confirmation: passed')
}

const transcript = [
  '상담자: 지난주는 어떻게 지내셨어요?',
  '내담자: 제가 가나다이고, 32세 팀장이에요. 나다 씨라고 불러요.',
  '내담자: 2026년 10월 14일에 발표했고 연락은 010-1212-3434나 test.user@example.com으로 주세요.',
  '내담자: 7살 때 이사했어요.',
].join('\n')

{
  const { items, remoteFailed } = await lib.detectDeidentificationItems([transcript], { clientName: '가나다', counselorName: '' })
  assert.equal(remoteFailed, false)
  const byOriginal = Object.fromEntries(items.map((item) => [item.original, item]))
  assert.equal(byOriginal['가나다'].replacement, '내담자 A')
  assert.equal(byOriginal['나다'].replacement, '내담자 A')
  assert.equal(byOriginal['010-1212-3434'].replacement, '010********')
  assert.equal(byOriginal['test.user@example.com'].replacement, 't********@example.com')
  assert.equal(byOriginal['2026년 10월 14일'].replacement, '10월 중순')
  assert.equal(byOriginal['2026년 10월 14일'].kind, 'review')
  assert.equal(byOriginal['32세'].replacement, '30대')
  assert.equal(byOriginal['7살'], undefined, 'past-event ages stay')
  assert.ok(items.every((item) => item.origin === 'detected'))
  console.log('detection: passed')

  const sent = lib.applyDeidItems(transcript, items)
  for (const raw of ['가나다', '나다 씨', '010-1212-3434', 'test.user@example.com', '2026년 10월 14일', '32세']) {
    assert.ok(!sent.includes(raw), `${raw} must not be sent`)
  }
  assert.ok(sent.includes('제가 [내담자 A]이고, [30대] 팀장'))
  assert.ok(sent.includes('[010********]'))
  assert.ok(sent.includes('7살 때'))
  console.log('replacement: passed')
}

{
  // Server items (anyone's name, organizations, ...) are merged; local rules win on duplicates.
  const text = '내담자: 가나다예요. 친구 마바사랑 한빛소프트에 다녀요. 32세예요.'
  const remote = async (texts, context) => {
    assert.deepEqual(texts, [text])
    assert.equal(context.clientName, '가나다')
    return [
      { original: '가나다', replacement: '다른 라벨' },
      { original: '마바사', replacement: '인물 B' },
      { original: '한빛소프트', replacement: '회사' },
      { original: '32세', replacement: '30대' },
      { original: '본문에없음', replacement: 'X' },
    ]
  }
  const merged = await lib.detectDeidentificationItems([text], { clientName: '가나다' }, remote)
  const byOriginal = Object.fromEntries(merged.items.map((item) => [item.original, item.replacement]))
  assert.equal(byOriginal['가나다'], '내담자 A')
  assert.equal(byOriginal['마바사'], '인물 B')
  assert.equal(byOriginal['한빛소프트'], '회사')
  assert.equal(merged.items.filter((item) => item.original === '32세').length, 1)
  assert.equal(byOriginal['본문에없음'], undefined)

  const failed = await lib.detectDeidentificationItems([text], { clientName: '가나다' }, async () => { throw new Error('offline') })
  assert.equal(failed.remoteFailed, true)
  assert.deepEqual(failed.items.map((item) => item.original).sort(), ['32세', '가나다', '마바사'])
  console.log('server merge: passed')
}

{
  // A full name wins over the given-name form inside it; overlapping matches are not doubled.
  const items = [
    { id: 'a', original: '나다', replacement: 'X', kind: 'auto', origin: 'detected' },
    { id: 'b', original: '가나다', replacement: '내담자 A', kind: 'auto', origin: 'detected' },
  ]
  assert.deepEqual(lib.findDeidMatches('가나다와 나다', items), [
    { start: 0, end: 3, itemId: 'b' },
    { start: 5, end: 7, itemId: 'a' },
  ])
  assert.equal(lib.applyDeidItems('가나다와 나다', items), '[내담자 A]와 [X]')
  console.log('overlaps: passed')
}

{
  const items = [{ id: 'n', original: '가나다', replacement: '내담자 A', kind: 'auto', origin: 'manual' }]
  const original = lib.deidSegments('내담자: 가나다예요', items, false)
  assert.deepEqual(original.map((segment) => segment.type), ['speaker', 'text', 'item', 'text'])
  assert.equal(original[2].text, '가나다')
  const replaced = lib.deidSegments('내담자: 가나다예요', items, true)
  assert.equal(replaced[2].text, '[내담자 A]')
  console.log('segments: passed')
}

{
  const sources = lib.sessionReviewSources(
    { transcript_text: '축어록 내용', counselor_memo: '  ', previous_session_summary: '이전 요약' },
    '상담 녹음.txt',
  )
  assert.deepEqual(sources.map((source) => [source.key, source.label]), [
    ['transcript_text', '상담 녹음.txt'],
    ['previous_session_summary', '이전 회기 요약'],
  ])
  assert.deepEqual(lib.sourcesContaining(sources, '이전').map((source) => source.key), ['previous_session_summary'])
  assert.equal(lib.generalizeDate(3, 25), '3월 하순')
  assert.equal(lib.maskPhone('02-123-4567'), '02*******')
  console.log('sources and helpers: passed')
}
