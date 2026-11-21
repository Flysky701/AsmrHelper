import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const i18n = { t: value => value, useI18n: () => value => value, format: (source, values) => source.replace(/\{(\d+)\}/g, (_, index) => String(values[index] ?? '')) }
function load(path, overrides = {}) {
  const source = readFileSync(new URL(path, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(name => overrides[name] ?? (name === '@/i18n' ? i18n : require(name)), module, module.exports)
  return module.exports
}
const { FishCloneSubmission } = load('../src/domain/fishCloneSubmission.ts')
const draft = { connection_ref: 'test-connection', asset_id: 'generated-asset', title: 'Test voice' }
const preview = { token: 'test-token' }
const result = { id: 'test-receipt', state: 'created', remote_voice_id: 'test-voice' }

test('one action runs local preflight then creation; duplicate clicks share the request', async () => {
  const calls = []
  let resolvePreview
  const controller = new FishCloneSubmission({
    preview: () => { calls.push('preview'); return new Promise(resolve => { resolvePreview = resolve }) },
    create: async (actual, token, id) => { calls.push('create'); assert.deepEqual(actual, draft); assert.equal(token, 'test-token'); assert.equal(id, 'fixed-id'); return result },
  }, () => 'fixed-id')
  const a = controller.submit(draft), b = controller.submit({ ...draft })
  assert.equal(a, b)
  await Promise.resolve()
  assert.deepEqual(calls, ['preview'])
  resolvePreview(preview)
  assert.deepEqual(await a, result)
  assert.equal(await controller.submit(draft), result)
  assert.deepEqual(calls, ['preview', 'create'])
})

test('a lost creation response remains unknown and repeat clicks never re-upload', async () => {
  let uploads = 0
  const controller = new FishCloneSubmission({ preview: async () => preview,
    create: async () => { uploads++; throw new Error('transport lost') },
  }, () => 'fixed-id')
  await assert.rejects(controller.submit(draft), /请刷新本地记录/)
  assert.equal(controller.dispatched(draft), true)
  await assert.rejects(controller.submit(draft), /不要重复上传/)
  assert.equal(uploads, 1)
})
