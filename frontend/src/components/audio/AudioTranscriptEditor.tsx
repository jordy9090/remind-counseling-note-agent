import { Play, RefreshCcw } from 'lucide-react'
import { useMemo, useRef } from 'react'
import {
  buildNonverbalNotes,
  buildTranscriptText,
  formatTimestamp,
  getAudioSeekTarget,
  getNotableAcousticObservations,
  getSegmentSpeakerKey,
  getSpeakerRoleLabel,
  type SpeakerRole,
  type SpeakerRoleMap,
} from '../../lib/audioTranscriptWorkflow'
import type { AudioSegment } from '../../types/session'

type AudioMaterialStatus = 'uploading' | 'completed' | 'warning' | 'selected' | 'transcribing' | 'transcribed' | 'failed'
type AudioApplyMode = 'append' | 'replace'

export interface AudioTranscriptEditorMaterial {
  id: string
  filename: string
  status: AudioMaterialStatus
  objectUrl?: string
  transcriptText?: string
  segments?: AudioSegment[]
  warnings: string[]
  error?: string
  speakerRoleMap?: SpeakerRoleMap
  runtimeMode?: 'real' | 'stub'
  diarizationStatus?: 'completed' | 'fallback' | 'disabled'
  languageProbability?: number | null
  nonverbalNotes?: string
  dirtySinceApply?: boolean
  expectedSpeakers?: number
}

