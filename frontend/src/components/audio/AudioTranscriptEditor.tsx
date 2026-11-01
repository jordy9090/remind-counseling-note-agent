import { Play, RefreshCcw } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { reviewAudioPrivacy } from '../../api/client'
import {
  buildNonverbalNotes,
  buildTranscriptText,
  formatTimestamp,
  getAudioSeekTarget,
  getNotableAcousticObservations,
  getSegmentSpeakerKey,
  getSpeakerRoleLabel,
  mergeAudioSegments,
  splitAudioSegment,
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
  rawSegments?: AudioSegment[]
  reviewRanges?: { start: number; end: number; code?: string }[]
  failedRanges?: { start: number; end: number; code?: string }[]
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
  onUpdateSegments,
  onUpdateSpeakerRole,
  transcriptionAvailable,
  transcriptionReason,
}: {
  applyMode: AudioApplyMode
  material: AudioTranscriptEditorMaterial
  onApply: (reviewedText: string, sourceText: string) => void
  onApplyModeChange: (mode: AudioApplyMode) => void
  onExpectedSpeakersChange: (value: number) => void
  onTranscribe: () => void
  onUpdateSegmentText: (segmentId: number, text: string) => void
  onUpdateSegments: (segments: AudioSegment[]) => void
  onUpdateSpeakerRole: (speakerKey: string, role: SpeakerRole) => void
  transcriptionAvailable: boolean
  transcriptionReason: string | null
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [splitPositions, setSplitPositions] = useState<Record<number, number>>({})
  const [splitTimes, setSplitTimes] = useState<Record<number, string>>({})
  const [privacy, setPrivacy] = useState<{ key: string; source: string; text: string; categories: string[] } | null>(null)
  const [confirmedReviewKey, setConfirmedReviewKey] = useState<string | null>(null)
  const [privacyBusy, setPrivacyBusy] = useState(false)
  const [privacyError, setPrivacyError] = useState('')
  const [editError, setEditError] = useState('')
  const segments = material.segments || []
  const speakerRoleMap = material.speakerRoleMap || {}
  const reviewKey = JSON.stringify([material.id, segments.map(s => [s.id, s.start, s.end, s.speaker, s.text]), speakerRoleMap,
    material.failedRanges, material.reviewRanges])
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
  const canApply = material.status === 'transcribed' && Boolean(privacy?.text.trim())
    && privacy?.key === reviewKey && confirmedReviewKey === reviewKey

  const preparePrivacyReview = async () => {
    setPrivacyBusy(true)
    setPrivacyError('')
    setConfirmedReviewKey(null)
    try {
      const result = await reviewAudioPrivacy(transcriptPreview)
      setPrivacy({ key: reviewKey, source: transcriptPreview, text: result.text, categories: result.candidates.map(c => c.category) })
    } catch {
      setPrivacyError('개인정보 후보를 확인하지 못했습니다. 로컬 음성 서버 연결을 확인해주세요.')
    } finally {
      setPrivacyBusy(false)
    }
  }

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
      {!!material.failedRanges?.length && <p className="text-sm text-rose-700">미처리 구간: {material.failedRanges.map(range =>
        `${formatTimestamp(range.start)}–${formatTimestamp(range.end)}`).join(', ')}</p>}
      {!!material.reviewRanges?.length && <div className="rounded border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
        <p>음성·텍스트 연결 확인 필요: 음성 시각이 부정확하거나 말이 누락되었을 수 있습니다.</p>
        <div className="mt-2 flex flex-wrap gap-2">{material.reviewRanges.map((range, index) =>
          <button type="button" key={`${range.start}-${index}`} disabled={!material.objectUrl}
            className="rounded border border-amber-300 px-2 py-1 disabled:opacity-40"
            onClick={() => { if (audioRef.current) { audioRef.current.currentTime = Math.max(0, range.start - 1); void audioRef.current.play() } }}>
            {formatTimestamp(range.start)}–{formatTimestamp(range.end)} 듣기
          </button>)}</div>
      </div>}
      <p className="text-xs text-slate-600">화자 번호는 역할을 뜻하지 않습니다. 원음을 확인해 상담자·내담자를 지정해주세요.</p>
      <p className="text-xs text-slate-600">발화를 나누려면 본문에 커서를 놓고 원음에서 확인한 분리 시각을 입력하세요. 병합은 같은 화자의 인접 발화에 사용할 수 있습니다.</p>
      {editError && <p role="alert" className="text-xs text-rose-700">{editError}</p>}

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
          {segments.map((segment, index) => {
            const observations = getNotableAcousticObservations(segment)
            const seekTarget = getAudioSeekTarget(segment)
            return (
              <div key={segment.id} className="rounded-md border border-slate-200 bg-white p-3" style={{ contentVisibility: 'auto', containIntrinsicSize: 'auto 220px' }}>
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
                  aria-label={`${segment.id}번 발화 텍스트`}
                  value={segment.text}
                  onChange={(event) => onUpdateSegmentText(segment.id, event.target.value)}
                  onSelect={(event) => { const position = event.currentTarget.selectionStart; setSplitPositions(current => ({ ...current, [segment.id]: position })) }}
                  className="mt-2 min-h-[72px] w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  <label>이 발화의 화자
                    <select aria-label={`${segment.id}번 발화 화자`} value={segment.speaker || 'unknown'}
                      onChange={event => onUpdateSegments(segments.map(s => s.id === segment.id ? { ...s, speaker: event.target.value } : s))}
                      className="ml-2 rounded border p-1">
                      {[...new Set([...speakerKeys, 'speaker_0', 'speaker_1', 'unknown'])].map(key => <option key={key} value={key}>{key}</option>)}
                    </select>
                  </label>
                  <button type="button" disabled={!segments[index + 1] || segment.speaker !== segments[index + 1].speaker}
                    className="rounded border p-1 disabled:opacity-40" onClick={() => onUpdateSegments(mergeAudioSegments(segments, segment.id))}>
                    다음 발화와 병합
                  </button>
                  <label>분리 시각(초)
                    <input type="number" step="0.01" min={segment.start} max={segment.end}
                      aria-label={`${segment.id}번 발화 분리 시각`} value={splitTimes[segment.id] || ''}
                      onChange={event => setSplitTimes(current => ({ ...current, [segment.id]: event.target.value }))}
                      className="ml-2 w-24 rounded border p-1" />
                  </label>
                  <button type="button" className="rounded border p-1" onClick={() => {
                    const next = splitAudioSegment(segments, segment.id, splitPositions[segment.id] || 0, Number(splitTimes[segment.id]))
                    if (next === segments) setEditError('본문 중간에 커서를 놓고 발화 시작과 끝 사이의 시각을 입력해주세요.')
                    else { setEditError(''); onUpdateSegments(next) }
                  }}>커서에서 분리</button>
                </div>
                {!!segment.review_flags?.length && <p className="mt-2 text-xs text-amber-800">
                  원음 확인 필요: {segment.review_flags.map(flag => ({
                    speaker_uncertain: '화자 경계', low_confidence: '낮은 인식 신뢰도', sensitive_expression: '부정·수치·민감 표현',
                    coarse_timestamps: '대략적인 시각', mixed_speakers_without_word_timestamps: '한 구간에 여러 화자',
                    repetition_candidate: '반복 의심',
                    timestamp_anomaly: '발화 시간과 텍스트 길이 불일치',
                  }[flag] || '전사 검토')).join(', ')}
                </p>}
                {!!segment.source_ranges?.length && <p className="mt-1 text-xs text-slate-500">원본 시각: {segment.source_ranges.map(range =>
                  `${range.start.toFixed(2)}–${range.end.toFixed(2)}초`).join(', ')}</p>}
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

      {!!material.rawSegments?.length && <details className="text-xs text-slate-600">
        <summary>수정 전 ASR 원본 보기</summary>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap">{material.rawSegments.map(s =>
          `[${formatTimestamp(s.start)}] ${s.text}`).join('\n')}</pre>
      </details>}

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
          <button type="button" disabled={privacyBusy || !transcriptPreview.trim()} onClick={() => void preparePrivacyReview()}
            className="rounded border border-blue-600 px-3 py-2 text-sm text-blue-700">
            {privacyBusy ? '개인정보 후보 확인 중' : '수정본의 개인정보 후보 확인'}
          </button>
          {privacyError && <p className="text-sm text-rose-700">{privacyError}</p>}
          {privacy?.key === reviewKey && <div className="space-y-2 rounded border p-3">
            <label className="block text-sm font-semibold">비식별화 후 요약에 전달할 텍스트
              <textarea aria-label="비식별화 후 요약에 전달할 텍스트" className="mt-2 min-h-48 w-full rounded border p-2 font-normal"
                value={privacy.text} onChange={event => { setPrivacy({ ...privacy, text: event.target.value }); setConfirmedReviewKey(null) }} />
            </label>
            <p className="text-xs text-slate-600">자동 탐지가 놓친 이름·기관·연락처를 직접 치환해주세요. 의미가 달라지는 문장 재작성은 하지 않습니다.</p>
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={confirmedReviewKey === reviewKey}
              onChange={event => setConfirmedReviewKey(event.target.checked ? reviewKey : null)} />
              원음과 화자, 누락 구간 및 개인정보 치환 결과를 확인했습니다.
            </label>
          </div>}
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
            onClick={() => { if (canApply && privacy) onApply(privacy.text, privacy.source) }}
            className="inline-flex w-full items-center justify-center rounded-lg bg-blue-700 px-4 py-3 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
          >
            검토한 수정본을 회기요약 입력에 반영
          </button>
        </div>
      )}
    </div>
  )
}
