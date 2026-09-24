import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'

/**
 * Figma 모달 공통 껍데기: 외곽선 grey/200, 패딩 24, 모서리 24, 내부 간격 24.
 * 내담자 생성 / 내담자 선택 / 새 회기 기록이 같은 규격을 쓴다.
 */
export default function ModalShell({
  title,
  description,
  onClose,
  children,
  footer,
  width = 660,
  ariaLabel,
  closeDisabled = false,
}: {
  title: ReactNode
  description?: ReactNode
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  width?: number
  ariaLabel: string
  closeDisabled?: boolean
}) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !closeDisabled) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, closeDisabled])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-grey-900/45 px-4 py-6" role="presentation">
      <section
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        className="rm-modal max-h-[92vh] w-full overflow-hidden"
        style={{ maxWidth: width }}
      >
        <header className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-lg font-bold text-grey-900">{title}</h2>
            {description && <p className="mt-1.5 text-sm text-grey-500">{description}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={closeDisabled}
            aria-label="닫기"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-grey-500 hover:bg-grey-100 hover:text-grey-900 disabled:opacity-40"
          >
            <X className="h-5 w-5" />
          </button>
        </header>
        <div className="rm-scroll -mx-1 min-h-0 flex-1 overflow-y-auto px-1">{children}</div>
        {footer && <footer className="flex flex-wrap gap-3">{footer}</footer>}
      </section>
    </div>
  )
}
