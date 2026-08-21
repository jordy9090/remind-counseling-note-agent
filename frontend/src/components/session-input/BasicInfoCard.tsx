import { Edit3, User } from 'lucide-react'

export default function BasicInfoCard({
  clientDisplayName,
  onEditBasicInfo,
  sessionDate,
  sessionNumber,
  sessionTopic,
}: {
  clientDisplayName: string
  onEditBasicInfo: () => void
  sessionDate: string
  sessionNumber: number
  sessionTopic: string
}) {
  return (
    <section className="flex items-center justify-between gap-3 rounded-[14px] border border-slate-200 bg-white px-4 py-3 shadow-sm">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-blue-50">
          <User className="h-4 w-4 text-blue-700" />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-slate-950">{clientDisplayName}</p>
          <p className="truncate text-xs text-slate-500">
            {sessionNumber}회기 · {sessionTopic || '주제 미정'} · {sessionDate || '날짜 미정'}
          </p>
        </div>
      </div>
      <button
        type="button"
        onClick={onEditBasicInfo}
        className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
      >
        <Edit3 className="h-3.5 w-3.5" />
        수정하기
      </button>
    </section>
  )
}