export function AudioTranscriptEditor({
  applyMode,
  material,
  onApply,
  onApplyModeChange,
  onExpectedSpeakersChange,
  onTranscribe,
  onUpdateSegmentText,
  onUpdateSpeakerRole,
  transcriptionAvailable,
  transcriptionReason,
}: {
  applyMode: AudioApplyMode
  material: AudioTranscriptEditorMaterial
  onApply: () => void
  onApplyModeChange: (mode: AudioApplyMode) => void
  onExpectedSpeakersChange: (value: number) => void
  onTranscribe: () => void
  onUpdateSegmentText: (segmentId: number, text: string) => void
  onUpdateSpeakerRole: (speakerKey: string, role: SpeakerRole) => void
  transcriptionAvailable: boolean
  transcriptionReason: string | null
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const segments = material.segments || []
  const speakerRoleMap = material.speakerRoleMap || {}
  const transcriptPreview = useMemo(
    () => buildTranscriptText(segments, speakerRoleMap),
    [segments, speakerRoleMap],
  )
  const nonverbalPreview = useMemo(
    () => buildNonverbalNotes(segments, speakerRoleMap),
    [segments, speakerRoleMap],
  )
  const speakerKeys = useMemo(() => {
    return Array.from(new Set(segments.map(getSegmentSpeakerKey)))
  }, [segments])
  const canApply = material.status === 'transcribed' && Boolean(transcriptPreview.trim())

  const playSegment = async (segment: AudioSegment) => {
    const seekTarget = getAudioSeekTarget(segment)
    if (!audioRef.current || seekTarget === null) return
    audioRef.current.currentTime = seekTarget
    await audioRef.current.play()
  }

  return (
    <div className="space-y-4">
      {material.objectUrl && (
        <audio ref={audioRef} controls src={material.objectUrl} className="w-full" />
      )}

      {material.dirtySinceApply && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-800">
          축어록 수정사항이 회기 입력에 아직 다시 반영되지 않았습니다.
        </p>
      )}

      <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:grid-cols-[minmax(0,1fr)_140px]">
        <div>
          <p className="text-sm font-bold text-slate-900">{material.filename}</p>
          <p className="mt-1 text-xs text-slate-500">
            실행 모드: {material.runtimeMode === 'stub' ? '시연용 stub' : material.runtimeMode === 'real' ? '실제 STT' : '대기'}
            {material.diarizationStatus ? ` · 화자 분리: ${material.diarizationStatus}` : ''}
          </p>
          {material.languageProbability != null && (
            <p className="mt-1 text-xs text-slate-500">
              언어 감지 신뢰도 {(material.languageProbability * 100).toFixed(1)}%
            </p>
          )}
        </div>
        <label className="text-xs font-semibold text-slate-600">
          예상 화자 수
          <select
            value={material.expectedSpeakers || 2}
            onChange={(event) => onExpectedSpeakersChange(Number(event.target.value))}
            className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm"
          >
            {[1, 2, 3, 4].map((count) => (
              <option key={count} value={count}>
                {count}명
              </option>
            ))}
          </select>
        </label>
      </div>

      {material.status !== 'transcribed' && (
        <button
          type="button"
          disabled={!transcriptionAvailable || material.status === 'transcribing'}
          onClick={onTranscribe}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCcw className="h-4 w-4" />
          {material.status === 'transcribing' ? '축어록 생성 중' : '축어록 생성'}
        </button>
      )}
      {!transcriptionAvailable && material.status !== 'transcribed' && (
        <p className="text-xs text-slate-500">{transcriptionReason || '음성 자동 축어록은 현재 비활성화되어 있습니다.'}</p>
      )}

      {material.warnings.length > 0 && (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-800">
          {material.warnings.join(' ')}
        </p>
      )}
      {material.error && <p className="text-xs font-semibold text-rose-600">{material.error}</p>}

      {speakerKeys.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {speakerKeys.map((speakerKey) => (
            <label key={speakerKey} className="rounded-md border border-slate-200 bg-white p-3 text-xs font-semibold text-slate-600">
              {speakerKey}
              <select
                value={speakerRoleMap[speakerKey] || 'unassigned'}
                onChange={(event) => onUpdateSpeakerRole(speakerKey, event.target.value as SpeakerRole)}
                className="mt-1 h-9 w-full rounded-md border border-slate-300 bg-white px-2 text-sm"
              >
                <option value="unassigned">{getSpeakerRoleLabel('unassigned')}</option>
                <option value="client">{getSpeakerRoleLabel('client')}</option>
                <option value="counselor">{getSpeakerRoleLabel('counselor')}</option>
              </select>
            </label>
          ))}
        </div>
      )}

      {segments.length > 0 && (
        <div className="space-y-2">
          {segments.map((segment) => {
            const observations = getNotableAcousticObservations(segment)
            const seekTarget = getAudioSeekTarget(segment)
            return (
              <div key={segment.id} className="rounded-md border border-slate-200 bg-white p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold text-slate-500">
                    {formatTimestamp(segment.start)} - {formatTimestamp(segment.end)}
                  </span>
                  <button
                    type="button"
                    onClick={() => void playSegment(segment)}
                    disabled={!material.objectUrl || seekTarget === null}
                    aria-label={`${formatTimestamp(segment.start)} 발화 재생`}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    <Play className="h-4 w-4" />
                  </button>
                </div>
                <textarea
                  value={segment.text}
                  onChange={(event) => onUpdateSegmentText(segment.id, event.target.value)}
                  className="mt-2 min-h-[72px] w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
                {observations.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {observations.map((observation) => (
                      <span key={observation} className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-amber-800">
                        {observation}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      <label className="block text-sm font-semibold text-slate-700">
        전체 축어록 미리보기
        <textarea
          value={transcriptPreview || material.transcriptText || ''}
          readOnly
          className="mt-1 min-h-[180px] w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-900 outline-none"
        />
      </label>

      <label className="block text-sm font-semibold text-slate-700">
        비언어/음향 관찰 메모 미리보기
        <textarea
          value={nonverbalPreview || material.nonverbalNotes || ''}
          readOnly
          className="mt-1 min-h-[120px] w-full rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-900 outline-none"
        />
      </label>

      {material.status === 'transcribed' && (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => onApplyModeChange('append')}
              className={`rounded-md border px-3 py-2 text-sm font-semibold ${
                applyMode === 'append' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'
              }`}
            >
              기존 회기 입력 뒤에 추가
            </button>
            <button
              type="button"
              onClick={() => onApplyModeChange('replace')}
              className={`rounded-md border px-3 py-2 text-sm font-semibold ${
                applyMode === 'replace' ? 'border-blue-600 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'
              }`}
            >
              기존 회기 입력 교체
            </button>
          </div>
          <button
            type="button"
            disabled={!canApply}
            onClick={onApply}
            className="inline-flex w-full items-center justify-center rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            회기요약 입력에 반영
          </button>
        </div>
      )}
    </div>
  )
}
