import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'

const sourcePath = path.resolve('src/lib/materialWorkflow.ts')
const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), 'remind-material-workflow-'))
const outputPath = path.join(outputDir, 'materialWorkflow.mjs')

const source = fs.readFileSync(sourcePath, 'utf8')
const transpiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2020,
  },
})
fs.writeFileSync(outputPath, transpiled.outputText, 'utf8')

const { getUnappliedReadyMaterials } = await import(pathToFileURL(outputPath).href)

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

const readyPdf = {
  kind: 'document',
  status: 'completed',
  extractedText: '새로 업로드한 상담 자료',
  appliedTargets: [],
}
const appliedPdf = {
  ...readyPdf,
  appliedTargets: ['counselor_memo'],
}
const scanPdf = {
  kind: 'document',
  status: 'warning',
  extractedText: '',
  appliedTargets: [],
}
const selectedAudio = {
  kind: 'audio',
  status: 'selected',
  transcriptText: '',
  appliedTargets: [],
}
const staleAudio = {
  kind: 'audio',
  status: 'transcribed',
  transcriptText: '수정된 축어록',
  appliedTargets: ['transcript_text', 'nonverbal_notes'],
  dirtySinceApply: true,
}

assert(
  getUnappliedReadyMaterials([readyPdf]).length === 1,
  'existing demo form text must not hide an unapplied ready PDF',
)
assert(getUnappliedReadyMaterials([appliedPdf]).length === 0, 'applied PDF must allow submit')
assert(getUnappliedReadyMaterials([]).length === 0, 'deleted PDF must allow submit')
assert(getUnappliedReadyMaterials([scanPdf]).length === 0, 'scan PDF without text must not block as ready')
assert(getUnappliedReadyMaterials([selectedAudio]).length === 0, 'audio without transcript must not block as ready')
assert(getUnappliedReadyMaterials([staleAudio]).length === 1, 'edited audio after apply must block until re-applied')

fs.rmSync(outputDir, { recursive: true, force: true })
console.log('material workflow verification passed')
