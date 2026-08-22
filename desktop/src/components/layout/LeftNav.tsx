import { useNavStore, PAGE_LABELS } from '@/stores/navStore'
import type { PageId } from '@/stores/navStore'
import type { ReactNode } from 'react'

const NAV_ICONS: Record<PageId, ReactNode> = {
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
  'batch-processing': (
    <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <path d="M7 14h7V7M5.5 6h3M5.5 8h3" />
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

const TOP_PAGES: PageId[] = ['workbench', 'batch-processing', 'task-center', 'audio-tools', 'subtitle-workshop', 'voice-lab']
const BOTTOM_PAGES: PageId[] = ['engines', 'settings']

export default function LeftNav() {
  const activePage = useNavStore((s) => s.activePage)
  const setPage = useNavStore((s) => s.setPage)

  const renderItem = (pageId: PageId) => {
    const isActive = activePage === pageId
    return (
      <button
        key={pageId}
        type="button"
        className="app-nav__item"
        data-page={pageId}
        aria-current={isActive ? 'page' : undefined}
        onClick={() => setPage(pageId)}
      >
        {NAV_ICONS[pageId]}
        <span className="app-nav__item-label">{PAGE_LABELS[pageId]}</span>
      </button>
    )
  }

  return (
    <nav className="app-nav" aria-label="主导航">
      <div className="app-nav__brand">
        <div className="app-nav__brand-eyebrow">
          AsmrHelper
        </div>
        <div className="app-nav__brand-title">
          Production Desk
        </div>
        <div className="app-nav__brand-description">
          把输入、任务、产物和预览串在同一条主链路里。
        </div>
      </div>

      <div className="app-nav__scroller">
        <div className="app-nav__group">
          <div className="app-nav__group-label">Workflow</div>
          <div className="app-nav__items">
            {TOP_PAGES.map(renderItem)}
          </div>
        </div>

        <div className="app-nav__group app-nav__group--control">
          <div className="app-nav__group-label">Control</div>
          <div className="app-nav__items">
            {BOTTOM_PAGES.map(renderItem)}
          </div>
        </div>
      </div>
    </nav>
  )
}
