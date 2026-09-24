import { useState, type FormEvent } from 'react'
import { UserPlus } from 'lucide-react'

import ModalShell from '../app-shell/ModalShell'
import { PrimaryButton, SelectField } from '../app-shell/ui'
import type { CaseCreateRequest, CaseProfileUpdateRequest, ClientProfileFields } from '../../types/session'

export type ClientFormInitial = Partial<ClientProfileFields> & { case_alias?: string | null; status?: string | null }

const GENDERS = [{ id: '', label: '여/남' }, { id: '여', label: '여' }, { id: '남', label: '남' }, { id: '기타', label: '기타' }]
const MARITAL = [{ id: '', label: '선택' }, { id: '미혼', label: '미혼' }, { id: '기혼', label: '기혼' }, { id: '이혼', label: '이혼' }, { id: '사별', label: '사별' }, { id: '기타', label: '기타' }]
const FAMILY = [{ id: '', label: '선택' }, { id: '1인', label: '1인' }, { id: '2인', label: '2인' }, { id: '3인', label: '3인' }, { id: '4인 이상', label: '4인 이상' }, { id: '기타', label: '기타' }]
const STATUSES = [{ id: 'active', label: '진행중' }, { id: 'closed', label: '종결' }]

interface FormState {
  case_alias: string
  client_gender: string
  client_age: string
  client_occupation: string
  marital_status: string
  family_composition: string
  client_phone: string
  client_email: string
  client_notes: string
  status: string
}

function toState(initial?: ClientFormInitial): FormState {
  return {
    case_alias: initial?.case_alias || '',
    client_gender: initial?.client_gender || '',
    client_age: initial?.client_age === null || initial?.client_age === undefined ? '' : String(initial.client_age),
    client_occupation: initial?.client_occupation || '',
    marital_status: initial?.marital_status || '',
    family_composition: initial?.family_composition || '',
    client_phone: initial?.client_phone || '',
    client_email: initial?.client_email || '',
    client_notes: initial?.client_notes || '',
    status: initial?.status || 'active',
  }
}

