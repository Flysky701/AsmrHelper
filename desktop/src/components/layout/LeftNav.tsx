import { t, useI18n } from '@/i18n'
import { useNavStore, PAGE_LABELS } from '@/stores/navStore'
import type { PageId } from '@/stores/navStore'
import { draftsApi } from '@/api/drafts'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const NAV_ICONS: Record<PageId, ReactNode> = {
  workbench: (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="3" width="12" height="12" rx="2" />
      <path d="M3 7h12" />
      <path d="M8 10.5l3 1.75-3 1.75v-3.5z" fill="currentColor" stroke="none" />
    </svg>
  ),
  'subtitle-workshop': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="4" width="12" height="10" rx="2" />
      <path d="M6 8h6M6 11h4" />
    </svg>
  ),
  'voice-lab': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M9 3v12M5 7v4M13 6v6" />
    </svg>
  ),
  'task-center': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M4 5h10M4 9h10M4 13h6" />
    </svg>
  ),
  'audio-tools': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M4 5h10M6 9h6M8 13h2" />
      <circle cx="5" cy="5" r="1" fill="currentColor" stroke="none" />
      <circle cx="13" cy="9" r="1" fill="currentColor" stroke="none" />
      <circle cx="7" cy="13" r="1" fill="currentColor" stroke="none" />
    </svg>
  ),
  'workflow-presets': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="6" width="4" height="5" rx="1" /><rect x="12" y="2" width="4" height="5" rx="1" />
      <rect x="12" y="11" width="4" height="5" rx="1" /><path d="M6 8.5h3V4.5h3M9 8.5v5h3" />
    </svg>
  ),
  engines: (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M10 2L4.5 10H9l-1 6 5.5-8H9l1-6z" />
    </svg>
  ),
  settings: (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="9" cy="9" r="2.5" />
      <path d="M9 3v1.5M9 13.5V15M3 9h1.5M13.5 9H15M5 5l1 1M12 12l1 1M5 13l1-1M12 6l1-1" />
    </svg>
  ),
}

const PRIMARY_PAGES: PageId[] = ['workbench', 'subtitle-workshop', 'voice-lab', 'task-center', 'audio-tools']
const SYSTEM_PAGES: PageId[] = ['engines', 'settings']

const PAGE_DESCRIPTIONS: Record<PageId, string> = {
  workbench: '制作字幕、配音或批量处理音频',
  'subtitle-workshop': '核对台词、试听样音和编辑字幕',
  'voice-lab': '管理音色预设、参考干声与 A/B 试听',
  'task-center': '查看任务进度、批次队列与运行产物',
  'audio-tools': '人声分离、格式转换、按字幕切分与音量分析',
  'workflow-presets': '高级节点画布与自定义流水线预设',
  engines: '管理本机模型、国内镜像、远端 Colab GPU 与外部 API',
  settings: '外观语言、工作区目录与 AI Agent / MCP 接入',
}

