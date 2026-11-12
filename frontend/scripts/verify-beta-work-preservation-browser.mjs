import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

// Uses real built React components with synthetic, intercepted APIs only.
// Build with VITE_SUPABASE_URL=https://synthetic.supabase.co and a synthetic key,
// or set SUPABASE_HOST to the host embedded in the tested build.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const root = fileURLToPath(new URL('../dist/', import.meta.url))
const origin = process.env.TARGET_URL || 'http://127.0.0.1:4189'
const storageKey = `sb-${(process.env.SUPABASE_HOST || 'synthetic.supabase.co').split('.')[0]}-auth-token`
const deferred = () => {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}
const makeSession = suffix => {
  const id = `00000000-0000-4000-8000-${String(suffix).padStart(12, '0')}`
  const user = { id, aud: 'authenticated', role: 'authenticated', email: `beta-${suffix}@example.invalid`,
    app_metadata: { provider: 'email' }, user_metadata: {}, created_at: '2026-11-12T00:00:00Z' }
  const jwt = [Buffer.from('{"alg":"HS256","typ":"JWT"}').toString('base64url'),
    Buffer.from(JSON.stringify({ sub: id, exp: Math.floor(Date.now() / 1000) + 3600, role: 'authenticated', aud: 'authenticated' })).toString('base64url'), 'synthetic-signature'].join('.')
  return { access_token: jwt, refresh_token: `synthetic-refresh-${suffix}`, token_type: 'bearer', expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600, user }
}
const summary = marker => {
  const draft = { session_info: { case_id: 'synthetic', session_number: 1, session_date: '2026-11-12', counselor_name: '' } }
  for (const key of ['presenting_problem', 'session_theme', 'session_content', 'counselor_intervention', 'client_response', 'reflection', 'next_plan']) {
    draft[key] = { text: marker, evidence_type: 'reported', source_refs: [], needs_review: false }
  }
  return { session_summary_draft: draft, verification_report: { requires_counselor_review: [], unsupported_or_risky_claims: [], sensitive_info_items: [] },
    document_transform_preview: { missing_required_fields: [] }, evidence_mapped_data: { items: [] }, stub: true }
}
const wav = () => {
  const frames = 3 * 16000, data = Buffer.alloc(44 + frames * 2)
  data.write('RIFF'); data.writeUInt32LE(data.length - 8, 4); data.write('WAVEfmt ', 8)
  data.writeUInt32LE(16, 16); data.writeUInt16LE(1, 20); data.writeUInt16LE(1, 22)
  data.writeUInt32LE(16000, 24); data.writeUInt32LE(32000, 28); data.writeUInt16LE(2, 32)
  data.writeUInt16LE(16, 34); data.write('data', 36); data.writeUInt32LE(frames * 2, 40)
  for (let i = 0; i < frames; i++) data.writeInt16LE(Math.round(Math.sin(i / 30) * 1000), 44 + i * 2)
  return data
}
const server = http.createServer((req, res) => {
  let file = path.resolve(root, '.' + decodeURIComponent(new URL(req.url, origin).pathname))
  if (file !== path.resolve(root) && !file.startsWith(path.resolve(root) + path.sep)) { res.writeHead(404); res.end(); return }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html')
  res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html')
  res.end(fs.readFileSync(file))
})
if (!process.env.TARGET_URL) await new Promise(resolve => server.listen(4189, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) })

