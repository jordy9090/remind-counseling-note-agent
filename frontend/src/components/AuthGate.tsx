import { FormEvent, ReactNode, useEffect, useState } from 'react'
import type { Session } from '@supabase/supabase-js'

import { isAuthConfigured, supabase } from '../lib/supabase'

const SAFETY_WARNING = '현재 테스트 버전입니다. 실제 상담자료 및 개인정보를 입력하지 마세요.'

export default function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(isAuthConfigured)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!supabase) return
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
      setLoading(false)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  if (!isAuthConfigured) {
    return (
      <AuthShell>
        <h1 className="text-2xl font-extrabold text-slate-950">서비스 설정이 필요합니다</h1>
        <p className="mt-3 rounded-lg border border-red-300 bg-red-50 p-4 font-bold text-red-900">{SAFETY_WARNING}</p>
        <p className="mt-4 text-sm leading-6 text-slate-700">
          사용자 인증 환경이 준비되지 않아 상담 입력 화면을 차단했습니다. 운영자가 Preview 환경에
          <code className="mx-1 rounded bg-slate-100 px-1.5 py-0.5">VITE_SUPABASE_URL</code>과
          <code className="mx-1 rounded bg-slate-100 px-1.5 py-0.5">VITE_SUPABASE_PUBLISHABLE_KEY</code>를 설정해야 합니다.
        </p>
      </AuthShell>
    )
  }

  if (loading) {
    return <AuthShell><p className="text-sm text-slate-700">로그인 상태를 확인하고 있습니다.</p></AuthShell>
  }

  if (!session) {
    const submit = async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      if (!supabase) return
      setSubmitting(true)
      setMessage('')
      const action = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null
      const mode = action?.value || 'signin'
      const result = mode === 'signup'
        ? await supabase.auth.signUp({ email, password })
        : await supabase.auth.signInWithPassword({ email, password })
      setSubmitting(false)
      if (result.error) {
        setMessage(result.error.message === 'Invalid login credentials'
          ? '이메일 또는 비밀번호가 올바르지 않습니다.'
          : `인증 요청을 처리하지 못했습니다: ${result.error.message}`)
        return
      }
      if (mode === 'signup' && !result.data.session) {
        setMessage('확인 이메일을 보냈습니다. 이메일 인증 후 로그인해주세요.')
      }
    }

    return (
      <AuthShell>
        <h1 className="text-2xl font-extrabold text-slate-950">상담사 로그인</h1>
        <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-4 font-bold text-amber-950">{SAFETY_WARNING}</p>
        <form className="mt-6 space-y-4" onSubmit={submit}>
          <label className="block text-sm font-bold text-slate-800">
            이메일
            <input className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label className="block text-sm font-bold text-slate-800">
            비밀번호
            <input className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2" type="password" autoComplete="current-password" minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          {message && <p className="rounded-lg bg-slate-100 p-3 text-sm text-slate-800">{message}</p>}
          <div className="grid grid-cols-2 gap-3">
            <button className="rounded-lg bg-blue-700 px-4 py-2.5 font-bold text-white disabled:opacity-60" type="submit" value="signin" disabled={submitting}>로그인</button>
            <button className="rounded-lg border border-slate-300 px-4 py-2.5 font-bold text-slate-800 disabled:opacity-60" type="submit" value="signup" disabled={submitting}>계정 만들기</button>
          </div>
        </form>
      </AuthShell>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-4 border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-950">
        <strong>{SAFETY_WARNING}</strong>
        <button className="shrink-0 rounded border border-amber-400 px-2 py-1 font-bold" type="button" onClick={() => void supabase?.auth.signOut()}>로그아웃</button>
      </div>
      {children}
    </div>
  )
}

function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-100 px-4 py-10">
      <section className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-7 shadow-xl">{children}</section>
    </main>
  )
}
