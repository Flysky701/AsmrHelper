import { useEffect, useRef, useState } from 'react'
import type { PointerEvent } from 'react'
import { speechApi } from '@/api/speech'
import type { ReferenceAsset, ReferenceInspection, ReferenceDraft, ReferenceCandidate } from '@/api/speech'
import { FILE_FILTERS } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import './ReferenceLibrary.css'

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
  const [step, setStep] = useState<'select' | 'details' | 'saved'>('select')
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [listError, setListError] = useState('')
  const [candidates, setCandidates] = useState<ReferenceCandidate[]>([])
  const [analyzed, setAnalyzed] = useState(false)
  const [analysisError, setAnalysisError] = useState('')
  const [preview, setPreview] = useState<ReferenceInspection | null>(null)
  const [segments, setSegments] = useState<{ start: number; end: number; text: string }[]>([])
  const [loop, setLoop] = useState(false)
  const audio = useRef<HTMLAudioElement>(null)
  const selection = useRef<{ start: number; end: number } | null>(null)
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

  async function run(label: string, action: () => Promise<void>) {
    if (busy) return
    setBusy(label); onBusy(true); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(message(cause)) }
    finally { setBusy(''); onBusy(false) }
  }
  function mayReplace() { return !dirty || window.confirm('当前录音还没有保存。放弃修改并打开另一段录音？') }
  function change(patch: Partial<Draft>) {
    audio.current?.pause(); selection.current = null
    setDraft(value => ({ ...value, ...patch, confirmed: patch.confirmed ?? (patch.start !== undefined || patch.end !== undefined || patch.transcript !== undefined || patch.language !== undefined ? false : value.confirmed) }))
    setDirty(true); setPreview(null)
  }
  function load(value: ReferenceInspection, name: string) {
    audio.current?.pause(); selection.current = null
    setStored(null); setSource(value); setPreview(null); setSegments([]); setCandidates([]); setAnalyzed(false); setAnalysisError('')
    setDraft({ ...initialDraft(), name: name.replace(/\.[^.]+$/, ''), end: value.duration }); setStep('select'); setDirty(true)
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
  function play(start: number, end: number) {
    if (!audio.current) return
    selection.current = { start, end }; audio.current.currentTime = start
    void audio.current.play().catch(cause => setError(message(cause)))
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
    await run('正在分析录音，长音频可能需要几分钟', async () => {
      setAnalysisError('')
      try {
        const result = await speechApi.analyze(source.path, draft.language, false)
        const available = result.segments.filter(item => Number.isFinite(item.start) && Number.isFinite(item.end) && item.start >= 0 && item.end > item.start && item.end <= source.duration)
        // Preserve source timestamps and offer alternatives without displaying the legacy quality score.
        const ranked = [...available].sort((a, b) => Number(!!b.selected) - Number(!!a.selected) || (b.score ?? 0) - (a.score ?? 0))
        const picks: ReferenceCandidate[] = []
        for (const item of ranked) {
          if (picks.every(pick => Math.min(pick.end, item.end) <= Math.max(pick.start, item.start))) picks.push(item)
          if (picks.length === 5) break
        }
        setCandidates(picks); setAnalyzed(true)
      } catch (cause) { setAnalysisError(message(cause)); setAnalyzed(true) }
    })
  }
  async function save() {
    await run('正在保存录音', async () => {
      const saved = await speechApi.reference(payload())
      setStored(saved); setDirty(false); setStep('saved'); audio.current?.pause()
      setAllAssets(previous => [saved, ...previous.filter(item => item.id !== saved.id)])
      try { await refresh() } catch { setNotice('录音已保存，列表刷新失败；稍后可重试刷新。') }
    })
  }
  function openStored(item: ReferenceAsset) {
    if (!mayReplace()) return
    audio.current?.pause(); setStored(item); setSource(null); setDirty(false); setStep('saved'); setNotice(''); setError('')
  }

  return <div className="reference-library">
    <input ref={fileInput} hidden type="file" accept=".mp3,.wav,.flac,.ogg,.m4a,.aac,.wma" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) upload(file) }} />
    <input ref={subtitleInput} hidden type="file" accept=".srt,.vtt" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void run('读取字幕', async () => setSegments((await speechApi.subtitles(await file.text(), file.name.toLowerCase().endsWith('.vtt') ? 'vtt' : 'srt')).segments)) }} />
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
        {step !== 'saved' && <ol className="reference-steps" aria-label="录音入库步骤">{['选择片段', '整理录音', '保存入库'].map((label, index) => <li key={label} aria-current={(step === 'select' ? 0 : 1) === index ? 'step' : undefined}><span>{index + 1}</span>{label}</li>)}</ol>}
        {!source && step !== 'saved' && <div className="panel reference-start" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); const file = event.dataTransfer.files[0]; if (file) upload(file) }}>
          <div className="reference-start-icon" aria-hidden="true">♫</div><h2>先放入一份你喜欢的录音</h2><p>整段保存，或从长音频里选出一小段。<br />你可以自己选，也可以让程序辅助寻找。</p>
          <button className="primary" onClick={() => void chooseFile()}>选择音频文件</button><p className="muted">也可以拖入文件 · WAV / MP3 / FLAC 等<br />浏览器上传上限 100 MiB</p>
          <div className="reference-start-tip">先存素材，再创建音色。现在不需要选择合成模型。</div>
        </div>}
        {source && step !== 'saved' && <>
          <section className="panel reference-editor">
            <div className="row spread"><div><span className="reference-eyebrow">{step === 'select' ? '01 / 选择片段' : '02 / 整理录音'}</span><h2>{step === 'select' ? '找到想留下的那一段' : '给这段录音补上信息'}</h2></div><button onClick={() => step === 'details' ? setStep('select') : void chooseFile()}>{step === 'details' ? '← 返回选段' : '更换文件'}</button></div>
            <div className="reference-source"><strong>{draft.name || '未命名录音'}</strong><span>原音 {time(source.duration)} · 已选 {(draft.end - draft.start).toFixed(1)} 秒</span></div>
            <svg className="waveform reference-waveform" viewBox="0 0 800 100" preserveAspectRatio="none" role="img" aria-label="录音波形，可拖动两端调整选区" onPointerDown={event => {
              if (step !== 'select' || busy) return
              const bounds = event.currentTarget.getBoundingClientRect(); const point = (event.clientX - bounds.left) / bounds.width * source.duration
              dragging.current = Math.abs(point - draft.start) < Math.abs(point - draft.end) ? 'start' : 'end'
              event.currentTarget.setPointerCapture(event.pointerId); moveSelection(event)
            }} onPointerMove={moveSelection} onPointerUp={event => { dragging.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId) }} onPointerCancel={() => { dragging.current = null }}>
              <rect x={draft.start / source.duration * 800} width={(draft.end - draft.start) / source.duration * 800} height="100" fill="var(--accent-soft)" />
              {source.peaks.map((peak, index) => <line key={index} x1={index / source.peaks.length * 800} x2={index / source.peaks.length * 800} y1={50 - Math.abs(peak) * 43} y2={50 + Math.abs(peak) * 43} stroke="var(--accent)" opacity=".65" />)}
              {[draft.start, draft.end].map((point, index) => <g key={index}><line x1={point / source.duration * 800} x2={point / source.duration * 800} y1="0" y2="100" stroke="var(--accent)" strokeWidth="3" /><rect x={Math.max(0, Math.min(790, point / source.duration * 800 - 5))} y="35" width="10" height="30" rx="4" fill="var(--accent)" /></g>)}
            </svg>
            <div className="reference-timeline"><span>00:00</span><span>{time(source.duration)}</span></div>
            <audio controls ref={audio} src={speechApi.referenceAudio(source.id, true)} onTimeUpdate={() => { const player = audio.current; const range = selection.current; if (player && range && player.currentTime >= range.end) { if (loop) player.currentTime = range.start; else { player.pause(); selection.current = null } } }} onSeeked={() => { const range = selection.current; if (audio.current && range && (audio.current.currentTime < range.start || audio.current.currentTime > range.end)) selection.current = null }} />
            <div className="row reference-playback"><button disabled={!valid} onClick={() => play(draft.start, draft.end)}>▶ 试听选段</button><button onClick={() => play(0, source.duration)}>试听整段</button><label><input type="checkbox" checked={loop} onChange={event => setLoop(event.target.checked)} /> 循环选段</label></div>
            {step === 'select' && <><div className="reference-range">{(['start', 'end'] as const).map(key => <label className="field" key={key}>{key === 'start' ? '起点' : '终点'}（秒）<input type="number" step=".01" min="0" max={source.duration} value={Number(draft[key].toFixed(2))} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}<button onClick={() => change({ start: 0, end: source.duration })}>使用整段</button></div><p className="muted">拖动选区两端，或填写精确时间。选中推荐后仍可微调。</p></>}
          </section>
          {step === 'select' && <>
            <section className="panel reference-assist">
              <div className="row spread"><div><h3>让程序帮你缩小试听范围</h3><p className="muted">根据识别结果寻找片段。推荐仅供参考，最终听一听再决定。</p></div><button onClick={() => void analyze()}>{analyzed ? '重新分析' : '帮我选片段'}</button></div>
              <label className="reference-language">录音语言 <select aria-label="分析语言" value={draft.language} onChange={event => change({ language: event.target.value })}>{Object.entries(languages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><span className="muted">不确定时可自动识别</span></label>
              {analysisError && <p className="notice" role="alert">暂时没能完成分析。你仍可以手动选段。<details><summary>查看原因</summary>{analysisError}</details></p>}
              {analyzed && !analysisError && !candidates.length && <p className="notice">暂时没有找到候选，你可以在上方试听并手动选段。</p>}
              {candidates.length > 0 && <div className="reference-candidates">{candidates.map((candidate, index) => {
                const selected = Math.abs(candidate.start - draft.start) < .01 && Math.abs(candidate.end - draft.end) < .01
                return <article className={'reference-candidate ' + (selected ? 'is-selected' : '')} key={`${candidate.start}-${candidate.end}`}>
                  <div className="row spread"><strong>片段 {String(index + 1).padStart(2, '0')}</strong><span className="muted">{time(candidate.start)} — {time(candidate.end)} · {(candidate.end - candidate.start).toFixed(1)} 秒</span></div>
                  <p>{candidate.text || '尚无识别原文，可以先试听。'}</p>
                  <div className="reference-hints"><span>原文待核对</span>{candidate.reasons?.filter(reason => !/ICL|x-vector/.test(reason)).slice(0, 2).map(reason => <span key={reason}>{/ASR 置信度/.test(reason) ? '识别原文可能有误，请试听核对' : /边界能量/.test(reason) ? '开头或结尾可能截断，请试听确认' : /信噪比/.test(reason) ? '可能存在背景干扰，请试听确认' : reason}</span>)}</div>
                  <div className="row"><button onClick={() => play(candidate.start, candidate.end)}>▶ 试听</button><button className={selected ? 'primary' : ''} onClick={() => change({ start: candidate.start, end: candidate.end, transcript: candidate.text || '', confirmed: false })}>{selected ? '已选用 · 可在上方微调' : '选用这段'}</button></div>
                </article>
              })}</div>}
            </section>
            <div className="reference-footer"><span>{valid ? `已选 ${(draft.end - draft.start).toFixed(1)} 秒；不分析也可以继续。` : '请设置有效的起止时间。'}</span><button className="primary" disabled={!valid} onClick={() => { audio.current?.pause(); setStep('details') }}>下一步：整理录音 →</button></div>
          </>}
          {step === 'details' && <>
            <section className="panel"><div className="grid"><label className="field">录音名称<input value={draft.name} placeholder="例如：晚安独白 · 片段 01" onChange={event => change({ name: event.target.value })} /></label><label className="field">录音语言<select value={draft.language} onChange={event => change({ language: event.target.value })}>{Object.entries(languages).map(([key, label]) => <option key={key} value={key}>{label}</option>)}{!languages[draft.language] && <option value={draft.language}>{draft.language}</option>}</select></label></div>
              <div className="row spread"><h3>录音原文 <span className="reference-optional">可选</span></h3><button onClick={() => subtitleInput.current?.click()}>从 SRT / VTT 选取</button></div><p className="muted">填写这段录音实际说出的话。不是译文，也不是希望生成的新台词。</p>
              <textarea aria-label="录音原文" rows={4} value={draft.transcript} placeholder="可以先留空。部分克隆引擎会在创建音色时要求补充原文。" onChange={event => change({ transcript: event.target.value })} />
              {segments.length > 0 && <div className="subtitle-segments">{segments.map((segment, index) => <button key={index} disabled={segment.start < 0 || segment.end > source.duration || segment.end <= segment.start} onClick={() => { change({ start: segment.start, end: segment.end, transcript: segment.text }); setStep('select') }}>{time(segment.start)}–{time(segment.end)} · {segment.text}</button>)}</div>}
              <label className="reference-confirm"><input type="checkbox" disabled={!draft.transcript.trim()} checked={draft.confirmed} onChange={event => change({ confirmed: event.target.checked })} /> 我已试听，确认原文与当前片段一致</label>
              <label className="field">备注 <span className="reference-optional">可选</span><input value={draft.notes} placeholder="记录来源、发声特点，方便以后查找" onChange={event => change({ notes: event.target.value })} /></label>
            </section>
            <details className="panel reference-processing"><summary>音频处理 <span className="muted">按需调整音量、淡入淡出</span></summary><div className="grid"><label className="field">音量增益（dB）<input type="number" min="-24" max="12" value={draft.gain_db} onChange={event => change({ gain_db: Number(event.target.value) })} /></label>{(['fade_in', 'fade_out'] as const).map(key => <label className="field" key={key}>{key === 'fade_in' ? '淡入' : '淡出'}（秒）<input type="number" min="0" max={draft.end - draft.start} step=".05" value={draft[key]} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}</div>
              {!processingValid && <p className="error">请检查增益和淡入淡出范围；淡入与淡出总时长不能超过选段。</p>}
              <button disabled={!valid || !processingValid} onClick={() => void run('生成处理试听', async () => { audio.current?.pause(); setPreview(await speechApi.previewReference(payload())) })}>试听处理结果</button>
              {preview && <div className="item"><strong>处理后选段</strong><audio controls src={speechApi.referenceAudio(preview.id)} /><p className="muted">尚未保存。上方播放器仍播放处理前的原音。</p></div>}
            </details>
            <div className="reference-footer"><span>保存为独立录音，保留来源音频。</span><button className="primary" disabled={!valid || !processingValid || !draft.name.trim()} onClick={() => void save()}>保存到声音库</button></div>
          </>}
        </>}
        {step === 'saved' && stored && <section className="panel reference-saved">
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
