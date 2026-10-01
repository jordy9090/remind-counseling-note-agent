import { useRef, type ReactNode } from 'react'
import {
  AlignCenter,
  AlignLeft,
  AlignRight,
  Baseline,
  Bold,
  Download,
  Highlighter,
  Image as ImageIcon,
  Italic,
  Link2,
  List,
  ListOrdered,
  Loader2,
  Underline,
  type LucideIcon,
} from 'lucide-react'

import type { DocumentCapabilitiesResponse, DocumentExportFormat } from '../../types/session'

type ListKind = 'bullet' | 'numbered'

const BULLET_PATTERN = /^\s*(?:•|-|\d+\.)\s+/

/**
 * Prefix (or un-prefix) the selected lines of a textarea with bullets or numbers.
 * Exports are plain text, so lists are the only formatting that survives into DOCX/PDF.
 */
export function applyListToLines(value: string, start: number, end: number, kind: ListKind): { value: string; start: number; end: number } {
  const lineStart = value.lastIndexOf('\n', Math.max(0, start - 1)) + 1
  const nextBreak = value.indexOf('\n', end)
  const lineEnd = nextBreak === -1 ? value.length : nextBreak
  const lines = value.slice(lineStart, lineEnd).split('\n')
  const alreadyListed = lines.every((line) => !line.trim() || (kind === 'bullet' ? /^\s*•\s+/.test(line) : /^\s*\d+\.\s+/.test(line)))
  let counter = 0
  const nextLines = lines.map((line) => {
    if (!line.trim()) return line
    const stripped = line.replace(BULLET_PATTERN, '')
    if (alreadyListed) return stripped
    counter += 1
    return kind === 'bullet' ? `• ${stripped}` : `${counter}. ${stripped}`
  })
  const replaced = nextLines.join('\n')
  return {
    value: value.slice(0, lineStart) + replaced + value.slice(lineEnd),
    start: lineStart,
    end: lineStart + replaced.length,
  }
}

