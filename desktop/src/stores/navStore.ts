import { create } from 'zustand'

export type PageId =
  | 'workbench'
  | 'workflow-presets'
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
  'workflow-presets': '流水线编辑',
  'subtitle-workshop': '字幕工坊',
  'voice-lab': '声音与音色',
  'audio-tools': '音频工具',
  'task-center': '任务中心',
  engines: '引擎与资源',
  settings: '设置',
}

type NavigationGuard = () => boolean | Promise<boolean>
let checkingNavigation = false

interface NavStore {
  activePage: PageId
  setPage: (page: PageId) => Promise<void>
  enginesView: EnginesView
  setEnginesView: (view: EnginesView) => void
  openEngines: (view?: EnginesView) => Promise<void>
  taskCenterView: TaskCenterView
  setTaskCenterView: (view: TaskCenterView) => void
  openTaskCenter: (view?: TaskCenterView) => Promise<void>
  navigationGuard: NavigationGuard | null
  confirmLeaveCurrentPage: () => Promise<boolean>
  setNavigationGuard: (guard: NavigationGuard | null) => void
}

export const useNavStore = create<NavStore>((set, get) => ({
  activePage: 'workbench',
  setPage: async (page) => {
    const state = get()
    if (page !== state.activePage && !(await state.confirmLeaveCurrentPage())) return
    set(page === 'task-center'
      ? { activePage: page, taskCenterView: 'tasks' }
      : { activePage: page })
  },
  taskCenterView: 'tasks',
  enginesView: 'local',
  setEnginesView: (enginesView) => set({ enginesView }),
  openEngines: async (enginesView = 'local') => {
    const state = get()
    if (state.activePage !== 'engines' && !(await state.confirmLeaveCurrentPage())) return
    set({ activePage: 'engines', enginesView })
  },
  setTaskCenterView: (taskCenterView) => set({ taskCenterView }),
  openTaskCenter: async (taskCenterView = 'tasks') => {
    const state = get()
    if (state.activePage !== 'task-center' && !(await state.confirmLeaveCurrentPage())) return
    set({ activePage: 'task-center', taskCenterView })
  },
  navigationGuard: null,
  confirmLeaveCurrentPage: async () => {
    if (checkingNavigation) return false
    checkingNavigation = true
    const guard = get().navigationGuard
    try { return (await guard?.() ?? true) && get().navigationGuard === guard }
    catch (error) { console.error('无法确认离开页面', error); return false }
    finally { checkingNavigation = false }
  },
  setNavigationGuard: (navigationGuard) => set({ navigationGuard }),
}))
