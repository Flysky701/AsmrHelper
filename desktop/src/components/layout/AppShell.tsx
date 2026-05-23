import LeftNav from './LeftNav'
import MainContent from './MainContent'
import RightSidebar from './RightSidebar'
import AudioPlayerBar from './AudioPlayerBar'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'

export default function AppShell() {
  const playerVisible = useAudioPlayerStore((s) => s.visible)

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr 280px',
        gridTemplateRows: '1fr auto',
        height: '100vh',
        background: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      <LeftNav />
      <MainContent />
      <RightSidebar />
      {playerVisible && <AudioPlayerBar />}
    </div>
  )
}
