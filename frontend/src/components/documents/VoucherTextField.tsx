import { useId } from 'react'
import type { VoucherEdition, VoucherTemplate } from '../../lib/voucherApi'

export type FieldLayout = { width: number; size: number; maxLines: number; maxChars?: number }
type WidthGroup = [number, [number, number][]]
export type VoucherCapabilities = {
  enabled: boolean
  formats: { pdf: boolean; hwpx: boolean }
  layout: Record<VoucherEdition, Record<VoucherTemplate, Record<string, FieldLayout>>>
  fontWidths: WidthGroup[]
}

export function fontAdvances(groups: WidthGroup[]) {
  const advances = new Map<number, number>()
  for (const [width, ranges] of groups) {
    for (const [first, last] of ranges) {
      for (let code = first; code <= last; code++) advances.set(code, width)
    }
  }
  return advances
}

const contractGlyphs: Record<string, string> = { '①': '(1)', '②': '(2)', '③': '(3)', '④': '(4)', '･': '·' }
const wrapTolerance = 0.000001

export function measureVoucherText(text: string, layout: FieldLayout, advances: Map<number, number>, legacyContract = false) {
  let count = 0
  let fittingCharacters = 0
  let lines = text ? 1 : 0
  let width = 0
  let lastFittingWidth = 0
  let column = 0
  let unsupported = false
  for (const char of text.replace(/\r\n?/g, '\n')) {
    count++
    if (char === '\n') {
      lines++
      width = 0
      column = 0
    } else {
      const printed = legacyContract ? contractGlyphs[char] ?? char : char
      const run = char === '\t' ? ' '.repeat(legacyContract ? 4 : 4 - column % 4) : printed
      for (const glyph of run) {
        const advance = advances.get(glyph.codePointAt(0)!)
        if (advance === undefined) unsupported = true
        const unit = (advance ?? 1000) * layout.size / 1000
        if (width > 0 && width + unit > layout.width + wrapTolerance) { lines++; width = 0 }
        width += unit
        column++
      }
    }
    if (lines <= layout.maxLines) {
      fittingCharacters++
      lastFittingWidth = width
    }
  }

  // Express the remaining width in full Hangul syllables, using the same font as the export.
  const hangulWidth = (advances.get('가'.codePointAt(0)!) ?? 1000) * layout.size / 1000
  const slotsIn = (points: number) => Math.max(0, Math.floor((points + wrapTolerance) / hangulWidth))
  const remaining = lines > 0 ? slotsIn(layout.width - lastFittingWidth) : 0
  const freeLines = Math.max(0, layout.maxLines - lines)
  const capacity = Math.min(layout.maxChars ?? Infinity, fittingCharacters + remaining + freeLines * slotsIn(layout.width))
  return { count, capacity, lines, unsupported }
}

export default function VoucherTextField({ field, serverError, label, accessibleLabel = label, value, onChange, layout, advances, legacyContract = false }:
  { field: string; serverError?: string; label: string; accessibleLabel?: string; value: string; onChange: (text: string) => void;
    layout: FieldLayout; advances: Map<number, number>; legacyContract?: boolean }) {
  const id = useId()
  const fit = measureVoucherText(value, layout, advances, legacyContract)
  const over = fit.lines - layout.maxLines
  const excessChars = Math.max(0, fit.count - (layout.maxChars ?? Infinity))
  const invalid = over > 0 || excessChars > 0 || fit.unsupported || Boolean(serverError)
  return <div className="min-w-0">
    <label htmlFor={id} className="font-semibold">{label}</label>
    <textarea id={id} data-output-field={field} aria-label={accessibleLabel} aria-describedby={id + '-hint'} aria-invalid={invalid}
      value={value} onChange={e => onChange(e.target.value)} rows={Math.min(4, Math.max(2, layout.maxLines))}
      className={'rm-textarea mt-1 min-h-16 [field-sizing:content] ' + (invalid ? 'border-red-600 bg-red-50' : '')} />
    <div id={id + '-hint'} className={'mt-1 flex flex-wrap items-baseline gap-x-3 text-xs ' + (invalid ? 'font-semibold text-red-700' : 'text-slate-600')}>
      <span className="font-semibold tabular-nums">{fit.count.toLocaleString('ko-KR')}/{fit.capacity.toLocaleString('ko-KR')}자</span>
      <span>한글 기준 · 출력 예상 {fit.lines}/{layout.maxLines}줄</span>
      <span aria-live="polite">{serverError || (fit.unsupported ? '출력할 수 없는 문자를 바꿔주세요.' : over > 0 ? '출력 칸보다 ' + over + '줄 길어요.' : excessChars > 0 ? excessChars + '자를 줄여주세요.' : '')}</span>
    </div>
  </div>
}
