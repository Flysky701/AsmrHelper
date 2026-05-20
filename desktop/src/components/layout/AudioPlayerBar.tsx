import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useAudioPlayer } from '@/hooks/useAudioPlayer'
import { NeuButton, NeuSlider } from '@/components/ui'

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function AudioPlayerBar() {
  const visible = useAudioPlayerStore((s) => s.visible)
  const title = useAudioPlayerStore((s) => s.title)
  const isPlaying = useAudioPlayerStore((s) => s.isPlaying)
  const currentTime = useAudioPlayerStore((s) => s.currentTime)
  const duration = useAudioPlayerStore((s) => s.duration)
  const volume = useAudioPlayerStore((s) => s.volume)
  const togglePlay = useAudioPlayerStore((s) => s.togglePlay)
  const hide = useAudioPlayerStore((s) => s.hide)
  const setVolume = useAudioPlayerStore((s) => s.setVolume)

  const { seek } = useAudioPlayer()

  if (!visible) return null

  return (
    <div
      style={{
        gridColumn: '2 / 4',
        height: '64px',
        background: 'var(--bg-surface)',
        borderTop: '1px solid rgba(0,0,0,0.06)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 20px',
        gap: '16px',
      }}
    >
      <NeuButton size="sm" variant="ghost" onClick={togglePlay}>
        {isPlaying ? '⏸' : '▶'}
      </NeuButton>

      <span
        style={{
          fontSize: '0.8125rem',
          fontWeight: 500,
          color: 'var(--text-primary)',
          minWidth: '120px',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={title}
      >
        {title}
      </span>

      <span
        style={{
          fontSize: '0.75rem',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-secondary)',
          minWidth: '40px',
        }}
      >
        {formatTime(currentTime)}
      </span>

      <div style={{ flex: 1 }}>
        <NeuSlider
          value={currentTime}
          min={0}
          max={duration || 100}
          step={0.1}
          onChange={seek}
        />
      </div>

      <span
        style={{
          fontSize: '0.75rem',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-secondary)',
          minWidth: '40px',
        }}
      >
        {formatTime(duration)}
      </span>

      <div style={{ width: '100px' }}>
        <NeuSlider
          value={volume}
          min={0}
          max={1}
          step={0.01}
          onChange={setVolume}
        />
      </div>

      <NeuButton size="sm" variant="ghost" onClick={hide}>
        ✕
      </NeuButton>
    </div>
  )
}
