import { create } from 'zustand'

export type PageId =
  | 'workbench'
  | 'subtitle-workshop'
  | 'voice-lab'
  | 'audio-tools'
  | 'task-center'
  | 'engines'
  | 'settings'

export type TaskCenterView = 'tasks' | 'batches'

export const PAGE_LABELS: Record<PageId, string> = {
  workbench: '工作台',
  'subtitle-workshop': '字幕工坊',
  'voice-lab': '音色实验室',
  'audio-tools': '音频工具',
  'task-center': '任务中心',
  engines: '引擎与资源',
  settings: '设置',
}

export const PAGE_ORDER: PageId[] = [
  'workbench',
  'subtitle-workshop',
  'voice-lab',
  'audio-tools',
  'task-center',
  'engines',
  'settings',
]

interface NavStore {
  activePage: PageId
  setPage: (page: PageId) => void
  taskCenterView: TaskCenterView
  setTaskCenterView: (view: TaskCenterView) => void
  openTaskCenter: (view?: TaskCenterView) => void
  navigationGuard: (() => boolean) | null
  confirmLeaveCurrentPage: () => boolean
  setNavigationGuard: (guard: (() => boolean) | null) => void
}

export const useNavStore = create<NavStore>((set, get) => ({
  activePage: 'workbench',
  setPage: (page) => {
    const state = get()
    if (page !== state.activePage && !state.confirmLeaveCurrentPage()) return
    set(page === 'task-center'
      ? { activePage: page, taskCenterView: 'tasks' }
      : { activePage: page })
  },
  taskCenterView: 'tasks',
  setTaskCenterView: (taskCenterView) => set({ taskCenterView }),
  openTaskCenter: (taskCenterView = 'tasks') => {
    const state = get()
    if (state.activePage !== 'task-center' && !state.confirmLeaveCurrentPage()) return
    set({ activePage: 'task-center', taskCenterView })
  },
  navigationGuard: null,
  confirmLeaveCurrentPage: () => get().navigationGuard?.() ?? true,
  setNavigationGuard: (navigationGuard) => set({ navigationGuard }),
}))
