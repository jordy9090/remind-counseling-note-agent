import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { test } from 'node:test'
import { observeHostedFlow } from './verify-hosted-api-traffic.mjs'

// Contract tests for the observer, not evidence that a deployed flow passed.
const api = 'https://api.remind.ai.kr', auth = 'https://synthetic.supabase.co'
function fixture(type, { wrongId, failedSave } = {}) {
  const ctx = new EventEmitter()
  const page = () => {
    const p = { context: () => ctx, url: () => 'about:blank', mainFrame: () => frame }
    const frame = { page: () => p }; return p
  }
  const first = page(), second = page()
  const gate = observeHostedFlow(ctx, { authOrigin: auth })
  const send = (url, method = 'POST', status = 200, p = first) => {
    const req = { url: () => url, method: () => method, resourceType: () => 'xhr', redirectedFrom: () => null, frame: () => p.mainFrame() }
    ctx.emit('request', req); ctx.emit('response', { request: () => req, status: () => status, ok: () => status >= 200 && status < 300 })
  }
  send(`${auth}/auth/v1/token`)
  for (const path of [type === 'audio' ? 'audio/transcribe' : 'materials/documents/extract', 'notes/deidentification-preview', 'notes/deidentification-confirm', 'notes/generate']) send(`${api}/api/${path}`)
  send(`${api}/api/notes/confirm`, 'POST', failedSave ? 500 : 200)
  if (!failedSave) {
    gate.expectReopenOn(second, 'synthetic-record')
    send(`${api}/api/notes/records/${wrongId ? 'another' : 'synthetic-record'}`, 'GET', 200, second)
  }
  return { gate, send, first, second }
}

for (const input of ['audio', 'text']) test(`${input} needs all six direct successful operations`, () => {
  const { gate } = fixture(input)
  assert.equal(gate.assertCompleted(input).length, 6)
  assert.throws(() => gate.assertCompleted(input === 'audio' ? 'text' : 'audio'), /Missing successful browser request/)
  gate.stop()
})

test('non-API uploads, third-party fetches and auth misuse fail even after an otherwise successful flow', () => {
  for (const [url, method] of [['https://remind.ai.kr/api/drafts', 'GET'], ['https://preview.vercel.app/ingest', 'POST'], ['https://other.invalid/collect', 'POST'], ['https://other.invalid/read', 'GET'], [`${auth}/rest/v1/table`, 'POST'], [`${auth}/auth/v1/user`, 'PUT'], ['https://other-project.supabase.co/auth/v1/token', 'POST']]) {
    const { gate, send } = fixture('text')
    send(`${url}?private=do-not-log`, method)
    assert.throws(() => gate.assertCompleted('text'), e => /Disallowed data request/.test(e.message) && !/private|do-not-log|other\.invalid/.test(e.message))
    gate.stop()
  }
})

test('failed save, mismatched ID or same page cannot prove persistence', () => {
  const failed = fixture('text', { failedSave: true })
  assert.throws(() => failed.gate.expectReopenOn(failed.second, 'synthetic-record'), /Save must succeed/)
  const wrong = fixture('text', { wrongId: true })
  wrong.send(`${api}/api/notes/records/synthetic-record`, 'GET', 200, wrong.first)
  assert.throws(() => wrong.gate.assertCompleted('text'), /reopen/)
  assert.throws(() => wrong.gate.expectReopenOn(wrong.first, 'synthetic-record'), /fresh page/)
})
