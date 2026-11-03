import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createRequire } from 'node:module'
import { createServer } from 'vite'

// Start backend/tests/voucher_browser_server.py first. Every identity and row is
// synthetic; the backend uses memory storage and disables entity-model extraction.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
process.env.VITE_SUPABASE_URL = 'https://voucher-test.invalid'
process.env.VITE_SUPABASE_PUBLISHABLE_KEY = 'synthetic-public-key'
process.env.VITE_API_BASE_URL = ''
const origin = 'http://127.0.0.1:4194'
const server = await createServer({ server: { host: '127.0.0.1', port: 4194, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8194' } } })
await server.listen()
const browser = await chromium.launch({ headless: true, ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}) })
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } })
const page = await context.newPage()
const errors = []
const ids = new Set()
const user = { id: '00000000-0000-4000-8000-000000000001', aud: 'authenticated', role: 'authenticated', email: 'voucher@example.invalid', user_metadata: {}, app_metadata: { provider: 'email' } }
const jwt = [Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url'), Buffer.from(JSON.stringify({ sub: user.id, exp: Math.floor(Date.now()/1000)+3600, role: 'authenticated', aud: 'authenticated' })).toString('base64url'), 'synthetic-signature'].join('.')
const session = { access_token: jwt, refresh_token: 'synthetic-refresh', token_type: 'bearer', expires_at: Math.floor(Date.now()/1000)+3600, expires_in: 3600, user }
page.on('pageerror', e => errors.push(e.message))
page.on('response', async r => {
  if (r.url().endsWith('/vouchers/prepare') && r.status() === 200) ids.add((await r.json()).id)
})
await context.addInitScript(value => localStorage.setItem('sb-voucher-test-auth-token', JSON.stringify(value)), session)
await page.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (url.hostname === 'voucher-test.invalid') return route.fulfill({ contentType: 'application/json', body: JSON.stringify(url.pathname.endsWith('/settings') ? { external: { email: true } } : user) })
  if (url.origin !== origin) return route.abort()
  return route.continue()
})
const open = async () => {
  await page.goto(origin)
  await page.getByRole('button', { name: '문서 보관함', exact: true }).click()
  await page.getByRole('button', { name: '전마투 기록지·계약서·계획서 작성', exact: true }).click()
  await page.getByRole('heading', { name: '기록할 회기 선택' }).waitFor()
}
const approve = async () => {
  const canvas = page.getByRole('img', { name: '전마투 PDF 1 / 1페이지', exact: true })
  await canvas.waitFor()
  assert.equal(await page.locator('iframe').count(), 0, 'preview must not depend on the browser PDF plugin')
  assert.ok(await canvas.evaluate(el => {
    const pixels = el.getContext('2d').getImageData(0, 0, el.width, el.height).data
    let ink = 0
    for (let i = 0; i < pixels.length; i += 4) if (pixels[i+3] && pixels[i] < 200 && pixels[i+1] < 200 && pixels[i+2] < 200) ink++
    return ink > 1000
  }), 'the PDF canvas must contain actual rendered text/grid pixels')
  await page.getByRole('checkbox', { name: '미리보기의 식별정보를 확인하고 직접 인용·사생활 세부내용을 기관 제출에 필요한 수준으로 줄였습니다.' }).check()
  await page.getByRole('checkbox', { name: '기본정보·서명·미기입 항목은 기관에서 보완하겠습니다.' }).check()
  await page.getByRole('button', { name: '내용 검토 완료', exact: true }).click()
  await page.getByText('검토 완료 · 기관 보완 필요', { exact: true }).waitFor()
}
const download = async (format = 'pdf') => {
  const event = page.waitForEvent('download')
  await page.getByRole('button', { name: `${format.toUpperCase()} 다운로드`, exact: true }).click()
  const data = await fs.readFile(await (await event).path())
  assert.equal(data.subarray(0, format === 'pdf' ? 5 : 2).toString(), format === 'pdf' ? '%PDF-' : 'PK')
  return data
}
try {
  if (process.env.VOUCHER_SCENARIO === 'preview_retry') {
    await open()
    await page.getByLabel('서식', { exact: true }).selectOption('form26')
    await page.getByLabel('서비스 목적', { exact: true }).fill('연락처 010-1234-5678 확인')
    await page.getByLabel('서비스 내용', { exact: true }).fill('감정을 탐색한다.')
    await page.getByLabel('서비스 제공계획', { exact: true }).fill('목표를 함께 정한다.')
    await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
    await page.getByTitle('실제 출력될 전마투 PDF').waitFor()
    assert.ok(!(await page.getByLabel('서비스 목적', { exact: true }).inputValue()).includes('010-1234-5678'))
    await page.route('**/vouchers/saved/*/preview', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '합성 미리보기 오류' }) }), { times: 1 })
    await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
    await page.getByRole('alert').waitFor()
    assert.equal(await page.getByTitle('실제 출력될 전마투 PDF').count(), 0, 'failed preview cannot leave an old PDF available for approval')
    assert.equal(await page.getByRole('button', { name: '내용 검토 완료', exact: true }).isDisabled(), true)
    await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
    await page.getByTitle('실제 출력될 전마투 PDF').waitFor()
    assert.equal(ids.size, 1, 'retrying sanitized preview must reuse the candidate')
    await page.route('**/vouchers/saved/*/preview', route => route.fulfill({ status: 200, contentType: 'application/pdf', body: 'invalid synthetic PDF' }), { times: 1 })
    await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
    await page.getByText(/PDF를 표시하지 못했습니다/).waitFor()
    await page.getByRole('checkbox', { name: '미리보기의 식별정보를 확인하고 직접 인용·사생활 세부내용을 기관 제출에 필요한 수준으로 줄였습니다.' }).check()
    await page.getByRole('checkbox', { name: '기본정보·서명·미기입 항목은 기관에서 보완하겠습니다.' }).check()
    assert.equal(await page.getByRole('button', { name: '내용 검토 완료', exact: true }).isDisabled(), true)
    assert.equal(await page.locator('canvas').count(), 0, 'a render failure must clear old content')
    await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
    await page.getByTitle('실제 출력될 전마투 PDF').waitFor()
    await approve()
    console.log('PASS: sanitized preview retry reuses snapshot; failed preview clears stale PDF and blocks approval')
  } else {
  await open()
  await page.getByLabel('작성월', { exact: true }).fill('2026-10')
  await page.getByRole('checkbox', { name: '상담 12회기', exact: true }).check()
  await page.getByRole('spinbutton', { name: '상담 12회기 바우처 회차' }).fill('3')
  await page.getByRole('checkbox', { name: '실제 제공한 서비스입니다', exact: true }).check()
  let metadataOnly = false
  await page.route('**/api/documents/vouchers/map', async route => {
    const response = await route.fetch()
    assert.equal(response.status(), 200)
    const mapped = await response.json()
    assert.equal(mapped.rows[0].content_left, '')
    assert.equal(mapped.rows[0].content_right, '')
    metadataOnly = true
    // An older backend must not reintroduce copied private narrative in the UI.
    await route.fulfill({ response, json: { ...mapped, rows: mapped.rows.map(row => ({ ...row,
      content_left: '합성 개인 기록: 비밀 약속', content_right: '합성 개인 발화: 상세 사생활' })) } })
  }, { times: 1 })
  await page.getByRole('button', { name: '선택한 회기 입력란 만들기', exact: true }).click()
  const text = page.getByLabel('바우처 3회차 서비스 내용', { exact: true })
  await text.waitFor()
  assert.equal(metadataOnly, true)
  assert.equal(await text.inputValue(), '')
  assert.equal(await page.getByLabel('바우처 3회차 추가 기록', { exact: true }).inputValue(), '')
  assert.equal(await page.getByRole('button', { name: '출력 내용 확인', exact: true }).isDisabled(), true)
  await text.fill('  ')
  assert.equal(await page.getByRole('button', { name: '출력 내용 확인', exact: true }).isDisabled(), true)
  await text.fill('합성사례: 긴장과 대처를 탐색함.')
  await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
  await page.getByTitle('실제 출력될 전마투 PDF').waitFor()
  assert.equal(await page.getByRole('button', { name: 'PDF 다운로드', exact: true }).isDisabled(), true)
  await approve()
  const first = await download()
  await page.screenshot({ path: path.resolve('../tmp_ab/voucher-browser-record.png'), fullPage: true })
  assert.equal(await page.getByRole('button', { name: 'HWPX 다운로드', exact: true }).isDisabled(), false)
  await download('hwpx')
  await open()
  await page.getByRole('button', { name: /서비스 제공기록지 · 제10호 · 검토 완료/ }).click()
  await page.getByTitle('실제 출력될 전마투 PDF').waitFor()
  assert.equal(await page.getByLabel('바우처 3회차 서비스 내용', { exact: true }).inputValue(), '합성사례: 긴장과 대처를 탐색함.')
  assert.equal(await page.getByLabel('바우처 3회차 추가 기록', { exact: true }).inputValue(), '')
  assert.deepEqual(await download(), first, 'reopened reviewed PDF is byte-identical')
  // Editing an approved document creates a new candidate with no inherited approval.
  await page.getByLabel('바우처 3회차 서비스 내용', { exact: true }).fill('합성사례: 수정한 기록.')
  assert.equal(await page.getByRole('button', { name: 'PDF 다운로드', exact: true }).count(), 0)
  await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
  await page.getByTitle('실제 출력될 전마투 PDF').waitFor()
  assert.equal(await page.getByRole('button', { name: 'PDF 다운로드', exact: true }).isDisabled(), true)
  await approve(); await download()
  await page.getByLabel('서식', { exact: true }).selectOption('form26')
  await page.getByLabel('서비스 목적', { exact: true }).fill('합성사례: 정서 이해를 돕는다.')
  await page.getByLabel('서비스 내용', { exact: true }).fill('감정과 대처방식을 탐색한다.')
  await page.getByLabel('서비스 제공계획', { exact: true }).fill('상담 목표를 함께 정한다.')
  await page.getByRole('button', { name: '출력 내용 확인', exact: true }).click()
  await page.getByTitle('실제 출력될 전마투 PDF').waitFor()
  await approve(); await download()
  await page.screenshot({ path: path.resolve('../tmp_ab/voucher-browser-plan.png'), fullPage: true })
  await download('hwpx')
  console.log('PASS: metadata-only mapping, legacy-response narrative discarded, manual entry required -> API -> PDF review -> PDF/HWPX download -> reopen -> edit/review; manual plan without source notes')
  }
  assert.deepEqual(errors, [])
} catch (error) {
  await page.screenshot({ path: path.resolve('../tmp_ab/voucher-browser-failure.png'), fullPage: true })
  console.error('UI alerts:', await page.getByRole('alert').allTextContents())
  console.error('Browser errors:', errors)
  throw error
} finally {
  for (const id of ids) await page.request.delete(`${origin}/api/documents/vouchers/saved/${id}`, { headers: { Authorization: 'Bearer synthetic-voucher-token' } })
  const cleanup = await (await page.request.get(`${origin}/api/fixture/remaining`)).json()
  assert.equal(cleanup.remaining, 0)
  console.log('Cleanup: zero synthetic voucher snapshots remain; no live accounts or rows created.')
  await browser.close()
  await server.close()
}
