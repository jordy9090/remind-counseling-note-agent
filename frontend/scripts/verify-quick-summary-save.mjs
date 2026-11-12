import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

const { outputText } = ts.transpileModule(fs.readFileSync('src/lib/quickSummarySave.ts', 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const { createSummarySaveJob, saveSummaryWithRetry } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const transient = { status: 503 }
const retryable = error => error?.status === 503
const delays = []
const noWait = async milliseconds => { delays.push(milliseconds) }
const draft = { case_id: 'quick-summary', draft_sections: [{ content: 'synthetic summary' }] }

// The server may commit a write before the response disappears. Retries must target that same row.
const job = createSummarySaveJob(draft, 'synthetic-owner')
const rows = new Map(), submittedIds = []
let attempts = 0
const lostResponse = async (payload, scope) => {
  assert.equal(scope.ownerId, 'synthetic-owner')
  submittedIds.push(payload.draft_id)
  rows.set(payload.draft_id, payload)
  if (attempts++ === 0) throw transient
  return { draft_id: 'server-scoped-identifier' }
}
assert.equal(await saveSummaryWithRetry(job, lostResponse, retryable, noWait), true)
assert.equal(rows.size, 1)
assert.equal(new Set(submittedIds).size, 1)
assert.match(job.draft.draft_id, /^draft_[0-9a-f]{32}$/)
assert.notEqual(job.draft.draft_id, 'server-scoped-identifier')

// Exhausted automatic attempts leave the same job usable by the explicit retry button.
const failed = createSummarySaveJob(draft, 'synthetic-owner')
let failures = 0
delays.length = 0
await assert.rejects(saveSummaryWithRetry(failed, async () => { failures++; throw transient }, retryable, noWait))
assert.equal(failures, 3)
assert.deepEqual(delays, [1000, 3000])
const stableId = failed.draft.draft_id
assert.equal(await saveSummaryWithRetry(failed, async payload => {
  assert.equal(payload.draft_id, stableId)
}, retryable, noWait), true)

// Authentication failures must not loop, and repeat clicks cannot start another concurrent write.
let unauthorizedAttempts = 0
await assert.rejects(saveSummaryWithRetry(createSummarySaveJob(draft, 'owner'), async () => {
  unauthorizedAttempts++; throw { status: 401 }
}, retryable, noWait))
assert.equal(unauthorizedAttempts, 1)
let release
const pending = createSummarySaveJob(draft, 'owner')
let concurrentCalls = 0
const send = () => { concurrentCalls++; return new Promise(resolve => { release = resolve }) }
const first = saveSummaryWithRetry(pending, send, retryable, noWait)
assert.equal(await saveSummaryWithRetry(pending, send, retryable, noWait), false)
release()
assert.equal(await first, true)
assert.equal(concurrentCalls, 1)

// Even a transport that ignores AbortSignal cannot report an obsolete task as saved.
const obsolete = createSummarySaveJob(draft, 'old-owner')
const obsoleteRun = saveSummaryWithRetry(obsolete, () => new Promise(resolve => { release = resolve }), retryable, noWait)
obsolete.controller.abort()
release()
await assert.rejects(obsoleteRun)
let cancelledCalls = 0
const cancelled = createSummarySaveJob(draft, 'owner')
await assert.rejects(saveSummaryWithRetry(cancelled, async () => {
  cancelledCalls++; throw transient
}, retryable, async () => { cancelled.controller.abort(); cancelled.controller.signal.throwIfAborted() }))
assert.equal(cancelledCalls, 1)

console.log('Quick summary save: stable lost-response retry, bounded attempts, manual retry, auth failure, duplicate clicks and obsolete cancellation PASS')
