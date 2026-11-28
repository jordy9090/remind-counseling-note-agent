import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

// Build with synthetic Supabase settings. All APIs are intercepted; no account or cloud data is created.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const root = fileURLToPath(new URL('../dist/', import.meta.url))
const origin = 'http://127.0.0.1:4197'
const storageKey = 'sb-synthetic-auth-token'
const user = { id: '00000000-0000-4000-8000-000000000707', aud: 'authenticated', role: 'authenticated',
  email: 'live-audio@example.invalid', app_metadata: { provider: 'email' }, user_metadata: {} }
const token = [Buffer.from('{"alg":"HS256","typ":"JWT"}').toString('base64url'),
  Buffer.from(JSON.stringify({ sub: user.id, exp: Math.floor(Date.now() / 1000) + 604800, role: 'authenticated', aud: 'authenticated' })).toString('base64url'), 'synthetic'].join('.')
const session = { access_token: token, refresh_token: 'synthetic-refresh', token_type: 'bearer',
  expires_in: 604800, expires_at: Math.floor(Date.now() / 1000) + 604800, user }
const client = { case_id: 'synthetic-live', case_alias: '합성 녹음 검증', status: 'active', total_session_count: 0,
  latest_session_number: null, transcript_completed_count: 0, confirmed_note_count: 0, draft_note_count: 0,
  document_count: 0, export_count: 0, temporary_draft_count: 0, sessions: [], documents: [], exports: [] }
const server = http.createServer((req, res) => {
  let file = path.resolve(root, '.' + decodeURIComponent(new URL(req.url, origin).pathname))
  if (!file.startsWith(path.resolve(root) + path.sep)) file = path.join(root, 'index.html')
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html')
  res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html')
  res.end(fs.readFileSync(file))
})
await new Promise(resolve => server.listen(4197, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true, args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'],
  ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['microphone'], acceptDownloads: true })