/** 새 내담자 생성 / 프로필 수정 모달 (Figma "새 내담자를 생성해요"). */
export default function ClientFormModal({
  mode,
  initial,
  submitting,
  error,
  onClose,
  onSubmit,
}: {
  mode: 'create' | 'edit'
  initial?: ClientFormInitial
  submitting: boolean
  error: string | null
  onClose: () => void
  onSubmit: (payload: CaseCreateRequest & CaseProfileUpdateRequest) => void
}) {
  const [form, setForm] = useState<FormState>(() => toState(initial))
  const update = (field: keyof FormState, value: string) => setForm((prev) => ({ ...prev, [field]: value }))
  const ageNumber = form.client_age.trim() === '' ? null : Number(form.client_age)
  const ageInvalid = ageNumber !== null && (!Number.isInteger(ageNumber) || ageNumber < 0 || ageNumber > 150)
  const requiredMissing = !form.case_alias.trim() || !form.client_gender || ageNumber === null || !form.client_occupation.trim()
    || !form.marital_status || !form.family_composition || !form.client_phone.trim()
  const canSubmit = !requiredMissing && !ageInvalid && !submitting

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canSubmit) return
    onSubmit({
      case_alias: form.case_alias.trim(),
      client_gender: form.client_gender || null,
      client_age: ageNumber,
      client_occupation: form.client_occupation.trim() || null,
      marital_status: form.marital_status || null,
      family_composition: form.family_composition || null,
      client_phone: form.client_phone.trim() || null,
      client_email: form.client_email.trim() || null,
      client_notes: form.client_notes.trim() || null,
      ...(mode === 'edit' ? { status: form.status } : {}),
    })
  }

  return (
    <ModalShell
      ariaLabel={mode === 'create' ? '새 내담자 생성' : '내담자 프로필 수정'}
      title={mode === 'create' ? '새 내담자를 생성해요' : '내담자 정보를 수정해요'}
      description={mode === 'create' ? '내담자의 기본 정보를 입력하고 첫 상담을 준비해보세요.' : '수정한 정보는 이 내담자의 모든 화면에 반영됩니다.'}
      onClose={onClose}
      closeDisabled={submitting}
      width={660}
    >
      <form id="client-form" onSubmit={submit} className="flex flex-col gap-6">
        <div className="grid grid-cols-1 gap-x-4 gap-y-6 sm:grid-cols-[minmax(0,1fr)_120px_120px]">
          <label className="block">
            <span className="rm-label">이름<span className="req">*</span></span>
            <input className="rm-input" value={form.case_alias} onChange={(event) => update('case_alias', event.target.value)} placeholder="홍길동" maxLength={100} required />
          </label>
          <label className="block">
            <span className="rm-label">성별<span className="req">*</span></span>
            <SelectField ariaLabel="성별" value={form.client_gender} onChange={(value) => update('client_gender', value)} options={GENDERS} />
          </label>
          <label className="block">
            <span className="rm-label">나이<span className="req">*</span></span>
            <input className="rm-input" inputMode="numeric" value={form.client_age} onChange={(event) => update('client_age', event.target.value.replace(/[^0-9]/g, ''))} placeholder="25세" maxLength={3} required />
          </label>
          <label className="block">
            <span className="rm-label">직업<span className="req">*</span></span>
            <input className="rm-input" value={form.client_occupation} onChange={(event) => update('client_occupation', event.target.value)} placeholder="직장인, 학생 등" maxLength={100} required />
          </label>
          <label className="block">
            <span className="rm-label">결혼 상태<span className="req">*</span></span>
            <SelectField ariaLabel="결혼 상태" value={form.marital_status} onChange={(value) => update('marital_status', value)} options={MARITAL} />
          </label>
          <label className="block">
            <span className="rm-label">가족 구성<span className="req">*</span></span>
            <SelectField ariaLabel="가족 구성" value={form.family_composition} onChange={(value) => update('family_composition', value)} options={FAMILY} />
          </label>
        </div>
        <label className="block">
          <span className="rm-label">전화번호<span className="req">*</span></span>
          <input className="rm-input" inputMode="tel" value={form.client_phone} onChange={(event) => update('client_phone', event.target.value)} placeholder="010-1234-5678" maxLength={40} required />
        </label>
        <label className="block">
          <span className="rm-label">이메일</span>
          <input className="rm-input" type="email" value={form.client_email} onChange={(event) => update('client_email', event.target.value)} placeholder="remind@email.com" maxLength={120} />
        </label>
        <label className="block">
          <span className="rm-label">특이사항</span>
          <textarea className="rm-textarea" value={form.client_notes} onChange={(event) => update('client_notes', event.target.value)} placeholder="상담 시 반드시 기억해야 할 정보를 자유롭게 기록해주세요" rows={3} maxLength={4000} />
        </label>
        {mode === 'edit' && (
          <label className="block">
            <span className="rm-label">케이스 상태</span>
            <SelectField ariaLabel="케이스 상태" value={form.status} onChange={(value) => update('status', value)} options={STATUSES} className="w-[160px]" />
          </label>
        )}
        {ageInvalid && <p role="alert" className="-mt-3 text-xs font-semibold text-danger-500">나이는 0~150 사이의 숫자로 입력해주세요.</p>}
        {error && <p role="alert" className="-mt-3 text-xs font-semibold text-danger-500">{error}</p>}
        <p className="-mt-3 text-[11px] leading-5 text-grey-500">전화번호·이메일은 연락용 개인정보입니다. 이 계정에서만 조회되며, 상담 기록·AI 요약에는 사용되지 않습니다.</p>
        <PrimaryButton type="submit" form="client-form" className="w-full" disabled={!canSubmit} loading={submitting}>
          <UserPlus className="h-4 w-4" />
          {mode === 'create' ? '내담자 생성하기' : '수정 내용 저장'}
        </PrimaryButton>
      </form>
    </ModalShell>
  )
}
