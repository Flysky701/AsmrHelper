import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useAudioPlayer } from '@/hooks/useAudioPlayer'

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function IconButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        width: 32,
        height: 32,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: 6,
        border: 'none',
        background: 'transparent',
        color: 'var(--fg)',
        cursor: 'pointer',
        fontSize: 14,
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--bg)' }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent' }}
    >
      {children}
    </button>
  )
}

export default function AudioPlayerBar() {
  const title = useAudioPlayerStore((s) => s.title)
  const isPlaying = useAudioPlayerStore((s) => s.isPlaying)
  const currentTime = useAudioPlayerStore((s) => s.currentTime)
  const duration = useAudioPlayerStore((s) => s.duration)
  const volume = useAudioPlayerStore((s) => s.volume)
  const error = useAudioPlayerStore((s) => s.error)
  const togglePlay = useAudioPlayerStore((s) => s.togglePlay)
  const hide = useAudioPlayerStore((s) => s.hide)
  const setVolume = useAudioPlayerStore((s) => s.setVolume)

  const { seek } = useAudioPlayer()

  return (
    <div
      style={{
        gridColumn: '1 / -1',
        height: 56,
        background: 'var(--surface)',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        gap: 12,
      }}
    >
      <IconButton onClick={togglePlay}>
        {isPlaying ? (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
            <rect x="2" y="1" width="3.5" height="12" rx="1" />
            <rect x="8.5" y="1" width="3.5" height="12" rx="1" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
            <path d="M3 1.5v11l9-5.5z" />
          </svg>
        )}
      </IconButton>

      <span
        style={{
          fontSize: 13,
          fontWeight: 500,
          color: 'var(--fg)',
          minWidth: 100,
          maxWidth: 200,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
        title={error || title}
      >
        {error || title}
      </span>

      <span
        style={{
          fontSize: 12,
          fontFamily: 'var(--font-mono)',
          color: 'var(--muted)',
          minWidth: 36,
          textAlign: 'right',
        }}
      >
        {formatTime(currentTime)}
      </span>

      <input
        type="range"
        min={0}
        max={duration || 100}
        step={0.1}
        value={currentTime}
        onChange={(e) => seek(Number(e.target.value))}
        style={{ flex: 1, height: 4, accentColor: 'var(--accent)' }}
      />

      <span
        style={{
          fontSize: 12,
          fontFamily: 'var(--font-mono)',
          color: 'var(--muted)',
          minWidth: 36,
        }}
      >
        {formatTime(duration)}
      </span>

      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        value={volume}
        onChange={(e) => setVolume(Number(e.target.value))}
        style={{ width: 80, height: 4, accentColor: 'var(--accent)' }}
      />

      <IconButton onClick={hide}>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2 2l8 8M10 2l-8 8" />
        </svg>
      </IconButton>
    </div>
  )
}
