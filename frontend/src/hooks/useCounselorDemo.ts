import { useCallback, useState } from 'react'
import {
  COUNSELOR_DEMO_FIXTURE,
  type CounselorDemoFixtureData,
  type DemoDraftSection,
  type DemoEvidenceItem,
} from '../data/counselorDemoFixture'

export type ReviewStatus = 'ai_draft' | 'in_review' | 'reviewed'

export interface UseCounselorDemoReturn {
  demoData: CounselorDemoFixtureData
  sections: DemoDraftSection[]
  selectedSectionId: string
  activeEvidenceItems: DemoEvidenceItem[]
  reviewStatus: ReviewStatus
  isDirty: boolean
  lastSavedAt: string | null
  activeTab: 'draft' | 'sources' | 'preview'
  setActiveTab: (tab: 'draft' | 'sources' | 'preview') => void
  setSelectedSectionId: (id: string) => void
  updateSectionContent: (id: string, newContent: string) => void
  markAsReviewed: () => void
  saveTemporary: () => void
  resetDemo: () => void
}

export function useCounselorDemo(): UseCounselorDemoReturn {
  const [demoData] = useState<CounselorDemoFixtureData>(COUNSELOR_DEMO_FIXTURE)
  const [sections, setSections] = useState<DemoDraftSection[]>(COUNSELOR_DEMO_FIXTURE.sections)
  const [selectedSectionId, setSelectedSectionId] = useState<string>(
    COUNSELOR_DEMO_FIXTURE.sections[0]?.id || '',
  )
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>('ai_draft')
  const [isDirty, setIsDirty] = useState<boolean>(false)
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'draft' | 'sources' | 'preview'>('draft')

  const selectedSection = sections.find((s) => s.id === selectedSectionId) || sections[0]

  const activeEvidenceItems: DemoEvidenceItem[] = (selectedSection?.evidenceIds || [])
    .map((evId) => demoData.evidences[evId])
    .filter(Boolean)

  const updateSectionContent = useCallback((id: string, newContent: string) => {
    setSections((prev) =>
      prev.map((sec) => (sec.id === id ? { ...sec, content: newContent } : sec)),
    )
    setIsDirty(true)
    setReviewStatus('in_review')
  }, [])

  const markAsReviewed = useCallback(() => {
    setReviewStatus('reviewed')
    setIsDirty(false)
    setLastSavedAt(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
  }, [])

  const saveTemporary = useCallback(() => {
    setIsDirty(false)
    setLastSavedAt(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
  }, [])

  const resetDemo = useCallback(() => {
    setSections(COUNSELOR_DEMO_FIXTURE.sections)
    setSelectedSectionId(COUNSELOR_DEMO_FIXTURE.sections[0]?.id || '')
    setReviewStatus('ai_draft')
    setIsDirty(false)
    setLastSavedAt(null)
    setActiveTab('draft')
  }, [])

  return {
    demoData,
    sections,
    selectedSectionId,
    activeEvidenceItems,
    reviewStatus,
    isDirty,
    lastSavedAt,
    activeTab,
    setActiveTab,
    setSelectedSectionId,
    updateSectionContent,
    markAsReviewed,
    saveTemporary,
    resetDemo,
  }
}
