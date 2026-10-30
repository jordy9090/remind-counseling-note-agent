import { useEffect, useRef, useState } from 'react'
import VoucherPdfPreview from './VoucherPdfPreview'
import { fetchCaseDashboard } from '../../api/client'
import type { CaseDashboardResponse, CaseListItem } from '../../types/session'
import { voucherApi, type VoucherDocument, type VoucherForm, type VoucherRow, type VoucherTemplate } from '../../lib/voucherApi'

const label = { form10: '서비스 제공기록지 · 제10호', form26: '서비스 제공계획서 · 제26호' }
const monthNow = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit' }).format(new Date())
const blank = (template: VoucherTemplate): VoucherForm => ({ template, report_month: monthNow(), service_tier: '', rows: [], general_comment: '', purpose: '', content: '', schedule: '', price: '', contract_period: '', plan_left: '', plan_right: '' })
const fieldLabels = { purpose: '서비스 목적', content: '서비스 내용', schedule: '제공 횟수·시간·일정', price: '서비스가격·정부지원금·본인부담금', contract_period: '계약기간', plan_left: '서비스 제공계획', plan_right: '추가 제공계획' } as const

export default function VoucherWorkspace({ cases, initialCaseId, initialNoteId, onClose }: {
  cases: CaseListItem[]; initialCaseId?: string; initialNoteId?: string | null; onClose: () => void
}) {
  const [caseId, setCaseId] = useState(initialCaseId || cases[0]?.case_id || '')
  const [form, setForm] = useState(blank('form10'))
  const [dashboard, setDashboard] = useState<CaseDashboardResponse | null>(null)
  const [selections, setSelections] = useState<Record<string, { number: string; date: string; attested: boolean }>>({})
  const [hashes, setHashes] = useState<Record<string, string>>({})
  const [candidate, setCandidate] = useState<VoucherDocument | null>(null)
  const [history, setHistory] = useState<VoucherDocument[]>([])
  const [caps, setCaps] = useState<{ enabled: boolean; formats: { pdf: boolean; hwpx: boolean } } | null>(null)
  const [preview, setPreview] = useState<Blob | null>(null)
  const [previewReady, setPreviewReady] = useState(false)
  const [privacy, setPrivacy] = useState(false)
  const [offline, setOffline] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const run = useRef(0)
  const operationKey = useRef(crypto.randomUUID())
  const clearReview = () => { setCandidate(null); setPreview(null); setPreviewReady(false); setPrivacy(false); setOffline(false); operationKey.current = crypto.randomUUID() }
  const change = (next: VoucherForm) => { setForm(next); clearReview() }

  useEffect(() => {
    let cancelled = false
    voucherApi<NonNullable<typeof caps>>('capabilities').then(value => { if (!cancelled) setCaps(value) }).catch(e => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    const current = ++run.current
    setDashboard(null); setSelections({}); setHashes({}); setHistory([]); setForm(blank('form10')); clearReview()
    if (!caseId) return
    fetchCaseDashboard(caseId).then(value => {
      if (current !== run.current) return
      setDashboard(value)
      const doc = value.documents.find(d => d.document_id === initialNoteId && d.status === 'confirmed')
      const session = value.sessions.find(s => s.session_number === doc?.session_number)
      if (doc) setSelections({ [doc.document_id]: { number: '', date: session?.session_date || '', attested: false } })
    }).catch(e => { if (current === run.current) setError(e.message) })
    return () => { run.current++ }
  }, [caseId, initialNoteId])
  useEffect(() => {
    let cancelled = false
    if (caseId && caps?.enabled) voucherApi<VoucherDocument[]>(`saved?case_id=${encodeURIComponent(caseId)}`).then(value => { if (!cancelled) setHistory(value) }).catch(e => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [caseId, caps, candidate?.id, candidate?.reviewed_at])
  const task = async (fn: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await fn() } catch (e) { setError(e instanceof Error ? e.message : '요청을 완료하지 못했습니다.') } finally { setBusy(false) }
  }
  const openPreview = async (doc: VoucherDocument) => {
    setPreview(null); setPreviewReady(false); setCandidate(doc); setForm(doc.snapshot.form); setHashes(doc.snapshot.sources); setPrivacy(false); setOffline(false)
    const blob = await voucherApi<Blob>(`saved/${doc.id}/preview`, 'GET', undefined, true)
    setPreview(blob)
  }
  const load = () => task(async () => {
    const sources = Object.entries(selections).map(([note_id, s]) => ({ note_id, voucher_session_no: Number(s.number), actual_service_date: s.date, delivered_attested: s.attested }))
    const mapped = await voucherApi<{ rows: VoucherRow[]; source_hashes: Record<string, string> }>('map', 'POST', { case_id: caseId, sources })
    change({ ...form, rows: mapped.rows }); setHashes(mapped.source_hashes)
  })
  const download = (format: 'pdf' | 'hwpx') => task(async () => {
    if (!candidate) return
    const blob = await voucherApi<Blob>(`saved/${candidate.id}/export`, 'POST', { format }, true)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `remind_${candidate.template}_${candidate.id}.${format}`; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
  const confirmed = dashboard?.documents.filter(d => d.document_type === 'session_note' && d.status === 'confirmed') || []
  return <div role="dialog" aria-modal="true" aria-label="전마투 서식 작성" className="fixed inset-0 z-[80] overflow-y-auto bg-slate-50 p-4 sm:p-8">
    <div className="mx-auto max-w-6xl">
      <div className="flex items-center justify-between"><h1 className="text-xl font-bold">전마투 서식 작성</h1><button type="button" disabled={busy} onClick={onClose} className="rm-input w-auto">닫기</button></div>
      <p className="my-3 text-sm text-slate-600">정신건강 심리상담 바우처사업 작성용 문서입니다. 기관에서 기본정보와 서명을 보완해 주세요.</p>
      {error && <p role="alert" className="my-3 rounded bg-red-50 p-3 text-red-700">{error}</p>}
      {!caps?.enabled ? <p role="status" className="rounded bg-white p-6">전마투 서식 출력을 준비하고 있습니다. 서식·저장소 확인 후 제공됩니다.</p> : <>
        <fieldset disabled={busy} className="rounded-xl border bg-white p-5">
          <div className="grid gap-4 sm:grid-cols-3">
            <label>내담자<select aria-label="내담자" className="rm-input mt-1" value={caseId} onChange={e => setCaseId(e.target.value)}>{cases.map(c => <option key={c.case_id} value={c.case_id}>{c.case_alias || c.case_id}</option>)}</select></label>
            <label>서식<select aria-label="서식" className="rm-input mt-1" value={form.template} onChange={e => { change(blank(e.target.value as VoucherTemplate)); setHashes({}) }}>{Object.entries(label).map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>
            <label>작성월<input className="rm-input mt-1" type="month" value={form.report_month} onChange={e => change({ ...form, report_month: e.target.value })} /></label>
          </div>
          {form.template === 'form10' && <section className="mt-5">
            <h2 className="font-bold">검토 완료된 회기 가져오기</h2>
            <p className="my-2 text-sm text-slate-600">일반 상담 회차와 바우처 회차는 다를 수 있습니다. 실제 제공일과 해당 과정의 1~8회차를 직접 확인해주세요.</p>
            {!confirmed.length && <p>먼저 회기 요약을 저장하고 검토 완료해주세요.</p>}
            {confirmed.map(doc => {
              const selection = selections[doc.document_id]
              const update = (value: Partial<NonNullable<typeof selection>>) => { setSelections({ ...selections, [doc.document_id]: { ...selection, ...value } }); change({ ...form, rows: [] }); setHashes({}) }
              return <div key={doc.document_id} className="my-2 flex flex-wrap items-center gap-3 rounded border p-3">
                <label><input type="checkbox" checked={!!selection} onChange={e => { const next = { ...selections }; if (e.target.checked) next[doc.document_id] = { number: '', date: dashboard?.sessions.find(s => s.session_number === doc.session_number)?.session_date || '', attested: false }; else delete next[doc.document_id]; setSelections(next); change({ ...form, rows: [] }); setHashes({}) }} /> 상담 {doc.session_number}회기</label>
                {selection && <><label>바우처 회차<input aria-label={`상담 ${doc.session_number}회기 바우처 회차`} className="rm-input w-20" type="number" min="1" max="8" value={selection.number} onChange={e => update({ number: e.target.value })} /></label><label>제공일<input className="rm-input" type="date" value={selection.date} onChange={e => update({ date: e.target.value })} /></label><label><input type="checkbox" checked={selection.attested} onChange={e => update({ attested: e.target.checked })} /> 실제 제공한 서비스입니다</label></>}
              </div>
            })}
            <button type="button" disabled={!Object.keys(selections).length || Object.values(selections).some(s => !s.number || !s.date || !s.attested)} onClick={load} className="mt-2 rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-40">확정 내용 가져오기</button>
            <label className="mt-4 block">서비스 유형<select className="rm-input" value={form.service_tier} onChange={e => change({ ...form, service_tier: e.target.value as VoucherForm['service_tier'] })}><option value="">기관에서 확인</option><option value="type_1">1급 유형</option><option value="type_2">2급 유형</option></select></label>
            {form.rows.map((row, i) => <div key={row.note_id} className="mt-4"><h3 className="font-semibold">바우처 {row.voucher_session_no}회차 · {row.actual_service_date}</h3><div className="grid gap-3 sm:grid-cols-2">{(['content_left', 'content_right'] as const).map((key, j) => <label key={key}>{j === 0 ? '서비스 내용' : '개입·반응 / 검사결과 등 추가 기록'}<textarea aria-label={`바우처 ${row.voucher_session_no}회차 ${j === 0 ? '서비스 내용' : '추가 기록'}`} className="rm-textarea min-h-28" value={row[key]} onChange={e => change({ ...form, rows: form.rows.map((r, index) => index === i ? { ...r, [key]: e.target.value } : r) })} /></label>)}</div></div>)}
            <label className="mt-4 block">비고·종합의견 / 확인된 전후 검사결과<textarea aria-label="비고·종합의견" className="rm-textarea min-h-24" value={form.general_comment} onChange={e => change({ ...form, general_comment: e.target.value })} /></label>
            <p className="text-xs text-slate-500">검사값을 추정해 넣지 마세요. 아직 종결 전이라면 사후 검사결과는 비워둘 수 있습니다.</p>
          </section>}
          {form.template === 'form26' && <div className="mt-4 grid gap-4 sm:grid-cols-2"><p className="text-sm text-slate-600 sm:col-span-2">첫 회기 전에도 직접 작성할 수 있습니다. 모르는 일정·금액은 비워두고 기관에서 보완해주세요.</p>{Object.entries(fieldLabels).map(([key, title]) => <label key={key}>{title}<textarea aria-label={title} className="rm-textarea min-h-24" value={form[key as keyof typeof fieldLabels]} onChange={e => change({ ...form, [key]: e.target.value })} /></label>)}</div>}
          <button type="button" className="mt-5 rounded bg-blue-600 px-5 py-3 font-bold text-white disabled:opacity-40" disabled={!caseId || (form.template === 'form10' && !form.rows.length)} onClick={() => task(async () => {
            const doc = candidate || await voucherApi<VoucherDocument>('prepare', 'POST', { case_id: caseId, operation_key: operationKey.current, form, source_hashes: hashes }); await openPreview(doc)
          })}>{busy ? '처리 중…' : '출력 내용 확인'}</button>
        </fieldset>
        {candidate && <section className="mt-5 rounded-xl border bg-white p-5"><h2 className="font-bold">출력 미리보기</h2><p className="my-2 text-sm">{candidate.privacy_status === 'degraded' ? '자동 식별정보 확인이 제한되었습니다. 남은 이름·기관·연락처를 확인해 주세요.' : '출력 내용을 확인해주세요. 자동 처리가 모든 식별정보를 제거한다고 보장하지 않습니다.'}</p>{preview && <VoucherPdfPreview blob={preview} onReady={setPreviewReady} />}
          {candidate.reviewed_at ? <p className="my-3 font-bold text-green-700">검토 완료 · 기관 보완 필요</p> : <div className="my-4 space-y-3"><label className="block"><input type="checkbox" checked={privacy} onChange={e => setPrivacy(e.target.checked)} /> 미리보기의 내용과 남아 있는 식별정보를 확인했습니다.</label><label className="block"><input type="checkbox" checked={offline} onChange={e => setOffline(e.target.checked)} /> 기본정보·서명·미기입 항목은 기관에서 보완하겠습니다.</label><button type="button" disabled={busy || !privacy || !offline || !previewReady} className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-40" onClick={() => task(async () => setCandidate(await voucherApi<VoucherDocument>(`saved/${candidate.id}/review`, 'POST', { fingerprint: candidate.fingerprint, human_privacy_reviewed: true, acknowledged_offline_completion: true }))) }>내용 검토 완료</button></div>}
          <div className="flex gap-3">{(['pdf', 'hwpx'] as const).map(format => <button type="button" key={format} className="rounded border px-4 py-2 disabled:opacity-40" disabled={busy || !candidate.reviewed_at || !caps.formats[format]} onClick={() => download(format)}>{format.toUpperCase()} 다운로드</button>)}</div>{!caps.formats.hwpx && <p className="mt-2 text-sm text-slate-500">HWPX는 문서 편집기 호환성 확인 후 제공됩니다.</p>}</section>}
        <section className="mt-5 rounded-xl border bg-white p-5"><h2 className="font-bold">저장한 전마투 문서</h2>{history.map(doc => <div key={doc.id} className="mt-2 flex justify-between border-b py-2"><button disabled={busy} type="button" onClick={() => task(async () => openPreview(await voucherApi<VoucherDocument>(`saved/${doc.id}`)))}>{label[doc.template]} · {doc.reviewed_at ? '검토 완료' : '검토 전'} · {new Date(doc.created_at).toLocaleDateString('ko-KR')}</button><button disabled={busy} type="button" onClick={() => { if (window.confirm('이 서식 문서를 삭제할까요? 원래 회기 기록은 유지됩니다.')) void task(async () => { await voucherApi(`saved/${doc.id}`, 'DELETE'); setHistory(history.filter(d => d.id !== doc.id)); if (candidate?.id === doc.id) clearReview() }) }}>삭제</button></div>)}</section>
      </>}
    </div>
  </div>
}
