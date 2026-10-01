/**
 * Formatted text for the final document editor.
 *
 * The editor keeps a small HTML subset (bold, italic, underline, text color, highlight, alignment,
 * lists) next to the plain text. Markup is always rebuilt from an allowlist before it is rendered
 * or stored, and the export API parses it again on the server.
 */

const INLINE_TAGS: Record<string, string> = { B: 'b', STRONG: 'b', I: 'i', EM: 'i', U: 'u', SPAN: 'span', FONT: 'span' }
const BLOCK_TAGS: Record<string, string> = { DIV: 'div', P: 'div', UL: 'ul', OL: 'ol', LI: 'li' }
const DROPPED_TAGS = new Set(['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'IFRAME', 'OBJECT', 'EMBED', 'HEAD', 'TITLE', 'SVG', 'MATH'])
const ALIGNMENTS = new Set(['center', 'right'])

export function escapeHtml(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** "#rrggbb" for a hex or rgb()/rgba() color; null for anything else, including fully transparent. */
export function normalizeColor(value: string | null | undefined): string | null {
  const text = (value || '').trim().toLowerCase()
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/.exec(text)
  if (hex) return hex[1].length === 3 ? `#${hex[1].split('').map((char) => char + char).join('')}` : text
  const rgb = /^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([0-9.]+)\s*)?\)$/.exec(text)
  if (!rgb) return null
  const channels = [rgb[1], rgb[2], rgb[3]].map(Number)
  if (channels.some((channel) => channel > 255)) return null
  if (rgb[4] !== undefined && Number(rgb[4]) === 0) return null
  return `#${channels.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`
}

function styleDeclarations(element: Element): Record<string, string> {
  const declarations: Record<string, string> = {}
  for (const part of (element.getAttribute('style') || '').split(';')) {
    const index = part.indexOf(':')
    if (index > 0) declarations[part.slice(0, index).trim().toLowerCase()] = part.slice(index + 1).trim().toLowerCase()
  }
  return declarations
}

function inlineStyle(element: Element): string {
  const declarations = styleDeclarations(element)
  const styles: string[] = []
  const weight = declarations['font-weight'] || ''
  if (weight === 'bold' || weight === 'bolder' || Number(weight) >= 600) styles.push('font-weight:bold')
  if (declarations['font-style'] === 'italic' || declarations['font-style'] === 'oblique') styles.push('font-style:italic')
  if (`${declarations['text-decoration'] || ''} ${declarations['text-decoration-line'] || ''}`.includes('underline')) {
    styles.push('text-decoration:underline')
  }
  const color = normalizeColor(declarations.color) || (element.tagName === 'FONT' ? normalizeColor(element.getAttribute('color')) : null)
  if (color) styles.push(`color:${color}`)
  const highlight = normalizeColor(declarations['background-color'])
  if (highlight) styles.push(`background-color:${highlight}`)
  return styles.join(';')
}

function blockAlignment(element: Element): string {
  const candidates = [styleDeclarations(element)['text-align'], (element.getAttribute('align') || '').trim().toLowerCase()]
  return candidates.find((candidate) => candidate && ALIGNMENTS.has(candidate)) || ''
}

function serializeNode(node: Node): string {
  if (node.nodeType === 3) return escapeHtml(node.textContent || '')
  if (node.nodeType !== 1) return ''
  const element = node as Element
  const tag = element.tagName.toUpperCase()
  if (DROPPED_TAGS.has(tag)) return ''
  if (tag === 'BR') return '<br>'
  const inner = Array.from(element.childNodes).map(serializeNode).join('')
  if (INLINE_TAGS[tag]) {
    const name = INLINE_TAGS[tag]
    const style = inlineStyle(element)
    // A span without any kept style carries nothing; keep only its content.
    if (name === 'span' && !style) return inner
    return `<${name}${style ? ` style="${style}"` : ''}>${inner}</${name}>`
  }
  if (BLOCK_TAGS[tag]) {
    const name = BLOCK_TAGS[tag]
    const align = name === 'div' || name === 'li' ? blockAlignment(element) : ''
    return `<${name}${align ? ` style="text-align:${align}"` : ''}>${inner}</${name}>`
  }
  return inner
}

function parseBody(html: string): HTMLElement {
  // A parsed document is inert: nothing in it runs or loads while it is being read.
  return new DOMParser().parseFromString(`<!doctype html><body>${html}`, 'text/html').body
}

/** Rebuild editor markup from the allowlist. Unknown tags keep their text; scripts and styles are dropped. */
export function sanitizeRichHtml(html: string | null | undefined): string {
  if (!html) return ''
  return Array.from(parseBody(html).childNodes).map(serializeNode).join('')
}

export function plainTextToRichHtml(text: string | null | undefined): string {
  return (text || '').replace(/\r\n?/g, '\n').split('\n').map((line) => `<div>${escapeHtml(line) || '<br>'}</div>`).join('')
}

/** Plain-text projection of editor markup: one line per block, list items prefixed like typed lists. */
export function richHtmlToPlainText(html: string | null | undefined): string {
  if (!html) return ''
  const lines: string[] = []
  let current = ''
  let pending = false
  const flush = (force = false) => {
    if (!pending && !force) return
    lines.push(current)
    current = ''
    pending = false
  }
  const walk = (node: Node, listKind: string | null, counter: { value: number }) => {
    if (node.nodeType === 3) {
      const text = (node.textContent || '').replace(/[\r\n]+/g, ' ').replace(/ /g, ' ')
      if (text) {
        current += text
        pending = true
      }
      return
    }
    if (node.nodeType !== 1) return
    const element = node as Element
    const tag = element.tagName.toUpperCase()
    if (DROPPED_TAGS.has(tag)) return
    if (tag === 'BR') {
      flush(true)
      return
    }
    const isBlock = Boolean(BLOCK_TAGS[tag])
    if (isBlock) flush()
    if (tag === 'LI') {
      counter.value += 1
      current = listKind === 'OL' ? `${counter.value}. ` : '• '
    }
    const childList = tag === 'UL' || tag === 'OL' ? tag : listKind
    const childCounter = tag === 'UL' || tag === 'OL' ? { value: 0 } : counter
    element.childNodes.forEach((child) => walk(child, childList, childCounter))
    if (isBlock) flush()
    if (tag === 'LI') current = ''
  }
  parseBody(html).childNodes.forEach((child) => walk(child, null, { value: 0 }))
  flush()
  while (lines.length && !lines[lines.length - 1].trim()) lines.pop()
  return lines.join('\n')
}

/** True when the markup carries formatting that plain text cannot express. */
export function hasRichFormatting(html: string | null | undefined): boolean {
  return Boolean(html) && /<(?:b|i|u|span|ul|ol)\b|\sstyle="/.test(html as string)
}