const requests = [], errors = []
let failNext = false
await context.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url()), pathname = url.pathname
  const reply = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
  if (pathname.startsWith('/auth/v1/')) {
    if (pathname.endsWith('/settings')) return reply({ external: { email: true } })
    if (pathname.endsWith('/user')) return reply(user)
    if (pathname.endsWith('/logout')) return reply({})
    return reply(session)
  }
  if (pathname.startsWith('/api/')) {
    requests.push({ path: pathname, method: req.method() })
    if (pathname === '/api/cases') return reply({ cases: [client], total_count: 1, recent_documents: [] })
    if (pathname.endsWith('/dashboard')) return reply(client)
    if (pathname === '/api/notes/drafts') return reply([])
    if (pathname === '/api/audio/capabilities') return reply({ runtime_mode: 'real', provider: 'clova',
      upload: { available: true }, transcription: { available: true }, speaker_diarization: { available: true } })
    if (pathname === '/api/audio/transcribe') {
      if (failNext) { failNext = false; return reply({ detail: '합성 재시도 오류' }, 503) }
      return reply({ transcription_id: 'synthetic-live', filename: 'synthetic.wav', runtime_mode: 'real', transcription_engine: 'clova',
        status: 'completed', diarization_status: 'completed', duration_seconds: 10, warnings: [], failed_ranges: [],
        transcript_text: '합성 발화입니다.', nonverbal_notes: '', segments: [{ id: 0, start: 0, end: 8, speaker: 'A', text: '합성 발화입니다.' }] })
    }
    if (pathname === '/api/audio/deidentify') return reply({ text: req.postDataJSON().text, candidates: [] })
    return reply({})
  }
  if (url.origin !== origin || req.method() !== 'GET') return route.abort()
  return route.continue()
})
async function newPage() {
  const page = await context.newPage()
  page.setDefaultTimeout(15000)
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(origin)
  return page
}
async function openSession(page) {
  await page.getByRole('navigation', { name: '주 메뉴', exact: true }).getByRole('button', { name: '내담자 관리', exact: true }).click()
  await page.getByText(client.case_alias, { exact: true }).first().click()
  await page.getByRole('button', { name: '새 회기 기록', exact: true }).first().click()
  await page.getByRole('region', { name: '실시간 상담 기록', exact: true }).waitFor()
}
const uploads = () => requests.filter(req => req.method === 'POST' && req.path === '/api/audio/transcribe').length
const recorder = page => page.getByRole('region', { name: '실시간 상담 기록', exact: true })
const click = (page, name) => recorder(page).getByRole('button', { name, exact: true }).click()
async function waitFor(check, message, timeout = 15000) {
  const deadline = Date.now() + timeout
  while (!await check()) {
    if (Date.now() > deadline) throw Error(message)
    await new Promise(resolve => setTimeout(resolve, 100))
  }
}
async function db(page, action, args) {
  return page.evaluate(async ({ action, args }) => {
    const database = await new Promise((resolve, reject) => {
      const request = indexedDB.open('remind-live-audio', 1)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    try {
      const tx = database.transaction(['recordings', 'chunks'], action === 'read' ? 'readonly' : 'readwrite')
      const completed = new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onabort = () => reject(tx.error) })
      const records = tx.objectStore('recordings'), chunks = tx.objectStore('chunks')
      const a = records.getAll(), b = chunks.getAll()
      if (action === 'seed') {
        a.onsuccess = () => {
          const record = a.result[0]
          const key = [args.userId || record.key[0], args.caseId || record.key[1], args.sessionNumber || record.key[2], args.id]
          records.put({ ...record, key, expiresAt: Date.now() + args.ttl })
          b.onsuccess = () => {
            for (const part of b.result.filter(part => part.recording[3] === record.key[3])) chunks.put({ ...part, key: [...key, part.index], recording: key })
          }
        }
      }
      if (action === 'expire') a.onsuccess = () => {
        for (const record of a.result) records.put({ ...record, expiresAt: Date.now() + 24 * 3600 * 1000 })
      }
      if (action === 'fixture') {
        const key = [args.userId, 'logout-fixture', 1, 'logout-recording']
        records.put({ key, filename: 'synthetic.wav', count: 1, frames: 160000, expiresAt: Date.now() + 86400000 })
        chunks.put({ key: [...key, 0], recording: key, index: 0, pcm: new Blob([new Uint8Array(320000)]) })
      }
      if (action === 'clear') { records.clear(); chunks.clear() }
      await completed
      return { records: a.result, chunks: b.result.map(({ pcm, ...part }) => ({ ...part, size: pcm.size })) }
    } finally { database.close() }
  }, { action, args })
}
async function wav(page) {
  const event = page.waitForEvent('download')
  await click(page, '원음 다운로드')
  const download = await event, parts = []
  for await (const part of await download.createReadStream()) parts.push(part)
  await download.delete()
  return Buffer.concat(parts)
}
let page
try {
  page = await newPage()
  await page.evaluate(({ storageKey, session }) => localStorage.setItem(storageKey, JSON.stringify(session)), { storageKey, session })
  await page.reload()
  await openSession(page)
  await click(page, '상담 녹음 시작')
  await page.getByRole('dialog', { name: '상담 녹음 동의 확인' }).getByRole('checkbox').check()
  await page.getByRole('button', { name: '동의 확인 후 녹음 시작', exact: true }).click()
  await waitFor(async () => (await db(page, 'read')).chunks.length >= 2, 'two real microphone chunks were not committed', 30000)
  let recordingWarning = false
  page.once('dialog', async dialog => { recordingWarning = dialog.type() === 'beforeunload'; await dialog.dismiss() })
  await page.reload({ timeout: 2500 }).catch(() => {})
  assert.equal(recordingWarning, true)
  await click(page, '일시정지')
  const original = await wav(page)
  const saved = await db(page, 'read')
  assert.equal(saved.chunks.length, 2)
  assert.deepEqual(saved.chunks.map(chunk => chunk.index), [0, 1])
  assert.ok(saved.chunks.every(chunk => chunk.size === 320000))
  assert.deepEqual(saved.records[0].key.slice(0, 3), [user.id, client.case_id, 1])
  assert.deepEqual(Object.keys(saved.records[0]).sort(), ['count', 'expiresAt', 'filename', 'frames', 'key'])
  let pausedWarning = false
  page.once('dialog', async dialog => { pausedWarning = dialog.type() === 'beforeunload'; await dialog.accept() })
  const closed = page.waitForEvent('close')
  await page.close({ runBeforeUnload: true }); await closed
  assert.equal(pausedWarning, true)
  page = await newPage(); await openSession(page)
  await recorder(page).getByText(/중단된 녹음 1분이 있습니다/).waitFor()
  const before = requests.length, beforeUploads = uploads()
  await click(page, '이어서 검토')
  const restored = await wav(page)
  assert.equal(uploads(), beforeUploads, 'restore must not upload audio')
  assert.equal(requests.length, before, 'restore and WAV download must make no API request')
  assert.deepEqual(restored.subarray(44), original.subarray(44, restored.length))
  const lost = (original.length - restored.length) / 32000
  assert.ok(lost >= 0 && lost <= 10, `lost ${lost}s`)
  console.log(`PASS recovery: ${saved.records[0].frames / 16000}s restored; ${lost.toFixed(3)}s lost; zero restoration API calls; recording/paused beforeunload`)

  // Retention and scope fixtures reuse the real PCM, without another microphone run.
  await db(page, 'seed', { id: 'other-session', sessionNumber: 2, ttl: 86400000 })
  await db(page, 'seed', { id: 'other-case', caseId: 'other-case', ttl: 86400000 })
  failNext = true
  await click(page, '실패 구간 다시 처리')
  await recorder(page).getByText('합성 재시도 오류', { exact: true }).waitFor()
  await click(page, '실패 구간 다시 처리')
  await recorder(page).getByText('전사를 복구했습니다. 녹음을 계속하거나 종료할 수 있습니다.', { exact: true }).waitFor()
  assert.equal(uploads(), beforeUploads + 3)
  await click(page, '녹음 종료·검토')
  await page.getByRole('heading', { name: '축어록 확인', exact: true }).waitFor()
  assert.equal((await db(page, 'read')).records.length, 3, 'handoff alone must not delete PCM')
  console.log('PASS explicit failed-chunk retry and existing review handoff; PCM retained until application')

  await db(page, 'seed', { id: 'manual-delete', ttl: 86400000 })
  for (const select of await page.getByRole('combobox').all()) {
    if (await select.locator('option[value="client"]').count()) await select.selectOption('client')
  }
  await page.getByRole('button', { name: '수정본의 개인정보 후보 확인', exact: true }).click()
  await page.getByRole('checkbox', { name: '원음과 화자, 누락 구간 및 개인정보 치환 결과를 확인했습니다.', exact: true }).check()
  await page.getByRole('button', { name: '검토한 수정본을 회기요약 입력에 반영', exact: true }).click()
  await waitFor(async () => !(await db(page, 'read')).records.some(record => record.key[3] === saved.records[0].key[3]), 'review application did not delete original recording')
  assert.equal((await db(page, 'read')).chunks.length, 6)
  console.log('PASS review application deletes only its original PCM after counselor/privacy confirmation')

  // Close the page without applying; reopening must still offer only the matching session.
  await page.close()
  page = await newPage(); await openSession(page)
  assert.equal(await recorder(page).getByRole('button', { name: '이어서 검토', exact: true }).count(), 1)
  await click(page, '삭제')
  await waitFor(async () => (await db(page, 'read')).records.length === 2, 'manual deletion did not remove its recording')
  assert.equal((await db(page, 'read')).chunks.length, 4)
  console.log('PASS case/session isolation and explicit deletion of PCM plus metadata')

  await page.clock.install()
  await db(page, 'expire')
  await page.clock.fastForward(86400001)
  await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  await waitFor(async () => (await db(page, 'read')).records.length === 0, '24h expiry did not remove PCM')
  assert.equal((await db(page, 'read')).chunks.length, 0)
  console.log('PASS 24-hour clock-controlled expiry')

  // Force a quota error in the real IndexedDB write while the fake microphone keeps running.
  await page.close(); page = await newPage(); await openSession(page)
  await page.evaluate(() => {
    const add = IDBObjectStore.prototype.add
    IDBObjectStore.prototype.add = function (...args) {
      if (this.name === 'chunks') throw new DOMException('Synthetic quota', 'QuotaExceededError')
      return add.apply(this, args)
    }
  })
  await click(page, '상담 녹음 시작')
  await page.getByRole('dialog', { name: '상담 녹음 동의 확인' }).getByRole('checkbox').check()
  await page.getByRole('button', { name: '동의 확인 후 녹음 시작', exact: true }).click()
  await recorder(page).getByRole('alert').filter({ hasText: '저장 공간' }).waitFor({ timeout: 20000 })
  await recorder(page).getByRole('button', { name: '일시정지', exact: true }).waitFor()
  const full = await wav(page)
  assert.ok(full.length > 320044)
  console.log('PASS quota failure leaves capture and original WAV download running')
  // Logout in another page must cancel access and remove records even outside the recording screen.
  const other = await newPage()
  await db(other, 'fixture', { userId: user.id })
  assert.equal((await db(other, 'read')).chunks.length, 1)
  await other.getByRole('button', { name: '로그아웃', exact: true }).click()
  await waitFor(async () => (await db(other, 'read')).records.length === 0, 'logout did not remove records')
  assert.equal((await db(other, 'read')).chunks.length, 0)
  await new Promise(resolve => setTimeout(resolve, 500))
  assert.deepEqual(await db(other, 'read'), { records: [], chunks: [] }, 'late writes must not resurrect logged-out audio')
  console.log('PASS cross-tab logout cleanup outside recorder screen')
  assert.deepEqual(errors, [])
} catch (error) {
  if (page && !page.isClosed()) console.error((await page.locator('body').innerText()).slice(0, 5000))
  throw error
} finally {
  if (page && !page.isClosed()) await db(page, 'clear').catch(() => {})
  await context.close(); await browser.close()
  await new Promise(resolve => server.close(resolve))
}
