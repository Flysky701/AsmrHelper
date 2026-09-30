import { useEffect, useState } from 'react'
import { pipelineApi } from '@/api/pipeline'
import type { PresetItem } from '@/api/types'
import { PIPELINE_STAGE_LABELS, type PipelineStageId } from '@/domain/pipelinePreset'
import { isUsableFlowPreset, matchingFlowPreset, type FlowDraft } from '@/domain/workbenchFlow'
import { useWorkbenchStore } from '@/stores/workbenchStore'
import './FlowPresets.css'

export default function FlowPresetPicker({ flow, disabled, onApply }: { flow: FlowDraft; disabled: boolean; onApply: (preset: PresetItem) => void }) {
  const { presets, setPresets } = useWorkbenchStore()
  const [selection, setSelection] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let active = true
    setLoading(true)
    void pipelineApi.presets().then(result => {
      if (active) { setPresets(result.presets); setError('') }
    }).catch(cause => { if (active) { setPresets([]); setError('流程预设加载失败：' + String(cause)) } })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [reload, setPresets])
  const selected = presets.find(item => item.id === selection)
  const matched = matchingFlowPreset(flow, presets)
  return <div className="flow-preset-picker">
    <label>流程预设 · 与设置共享
      <select aria-label="常用步骤预设" value={selection} disabled={disabled || loading} onChange={event => setSelection(event.target.value)}>
        <option value="">选择预设，查看将应用的内容</option>
        {presets.map(item => <option key={item.id} value={item.id}>{item.label}{item.builtin ? '' : ' · 自定义'}</option>)}
      </select>
    </label>
    {selected && <div className="flow-preset-preview">
      <p>{selected.description}</p>
      <p>步骤：{selected.stages.map(stage => PIPELINE_STAGE_LABELS[stage as PipelineStageId] || stage).join(' → ')}</p>
      <p>产出：{selected.outputs?.map(stage => PIPELINE_STAGE_LABELS[stage as PipelineStageId] || stage).join('、') || '未定义'}</p>
      <button type="button" disabled={disabled || !isUsableFlowPreset(selected)} onClick={() => onApply(selected)}>应用流程预设</button>
      {!isUsableFlowPreset(selected) && <p role="alert">预设包含不支持的步骤或产出，请在设置中核对。</p>}
    </div>}
    <p className="flow-preset-scope">只改步骤与产出，保留素材、来源绑定、音色、语言及参数，不启动任务。</p>
    <p className="flow-preset-scope" role="status">当前：{matched ? matched.label : '自定义'}（按步骤与产出匹配）</p>
    {error && <div role="alert">{error}<button type="button" disabled={disabled || loading} onClick={() => setReload(value => value + 1)}>重新加载</button></div>}
  </div>
}
