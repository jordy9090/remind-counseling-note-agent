import { getAccessToken } from './supabase'

export type VoucherTemplate = 'form10' | 'form25' | 'form26'
export interface VoucherRow {
  note_id: string
  voucher_session_no: number
  actual_service_date: string
  delivered_attested: true
  content_left: string
  content_right: string
}
export interface VoucherForm {
  template: VoucherTemplate
  report_month: string
  service_tier: '' | 'type_1' | 'type_2'
  rows: VoucherRow[]
  general_comment: string
  purpose: string
  content: string
  schedule: string
  price: string
  contract_period: string
  plan_left: string
  plan_right: string
  additional_cost: string
  refund_terms: string
  other_terms: string
}
export interface VoucherDocument {
  id: string
  template: VoucherTemplate
  fingerprint: string
  privacy_status: 'applied' | 'degraded'
  reviewed_at: string | null
  created_at: string
  snapshot: { form: VoucherForm; sources: Record<string, string> }
}
export async function voucherApi<T>(path: string, method = 'GET', body?: unknown, binary = false): Promise<T> {
  const token = await getAccessToken()
  if (!token) throw new Error('다시 로그인해주세요.')
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || ''}/api/documents/vouchers/${path}`, {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    const detail = error.detail
    const row = typeof detail?.field === 'string' && /^row(\d+)_(left|right|date)$/.exec(detail.field)
    const fields: Record<string, string> = { general_comment: '비고·종합의견', purpose: '서비스 목적', content: '서비스 내용', schedule: '일정', price: '금액', contract_period: '계약기간', plan_left: '서비스 제공계획', plan_right: '추가 제공계획' }
    Object.assign(fields, { additional_cost: '추가비용', refund_terms: '환불규정', other_terms: '기타 합의사항' })
    const field = row ? `바우처 ${row[1]}회차 ${row[2] === 'left' ? '서비스 내용' : row[2] === 'right' ? '추가 기록' : '제공일'}` : fields[detail?.field]
    const message = typeof detail === 'string' ? detail : detail?.message || (Array.isArray(detail) ? '입력 항목과 날짜·회차를 확인해주세요.' : '문서 요청을 완료하지 못했습니다.')
    throw new Error(field ? `${field}: ${message}` : message)
  }
  if (response.status === 204) return undefined as T
  return (binary ? await response.blob() : await response.json()) as T
}
