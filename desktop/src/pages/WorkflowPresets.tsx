import { t, format, useI18n } from '@/i18n'
import { confirmAction } from '@/utils/confirmAction'
import { useEffect, useRef, useState } from 'react'
import { useSpeechPresetHandoffStore } from '@/stores/speechPresetHandoffStore'
import type { GraphPresetItem, PresetItem } from '@/api/types'
import WorkflowEditor from '@/components/workflow/WorkflowEditor'
import GraphNodeParameters from '@/components/workflow/GraphNodeParameters'
import { editorDirty, newGraphNode } from '@/domain/workflowDraft'
import { validateGraph } from '@/domain/workflowGraph'
import { useNavStore } from '@/stores/navStore'
import { presetDeleteConfirmation, useWorkflowStore } from '@/stores/workflowStore'
import './WorkflowPresets.css'

const presetKind = (preset: PresetItem | GraphPresetItem) => `${'graph' in preset ? t('节点') : t('旧版')} · ${preset.builtin ? t('内置') : t('自定义')}`

export default function WorkflowPresets() {
  useI18n()
  const workflow = useWorkflowStore()
  const { catalog, catalogLoading, catalogError, catalogNotice, builtinTemplates, templatesLoading, templatesError, editor, saving, error } = workflow
  const [catalogId, setCatalogId] = useState(editor?.preset?.id || '')
  const [opening, setOpening] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [addingTemplateId, setAddingTemplateId] = useState<string | null>(null)
  const [templateNames, setTemplateNames] = useState<Record<string, string>>({})
  const [templateErrors, setTemplateErrors] = useState<Record<string, string>>({})
  const [templateNotice, setTemplateNotice] = useState('')
  const [notice, setNotice] = useState('')
  const openingRef = useRef(false)
  const mutationRef = useRef(false)
  const current = useRef({ editor, saving })
  current.current = { editor, saving }
  const issues = editor ? validateGraph(editor.graph) : []
  const dirty = !!editor && editorDirty(editor)
  const busy = saving || opening || deletingId !== null || addingTemplateId !== null || catalogLoading
  const saveReason = !editor ? '' : !editor.label.trim() ? '请填写流水线名称后保存。'
    : issues.length ? `请先处理 ${issues.length} 项结构问题：${t(issues[0]!.message)}` : ''

  useEffect(() => {
    const store = useWorkflowStore.getState()
    void store.loadCatalog()
    void store.loadBuiltinTemplates()
  }, [])
  useEffect(() => {
    const guard = async () => {
      if (current.current.saving || openingRef.current || mutationRef.current) {
        setNotice('正在处理预设，请稍候再离开。')
        return false
      }
      if (useSpeechPresetHandoffStore.getState().navigating) return true
      if (current.current.editor && editorDirty(current.current.editor)
          && !await confirmAction(t('流水线有未保存的修改。离开后将放弃这些修改，工作台素材草稿会保留。继续离开？'))) return false
      useWorkflowStore.getState().closeEditor()
      return true
    }
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (current.current.saving || mutationRef.current || current.current.editor && editorDirty(current.current.editor)) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    useNavStore.getState().setNavigationGuard(guard)
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      if (useNavStore.getState().navigationGuard === guard) useNavStore.getState().setNavigationGuard(null)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [])
  useEffect(() => { setCatalogId(editor?.preset?.id || '') }, [editor?.preset?.id])

  async function openPreset(create = false) {
    if (busy || openingRef.current) return
    const item = catalog.find(preset => preset.id === catalogId)
    if (!create && !item) return
    const returnTo = editor?.returnTo || 'settings'
    if (!(await useNavStore.getState().confirmLeaveCurrentPage())) return
    setNotice('')
    if (create || item && 'graph' in item) {
      if (create) setCatalogId('')
      workflow.openEditor(create ? null : item && 'graph' in item ? item : null, returnTo)
      return
    }
    if (!item) return
    openingRef.current = true
    setOpening(true)
    try { await workflow.openLegacyEditor(item, returnTo) }
    finally { openingRef.current = false; setOpening(false) }
  }
  async function save(mode: 'update' | 'copy') {
    if (!editor || saving || openingRef.current) return
    const returnTo = editor.returnTo
    const result = await workflow.saveEditor(mode)
    if (!result) return
    useNavStore.getState().setNavigationGuard(null)
    useWorkflowStore.getState().closeEditor()
    useNavStore.getState().setPage(returnTo)
  }
  function goBack() {
    setNotice('')
    useNavStore.getState().setPage(editor?.returnTo || 'settings')
  }
  const selected = catalog.find(preset => preset.id === catalogId)
  async function deletePreset(preset: PresetItem | GraphPresetItem) {
    if (busy || mutationRef.current) return
    if (!await confirmAction(t(presetDeleteConfirmation(preset)))) return
    mutationRef.current = true; setDeletingId(preset.id); setNotice(''); setTemplateNotice('')
    setTemplateErrors(current => ({ ...current, [preset.id]: '' }))
    try {
      const result = await workflow.deleteCatalogPreset(preset)
      if (result) {
        setCatalogId(current => current === preset.id ? '' : current)
      } else {
        const reason = useWorkflowStore.getState().error || '请刷新目录后重试'
        setTemplateErrors(current => ({ ...current, [preset.id]: `删除未完成：${t(reason)}` }))
      }
    } finally { mutationRef.current = false; setDeletingId(null) }
  }
  async function addTemplate(preset: PresetItem | GraphPresetItem) {
    if (busy || mutationRef.current) return
    const label = (templateNames[preset.id] ?? preset.label).trim()
    if (!label) { setTemplateErrors(current => ({ ...current, [preset.id]: '请填写新预设名称。' })); return }
    mutationRef.current = true; setAddingTemplateId(preset.id); setNotice(''); setTemplateNotice('')
    setTemplateErrors(current => ({ ...current, [preset.id]: '' }))
    try {
      const restored = await workflow.addBuiltinTemplate(preset.id, preset.revision, label === preset.label ? undefined : label)
      if (restored) {
        const message = `已添加“${restored.label}”，可在目录中选择并打开。`
        setNotice(message); setTemplateNotice(message)
        setTemplateErrors(current => { const next = { ...current }; delete next[preset.id]; return next })
      } else {
        const reason = useWorkflowStore.getState().error || '请检查目录状态后重试'
        setTemplateErrors(current => ({ ...current, [preset.id]: `添加未完成：${t(reason)}` }))
      }
    } catch (reason) {
      setTemplateErrors(current => ({ ...current, [preset.id]: `添加未完成：${reason instanceof Error ? reason.message : String(reason)}` }))
    } finally { mutationRef.current = false; setAddingTemplateId(null) }
  }

  return <div className="workflow-presets">
    <header className="wfp-header page-heading">
      <div className="page-heading__copy"><h1 className="page-title">{editor ? editor.preset ? t("编辑流水线") : t("新建流水线") : t("流水线编辑器")}</h1>
        <p className="wfp-description page-description">{t("编辑处理步骤，保存后在工作台运行。")}</p></div>
      <div className="wfp-actions page-heading__actions">
        {editor?.preset && !editor.preset.builtin && <button type="button" className="wfp-button" disabled={busy || !!saveReason} title={saveReason ? t(saveReason) : undefined} onClick={() => void save('copy')}>{t("另存为新预设")}</button>}
        {editor && <button type="button" className="wfp-button is-primary" disabled={busy || !!saveReason} title={saveReason ? t(saveReason) : undefined} aria-describedby={saveReason ? 'wfp-save-reason' : undefined} onClick={() => void save(editor.preset && !editor.preset.builtin ? 'update' : 'copy')}>{saving && !deletingId && !addingTemplateId ? t("正在保存…") : editor.preset?.builtin ? t("保存副本并返回") : t("保存并返回")}</button>}
        <button type="button" className="wfp-button" disabled={busy} onClick={goBack}>{t("返回")}{editor?.returnTo === 'workbench' ? t("工作台") : t("设置")}</button>
      </div>
    </header>
    <section className="wfp-catalog" aria-label={t("选择要编辑的流水线")}>
      <label><span>{t("已保存流水线")}</span><select aria-label={t("已保存流水线")} value={catalogId} disabled={busy || catalogLoading} onChange={event => setCatalogId(event.target.value)}>
        <option value="">{catalogLoading ? t("正在读取目录…") : catalog.length ? t("选择流水线") : t("活动目录为空，可新建或添加模板")}</option>
        {catalog.map(preset => <option key={preset.id} value={preset.id}>{preset.label} · {presetKind(preset)}</option>)}
      </select></label>
      <button type="button" className="wfp-button" disabled={busy || !selected} onClick={() => void openPreset()}>{opening ? t("正在转换…") : selected && !('graph' in selected) ? t("转换为节点草稿") : t("打开编辑")}</button>
      <button type="button" className="wfp-button" disabled={busy} onClick={() => void openPreset(true)}>{t("新建流水线")}</button>
      {selected && <button type="button" className="wfp-button is-danger" disabled={busy} title={t("删除此预设；当前草稿与已提交任务保留，重启不会重新出现。")} onClick={() => void deletePreset(selected)}>{deletingId === selected.id ? t("正在删除…") : t("删除")}</button>}
      <div className="wfp-archive-anchor">
        <button type="button" className="wfp-button" aria-expanded={templatesOpen} aria-controls="wfp-archive-panel" onClick={() => setTemplatesOpen(value => !value)}>{t("添加内置模板")}{templatesLoading ? ' …' : ` · ${builtinTemplates.length}`}</button>
        {templatesOpen && <section id="wfp-archive-panel" className="wfp-archive-panel" aria-label={t("添加内置模板")} onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setTemplatesOpen(false) } }}>
          <header><div><strong>{t("添加内置模板")}</strong><p>{t("每次添加都会新建独立预设。")}</p></div><div className="wfp-archive-header-actions"><button type="button" className="wfp-button" disabled={busy || templatesLoading} onClick={() => { void Promise.all([workflow.loadCatalog(), workflow.loadBuiltinTemplates()]) }}>{t("刷新目录")}</button><button type="button" className="wfp-archive-close" aria-label={t("收起添加内置模板")} onClick={() => setTemplatesOpen(false)}>×</button></div></header>
          {templateNotice && <p className="wfp-archive-feedback" role="status">{t(templateNotice)}</p>}
          <div className="wfp-archive-scroll" role="region" aria-label={t("内置模板列表")} tabIndex={0}>
            {templatesLoading && <p className="wfp-archive-message" role="status">{t("正在读取内置模板…")}</p>}
            {templatesError && <div className="wfp-archive-message" role="alert">{t("读取失败：")}{templatesError}<button type="button" className="wfp-button" disabled={templatesLoading || busy} onClick={() => void workflow.loadBuiltinTemplates()}>{t("重试")}</button></div>}
            {!templatesLoading && !templatesError && !builtinTemplates.length && <p className="wfp-archive-message">{t("没有可添加的内置模板。可从当前目录打开，或新建流水线。")}</p>}
            {builtinTemplates.map(preset => <article className="wfp-archive-item" key={preset.id}>
              <div className="wfp-archive-item-title"><strong>{preset.label}</strong><span>{presetKind(preset)}</span></div>
              <div className="wfp-archive-restore"><label><span>{t("新预设名称")}</span><input aria-label={format("{0} 新预设名称", [preset.label])} value={templateNames[preset.id] ?? preset.label} maxLength={100} disabled={busy} onChange={event => setTemplateNames(current => ({ ...current, [preset.id]: event.target.value }))} /></label><button type="button" className="wfp-button" disabled={busy || !(templateNames[preset.id] ?? preset.label).trim()} aria-label={format("添加 {0} 到目录", [preset.label])} onClick={() => void addTemplate(preset)}>{addingTemplateId === preset.id ? t("正在添加…") : t("添加到目录")}</button></div>
              {templateErrors[preset.id] && <p className="wfp-restore-error" role="alert">{t(templateErrors[preset.id] || '')}</p>}
            </article>)}
          </div>
        </section>}
      </div>
      {selected?.builtin && <span className="wfp-catalog-hint">{t("修改内置结构时需另存副本。")}</span>}
    </section>
    {(catalogError || catalogNotice || notice || error || saveReason) && <div className="wfp-alerts">
      {catalogError && <div className="wfp-alert" role="alert">{t("目录读取失败：")}{t(catalogError)} <button type="button" disabled={catalogLoading || busy} onClick={() => void workflow.loadCatalog()}>{t("重试")}</button></div>}
      {catalogNotice && <p className="wfp-alert" role="status">{t(catalogNotice)}</p>}
      {notice && (!templatesOpen || notice !== templateNotice) && <p className="wfp-alert wfp-feedback" role="status">{t(notice)}</p>}
      {error && <p className="wfp-alert" role="alert">{t(error)}</p>}
      {saveReason && <p id="wfp-save-reason" className="wfp-alert" role="status">{t(saveReason)}</p>}
    </div>}
    {!editor ? <section className="wfp-empty"><h2>{catalog.length ? t("选择预设继续编辑") : t("还没有流水线")}</h2><p>{catalog.length ? t("选择已保存流水线，或新建一个。") : t("从空白开始，或添加内置模板。")}</p><div className="wfp-empty-actions"><button type="button" className="wfp-button is-primary" disabled={busy} onClick={() => void openPreset(true)}>{t("新建节点流水线")}</button><button type="button" className="wfp-button" onClick={() => setTemplatesOpen(true)}>{t("添加内置模板")}</button></div></section> : <>
      <fieldset className="wfp-editable" disabled={busy}>
        <div className="wfp-metadata">
          <label><span>{t("名称")}</span><input aria-label={t("流水线名称")} maxLength={100} value={editor.label} onChange={event => workflow.updateEditor({ label: event.target.value })} placeholder={t("例如：字幕翻译后配音")} /></label>
          <label><span>{t("说明")}</span><input aria-label={t("流水线说明")} maxLength={1000} value={editor.description} onChange={event => workflow.updateEditor({ description: event.target.value })} placeholder={t("说明用途和需要的输入")} /></label>
          <p className="wfp-edit-state">{editor.preset?.builtin ? t("内置预设 · 保存为副本") : editor.preset ? format("自定义预设 · 修订 {0}", [editor.preset.revision]) : t("新预设")}<span>{dirty ? t("有未保存修改") : editor.preset ? t("尚未修改") : t("尚未保存")}</span></p>
        </div>
        {!!editor.warnings?.length && <div className="wfp-conversion" role="status"><strong>{t("旧版转换说明")}</strong>{editor.warnings.map((warning, index) => <p key={index}>{t(warning)}</p>)}<p>{t("请确认输入槽和连线。转换草稿会另存，原流程保持不变。")}</p></div>}
        <WorkflowEditor key={`${editor.preset?.id || 'new'}:${editor.initialFingerprint}`} templateMode graph={editor.graph} bindings={{}} materials={[]} issues={issues.map(issue => ({ message: `${issue.node_id ? `${issue.node_id}：` : ''}${t(issue.message)}`, nodeId: issue.node_id }))}
          onChange={graph => workflow.updateEditor({ graph })} onBindingsChange={() => {}} createNode={newGraphNode}
          renderParameters={(node, onChange) => <GraphNodeParameters node={node} onChange={onChange} disabled={busy} allowStructureChanges />} />
      </fieldset>
    </>}
  </div>
}
