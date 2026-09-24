import { useEffect, useRef, useState } from 'react'

/** Playback gain only; never rewrites the provider's original artifact. */
export default function CandidateAudio({ url, equalLoudness }: { url: string; equalLoudness: boolean }) {
  const player = useRef<HTMLAudioElement>(null)
  const context = useRef<AudioContext | null>(null)
  const gain = useRef<GainNode | null>(null)
  const level = useRef(1)
  const [error, setError] = useState('')
  const [measuring, setMeasuring] = useState(false)

  function preparePlayback() {
    if (!player.current) return
    document.querySelectorAll<HTMLAudioElement>('.speech-lab audio').forEach(audio => { if (audio !== player.current) audio.pause() })
    if (context.current) { void context.current.resume(); return }
    const audioContext = new AudioContext()
    context.current = audioContext
    const media = audioContext.createMediaElementSource(player.current)
    const node = audioContext.createGain()
    gain.current = node
    node.gain.value = equalLoudness ? level.current : 1
    media.connect(node).connect(audioContext.destination)
    void audioContext.resume()
  }
  useEffect(() => () => { void context.current?.close(); context.current = null; gain.current = null }, [])

  useEffect(() => {
    const abort = new AbortController()
    level.current = 1
    setError('')
    setMeasuring(false)
    if (gain.current) gain.current.gain.value = 1
    if (!equalLoudness) return () => abort.abort()
    setMeasuring(true)
    void fetch(url, { signal: abort.signal }).then(async response => {
      if (!response.ok) throw new Error('音频不可读取')
      const audioContext = new OfflineAudioContext(2, 1, 44100)
      const decoded = await audioContext.decodeAudioData(await response.arrayBuffer())
      if (abort.signal.aborted) return
      let squares = 0
      let peak = 0
      for (let channel = 0; channel < decoded.numberOfChannels; channel++) {
        const samples = decoded.getChannelData(channel)
        for (let i = 0; i < samples.length; i++) {
          squares += samples[i]! * samples[i]!
          peak = Math.max(peak, Math.abs(samples[i]!))
        }
      }
      const rms = Math.sqrt(squares / (decoded.length * decoded.numberOfChannels))
      if (abort.signal.aborted) return
      level.current = rms > 0 ? Math.min(.12 / rms, peak > 0 ? .95 / peak : 1) : 1
      if (!abort.signal.aborted && gain.current) gain.current.gain.value = level.current
    }).catch(cause => { if (!abort.signal.aborted) setError(`音量校准不可用：${String(cause)}`) })
      .finally(() => { if (!abort.signal.aborted) setMeasuring(false) })
    return () => abort.abort()
  }, [url, equalLoudness])

  return <div>
    <audio ref={player} controls crossOrigin="anonymous" src={url} onPlay={preparePlayback} onError={() => setError('音频无法播放，请检查候选产物是否仍存在')} />
    {equalLoudness && <p className="muted">{measuring ? '正在分析播放音量…' : '按 RMS 校准试听音量，保留峰值余量；原始文件不变。'}</p>}
    {error && <p role="alert" className="error muted">{error}</p>}
  </div>
}
