import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { PipelineStageId } from '@/domain/pipelinePreset'
import type { WorkflowReference } from '@/api/types'
import { applyFlowPreset, emptyFlow, restoreFlow, toggleFlowStage, type FlowDraft } from '@/domain/workbenchFlow'
import type { PresetItem } from '@/api/types'
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
  flow: FlowDraft
  toggleStage: (stage: PipelineStageId) => void
  applyStepPreset: (presetId: string) => void
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
  flow: emptyFlow(),
  toggleStage: (stage) => set(s => ({ flow: toggleFlowStage(s.flow, stage) })),
  applyStepPreset: (presetId) => set(s => ({ flow: applyFlowPreset(s.flow, presetId) })),
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
    return { ...current, ...saved, params, flow: restoreFlow(saved.flow) }
  },
}))
