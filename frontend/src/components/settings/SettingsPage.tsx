import { useEffect, useState } from 'react'
import { Loader2, LogOut } from 'lucide-react'

import { displayNameFromEmail, useAuthSession } from '../../lib/authSession'
import { readStoreOriginalInput, writeStoreOriginalInput } from '../../lib/storagePreference'
import { ClientAvatar, OutlineButton } from '../app-shell/ui'

/** What the service actually does with counselor data. Keep each line true to the code it describes. */
export const DATA_HANDLING_NOTICES = [
  { title: '음성 파일', text: '축어록을 만든 뒤 서버에서 바로 삭제해요. 음성 원본은 저장하지 않아요.' },
  { title: '문서 파일', text: 'PDF·DOCX·TXT 파일은 글자만 추출하고 파일은 저장하지 않아요.' },
  { title: '저장 전 비식별화', text: '회기 기록·임시저장·내담자 정보를 저장할 때 이름은 가운데 글자를 가리고(예: 홍길동 → 홍O동), 직업은 큰 분류로 바꿔요(예: 초등학교 교사 → 교육자). 이름과 직업을 찾을 때 입력 원문이 AI(OpenAI)에 한 번 전달돼요.' },
  { title: 'AI 요약', text: '요약을 만들 때는 위처럼 가린 내용에서 연락처·주소 등 개인정보로 보이는 내용을 한 번 더 가린 뒤 AI(OpenAI)에 보내요.' },
  { title: '입력 원문', text: '아래 원문 저장 설정에 따라 회기 기록에 저장해요. 회기 상세의 첨부 자료에서 "원문 삭제"로 언제든 지울 수 있어요.' },
  { title: '임시저장', text: '임시저장을 누르면 작업 중인 입력 내용이 그대로 저장돼요.' },
  { title: '간편 요약', text: '로그인하지 않고 쓴 간편 요약은 저장하지 않아요. "로그인 후 저장하기"를 누르면 요약 결과를 이 브라우저에 최대 30분 보관했다가, 로그인한 뒤 고른 내담자의 다음 회기로 저장해요. 로그인 상태의 요약은 "이전 요약한 기록"에 자동 저장되고, "내담자에 저장하기"로 내담자의 회기로 저장할 수 있어요. 입력한 내용은 저장하지 않아요.' },
  { title: '내담자 연락처', text: '내담자의 전화번호와 이메일은 받지 않아요.' },
]

/** 설정: 계정, 원문 저장 설정, 데이터 처리 안내. */
export default function SettingsPage() {
  const { email, signOut, signingOut } = useAuthSession()
  const [storeOriginal, setStoreOriginal] = useState<boolean | null>(null)
  const [savingPreference, setSavingPreference] = useState(false)
  const [preferenceError, setPreferenceError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    readStoreOriginalInput()
      .then((value) => { if (!cancelled) setStoreOriginal(value) })
      .catch(() => { if (!cancelled) setPreferenceError('원문 저장 설정을 불러오지 못했어요. 새로고침 후 다시 시도해주세요.') })
    return () => { cancelled = true }
  }, [])

  const toggleStoreOriginal = async () => {
    if (storeOriginal === null || savingPreference) return
    const next = !storeOriginal
    setSavingPreference(true)
    setPreferenceError(null)
    try {
      await writeStoreOriginalInput(next)
      setStoreOriginal(next)
    } catch {
      setPreferenceError('설정을 저장하지 못했어요. 잠시 후 다시 시도해주세요.')
    } finally {
      setSavingPreference(false)
    }
  }

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

      <div className="rm-card mt-5 p-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 id="store-original-label" className="text-base font-bold text-grey-900">원문 저장</h2>
            <p className="mt-1.5 text-sm leading-6 text-grey-600">
              켜 두면 AI 요약을 만들 때 입력한 메모·축어록 원문을 회기 기록에 함께 저장해요. 끄면 앞으로 만드는 회기에는 원문을 저장하지 않고, 개인정보를 가린 사본만 저장해요.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={storeOriginal === true}
            aria-labelledby="store-original-label"
            disabled={storeOriginal === null || savingPreference}
            onClick={() => void toggleStoreOriginal()}
            className={`relative mt-1 inline-flex h-7 w-12 shrink-0 items-center rounded-full transition disabled:opacity-60 ${storeOriginal ? 'bg-primary-400' : 'bg-grey-200'}`}
          >
            <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${storeOriginal ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        <p className="mt-3 text-xs leading-5 text-grey-500">
          {savingPreference && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
          {storeOriginal === null && !preferenceError ? '설정을 불러오는 중이에요.' : storeOriginal ? '지금은 원문을 저장해요.' : '지금은 원문을 저장하지 않아요.'}
          {' '}이미 저장된 원문은 바뀌지 않아요. 회기 상세의 첨부 자료에서 "원문 삭제"로 지울 수 있어요. 임시저장한 작업에는 입력 내용이 그대로 남아요.
        </p>
        {preferenceError && <p role="alert" className="mt-2 text-xs text-danger-500">{preferenceError}</p>}
      </div>

      <div className="rm-card mt-5 p-6">
        <h2 className="text-base font-bold text-grey-900">데이터 처리 안내</h2>
        <dl className="mt-4 space-y-3">
          {DATA_HANDLING_NOTICES.map((notice) => (
            <div key={notice.title} className="grid gap-1 sm:grid-cols-[96px_minmax(0,1fr)]">
              <dt className="text-sm font-bold text-grey-800">{notice.title}</dt>
              <dd className="text-sm leading-6 text-grey-600">{notice.text}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  )
}
