import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

async function loadConfig(env) {
  const source = fs.readFileSync('src/lib/apiOrigin.ts', 'utf8')
    .replaceAll('import.meta.env', JSON.stringify(env))
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

for (const config of [{ PROD: true }, { PROD: true, VITE_API_BASE_URL: 'https://api.remind.ai.kr/' }]) {
  const result = await loadConfig(config)
  assert.equal(result.API_BASE_URL, 'https://api.remind.ai.kr')
  assert.equal(result.AUDIO_API_BASE_URL, result.API_BASE_URL)
}
for (const badOrigin of ['https://remind.ai.kr', 'https://preview.vercel.app', '/api',
  'http://api.remind.ai.kr', 'https://api.remind.ai.kr.evil.invalid', 'https://api.remind.ai.kr/path']) {
  await assert.rejects(loadConfig({ PROD: true, VITE_API_BASE_URL: badOrigin }))
  await assert.rejects(loadConfig({ PROD: true, VITE_AUDIO_API_BASE_URL: badOrigin }))
}
assert.equal((await loadConfig({ PROD: false })).API_BASE_URL, '')
assert.equal((await loadConfig({ PROD: false, VITE_API_BASE_URL: 'http://localhost:8000/' })).API_BASE_URL,
  'http://localhost:8000')

// The retired API must stop at Vercel's routing layer, never proxy to the backend.
const deployment = JSON.parse(fs.readFileSync('../vercel.json', 'utf8'))
const frontendDeployment = JSON.parse(fs.readFileSync('vercel.json', 'utf8'))
assert.deepEqual(frontendDeployment.routes, deployment.routes)
assert.equal(frontendDeployment.outputDirectory, 'dist')
const retired = deployment.routes[0]
for (const path of ['/api', '/api/audio/transcribe', '/api/notes/drafts', '/api/documents/export']) {
  assert.ok(new RegExp(`^${retired.src}$`).test(path))
}
assert.equal(retired.status, 410)
assert.equal(retired.dest, undefined)
assert.equal(deployment.functions, undefined)
assert.equal(deployment.rewrites, undefined)
assert.equal(frontendDeployment.functions, undefined)
assert.equal(frontendDeployment.rewrites, undefined)
console.log('Direct API origins, fail-closed hosted configuration, and retired Vercel API: passed')
