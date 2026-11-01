import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

// Run against a build with synthetic Supabase settings, or set TARGET_URL for
// deployed static assets. All auth, generation, and persistence requests are mocked.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const root = fileURLToPath(new URL('../dist/', import.meta.url))
const port = 4187
const entryUrl = process.env.TARGET_URL || ('http://127.0.0.1:' + port)
const origin = new URL(entryUrl).origin
const marker = '합성 회기 인계 확인 문장'
const section = text => ({ text, evidence_type: 'reported', source_refs: [], needs_review: false })
const draft = { session_info: { case_id: 'synthetic', session_number: 1, session_date: '2026-10-27', counselor_name: '' } }
for (const name of ['presenting_problem', 'session_theme', 'session_content', 'counselor_intervention', 'client_response', 'next_plan', 'reflection']) draft[name] = section(marker)
const response = { session_summary_draft: draft, verification_report: { requires_counselor_review: [], unsupported_or_risky_claims: [], sensitive_info_items: [] }, document_transform_preview: { missing_required_fields: [] }, evidence_mapped_data: { items: [] }, stub: true }
draft.session_content = { text: marker, evidence_type: 'direct', source_refs: ['transcript.turn_1', 'transcript.turn_2'], requires_review: true }
response.sanitized_input = { sources: { transcript_text: '상담자: SYNTHETIC-QUESTION-CUE\n내담자: SYNTHETIC-RESPONSE-CUE' } }
const uid = '00000000-0000-4000-8000-000000000001'
const user = { id: uid, aud: 'authenticated', role: 'authenticated', email: 'handoff@example.invalid', app_metadata: { provider: 'email' }, user_metadata: {}, created_at: '2026-10-27T00:00:00Z' }
const jwt = [Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url'), Buffer.from(JSON.stringify({ sub: uid, exp: Math.floor(Date.now() / 1000) + 3600, role: 'authenticated', aud: 'authenticated' })).toString('base64url'), 'synthetic-signature'].join('.')
const session = { access_token: jwt, refresh_token: 'synthetic-refresh', token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now() / 1000) + 3600, user }
const server = http.createServer((req, res) => {
  let file = path.resolve(root, '.' + decodeURIComponent(new URL(req.url, origin).pathname))
  if (file !== path.resolve(root) && !file.startsWith(path.resolve(root) + path.sep)) { res.writeHead(404); res.end(); return }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html')
  res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html')
  res.end(fs.readFileSync(file))
})
if (!process.env.TARGET_URL) await new Promise(resolve => server.listen(port, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) })
try {
  for (const scenario of [
    { name: 'password login', slowSettings: false, retryLogin: false },
    { name: 'late provider settings', slowSettings: true, retryLogin: false },
    { name: 'failed password then retry', slowSettings: true, retryLogin: true },
  ]) {
    const context = await browser.newContext()
    const page = await context.newPage()
    const errors = [], draftWrites = []
    let releaseSettings, tokenRequests = 0
    const settingsGate = new Promise(resolve => { releaseSettings = resolve })
    page.on('pageerror', error => errors.push(error.message))
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), pathname = url.pathname
      const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
      if (pathname.endsWith('/auth/v1/settings')) {
        if (scenario.slowSettings) await settingsGate
        return reply({ external: { email: true } })
      }
      if (pathname.endsWith('/auth/v1/token')) {
        tokenRequests += 1
        if (scenario.retryLogin && tokenRequests === 1) return reply({ error: 'invalid_grant', error_description: 'Invalid login credentials' }, 400)
        return reply(session)
      }
      if (pathname.endsWith('/auth/v1/user')) return reply(user)
      if (url.origin !== origin) return route.abort()
      if (pathname === '/api/notes/quick-summary') return reply(response)
      if (pathname === '/api/notes/deidentification-preview') return reply({ items: [] })
      if (pathname === '/api/notes/drafts') {
        if (req.method() === 'POST') {
          draftWrites.push(req.postDataJSON())
          return reply({ draft_id: 'synthetic-draft', saved_at: new Date().toISOString() })
        }
        return reply([])
      }
      if (pathname === '/api/cases') return reply({ cases: [], recent_documents: [] })
      if (pathname.startsWith('/api/')) return reply({})
      // Only static assets can leave this harness; no live auth/model/database calls.
      if (req.method() !== 'GET' || pathname.includes('/auth/v1/')) return route.abort()
      return route.continue()
    })
    try {
      await page.goto(entryUrl)
      await page.getByLabel('요약할 상담 내용', { exact: true }).fill('상담사: 오늘은 어떠셨나요? 내담자: 합성사례이며 회의 뒤 긴장한 마음을 이야기했습니다.')
      await page.getByRole('button', { name: '요약하기', exact: true }).click()
      await page.getByRole('checkbox').check()
      await page.getByRole('button', { name: 'AI 요약 생성하기', exact: true }).click()
      await page.getByText('관련 원문 보기 (2)', { exact: true }).click()
      assert.equal(await page.getByText('상담자: SYNTHETIC-QUESTION-CUE', { exact: true }).isVisible(), true)
      assert.equal(await page.getByText('내담자: SYNTHETIC-RESPONSE-CUE', { exact: true }).isVisible(), true)
      await page.getByRole('button', { name: '로그인 후 저장하기', exact: true }).click()
      assert.equal(await page.evaluate(() => localStorage.getItem('remind.quickSummary.pending').includes('SYNTHETIC-QUESTION-CUE')), false)
      assert.equal(await page.evaluate(() => Boolean(localStorage.getItem('remind.quickSummary.pending'))), true)
      const login = page.getByRole('dialog', { name: '로그인', exact: true })
      await login.getByRole('textbox', { name: '이메일' }).fill(user.email)
      await login.getByPlaceholder('8자 이상 입력').fill('synthetic-password')
      await login.getByRole('button', { name: '로그인', exact: true }).click()
      if (scenario.retryLogin) {
        await login.getByText('이메일 또는 비밀번호를 확인해주세요.', { exact: true }).waitFor()
        assert.equal(await page.evaluate(() => Boolean(localStorage.getItem('remind.quickSummary.pending'))), true)
        await login.getByRole('button', { name: '로그인', exact: true }).click()
      }
      const picker = page.getByRole('dialog', { name: '내담자 선택', exact: true })
      await picker.waitFor()
      if (scenario.slowSettings) {
        const settingsResponse = page.waitForResponse(r => r.url().endsWith('/auth/v1/settings'))
        releaseSettings()
        await (await settingsResponse).finished()
        // Wait for the provider state update to render, not only the HTTP response.
        await page.waitForTimeout(300)
      }
      assert.equal(await picker.isVisible(), true, scenario.name + ': login must retain the client picker after provider discovery')
      const result = page.getByRole('article', { name: 'AI 요약 결과' })
      assert.equal(await result.isVisible(), true)
      assert.ok((await result.innerText()).includes(marker))
      assert.equal(draftWrites.length, 1, 'Handoff saves the summary exactly once')
      assert.ok(draftWrites[0].draft_sections.some(item => item.content === marker))
      assert(!JSON.stringify(draftWrites).includes('SYNTHETIC-QUESTION-CUE'))
      assert.equal(await page.evaluate(() => localStorage.getItem('remind.quickSummary.pending')), null)
      await picker.getByRole('button', { name: '내담자 새로 등록하기', exact: true }).click()
      await page.getByRole('dialog', { name: '새 내담자 생성', exact: true }).waitFor()
      assert.deepEqual(errors, [])
      console.log('PASS: ' + scenario.name + ' -> preserved summary -> client picker -> registration; one synthetic draft write')
    } finally {
      releaseSettings()
      await context.close()
    }
  }
} finally {
  await browser.close()
  if (server.listening) await new Promise(resolve => server.close(resolve))
}

