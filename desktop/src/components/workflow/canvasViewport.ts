/** View-only geometry. Graph/card positions stay in unscaled canvas units. */
export type CanvasPoint = { x: number; y: number }
export const MIN_CANVAS_ZOOM = 0.25
export const MAX_CANVAS_ZOOM = 2
export function clampCanvasZoom(value: number): number {
  return Number.isFinite(value) ? Math.min(MAX_CANVAS_ZOOM, Math.max(MIN_CANVAS_ZOOM, value)) : 1
}
export function canvasPoint(point: CanvasPoint, origin: CanvasPoint, zoom: number): CanvasPoint {
  return { x: (point.x - origin.x) / zoom, y: (point.y - origin.y) / zoom }
}
/** Preserve the canvas point under the anchor, except at scroll boundaries. */
export function zoomedScroll(scroll: CanvasPoint, anchor: CanvasPoint, from: number, to: number, padding: CanvasPoint = { x: 0, y: 0 }): CanvasPoint {
  return { x: Math.max(0, padding.x + (scroll.x + anchor.x - padding.x) * to / from - anchor.x),
    y: Math.max(0, padding.y + (scroll.y + anchor.y - padding.y) * to / from - anchor.y) }
}
export function draggedCanvasPoint(origin: CanvasPoint, screenDelta: CanvasPoint, zoom: number): CanvasPoint {
  return { x: Math.max(10, origin.x + screenDelta.x / zoom), y: Math.max(12, origin.y + screenDelta.y / zoom) }
}
export function fitCanvasView(bounds: CanvasPoint & { width: number; height: number }, viewport: { width: number; height: number }) {
  const zoom = clampCanvasZoom(Math.min(1, Math.max(1, viewport.width - 48) / Math.max(1, bounds.width),
    Math.max(1, viewport.height - 48) / Math.max(1, bounds.height)))
  return { zoom, scroll: { x: (bounds.x + bounds.width / 2) * zoom - viewport.width / 2,
    y: (bounds.y + bounds.height / 2) * zoom - viewport.height / 2 } }
}
/** Pan uses viewport pixels regardless of the content zoom. */
export function pannedCanvasScroll(scroll: CanvasPoint, pointerDelta: CanvasPoint): CanvasPoint {
  return { x: Math.max(0, scroll.x - pointerDelta.x), y: Math.max(0, scroll.y - pointerDelta.y) }
}
