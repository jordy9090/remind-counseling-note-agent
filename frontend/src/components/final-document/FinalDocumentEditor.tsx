import { useEffect, useRef, useState, type ReactNode } from 'react'
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
import { RICH_TEXT_FIELD_ATTRIBUTE } from './RichTextField'

type Alignment = 'left' | 'center' | 'right'
type PaletteKind = 'color' | 'highlight'

interface ToolState {
  bold: boolean
  italic: boolean
  underline: boolean
  align: Alignment | null
  bullet: boolean
  numbered: boolean
}

const IDLE_TOOL_STATE: ToolState = { bold: false, italic: false, underline: false, align: null, bullet: false, numbered: false }

const TEXT_COLORS = [
  { label: '검정', value: '#111827' },
  { label: '빨강', value: '#dc2626' },
  { label: '주황', value: '#ea580c' },
  { label: '초록', value: '#16a34a' },
  { label: '파랑', value: '#2563eb' },
  { label: '보라', value: '#7c3aed' },
]

const HIGHLIGHT_COLORS = [
  { label: '노랑', value: '#fef08a' },
  { label: '연두', value: '#bbf7d0' },
  { label: '하늘', value: '#bfdbfe' },
  { label: '분홍', value: '#fbcfe8' },
  { label: '주황', value: '#fed7aa' },
]

