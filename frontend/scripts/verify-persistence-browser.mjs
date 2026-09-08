// Run against the offline Python harness documented in docs/persistence_workflow.md.
// Edge/CDP only; no production credentials or real counseling data are used.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const pageUrl = 'http://127.0.0.1:4174/'
const apiUrl = 'http://127.0.0.1:8017'
const caseId = `SYNTHETIC-BROWSER-${Date.now()}`
const memo = '합성 내담자는 산책한 뒤 마음이 편안해졌다고 말했다.'
const edited = '상담사가 확인한 최신 합성 문장. 내담자는 산책 후 편안함을 보고했다. '.repeat(12)
const port = 9500 + process.pid % 400
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'remind-persistence-browser-'))
const screenshots = path.resolve('screenshots/persistence')
fs.mkdirSync(screenshots, { recursive: true })
const browser = spawn(process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', [
  '--headless=new', '--no-first-run', '--disable-gpu', '--window-size=1440,1000',
  `--remote-debugging-port=${port}`, `--user-data-dir=${profileDir}`, pageUrl,
], { stdio: 'ignore', windowsHide: true })
let socket, cdp
try {
  const target = await waitForTarget(port, pageUrl)
  socket = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve, { once: true }); socket.addEventListener('error', reject, { once: true }) })
  cdp = createCdpClient(socket)
  const exceptions = [], requests = []
  let failDraft = false, failConfirm = false
  cdp.on('Runtime.exceptionThrown', ({ exceptionDetails }) => exceptions.push(exceptionDetails.text))
  cdp.on('Network.requestWillBeSent', ({ request }) => requests.push(request))
  cdp.on('Page.javascriptDialogOpening', () => void cdp.send('Page.handleJavaScriptDialog', { accept: true }))
  cdp.on('Fetch.requestPaused', async ({ requestId, request }) => {
    const fail = (failDraft && request.url.endsWith('/api/notes/drafts') && request.method === 'POST')
      || (failConfirm && request.url.endsWith('/api/notes/confirm'))
    if (fail) {
      await cdp.send('Fetch.fulfillRequest', { requestId, responseCode: 503,
        responseHeaders: [{ name: 'Content-Type', value: 'application/json' }, { name: 'Access-Control-Allow-Origin', value: new URL(pageUrl).origin }],
        body: Buffer.from(JSON.stringify({ detail: 'synthetic storage failure' })).toString('base64') })
    } else await cdp.send('Fetch.continueRequest', { requestId })
  })
  await cdp.send('Network.enable')
  await cdp.send('Runtime.enable')
  await cdp.send('Page.enable')
  await cdp.send('Fetch.enable', { patterns: [{ urlPattern: `${apiUrl}/api/notes/*` }] })
  // Seed a synthetic Supabase client session, keeping AuthGate and token client unchanged.
  const seed = await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: `localStorage.setItem('sb-127-auth-token', JSON.stringify({access_token:'synthetic-access-token',refresh_token:'synthetic-refresh-token',token_type:'bearer',expires_in:3600,expires_at:Math.floor(Date.now()/1000)+3600,user:{id:'synthetic-user-a',aud:'authenticated',role:'authenticated',app_metadata:{},user_metadata:{},created_at:'2026-09-09T00:00:00Z'}}));` })
  await cdp.send('Page.reload')
  await hasText('저장된 기록 불러오기')
  await cdp.send('Page.removeScriptToEvaluateOnNewDocument', { identifier: seed.identifier })
  await click('수정하기')
  await fill('#modal_case_id', caseId)
  await fill('#modal_counselor_name', '합성 상담사')
  await fill('#modal_session_date', '2026-09-09')
  await click('완료')
  await click('회기 중 특이사항', true)
  await fill('#modal_counselor_memo', memo)
  await click('완료')
  const before = requests.filter((r) => r.method === 'POST' && r.url.endsWith('/api/notes/drafts')).length
  await cdp.evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='임시저장'); b.click(); b.click(); })()`)
  await hasText('임시저장 완료')
  assert.equal(requests.filter((r) => r.method === 'POST' && r.url.endsWith('/api/notes/drafts')).length, before + 1, 'duplicate save must be blocked')
  await cdp.send('Page.reload')
  await hasText('저장된 기록 불러오기')
  await click('저장된 기록 불러오기')
  await click('저장 목록 조회')
  await click(`임시저장 · ${caseId}`, true)
  await hasText(memo)
  console.log('temporary save -> reload -> server restore: passed')

  failDraft = true
  await click('임시저장')
  await hasText('저장소 요청을 완료하지 못했습니다')
  assert((await bodyText()).includes(memo), 'failed save must preserve input')
  failDraft = false
  await click('요약 초안 생성')
  await hasText('AI 초안을 저장했습니다')
  assert.equal(JSON.parse(requests.find((r) => r.url.endsWith('/api/notes/generate') && r.method === 'POST').postData).persist, true)
  await editSummary(edited)
  failConfirm = true
  await click('상담사 확정')
  await hasText('저장소 요청을 완료하지 못했습니다')
  assert((await bodyText()).includes(edited.trim()), 'failed confirmation must preserve edits')
  failConfirm = false
  await click('상담사 확정')
  await hasText('상담사 확정 완료')
  const payload = JSON.parse(requests.filter((r) => r.url.endsWith('/api/notes/confirm') && r.method === 'POST').at(-1).postData)
  assert.equal(payload.confirmed_note.session_content.text, edited)
  assert.equal(payload.confirmed_note.sections.session_content, edited)
  assert.equal(payload.create_case_memory, false)
  await cdp.send('Page.reload')
  await hasText('저장된 기록 불러오기')
  await click('저장된 기록 불러오기')
  await fill('[aria-label="저장 기록 케이스 ID"]', caseId)
  await click('저장 목록 조회')
  await click('확정본 ·', true)
  await hasText('서버에서 상담사 확정본 전체를 불러왔습니다')
  assert((await bodyText()).includes(edited.trim()), 'full edited confirmed note must survive browser reload')
  console.log('AI draft -> counselor edit -> confirm -> browser reload -> full confirmed record: passed')
  await editSummary('재확정 전 합성 수정 문장')
  await hasText('확정본에 미확정 수정사항이 있습니다')
  await click('임시저장')
  await hasText('임시저장 완료')
  await cdp.send('Page.reload')
  await hasText('저장된 기록 불러오기')
  await click('저장된 기록 불러오기')
  await fill('[aria-label="저장 기록 케이스 ID"]', caseId)
  await click('저장 목록 조회')
  // Both input-only and edited snapshots exist. Pick the newest matching draft.
  await click(`임시저장 · ${caseId}`, true)
  await hasText('재확정 전 합성 수정 문장')
  await hasText('확정본에 미확정 수정사항이 있습니다')
  console.log('temporary edits never overwritten by confirmed original: passed')

  for (const width of [375, 767, 768, 1024, 1440]) {
    await cdp.send('Emulation.setDeviceMetricsOverride', { width, height: 1000, deviceScaleFactor: 1, mobile: width < 768 })
    await cdp.evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    const bounds = await cdp.evaluate(`({width:innerWidth, scroll:document.documentElement.scrollWidth, panel:[...document.querySelector('[aria-label="기록 저장과 복원"]').querySelectorAll('button,input')].filter(e=>e.getBoundingClientRect().width).map(e=>({left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})`)
    assert(bounds.scroll <= bounds.width + 1, `horizontal overflow at ${width}: ${JSON.stringify(bounds)}`)
    assert(bounds.panel.every((b) => b.left >= 0 && b.right <= width + 1), `persistence controls clipped at ${width}`)
    await captureScreenshot(cdp, path.join(screenshots, `summary-${width}.png`))
  }
  console.log('mobile/breakpoint/laptop/desktop persistence controls: passed')
  await cdp.evaluate(`localStorage.removeItem('sb-127-auth-token')`)
  await cdp.send('Page.reload')
  await hasText('무료로 시작하기')
  const requestCount = requests.filter((r) => r.method === 'POST' && r.url.includes('/api/notes/')).length
  const missingToken = await cdp.evaluate(`(async () => { const api=await import('/src/api/client.ts'); try { await api.saveTemporaryDraft({case_id:'SYNTHETIC',session_number:1}); return 'unexpected success'; } catch(error) { return error.message; } })()`)
  assert(missingToken.includes('로그인'), missingToken)
  assert.equal(requests.filter((r) => r.method === 'POST' && r.url.includes('/api/notes/')).length, requestCount, 'no-token save must not send a request')
  assert.equal(exceptions.length, 0, `browser exceptions: ${exceptions.join(', ')}`)
  console.log('save/confirm failure UI and missing token: passed')
  console.log(`screenshots: ${screenshots}`)
} finally {
  try { await cdp?.send('Browser.close') } catch {}
  socket?.close()
  if (!browser.killed) browser.kill()
  // Keep any locked temporary browser profile for the OS to reclaim.
}

async function bodyText() { return cdp.evaluate('document.body.innerText') }
async function hasText(text) { return waitFor(async () => (await bodyText()).includes(text), 30000) }
async function click(text, partial = false) {
  await waitFor(async () => cdp.evaluate(`(() => {const b=[...document.querySelectorAll('button')].find(b=>${partial ? 'b.textContent.trim().includes' : 'b.textContent.trim() ==='}(${JSON.stringify(text)}) && !b.matches(':disabled')); if(!b)return false; b.click(); return true})()`))
}
async function fill(selector, value) {
  await waitFor(async () => cdp.evaluate(`Boolean(document.querySelector(${JSON.stringify(selector)}))`))
  await cdp.evaluate(`(() => {const e=document.querySelector(${JSON.stringify(selector)}); const proto=e.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype; Object.getOwnPropertyDescriptor(proto,'value').set.call(e,${JSON.stringify(value)}); e.dispatchEvent(new Event('input',{bubbles:true}));})()`)
}
async function editSummary(text) {
  await cdp.evaluate(`(() => {const section=[...document.querySelectorAll('section')].find(e=>e.querySelector('h2')?.textContent==='상담 내용'); section.querySelector('button.mt-4').click()})()`)
  await fill('section textarea', text)
  await cdp.evaluate(`document.querySelector('section textarea').blur()`)
}

async function captureScreenshot(cdp, screenshotPath) {
  const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png' })
  fs.writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'))
}

function createCdpClient(ws) {
  let nextId = 0
  const pending = new Map(), listeners = new Map()
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id) {
      const waiter = pending.get(message.id); pending.delete(message.id)
      if (message.error) waiter?.reject(new Error(message.error.message)); else waiter?.resolve(message.result)
    } else for (const listener of listeners.get(message.method) || []) listener(message.params)
  })
  return {
    on(method, listener) { listeners.set(method, [...(listeners.get(method) || []), listener]) },
    send(method, params = {}) {
      const id = ++nextId
      ws.send(JSON.stringify({ id, method, params }))
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
    },
    async evaluate(expression) {
      const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text)
      return result.result.value
    },
  }
}
async function waitForTarget(port, expectedUrl) {
  return waitFor(async () => {
    try { return (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === 'page' && t.url.includes(new URL(expectedUrl).host)) } catch { return false }
  }, 10000)
}
async function waitFor(predicate, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) { const value = await predicate(); if (value) return value; await new Promise(r => setTimeout(r, 100)) }
  throw new Error(`Timed out after ${timeoutMs}ms`)
}
