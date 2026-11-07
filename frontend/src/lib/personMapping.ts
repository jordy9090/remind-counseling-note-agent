/**
 * People in the reviewed (de-identified) session text, matched by the counselor before summary
 * generation ("등장 인물 정리").
 *
 * A client may call one person by a name, a misheard name, a nickname or a relation ("서영",
 * "서연", "베프", "친구"). After de-identification these show up as separate labels or plain
 * words, so the AI treats them as different people. The counselor links each expression to one
 * person; the AI then receives one label per person:
 * - de-identification labels are unified ("[인물 C]" → "[인물 B]"),
 * - names that are still in the text are replaced ("서연" → "[인물 B]"),
 * - relation words keep the client's wording and gain the label ("베프" → "베프[인물 B]").
 *
 * Runs in the browser on text that already passed the de-identification review; nothing is sent
 * or stored here.
 */

import { discoverPersonNames, namePattern } from './deidentificationReview'

export type PersonMentionKind = 'label' | 'name' | 'relation' | 'manual'
/** replace: the expression is hidden behind the label. annotate: the wording stays, the label follows. */
export type PersonMentionMode = 'replace' | 'annotate'

export interface Person {
  id: string
  /** "내담자 A", "상담자", "인물 B", ... (without brackets). */
  label: string
  /** The client and the counselor are always listed and cannot be removed. */
  fixed: boolean
}

export interface PersonMention {
  id: string
  /** The expression as it appears in the reviewed text ("[인물 C]", "서연", "베프"). */
  text: string
  kind: PersonMentionKind
  mode: PersonMentionMode
  count: number
  /** First occurrence with a little surrounding text, for the counselor to recognise it. */
  context: string
  /** null: not linked; the expression is sent unchanged. */
  personId: string | null
}

export interface PersonMapping {
  persons: Person[]
  mentions: PersonMention[]
}

/** One person in the client's saved 인물 사전 (GET/PUT /api/cases/{case_id}/person-dictionary). */
export interface StoredPerson {
  label: string
  /** Hidden behind the label in later sessions: names and misheard names. */
  names: string[]
  /** Kept as written with the label added: 베프, 친구. */
  relations: string[]
}

/** A replacement the de-identification review applied (original → replacement). */
export interface AppliedDeidItem {
  original: string
  replacement: string
}

export const CLIENT_PERSON_ID = 'person-client'
export const COUNSELOR_PERSON_ID = 'person-counselor'
const UNRESOLVED_LABEL = '인물 확인 필요'

/** Labels written by the de-identification review ("[인물 B]", "[인물 확인 필요]", ...). */
const LABEL = /\[(내담자 A|상담자|인물 (?:[A-Z]|\d+)|인물 확인 필요)\]/g

/**
 * Relation and nickname words that usually point at one person in a session. Words that are
 * not about a specific person ("친구들", "남자친구" inside "친구") are excluded by the
 * name-boundary rules shared with the de-identification review.
 */
export const RELATION_TERMS = [
  '베프', '절친', '친구', '남자친구', '남친', '여자친구', '여친', '애인', '전남친', '전여친', '전남편', '전처',
  '엄마', '어머니', '아빠', '아버지', '새엄마', '새아빠', '할머니', '할아버지', '외할머니', '외할아버지',
  '오빠', '언니', '누나', '형', '남동생', '여동생', '동생', '쌍둥이', '이모', '고모', '삼촌', '외삼촌', '사촌',
  '남편', '아내', '와이프', '시어머니', '시아버지', '장모', '장인', '아들', '딸', '큰딸', '작은딸', '큰아들', '작은아들',
  // "과장", "대표" are left out: "과장하고", "대표하는" are verbs far more often than people.
  '선배', '후배', '동기', '동료', '상사', '팀장', '부장', '사장', '룸메', '룸메이트',
  '담임', '선생님', '교수님', '지도교수', '코치', '목사님',
]

/**
 * A relation word followed by a particle or copula ("베프라서", "엄마한테", "친구였어요"), or by
 * a non-Hangul character. Other continuations make it a different word ("친구들", "형편", "딸기").
 */
