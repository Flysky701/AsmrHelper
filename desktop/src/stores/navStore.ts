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
export type EnginesView = 'local' | 'remote' | 'external'
export type ReviewView = 'drafts' | 'subtitles'

export const PAGE_LABELS: Record<PageId, string> = {
  workbench: '创作台',
  'workflow-presets': '高级流程编排',
  'subtitle-workshop': '精修与字幕',
  'voice-lab': '音色与配音',
  'audio-tools': '音频工具',
  'task-center': '任务记录',
  engines: '算力与模型',
  settings: '设置',
}

type NavigationGuard = () => boolean | Promise<boolean>
let checkingNavigation = false

interface NavStore {
  activePage: PageId
  setPage: (page: PageId) => Promise<void>
  navCollapsed: boolean
  toggleNavCollapsed: () => void
  pendingDraftCount: number
  setPendingDraftCount: (count: number) => void
  reviewView: ReviewView
  openReview: (view?: ReviewView) => Promise<void>
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
  navCollapsed: false,
  toggleNavCollapsed: () => set((s) => ({ navCollapsed: !s.navCollapsed })),
  pendingDraftCount: 0,
  setPendingDraftCount: (pendingDraftCount) => set({ pendingDraftCount }),
  reviewView: 'drafts',
  openReview: async (reviewView = 'drafts') => {
    const state = get()
    if (state.activePage === 'subtitle-workshop' && state.reviewView === reviewView) return
    if (!(await state.confirmLeaveCurrentPage())) return
    set({ activePage: 'subtitle-workshop', reviewView })
  },
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
