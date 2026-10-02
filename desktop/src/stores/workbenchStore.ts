import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { PipelineStageId } from '@/domain/pipelinePreset'
import type { WorkflowReference } from '@/api/types'
import { applyFlowPreset, emptyFlow, restoreFlow, toggleFlowStage, type FlowDraft } from '@/domain/workbenchFlow'
import type { PresetItem } from '@/api/types'
import type { BatchRunResponse } from '@/api/types'
import type { GraphBindings, GraphDefinition, GraphMaterialBinding } from '@/domain/workflowGraph'
import { attachSubmittedBatch, createImportedGroups, groupEditable, queueId, type QueueGroup, type QueueSubmission } from '@/domain/queueGroups'
import { cloneDraft } from '@/domain/workflowDraft'
import {
  inputPathKey,
  mergeInputItems,
  type WorkbenchInputItem,
} from '@/domain/workbenchInput'

export interface WorkbenchParams {
  sourceLang: string
  targetLang: string
  ttsEngine: string
  vocalProvider: string
  vocalModel: string
  asrProvider: string
  asrModel: string
  translateProvider: string
  translateModel: string
  translateConnectionId?: string
  originalVolume: number
  ttsVolumeRatio: number
  ttsDelay: number
  skipExisting: boolean
}

const DEFAULT_PARAMS: WorkbenchParams = {
  sourceLang: 'ja',
  targetLang: 'zh',
  ttsEngine: 'edge',
  vocalProvider: 'demucs',
  vocalModel: 'htdemucs',
  asrProvider: 'faster_whisper',
  asrModel: 'faster-whisper-base',
  translateProvider: 'deepseek',
  translateModel: 'deepseek-chat',
  translateConnectionId: '',
  originalVolume: 0.85,
  ttsVolumeRatio: 0.5,
  ttsDelay: 0.0,
  skipExisting: false,
}

interface WorkbenchStore {
  queueGroups: QueueGroup[]
  queueInitialized: boolean
  queueMigrationNotice: boolean
  queueSubmission: QueueSubmission | null
  queueBatches: BatchRunResponse[]
  queueBatchActions: Record<string, { action: 'retry' | 'cancel'; taskIds: string; state: string }>
  beginQueueBatchAction: (batch: BatchRunResponse, action: 'retry' | 'cancel') => void
  clearQueueBatchAction: (batchId: string) => void
  initializeQueue: (graph: GraphDefinition | null, legacyBindings: GraphBindings) => void
  importQueueItems: (items: WorkbenchInputItem[], graph: GraphDefinition | null) => void
  patchQueueGroup: (id: string, patch: Partial<Pick<QueueGroup, 'label' | 'selected' | 'excluded' | 'materialPaths'>>) => void
  bindQueueGroup: (id: string, slotId: string, binding: GraphMaterialBinding | undefined) => void
  selectQueueGroups: (ids: string[], selected: boolean) => void
  duplicateQueueGroup: (id: string) => void
  beginQueueSubmission: (submission: QueueSubmission) => void
  failQueueSubmission: (error: string, uncertain: boolean) => void
  receiveQueueBatch: (batch: BatchRunResponse) => void
  flow: FlowDraft
  toggleStage: (stage: PipelineStageId) => void
  applyStepPreset: (preset: PresetItem) => void
  setBinding: (stage: PipelineStageId, port: string, ref?: WorkflowReference) => void
  toggleOutput: (stage: PipelineStageId) => void
  setSubtitleFormat: (format: 'srt' | 'vtt') => void
  inputItems: WorkbenchInputItem[]
  selectedInputPaths: string[]
  inputFolder: string | null
  scanRecursive: boolean
  outputDirectory: string
  batchName: string
  batchMaxParallel: number
  preset: string
  params: WorkbenchParams
  llmSelectionInitialized: boolean
  layer2Expanded: boolean
  layer3Expanded: boolean
  commonExpanded: boolean
  modelExpanded: boolean
  advExpanded: boolean
  presetsLoading: boolean
  presets: PresetItem[]
  capabilityOptions: Record<string, Record<string, unknown>>

