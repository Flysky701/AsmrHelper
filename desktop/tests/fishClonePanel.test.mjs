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
const { FishCloneSubmission } = load('../src/domain/fishCloneSubmission.ts')
const draft = { connection_ref: 'test-connection', asset_id: 'generated-asset', title: 'Test voice' }
const preview = { token: 'test-token' }
const result = { id: 'test-receipt', state: 'created', remote_voice_id: 'test-voice' }

function render({ selected = false, items = [] } = {}) {
  const Panel = load('../src/pages/voice-lab/FishClonePanel.tsx', {
    react: { ...React, useState: initial => [Array.isArray(initial) ? items : selected && initial?.connection_ref === '' ? draft : initial, () => {}] },
    '@/api/fishClones': { fishClonesApi: {} },
    '@/api/speech': { speechApi: { referenceAudio: () => '/test.wav' } },
    '@/domain/fishCloneSubmission': { FishCloneSubmission },
    './FishClonePanel.css': {},
  }).default
  return renderToStaticMarkup(React.createElement(Panel, { active: false,
    assets: [{ id: draft.asset_id, name: 'Synthetic sample', confirmed: true, transcript: 'Synthetic transcript', duration: 3 }],
    connections: [{ id: draft.connection_ref, provider_id: 'fish_audio', name: 'Test connection' }], onSaved() {},
  }))
}

test('summary is always visible with a single upload action and no checkboxes or preview expander', () => {
  for (const selected of [false, true]) {
    const html = render({ selected })
    assert.match(html, /aria-label="远程创建摘要"/)
    assert.match(html, /上传至/)
    assert.match(html, /参考片段/)
    assert.match(html, /目标音色/)
    assert.match(html, /上传片段并创建音色/)
    assert.doesNotMatch(html, /type="checkbox"|<details|预览上传内容/)
    if (selected) assert.match(html, /Synthetic transcript/)
    else assert.match(html, /disabled=""[^>]*>上传片段并创建音色/)
  }
})

test('results have simple local deletion and a single undo action, with no cloud management', () => {
  const html = render({ items: [{ ...result, state: 'unknown', remote_voice_id: null, title: 'Unknown' },
    { ...result, id: 'ready', state: 'trained', title: 'Ready' },
    { ...result, id: 'deleted', deleted: true, title: 'Hidden' }] })
  assert.match(html, /结果未知/)
  assert.match(html, /保存到音色库（Free 合成）/)
  assert.equal((html.match(/>删除本地记录</g) || []).length, 2)
  assert.equal((html.match(/>撤销上次删除</g) || []).length, 1)
  assert.doesNotMatch(html, /Hidden|云端删除|恢复中心|查看历史|更新状态/)
})

test('in-progress results keep a status action and disable local deletion', () => {
  const html = render({ items: [{ ...result, title: 'Pending', state: 'training' }] })
  assert.match(html, /更新状态/)
  assert.match(html, /disabled=""[^>]*>删除本地记录/)
  assert.doesNotMatch(html, /保存到音色库（Free 合成）/)
})

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

test('a local validation error can be corrected and retried without any prior upload', async () => {
  let preflights = 0, uploads = 0
  const controller = new FishCloneSubmission({
    preview: async () => { if (++preflights === 1) throw new Error('invalid sample'); return preview },
    create: async () => { uploads++; return result },
  }, () => 'fixed-id')
  await assert.rejects(controller.submit(draft), /invalid sample/)
  assert.equal(controller.dispatched(draft), false)
  assert.equal(uploads, 0)
  await controller.submit(draft)
  assert.equal(uploads, 1)
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

test('failed and unknown server receipts remain results, never automatic retry triggers', async () => {
  for (const state of ['failed', 'unknown']) {
    let uploads = 0
    const controller = new FishCloneSubmission({ preview: async () => preview,
      create: async () => { uploads++; return { ...result, state } },
    }, () => 'fixed-id')
    assert.equal((await controller.submit(draft)).state, state)
    await controller.submit(draft)
    assert.equal(uploads, 1)
  }
})
