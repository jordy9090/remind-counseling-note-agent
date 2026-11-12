import type { TemporaryDraftSaveRequest } from '../types/session'

export interface SummarySaveJob {
  draft: TemporaryDraftSaveRequest
  ownerId: string
  controller: AbortController
  running: boolean
}

export function createSummarySaveJob(draft: TemporaryDraftSaveRequest, ownerId: string): SummarySaveJob {
  return {
    // Retain this client identifier even when the server returns its owner-scoped identifier.
    draft: { ...draft, draft_id: `draft_${crypto.randomUUID().replace(/-/g, '')}` },
    ownerId,
    controller: new AbortController(),
    running: false,
  }
}

function waitForRetry(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    signal.throwIfAborted()
    const onAbort = () => { clearTimeout(timer); reject(signal.reason) }
    const timer = setTimeout(() => { signal.removeEventListener('abort', onAbort); resolve() }, milliseconds)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

/** A manual retry reuses the same job and payload; concurrent clicks never duplicate requests. */
export async function saveSummaryWithRetry(
  job: SummarySaveJob,
  save: (draft: TemporaryDraftSaveRequest, scope: { ownerId: string; signal: AbortSignal }) => Promise<unknown>,
  retryable: (error: unknown) => boolean,
  wait = waitForRetry,
): Promise<boolean> {
  if (job.running) return false
  job.running = true
  const signal = job.controller.signal
  try {
    for (let attempt = 0; ; attempt++) {
      signal.throwIfAborted()
      try {
        await save(job.draft, { ownerId: job.ownerId, signal })
        signal.throwIfAborted()
        return true
      } catch (error) {
        if (signal.aborted || !retryable(error) || attempt >= 2) throw error
        await wait(attempt === 0 ? 1000 : 3000, signal)
      }
    }
  } finally { job.running = false }
}
