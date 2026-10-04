import { confirmAction } from '@/utils/confirmAction'
import { useEffect, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import { speechApi } from '@/api/speech'
import { tasksApi } from '@/api/tasks'
import type { ReferenceAsset, ReferenceInspection, ReferenceDraft } from '@/api/speech'
import { FILE_FILTERS } from '@/hooks/useFileSelector'
import { useReferenceField, useReferenceSessionStore, startReferenceAnalysis } from '@/stores/referenceSessionStore'
import './ReferenceLibrary.css'
import ClipTranscription from './ClipTranscription'
import { playbackBoundary } from './referencePlayback'
import { confidenceLabel, hasTimestamp, selectionFromSegment } from './referenceAnalysis'

type Props = { assets: ReferenceAsset[]; refresh: () => Promise<void>; onUse: (asset: ReferenceAsset) => void; onBusy: (value: boolean) => void; active: boolean }
type Draft = Omit<ReferenceDraft, 'path'>
const initialDraft = (): Draft => ({ name: '', notes: '', start: 0, end: 0, transcript: '', language: 'auto', confirmed: false, gain_db: 0, fade_in: 0, fade_out: 0 })
const time = (value: number) => `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toFixed(1).padStart(4, '0')}`
const languages: Record<string, string> = { auto: '暂不确定', zh: '中文', ja: '日语', en: '英语', ko: '韩语' }
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

export default function ReferenceLibrary({ assets, refresh, onUse, onBusy, active }: Props) {
  const [allAssets, setAllAssets] = useState(assets)
  const [showArchived, setShowArchived] = useReferenceField('showArchived')
  const [query, setQuery] = useReferenceField('query')
  const [stored, setStored] = useReferenceField('stored')
  const [source, setSource] = useReferenceField('source')
  const [draft, setDraft] = useReferenceField('draft')
  const [view, setView] = useReferenceField('view')
  const [dirty, setDirty] = useReferenceField('dirty')
  const [busy, setBusy] = useReferenceField('busy')
  const [error, setError] = useReferenceField('error')
  const [notice, setNotice] = useReferenceField('notice')
  const [listError, setListError] = useState('')
  const [candidates, setCandidates] = useReferenceField('candidates')
  const [analyzed, setAnalyzed] = useReferenceField('analyzed')
  const [analysisError, setAnalysisError] = useReferenceField('analysisError')
  const [analysisTask, setAnalysisTask] = useReferenceField('analysisTask')
  const [recognizeText, setRecognizeText] = useReferenceField('recognizeText')
  const [analysisWarnings, setAnalysisWarnings] = useReferenceField('analysisWarnings')
  const [analysisSource, setAnalysisSource] = useReferenceField('analysisSource')
  const [clock, setClock] = useState(Date.now())
  const [trackingFailed, setTrackingFailed] = useReferenceField('trackingFailed')
  const [, setTrackingRetry] = useReferenceField('trackingRetry')
  const [loadedSubtitle, setLoadedSubtitle] = useReferenceField('loadedSubtitle')
  const [preview, setPreview] = useReferenceField('preview')
  const [segments, setSegments] = useReferenceField('segments')
  const [loop, setLoop] = useReferenceField('loop')
  const [playing, setPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [playbackMode, setPlaybackMode] = useState<'selection' | 'whole' | 'segment'>('selection')
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [assistOpen, setAssistOpen] = useReferenceField('assistOpen')
  const [subtitleRole, setSubtitleRole] = useReferenceField('subtitleRole')
  const audio = useRef<HTMLAudioElement>(null)
  const selection = useRef<{ start: number; end: number } | null>(null)
  const wholePlayback = useRef(false)
  const playbackFrame = useRef(0)
  const playbackBounds = useRef({ start: 0, end: 0, loop: false })
  playbackBounds.current = { start: draft.start, end: draft.end, loop }
  const dragging = useRef<'start' | 'end' | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const subtitleInput = useRef<HTMLInputElement>(null)
  useEffect(() => {
    let mounted = true
    void speechApi.references(showArchived).then(result => { if (mounted) { setAllAssets(result.assets); setListError('') } })
      .catch(cause => { if (mounted) setListError(message(cause)) })
    return () => { mounted = false }
  }, [assets, showArchived])
  useEffect(() => { if (!active) audio.current?.pause() }, [active])
  useEffect(() => {
    const player = audio.current
    return () => { player?.pause(); cancelAnimationFrame(playbackFrame.current) }
  }, [source?.id])
  useEffect(() => { onBusy(!!busy); return () => onBusy(false) }, [busy, onBusy])

  async function run(label: string, action: () => Promise<void>) {
    if (useReferenceSessionStore.getState().busy) return
    setBusy(label); onBusy(true); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(message(cause)) }
    finally { setBusy(''); onBusy(false) }
  }
  async function mayReplace() { return !dirty || await confirmAction('当前录音还没有保存。放弃修改并打开另一段录音？') }
  function change(patch: Partial<Draft>) {
    audio.current?.pause(); selection.current = null; wholePlayback.current = false
    setPlaybackMode('selection')
    if (patch.start !== undefined || patch.end !== undefined) {
      const start = patch.start ?? draft.start
      if (Number.isFinite(start) && start >= 0) {
        if (audio.current) audio.current.currentTime = start
        setPosition(start)
      }
    }
    setDraft(value => ({ ...value, ...patch, confirmed: patch.confirmed ?? (patch.start !== undefined || patch.end !== undefined || patch.transcript !== undefined || patch.language !== undefined ? false : value.confirmed) }))
    setDirty(true); setPreview(null)
  }
  function load(value: ReferenceInspection, name: string) {
    audio.current?.pause(); selection.current = null; wholePlayback.current = false
    setPosition(0); setPlaying(false); setPlaybackMode('selection'); setAssistOpen(false); setSubtitleRole('reference'); setLibraryOpen(false)
    setStored(null); setSource(value); setPreview(null); setSegments([]); setCandidates([]); setAnalyzed(false); setAnalysisError(''); setAnalysisTask(null); setAnalysisWarnings([]); setAnalysisSource(''); setLoadedSubtitle(null); setTrackingFailed(false)
    setDraft({ ...initialDraft(), name: name.replace(/\.[^.]+$/, ''), end: value.duration }); setView('editor'); setDirty(true)
  }
  async function upload(file: File) {
    if (busy || !(await mayReplace())) return
    void run('正在读取录音', async () => load(await speechApi.uploadReference(file), file.name))
  }
  async function chooseFile() {
    if (busy) return
    if ('__TAURI_INTERNALS__' in window) {
      if (!(await mayReplace())) return
      await run('正在读取录音', async () => {
        const { open } = await import('@tauri-apps/plugin-dialog')
        const path = await open({ multiple: false, filters: [FILE_FILTERS.audio] })
        if (typeof path === 'string') load(await speechApi.inspect(path), path.split(/[\\/]/).pop() || '参考录音')
      })
    } else fileInput.current?.click()
  }
  const valid = !!source && Number.isFinite(draft.start) && Number.isFinite(draft.end) && draft.start >= 0 && draft.end > draft.start && draft.end <= source.duration
  const processingValid = draft.gain_db >= -24 && draft.gain_db <= 12 && draft.fade_in >= 0 && draft.fade_out >= 0 && draft.fade_in + draft.fade_out <= draft.end - draft.start
  const payload = (): ReferenceDraft => ({ ...draft, path: source!.path })
  const found = allAssets.filter(item => `${item.name || ''} ${item.notes || ''} ${item.transcript || ''}`.toLowerCase().includes(query.toLowerCase()))
  function play(start: number, end: number, whole = false, segment = false) {
    if (!audio.current) return
    wholePlayback.current = whole
    setPlaybackMode(whole ? 'whole' : segment ? 'segment' : 'selection')
    selection.current = { start, end }; audio.current.currentTime = start
    void audio.current.play().catch(cause => setError(message(cause)))
  }
  function enforcePlayback() {
    const player = audio.current
    if (!player || wholePlayback.current) return
    const range = selection.current || playbackBounds.current
    const action = playbackBoundary(player.currentTime, range, playbackBounds.current.loop, !player.paused)
    if (action.pause) player.pause()
    if (action.seek !== undefined && player.currentTime !== action.seek) player.currentTime = action.seek
  }
  function onPlayerPlay() {
    setPlaying(true)
    const player = audio.current
    if (!player) return
    const range = selection.current || playbackBounds.current
    if (!wholePlayback.current && (player.currentTime < range.start || player.currentTime >= range.end)) player.currentTime = range.start
    cancelAnimationFrame(playbackFrame.current)
    const tick = () => { enforcePlayback(); if (!player.paused) playbackFrame.current = requestAnimationFrame(tick) }
    tick()
  }
  function onPlayerEnded() {
    const range = selection.current || playbackBounds.current
    if (!wholePlayback.current && playbackBounds.current.loop && range.end > range.start) play(range.start, range.end)
    else { wholePlayback.current = false; selection.current = null; setPlaybackMode('selection'); setPlaying(false) }
  }
  function moveSelection(event: PointerEvent<SVGSVGElement>) {
    if (!source || !dragging.current || busy) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const position = Math.max(0, Math.min(source.duration, (event.clientX - bounds.left) / bounds.width * source.duration))
    const gap = Math.min(.01, source.duration)
    change(dragging.current === 'start' ? { start: Math.min(draft.end - gap, position) } : { end: Math.max(draft.start + gap, position) })
  }
  const analyze = startReferenceAnalysis
  const analyzing = !!analysisTask && !['completed', 'failed', 'cancelled', 'skipped'].includes(analysisTask.state)
  useEffect(() => {
    if (!analyzing) return
    const timer = setInterval(() => setClock(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [analyzing])
  const elapsed = analysisTask ? Math.max(0, Math.floor(((analysisTask.finished_at ? Date.parse(analysisTask.finished_at) : clock) - Date.parse(analysisTask.started_at || analysisTask.created_at)) / 1000)) : 0
  const analysisLabel = analysisTask?.state === 'completed' ? '分析完成' : analysisTask?.state === 'failed' ? '分析失败' : analysisTask?.state === 'cancelled' ? '已取消' : analysisTask?.state === 'pending' ? '等待分析' : analysisTask?.message || '正在分析'
  async function save() {
    await run('正在保存录音', async () => {
      const saved = await speechApi.reference(payload())
      setStored(saved); setDirty(false); setView('saved'); audio.current?.pause()
      setAllAssets(previous => [saved, ...previous.filter(item => item.id !== saved.id)])
      try { await refresh() } catch { setNotice('录音已保存，列表刷新失败；稍后可重试刷新。') }
    })
  }
  async function openStored(item: ReferenceAsset) {
    if (!(await mayReplace())) return
    audio.current?.pause(); setAnalysisTask(null); setStored(item); setSource(null); setDirty(false); setView('saved'); setNotice(''); setError('')
  }

  return <div className="reference-library">
    <input ref={fileInput} hidden type="file" accept=".mp3,.wav,.flac,.ogg,.m4a,.aac,.wma" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) upload(file) }} />
    <input ref={subtitleInput} hidden type="file" accept=".srt,.vtt" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void run('读取字幕', async () => {
      if (file.size > 5 * 1024 * 1024) throw new Error('字幕文件不能超过 5 MiB')
      const subtitle_text = await file.text()
      const subtitle_format = file.name.toLowerCase().endsWith('.vtt') ? 'vtt' : 'srt'
      const result = await speechApi.subtitles(subtitle_text, subtitle_format)
      setSegments(result.segments); setLoadedSubtitle({ name: file.name, subtitle_text, subtitle_format })
      setSubtitleRole('reference'); setAssistOpen(true)
      setNotice('已加载字幕供辅助查看。确认是与录音同语的原文后可填入；译文仅供参考。')
    }) }} />
    {error && <div className="notice error" role="alert">{error}</div>}{notice && <div className="notice" role="status">{notice}</div>}
    {busy && <div className="reference-busy" role="status"><span className="reference-spinner" />{busy}…</div>}
    <fieldset disabled={!!busy} className="lab-fieldset"><div className="reference-layout">
      <button className="reference-library-toggle" aria-expanded={libraryOpen} aria-controls="reference-recordings" onClick={() => setLibraryOpen(value => !value)}>我的录音 · {allAssets.length} {libraryOpen ? '收起' : '展开'}</button>
      <aside id="reference-recordings" className={'panel reference-sidebar' + (libraryOpen ? ' is-open' : '')}>
        <div className="row spread"><h2>我的录音 <span className="reference-count">{found.length}</span></h2><button onClick={() => void chooseFile()}>＋ 导入</button></div>
        <input aria-label="搜索录音" placeholder="搜索名称、备注或原文" value={query} onChange={event => setQuery(event.target.value)} />
        <label className="reference-archive"><input type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} /> 显示已归档</label>
        {listError && <p className="error" role="alert">录音列表加载失败，可点击页面右上角刷新。</p>}
        {!found.length && !listError && <div className="empty">{query ? <>没有匹配的录音。<button onClick={() => setQuery('')}>清空搜索</button></> : source ? '还没有保存的录音。当前片段保存后会出现在这里。' : '还没有参考录音。导入一份音频，保存你想留下的声音。'}</div>}
        <div className="reference-assets">{found.map(item => <button key={item.id} className={'reference-asset ' + (stored?.id === item.id ? 'is-selected' : '')} aria-current={stored?.id === item.id ? 'true' : undefined} onClick={() => { openStored(item); setLibraryOpen(false) }}>
          <strong>{item.name || '未命名录音'}</strong><span>{languages[item.language] || item.language} · {(item.duration ?? 0).toFixed(1)} 秒{item.archived ? ' · 已归档' : ''}</span>
          <span className={'reference-status ' + (item.confirmed ? 'is-confirmed' : '')}>{!item.transcript ? '原文待补充' : item.confirmed ? '原文已核对' : '原文待核对'}</span>
        </button>)}</div>
      </aside>
      <section className="reference-main">
        {!source && view !== 'saved' && <div className="panel reference-start" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); const file = event.dataTransfer.files[0]; if (file) upload(file) }}>
          <div className="reference-start-icon" aria-hidden="true">♫</div><h2>导入参考录音</h2><p>整段保存，或从长音频里选出一小段。<br />可以手动框选，也可识别台词后逐段试听选择。</p>
          <button className="primary" onClick={() => void chooseFile()}>选择音频文件</button><p className="muted">也可以拖入文件 · WAV / MP3 / FLAC 等<br />浏览器上传上限 100 MiB</p>
          <div className="reference-start-tip">录音可独立保存，需要时再用于创建音色。</div>
        </div>}
        {source && view !== 'saved' && <div className="reference-workspace">
          <section className="panel reference-editor">
            <div className="row spread"><h2>编辑录音 <span className="reference-optional">· {dirty ? '未保存' : '已保存'}</span></h2><button onClick={() => void chooseFile()}>更换文件</button></div>
            <details className="reference-source"><summary><span>{source.path.split(/[\\/]/).pop() || draft.name || '未命名录音'}</span></summary><p>{source.path.split(/[\\/]/).pop() || draft.name}</p></details>
            <p className="reference-duration">原音 {time(source.duration)} · 已选 {Math.max(0, draft.end - draft.start).toFixed(2)} 秒</p>
            <svg className="waveform reference-waveform" viewBox="0 0 800 100" preserveAspectRatio="none" role="img" aria-label="录音波形，可拖动两端调整选区" onPointerDown={event => {
              if (busy) return
              const bounds = event.currentTarget.getBoundingClientRect(); const point = (event.clientX - bounds.left) / bounds.width * source.duration
              dragging.current = Math.abs(point - draft.start) < Math.abs(point - draft.end) ? 'start' : 'end'
              event.currentTarget.setPointerCapture(event.pointerId); moveSelection(event)
            }} onPointerMove={moveSelection} onPointerUp={event => { dragging.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId) }} onPointerCancel={() => { dragging.current = null }}>
              <rect x={draft.start / source.duration * 800} width={(draft.end - draft.start) / source.duration * 800} height="100" fill="var(--accent-soft)" />
              {source.peaks.map((peak, index) => <line key={index} x1={index / source.peaks.length * 800} x2={index / source.peaks.length * 800} y1={50 - Math.abs(peak) * 43} y2={50 + Math.abs(peak) * 43} stroke="var(--accent)" opacity=".65" />)}
              {[draft.start, draft.end].map((point, index) => <g key={index}><line x1={point / source.duration * 800} x2={point / source.duration * 800} y1="0" y2="100" stroke="var(--accent)" strokeWidth="3" /><rect x={Math.max(0, Math.min(790, point / source.duration * 800 - 5))} y="35" width="10" height="30" rx="4" fill="var(--accent)" /></g>)}
            </svg>
            <div className="reference-timeline"><span>00:00</span><span>{time(source.duration)}</span></div>
            <audio hidden ref={audio} src={speechApi.referenceAudio(source.id, true)} onPlay={onPlayerPlay} onPause={() => { cancelAnimationFrame(playbackFrame.current); setPlaying(false) }} onTimeUpdate={() => { enforcePlayback(); setPosition(audio.current?.currentTime || 0) }} onSeeked={enforcePlayback} onEnded={onPlayerEnded} onError={() => setError('音频加载失败，请更换文件或重新导入。')} />
            <div className="row reference-playback"><button className="reference-play" disabled={!valid} onClick={() => {
              const player = audio.current
              if (!player) return
              if (!player.paused) { player.pause(); return }
              const range = selection.current || { start: draft.start, end: draft.end }
              if (player.currentTime >= range.start && player.currentTime < range.end) {
                selection.current = range
                void player.play().catch(cause => setError(message(cause)))
              }
              else play(draft.start, draft.end)
            }}>{playing ? 'Ⅱ 暂停' : '▶ ' + (playbackMode === 'whole' ? '继续整段' : playbackMode === 'segment' ? '继续片段' : '播放选段')}</button><button onClick={() => play(0, source.duration, true)}>试听整段</button><label><input type="checkbox" checked={loop} disabled={playbackMode === 'whole' && playing} onChange={event => setLoop(event.target.checked)} /> 循环选段</label><span className="reference-playhead">{time(position)} / {time(source.duration)}</span><span className="muted" role="status">{playbackMode === 'whole' ? '整段试听' : playbackMode === 'segment' ? '片段试听' : '选段播放'}</span></div>
            <label className="reference-seek"><span className="muted">播放位置</span><input aria-label="播放位置" type="range" min={selection.current?.start ?? draft.start} max={selection.current?.end ?? draft.end} step="0.01" disabled={!valid} value={Math.max(selection.current?.start ?? draft.start, Math.min(selection.current?.end ?? draft.end, position))} onChange={event => { if (audio.current) { audio.current.currentTime = Number(event.target.value); setPosition(Number(event.target.value)) } }} /></label>
            {!valid && <p className="error" role="alert">起点须小于终点，且时间须在录音范围内。</p>}
            {<><div className="reference-range">{(['start', 'end'] as const).map(key => <label className="field" key={key}>{key === 'start' ? '起点' : '终点'}（秒）<input type="number" step=".01" min="0" max={source.duration} value={Number(draft[key].toFixed(2))} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}<button onClick={() => change({ start: 0, end: source.duration })}>使用整段</button></div><p className="muted">拖动选区两端，或填写精确时间。选用片段后仍可微调。</p></>}
          </section>
            <section className="panel reference-information"><div className="reference-metadata"><label className="field">录音名称<input value={draft.name} placeholder="例如：晚安独白 · 片段 01" onChange={event => change({ name: event.target.value })} /></label><label className="field">录音语言<select value={draft.language} onChange={event => change({ language: event.target.value })}>{Object.entries(languages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}{!languages[draft.language] && <option value={draft.language}>{draft.language}</option>}</select></label></div>
              <div className="row spread"><h3>录音原文 <span className="reference-optional">可选</span></h3><button onClick={() => subtitleInput.current?.click()}>从 SRT / VTT 选取</button></div><p className="muted">填写选段中实际说出的原文；译文仅供辅助查看。</p>
              <textarea aria-label="录音原文" rows={4} value={draft.transcript} placeholder="可以先留空。部分克隆引擎会在创建音色时要求补充原文。" onChange={event => change({ transcript: event.target.value })} />
              <ClipTranscription key={source.id} path={source.path} start={draft.start} end={draft.end} language={draft.language} transcript={draft.transcript} valid={valid} onResult={transcript => change({ transcript, confirmed: false })} />

            </section>
            <details className="panel reference-assist" open={assistOpen} onToggle={event => setAssistOpen(event.currentTarget.open)}><summary>台词分段与字幕 <span className="muted">按时间顺序 · 试听后自行选用</span></summary>
              <div className="row spread"><div><p className="muted">仅复用语言与录音一致的 VTT/SRT；译文和无法确定语言的字幕不会代替原文。没有可用字幕时运行 ASR，按音频时间顺序展示全部台词片段，由你试听选择。</p></div><button disabled={analyzing} onClick={() => void analyze()}>{analyzing ? '正在分析…' : analyzed ? '重新分析' : '识别并分段'}</button></div>
              {!!source.companion_subtitles?.length && <p className="notice">发现同目录字幕：{source.companion_subtitles.map(item => item.name).join('、')}。分析时先检查时间轴与语言。</p>}
              <div className="row"><button onClick={() => subtitleInput.current?.click()}>加载已有 VTT / SRT</button><span className="muted">浏览器上传音频时，可另选字幕。</span></div>
              {loadedSubtitle && <div className="row"><span className="muted">优先使用：{loadedSubtitle.name}</span><button onClick={() => { setLoadedSubtitle(null); setSegments([]) }}>移除字幕</button></div>}
              <label className="reference-language"><input type="checkbox" checked={recognizeText} disabled={analyzing} onChange={event => setRecognizeText(event.target.checked)} /> 无可用字幕时运行 ASR（可能耗时数分钟）</label>
              <label className="reference-language">录音语言 <select aria-label="分析语言" value={draft.language} onChange={event => change({ language: event.target.value })}>{Object.entries(languages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><span className="muted">不确定时可自动识别</span></label>
              {analysisTask && <div className="reference-analysis-status" role="status"><div className="row spread"><span>{analysisLabel}</span>{analyzing && <button onClick={() => void run('取消分析', async () => { setAnalysisTask(await tasksApi.cancel(analysisTask.task_id)) })}>取消分析</button>}</div>{analyzing && <progress max={1} value={analysisTask.progress} aria-label="片段分析进度" />}<p className="muted">{analyzing ? `阶段进度 ${Math.round(analysisTask.progress * 100)}% · ` : ''}已用时 {Math.floor(elapsed / 60)} 分 {elapsed % 60} 秒</p>{analyzing && <p className="muted">百分比表示处理阶段，不是剩余时间估算。可继续试听和编辑；取消将在当前处理阶段结束后生效。</p>}</div>}
              {analysisSource && <p className="notice">{analysisSource}</p>}
              {analysisWarnings.map((warning, index) => <p className="notice" key={index}>{warning}</p>)}
              {analysisError && <div className="notice error" role="alert">{analysisError}<p>你仍可以手动选段并保存。</p></div>}
              {trackingFailed && <div className="row"><span className="muted">进度连接中断，已暂停自动重试。</span><button onClick={() => setTrackingRetry(value => value + 1)}>重新获取进度</button><button onClick={() => { setAnalysisTask(null); setTrackingFailed(false); setNotice('已结束进度跟踪，原任务可能仍在运行，可在任务中心查看。') }}>结束跟踪</button></div>}
              {analyzed && !analysisError && !candidates.length && <p className="notice">暂时没有识别到台词片段，你可以在上方试听并手动选段。</p>}
              {candidates.length > 0 && <div className="reference-candidates">{candidates.map((candidate, index) => {
                const timed = hasTimestamp(candidate) && candidate.end <= source.duration
                const selected = timed && Math.abs(candidate.start! - draft.start) < .01 && Math.abs(candidate.end! - draft.end) < .01
                return <article className={'reference-candidate ' + (selected ? 'is-selected' : '')} key={`${index}-${candidate.start}-${candidate.end}`}>
                  <div className="row spread"><strong>片段 {String(index + 1).padStart(2, '0')}</strong><span className="muted">{timed ? `${time(candidate.start!)} — ${time(candidate.end!)} · ${(candidate.end! - candidate.start!).toFixed(1)} 秒` : '未提供有效时间戳 · 请手动定位'}</span></div>
                  <p>{candidate.text || '尚无识别原文，可以先试听。'}</p>
                  <div className="reference-hints"><span>{candidate.text ? '原文待核对' : '未识别原文'}</span><span>{confidenceLabel(candidate)}</span></div>
                  <div className="row"><button disabled={!timed} onClick={() => { if (hasTimestamp(candidate)) play(candidate.start, candidate.end, false, true) }}>▶ 试听</button><button disabled={!timed} className={selected ? 'reference-play' : ''} onClick={() => { const chosen = selectionFromSegment(candidate); if (chosen) change(chosen) }}>{selected ? '已选用 · 可在上方微调' : '选用这段'}</button></div>
                </article>
              })}</div>}
              {segments.length > 0 && <details className="reference-subtitles" open><summary>字幕辅助 · {subtitleRole === 'original' ? '同语原文' : '译文 / 未确认语言，仅供参考'}</summary><label className="field">字幕用途<select value={subtitleRole} onChange={event => setSubtitleRole(event.target.value as 'reference' | 'original')}><option value="reference">译文 / 未确认语言 · 仅参考</option><option value="original">已确认是与录音同语的原文</option></select></label><p className="muted">仅同语原文可填入原文编辑器；参考字幕只选用时间范围。</p>
              {segments.length > 0 && <div className="subtitle-segments">{segments.map((segment, index) => <button key={index} disabled={segment.start < 0 || segment.end > source.duration || segment.end <= segment.start} onClick={() => { change({ start: segment.start, end: segment.end, ...(subtitleRole === 'original' ? { transcript: segment.text } : {}) }); setView('editor') }}>{time(segment.start)}–{time(segment.end)} · {segment.text} · {subtitleRole === 'original' ? '选用并填入原文' : '仅选用时间范围'}</button>)}</div>}</details>}
            </details>
            <details className="panel reference-processing"><summary>音频处理 <span className="muted">按需调整音量、淡入淡出</span></summary><div className="grid"><label className="field">音量增益（dB）<input type="number" min="-24" max="12" value={draft.gain_db} onChange={event => change({ gain_db: Number(event.target.value) })} /></label>{(['fade_in', 'fade_out'] as const).map(key => <label className="field" key={key}>{key === 'fade_in' ? '淡入' : '淡出'}（秒）<input type="number" min="0" max={draft.end - draft.start} step=".05" value={draft[key]} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}</div>
              {!processingValid && <p className="error">请检查增益和淡入淡出范围；淡入与淡出总时长不能超过选段。</p>}
              <button disabled={!valid || !processingValid} onClick={() => void run('生成处理试听', async () => { audio.current?.pause(); setPreview(await speechApi.previewReference(payload())) })}>试听处理结果</button>
              {preview && <div className="item"><strong>处理后选段</strong><audio controls src={speechApi.referenceAudio(preview.id)} /><p className="muted">尚未保存。上方播放器仍播放处理前的原音。</p></div>}
            </details>
            <details className="panel reference-notes"><summary>备注 <span className="muted">来源、发布者及其他信息</span></summary>
              <label className="field">备注 <span className="reference-optional">可选</span><input value={draft.notes} placeholder="记录来源、发声特点，方便以后查找" onChange={event => change({ notes: event.target.value })} /></label>
            </details>
            <div className="reference-footer">
              <label className="reference-confirm"><input type="checkbox" disabled={!draft.transcript.trim()} checked={draft.confirmed} onChange={event => change({ confirmed: event.target.checked })} /> 我已试听，确认原文与当前片段一致</label>
<div className="row spread"><span>保存为独立录音，保留来源音频。</span><button className="primary" disabled={!valid || !processingValid || !draft.name.trim()} onClick={() => void save()}>保存到声音库</button></div></div>
        </div>}
        {view === 'saved' && stored && <section className="panel reference-saved">
          <span className="reference-eyebrow">已保存的参考录音</span><div className="row spread"><h2>{stored.name || '未命名录音'}</h2><span className="pill">{stored.archived ? '已归档' : '已入库'}</span></div>
          <p className="muted">{languages[stored.language] || stored.language} · {(stored.duration ?? 0).toFixed(1)} 秒 · {stored.confirmed ? '原文已核对' : '原文待补充或核对'}</p>
          <audio controls preload="none" src={speechApi.referenceAudio(stored.id)} />
          <div className="reference-saved-transcript"><h3>录音原文</h3><p>{stored.transcript || '尚未填写原文。'}</p>{stored.notes && <p className="muted">备注：{stored.notes}</p>}</div>
          <div className="row"><button className="primary" disabled={stored.archived} onClick={() => onUse(stored)}>用此录音创建音色</button></div>
          <details className="reference-more"><summary>更多：录音管理</summary><form key={stored.id + (stored.name || '') + (stored.notes || '')} onSubmit={event => {
            event.preventDefault(); const fields = new FormData(event.currentTarget)
            void run('更新信息', async () => { const updated = await speechApi.updateReference(stored.id, { name: String(fields.get('name') || ''), notes: String(fields.get('notes') || '') }); setStored(updated); await refresh(); setNotice('名称与备注已更新。') })
          }}><label className="field">名称<input name="name" required defaultValue={stored.name || ''} /></label><label className="field">备注<input name="notes" defaultValue={stored.notes || ''} /></label><button type="submit">更新名称与备注</button><p className="muted">修改原文或音频时，可通过“截取／处理为新录音”另存新条目。</p></form><div className="row"><a href={speechApi.referenceAudio(stored.id, false, true)} download>导出录音</a><button onClick={() => void run('载入录音', async () => {
            const item = stored; load(await speechApi.inspect(item.path), (item.name || '参考录音') + ' · 副本')
            setDraft(value => ({ ...value, transcript: item.transcript, language: item.language, confirmed: item.confirmed || false, notes: item.notes || '' }))
          })}>截取／处理为新录音</button><button onClick={() => void run(stored.archived ? '恢复录音' : '归档录音', async () => { const updated = await speechApi.updateReference(stored.id, { archived: !stored.archived }); setStored(updated); await refresh() })}>{stored.archived ? '恢复录音' : '归档录音'}</button></div></details>
        </section>}
      </section>
    </div></fieldset>
  </div>
}
