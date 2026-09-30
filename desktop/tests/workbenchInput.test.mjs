import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'
const source = await readFile(new URL('../src/domain/workbenchInput.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { expandInputMaterials, discoveredFileToInput, companionDescription } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('audio and discovered subtitles become visible candidates without choosing an execution source', () => {
  const item = discoveredFileToInput({ path: 'a.wav', name: 'a.wav', size_bytes: 20,
    companion_paths: ['a.vtt'], companion_subtitles: [{ path: 'a.vtt', language: 'zh', valid: true, reason: '' }] })
  const materials = expandInputMaterials([item])
  assert.equal(materials.length, 2)
  const subtitle = materials.find(item => item.path === 'a.vtt')
  assert.deepEqual(subtitle.subtitleSummary, { language: 'zh', valid: true, reason: '' })
  assert.match(companionDescription(subtitle), /来源与对应关系由你选择/)
  assert.equal(expandInputMaterials(materials).length, 2)
})
