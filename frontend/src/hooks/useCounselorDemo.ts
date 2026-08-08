import { useCallback, useEffect, useState } from 'react'
import { confirmGeneratedNote, generateNoteDraft, generateSupervisionReport } from '../api/client'
import type { RetrievalReport } from '../types/session'
import {
  COUNSELOR_DEMO_FIXTURE,
  COUNSELOR_DEMO_SESSION_INPUT,
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
  retrievalReport: RetrievalReport | null
  backendStatus: 'loading' | 'connected' | 'fallback'
  backendMessage: string | null
  confirmationStatus: 'idle' | 'confirming' | 'confirmed' | 'error'
  confirmationMessage: string | null
  setActiveTab: (tab: 'draft' | 'sources' | 'preview') => void
  setSelectedSectionId: (id: string) => void
  updateSectionContent: (id: string, newContent: string) => void
  markAsReviewed: () => Promise<void>
  saveTemporary: () => void
  resetDemo: () => void
}

export function useCounselorDemo(): UseCounselorDemoReturn {
  const [demoData, setDemoData] = useState<CounselorDemoFixtureData>(COUNSELOR_DEMO_FIXTURE)
  const [sections, setSections] = useState<DemoDraftSection[]>(COUNSELOR_DEMO_FIXTURE.sections)
  const [selectedSectionId, setSelectedSectionId] = useState<string>(
    COUNSELOR_DEMO_FIXTURE.sections[0]?.id || '',
  )
  const [reviewStatus, setReviewStatus] = useState<ReviewStatus>('ai_draft')
  const [isDirty, setIsDirty] = useState<boolean>(false)
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'draft' | 'sources' | 'preview'>('draft')
  const [retrievalReport, setRetrievalReport] = useState<RetrievalReport | null>(null)
  const [backendStatus, setBackendStatus] = useState<'loading' | 'connected' | 'fallback'>('loading')
  const [backendMessage, setBackendMessage] = useState<string | null>(null)
  const [noteId, setNoteId] = useState<string | null>(null)
  const [confirmedNoteBase, setConfirmedNoteBase] = useState<Record<string, unknown> | null>(null)
  const [confirmationStatus, setConfirmationStatus] = useState<'idle' | 'confirming' | 'confirmed' | 'error'>('idle')
  const [confirmationMessage, setConfirmationMessage] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function loadLiveDemo() {
      try {
        const note = await generateNoteDraft(COUNSELOR_DEMO_SESSION_INPUT)
        const full = note.full_response
        if (!full) throw new Error('backend response did not include the full note result')
        const report = await generateSupervisionReport({
          session_input: COUNSELOR_DEMO_SESSION_INPUT,
          session_summary_draft: full.session_summary_draft,
          demo_mode: true,
          report_date: COUNSELOR_DEMO_SESSION_INPUT.session_date,
          client_alias: COUNSELOR_DEMO_SESSION_INPUT.client_alias,
        })
        if (cancelled) return
        const evidences: Record<string, DemoEvidenceItem> = {}
        Object.entries(report.evidenceIndex).forEach(([id, item]) => {
          evidences[id] = {
            id,
            sourceType: inferEvidenceSourceType(item.label),
            sourceLabel: item.label,
            excerpt: item.text,
            rationale: 'backend evidence index에서 연결된 근거',
          }
        })
        const liveSections = report.sections.map((section) => ({
          id: section.id,
          title: section.title,
          content: section.contentBlocks.map(renderBlockText).filter(Boolean).join('\n\n'),
          status: section.status === 'complete' ? ('connected' as const) : ('needs_review' as const),
          evidenceIds: Array.from(new Set(section.contentBlocks.flatMap((block) => block.evidenceIds))),
        }))
        const nextData: CounselorDemoFixtureData = {
          ...COUNSELOR_DEMO_FIXTURE,
          clientInfo: {
            ...COUNSELOR_DEMO_FIXTURE.clientInfo,
            name: report.meta.clientAlias,
            sessionNumber: report.meta.sessionNumber,
            sessionDate: report.meta.reportDate,
            counselorName: report.meta.counselorName || COUNSELOR_DEMO_FIXTURE.clientInfo.counselorName,
            institution: report.meta.institution || COUNSELOR_DEMO_FIXTURE.clientInfo.institution,
            supervisor: report.meta.supervisor,
            supervisionDatePlace: report.meta.supervisionDatePlace,
          },
          sections: liveSections,
          evidences,
          missingItems: report.aiReview.missingFields,
          warnings: [report.aiReview.caution],
          templateContext: full.retrieved_template_context || undefined,
        }
        setDemoData(nextData)
        setSections(liveSections)
        setSelectedSectionId(liveSections[0]?.id || '')
        setRetrievalReport(full.retrieval_report)
        setNoteId(full.persistence_report.stored ? full.persistence_report.note_id || null : null)
        setConfirmedNoteBase(full.confirmed_session_note)
        setBackendStatus('connected')
        setBackendMessage(null)
      } catch (error) {
        if (cancelled) return
        setBackendStatus('fallback')
        setBackendMessage(error instanceof Error ? error.message : 'backend 연결 실패')
      }
    }
    void loadLiveDemo()
    return () => {
      cancelled = true
    }
  }, [])

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

  const markAsReviewed = useCallback(async () => {
    if (!noteId || !confirmedNoteBase) {
      setConfirmationStatus('error')
      setConfirmationMessage('Backend persistence가 활성화되지 않아 확정할 note_id가 없습니다.')
      return
    }
    setConfirmationStatus('confirming')
    setConfirmationMessage(null)
    try {
      const response = await confirmGeneratedNote({
        note_id: noteId,
        confirmed_note: buildConfirmedNote(confirmedNoteBase, sections),
        counselor_edited: isDirty,
        create_case_memory: true,
      })
      setReviewStatus('reviewed')
      setIsDirty(false)
      setLastSavedAt(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
      setConfirmationStatus('confirmed')
      setConfirmationMessage(`${response.message} memory chunks: ${response.memory_chunk_count}`)
    } catch (error) {
      setConfirmationStatus('error')
      setConfirmationMessage(error instanceof Error ? error.message : '상담 기록 확정에 실패했습니다.')
    }
  }, [confirmedNoteBase, isDirty, noteId, sections])

  const saveTemporary = useCallback(() => {
    setIsDirty(false)
    setLastSavedAt(new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }))
  }, [])

  const resetDemo = useCallback(() => {
    setSections(demoData.sections)
    setSelectedSectionId(demoData.sections[0]?.id || '')
    setReviewStatus('ai_draft')
    setIsDirty(false)
    setLastSavedAt(null)
    setActiveTab('draft')
    setConfirmationStatus('idle')
    setConfirmationMessage(null)
  }, [demoData])

  return {
    demoData,
    sections,
    selectedSectionId,
    activeEvidenceItems,
    reviewStatus,
    isDirty,
    lastSavedAt,
    activeTab,
    retrievalReport,
    backendStatus,
    backendMessage,
    confirmationStatus,
    confirmationMessage,
    setActiveTab,
    setSelectedSectionId,
    updateSectionContent,
    markAsReviewed,
    saveTemporary,
    resetDemo,
  }
}

