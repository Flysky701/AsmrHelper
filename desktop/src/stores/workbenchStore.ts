import { create } from 'zustand'
import type { PresetItem } from '@/api/types'

interface WorkbenchParams {
  sourceLang: string
  targetLang: string
  ttsEngine: string
  ttsVoice: string
  vocalModel: string
  asrModel: string
  translateProvider: string
  ttsSpeed: number
  originalVolume: number
  ttsVolumeRatio: number
  ttsDelay: number
  useVocalSeparator: boolean
  voiceProfileId: string | null
  skipExisting: boolean
}

const DEFAULT_PARAMS: WorkbenchParams = {
  sourceLang: 'ja',
  targetLang: 'zh',
  ttsEngine: 'edge',
  ttsVoice: 'zh-CN-XiaoxiaoNeural',
  vocalModel: 'htdemucs',
  asrModel: 'base',
  translateProvider: 'deepseek',
  ttsSpeed: 1.0,
  originalVolume: 0.85,
  ttsVolumeRatio: 0.5,
  ttsDelay: 0.0,
  useVocalSeparator: true,
  voiceProfileId: null,
  skipExisting: false,
}

interface WorkbenchStore {
  selectedFiles: string[]
  selectedFolder: string | null
  preset: string
  params: WorkbenchParams
  layer2Expanded: boolean
  layer3Expanded: boolean
  commonExpanded: boolean
  modelExpanded: boolean
  advExpanded: boolean
  presetsLoading: boolean
  presets: PresetItem[]

  setFiles: (files: string[]) => void
  removeFile: (path: string) => void
  setFolder: (folder: string | null) => void
  setPreset: (preset: string) => void
  setPresets: (presets: PresetItem[]) => void
  setPresetsLoading: (loading: boolean) => void
  updateParam: <K extends keyof WorkbenchParams>(key: K, value: WorkbenchParams[K]) => void
  toggleLayer2: () => void
  toggleLayer3: () => void
  toggleCommon: () => void
  toggleModel: () => void
  toggleAdv: () => void
  reset: () => void
}

export const useWorkbenchStore = create<WorkbenchStore>((set) => ({
  selectedFiles: [],
  selectedFolder: null,
  preset: '',
  params: { ...DEFAULT_PARAMS },
  layer2Expanded: true,
  layer3Expanded: false,
  commonExpanded: true,
  modelExpanded: true,
  advExpanded: false,
  presetsLoading: false,
  presets: [],

  setFiles: (files) => set({ selectedFiles: files }),
  removeFile: (path) =>
    set((s) => ({
      selectedFiles: s.selectedFiles.filter((f) => f !== path),
    })),
  setFolder: (folder) => set({ selectedFolder: folder }),
  setPreset: (preset) => set({ preset }),
  setPresets: (presets) => set({ presets }),
  setPresetsLoading: (loading) => set({ presetsLoading: loading }),
  updateParam: (key, value) =>
    set((s) => ({ params: { ...s.params, [key]: value } })),
  toggleLayer2: () => set((s) => ({ layer2Expanded: !s.layer2Expanded })),
  toggleLayer3: () => set((s) => ({ layer3Expanded: !s.layer3Expanded })),
  toggleCommon: () => set((s) => ({ commonExpanded: !s.commonExpanded })),
  toggleModel: () => set((s) => ({ modelExpanded: !s.modelExpanded })),
  toggleAdv: () => set((s) => ({ advExpanded: !s.advExpanded })),
  reset: () =>
    set({
      selectedFiles: [],
      selectedFolder: null,
      preset: '',
      params: { ...DEFAULT_PARAMS },
      layer2Expanded: true,
      layer3Expanded: false,
      commonExpanded: true,
      modelExpanded: true,
      advExpanded: false,
    }),
}))
