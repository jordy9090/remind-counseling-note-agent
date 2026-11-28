import type { AudioSegment } from '../types/session'

export interface LiveDraftItem {
  segmentId: string
  quote: string
  start: number
  end: number
}

export interface LiveDraftSection {
  id: string
  title: string
  items: LiveDraftItem[]
  omittedCount: number
}

const MAX_VISIBLE_ITEMS = 12

// These labels organize literal mentions. They never assert a speaker, clinical
// finding, agreement, or intervention; the original sentence remains the claim.
const categories = [
  { id: 'context', title: '상황·주제', pattern: /학교|직장|회사|가족|부모|엄마|아빠|친구|관계|연애|시험|업무|생활|일상|사건|갈등|경제|돈|진로|연구/ },
  { id: 'experience', title: '감정·몸 상태 언급', pattern: /불안|걱정|슬프|슬펐|슬픔|우울|화가|분노|외로|외롭|외로운|긴장|두려|무섭|무서|괴롭|기쁘|행복|편안|감정|마음|수면|잠을|잠이|잠은|잠도|피곤|통증|아프|아팠|몸이|몸은|가슴|호흡/ },
  { id: 'change', title: '변화 언급', pattern: /전보다|예전보다|지난번|지난주|이전과|이전보다|처음보다|나아졌|나아진|좋아졌|좋아진|줄었|줄어|늘었|늘어|심해졌|심해진|달라졌|달라진|변했|변화|덜해|덜하|덜했|계속되고|지속되/ },
  { id: 'next', title: '계획·다음 회기', pattern: /다음\s*(?:주|시간|상담|회기)|앞으로|해\s*보|해볼|해보고|해보기|할\s*예정|하려고|하기로|계획|목표|숙제|과제/ },
] as const

/** Group observed transcript segments without sending them to an AI service. */
export function buildLiveSessionDraft(segments: AudioSegment[]): LiveDraftSection[] {
  const sections: LiveDraftSection[] = [
    ...categories.map(({ id, title }) => ({ id, title, items: [], omittedCount: 0 })),
    { id: 'other', title: '추가 발화', items: [], omittedCount: 0 },
  ]
  const byId = new Map(sections.map(section => [section.id, section]))
  // Replacements of one source segment update its existing quote instead of
  // leaving a stale observation behind after an ASR correction or retry.
  const current = new Map<string, AudioSegment>()
  for (const segment of segments) {
    const key = segment.segment_id || `live-segment-${segment.id}`
    current.set(key, segment)
  }
  const ordered = [...current.entries()].sort((a, b) => a[1].start - b[1].start || a[1].id - b[1].id)
  for (const [segmentId, segment] of ordered) {
    if (!Number.isFinite(segment.start) || !Number.isFinite(segment.end)
      || segment.start < 0 || segment.end <= segment.start || !segment.text.trim()) continue
    const item: LiveDraftItem = {
      segmentId, quote: segment.text.trim(), start: segment.start, end: segment.end,
    }
    const matches = categories.filter(category => category.pattern.test(item.quote))
    if (!matches.length) byId.get('other')!.items.push(item)
    else for (const category of matches) byId.get(category.id)!.items.push(item)
  }
  for (const section of sections) {
    section.omittedCount = Math.max(0, section.items.length - MAX_VISIBLE_ITEMS)
    section.items = section.items.slice(-MAX_VISIBLE_ITEMS)
  }
  return sections
}
