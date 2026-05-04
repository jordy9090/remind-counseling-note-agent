import { useState } from 'react'
import type { SessionInput, StructuredCase, SessionSummary, VerificationReport } from '../types/session'
import { postSessionDraft } from '../api/client'
import { AppShell } from '../components/layout/AppShell'
import { Header } from '../components/layout/Header'
import { SessionInputForm } from '../components/note/SessionInputForm'
import { StructuredResult } from '../components/note/StructuredResult'
import { SummaryResult } from '../components/note/SummaryResult'
import { VerificationReportComponent } from '../components/note/VerificationReport'

export default function SessionDraftPage() {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{
    structured: StructuredCase
    summary: SessionSummary
    verification: VerificationReport
  } | null>(null)

  const handleSubmit = async (input: SessionInput) => {
    setIsLoading(true)
    setError(null)
    setResult(null)

    try {
      const response = await postSessionDraft(input)
      setResult(response)
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : '회기 요약 생성 중 오류 발생'
      setError(errorMsg)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <AppShell>
      <Header title="상담 회기 요약 생성" />
      <div className="mx-auto max-w-7xl px-6 py-8">
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-3">
          {/* 입력 폼 */}
          <div className="lg:col-span-1">
            <div className="sticky top-8 rounded-lg border border-gray-200 bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-lg font-bold">회기 정보 입력</h2>
              <SessionInputForm onSubmit={handleSubmit} isLoading={isLoading} />
              
              {error && (
                <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {error}
                </div>
              )}
            </div>
          </div>

          {/* 결과 표시 */}
          <div className="space-y-6 lg:col-span-2">
            {isLoading && (
              <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
                <div className="inline-block animate-spin rounded-full border-4 border-gray-300 border-t-blue-600 h-8 w-8"></div>
                <p className="mt-4 text-gray-600">처리 중입니다...</p>
              </div>
            )}

            {result && !isLoading && (
              <>
                <StructuredResult data={result.structured} />
                <SummaryResult data={result.summary} />
                <VerificationReportComponent data={result.verification} />
              </>
            )}

            {!isLoading && !result && (
              <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
                <p className="text-gray-500">좌측 폼에서 회기 정보를 입력하고 "회기 요약 생성"을 클릭하세요.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  )
}
