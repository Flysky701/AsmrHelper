import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(path, overrides = {}) {
  const { outputText } = ts.transpileModule(readFileSync(new URL(path, import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? require(name), module, module.exports)
  return module.exports
}
const { default: VoiceRecipeList } = load('../src/pages/voice-lab/VoiceRecipeList.tsx', { './VoiceRecipeList.css': {} })
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  return [tree, ...nodes(tree.props?.children)]
}
const base = { revision: 1, voice_id: 'internal-only', language: 'auto', provider_options: {}, connection_ref: 'connection' }
const recipes = [
  { ...base, id: 'local', name: '本地旁白', provider_id: 'qwen3', model: 'qwen3-base', mode: 'reference', variant: { kind: 'reference', value: 'asset-id', style: 'normal' } },
  { ...base, id: 'owned', name: '本人云端', provider_id: 'fish_audio', model: 's2.1-pro-free', mode: 'hosted', variant: { kind: 'hosted', value: 'owned-remote-id', style: 'normal' } },
  { ...base, id: 'public', name: '公开收藏', provider_id: 'fish_audio', model: 's2.1-pro-free', mode: 'hosted', variant: { kind: 'hosted', value: 'public-remote-id', style: 'normal' } },
]
const providers = [{ provider_id: 'qwen3', name: 'Qwen', remote: false }, { provider_id: 'fish_audio', name: 'Fish', remote: true }]

test('local, owned and public sources use identical saved recipe cards and actions', () => {
  const selected = [], auditioned = [], removed = []
  const tree = VoiceRecipeList({ recipes, providers, selectedId: 'owned', onSelect: item => selected.push(item), onAudition: item => auditioned.push(item), onRemove: item => removed.push(item) })
  const all = nodes(tree), html = renderToStaticMarkup(tree)
  assert.equal(all.filter(node => node.props.role === 'listitem').length, 3)
  assert.match(html, /本地引擎/)
  assert.equal((html.match(/云端 ID/g) || []).length, 2)
  assert.doesNotMatch(html, /internal-only|owned-remote-id|public-remote-id/)
  for (const [label, output] of [['编辑', selected], ['试听', auditioned], ['删除', removed]]) {
    const buttons = all.filter(node => node.type === 'button' && node.props.children === label)
    assert.equal(buttons.length, 3)
    buttons.forEach(button => button.props.onClick())
    assert.deepEqual(output, recipes)
    assert.equal(output[2].variant.value, 'public-remote-id')
    assert.equal(output[2].voice_id, 'internal-only')
  }
})

test('legacy saved recipes need no audition history; archived entries remain editable', () => {
  const archived = { ...recipes[0], archived: true }
  const tree = VoiceRecipeList({ recipes: [archived], providers: [], selectedId: archived.id, onSelect() {}, onAudition() {}, onRemove() {} })
  const all = nodes(tree)
  assert.equal(all.find(node => node.type === 'button' && node.props.children === '试听').props.disabled, true)
  assert.equal(all.filter(node => node.type === 'button' && node.props.children === '删除').length, 1)
  assert.equal(all.find(node => node.type === 'button' && node.props.children === '编辑').props.disabled, undefined)
  assert.match(renderToStaticMarkup(tree), /aria-current="true"/)
})

test('busy state blocks every preset action', () => {
  const tree = VoiceRecipeList({ recipes, providers, selectedId: '', disabled: true, onSelect() {}, onAudition() {}, onRemove() {} })
  assert.ok(nodes(tree).filter(node => node.type === 'button').every(node => node.props.disabled))
})

test('Edge default can be explicitly added without automatic requests or restoring deleted data', async () => {
  const calls = []
  const { default: DefaultVoicePreset } = load('../src/pages/voice-lab/DefaultVoicePreset.tsx', {
    react: { ...React, useState: initial => [initial, () => {}] },
    '@/api/client': { api: { post: async path => calls.push(path) } },
  })
  const tree = DefaultVoicePreset({ onChanged: async () => calls.push('refresh') })
  assert.deepEqual(calls, [])
  const html = renderToStaticMarkup(tree)
  assert.match(html, /需联网及 edge-tts/)
  assert.doesNotMatch(html, /恢复/)
  await nodes(tree).find(node => node.type === 'button').props.onClick()
  assert.deepEqual(calls, ['/speech/default-preset/add', 'refresh'])
  const disabled = DefaultVoicePreset({ disabled: true, onChanged: async () => {} })
  assert.equal(nodes(disabled).find(node => node.type === 'button').props.disabled, true)
})
