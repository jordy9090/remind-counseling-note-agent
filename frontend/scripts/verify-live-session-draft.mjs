import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'remind-live-draft-'))
try {
  const source = fs.readFileSync('src/lib/liveSessionDraft.ts', 'utf8')
  const output = path.join(directory, 'liveSessionDraft.mjs')
  fs.writeFileSync(output, ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText)
  const { buildLiveSessionDraft } = await import(pathToFileURL(output).href)
  const segment = (id, text, values = {}) => ({
    id, segment_id: `live_0_${id}`, start: id * 3, end: id * 3 + 2, text, ...values,
  })
  const input = [
    segment(0, '지난주보다 잠이 좋아지지는 않았어요.'),
    segment(1, '다음 주에 호흡 연습을 해볼까요?'),
    segment(2, '직장 일에 대해서 이야기하고 싶어요.'),
    segment(3, '그 말은 제 친구가 했어요.'),
  ]
  const before = JSON.stringify(input)
  const sections = buildLiveSessionDraft(input)
  const items = sections.flatMap(section => section.items)
  for (const item of items) {
    const original = input.find(candidate => candidate.segment_id === item.segmentId)
    assert.ok(original, 'every draft item must refer to an actual transcript segment')
    assert.equal(item.quote, original.text, 'negation, questions and reported speech must stay verbatim')
    assert.equal(item.start, original.start)
    assert.equal(item.end, original.end)
  }
  assert.equal(JSON.stringify(input), before, 'building a draft must not edit the source transcript')
  assert.ok(sections.find(section => section.id === 'change').items.some(item => item.segmentId === 'live_0_0'))
  assert.ok(sections.find(section => section.id === 'next').items.some(item => item.segmentId === 'live_0_1'))
  assert.ok(!JSON.stringify(sections).includes('상담사 개입'), 'unknown roles cannot become clinical findings')

  const corrected = buildLiveSessionDraft([
    segment(0, '잠이 좋아졌어요.'), segment(0, '잠이 좋아지지는 않았어요.'),
  ]).flatMap(section => section.items)
  assert.ok(corrected.length)
  assert.ok(corrected.every(item => item.quote === '잠이 좋아지지는 않았어요.'), 'a correction must remove the old claim')
  const repeated = buildLiveSessionDraft([segment(0, '오늘은 그냥 이야기했어요.'), segment(1, '오늘은 그냥 이야기했어요.')])
  assert.equal(repeated.find(section => section.id === 'other').items.length, 2, 'distinct source turns must survive text deduplication')

  const long = Array.from({ length: 25 }, (_, index) => segment(index, `직장에서 있었던 일 ${index}`))
  const context = buildLiveSessionDraft(long).find(section => section.id === 'context')
  assert.equal(context.items.length, 12)
  assert.equal(context.omittedCount, 13, 'a bounded preview must disclose older hidden items')
  assert.equal(context.items[0].segmentId, 'live_0_13')
  assert.equal(long.length, 25, 'the full transcript remains available')

  const invalid = buildLiveSessionDraft([
    segment(0, ' '), segment(1, '잠이', { start: Number.NaN }),
    segment(2, '직장', { end: -1 }), segment(3, '다음 주', { end: Number.POSITIVE_INFINITY }),
    segment(4, '지난주', { end: 12 }),
  ])
  assert.equal(invalid.flatMap(section => section.items).length, 0)
  assert.equal(buildLiveSessionDraft([]).flatMap(section => section.items).length, 0)
  console.log('Live draft: evidence links, corrections, negation, unknown roles and bounded previews passed.')
} finally {
  fs.rmSync(directory, { recursive: true, force: true })
}
