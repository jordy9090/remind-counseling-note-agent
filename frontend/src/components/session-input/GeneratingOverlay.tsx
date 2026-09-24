import { useEffect, useState } from 'react'
import { CheckCircle2, Loader2 } from 'lucide-react'

export const GENERATING_STEPS = ['상담 자료 불러오는 중', '녹음 파일 분석 중', '상담사 메모 확인 중', '주요 내용 추출 중']

/**
 * 회기 요약 생성 로딩 화면 (Figma). 진행률은 시각적 추정치이며 완료 시 100%로 채운 뒤 사라진다.
 */
export default function GeneratingOverlay({ active }: { active: boolean }) {
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    if (!active) {
      setProgress(0)
      return
    }
    setProgress(6)
    const timer = window.setInterval(() => {
      setProgress((value) => (value >= 92 ? value : value + Math.max(1, Math.round((92 - value) / 12))))
    }, 400)
    return () => window.clearInterval(timer)
  }, [active])

  if (!active) return null
  const doneCount = Math.min(GENERATING_STEPS.length, Math.floor((progress / 92) * GENERATING_STEPS.length))

  return (
    <div role="status" aria-live="polite" aria-label="회기 요약 생성 중" className="fixed inset-0 z-[60] flex items-center justify-center bg-white/85 backdrop-blur-sm">
      <div className="w-full max-w-[400px] px-6 text-center">
        <Loader2 className="mx-auto h-12 w-12 animate-spin text-grey-800" strokeWidth={1.5} />
        <h2 className="mt-8 text-2xl font-extrabold text-grey-900">회기 요약 생성 중...</h2>
        <p className="mt-2 text-sm text-grey-600">AI가 회기 내용을 분석하고 있어요.</p>
        <div className="mx-auto mt-8 h-2 w-full max-w-[380px] overflow-hidden rounded-full bg-grey-100">
          <div className="h-full rounded-full bg-gradient-to-r from-primary-400 to-primary-100 transition-[width] duration-300" style={{ width: `${progress}%` }} />
        </div>
        <p className="mt-2 text-xs font-semibold text-grey-600">{progress}%</p>
        <ul className="mx-auto mt-8 inline-flex flex-col gap-3 text-left text-sm text-grey-800">
          {GENERATING_STEPS.map((label, index) => (
            <li key={label} className={`flex items-center gap-2.5 ${index < doneCount ? 'text-grey-900' : 'text-grey-400'}`}>
              <CheckCircle2 className={`h-5 w-5 ${index < doneCount ? 'text-grey-900' : 'text-grey-200'}`} />
              {label}
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
