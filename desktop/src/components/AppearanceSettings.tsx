import { useEffect, useRef, useState } from 'react'
import { prepareBackground, useAppearanceStore } from '@/stores/appearanceStore'
import { useI18n } from '@/i18n'
import './AppearanceSettings.css'

export default function AppearanceSettings() {
  const t = useI18n()
  const appearance = useAppearanceStore()
  const input = useRef<HTMLInputElement>(null)
  const mounted = useRef(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  async function choose(file?: File) {
    if (!file || busy) return
    setBusy(true); setError(''); setSaved(false)
    try {
      const background = await prepareBackground(file)
      if (mounted.current) setSaved(appearance.setBackground(background))
    } catch { if (mounted.current) setError('invalidImage') }
    finally { if (mounted.current) setBusy(false) }
  }
  return <div className="appearance-settings">
    <section className="appearance-card">
      <div><h3>{t('界面语言')}</h3><p>{t('仅切换界面文案，素材、音色与模板名称保持原样。')}</p></div>
      <select aria-label={t('界面语言')} value={appearance.language} onChange={event => setSaved(appearance.setPreferences({ language: event.target.value === 'en' ? 'en' : 'zh-CN' }))}>
        <option value="zh-CN">简体中文</option><option value="en">English</option>
      </select>
    </section>
    <section className="appearance-card appearance-card--background">
      <div><h3>{t('背景图片')}</h3><p>{t('PNG、JPG 或 WebP，最大 20 MB。保存优化后的本机副本。')}</p></div>
      <div className="appearance-preview" style={appearance.background ? { backgroundImage: `url("${appearance.background.data}")` } : undefined}>
        <div className="appearance-preview__veil" style={{ opacity: appearance.overlay }} />
        <div className="appearance-preview__sample"><span>ASMR Helper</span><strong>{t('工作台')}</strong><span>{t('本机图片副本 · 不上传')}</span></div>
      </div>
      <div className="appearance-background-actions"><span className="appearance-filename" title={appearance.background?.name}>{appearance.background?.name || t('默认背景')}</span>
        <div><button className="settings-button" disabled={busy} onClick={() => input.current?.click()}>{t(busy ? '正在处理图片…' : appearance.background ? '替换图片' : '选择图片')}</button>
        <button className="settings-button quiet" disabled={busy || (!appearance.background && !appearance.issue)} onClick={() => { setError(''); setSaved(appearance.setBackground(null)) }}>{t('恢复默认')}</button></div>
      </div>
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={event => { void choose(event.target.files?.[0]); event.target.value = '' }} />
      <label className="appearance-overlay" htmlFor="background-overlay"><span>{t('背景遮罩')}</span><output>{Math.round(appearance.overlay * 100)}%</output></label>
      <input id="background-overlay" type="range" min="72" max="94" step="1" value={Math.round(appearance.overlay * 100)} onChange={event => setSaved(appearance.setPreferences({ overlay: Number(event.target.value) / 100 }))} />
      <div className="appearance-range-labels"><span>{t('更鲜明')}</span><span>{t('更清晰')}</span></div>
    </section>
    {(error || appearance.issue) ? <p className="settings-status error" role="alert">{t(error || appearance.issue)}</p> : <p className="appearance-saved" role="status">{saved ? `✓ ${t('已保存')}` : ''}</p>}
  </div>
}
