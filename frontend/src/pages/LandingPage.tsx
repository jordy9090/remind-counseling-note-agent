import { useState } from 'react'

import QuickSummaryPanel from '../components/quick-summary/QuickSummaryPanel'
import { clearPendingQuickSummary, storePendingQuickSummary, type QuickSummaryResult } from '../lib/quickSummary'

interface LandingPageProps {
  onLogin: () => void
}

/**
 * Public landing = quick summary without login (랜딩 → 입력 → AI 요약 → 복사 / 로그인 후 저장하기).
 * Nothing is saved before login. 로그인 후 저장하기 keeps the AI output in this browser until the
 * login completes; the workspace then saves it like any signed-in summary.
 */
export default function LandingPage({ onLogin }: LandingPageProps) {
  const [result, setResult] = useState<QuickSummaryResult | null>(null)

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
            // 새로 요약하기 also drops a summary waiting for login.
            if (!next) clearPendingQuickSummary()
          }}
          canExtractDocuments={false}
          privacyNote="입력한 내용과 요약 결과는 저장되지 않아요. '로그인 후 저장하기'를 누르면 로그인한 뒤 요약 결과만 저장돼요. 이름·연락처 등 개인정보로 보이는 내용은 가린 뒤 AI에 보내요."
          saveAction={{
            label: '로그인 후 저장하기',
            onSave: (summary) => {
              storePendingQuickSummary(summary)
              onLogin()
            },
          }}
        />
      </div>
    </main>
  )
}
