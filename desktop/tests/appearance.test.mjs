import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(relative, overrides = {}) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(relative, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? require(name), module, module.exports)
  return module.exports
}
function storage(initial = {}) {
  const data = new Map(Object.entries(initial))
  globalThis.localStorage = { getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, value), removeItem: key => data.delete(key) }
  return data
}
test('a quota error retains the previous background; restore removes only the image', () => {
  const data = storage()
  const { useAppearanceStore, BACKGROUND_KEY } = load('../src/stores/appearanceStore.ts')
  const first = { name: '用户图片.jpg', data: 'data:image/jpeg;base64,fixture' }
  assert.equal(useAppearanceStore.getState().setBackground(first), true)
  const saved = data.get(BACKGROUND_KEY)
  localStorage.setItem = () => { throw new Error('QuotaExceededError') }
  assert.equal(useAppearanceStore.getState().setBackground({ ...first, name: 'replacement.jpg' }), false)
  assert.deepEqual(useAppearanceStore.getState().background, first)
  assert.equal(data.get(BACKGROUND_KEY), saved)
  assert.equal(useAppearanceStore.getState().issue, 'storageFailed')
  assert.equal(useAppearanceStore.getState().setBackground(null), true)
  assert.equal(data.has(BACKGROUND_KEY), false)
  assert.equal(useAppearanceStore.getState().background, null)
})
