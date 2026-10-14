import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
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

test('page help is a collapsed, keyboard-accessible question button by default', () => {
  const QuickStartHelp = load('../src/components/QuickStartHelp.tsx', {
    '@/domain/pageHelp': { PAGE_HELP: { workbench: { title: '工作台', document: '', steps: [] } }, resolveHelpDocument: () => null },
    '@/stores/pageHelpStore': { usePageHelpStore: selector => selector({ openTopic: null, toggle() {}, dismiss() {} }) },
  }).default
  const html = renderToStaticMarkup(React.createElement(QuickStartHelp))
  assert.match(html, /<button/)
  assert.match(html, /aria-label="本页帮助"/)
  assert.match(html, /aria-expanded="false"/)
  assert.doesNotMatch(html, /<aside|<details/)
})

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

test('each supported context has distinct contextual actions and only static public copy examples', () => {
  const { PAGE_HELP, SERVICE_ADDRESSES } = load('../src/domain/pageHelp.ts')
  assert.equal(Object.keys(PAGE_HELP).length, 29)
  for (const topic of ['workbench', 'workflow', 'subtitle-editor', 'subtitle-translate', 'script-text', 'script-audio', 'script-vtt', 'presets', 'references', 'audition', 'fish-clone', 'audio-separate', 'audio-convert', 'audio-split', 'audio-translate', 'audio-volume', 'tasks', 'batches', 'local-asr', 'local-tts', 'local-llm', 'local-other', 'connections', 'appearance', 'preset-catalog', 'preset-templates', 'paths', 'workbench-common', 'workbench-advanced']) assert.ok(PAGE_HELP[topic]?.document, topic)
  const steps = new Set()
  for (const help of Object.values(PAGE_HELP)) {
    assert.ok(help.steps.length > 0)
    steps.add(help.steps.map(step => step.title + step.detail).join('|'))
  }
  assert.equal(steps.size, 29)
  assert.equal(SERVICE_ADDRESSES.length, 4)
  assert.deepEqual(SERVICE_ADDRESSES.map(item => item.value), [
    'https://api.fish.audio/v1', 'https://generativelanguage.googleapis.com/v1beta',
    'https://api.elevenlabs.io', 'https://api.xiaomimimo.com/v1',
  ])
  assert.doesNotMatch(JSON.stringify(PAGE_HELP), /E:\\\\|api_key|credential_ref|voicekey_/)
})

test('all help copy has English translations without translating public URLs or sample data', () => {
  const { PAGE_HELP } = load('../src/domain/pageHelp.ts')
  const { helpMessages } = load('../src/locales/help.ts')
  for (const help of Object.values(PAGE_HELP)) {
    for (const text of [help.title, ...help.steps.flatMap(step => [step.title, step.detail])]) {
      assert.ok(helpMessages[text], `Missing translation: ${text}`)
      assert.doesNotMatch(helpMessages[text], /[\u3400-\u9fff]/)
    }
  }
})
