import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function store() {
  const source = readFileSync(new URL('../src/stores/taskStore.ts', import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } })
  const module = { exports: {} }
  new Function('require', 'module', 'exports', outputText)(require, module, module.exports)
  return module.exports.useTaskStore
}
const draft = { jobType: 'convert', sourceName: 'input.wav', sourcePath: 'input.wav', params: {} }

test('only an unbound failed record can be removed and undo retains its identity and diagnostic', () => {
  const tasks = store()
  const id = tasks.getState().addTask(draft)
  assert.equal(tasks.getState().removeLocalFailure(id), false)
  tasks.getState().updateTask(id, { status: 'failed', errorMessage: 'submission response lost' })
  tasks.getState().selectTask(id)
  const before = tasks.getState().tasks[0]
  assert.equal(tasks.getState().removeLocalFailure(id), true)
  assert.equal(tasks.getState().tasks.length, 0)
  assert.equal(tasks.getState().selectedTaskId, null)
  tasks.getState().undoLocalRemoval()
  assert.deepEqual(tasks.getState().tasks, [before])
  assert.equal(tasks.getState().selectedTaskId, id)
  tasks.getState().undoLocalRemoval()
  assert.equal(tasks.getState().tasks.length, 1)
})

test('a stale local delete action cannot remove a newly bound server task', () => {
  const tasks = store()
  const id = tasks.getState().addTask(draft)
  tasks.getState().updateTask(id, { status: 'failed' })
  tasks.getState().updateTask(id, { serverTaskId: 'actual-task' })
  assert.equal(tasks.getState().removeLocalFailure(id), false)
  assert.equal(tasks.getState().tasks[0].serverTaskId, 'actual-task')
  assert.equal(tasks.getState().removedLocalTasks.length, 0)
})

test('removal and undo do not alter unrelated tasks and undo works in reverse order', () => {
  const tasks = store()
  const ids = [0, 1, 2].map(() => tasks.getState().addTask(draft))
  for (const id of ids.slice(0, 2)) tasks.getState().updateTask(id, { status: 'failed' })
  for (const id of ids.slice(0, 2)) assert.equal(tasks.getState().removeLocalFailure(id), true)
  assert.deepEqual(tasks.getState().tasks.map(t => t.id), [ids[2]])
  tasks.getState().undoLocalRemoval()
  assert.deepEqual(tasks.getState().tasks.map(t => t.id), [ids[2], ids[1]])
  tasks.getState().undoLocalRemoval()
  assert.equal(new Set(tasks.getState().tasks.map(t => t.id)).size, 3)
})
