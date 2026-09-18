import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { ChevronLeft, ChevronRight, FileText, Loader2, User } from 'lucide-react'

import type { CaseStatusKind } from '../../lib/caseList'

const buttonBase =
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-[10px] font-bold transition disabled:cursor-not-allowed'

/** 파란 채움 버튼 (primary/400) */
export function PrimaryButton({ children, className = '', loading = false, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) {
  return (
    <button
      type="button"
      {...props}
      disabled={props.disabled || loading}
      className={`${buttonBase} h-11 bg-primary-400 px-5 text-sm text-white hover:bg-primary-500 disabled:bg-grey-100 disabled:text-grey-400 ${className}`}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
      {children}
    </button>
  )
}

/** 파란 외곽선 버튼 */
export function OutlineButton({ children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={`${buttonBase} h-11 border border-primary-400 bg-white px-5 text-sm text-primary-400 hover:bg-primary-50 disabled:border-grey-200 disabled:text-grey-400 ${className}`}
    >
      {children}
    </button>
  )
}

/** 회색 외곽선 보조 버튼 */
export function GhostButton({ children, className = '', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      className={`${buttonBase} h-9 border border-grey-200 bg-white px-3 text-xs text-grey-700 hover:bg-grey-100 disabled:text-grey-400 ${className}`}
    >
      {children}
    </button>
  )
}

const STATUS_CHIP: Record<CaseStatusKind, string> = {
  active: 'bg-success-50 text-success-500 border border-success-500/40',
  closed: 'bg-grey-100 text-grey-600 border border-grey-200',
  pending: 'bg-danger-50 text-danger-500 border border-danger-500/30',
}

export function StatusChip({ kind, label }: { kind: CaseStatusKind; label: string }) {
  return <span className={`inline-flex h-6 items-center rounded-full px-2.5 text-[11px] font-bold ${STATUS_CHIP[kind]}`}>{label}</span>
}

const SCHEDULE_CHIP = {
  done: 'bg-success-50 text-success-500',
  active: 'bg-primary-50 text-primary-400',
  upcoming: 'bg-danger-50 text-danger-500',
} as const

export function ScheduleChip({ label, tone }: { label: string; tone: keyof typeof SCHEDULE_CHIP }) {
  return <span className={`inline-flex h-6 items-center rounded-md px-2 text-[11px] font-bold ${SCHEDULE_CHIP[tone]}`}>{label}</span>
}

export function ClientAvatar({ size = 40 }: { size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-flex shrink-0 items-center justify-center rounded-full border border-primary-100 bg-primary-50 text-primary-400/60"
      style={{ width: size, height: size }}
    >
      <User style={{ width: size * 0.5, height: size * 0.5 }} />
    </span>
  )
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <FileText className="h-12 w-12 text-grey-400" strokeWidth={1.2} />
      <p className="mt-4 text-base font-bold text-grey-700">{title}</p>
      {description && <p className="mt-1.5 text-sm text-grey-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Pagination({ page, pageCount, onChange, unit = '' }: { page: number; pageCount: number; onChange: (page: number) => void; unit?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 text-sm text-grey-500">
      <button
        type="button"
        aria-label="이전 페이지"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
        className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-grey-200 text-grey-600 hover:bg-grey-100 disabled:text-grey-200 disabled:hover:bg-transparent"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>
      <span>
        <b className="text-grey-900">{page}</b> / {pageCount}{unit ? ` ${unit}` : ''}
      </span>
      <button
        type="button"
        aria-label="다음 페이지"
        disabled={page >= pageCount}
        onClick={() => onChange(page + 1)}
        className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-grey-200 text-grey-600 hover:bg-grey-100 disabled:text-grey-200 disabled:hover:bg-transparent"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )
}

export function SelectField({ value, onChange, options, ariaLabel, className = '' }: {
  value: string
  onChange: (value: string) => void
  options: { id: string; label: string }[]
  ariaLabel: string
  className?: string
}) {
  return (
    <select aria-label={ariaLabel} value={value} onChange={(event) => onChange(event.target.value)} className={`rm-input appearance-none pr-8 ${className}`}
      style={{ backgroundImage: "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%236b7280' stroke-width='2'><path d='m6 9 6 6 6-6'/></svg>\")", backgroundRepeat: 'no-repeat', backgroundPosition: 'right 12px center' }}>
      {options.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
    </select>
  )
}

export function SectionCard({ title, icon, action, children, className = '' }: { title: ReactNode; icon?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rm-card p-6 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-bold text-grey-900">{icon}{title}</h2>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  )
}

export function LinkAction({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex items-center gap-0.5 text-xs font-medium text-grey-500 hover:text-grey-900">
      {children}
      <ChevronRight className="h-3.5 w-3.5" />
    </button>
  )
}
