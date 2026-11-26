import { useCallback, useEffect, useState } from 'react'
import { Check, Copy, Link2, Loader2, Unlink } from 'lucide-react'

import { checkInErrorMessage, createClientInvite, endCaseClientLink, getCaseClientLink, listCaseCheckIns } from '../../api/client'
import {
  clientInviteUrl,
  entriesSince,
  formatCheckInTime,
  moodLabel,
  type CheckIn,
  type ClientLinkStatus,
} from '../../lib/clientCheckIns'

/**
 * "회기 사이 기록" tab: invite the client, see the link state, and read what the client recorded
 * between sessions. Read-only for the counselor; nothing here is sent to an AI model.
 */
export default function ClientCheckInsPanel({ caseId, lastSessionDate }: { caseId: string; lastSessionDate: string | null }) {
  const [link, setLink] = useState<ClientLinkStatus | null>(null)
  const [entries, setEntries] = useState<CheckIn[]>([])
  const [inviteUrl, setInviteUrl] = useState('')
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [onlySinceSession, setOnlySinceSession] = useState(Boolean(lastSessionDate))

  const load = useCallback(async () => {
    setLoading(true); setMessage('')
    try {
      const [currentLink, currentEntries] = await Promise.all([getCaseClientLink(caseId), listCaseCheckIns(caseId)])
      setLink(currentLink)
      setEntries(currentEntries)
    } catch (error) {
      setMessage(checkInErrorMessage(error, '회기 사이 기록을 불러오지 못했어요.'))
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => { void load() }, [load])

  const invite = async () => {
    if (link?.status === 'invited' && !window.confirm('새 초대 링크를 만들면 이전 링크는 쓸 수 없게 돼요. 계속할까요?')) return
    setBusy(true); setMessage(''); setCopied(false)
    try {
      const created = await createClientInvite(caseId)
      setInviteUrl(clientInviteUrl(created.token))
      await load()
    } catch (error) {
      setMessage(checkInErrorMessage(error, '초대 링크를 만들지 못했어요.'))
    } finally {
      setBusy(false)
    }
  }

  const end = async () => {
    const text = link?.status === 'active'
      ? '내담자와의 연결을 끊을까요? 내담자는 새 기록을 남길 수 없게 되고, 이미 남긴 기록은 계속 볼 수 있어요.'
      : '사용 전 초대 링크를 취소할까요?'
    if (!window.confirm(text)) return
    setBusy(true); setMessage('')
    try {
      await endCaseClientLink(caseId)
      setInviteUrl('')
      await load()
    } catch (error) {
      setMessage(checkInErrorMessage(error, '연결을 끊지 못했어요.'))
    } finally {
      setBusy(false)
    }
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inviteUrl)
      setCopied(true)
    } catch {
      setMessage('복사하지 못했어요. 링크를 직접 선택해 복사해주세요.')
    }
  }

  if (loading) return <p className="flex items-center gap-2 text-sm text-grey-500"><Loader2 className="h-4 w-4 animate-spin" />회기 사이 기록을 불러오고 있어요</p>

  const shown = onlySinceSession ? entriesSince(entries, lastSessionDate) : entries
  const chart = [...shown].reverse().slice(-30)

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-[12px] border border-grey-200 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-bold text-grey-900">내담자 기록 공유</span>
          <span className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${link?.status === 'active' ? 'bg-success-50 text-success-500' : link?.status === 'invited' ? 'bg-primary-50 text-primary-400' : 'bg-grey-100 text-grey-500'}`}>
            {link?.status === 'active' ? '연결됨' : link?.status === 'invited' ? '초대 대기 중' : '연결 안 됨'}
          </span>
          <div className="ml-auto flex gap-2">
            {link?.status !== 'active' && (
              <button type="button" disabled={busy} onClick={() => void invite()} className="inline-flex h-9 items-center gap-1.5 rounded-[10px] bg-primary-400 px-3 text-xs font-bold text-white disabled:opacity-60">
                <Link2 className="h-3.5 w-3.5" />{link?.status === 'invited' ? '새 초대 링크' : '초대 링크 만들기'}
              </button>
            )}
            {link && (
              <button type="button" disabled={busy} onClick={() => void end()} className="inline-flex h-9 items-center gap-1.5 rounded-[10px] border border-grey-200 px-3 text-xs font-bold text-grey-600 disabled:opacity-60">
                <Unlink className="h-3.5 w-3.5" />{link.status === 'active' ? '연결 끊기' : '초대 취소'}
              </button>
            )}
          </div>
        </div>
        {link?.status === 'invited' && link.invite_expires_at && !inviteUrl && (
          <p className="mt-2 text-xs text-grey-500">초대 링크는 {formatCheckInTime(link.invite_expires_at)}까지 쓸 수 있어요. 링크를 잃어버렸다면 새 초대 링크를 만들어주세요.</p>
        )}
        {inviteUrl && (
          <div className="mt-3 rounded-[10px] bg-primary-50/60 p-3">
            <p className="text-xs text-grey-600">이 링크를 내담자에게 직접 전달하세요. 한 번만 쓸 수 있고 7일 뒤 만료돼요. 이 화면을 벗어나면 다시 볼 수 없어요.</p>
            <div className="mt-2 flex gap-2">
              <input readOnly value={inviteUrl} aria-label="초대 링크" onFocus={(event) => event.target.select()} className="h-9 min-w-0 flex-1 rounded-[8px] border border-grey-200 bg-white px-2 text-xs" />
              <button type="button" onClick={() => void copy()} className="inline-flex h-9 items-center gap-1 rounded-[8px] border border-primary-400 px-3 text-xs font-bold text-primary-400">
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{copied ? '복사됨' : '복사'}
              </button>
            </div>
          </div>
        )}
        <p className="mt-2 text-[11px] leading-4 text-grey-500">내담자 기록은 실시간으로 알림이 가지 않으며, 다음 회기 전 참고용이에요. AI 분석에 쓰이지 않아요.</p>
      </div>

      {message && <p role="alert" className="text-sm text-danger-500">{message}</p>}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-grey-900">기록 {shown.length}개</h3>
        {lastSessionDate && (
          <label className="flex items-center gap-1.5 text-xs text-grey-600">
            <input type="checkbox" className="h-3.5 w-3.5 accent-primary-400" checked={onlySinceSession} onChange={(event) => setOnlySinceSession(event.target.checked)} />
            지난 회기({lastSessionDate}) 이후만
          </label>
        )}
      </div>

      {chart.length > 1 && <MoodChart entries={chart} />}

      {shown.length === 0 ? (
        <p className="rounded-[12px] border border-dashed border-grey-200 px-4 py-8 text-center text-sm text-grey-500">
          {link?.status === 'active' ? '아직 남긴 기록이 없어요.' : '내담자를 초대하면 회기 사이에 남긴 기록을 여기서 볼 수 있어요.'}
        </p>
      ) : (
        <ul className="space-y-2">
          {shown.map((entry) => (
            <li key={entry.id} className="rounded-[12px] border border-grey-200 px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`text-sm font-bold ${entry.mood <= 2 ? 'text-danger-500' : 'text-grey-900'}`}>{entry.mood}점 · {moodLabel(entry.mood)}</span>
                <span className="text-xs text-grey-500">{formatCheckInTime(entry.created_at)}</span>
              </div>
              {entry.emotions.length > 0 && <p className="mt-1 text-xs text-primary-400">{entry.emotions.join(' · ')}</p>}
              {entry.note && <p className="mt-1.5 whitespace-pre-wrap text-sm text-grey-700">{entry.note}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MoodChart({ entries }: { entries: CheckIn[] }) {
  const width = 600
  const height = 120
  const step = entries.length > 1 ? width / (entries.length - 1) : width
  const y = (mood: number) => height - 10 - (mood / 10) * (height - 20)
  const points = entries.map((entry, index) => `${(index * step).toFixed(1)},${y(entry.mood).toFixed(1)}`).join(' ')
  return (
    <figure className="rounded-[12px] border border-grey-200 px-3 py-2" aria-label="기분 점수 흐름">
      <svg viewBox={`-8 0 ${width + 16} ${height}`} className="h-[120px] w-full" role="img" aria-label={`기분 점수 ${entries.map((entry) => entry.mood).join(', ')}`}>
        <line x1="0" x2={width} y1={y(5)} y2={y(5)} className="stroke-grey-200" strokeDasharray="4 4" />
        <polyline points={points} fill="none" className="stroke-primary-400" strokeWidth="2.5" strokeLinejoin="round" />
        {entries.map((entry, index) => <circle key={entry.id} cx={index * step} cy={y(entry.mood)} r="4" className={entry.mood <= 2 ? 'fill-danger-500' : 'fill-primary-400'} />)}
      </svg>
      <figcaption className="text-[11px] text-grey-500">기분 점수(0~10) 흐름 · 오래된 기록부터 · 가운데 점선은 5점</figcaption>
    </figure>
  )
}