function formatEditedDate(value: Date | null): string {
  if (!value) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${value.getFullYear()}.${pad(value.getMonth() + 1)}.${pad(value.getDate())} 수정됨`
}

const UNSUPPORTED_TITLE = '아직 지원하지 않습니다.'
const SELECT_TEXT_HINT = '본문에서 서식을 적용할 부분을 먼저 선택해 주세요.'

/**
 * Final document editor card (Figma "1회기 슈퍼비전 보고서"): title, last-edited date, PDF download,
 * a formatting toolbar, and the editable document body passed as children. The toolbar formats the
 * selection inside any RichTextField rendered in the body.
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
  const toolbarRef = useRef<HTMLDivElement>(null)
  // Last selection inside a formatted-text field, so a toolbar click still applies after focus moved.
  const savedRange = useRef<Range | null>(null)
  const [toolState, setToolState] = useState<ToolState>(IDLE_TOOL_STATE)
  const [openPalette, setOpenPalette] = useState<PaletteKind | null>(null)
  const [showHint, setShowHint] = useState(false)
  const pdfAvailable = Boolean(capabilities && capabilities.pdf.available !== false)

  const fieldOf = (node: Node | null): HTMLElement | null => {
    const element = node instanceof Element ? node : node?.parentElement
    const field = element?.closest<HTMLElement>(`[${RICH_TEXT_FIELD_ATTRIBUTE}]`) || null
    return field && bodyRef.current?.contains(field) ? field : null
  }

  const readToolState = () => {
    const selection = window.getSelection()
    const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null
    if (!range || !fieldOf(range.commonAncestorContainer)) {
      setToolState((current) => (current === IDLE_TOOL_STATE ? current : IDLE_TOOL_STATE))
      return
    }
    savedRange.current = range.cloneRange()
    const next: ToolState = {
      bold: document.queryCommandState('bold'),
      italic: document.queryCommandState('italic'),
      underline: document.queryCommandState('underline'),
      align: document.queryCommandState('justifyCenter') ? 'center' : document.queryCommandState('justifyRight') ? 'right' : 'left',
      bullet: document.queryCommandState('insertUnorderedList'),
      numbered: document.queryCommandState('insertOrderedList'),
    }
    setToolState((current) => (
      (Object.keys(next) as Array<keyof ToolState>).every((key) => current[key] === next[key]) ? current : next
    ))
  }

  useEffect(() => {
    // New lines become <div> blocks in every browser, which is what the export parser expects.
    document.execCommand('defaultParagraphSeparator', false, 'div')
    document.addEventListener('selectionchange', readToolState)
    return () => document.removeEventListener('selectionchange', readToolState)
  // The listener only reads refs and the DOM.
  }, [])

  useEffect(() => {
    if (!openPalette) return
    const close = (event: MouseEvent) => {
      if (!toolbarRef.current?.contains(event.target as Node)) setOpenPalette(null)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [openPalette])

  useEffect(() => {
    if (!showHint) return
    const timer = window.setTimeout(() => setShowHint(false), 3000)
    return () => window.clearTimeout(timer)
  }, [showHint])

  /** Apply an editing command to the selection in a formatted-text field. */
  const applyCommand = (command: string, value?: string, styleWithCss = false) => {
    const selection = window.getSelection()
    const current = selection && selection.rangeCount ? selection.getRangeAt(0) : null
    if (!selection || !current || !fieldOf(current.commonAncestorContainer)) {
      const saved = savedRange.current
      const field = saved && document.contains(saved.commonAncestorContainer) ? fieldOf(saved.commonAncestorContainer) : null
      if (!selection || !saved || !field) {
        setShowHint(true)
        return
      }
      field.focus()
      selection.removeAllRanges()
      selection.addRange(saved)
    }
    document.execCommand('styleWithCSS', false, styleWithCss ? 'true' : 'false')
    document.execCommand(command, false, value)
    setShowHint(false)
    readToolState()
  }

  const applyPaletteColor = (kind: PaletteKind, value: string) => {
    setOpenPalette(null)
    if (kind === 'color') applyCommand('foreColor', value)
    else applyCommand('hiliteColor', value, true)
  }

  return (
    // overflow-clip keeps the rounded corners without making the card a scroll container, which
    // would stop the title bar and toolbar from sticking to the viewport.
    <section className="rm-card overflow-clip" aria-label={title}>
      {/* Title, download status, and toolbar stay pinned under the page header while the body scrolls. */}
      <div className="z-20 rounded-t-[15px] bg-white md:sticky md:top-[var(--workflow-header-height,0px)]">
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

        <div ref={toolbarRef} role="toolbar" aria-label="문서 서식" className="flex flex-wrap items-center gap-1 border-b border-grey-200 px-4 py-2 md:px-5">
          <ToolGroup>
            <ToolButton icon={Bold} label="굵게" pressed={toolState.bold} onApply={() => applyCommand('bold')} />
            <ToolButton icon={Italic} label="기울임" pressed={toolState.italic} onApply={() => applyCommand('italic')} />
            <ToolButton icon={Underline} label="밑줄" pressed={toolState.underline} onApply={() => applyCommand('underline')} />
          </ToolGroup>
          <ToolGroup>
            <div className="relative">
              <ToolButton icon={Baseline} label="글자 색" expanded={openPalette === 'color'} onApply={() => setOpenPalette(openPalette === 'color' ? null : 'color')} />
              {openPalette === 'color' && (
                <ColorPalette label="글자 색" colors={TEXT_COLORS} onPick={(value) => applyPaletteColor('color', value)} />
              )}
            </div>
            <div className="relative">
              <ToolButton icon={Highlighter} label="형광펜" expanded={openPalette === 'highlight'} onApply={() => setOpenPalette(openPalette === 'highlight' ? null : 'highlight')} />
              {openPalette === 'highlight' && (
                <ColorPalette
                  label="형광펜"
                  colors={HIGHLIGHT_COLORS}
                  clearLabel="없음"
                  onPick={(value) => applyPaletteColor('highlight', value)}
                />
              )}
            </div>
          </ToolGroup>
          <ToolGroup>
            <ToolButton icon={AlignLeft} label="왼쪽 정렬" pressed={toolState.align === 'left'} onApply={() => applyCommand('justifyLeft')} />
            <ToolButton icon={AlignCenter} label="가운데 정렬" pressed={toolState.align === 'center'} onApply={() => applyCommand('justifyCenter')} />
            <ToolButton icon={AlignRight} label="오른쪽 정렬" pressed={toolState.align === 'right'} onApply={() => applyCommand('justifyRight')} />
          </ToolGroup>
          <ToolGroup>
            <ToolButton icon={List} label="글머리 기호" pressed={toolState.bullet} onApply={() => applyCommand('insertUnorderedList')} />
            <ToolButton icon={ListOrdered} label="번호 매기기" pressed={toolState.numbered} onApply={() => applyCommand('insertOrderedList')} />
          </ToolGroup>
          <ToolGroup last>
            <ToolButton icon={ImageIcon} label="이미지" />
            <ToolButton icon={Link2} label="링크" />
          </ToolGroup>
          {showHint && <span role="status" className="ml-auto text-xs font-semibold text-grey-500">{SELECT_TEXT_HINT}</span>}
        </div>
      </div>

      <div ref={bodyRef} className="px-5 py-5 md:px-6">
        {children}
      </div>
    </section>
  )
}

function ToolGroup({ children, last = false }: { children: ReactNode; last?: boolean }) {
  return <div className={`flex items-center gap-0.5 pr-1.5 ${last ? '' : 'mr-1.5 border-r border-grey-200'}`}>{children}</div>
}

function ToolButton({
  icon: Icon,
  label,
  onApply,
  pressed,
  expanded,
}: {
  icon: LucideIcon
  label: string
  onApply?: () => void
  pressed?: boolean
  expanded?: boolean
}) {
  const enabled = Boolean(onApply)
  const active = Boolean(pressed || expanded)
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={pressed === undefined ? undefined : pressed}
      aria-expanded={expanded === undefined ? undefined : expanded}
      title={enabled ? label : `${label} · ${UNSUPPORTED_TITLE}`}
      disabled={!enabled}
      // Keep the caret/selection inside the document body while clicking the toolbar.
      onMouseDown={(event) => event.preventDefault()}
      onClick={onApply}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-md hover:bg-grey-100 disabled:cursor-not-allowed disabled:text-grey-400 disabled:hover:bg-transparent ${active ? 'bg-primary-50 text-primary-500' : 'text-grey-700'}`}
    >
      <Icon className="h-[18px] w-[18px]" />
    </button>
  )
}

function ColorPalette({
  label,
  colors,
  clearLabel,
  onPick,
}: {
  label: string
  colors: Array<{ label: string; value: string }>
  clearLabel?: string
  onPick: (value: string) => void
}) {
  return (
    <div role="group" aria-label={`${label} 선택`} className="absolute left-0 top-full z-30 mt-1 flex items-center gap-1.5 rounded-[10px] border border-grey-200 bg-white p-2 shadow-lg">
      {clearLabel && (
        <button
          type="button"
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onPick('transparent')}
          className="inline-flex h-6 items-center rounded-md border border-grey-200 px-2 text-xs font-semibold text-grey-700 hover:bg-grey-100"
        >
          {clearLabel}
        </button>
      )}
      {colors.map((color) => (
        <button
          key={color.value}
          type="button"
          aria-label={color.label}
          title={color.label}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onPick(color.value)}
          className="h-6 w-6 rounded-full border border-grey-200 hover:ring-2 hover:ring-primary-100"
          style={{ backgroundColor: color.value }}
        />
      ))}
    </div>
  )
}
