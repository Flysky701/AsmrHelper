import LeftNav from './LeftNav'
import MainContent from './MainContent'
import AudioPlayerBar from './AudioPlayerBar'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'

export default function AppShell() {
  const playerVisible = useAudioPlayerStore((s) => s.visible)

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '220px minmax(0, 1fr)',
        gridTemplateRows: '1fr auto',
        height: '100vh',
        background: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      <LeftNav />
      <MainContent />
      {playerVisible && <AudioPlayerBar />}
    </div>
  )
}
