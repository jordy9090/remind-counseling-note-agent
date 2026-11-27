import assert from 'node:assert/strict'
import { mock } from 'node:test'
import { AxiosError } from 'axios'
import { createServer } from 'vite'

// Exercise the production client and review gate with a synthetic session and HTTP adapter.
const vite = await createServer({
  configFile: false, envFile: false, appType: 'custom', server: { middlewareMode: true, hmr: false },
  plugins: [{
    name: 'synthetic-session', enforce: 'pre',
    resolveId(id) { if (id === '../lib/supabase') return '\0synthetic-session' },
    load(id) {
      if (id !== '\0synthetic-session') return
      return `export let owner = 'demo'
        export const setOwner = next => { owner = next }
        export const supabase = { auth: { getSession: async () => ({
          data: { session: owner ? { user: { id: owner }, access_token: 'synthetic' } : null }
        }) } }
        export const getAccessToken = async () => owner ? 'synthetic' : null`
    },
  }],
})
try {
  const { default: client, requestQuickSummary } = await vite.ssrLoadModule('/src/api/client.ts')
  const { registerAIReview } = await vite.ssrLoadModule('/src/lib/aiReview.ts')
  const { setOwner } = await vite.ssrLoadModule('\0synthetic-session')
  const detail = '요약을 만들지 못했어요. 잠시 후 다시 시도해주세요.'
  const fields = ['session_content', 'presenting_problem', 'counselor_intervention', 'client_response', 'next_plan']
  const success = {
    sanitized_input: { case_id: '', session_number: 0 }, session_summary_draft: Object.fromEntries(fields.map(k => [k, { text: 'synthetic' }])),
    evidence_mapped_data: { items: [] }, document_transform_preview: { missing_required_fields: [] },
    verification_report: { requires_counselor_review: [], unsupported_or_risky_claims: [], sensitive_info_items: [] },
  }
  for (const scenario of [
    'success', 'recover', 'twice', 'exhausted', 'forbidden', 'different-502', 'gateway',
    'extra-key', 'other-5xx', 'rate-limited', 'canceled', 'owner-changed', 'review-canceled', 'too-late',
  ]) {
    setOwner('demo')
    const controller = new AbortController()
    const calls = []
    let approvals = 0, completions = 0, clock = 0
    const timer = mock.method(performance, 'now', () => clock)
    const unregister = registerAIReview(task => {
      approvals++
      assert.equal(task.ownerId, 'demo')
      assert.equal(task.signal, controller.signal)
      assert.deepEqual(task.payload, { text: 'unreviewed' })
      if (scenario === 'review-canceled') return task.reject(new Error('Canceled'))
      task.resolve({ payload: { text: 'masked' }, receipt: 'synthetic-reviewed-receipt' })
    })
    try {
      client.defaults.adapter = async config => {
        calls.push(config)
        assert.equal(config.url, '/api/notes/quick-summary')
        assert.equal(config.data, '{"text":"masked"}')
        assert.equal(config.headers['X-Review-Receipt'], 'synthetic-reviewed-receipt')
        assert.equal(config.headers.Authorization, 'Bearer synthetic')
        assert.equal(config.signal, controller.signal)
        if (scenario === 'success' || (scenario === 'recover' && calls.length === 2)) {
          return { status: 200, data: success, config, headers: {}, statusText: 'OK' }
        }
        if (scenario === 'owner-changed') setOwner('another-owner')
        if (scenario === 'canceled') controller.abort()
        clock = scenario === 'too-late' ? 90001 : 40000
        const statuses = { 'other-5xx': 503, 'rate-limited': 429, forbidden: 403 }
        const data = scenario === 'gateway' ? '<html>502</html>' : JSON.stringify({
          detail: scenario === 'exhausted' ? '요약 검증을 마치지 못했어요. 잠시 후 다시 시도해주세요.'
            : scenario === 'different-502' ? 'different' : detail,
          ...(scenario === 'extra-key' ? { code: 'quick_summary_recovery_exhausted' } : {}),
        })
        const response = { status: statuses[scenario] ?? 502, data, config,
          headers: { 'content-type': scenario === 'gateway' ? 'text/html' : 'application/json' } }
        throw new AxiosError('request failed', 'ERR_BAD_RESPONSE', config, {}, response)
      }
      const result = requestQuickSummary('unreviewed', { ownerId: 'demo', signal: controller.signal }).then(() => { completions++ })
      const succeeds = scenario === 'success' || scenario === 'recover'
      if (succeeds) await result
      else await assert.rejects(result)
      assert.equal(approvals, 1, scenario)
      assert.equal(completions, succeeds ? 1 : 0, scenario)
      const expectedCalls = ['recover', 'twice'].includes(scenario) ? 2 : scenario === 'review-canceled' ? 0 : 1
      assert.equal(calls.length, expectedCalls, scenario)
      if (expectedCalls === 2) assert.equal(calls[1].timeout, calls[0].timeout - 40000)
    } finally {
      unregister()
      timer.mock.restore()
    }
  }
  console.log('PASS: 14 synthetic quick-summary approval, recovery, and cancellation scenarios')
} finally {
  await vite.close()
}
