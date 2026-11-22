import assert from 'node:assert/strict'
import fs from 'node:fs'
import ts from 'typescript'

// Synthetic data only. Client check-in helpers (내담자 수시 기록).
const source = fs.readFileSync('src/lib/clientCheckIns.ts', 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } })
const lib = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

// The emotion list and consent version match the backend schema and the database constraint.
const schema = fs.readFileSync('../backend/app/schemas/client_check_in.py', 'utf8')
const migration = fs.readFileSync('../supabase/migrations/20261122000100_client_check_ins.sql', 'utf8')
const quoted = (text) => [...text.matchAll(/'([^']+)'|"([^"]+)"/g)].map((m) => m[1] ?? m[2])
const backendEmotions = quoted(schema.match(/CHECK_IN_EMOTIONS = \(([^)]*)\)/)[1])
const dbEmotions = quoted(migration.match(/emotions <@ array\[([^\]]*)\]/)[1])
assert.deepEqual([...lib.CHECK_IN_EMOTIONS], backendEmotions)
assert.deepEqual([...lib.CHECK_IN_EMOTIONS], dbEmotions)
assert.ok(schema.includes(`CLIENT_CONSENT_VERSION = "${lib.CLIENT_CONSENT_VERSION}"`))
assert.ok(migration.includes(`char_length(note) <= ${lib.NOTE_MAX_LENGTH}`))

// Crisis contacts are shown again for very low moods or crisis words; ordinary notes do not trigger it.
assert.equal(lib.needsCrisisSupport(1, ''), true)
assert.equal(lib.needsCrisisSupport(0, '괜찮아요'), true)
assert.equal(lib.needsCrisisSupport(6, '그냥 사라지고 싶다는 생각이 들어요'), true)
assert.equal(lib.needsCrisisSupport(5, '죽고   싶어요'), true)
assert.equal(lib.needsCrisisSupport(4, '회의 전에 숨이 막혔어요.'), false)
assert.equal(lib.needsCrisisSupport(2, '피곤해요'), false)
assert.ok(lib.CRISIS_CONTACTS.some((contact) => contact.number === '109'))

// Invite links: the token survives the round trip; malformed tokens are ignored.
const token = 'Abc_def-0123456789xyzXYZ'
const url = lib.clientInviteUrl(token, 'https://remind.ai.kr/')
assert.equal(url, `https://remind.ai.kr/client?invite=${token}`)
assert.equal(lib.inviteTokenFrom(new URL(url).search), token)
assert.equal(lib.inviteTokenFrom('?invite=short'), '')
assert.equal(lib.inviteTokenFrom('?invite=<script>alert(1)</script>xxxxxxxxxxxx'), '')
assert.equal(lib.inviteTokenFrom(''), '')
assert.equal(lib.isClientPath('/client'), true)
assert.equal(lib.isClientPath('/client/'), true)
assert.equal(lib.isClientPath('/clients'), false)
assert.equal(lib.isClientPath('/'), false)

// Counselor view: entries since the last session date.
const entries = [
  { id: '3', mood: 2, emotions: [], note: '', created_at: '2026-11-20T09:00:00Z' },
  { id: '2', mood: 6, emotions: [], note: '', created_at: '2026-11-15T09:00:00Z' },
  { id: '1', mood: 4, emotions: [], note: '', created_at: '2026-11-10T09:00:00Z' },
]
assert.deepEqual(lib.entriesSince(entries, '2026-11-15').map((entry) => entry.id), ['3', '2'])
assert.equal(lib.entriesSince(entries, null).length, 3)
assert.equal(lib.moodLabel(0), '매우 힘듦')
assert.equal(lib.moodLabel(10), '좋음')

console.log('client check-in checks passed')
