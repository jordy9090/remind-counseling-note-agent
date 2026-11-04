import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'
import { createServer } from 'vite'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const deployed = process.env.VOUCHER_BASE_URL
const origin = deployed || 'http://127.0.0.1:4196'
const output = path.resolve(process.env.VOUCHER_OUTPUT || '../tmp_ab/voucher-original')
await fs.mkdir(output, { recursive: true })
let server
let credentials
if (!deployed) {
  process.env.VITE_SUPABASE_URL = 'https://voucher-test.invalid'
  process.env.VITE_SUPABASE_PUBLISHABLE_KEY = 'synthetic-public-key'
  process.env.VITE_API_BASE_URL = ''
  server = await createServer({ server: { host: '127.0.0.1', port: 4196, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8194' } } })
  await server.listen()
} else {
  credentials = JSON.parse(await fs.readFile(process.env.VOUCHER_CREDENTIAL_FILE, 'utf8'))
}
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', e => errors.push(e.message))
// Capture the exact isolated print document; never open a physical printer dialog.
await context.addInitScript(() => {
  window.print = () => {
    window.top.__voucherPrinted = { count: document.images.length, html: document.documentElement.outerHTML }
  }
})
if (!deployed) {
  const user = { id: '00000000-0000-4000-8000-000000000001', aud: 'authenticated', role: 'authenticated', email: 'voucher@example.invalid', user_metadata: {}, app_metadata: { provider: 'email' } }
  const jwt = [Buffer.from('{}').toString('base64url'), Buffer.from(JSON.stringify({ sub: user.id, exp: Math.floor(Date.now() / 1000) + 3600 })).toString('base64url'), 'synthetic'].join('.')
  await context.addInitScript(value => localStorage.setItem('sb-voucher-test-auth-token', JSON.stringify(value)), { access_token: jwt, refresh_token: 'synthetic', token_type: 'bearer', expires_in: 3600, expires_at: Math.floor(Date.now()/1000)+3600, user })
  await page.route('https://voucher-test.invalid/**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(route.request().url().endsWith('/settings') ? { external: { email: true } } : user) }))
}
try {
  if (credentials?.bypass) {
    await page.goto(`${origin}/?_vercel_share=${encodeURIComponent(credentials.bypass)}`)
  }
  await page.goto(origin)
  if (deployed) {
    await page.getByRole('button', { name: '로그인 / 회원가입', exact: true }).click()
    await page.getByLabel('이메일', { exact: true }).fill(credentials.email)
    await page.getByLabel('비밀번호', { exact: true }).fill(credentials.password)
    await page.getByRole('button', { name: '로그인', exact: true }).last().click()
  }
  await page.getByRole('button', { name: '문서 보관함', exact: true }).click()
  await page.getByRole('button', { name: '전마투 기록지·계약서·계획서 작성', exact: true }).click()
  await page.getByTitle('전마투 원본 양식 미리보기').waitFor({ timeout: 60000 })
  assert.equal(await page.locator('canvas:visible').count(), 12)
  assert.equal(await page.getByLabel('서비스 목적', { exact: true }).isVisible(), false)
  assert.equal(await page.getByRole('button', { name: '인쇄', exact: true }).isEnabled(), true)
  assert.ok(await page.locator('canvas:visible').evaluateAll(canvases => canvases.every(canvas => {
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    let ink = 0
    for (let i = 0; i < data.length; i += 4) if (data[i] < 180 && data[i+1] < 180 && data[i+2] < 180) ink++
    return ink > 1000
  })))
  const assets = path.resolve('../backend/app/templates/vouchers/original')
  for (const format of ['pdf', 'hwpx']) {
    const event = page.waitForEvent('download')
    await page.getByRole('button', { name: `${format.toUpperCase()} 저장`, exact: true }).click()
    const download = await event
    assert.equal(download.suggestedFilename(), `정신건강바우처 서류 양식.${format}`)
    assert.deepEqual(await fs.readFile(await download.path()), await fs.readFile(path.join(assets, `ari-voucher-original.${format}`)))
  }
  await page.screenshot({ path: path.join(output, 'original-screen.png') })
  await page.getByRole('button', { name: '인쇄', exact: true }).click()
  await page.waitForFunction(() => window.__voucherPrinted?.count === 12)
  const printHtml = await page.evaluate(() => window.__voucherPrinted.html)
  const printPage = await context.newPage()
  await printPage.setContent(printHtml, { waitUntil: 'load' })
  await printPage.pdf({ path: path.join(output, 'print-check.pdf'), preferCSSPageSize: true, printBackground: true })
  await printPage.close()
  await page.getByRole('button', { name: '내용 입력 · 저장한 문서', exact: true }).click()
  await page.getByRole('heading', { name: '기록할 회기 선택' }).waitFor()
  await page.getByRole('button', { name: '원본 양식 · 인쇄/저장', exact: true }).click()
  await page.getByTitle('전마투 원본 양식 미리보기').waitFor()
  assert.equal(await page.locator('canvas:visible').count(), 12)
  assert.deepEqual(errors, [])
  console.log('PASS: automatic 12-page original preview, PDF/HWPX byte equality, 12-page print document, and existing editor navigation')
} finally {
  await context.close()
  await browser.close()
  await server?.close()
}
