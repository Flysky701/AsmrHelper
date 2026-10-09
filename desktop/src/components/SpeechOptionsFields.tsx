import { useId } from 'react'
import type { SpeechProvider } from '@/api/speech'
import { availableSpeechOptions, speechOptionsIssue, unsupportedSpeechOptions } from '@/domain/speechAdvancedOptions'
import QwenReferenceMode from './QwenReferenceMode'
import './SpeechOptionsFields.css'

const names: Record<string, string> = { speed: '语速', temperature: '采样温度', top_p: '采样范围（top_p）', style_description: '风格描述', tag_density: '标签密度', cfg_value: '引导强度', inference_timesteps: '推理步数', instructions: '合成指令' }
export default function SpeechOptionsFields({ provider, mode, model, values, onChange, omit = [] }: {
  provider: SpeechProvider | undefined; mode: string; model: string; values: Record<string, unknown>; onChange: (values: Record<string, unknown>) => void
  omit?: string[]
}) {
  const id = useId()
  const fields = availableSpeechOptions(provider, mode, model).filter(([key]) => !omit.includes(key))
  const unknown = unsupportedSpeechOptions(provider, mode, values, model)
  const issue = speechOptionsIssue(provider, mode, values, model)
  const update = (key: string, value: unknown) => { const next = { ...values }; if (value === undefined) delete next[key]; else next[key] = value; onChange(next) }
  return <div className="speech-options-fields">
    {fields.map(([key, field]) => {
      const controlId = id + key
      const value = values[key] ?? field.default
      if (provider?.provider_id === 'qwen3' && mode === 'reference' && key === 'x_vector_only_mode') return <QwenReferenceMode key={key} value={value === true} onChange={next => update(key, next)} />
      return <div key={key} className="speech-option">
        <label htmlFor={controlId}>{field.title || names[key] || key}</label>
        {field.type === 'boolean' ? <input id={controlId} type="checkbox" checked={value === true} aria-describedby={field.description ? controlId + '-hint' : undefined} onChange={event => update(key, event.target.checked)} />
          : field.enum ? <select id={controlId} value={String(value ?? '')} onChange={event => update(key, ['number', 'integer'].includes(field.type || '') ? Number(event.target.value) : event.target.value)}>{field.enum.map(option => <option key={String(option)} value={String(option)}>{String(option)}</option>)}</select>
          : field.type === 'string' && (field.maxLength || 0) > 200 ? <textarea id={controlId} rows={3} maxLength={field.maxLength} value={String(value ?? '')} onChange={event => update(key, event.target.value || undefined)} />
          : <input id={controlId} type={['number', 'integer'].includes(field.type || '') ? 'number' : 'text'} min={field.minimum} max={field.maximum} maxLength={field.maxLength} step={field.type === 'integer' ? 1 : 'any'} value={String(value ?? '')} aria-describedby={field.description ? controlId + '-hint' : undefined}
            onChange={event => update(key, event.target.value === '' ? undefined : ['number', 'integer'].includes(field.type || '') ? Number(event.target.value) : event.target.value)} />}
        {field.description && <details className="speech-option-help"><summary>参数说明</summary><p id={controlId + '-hint'}>{field.description}</p></details>}
      </div>
    })}
    {!fields.length && <p>当前引擎没有额外可调参数。</p>}
    {issue && <p className="speech-options-issue" role="alert">{issue}</p>}
    {unknown.length > 0 && <button type="button" onClick={() => onChange(Object.fromEntries(Object.entries(values).filter(([key]) => !unknown.includes(key))))}>移除不支持的参数</button>}
  </div>
}
