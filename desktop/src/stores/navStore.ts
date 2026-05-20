import { create } from 'zustand'

export type PageId =
  | 'workbench'
  | 'tools'
  | 'voice-lab'
  | 'tasks'
  | 'resources'
  | 'settings'

export const PAGE_LABELS: Record<PageId, string> = {
  workbench: '汉化工作台',
  tools: '工具箱',
  'voice-lab': '音色实验室',
  tasks: '任务/日志',
  resources: '资源中心',
  settings: '设置',
}

export const PAGE_ORDER: PageId[] = [
  'workbench',
  'tools',
  'voice-lab',
  'tasks',
  'resources',
  'settings',
]

interface NavStore {
  activePage: PageId
  setPage: (page: PageId) => void
}

export const useNavStore = create<NavStore>((set) => ({
  activePage: 'workbench',
  setPage: (page) => set({ activePage: page }),
}))
