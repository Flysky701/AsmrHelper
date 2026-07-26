import { create } from 'zustand'

interface AudioPlayerState {
  visible: boolean
  src: string | null
  title: string
  isPlaying: boolean
  currentTime: number
  duration: number
  volume: number
  error: string

  show: (src: string, title: string) => void
  hide: () => void
  togglePlay: () => void
  seek: (time: number) => void
  setVolume: (vol: number) => void
  updateTime: (current: number, duration: number) => void
  setPlaying: (playing: boolean) => void
  setError: (error: string) => void
}

export const useAudioPlayerStore = create<AudioPlayerState>((set) => ({
  visible: false,
  src: null,
  title: '',
  isPlaying: false,
  currentTime: 0,
  duration: 0,
  volume: 0.8,
  error: '',

  show: (src, title) => set({ visible: true, src, title, isPlaying: false, currentTime: 0, duration: 0, error: '' }),
  hide: () => set({ visible: false, src: null, isPlaying: false, error: '' }),
  togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
  seek: (time) => set({ currentTime: time }),
  setVolume: (vol) => set({ volume: Math.max(0, Math.min(1, vol)) }),
  updateTime: (current, duration) => set({ currentTime: current, duration }),
  setPlaying: (playing) => set({ isPlaying: playing }),
  setError: (error) => set({ error }),
}))
