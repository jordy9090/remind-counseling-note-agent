import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

// Synthetic data only. Exercises the person matching step between de-identification review and summary.
function transpile(name) {
  const source = fs.readFileSync(`src/lib/${name}.ts`, 'utf8')
  return ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  }).outputText
}
const toUrl = (code) => `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`
const reviewUrl = toUrl(transpile('deidentificationReview'))
const lib = await import(toUrl(transpile('personMapping').replace("'./deidentificationReview'", `'${reviewUrl}'`)))
const review = await import(reviewUrl)

const link = (mapping, text, personId) => ({
  ...mapping,
  mentions: mapping.mentions.map((mention) => (mention.text === text ? { ...mention, personId } : mention)),
})

// One friend called by a name, a misheard name, a nickname and a relation.
{
  const transcript = [
    '내담자: [인물 B]랑 어제 싸웠어요. 베프라서 더 속상해요.',
    '상담자: [인물 C]하고는 화해했나요?',
    '내담자: 아뇨, 친구가 먼저 연락을 안 해요. 친구들은 다 알아요.',
    '내담자: 엄마는 몰라요.',
  ].join('\n')
  let mapping = lib.detectPersonMapping([transcript])
  const b = mapping.persons.find((person) => person.label === '인물 B')
  const c = mapping.persons.find((person) => person.label === '인물 C')
  assert.ok(b && c, 'each de-identification label starts as its own person')
  assert.deepEqual(mapping.mentions.map((mention) => mention.text).sort(), ['[인물 B]', '[인물 C]', '베프', '엄마', '친구'].sort())
  assert.equal(mapping.mentions.find((mention) => mention.text === '친구').count, 1, '"친구들" is not the same expression')
  assert.equal(lib.applyPersonMapping(transcript, mapping), transcript, 'nothing changes before the counselor links expressions')

  mapping = link(link(link(mapping, '[인물 C]', b.id), '베프', b.id), '친구', b.id)
  assert.equal(
    lib.applyPersonMapping(transcript, mapping),
    [
      '내담자: [인물 B]랑 어제 싸웠어요. 베프[인물 B]라서 더 속상해요.',
      '상담자: [인물 B]하고는 화해했나요?',
      '내담자: 아뇨, 친구[인물 B]가 먼저 연락을 안 해요. 친구들은 다 알아요.',
      '내담자: 엄마는 몰라요.',
    ].join('\n'),
  )
  const once = lib.applyPersonMapping(transcript, mapping)
  assert.equal(lib.applyPersonMapping(once, mapping), once, 'applying twice does not stack labels')
  assert.deepEqual(lib.personDictionary(mapping).map((entry) => [entry.person.label, entry.expressions.sort()]), [
    ['인물 B', ['[인물 B]', '[인물 C]', '베프', '친구'].sort()],
  ])
}

// A relation word directly before its person's label is not labelled twice.
{
  const text = '친구 [인물 B]랑 싸웠어요. 친구 [인물 C]도요. 친구가 미워요.'
  let mapping = lib.detectPersonMapping([text])
  const b = mapping.persons.find((person) => person.label === '인물 B')
  mapping = link(link(mapping, '친구', b.id), '[인물 C]', b.id)
  assert.equal(lib.applyPersonMapping(text, mapping), '친구 [인물 B]랑 싸웠어요. 친구 [인물 B]도요. 친구[인물 B]가 미워요.')
}

// A misheard name the review missed is added by hand and hidden once linked.
{
  const text = '내담자: [인물 B]가 그랬어요. 서연이가 또 그러더라고요.'
  const mapping = lib.detectPersonMapping([text])
  const result = lib.manualMention([text], mapping, '서연', 'replace')
  assert.ok('mention' in result)
  assert.equal(result.mention.count, 1)
  assert.deepEqual(lib.manualMention([text], mapping, '없는말', 'replace'), { error: '상담 내용에서 찾을 수 없는 표현이에요. 똑같이 입력해주세요.' })
  const b = mapping.persons.find((person) => person.label === '인물 B')
  const linked = { ...mapping, mentions: [...mapping.mentions, { ...result.mention, personId: b.id }] }
  assert.equal(lib.applyPersonMapping(text, linked), '내담자: [인물 B]가 그랬어요. [인물 B]이가 또 그러더라고요.')
}

// Unresolved names stay visible as a warning; a new person gets the next free label.
{
  const text = '친구 김하린에게 전화했어요. [인물 확인 필요]도 왔어요. [인물 B]는 안 왔어요.'
  const mapping = lib.detectPersonMapping([text])
  assert.deepEqual(lib.unresolvedNameMentions(mapping).map((mention) => mention.text).sort(), ['[인물 확인 필요]', '김하린'].sort())
  const created = lib.createPerson(mapping.persons)
  assert.equal(created.label, '인물 C')
  const linked = link(link({ ...mapping, persons: [...mapping.persons, created] }, '김하린', created.id), '[인물 확인 필요]', created.id)
  assert.deepEqual(lib.unresolvedNameMentions(linked), [])
  assert.equal(lib.applyPersonMapping(text, linked), '친구 [인물 C]에게 전화했어요. [인물 C]도 왔어요. [인물 B]는 안 왔어요.')
}

