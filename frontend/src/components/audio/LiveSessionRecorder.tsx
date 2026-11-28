import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, CheckCircle2, Download, Loader2, Mic, Pause, Play, RefreshCcw, Square } from 'lucide-react'
import { getAudioCapabilities, transcribeLiveAudioChunk } from '../../api/client'
import { useAuthSession } from '../../lib/authSession'
import { AUDIO_CONSENT_MESSAGE } from '../../lib/audioConsent'
import { LiveAudioRecorder, initialLiveAudioSnapshot, type LiveRecordingResult } from '../../lib/liveAudio'
import { buildLiveSessionDraft } from '../../lib/liveSessionDraft'
import { useUnsavedWork } from '../../lib/unsavedWork'
import { appendLiveAudio, createLiveAudio, deleteLiveAudio, listLiveAudio, loadLiveAudio,
  rememberLiveAudioFile, subscribeLiveAudioStore, type StoredLiveAudio } from '../../lib/liveAudioStore'

const time = (value: number) => `${Math.floor(value / 60).toString().padStart(2, '0')}:${Math.floor(value % 60).toString().padStart(2, '0')}`
const buttonBase = 'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50'
const button = `${buttonBase} border-grey-200 bg-white text-grey-800`
const accentButton = `${buttonBase} border-primary-400 bg-white text-primary-500`
const solidButton = `${buttonBase} border-primary-400 bg-primary-400 text-white`

