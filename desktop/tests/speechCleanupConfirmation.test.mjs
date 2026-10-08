import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function fixture({ confirmed = false, blockers = [], fail = false } = {}) {
  const calls = [], confirmations = []
  const preview = { token: 'reviewed-token', blockers, records: { recipes: 1 }, files: [], bytes: 0 }
  const overrides = {
    '@/api/client': { api: { post: async (path, body) => {
      calls.push({ path, body })
      if (path.endsWith('/preview')) return preview
      if (fail) throw new Error('stale preview')
      return { deleted: 'recipe' }
    } } },
    '@/utils/confirmAction': { confirmAction: async message => { confirmations.push(message); return confirmed } },
  }
  const { outputText } = ts.transpileModule(readFileSync(new URL('../src/pages/voice-lab/SpeechCleanup.tsx', import.meta.url), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? require(name), module, module.exports)
  return { ...module.exports, calls, confirmations }
}

test('cancelled deletion only previews and never sends a mutation', async () => {
  const f = fixture()
  assert.equal(await f.deleteSpeechData('recipes', 'recipe', '我的音色'), false)
  assert.equal(f.calls.length, 1)
  assert.ok(f.calls[0].path.endsWith('/preview'))
  assert.match(f.confirmations[0], /删除无法撤销/)
})

test('reference blockers stop before confirmation or execution', async () => {
  const f = fixture({ confirmed: true, blockers: ['仍被工作流引用'] })
  await assert.rejects(f.deleteSpeechData('recipes', 'recipe'), /工作流引用/)
  assert.equal(f.calls.length, 1)
  assert.equal(f.confirmations.length, 0)
})

test('confirmed deletion sends exactly the preview token and reports stale failures', async () => {
  const f = fixture({ confirmed: true, fail: true })
  await assert.rejects(f.deleteSpeechData('recipes', 'recipe'), /stale preview/)
  assert.equal(f.calls.length, 2)
  assert.deepEqual(f.calls[1], { path: '/speech/cleanup/recipes/recipe/execute', body: { token: 'reviewed-token', confirmed: true } })
})
