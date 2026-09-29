import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

test('preview only reads the sanitized report; explicit import posts no legacy settings or credentials', async () => {
  const calls = []
  const report = { entries: [], legacy_local_settings_retained: true, note: 'Preserved' }
  const client = {
    api: {
      get: async (...args) => { calls.push(['GET', ...args]); return report },
      post: async (...args) => { calls.push(['POST', ...args]); return report },
    },
    apiUrl: path => path,
  }
  const source = await readFile(new URL('../src/api/speech.ts', import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  })
  const exports = {}
  new Function('require', 'exports', outputText)(name => {
    assert.equal(name, './client')
    return client
  }, exports)
  assert.equal(await exports.speechApi.legacyImportReport(), report)
  assert.deepEqual(calls, [['GET', '/speech/legacy-import']])
  assert.equal(await exports.speechApi.importLegacy(), report)
  assert.deepEqual(calls[1], ['POST', '/speech/legacy-import', {}])
})
