import { useEffect, useRef, useState } from 'react'
import { voucherApi } from '../../lib/voucherApi'
import VoucherPdfPreview from './VoucherPdfPreview'

const filename = '정신건강바우처 서류 양식'

function saveBlob(blob: Blob, extension: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${filename}.${extension}`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function VoucherOriginalForms() {
  const [pdf, setPdf] = useState<Blob | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const pages = useRef<HTMLDivElement>(null)
  const printFrame = useRef<HTMLIFrameElement | null>(null)

  useEffect(() => {
    let cancelled = false
    setPdf(null); setReady(false); setError('')
    voucherApi<Blob>('original/pdf', 'GET', undefined, true)
      .then(value => { if (!cancelled) setPdf(value) })
      .catch(e => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [attempt])
  useEffect(() => () => { printFrame.current?.remove() }, [])

  async function saveHwpx() {
    setBusy(true); setError('')
    try { saveBlob(await voucherApi<Blob>('original/hwpx', 'GET', undefined, true), 'hwpx') }
    catch (e) { setError(e instanceof Error ? e.message : '한글 원본을 저장하지 못했습니다.') }
    finally { setBusy(false) }
  }

  async function print() {
    if (!ready || !pages.current) return
    setBusy(true); setError('')
    try {
      printFrame.current?.remove()
      const frame = document.createElement('iframe')
      frame.title = '바우처 원본 인쇄'
      frame.style.cssText = 'position:fixed;left:-10000px;top:0;width:1px;height:1px;border:0'
      document.body.append(frame)
      printFrame.current = frame
      const doc = frame.contentDocument!
      doc.title = filename
      const style = doc.createElement('style')
      style.textContent = '@page{size:A4;margin:0}html,body{margin:0;padding:0}img{display:block;break-after:page;max-width:100%;print-color-adjust:exact}img:last-child{break-after:auto}'
      doc.head.append(style)
      const images = Array.from(pages.current.querySelectorAll('canvas')).map(canvas => {
        const image = doc.createElement('img')
        image.alt = canvas.getAttribute('aria-label') || '바우처 원본 양식'
        image.style.width = `${canvas.dataset.pageWidth}pt`
        image.style.height = `${canvas.dataset.pageHeight}pt`
        image.src = canvas.toDataURL('image/png')
        doc.body.append(image)
        return image
      })
      if (!images.length) throw new Error('인쇄할 양식을 먼저 불러와 주세요.')
      await Promise.all(images.map(image => image.decode()))
      if (printFrame.current !== frame || !frame.isConnected) return
      frame.contentWindow!.addEventListener('afterprint', () => frame.remove(), { once: true })
      frame.contentWindow!.focus()
      frame.contentWindow!.print()
    } catch (e) {
      setError(e instanceof Error ? e.message : '인쇄 창을 열지 못했습니다. PDF 저장 후 인쇄해주세요.')
    } finally { setBusy(false) }
  }

  return <section aria-label="바우처 원본 양식">
    <div className="relative z-10 mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-white p-4 shadow-sm">
      <div><h2 className="font-bold">바우처 원본 양식</h2><p className="mt-1 text-sm text-slate-600">아리심리상담센터 · {filename}.hwpx</p></div>
      <div className="flex flex-wrap gap-2">
        <button type="button" className="rounded-lg bg-blue-600 px-4 py-2 font-semibold text-white disabled:opacity-40" disabled={!ready || busy} onClick={print}>인쇄</button>
        <button type="button" className="rounded-lg border px-4 py-2 font-semibold disabled:opacity-40" disabled={!pdf || busy} onClick={() => pdf && saveBlob(pdf, 'pdf')}>PDF 저장</button>
        <button type="button" className="rounded-lg border px-4 py-2 font-semibold disabled:opacity-40" disabled={busy} onClick={saveHwpx}>HWPX 저장</button>
      </div>
    </div>
    <p className="mb-4 text-sm text-slate-600">기록지·계약서·계획서·검사지 등 전달받은 원본 서류 전체입니다. 바로 인쇄해 작성하거나, HWPX로 저장해 한글에서 작성할 수 있습니다.</p>
    {error && <p role="alert" className="mb-3 rounded bg-red-50 p-3 text-red-700">{error}</p>}
    {!pdf && !error && <p role="status" className="rounded border bg-white p-8">바우처 원본 양식을 불러오고 있습니다…</p>}
    <div ref={pages}>{pdf && <VoucherPdfPreview blob={pdf} onReady={setReady} maxPages={32} title="바우처 원본 양식 미리보기" />}</div>
    {(!ready || error) && <button type="button" className="mt-3 rounded border px-4 py-2" onClick={() => setAttempt(value => value + 1)}>원본 다시 불러오기</button>}
  </section>
}
