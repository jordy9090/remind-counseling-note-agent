import { useCallback, useState } from 'react'
import {
  COUNSELOR_DEMO_FIXTURE,
  type CounselorDemoFixtureData,
  type DemoDocumentType,
  type DemoDraftSection,
  type DemoEvidenceItem,
} from '../data/counselorDemoFixture'

export type ReviewStatus = 'ai_draft' | 'in_review' | 'reviewed'

type DocumentSectionState = Record<DemoDocumentType, DemoDraftSection[]>

export interface UseCounselorDemoReturn {
  demoData: CounselorDemoFixtureData
  sections: DemoDraftSection[]
  activeDocumentType: DemoDocumentType
  selectedSectionId: string
  activeEvidenceItems: DemoEvidenceItem[]
  reviewStatus: ReviewStatus
  isDirty: boolean
  lastSavedAt: string | null
  confirmationStatus: 'idle' | 'confirmed'
  confirmationMessage: string | null
  setActiveDocumentType: (type: DemoDocumentType) => void
  setSelectedSectionId: (id: string) => void
  updateSectionContent: (id: string, newContent: string) => void
  markAsReviewed: () => void
  saveTemporary: () => void
  resetDemo: () => void
}

const createInitialDocumentSections = (): DocumentSectionState => ({
  session_summary: COUNSELOR_DEMO_FIXTURE.documents.session_summary.sections,
  session_note: COUNSELOR_DEMO_FIXTURE.documents.session_note.sections,
  supervision_report: COUNSELOR_DEMO_FIXTURE.documents.supervision_report.sections,
})

export function useCounselorDemo(): UseCounselorDemoReturn {
  const demoData = COUNSELOR_DEMO_FIXTURE
  const [documentSections, setDocumentSections] = useState<DocumentSectionState>(
    createInitialDocumentSections,
  )
  const [activeDocumentType, setActiveDocumentTypeState] =
    useState<DemoDocumentType>('session_note')
  const [selectedSectionId, setSelectedSectionId] = useState<string>(
    COUNSELOR_DEMO_FIXTURE.documents.session_note.sections[0]?.id || '',
  )
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>('ai_draft')
  const [isDirty, setIsDirty] = useState<boolean>(false)
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null)
  const [confirmationStatus, setConfirmationStatus] = useState<'idle' | 'confirmed'>('idle')
  const [confirmationMessage, setConfirmationMessage] = useState<string | null>(null)

  const sections = documentSections[activeDocumentType]
  const selectedSection = sections.find((section) => section.id === selectedSectionId) || sections[0]
  const activeEvidenceItems = (selectedSection?.evidenceIds || [])
    .map((evidenceId) => demoData.evidences[evidenceId])
    .filter(Boolean)

  const setActiveDocumentType = useCallback((type: DemoDocumentType) => {
    setActiveDocumentTypeState(type)
    setSelectedSectionId(COUNSELOR_DEMO_FIXTURE.documents[type].sections[0]?.id || '')
  }, [])

  const updateSectionContent = useCallback(
    (id: string, newContent: string) => {
      setDocumentSections((previous) => ({
        ...previous,
        [activeDocumentType]: previous[activeDocumentType].map((section) =>
          section.id === id ? { ...section, content: newContent } : section,
        ),
      }))
      setIsDirty(true)
      setReviewStatus('in_review')
      setConfirmationStatus('idle')
      setConfirmationMessage(null)
    },
    [activeDocumentType],
  )

  const markAsReviewed = useCallback(() => {
    setReviewStatus('reviewed')
    setIsDirty(false)
    setLastSavedAt(
      new Date().toLocaleTimeString('ko-KR', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    )
    setConfirmationStatus('confirmed')
    setConfirmationMessage('검토 완료 상태를 이 브라우저 세션에만 반영했습니다. 서버나 DB에는 저장하지 않았습니다.')
  }, [])

  const saveTemporary = useCallback(() => {
    setIsDirty(false)
    setLastSavedAt(
      new Date().toLocaleTimeString('ko-KR', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
    )
  }, [])

  const resetDemo = useCallback(() => {
    setDocumentSections(createInitialDocumentSections())
    setActiveDocumentTypeState('session_note')
    setSelectedSectionId(COUNSELOR_DEMO_FIXTURE.documents.session_note.sections[0]?.id || '')
    setReviewStatus('ai_draft')
    setIsDirty(false)
    setLastSavedAt(null)
    setConfirmationStatus('idle')
    setConfirmationMessage(null)
  }, [])

  return {
    demoData,
    sections,
    activeDocumentType,
    selectedSectionId,
    activeEvidenceItems,
    reviewStatus,
    isDirty,
    lastSavedAt,
    confirmationStatus,
    confirmationMessage,
    setActiveDocumentType,
    setSelectedSectionId,
    updateSectionContent,
    markAsReviewed,
    saveTemporary,
    resetDemo,
  }
}
