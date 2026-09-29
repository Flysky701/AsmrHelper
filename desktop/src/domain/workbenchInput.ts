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

export function companionDescription(item: WorkbenchInputItem, source: string, target: string) {
  const normalize = (value: string) => value.toLowerCase().replace('-', '_').split('_')[0] || 'unknown'
  const names: Record<string, string> = { zh: '中文', ja: '日语', en: '英语', ko: '韩语', mixed: '多语言', unknown: '语言不确定' }
  if (!item.companionPaths.length) return '无伴随字幕'
  if (!item.companionSubtitles?.length) return '已发现字幕 · 语言待检查，运行时校验'
  return item.companionSubtitles.map(subtitle => {
    const language = normalize(subtitle.language)
    const label = `${fileName(subtitle.path)} · ${names[language] || language}`
    if (!subtitle.valid) return `${label} · 无法使用：${subtitle.reason}`
    if (['unknown', 'mixed', 'auto'].includes(language)) return `${label} · 不作为原文，保留 ASR`
    if (language === normalize(source)) return `${label} · 与原语言一致，时间轴有效时复用`
    if (language === normalize(target)) return `${label} · 可能为目标译文，保留 ASR 原文识别`
    return `${label} · 与原语言不符，保留 ASR`
  }).join('；')
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
      ...item,
      companionPaths: Array.from(new Map(
        item.companionPaths.map((path) => [inputPathKey(path), path]),
      ).values()),
    })
  })
  return Array.from(byPath.values()).sort((left, right) => (
    left.path.localeCompare(right.path)
  ))
}
