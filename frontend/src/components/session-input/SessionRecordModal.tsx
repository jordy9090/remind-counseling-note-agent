import { useState, type FormEvent } from 'react'
import { AlertTriangle, ArrowLeft, CalendarDays, CheckCircle2, Clock, FileText, Loader2, Plus, Sparkles, Upload, X } from 'lucide-react'

import ModalShell from '../app-shell/ModalShell'
import { OutlineButton, PrimaryButton } from '../app-shell/ui'
import type { ChecklistItem } from '../../lib/checklist'
import { suggestedCustomItems } from '../../lib/checklist'
import type { AudioCapabilitiesResponse, SessionInput } from '../../types/session'
import type { UploadedMaterial } from '../../types/materials'

export interface SessionTime {
  start: string
  end: string
}

const ACCEPT = '.pdf,.docx,.txt,.mp3,.m4a,.wav,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,audio/mpeg,audio/mp4,audio/wav,audio/x-wav'

/**
 * 새 회기 기록 모달 (Figma). 상담 날짜·시간, 자료 업로드, 요약 항목 체크리스트, 메모 → AI 요약 생성.
 * 시간은 화면 표시용이다(백엔드 필드 없음). 업로드 자료는 추출·전사 후 자동으로 축어록 입력에 반영된다.
 */
