import { FormEvent, ReactNode, useEffect, useState } from 'react'
import type { Provider, Session } from '@supabase/supabase-js'
import { ArrowLeft, Loader2, Mail } from 'lucide-react'

import { getAvailableOAuthProviders, isAuthConfigured, supabase, type AvailableOAuthProviders } from '../lib/supabase'
import LandingPage from '../pages/LandingPage'

type AuthMode = 'signin' | 'signup' | 'reset' | 'recovery'
const PRIVACY_NOTE = '상담 기록은 계정별로 분리하여 관리됩니다. 민감정보는 필요한 범위에서 비식별화해 입력해주세요.'

function authErrorMessage(message: string) {
  const normalized = message.toLowerCase()
  if (normalized.includes('invalid login credentials')) return '이메일 또는 비밀번호를 확인해주세요.'
  if (normalized.includes('email not confirmed')) return '이메일 인증을 먼저 완료해주세요.'
  if (normalized.includes('user already registered')) return '이미 가입된 이메일입니다.'
  if (normalized.includes('password should be')) return '비밀번호는 8자 이상으로 입력해주세요.'
  if (normalized.includes('rate limit')) return '요청이 많습니다. 잠시 후 다시 시도해주세요.'
  return '인증 요청을 완료하지 못했습니다. 잠시 후 다시 시도해주세요.'
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(isAuthConfigured)
  const [mode, setMode] = useState<AuthMode>('signin')
  const [authOpen, setAuthOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [providers, setProviders] = useState<AvailableOAuthProviders>({ google: false, kakao: false })

  useEffect(() => {
    if (!supabase) return
    void Promise.all([supabase.auth.getSession(), getAvailableOAuthProviders()]).then(([auth, available]) => {
      setSession(auth.data.session)
      setProviders(available)
      setLoading(false)
    })
    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      setSession(nextSession)
      if (event === 'PASSWORD_RECOVERY') setMode('recovery')
      setLoading(false)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  const startAnonymousWorkspace = async () => {
    if (!supabase || submitting) return
    setSubmitting(true)
    setMessage('')
    const { error } = await supabase.auth.signInAnonymously()
    if (error) {
      setSubmitting(false)
      setMessage('워크스페이스를 열지 못했습니다. 잠시 후 다시 시도해주세요.')
    }
  }

  if (!isAuthConfigured) return <AuthShell><Brand /><AuthHeading title="서비스 연결을 준비하고 있습니다" description="인증 설정을 확인한 뒤 다시 시도해주세요." /></AuthShell>
  if (loading) return <AuthShell><Brand /><Status text="로그인 상태를 확인하고 있습니다" /></AuthShell>

  if (session && mode === 'recovery') {
    return <AuthShell><Brand /><AuthHeading title="새 비밀번호 설정" description="앞으로 사용할 비밀번호를 입력해주세요." />
      <form className="mt-8 space-y-5" onSubmit={async (event) => {
        event.preventDefault()
        if (!supabase) return
        setSubmitting(true); setMessage('')
        const { error } = await supabase.auth.updateUser({ password })
        setSubmitting(false)
        if (error) return setMessage(authErrorMessage(error.message))
        setPassword(''); setMessage('비밀번호가 변경되었습니다.'); setMode('signin')
      }}>
        <PasswordField value={password} onChange={setPassword} autoComplete="new-password" />
        <PrimaryButton loading={submitting}>비밀번호 변경</PrimaryButton>
        {message && <Feedback message={message} />}
      </form>
    </AuthShell>
  }

  if (!session) {
    if (!authOpen) {
      return <LandingPage
        onStart={() => void startAnonymousWorkspace()}
        startError={message}
        starting={submitting}
      />
    }

    const oauthEnabled = providers.google || providers.kakao
    const startOAuth = async (provider: Provider) => {
      if (!supabase) return
      setSubmitting(true); setMessage('')
      const { error } = await supabase.auth.signInWithOAuth({ provider, options: { redirectTo: window.location.origin } })
      if (error) { setSubmitting(false); setMessage(authErrorMessage(error.message)) }
    }
    const submit = async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      if (!supabase) return
      setSubmitting(true); setMessage('')
      if (mode === 'reset') {
        const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: window.location.origin })
        setSubmitting(false)
        setMessage(error ? authErrorMessage(error.message) : '비밀번호 재설정 이메일을 보냈습니다.')
        return
      }
      const result = mode === 'signup'
        ? await supabase.auth.signUp({ email, password, options: { emailRedirectTo: window.location.origin } })
        : await supabase.auth.signInWithPassword({ email, password })
      setSubmitting(false)
      if (result.error) return setMessage(authErrorMessage(result.error.message))
      if (mode === 'signup' && !result.data.session) setMessage('인증 이메일을 보냈습니다. 메일의 확인 링크를 눌러주세요.')
    }

    const heading = mode === 'reset' ? '비밀번호 찾기' : mode === 'signup' ? '무료로 시작하기' : '로그인'
    const description = mode === 'reset'
      ? '가입한 이메일로 비밀번호 재설정 링크를 보내드립니다.'
      : mode === 'signup'
        ? 'Re:mind 계정을 만들고 상담 기록 워크스페이스를 시작하세요.'
        : 'Re:mind 계정으로 상담 기록 워크스페이스에 들어가세요.'

    return <AuthShell>
      <button className="mb-8 inline-flex items-center gap-2 text-sm font-semibold text-slate-500 transition hover:text-slate-900" type="button" onClick={() => { setAuthOpen(false); setMessage('') }}><ArrowLeft size={17} />처음으로</button>
      <Brand />
      <AuthHeading title={heading} description={description} />
      {mode !== 'reset' && oauthEnabled && <div className="mt-8 space-y-3">
        {providers.google && <button className="flex w-full items-center justify-center gap-3 rounded-xl border border-slate-300 bg-white px-4 py-3.5 font-bold text-slate-800 shadow-sm transition hover:bg-slate-50 disabled:opacity-60" type="button" disabled={submitting} onClick={() => void startOAuth('google')}><GoogleMark /> Google로 계속하기</button>}
        {providers.kakao && <button className="w-full rounded-xl bg-[#FEE500] px-4 py-3.5 font-bold text-[#191919] transition hover:brightness-95 disabled:opacity-60" type="button" disabled={submitting} onClick={() => void startOAuth('kakao')}>Kakao로 계속하기</button>}
      </div>}
      {mode !== 'reset' && oauthEnabled && <div className="my-7 flex items-center gap-4 text-xs font-semibold text-slate-400"><span className="h-px flex-1 bg-slate-200" />이메일로 계속<span className="h-px flex-1 bg-slate-200" /></div>}
      <form className={`${oauthEnabled && mode !== 'reset' ? '' : 'mt-8'} space-y-5`} onSubmit={submit}>
        <EmailField value={email} onChange={setEmail} />
        {mode !== 'reset' && <PasswordField value={password} onChange={setPassword} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} />}
        {message && <Feedback message={message} />}
        <PrimaryButton loading={submitting}>{mode === 'signup' ? '계정 만들기' : mode === 'reset' ? '재설정 이메일 받기' : '이메일로 로그인'}</PrimaryButton>
      </form>
      <div className="mt-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-2 text-sm">
        {mode === 'signin' && <button className="font-semibold text-slate-600 hover:text-blue-700" type="button" onClick={() => { setMode('reset'); setMessage('') }}>비밀번호를 잊으셨나요?</button>}
        {mode !== 'signin' && <button className="font-bold text-blue-700 hover:text-blue-800" type="button" onClick={() => { setMode('signin'); setMessage('') }}>로그인으로 돌아가기</button>}
      </div>
      <p className="mt-8 border-t border-slate-100 pt-5 text-center text-xs leading-5 text-slate-500">{PRIVACY_NOTE}</p>
    </AuthShell>
  }

  return <div className="min-h-screen bg-slate-50">
    <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur"><div className="mx-auto flex max-w-7xl items-center px-4 py-3 sm:px-6 lg:px-8"><Brand compact /></div></header>{children}
  </div>
}

