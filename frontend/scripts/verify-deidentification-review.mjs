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

const transcript = [
  '상담자: 지난주는 어떻게 지내셨어요?',
  '내담자: 제가 가나다이고, 32세 팀장이에요. 나다 씨라고 불러요.',
  '내담자: 2026년 10월 14일에 발표했고 연락은 010-1212-3434나 test.user@example.com으로 주세요.',
  '내담자: 7살 때 이사했어요.',
].join('\n')

{
  const items = await lib.detectDeidentificationItems([transcript], { clientName: '가나다', counselorName: '' })
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
