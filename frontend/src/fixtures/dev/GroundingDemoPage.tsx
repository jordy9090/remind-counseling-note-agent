import { useEffect, useState } from 'react'
import { toNoteDraftResponse } from '../../api/client'
import SessionDraftPage, { type DevGroundingDemoData } from '../../pages/SessionDraftPage'
import type { GenerateNoteResponse, SessionInput } from '../../types/session'
import {
  groundingDemoForm,
  groundingDemoNote,
  groundingDemoSupervisionReport,
} from './groundingDemo'

const historicalDemo: DevGroundingDemoData = {
  form: groundingDemoForm,
  note: groundingDemoNote,
  supervisionReport: groundingDemoSupervisionReport,
  sessionTopic: '부모 갈등 상황에서 자기표현 연습',
}

export default function GroundingDemoPage() {
  const [demo, setDemo] = useState<DevGroundingDemoData | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    async function loadSavedRun() {
      try {
        // Fetch this ignored source file only in the existing DEV fixture. It is
        // deliberately not imported or placed in public, so builds exclude it.
        const response = await fetch('/src/fixtures/dev/local-live-result.json', {
          cache: 'no-store',
          signal: controller.signal,
          headers: { Accept: 'application/json' },
        })
        if (response.status === 404) {
          if (!controller.signal.aborted) setDemo(historicalDemo)
          return
        }
        if (!response.ok) throw new Error('Saved run could not be loaded')
        const saved = await response.json() as {
          form: SessionInput
          full_response: GenerateNoteResponse
          enable_live_generation?: boolean
        }
        if (!saved.form?.case_id || typeof saved.form.counselor_memo !== 'string'
          || typeof saved.form.transcript_text !== 'string'
          || saved.form.case_id !== saved.full_response?.session_summary_draft?.session_info?.case_id) {
          throw new Error('Saved run does not match its input')
        }
        const note = toNoteDraftResponse(saved.full_response)
        if (!controller.signal.aborted) {
          setDemo({
            form: { ...saved.form, persist: false },
            note,
            liveGeneration: saved.enable_live_generation === true,
          })
        }
      } catch {
        if (!controller.signal.aborted) setError(true)
      }
    }
    void loadSavedRun()
    return () => controller.abort()
  }, [])

  if (error) return <p role="alert">저장된 실제 실행 결과를 읽지 못했습니다. 로컬 시연 파일을 확인해주세요.</p>
  return demo ? <SessionDraftPage devGroundingDemo={demo} /> : null
}
