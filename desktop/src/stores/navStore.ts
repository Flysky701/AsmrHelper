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
export type EnginesView = 'local' | 'external'

export const PAGE_LABELS: Record<PageId, string> = {
  workbench: '工作台',
  'subtitle-workshop': '字幕工坊',
  'voice-lab': '声音与音色',
  'audio-tools': '音频工具',
  'task-center': '任务中心',
  engines: '引擎与资源',
  settings: '设置',
}

interface NavStore {
  activePage: PageId
  setPage: (page: PageId) => void
  enginesView: EnginesView
  setEnginesView: (view: EnginesView) => void
  openEngines: (view?: EnginesView) => void
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
  enginesView: 'local',
  setEnginesView: (enginesView) => set({ enginesView }),
  openEngines: (enginesView = 'local') => {
    const state = get()
    if (state.activePage !== 'engines' && !state.confirmLeaveCurrentPage()) return
    set({ activePage: 'engines', enginesView })
  },
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
