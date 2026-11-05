import { useEffect, useRef, useState, type DragEvent, type MouseEvent } from 'react'
import { AlertTriangle, CheckCircle2, FileText, Loader2, PenLine, Plus, Upload, X } from 'lucide-react'

import { PrimaryButton } from '../app-shell/ui'
import type { AudioCapabilitiesResponse, SessionInput } from '../../types/session'
import type { UploadedMaterial } from '../../types/materials'
import { AUDIO_CONSENT_MESSAGE } from '../../lib/audioConsent'

export interface SessionTime {
  start: string
  end: string
}

const ACCEPT = '.pdf,.docx,.txt,.mp3,.m4a,.wav,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,audio/mpeg,audio/mp4,audio/wav,audio/x-wav'
const AUDIO_EXTENSION = /\.(mp3|m4a|wav)$/i

const fieldClass = 'h-11 w-full cursor-pointer rounded-[10px] border border-grey-200 bg-grey-100 px-3 text-sm text-grey-800 outline-none focus:border-primary-400 focus:bg-white'

/**
 * Open the native date/time picker when any part of the box is clicked, not only the small icon.
 * Typing still works; browsers without showPicker keep their default behavior.
 */
function openNativePicker(event: MouseEvent<HTMLInputElement>) {
  const input = event.currentTarget
  if (input.disabled || typeof input.showPicker !== 'function') return
  try {
    input.showPicker()
  } catch {
    // showPicker can throw without a user gesture or in cross-origin frames; fall back to the default.
  }
}

function toFileList(files: File[]): FileList {
  const transfer = new DataTransfer()
  files.forEach((file) => transfer.items.add(file))
  return transfer.files
}

/**
 * Upload and review materials first, then optionally add session metadata before summarizing.
 * Session time is display-only (no backend field). Uploaded files are extracted/transcribed and applied
 * to the review editor before explicit application. In-browser recording is not implemented yet.
 */
