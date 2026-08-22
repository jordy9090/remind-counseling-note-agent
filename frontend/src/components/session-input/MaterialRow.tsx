export default function MaterialRow({
  actionLabel,
  label,
  meta,
  onAction,
}: {
  actionLabel: string
  label: string
  meta: string
  onAction: () => void
}) {
  return (
    <div className="material-row flex items-center justify-between gap-3 px-3 py-1">
      <div className="min-w-0">
        <p className="text-sm font-bold text-slate-950">{label}</p>
        <p className="mt-0.5 truncate text-xs text-slate-500">{meta}</p>
      </div>
      <button
        type="button"
        onClick={onAction}
        className="h-7 shrink-0 rounded-md border border-slate-200 px-2.5 text-xs font-medium text-slate-500 hover:bg-slate-50"
      >
        {actionLabel}
      </button>
    </div>
  )
}
