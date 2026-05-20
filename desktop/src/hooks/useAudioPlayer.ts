import { useEffect, useRef, useCallback } from 'react'
import { useAudioPlayerStore } from '@/stores/audioPlayerStore'

export function useAudioPlayer() {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const src = useAudioPlayerStore((s) => s.src)
  const isPlaying = useAudioPlayerStore((s) => s.isPlaying)
  const volume = useAudioPlayerStore((s) => s.volume)
  const currentTime = useAudioPlayerStore((s) => s.currentTime)
  const updateTime = useAudioPlayerStore((s) => s.updateTime)
  const setPlaying = useAudioPlayerStore((s) => s.setPlaying)

  // Create/update audio element
  useEffect(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio()
      audioRef.current.addEventListener('timeupdate', () => {
        const a = audioRef.current
        if (a) updateTime(a.currentTime, a.duration || 0)
      })
      audioRef.current.addEventListener('ended', () => setPlaying(false))
      audioRef.current.addEventListener('loadedmetadata', () => {
        const a = audioRef.current
        if (a) updateTime(a.currentTime, a.duration || 0)
      })
    }
    return () => {
      audioRef.current?.pause()
    }
  }, [updateTime, setPlaying])

  // Sync src
  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !src) return
    audio.src = src
    audio.load()
  }, [src])

  // Sync play state
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    if (isPlaying) {
      audio.play().catch(() => setPlaying(false))
    } else {
      audio.pause()
    }
  }, [isPlaying, setPlaying])

  // Sync volume
  useEffect(() => {
    if (audioRef.current) audioRef.current.volume = volume
  }, [volume])

  // Seek from store changes (user dragging slider)
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    // Only seek if the difference is significant (user initiated)
    if (Math.abs(audio.currentTime - currentTime) > 1.5) {
      audio.currentTime = currentTime
    }
  }, [currentTime])

  const seek = useCallback((time: number) => {
    if (audioRef.current) {
      audioRef.current.currentTime = time
      updateTime(time, audioRef.current.duration || 0)
    }
  }, [updateTime])

  return { seek, audioRef }
}
