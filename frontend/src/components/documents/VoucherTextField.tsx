import { useId } from 'react'
import type { VoucherEdition, VoucherTemplate } from '../../lib/voucherApi'

export type FieldLayout = { width: number; size: number; maxLines: number }
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

export function measureVoucherText(text: string, layout: FieldLayout, advances: Map<number, number>, legacyContract = false) {
  const count = Array.from(text).length
  if (!count) return { count, lines: 0, unsupported: false }
  // Contract typography substitutions are also made by the standard contract renderer.
  const source = legacyContract ? text.replace(/[①②③④]/g, c => '(' + ('①②③④'.indexOf(c) + 1) + ')').replace(/･/g, '·') : text
  let lines = 0
  let unsupported = false
  for (const paragraph of source.replace(/\r\n?/g, '\n').split('\n')) {
    lines++
    let width = 0
    let column = 0
    for (const char of paragraph) {
      const run = char === '\t' ? ' '.repeat(legacyContract ? 4 : 4 - column % 4) : char
      for (const glyph of run) {
        const advance = advances.get(glyph.codePointAt(0)!)
        if (advance === undefined) unsupported = true
        const unit = (advance ?? 1000) * layout.size / 1000
        if (width > 0 && width + unit > layout.width + 0.000001) { lines++; width = 0 }
        width += unit
        column++
      }
    }
  }
  return { count, lines, unsupported }
}

export default function VoucherTextField({ field, serverError, label, accessibleLabel = label, value, onChange, layout, advances, legacyContract = false }:
  { field: string; serverError?: string; label: string; accessibleLabel?: string; value: string; onChange: (text: string) => void;
    layout: FieldLayout; advances: Map<number, number>; legacyContract?: boolean }) {
  const id = useId()
  const fit = measureVoucherText(value, layout, advances, legacyContract)
  const over = fit.lines - layout.maxLines
  const invalid = over > 0 || fit.unsupported || Boolean(serverError)
  return <div className="min-w-0">
    <label htmlFor={id} className="font-semibold">{label}</label>
    <textarea id={id} data-output-field={field} aria-label={accessibleLabel} aria-describedby={id + '-hint'} aria-invalid={invalid}
      value={value} onChange={e => onChange(e.target.value)} rows={Math.min(4, Math.max(2, layout.maxLines))}
      className={'rm-textarea mt-1 min-h-16 [field-sizing:content] ' + (invalid ? 'border-red-600 bg-red-50' : '')} />
    <div id={id + '-hint'} className={'mt-1 flex flex-wrap items-baseline gap-x-3 text-xs ' + (invalid ? 'font-semibold text-red-700' : 'text-slate-600')}>
      <span>{fit.count.toLocaleString('ko-KR')}자 · 출력 예상 {fit.lines}/{layout.maxLines}줄</span>
      <span aria-live="polite">{serverError || (fit.unsupported ? '출력할 수 없는 문자를 바꿔주세요.' : over > 0 ? '출력 칸보다 ' + over + '줄 길어요.' : '')}</span>
    </div>
  </div>
}
