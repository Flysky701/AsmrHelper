import { useEffect, type CSSProperties } from 'react'
import { useAppearanceStore } from '@/stores/appearanceStore'
import LeftNav from './LeftNav'
import MainContent from './MainContent'
import AudioPlayerBar from './AudioPlayerBar'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'

export default function AppShell() {
  const playerVisible = useAudioPlayerStore((s) => s.visible)

  const { background, overlay, language, markBackgroundUnavailable } = useAppearanceStore()
  useEffect(() => { document.documentElement.lang = language }, [language])
  useEffect(() => {
    if (!background) return
    const image = new Image()
    image.onerror = markBackgroundUnavailable
    image.src = background.data
    return () => { image.onerror = null }
  }, [background, markBackgroundUnavailable])
  return (
    <div className={`app-shell${background ? ' has-custom-background' : ''}`} style={background ? {
      '--app-background': `url("${background.data}")`, '--app-overlay': overlay,
    } as CSSProperties : undefined}>
      <LeftNav />
      <MainContent />
      {playerVisible && <AudioPlayerBar />}
    </div>
  )
}
