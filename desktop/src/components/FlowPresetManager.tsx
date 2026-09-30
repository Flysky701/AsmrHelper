import { useState } from 'react'
import { pipelineApi } from '@/api/pipeline'
import type { FlowPresetDraft, PresetItem } from '@/api/types'
import { PIPELINE_STAGE_IDS, PIPELINE_STAGE_LABELS, type PipelineStageId } from '@/domain/pipelinePreset'
import { isUsableFlowPreset } from '@/domain/workbenchFlow'
import './FlowPresets.css'

type Editor = FlowPresetDraft & { id?: string; revision?: number }
export default function FlowPresetManager({ presets, loading, error, onReload }: {
  presets: PresetItem[]; loading: boolean; error: string; onReload: () => Promise<void>
}) {
  const [draft, setDraft] = useState<Editor | null>(null)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const [saveError, setSaveError] = useState('')
  function open(item: PresetItem, copy: boolean) {
    if (!isUsableFlowPreset(item)) { setSaveError('预设缺少有效步骤或产出，请确认后端版本并重新加载目录。'); return }
    if (draft && !window.confirm('当前预设编辑尚未保存，放弃修改并打开另一项？')) return
    setDraft({ label: item.label + (copy ? '（副本）' : ''), description: item.description, stages: [...item.stages], outputs: [...item.outputs],
      ...(copy ? {} : { id: item.id, revision: item.revision }) })
    setMessage(''); setSaveError('')
  }
  async function save() {
    if (!draft || saving) return
    setSaving(true); setMessage(''); setSaveError('')
    try {
      const body = { label: draft.label.trim(), description: draft.description.trim(), stages: draft.stages, outputs: draft.outputs }
      const saved = draft.id
        ? await pipelineApi.updatePreset(draft.id, { ...body, revision: draft.revision! })
        : await pipelineApi.createPreset(body)
      await onReload()
      setDraft(null); setMessage(`已保存“${saved.label}” · 修订 ${saved.revision}，工作台可选择此预设。`)
    } catch (cause) { setSaveError('保存失败，当前编辑已保留：' + String(cause)) }
    finally { setSaving(false) }
  }
  return <section className="flow-preset-manager">
    <h2>流程预设</h2><p>这里与工作台使用同一份目录。内置预设可复制为自定义预设，再编辑步骤与产出。</p>
    <p className="flow-preset-scope">流程预设不包含素材、音色或合成参数。TTS 高级预设在“声音与音色”中保存，在工作台配音参数中使用。</p>
    {error && <div role="alert">{error}<button type="button" disabled={loading || saving} onClick={() => void onReload()}>重新加载</button></div>}
    {loading && <p role="status">正在加载预设…</p>}
    {message && <p role="status">{message}</p>}
    {draft && <form className="flow-preset-editor" onSubmit={event => { event.preventDefault(); void save() }}>
      <h3>{draft.id ? '编辑自定义预设' : '复制为自定义预设'}</h3>
      <fieldset disabled={saving}>
        <label>预设名称<input value={draft.label} maxLength={100} required onChange={event => setDraft({ ...draft, label: event.target.value })} /></label>
        <label>说明<textarea value={draft.description} rows={2} maxLength={1000} onChange={event => setDraft({ ...draft, description: event.target.value })} /></label>
        <fieldset className="flow-preset-choices"><legend>执行步骤</legend>{PIPELINE_STAGE_IDS.map(stage => <label key={stage}><input type="checkbox" checked={draft.stages.includes(stage)} onChange={event => setDraft({ ...draft,
          stages: PIPELINE_STAGE_IDS.filter(id => id === stage ? event.target.checked : draft.stages.includes(id)),
          outputs: event.target.checked ? draft.outputs : draft.outputs.filter(id => id !== stage) })} />{PIPELINE_STAGE_LABELS[stage]}</label>)}</fieldset>
        <fieldset className="flow-preset-choices"><legend>产出</legend>{draft.stages.map(stage => <label key={stage}><input type="checkbox" checked={draft.outputs.includes(stage)} onChange={event => setDraft({ ...draft, outputs: event.target.checked ? [...draft.outputs, stage] : draft.outputs.filter(id => id !== stage) })} />{PIPELINE_STAGE_LABELS[stage as PipelineStageId]}</label>)}</fieldset>
        <p className="flow-preset-scope">只保存选中的步骤与产出；缺素材时工作台会提示，不会自动补跑其他步骤。</p>
        {saveError && <p role="alert">{saveError}</p>}
        <div className="flow-preset-buttons"><button type="submit" disabled={!draft.label.trim() || !draft.stages.length || !draft.outputs.length}>保存自定义预设</button><button type="button" onClick={() => { setDraft(null); setSaveError('') }}>取消编辑</button></div>
      </fieldset>
    </form>}
    <div className="flow-preset-list">{presets.map(item => <article key={item.id}>
      <div className="flow-preset-title"><h3>{item.label}</h3><span>{item.builtin ? '内置 · 只读' : `自定义 · r${item.revision}`}</span></div>
      <p>{item.description}</p>
      <p>步骤：{item.stages.map(stage => PIPELINE_STAGE_LABELS[stage as PipelineStageId] || stage).join(' → ')}</p>
      <p>产出：{item.outputs?.map(stage => PIPELINE_STAGE_LABELS[stage as PipelineStageId] || stage).join('、') || '未定义'}</p>
      {!isUsableFlowPreset(item) && <p role="alert">此预设缺少有效步骤或产出，请确认后端版本并重新加载目录。</p>}
      <div className="flow-preset-buttons"><button type="button" disabled={saving || !isUsableFlowPreset(item)} onClick={() => open(item, true)}>复制“{item.label}”</button>{!item.builtin && <button type="button" disabled={saving || !isUsableFlowPreset(item)} onClick={() => open(item, false)}>编辑“{item.label}”</button>}</div>
    </article>)}</div>
    {!loading && !error && !presets.length && <p>暂无流程预设。</p>}
  </section>
}
