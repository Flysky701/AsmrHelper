import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(relative, overrides = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? require(name), module, module.exports)
  return module.exports
}
const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('native cancellation retains the current page; acceptance navigates only after the decision', async () => {
  let decision = deferred()
  const { confirmAction } = load('../src/utils/confirmAction.ts', {
    '@tauri-apps/api/core': { isTauri: () => true },
    '@tauri-apps/plugin-dialog': { confirm: () => decision.promise },
  })
  const { useNavStore } = load('../src/stores/navStore.ts')
  const store = useNavStore.getState()
  store.setNavigationGuard(() => confirmAction('Unsaved draft'))
  const first = store.setPage('settings')
  assert.equal(useNavStore.getState().activePage, 'workbench')
  decision.resolve(false)
  await first
  assert.equal(useNavStore.getState().activePage, 'workbench')
  decision = deferred()
  const second = store.openEngines('external')
  assert.equal(useNavStore.getState().activePage, 'workbench')
  decision.resolve(true)
  await second
  assert.equal(useNavStore.getState().activePage, 'engines')
  assert.equal(useNavStore.getState().enginesView, 'external')
})

test('rapid navigation cannot bypass the pending confirmation or replace its destination', async () => {
  const { useNavStore } = load('../src/stores/navStore.ts')
  const decision = deferred()
  let calls = 0
  useNavStore.getState().setNavigationGuard(() => { calls++; return decision.promise })
  const first = useNavStore.getState().setPage('settings')
  await useNavStore.getState().openTaskCenter('batches')
  assert.equal(calls, 1)
  assert.equal(useNavStore.getState().activePage, 'workbench')
  decision.resolve(true)
  await first
  assert.equal(useNavStore.getState().activePage, 'settings')
})

test('a replaced guard cannot authorize leaving a different draft', async () => {
  const { useNavStore } = load('../src/stores/navStore.ts')
  const decision = deferred()
  useNavStore.getState().setNavigationGuard(() => decision.promise)
  const first = useNavStore.getState().setPage('settings')
  useNavStore.getState().setNavigationGuard(() => false)
  decision.resolve(true)
  await first
  assert.equal(useNavStore.getState().activePage, 'workbench')
})

test('failed native confirmation preserves the draft and releases the dialog lock', async () => {
  let fail = true
  const { confirmAction } = load('../src/utils/confirmAction.ts', {
    '@tauri-apps/api/core': { isTauri: () => true },
    '@tauri-apps/plugin-dialog': { confirm: async () => { if (fail) throw Error('test dialog failure'); return true } },
  })
  assert.equal(await confirmAction('Unsaved draft'), false)
  fail = false
  assert.equal(await confirmAction('Unsaved draft'), true)
})
