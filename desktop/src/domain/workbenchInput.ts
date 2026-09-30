import type { BatchDiscoveredFileResponse } from '@/api/types'

export const MAX_WORKBENCH_INPUTS = 500

export interface CompanionSubtitle {
  path: string
  language: string
  valid: boolean
  reason: string
}

export interface WorkbenchInputItem {
  path: string
  name: string
  size: number
  kind?: string
  subtitleSummary?: { language: string; valid: boolean; reason: string }
  companionPaths: string[]
  companionSubtitles?: CompanionSubtitle[]
}

export function inputPathKey(path: string) {
  return path.replace(/\\/g, '/').toLocaleLowerCase()
}

export function fileName(path: string) {
  return path.split(/[/\\]/).pop() || path
}

export function discoveredFileToInput(
  item: BatchDiscoveredFileResponse,
): WorkbenchInputItem {
  return {
    path: item.path,
    name: item.name || fileName(item.path),
    size: item.size_bytes,
    companionPaths: [...item.companion_paths],
    companionSubtitles: item.companion_subtitles ?? [],
  }
}

export function companionDescription(item: WorkbenchInputItem) {
  if (item.subtitleSummary) {
    const summary = item.subtitleSummary
    return summary.valid ? `字幕 · ${summary.language || '语言待确认'} · 来源与对应关系由你选择`
      : `字幕待校验：${summary.reason}`
  }
  return /\.(srt|vtt|lrc)$/i.test(item.path) ? '字幕 · 语言与时间轴待检查' : '音频素材'
}

/** Discovery adds visible candidates to the pool; it never binds an execution input. */
export function expandInputMaterials(items: WorkbenchInputItem[]): WorkbenchInputItem[] {
  return mergeInputItems([], items.flatMap(item => [item, ...item.companionPaths.map(path => {
    const summary = item.companionSubtitles?.find(candidate => inputPathKey(candidate.path) === inputPathKey(path))
    return { path, name: fileName(path), size: 0, kind: 'subtitle', companionPaths: [],
      subtitleSummary: summary ? { language: summary.language, valid: summary.valid, reason: summary.reason } : undefined }
  })]))
}

export function pathToInput(path: string): WorkbenchInputItem {
  return {
    path,
    name: fileName(path),
    size: 0,
    companionPaths: [],
  }
}

export function mergeInputItems(
  current: WorkbenchInputItem[],
  incoming: WorkbenchInputItem[],
) {
  const byPath = new Map(current.map((item) => [inputPathKey(item.path), item]))
  incoming.forEach((item) => {
    const key = inputPathKey(item.path)
    byPath.set(key, {
      ...byPath.get(key),
      ...item,
      subtitleSummary: item.subtitleSummary ?? byPath.get(key)?.subtitleSummary,
      companionPaths: Array.from(new Map(
        item.companionPaths.map((path) => [inputPathKey(path), path]),
      ).values()),
    })
  })
  return Array.from(byPath.values()).sort((left, right) => (
    left.path.localeCompare(right.path)
  ))
}
