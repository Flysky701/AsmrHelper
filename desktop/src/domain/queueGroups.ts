import type { BatchRunItemResponse, BatchRunResponse, GraphBatchRunCreateRequest } from '@/api/types'
import { graphBindingIssues, materialType, usedGraphSlots } from '@/components/GraphRunBindings'
import { cloneDraft } from './workflowDraft'
import type { GraphBindings, GraphDefinition, GraphLanguage } from './workflowGraph'
import { fileName, inputPathKey, type WorkbenchInputItem } from './workbenchInput'

export interface FrozenQueueRun {
  batchId: string
  itemId: string
  presetLabel: string
  graph: GraphDefinition | null
  bindings: GraphBindings
  outputDirectory: string
  submittedAt: string
  state?: BatchRunItemResponse['state'] | 'unknown'
}
export interface QueueGroup {
  id: string
  label: string
  materialPaths: string[]
  bindings: GraphBindings
  selected: boolean
  excluded: boolean
  run?: FrozenQueueRun
  pendingRequestId?: string
}
export interface QueueSubmission {
  request: GraphBatchRunCreateRequest
  presetLabel: string
  createdAt: string
  /** Persist before sending. A restored sending request is an unknown outcome. */
  state: 'sending' | 'unknown'
  error?: string
}
export const queueId = () => `group_${crypto.randomUUID()}`
const terminalStates = new Set(['completed', 'failed', 'cancelled', 'skipped', 'history_deleted'])
export const groupEditable = (group: QueueGroup) => !group.pendingRequestId && (!group.run || terminalStates.has(group.run.state ?? 'unknown'))
export const groupLockReason = (group: QueueGroup) => group.pendingRequestId ? '提交结果尚未确认，暂不能编辑或删除素材。'
  : !groupEditable(group) ? ['pending', 'running'].includes(group.run?.state ?? '') ? '本组正在排队或运行，暂不能编辑或删除素材。' : '最近执行状态待核实，暂不能编辑或删除素材。' : ''
export const groupPaths = (group: QueueGroup) => [...new Set([...group.materialPaths,
  ...Object.values(group.bindings).flatMap(binding => [binding.path, ...(binding.audio_path ? [binding.audio_path] : [])])])]

/** Preserve legacy material data. Only a proven history-injected terminal duplicate
 * with identical paths and bindings may collapse into an existing user draft. */
export function migrateMaterialGroups(groups: QueueGroup[]): QueueGroup[] {
  const signature = (group: QueueGroup) => JSON.stringify({ paths: groupPaths(group).map(inputPathKey).sort(),
    bindings: Object.entries(group.bindings).sort(([a], [b]) => a.localeCompare(b)).map(([id, binding]) => [id, {
      ...binding, path: inputPathKey(binding.path), ...(binding.audio_path ? { audio_path: inputPathKey(binding.audio_path) } : {}),
    }]) })
  const drafts = new Set(groups.filter(group => !group.run && !group.pendingRequestId).map(signature))
  return groups.filter(group => !(group.run && !group.pendingRequestId && groupEditable(group)
    && group.id.endsWith(`_${group.run.batchId}`) && drafts.has(signature(group))))
}
export const knownLanguage = (value: unknown): value is GraphLanguage => ['ja', 'zh', 'en'].includes(String(value))
export function groupMaterials(group: QueueGroup, items: WorkbenchInputItem[]) {
  const keys = new Set(group.materialPaths.map(inputPathKey))
  return items.filter(item => keys.has(inputPathKey(item.path)))
}
export function groupIssues(group: QueueGroup, graph: GraphDefinition | null, items: WorkbenchInputItem[]) {
  if (!graph) return ['请先选择已保存的流水线']
  const local = groupMaterials(group, items)
  const issues = graphBindingIssues(graph, group.bindings, local)
  for (const slot of usedGraphSlots(graph)) {
    const binding = group.bindings[slot.id]
    for (const path of binding ? [binding.path, ...(binding.audio_path ? [binding.audio_path] : [])] : []) {
      const item = local.find(item => inputPathKey(item.path) === inputPathKey(path))
      if (item && !item.inspection?.ready) issues.push(`${item.name}：${item.inspection?.reason || '尚未检查文件，请重新检查'}`)
    }
  }
  return [...new Set(issues)]
}

/** Only one candidate and one slot of its type can be provisionally bound.
 * Language evidence comes from inspection; audio/subtitle timeline pairing is never inferred. */
