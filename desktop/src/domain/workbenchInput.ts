import type { BatchDiscoveredFileResponse } from '@/api/types'

export const MAX_WORKBENCH_INPUTS = 500

export interface WorkbenchInputItem {
  path: string
  name: string
  size: number
  companionPaths: string[]
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
  }
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
