import { api } from './client'
import type { CompanionSubtitle, WorkbenchInputItem } from '@/domain/workbenchInput'

export interface InspectInputsRequest {
  paths: string[]
}

export interface InputAssetResponse {
  asset_id: string
  absolute_path: string
  kind: string
  display_name: string
  extension: string
  exists: boolean
  readable: boolean
  size_bytes: number
  warnings: string[]
  subtitle_summary?: { language: string; valid: boolean; reason: string }
}

export interface InspectInputsResponse {
  assets: InputAssetResponse[]
  errors: string[]
  warnings: string[]
}

export interface DiscoverCompanionsRequest {
  asset_id: string
}

export interface DiscoverCompanionsResponse {
  primary_asset_id: string
  suggested_companions: InputAssetResponse[]
  companion_subtitles?: CompanionSubtitle[]
}

export interface ResolveInputsResult {
  items: WorkbenchInputItem[]
  warnings: string[]
}

const DEFAULT_COMPANION_CONCURRENCY = 4

function inspect(paths: string[]) {
  const body: InspectInputsRequest = { paths }
  return api.post<InspectInputsResponse>('/inputs/inspect', body)
}

function discoverCompanions(assetId: string) {
  const body: DiscoverCompanionsRequest = { asset_id: assetId }
  return api.post<DiscoverCompanionsResponse>('/inputs/discover-companions', body)
}

async function mapWithConcurrency<T, R>(
  items: T[],
  concurrency: number,
  mapper: (item: T) => Promise<R>,
): Promise<R[]> {
  if (items.length === 0) return []

  const results = new Array<R>(items.length)
  let nextIndex = 0
  let firstError: unknown
  let failed = false
  const workerCount = Math.min(Math.max(1, concurrency), items.length)

  await Promise.all(Array.from({ length: workerCount }, async () => {
    while (nextIndex < items.length && !failed) {
      const index = nextIndex
      nextIndex += 1
      try {
        results[index] = await mapper(items[index]!)
      } catch (error) {
        if (!failed) firstError = error
        failed = true
      }
    }
  }))

  if (failed) throw firstError
  return results
}

async function resolveItems(
  paths: string[],
  companionConcurrency = DEFAULT_COMPANION_CONCURRENCY,
): Promise<ResolveInputsResult> {
  const inspected = await inspect(paths)
  const resolved = await mapWithConcurrency(inspected.assets, companionConcurrency, async (asset) => {
    let companionPaths: string[] = []
    let companionSubtitles: CompanionSubtitle[] = []
    let warning = ''
    if (asset.kind === 'audio' && asset.exists) {
      try {
        const discovered = await discoverCompanions(asset.asset_id)
        companionSubtitles = discovered.companion_subtitles ?? []
        companionPaths = discovered.suggested_companions
          .map((companion) => companion.absolute_path)
      } catch (error) {
        warning = `${asset.display_name || asset.absolute_path} 的伴随字幕发现失败：${error instanceof Error ? error.message : String(error)}`
      }
    }

    return {
      item: {
        path: asset.absolute_path,
        kind: asset.kind,
        subtitleSummary: asset.subtitle_summary,
        name: asset.display_name,
        size: asset.size_bytes,
        companionPaths,
        companionSubtitles,
      },
      warning,
    }
  })

  return {
    items: resolved.map((item) => item.item),
    warnings: [
      ...inspected.errors,
      ...inspected.warnings,
      ...inspected.assets.flatMap((asset) => asset.warnings),
      ...resolved.map((item) => item.warning).filter(Boolean),
    ],
  }
}

export const inputsApi = {
  inspect,
  discoverCompanions,
  resolveItems,
}
