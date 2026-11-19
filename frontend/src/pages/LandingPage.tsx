import { useEffect, useState } from 'react'

import QuickSummaryPanel from '../components/quick-summary/QuickSummaryPanel'
import { quickSummaryResultFromNote } from './SessionDraftPage'
import { clearPendingQuickSummary, type QuickSummaryResult } from '../lib/quickSummary'

interface LandingPageProps {
  onLogin: () => void
}

/**
 * The public landing routes AI processing to login and keeps no cross-account handoff.
 */
export default function LandingPage({ onLogin }: LandingPageProps) {
  const [result, setResult] = useState<QuickSummaryResult | null>(null)
  useEffect(clearPendingQuickSummary, [])

  return (
    <main className="quick-summary-bg min-h-screen text-slate-950">
      <header className="flex h-[73px] items-center justify-between px-6 sm:px-8">
        <img src="/remind-logo.png" alt="Re:mind" className="h-7 w-auto object-contain" />
        <button
          type="button"
          onClick={onLogin}
          className="inline-flex h-8 items-center rounded-full border border-grey-200 bg-white px-3.5 text-xs font-semibold text-grey-600 hover:bg-grey-100"
        >
          로그인 / 회원가입
        </button>
      </header>
      <div className="flex min-h-[calc(100vh-73px)] flex-col justify-center">
        <QuickSummaryPanel
          result={result}
          toResult={quickSummaryResultFromNote}
          onResult={setResult}
          canExtractDocuments={false}
          onAudioLogin={onLogin}
          onGenerationRequiresLogin={onLogin}
          privacyNote="상담자료를 AI로 처리하고 기록을 저장하려면 먼저 로그인해주세요. 로그인 전 이 화면에 입력한 내용은 계정으로 옮겨지지 않아요."
        />
      </div>
    </main>
  )
}
