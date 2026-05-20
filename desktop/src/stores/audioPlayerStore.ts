import { create } from 'zustand'

interface AudioPlayerState {
  visible: boolean
  src: string | null
  title: string
  isPlaying: boolean
  currentTime: number
  duration: number
  volume: number

  show: (src: string, title: string) => void
  hide: () => void
  togglePlay: () => void
  seek: (time: number) => void
  setVolume: (vol: number) => void
  updateTime: (current: number, duration: number) => void
  setPlaying: (playing: boolean) => void
}

export const useAudioPlayerStore = create<AudioPlayerState>((set) => ({
  visible: false,
  src: null,
  title: '',
  isPlaying: false,
  currentTime: 0,
  duration: 0,
  volume: 0.8,

  show: (src, title) => set({ visible: true, src, title, isPlaying: false, currentTime: 0, duration: 0 }),
  hide: () => set({ visible: false, src: null, isPlaying: false }),
  togglePlay: () => set((s) => ({ isPlaying: !s.isPlaying })),
  seek: (time) => set({ currentTime: time }),
  setVolume: (vol) => set({ volume: Math.max(0, Math.min(1, vol)) }),
  updateTime: (current, duration) => set({ currentTime: current, duration }),
  setPlaying: (playing) => set({ isPlaying: playing }),
}))
