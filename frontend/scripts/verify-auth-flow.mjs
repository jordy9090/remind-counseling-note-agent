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

// 2. Landing 동선: 로그인 → 로그인 화면, 무료로 시작하기 → 회원가입 화면
assert(/onLogin/.test(landing) && /onSignup/.test(landing), 'LandingPage must expose onLogin/onSignup')
assert(!/onStart/.test(landing), 'LandingPage must not keep the old onStart prop')
assert(/>로그인</.test(landing), 'Landing header must render a 로그인 button')
assert(/onClick=\{onSignup\}[^>]*>무료로 시작하기/.test(landing), '무료로 시작하기 must open signup')
assert(/onLogin=\{\(\) => openAuth\('signin'\)\}/.test(authGate), 'AuthGate must route onLogin to signin')
assert(/onSignup=\{\(\) => openAuth\('signup'\)\}/.test(authGate), 'AuthGate must route onSignup to signup')

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

console.log('verify-auth-flow: OK')
console.log('  - anonymous entry removed')
console.log('  - landing 로그인/무료로 시작하기 routed to signin/signup')
console.log('  - signup/login/logout/verify-resend/password-reset present')
console.log('  - workspace gated on session; token attached to API calls')
