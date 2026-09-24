import { LogOut } from 'lucide-react'

import { displayNameFromEmail, useAuthSession } from '../../lib/authSession'
import { ClientAvatar, OutlineButton } from '../app-shell/ui'

/** 설정 (데이터 축소판): 계정 정보와 로그아웃만 제공한다. */
export default function SettingsPage() {
  const { email, signOut, signingOut } = useAuthSession()
  return (
    <section aria-label="설정" className="mx-auto w-full max-w-[720px] px-4 py-6 md:px-6 md:py-7">
      <h1 className="text-2xl font-extrabold text-grey-900">설정</h1>
      <div className="rm-card mt-5 p-6">
        <h2 className="text-base font-bold text-grey-900">계정</h2>
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <ClientAvatar size={48} />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold text-grey-900">{displayNameFromEmail(email)}</p>
            <p className="truncate text-sm text-grey-500">{email}</p>
          </div>
          <OutlineButton onClick={() => void signOut()} disabled={signingOut}><LogOut className="h-4 w-4" />로그아웃</OutlineButton>
        </div>
        <p className="mt-5 text-xs leading-5 text-grey-500">비밀번호 변경은 로그아웃 후 로그인 화면의 "비밀번호를 잊으셨나요?"에서 재설정 메일을 받아 진행할 수 있습니다. 상담 기록은 계정별로 분리 저장됩니다.</p>
      </div>
    </section>
  )
}
