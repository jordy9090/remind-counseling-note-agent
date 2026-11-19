import { useEffect, useState } from 'react'
import { Loader2, LogOut } from 'lucide-react'

import { displayNameFromEmail, useAuthSession } from '../../lib/authSession'
import { writeStoreOriginalInput } from '../../lib/storagePreference'
import { getNoteStoragePolicy, type NoteStoragePolicy } from '../../api/client'
import { ClientAvatar, OutlineButton } from '../app-shell/ui'

/** What the service actually does with counselor data. Keep each line true to the code it describes. */
export const DATA_HANDLING_NOTICES = [
  { title: '바우처 삭제·복구', text: '바우처를 직접 지우거나 원본 회기와 함께 지우면 바우처 사본을 7일 동안 복구할 수 있어요. 삭제자·삭제 경로·복구 여부는 90일 동안 확인할 수 있어요. 내담자나 계정을 삭제하면 해당 사본과 삭제 기록도 함께 지워져요.' },
  { title: '음성 파일', text: '동의 후 원본 음성과 짧은 화자 참조를 네이버클라우드 CLOVA Speech로 보내 축어록을 만들어요. Re:mind 서버 임시 파일은 성공·실패 후 삭제하며, 제공업체의 보관 정책은 별도로 적용돼요.' },
  { title: '문서 파일', text: 'PDF·DOCX·TXT 파일은 글자만 추출하고 파일은 저장하지 않아요.' },
  { title: '문서 비식별화', text: '상담사가 원문 전달을 승인하면 설정된 식별정보 탐지 서버에서 이름·기관·연락처 등 가릴 항목을 찾아 표시해요. 탐지가 끝나면 놓친 항목을 직접 가리고, 요약에 사용할 내용을 다시 확인해주세요.' },
  { title: 'AI 요약', text: '간편 요약과 회기 요약은 상담사가 확인한 내용을 OpenAI에 보내 만들어요. 식별정보를 확인할 수 없으면 요약을 중단해요.' },
  { title: '입력 원문', text: '회기 기록의 원문 보관 여부는 아래 표시된 현재 저장 정책을 따라요. 이미 저장된 원문은 회기 상세의 첨부 자료에서 "원문 삭제"로 지울 수 있어요.' },
  { title: '임시저장', text: '임시저장을 누르면 작업 중인 입력 내용이 그대로 저장돼요.' },
  { title: '간편 요약', text: '로그인 후 이용할 수 있어요. 확인한 요약과 가명 처리된 근거 일부는 "이전 요약한 기록"에 자동 저장되고, "내담자에 저장하기"로 내담자의 회기로 저장할 수 있어요. 입력 전문은 간편 요약 기록에 저장하지 않아요.' },
  { title: '내담자 연락처', text: '내담자의 전화번호와 이메일은 받지 않아요.' },
  { title: '내담자 정보', text: '내담자 관리 화면의 이름·직업 등 프로필은 입력한 그대로 보관해요. 비식별화는 문서에만 적용돼요.' },
]

/** 설정: 계정, 원문 저장 설정, 데이터 처리 안내. */
export default function SettingsPage() {
  const { email, userId, signOut, signingOut } = useAuthSession()
  const [storeOriginal, setStoreOriginal] = useState<boolean | null>(null)
  const [policy, setPolicy] = useState<NoteStoragePolicy | null>(null)
  const [savingPreference, setSavingPreference] = useState(false)
  const [preferenceError, setPreferenceError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setPolicy(null)
    setPreferenceError(null)
    getNoteStoragePolicy({ ownerId: userId })
      .then((value) => { if (!cancelled) { setPolicy(value); setStoreOriginal(value.account_store_original_input) } })
      .catch(() => { if (!cancelled) setPreferenceError('원문 저장 설정을 불러오지 못했어요. 새로고침 후 다시 시도해주세요.') })
    return () => { cancelled = true }
  }, [userId])

  const toggleStoreOriginal = async () => {
    if (storeOriginal === null || savingPreference || !policy?.save_original_input || !policy.persistence_enabled) return
    const next = !storeOriginal
    setSavingPreference(true)
    setPreferenceError(null)
    try {
      await writeStoreOriginalInput(next)
      setStoreOriginal(next)
      setPolicy(await getNoteStoragePolicy({ ownerId: userId }))
    } catch {
      setPolicy(null)
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
              서버가 원문 보관을 허용할 때 이 설정으로 새 회기 기록의 원문 보관 여부를 선택할 수 있어요. 실제 적용 여부는 현재 저장 정책에 표시됩니다.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={policy?.generated_note_raw_input_mode === 'original'}
            aria-labelledby="store-original-label"
            disabled={!policy?.save_original_input || !policy.persistence_enabled || storeOriginal === null || savingPreference}
            onClick={() => void toggleStoreOriginal()}
            className={`relative mt-1 inline-flex h-7 w-12 shrink-0 items-center rounded-full transition disabled:opacity-60 ${policy?.generated_note_raw_input_mode === 'original' ? 'bg-primary-400' : 'bg-grey-200'}`}
          >
            <span className={`inline-block h-5 w-5 rounded-full bg-white shadow transition ${policy?.generated_note_raw_input_mode === 'original' ? 'translate-x-6' : 'translate-x-1'}`} />
          </button>
        </div>
        <p className="mt-3 text-xs leading-5 text-grey-500">
          {savingPreference && <Loader2 className="mr-1 inline h-3.5 w-3.5 animate-spin" />}
          {!policy ? (preferenceError ? '현재 저장 정책을 확인하지 못했어요.' : '현재 저장 정책을 불러오는 중이에요.')
            : policy.generated_note_raw_input_mode === 'original' ? '현재 새 회기 기록에 원문을 저장해요.'
              : policy.generated_note_raw_input_mode === 'masked' ? '현재 새 회기 기록에 가명 처리된 입력 사본을 저장해요.'
                : policy.generated_note_raw_input_mode === 'disabled' ? '현재 회기 기록의 서버 저장이 비활성화되어 있어요.'
                  : '현재 새 회기 기록에 입력 원문을 저장하지 않아요.'}
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
