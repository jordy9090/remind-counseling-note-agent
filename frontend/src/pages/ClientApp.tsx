import { FormEvent, type ReactNode, useCallback, useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'
import axios from 'axios'
import { Loader2, LogOut, Phone, Trash2 } from 'lucide-react'

import {
  acceptClientInvite,
  checkInErrorMessage,
  createCheckIn,
  deleteCheckIn,
  endMyClientLink,
  getClientMe,
  listMyCheckIns,
} from '../api/client'
import { isAuthConfigured, supabase } from '../lib/supabase'
import {
  CHECK_IN_EMOTIONS,
  CLIENT_CONSENT_VERSION,
  CONSENT_DRAFT_NOTICE,
  CONSENT_ITEMS,
  CRISIS_CONTACTS,
  CRISIS_NOTICE,
  NOTE_MAX_LENGTH,
  formatCheckInTime,
  inviteTokenFrom,
  moodLabel,
  needsCrisisSupport,
  type CheckIn,
  type CheckInEmotion,
  type ClientMe,
} from '../lib/clientCheckIns'

type View = 'loading' | 'consent' | 'no-invite' | 'home' | 'error'

/**
 * Client page (/client): a client joins through the counselor's invite link, consents, and records
 * how they are doing between sessions. Separate from the counselor workspace.
 */
export default function ClientApp() {
  const [session, setSession] = useState<Session | null>(null)
  const [authReady, setAuthReady] = useState(!isAuthConfigured)
  const [invite, setInvite] = useState(() => inviteTokenFrom(window.location.search))

  useEffect(() => { document.title = 'Re:mind 내 마음 기록' }, [])

  useEffect(() => {
    if (!supabase) return
    const { data } = supabase.auth.onAuthStateChange((_event, next) => {
      setSession(next?.user?.is_anonymous ? null : next)
      setAuthReady(true)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  const clearInvite = () => {
    setInvite('')
    window.history.replaceState(null, '', '/client')
  }

  return (
    <main className="min-h-screen bg-[#F8FAFC] px-4 py-6 text-grey-900">
      <div className="mx-auto w-full max-w-[480px]">
        <header className="mb-5 flex items-center justify-between">
          <p className="text-lg font-bold text-primary-400">Re:mind <span className="text-sm font-semibold text-grey-500">내 마음 기록</span></p>
          {session && (
            <button type="button" onClick={() => void supabase?.auth.signOut()} className="inline-flex items-center gap-1 text-xs font-semibold text-grey-500 hover:text-grey-800">
              <LogOut className="h-3.5 w-3.5" />로그아웃
            </button>
          )}
        </header>
        <CrisisCard />
        {!isAuthConfigured ? <Card><p className="text-sm">서비스 연결을 준비하고 있어요.</p></Card>
          : !authReady ? <Card><Busy text="로그인 상태를 확인하고 있어요" /></Card>
          : !session ? <ClientAuth hasInvite={Boolean(invite)} />
          : <ClientHome key={session.user.id} invite={invite} onInviteUsed={clearInvite} />}
      </div>
    </main>
  )
}

function ClientHome({ invite, onInviteUsed }: { invite: string; onInviteUsed: () => void }) {
  const [view, setView] = useState<View>('loading')
  const [me, setMe] = useState<ClientMe | null>(null)
  const [entries, setEntries] = useState<CheckIn[]>([])
  const [message, setMessage] = useState('')

  const load = useCallback(async () => {
    setMessage('')
    try {
      const current = await getClientMe()
      setMe(current)
      setEntries(await listMyCheckIns())
      setView('home')
    } catch (error) {
      // 403: this account has not joined through an invite yet.
      if (axios.isAxiosError(error) && error.response?.status === 403) setView(invite ? 'consent' : 'no-invite')
      else { setMessage(checkInErrorMessage(error, '기록을 불러오지 못했어요. 잠시 후 다시 시도해주세요.')); setView('error') }
    }
  }, [invite])

  useEffect(() => { void load() }, [load])

  if (view === 'loading') return <Card><Busy text="기록을 불러오고 있어요" /></Card>
  if (view === 'error') return <Card><p role="alert" className="text-sm text-danger-500">{message}</p></Card>
  if (view === 'no-invite') {
    return <Card><h1 className="text-base font-bold">상담사의 초대 링크가 필요해요</h1>
      <p className="mt-2 text-sm leading-6 text-grey-600">상담사에게 받은 초대 링크를 열면 기록을 시작할 수 있어요. 상담사 계정으로는 이 기능을 이용할 수 없어요.</p></Card>
  }
  if (view === 'consent') return <Consent invite={invite} onJoined={() => { onInviteUsed(); void load() }} />
  return <Journal me={me} entries={entries} setEntries={setEntries} onChanged={load} />
}

function Consent({ invite, onJoined }: { invite: string; onJoined: () => void }) {
  const [agreed, setAgreed] = useState(false)
  const [adult, setAdult] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const join = async () => {
    setBusy(true); setMessage('')
    try {
      await acceptClientInvite(invite, CLIENT_CONSENT_VERSION)
      onJoined()
    } catch (error) {
      setMessage(checkInErrorMessage(error, '연결하지 못했어요. 잠시 후 다시 시도해주세요.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h1 className="text-base font-bold">기록을 시작하기 전에 확인해주세요</h1>
      <p className="mt-1 rounded-[8px] bg-amber-50 px-3 py-2 text-xs text-amber-800">{CONSENT_DRAFT_NOTICE}</p>
      <ul className="mt-4 space-y-2.5 text-sm leading-6 text-grey-700">
        {CONSENT_ITEMS.map((item) => <li key={item} className="flex gap-2"><span aria-hidden className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-400" />{item}</li>)}
      </ul>
      <label className="mt-5 flex items-start gap-2.5 text-sm font-semibold">
        <input type="checkbox" className="mt-1 h-4 w-4 accent-primary-400" checked={adult} onChange={(event) => setAdult(event.target.checked)} />
        만 19세 이상이에요.
      </label>
      <label className="mt-2 flex items-start gap-2.5 text-sm font-semibold">
        <input type="checkbox" className="mt-1 h-4 w-4 accent-primary-400" checked={agreed} onChange={(event) => setAgreed(event.target.checked)} />
        위 내용을 확인했고, 상담사가 내 기록을 보는 데 동의해요.
      </label>
      {message && <p role="alert" className="mt-3 text-sm text-danger-500">{message}</p>}
      <button type="button" disabled={!agreed || !adult || busy} onClick={() => void join()}
        className="mt-5 flex h-12 w-full items-center justify-center gap-2 rounded-[12px] bg-primary-400 font-bold text-white disabled:bg-grey-200 disabled:text-grey-500">
        {busy && <Loader2 className="h-4 w-4 animate-spin" />}동의하고 시작하기
      </button>
    </Card>
  )
}

function Journal({ me, entries, setEntries, onChanged }: {
  me: ClientMe | null
  entries: CheckIn[]
  setEntries: (entries: CheckIn[]) => void
  onChanged: () => Promise<void>
}) {
  const [mood, setMood] = useState<number | null>(null)
  const [emotions, setEmotions] = useState<CheckInEmotion[]>([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [support, setSupport] = useState(false)
  const linked = Boolean(me?.linked)

  const toggle = (emotion: CheckInEmotion) =>
    setEmotions((current) => current.includes(emotion) ? current.filter((value) => value !== emotion) : [...current, emotion])

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (mood === null) return setMessage('지금 기분을 0~10 중에서 골라주세요.')
    setBusy(true); setMessage('')
    try {
      const created = await createCheckIn({ mood, emotions, note })
      setEntries([created, ...entries])
      setSupport(needsCrisisSupport(mood, note))
      setMood(null); setEmotions([]); setNote('')
      setMessage('기록했어요.')
    } catch (error) {
      setMessage(checkInErrorMessage(error, '기록을 저장하지 못했어요. 잠시 후 다시 시도해주세요.'))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (entry: CheckIn) => {
    if (!window.confirm('이 기록을 지울까요? 지운 기록은 상담사도 볼 수 없고 되돌릴 수 없어요.')) return
    try {
      await deleteCheckIn(entry.id)
      setEntries(entries.filter((item) => item.id !== entry.id))
    } catch (error) {
      setMessage(checkInErrorMessage(error, '기록을 지우지 못했어요.'))
    }
  }

  const endLink = async () => {
    if (!window.confirm('상담사와의 연결을 끊을까요? 새 기록을 남길 수 없게 되고, 이미 남긴 기록은 지우기 전까지 상담사가 볼 수 있어요.')) return
    try {
      await endMyClientLink()
      await onChanged()
    } catch (error) {
      setMessage(checkInErrorMessage(error, '연결을 끊지 못했어요.'))
    }
  }

  return (
    <>
      {support && <CrisisCard emphasized onClose={() => setSupport(false)} />}
      {linked ? (
        <Card>
          <form onSubmit={save}>
            <h1 className="text-base font-bold">지금 기분은 어떤가요?</h1>
            <div className="mt-3 grid grid-cols-11 gap-1" role="radiogroup" aria-label="지금 기분 0~10">
              {Array.from({ length: 11 }, (_, value) => (
                <button key={value} type="button" role="radio" aria-checked={mood === value} onClick={() => setMood(value)}
                  className={`h-10 rounded-[8px] text-sm font-bold ${mood === value ? 'bg-primary-400 text-white' : 'bg-grey-100 text-grey-700'}`}>{value}</button>
              ))}
            </div>
            <p className="mt-1.5 flex justify-between text-[11px] text-grey-500"><span>매우 힘듦</span>{mood !== null && <span className="font-bold text-primary-400">{moodLabel(mood)}</span>}<span>매우 좋음</span></p>
            <p className="mt-4 text-sm font-bold">어떤 감정이 있나요? <span className="font-normal text-grey-500">(선택)</span></p>
            <div className="mt-2 flex flex-wrap gap-2">
              {CHECK_IN_EMOTIONS.map((emotion) => (
                <button key={emotion} type="button" aria-pressed={emotions.includes(emotion)} onClick={() => toggle(emotion)}
                  className={`h-9 rounded-full border px-3 text-sm ${emotions.includes(emotion) ? 'border-primary-400 bg-primary-50 font-bold text-primary-400' : 'border-grey-200 bg-white text-grey-700'}`}>{emotion}</button>
              ))}
            </div>
            <label className="mt-4 block text-sm font-bold">
              남기고 싶은 말 <span className="font-normal text-grey-500">(선택)</span>
              <textarea value={note} maxLength={NOTE_MAX_LENGTH} onChange={(event) => setNote(event.target.value)} rows={3}
                placeholder="예: 회의 전에 숨이 막혔어요."
                className="mt-2 w-full rounded-[10px] border border-grey-200 bg-white px-3 py-2 text-sm font-normal outline-none focus:border-primary-400" />
            </label>
            {message && <p role="status" className="mt-2 text-sm text-grey-700">{message}</p>}
            <button type="submit" disabled={busy} className="mt-3 flex h-12 w-full items-center justify-center gap-2 rounded-[12px] bg-primary-400 font-bold text-white disabled:opacity-60">
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}기록하기
            </button>
          </form>
        </Card>
      ) : (
        <Card>
          <h1 className="text-base font-bold">상담사와의 연결이 끝났어요</h1>
          <p className="mt-2 text-sm leading-6 text-grey-600">새 기록은 남길 수 없어요. 이전 기록은 아래에서 확인하고 지울 수 있어요.</p>
          {message && <p role="status" className="mt-2 text-sm text-grey-700">{message}</p>}
        </Card>
      )}

      <section aria-label="내 기록" className="mt-4">
        <h2 className="mb-2 text-sm font-bold text-grey-700">내 기록 {entries.length > 0 && `(${entries.length})`}</h2>
        {entries.length === 0 ? <p className="rounded-[12px] border border-dashed border-grey-200 px-4 py-6 text-center text-sm text-grey-500">아직 남긴 기록이 없어요.</p> : (
          <ul className="space-y-2">
            {entries.map((entry) => (
              <li key={entry.id} className="rounded-[12px] border border-grey-200 bg-white px-4 py-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-bold">{entry.mood}점 · {moodLabel(entry.mood)}</span>
                  <span className="text-xs text-grey-500">{formatCheckInTime(entry.created_at)}</span>
                  <button type="button" onClick={() => void remove(entry)} aria-label="기록 지우기" className="ml-auto text-grey-400 hover:text-danger-500"><Trash2 className="h-4 w-4" /></button>
                </div>
                {entry.emotions.length > 0 && <p className="mt-1 text-xs text-primary-400">{entry.emotions.join(' · ')}</p>}
                {entry.note && <p className="mt-1.5 whitespace-pre-wrap text-sm text-grey-700">{entry.note}</p>}
              </li>
            ))}
          </ul>
        )}
      </section>
      {linked && <button type="button" onClick={() => void endLink()} className="mt-6 w-full text-center text-xs font-semibold text-grey-500 underline">상담사와의 연결 끊기</button>}
    </>
  )
}

function ClientAuth({ hasInvite }: { hasInvite: boolean }) {
  const [mode, setMode] = useState<'signup' | 'signin' | 'verify'>(hasInvite ? 'signup' : 'signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!supabase) return
    setBusy(true); setMessage('')
    // The confirmation link returns here with the invite still in the URL.
    const redirect = window.location.href
    const { data, error } = mode === 'signup'
      ? await supabase.auth.signUp({ email, password, options: { emailRedirectTo: redirect } })
      : await supabase.auth.signInWithPassword({ email, password })
    setBusy(false)
    if (error) {
      const text = error.message.toLowerCase()
      return setMessage(text.includes('invalid login') ? '이메일 또는 비밀번호를 확인해주세요.'
        : text.includes('not confirmed') ? '이메일 인증을 먼저 완료해주세요.'
        : text.includes('password') ? '비밀번호는 8자 이상으로 입력해주세요.'
        : '요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.')
    }
    if (mode === 'signup' && data.user && (data.user.identities?.length ?? 0) === 0) return setMessage('이미 가입된 이메일이에요. 로그인해주세요.')
    if (mode === 'signup' && !data.session) setMode('verify')
  }

  if (mode === 'verify') {
    return <Card><h1 className="text-base font-bold">이메일을 확인해주세요</h1>
      <p className="mt-2 text-sm leading-6 text-grey-600">{email}로 보낸 인증 메일의 링크를 누르면 이어서 진행돼요. 메일이 없으면 스팸함도 확인해주세요.</p></Card>
  }
  return (
    <Card>
      <h1 className="text-base font-bold">{mode === 'signup' ? '내 마음 기록 시작하기' : '로그인'}</h1>
      <p className="mt-1 text-sm text-grey-600">{hasInvite ? '상담사의 초대로 오셨어요. 이메일로 가입하거나 로그인해주세요.' : '상담사에게 받은 초대 링크로 처음 가입할 수 있어요.'}</p>
      <form onSubmit={submit} className="mt-4 space-y-3">
        <input type="email" required autoComplete="email" placeholder="이메일" value={email} onChange={(event) => setEmail(event.target.value)}
          className="h-12 w-full rounded-[10px] border border-grey-200 bg-white px-3 text-sm outline-none focus:border-primary-400" />
        <input type="password" required minLength={8} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} placeholder="비밀번호 (8자 이상)"
          value={password} onChange={(event) => setPassword(event.target.value)}
          className="h-12 w-full rounded-[10px] border border-grey-200 bg-white px-3 text-sm outline-none focus:border-primary-400" />
        {message && <p role="alert" className="text-sm text-danger-500">{message}</p>}
        <button type="submit" disabled={busy} className="flex h-12 w-full items-center justify-center gap-2 rounded-[12px] bg-primary-400 font-bold text-white disabled:opacity-60">
          {busy && <Loader2 className="h-4 w-4 animate-spin" />}{mode === 'signup' ? '가입하기' : '로그인'}
        </button>
      </form>
      <button type="button" onClick={() => { setMode(mode === 'signup' ? 'signin' : 'signup'); setMessage('') }} className="mt-3 w-full text-center text-sm font-semibold text-primary-400">
        {mode === 'signup' ? '이미 가입했어요. 로그인하기' : '처음이에요. 가입하기'}
      </button>
    </Card>
  )
}

function CrisisCard({ emphasized = false, onClose }: { emphasized?: boolean; onClose?: () => void }) {
  return (
    <aside role={emphasized ? 'alert' : 'note'} aria-label="위급할 때 연락처"
      className={`mb-4 rounded-[14px] px-4 py-3 ${emphasized ? 'border border-danger-500 bg-danger-50' : 'bg-white ring-1 ring-grey-200'}`}>
      <p className={`text-xs leading-5 ${emphasized ? 'font-bold text-danger-500' : 'text-grey-600'}`}>
        {emphasized ? '많이 힘드신가요? 혼자 견디지 말고 지금 바로 연락해주세요. 상담사는 이 기록을 실시간으로 보지 않아요.' : CRISIS_NOTICE}
      </p>
      <ul className="mt-2 flex flex-wrap gap-2">
        {CRISIS_CONTACTS.map((contact) => (
          <li key={contact.number}>
            <a href={`tel:${contact.number.split(' ')[0].replace(/-/g, '')}`} className="inline-flex h-8 items-center gap-1 rounded-full bg-grey-100 px-3 text-xs font-bold text-grey-800">
              <Phone className="h-3 w-3" />{contact.label} {contact.number}
            </a>
          </li>
        ))}
      </ul>
      {onClose && <button type="button" onClick={onClose} className="mt-2 text-xs font-semibold text-grey-500 underline">닫기</button>}
    </aside>
  )
}

function Card({ children }: { children: ReactNode }) {
  return <section className="rounded-[16px] bg-white p-5 shadow-sm ring-1 ring-grey-200">{children}</section>
}

function Busy({ text }: { text: string }) {
  return <p className="flex items-center gap-2 text-sm text-grey-600"><Loader2 className="h-4 w-4 animate-spin" />{text}</p>
}