export default function SessionInputPage({
  mode,
  form,
  sessionTime,
  materials,
  audioCapabilities,
  error,
  isLoading,
  uploadLimitLabel,
  onChangeSessionTime,
  onUpdateField,
  onUploadFiles,
  onOpenMaterial,
  onRemoveMaterial,
  onSubmit,
}: {
  /** 'existing' re-summarizes a stored session and overwrites its record. */
  mode: 'new' | 'existing'
  form: SessionInput
  sessionTime: SessionTime
  materials: UploadedMaterial[]
  audioCapabilities: AudioCapabilitiesResponse | null
  error: string | null
  isLoading: boolean
  uploadLimitLabel: string
  onChangeSessionTime: (next: SessionTime) => void
  onUpdateField: (field: keyof SessionInput, value: string | number) => void
  onUploadFiles: (files: FileList | null, audioConsent: boolean) => void
  onOpenMaterial: (materialId: string, mode: 'document_preview' | 'audio_review' | 'material_apply') => void
  onRemoveMaterial: (materialId: string) => void
  onSubmit: () => void
}) {
  const [isDraggingFiles, setIsDraggingFiles] = useState(false)
  const [pendingAudioFiles, setPendingAudioFiles] = useState<File[] | null>(null)
  const consentDialog = useRef<HTMLDialogElement | null>(null)
  // dragenter/dragleave fire for every child element, so count them instead of toggling.
  const dragDepth = useRef(0)

  useEffect(() => {
    const dialog = consentDialog.current
    if (pendingAudioFiles && dialog && !dialog.open) dialog.showModal()
    else if (!pendingAudioFiles && dialog?.open) dialog.close()
  }, [pendingAudioFiles])

  useEffect(() => {
    // A file dropped outside the upload area would make the browser navigate to it and lose the form.
    const blockFileNavigation = (event: globalThis.DragEvent) => {
      if (event.dataTransfer?.types.includes('Files')) event.preventDefault()
    }
    window.addEventListener('dragover', blockFileNavigation)
    window.addEventListener('drop', blockFileNavigation)
    return () => {
      window.removeEventListener('dragover', blockFileNavigation)
      window.removeEventListener('drop', blockFileNavigation)
    }
  }, [])

  /** Audio needs explicit consent; when declined, the remaining (non-audio) files are still uploaded. */
  const upload = (files: FileList | null) => {
    if (!files?.length) return
    const list = Array.from(files)
    const hasAudio = list.some((file) => AUDIO_EXTENSION.test(file.name))
    if (!hasAudio) return onUploadFiles(files, false)
    setPendingAudioFiles(list)
  }

  const resolveAudioConsent = (approved: boolean) => {
    const files = pendingAudioFiles
    setPendingAudioFiles(null)
    if (!files) return
    const selected = approved ? files : files.filter((file) => !AUDIO_EXTENSION.test(file.name))
    if (selected.length) onUploadFiles(toFileList(selected), approved)
  }

  const hasDraggedFiles = (event: DragEvent) => event.dataTransfer.types.includes('Files')
  const dropZoneHandlers = {
    onDragEnter: (event: DragEvent) => {
      if (!hasDraggedFiles(event) || isLoading) return
      event.preventDefault()
      dragDepth.current += 1
      setIsDraggingFiles(true)
    },
    onDragOver: (event: DragEvent) => {
      if (!hasDraggedFiles(event) || isLoading) return
      event.preventDefault()
      event.dataTransfer.dropEffect = 'copy'
    },
    onDragLeave: (event: DragEvent) => {
      if (!hasDraggedFiles(event)) return
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (dragDepth.current === 0) setIsDraggingFiles(false)
    },
    onDrop: (event: DragEvent) => {
      if (!hasDraggedFiles(event)) return
      event.preventDefault()
      dragDepth.current = 0
      setIsDraggingFiles(false)
      if (isLoading) return
      upload(event.dataTransfer.files)
    },
  }

  const hasInput = Boolean(form.counselor_memo.trim() || form.transcript_text.trim() || form.previous_session_summary.trim() || form.psychological_test_summary?.trim())
  const processing = materials.some((material) => material.status === 'uploading' || material.status === 'transcribing')
  const canSubmit = hasInput && !processing && !isLoading && !pendingAudioFiles
  const blockedReason = !hasInput
      ? '자료를 업로드하거나 메모를 입력하면 AI 요약을 생성할 수 있습니다.'
      : processing ? '자료 처리가 끝나면 AI 요약을 생성할 수 있습니다.' : null

  return (
    <section aria-label="새 회기 입력" className="mx-auto w-full max-w-[658px] px-4 pb-10 pt-2">
      <dialog ref={consentDialog} aria-labelledby="audio-consent-title" aria-describedby="audio-consent-description"
        onCancel={(event) => { event.preventDefault(); resolveAudioConsent(false) }}
        className="m-auto w-[min(92vw,480px)] rounded-xl border border-grey-200 bg-white p-6 shadow-xl backdrop:bg-black/40">
        <h2 id="audio-consent-title" className="text-base font-bold text-grey-900">음성 업로드 동의 확인</h2>
        <p id="audio-consent-description" className="mt-3 whitespace-pre-line text-sm leading-6 text-grey-700">{AUDIO_CONSENT_MESSAGE}</p>
        <p className="mt-2 break-all text-xs text-grey-500">{pendingAudioFiles?.filter(file => AUDIO_EXTENSION.test(file.name)).map(file => file.name).join(', ')}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" autoFocus onClick={() => resolveAudioConsent(false)} className="rounded-lg border border-grey-300 px-4 py-2 text-sm">취소</button>
          <button type="button" onClick={() => resolveAudioConsent(true)} className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white">동의를 확인하고 업로드</button>
        </div>
      </dialog>
      <div className="rm-card p-5">
        <h1 className="text-base font-bold text-grey-900">{mode === 'existing' ? `${form.session_number}회기 다시 요약하기` : '상담 자료를 먼저 올려주세요'}</h1>
        <p className="mt-2 text-sm text-grey-500">자료를 올리고 내용을 확인한 뒤 요약하세요. 상담일시는 필요할 때 입력하면 됩니다.</p>
        {mode === 'existing' && (
          <p role="note" className="mt-2 rounded-[10px] bg-primary-50 px-3 py-2 text-xs leading-5 text-grey-700">
            저장된 {form.session_number}회기 기록을 새 요약으로 바꿉니다. 다음 회기를 새로 만들려면 내담자 화면의 "새 회기 기록"을 눌러주세요.
          </p>
        )}

        <div className="mt-6" {...dropZoneHandlers} data-dragging={isDraggingFiles || undefined}>
          <p className="rm-label">자료 업로드</p>
          {materials.length === 0 ? (
            <label className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-[12px] border border-dashed px-4 py-9 text-center ${isDraggingFiles ? 'border-primary-400 bg-primary-50' : 'border-grey-400/60 bg-white hover:bg-primary-50/40'}`}>
              <Upload className={`h-6 w-6 ${isDraggingFiles ? 'text-primary-400' : 'text-grey-800'}`} strokeWidth={1.5} />
              <span className="text-sm font-semibold text-grey-900">{isDraggingFiles ? '여기에 놓으면 업로드됩니다.' : '파일을 끌어다 놓거나 클릭하여 파일을 선택해주세요.'}</span>
              <span className="text-xs text-grey-500">MP3 · M4A · WAV · PDF · DOCX · TXT</span>
              <span className="text-xs text-grey-500">음성 길이 제한 없음 · 파일 최대 500MB · 문서 최대 {uploadLimitLabel}</span>
              <input type="file" multiple accept={ACCEPT} className="sr-only" onChange={(event) => { upload(event.target.files); event.target.value = '' }} />
            </label>
          ) : (
            <div className={`rounded-[12px] border p-3 ${isDraggingFiles ? 'border-dashed border-primary-400 bg-primary-50' : 'border-grey-200'}`}>
              <ul className="space-y-2">
                {materials.map((material) => <MaterialItem key={material.id} material={material} onOpen={onOpenMaterial} onRemove={onRemoveMaterial} transcriptionAvailable={Boolean(audioCapabilities?.transcription.available)} />)}
              </ul>
              <label className="mt-3 flex h-11 cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-primary-400 text-sm font-bold text-primary-400 hover:bg-primary-50">
                <Plus className="h-4 w-4" />{isDraggingFiles ? '여기에 놓으면 추가됩니다' : '자료 추가하기'}
                <input type="file" multiple accept={ACCEPT} className="sr-only" onChange={(event) => { upload(event.target.files); event.target.value = '' }} />
              </label>
            </div>
          )}
          <p className="mt-2 text-xs text-grey-500">서버의 음성 임시 파일은 작업 종료 후 삭제합니다. 원음 재생을 위한 브라우저 파일은 자료를 제거하거나 이 화면을 닫을 때 해제됩니다. 검토해 반영한 텍스트만 회기 입력으로 사용합니다.</p>
          {form.transcript_text.trim() && (
            <p className="mt-2 text-xs text-grey-500">축어록 {form.transcript_text.replace(/\s/g, '').length.toLocaleString('ko-KR')}자가 회기 입력에 반영되어 있습니다.{materials.length > 0 ? ' 파일 항목을 눌러 내용을 확인하거나 수정할 수 있습니다.' : ''}</p>
          )}
        </div>

        <label className="mt-6 block">
          <span className="rm-label">메모</span>
          <textarea
            className="min-h-[96px] w-full resize-y rounded-[10px] border border-grey-200 bg-grey-100 px-3 py-2.5 text-sm leading-6 text-grey-800 outline-none placeholder:text-grey-500 focus:border-primary-400 focus:bg-white"
            value={form.counselor_memo}
            onChange={(event) => onUpdateField('counselor_memo', event.target.value)}
            placeholder="회기 중 특이사항, 상담사 소견 등을 입력하세요"
          />
        </label>

        {(hasInput || materials.some(material => ['completed', 'warning', 'transcribed'].includes(material.status))) && (
          <details className="mt-5 rounded-[10px] border border-grey-200 p-3">
            <summary className="cursor-pointer text-sm font-semibold text-grey-700">상담일시 추가 · 선택사항{form.session_date ? ` (${form.session_date})` : ''}</summary>
            <p className="mt-2 text-xs text-grey-500">날짜를 입력하지 않아도 요약할 수 있습니다.</p>
            <div className="mt-3 grid grid-cols-1 items-center gap-2 sm:grid-cols-[minmax(0,1fr)_130px_12px_130px]">
              <input type="date" aria-label="상담 날짜" className={fieldClass} onClick={openNativePicker} value={form.session_date} onChange={event => onUpdateField('session_date', event.target.value)} />
              <input type="time" aria-label="상담 시작 시간" className={`${fieldClass} text-center`} onClick={openNativePicker} value={sessionTime.start} onChange={event => onChangeSessionTime({ ...sessionTime, start: event.target.value })} />
              <span className="hidden text-center text-sm text-grey-400 sm:block">~</span>
              <input type="time" aria-label="상담 종료 시간" className={`${fieldClass} text-center`} onClick={openNativePicker} value={sessionTime.end} onChange={event => onChangeSessionTime({ ...sessionTime, end: event.target.value })} />
            </div>
          </details>
        )}
      </div>

      {error && (
        <div role="alert" className="mt-4 flex items-start gap-2 rounded-[10px] border border-danger-500/30 bg-danger-50 px-3 py-2.5 text-sm text-danger-500">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      <PrimaryButton className="mt-4 h-[52px] w-full rounded-[12px] text-[15px]" disabled={!canSubmit} loading={isLoading} onClick={onSubmit}>
        <PenLine className="h-5 w-5" />{mode === 'existing' ? `${form.session_number}회기 요약 다시 생성하기` : 'AI 요약 생성하기'}
      </PrimaryButton>
      {blockedReason && !isLoading && <p className="mt-2 text-center text-xs text-grey-500">{blockedReason}</p>}
    </section>
  )
}

function MaterialItem({ material, onOpen, onRemove, transcriptionAvailable }: {
  material: UploadedMaterial
  onOpen: (materialId: string, mode: 'document_preview' | 'audio_review' | 'material_apply') => void
  onRemove: (materialId: string) => void
  transcriptionAvailable: boolean
}) {
  const busy = material.status === 'uploading' || material.status === 'transcribing'
  const failed = material.status === 'failed' || Boolean(material.requiresReattachment)
  const applied = material.appliedTargets.length > 0
  const detail = failed
    ? material.error || (material.requiresReattachment ? '파일을 다시 첨부해주세요.' : '처리에 실패했습니다.')
    : busy
      ? material.status === 'uploading' ? '내용을 읽는 중…' : material.transcriptionProgress || '축어록을 만드는 중…'
      : material.kind === 'audio' && material.status === 'selected' && !transcriptionAvailable
        ? '자동 축어록이 비활성화된 환경입니다. 파일을 눌러 직접 입력할 수 있습니다.'
        : applied
          ? '회기 입력에 반영됨'
          : material.kind === 'audio' ? '축어록 검토 후 반영해주세요.' : '내용을 확인해주세요.'
  return (
    <li className={`flex items-center gap-3 rounded-[10px] border px-3 py-2.5 ${failed ? 'border-danger-500/30 bg-danger-50/40' : 'border-grey-200 bg-white'}`}>
      <button
        type="button"
        onClick={() => onOpen(material.id, material.kind === 'audio' ? 'audio_review' : applied ? 'document_preview' : 'material_apply')}
        disabled={busy}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
      >
        <FileText className="h-4 w-4 shrink-0 text-grey-700" />
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold text-grey-900">{material.filename}</span>
          <span className={`block truncate text-[11px] ${failed ? 'text-danger-500' : 'text-grey-500'}`}>{detail}</span>
        </span>
      </button>
      {busy ? <Loader2 className="h-5 w-5 shrink-0 animate-spin text-primary-400" /> : failed ? <AlertTriangle className="h-5 w-5 shrink-0 text-danger-500" /> : <CheckCircle2 className={`h-5 w-5 shrink-0 ${applied ? 'text-success-500' : 'text-grey-400'}`} />}
      <button type="button" onClick={() => onRemove(material.id)} aria-label={`${material.filename} 삭제`} className="shrink-0 text-grey-400 hover:text-grey-900"><X className="h-4 w-4" /></button>
    </li>
  )
}
