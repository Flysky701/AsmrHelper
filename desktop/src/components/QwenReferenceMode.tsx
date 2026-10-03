import { useId } from 'react'

/** Both choices map to the existing Qwen Base x_vector_only_mode option. */
export default function QwenReferenceMode({ value, onChange, disabled = false, className = 'speech-option' }: {
  value: boolean; onChange: (value: boolean) => void; disabled?: boolean; className?: string
}) {
  const id = useId()
  return <div className={className}>
    <label htmlFor={id}>参考克隆方式</label>
    <select id={id} value={String(value)} disabled={disabled} aria-describedby={id + '-hint'} onChange={event => onChange(event.target.value === 'true')}>
      <option value="false">参考音频 + 原文（默认）</option>
      <option value="true">仅声音特征（无需原文）</option>
    </select>
    <p id={id + '-hint'} className="muted">{value
      ? '需要参考音频，无需录音原文。合成文本与目标语言另设；不保证跨语言效果更好。切换保留已有原文。'
      : '需要参考音频及原文；原文须与录音内容、语言一致，不填译文。要生成的文本与目标语言另设。'}</p>
  </div>
}
