import { create } from 'zustand'
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
  alignSubtitles: boolean
  translateProvider: string
  translateModel: string
  translateConnectionId?: string
  originalVolume: number
  ttsVolumeRatio: number
  ttsDelay: number
  useVocalSeparator: boolean
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
  alignSubtitles: false,
  translateProvider: 'deepseek',
  translateModel: 'deepseek-chat',
  translateConnectionId: '',
  originalVolume: 0.85,
  ttsVolumeRatio: 0.5,
  ttsDelay: 0.0,
  useVocalSeparator: true,
  skipExisting: false,
}

interface WorkbenchStore {
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

export const useWorkbenchStore = create<WorkbenchStore>((set) => ({
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
}))
