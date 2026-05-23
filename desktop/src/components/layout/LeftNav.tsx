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

const TOP_PAGES: PageId[] = ['workbench', 'task-center', 'subtitle-workshop', 'voice-lab']
const BOTTOM_PAGES: PageId[] = ['engines', 'settings']

export default function LeftNav() {
  const activePage = useNavStore((s) => s.activePage)
  const setPage = useNavStore((s) => s.setPage)

  const renderItem = (pageId: PageId) => {
    const isActive = activePage === pageId
    return (
      <button
        key={pageId}
        data-page={pageId}
        onClick={() => setPage(pageId)}
        style={{
          width: '100%',
          height: 36,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '0 14px',
          borderRadius: 6,
          border: 'none',
          cursor: 'pointer',
          fontSize: 13,
          fontFamily: 'inherit',
          background: isActive ? 'var(--accent-subtle)' : 'transparent',
          color: isActive ? 'var(--accent)' : 'var(--muted)',
          transition: 'background 0.15s, color 0.15s',
          textAlign: 'left',
        }}
        onMouseEnter={(e) => {
          if (!isActive) {
            e.currentTarget.style.background = 'oklch(97% 0.005 250)'
            e.currentTarget.style.color = 'var(--fg)'
          }
        }}
        onMouseLeave={(e) => {
          if (!isActive) {
            e.currentTarget.style.background = 'transparent'
            e.currentTarget.style.color = 'var(--muted)'
          }
        }}
      >
        {NAV_ICONS[pageId]}
        <span>{PAGE_LABELS[pageId]}</span>
      </button>
    )
  }

  return (
    <nav
      style={{
        width: 180,
        background: 'var(--surface)',
        borderRight: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        padding: '12px 8px',
        gap: 2,
      }}
    >
      {TOP_PAGES.map(renderItem)}
      <div style={{ flex: 1, minHeight: 12 }} />
      {BOTTOM_PAGES.map(renderItem)}
    </nav>
  )
}
