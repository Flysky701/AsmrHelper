import { useAudioPlayerStore } from '@/stores/audioPlayerStore'
import { useAudioPlayer } from '@/hooks/useAudioPlayer'

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function IconButton({
  label,
  onClick,
  children,
}: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      className="audio-player__icon-button"
      aria-label={label}
      title={label}
      onClick={onClick}
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
    <div className="audio-player">
      <div className="audio-player__identity">
        <IconButton label={isPlaying ? '暂停' : '播放'} onClick={togglePlay}>
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
          className="audio-player__title"
          data-error={error ? 'true' : undefined}
          title={error || title}
        >
          {error || title}
        </span>
      </div>

      <div className="audio-player__timeline">
        <span className="audio-player__time audio-player__time--current">
          {formatTime(currentTime)}
        </span>

        <input
          className="audio-player__range"
          aria-label="播放进度"
          type="range"
          min={0}
          max={duration || 100}
          step={0.1}
          value={currentTime}
          onChange={(e) => seek(Number(e.target.value))}
        />

        <span className="audio-player__time">
          {formatTime(duration)}
        </span>
      </div>

      <div className="audio-player__controls">
        <input
          className="audio-player__range audio-player__volume"
          aria-label="音量"
          title="音量"
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
        />

        <IconButton label="关闭播放器" onClick={hide}>
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M2 2l8 8M10 2l-8 8" />
          </svg>
        </IconButton>
      </div>
    </div>
  )
}
