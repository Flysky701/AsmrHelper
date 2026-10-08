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

const presetKind = (preset: PresetItem | GraphPresetItem) => `${'graph' in preset ? '节点' : '旧版'} · ${preset.builtin ? '内置' : '自定义'}`

export default function WorkflowPresets() {
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
    : issues.length ? `请先处理 ${issues.length} 项结构问题：${issues[0]!.message}` : ''

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
          && !await confirmAction('流水线有未保存的修改。离开后将放弃这些修改，工作台素材草稿会保留。继续离开？')) return false
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
    if (!await confirmAction(presetDeleteConfirmation(preset))) return
    mutationRef.current = true; setDeletingId(preset.id); setNotice(''); setTemplateNotice('')
    setTemplateErrors(current => ({ ...current, [preset.id]: '' }))
    try {
      const result = await workflow.deleteCatalogPreset(preset)
      if (result) {
        setCatalogId(current => current === preset.id ? '' : current)
        const message = result === 'already_missing' ? `“${preset.label}”已不存在，目录引用已清除。当前草稿与已提交任务保留。`
          : `预设“${preset.label}”已删除，重启不会重新出现。当前草稿、运行参数和素材绑定保留，已提交任务不受影响。`
        setNotice(message); setTemplateNotice(message)
      } else {
        const reason = useWorkflowStore.getState().error || '请刷新目录后重试'
        setTemplateErrors(current => ({ ...current, [preset.id]: `删除未完成：${reason}` }))
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
        const message = `“${restored.label}”已作为新预设加入目录，尚未打开。当前编辑草稿未改变；请自行选择后打开。`
        setNotice(message); setTemplateNotice(message)
        setTemplateErrors(current => { const next = { ...current }; delete next[preset.id]; return next })
      } else {
        const reason = useWorkflowStore.getState().error || '请检查目录状态后重试'
        setTemplateErrors(current => ({ ...current, [preset.id]: `添加未完成：${reason}。若目录已有同名预设，请修改新预设名称后重试，不会覆盖现有预设。` }))
      }
    } catch (reason) {
      setTemplateErrors(current => ({ ...current, [preset.id]: `添加未完成：${reason instanceof Error ? reason.message : String(reason)}。若名称冲突，请修改名称后重试，不会覆盖现有预设。` }))
    } finally { mutationRef.current = false; setAddingTemplateId(null) }
  }

  return <div className="workflow-presets">
    <header className="wfp-header page-heading">
      <div className="page-heading__copy"><h1 className="page-title">{editor ? editor.preset ? '编辑流水线' : '新建流水线' : '流水线编辑器'}</h1>
        <p className="wfp-description page-description">在这里定义可复用的结构。工作台负责选择流水线、绑定素材与调整本次运行参数。</p></div>
      <div className="wfp-actions page-heading__actions">
        {editor?.preset && !editor.preset.builtin && <button type="button" className="wfp-button" disabled={busy || !!saveReason} title={saveReason || undefined} onClick={() => void save('copy')}>另存为新预设</button>}
        {editor && <button type="button" className="wfp-button is-primary" disabled={busy || !!saveReason} title={saveReason || undefined} aria-describedby={saveReason ? 'wfp-save-reason' : undefined} onClick={() => void save(editor.preset && !editor.preset.builtin ? 'update' : 'copy')}>{saving && !deletingId && !addingTemplateId ? '正在保存…' : editor.preset?.builtin ? '保存副本并返回' : '保存并返回'}</button>}
        <button type="button" className="wfp-button" disabled={busy} onClick={goBack}>返回{editor?.returnTo === 'workbench' ? '工作台' : '设置'}</button>
      </div>
    </header>
    <section className="wfp-catalog" aria-label="选择要编辑的流水线">
      <label><span>已保存流水线</span><select aria-label="已保存流水线" value={catalogId} disabled={busy || catalogLoading} onChange={event => setCatalogId(event.target.value)}>
        <option value="">{catalogLoading ? '正在读取目录…' : catalog.length ? '选择流水线' : '活动目录为空，可新建或添加模板'}</option>
        {catalog.map(preset => <option key={preset.id} value={preset.id}>{preset.label} · {presetKind(preset)}</option>)}
      </select></label>
      <button type="button" className="wfp-button" disabled={busy || !selected} onClick={() => void openPreset()}>{opening ? '正在转换…' : selected && !('graph' in selected) ? '转换为节点草稿' : '打开编辑'}</button>
      <button type="button" className="wfp-button" disabled={busy} onClick={() => void openPreset(true)}>新建流水线</button>
      {selected && <button type="button" className="wfp-button is-danger" disabled={busy} title={'删除此预设；当前草稿与已提交任务保留，重启不会重新出现。'} onClick={() => void deletePreset(selected)}>{deletingId === selected.id ? '正在删除…' : '删除'}</button>}
      <div className="wfp-archive-anchor">
        <button type="button" className="wfp-button" aria-expanded={templatesOpen} aria-controls="wfp-archive-panel" onClick={() => setTemplatesOpen(value => !value)}>添加内置模板{templatesLoading ? ' …' : ` · ${builtinTemplates.length}`}</button>
        {templatesOpen && <section id="wfp-archive-panel" className="wfp-archive-panel" aria-label="添加内置模板" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setTemplatesOpen(false) } }}>
          <header><div><strong>添加内置模板</strong><p>选择出厂模板新建独立预设，不恢复以前删除的记录。</p></div><div className="wfp-archive-header-actions"><button type="button" className="wfp-button" disabled={busy || templatesLoading} onClick={() => { void Promise.all([workflow.loadCatalog(), workflow.loadBuiltinTemplates()]) }}>刷新目录</button><button type="button" className="wfp-archive-close" aria-label="收起添加内置模板" onClick={() => setTemplatesOpen(false)}>×</button></div></header>
          {templateNotice && <p className="wfp-archive-feedback" role="status">{templateNotice}</p>}
          <div className="wfp-archive-scroll" role="region" aria-label="内置模板列表" tabIndex={0}>
            {templatesLoading && <p className="wfp-archive-message" role="status">正在读取内置模板…</p>}
            {templatesError && <div className="wfp-archive-message" role="alert">读取失败：{templatesError}<button type="button" className="wfp-button" disabled={templatesLoading || busy} onClick={() => void workflow.loadBuiltinTemplates()}>重试</button></div>}
            {!templatesLoading && !templatesError && !builtinTemplates.length && <p className="wfp-archive-message">没有可添加的内置模板。可从当前目录打开，或新建流水线。</p>}
            {builtinTemplates.map(preset => <article className="wfp-archive-item" key={preset.id}>
              <div className="wfp-archive-item-title"><strong>{preset.label}</strong><span>{presetKind(preset)}</span></div>
              <div className="wfp-archive-restore"><label><span>新预设名称</span><input aria-label={`${preset.label} 新预设名称`} value={templateNames[preset.id] ?? preset.label} maxLength={100} disabled={busy} onChange={event => setTemplateNames(current => ({ ...current, [preset.id]: event.target.value }))} /></label><button type="button" className="wfp-button" disabled={busy || !(templateNames[preset.id] ?? preset.label).trim()} aria-label={`添加 ${preset.label} 到目录`} onClick={() => void addTemplate(preset)}>{addingTemplateId === preset.id ? '正在添加…' : '添加到目录'}</button></div>
              {templateErrors[preset.id] && <p className="wfp-restore-error" role="alert">{templateErrors[preset.id]}</p>}
            </article>)}
          </div>
        </section>}
      </div>
      {selected?.builtin && <span className="wfp-catalog-hint">修改内置结构时需另存副本。</span>}
    </section>
    {(catalogError || catalogNotice || notice || error || saveReason) && <div className="wfp-alerts">
      {catalogError && <div className="wfp-alert" role="alert">目录读取失败：{catalogError} <button type="button" disabled={catalogLoading || busy} onClick={() => void workflow.loadCatalog()}>重试</button></div>}
      {catalogNotice && <p className="wfp-alert" role="status">{catalogNotice}</p>}
      {notice && <p className="wfp-alert" role="status">{notice}</p>}
      {error && <p className="wfp-alert" role="alert">{error} 当前草稿已保留；可调整后重试，或另存为新预设。</p>}
      {saveReason && <p id="wfp-save-reason" className="wfp-alert" role="status">{saveReason}</p>}
    </div>}
    {!editor ? <section className="wfp-empty"><h2>{catalog.length ? '选择预设继续编辑' : '活动目录为空'}</h2><p>{catalog.length ? '选择一个已保存流水线，或从空白开始添加模块。' : '可以新建流水线，或添加内置模板创建新预设，之后自行选择打开。'}旧版流程需显式转换，原定义会保留。</p><div className="wfp-empty-actions"><button type="button" className="wfp-button is-primary" disabled={busy} onClick={() => void openPreset(true)}>新建节点流水线</button><button type="button" className="wfp-button" onClick={() => setTemplatesOpen(true)}>添加内置模板</button></div></section> : <>
      <fieldset className="wfp-editable" disabled={busy}>
        <div className="wfp-metadata">
          <label><span>名称</span><input aria-label="流水线名称" maxLength={100} value={editor.label} onChange={event => workflow.updateEditor({ label: event.target.value })} placeholder="例如：字幕翻译后配音" /></label>
          <label><span>说明</span><input aria-label="流水线说明" maxLength={1000} value={editor.description} onChange={event => workflow.updateEditor({ description: event.target.value })} placeholder="说明用途和需要的输入" /></label>
          <p className="wfp-edit-state">{editor.preset?.builtin ? '内置预设 · 保存为副本' : editor.preset ? `自定义预设 · 修订 ${editor.preset.revision}` : '新预设'}<span>{dirty ? '有未保存修改' : editor.preset ? '尚未修改' : '尚未保存'}</span></p>
        </div>
        {!!editor.warnings?.length && <div className="wfp-conversion" role="status"><strong>旧版转换说明</strong>{editor.warnings.map((warning, index) => <p key={index}>{warning}</p>)}<p>请确认输入槽和连线。转换草稿会另存，原流程保持不变。</p></div>}
        <WorkflowEditor key={`${editor.preset?.id || 'new'}:${editor.initialFingerprint}`} templateMode graph={editor.graph} bindings={{}} materials={[]} issues={issues.map(issue => ({ message: `${issue.node_id ? `${issue.node_id}：` : ''}${issue.message}`, nodeId: issue.node_id }))}
          onChange={graph => workflow.updateEditor({ graph })} onBindingsChange={() => {}} createNode={newGraphNode}
          renderParameters={(node, onChange) => <GraphNodeParameters node={node} onChange={onChange} disabled={busy} />} />
      </fieldset>
      <footer className="wfp-footer"><p>保存仅更新预设，不会执行流水线。实际素材、声音与引擎可用性在工作台检查。</p></footer>
    </>}
  </div>
}
