import { useEffect, useRef, useState, type DragEvent } from 'react'
import { AlertTriangle, CheckCircle2, FileText, Loader2, Mic, PenLine, Plus, Upload, X } from 'lucide-react'

import { PrimaryButton } from '../app-shell/ui'
import type { AudioCapabilitiesResponse, SessionInput } from '../../types/session'
import type { UploadedMaterial } from '../../types/materials'

export interface SessionTime {
  start: string
  end: string
}

const ACCEPT = '.pdf,.docx,.txt,.mp3,.m4a,.wav,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,audio/mpeg,audio/mp4,audio/wav,audio/x-wav'
const AUDIO_EXTENSION = /\.(mp3|m4a|wav)$/i
const AUDIO_CONSENT_MESSAGE = '음성 파일은 자동 축어록 생성을 위해 임시 처리되며 원본은 저장하지 않습니다.\n상담 음성 업로드에 필요한 동의를 확인하셨나요?'

const fieldClass = 'h-11 w-full rounded-[10px] border border-grey-200 bg-grey-100 px-3 text-sm text-grey-800 outline-none focus:border-primary-400 focus:bg-white'

function toFileList(files: File[]): FileList {
  const transfer = new DataTransfer()
  files.forEach((file) => transfer.items.add(file))
  return transfer.files
}

/**
 * New-session input page (Figma "홍길동 · 8회기 입력"): 상담 일시, 직접 녹음, 자료 업로드, 메모 → AI 요약 생성.
 * Session time is display-only (no backend field). Uploaded files are extracted/transcribed and applied
 * to the transcript input automatically. In-browser recording is not implemented yet.
 */
export default function SessionInputPage({
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
  // dragenter/dragleave fire for every child element, so count them instead of toggling.
  const dragDepth = useRef(0)

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
    if (window.confirm(AUDIO_CONSENT_MESSAGE)) return onUploadFiles(files, true)
    const rest = list.filter((file) => !AUDIO_EXTENSION.test(file.name))
    if (rest.length) onUploadFiles(toFileList(rest), false)
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
  const canSubmit = Boolean(form.session_date) && hasInput && !processing && !isLoading
  const blockedReason = !form.session_date
    ? '상담 날짜를 입력해주세요.'
    : !hasInput
      ? '자료를 업로드하거나 메모를 입력하면 AI 요약을 생성할 수 있습니다.'
      : processing ? '자료 처리가 끝나면 AI 요약을 생성할 수 있습니다.' : null

  return (
    <section aria-label="새 회기 입력" className="mx-auto w-full max-w-[658px] px-4 pb-10 pt-2">
      <div className="rm-card p-5">
        <h1 className="text-base font-bold text-grey-900">새 회기 시작</h1>

        <div className="mt-5">
          <p className="rm-label">상담 일시</p>
          <div className="grid grid-cols-1 items-center gap-2 sm:grid-cols-[minmax(0,1fr)_130px_12px_130px]">
            <input type="date" aria-label="상담 날짜" className={fieldClass} value={form.session_date} onChange={(event) => onUpdateField('session_date', event.target.value)} />
            <input type="time" aria-label="상담 시작 시간" className={`${fieldClass} text-center`} value={sessionTime.start} onChange={(event) => onChangeSessionTime({ ...sessionTime, start: event.target.value })} />
            <span className="hidden text-center text-sm text-grey-400 sm:block">~</span>
            <input type="time" aria-label="상담 종료 시간" className={`${fieldClass} text-center`} value={sessionTime.end} onChange={(event) => onChangeSessionTime({ ...sessionTime, end: event.target.value })} />
          </div>
        </div>

        <div className="mt-6">
          <p className="rm-label">직접 녹음</p>
          <button
            type="button"
            disabled
            title="직접 녹음은 준비 중입니다. 녹음 파일은 자료 업로드로 올려주세요."
            className="inline-flex h-[52px] w-full items-center justify-center gap-2 rounded-[10px] border border-grey-200 bg-white text-[15px] font-bold text-grey-900 disabled:cursor-not-allowed disabled:text-grey-400"
          >
            <Mic className="h-5 w-5" />
            녹음 시작
          </button>
          <p className="mt-1.5 text-xs text-grey-500">직접 녹음은 준비 중입니다. 녹음 파일(mp3·m4a·wav)은 아래 자료 업로드로 올려주세요.</p>
        </div>

        <div className="mt-6" {...dropZoneHandlers} data-dragging={isDraggingFiles || undefined}>
          <p className="rm-label">자료 업로드</p>
          {materials.length === 0 ? (
            <label className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-[12px] border border-dashed px-4 py-9 text-center ${isDraggingFiles ? 'border-primary-400 bg-primary-50' : 'border-grey-400/60 bg-white hover:bg-primary-50/40'}`}>
              <Upload className={`h-6 w-6 ${isDraggingFiles ? 'text-primary-400' : 'text-grey-800'}`} strokeWidth={1.5} />
              <span className="text-sm font-semibold text-grey-900">{isDraggingFiles ? '여기에 놓으면 업로드됩니다.' : '파일을 끌어다 놓거나 클릭하여 파일을 선택해주세요.'}</span>
              <span className="text-xs text-grey-500">STT 자료, 검사 결과 PDF, 워드 파일 등 · 최대 {uploadLimitLabel}</span>
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
          {form.transcript_text.trim() && (
            <p className="mt-2 text-xs text-grey-500">축어록 {form.transcript_text.replace(/\s/g, '').length.toLocaleString('ko-KR')}자가 회기 입력에 반영되어 있습니다. 파일 항목을 눌러 내용을 확인하거나 수정할 수 있습니다.</p>
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
      </div>

      {error && (
        <div role="alert" className="mt-4 flex items-start gap-2 rounded-[10px] border border-danger-500/30 bg-danger-50 px-3 py-2.5 text-sm text-danger-500">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <p>{error}</p>
        </div>
      )}

      <PrimaryButton className="mt-4 h-[52px] w-full rounded-[12px] text-[15px]" disabled={!canSubmit} loading={isLoading} onClick={onSubmit}>
        <PenLine className="h-5 w-5" />AI 요약 생성하기
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
      ? material.status === 'uploading' ? '내용을 읽는 중…' : '축어록을 만드는 중…'
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
