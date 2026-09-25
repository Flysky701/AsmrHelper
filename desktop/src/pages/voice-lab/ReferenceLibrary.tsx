import { useEffect, useRef, useState } from 'react'
import { speechApi } from '@/api/speech'
import type { ReferenceAsset, ReferenceInspection, ReferenceDraft } from '@/api/speech'
import { FILE_FILTERS } from '@/hooks/useFileSelector'

type Props = { assets: ReferenceAsset[]; refresh: () => Promise<void>; onUse: (asset: ReferenceAsset) => void; onBusy: (value: boolean) => void }
export default function ReferenceLibrary({ assets, refresh, onUse, onBusy }: Props) {
  const [stored, setStored] = useState<ReferenceAsset | null>(null)
  const [allAssets, setAllAssets] = useState<ReferenceAsset[]>(assets)
  const [showArchived, setShowArchived] = useState(false)
  useEffect(() => { let active = true; void speechApi.references(showArchived).then(result => { if (active) setAllAssets(result.assets) }).catch(cause => { if (active) setError(String(cause)) }); return () => { active = false } }, [assets, showArchived])
  const [source, setSource] = useState<ReferenceInspection | null>(null)
  const [draft, setDraft] = useState<Omit<ReferenceDraft, 'path'>>({ name: '', notes: '', start: 0, end: 10, transcript: '', language: 'zh', confirmed: false, gain_db: 0, fade_in: 0, fade_out: 0 })
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [loop, setLoop] = useState(true)
  const [preview, setPreview] = useState<ReferenceInspection | null>(null)
  const [segments, setSegments] = useState<{ start: number; end: number; text: string }[]>([])
  const audio = useRef<HTMLAudioElement>(null)
  const selecting = useRef(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const subtitleInput = useRef<HTMLInputElement>(null)
  async function run(label: string, action: () => Promise<void>) {
    if (busy) return
    setBusy(label); onBusy(true); setError(''); setNotice('')
    try { await action() } catch (cause) { setError(String(cause)) }
    finally { setBusy(''); onBusy(false) }
  }
  function change(patch: Partial<typeof draft>) { setDraft(value => ({ ...value, ...patch, confirmed: patch.confirmed ?? (patch.start !== undefined || patch.end !== undefined || patch.transcript !== undefined || patch.language !== undefined ? false : value.confirmed) })); setPreview(null) }
  function load(value: ReferenceInspection, name: string, item?: ReferenceAsset) {
    audio.current?.pause(); selecting.current = false
    setStored(item || null); setSource(value); setPreview(null); setSegments([])
    setDraft({ name: item?.name || name, notes: item?.notes || '', start: 0, end: value.duration, transcript: item?.transcript || '', language: item?.language || 'zh', confirmed: item?.confirmed || false, gain_db: 0, fade_in: 0, fade_out: 0 })
  }
  async function chooseFile() {
    if ('__TAURI_INTERNALS__' in window) {
      await run('读取音频', async () => { const { open } = await import('@tauri-apps/plugin-dialog'); const path = await open({ multiple: false, filters: [FILE_FILTERS.audio] }); if (typeof path === 'string') load(await speechApi.inspect(path), path.split(/[\\/]/).pop() || '参考录音') })
    } else fileInput.current?.click()
  }
  const payload = (): ReferenceDraft => ({ ...draft, path: source!.path })
  const valid = !!source && draft.start >= 0 && draft.end > draft.start && draft.end <= source.duration
  const found = allAssets.filter(item => `${item.name || ''} ${item.notes || ''} ${item.transcript || ''}`.toLowerCase().includes(query.toLowerCase()))
  return <div>
    <input ref={fileInput} hidden type="file" accept=".mp3,.wav,.flac,.ogg,.m4a,.aac,.wma" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void run('上传并读取音频', async () => { load(await speechApi.uploadReference(file), file.name); setNotice('音频已读取，请选段并保存到声音库。原音频保留。') }) }} />
    <input ref={subtitleInput} hidden type="file" accept=".srt,.vtt" onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) void run('读取字幕', async () => setSegments((await speechApi.subtitles(await file.text(), file.name.toLowerCase().endsWith('.vtt') ? 'vtt' : 'srt')).segments)) }} />
    {error && <p className="notice error" role="alert">{error}</p>}{notice && <p className="notice" role="status">{notice}</p>}{busy && <p role="status">{busy}…</p>}
    <fieldset disabled={!!busy} className="lab-fieldset"><div className="columns"><aside className="panel"><div className="row spread"><h2>人声参考录音</h2><button className="primary" onClick={() => void chooseFile()}>导入录音</button></div><p className="muted">保存录音片段，供我的音色引用。导入和保存均不会合成声音。</p><input aria-label="搜索录音" placeholder="搜索名称、备注或参考文字" value={query} onChange={event => setQuery(event.target.value)} />
      <label><input type="checkbox" checked={showArchived} onChange={event => setShowArchived(event.target.checked)} /> 显示已归档</label>
      {!found.length && <p className="empty">{assets.length ? '没有匹配的录音。' : '声音库为空。先导入人声录音，也可在我的音色中直接创建声音设计规则。'}</p>}
      {found.map(item => <div className="item" key={item.id}><strong>{item.archived ? '已归档 · ' : ''}{item.name || item.transcript?.slice(0, 24) || '未命名录音'}</strong><p className="muted">{item.language} · {item.duration?.toFixed(1) || '—'} 秒 · {item.notes}</p><audio controls src={speechApi.referenceAudio(item.id)} /><div className="row"><a href={speechApi.referenceAudio(item.id, false, true)} download>导出录音</a><button onClick={() => void run('载入录音', async () => load(await speechApi.inspect(item.path), item.name || '', item))}>选段与处理</button><button disabled={item.archived} onClick={() => onUse(item)}>用于我的音色</button>{item.archived ? <button onClick={() => void run('恢复录音', async () => { await speechApi.updateReference(item.id, { archived: false }); await refresh() })}>恢复录音</button> : <button onClick={() => void run('归档录音', async () => { await speechApi.archiveReference(item.id); await refresh(); setNotice('已归档，已有音色与历史任务仍保留引用。') })}>归档</button>}</div></div>)}
    </aside><section className="panel"><h2>录音编辑</h2>{!source ? <p className="empty">导入或选择录音后，在这里试听、截取与处理。</p> : <>
      <p className="muted">{source.path} · {source.duration.toFixed(2)} 秒</p>
      <svg className="waveform" viewBox="0 0 600 100" preserveAspectRatio="none" role="img" aria-label="音频波形；点击设起点，Shift 点击设终点" onClick={event => { if (busy) return; const bounds = event.currentTarget.getBoundingClientRect(); const time = Math.max(0, Math.min(source.duration, (event.clientX - bounds.left) / bounds.width * source.duration)); change(event.shiftKey ? { end: Math.max(draft.start + .01, time) } : { start: Math.min(draft.end - .01, time) }) }}>
        <rect x={draft.start / source.duration * 600} width={(draft.end - draft.start) / source.duration * 600} height="100" fill="var(--accent-soft)" />{source.peaks.map((peak, index) => <line key={index} x1={index / source.peaks.length * 600} x2={index / source.peaks.length * 600} y1={50 - Math.abs(peak) * 45} y2={50 + Math.abs(peak) * 45} stroke="var(--accent)" />)}
      </svg><p className="muted">点击波形设起点，Shift + 点击设终点；也可填写精确时间。</p>
      <audio controls ref={audio} src={speechApi.referenceAudio(source.id, true)} onTimeUpdate={() => { if (!audio.current || !selecting.current) return; if (audio.current.currentTime >= draft.end) { if (loop) audio.current.currentTime = draft.start; else { audio.current.pause(); selecting.current = false } } }} />
      {stored && <details><summary>保留的原始录音</summary><audio controls src={speechApi.referenceAudio(stored.id, true)} /></details>}
      <div className="row"><button disabled={!valid} onClick={() => { if (audio.current) { selecting.current = true; audio.current.currentTime = draft.start; void audio.current.play().catch(cause => setError(String(cause))) } }}>试听选段</button><button onClick={() => { selecting.current = false; if (audio.current) { audio.current.currentTime = 0; void audio.current.play().catch(cause => setError(String(cause))) } }}>试听原音</button><label><input type="checkbox" checked={loop} onChange={event => setLoop(event.target.checked)} /> 循环选段</label></div>
      <div className="grid" style={{ marginTop: 16 }}>{(['start', 'end'] as const).map(key => <label className="field" key={key}>{key === 'start' ? '起点' : '终点'}（秒）<input type="number" step=".01" min="0" max={source.duration} value={draft[key]} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}<label className="field">名称<input value={draft.name} onChange={event => change({ name: event.target.value })} /></label><label className="field">备注<input value={draft.notes} onChange={event => change({ notes: event.target.value })} /></label><label className="field">语言<input value={draft.language} onChange={event => change({ language: event.target.value })} /></label></div>
      {stored && <button disabled={!draft.name.trim()} onClick={() => void run('更新名称与备注', async () => { const updated = await speechApi.updateReference(stored.id, { name: draft.name, notes: draft.notes }); setStored(updated); await refresh(); setNotice('名称与备注已更新，音频不变。') })}>更新名称与备注</button>}
      <label className="field">参考文字（可稍后补充）<textarea value={draft.transcript} onChange={event => change({ transcript: event.target.value })} /></label><label><input type="checkbox" checked={draft.confirmed} onChange={event => change({ confirmed: event.target.checked })} /> 已核对文字与录音片段一致</label><p className="muted">字幕可辅助定位；译文不能当作原音频转录。部分克隆引擎需要准确原文。</p>
      <button onClick={() => subtitleInput.current?.click()}>加载 SRT / VTT 辅助选段</button>{segments.length > 0 && <div className="subtitle-segments">{segments.map((segment, index) => <button key={index} disabled={segment.end > source.duration} onClick={() => change({ start: segment.start, end: segment.end, transcript: segment.text })}>{segment.start.toFixed(1)}–{segment.end.toFixed(1)} · {segment.text}</button>)}</div>}
      <h3 style={{ marginTop: 20 }}>简单音频处理</h3><div className="grid"><label className="field">音量增益（dB）<input type="number" min="-24" max="12" step="1" value={draft.gain_db} onChange={event => change({ gain_db: Number(event.target.value) })} /></label>{(['fade_in', 'fade_out'] as const).map(key => <label className="field" key={key}>{key === 'fade_in' ? '淡入' : '淡出'}（秒）<input type="number" min="0" max={draft.end - draft.start} step=".05" value={draft[key]} onChange={event => change({ [key]: Number(event.target.value) })} /></label>)}</div>
      <div className="row"><button disabled={!valid} onClick={() => void run('生成处理试听', async () => { audio.current?.pause(); setPreview(await speechApi.previewReference(payload())) })}>试听处理结果</button><button className="primary" disabled={!valid || !draft.name.trim()} onClick={() => void run('保存录音', async () => { const saved = await speechApi.reference(payload()); await refresh(); load(await speechApi.inspect(saved.path), saved.name || '', saved); setNotice('已保存为独立录音，原音保留。可从左侧用于我的音色。') })}>保存为新录音</button></div>
      {preview && <div className="item"><h3>处理后选段</h3><audio controls src={speechApi.referenceAudio(preview.id)} /><p className="muted">上方试听选段为处理前原音；此处为当前处理效果。尚未保存到声音库。</p></div>}
    </>}</section></div></fieldset>
  </div>
}
