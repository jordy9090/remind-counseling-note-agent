import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const require = createRequire(import.meta.url)
const ts = require(process.env.TYPESCRIPT_MODULE || 'typescript')
const sourceRoot = fileURLToPath(new URL('../src/', import.meta.url))
const pendingKey = 'remind.quickSummary.pending'
const summary = {
  sections: [{ id: 'session_content', title: '상담 내용', content: 'Synthetic guest summary' }],
  deidentified: true,
}

function harness({ ownerId = null, pending = true, unavailableStorage = false } = {}) {
  const storage = new Map(pending ? [[pendingKey, JSON.stringify({ sections: summary.sections, savedAt: Date.now() })]] : [])
  const reads = [], writes = [], saves = [], results = [], clientSelections = []
  const window = { localStorage: {
    getItem(key) { reads.push(key); return storage.get(key) ?? null },
    setItem(key, value) { writes.push(key); storage.set(key, value) },
    removeItem(key) { if (unavailableStorage) throw new Error('Synthetic storage failure'); storage.delete(key) },
  } }
  let cursor = 0
  const slots = [], effects = [], cleanups = []
  const react = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial
      return [slots[index], value => { slots[index] = typeof value === 'function' ? value(slots[index]) : value }]
    },
    useRef(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = { current: initial }
      return slots[index]
    },
    useEffect(callback, dependencies) {
      const index = cursor++
      if (!(index in slots) || dependencies.some((value, offset) => value !== slots[index][offset])) {
        effects.push(() => { cleanups[index]?.(); cleanups[index] = callback() })
        slots[index] = dependencies
      }
    },
  }
  const panel = Symbol('QuickSummaryPanel')
  const jsx = (type, props) => ({ type, props })
  const mocks = {
    react,
    'react/jsx-runtime': { jsx, jsxs: jsx, Fragment: Symbol('Fragment') },
    'lucide-react': { Check: Symbol('Check'), History: Symbol('History'), Loader2: Symbol('Loader2'), LogOut: Symbol('LogOut') },
    'src/components/quick-summary/QuickSummaryPanel': { default: panel },
    'src/pages/SessionDraftPage': { quickSummaryResultFromNote: value => value },
    'src/lib/authSession': { useAuthSession: () => ({ userId: ownerId }), displayNameFromEmail: () => 'Synthetic counselor' },
    'src/lib/storagePreference': { readStoreOriginalInput: async () => true, writeStoreOriginalInput: async () => {} },
    'src/components/app-shell/ui': { ClientAvatar: Symbol('ClientAvatar'), OutlineButton: Symbol('OutlineButton') },
    'src/lib/unsavedWork': { useUnsavedWork: () => {} },
    'src/api/client': {
      listTemporaryDrafts: async () => saves.map(({ draft }) => ({ ...draft, saved_at: '2026-11-19T00:00:00Z' })),
      saveTemporaryDraft: async (draft, scope) => { saves.push({ draft, ownerId: scope.ownerId }); return { draft_id: draft.draft_id } },
      isRetryableRequestError: () => false,
      persistenceErrorMessage: () => 'Synthetic failure',
      getNoteStoragePolicy: async () => ({ persistence_enabled: true, save_original_input: false, save_raw_input: false,
        account_store_original_input: true, generated_note_raw_input_mode: 'omitted' }),
    },
  }
  const cache = new Map()
  function load(relative) {
    if (mocks[relative]) return mocks[relative]
    if (cache.has(relative)) return cache.get(relative).exports
    const filename = ['.ts', '.tsx'].map(extension => path.join(sourceRoot, relative.slice(4) + extension)).find(candidate => fs.existsSync(candidate))
    assert.ok(filename, 'The isolated loader accepts only local TypeScript modules or explicit mocks')
    const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
    }).outputText
    const module = { exports: {} }
    cache.set(relative, module)
    const requireLocal = dependency => {
      if (mocks[dependency]) return mocks[dependency]
      assert.ok(dependency.startsWith('.'), 'Unmocked external modules are forbidden')
      return load(path.posix.normalize(path.posix.join(path.posix.dirname(relative), dependency)))
    }
    new Function('require', 'module', 'exports', 'window', 'crypto', compiled)(
      requireLocal, module, module.exports, window, { randomUUID: () => '00000000-0000-4000-8000-000000000001' },
    )
    return module.exports
  }
  const workspaceProps = { result: null, onResult: value => results.push(value), toResult: value => value, onSaveToClient: value => clientSelections.push(value) }
  function render(component, props) {
    cursor = 0
    const tree = load(component).default(props)
    for (const run of effects.splice(0)) run()
    return tree
  }
  return {
    storage, reads, writes, saves, results, clientSelections, panel, load, render, workspaceProps,
    unmount: () => { for (const cleanup of cleanups) cleanup?.() },
  }
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined
  if (predicate(tree)) return tree
  const children = [tree.props?.children].flat(Infinity)
  for (const child of children) {
    const found = find(child, predicate)
    if (found) return found
  }
}

