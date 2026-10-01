import { useEffect, useRef, useState } from 'react'
import WorkflowEditor from '@/components/workflow/WorkflowEditor'
import GraphNodeParameters from '@/components/workflow/GraphNodeParameters'
import { editorDirty, newGraphNode } from '@/domain/workflowDraft'
import { validateGraph } from '@/domain/workflowGraph'
import { useNavStore } from '@/stores/navStore'
import { useWorkflowStore } from '@/stores/workflowStore'
import './WorkflowPresets.css'

export default function WorkflowPresets() {
  const workflow = useWorkflowStore()
  const { catalog, catalogLoading, catalogError, editor, saving, error } = workflow
  const [catalogId, setCatalogId] = useState(editor?.preset?.id || '')
  const [opening, setOpening] = useState(false)
  const [notice, setNotice] = useState('')
  const openingRef = useRef(false)
  const current = useRef({ editor, saving })
  current.current = { editor, saving }
  const issues = editor ? validateGraph(editor.graph) : []
  const dirty = !!editor && editorDirty(editor)
  const busy = saving || opening

  useEffect(() => { void useWorkflowStore.getState().loadCatalog() }, [])
  useEffect(() => {
    const guard = () => {
      if (current.current.saving || openingRef.current) {
        setNotice('正在保存或读取流水线，请稍候再离开。')
        return false
      }
      if (current.current.editor && editorDirty(current.current.editor)
          && !window.confirm('流水线有未保存的修改。离开后将放弃这些修改，工作台素材草稿会保留。继续离开？')) return false
      useWorkflowStore.getState().closeEditor()
      return true
    }
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (current.current.saving || current.current.editor && editorDirty(current.current.editor)) {
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
    if (!useNavStore.getState().confirmLeaveCurrentPage()) return
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

  return <div className="workflow-presets">
    <header className="wfp-header">
      <div><p className="wfp-eyebrow">流水线预设</p><h1>{editor ? editor.preset ? '编辑流水线' : '新建流水线' : '流水线编辑器'}</h1>
        <p className="wfp-description">在这里定义可复用的结构。工作台负责选择流水线、绑定素材与调整本次运行参数。</p></div>
      <button type="button" className="wfp-button" disabled={busy} onClick={goBack}>返回{editor?.returnTo === 'workbench' ? '工作台' : '设置'}</button>
    </header>
    <section className="wfp-catalog" aria-label="选择要编辑的流水线">
      <label><span>已保存流水线</span><select aria-label="已保存流水线" value={catalogId} disabled={busy || catalogLoading} onChange={event => setCatalogId(event.target.value)}>
        <option value="">{catalogLoading ? '正在读取目录…' : catalog.length ? '选择流水线' : '还没有已保存流水线'}</option>
        {catalog.map(preset => <option key={preset.id} value={preset.id}>{preset.label}{'graph' in preset ? preset.builtin ? ' · 内置' : ' · 自定义' : ' · 旧版流程'}</option>)}
      </select></label>
      <button type="button" className="wfp-button" disabled={busy || !selected} onClick={() => void openPreset()}>{opening ? '正在转换…' : selected && !('graph' in selected) ? '转换为节点草稿' : '打开编辑'}</button>
      <button type="button" className="wfp-button" disabled={busy} onClick={() => void openPreset(true)}>新建流水线</button>
    </section>
    {catalogError && <div className="wfp-alert" role="alert">目录读取失败：{catalogError} <button type="button" disabled={catalogLoading || busy} onClick={() => void workflow.loadCatalog()}>重试</button></div>}
    {notice && <p className="wfp-alert" role="status">{notice}</p>}
    {error && <p className="wfp-alert" role="alert">{error} 当前草稿已保留；可调整后重试，或另存为新预设。</p>}
    {!editor ? <section className="wfp-empty"><h2>把常用流程保存一次，之后重复使用</h2><p>选择一个已保存流水线，或从空白开始添加模块。旧版流程需显式转换，原预设会保留。</p><button type="button" className="wfp-button is-primary" disabled={busy} onClick={() => void openPreset(true)}>创建第一条节点流水线</button></section> : <>
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
      <footer className="wfp-footer"><div><strong>{issues.length ? `${issues.length} 项结构问题需处理` : '可保存结构与默认参数'}</strong><p>保存不会启动执行。实际文件、声音预设与引擎可用性在工作台检查。</p></div>
        <div className="wfp-actions"><button type="button" className="wfp-button" disabled={busy} onClick={goBack}>取消并返回</button>
          {editor.preset && !editor.preset.builtin && <button type="button" className="wfp-button" disabled={busy || !!issues.length || !editor.label.trim()} onClick={() => void save('copy')}>另存为新预设</button>}
          <button type="button" className="wfp-button is-primary" disabled={busy || !!issues.length || !editor.label.trim()} onClick={() => void save(editor.preset && !editor.preset.builtin ? 'update' : 'copy')}>{saving ? '正在保存…' : editor.preset?.builtin ? '保存副本并返回' : '保存并返回'}</button>
        </div>
      </footer>
    </>}
  </div>
}
