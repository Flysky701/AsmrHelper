import type { ReferenceCandidate } from '@/api/speech'

export function hasTimestamp(item: ReferenceCandidate): item is ReferenceCandidate & { start: number; end: number } {
  return item.timestamp_valid !== false && item.start !== null && item.end !== null && Number.isFinite(item.start) && Number.isFinite(item.end) && item.start >= 0 && item.end > item.start
}
export function chronologicalSegments(items: ReferenceCandidate[]) {
  return [...items].sort((a, b) => Number(!hasTimestamp(a)) - Number(!hasTimestamp(b)) || (a.start ?? 0) - (b.start ?? 0) || (a.end ?? 0) - (b.end ?? 0))
}
export function confidenceLabel(item: ReferenceCandidate) {
  const meta = item.recognition_metadata
  const source = meta?.provider ? `（${meta.provider}）` : ''
  if (item.asr_confidence == null || !Number.isFinite(item.asr_confidence)) return `未提供置信度${source}`
  return `台词识别分数${source} · ${meta?.confidence_kind || '引擎原始分数'}：${item.asr_confidence.toFixed(4)}；${meta?.confidence_note || '未经校准，不能跨引擎比较'}`
}
export function selectionFromSegment(item: ReferenceCandidate) {
  return hasTimestamp(item) ? { start: item.start, end: item.end, transcript: item.text || '', confirmed: false } : null
}
