import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
// Start the synthetic export API on 8187 and Vite on 4187 with VITE_API_BASE_URL pointing to it.
// PLAYWRIGHT_MODULE may select the bundled runtime; REMIND_PYTHON selects the backend environment.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const browser = await chromium.launch({channel: 'msedge', headless: true})
const output = path.resolve('../output/validation/hwpx-supervision-form')
fs.mkdirSync(output, {recursive: true})
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1100}, acceptDownloads: true})
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/src/fixtures/dev/local-live-result.json', route => route.fulfill({status: 404, body: ''}))
  // Use the actual generator's synthetic reference-form report, not the older generic UI demo.
  const report = JSON.parse(execFileSync(process.env.REMIND_PYTHON || 'python', ['-c',
    'from test_supervision_form import request_for; from app.graph.supervision_report import run_supervision_report_pipeline; print(run_supervision_report_pipeline(request_for(maximum_sessions=12)).model_dump_json(by_alias=True))',
  ], {cwd: path.resolve('../backend'), encoding: 'utf8', windowsHide: true}))
  await page.route('**/src/fixtures/dev/groundingDemo.ts', async route => {
    const response = await route.fetch()
    const body = await response.text()
    const start = body.indexOf('export const groundingDemoSupervisionReport =')
    assert(start >= 0, 'Vite fixture export must be present')
    await route.fulfill({response, body: body.slice(0, start) + 'export const groundingDemoSupervisionReport = ' + JSON.stringify(report) + ';'})
  })
  await page.goto('http://127.0.0.1:4187/?grounding-demo=1&screen=supervision')
  const button = page.getByRole('button', {name: '한글 (HWPX)', exact: true})
  await button.waitFor()
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === '한글 (HWPX)' && !b.disabled))
  const headers = await page.getByRole('table', {name: '회기 진행표'}).locator('thead').innerText()
  assert(headers.includes('최대 상담 가능 회기 수'))
  assert(headers.includes('날짜(소요시간)'))
  assert(headers.includes('회기 주제'))
  assert(!headers.includes('취소·지각·결석'))
  const cell = page.getByRole('textbox', {name: '회기 진행표 1행 회기 주제'})
  await cell.fill('브라우저에서 수정한 합성 회기 주제')
  const sent = page.waitForRequest(request => request.url().endsWith('/api/documents/export'))
  const downloadPromise = page.waitForEvent('download')
  await button.click()
  const payload = (await sent).postDataJSON()
  assert.equal(payload.format, 'hwpx')
  assert(payload.sections.some(s => s.content_blocks?.some(b => b.rows?.some(row => row['회기 주제'] === '브라우저에서 수정한 합성 회기 주제'))))
  const download = await downloadPromise
  assert(download.suggestedFilename().endsWith('.hwpx'))
  await download.saveAs(path.join(output, 'browser-supervision.hwpx'))
  await page.getByRole('status').filter({hasText: '한글 (HWPX) 다운로드를 시작했습니다.'}).waitFor()
  await page.screenshot({path: path.join(output, 'browser-supervision.png'), fullPage: true})
  const bytes = fs.readFileSync(path.join(output, 'browser-supervision.hwpx'))
  assert.equal(bytes.subarray(0,2).toString(), 'PK')
  // Capability failure must disable the button without sending another export.
  await page.route('**/api/documents/capabilities', route => route.fulfill({status: 503, body: '{}'}))
  await page.reload()
  await button.waitFor()
  assert(await button.isDisabled())
  assert.deepEqual(errors, [])
  console.log('PASS: reopened supervision, reference table, edited cell, real HWPX API/download, status, unavailable capability')
} finally {
  await browser.close()
}
