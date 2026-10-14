import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'
const require = createRequire(import.meta.url)
const domainUrl = new URL('../src/domain/pageHelp.ts', import.meta.url)
const module = { exports: {} }
new Function('require', 'module', 'exports', ts.transpileModule(readFileSync(domainUrl, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText)(name => name.endsWith('?raw') ? { default: readFileSync(new URL(name.slice(0, -4), domainUrl), 'utf8') } : require(name), module, module.exports)
const { PAGE_HELP, resolveHelpDocument } = module.exports
test('all 29 context documents resolve to the correct heading and valid bundled links', () => {
  for (const [topic, help] of Object.entries(PAGE_HELP)) {
    const doc = resolveHelpDocument(help.document)
    assert.ok(doc?.source?.trim(), topic)
    if (help.document.includes('#')) assert.ok(doc.source.startsWith('## ' + help.document.split('#')[1]), topic)
    for (const match of doc.source.matchAll(/\]\(([^)]+\.md(?:#[^)]+)?)\)/g)) {
      // A nonbundled link remains a labelled button with explicit unavailable feedback.
      if (resolveHelpDocument(match[1])) assert.ok(resolveHelpDocument(match[1]).source)
    }
  }
  assert.match(resolveHelpDocument(PAGE_HELP.workbench.document).source, /^# 工作台：选择流水线、管理素材、提交处理/)
  assert.doesNotMatch(PAGE_HELP.workbench.steps.map(s => s.detail).join(' '), /演示预设|中文配音/)
  assert.match(resolveHelpDocument(PAGE_HELP.references.document).source, /^## 声音库/)
  assert.match(resolveHelpDocument(PAGE_HELP['fish-clone'].document).source, /^# Fish Audio 持久音色克隆/)
  assert.equal(resolveHelpDocument('javascript:alert(1)'), null)
  assert.equal(resolveHelpDocument('../../config/settings.md'), null)
  assert.equal(resolveHelpDocument('desktop-page-help.md#missing'), null)
})
test('every navigation page and task-specific subview mounts contextual help', () => {
  const pages = ['Workbench', 'WorkflowPresets', 'SubtitleWorkshop', 'voice-lab/VoiceLab', 'AudioTools', 'TaskCenter', 'EnginesResources', 'Settings']
  for (const page of pages) {
    const source = readFileSync(new URL(`../src/pages/${page}.tsx`, import.meta.url), 'utf8')
    assert.match(source, /<QuickStartHelp topic=/, page)
  }
})
