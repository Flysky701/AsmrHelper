import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
const source = readFileSync(new URL('../src/components/workflow/canvasViewport.ts', import.meta.url), 'utf8')
const module = { exports: {} }
new Function('module', 'exports', ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(module, module.exports)
const { canvasPoint, draggedCanvasPoint } = module.exports
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`)

test('port endpoints and drag deltas map to the same unscaled coordinates at every supported ratio', () => {
  for (const scale of [.25, .5, 1, 1.2, 2]) {
    const origin = Object.freeze({ x: 137, y: 89 })
    const point = canvasPoint({ x: origin.x + 240 * scale, y: origin.y + 75 * scale }, origin, scale)
    close(point.x, 240); close(point.y, 75)
    const moved = draggedCanvasPoint({ x: 100, y: 120 }, { x: 60 * scale, y: -20 * scale }, scale)
    close(moved.x, 160); close(moved.y, 100)
  }
  assert.deepEqual(draggedCanvasPoint({ x: 20, y: 20 }, { x: -100, y: -100 }, .25), { x: 10, y: 12 })
})