// Relation words inside other words or labels are left alone.
{
  const text = '[상담자]: 남자친구와 형편은 어때요? 형이 왔어요. 딸기를 샀어요.'
  const mapping = lib.detectPersonMapping([text])
  assert.deepEqual(mapping.mentions.map((mention) => mention.text).sort(), ['남자친구', '형'].sort())
  assert.equal(lib.nextPersonLabel(mapping.persons), '인물 B')
}

// The client's 인물 사전 carries labels from one session to the next.
{
  const sortedPeople = (people) => people.map((p) => ({ ...p, names: [...p.names].sort(), relations: [...p.relations].sort() }))
    .sort((a, b) => a.label.localeCompare(b.label))

  // Session 1: the review finds 김서영/서영; the counselor links 베프, 친구 and the misheard 서연.
  const first = '내담자: 친구 김서영이랑 싸웠어요. 서영이가 베프라서요. 서연이가 먼저 연락을 안 해요.'
  const firstItems = review.detectLocalDeidItems([first])
  const firstText = review.applyDeidItems(first, firstItems)
  let mapping = lib.detectPersonMapping([firstText])
  const b = mapping.persons.find((person) => person.label === '인물 B')
  const seoyeon = lib.manualMention([firstText], mapping, '서연', 'replace').mention
  mapping = { ...mapping, mentions: [...mapping.mentions, seoyeon] }
  mapping = link(link(link(mapping, '베프', b.id), '친구', b.id), '서연', b.id)
  const afterFirst = lib.updatedPersonDictionary([], mapping, firstItems)
  assert.deepEqual(sortedPeople(afterFirst), [{ label: '인물 B', names: ['김서영', '서연', '서영'], relations: ['베프', '친구'] }])

  // Session 2: stored names keep 인물 B (even the misheard one); a new person skips the stored label.
  const second = '내담자: 서연이가 또 연락했어요. 베프니까 받았죠. 선배 박민준이 일을 넘겨요.'
  const secondItems = review.detectLocalDeidItems([second], { people: afterFirst })
  const secondText = review.applyDeidItems(second, secondItems)
  assert.equal(secondText, '내담자: [인물 B]이가 또 연락했어요. 베프니까 받았죠. 선배 [인물 C]이 일을 넘겨요.')
  const secondMapping = lib.detectPersonMapping([secondText], afterFirst)
  const stillB = secondMapping.persons.find((person) => person.label === '인물 B')
  assert.equal(secondMapping.mentions.find((mention) => mention.text === '베프').personId, stillB.id, 'saved relation is preselected')
  assert.equal(lib.applyPersonMapping(secondText, secondMapping), '내담자: [인물 B]이가 또 연락했어요. 베프[인물 B]니까 받았죠. 선배 [인물 C]이 일을 넘겨요.')
  const afterSecond = lib.updatedPersonDictionary(afterFirst, secondMapping, secondItems)
  assert.deepEqual(sortedPeople(afterSecond), [
    { label: '인물 B', names: ['김서영', '서연', '서영'], relations: ['베프', '친구'] },
    { label: '인물 C', names: ['박민준'], relations: [] },
  ])
  assert.ok(lib.samePersonDictionary(afterFirst, [...afterFirst].reverse()))
  assert.ok(!lib.samePersonDictionary(afterFirst, afterSecond))

  // Session 3: the counselor says 인물 C is really 인물 B, and 친구 no longer means anyone in particular.
  const third = '내담자: 박민준이 연락했어요. 친구가 많아졌어요.'
  const thirdItems = review.detectLocalDeidItems([third], { people: afterSecond })
  const thirdText = review.applyDeidItems(third, thirdItems)
  let thirdMapping = lib.detectPersonMapping([thirdText], afterSecond)
  const bAgain = thirdMapping.persons.find((person) => person.label === '인물 B')
  thirdMapping = link(link(thirdMapping, '[인물 C]', bAgain.id), '친구', null)
  assert.deepEqual(sortedPeople(lib.updatedPersonDictionary(afterSecond, thirdMapping, thirdItems)), [
    { label: '인물 B', names: ['김서영', '박민준', '서연', '서영'], relations: ['베프'] },
  ])

  // The client's own name is not copied into the dictionary; relations to the client are.
  const clientText = '내담자: 엄마가 지혜야 하고 불렀어요.'
  const clientItems = review.detectLocalDeidItems([clientText], { clientName: '지혜' })
  let clientMapping = lib.detectPersonMapping([review.applyDeidItems(clientText, clientItems)])
  clientMapping = link(clientMapping, '엄마', lib.createPerson(clientMapping.persons).id)
  assert.deepEqual(lib.updatedPersonDictionary([], clientMapping, clientItems).filter((p) => p.label === '내담자 A'), [])
}

console.log('person mapping checks passed')
