// Static verification of the email auth flow wiring (no anonymous entry).
// Run: pnpm verify:auth-flow
import fs from 'node:fs'
import path from 'node:path'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}
const read = (relative) => fs.readFileSync(path.resolve(relative), 'utf8')

const authGate = read('src/components/AuthGate.tsx')
const landing = read('src/pages/LandingPage.tsx')
const app = read('src/App.tsx')
const client = read('src/api/client.ts')
const supabase = read('src/lib/supabase.ts')

// 1. 익명 진입 제거
assert(!/signInAnonymously/.test(authGate), 'AuthGate must not call signInAnonymously')
assert(!/signInAnonymously/.test(landing), 'LandingPage must not call signInAnonymously')

// 2. Landing = 비로그인 간편 요약: 서버 저장 없음. '로그인 후 저장하기' → 로그인 → 로그인한 상담사처럼 자동 저장
assert(/onLogin/.test(landing) && !/onSaveRequiresLogin/.test(landing), 'LandingPage routes 로그인 후 저장하기 through onLogin')
assert(!/onStart/.test(landing), 'LandingPage must not keep the old onStart prop')
assert(/>\s*로그인 \/ 회원가입\s*</.test(landing), 'Landing header must render a 로그인 / 회원가입 button')
assert(/QuickSummaryPanel/.test(landing), 'Landing must render the quick summary')
assert(/label: '로그인 후 저장하기'/.test(landing), 'Landing must offer 로그인 후 저장하기')
assert(/storePendingQuickSummary\(summary\)\s*onLogin\(\)/.test(landing), '로그인 후 저장하기 keeps the summary, then opens login')
assert(/if \(!next\) clearPendingQuickSummary\(\)/.test(landing), '새로 요약하기 drops a summary waiting for login')
const panel = read('src/components/quick-summary/QuickSummaryPanel.tsx')
assert(!/'저장하기'/.test(panel) && /saveAction\?:/.test(panel), 'The panel has no fixed save button, only an optional save action')
const quickWorkspace = read('src/components/quick-summary/QuickSummaryWorkspace.tsx')
assert(/saveTemporaryDraft\(temporaryDraftPayload\(quickSummaryDraftPayload\(next\)\)\)/.test(quickWorkspace),
  'Signed-in quick summaries must be saved automatically')
assert(/const pending = takePendingQuickSummary\(\)[\s\S]{0,200}handleResult\(pending\)/.test(quickWorkspace),
  'A summary waiting for login must be saved through the same auto-save path')
assert(/label: '내담자에 저장하기', onSave: onSaveToClient/.test(quickWorkspace), 'Signed-in users can save a summary to a client')
assert(/handleResult\(pending\)\s*onSaveToClient\(pending\)/.test(quickWorkspace), 'A summary waiting for login opens the client picker')
const page = read('src/pages/SessionDraftPage.tsx')
assert(/const cancelQuickClientSave = \(\) => \{[^}]*setQuickClientSave\(null\)/.test(page) && /onClose=\{cancelQuickClientSave\}/.test(page),
  'Closing the client picker abandons the quick-summary save')
assert(/clientModal\.purpose === 'quick-summary' \? quickClientSave : null/.test(page),
  'Only a client created from the quick-summary picker receives the summary')
assert(/saveQuickSummaryToClient\(caseId, summary\)/.test(page), 'The summary is saved as a session of the chosen client')
assert(/onLogin=\{\(\) => openAuth\('signin'\)\}/.test(authGate), 'AuthGate must route onLogin to signin')
assert(/setMode\('signup'\)/.test(authGate), 'Login modal must link to signup')

// 3. 이메일 인증 기능 존재
for (const call of ['signInWithPassword', 'signUp(', 'resetPasswordForEmail', 'updateUser({ password })', 'signOut()', "resend({ type: 'signup'"]) {
  assert(authGate.includes(call), `AuthGate must call ${call}`)
}
assert(/PASSWORD_RECOVERY/.test(authGate), 'AuthGate must handle PASSWORD_RECOVERY')
assert(/SIGNED_OUT/.test(authGate), 'AuthGate must reset UI on SIGNED_OUT')
assert(/emailRedirectTo: window\.location\.origin/.test(authGate), 'signup must redirect back to the app origin')

// 4. 비로그인 사용자의 workspace 차단: App은 AuthGate 안에서만 SessionDraftPage를 렌더
assert(/<AuthGate><SessionDraftPage \/><\/AuthGate>/.test(app), 'App must wrap SessionDraftPage in AuthGate')
assert(/if \(!session\)/.test(authGate), 'AuthGate must gate on session')

// 5. 세션 유지 + API 토큰 전달
for (const flag of ['persistSession: true', 'autoRefreshToken: true', 'detectSessionInUrl: true']) {
  assert(supabase.includes(flag), `supabase client must set ${flag}`)
}
assert(/getAccessToken/.test(client) && /Authorization = `Bearer \$\{accessToken\}`/.test(client), 'API client must attach the Supabase access token')

// 5. 보안 조치: 원문 저장 설정 키, 원문 삭제 경로, 내담자 연락처 미수집
const preference = read('src/lib/storagePreference.ts')
const backendSecurity = read('../backend/app/api/security.py')
const keyMatch = /ORIGINAL_INPUT_PREFERENCE_KEY = '([a-z_]+)'/.exec(preference)
assert(keyMatch && backendSecurity.includes(`ORIGINAL_INPUT_PREFERENCE_KEY = "${keyMatch[1]}"`),
  'The 원문 저장 preference key must match the backend guard')
assert(/\/input-deletion`/.test(client) && read('../backend/app/api/routes/notes.py').includes('"/records/{note_id}/input-deletion"'),
  'The 원문 삭제 client path must match the backend route')
assert(!/client_phone|client_email/.test(read('src/components/clients/ClientFormModal.tsx')), 'The client form must not collect phone or email')

console.log('verify-auth-flow: OK')
console.log('  - anonymous entry removed')
console.log('  - landing quick summary saves nothing until 로그인 후 저장하기; signed-in summaries save automatically')
console.log('  - signup/login/logout/verify-resend/password-reset present')
console.log('  - workspace gated on session; token attached to API calls')