export default function LiveSessionRecorder({ caseId, sessionNumber, onComplete, onActiveChange, disabled = false }: {
  caseId: string
  sessionNumber: number
  onComplete: (result: LiveRecordingResult) => void
  onActiveChange: (active: boolean) => void
  disabled?: boolean
}) {
  const { userId } = useAuthSession()
  const [snapshot, setSnapshot] = useState(initialLiveAudioSnapshot)
  const [consentOpen, setConsentOpen] = useState(false)
  const [consented, setConsented] = useState(false)
  const [notice, setNotice] = useState('')
  const [storageNotice, setStorageNotice] = useState('')
  const [recoverable, setRecoverable] = useState<StoredLiveAudio[]>([])
  const [recovering, setRecovering] = useState(false)
  const [recovered, setRecovered] = useState(false)
  const stored = useRef<StoredLiveAudio | null>(null)
  const recorder = useRef<LiveAudioRecorder | null>(null)
  const startupAbort = useRef<AbortController | null>(null)
  const epoch = useRef(0)
  const completing = useRef(false)
  const dialog = useRef<HTMLDialogElement | null>(null)
  const transcript = useRef<HTMLDivElement | null>(null)
  const follow = useRef(true)
  const onCompleteRef = useRef(onComplete)
  const onActiveRef = useRef(onActiveChange)
  onCompleteRef.current = onComplete
  onActiveRef.current = onActiveChange
  const active = ['starting', 'recording', 'paused', 'finishing'].includes(snapshot.state)
  useUnsavedWork(active || consentOpen)
  const draft = useMemo(() => buildLiveSessionDraft(snapshot.segments), [snapshot.segments])
  const transcriptEntries = useMemo(() => snapshot.segments.map(segment => (
    <div id={`live-transcript-${segment.segment_id}`} tabIndex={-1} key={segment.segment_id} className="rounded-lg bg-white p-2.5 outline-none focus:ring-2 focus:ring-primary-400">
      <p className="text-xs text-grey-500">{time(segment.start)} · 화자 확인 전</p>
      <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-6 text-grey-800">{segment.text}</p>
    </div>
  )), [snapshot.segments])

  useEffect(() => {
    if (consentOpen && dialog.current && !dialog.current.open) dialog.current.showModal()
    else if (!consentOpen && dialog.current?.open) dialog.current.close()
  }, [consentOpen])

  useEffect(() => {
    if (follow.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight
  }, [snapshot.segments.length])

  useEffect(() => () => {
    epoch.current++
    startupAbort.current?.abort()
    recorder.current?.dispose()
    recorder.current = null
    onActiveRef.current(false)
  }, [userId, caseId, sessionNumber])

  useEffect(() => {
    let alive = true
    let request = 0
    const refresh = async () => {
      if (!userId) return
      const current = ++request
      try {
        const records = await listLiveAudio({ userId, caseId, sessionNumber })
        if (alive && current === request) setRecoverable(records.filter(record => record.key[3] !== stored.current?.key[3]))
      } catch {
        if (alive) setStorageNotice('브라우저 녹음 저장소를 사용할 수 없습니다. 녹음은 계속할 수 있지만 화면을 닫기 전에 원음을 내려받아주세요.')
      }
    }
    void refresh()
    const unsubscribe = subscribeLiveAudioStore(() => { void refresh() })
    return () => { alive = false; unsubscribe() }
  }, [userId, caseId, sessionNumber])

  const storageError = () => setStorageNotice('브라우저 저장 공간이 부족하거나 저장소를 사용할 수 없어 이후 원음을 보관하지 못합니다. 녹음은 계속됩니다. 화면을 닫기 전에 원음을 내려받아주세요.')

  const finish = async () => {
    const current = recorder.current
    if (!current || completing.current || snapshot.state === 'finishing' || snapshot.state === 'finished') return
    completing.current = true
    const run = epoch.current
    try {
      const result = await current.finish()
      if (run !== epoch.current) return
      if (stored.current) rememberLiveAudioFile(result.file, stored.current.key)
      onActiveRef.current(false)
      onCompleteRef.current(result)
      setNotice(result.transcription.failed_ranges?.length
        ? '녹음과 처리된 축어록을 검토 화면에 보관했습니다. 미처리 구간을 다시 처리해주세요.'
        : '녹음과 축어록을 검토 화면에 보관했습니다. 화자와 개인정보를 확인한 뒤 회기에 반영해주세요.')
    } catch (error) {
      if (run !== epoch.current) return
      setNotice(error instanceof Error ? error.message : '녹음을 마무리하지 못했습니다. 원음을 내려받아주세요.')
      onActiveRef.current(false)
    } finally {
      if (run === epoch.current) completing.current = false
    }
  }
  const finishRef = useRef(finish)
  finishRef.current = finish

  const start = async () => {
    if (!consented || !userId || disabled || active || recovering) return
    const run = ++epoch.current
    completing.current = false
    const owner = userId
    startupAbort.current?.abort()
    startupAbort.current = new AbortController()
    recorder.current?.dispose()
    recorder.current = null
    setConsentOpen(false)
    setNotice('')
    setStorageNotice('')
    setRecovered(false)
    stored.current = null
    setSnapshot({ ...initialLiveAudioSnapshot(), state: 'starting' })
    onActiveRef.current(true)
    try {
      const capabilities = await getAudioCapabilities({ ownerId: owner, signal: startupAbort.current.signal })
      if (run !== epoch.current) return
      if (!capabilities.transcription.available || capabilities.runtime_mode !== 'real' || capabilities.provider !== 'clova') {
        throw new Error('현재 연결에서는 CLOVA 실시간 녹음을 사용할 수 없습니다. 음성 인식 연결 설정을 확인해주세요.')
      }
      let saved: StoredLiveAudio | null = null
      const current = new LiveAudioRecorder({
        send: (file, signal) => transcribeLiveAudioChunk(file, owner, signal),
        onUpdate: next => { if (run === epoch.current) setSnapshot(next) },
        onLimit: () => { if (run === epoch.current) void finishRef.current() },
        persistChunk: (index, pcm) => saved ? appendLiveAudio(saved.key, index, pcm) : Promise.resolve(),
        onStorageError: () => { if (run === epoch.current) storageError() },
      })
      try { saved = await createLiveAudio({ userId: owner, caseId, sessionNumber }, current.recordingFilename) }
      catch { if (run === epoch.current) storageError() }
      if (run !== epoch.current) { current.dispose(); return }
      stored.current = saved
      recorder.current = current
      await current.start()
    } catch (error) {
      if (run !== epoch.current) return
      recorder.current?.dispose()
      recorder.current = null
      setSnapshot(initialLiveAudioSnapshot())
      setNotice(error instanceof Error ? error.message : '녹음을 시작하지 못했습니다.')
      onActiveRef.current(false)
    }
  }

  const recover = async (record: StoredLiveAudio) => {
    if (!userId || active || disabled || recovering) return
    const run = ++epoch.current
    setRecovering(true)
    try {
      const saved = await loadLiveAudio(record.key)
      if (run !== epoch.current) return
      recorder.current?.dispose()
      const current = new LiveAudioRecorder({
        send: (file, signal) => transcribeLiveAudioChunk(file, userId, signal),
        onUpdate: next => { if (run === epoch.current) setSnapshot(next) },
        onLimit: () => {},
      })
      current.restore(saved.record.filename, saved.chunks)
      recorder.current = current
      stored.current = saved.record
      completing.current = false
      setRecovered(true)
      setNotice('')
      setRecoverable(previous => previous.filter(item => item.key[3] !== record.key[3]))
      onActiveRef.current(true)
    } catch (error) {
      if (run === epoch.current) setNotice(error instanceof Error ? error.message : '녹음을 복구하지 못했습니다.')
    } finally { if (run === epoch.current) setRecovering(false) }
  }

  const discard = async (record: StoredLiveAudio | null) => {
    const run = epoch.current
    try {
      if (record) await deleteLiveAudio(record.key)
      if (run !== epoch.current) return
      setRecoverable(previous => previous.filter(item => item.key[3] !== record?.key[3]))
      if (!record || record.key[3] === stored.current?.key[3]) {
        epoch.current++
        recorder.current?.dispose()
        recorder.current = null
        stored.current = null
        completing.current = false
        setSnapshot(initialLiveAudioSnapshot())
        setNotice('녹음을 삭제했습니다.')
        onActiveRef.current(false)
      }
    } catch { setNotice('녹음을 삭제하지 못했습니다. 다시 시도해주세요.') }
  }

  const download = () => {
    const file = recorder.current?.recordingFile()
    if (!file || file.size <= 44) return
    const url = URL.createObjectURL(file)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = file.name
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const selectEvidence = (segmentId: string) => {
    follow.current = false
    const target = document.getElementById(`live-transcript-${segmentId}`)
    target?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    target?.focus({ preventScroll: true })
  }

  return <section aria-label="실시간 상담 기록" className="mb-5 overflow-hidden rounded-xl border border-primary-100 bg-white">
    <dialog ref={dialog} aria-labelledby="live-consent-title" aria-describedby="live-consent-description"
      onCancel={() => setConsentOpen(false)} className="m-auto w-[min(92vw,520px)] rounded-xl border border-grey-200 bg-white p-6 shadow-xl backdrop:bg-black/40">
      <h2 id="live-consent-title" className="text-lg font-bold text-grey-900">상담 녹음 동의 확인</h2>
      <p id="live-consent-description" className="mt-3 whitespace-pre-line text-sm leading-6 text-grey-700">{AUDIO_CONSENT_MESSAGE}</p>
      <p className="mt-3 text-sm leading-6 text-grey-700">시작하면 마이크 음성을 약 10초 단위로 전송합니다. 최대 60분까지 녹음하며, 원음은 검토를 위해 이 브라우저에 보관됩니다.</p>
      <label className="mt-4 flex items-start gap-3 text-sm leading-6 text-grey-800"><input type="checkbox" className="mt-1 h-4 w-4" checked={consented} onChange={event => setConsented(event.target.checked)} />녹음과 원본 음성의 외부 전송·처리에 필요한 동의를 확인했습니다.</label>
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className={button} onClick={() => setConsentOpen(false)}>취소</button>
        <button type="button" className={solidButton} disabled={!consented} onClick={() => void start()}>동의 확인 후 녹음 시작</button>
      </div>
    </dialog>

    <div className="flex flex-wrap items-center justify-between gap-3 bg-primary-50/60 p-4">
      <div><h2 className="flex items-center gap-2 text-base font-bold text-grey-900"><Mic className="h-5 w-5 text-primary-400" />실시간 상담 기록 <span className="rounded bg-white px-2 py-0.5 text-xs font-medium text-grey-600">베타</span></h2>
        <p className="mt-1 text-sm leading-6 text-grey-600">상담하면서 축어록과 발화별 임시 메모를 확인하세요.</p></div>
      {!active && <button type="button" className={accentButton} disabled={disabled || !userId || recovering}
        onClick={() => { setConsented(false); setConsentOpen(true) }}><Mic className="h-4 w-4" />{snapshot.state === 'finished' ? '새 녹음 시작' : '상담 녹음 시작'}</button>}
      {active && <div className="flex items-center gap-2 text-sm font-semibold text-grey-800" role="status">
        {snapshot.state === 'recording' ? <span className="h-2.5 w-2.5 rounded-full bg-red-500" /> : snapshot.state === 'starting' || snapshot.state === 'finishing' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pause className="h-4 w-4" />}
        {snapshot.state === 'starting' ? '마이크 연결 중' : snapshot.state === 'finishing' ? '마지막 구간 처리 중' : snapshot.state === 'paused' ? '일시정지' : '녹음 중'}
        <span className="font-mono tabular-nums">{time(snapshot.duration)}</span>
      </div>}
    </div>

    {!active && recoverable.map(record => <div key={record.key[3]} role="status" className="space-y-2 border-t border-grey-200 p-4">
      <p className="text-sm text-grey-800">중단된 녹음 {Math.max(1, Math.ceil(record.frames / 16000 / 60))}분이 있습니다. 이어서 검토할까요?</p>
      <button type="button" className={accentButton} disabled={disabled || recovering} onClick={() => void recover(record)}>이어서 검토</button>{' '}
      <button type="button" className={button} disabled={recovering} onClick={() => void discard(record)}>삭제</button>
    </div>)}

    {(active || snapshot.state === 'finished') && <div className="space-y-4 p-4">
      {snapshot.state !== 'starting' && <div className="flex flex-wrap items-center gap-2">
        {snapshot.state === 'recording' && <button type="button" className={button} onClick={() => recorder.current?.pause()}><Pause className="h-4 w-4" />일시정지</button>}
        {snapshot.state === 'paused' && !recovered && <button type="button" className={button} disabled={snapshot.failed > 0 || snapshot.queued >= 3} onClick={() => void recorder.current?.resume()}><Play className="h-4 w-4" />녹음 계속</button>}
        {snapshot.failed > 0 && snapshot.state === 'paused' && <button type="button" className={button} onClick={() => void recorder.current?.retry()}><RefreshCcw className="h-4 w-4" />실패 구간 다시 처리</button>}
        {active && <button type="button" className={accentButton} disabled={snapshot.state === 'finishing'} onClick={() => void finish()}><Square className="h-4 w-4" />녹음 종료·검토</button>}
        <button type="button" className={button} disabled={!snapshot.duration} onClick={download}><Download className="h-4 w-4" />원음 다운로드</button>
        <button type="button" className={button} disabled={snapshot.state === 'finishing'} onClick={() => void discard(stored.current)}>삭제</button>
        {snapshot.queued > 0 && <span className="text-sm text-grey-600">{snapshot.queued}개 구간 처리 대기</span>}
      </div>}
      <div aria-label="마이크 입력 크기" className="h-1.5 overflow-hidden rounded-full bg-grey-100"><div className="h-full rounded-full bg-primary-400 transition-[width]" style={{ width: `${snapshot.level * 100}%` }} /></div>
      {snapshot.message && <p role="status" className="flex items-start gap-2 rounded-lg bg-amber-50 p-3 text-sm leading-6 text-amber-900"><AlertTriangle className="mt-1 h-4 w-4 shrink-0" />{snapshot.message}</p>}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="min-w-0"><div className="mb-2 flex items-center justify-between gap-2"><h3 className="text-sm font-bold text-grey-900">실시간 축어록</h3><button type="button" className="text-xs text-primary-500 underline" onClick={() => { follow.current = true; if (transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight }}>최신 발화 보기</button></div>
          <div ref={transcript} className="h-72 space-y-2 overflow-y-auto rounded-lg border border-grey-200 bg-grey-100/40 p-3" onScroll={event => { const node = event.currentTarget; follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 40 }}>
            {!snapshot.segments.length && <p className="text-sm leading-6 text-grey-500">녹음된 음성이 약 10초씩 모이면 전사를 요청합니다. 처리된 발화가 여기에 표시됩니다.</p>}
            {transcriptEntries}
          </div>
        </div>
        <div className="min-w-0"><h3 className="mb-2 text-sm font-bold text-grey-900">구조화 메모 <span className="font-normal text-grey-500">· 임시 분류</span></h3>
          <div className="h-72 space-y-3 overflow-y-auto rounded-lg border border-grey-200 p-3">
            {!draft.some(section => section.items.length) && <p className="text-sm leading-6 text-grey-500">발화 원문을 주제별로 모읍니다. 상담자·내담자 구분과 의미는 상담 후 확인해주세요.</p>}
            {draft.filter(section => section.items.length).map(section => <section key={section.id}><h4 className="text-sm font-semibold text-grey-800">{section.title}</h4><ul className="mt-1 space-y-1">{section.items.map(item => <li key={item.segmentId}><button type="button" onClick={() => selectEvidence(item.segmentId)} className="w-full rounded-md px-2 py-1 text-left text-sm leading-6 text-grey-700 hover:bg-primary-50"><span className="mr-1 text-xs text-primary-500">{time(item.start)}</span>{item.quote}</button></li>)}</ul>{!!section.omittedCount && <p className="mt-1 text-xs text-grey-500">이전 {section.omittedCount}개 발화는 축어록에서 확인할 수 있습니다.</p>}</section>)}
          </div>
        </div>
      </div>
      <p className="text-xs leading-5 text-grey-500">10초 단위 전사 · 서버 응답에 따라 표시가 늦어질 수 있습니다 · 최대 60분<br />임시 메모는 원문 발화를 자동 분류합니다. 최종 AI 요약은 종료 후 화자·개인정보 검토를 거쳐 생성합니다. 녹음 중에는 이 화면을 열어두세요.</p>
    </div>}
    {notice && <p role="status" className="flex items-start gap-2 border-t border-grey-200 px-4 py-3 text-sm leading-6 text-grey-700">{snapshot.state === 'finished' && <CheckCircle2 className="mt-1 h-4 w-4 shrink-0 text-emerald-600" />}{notice}</p>}
    {storageNotice && <p role="alert" className="border-t border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-900">{storageNotice}</p>}
  </section>
}
