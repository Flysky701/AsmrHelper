import LeftNav from './LeftNav'
import MainContent from './MainContent'
import AudioPlayerBar from './AudioPlayerBar'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'

export default function AppShell() {
  const playerVisible = useAudioPlayerStore((s) => s.visible)

  return (
    <div className="app-shell">
      <LeftNav />
      <MainContent />
      {playerVisible && <AudioPlayerBar />}
    </div>
  )
}
