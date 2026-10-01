import { useEffect, useLayoutEffect, useRef, type FocusEvent, type KeyboardEvent } from 'react'

import { richHtmlToPlainText, sanitizeRichHtml } from '../../lib/richText'

/** Marks the editable regions the formatting toolbar may act on. */
export const RICH_TEXT_FIELD_ATTRIBUTE = 'data-rich-text-field'

/**
 * Editable formatted-text region for the final document. The toolbar in FinalDocumentEditor applies
 * formatting to the current selection; this component reports the sanitized markup and its
 * plain-text projection on every change.
 */
export default function RichTextField({
  html,
  onChange,
  ariaLabel,
  ariaLabelledBy,
  autoFocus = false,
  className,
  id,
  onBlur,
  onKeyDown,
}: {
  html: string
  onChange: (html: string, text: string) => void
  ariaLabel?: string
  ariaLabelledBy?: string
  autoFocus?: boolean
  className?: string
  id?: string
  onBlur?: (event: FocusEvent<HTMLDivElement>) => void
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void
}) {
  const fieldRef = useRef<HTMLDivElement>(null)
  // The markup this field last rendered or reported. The DOM is rewritten only when the parent
  // supplies something else, so typing never resets the caret.
  const lastHtml = useRef<string | null>(null)

  useLayoutEffect(() => {
    const field = fieldRef.current
    if (!field || lastHtml.current === html) return
    field.innerHTML = sanitizeRichHtml(html)
    lastHtml.current = html
  }, [html])

  useEffect(() => {
    const field = fieldRef.current
    if (!autoFocus || !field) return
    field.focus()
    const selection = window.getSelection()
    if (!selection) return
    const range = document.createRange()
    range.selectNodeContents(field)
    range.collapse(false)
    selection.removeAllRanges()
    selection.addRange(range)
  }, [])

  const report = () => {
    const field = fieldRef.current
    if (!field) return
    const next = sanitizeRichHtml(field.innerHTML)
    lastHtml.current = next
    onChange(next, richHtmlToPlainText(next))
  }

  return (
    <div
      ref={fieldRef}
      id={id}
      role="textbox"
      aria-multiline="true"
      aria-label={ariaLabel}
      aria-labelledby={ariaLabelledBy}
      contentEditable
      suppressContentEditableWarning
      {...{ [RICH_TEXT_FIELD_ATTRIBUTE]: '' }}
      onInput={report}
      onBlur={onBlur}
      onKeyDown={onKeyDown}
      // Pasted and dropped content is inserted as plain text; formatting comes from the toolbar only.
      onPaste={(event) => {
        event.preventDefault()
        const text = event.clipboardData.getData('text/plain')
        if (text) document.execCommand('insertText', false, text)
      }}
      onDrop={(event) => event.preventDefault()}
      className={className}
    />
  )
}