  addInputItems: (items: WorkbenchInputItem[]) => void
  removeInputItem: (path: string) => void
  toggleInputSelection: (path: string) => void
  selectAllInputs: (selected: boolean) => void
  clearInputItems: () => void
  setInputFolder: (folder: string | null) => void
  setScanRecursive: (recursive: boolean) => void
  setOutputDirectory: (directory: string) => void
  setBatchName: (name: string) => void
  setBatchMaxParallel: (maxParallel: number) => void
  setPreset: (preset: string) => void
  setPresets: (presets: PresetItem[]) => void
  setPresetsLoading: (loading: boolean) => void
  updateParam: <K extends keyof WorkbenchParams>(key: K, value: WorkbenchParams[K]) => void
  updateCapabilityOption: (scope: string, name: string, value: unknown) => void
  toggleLayer2: () => void
  toggleLayer3: () => void
  toggleCommon: () => void
  toggleModel: () => void
  toggleAdv: () => void
  reset: () => void
}

export const useWorkbenchStore = create<WorkbenchStore>()(persist((set) => ({
  queueGroups: [], queueInitialized: false, queueMigrationNotice: false, queueSubmission: null, queueBatches: [], queueBatchActions: {},
  beginQueueBatchAction: (batch, action) => set(state => ({ queueBatchActions: { ...state.queueBatchActions,
    [batch.batch_id]: { action, taskIds: JSON.stringify(batch.items.flatMap(item => item.task_ids)), state: batch.state } } })),
  clearQueueBatchAction: batchId => set(state => ({ queueBatchActions: Object.fromEntries(Object.entries(state.queueBatchActions).filter(([id]) => id !== batchId)) })),
  initializeQueue: (graph, legacyBindings) => set(state => {
    if (state.queueInitialized) return {}
    const groups: QueueGroup[] = []
    const legacyPaths = Object.values(legacyBindings).flatMap(binding => [binding.path, ...(binding.audio_path ? [binding.audio_path] : [])])
    if (legacyPaths.length) groups.push({ id: queueId(), label: '原工作台绑定', materialPaths: [...new Set(legacyPaths)], bindings: cloneDraft(legacyBindings), selected: false, excluded: false })
    groups.push(...createImportedGroups(state.inputItems, groups, graph, false))
    return { queueGroups: groups, queueInitialized: true, queueMigrationNotice: groups.length > 0 }
  }),
  importQueueItems: (items, graph) => set(state => {
    const merged = mergeInputItems(state.inputItems, items)
    return { inputItems: merged, queueGroups: [...state.queueGroups, ...createImportedGroups(items, state.queueGroups, graph)], queueInitialized: true }
  }),
  patchQueueGroup: (id, patch) => set(state => ({ queueGroups: state.queueGroups.map(group =>
    group.id === id && groupEditable(group) ? { ...group, ...patch, ...(patch.excluded ? { selected: false } : {}) } : group) })),
  bindQueueGroup: (id, slotId, binding) => set(state => ({ queueGroups: state.queueGroups.map(group => {
    if (group.id !== id || !groupEditable(group)) return group
    const bindings = { ...group.bindings }
    if (binding) bindings[slotId] = cloneDraft(binding)
    else delete bindings[slotId]
    return { ...group, bindings, materialPaths: [...new Set([...group.materialPaths, ...(binding ? [binding.path, ...(binding.audio_path ? [binding.audio_path] : [])] : [])])] }
  }) })),
  selectQueueGroups: (ids, selected) => set(state => ({ queueGroups: state.queueGroups.map(group =>
    ids.includes(group.id) && groupEditable(group) && !group.excluded ? { ...group, selected } : group) })),
  duplicateQueueGroup: id => set(state => {
    const group = state.queueGroups.find(item => item.id === id)
    if (!group) return {}
    return { queueGroups: [...state.queueGroups, { id: queueId(), label: `${group.label.slice(0, 95)} · 副本`,
      materialPaths: [...group.materialPaths], bindings: cloneDraft(group.run?.bindings ?? group.bindings), selected: false, excluded: false }] }
  }),
  beginQueueSubmission: submission => set(state => {
    if (state.queueSubmission) return {}
    const ids = new Set(submission.request.groups.map(group => group.group_id))
    return { queueSubmission: cloneDraft(submission), queueGroups: state.queueGroups.map(group => ids.has(group.id)
      ? { ...group, pendingRequestId: submission.request.client_request_id } : group) }
  }),
  failQueueSubmission: (error, uncertain) => set(state => {
    if (!state.queueSubmission) return {}
    const id = state.queueSubmission.request.client_request_id
    return uncertain ? { queueSubmission: { ...state.queueSubmission, state: 'unknown' as const, error } }
      : { queueSubmission: null, queueGroups: state.queueGroups.map(group => group.pendingRequestId === id ? { ...group, pendingRequestId: undefined } : group) }
  }),
  receiveQueueBatch: batch => set(state => {
    const matching = state.queueSubmission?.request.client_request_id === batch.client_request_id ? state.queueSubmission : null
    if (matching) {
      const expected = new Set(matching.request.groups.map(group => group.group_id))
      if (batch.items.length !== expected.size || batch.items.some(item => !item.group_id || !expected.delete(item.group_id)) || expected.size) return {}
    }
    const previous = state.queueBatches.find(item => item.batch_id === batch.batch_id)
    if (previous && previous.updated_at > batch.updated_at) return {}
    const pendingAction = state.queueBatchActions[batch.batch_id]
    const resolved = pendingAction && (pendingAction.action === 'retry'
      ? pendingAction.taskIds !== JSON.stringify(batch.items.flatMap(item => item.task_ids)) : pendingAction.state !== batch.state)
    return { queueBatches: [...state.queueBatches.filter(item => item.batch_id !== batch.batch_id), batch],
      ...(resolved ? { queueBatchActions: Object.fromEntries(Object.entries(state.queueBatchActions).filter(([id]) => id !== batch.batch_id)) } : {}),
      queueGroups: attachSubmittedBatch(state.queueGroups, batch, matching), queueSubmission: matching ? null : state.queueSubmission }
  }),
  flow: emptyFlow(),
  toggleStage: (stage) => set(s => ({ flow: toggleFlowStage(s.flow, stage) })),
  applyStepPreset: (preset) => set(s => ({ flow: applyFlowPreset(s.flow, preset) })),
  setBinding: (stage, port, ref) => set(s => {
    const ports = { ...s.flow.bindings[stage] }
    if (ref) ports[port] = ref
    else delete ports[port]
    return { flow: { ...s.flow, bindings: { ...s.flow.bindings, [stage]: ports } } }
  }),
  toggleOutput: (stage) => set(s => ({ flow: { ...s.flow, outputs: s.flow.outputs.includes(stage)
    ? s.flow.outputs.filter(id => id !== stage) : s.flow.selectedStages.includes(stage) ? [...s.flow.outputs, stage] : s.flow.outputs } })),
  setSubtitleFormat: (subtitleFormat) => set(s => ({ flow: { ...s.flow, subtitleFormat } })),
  inputItems: [],
  selectedInputPaths: [],
  inputFolder: null,
  scanRecursive: true,
  outputDirectory: '',
  batchName: '',
  batchMaxParallel: 1,
  preset: '',
  params: { ...DEFAULT_PARAMS },
  llmSelectionInitialized: false,
  layer2Expanded: true,
  layer3Expanded: false,
  commonExpanded: true,
  modelExpanded: true,
  advExpanded: false,
  presetsLoading: false,
  presets: [],
  capabilityOptions: {},

  addInputItems: (items) => set((state) => {
    const merged = mergeInputItems(state.inputItems, items)
    const existingKeys = new Set(state.inputItems.map((item) => inputPathKey(item.path)))
    const selectedKeys = new Set(state.selectedInputPaths.map(inputPathKey))
    items.forEach((item) => {
      const key = inputPathKey(item.path)
      if (!existingKeys.has(key)) selectedKeys.add(key)
    })
    return {
      inputItems: merged,
      selectedInputPaths: merged
        .filter((item) => selectedKeys.has(inputPathKey(item.path)))
        .map((item) => item.path),
    }
  }),
  removeInputItem: (path) => set((state) => {
    const removedKey = inputPathKey(path)
    return {
      inputItems: state.inputItems.filter((item) => inputPathKey(item.path) !== removedKey),
      selectedInputPaths: state.selectedInputPaths.filter((item) => inputPathKey(item) !== removedKey),
    }
  }),
  toggleInputSelection: (path) => set((state) => {
    const pathKey = inputPathKey(path)
    const selected = state.selectedInputPaths.some((item) => inputPathKey(item) === pathKey)
    return {
      selectedInputPaths: selected
        ? state.selectedInputPaths.filter((item) => inputPathKey(item) !== pathKey)
        : [...state.selectedInputPaths, path],
    }
  }),
  selectAllInputs: (selected) => set((state) => ({
    selectedInputPaths: selected ? state.inputItems.map((item) => item.path) : [],
  })),
  clearInputItems: () => set({ inputItems: [], selectedInputPaths: [], inputFolder: null, batchName: '' }),
  setInputFolder: (inputFolder) => set({ inputFolder }),
  setScanRecursive: (scanRecursive) => set({ scanRecursive }),
  setOutputDirectory: (outputDirectory) => set({ outputDirectory }),
  setBatchName: (batchName) => set({ batchName: batchName.slice(0, 100) }),
  setBatchMaxParallel: (batchMaxParallel) => set({ batchMaxParallel }),
  setPreset: (preset) => set({ preset }),
  setPresets: (presets) => set({ presets }),
  setPresetsLoading: (loading) => set({ presetsLoading: loading }),
  updateParam: (key, value) =>
    set((s) => ({
      params: { ...s.params, [key]: value },
      llmSelectionInitialized: s.llmSelectionInitialized || key === 'translateProvider' || key === 'translateModel',
    })),
  updateCapabilityOption: (scope, name, value) =>
    set((s) => ({
      capabilityOptions: {
        ...s.capabilityOptions,
        [scope]: {
          ...s.capabilityOptions[scope],
          [name]: value,
        },
      },
    })),
  toggleLayer2: () => set((s) => ({ layer2Expanded: !s.layer2Expanded })),
  toggleLayer3: () => set((s) => ({ layer3Expanded: !s.layer3Expanded })),
  toggleCommon: () => set((s) => ({ commonExpanded: !s.commonExpanded })),
  toggleModel: () => set((s) => ({ modelExpanded: !s.modelExpanded })),
  toggleAdv: () => set((s) => ({ advExpanded: !s.advExpanded })),
  reset: () =>
    set({
      flow: emptyFlow(),
      queueGroups: [], queueInitialized: true, queueMigrationNotice: false, queueSubmission: null, queueBatches: [], queueBatchActions: {},
      inputItems: [],
      selectedInputPaths: [],
      inputFolder: null,
      scanRecursive: true,
      outputDirectory: '',
      batchName: '',
      batchMaxParallel: 1,
      preset: '',
      params: { ...DEFAULT_PARAMS },
      llmSelectionInitialized: false,
      capabilityOptions: {},
      layer2Expanded: true,
      layer3Expanded: false,
      commonExpanded: true,
      modelExpanded: true,
      advExpanded: false,
    }),
}), {
  name: 'asmrhelper-workbench-flow',
  version: 1,
  partialize: (state) => ({
    queueGroups: state.queueGroups, queueInitialized: state.queueInitialized, queueMigrationNotice: state.queueMigrationNotice,
    queueSubmission: state.queueSubmission, queueBatchActions: state.queueBatchActions,
    flow: state.flow, inputItems: state.inputItems, selectedInputPaths: state.selectedInputPaths,
    inputFolder: state.inputFolder, scanRecursive: state.scanRecursive, outputDirectory: state.outputDirectory,
    params: state.params, capabilityOptions: state.capabilityOptions, llmSelectionInitialized: state.llmSelectionInitialized,
    preset: state.preset, batchName: state.batchName, batchMaxParallel: state.batchMaxParallel,
  }),
  merge: (persisted, current) => {
    const saved = (persisted || {}) as Partial<WorkbenchStore>
    // Old execution switches are not read by the workflow. Preserve other parameters.
    const params = { ...current.params, ...saved.params } as WorkbenchParams & Record<string, unknown>
    for (const old of ['subtitleInputMode', 'reuseTranslations', 'useVocalSeparator', 'alignSubtitles']) delete params[old]
    return { ...current, ...saved, params, flow: restoreFlow(saved.flow),
      queueGroups: Array.isArray(saved.queueGroups) ? saved.queueGroups : [], queueBatches: [],
      queueBatchActions: saved.queueBatchActions ?? {},
      queueSubmission: saved.queueSubmission ? { ...saved.queueSubmission, state: 'unknown' as const } : null }
  },
}))