async function setup(options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
  const state = { session: makeSession(1), writes: [], rows: new Map(), errors: [], logoutCalls: 0,
    historyCalls: 0, generationCalls: 0, audioCalls: 0, extractionCalls: 0, caseSaves: [], caseSaveCompleted: 0 }
  await context.addInitScript(({ key, session }) => localStorage.setItem(key, JSON.stringify(session)), { key: storageKey, session: state.session })
  const page = await context.newPage()
  page.setDefaultTimeout(12000)
  page.on('pageerror', error => state.errors.push(error.message))
  await context.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), pathname = url.pathname
    const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }).catch(() => {})
    if (pathname.endsWith('/auth/v1/settings')) return reply({ external: { email: true } })
    if (pathname.endsWith('/auth/v1/token')) return reply(state.session)
    if (pathname.endsWith('/auth/v1/user')) return reply(state.session.user)
    if (pathname.endsWith('/auth/v1/logout')) { state.logoutCalls++; return reply({}) }
    if (url.origin !== new URL(origin).origin) return route.abort()
    if (pathname === '/api/notes/deidentification-preview') return reply({ items: [] })
    if (pathname === '/api/notes/quick-summary') {
      const index = ++state.generationCalls
      if (options.generate) return options.generate({ route, reply, state, index, request: req.postDataJSON() })
      return reply(summary('합성 회기 정상 요약'))
    }
    if (pathname === '/api/notes/drafts') {
      if (req.method() === 'POST') {
        const payload = req.postDataJSON()
        state.writes.push(payload)
        const attempt = state.writes.length
        if (options.save) return options.save({ route, reply, state, attempt, payload })
        state.rows.set(payload.draft_id, payload)
        return reply({ draft_id: 'server-scoped-' + payload.draft_id, saved_at: new Date().toISOString() })
      }
      state.historyCalls++
      if (options.historyFail && state.historyCalls === 1) return reply({ detail: 'synthetic unavailable' }, 503)
      return reply([...state.rows.values()].map(row => ({ ...row, saved_at: '2026-11-12T00:00:00Z' })))
    }
    if (pathname === '/api/audio/capabilities') return reply({ provider: 'clova', transcription: { available: true }, chunk_seconds: 60 })
    if (pathname === '/api/audio/transcribe') {
      state.audioCalls++
      if (options.audioGate) await options.audioGate.promise
      return reply({ transcription_id: 'synthetic-audio', filename: 'synthetic.wav', runtime_mode: 'real', status: 'completed',
        duration_seconds: 3, diarization_status: 'completed', warnings: [], failed_ranges: [],
        segments: [{ id: 0, start: 0, end: 2, speaker: 'A', text: '합성 발화 원문입니다.' }] })
    }
    if (pathname === '/api/materials/documents/extract') {
      state.extractionCalls++
      if (options.extractGate) await options.extractGate.promise
      return reply({ extracted_text: '늦게 도착한 이전 계정 합성 파일', filename: 'synthetic.pdf', warnings: [] })
    }
    if (pathname === '/api/cases') {
      if (req.method() === 'POST') return reply({ case_id: 'synthetic-client', ...req.postDataJSON() })
      return reply({ cases: [], recent_documents: [] })
    }
    if (pathname === '/api/cases/synthetic-client/quick-summary') {
      state.caseSaves.push(req.postDataJSON())
      if (options.caseSaveGate) await options.caseSaveGate.promise
      await reply({ case_id: 'synthetic-client', session_id: 'synthetic-session', note_id: 'synthetic-note', session_number: 1 })
      state.caseSaveCompleted++
      return
    }
    if (pathname.startsWith('/api/')) return reply({})
    // No real auth, model, provider or database request can leave this context.
    if (req.method() !== 'GET') return route.abort()
    return route.continue()
  })
  await page.goto(origin)
  await page.getByRole('button', { name: '음성 추가', exact: true }).waitFor()
  return { context, page, state }
}
async function menu(page, name) { await page.getByRole('navigation', { name: '주 메뉴', exact: true }).getByRole('button', { name, exact: true }).click() }
async function generate(page, input = '이번 회기에 합성 사례의 발표 불안과 다음 연습 계획을 이야기했습니다.') {
  await page.getByRole('textbox', { name: '요약할 상담 내용', exact: true }).fill(input)
  await page.getByRole('button', { name: '요약하기', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByRole('checkbox').check()
  await dialog.getByRole('button', { name: /다음: 등장 인물 정리|AI 요약 생성하기/ }).click()
  const mapping = page.getByRole('button', { name: '정리 없이 생성하기', exact: true })
  if (await mapping.isVisible().catch(() => false)) await mapping.click()
}
async function waitUntil(page, check, message, timeout = 12000) {
  const until = Date.now() + timeout
  while (!check()) {
    if (Date.now() >= until) throw Error(message)
    await page.waitForTimeout(50)
  }
}
async function loginSecond(page, state) {
  state.session = makeSession(2)
  await page.getByRole('button', { name: '로그인 / 회원가입', exact: true }).click()
  const login = page.getByRole('dialog', { name: '로그인', exact: true })
  await login.getByRole('textbox', { name: '이메일' }).fill(state.session.user.email)
  await login.getByPlaceholder('8자 이상 입력').fill('synthetic-password')
  await login.getByRole('button', { name: '로그인', exact: true }).click()
  await page.getByRole('button', { name: '음성 추가', exact: true }).waitFor()
}

const scenarios = {
  async navigation() {
    const gate = deferred(), { context, page, state } = await setup({ audioGate: gate })
    try {
      const input = page.getByRole('textbox', { name: '요약할 상담 내용', exact: true })
      await input.fill('메뉴를 이동해도 유지해야 하는 합성 입력 내용입니다.')
      await menu(page, '대시보드'); await menu(page, '간편 요약하기')
      assert.match(await input.inputValue(), /유지해야/)
      assert.equal(await page.evaluate(() => { const e = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(e); return e.defaultPrevented }), true)
      let unloadSeen = false
      page.once('dialog', async dialog => { unloadSeen = dialog.type() === 'beforeunload'; await dialog.dismiss() })
      await page.reload({ timeout: 3000 }).catch(() => {})
      assert.equal(unloadSeen, true, 'a real reload must prompt before discarding dirty input')
      assert.match(await input.inputValue(), /유지해야/)
      let logoutConfirm = false
      page.once('dialog', async dialog => { logoutConfirm = dialog.type() === 'confirm'; await dialog.dismiss() })
      await page.getByRole('button', { name: '로그아웃', exact: true }).click()
      assert.equal(logoutConfirm, true)
      assert.equal(state.logoutCalls, 0)
      await page.getByLabel('간편요약 음성 파일 선택').setInputFiles({ name: 'synthetic.wav', mimeType: 'audio/wav', buffer: wav() })
      await page.getByRole('button', { name: '동의를 확인하고 업로드', exact: true }).click()
      await waitUntil(page, () => state.audioCalls === 1, 'audio request never started')
      await menu(page, '대시보드'); await menu(page, '간편 요약하기')
      assert.equal(state.audioCalls, 1, 'menu navigation must not restart an upload')
      gate.resolve()
      const segment = page.getByRole('textbox', { name: '0번 발화 텍스트', exact: true })
      await segment.waitFor(); await segment.fill('상담사가 직접 수정한 합성 발화')
      await menu(page, '대시보드'); await menu(page, '간편 요약하기')
      assert.equal(await segment.inputValue(), '상담사가 직접 수정한 합성 발화')
      let removeConfirm = false
      page.once('dialog', async dialog => { removeConfirm = dialog.type() === 'confirm'; await dialog.dismiss() })
      await page.getByRole('button', { name: '간편요약 음성 제거', exact: true }).click()
      assert.equal(removeConfirm, true)
      assert.equal(await segment.inputValue(), '상담사가 직접 수정한 합성 발화')
      assert.deepEqual(state.errors, [])
    } finally { gate.resolve(); await context.close() }
  },
  async saves() {
    const { context, page, state } = await setup({ historyFail: true, save: async ({ route, reply, state, attempt, payload }) => {
      if (attempt === 1) { state.rows.set(payload.draft_id, payload); return route.abort('connectionfailed') }
      if (attempt === 2) return reply({ detail: 'synthetic unavailable' }, 503)
      state.rows.set(payload.draft_id, payload)
      return reply({ draft_id: 'server-scoped-' + payload.draft_id, saved_at: new Date().toISOString() })
    } })
    try {
      await page.getByRole('button', { name: '기록 다시 불러오기', exact: true }).click()
      await waitUntil(page, () => state.historyCalls >= 2, 'history retry did not run')
      await generate(page)
      await page.getByText('이전 요약한 기록에 저장됨', { exact: true }).waitFor()
      assert.equal(state.writes.length, 3)
      assert.equal(new Set(state.writes.map(x => x.draft_id)).size, 1)
      assert.equal(state.rows.size, 1, 'lost response must not duplicate the committed row')
      assert.ok(state.writes.every(x => /^draft_[a-zA-Z0-9_-]+$/.test(x.draft_id)))
      await menu(page, '대시보드'); await menu(page, '간편 요약하기')
      assert.equal(await page.getByRole('article', { name: 'AI 요약 결과' }).isVisible(), true)
      assert.deepEqual(state.errors, [])
    } finally { await context.close() }
  },
  async manualSave() {
    const { context, page, state } = await setup({ save: async ({ reply, state, attempt, payload }) => {
      if (attempt <= 3) return reply({ detail: 'synthetic unavailable' }, 503)
      state.rows.set(payload.draft_id, payload)
      return reply({ draft_id: 'server-scoped-' + payload.draft_id, saved_at: new Date().toISOString() })
    } })
    try {
      await generate(page)
      await page.getByRole('button', { name: '다시 저장', exact: true }).waitFor()
      assert.equal(state.writes.length, 3)
      assert.equal(await page.getByRole('article', { name: 'AI 요약 결과' }).isVisible(), true)
      assert.equal(await page.getByText('이전 요약한 기록에 저장됨', { exact: true }).count(), 0)
      await page.getByRole('button', { name: '다시 저장', exact: true }).click()
      await page.getByText('이전 요약한 기록에 저장됨', { exact: true }).waitFor()
      assert.equal(state.writes.length, 4)
      assert.equal(new Set(state.writes.map(x => x.draft_id)).size, 1)
      assert.equal(state.rows.size, 1)
      assert.deepEqual(state.errors, [])
    } finally { await context.close() }
  },
  async staleGeneration() {
    const gate = deferred(), { context, page, state } = await setup({ generate: async ({ reply, index }) => {
      if (index === 1) await gate.promise
      return reply(summary(index === 1 ? '이전 계정 지연 결과' : '현재 계정 최신 결과'))
    } })
    try {
      await generate(page)
      await waitUntil(page, () => state.generationCalls === 1, 'first generation did not start')
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('button', { name: '로그아웃', exact: true }).click()
      await loginSecond(page, state)
      await generate(page, '새 계정으로 시작한 합성 회기이며 이전 기록과 분리되어야 합니다.')
      await page.getByText('이전 요약한 기록에 저장됨', { exact: true }).waitFor()
      gate.resolve()
      await page.waitForTimeout(300)
      const content = await page.getByRole('article', { name: 'AI 요약 결과' }).innerText()
      assert.match(content, /현재 계정 최신 결과/); assert.doesNotMatch(content, /이전 계정 지연 결과/)
      assert.equal(state.writes.length, 1)
      assert.ok(JSON.stringify(state.writes).includes('현재 계정 최신 결과'))
      assert.ok(!JSON.stringify(state.writes).includes('이전 계정 지연 결과'))
      assert.deepEqual(state.errors, [])
    } finally { gate.resolve(); await context.close() }
  },
  async obsoleteWork() {
    const generationGate = deferred(), extractGate = deferred()
    const { context, page, state } = await setup({ extractGate, generate: async ({ reply, index }) => {
      if (index === 1) await generationGate.promise
      return reply(summary(index === 1 ? '폐기한 이전 작업 결과' : '새 작업 최종 결과'))
    } })
    try {
      await generate(page)
      await waitUntil(page, () => state.generationCalls === 1, 'generation A did not start')
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('button', { name: '입력 비우기', exact: true }).click()
      await generate(page, '새 작업의 합성 회기 내용이며 이전 요청을 대체했습니다.')
      await page.getByText('이전 요약한 기록에 저장됨', { exact: true }).waitFor()
      generationGate.resolve(); await page.waitForTimeout(300)
      const content = await page.getByRole('article', { name: 'AI 요약 결과' }).innerText()
      assert.match(content, /새 작업 최종 결과/); assert.doesNotMatch(content, /폐기한 이전 작업 결과/)
      assert.equal(state.writes.length, 1)
      await page.getByRole('button', { name: '새로 요약하기', exact: true }).click()
      await page.getByLabel('상담 내용 파일 선택').setInputFiles({ name: 'synthetic.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nsynthetic') })
      await waitUntil(page, () => state.extractionCalls === 1, 'file extraction A did not start')
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('button', { name: '입력 비우기', exact: true }).click()
      const input = page.getByRole('textbox', { name: '요약할 상담 내용', exact: true })
      await input.fill('새 작업의 파일 대체 내용')
      extractGate.resolve(); await page.waitForTimeout(300)
      assert.equal(await input.inputValue(), '새 작업의 파일 대체 내용')
      assert.deepEqual(state.errors, [])
    } finally { generationGate.resolve(); extractGate.resolve(); await context.close() }
  },
  async staleExtraction() {
    const gate = deferred(), { context, page, state } = await setup({ extractGate: gate })
    try {
      await page.getByLabel('상담 내용 파일 선택').setInputFiles({ name: 'synthetic.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nsynthetic') })
      await waitUntil(page, () => state.extractionCalls === 1, 'extraction did not start')
      page.once('dialog', dialog => dialog.accept())
      await page.getByRole('button', { name: '로그아웃', exact: true }).click()
      await loginSecond(page, state)
      const input = page.getByRole('textbox', { name: '요약할 상담 내용', exact: true })
      await input.fill('새 계정의 합성 입력')
      gate.resolve(); await page.waitForTimeout(300)
      assert.equal(await input.inputValue(), '새 계정의 합성 입력')
      assert.equal(state.writes.length, 0)
      assert.deepEqual(state.errors, [])
    } finally { gate.resolve(); await context.close() }
  },
  async staleAssociation() {
    const gate = deferred(), { context, page, state } = await setup({ caseSaveGate: gate,
      generate: ({ reply, index }) => reply(summary(index === 1 ? '이전 내담자에 연결할 요약' : '현재 작업의 새 요약')) })
    try {
      await generate(page)
      await page.getByText('이전 요약한 기록에 저장됨', { exact: true }).waitFor()
      await page.getByRole('button', { name: '내담자에 저장하기', exact: true }).click()
      await page.getByRole('button', { name: '새 내담자 만들기', exact: true }).click()
      const clientForm = page.getByRole('dialog', { name: '새 내담자 생성', exact: true })
      await clientForm.getByPlaceholder('홍길동').fill('합성 연결 검증')
      await clientForm.getByRole('button', { name: '내담자 생성하기', exact: true }).click()
      await waitUntil(page, () => state.caseSaves.length === 1, 'case association A did not start')
      await clientForm.waitFor({ state: 'hidden' })
      // Creating a new client closes both modals while its summary save is pending.
      // The counselor can genuinely start a new summary here without forced clicks.
      await page.getByRole('button', { name: '새로 요약하기', exact: true }).click()
      await generate(page, '새로운 합성 내담자의 회기이며 이전 내담자에게 연결되면 안 됩니다.')
      await page.getByText('이전 요약한 기록에 저장됨', { exact: true }).waitFor()
      gate.resolve()
      await waitUntil(page, () => state.caseSaveCompleted === 1, 'held association did not complete')
      await page.waitForTimeout(300)
      const content = await page.getByRole('article', { name: 'AI 요약 결과' }).innerText()
      assert.match(content, /현재 작업의 새 요약/)
      assert.doesNotMatch(content, /이전 내담자에 연결할 요약/)
      assert.equal(state.writes.length, 2)
      assert.equal(state.rows.size, 2)
      assert.equal(state.caseSaves.length, 1)
      assert.ok(JSON.stringify(state.caseSaves[0]).includes('이전 내담자에 연결할 요약'))
      assert.ok(!JSON.stringify(state.caseSaves[0]).includes('현재 작업의 새 요약'))
      assert.equal(await page.getByRole('button', { name: '내담자에 저장하기', exact: true }).isEnabled(), true)
      assert.deepEqual(state.errors, [])
    } finally { gate.resolve(); await context.close() }
  },
}
try {
  for (const [name, scenario] of Object.entries(scenarios)) {
    if (process.env.SCENARIO && process.env.SCENARIO !== name) continue
    await scenario()
    console.log('PASS: beta work preservation / ' + name)
  }
} finally {
  await browser.close()
  if (server.listening) await new Promise(resolve => server.close(resolve))
}
