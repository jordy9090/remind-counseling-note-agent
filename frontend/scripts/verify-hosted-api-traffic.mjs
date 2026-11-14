import assert from 'node:assert/strict'
import { resolve4, resolve6 } from 'node:dns/promises'
import { pathToFileURL } from 'node:url'

const api = 'https://api.remind.ai.kr'
const production = 'https://remind.ai.kr'
const authRoutes = new Set(['GET /auth/v1/settings', 'POST /auth/v1/token', 'GET /auth/v1/user', 'POST /auth/v1/logout'])
const operations = new Map([
  ['POST /api/audio/transcribe', 'audio upload'],
  ['POST /api/materials/documents/extract', 'text upload'],
  ['POST /api/notes/deidentification-preview', 'review'],
  ['POST /api/notes/deidentification-confirm', 'approve review'],
  ['POST /api/notes/generate', 'generate'],
  ['POST /api/notes/confirm', 'save'],
])

// Attach to a fresh, unmocked Playwright context with serviceWorkers: 'block'.
// Use one observer per synthetic session. After the UI confirms a save, call
// expectReopenOn(newPage, savedRecordId) before opening that record from the UI.
// The caller must separately assert visibly restored reviewed text and case. No
// request bodies, headers, full URLs or identifiers appear in the evidence.
export function observeHostedFlow(context, { frontendOrigin = production, authOrigin } = {}) {
  const frontend = new URL(frontendOrigin).origin
  if (authOrigin) assert.ok(authOrigin === new URL(authOrigin).origin && /^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(authOrigin), 'Use the exact configured Supabase Auth origin')
  const violations = new Set()
  const responses = []
  const pending = new WeakMap()
  const savingPages = new WeakSet()
  let reopenPage, reopenPath
  function onRequest(req) {
    const { origin, hostname, pathname, protocol } = new URL(req.url())
    if (!['http:', 'https:'].includes(protocol)) return
    const method = req.method()
    const apiPath = /^\/api(?:\/|$)/.test(pathname)
    const isFrontend = origin === frontend || origin === production || hostname.endsWith('.vercel.app')
    const dataRequest = !['GET', 'HEAD'].includes(method) || ['xhr', 'fetch', 'ping', 'eventsource'].includes(req.resourceType())
    const authOnly = origin === authOrigin && authRoutes.has(`${method} ${pathname}`)
    if (origin !== api && (apiPath || (!authOnly && dataRequest) || pending.has(req.redirectedFrom()))) {
      violations.add(isFrontend ? 'frontend/Vercel' : 'unexpected origin')
    }
    if (origin !== api || !apiPath) return
    const operation = operations.get(`${method} ${pathname}`) ||
      (method === 'GET' && reopenPage && pathname === reopenPath && req.frame() === reopenPage.mainFrame() ? 'reopen' : 'other API')
    pending.set(req, operation)
  }
  function onResponse(res) {
    const operation = pending.get(res.request())
    if (operation === 'save' && res.ok()) savingPages.add(res.request().frame().page())
    if (operation && operation !== 'other API') responses.push([operation, res.status()])
  }
  context.on('request', onRequest)
  context.on('response', onResponse)
  return {
    expectReopenOn(page, savedRecordId) {
      assert.ok(responses.some(([op, status]) => op === 'save' && status >= 200 && status < 300), 'Save must succeed before verifying a reopen')
      assert.ok(page.context() === context && page.url() === 'about:blank' && !savingPages.has(page), 'Reopen on a fresh page in the same browser context')
      assert.ok(typeof savedRecordId === 'string' && /^[a-zA-Z0-9_-]+$/.test(savedRecordId), 'Expected a saved synthetic record ID')
      reopenPage = page
      reopenPath = `/api/notes/records/${encodeURIComponent(savedRecordId)}`
    },
    assertCompleted(input) {
      assert.ok(['audio', 'text'].includes(input), 'Specify the uploaded synthetic fixture type')
      assert.equal(violations.size, 0, `Disallowed data request: ${[...violations].join(', ')}`)
      const required = [`${input} upload`, 'review', 'approve review', 'generate', 'save', 'reopen']
      const evidence = []
      for (const [operation, status] of responses) {
        if (operation === required[evidence.length] && status >= 200 && status < 300) {
          evidence.push({ operation, origin: api, status })
        }
      }
      assert.equal(evidence.length, required.length, `Missing successful browser request: ${required[evidence.length]}`)
      return evidence
    },
    stop() { context.off('request', onRequest); context.off('response', onResponse); reopenPage = reopenPath = undefined },
  }
}

// Anonymous read-only release preflight, distinct from authenticated browser evidence.
// Run: node scripts/verify-hosted-api-traffic.mjs [https://specific-preview.vercel.app]
export async function preflight(frontend = production) {
  const url = new URL(frontend)
  assert.ok(frontend === url.origin && (frontend === production || (url.protocol === 'https:' && url.hostname.endsWith('.vercel.app'))), 'Expected a bare production or candidate frontend origin')
  const get = (target, init) => fetch(target, { redirect: 'error', signal: AbortSignal.timeout(10000), ...init })
  const checks = {
    'API resolves directly to the configured iwinv address': async () => {
      const host = new URL(api).hostname
      assert.deepEqual([...new Set(await resolve4(host))], ['49.247.174.195'])
      const v6 = await resolve6(host).catch(e => { if (e.code === 'ENODATA' || e.code === 'ENOTFOUND') return []; throw e })
      assert.equal(v6.length, 0)
    },
    'Frontend serves the application': async () => {
      const r = await get(frontend)
      assert.ok(r.status === 200 && r.headers.get('content-type')?.includes('text/html') && (await r.text()).includes('<div id="root"></div>'))
    },
    'Legacy frontend API is retired': async () => {
      const r = await get(`${frontend}/api/health`)
      assert.ok(r.status === 410 && /\bno-store\b/i.test(r.headers.get('cache-control') || ''))
    },
    'Direct API health passes TLS and allows this web origin': async () => {
      const r = await get(`${api}/api/health`, { headers: { Origin: frontend } })
      assert.equal(r.headers.get('access-control-allow-origin'), frontend)
      assert.ok(r.status === 200 && (await r.json()).status === 'ok')
    },
    'Browser preflight permits authenticated JSON uploads': async () => {
      const r = await get(`${api}/api/notes/generate`, { method: 'OPTIONS', headers: {
        Origin: frontend, 'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type,x-review-receipt',
      } })
      assert.ok(r.ok && r.headers.get('access-control-allow-origin') === frontend)
      const tokens = key => (r.headers.get(key) || '').toLowerCase().split(',').map(s => s.trim())
      assert.ok(tokens('access-control-allow-methods').includes('post'))
      for (const header of ['authorization', 'content-type', 'x-review-receipt']) assert.ok(tokens('access-control-allow-headers').includes(header))
    },
  }
  return Promise.all(Object.entries(checks).map(async ([check, fn]) => {
    try { await fn(); return { check, passed: true } } catch { return { check, passed: false } }
  }))
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const checks = await preflight(process.argv[2])
  for (const { check, passed } of checks) console.log(`${passed ? 'PASS' : 'FAIL'}: ${check}`)
  if (checks.some(check => !check.passed)) process.exitCode = 1
}