test('guest results stay on the landing page without a save-after-login action', () => {
  const h = harness({ pending: false })
  let loginRequests = 0
  const props = { onLogin: () => { loginRequests += 1 } }
  let tree = h.render('src/pages/LandingPage', props)
  let panel = find(tree, node => node.type === h.panel)
  assert.ok(panel)
  assert.equal(panel.props.saveAction, undefined, 'Guests must not be offered persistent handoff')
  panel.props.onResult(summary)
  tree = h.render('src/pages/LandingPage', props)
  panel = find(tree, node => node.type === h.panel)
  assert.deepEqual(panel.props.result, summary)
  find(tree, node => node.type === 'button').props.onClick()
  assert.equal(loginRequests, 1)
  assert.equal(h.writes.length, 0)
  assert.equal(h.saves.length, 0)
  h.unmount()
})

test('landing discards a legacy pending summary without reading its content', () => {
  const h = harness()
  h.render('src/pages/LandingPage', { onLogin() {} })
  assert.equal(h.storage.has(pendingKey), false)
  assert.equal(h.reads.length, 0)
  assert.equal(h.writes.length, 0)
  h.unmount()
})

test('a new account discards legacy guest state without displaying or saving it', async () => {
  const h = harness({ ownerId: 'synthetic-user-b' })
  h.render('src/components/quick-summary/QuickSummaryWorkspace', h.workspaceProps)
  await Promise.resolve()
  assert.equal(h.saves.length, 0, 'Login must not save another browser user\'s guest result')
  assert.equal(h.results.length, 0)
  assert.equal(h.clientSelections.length, 0)
  assert.equal(h.storage.has(pendingKey), false)
  assert.equal(h.reads.length, 0)
  h.unmount()
})

test('signed-in creation retains owned save, reopen, copy and client-save behavior', async () => {
  const h = harness({ ownerId: 'synthetic-user-a', pending: false })
  const tree = h.render('src/components/quick-summary/QuickSummaryWorkspace', h.workspaceProps)
  const panel = find(tree, node => node.type === h.panel)
  panel.props.onResult(summary)
  await Promise.resolve()
  assert.equal(h.saves.length, 1)
  assert.equal(h.saves[0].ownerId, 'synthetic-user-a')
  const quick = h.load('src/lib/quickSummary')
  const reopened = quick.quickSummaryFromDraft(h.saves[0].draft)
  assert.deepEqual(reopened, summary)
  assert.ok(quick.quickSummaryText(reopened).includes(summary.sections[0].content))
  panel.props.saveAction.onSave(reopened)
  assert.deepEqual(h.clientSelections, [summary])
  assert.equal(h.writes.length, 0)
  h.unmount()
})

test('unavailable browser storage does not block the signed-in workspace', () => {
  const h = harness({ ownerId: 'synthetic-user-b', unavailableStorage: true, pending: false })
  assert.doesNotThrow(() => h.render('src/components/quick-summary/QuickSummaryWorkspace', h.workspaceProps))
  assert.equal(h.saves.length, 0)
  h.unmount()
})

test('PoC storage policy overrides an account preference to store original input', async () => {
  const h = harness({ ownerId: 'synthetic-user-a', pending: false })
  h.render('src/components/settings/SettingsPage', {})
  for (let index = 0; index < 6; index++) await Promise.resolve()
  const tree = h.render('src/components/settings/SettingsPage', {})
  const toggle = find(tree, node => node.type === 'button' && node.props.role === 'switch')
  assert.equal(toggle.props['aria-checked'], false)
  assert.equal(toggle.props.disabled, true)
  assert.equal(JSON.stringify(tree).includes('지금은 원문을 저장해요.'), false)
  h.unmount()
})

test('the public landing routes summary creation to login before any processing', () => {
  const h = harness({ pending: false })
  let loginRequests = 0
  const tree = h.render('src/pages/LandingPage', { onLogin: () => { loginRequests += 1 } })
  const panel = find(tree, node => node.type === h.panel)
  assert.equal(typeof panel.props.onGenerationRequiresLogin, 'function')
  const source = fs.readFileSync(path.join(sourceRoot, 'components/quick-summary/QuickSummaryPanel.tsx'), 'utf8')
  const ast = ts.createSourceFile('panel.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let callback
  const visit = node => {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'summarize') callback = node.initializer.getText(ast)
    ts.forEachChild(node, visit)
  }
  visit(ast)
  const output = ts.transpileModule('const summarize = ' + callback, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  // Any attempt to touch input or AI state before the login guard raises an unbound-variable error.
  new Function('onGenerationRequiresLogin', output + '\nsummarize()')(panel.props.onGenerationRequiresLogin)
  assert.equal(loginRequests, 1)
  h.unmount()
})
