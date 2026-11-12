import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

// A real browser, real review API and real Qwen; generation is explicitly stubbed
// by serve_iwinv_review_check.py. No synthetic account or database row is created.
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')
const root = fileURLToPath(new URL('../dist/', import.meta.url))
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) {
    const upstream = http.request({ hostname: '127.0.0.1', port: 8787, path: req.url, method: req.method,
      headers: { ...req.headers, host: '127.0.0.1:8787' } }, response => {
      res.writeHead(response.statusCode, response.headers); response.pipe(res)
    })
    upstream.on('error', () => { res.writeHead(503); res.end() })
    req.pipe(upstream)
    return
  }
  let file = path.resolve(root, '.' + decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname))
  if (file !== path.resolve(root) && !file.startsWith(path.resolve(root) + path.sep)) { res.writeHead(404); res.end(); return }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html')
  res.setHeader('Content-Type', file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.png') ? 'image/png' : 'text/html')
  res.end(fs.readFileSync(file))
})
await new Promise(resolve => server.listen(4189, '127.0.0.1', resolve))
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH })
const page = await browser.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
await page.route('https://synthetic.supabase.co/**', route => route.fulfill({ json: { external: {} } }))
let submitted = null
await page.route('**/api/notes/quick-summary', async route => {
  submitted = { body: route.request().postDataJSON(), headers: route.request().headers() }
  await route.continue()
})
try {
  await page.goto('http://127.0.0.1:4189')
  const text = '내담자: 제 이름은 윤가온입니다. 전화는 010-0000-3141이며 gaon@example.invalid로 연락해요. 가상누리병원에 다닙니다. 약 5mg은 2주 동안 복용하지 않았어요. 검사점수는 72점입니다.\n상담자: 복용하지 않았다는 말씀을 확인했어요.'
  await page.getByLabel('상담 내용 파일 선택').setInputFiles({ name: 'synthetic-only.txt', mimeType: 'text/plain', buffer: Buffer.from(text) })
  assert.equal(await page.getByLabel('요약할 상담 내용').inputValue(), text)
  await page.getByRole('button', { name: '요약하기', exact: true }).click()
  await page.getByRole('button', { name: '정리 없이 다음으로', exact: true }).click()
  await page.getByRole('dialog', { name: 'AI로 보내기 전 내용 확인' }).waitFor({ timeout: 120000 })
  const submit = page.getByRole('button', { name: '확인한 내용으로 AI 처리하기', exact: true })
  assert.equal(await submit.isEnabled(), false)
  assert.equal(await page.getByRole('switch', { name: '비식별화 검토 건너뛰기' }).count(), 0)
  assert.equal(submitted, null)
  await page.getByRole('tab', { name: 'AI 전달용', exact: true }).click()
  await page.getByText('표시된 항목과 AI에 전달할 내용을 모두 확인했어요.').click()
  assert.equal(await submit.isEnabled(), true)
  await submit.click()
  await page.getByRole('article', { name: 'AI 요약 결과' }).waitFor({ timeout: 30000 })
  assert.ok(submitted.headers['x-review-receipt'])
  for (const value of ['윤가온', '010-0000-3141', 'gaon@example.invalid', '가상누리병원']) assert.ok(!submitted.body.text.includes(value), 'Identifier reached generation')
  for (const value of ['5mg', '2주', '복용하지 않았어요', '72점']) assert.ok(submitted.body.text.includes(value), 'Clinical fact changed')
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log('PASS: real Qwen, TXT upload, mandatory review, receipt, masked generation payload, clinical facts, rendered result; no DB data')
} finally {
  await browser.close()
  server.close()
}