export default function LeftNav() {
  useI18n()
  const activePage = useNavStore((s) => s.activePage)
  const setPage = useNavStore((s) => s.setPage)
  const collapsed = useNavStore((s) => s.navCollapsed)
  const toggleCollapsed = useNavStore((s) => s.toggleNavCollapsed)
  const pendingDraftCount = useNavStore((s) => s.pendingDraftCount)
  const setPendingDraftCount = useNavStore((s) => s.setPendingDraftCount)
  const tooltipId = useId()
  const [tooltip, setTooltip] = useState<{ pageId: PageId; top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    let alive = true
    const refreshCount = async () => {
      try {
        const res = await draftsApi.list({ state: 'awaiting_review', limit: 50 })
        if (alive) setPendingDraftCount(res.drafts.length)
      } catch {
        // Ignore offline/preview polling errors silently.
      }
    }
    void refreshCount()
    const timer = window.setInterval(() => void refreshCount(), 15000)
    return () => { alive = false; window.clearInterval(timer) }
  }, [setPendingDraftCount])

  const cancelClose = () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current)
    closeTimer.current = null
  }
  const showTooltip = (pageId: PageId, trigger: HTMLButtonElement) => {
    if (!collapsed) return
    cancelClose()
    triggerRef.current = trigger
    const rect = trigger.getBoundingClientRect()
    setTooltip({ pageId, top: Math.max(8, Math.min(rect.top - 10, window.innerHeight - 88)), left: rect.right + 12 })
  }
  const scheduleClose = () => {
    cancelClose()
    closeTimer.current = setTimeout(() => {
      closeTimer.current = null
      if (document.activeElement === triggerRef.current || triggerRef.current?.matches(':hover') || tooltipRef.current?.matches(':hover')) return
      setTooltip(null)
    }, 120)
  }

  useEffect(() => {
    if (!collapsed) setTooltip(null)
  }, [collapsed])

  useEffect(() => {
    const reposition = () => setTooltip(current => {
      const trigger = triggerRef.current
      if (!current || !trigger) return null
      const rect = trigger.getBoundingClientRect()
      const scroller = trigger.closest('.app-nav__scroller')?.getBoundingClientRect()
      if (scroller && (rect.bottom <= scroller.top || rect.top >= scroller.bottom)) return null
      return { ...current, top: Math.max(8, Math.min(rect.top - 10, window.innerHeight - 88)), left: rect.right + 12 }
    })
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setTooltip(null)
    }
    document.addEventListener('keydown', handleKey)
    window.addEventListener('resize', reposition)
    window.addEventListener('scroll', reposition, true)
    return () => {
      document.removeEventListener('keydown', handleKey)
      window.removeEventListener('resize', reposition)
      window.removeEventListener('scroll', reposition, true)
      if (closeTimer.current !== null) clearTimeout(closeTimer.current)
    }
  }, [])

  const renderItem = (pageId: PageId) => {
    const isActive = activePage === pageId || (pageId === 'workbench' && activePage === 'workflow-presets')
    const badge = pageId === 'subtitle-workshop' && pendingDraftCount > 0 ? pendingDraftCount : 0
    return (
      <button
        key={pageId}
        type="button"
        className="app-nav__item"
        data-page={pageId}
        title={!collapsed ? t(PAGE_DESCRIPTIONS[pageId]) : undefined}
        aria-label={t(PAGE_LABELS[pageId])}
        aria-current={isActive ? 'page' : undefined}
        aria-describedby={tooltip?.pageId === pageId ? tooltipId : undefined}
        onMouseEnter={event => showTooltip(pageId, event.currentTarget)}
        onMouseLeave={scheduleClose}
        onFocus={event => showTooltip(pageId, event.currentTarget)}
        onBlur={scheduleClose}
        onClick={() => { cancelClose(); setTooltip(null); void setPage(pageId) }}
      >
        <span aria-hidden="true" className="app-nav__icon">{NAV_ICONS[pageId]}</span>
        {!collapsed && <span className="app-nav__label">{t(PAGE_LABELS[pageId])}</span>}
        {badge > 0 && <span className="app-nav__badge" aria-label={`${badge} 待审`}>{badge > 99 ? '99+' : badge}</span>}
      </button>
    )
  }

  return (
    <nav className={`app-nav${collapsed ? ' is-collapsed' : ''}`} aria-label={t("主导航")}>
      <div className="app-nav__header">
        <div className="app-nav__brand" role="img" aria-label="ASMR Helper">
          <img src="/brand/app-icon.png" width="30" height="30" alt="" aria-hidden="true" />
          {!collapsed && (
            <div className="app-nav__brand-copy">
              <strong>ASMR Helper</strong>
              <span>V2 Studio</span>
            </div>
          )}
        </div>
        <button
          type="button"
          className="app-nav__collapse"
          aria-label={collapsed ? t("展开导航栏") : t("收起导航栏")}
          title={collapsed ? t("展开导航栏") : t("收起导航栏")}
          onClick={toggleCollapsed}
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
            {collapsed ? <path d="M5 3l4 4-4 4" /> : <path d="M9 3L5 7l4 4" />}
          </svg>
        </button>
      </div>

      <div className="app-nav__scroller">
        {!collapsed && <div className="app-nav__group-title">{t("创作与精修")}</div>}
        <div className="app-nav__items" role="group" aria-label={t("创作与精修")}>
          {PRIMARY_PAGES.map(renderItem)}
        </div>
      </div>

      <div className="app-nav__footer">
        {!collapsed && <div className="app-nav__group-title">{t("算力与系统")}</div>}
        <div className="app-nav__items" role="group" aria-label={t("算力与系统")}>
          {SYSTEM_PAGES.map(renderItem)}
        </div>
      </div>

      {tooltip && collapsed && createPortal(
        <div ref={tooltipRef} id={tooltipId} role="tooltip" className="app-nav__tooltip" style={{ top: tooltip.top, left: tooltip.left }} onMouseEnter={cancelClose} onMouseLeave={scheduleClose}>
          <strong>{t(PAGE_LABELS[tooltip.pageId])}</strong>
          <span>{t(PAGE_DESCRIPTIONS[tooltip.pageId])}</span>
        </div>, document.body,
      )}
    </nav>
  )
}
