/** The final HTTP payload is reviewed once, after all source/person edits. */
export type ReviewPurpose = 'quick' | 'generate' | 'recompose' | 'supervision' | 'memory'
export interface ReviewTask {
  purpose: ReviewPurpose
  payload: Record<string, unknown>
  ownerId: string | null
  signal?: AbortSignal
  resolve: (value: ReviewedPayload) => void
  reject: (error: Error) => void
}
export interface ReviewedPayload { payload: Record<string, unknown>; receipt: string }
let handler: ((task: ReviewTask) => void) | null = null

export function registerAIReview(next: (task: ReviewTask) => void) {
  handler = next
  return () => { if (handler === next) handler = null }
}

export function reviewForAI(purpose: ReviewPurpose, payload: Record<string, unknown>, ownerId: string | null, signal?: AbortSignal): Promise<ReviewedPayload> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new Error('요청이 취소되었습니다.'))
    if (!handler) return reject(new Error('검토 화면을 준비하지 못했습니다. 새로고침 후 다시 시도해주세요.'))
    handler({ purpose, payload: structuredClone(payload), ownerId, signal, resolve, reject })
  })
}