export function initialGroupBindings(graph: GraphDefinition | null, items: WorkbenchInputItem[]): GraphBindings {
  if (!graph) return {}
  const slots = usedGraphSlots(graph), bindings: GraphBindings = {}
  for (const slot of slots) {
    const candidates = items.filter(item => materialType(item) === slot.type)
    if (slots.filter(other => other.type === slot.type).length !== 1 || candidates.length !== 1) continue
    const item = candidates[0]!, detected = item.subtitleSummary?.language
    if (slot.type === 'subtitle' && (!item.subtitleSummary?.valid || !knownLanguage(detected) || slot.language && slot.language !== detected)) continue
    bindings[slot.id] = { path: item.path, ...(knownLanguage(detected) ? { language: detected } : {}) }
  }
  return bindings
}

/** A discovered companion belongs with one audio only when discovery has a unique owner.
 * Ambiguous companions remain separate visible groups. No filename-only pairing. */
export function createImportedGroups(items: WorkbenchInputItem[], existing: QueueGroup[], graph: GraphDefinition | null, autoBind = true): QueueGroup[] {
  const present = new Set(existing.flatMap(group => group.materialPaths.map(inputPathKey)))
  const fresh = items.filter(item => !present.has(inputPathKey(item.path)))
  const audio = fresh.filter(item => materialType(item) === 'audio')
  const owners = new Map<string, number>()
  audio.forEach(item => item.companionPaths.forEach(path => owners.set(inputPathKey(path), (owners.get(inputPathKey(path)) ?? 0) + 1)))
  const assigned = new Set<string>()
  const bundles: WorkbenchInputItem[][] = audio.map(item => {
    const companions = fresh.filter(candidate => materialType(candidate) === 'subtitle'
      && owners.get(inputPathKey(candidate.path)) === 1 && item.companionPaths.some(path => inputPathKey(path) === inputPathKey(candidate.path)))
    ;[item, ...companions].forEach(candidate => assigned.add(inputPathKey(candidate.path)))
    return [item, ...companions]
  })
  fresh.filter(item => !assigned.has(inputPathKey(item.path))).forEach(item => bundles.push([item]))
  return bundles.map(bundle => {
    const group: QueueGroup = { id: queueId(), label: fileName(bundle[0]!.path).replace(/\.[^.]+$/, '').slice(0, 100),
      materialPaths: bundle.map(item => item.path), bindings: autoBind ? initialGroupBindings(graph, bundle) : {}, selected: false, excluded: false }
    group.selected = autoBind && !!graph && groupIssues(group, graph, items).length === 0
    return group
  })
}

export function attachSubmittedBatch(groups: QueueGroup[], batch: BatchRunResponse, submission?: QueueSubmission | null): QueueGroup[] {
  const next = [...groups]
  for (const item of batch.items.filter(item => !!item.group_id)) {
    // Existing user inputs remain in groups; deleted records must not create new
    // empty input groups from their intentionally redacted historical fields.
    let index = next.findIndex(group => group.run?.batchId === batch.batch_id && group.run.itemId === item.item_id)
    if (index < 0 && submission && submission.request.client_request_id === batch.client_request_id) index = next.findIndex(group =>
      group.id === item.group_id && group.pendingRequestId === submission.request.client_request_id)
    // A background list is history, not an import operation. Never create materials
    // from it, or use old execution parameters to overwrite the current draft.
    if (index < 0) continue
    const acceptedSubmission = !!submission && submission.request.client_request_id === batch.client_request_id
      && next[index]!.pendingRequestId === submission.request.client_request_id
    if (next[index]!.run && !acceptedSubmission) {
      next[index] = { ...next[index]!, run: { ...next[index]!.run!, state: item.state } }
      continue
    }
    const bindings = cloneDraft(item.bindings ?? submission?.request.groups.find(group => group.group_id === item.group_id)?.bindings ?? {})
    const run: FrozenQueueRun = { batchId: batch.batch_id, itemId: item.item_id, bindings,
      graph: submission ? cloneDraft(submission.request.execution_profile.graph) : null,
      presetLabel: submission?.presetLabel ?? batch.name, outputDirectory: batch.output_dir, submittedAt: batch.created_at, state: item.state }
    next[index] = { ...next[index]!, selected: false, pendingRequestId: undefined, run }
  }
  return migrateMaterialGroups(next)
}
