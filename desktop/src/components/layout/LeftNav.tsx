import { useNavStore, PAGE_LABELS } from '@/stores/navStore'
import type { PageId } from '@/stores/navStore'
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const NAV_ICONS: Record<PageId, ReactNode> = {
  'workflow-presets': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="6" width="4" height="5" rx="1" /><rect x="12" y="2" width="4" height="5" rx="1" />
      <rect x="12" y="11" width="4" height="5" rx="1" /><path d="M6 8.5h3V4.5h3M9 8.5v5h3" />
    </svg>
  ),
  workbench: (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="3" width="12" height="12" rx="2" />
      <path d="M3 7h12" />
    </svg>
  ),
  'task-center': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M4 5h10M4 9h10M4 13h6" />
    </svg>
  ),
  'subtitle-workshop': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="5" width="12" height="8" rx="2" />
      <path d="M6 9h6M6 11h4" />
    </svg>
  ),
  'voice-lab': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M9 3v12M5 7v4M13 6v6" />
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
  engines: (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="4" y="4" width="10" height="10" rx="2" />
      <circle cx="9" cy="9" r="2.5" />
    </svg>
  ),
  settings: (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="9" cy="9" r="2.5" />
      <path d="M9 3v1.5M9 13.5V15M3 9h1.5M13.5 9H15M5 5l1 1M12 12l1 1M5 13l1-1M12 6l1-1" />
    </svg>
  ),
}

const WORKFLOW_PAGES: PageId[] = ['workbench', 'task-center', 'workflow-presets']
const TOOL_PAGES: PageId[] = ['audio-tools', 'subtitle-workshop', 'voice-lab', 'engines']
const PAGE_DESCRIPTIONS: Record<PageId, string> = {
  workbench: '导入素材，配置并运行流水线',
  'task-center': '查看任务进度、批次与运行结果',
  'workflow-presets': '编辑节点流程，管理流水线预设',
  'audio-tools': '处理、转换与整理音频',
  'subtitle-workshop': '编辑、翻译与导出字幕',
  'voice-lab': '管理音色与配音设置',
  engines: '管理本地引擎、模型与外部服务',
  settings: '调整应用配置与运行偏好',
}

export default function LeftNav() {
  const activePage = useNavStore((s) => s.activePage)
  const setPage = useNavStore((s) => s.setPage)
  const tooltipId = useId()
  const [tooltip, setTooltip] = useState<{ pageId: PageId; top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cancelClose = () => {
    if (closeTimer.current !== null) clearTimeout(closeTimer.current)
    closeTimer.current = null
  }
  const showTooltip = (pageId: PageId, trigger: HTMLButtonElement) => {
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
    const isActive = activePage === pageId
    return (
      <button
        key={pageId}
        type="button"
        className="app-nav__item"
        data-page={pageId}
        aria-label={PAGE_LABELS[pageId]}
        aria-current={isActive ? 'page' : undefined}
        aria-describedby={tooltip?.pageId === pageId ? tooltipId : undefined}
        onMouseEnter={event => showTooltip(pageId, event.currentTarget)}
        onMouseLeave={scheduleClose}
        onFocus={event => showTooltip(pageId, event.currentTarget)}
        onBlur={scheduleClose}
        onClick={() => { cancelClose(); setTooltip(null); setPage(pageId) }}
      >
        <span aria-hidden="true" className="app-nav__icon">{NAV_ICONS[pageId]}</span>
      </button>
    )
  }

  return (
    <nav className="app-nav" aria-label="主导航">
      <div className="app-nav__brand" role="img" aria-label="ASMR Helper">
        <svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4" /></svg>
      </div>

      <div className="app-nav__scroller">
        <div className="app-nav__items" role="group" aria-label="流水线与任务">
          {WORKFLOW_PAGES.map(renderItem)}
        </div>
        <div className="app-nav__items app-nav__items--tools" role="group" aria-label="工具与资源">
          {TOOL_PAGES.map(renderItem)}
        </div>
      </div>
      <div className="app-nav__footer">{renderItem('settings')}</div>
      {tooltip && createPortal(
        <div ref={tooltipRef} id={tooltipId} role="tooltip" className="app-nav__tooltip" style={{ top: tooltip.top, left: tooltip.left }} onMouseEnter={cancelClose} onMouseLeave={scheduleClose}>
          <strong>{PAGE_LABELS[tooltip.pageId]}</strong>
          <span>{PAGE_DESCRIPTIONS[tooltip.pageId]}</span>
        </div>, document.body,
      )}
    </nav>
  )
}
