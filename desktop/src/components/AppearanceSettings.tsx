import { useEffect, useRef, useState } from 'react'
import { prepareBackground, useAppearanceStore, type ThemeMode } from '@/stores/appearanceStore'
import { useI18n } from '@/i18n'
import './AppearanceSettings.css'

const THEME_OPTIONS: Array<{ id: ThemeMode; icon: string; label: string; desc: string }> = [
  { id: 'light', icon: '☀', label: '浅色', desc: '清爽明亮的日间工作室风格' },
  { id: 'dark', icon: '☾', label: '深色', desc: '低眩光暗色面板，适合长时间精修' },
  { id: 'system', icon: '◐', label: '跟随系统', desc: '自动匹配操作系统深浅色' },
  { id: 'custom', icon: '✦', label: '自定义', desc: '自由搭配明暗基底与强调色' },
]

const ACCENT_SWATCHES: Array<{ name: string; color: string }> = [
  { name: '冰海青', color: '#117f8d' },
  { name: '深空蓝', color: '#2563eb' },
  { name: '星云紫', color: '#7c3aed' },
  { name: '森林绿', color: '#15803d' },
  { name: '琥珀橙', color: '#d97706' },
  { name: '玫瑰粉', color: '#db2777' },
]

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
    <section className="appearance-card appearance-card--theme">
      <div>
        <h3>{t('主题与配色')}</h3>
        <p>{t('切换浅色、深色、跟随系统，或在自定义模式中自由组合基底与强调色。')}</p>
      </div>
      <div className="appearance-theme-grid" role="radiogroup" aria-label={t('主题模式')}>
        {THEME_OPTIONS.map(option => (
          <button
            key={option.id}
            type="button"
            className={`appearance-theme-option${appearance.theme === option.id ? ' is-active' : ''}`}
            aria-pressed={appearance.theme === option.id}
            onClick={() => setSaved(appearance.setPreferences({ theme: option.id }))}
          >
            <span className="appearance-theme-icon" aria-hidden="true">{option.icon}</span>
            <strong>{t(option.label)}</strong>
            <small>{t(option.desc)}</small>
          </button>
        ))}
      </div>

      {appearance.theme === 'custom' && (
        <div className="appearance-custom-panel">
          <div className="appearance-custom-row">
            <span>{t('界面基底')}</span>
            <div className="appearance-surface-toggle" role="group" aria-label={t('界面基底')}>
              <button
                type="button"
                aria-pressed={appearance.customSurface === 'light'}
                onClick={() => setSaved(appearance.setPreferences({ customSurface: 'light' }))}
              >
                {t('浅色基底')}
              </button>
              <button
                type="button"
                aria-pressed={appearance.customSurface === 'dark'}
                onClick={() => setSaved(appearance.setPreferences({ customSurface: 'dark' }))}
              >
                {t('深色基底')}
              </button>
            </div>
          </div>

          <div className="appearance-custom-row">
            <span>{t('主强调色')}</span>
            <div className="appearance-swatches">
              {ACCENT_SWATCHES.map(swatch => (
                <button
                  key={swatch.color}
                  type="button"
                  className={`appearance-swatch${appearance.accentColor.toLowerCase() === swatch.color ? ' is-active' : ''}`}
                  style={{ '--swatch': swatch.color } as React.CSSProperties}
                  title={t(swatch.name)}
                  aria-label={t(swatch.name)}
                  aria-pressed={appearance.accentColor.toLowerCase() === swatch.color}
                  onClick={() => setSaved(appearance.setPreferences({ accentColor: swatch.color }))}
                />
              ))}
              <label className="appearance-color-picker" title={t('自定义取色')}>
                <input
                  type="color"
                  aria-label={t('自定义强调色')}
                  value={appearance.accentColor}
                  onChange={event => setSaved(appearance.setPreferences({ accentColor: event.target.value }))}
                />
                <span>{appearance.accentColor.toUpperCase()}</span>
              </label>
            </div>
          </div>
        </div>
      )}
    </section>

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
        <div className="appearance-preview__sample"><span>ASMR Helper</span><strong>{t('创作台')}</strong><span>{t('本机图片副本 · 不上传')}</span></div>
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