function buildConfirmedNote(base: Record<string, unknown>, sections: DemoDraftSection[]): Record<string, unknown> {
  const byId = new Map(sections.map((section) => [section.id, section.content]))
  const baseSections =
    typeof base.sections === 'object' && base.sections !== null
      ? (base.sections as Record<string, unknown>)
      : {}
  return {
    ...base,
    sections: {
      ...baseSections,
      session_theme: byId.get('C-1') || baseSections.session_theme || '',
      presenting_problem: byId.get('A-3') || baseSections.presenting_problem || '',
      session_content: byId.get('C-2-2') || baseSections.session_content || '',
      counselor_intervention: byId.get('C-2-3') || baseSections.counselor_intervention || '',
      client_response: byId.get('C-2-3') || baseSections.client_response || '',
      reflection: byId.get('C-2-5') || baseSections.reflection || '',
      next_plan: byId.get('B-2') || baseSections.next_plan || '',
    },
  }
}

function inferEvidenceSourceType(label: string): DemoEvidenceItem['sourceType'] {
  if (/이전|previous|case.memory/i.test(label)) return 'previous_summary'
  if (/메모|memo|관찰/i.test(label)) return 'counselor_memo'
  if (/추론|inference|AI/i.test(label)) return 'ai_inference'
  return 'transcript'
}

function renderBlockText(block: {
  text?: string
  rows?: Record<string, string>[]
  speakerTurns?: Array<{ speaker: string; text: string }>
}): string {
  if (block.text) return block.text
  if (block.speakerTurns?.length) {
    return block.speakerTurns.map((turn) => `${turn.speaker}: ${turn.text}`).join('\n')
  }
  if (block.rows?.length) {
    return block.rows.map((row) => Object.values(row).join(' · ')).join('\n')
  }
  return ''
}