const RELATION_PARTICLES = '이니까|니까|이라도|라도|이라면|라면|이랑|랑|하고|한테서|한테|에게서|에게|께서|께|이라서|라서|이라고|라고|이라는|라는|이라며|라며|이에요|예요|이었|였|이야|야|이고|고|인데|이네|네|이|가|은|는|을|를|의|와|과|도|만|으로|로|부터|까지|처럼|보다|님|씨'

function relationPattern(term: string): RegExp {
  return new RegExp(`(?<![가-힣A-Za-z0-9_])${term}(?=$|[^가-힣A-Za-z0-9_]|(?:${RELATION_PARTICLES}))`, 'g')
}

let idCounter = 0
function newId(prefix: string): string {
  idCounter += 1
  return `${prefix}-${Date.now().toString(36)}-${idCounter}`
}

interface Span {
  start: number
  end: number
}

function labelSpans(text: string): Span[] {
  return Array.from(text.matchAll(LABEL), (match) => ({ start: match.index ?? 0, end: (match.index ?? 0) + match[0].length }))
}

function insideAny(position: number, spans: Span[]): boolean {
  return spans.some((span) => position >= span.start && position < span.end)
}

/** Start positions of an expression in the text, outside de-identification labels. */
function occurrences(text: string, mention: Pick<PersonMention, 'text' | 'kind'>, spans = labelSpans(text)): number[] {
  if (!mention.text) return []
  if (mention.kind === 'label' || mention.kind === 'manual') {
    const found: number[] = []
    for (let from = text.indexOf(mention.text); from !== -1; from = text.indexOf(mention.text, from + 1)) {
      if (mention.kind === 'label' || !insideAny(from, spans)) found.push(from)
    }
    return found
  }
  const pattern = mention.kind === 'relation' ? relationPattern(mention.text) : namePattern(mention.text)
  return Array.from(text.matchAll(pattern), (match) => match.index ?? 0).filter((start) => !insideAny(start, spans))
}

function contextOf(texts: string[], mention: Pick<PersonMention, 'text' | 'kind'>): string {
  for (const text of texts) {
    const start = occurrences(text, mention)[0]
    if (start === undefined) continue
    const from = Math.max(0, start - 18)
    const to = Math.min(text.length, start + mention.text.length + 18)
    return `${from > 0 ? '…' : ''}${text.slice(from, to).replace(/\s+/g, ' ').trim()}${to < text.length ? '…' : ''}`
  }
  return ''
}

function countIn(texts: string[], mention: Pick<PersonMention, 'text' | 'kind'>): number {
  return texts.reduce((total, text) => total + occurrences(text, mention).length, 0)
}

/** The next free "인물 X" label (B..Z, then numbers), skipping labels already in use. */
export function nextPersonLabel(persons: Person[]): string {
  const used = new Set(persons.map((person) => person.label))
  for (let code = 66; code <= 90; code += 1) {
    const label = `인물 ${String.fromCharCode(code)}`
    if (!used.has(label)) return label
  }
  let index = 27
  while (used.has(`인물 ${index}`)) index += 1
  return `인물 ${index}`
}

export function createPerson(persons: Person[]): Person {
  return { id: newId('person'), label: nextPersonLabel(persons), fixed: false }
}

/**
 * Everyone the counselor may need to match: de-identification labels (each its own person),
 * names still in the text and relation words. Names and relations start unlinked.
 */
