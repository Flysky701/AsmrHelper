import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function load(path, overrides = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? require(name), module, module.exports)
  return module.exports
}
function nodes(tree) {
  if (!tree || typeof tree !== 'object') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  return [tree, ...nodes(tree.props?.children)]
}
function setup({ scope = 'mine_public', page = 1, result, value = 'manual-id', connectionId = 'connection', stale = false } = {}) {
  let hook = 0
  const changed = [], selected = []
  const key = JSON.stringify([connectionId, '', scope, page, 0])
  const states = ['', scope, page, 0, result ? { key: stale ? 'previous-request' : key, ...result } : undefined]
  const { ConnectionVoicePicker } = load('../src/components/FishVoicePicker.tsx', {
    react: { ...React, useEffect() {}, useState() { const index = hook++; return [states[index], value => changed.push([index, value])] } },
    '@/api/speech': { speechApi: {} }, './FishVoicePicker.css': {},
  })
  const tree = ConnectionVoicePicker({ connectionId, value, onSelect: value => selected.push(value) })
  return { tree, all: nodes(tree), html: renderToStaticMarkup(tree), changed, selected }
}
const data = { items: [{ id: 'selected-id', name: 'Synthetic voice' }], page: 1, page_size: 20, has_more: true, notice: '' }

test('one controlled Voice ID with clearly distinct account, workspace and public scopes', () => {
  const view = setup()
  assert.equal(view.all.filter(node => node.type === 'input' && node.props.value === 'manual-id').length, 1)
  assert.match(view.html, /我的公开音色（API 账号）/)
  assert.match(view.html, /当前工作区音色/)
  assert.match(view.html, /公共音色库（所有作者）/)
  assert.match(setup({ scope: 'workspace' }).html, /不等同于本人公开库/)
  assert.match(setup({ scope: 'public' }).html, /不代表属于当前账号/)
  assert.equal(view.selected.length, 0)
})

test('selection and manual edit share the same ID callback without default selection', () => {
  const view = setup({ result: { data } })
  const select = view.all.find(node => node.type === 'select' && node.props.value === '')
  assert.ok(select)
  select.props.onChange({ target: { value: 'selected-id' } })
  select.props.onChange({ target: { value: 'unknown-option' } })
  const manual = view.all.find(node => node.type === 'input' && node.props.value === 'manual-id')
  manual.props.onChange({ target: { value: 'direct-id' } })
  assert.deepEqual(view.selected, ['selected-id', 'direct-id'])
})

test('empty, permission error and stale results preserve the manually entered ID', () => {
  for (const options of [{ result: { data: { ...data, items: [] } } },
    { result: { error: '无法核实当前账号' } }, { result: { data }, stale: true }]) {
    const view = setup(options)
    assert.match(view.html, /value="manual-id"/)
    assert.equal(view.selected.length, 0)
    assert.doesNotMatch(view.html, /value="selected-id"/)
  }
})

test('scope and search reset page without clearing selection; pagination follows has_more', () => {
  const view = setup({ page: 3, result: { data } })
  const scope = view.all.find(node => node.type === 'select' && node.props.value === 'mine_public')
  scope.props.onChange({ target: { value: 'public' } })
  const search = view.all.find(node => node.type === 'input' && node.props.maxLength === 200)
  search.props.onChange({ target: { value: 'filter' } })
  assert.deepEqual(view.changed, [[1, 'public'], [2, 1], [0, 'filter'], [2, 1]])
  assert.deepEqual(view.selected, [])
  const last = setup({ result: { data: { ...data, has_more: false } } })
  assert.equal(last.all.find(node => node.type === 'button' && node.props.children === '下一页').props.disabled, true)
})

test('client sends explicit scope and pagination without a second voice field', async () => {
  const paths = []
  const { speechApi } = load('../src/api/speech.ts', { './client': { api: { get: async path => { paths.push(path); return data } }, apiUrl: value => value } })
  await speechApi.hostedVoices('connection/a', 'test name', 2, 'mine_public')
  const url = new URL(paths[0], 'http://test')
  assert.equal(url.pathname, '/speech/connections/connection%2Fa/voices')
  assert.equal(url.searchParams.get('scope'), 'mine_public')
  assert.equal(url.searchParams.get('page'), '2')
  assert.equal(url.searchParams.get('title'), 'test name')
  assert.equal(url.searchParams.has('workspace_only'), false)
})
