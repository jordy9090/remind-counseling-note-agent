import fs from 'node:fs'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const hook = fs.readFileSync('src/hooks/useCounselorDemo.ts', 'utf8')
const page = fs.readFileSync('src/pages/CounselorDemoPage.tsx', 'utf8')
const fixture = fs.readFileSync('src/data/counselorDemoFixture.ts', 'utf8')

assert(hook.includes('generateNoteDraft(COUNSELOR_DEMO_SESSION_INPUT)'), 'demo must call note generation')
assert(hook.includes('generateSupervisionReport({'), 'demo must call backend supervision generation')
assert(hook.includes('report.evidenceIndex'), 'demo must render the backend evidence index')
assert(hook.includes('full.retrieval_report'), 'demo must expose the backend retrieval report')
assert(page.includes('retrievalReport={retrievalReport}'), 'status card must use backend retrieval data')
assert(!page.includes('case_context_count: 3'), 'status card must not display invented retrieval counts')
assert(fixture.includes('persist: true'), 'demo generation must request a persistable note for confirmation deployments')
assert(page.includes('fixture fallback'), 'offline fixture fallback must be explicitly labeled')

console.log('counselor demo backend workflow verification passed')