export function detectPersonMapping(texts: string[], stored: StoredPerson[] = []): PersonMapping {
  const sources = texts.filter((text) => text.trim())
  const joined = sources.join('\n')
  const persons: Person[] = [
    { id: CLIENT_PERSON_ID, label: '내담자 A', fixed: true },
    { id: COUNSELOR_PERSON_ID, label: '상담자', fixed: true },
  ]
  // Saved people keep their labels even when they are not mentioned this session.
  for (const entry of stored) {
    if (!persons.some((person) => person.label === entry.label)) persons.push({ id: newId('person'), label: entry.label, fixed: false })
  }
  const savedOwner = (relation: string) => {
    const label = stored.find((entry) => entry.relations.includes(relation))?.label
    return persons.find((person) => person.label === label)?.id ?? null
  }
  const mentions: PersonMention[] = []
  const add = (text: string, kind: PersonMentionKind, mode: PersonMentionMode, personId: string | null) => {
    if (mentions.some((mention) => mention.text === text)) return
    const count = countIn(sources, { text, kind })
    if (!count) return
    mentions.push({ id: newId('mention'), text, kind, mode, count, context: contextOf(sources, { text, kind }), personId })
  }

  for (const match of joined.matchAll(LABEL)) {
    const label = match[1]
    if (label === '내담자 A' || label === '상담자') continue
    if (label === UNRESOLVED_LABEL) {
      add(match[0], 'label', 'replace', null)
      continue
    }
    let person = persons.find((candidate) => candidate.label === label)
    if (!person) {
      person = { id: newId('person'), label, fixed: false }
      persons.push(person)
    }
    add(match[0], 'label', 'replace', person.id)
  }
  // Names the review left in the text (missed or misheard) are hidden once linked.
  for (const name of discoverPersonNames(joined).keys()) add(name, 'name', 'replace', null)
  for (const term of RELATION_TERMS) add(term, 'relation', 'annotate', savedOwner(term))
  // Saved nicknames outside the built-in list ("짝꿍") are found literally, like manual expressions.
  for (const entry of stored) {
    for (const relation of entry.relations) {
      if (!RELATION_TERMS.includes(relation)) add(relation, 'manual', 'annotate', savedOwner(relation))
    }
  }
  return { persons, mentions }
}

const PERSON_LABEL_TEXT = /^인물 (?:[B-Z]|[1-9]\d{1,2})$/
const FIXED_LABELS = new Set(['내담자 A', '상담자'])
const STORED_EXPRESSION = /^[^[\]]{1,30}$/

/**
 * The client's 인물 사전 after this session. Names come from the de-identification review (their
 * label, or the person that label was linked to) and from linked names here; relations from linked
 * relation words. A saved label linked to another person is merged into it. The client's and
 * counselor's own names are not stored (they are registered elsewhere); their relations are.
 * Each expression belongs to one person: this session's choice wins.
 */
export function updatedPersonDictionary(stored: StoredPerson[], mapping: PersonMapping, deidItems: AppliedDeidItem[]): StoredPerson[] {
  const labelOf = (personId: string | null) => mapping.persons.find((person) => person.id === personId)?.label
  const linkedLabel = (labelText: string) => {
    const mention = mapping.mentions.find((candidate) => candidate.kind === 'label' && candidate.text === `[${labelText}]`)
    return mention ? labelOf(mention.personId) : undefined
  }
  const entries = new Map<string, StoredPerson>()
  const entry = (label: string) => {
    if (!entries.has(label)) entries.set(label, { label, names: [], relations: [] })
    return entries.get(label)!
  }
  for (const saved of stored) {
    const target = entry(linkedLabel(saved.label) ?? saved.label)
    target.names.push(...saved.names)
    target.relations.push(...saved.relations)
  }
  const assign = (label: string | undefined, field: 'names' | 'relations', expression: string) => {
    const value = expression.trim()
    if (!label || !STORED_EXPRESSION.test(value) || (field === 'names' && FIXED_LABELS.has(label))) return
    for (const other of entries.values()) other[field] = other[field].filter((existing) => existing !== value)
    entry(label)[field].push(value)
  }
  for (const item of deidItems) {
    const own = PERSON_LABEL_TEXT.test(item.replacement) ? item.replacement : undefined
    assign(linkedLabel(item.replacement) ?? own, 'names', item.original)
  }
  for (const mention of mapping.mentions) {
    const hides = mention.kind === 'name' || (mention.kind === 'manual' && mention.mode === 'replace')
    const relation = mention.kind === 'relation' || (mention.kind === 'manual' && mention.mode === 'annotate')
    if (mention.personId) {
      if (hides) assign(labelOf(mention.personId), 'names', mention.text)
      else if (relation) assign(labelOf(mention.personId), 'relations', mention.text)
    } else if (relation) {
      // Unlinked this session on purpose: the word no longer points at a saved person.
      for (const other of entries.values()) other.relations = other.relations.filter((existing) => existing !== mention.text)
    }
  }
  return [...entries.values()]
    .map((person) => ({
      label: person.label,
      names: FIXED_LABELS.has(person.label) ? [] : [...new Set(person.names)].slice(0, 30),
      relations: [...new Set(person.relations)].slice(0, 30),
    }))
    .filter((person) => person.names.length > 0 || person.relations.length > 0)
    .slice(0, 60)
}

