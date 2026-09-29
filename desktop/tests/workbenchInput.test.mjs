import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/domain/workbenchInput.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { companionDescription, discoveredFileToInput } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('queue interprets subtitle language against current source and target', () => {
  const item = discoveredFileToInput({ path: 'a.mp3', name: 'a.mp3', size_bytes: 20,
    companion_paths: ['a.mp3.vtt'], companion_subtitles: [{ path: 'a.mp3.vtt', language: 'zh', valid: true, reason: '' }] })
  assert.match(companionDescription(item, 'ja', 'zh'), /目标译文.*保留 ASR/)
  assert.match(companionDescription(item, 'zh', 'en'), /原语言一致/)
  item.companionSubtitles[0].language = 'mixed'
  assert.match(companionDescription(item, 'ja', 'zh'), /不作为原文/)
  item.companionSubtitles[0].valid = false
  item.companionSubtitles[0].reason = '时间轴无效'
  assert.match(companionDescription(item, 'ja', 'zh'), /无法使用.*时间轴无效/)
})
