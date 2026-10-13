import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'
const source = readFileSync(new URL('../src/components/workflow/canvasViewport.ts', import.meta.url), 'utf8')
const module = { exports: {} }
new Function('module', 'exports', ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(module, module.exports)
const { clampCanvasZoom, canvasPoint, draggedCanvasPoint, zoomedScroll, fitCanvasView, pannedCanvasScroll } = module.exports
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-8, `${actual} != ${expected}`)

test('zoom bounds and fit include the measured card bounds without changing positions', () => {
  assert.equal(clampCanvasZoom(.01), .25)
  assert.equal(clampCanvasZoom(9), 2)
  assert.equal(clampCanvasZoom(NaN), 1)
  const bounds = Object.freeze({ x: 20, y: 30, width: 900, height: 700 })
  const view = fitCanvasView(bounds, { width: 600, height: 500 })
  assert.ok(view.zoom * bounds.width <= 552)
  assert.ok(view.zoom * bounds.height <= 452)
  assert.equal(fitCanvasView({ x: 0, y: 0, width: 0, height: 0 }, { width: 0, height: 0 }).zoom, 1)
  assert.equal(fitCanvasView(bounds, { width: 1, height: 1 }).zoom, .25)
})

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

test('zoom preserves the anchored graph point through roundtrips; drag includes scrolled screen distance', () => {
  const scroll = { x: 600, y: 500 }, anchor = { x: 210, y: 160 }
  const next = zoomedScroll(scroll, anchor, 1, .5)
  close((next.x + anchor.x) / .5, scroll.x + anchor.x)
  close((next.y + anchor.y) / .5, scroll.y + anchor.y)
  const restored = zoomedScroll(next, anchor, .5, 1)
  close(restored.x, scroll.x); close(restored.y, scroll.y)
  // 40 screen pixels of pointer motion plus 30 pixels of scroll at 50% = 140 canvas units.
  assert.equal(draggedCanvasPoint({ x: 100, y: 100 }, { x: 40 + 30, y: 0 }, .5).x, 240)
  assert.deepEqual(zoomedScroll({ x: 0, y: 0 }, anchor, 1, .25), { x: 0, y: 0 })
})

test('padded viewport keeps zoom anchored after a pan and centers fitted cards', () => {
  const padding = { x: 600, y: 400 }, scroll = { x: 530, y: 510 }, anchor = { x: 180, y: 90 }
  const next = zoomedScroll(scroll, anchor, .5, 2, padding)
  close((next.x + anchor.x - padding.x) / 2, (scroll.x + anchor.x - padding.x) / .5)
  close((next.y + anchor.y - padding.y) / 2, (scroll.y + anchor.y - padding.y) / .5)
  const bounds = { x: 30, y: 50, width: 200, height: 120 }, viewport = { width: 600, height: 400 }
  const fit = fitCanvasView(bounds, viewport)
  close((bounds.x + bounds.width / 2) * fit.zoom - fit.scroll.x, viewport.width / 2)
  close((bounds.y + bounds.height / 2) * fit.zoom - fit.scroll.y, viewport.height / 2)
})

test('pan follows pointer pixels independent of zoom without mutating saved coordinates', () => {
  const scroll = Object.freeze({ x: 600, y: 400 }), delta = Object.freeze({ x: 75, y: -30 })
  assert.deepEqual(pannedCanvasScroll(scroll, delta), { x: 525, y: 430 })
  assert.deepEqual(pannedCanvasScroll({ x: 10, y: 10 }, { x: 50, y: 50 }), { x: 0, y: 0 })
  assert.deepEqual(scroll, { x: 600, y: 400 })
})
