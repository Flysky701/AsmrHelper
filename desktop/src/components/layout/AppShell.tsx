import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import LeftNav from './LeftNav'
import MainContent from './MainContent'
import RightSidebar from './RightSidebar'
import AudioPlayerBar from './AudioPlayerBar'

export default function AppShell() {
  const playerVisible = useAudioPlayerStore((s) => s.visible)

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '100px 1fr 280px',
        gridTemplateRows: playerVisible ? '1fr auto' : '1fr',
        height: '100vh',
        background: 'var(--bg-base)',
      }}
    >
      <LeftNav />
      <MainContent />
      <RightSidebar />
      {playerVisible && <AudioPlayerBar />}
    </div>
  )
}
