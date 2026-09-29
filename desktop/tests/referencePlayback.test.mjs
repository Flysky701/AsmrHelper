import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/pages/voice-lab/referencePlayback.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } })
const { playbackBoundary, sameClip } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

test('native playback and seeking stay inside the selected clip', () => {
  const range = { start: 34, end: 52 }
  assert.deepEqual(playbackBoundary(0, range, false, true), { pause: false, seek: 34 })
  assert.deepEqual(playbackBoundary(40, range, false, true), { pause: false })
  assert.deepEqual(playbackBoundary(52.2, range, false, true), { pause: true, seek: 52 })
  assert.deepEqual(playbackBoundary(100, range, true, false), { pause: true, seek: 52 })
  assert.deepEqual(playbackBoundary(52, range, true, true), { pause: false, seek: 34 })
  assert.deepEqual(playbackBoundary(1, { start: 4, end: 2 }, true, true), { pause: true })
})

test('ASR result identity includes file, both boundaries and language', () => {
  const clip = { path: 'recording.wav', start: 4, end: 12, language: 'ja' }
  assert.equal(sameClip(clip, { ...clip }), true)
  for (const update of [{ path: 'another.wav' }, { start: 5 }, { end: 13 }, { language: 'zh' }]) {
    assert.equal(sameClip(clip, { ...clip, ...update }), false)
  }
})
