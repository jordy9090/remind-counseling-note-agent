export type DraftSectionId =
  | 'client_info'
  | 'main_issue'
  | 'session_theme'
  | 'session_content'
  | 'counselor_intervention'
  | 'client_response'
  | 'next_plan'
  | 'risk_signal'
  | 'supervision_memo'
  | string

export interface ChecklistItem {
  id: DraftSectionId
  title: string
}

/** 요약 항목 체크리스트 기본 항목 (AI 생성 섹션과 1:1). */
export const defaultChecklistItems: ChecklistItem[] = [
  { id: 'main_issue', title: '주요 호소 문제' },
  { id: 'session_theme', title: '회기 주제' },
  { id: 'session_content', title: '상담 내용' },
  { id: 'counselor_intervention', title: '상담자 개입' },
  { id: 'client_response', title: '내담자 반응' },
  { id: 'next_plan', title: '다음 계획' },
  { id: 'psychological_test', title: '심리 검사 요약' },
  { id: 'risk_signal', title: '위험 신호' },
  { id: 'supervision_memo', title: '슈퍼비전 메모' },
]

/** 추천 항목: 기본 항목 외에 상담사가 자주 추가하는 사용자 정의 섹션 */
export const suggestedCustomItems: string[] = ['주요 감정', '행동 변화', '과제 수행', '위기 평가']

export const CHECKLIST_STORAGE_KEY = 'remind.summary-checklist.v1'

export interface StoredChecklistPreference {
  visible: string[]
  custom: ChecklistItem[]
}

export function customChecklistId(title: string): string {
  return `custom_${title.trim().replace(/\s+/g, '_')}`
}

export function readChecklistPreference(): StoredChecklistPreference | null {
  try {
    const raw = window.localStorage.getItem(CHECKLIST_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredChecklistPreference
    if (!Array.isArray(parsed.visible) || !Array.isArray(parsed.custom)) return null
    return {
      visible: parsed.visible.filter((id): id is string => typeof id === 'string'),
      custom: parsed.custom.filter((item) => item && typeof item.id === 'string' && typeof item.title === 'string'),
    }
  } catch {
    return null
  }
}

export function writeChecklistPreference(preference: StoredChecklistPreference | null): void {
  try {
    if (!preference) window.localStorage.removeItem(CHECKLIST_STORAGE_KEY)
    else window.localStorage.setItem(CHECKLIST_STORAGE_KEY, JSON.stringify(preference))
  } catch {
    // localStorage가 막힌 환경(프라이빗 창 등)에서는 조용히 무시한다.
  }
}
