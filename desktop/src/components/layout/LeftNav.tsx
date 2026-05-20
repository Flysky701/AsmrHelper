import { useNavStore, PAGE_ORDER, PAGE_LABELS } from '@/stores/navStore'
import type { PageId } from '@/stores/navStore'

const NAV_ICONS: Record<PageId, string> = {
  workbench: '⚙',   // ⚙ — will use text labels primarily
  tools: '⚒',
  'voice-lab': '♫',
  tasks: '☰',
  resources: '⬜',
  settings: '⚙',
}

export default function LeftNav() {
  const activePage = useNavStore((s) => s.activePage)
  const setPage = useNavStore((s) => s.setPage)

  return (
    <nav
      style={{
        width: '100px',
        background: 'var(--bg-base)',
        display: 'flex',
        flexDirection: 'column',
        padding: '12px 0',
        gap: '4px',
        borderRight: '1px solid rgba(0,0,0,0.05)',
      }}
    >
      {PAGE_ORDER.map((pageId) => {
        const isActive = activePage === pageId
        return (
          <button
            key={pageId}
            onClick={() => setPage(pageId)}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '4px',
              padding: '12px 8px',
              border: 'none',
              outline: 'none',
              cursor: 'pointer',
              background: isActive ? 'var(--bg-surface)' : 'transparent',
              boxShadow: isActive ? 'var(--shadow-pressed)' : 'none',
              borderRadius: '0',
              position: 'relative',
              transition: 'background 150ms, box-shadow 150ms',
            }}
          >
            {isActive && (
              <div
                style={{
                  position: 'absolute',
                  left: 0,
                  top: '8px',
                  bottom: '8px',
                  width: '3px',
                  borderRadius: '0 2px 2px 0',
                  background: 'var(--accent-text)',
                }}
              />
            )}
            <span
              style={{
                fontSize: '18px',
                lineHeight: 1,
                opacity: isActive ? 1 : 0.5,
              }}
            >
              {NAV_ICONS[pageId]}
            </span>
            <span
              style={{
                fontSize: '12px',
                fontWeight: isActive ? 600 : 400,
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                lineHeight: 1.3,
                textAlign: 'center',
              }}
            >
              {PAGE_LABELS[pageId]}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
