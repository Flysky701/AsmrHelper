import { t, useI18n } from '@/i18n'
import { useId } from 'react'

/** Both choices map to the existing Qwen Base x_vector_only_mode option. */
export default function QwenReferenceMode({ value, onChange, disabled = false, className = 'speech-option' }: {
  value: boolean; onChange: (value: boolean) => void; disabled?: boolean; className?: string
}) {
  useI18n()
  const id = useId()
  return <div className={className}>
    <label htmlFor={id}>{t("参考克隆方式")}</label>
    <select id={id} value={String(value)} disabled={disabled} aria-describedby={id + '-hint'} onChange={event => onChange(event.target.value === 'true')}>
      <option value="false">{t("参考音频 + 原文（默认）")}</option>
      <option value="true">{t("仅声音特征（无需原文）")}</option>
    </select>
    <p id={id + '-hint'} className="muted">{value
      ? t('需要参考音频，无需原文。')
      : t('原文须与参考录音一致，不填译文。')}</p>
  </div>
}
