import { useEffect, useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import VoucherTextField, { fontAdvances, measureVoucherText, type VoucherCapabilities } from './VoucherTextField'
import VoucherPdfPreview from './VoucherPdfPreview'
import VoucherOriginalForms from './VoucherOriginalForms'
import { fetchCaseDashboard } from '../../api/client'
import type { CaseDashboardResponse, CaseListItem } from '../../types/session'
import { voucherApi, VoucherRequestError, type VoucherDocument, type VoucherEdition, type VoucherForm, type VoucherRow, type VoucherTemplate } from '../../lib/voucherApi'

const label = { form10: '서비스 제공기록지 · 제10호', form25: '서비스 제공(이용)계약서 · 제25호', form26: '서비스 제공계획서 · 제26호' }
const monthNow = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit' }).format(new Date())
type Selection = { number: string; date: string; attested: boolean }
const complete = (s: Selection) => Number.isInteger(Number(s.number)) && Number(s.number) >= 1 && Number(s.number) <= 8 && Boolean(s.date) && s.attested
const selectionsFor = (rows: VoucherRow[]) => Object.fromEntries(rows.map(row => [row.note_id || 'manual-' + crypto.randomUUID(), { number: String(row.voucher_session_no), date: row.actual_service_date, attested: true }]))
const blank = (template: VoucherTemplate, edition: VoucherEdition = 'ari-2026'): VoucherForm => ({ template, edition, report_month: monthNow(), service_tier: '', rows: [], general_comment: '', purpose: '', content: '', schedule: '', price: '', contract_period: '', plan_left: '', plan_right: '', additional_cost: '', refund_terms: '', other_terms: '' })
const fieldLabels = { purpose: '서비스 목적', content: '서비스 내용', schedule: '제공 횟수·시간·일정', price: '서비스가격·정부지원금·본인부담금', contract_period: '계약기간', plan_left: '서비스 제공계획', plan_right: '추가 제공계획' } as const
const contractLabels = { contract_period: '계약기간', content: '서비스 종류·내용', schedule: '제공시간·횟수·일정', price: '계약금액 (서비스가격·정부지원금·본인부담금)', additional_cost: '추가비용 발생여부·금액', refund_terms: '계약 해제·해지에 따른 환불규정', other_terms: '기타 합의사항 (선택)' } as const

export default function VoucherWorkspace({ cases, initialCaseId, initialNoteId, onClose }: {
  cases: CaseListItem[]; initialCaseId?: string; initialNoteId?: string | null; onClose: () => void
}) {
  const [mode, setMode] = useState<'original' | 'write'>('original')
  const [caseId, setCaseId] = useState(initialCaseId || cases[0]?.case_id || '')
  const [form, setForm] = useState(blank('form10'))
  const [dashboard, setDashboard] = useState<CaseDashboardResponse | null>(null)
  const [selections, setSelections] = useState<Record<string, Selection>>({})
  const [hashes, setHashes] = useState<Record<string, string>>({})
  const [candidate, setCandidate] = useState<VoucherDocument | null>(null)
  const [history, setHistory] = useState<VoucherDocument[]>([])
  const [caps, setCaps] = useState<VoucherCapabilities | null>(null)
  const [preview, setPreview] = useState<Blob | null>(null)
  const [previewReady, setPreviewReady] = useState(false)
  const [privacy, setPrivacy] = useState(false)
  const [offline, setOffline] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [errorField, setErrorField] = useState<string | undefined>()
  const run = useRef(0)
  const operationKey = useRef(crypto.randomUUID())
  const clearReview = () => { setCandidate(null); setPreview(null); setPreviewReady(false); setPrivacy(false); setOffline(false); operationKey.current = crypto.randomUUID() }
  const change = (next: VoucherForm) => { setForm(next); setError(''); setErrorField(undefined); clearReview() }

  const rowText = useRef(new Map<string, Pick<VoucherRow, 'content_left' | 'content_right'>>())
  const drafts = useRef(new Map<string, VoucherForm>())
  const edition = form.edition || 'standard'
  const center = edition === 'ari-2026'
  const advances = useMemo(() => fontAdvances(caps?.fontWidths || []), [caps])
  const profiles = caps?.layout?.[edition]?.[form.template]
  const legacyContract = !center && form.template === 'form25'
  const narrative = (key: string, title: string, value: string, onChange: (text: string) => void, accessibleLabel = title) =>
    profiles && <VoucherTextField key={key} field={key} serverError={errorField === key ? error : undefined} label={title} accessibleLabel={accessibleLabel} value={value}
      onChange={onChange} layout={profiles[key]} advances={advances} legacyContract={legacyContract} />
  const visibleFields = form.template === 'form25'
    ? Object.entries(contractLabels).filter(([key]) => !center || key === 'contract_period' || key === 'other_terms')
    : Object.entries(fieldLabels).filter(([key]) => !center || key !== 'plan_right')
  const textValues: [string, string][] = form.template === 'form10'
    ? [['general_comment', form.general_comment], ...form.rows.flatMap(row => {
      const fields: [string, string][] = [['row' + row.voucher_session_no + '_left', row.content_left]]
      if (!center) fields.push(['row' + row.voucher_session_no + '_right', row.content_right])
      return fields
    })] : visibleFields.map(([key]) => [key, form[key as keyof typeof fieldLabels] as string])
  const overflowing = profiles && textValues.some(([key, value]) => {
    const fit = measureVoucherText(value, profiles[key], advances, legacyContract)
    return fit.unsupported || fit.lines > profiles[key].maxLines
  })
  const changeTemplate = (nextTemplate: VoucherTemplate, nextEdition: VoucherEdition) => {
    drafts.current.set(edition + form.template, form)
    const next = drafts.current.get(nextEdition + nextTemplate) || blank(nextTemplate, nextEdition)
    change(next); setHashes({}); setError('')
    setSelections(selectionsFor(next.rows))
    rowText.current.clear()
  }
  const updateSelection = (next: typeof selections) => {
    const existing = Object.entries(selections).filter(([, value]) => complete(value))
    form.rows.forEach((row, i) => { if (existing[i]) rowText.current.set(existing[i][0], { content_left: row.content_left, content_right: row.content_right }) })
    const rows: VoucherRow[] = []
    for (const [id, meta] of Object.entries(next)) {
      const number = Number(meta.number)
      if (complete(meta)) {
        rows.push({ note_id: id.startsWith('manual-') ? null : id, voucher_session_no: number, actual_service_date: meta.date, delivered_attested: true,
          content_left: '', content_right: '', ...rowText.current.get(id) })
      }
    }
    setSelections(next); setHashes({}); setError(''); change({ ...form, rows })
  }

  const firstCaseId = cases[0]?.case_id
  useEffect(() => {
    if (!caseId && firstCaseId) setCaseId(firstCaseId)
  }, [caseId, firstCaseId])

  useEffect(() => {
    let cancelled = false
    voucherApi<NonNullable<typeof caps>>('capabilities').then(value => { if (!cancelled) setCaps(value) }).catch(e => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    const current = ++run.current
    drafts.current.clear(); rowText.current.clear(); setError('')
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
  const numbers = form.rows.map(row => row.voucher_session_no)
  const dateProblem = form.template === 'form10' && (new Set(numbers).size !== numbers.length
    ? '같은 바우처 회차가 두 번 선택됐습니다. 회차를 확인해주세요.'
    : form.rows.some(row => !row.actual_service_date.startsWith(form.report_month) || row.actual_service_date > new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Seoul' }).format(new Date()))
      ? '제공일은 작성월 안에서 오늘 또는 그 이전 날짜로 입력해주세요.' : '')
  const task = async (fn: () => Promise<void>) => {
    setBusy(true); setError(''); setErrorField(undefined)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : '요청을 완료하지 못했습니다.')
      if (e instanceof VoucherRequestError && e.field) {
        setErrorField(e.field)
        const field = e.field
        requestAnimationFrame(() => {
          const input = document.querySelector<HTMLTextAreaElement>('[data-output-field="' + CSS.escape(field) + '"]')
          input?.focus({ preventScroll: true }); input?.scrollIntoView({ block: 'center' })
        })
      }
    } finally { setBusy(false) }
  }
  const openPreview = async (doc: VoucherDocument) => {
    setPreview(null); setPreviewReady(false); setCandidate(doc); setForm({ ...blank(doc.template, 'standard'), ...doc.snapshot.form }); rowText.current.clear()
    setSelections(selectionsFor(doc.snapshot.form.rows)); setHashes(doc.snapshot.sources); setPrivacy(false); setOffline(false)
    const blob = await voucherApi<Blob>(`saved/${doc.id}/preview`, 'GET', undefined, true)
    setPreview(blob)
  }
  const prepare = async () => {
    let sourceHashes = hashes
    if (form.template === 'form10') {
      const sources = form.rows.filter(row => row.note_id).map(({ note_id, voucher_session_no, actual_service_date, delivered_attested }) =>
        ({ note_id, voucher_session_no, actual_service_date, delivered_attested }))
      sourceHashes = sources.length ? (await voucherApi<{ source_hashes: Record<string, string> }>('map', 'POST', { case_id: caseId, sources })).source_hashes : {}
      setHashes(sourceHashes)
    }
    return voucherApi<VoucherDocument>('prepare', 'POST', { case_id: caseId, operation_key: operationKey.current, form, source_hashes: sourceHashes })
  }
  const download = (format: 'pdf' | 'hwpx') => task(async () => {
    if (!candidate) return
    const blob = await voucherApi<Blob>(`saved/${candidate.id}/export`, 'POST', { format }, true)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `remind_${candidate.template}_${candidate.id}.${format}`; a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  })
  const confirmed = dashboard?.documents.filter(d => d.document_type === 'session_note' && d.status === 'confirmed') || []
  return <div role="dialog" aria-modal="true" aria-label="정신건강 심리상담 바우처사업 서식 작성" className="fixed inset-0 z-[80] overflow-y-auto bg-slate-50 p-4 sm:p-8">
    <div className="mx-auto max-w-6xl">
      <header className="sticky top-0 z-30 -mx-2 flex items-center justify-between gap-3 border-b border-slate-200 bg-slate-50 px-2 py-2">
        <h1 className="text-lg font-bold sm:text-xl">정신건강 심리상담 바우처사업 서식 작성</h1>
        <button type="button" aria-label="닫기" disabled={busy} onClick={onClose}
          className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-lg border border-slate-400 bg-white px-4 font-bold text-slate-900 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-blue-600"><X size={18} aria-hidden="true" />닫기</button>
      </header>
      <div className="my-4 flex flex-wrap gap-2" aria-label="바우처 이용 방식">
        <button type="button" aria-pressed={mode === 'original'} className={`rounded-lg px-4 py-2 font-semibold ${mode === 'original' ? 'bg-blue-600 text-white' : 'border bg-white'}`} disabled={busy} onClick={() => setMode('original')}>원본 양식 · 인쇄/저장</button>
        <button type="button" aria-pressed={mode === 'write'} className={`rounded-lg px-4 py-2 font-semibold ${mode === 'write' ? 'bg-blue-600 text-white' : 'border bg-white'}`} disabled={busy} onClick={() => setMode('write')}>내용 입력 · 저장한 문서</button>
      </div>
      <div hidden={mode !== 'original'}>{mode === 'original' && <VoucherOriginalForms />}</div>
      <div hidden={mode !== 'write'}>
      <p className="my-3 text-sm text-slate-600">정신건강 심리상담 바우처사업 작성용 문서입니다. 기관에서 기본정보와 서명을 보완해 주세요.</p>
      {error && <p role="alert" className="my-3 rounded bg-red-50 p-3 text-red-700">{error}</p>}
      {!caps?.enabled || !profiles ? <p role="status" className="rounded bg-white p-6">바우처 서식 출력을 준비하고 있습니다. 서식·저장소 확인 후 제공됩니다.</p> : <>
        <fieldset disabled={busy} className="rounded-xl border bg-white p-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <label>내담자<select aria-label="내담자" className="rm-input mt-1" value={caseId} onChange={e => setCaseId(e.target.value)}>{cases.map(c => <option key={c.case_id} value={c.case_id}>{c.case_alias || c.case_id}</option>)}</select></label>
            <label>출력 기준<select aria-label="출력 기준" className="rm-input mt-1" value={edition} onChange={e => changeTemplate(form.template, e.target.value as VoucherEdition)}><option value="ari-2026">아리심리상담센터 원본</option><option value="standard">기존 사업안내 서식</option></select></label>
            <label>서식<select aria-label="서식" className="rm-input mt-1" value={form.template} onChange={e => changeTemplate(e.target.value as VoucherTemplate, edition)}>{Object.entries(label).map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>
            <label>작성월<input className="rm-input mt-1" type="month" value={form.report_month} onChange={e => change({ ...form, report_month: e.target.value })} /></label>
          </div>
          {form.template === 'form10' && <section className="mt-5">
            <h2 className="font-bold">기록할 회기 선택</h2>
            <p className="my-2 text-sm text-slate-600">{center ? '직접 입력하거나 검토 완료된 회기를 선택하세요. 회차와 제공일을 확인하면 아래에 서비스 내용 칸이 열립니다.' : '검토 완료된 회기를 선택하고 실제 제공일과 바우처 회차를 확인하세요.'}</p>
            <p className="my-2 text-sm text-slate-600">일반 상담 회차와 바우처 회차는 다를 수 있습니다. 실제 제공일과 해당 과정의 1~8회차를 직접 확인해주세요.</p>
            {!confirmed.length && !center && <p>먼저 회기 요약을 저장하고 검토 완료해주세요.</p>}
            {center && <button type="button" disabled={Object.keys(selections).length >= 8} className="my-2 rounded-lg border border-blue-300 bg-blue-50 px-4 py-2 font-semibold text-blue-800 disabled:opacity-50"
              onClick={() => {
                const used = new Set(Object.values(selections).map(s => Number(s.number)))
                const number = Array.from({ length: 8 }, (_, i) => i + 1).find(n => !used.has(n))
                updateSelection({ ...selections, ['manual-' + crypto.randomUUID()]: { number: String(number || ''), date: '', attested: false } })
              }}>회차 직접 입력</button>}
            {Object.entries(selections).filter(([key]) => key.startsWith('manual-')).map(([key, s]) => {
              const update = (patch: Partial<Selection>) => updateSelection({ ...selections, [key]: { ...s, ...patch } })
              return <div key={key} className="my-2 flex flex-wrap items-end gap-3 rounded-lg border p-3">
                <label>바우처 회차<input className="rm-input w-20" type="number" min="1" max="8" value={s.number} onChange={e => update({ number: e.target.value })} /></label>
                <label>제공일<input className="rm-input" type="date" value={s.date} onChange={e => update({ date: e.target.value })} /></label>
                <label><input type="checkbox" checked={s.attested} onChange={e => update({ attested: e.target.checked })} /> 실제 제공한 서비스입니다</label>
                <button type="button" className="rounded border px-2 py-1" onClick={() => { const next = { ...selections }; delete next[key]; updateSelection(next) }}>회차 제외</button>
              </div>
            })}
            {confirmed.map(doc => {
              const selection = selections[doc.document_id]
              const update = (value: Partial<NonNullable<typeof selection>>) => { updateSelection({ ...selections, [doc.document_id]: { ...selection, ...value } }) }
              return <div key={doc.document_id} className="my-2 flex flex-wrap items-center gap-3 rounded border p-3">
                <label><input type="checkbox" checked={!!selection} onChange={e => { const next = { ...selections }; if (e.target.checked) next[doc.document_id] = { number: '', date: dashboard?.sessions.find(s => s.session_number === doc.session_number)?.session_date || '', attested: false }; else delete next[doc.document_id]; updateSelection(next) }} /> 상담 {doc.session_number}회기</label>
                {selection && <><label>바우처 회차<input aria-label={`상담 ${doc.session_number}회기 바우처 회차`} className="rm-input w-20" type="number" min="1" max="8" value={selection.number} onChange={e => update({ number: e.target.value })} /></label><label>제공일<input className="rm-input" type="date" value={selection.date} onChange={e => update({ date: e.target.value })} /></label><label><input type="checkbox" checked={selection.attested} onChange={e => update({ attested: e.target.checked })} /> 실제 제공한 서비스입니다</label></>}
              </div>
            })}
            <label className="mt-4 block">서비스 유형<select className="rm-input" value={form.service_tier} onChange={e => change({ ...form, service_tier: e.target.value as VoucherForm['service_tier'] })}><option value="">기관에서 확인</option><option value="type_1">1급 유형</option><option value="type_2">2급 유형</option></select></label>
            {form.rows.map((row, i) => <div key={Object.entries(selections).filter(([, s]) => complete(s))[i]?.[0] || i} className="mt-4"><h3 className="font-semibold">바우처 {row.voucher_session_no}회차 · {row.actual_service_date}</h3><div className={center ? 'mt-2' : 'mt-2 grid gap-3 sm:grid-cols-2'}>
              {(['content_left', 'content_right'] as const).filter(key => !center || key === 'content_left').map(key => {
                const left = key === 'content_left'
                return narrative('row' + row.voucher_session_no + (left ? '_left' : '_right'), left ? '서비스 내용' : '개입·반응 / 검사결과 등 추가 기록', row[key],
                  text => change({ ...form, rows: form.rows.map((r, index) => index === i ? { ...r, [key]: text } : r) }),
                  '바우처 ' + row.voucher_session_no + '회차 ' + (left ? '서비스 내용' : '추가 기록'))
              })}
            </div></div>)}
            <div className="mt-4">{narrative('general_comment', '비고·종합의견 / 확인된 전후 검사결과', form.general_comment, text => change({ ...form, general_comment: text }), '비고·종합의견')}</div>
            <p className="text-xs text-slate-500">검사값을 추정해 넣지 마세요. 아직 종결 전이라면 사후 검사결과는 비워둘 수 있습니다.</p>
          </section>}
          {form.template !== 'form10' && <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <p className="text-sm text-slate-600 sm:col-span-2">{form.template === 'form26' ? '일정과 금액은 확인된 내용을 작성해주세요.' : center ? '센터 계약서의 계약기간과 기타 합의사항을 작성합니다. 원본의 제1~8조와 서명란이 함께 출력됩니다.' : '이용자와 합의한 조건을 입력해주세요. 사업안내 제25호의 제1~9조가 함께 출력됩니다.'}</p>
            {visibleFields.map(([key, title]) => narrative(key, title, form[key as keyof typeof fieldLabels], text => change({ ...form, [key]: text })))}
            {form.template === 'form25' && !center && <p className="text-xs text-slate-500 sm:col-span-2">출처: 보건복지부 2026년 정신건강 심리상담 바우처사업 안내 제25호 · <a className="underline" href="https://welfare.dobong.go.kr/dobongBokji/bbs/BMSR00004/view.do?boardId=1771&menuNo=200113" target="_blank" rel="noreferrer">도봉복지로 공개본</a> · 공공누리 제1유형(출처표시). 작성란·배치는 리마인드에서 재구성했습니다.</p>}
          </div>}
          {dateProblem && <p role="alert" className="mt-2 text-sm text-red-700">{dateProblem}</p>}
          <button type="button" className="mt-5 rounded bg-blue-600 px-5 py-3 font-bold text-white disabled:opacity-40" disabled={!caseId || Boolean(dateProblem) || Boolean(center && overflowing) || (form.template === 'form10' && (!form.rows.length || form.rows.length !== Object.keys(selections).length || new Set(form.rows.map(r => r.voucher_session_no)).size !== form.rows.length || form.rows.some(row => !row.content_left.trim())))} onClick={() => task(async () => {
            const doc = candidate || await prepare(); await openPreview(doc)
          })}>{busy ? '처리 중…' : '출력 내용 확인'}</button>
        </fieldset>
        {candidate && <section className="mt-5 rounded-xl border bg-white p-5"><h2 className="font-bold">출력 미리보기</h2><p className="my-2 text-sm">{candidate.privacy_status === 'degraded' ? '자동 식별정보 확인이 제한되었습니다. 남은 이름·기관·연락처를 확인해 주세요.' : '출력 내용을 확인해주세요. 자동 처리가 모든 식별정보를 제거한다고 보장하지 않습니다.'}</p>{preview && <VoucherPdfPreview blob={preview} onReady={setPreviewReady} />}
          {candidate.reviewed_at ? <p className="my-3 font-bold text-green-700">검토 완료 · 기관 보완 필요</p> : <div className="my-4 space-y-3"><label className="block"><input type="checkbox" checked={privacy} onChange={e => setPrivacy(e.target.checked)} /> 미리보기의 식별정보를 확인하고 직접 인용·사생활 세부내용을 기관 제출에 필요한 수준으로 줄였습니다.</label><label className="block"><input type="checkbox" checked={offline} onChange={e => setOffline(e.target.checked)} /> 기본정보·서명·미기입 항목은 기관에서 보완하겠습니다.</label><button type="button" disabled={busy || !privacy || !offline || !previewReady} className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-40" onClick={() => task(async () => setCandidate(await voucherApi<VoucherDocument>(`saved/${candidate.id}/review`, 'POST', { fingerprint: candidate.fingerprint, human_privacy_reviewed: true, acknowledged_offline_completion: true }))) }>내용 검토 완료</button></div>}
          <div className="flex gap-3">{(['pdf', 'hwpx'] as const).map(format => <button type="button" key={format} className="rounded border px-4 py-2 disabled:opacity-40" disabled={busy || !candidate.reviewed_at || !caps.formats[format]} onClick={() => download(format)}>{format.toUpperCase()} 다운로드</button>)}</div>{!caps.formats.hwpx && <p className="mt-2 text-sm text-slate-500">HWPX는 문서 편집기 호환성 확인 후 제공됩니다.</p>}</section>}
        <section className="mt-5 rounded-xl border bg-white p-5"><h2 className="font-bold">저장한 바우처 문서</h2>{history.map(doc => <div key={doc.id} className="mt-2 flex justify-between border-b py-2"><button disabled={busy} type="button" onClick={() => task(async () => openPreview(await voucherApi<VoucherDocument>(`saved/${doc.id}`)))}>{label[doc.template]} · {doc.reviewed_at ? '검토 완료' : '검토 전'} · {new Date(doc.created_at).toLocaleDateString('ko-KR')}</button><button disabled={busy} type="button" onClick={() => { if (window.confirm('이 서식 문서를 삭제할까요? 원래 회기 기록은 유지됩니다.')) void task(async () => { await voucherApi(`saved/${doc.id}`, 'DELETE'); setHistory(history.filter(d => d.id !== doc.id)); if (candidate?.id === doc.id) clearReview() }) }}>삭제</button></div>)}</section>
      </>}
      </div>
    </div>
  </div>
}
