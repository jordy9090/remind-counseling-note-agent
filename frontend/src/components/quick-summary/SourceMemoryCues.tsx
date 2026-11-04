import { clientMemoryQuotes } from '../../lib/summaryEvidence'

export default function SourceMemoryCues({ evidence }: { evidence: unknown[] }) {
  const quotes = clientMemoryQuotes(evidence)
  if (!quotes.length) return null
  return (
    <aside aria-label="내담자 원문 표현" className="my-4 rounded-lg bg-primary-50 px-4 py-3 text-sm">
      <p className="font-bold text-primary-900">기억을 돕는 내담자 표현</p>
      <p className="mt-1 text-xs text-grey-600">요약에 연결된 비식별 원문의 발화입니다. 해석은 관련 원문과 함께 확인해주세요.</p>
      {quotes.map(quote => <blockquote key={quote} className="mt-2 whitespace-pre-wrap border-l-2 border-primary-200 pl-3 leading-6">{quote}</blockquote>)}
    </aside>
  )
}
