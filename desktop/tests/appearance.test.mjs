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
test('corrupt and unsupported preferences fall back; overlay stays readable', () => {
  storage({ 'asmr-helper.appearance.v1': '{broken' })
  const { readPreferences } = load('../src/stores/appearanceStore.ts')
  assert.deepEqual(readPreferences(), { language: 'zh-CN', overlay: 0.78 })
  localStorage.setItem('asmr-helper.appearance.v1', JSON.stringify({ language: 'xx', overlay: 0 }))
  assert.deepEqual(readPreferences(), { language: 'zh-CN', overlay: 0.72 })
  localStorage.setItem('asmr-helper.appearance.v1', JSON.stringify({ language: 'en', overlay: 12 }))
  assert.deepEqual(readPreferences(), { language: 'en', overlay: 0.94 })
})
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
test('missing and invalid image records recover without an external URL', () => {
  storage({ 'asmr-helper.background.v1': JSON.stringify({ name: 'remote', data: 'https://example.com/image.jpg' }) })
  const { useAppearanceStore } = load('../src/stores/appearanceStore.ts')
  assert.equal(useAppearanceStore.getState().background, null)
  assert.equal(useAppearanceStore.getState().issue, 'backgroundUnavailable')
})
test('language updates cannot silently succeed when persistence fails', () => {
  storage()
  const { useAppearanceStore } = load('../src/stores/appearanceStore.ts')
  localStorage.setItem = () => { throw new Error('blocked') }
  assert.equal(useAppearanceStore.getState().setPreferences({ language: 'en' }), false)
  assert.equal(useAppearanceStore.getState().language, 'zh-CN')
})
test('UI translation preserves supplied names, paths and unknown backend details', () => {
  let language = 'en'
  const { en } = load('../src/locales/en.ts')
  const { t, format } = load('../src/i18n.ts', {
    './locales/en': { en },
    ...Object.fromEntries(['workflow', 'voices', 'operations', 'shared', 'audio'].map(name => [`./locales/${name}`, load(`../src/locales/${name}.ts`)])), './stores/appearanceStore': { useAppearanceStore: { getState: () => ({ language }) } },
  })
  assert.equal(t('工作台'), 'Workbench')
  assert.equal(format('查看 {0}', ['我的模板 中文声线']), 'View 我的模板 中文声线')
  assert.equal(t('状态刷新失败：backend 原始错误。当前显示为上次已知状态。'), 'Could not refresh status: backend 原始错误. Showing the last known state.')
  assert.equal(t('unknown backend detail'), 'unknown backend detail')
  assert.equal(t('将本次节点参数保存到“用户模板”？'), 'Save these node parameters to “用户模板”?')
  assert.equal(format('将本次节点参数保存到“{0}”？', ['用户 {1} 模板']), 'Save these node parameters to “用户 {1} 模板”?')
  language = 'zh-CN'
  assert.equal(t('工作台'), '工作台')
  assert.equal(format('查看 {0}', ['My voice']), '查看 My voice')
})
