import { CheckCircle2, Loader2, RefreshCcw } from 'lucide-react'

export default function ProcessStatusCard({
  completedSteps,
  isLoading,
  steps,
}: {
  completedSteps: number
  isLoading: boolean
  steps: string[]
}) {
  return (
    <section className="session-card session-process-card rounded-[12px] border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-2">
        <RefreshCcw className="h-4 w-4 text-blue-700" />
        <h2 className="text-lg font-bold">처리 상태</h2>
      </div>
      {isLoading && <p className="mt-2 text-xs font-medium text-blue-700">구조화 → 회기요약 → 검증 진행 중...</p>}
      <div className="mt-3 grid gap-2 md:grid-cols-5">
        {steps.map((step, index) => {
          const isDone = index < completedSteps
          const isActive = isLoading && index === completedSteps
          return (
            <div
              key={step}
              className={`process-step flex items-center gap-1.5 rounded-md border px-2 text-xs font-semibold ${
                isDone || isActive ? 'border-blue-600 bg-blue-50 text-blue-800' : 'border-slate-200 bg-slate-50 text-slate-500'
              }`}
            >
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                  isDone
                    ? 'border-blue-200 bg-blue-600 text-white'
                    : isActive
                      ? 'border-blue-200 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-400'
                }`}
              >
                {isDone ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : isActive ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  index + 1
                )}
              </span>
              <span className="truncate">{step}</span>
            </div>
          )
        })}
      </div>
    </section>
  )
}
