import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'

const require = createRequire(import.meta.url)
const ts = require(process.env.TYPESCRIPT_MODULE || 'typescript')
const hostSource = fs.readFileSync(new URL('../src/components/deidentification/AIReviewHost.tsx', import.meta.url), 'utf8')
const compiled = ts.transpileModule(hostSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
}).outputText
const flush = async () => { for (let index = 0; index < 6; index++) await Promise.resolve() }

function harness() {
  let cursor = 0, handler, userId = 'synthetic-owner'
  const slots = [], effects = [], cleanups = [], prepareCalls = [], detectCalls = [], confirmCalls = []
  const resolved = [], rejected = []
  const controller = new AbortController()
  const task = { purpose: 'generate', payload: { text: 'Synthetic current text' }, ownerId: userId, signal: controller.signal,
    resolve: value => resolved.push(value), reject: value => rejected.push(value) }
  const prepared = { payload: { text: 'Synthetic current text', history: 'Synthetic owned previous text' },
    sources: [{ key: 'text', label: '현재 자료', text: 'Synthetic current text' },
      { key: 'history', label: '이전 회기', text: 'Synthetic owned previous text' }],
    items: [], model_used: false, preparation_token: 'synthetic-prepared', requires_detection_approval: true }
  const preview = { ...prepared, model_used: true, detection_token: 'synthetic-detected' }
  const reviewModal = Symbol('final-review')
  const shell = Symbol('shell')
  const react = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = initial
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
  const jsx = (type, props) => ({ type, props })
  const mocks = {
    react,
    'react/jsx-runtime': { jsx, jsxs: jsx },
    '../../api/client': {
      prepareAIReview: async (...args) => { prepareCalls.push(args); return structuredClone(prepared) },
      startAIReview: async (...args) => { detectCalls.push(args); return structuredClone(preview) },
      confirmAIReview: async (...args) => { confirmCalls.push(args); return { payload: preview.payload, receipt: 'synthetic-approved' } },
    },
    '../../lib/aiReview': { registerAIReview: next => { handler = next; return () => { handler = null } } },
    '../../lib/authSession': { useAuthSession: () => ({ userId }) },
    '../../lib/deidentificationReview': { detectLocalDeidItems: () => [], findDeidMatches: () => [], newDeidItemId: () => 'synthetic-item' },
    '../app-shell/ModalShell': { default: shell },
    './DeidentificationReviewModal': { default: reviewModal },
  }
  const module = { exports: {} }
  new Function('require', 'module', 'exports', compiled)(name => {
    assert.ok(mocks[name], 'All component dependencies must be mocked')
    return mocks[name]
  }, module, module.exports)
  function render() {
    cursor = 0
    const tree = module.exports.default()
    for (const run of effects.splice(0)) run()
    return tree
  }
  render()
  handler(task)
  return { render, prepared, task, controller, prepareCalls, detectCalls, confirmCalls, resolved, rejected, reviewModal, shell,
    setOwner: value => { userId = value },
    close: () => { for (const cleanup of cleanups) cleanup?.() },
  }
}

function find(tree, predicate) {
  if (!tree || typeof tree !== 'object') return undefined
  if (predicate(tree)) return tree
  for (const child of [tree.props?.children, tree.props?.footer].flat(Infinity)) {
    const found = find(child, predicate)
    if (found) return found
  }
}

test('preparation displays current and owned prior text without calling the detector', async () => {
  const h = harness()
  h.render()
  await flush()
  const tree = h.render()
  assert.equal(h.prepareCalls.length, 1)
  assert.equal(h.detectCalls.length, 0, 'The detector must wait for explicit approval')
  for (const source of h.prepared.sources) assert.ok(JSON.stringify(tree).includes(source.text))
  const approval = find(tree, node => node.type === 'input' && node.props.type === 'checkbox')
  assert.equal(approval.props.checked, false)
  const submit = find(tree, node => node.type === 'button' && node.props.children === '개인정보 찾기')
  assert.equal(submit.props.disabled, true)
  h.close()
})

