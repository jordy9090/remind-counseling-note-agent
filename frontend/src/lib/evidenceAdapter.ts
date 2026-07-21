import type { DemoEvidenceItem } from '../data/counselorDemoFixture'

export interface VisualEvidence {
  id: string
  sourceType: 'transcript' | 'counselor_memo' | 'previous_summary' | 'ai_inference'
  badgeLabel: string
  badgeBg: string
  badgeText: string
  sourceLabel: string
  excerpt: string
  rationale: string
  warning?: string | null
}

export function formatEvidence(item: DemoEvidenceItem): VisualEvidence {
  switch (item.sourceType) {
    case 'transcript':
      return {
        ...item,
        badgeLabel: 'STT 축어록',
        badgeBg: 'bg-blue-50 border-blue-200',
        badgeText: 'text-blue-700',
      }
    case 'counselor_memo':
      return {
        ...item,
        badgeLabel: '상담사 메모',
        badgeBg: 'bg-emerald-50 border-emerald-200',
        badgeText: 'text-emerald-700',
      }
    case 'previous_summary':
      return {
        ...item,
        badgeLabel: '이전 회기 기록',
        badgeBg: 'bg-purple-50 border-purple-200',
        badgeText: 'text-purple-700',
      }
    case 'ai_inference':
    default:
      return {
        ...item,
        badgeLabel: 'AI 요약/추론',
        badgeBg: 'bg-amber-50 border-amber-200',
        badgeText: 'text-amber-800',
      }
  }
}