/** Update a React-controlled textarea so its onChange handler runs. */
function setTextareaValue(textarea: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set
  setter?.call(textarea, value)
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

function formatEditedDate(value: Date | null): string {
  if (!value) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${value.getFullYear()}.${pad(value.getMonth() + 1)}.${pad(value.getDate())} 수정됨`
}

const UNSUPPORTED_TITLE = '다운로드 파일은 텍스트로 저장되어 이 서식은 아직 지원하지 않습니다.'

/**
 * Final document editor card (Figma "1회기 슈퍼비전 보고서"): title, last-edited date, PDF download,
 * a formatting toolbar, and the editable document body passed as children.
 */
export default function FinalDocumentEditor({
  title,
  editedAt,
  capabilities,
  isExporting,
  exportStatus,
  exportError,
  onDownload,
  children,
}: {
  title: string
  editedAt: Date | null
  capabilities: DocumentCapabilitiesResponse | null
  isExporting: boolean
  exportStatus: string | null
  exportError: string | null
  onDownload: (format: DocumentExportFormat) => void
  children: ReactNode
}) {
  const bodyRef = useRef<HTMLDivElement>(null)
  const lastTextareaRef = useRef<HTMLTextAreaElement | null>(null)
  const pdfAvailable = Boolean(capabilities && capabilities.pdf.available !== false)

  const applyList = (kind: ListKind) => {
    const active = document.activeElement
    const textarea = active instanceof HTMLTextAreaElement && bodyRef.current?.contains(active)
      ? active
      : lastTextareaRef.current && document.body.contains(lastTextareaRef.current) ? lastTextareaRef.current : null
    if (!textarea) return
    const next = applyListToLines(textarea.value, textarea.selectionStart, textarea.selectionEnd, kind)
    setTextareaValue(textarea, next.value)
    textarea.focus()
    textarea.setSelectionRange(next.start, next.end)
  }

  return (
    <section className="rm-card overflow-hidden" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-grey-200 px-5 py-4 md:px-6">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
          <h1 className="text-xl font-extrabold text-grey-900">{title}</h1>
          {editedAt && <span className="text-sm text-grey-400">{formatEditedDate(editedAt)}</span>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => onDownload('docx')}
            disabled={isExporting}
            className="inline-flex h-11 items-center gap-1.5 rounded-[10px] border border-grey-200 bg-white px-4 text-sm font-bold text-grey-700 hover:bg-grey-100 disabled:opacity-50"
          >
            Word
          </button>
          <button
            type="button"
            onClick={() => onDownload('pdf')}
            disabled={isExporting || !pdfAvailable}
            title={pdfAvailable ? undefined : 'PDF 변환을 사용할 수 없는 환경입니다. Word로 다운받아주세요.'}
            className="inline-flex h-11 items-center gap-2 rounded-[10px] bg-primary-400 px-5 text-sm font-bold text-white hover:bg-primary-500 disabled:bg-grey-100 disabled:text-grey-400"
          >
            {isExporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
            PDF로 다운받기
          </button>
        </div>
      </div>
      {(exportStatus || exportError) && (
        <p role={exportError ? 'alert' : 'status'} className={`border-b border-grey-200 px-5 py-2 text-xs font-semibold md:px-6 ${exportError ? 'text-danger-500' : 'text-success-500'}`}>
          {exportError || exportStatus}
        </p>
      )}

      <div role="toolbar" aria-label="문서 서식" className="flex flex-wrap items-center gap-1 border-b border-grey-200 px-4 py-2 md:px-5">
        <ToolGroup>
          <ToolButton icon={Bold} label="굵게" />
          <ToolButton icon={Italic} label="기울임" />
          <ToolButton icon={Underline} label="밑줄" />
        </ToolGroup>
        <ToolGroup>
          <ToolButton icon={Baseline} label="글자 색" />
          <ToolButton icon={Highlighter} label="형광펜" />
        </ToolGroup>
        <ToolGroup>
          <ToolButton icon={AlignLeft} label="왼쪽 정렬" />
          <ToolButton icon={AlignCenter} label="가운데 정렬" />
          <ToolButton icon={AlignRight} label="오른쪽 정렬" />
        </ToolGroup>
        <ToolGroup>
          <ToolButton icon={List} label="글머리 기호" onApply={() => applyList('bullet')} />
          <ToolButton icon={ListOrdered} label="번호 매기기" onApply={() => applyList('numbered')} />
        </ToolGroup>
        <ToolGroup last>
          <ToolButton icon={ImageIcon} label="이미지" />
          <ToolButton icon={Link2} label="링크" />
        </ToolGroup>
      </div>

      <div
        ref={bodyRef}
        onFocusCapture={(event) => {
          if (event.target instanceof HTMLTextAreaElement) lastTextareaRef.current = event.target
        }}
        className="px-5 py-5 md:px-6"
      >
        {children}
      </div>
    </section>
  )
}

function ToolGroup({ children, last = false }: { children: ReactNode; last?: boolean }) {
  return <div className={`flex items-center gap-0.5 pr-1.5 ${last ? '' : 'mr-1.5 border-r border-grey-200'}`}>{children}</div>
}

function ToolButton({ icon: Icon, label, onApply }: { icon: LucideIcon; label: string; onApply?: () => void }) {
  const enabled = Boolean(onApply)
  return (
    <button
      type="button"
      aria-label={label}
      title={enabled ? label : `${label} · ${UNSUPPORTED_TITLE}`}
      disabled={!enabled}
      // Keep the caret/selection inside the textarea while clicking the toolbar.
      onMouseDown={(event) => event.preventDefault()}
      onClick={onApply}
      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-grey-700 hover:bg-grey-100 disabled:cursor-not-allowed disabled:text-grey-400 disabled:hover:bg-transparent"
    >
      <Icon className="h-[18px] w-[18px]" />
    </button>
  )
}
