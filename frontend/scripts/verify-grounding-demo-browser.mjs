import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const pageUrl = process.argv[2] || 'http://127.0.0.1:4174/?grounding-demo=1'
const edgePath = process.env.EDGE_PATH || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const debuggingPort = 9300 + process.pid % 500
const profileDir = fs.mkdtempSync(path.join(os.tmpdir(), 'remind-grounding-demo-browser-'))
const browser = spawn(edgePath, [
  '--headless=new',
  '--no-first-run',
  '--disable-gpu',
  '--window-size=1440,1100',
  `--remote-debugging-port=${debuggingPort}`,
  `--user-data-dir=${profileDir}`,
  pageUrl,
], { stdio: 'ignore', windowsHide: true })

let socket
let cdp
try {
  const target = await waitForTarget(debuggingPort, pageUrl)
  socket = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true })
    socket.addEventListener('error', reject, { once: true })
  })

  cdp = createCdpClient(socket)
  const requests = []
  const exceptions = []
  cdp.on('Network.requestWillBeSent', ({ request }) => requests.push(request.url))
  cdp.on('Runtime.exceptionThrown', ({ exceptionDetails }) => {
    exceptions.push(exceptionDetails.exception?.description || exceptionDetails.text)
  })
  await cdp.send('Network.enable')
  await cdp.send('Page.enable')
  await cdp.send('Runtime.enable')

  await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes('요약 초안'))
  const navigation = await cdp.evaluate(`(() => {
    const button = [...document.querySelectorAll('button')]
      .find((item) => item.textContent?.replace(/\\s/g, '') === '회기입력')
    if (!button) return 'missing'
    button.click()
    return 'clicked'
  })()`)
  if (navigation !== 'clicked') throw new Error('회기입력 navigation button was not found')
  await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes('요약 초안 생성'))

  requests.length = 0
  const submitted = await cdp.evaluate(`(() => {
    const button = [...document.querySelectorAll('button')]
      .find((item) => item.textContent?.includes('요약 초안 생성'))
    if (!button) return false
    button.click()
    return true
  })()`)
  if (!submitted) throw new Error('요약 초안 생성 button was not found')

  try {
    await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes('근거 2개'))
  } catch (error) {
    const pendingGenerateRequests = requests.filter((url) => url.includes('/api/notes/generate'))
    if (pendingGenerateRequests.length) {
      throw new Error(`DEV fixture remained loading after requesting: ${pendingGenerateRequests.join(', ')}`)
    }
    throw error
  }
  const generateRequests = requests.filter((url) => url.includes('/api/notes/generate'))
  if (generateRequests.length) {
    throw new Error(`DEV fixture made an unexpected generation request: ${generateRequests.join(', ')}`)
  }
  const duplicatedClaimCount = await cdp.evaluate(`(() => {
    const claim = '내담자는 부모에게 쉬고 싶다는 의견을 전달하고 실제 반응을 확인했다.'
    return document.body.innerText.split(claim).length - 1
  })()`)
  if (duplicatedClaimCount !== 0) {
    throw new Error(`Mapped grounding claim was repeated below the rendered summary (${duplicatedClaimCount})`)
  }

  await clickClaim(cdp, 'C1')
  await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes('토요일 모임 대신 집에서 쉬고'))
  const directState = await cdp.evaluate(`(() => ({
    selected: document.querySelector('[data-claim-id="C1"]')?.getAttribute('aria-pressed'),
    paragraphHighlighted: Boolean(document.querySelector('[data-claim-id="C1"]')?.closest('section')?.querySelector('button.bg-amber-50')),
    sourceRefs: [...document.querySelectorAll('[aria-label="근거 원문"] [data-source-ref]')].map((node) => node.dataset.sourceRef),
    text: document.querySelector('[aria-label="근거 원문"]')?.innerText || '',
  }))()`)
  if (directState.selected !== 'true' || !directState.paragraphHighlighted) {
    throw new Error('Direct evidence selection did not highlight the mapped summary paragraph')
  }
  if (JSON.stringify(directState.sourceRefs) !== JSON.stringify([
    'transcript:synthetic-session-5:0-3',
    'transcript:synthetic-session-3:0-3',
  ])) throw new Error(`Direct evidence regions were not kept separate: ${directState.sourceRefs.join(', ')}`)
  if (!directState.text.includes('5회기 · 상담 원문') || !directState.text.includes('3회기 · 상담 원문')) {
    throw new Error('Direct evidence panel did not show both historical session numbers')
  }

  await closeEvidence(cdp)
  await clickClaim(cdp, 'C2')
  await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes('확정 기록 필드 · 상담자 개입'))
  const counselorState = await cdp.evaluate(`(() => ({
    sourceRef: document.querySelector('[aria-label="근거 원문"] [data-source-ref]')?.dataset.sourceRef,
    text: document.querySelector('[aria-label="근거 원문"]')?.innerText || '',
  }))()`)
  if (counselorState.sourceRef !== 'confirmed_note:synthetic-session-3:counselor_intervention') {
    throw new Error(`Counselor judgment source was not distinct: ${counselorState.sourceRef}`)
  }
  if (!counselorState.text.includes('상담사 확정 기록')) throw new Error('Counselor judgment label was not visible')

  await closeEvidence(cdp)
  const reviewStates = await cdp.evaluate(`(() => ({
    clinical: document.body.innerText.includes('AI 해석 · 확인 필요'),
    unsupported: document.body.innerText.includes('근거 부족 · 검토 필요'),
    excluded: document.body.innerText.includes('이 문장은 확정 문서 본문에 자동으로 추가되지 않습니다.'),
  }))()`)
  if (!reviewStates.clinical || !reviewStates.unsupported || !reviewStates.excluded) {
    throw new Error(`Clinical/unsupported review states were not safely separated: ${JSON.stringify(reviewStates)}`)
  }
  await clickClaim(cdp, 'C3')
  await waitFor(async () => (await cdp.evaluate('document.querySelector(\'[aria-label="근거 원문"]\')?.innerText || \'\'')).includes('AI 해석 · 확인 필요'))

  await closeEvidence(cdp)
  await clickClaim(cdp, 'C5')
  await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes('근거 정보를 불러올 수 없습니다.'))
  const missingState = await cdp.evaluate(`(() => ({
    safeMessage: document.querySelector('[aria-label="근거 원문"]')?.innerText.includes('근거 정보를 불러올 수 없습니다.'),
    leakedId: document.querySelector('[aria-label="근거 원문"]')?.innerText.includes('R404'),
  }))()`)
  if (!missingState.safeMessage || missingState.leakedId) throw new Error('Missing source did not fail safely')

  await closeEvidence(cdp)
  const edited = await cdp.evaluate(`(() => {
    const section = [...document.querySelectorAll('section')].find((node) => node.querySelector('h2')?.textContent?.trim() === '상담 내용')
    const contentButton = section?.querySelector('button.mt-4')
    if (!contentButton) return false
    contentButton.click()
    return true
  })()`)
  if (!edited) throw new Error('Grounding-linked summary field could not enter edit mode')
  await waitFor(async () => await cdp.evaluate(`Boolean(document.querySelector('section textarea'))`))
  await cdp.evaluate(`(() => {
    const textarea = document.querySelector('section textarea')
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
    setter.call(textarea, textarea.value + ' 상담사 수정.')
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
    textarea.blur()
  })()`)
  await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes('수정 후 근거 재확인 필요'))

  await navigate(cdp, `${new URL(pageUrl).origin}/?grounding-demo=1&screen=final`, '상담일지')
  const unsupportedInExport = await cdp.evaluate(`(() => [...document.querySelectorAll('textarea[id^="final-section-"]')]
    .some((node) => node.value.includes('자기표현 불안이 완전히 해소되었다')))()`)
  if (unsupportedInExport) throw new Error('Unsupported review claim leaked into generated document body')
  await clickClaim(cdp, 'C1')
  await waitFor(async () => await cdp.evaluate(`Boolean(document.querySelector('[aria-label="근거 원문"]'))`))
  await closeEvidence(cdp)
  const drawerClosed = await cdp.evaluate(`(() => ({
    drawer: Boolean(document.querySelector('[aria-label="근거 원문"]')),
    editor: Boolean(document.querySelector('textarea[id^="final-section-"]')),
  }))()`)
  if (drawerClosed.drawer || !drawerClosed.editor) throw new Error('Document drawer did not close back to the full editor')

  await navigate(cdp, `${new URL(pageUrl).origin}/?grounding-demo=1&screen=supervision`, '개인상담 사례 수퍼비전 보고서')
  const supervisionLayout = await cdp.evaluate(`(() => ({
    headings: [...document.querySelectorAll('h1,h2,h3')].map((node) => node.textContent || ''),
    hasSupervisor: document.body.innerText.includes('박수퍼 박사'),
    hasReflection: document.body.innerText.includes('상담자 성찰'),
  }))()`)
  if (!supervisionLayout.hasSupervisor || !supervisionLayout.hasReflection) {
    throw new Error(`Supervision fixture layout was incomplete: ${JSON.stringify(supervisionLayout)}`)
  }

  await navigate(cdp, `${new URL(pageUrl).origin}/`, '')
  const flagOffState = await cdp.evaluate(`(() => ({
    evidenceControls: document.querySelectorAll('[data-claim-id]').length,
    evidencePanel: Boolean(document.querySelector('[aria-label="근거 원문"]')),
  }))()`)
  if (flagOffState.evidenceControls || flagOffState.evidencePanel) {
    throw new Error(`Grounding UI leaked into flag-off browser state: ${JSON.stringify(flagOffState)}`)
  }
  if (exceptions.length) throw new Error(`Browser runtime exception: ${exceptions.join(' | ')}`)

  await navigate(cdp, `${new URL(pageUrl).origin}/?grounding-demo=1`, '근거 2개')
  const screenshot = await cdp.send('Page.captureScreenshot', { format: 'png' })
  const screenshotPath = path.resolve('../results/debug/pr5_evidence_ui/session-detail-inline-evidence.png')
  fs.mkdirSync(path.dirname(screenshotPath), { recursive: true })
  fs.writeFileSync(screenshotPath, Buffer.from(screenshot.data, 'base64'))

  console.log('grounding demo browser verification passed')
  console.log('notes/generate requests: 0')
  console.log('direct/multiple/counselor/clinical/unsupported/missing/stale: passed')
  console.log('document drawer/supervision layout/flag off: passed')
  console.log(`screenshot: ${screenshotPath}`)
} finally {
  try {
    await cdp?.send('Browser.close')
  } catch {
    // The browser may already be closing after a failed assertion.
  }
  socket?.close()
  if (!browser.killed) browser.kill()
  try {
    fs.rmSync(profileDir, { recursive: true, force: true })
  } catch {
    // Windows can retain Chromium profile handles briefly after Browser.close.
  }
}

