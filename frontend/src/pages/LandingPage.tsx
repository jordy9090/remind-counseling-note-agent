import { useState } from 'react'

import QuickSummaryPanel from '../components/quick-summary/QuickSummaryPanel'
import { clearPendingQuickSummary, readPendingQuickSummary, storePendingQuickSummary, type QuickSummaryResult } from '../lib/quickSummary'

interface LandingPageProps {
  onLogin: () => void
  /** "저장하기" before login: the summary is kept, then the login/signup modal opens. */
  onSaveRequiresLogin: () => void
}

/** Public landing = quick summary without login (랜딩 → 입력 → AI 요약 → 복사 / 저장하기 → 로그인). */
export default function LandingPage({ onLogin, onSaveRequiresLogin }: LandingPageProps) {
  const [result, setResult] = useState<QuickSummaryResult | null>(() => readPendingQuickSummary())

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
          onResult={(next) => {
            setResult(next)
            // 새로 요약하기 discards the summary kept for after login, too.
            if (!next) clearPendingQuickSummary()
          }}
          canExtractDocuments={false}
          onSave={(summary) => {
            storePendingQuickSummary(summary)
            onSaveRequiresLogin()
          }}
        />
      </div>
    </main>
  )
}
