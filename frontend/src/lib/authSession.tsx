import { createContext, useContext } from 'react'

export interface AuthSessionValue {
  email: string | null
  signOut: () => Promise<void>
  signingOut: boolean
}

const AuthSessionContext = createContext<AuthSessionValue>({
  email: null,
  signOut: async () => {},
  signingOut: false,
})

export const AuthSessionProvider = AuthSessionContext.Provider

/** AuthGate가 제공하는 로그인 사용자 정보. 워크스페이스 사이드바·설정 화면에서 사용한다. */
export function useAuthSession(): AuthSessionValue {
  return useContext(AuthSessionContext)
}

/** 이메일에서 표시용 이름을 만든다 (예: hong.gildong+remind@x.com → hong.gildong). */
export function displayNameFromEmail(email: string | null): string {
  if (!email) return '상담사'
  const local = email.split('@')[0] || ''
  const base = local.split('+')[0] || local
  return base || '상담사'
}