export default function SessionRecordModal({
  clientName,
  form,
  sessionTime,
  materials,
  audioCapabilities,
  checklistItems,
  visibleSectionIds,
  rememberChecklist,
  error,
  isLoading,
  uploadLimitLabel,
  onChangeSessionTime,
  onUpdateField,
  onUploadFiles,
  onOpenMaterial,
  onRemoveMaterial,
  onToggleChecklist,
  onAddCustomItem,
  onRemoveCustomItem,
  onToggleRememberChecklist,
  onBack,
  onClose,
  onSubmit,
}: {
  clientName: string
  form: SessionInput
  sessionTime: SessionTime
  materials: UploadedMaterial[]
  audioCapabilities: AudioCapabilitiesResponse | null
  checklistItems: ChecklistItem[]
  visibleSectionIds: Set<string>
  rememberChecklist: boolean
  error: string | null
  isLoading: boolean
  uploadLimitLabel: string
  onChangeSessionTime: (next: SessionTime) => void
  onUpdateField: (field: keyof SessionInput, value: string | number) => void
  onUploadFiles: (files: FileList | null, audioConsent: boolean) => void
  onOpenMaterial: (materialId: string, mode: 'document_preview' | 'audio_review' | 'material_apply') => void
  onRemoveMaterial: (materialId: string) => void
  onToggleChecklist: (id: string) => void
  onAddCustomItem: (title: string) => void
  onRemoveCustomItem: (id: string) => void
  onToggleRememberChecklist: (value: boolean) => void
  onBack: (() => void) | null
  onClose: () => void
  onSubmit: () => void
}) {
  const [customDraft, setCustomDraft] = useState('')
  const [audioConsent, setAudioConsent] = useState(false)
  const selected = checklistItems.filter((item) => visibleSectionIds.has(item.id))
  const selectedIds = new Set(selected.map((item) => item.id))
  const recommended = [
    ...checklistItems.filter((item) => !selectedIds.has(item.id)),
    ...suggestedCustomItems
      .filter((title) => !checklistItems.some((item) => item.title === title))
      .map((title) => ({ id: `suggest:${title}`, title })),
  ]
  const hasInput = Boolean(form.counselor_memo.trim() || form.transcript_text.trim() || form.previous_session_summary.trim() || form.psychological_test_summary?.trim())
  const processing = materials.some((material) => material.status === 'uploading' || material.status === 'transcribing')
  const canSubmit = Boolean(form.session_date) && hasInput && !processing && !isLoading

  const submitCustom = (event: FormEvent) => {
    event.preventDefault()
    const title = customDraft.trim()
    if (!title) return
    onAddCustomItem(title)
    setCustomDraft('')
  }

  return (
    <ModalShell
      ariaLabel="새 회기 기록"
      title={<><span className="text-primary-400">{clientName}</span>님과의 회기를 기록해요</>}
      description="상담 자료를 업로드하고 메모를 작성하면 AI가 회기 내용을 요약해드려요."
      onClose={onClose}
      closeDisabled={isLoading}
      width={740}
      footer={
        <>
          {onBack && <OutlineButton onClick={onBack} disabled={isLoading} className="min-w-[180px]"><ArrowLeft className="h-4 w-4" />뒤로가기</OutlineButton>}
          <PrimaryButton className="flex-1" disabled={!canSubmit} loading={isLoading} onClick={onSubmit}><Sparkles className="h-4 w-4" />AI 요약 생성하기</PrimaryButton>
        </>
      }
    >
      <div className="flex flex-col gap-6">
        <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <label className="block">
            <span className="rm-label flex items-center gap-1.5"><CalendarDays className="h-4 w-4" />상담 날짜<span className="req">*</span></span>
            <input type="date" className="rm-input" value={form.session_date} onChange={(event) => onUpdateField('session_date', event.target.value)} required />
          </label>
          <div>
            <span className="rm-label flex items-center gap-1.5"><Clock className="h-4 w-4" />상담 시간<span className="req">*</span></span>
            <div className="flex items-center gap-2">
              <input type="time" aria-label="상담 시작 시간" className="rm-input" value={sessionTime.start} onChange={(event) => onChangeSessionTime({ ...sessionTime, start: event.target.value })} />
              <span className="text-grey-500">-</span>
              <input type="time" aria-label="상담 종료 시간" className="rm-input" value={sessionTime.end} onChange={(event) => onChangeSessionTime({ ...sessionTime, end: event.target.value })} />
            </div>
          </div>
        </div>

        <div>
          <span className="rm-label">자료 업로드</span>
          {materials.length === 0 ? (
            <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-[12px] border border-dashed border-primary-100 bg-white px-4 py-10 text-center hover:bg-primary-50/40">
              <Upload className="h-7 w-7 text-grey-700" strokeWidth={1.5} />
              <span className="text-sm font-semibold text-grey-800">클릭하여 파일을 선택해주세요.</span>
              <span className="text-xs text-grey-500">STT 자료, 검사 결과 PDF, 워드 파일, 음성(mp3·m4a·wav) · 최대 {uploadLimitLabel}</span>
              <input type="file" multiple accept={ACCEPT} className="sr-only" onChange={(event) => { onUploadFiles(event.target.files, audioConsent); event.target.value = '' }} />
            </label>
          ) : (
            <div className="rounded-[12px] border border-primary-100 p-3">
              <ul className="space-y-2">
                {materials.map((material) => <MaterialItem key={material.id} material={material} onOpen={onOpenMaterial} onRemove={onRemoveMaterial} transcriptionAvailable={Boolean(audioCapabilities?.transcription.available)} />)}
              </ul>
              <label className="mt-3 flex h-11 cursor-pointer items-center justify-center gap-2 rounded-[10px] border border-primary-400 text-sm font-bold text-primary-400 hover:bg-primary-50">
                <Plus className="h-4 w-4" />자료 추가하기
                <input type="file" multiple accept={ACCEPT} className="sr-only" onChange={(event) => { onUploadFiles(event.target.files, audioConsent); event.target.value = '' }} />
              </label>
            </div>
          )}
          <label className="mt-2 flex items-start gap-2 text-xs text-grey-500">
            <input type="checkbox" checked={audioConsent} onChange={(event) => setAudioConsent(event.target.checked)} className="mt-0.5 h-3.5 w-3.5 rounded border-grey-200 text-primary-400" />
            <span>음성 파일은 자동 축어록 생성을 위해 임시 처리되며 원본은 저장하지 않습니다. 음성 업로드 전 동의를 체크해주세요.</span>
          </label>
        </div>

        <div>
          <span className="rm-label">요약 항목 체크리스트</span>
          <p className="-mt-1 mb-2 text-xs text-grey-500">AI가 선택한 항목을 중심으로 회기 내용을 정리해드려요.</p>
          <div className="rounded-[12px] border border-primary-100 p-3">
            <div className="flex flex-wrap gap-2">
              {selected.map((item) => (
                <span key={item.id} className="inline-flex h-8 items-center gap-1 rounded-full border border-primary-400 bg-white px-3 text-xs font-bold text-primary-400">
                  <button type="button" aria-label={`${item.title} 제외`} onClick={() => (item.id.startsWith('custom_') ? onRemoveCustomItem(item.id) : onToggleChecklist(item.id))} className="text-primary-400 hover:text-primary-900"><X className="h-3.5 w-3.5" /></button>
                  {item.title}
                </span>
              ))}
              <form onSubmit={submitCustom} className="inline-flex h-8 items-center gap-1 rounded-full border border-dashed border-primary-400 bg-white px-3 text-xs font-bold text-primary-400">
                <Plus className="h-3.5 w-3.5" />
                <input value={customDraft} onChange={(event) => setCustomDraft(event.target.value)} placeholder="항목을 입력하세요" aria-label="추가할 요약 항목" className="w-[120px] bg-transparent text-xs font-semibold text-grey-900 outline-none placeholder:text-primary-400/70" maxLength={30} />
              </form>
            </div>
            {recommended.length > 0 && (
              <div className="mt-3 border-t border-grey-200 pt-3">
                <p className="text-xs text-grey-500">추천 항목</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {recommended.map((item) => (
                    <button key={item.id} type="button" onClick={() => (item.id.startsWith('suggest:') ? onAddCustomItem(item.title) : onToggleChecklist(item.id))} className="inline-flex h-8 items-center rounded-full border border-primary-100 bg-white px-3 text-xs font-bold text-primary-400 hover:bg-primary-50">
                      {item.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
          <label className="mt-2 flex items-center justify-end gap-2 text-xs text-grey-600">
            다음에도 이 설정 사용하기
            <span className="relative inline-flex h-6 w-11 items-center">
              <input type="checkbox" role="switch" checked={rememberChecklist} onChange={(event) => onToggleRememberChecklist(event.target.checked)} className="peer sr-only" />
              <span className="h-6 w-11 rounded-full bg-grey-200 transition peer-checked:bg-primary-400" />
              <span className="absolute left-0.5 h-5 w-5 rounded-full bg-white shadow transition peer-checked:translate-x-5" />
            </span>
          </label>
        </div>

        <label className="block">
          <span className="rm-label">메모</span>
          <textarea
            className="rm-textarea min-h-[120px]"
            value={form.counselor_memo}
            onChange={(event) => onUpdateField('counselor_memo', event.target.value)}
            placeholder="회기 중 특이사항, 상담사 소견 등을 입력하세요"
          />
        </label>
        {form.transcript_text.trim() && (
          <p className="-mt-3 text-xs text-grey-500">축어록 {form.transcript_text.replace(/\s/g, '').length.toLocaleString('ko-KR')}자가 회기 입력에 반영되어 있습니다. 파일 항목을 눌러 내용을 확인하거나 수정할 수 있습니다.</p>
        )}
        {!hasInput && <p className="-mt-3 text-xs text-grey-500">자료를 업로드하거나 메모를 입력하면 AI 요약을 생성할 수 있습니다.</p>}
        {error && (
          <div role="alert" className="flex items-start gap-2 rounded-[10px] border border-danger-500/30 bg-danger-50 px-3 py-2.5 text-sm text-danger-500">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>{error}</p>
          </div>
        )}
      </div>
    </ModalShell>
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