function Brand({ compact = false }: { compact?: boolean }) { return <img src="/remind-logo.png" alt="Re:mind" className="object-contain" style={{ height: compact ? 24 : 30, width: compact ? 120 : 150 }} /> }
function AuthHeading({ title, description }: { title: string; description: string }) { return <div className="mt-10"><h1 className="text-[1.75rem] font-extrabold leading-tight tracking-[-0.025em] text-slate-950">{title}</h1><p className="mt-3 text-sm leading-6 text-slate-500">{description}</p></div> }
function EmailField({ value, onChange }: { value: string; onChange: (value: string) => void }) { return <label className="block text-sm font-bold text-slate-800">이메일<div className="relative mt-2"><Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" size={18} /><input className="w-full rounded-xl border border-slate-300 bg-white py-3 pl-11 pr-3 outline-none transition focus:border-blue-600 focus:ring-4 focus:ring-blue-100" type="email" autoComplete="email" value={value} onChange={(event) => onChange(event.target.value)} placeholder="name@example.com" required /></div></label> }
function PasswordField({ value, onChange, autoComplete }: { value: string; onChange: (value: string) => void; autoComplete: string }) { return <label className="block text-sm font-bold text-slate-800">비밀번호<input className="mt-2 w-full rounded-xl border border-slate-300 bg-white px-3.5 py-3 outline-none transition focus:border-blue-600 focus:ring-4 focus:ring-blue-100" type="password" autoComplete={autoComplete} minLength={8} value={value} onChange={(event) => onChange(event.target.value)} placeholder="8자 이상 입력" required /></label> }
function PrimaryButton({ children, loading }: { children: ReactNode; loading: boolean }) { return <button className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-700 px-4 py-3.5 font-bold text-white shadow-sm transition hover:bg-blue-800 disabled:cursor-wait disabled:opacity-60" type="submit" disabled={loading}>{loading && <Loader2 className="animate-spin" size={18} />}{loading ? '처리하고 있습니다' : children}</button> }
function Feedback({ message }: { message: string }) { return <p className="rounded-xl bg-slate-100 px-4 py-3 text-sm leading-5 text-slate-700" role="status">{message}</p> }
function Status({ text }: { text: string }) { return <div className="mt-10 flex items-center gap-3 text-sm font-semibold text-slate-600"><Loader2 className="animate-spin text-blue-700" size={20} />{text}</div> }
function GoogleMark() { return <span className="text-lg font-black text-[#4285F4]" aria-hidden="true">G</span> }
function AuthShell({ children }: { children: ReactNode }) { return <main className="flex min-h-screen items-center justify-center bg-[#f6f9ff] px-5 py-10"><section className="w-full max-w-[420px] rounded-2xl border border-slate-200 bg-white p-7 shadow-[0_18px_50px_rgba(45,75,130,0.10)] sm:p-9">{children}</section></main> }
