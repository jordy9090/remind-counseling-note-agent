import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

// Synthetic data only. Exercises the pure helpers the case list / client dashboard screens rely on.
async function loadModule(name) {
  const source = fs.readFileSync(`src/lib/${name}.ts`, 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}
const lib = await loadModule('caseList')

const item = (overrides) => ({
  case_id: 'SYNTHETIC-1', case_alias: null, status: 'active', created_at: null, updated_at: null,
  total_session_count: 0, latest_session_number: null, first_consultation_date: null, latest_consultation_date: null,
  total_scheduled_session_count: null, next_scheduled_date: null, transcript_completed_count: 0,
  confirmed_note_count: 0, draft_note_count: 0, document_count: 0, export_count: 0, temporary_draft_count: 0,
  ...overrides,
})

{
  assert.equal(lib.caseStatusLabel('active'), '진행중')
  assert.equal(lib.caseStatusLabel('closed'), '종결')
  assert.equal(lib.caseStatusLabel('paused'), '대기중')
  assert.equal(lib.caseStatusLabel(undefined), '진행중')
  assert.equal(lib.caseDisplayName({ case_id: 'C-1', case_alias: ' 가명 ' }), '가명')
  assert.equal(lib.caseDisplayName({ case_id: 'C-1', case_alias: 'C-1' }), 'C-1')
  assert.equal(lib.caseDisplayName({ case_id: 'C-1', case_alias: null }), 'C-1')
  console.log('status labels and display names: passed')
}

{
  const cases = [
    item({ case_id: 'A-1', case_alias: '합성 가명', status: 'active' }),
    item({ case_id: 'B-2', status: 'closed' }),
    item({ case_id: 'C-3', status: 'paused' }),
  ]
  assert.deepEqual(lib.filterCases(cases, 'all', '').map((c) => c.case_id), ['A-1', 'B-2', 'C-3'])
  assert.deepEqual(lib.filterCases(cases, 'active', '').map((c) => c.case_id), ['A-1', 'C-3'])
  assert.deepEqual(lib.filterCases(cases, 'closed', '').map((c) => c.case_id), ['B-2'])
  assert.deepEqual(lib.filterCases(cases, 'all', ' 가명').map((c) => c.case_id), ['A-1'])
  assert.deepEqual(lib.filterCases(cases, 'all', 'b-2').map((c) => c.case_id), ['B-2'])
  assert.deepEqual(lib.filterCases(cases, 'closed', 'A-1'), [])
  console.log('status filter and search: passed')
}

{
  assert.equal(lib.nextSessionNumber([]), 1)
  assert.equal(lib.nextSessionNumber([{ session_number: 1 }, { session_number: 3 }]), 4)
  assert.equal(lib.nextSessionNumber([{ session_number: 1 }], [{ session_number: 5 }]), 6)
  assert.equal(lib.nextSessionNumber([{ session_number: 0 }, { session_number: -2 }]), 1)
  console.log('next session number: passed')
}

{
  const dashboard = {
    sessions: [
      { session_id: 's1', session_number: 1, session_date: '2026-09-01', session_title: '', summary: null, transcript_status: 'completed', note_confirmation_status: 'confirmed' },
      { session_id: 's2', session_number: 2, session_date: null, session_title: '', summary: null, transcript_status: 'none', note_confirmation_status: 'draft' },
    ],
    documents: [
      { document_id: 'old', document_type: 'session_note', title: '1회기 회기 기록', status: 'draft', session_number: 1, created_at: '2026-09-01T01:00:00Z' },
      { document_id: 'new', document_type: 'session_note', title: '1회기 회기 기록', status: 'confirmed', session_number: 1, created_at: '2026-09-01T02:00:00Z' },
      { document_id: 'sup', document_type: 'supervision_report', title: '2회기 수퍼비전 보고서', status: 'draft', session_number: 2, created_at: '2026-09-02T00:00:00Z' },
      { document_id: 'unlinked', document_type: 'session_note', title: '회기 기록', status: 'draft', session_number: null, created_at: '2026-09-03T00:00:00Z' },
    ],
  }
  const drafts = [
    { draft_id: 'd-old', case_id: 'X', session_number: 3, saved_at: '2026-09-03T00:00:00Z' },
    { draft_id: 'd-new', case_id: 'X', session_number: 3, saved_at: '2026-09-04T00:00:00Z' },
    { draft_id: 'd-1', case_id: 'X', session_number: 1, saved_at: '2026-09-01T00:00:00Z' },
  ]
  const groups = lib.groupSessionRecords(dashboard, drafts)
  assert.deepEqual(groups.map((g) => g.sessionNumber), [3, 2, 1], 'newest session first, draft-only session included')
  assert.equal(groups[0].session, null)
  assert.deepEqual(groups[0].drafts.map((d) => d.draft_id), ['d-new', 'd-old'])
  assert.equal(groups[1].latestNote, null, 'supervision reports are not restorable session notes')
  assert.equal(groups[1].documents.length, 1)
  assert.equal(groups[2].latestNote.document_id, 'new', 'latest session note wins')
  assert.equal(groups[2].documents.length, 2)
  assert.deepEqual(groups[2].drafts.map((d) => d.draft_id), ['d-1'])
  assert.deepEqual(lib.summaryStatusLabel(groups[2].latestNote), { label: '검토 완료', tone: 'confirmed' })
  assert.deepEqual(lib.summaryStatusLabel(groups[1].latestNote), { label: '요약 없음', tone: 'none' })
  assert.deepEqual(lib.summaryStatusLabel({ status: 'draft' }), { label: 'AI 초안', tone: 'draft' })
  assert.equal(lib.transcriptStatusLabel('completed'), '축어록 완료')
  assert.equal(lib.transcriptStatusLabel(undefined), '축어록 없음')
  console.log('session record grouping: passed')
}

{
  const withStatus = (status, detail) => ({ response: { status, data: { detail } } })
  assert.match(lib.caseRequestErrorMessage(withStatus(401)), /로그인/)
  assert.match(lib.caseRequestErrorMessage(withStatus(403)), /다른 사용자/)
  assert.match(lib.caseRequestErrorMessage(withStatus(404)), /저장된 기록이 없습니다/)
  assert.match(lib.caseRequestErrorMessage(withStatus(503)), /Supabase/)
  assert.equal(lib.caseRequestErrorMessage(withStatus(500, '서버 상세')), '서버 상세')
  assert.equal(lib.caseRequestErrorMessage(new Error('네트워크')), '네트워크')
  assert.equal(lib.caseRequestErrorMessage({}), '케이스 정보를 불러오지 못했습니다.')
  console.log('error messages: passed')
}

// Static wiring checks against the page and client.
{
  const page = fs.readFileSync('src/pages/SessionDraftPage.tsx', 'utf8')
  const client = fs.readFileSync('src/api/client.ts', 'utf8')
  assert.match(client, /client\.get<CaseListResponse>\('\/api\/cases'\)/, 'case list must call GET /api/cases')
  assert.match(page, /fetchCaseList\(\)/, 'page must load the owned case list from the API')
  assert.doesNotMatch(page, /const caseSummaries: CaseSummary\[\] = \[\]/, 'hard-coded empty case list must be gone')
  assert.match(page, /'client_detail'/, 'client detail screen must exist')
  assert.match(page, /createCase\(payload\)/, 'client creation must call the create API')
  assert.match(page, /updateCaseProfile\(clientModal\.caseId, payload\)/, 'profile edit must call the profile API')
  assert.match(page, /<GeneratingOverlay active=\{isLoading\} \/>/, 'generation overlay must reflect loading state')
  assert.match(page, /onStartSession=\{startSessionForCase\}/, 'client detail must open the session record modal')
  assert.match(page, /onOpenNote=\{restoreNote\}/, 'dashboard must open stored notes through the existing restore flow')
  assert.match(page, /onOpenDraft=\{restoreTemporary\}/, 'dashboard must open temporary drafts through the existing restore flow')
  console.log('page/client wiring: passed')
}