async function clickClaim(cdp, claimId) {
  const clicked = await cdp.evaluate(`(() => {
    const button = document.querySelector('[data-claim-id="${claimId}"]')
    if (!button) return false
    button.click()
    return true
  })()`)
  if (!clicked) throw new Error(`Grounding control ${claimId} was not found`)
}

async function closeEvidence(cdp) {
  const closed = await cdp.evaluate(`(() => {
    const button = document.querySelector('[aria-label="근거 원문 닫기"]')
    if (!button) return false
    button.click()
    return true
  })()`)
  if (!closed) throw new Error('Evidence close button was not found')
  await waitFor(async () => !(await cdp.evaluate(`Boolean(document.querySelector('[aria-label="근거 원문"]'))`)))
}

async function navigate(cdp, url, expectedText) {
  await cdp.send('Page.navigate', { url })
  await waitFor(async () => (await cdp.evaluate('location.href')) === url, 10000)
  if (expectedText) await waitFor(async () => (await cdp.evaluate('document.body.innerText')).includes(expectedText), 10000)
  else await waitFor(async () => (await cdp.evaluate('document.readyState')) === 'complete', 10000)
}

function createCdpClient(ws) {
  let nextId = 0
  const pending = new Map()
  const listeners = new Map()
  ws.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    if (message.id) {
      const waiter = pending.get(message.id)
      pending.delete(message.id)
      if (message.error) waiter?.reject(new Error(message.error.message))
      else waiter?.resolve(message.result)
      return
    }
    for (const listener of listeners.get(message.method) || []) listener(message.params)
  })
  return {
    on(method, listener) {
      listeners.set(method, [...(listeners.get(method) || []), listener])
    },
    send(method, params = {}) {
      const id = ++nextId
      ws.send(JSON.stringify({ id, method, params }))
      return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
    },
    async evaluate(expression) {
      const result = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
      if (result.exceptionDetails) throw new Error(result.exceptionDetails.text)
      return result.result.value
    },
  }
}

async function waitForTarget(port, expectedUrl) {
  const expectedHost = new URL(expectedUrl).host
  return waitFor(async () => {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`)
      const targets = await response.json()
      return targets.find((target) => target.type === 'page' && target.url.includes(expectedHost)) || false
    } catch {
      return false
    }
  }, 10000)
}

async function waitFor(predicate, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const value = await predicate()
    if (value) return value
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error(`Timed out after ${timeoutMs}ms`)
}
