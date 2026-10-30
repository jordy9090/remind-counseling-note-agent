import { useEffect, useRef, useState } from 'react'
import type { PDFDocumentLoadingTask } from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

/** Render the downloaded bytes locally, including browsers without a PDF plugin. */
export default function VoucherPdfPreview({ blob, onReady }: { blob: Blob; onReady: (ready: boolean) => void }) {
  const host = useRef<HTMLDivElement>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  useEffect(() => {
    let cancelled = false
    let loading: PDFDocumentLoadingTask | undefined
    const target = host.current!
    target.replaceChildren()
    setState('loading'); onReady(false)
    void (async () => {
      try {
        const pdfjs = await import('pdfjs-dist')
        const data = new Uint8Array(await blob.arrayBuffer())
        if (cancelled) return
        pdfjs.GlobalWorkerOptions.workerSrc = workerUrl
        loading = pdfjs.getDocument({ data })
        const pdf = await loading.promise
        // Voucher documents are bounded forms, not arbitrary uploaded PDFs.
        if (pdf.numPages < 1 || pdf.numPages > 8) throw new Error('Unexpected page count')
        for (let index = 1; index <= pdf.numPages; index++) {
          const page = await pdf.getPage(index)
          if (cancelled) return
          const viewport = page.getViewport({ scale: 1.75 })
          const canvas = document.createElement('canvas')
          canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height)
          canvas.className = 'mx-auto mb-4 block h-auto w-full max-w-[900px] bg-white shadow'
          canvas.setAttribute('role', 'img')
          canvas.setAttribute('aria-label', `전마투 PDF ${index} / ${pdf.numPages}페이지`)
          target.append(canvas)
          await page.render({ canvas, viewport }).promise
        }
        if (!cancelled) { setState('ready'); onReady(true) }
      } catch {
        if (!cancelled) { target.replaceChildren(); setState('error'); onReady(false) }
      }
    })()
    return () => { cancelled = true; target.replaceChildren(); void loading?.destroy() }
  }, [blob, onReady])
  return <div className="rounded border bg-slate-100 p-2" aria-busy={state === 'loading'} data-rendered={state === 'ready'} title={state === 'ready' ? '실제 출력될 전마투 PDF' : undefined}>
    {state === 'loading' && <p role="status" className="p-6">PDF를 화면에 표시하고 있습니다…</p>}
    {state === 'error' && <p role="alert" className="p-6 text-red-700">PDF를 표시하지 못했습니다. ‘출력 내용 확인’을 다시 눌러주세요. 표시되기 전에는 검토를 완료할 수 없습니다.</p>}
    <div ref={host} hidden={state !== 'ready'} />
  </div>
}