test('detection and final approval use the exact prepared payload and token', async () => {
  const h = harness()
  h.render()
  await flush()
  let tree = h.render()
  assert.equal(h.detectCalls.length, 0)
  find(tree, node => node.type === 'input').props.onChange({ target: { checked: true } })
  tree = h.render()
  const button = find(tree, node => node.type === 'button' && node.props.children === '개인정보 찾기')
  assert.equal(button.props.disabled, false)
  await button.props.onClick()
  await flush()
  assert.equal(h.detectCalls.length, 1)
  assert.deepEqual(h.detectCalls[0][0].payload, h.prepared.payload)
  assert.equal(h.detectCalls[0][2], h.prepared.preparation_token)
  assert.equal(h.resolved.length, 0, 'Detection approval does not approve summary generation')
  tree = h.render()
  await find(tree, node => node.type === h.reviewModal).props.onConfirm({ fullItems: [] })
  await flush()
  assert.equal(h.confirmCalls.length, 1)
  assert.deepEqual(h.confirmCalls[0][0].payload, h.prepared.payload)
  assert.equal(h.resolved.length, 1)
  h.close()
})

test('cancellation before approval invokes no detector', async () => {
  const h = harness()
  h.render()
  await flush()
  const tree = h.render()
  find(tree, node => node.type === h.shell).props.onClose()
  await flush()
  assert.equal(h.detectCalls.length, 0)
  assert.equal(h.rejected.length, 1)
  assert.equal(h.render(), null)
  h.close()
})

test('an account change invalidates the prepared review before detection', async () => {
  const h = harness()
  h.render()
  await flush()
  h.setOwner('synthetic-other-owner')
  h.render()
  await flush()
  assert.equal(h.detectCalls.length, 0)
  assert.equal(h.rejected.length, 1)
  assert.equal(h.render(), null)
  h.close()
})

test('the transport keeps prepared payload, approval and owner on every detector poll', async () => {
  const source = fs.readFileSync(new URL('../src/api/client.ts', import.meta.url), 'utf8')
  const ast = ts.createSourceFile('client.ts', source, ts.ScriptTarget.Latest, true)
  const selected = ast.statements.filter(node => ts.isFunctionDeclaration(node)
    && ['prepareAIReview', 'startAIReview'].includes(node.name?.text)).map(node => node.getText(ast)).join('\n')
  assert.ok(selected.includes('prepareAIReview'))
  const output = ts.transpileModule(selected, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText
  const calls = []
  const payload = { text: 'Synthetic current text', history: 'Synthetic owned history' }
  const client = { post: async (url, body, options) => {
    calls.push({ url, body, options })
    if (url.endsWith('-prepare')) return { data: { payload, preparation_token: 'synthetic-approved-for-detection' } }
    return { data: calls.length === 2 ? { status: 'pending', job_token: 'synthetic-job' } : { payload, model_used: true } }
  } }
  const module = { exports: {} }
  new Function('module', 'exports', 'client', 'window', output)(module, module.exports, client,
    { setTimeout: callback => { queueMicrotask(callback); return 1 } })
  const signal = new AbortController().signal
  const task = { purpose: 'generate', payload: { text: 'Synthetic current text' }, ownerId: 'synthetic-user' }
  const prepared = await module.exports.prepareAIReview(task, signal)
  await module.exports.startAIReview({ ...task, payload: prepared.payload }, signal, prepared.preparation_token)
  assert.equal(calls.length, 3)
  assert.equal(calls[0].url, '/api/notes/deidentification-prepare')
  assert.equal(calls[1].body.job_token, '')
  assert.equal(calls[2].body.job_token, 'synthetic-job')
  for (const call of calls.slice(1)) {
    assert.deepEqual(call.body.payload, payload)
    assert.equal(call.body.preparation_token, prepared.preparation_token)
    assert.equal(call.options.expectedOwnerId, task.ownerId)
    assert.equal(call.options.signal, signal)
  }
})
