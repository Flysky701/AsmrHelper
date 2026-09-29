import { useEffect, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import { speechApi } from '@/api/speech'
import { tasksApi } from '@/api/tasks'
import { ApiError } from '@/api/client'
import type { TaskStatusResponse } from '@/api/types'
import type { ReferenceAsset, ReferenceInspection, ReferenceDraft, ReferenceCandidate } from '@/api/speech'
import { FILE_FILTERS } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import './ReferenceLibrary.css'
import ClipTranscription from './ClipTranscription'
import { playbackBoundary } from './referencePlayback'

type Props = { assets: ReferenceAsset[]; refresh: () => Promise<void>; onUse: (asset: ReferenceAsset) => void; onBusy: (value: boolean) => void; active: boolean }
type Draft = Omit<ReferenceDraft, 'path'>
const initialDraft = (): Draft => ({ name: '', notes: '', start: 0, end: 0, transcript: '', language: 'auto', confirmed: false, gain_db: 0, fade_in: 0, fade_out: 0 })
const time = (value: number) => `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toFixed(1).padStart(4, '0')}`
const languages: Record<string, string> = { auto: '暂不确定', zh: '中文', ja: '日语', en: '英语', ko: '韩语' }
const message = (cause: unknown) => cause instanceof Error ? cause.message : String(cause)

export default function ReferenceLibrary({ assets, refresh, onUse, onBusy, active }: Props) {
  const [allAssets, setAllAssets] = useState(assets)
  const [showArchived, setShowArchived] = useState(false)
  const [query, setQuery] = useState('')
  const [stored, setStored] = useState<ReferenceAsset | null>(null)
  const [source, setSource] = useState<ReferenceInspection | null>(null)
  const [draft, setDraft] = useState<Draft>(initialDraft)
  const [view, setView] = useState<'editor' | 'saved'>('editor')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [listError, setListError] = useState('')
  const [candidates, setCandidates] = useState<ReferenceCandidate[]>([])
  const [analyzed, setAnalyzed] = useState(false)
  const [analysisError, setAnalysisError] = useState('')
  const [analysisTask, setAnalysisTask] = useState<TaskStatusResponse | null>(null)
  const [recognizeText, setRecognizeText] = useState(false)
  const [analysisWarnings, setAnalysisWarnings] = useState<string[]>([])
  const [analysisSource, setAnalysisSource] = useState('')
  const [clock, setClock] = useState(Date.now())
  const [trackingFailed, setTrackingFailed] = useState(false)
  const [trackingRetry, setTrackingRetry] = useState(0)
  const [loadedSubtitle, setLoadedSubtitle] = useState<{ name: string; subtitle_text: string; subtitle_format: 'vtt' | 'srt' } | null>(null)
  const [preview, setPreview] = useState<ReferenceInspection | null>(null)
  const [segments, setSegments] = useState<{ start: number; end: number; text: string }[]>([])
  const [loop, setLoop] = useState(false)
  const audio = useRef<HTMLAudioElement>(null)
  const selection = useRef<{ start: number; end: number } | null>(null)
  const wholePlayback = useRef(false)
  const playbackFrame = useRef(0)
  const playbackBounds = useRef({ start: 0, end: 0, loop: false })
  playbackBounds.current = { start: draft.start, end: draft.end, loop }
  const dragging = useRef<'start' | 'end' | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const subtitleInput = useRef<HTMLInputElement>(null)
  const dirtyRef = useRef(false)
  dirtyRef.current = dirty

  useEffect(() => {
    let mounted = true
    void speechApi.references(showArchived).then(result => { if (mounted) { setAllAssets(result.assets); setListError('') } })
      .catch(cause => { if (mounted) setListError(message(cause)) })
    return () => { mounted = false }
  }, [assets, showArchived])
  useEffect(() => {
    const guard = () => !dirtyRef.current || window.confirm('这段录音还没有保存。离开并放弃本次修改？')
    useNavStore.getState().setNavigationGuard(guard)
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirtyRef.current) { event.preventDefault(); event.returnValue = '' } }
    window.addEventListener('beforeunload', beforeUnload)
    return () => { useNavStore.getState().setNavigationGuard(null); window.removeEventListener('beforeunload', beforeUnload) }
  }, [])
  useEffect(() => { if (!active) audio.current?.pause() }, [active])
  useEffect(() => () => cancelAnimationFrame(playbackFrame.current), [])
  useEffect(() => {
    const taskId = analysisTask?.task_id
    if (!taskId || !source) return
    let mounted = true
    let timer: ReturnType<typeof setTimeout>
    let failures = 0
    setTrackingFailed(false)
    const duration = source.duration
    async function poll() {
      try {
        const { status, result } = await speechApi.analysisStatus(taskId!)
        if (!mounted) return
        failures = 0
        setAnalysisTask(status); setAnalysisError('')
        if (status.state === 'completed') {
          if (!result) { setAnalysisError('分析任务已结束，但未返回片段结果。请重新分析。'); setAnalyzed(true); return }
          const ranked = result.segments.filter(item => Number.isFinite(item.start) && Number.isFinite(item.end) && item.start >= 0 && item.end > item.start && item.end <= duration)
            .sort((a, b) => Number(!!b.selected) - Number(!!a.selected) || (b.score ?? 0) - (a.score ?? 0))
          const picks: ReferenceCandidate[] = []
          for (const item of ranked) {
            if (picks.every(pick => Math.min(pick.end, item.end) <= Math.max(pick.start, item.start))) picks.push(item)
            if (picks.length === 5) break
          }
          setCandidates(picks); setAnalyzed(true)
          setAnalysisWarnings(result.warnings || [])
          setAnalysisSource(result.transcript_source === 'subtitle' ? `已复用字幕：${result.subtitle?.name || '同目录字幕'}，未运行 ASR。` : result.transcript_source === 'asr' ? '原文来自本次 ASR，仍需试听核对。' : '根据停顿和音量变化选段，未运行 ASR。')
          return
        }
        if (['failed', 'cancelled', 'skipped'].includes(status.state)) {
          setAnalysisError(String(status.error?.message || status.detail || status.message || '分析已结束，未生成结果。')); setAnalyzed(true)
          return
        }
      } catch (cause) {
        if (!mounted) return
        setAnalysisError(message(cause))
        if (cause instanceof ApiError && cause.status === 404) {
          setAnalysisTask(null); setAnalyzed(true)
          setAnalysisError('分析任务已不存在，后端可能已重启。请重新分析。')
          return
        }
        if (++failures >= 3) { setTrackingFailed(true); return }
      }
      if (mounted) timer = setTimeout(() => void poll(), 1500)
    }
    void poll()
    return () => { mounted = false; clearTimeout(timer) }
  }, [analysisTask?.task_id, trackingRetry])

  async function run(label: string, action: () => Promise<void>) {
    if (busy) return
    setBusy(label); onBusy(true); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(message(cause)) }
    finally { setBusy(''); onBusy(false) }
  }
  function mayReplace() { return !dirty || window.confirm('当前录音还没有保存。放弃修改并打开另一段录音？') }
  function change(patch: Partial<Draft>) {
    audio.current?.pause(); selection.current = null; wholePlayback.current = false
    setDraft(value => ({ ...value, ...patch, confirmed: patch.confirmed ?? (patch.start !== undefined || patch.end !== undefined || patch.transcript !== undefined || patch.language !== undefined ? false : value.confirmed) }))
    setDirty(true); setPreview(null)
  }
  function load(value: ReferenceInspection, name: string) {
    audio.current?.pause(); selection.current = null; wholePlayback.current = false
    setStored(null); setSource(value); setPreview(null); setSegments([]); setCandidates([]); setAnalyzed(false); setAnalysisError(''); setAnalysisTask(null); setAnalysisWarnings([]); setAnalysisSource(''); setLoadedSubtitle(null); setTrackingFailed(false)
    setDraft({ ...initialDraft(), name: name.replace(/\.[^.]+$/, ''), end: value.duration }); setView('editor'); setDirty(true)
  }
  function upload(file: File) {
    if (busy || !mayReplace()) return
    void run('正在读取录音', async () => load(await speechApi.uploadReference(file), file.name))
  }
  async function chooseFile() {
    if (busy) return
    if ('__TAURI_INTERNALS__' in window) {
      if (!mayReplace()) return
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
  function play(start: number, end: number, whole = false) {
    if (!audio.current) return
    wholePlayback.current = whole
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
    else { wholePlayback.current = false; selection.current = null }
  }
  function moveSelection(event: PointerEvent<SVGSVGElement>) {
    if (!source || !dragging.current || busy) return
    const bounds = event.currentTarget.getBoundingClientRect()
    const position = Math.max(0, Math.min(source.duration, (event.clientX - bounds.left) / bounds.width * source.duration))
    const gap = Math.min(.01, source.duration)
    change(dragging.current === 'start' ? { start: Math.min(draft.end - gap, position) } : { end: Math.max(draft.start + gap, position) })
  }
  async function analyze() {
    if (!source) return
    await run('正在提交片段分析', async () => {
      setAnalysisError('')
      try {
        setCandidates([]); setAnalyzed(false); setAnalysisWarnings([]); setAnalysisSource('')
        setAnalysisTask(await speechApi.analyzeTask(source.path, draft.language, recognizeText, loadedSubtitle || undefined))
      } catch (cause) { setAnalysisError(message(cause)); setAnalyzed(true) }
    })
  }
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
  function openStored(item: ReferenceAsset) {
    if (!mayReplace()) return
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
      setNotice('已加载字幕，可直接选取字幕片段，或重新分析以筛选候选。')
    }) }} />
    {error && <div className="notice error" role="alert">{error}</div>}{notice && <div className="notice" role="status">{notice}</div>}
    {busy && <div className="reference-busy" role="status"><span className="reference-spinner" />{busy}…</div>}
    <fieldset disabled={!!busy} className="lab-fieldset"><div className="reference-layout">
      <aside className="panel reference-sidebar">
        <div className="row spread"><h2>我的录音 <span className="reference-count">{found.length}</span></h2><button className="primary" onClick={() => void chooseFile()}>＋ 导入</button></div>
        <p className="muted">每段录音都是一份可复用的参考素材。</p>
        <input aria-label="搜索录音" placeholder="搜索名称、备注或原文" value={query} onChange={event => setQuery(event.target.value)} />
        <label className="reference-archive"><input type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} /> 显示已归档</label>
        {listError && <p className="error" role="alert">录音列表加载失败，可点击页面右上角刷新。</p>}
        {!found.length && !listError && <div className="empty">{query ? '没有匹配的录音。试试其他关键词。' : '还没有参考录音。\n从一份音频开始，保存你想留下的声音。'}</div>}
        <div className="reference-assets">{found.map(item => <button key={item.id} className={'reference-asset ' + (stored?.id === item.id ? 'is-selected' : '')} onClick={() => openStored(item)}>
          <strong>{item.name || '未命名录音'}</strong><span>{languages[item.language] || item.language} · {(item.duration ?? 0).toFixed(1)} 秒{item.archived ? ' · 已归档' : ''}</span>
          <span className={'reference-status ' + (item.confirmed ? 'is-confirmed' : '')}>{!item.transcript ? '原文待补充' : item.confirmed ? '原文已核对' : '原文待核对'}</span>
        </button>)}</div>
      </aside>
      <section className="reference-main">
        {!source && view !== 'saved' && <div className="panel reference-start" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); const file = event.dataTransfer.files[0]; if (file) upload(file) }}>
          <div className="reference-start-icon" aria-hidden="true">♫</div><h2>导入参考录音</h2><p>整段保存，或从长音频里选出一小段。<br />你可以自己选，也可以让程序辅助寻找。</p>
          <button className="primary" onClick={() => void chooseFile()}>选择音频文件</button><p className="muted">也可以拖入文件 · WAV / MP3 / FLAC 等<br />浏览器上传上限 100 MiB</p>
          <div className="reference-start-tip">录音可独立保存，需要时再用于创建音色。</div>
        </div>}
        {source && view !== 'saved' && <div className="reference-workspace"><div className="reference-workspace-audio">
          <section className="panel reference-editor">
            <div className="row spread"><h2>录音工作台</h2><button onClick={() => void chooseFile()}>更换文件</button></div>
            <div className="reference-source"><strong>{draft.name || '未命名录音'}</strong><span>原音 {time(source.duration)} · 已选 {(draft.end - draft.start).toFixed(1)} 秒</span></div>
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
            <audio controls ref={audio} src={speechApi.referenceAudio(source.id, true)} onPlay={onPlayerPlay} onPause={() => cancelAnimationFrame(playbackFrame.current)} onTimeUpdate={enforcePlayback} onSeeked={enforcePlayback} onEnded={onPlayerEnded} />
            <div className="row reference-playback"><button disabled={!valid} onClick={() => play(draft.start, draft.end)}>▶ 试听选段</button><button onClick={() => play(0, source.duration, true)}>试听整段</button><label><input type="checkbox" checked={loop} onChange={event => setLoop(event.target.checked)} /> 循环选段</label></div>
            <p className="muted">播放器默认播放框选范围；“试听整段”可临时播放完整录音。</p>
            {<><div className="reference-range">{(['start', 'end'] as const).map(key => <label className="field" key={key}>{key === 'start' ? '起点' : '终点'}（秒）<input type="number" step=".01" min="0" max={source.duration} value={Number(draft[key].toFixed(2))} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}<button onClick={() => change({ start: 0, end: source.duration })}>使用整段</button></div><p className="muted">拖动选区两端，或填写精确时间。选中推荐后仍可微调。</p></>}
          </section>
            <section className="panel reference-assist">
              <div className="row spread"><div><h3>辅助选段</h3><p className="muted">仅复用语言与录音一致的 VTT/SRT；译文和无法确定语言的字幕不会代替原文。没有可用字幕时按停顿和音量变化选段。</p></div><button disabled={analyzing} onClick={() => void analyze()}>{analyzing ? '正在分析…' : analyzed ? '重新分析' : '帮我选片段'}</button></div>
              {!!source.companion_subtitles?.length && <p className="notice">发现同目录字幕：{source.companion_subtitles.map(item => item.name).join('、')}。分析时先检查时间轴与语言。</p>}
              <div className="row"><button onClick={() => subtitleInput.current?.click()}>加载已有 VTT / SRT</button><span className="muted">浏览器上传音频时，可另选字幕。</span></div>
              {loadedSubtitle && <div className="row"><span className="muted">优先使用：{loadedSubtitle.name}</span><button onClick={() => { setLoadedSubtitle(null); setSegments([]) }}>移除字幕</button></div>}
              <label className="reference-language"><input type="checkbox" checked={recognizeText} disabled={analyzing} onChange={event => setRecognizeText(event.target.checked)} /> 无可用字幕时运行 ASR（可能耗时数分钟）</label>
              <label className="reference-language">录音语言 <select aria-label="分析语言" value={draft.language} onChange={event => change({ language: event.target.value })}>{Object.entries(languages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><span className="muted">不确定时可自动识别</span></label>
              {analysisTask && <div className="reference-analysis-status" role="status"><div className="row spread"><span>{analysisLabel}</span>{analyzing && <button onClick={() => void run('取消分析', async () => { setAnalysisTask(await tasksApi.cancel(analysisTask.task_id)) })}>取消分析</button>}</div><progress max={1} value={analysisTask.progress} aria-label="片段分析进度" /><p className="muted">阶段进度 {Math.round(analysisTask.progress * 100)}% · 已用时 {Math.floor(elapsed / 60)} 分 {elapsed % 60} 秒</p>{analyzing && <p className="muted">百分比表示处理阶段，不是剩余时间估算。可继续试听和编辑；取消将在当前处理阶段结束后生效。</p>}</div>}
              {analysisSource && <p className="notice">{analysisSource}</p>}
              {analysisWarnings.map((warning, index) => <p className="notice" key={index}>{warning}</p>)}
              {analysisError && <div className="notice error" role="alert">{analysisError}<p>你仍可以手动选段并保存。</p></div>}
              {trackingFailed && <div className="row"><span className="muted">进度连接中断，已暂停自动重试。</span><button onClick={() => setTrackingRetry(value => value + 1)}>重新获取进度</button><button onClick={() => { setAnalysisTask(null); setTrackingFailed(false); setNotice('已结束进度跟踪，原任务可能仍在运行，可在任务中心查看。') }}>结束跟踪</button></div>}
              {analyzed && !analysisError && !candidates.length && <p className="notice">暂时没有找到候选，你可以在上方试听并手动选段。</p>}
              {candidates.length > 0 && <div className="reference-candidates">{candidates.map((candidate, index) => {
                const selected = Math.abs(candidate.start - draft.start) < .01 && Math.abs(candidate.end - draft.end) < .01
                return <article className={'reference-candidate ' + (selected ? 'is-selected' : '')} key={`${candidate.start}-${candidate.end}`}>
                  <div className="row spread"><strong>片段 {String(index + 1).padStart(2, '0')}</strong><span className="muted">{time(candidate.start)} — {time(candidate.end)} · {(candidate.end - candidate.start).toFixed(1)} 秒</span></div>
                  <p>{candidate.text || '尚无识别原文，可以先试听。'}</p>
                  <div className="reference-hints"><span>{candidate.text ? '原文待核对' : '未识别原文'}</span>{candidate.reasons?.filter(reason => !/ICL|x-vector/.test(reason)).slice(0, 2).map(reason => <span key={reason}>{/ASR 置信度/.test(reason) ? '识别原文可能有误，请试听核对' : /边界能量/.test(reason) ? '开头或结尾可能截断，请试听确认' : /信噪比/.test(reason) ? '可能存在背景干扰，请试听确认' : reason}</span>)}</div>
                  <div className="row"><button onClick={() => play(candidate.start, candidate.end)}>▶ 试听</button><button className={selected ? 'primary' : ''} onClick={() => change({ start: candidate.start, end: candidate.end, transcript: candidate.text || '', confirmed: false })}>{selected ? '已选用 · 可在上方微调' : '选用这段'}</button></div>
                </article>
              })}</div>}
            </section>
          </div><div className="reference-workspace-details">
            <section className="panel"><h3>录音信息</h3><div className="grid"><label className="field">录音名称<input value={draft.name} placeholder="例如：晚安独白 · 片段 01" onChange={event => change({ name: event.target.value })} /></label><label className="field">录音语言<select value={draft.language} onChange={event => change({ language: event.target.value })}>{Object.entries(languages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}{!languages[draft.language] && <option value={draft.language}>{draft.language}</option>}</select></label></div>
              <div className="row spread"><h3>录音原文 <span className="reference-optional">可选</span></h3><button onClick={() => subtitleInput.current?.click()}>从 SRT / VTT 选取</button></div><p className="muted">填写这段录音实际说出的话。不是译文，也不是希望生成的新台词。</p>
              <textarea aria-label="录音原文" rows={4} value={draft.transcript} placeholder="可以先留空。部分克隆引擎会在创建音色时要求补充原文。" onChange={event => change({ transcript: event.target.value })} />
              <ClipTranscription key={source.id} path={source.path} start={draft.start} end={draft.end} language={draft.language} transcript={draft.transcript} valid={valid} onResult={transcript => change({ transcript, confirmed: false })} />
              {segments.length > 0 && <div className="subtitle-segments">{segments.map((segment, index) => <button key={index} disabled={segment.start < 0 || segment.end > source.duration || segment.end <= segment.start} onClick={() => { change({ start: segment.start, end: segment.end, transcript: segment.text }); setView('editor') }}>{time(segment.start)}–{time(segment.end)} · {segment.text}</button>)}</div>}
              <label className="reference-confirm"><input type="checkbox" disabled={!draft.transcript.trim()} checked={draft.confirmed} onChange={event => change({ confirmed: event.target.checked })} /> 我已试听，确认原文与当前片段一致</label>
              <label className="field">备注 <span className="reference-optional">可选</span><input value={draft.notes} placeholder="记录来源、发声特点，方便以后查找" onChange={event => change({ notes: event.target.value })} /></label>
            </section>
            <details className="panel reference-processing"><summary>音频处理 <span className="muted">按需调整音量、淡入淡出</span></summary><div className="grid"><label className="field">音量增益（dB）<input type="number" min="-24" max="12" value={draft.gain_db} onChange={event => change({ gain_db: Number(event.target.value) })} /></label>{(['fade_in', 'fade_out'] as const).map(key => <label className="field" key={key}>{key === 'fade_in' ? '淡入' : '淡出'}（秒）<input type="number" min="0" max={draft.end - draft.start} step=".05" value={draft[key]} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}</div>
              {!processingValid && <p className="error">请检查增益和淡入淡出范围；淡入与淡出总时长不能超过选段。</p>}
              <button disabled={!valid || !processingValid} onClick={() => void run('生成处理试听', async () => { audio.current?.pause(); setPreview(await speechApi.previewReference(payload())) })}>试听处理结果</button>
              {preview && <div className="item"><strong>处理后选段</strong><audio controls src={speechApi.referenceAudio(preview.id)} /><p className="muted">尚未保存。上方播放器仍播放处理前的原音。</p></div>}
            </details>
            <div className="reference-footer"><span>保存为独立录音，保留来源音频。</span><button className="primary" disabled={!valid || !processingValid || !draft.name.trim()} onClick={() => void save()}>保存到声音库</button></div>
          </div>
        </div>}
        {view === 'saved' && stored && <section className="panel reference-saved">
          <span className="reference-eyebrow">已保存的参考录音</span><div className="row spread"><h2>{stored.name || '未命名录音'}</h2><span className="pill">{stored.archived ? '已归档' : '已入库'}</span></div>
          <p className="muted">{languages[stored.language] || stored.language} · {(stored.duration ?? 0).toFixed(1)} 秒 · {stored.confirmed ? '原文已核对' : '原文待补充或核对'}</p>
          <audio controls src={speechApi.referenceAudio(stored.id)} />
          <div className="reference-saved-transcript"><h3>录音原文</h3><p>{stored.transcript || '尚未填写原文。'}</p>{stored.notes && <p className="muted">备注：{stored.notes}</p>}</div>
          <div className="row"><button className="primary" disabled={stored.archived} onClick={() => onUse(stored)}>用于创建音色 →</button><button onClick={() => void chooseFile()}>继续添加录音</button></div>
          <details className="reference-more"><summary>录音管理</summary><form key={stored.id + (stored.name || '') + (stored.notes || '')} onSubmit={event => {
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
