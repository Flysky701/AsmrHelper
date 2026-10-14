import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import HelpMarkdown from './HelpMarkdown'
import { useI18n } from '@/i18n'
import { AUDITION_EXAMPLE, PAGE_HELP, resolveHelpDocument, SERVICE_ADDRESSES, VOICE_STARTERS } from '@/domain/pageHelp'
import type { PageHelpTopic } from '@/domain/pageHelp'
import { usePageHelpStore } from '@/stores/pageHelpStore'
import './QuickStartHelp.css'

export default function QuickStartHelp({ topic = 'workbench' }: { topic?: PageHelpTopic }) {
  const t = useI18n()
  const open = usePageHelpStore(state => state.openTopic === topic)
  const trigger = useRef<HTMLButtonElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const copyGeneration = useRef(0)
  const documentArea = useRef<HTMLDivElement>(null)
  const documentNavigation = useRef(false)
  const [copyStatus, setCopyStatus] = useState('')
  const content = PAGE_HELP[topic]
  const [documentReference, setDocumentReference] = useState<string | null>(null)
  const guide = resolveHelpDocument(documentReference || content.document)

  useEffect(() => {
    if (!open || !documentNavigation.current) return
    documentNavigation.current = false
    documentArea.current?.focus()
    documentArea.current?.scrollIntoView({ block: 'start' })
  }, [documentReference, open])

  const close = () => {
    copyGeneration.current++
    usePageHelpStore.getState().dismiss(topic)
    trigger.current?.focus()
  }
  useEffect(() => () => {
    copyGeneration.current++
    usePageHelpStore.getState().dismiss(topic)
  }, [topic])
  useEffect(() => {
    copyGeneration.current++
    setCopyStatus('')
    documentNavigation.current = false
    setDocumentReference(null)
    if (!open) return
    closeButton.current?.focus()
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented && !event.isComposing) {
        event.preventDefault()
        close()
      }
    }
    document.addEventListener('keydown', escape)
    return () => document.removeEventListener('keydown', escape)
  }, [open, topic])

  async function copy(value: string) {
    const generation = ++copyGeneration.current
    setCopyStatus('')
    try {
      await navigator.clipboard.writeText(value)
      if (generation === copyGeneration.current) setCopyStatus('已复制')
    } catch {
      if (generation === copyGeneration.current) setCopyStatus('无法复制，请选中文本后复制。')
    }
  }
  const host = open && typeof document !== 'undefined' ? document.getElementById('page-help-host') : null
  const sample = AUDITION_EXAMPLE
  return <>
    <button ref={trigger} type="button" className="page-help-trigger" aria-label={t('本页帮助')} title={t('本页帮助')}
      aria-expanded={open} aria-controls="page-help-panel" onClick={() => {
        if (open) close()
        else usePageHelpStore.getState().toggle(topic)
      }}><span aria-hidden="true">?</span></button>
    {host && createPortal(<aside id="page-help-panel" className="page-help-panel" aria-labelledby="page-help-title">
      <header className="page-help-heading"><div><span className="page-help-eyebrow">{t('本页帮助')}</span><h2 id="page-help-title">{t(content.title)}</h2></div>
        <button ref={closeButton} type="button" className="page-help-close" aria-label={t('关闭帮助')} onClick={close}><span aria-hidden="true">×</span></button>
      </header>
      <div className="page-help-body">
        <div className="page-help-steps">{content.steps.map(step => <section key={step.title}><h3>{t(step.title)}</h3><p>{t(step.detail)}</p></section>)}</div>
        {topic === 'connections' && <details className="page-help-extra"><summary>{t('默认 API 地址')}</summary>
          {SERVICE_ADDRESSES.map(item => <div className="page-help-copy" key={item.label}><strong>{item.label}</strong><code>{item.value}</code><button type="button" onClick={() => void copy(item.value)} aria-label={`${t('复制')} ${item.label}`}>{t('复制')}</button></div>)}
          <p className="page-help-note">{t('公开地址与示例；不包含账户密钥。')}</p>
        </details>}
        {topic === 'presets' && <details className="page-help-extra"><summary>{t('声音起步选项')}</summary>
          {VOICE_STARTERS.map(item => <div className="page-help-voice" key={item.label}><strong>{item.label}</strong><code>{item.model}</code><span>{t(item.voice)}</span></div>)}
        </details>}
        {topic === 'audition' && <details className="page-help-extra"><summary>{t('短句示例')}</summary>
          <pre>{sample}</pre><button type="button" onClick={() => void copy(sample)}>{t('复制')}</button>
        </details>}
        {topic === 'audition' && <p className="page-help-note">{t('云端生成可能计费，以账户权限和额度为准。')}</p>}
        <details className="page-help-extra page-help-guide"><summary>{t('详细说明（中文）')}</summary>
          {documentReference && <button type="button" onClick={() => { documentNavigation.current = true; setDocumentReference(null); setCopyStatus('') }}>{t('返回本页说明')}</button>}
          <div ref={documentArea} tabIndex={-1} role="region" aria-label={t('详细说明（中文）')}>{guide && <HelpMarkdown source={guide.source} onDocument={href => {
            if (!resolveHelpDocument(href)) { setCopyStatus('本指南未内置该链接。'); return false }
            documentNavigation.current = true; setDocumentReference(href); setCopyStatus(''); return true
          }} />}</div>
        </details>
        <p className="page-help-copy-status" role="status" aria-live="polite">{t(copyStatus)}</p>
      </div>
    </aside>, host)}
  </>
}
