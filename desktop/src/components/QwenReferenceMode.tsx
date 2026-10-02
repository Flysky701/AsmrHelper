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
      ? '仍需参考音频，仅提取说话人特征，不使用参考原文；克隆质量可能降低。切换不会删除原文。'
      : '使用参考音频及其准确原文。跨语言配音也应保留录音原语言的转录，不要替换成译文。'}</p>
  </div>
}
