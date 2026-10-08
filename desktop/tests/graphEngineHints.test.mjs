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
const Control = load('../src/components/workflow/GraphEngineControl.tsx', {
  '@/api/models': { modelsApi: {} },
  '@/domain/nodeEngineStatus': { nodeInstallModel: () => undefined },
  '@/stores/navStore': { useNavStore: {} },
}).default
const render = overrides => renderToStaticMarkup(React.createElement(Control, {
  provider: 'qwen3', model: 'base', category: 'tts', choices: [{ id: 'qwen3', name: 'Qwen3' }],
  local: true, onSelect() {}, onRefresh() {}, ...overrides,
}))

test('an old generic provider asks for an explicit engine instead of an installation', () => {
  const html = render({ provider: 'speech', unavailable: true })
  assert.match(html, /需要重新选择引擎/)
  assert.match(html, /确认更换/)
  assert.match(html, /不可用/)
  assert.doesNotMatch(html, /speech（待确认）/)
})

test('an unchecked valid engine remains neutral with an explicit check entry', () => {
  const html = render({})
  assert.match(html, /尚未检查/)
  assert.match(html, /配置与检查/)
  assert.doesNotMatch(html, /安装失败|连接待修复/)
})

test('connection mismatch names the existing configuration action', () => {
  const html = render({ connectionIssue: '声音运行连接已缺失，请重新选择。' })
  assert.match(html, /当前节点配置需处理/)
  assert.match(html, /配置当前节点/)
  assert.match(html, /声音运行连接已缺失/)
})

test('unavailable catalog and in-flight loading are distinct', () => {
  assert.match(render({ choices: [], unavailable: true }), /引擎列表未能读取/)
  const html = render({ choices: [], unavailable: true, loading: true })
  assert.match(html, /正在读取引擎列表/)
  assert.doesNotMatch(html, /<strong>引擎列表未能读取/)
})
