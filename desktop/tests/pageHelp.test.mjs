import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const i18n = { t: value => value, useI18n: () => value => value, format: (source, values) => source.replace(/\{(\d+)\}/g, (_, i) => String(values[Number(i)])) }
function load(relative, overrides = {}) {
  const source = readFileSync(new URL(relative, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? (name === './HelpMarkdown' ? { default: () => null } : name === '@/i18n' ? i18n : name.endsWith('?raw') ? 'Fixture guide and subtitle' : name.endsWith('.css') ? {} : require(name)), module, module.exports)
  return module.exports
}

test('help opens only on explicit toggle, repeated toggles close, and stale page cleanup cannot close another topic', () => {
  const { usePageHelpStore } = load('../src/stores/pageHelpStore.ts')
  assert.equal(usePageHelpStore.getState().openTopic, null)
  usePageHelpStore.getState().toggle('workbench')
  assert.equal(usePageHelpStore.getState().openTopic, 'workbench')
  usePageHelpStore.getState().toggle('workbench')
  assert.equal(usePageHelpStore.getState().openTopic, null)
  usePageHelpStore.getState().toggle('connections')
  usePageHelpStore.getState().dismiss('workbench')
  assert.equal(usePageHelpStore.getState().openTopic, 'connections')
  usePageHelpStore.getState().dismiss('connections')
  assert.equal(usePageHelpStore.getState().openTopic, null)
})
