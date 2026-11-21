import { useEffect, type CSSProperties } from 'react'
import { useAppearanceStore } from '@/stores/appearanceStore'
import LeftNav from './LeftNav'
import MainContent from './MainContent'
import AudioPlayerBar from './AudioPlayerBar'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useNavStore } from '@/stores/navStore'
import { usePageHelpStore } from '@/stores/pageHelpStore'
import { useWorkflowStore } from '@/stores/workflowStore'

function hexToRgb(hex: string): [number, number, number] {
  const clean = hex.replace('#', '')
  return [
    parseInt(clean.slice(0, 2), 16),
    parseInt(clean.slice(2, 4), 16),
    parseInt(clean.slice(4, 6), 16),
  ]
}

export default function AppShell() {
  const helpOpen = usePageHelpStore(state => state.openTopic !== null)
  const playerVisible = useAudioPlayerStore((s) => s.visible)
  const navCollapsed = useNavStore((s) => s.navCollapsed)
  const activePage = useNavStore((s) => s.activePage)
  const hasWorkflowDraft = useWorkflowStore((s) => s.editor !== null)
  const editingWorkflow = activePage === 'workflow-presets' && hasWorkflowDraft

  const { background, overlay, language, theme, customSurface, accentColor, markBackgroundUnavailable } = useAppearanceStore()
  useEffect(() => { document.documentElement.lang = language }, [language])

  useEffect(() => {
    const root = document.documentElement
    const media = window.matchMedia?.('(prefers-color-scheme: dark)')
    const applyTheme = () => {
      const resolvedBase = theme === 'dark'
        ? 'dark'
        : theme === 'light'
          ? 'light'
          : theme === 'custom'
            ? customSurface
            : media?.matches ? 'dark' : 'light'
      root.dataset.theme = resolvedBase
      if (theme === 'custom' && accentColor) {
        const [r, g, b] = hexToRgb(accentColor)
        root.style.setProperty('--accent', accentColor)
        root.style.setProperty('--accent-hover', `rgb(${Math.max(0, r - 18)}, ${Math.max(0, g - 18)}, ${Math.max(0, b - 18)})`)
        root.style.setProperty('--accent-soft', `rgba(${r}, ${g}, ${b}, ${resolvedBase === 'dark' ? 0.18 : 0.12})`)
        root.style.setProperty('--accent-ghost-border', `rgba(${r}, ${g}, ${b}, ${resolvedBase === 'dark' ? 0.38 : 0.32})`)
      } else {
        root.style.removeProperty('--accent')
        root.style.removeProperty('--accent-hover')
        root.style.removeProperty('--accent-soft')
        root.style.removeProperty('--accent-ghost-border')
      }
    }
    applyTheme()
    if (theme === 'system' && media) {
      media.addEventListener('change', applyTheme)
      return () => media.removeEventListener('change', applyTheme)
    }
  }, [theme, customSurface, accentColor])

  useEffect(() => {
    if (!background) return
    const image = new Image()
    image.onerror = markBackgroundUnavailable
    image.src = background.data
    return () => { image.onerror = null }
  }, [background, markBackgroundUnavailable])

  return (
    <div className={`app-shell${navCollapsed ? ' is-nav-collapsed' : ''}${editingWorkflow ? ' is-editing-workflow' : ''}${background ? ' has-custom-background' : ''}${helpOpen ? ' has-page-help' : ''}`} style={background ? {
      '--app-background': `url("${background.data}")`, '--app-overlay': overlay,
    } as CSSProperties : undefined}>
      {!editingWorkflow && <LeftNav />}
      <MainContent />
      <div id="page-help-host" hidden={!helpOpen} />
      {playerVisible && <AudioPlayerBar />}
    </div>
  )
}