/** Same people, names and relations regardless of order. */
export function samePersonDictionary(a: StoredPerson[], b: StoredPerson[]): boolean {
  const key = (people: StoredPerson[]) => JSON.stringify(
    [...people].map((person) => [person.label, [...person.names].sort(), [...person.relations].sort()]).sort(),
  )
  return key(a) === key(b)
}

export type ManualMentionResult = { mention: PersonMention } | { error: string }

/** A counselor-added expression ("서연이", "그 애"); literal matching outside labels. */
export function manualMention(texts: string[], mapping: PersonMapping, rawText: string, mode: PersonMentionMode): ManualMentionResult {
  const text = rawText.trim()
  if (!text) return { error: '표현을 입력해주세요.' }
  if (mapping.mentions.some((mention) => mention.text === text)) return { error: '이미 목록에 있는 표현이에요.' }
  const count = countIn(texts, { text, kind: 'manual' })
  if (!count) return { error: '상담 내용에서 찾을 수 없는 표현이에요. 똑같이 입력해주세요.' }
  return { mention: { id: newId('mention'), text, kind: 'manual', mode, count, context: contextOf(texts, { text, kind: 'manual' }), personId: null } }
}

/** What the AI receives: every linked expression points at its person's label. */
export function applyPersonMapping(text: string, mapping: PersonMapping): string {
  const labels = new Map(mapping.persons.map((person) => [person.id, person.label]))
  const spans = labelSpans(text)
  const edits: { start: number; end: number; output: string }[] = []
  const linked = mapping.mentions
    .filter((mention) => mention.personId && labels.has(mention.personId))
    .sort((a, b) => b.text.length - a.text.length)
  for (const mention of linked) {
    const target = `[${labels.get(mention.personId!)}]`
    if (mention.kind === 'label' && mention.text === target) continue
    for (const start of occurrences(text, mention, spans)) {
      const end = start + mention.text.length
      if (edits.some((edit) => start < edit.end && edit.start < end)) continue
      if (mention.mode === 'annotate') {
        // "친구 [인물 B]" already names the person right after the word.
        const next = /^\s*(\[[^\]\n]+\])/.exec(text.slice(end))?.[1]
        if (next && (next === target || mapping.mentions.some((other) => other.text === next && other.personId === mention.personId))) continue
        edits.push({ start, end, output: `${mention.text}${target}` })
      } else {
        edits.push({ start, end, output: target })
      }
    }
  }
  let out = ''
  let cursor = 0
  for (const edit of edits.sort((a, b) => a.start - b.start)) {
    out += text.slice(cursor, edit.start) + edit.output
    cursor = edit.end
  }
  return out + text.slice(cursor)
}

/** Expressions that would still reach the AI as an unresolved name or "[인물 확인 필요]". */
export function unresolvedNameMentions(mapping: PersonMapping): PersonMention[] {
  return mapping.mentions.filter((mention) => !mention.personId && (mention.kind === 'name' || mention.text === `[${UNRESOLVED_LABEL}]`))
}

/** Persons with at least one linked expression, or a de-identification label of their own. */
export function personDictionary(mapping: PersonMapping): { person: Person; expressions: string[] }[] {
  return mapping.persons
    .map((person) => ({ person, expressions: mapping.mentions.filter((mention) => mention.personId === person.id).map((mention) => mention.text) }))
    .filter((entry) => entry.expressions.length > 0)
}
