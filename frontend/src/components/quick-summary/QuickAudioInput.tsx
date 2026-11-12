import { useEffect, useRef, useState } from 'react'
import { Mic, Loader2, X } from 'lucide-react'
import { transcribeAudio } from '../../api/client'
import { AUDIO_CONSENT_MESSAGE, AUDIO_FILE_ACCEPT, AUDIO_UPLOAD_MAX_BYTES, AUDIO_UPLOAD_LIMIT_LABEL } from '../../lib/audioConsent'
import { buildTranscriptText } from '../../lib/audioTranscriptWorkflow'
import { clearHostedAudioCheckpoint } from '../../lib/hostedAudio'
import { AudioTranscriptEditor, type AudioTranscriptEditorMaterial } from '../audio/AudioTranscriptEditor'

/** Keeps raw audio/ASR in memory; only explicitly reviewed text reaches quick summary. */
export default function QuickAudioInput({ onApply, onPendingChange, disabled = false }: {
  onApply: (text: string) => void
  onPendingChange: (pending: boolean) => void
  disabled?: boolean
}) {
  const [material, setMaterial] = useState<AudioTranscriptEditorMaterial | null>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const [applied, setApplied] = useState(false)
  const [editing, setEditing] = useState(true)
  const fileInput = useRef<HTMLInputElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const fileRef = useRef<File | null>(null)
  const objectUrl = useRef<string | null>(null)
  const run = useRef(0)

  useEffect(() => {
    if (pendingFile && dialog.current && !dialog.current.open) dialog.current.showModal()
    else if (!pendingFile && dialog.current?.open) dialog.current.close()
  }, [pendingFile])

  useEffect(() => () => {
    run.current += 1
    if (fileRef.current) clearHostedAudioCheckpoint(fileRef.current)
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    fileRef.current = null
  }, [])

  const invalidate = () => {
    setApplied(false)
    onApply('')
    onPendingChange(true)
  }

  const update = (change: (current: AudioTranscriptEditorMaterial) => AudioTranscriptEditorMaterial) => {
    invalidate()
    setMaterial(current => current ? { ...change(current), dirtySinceApply: true } : current)
  }

  const transcribe = async (file: File, expectedSpeakers = 2) => {
    const resuming = fileRef.current === file && material?.expectedSpeakers === expectedSpeakers
    if (fileRef.current && !resuming) clearHostedAudioCheckpoint(fileRef.current)
    const currentRun = ++run.current
    invalidate()
    setError('')
    setEditing(true)
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = URL.createObjectURL(file)
    fileRef.current = file
    setMaterial(current => ({ ...(resuming ? current : null), id: `quick-audio-${currentRun}`, filename: file.name, status: 'transcribing',
      objectUrl: objectUrl.current || undefined, expectedSpeakers, warnings: [], error: undefined }))
    try {
      const response = await transcribeAudio(file, 'ko', 'transcribe', expectedSpeakers,
        message => { if (run.current === currentRun) setMaterial(current => current ? { ...current, transcriptionProgress: message } : current) },
        () => run.current === currentRun)
      if (run.current !== currentRun) return
      setMaterial(current => current ? { ...current, status: 'transcribed', segments: response.segments,
        rawSegments: structuredClone(response.raw_segments?.length ? response.raw_segments : response.segments),
        reviewRanges: response.review_ranges, failedRanges: response.failed_ranges, warnings: response.warnings,
        runtimeMode: response.runtime_mode, diarizationStatus: response.diarization_status,
        languageProbability: response.language_probability, dirtySinceApply: true, speakerRoleMap: {} } : current)
    } catch (cause) {
      if (run.current !== currentRun) return
      const message = cause instanceof Error ? cause.message : '축어록을 만들지 못했어요.'
      setError(message)
      setMaterial(current => current ? { ...current, status: 'failed', error: message } : current)
    }
  }

  const remove = () => {
    run.current += 1
    if (fileRef.current) clearHostedAudioCheckpoint(fileRef.current)
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current)
    objectUrl.current = null
    fileRef.current = null
    setMaterial(null)
    setApplied(false)
    setError('')
    onApply('')
    onPendingChange(false)
  }

  const selectFile = (file?: File) => {
    if (!file) return
    setError('')
    if (!/\.(mp3|m4a|wav)$/i.test(file.name)) return setError('MP3, M4A, WAV 음성을 선택해주세요.')
    if (file.size > AUDIO_UPLOAD_MAX_BYTES) return setError(`음성 파일은 ${AUDIO_UPLOAD_LIMIT_LABEL}까지 올릴 수 있어요.`)
    if (!file.size) return setError('빈 음성 파일은 올릴 수 없어요.')
    setPendingFile(file)
  }

  return (
    <section aria-label="간편요약 음성 자료" className="mt-4 w-full rounded-2xl border border-primary-100 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" disabled={disabled || material?.status === 'transcribing'} onClick={() => fileInput.current?.click()}
          className="inline-flex h-10 items-center gap-2 rounded-full border border-primary-400 px-4 text-sm font-bold text-primary-400 disabled:opacity-50">
          <Mic className="h-4 w-4" />{material ? '음성 바꾸기' : '음성 추가'}
        </button>
        <span className="text-xs text-grey-500">MP3 · M4A · WAV · 2시간 상담 지원 · 최대 {AUDIO_UPLOAD_LIMIT_LABEL}</span>
      </div>
      <input ref={fileInput} type="file" accept={AUDIO_FILE_ACCEPT} disabled={disabled || material?.status === 'transcribing'} aria-label="간편요약 음성 파일 선택" className="sr-only"
        onChange={event => { selectFile(event.target.files?.[0]); event.target.value = '' }} />
      {!material && <p className="mt-2 text-xs leading-5 text-grey-500">음성을 올린 뒤 화자와 축어록을 수정하고, 개인정보를 확인해 요약에 반영하세요.</p>}
      {material && (
        <div className="mt-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-semibold">{material.filename}</p>
            <button type="button" disabled={disabled} onClick={remove} aria-label="간편요약 음성 제거" className="p-2 text-grey-500"><X className="h-4 w-4" /></button>
          </div>
          {material.status === 'transcribing' ? (
            <p role="status" className="mt-3 flex items-center gap-2 text-sm text-primary-400"><Loader2 className="h-4 w-4 animate-spin" />{material.transcriptionProgress || '음성을 준비하는 중…'}</p>
          ) : editing ? (
            <fieldset disabled={disabled} className="mt-3 max-h-[65vh] overflow-y-auto rounded-lg border border-grey-200 p-3">
              <AudioTranscriptEditor material={material} applyMode="replace" onApplyModeChange={() => undefined}
                showApplyMode={false} applyLabel="검토한 축어록을 간편요약에 반영"
                transcriptionAvailable={!disabled} transcriptionReason={null}
                onExpectedSpeakersChange={value => update(current => ({ ...current, expectedSpeakers: value }))}
                onTranscribe={() => { if (fileRef.current) void transcribe(fileRef.current, material.expectedSpeakers) }}
                onUpdateSegmentText={(id, text) => update(current => ({ ...current,
                  segments: current.segments?.map(segment => segment.id === id ? { ...segment, text, words: [], confidence: null } : segment) }))}
                onUpdateSegments={segments => update(current => ({ ...current, segments }))}
                onUpdateSpeakerRole={(speaker, role) => update(current => ({ ...current, speakerRoleMap: { ...current.speakerRoleMap, [speaker]: role } }))}
                onApply={(reviewed, source) => {
                  if (material.failedRanges?.length || !reviewed.trim() || source !== buildTranscriptText(material.segments || [], material.speakerRoleMap || {})) return
                  onApply(reviewed)
                  onPendingChange(false)
                  setApplied(true)
                  setEditing(false)
                  setMaterial(current => current ? { ...current, dirtySinceApply: false } : current)
                }} />
            </fieldset>
          ) : (
            <div className="mt-2 flex items-center justify-between gap-3">
              <p role="status" className="text-sm text-success-500">{applied ? '검토한 축어록이 요약 입력에 반영됐어요.' : '축어록을 검토해주세요.'}</p>
              <button type="button" disabled={disabled} onClick={() => { invalidate(); setEditing(true) }} className="text-sm font-bold text-primary-400">축어록 다시 확인</button>
            </div>
          )}
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-sm text-danger-500">{error}</p>}
      <dialog ref={dialog} aria-labelledby="quick-audio-consent-title" onCancel={event => { event.preventDefault(); setPendingFile(null) }}
        className="m-auto w-[min(92vw,480px)] rounded-xl border border-grey-200 bg-white p-6 shadow-xl backdrop:bg-black/40">
        <h2 id="quick-audio-consent-title" className="font-bold">음성 업로드 동의 확인</h2>
        <p className="mt-3 whitespace-pre-line text-sm leading-6 text-grey-700">{AUDIO_CONSENT_MESSAGE}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" autoFocus onClick={() => setPendingFile(null)} className="rounded-lg border px-4 py-2 text-sm">취소</button>
          <button type="button" onClick={() => { const file = pendingFile; setPendingFile(null); if (file) void transcribe(file) }}
            className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white">동의를 확인하고 업로드</button>
        </div>
      </dialog>
    </section>
  )
}
