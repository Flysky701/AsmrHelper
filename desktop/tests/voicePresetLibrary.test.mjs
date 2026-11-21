import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const i18n = { t: value => value, useI18n: () => value => value, format: (source, values) => source.replace(/\{(\d+)\}/g, (_, index) => String(values[index] ?? '')) }
function load(path, overrides = {}) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? (name === '@/i18n' ? i18n : require(name)), module, module.exports)
  return module.exports
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  return [tree, ...nodes(tree.props?.children)]
}
test('Edge default can be explicitly added without automatic requests or restoring deleted data', async () => {
  const calls = []
  const { default: DefaultVoicePreset } = load('../src/pages/voice-lab/DefaultVoicePreset.tsx', {
    react: { ...React, useState: initial => [initial, () => {}] },
    '@/api/client': { api: { post: async path => calls.push(path) } },
  })
  const tree = DefaultVoicePreset({ onChanged: async () => calls.push('refresh') })
  assert.deepEqual(calls, [])
  await nodes(tree).find(node => node.type === 'button').props.onClick()
  assert.deepEqual(calls, ['/speech/default-preset/add', 'refresh'])
  const disabled = DefaultVoicePreset({ disabled: true, onChanged: async () => {} })
  assert.equal(nodes(disabled).find(node => node.type === 'button').props.disabled, true)
})
