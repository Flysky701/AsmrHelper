import { confirmAction } from '@/utils/confirmAction'
import { useEffect, useRef, useState } from 'react'
import { settingsApi } from '@/api/settings'
import type { SettingsView } from '@/api/settings'
import type { GraphPresetItem, PresetItem } from '@/api/types'
import { GRAPH_CATALOG } from '@/domain/workflowGraph'
import { editorDirty } from '@/domain/workflowDraft'
import { useFileSelector } from '@/hooks/useFileSelector'
import { useNavStore } from '@/stores/navStore'
import { presetDeleteConfirmation, useWorkflowStore } from '@/stores/workflowStore'
import './Settings.css'

type Preset = PresetItem | GraphPresetItem
type Paths = SettingsView['paths']
type Category = 'presets' | 'paths'
type CatalogTab = 'active' | 'builtin' | 'custom'
const EMPTY_PATHS: Paths = { output_dir: '', vtt_dir: '', model_cache_dir: '', temp_dir: '' }
const PATH_FIELDS: { key: keyof Paths; label: string; placeholder: string; hint: string; compatibility?: boolean }[] = [
  { key: 'output_dir', label: '输出目录', placeholder: '留空使用工作区 / output', hint: '默认结果位置；任务指定的输出位置优先。' },
  { key: 'vtt_dir', label: 'VTT 字幕目录', placeholder: '留空保留默认配置', hint: '兼容字段；节点流水线仍在工作台指定字幕输入。', compatibility: true },
  { key: 'model_cache_dir', label: '模型缓存目录', placeholder: '留空使用工作区 / models', hint: '修改目录不会搬移已安装的模型文件。' },
  { key: 'temp_dir', label: '临时文件目录', placeholder: '留空使用工作区 / debug / runtime', hint: '供工作区会话存放处理中间文件。' },
]
const reason = (error: unknown) => error instanceof Error ? error.message : String(error)
const inputs = (preset: Preset) => 'graph' in preset ? preset.graph.input_slots.map(slot => slot.label).join(' + ') || '未定义输入' : '在编辑页确认输入'
const outputs = (preset: Preset) => 'graph' in preset ? preset.graph.outputs.map(output => output.label || `${output.node_id} · ${output.port === 'audio' ? '音频' : '字幕'}`).join(' / ') || '未定义产出' : preset.outputs.map(stage => GRAPH_CATALOG[stage as keyof typeof GRAPH_CATALOG]?.label || stage).join(' / ')

function Icon({ kind }: { kind: 'graph' | 'folder' | 'refresh' | 'plus' | 'search' }) {
  return <svg viewBox="0 0 20 20" aria-hidden="true">{kind === 'graph' ? <path d="M2 3h6v6H2zM12 11h6v6h-6zM8 6h7v5M5 9v5h7" /> : kind === 'folder' ? <path d="M2 5h6l2 2h8v9H2zM2 5V3h6l2 2" /> : kind === 'refresh' ? <path d="M16 7a6 6 0 1 0 0 7M16 3v4h-4" /> : kind === 'plus' ? <path d="M10 3v14M3 10h14" /> : <><circle cx="8" cy="8" r="5" /><path d="m12 12 5 5" /></>}</svg>
}

export default function Settings() {
  const workflow = useWorkflowStore()
  const { selectFolder } = useFileSelector()
  const [category, setCategory] = useState<Category>('presets')
  const [catalogTab, setCatalogTab] = useState<CatalogTab>('active')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [notice, setNotice] = useState('')
  const [actionError, setActionError] = useState('')
  const [working, setWorking] = useState(false)
  const [modal, setModal] = useState<{ kind: 'copy' | 'restore'; preset: Preset; label: string } | null>(null)
  const dialog = useRef<HTMLDialogElement>(null)
  const [paths, setPaths] = useState<Paths>(EMPTY_PATHS)
  const [savedPaths, setSavedPaths] = useState<Paths | null>(null)
  const [pathsLoading, setPathsLoading] = useState(false)
  const [pathsSaving, setPathsSaving] = useState(false)
  const [pathsLoadError, setPathsLoadError] = useState('')
  const [pathsMessage, setPathsMessage] = useState('')
  const [pathsSaveError, setPathsSaveError] = useState(false)
  const [browsing, setBrowsing] = useState<keyof Paths | null>(null)
  const mounted = useRef(true), loadGeneration = useRef(0), actionRef = useRef(false)
  const versions = useRef({ output_dir: 0, vtt_dir: 0, model_cache_dir: 0, temp_dir: 0 })
  const pathState = useRef({ paths, savedPaths, pathsSaving, browsing })
  pathState.current = { paths, savedPaths, pathsSaving, browsing }
  const dirty = !!savedPaths && PATH_FIELDS.some(field => paths[field.key] !== savedPaths[field.key])
  const navigation = useRef({ dirty, busy: false })
  const busy = working || workflow.saving || pathsSaving || browsing !== null
  navigation.current = { dirty, busy: busy || modal !== null }
  const guardRef = useRef<(() => Promise<boolean>) | null>(null)
  const catalogBusy = busy || workflow.catalogLoading || workflow.archivedLoading
  const builtinArchive = workflow.archivedCatalog.filter(preset => preset.builtin)
  const customArchive = workflow.archivedCatalog.filter(preset => !preset.builtin)
  const catalog = catalogTab === 'active' ? workflow.catalog : catalogTab === 'builtin' ? builtinArchive : customArchive
  const filtered = catalog.filter(preset => preset.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  // A disappearing selection stays unselected; it never chooses another workflow to run.
  const selected = filtered.find(preset => preset.id === selectedId) || null
  const catalogError = catalogTab === 'active' ? workflow.catalogError : workflow.archivedError

  async function loadPaths() {
    if (pathState.current.pathsSaving || pathState.current.browsing) return
    const generation = ++loadGeneration.current, readVersions = { ...versions.current }
    const previous = pathState.current.savedPaths
    setPathsLoading(true); setPathsLoadError('')
    try {
      const response = await settingsApi.get()
      if (!mounted.current || generation !== loadGeneration.current) return
      const fresh = response.settings.paths
      setSavedPaths({ ...fresh })
      setPaths(current => Object.fromEntries(PATH_FIELDS.map(({ key }) => [key,
        versions.current[key] === readVersions[key] && (previous === null || current[key] === previous[key]) ? fresh[key] : current[key],
      ])) as Paths)
    } catch (error) {
      if (mounted.current && generation === loadGeneration.current) setPathsLoadError(`无法读取路径设置：${reason(error)}。当前输入已保留。`)
    } finally { if (mounted.current && generation === loadGeneration.current) setPathsLoading(false) }
  }

  useEffect(() => {
    mounted.current = true
    void useWorkflowStore.getState().loadCatalog()
    void useWorkflowStore.getState().loadArchivedCatalog()
    void loadPaths()
    return () => { mounted.current = false; loadGeneration.current++ }
  }, [])
  useEffect(() => {
    const guard = async () => {
      if (navigation.current.busy || actionRef.current) { setNotice('正在处理设置，请稍候再离开。'); return false }
      return !navigation.current.dirty || await confirmAction('路径有未保存的修改。离开设置页将放弃这些路径修改，继续离开？')
    }
    guardRef.current = guard
    useNavStore.getState().setNavigationGuard(guard)
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (navigation.current.dirty || navigation.current.busy || actionRef.current) { event.preventDefault(); event.returnValue = '' }
    }
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      if (useNavStore.getState().navigationGuard === guard) useNavStore.getState().setNavigationGuard(null)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [])
  useEffect(() => { if (modal && dialog.current && !dialog.current.open) dialog.current.showModal() }, [modal?.kind, modal?.preset.id])

  async function openEditor(preset?: Preset) {
    if (catalogBusy || actionRef.current || (preset && workflow.catalogError)) return
    if (!(await useNavStore.getState().confirmLeaveCurrentPage())) return
    const current = useWorkflowStore.getState().editor
    const keepCurrent = !!current && !!preset && current.preset?.id === preset.id && editorDirty(current)
    if (!keepCurrent && editorDirty(current) && !await confirmAction('已有未保存的流水线草稿。打开新的编辑内容会替换该草稿；工作台素材和运行参数保留。继续？')) return
    actionRef.current = true; setWorking(true); setActionError('')
    try {
      if (!keepCurrent) {
        if (!preset || 'graph' in preset) useWorkflowStore.getState().openEditor(preset || null, 'settings')
        else {
          await useWorkflowStore.getState().openLegacyEditor(preset, 'settings')
          if (!mounted.current) return
          const next = useWorkflowStore.getState()
          if (next.error || !next.editor || next.editor === current) { setActionError(next.error || '转换未完成，原草稿已保留。'); return }
        }
      }
      if (!mounted.current) return
      if (useNavStore.getState().navigationGuard === guardRef.current) useNavStore.getState().setNavigationGuard(null)
      useNavStore.getState().setPage('workflow-presets')
    } finally { actionRef.current = false; if (mounted.current) setWorking(false) }
  }

  async function deletePreset(preset: Preset) {
    if (catalogBusy || catalogError || actionRef.current || !await confirmAction(presetDeleteConfirmation(preset))) return
    actionRef.current = true; setWorking(true); setActionError(''); setNotice('')
    try {
      const result = await useWorkflowStore.getState().deleteCatalogPreset(preset)
      if (!mounted.current) return
      if (result) {
        setSelectedId(current => current === preset.id ? null : current)
        setNotice(result === 'archived' ? `内置预设“${preset.label}”已从目录删除，可在“恢复内置预设”中恢复。`
          : result === 'already_missing' ? `“${preset.label}”已不存在，目录引用已清除。`
          : `自定义预设“${preset.label}”已永久删除，不能恢复。当前草稿与已提交任务保留。`)
      } else setActionError(useWorkflowStore.getState().error || '删除未完成，请刷新目录后重试。')
    } finally { actionRef.current = false; if (mounted.current) setWorking(false) }
  }

  async function submitModal() {
    if (!modal || !modal.label.trim() || catalogBusy || actionRef.current) return
    const submitted = modal
    actionRef.current = true; setWorking(true); setActionError(''); setNotice('')
    try {
      const result = submitted.kind === 'copy'
        ? await useWorkflowStore.getState().copyPreset(submitted.preset.id, submitted.label.trim())
        : await useWorkflowStore.getState().restorePreset(submitted.preset.id, submitted.preset.revision, submitted.label.trim())
      if (!mounted.current) return
      if (result) {
        setNotice(`${submitted.kind === 'copy' ? '副本' : '预设'}“${result.label}”已保存到当前目录；当前草稿和工作台参数保持不变。`)
        dialog.current?.close(); setModal(null)
      } else setActionError(useWorkflowStore.getState().error || '未能保存，请重试。')
    } finally { actionRef.current = false; if (mounted.current) setWorking(false) }
  }

  function changePath(key: keyof Paths, value: string) {
    versions.current[key]++
    setPaths(current => ({ ...current, [key]: value }))
    setPathsMessage('')
  }
  async function browse(key: keyof Paths) {
    if (busy || !savedPaths || pathsLoadError) return
    const version = versions.current[key]
    setBrowsing(key); actionRef.current = true
    try {
      const value = await selectFolder()
      if (!mounted.current || value === null) return
      if (version === versions.current[key]) changePath(key, value)
      else { setPathsMessage('选择文件夹期间该字段已有修改，已保留最新输入。'); setPathsSaveError(false) }
    } catch (error) { if (mounted.current) { setPathsMessage(`选择失败：${reason(error)}`); setPathsSaveError(true) } }
    finally { actionRef.current = false; if (mounted.current) setBrowsing(null) }
  }
  async function savePaths() {
    if (busy || pathsLoading || pathsLoadError || !savedPaths || !dirty || actionRef.current) return
    const changed = Object.fromEntries(PATH_FIELDS.filter(({ key }) => paths[key] !== savedPaths[key]).map(({ key }) => [key, paths[key]]))
    const submittedVersions = { ...versions.current }, previous = savedPaths
    actionRef.current = true; setPathsSaving(true); setPathsMessage(''); setPathsSaveError(false)
    try {
      const validation = await settingsApi.validate({ paths: changed })
      if (!mounted.current) return
      if (!validation.valid) { setPathsMessage(`验证失败：${validation.errors.join('；')}`); setPathsSaveError(true); return }
      const response = await settingsApi.update({ paths: changed })
      if (!mounted.current) return
      const fresh = response.settings.paths
      setSavedPaths({ ...fresh })
      setPaths(current => Object.fromEntries(PATH_FIELDS.map(({ key }) => [key,
        versions.current[key] === submittedVersions[key] && (key in changed || current[key] === previous[key]) ? fresh[key] : current[key],
      ])) as Paths)
      setPathsMessage('路径已保存，已有文件未移动。')
    } catch (error) { if (mounted.current) { setPathsMessage(`保存失败：${reason(error)}。当前输入已保留。`); setPathsSaveError(true) } }
    finally { actionRef.current = false; if (mounted.current) setPathsSaving(false) }
  }

  const openModal = (kind: 'copy' | 'restore', preset: Preset) => {
    if (catalogBusy || catalogError) return
    setActionError(''); setModal({ kind, preset, label: kind === 'copy' ? `${preset.label.slice(0, 96)}（副本）` : preset.label })
  }
  return <div className="settings-page">
    <aside className="settings-sidebar"><h1 className="page-title">设置</h1><p className="settings-sidebar-caption">工作区</p>
      <nav className="settings-categories" aria-label="设置分类">
        <button type="button" aria-current={category === 'presets' ? 'page' : undefined} onClick={() => setCategory('presets')}><Icon kind="graph" /><span>预设管理<small>复用流水线</small></span></button>
        <button type="button" aria-current={category === 'paths' ? 'page' : undefined} onClick={() => setCategory('paths')}><Icon kind="folder" /><span>文件与缓存<small>输出与存储位置</small></span></button>
      </nav><p className="settings-sidebar-foot">● 与工作台共用</p>
    </aside>
    <main className="settings-main" aria-label="设置内容">
      <header className="settings-header page-heading"><div className="page-heading__copy"><h2 className="panel-title">{category === 'presets' ? '预设管理' : '文件与缓存'}</h2><p className="settings-description page-description">{category === 'presets' ? '工作台共用的流水线，集中查看与维护。' : '留空沿用工作区默认位置。'}</p></div>
        <div className="settings-header-actions page-heading__actions">{category === 'presets' ? <><button className="settings-button quiet" disabled={catalogBusy} onClick={() => { void Promise.all([workflow.loadCatalog(), workflow.loadArchivedCatalog()]) }}><Icon kind="refresh" />刷新</button><button className="settings-button primary" disabled={catalogBusy} onClick={() => void openEditor()}><Icon kind="plus" />新建流水线</button></> : <button className="settings-button quiet" disabled={busy || pathsLoading} onClick={() => void loadPaths()}><Icon kind="refresh" />重新读取</button>}</div>
      </header>
      <div className="settings-body">
        {category === 'presets' ? <>
          {(notice || workflow.catalogNotice) && <p className="settings-status" role="status">{notice || workflow.catalogNotice}</p>}
          {actionError && !modal && <p className="settings-status error" role="alert">{actionError}</p>}
          <div className="settings-catalog-toolbar"><nav className="settings-catalog-tabs" aria-label="预设目录">
            <button aria-current={catalogTab === 'active' ? 'page' : undefined} onClick={() => { setCatalogTab('active'); setSelectedId(null) }}>当前目录 <small>{workflow.catalog.length}</small></button>
            <button aria-current={catalogTab === 'builtin' ? 'page' : undefined} onClick={() => { setCatalogTab('builtin'); setSelectedId(null) }}>恢复内置预设 <small>{builtinArchive.length}</small></button>
            {!!customArchive.length && <button aria-current={catalogTab === 'custom' ? 'page' : undefined} onClick={() => { setCatalogTab('custom'); setSelectedId(null) }}>以前移出的自定义 <small>{customArchive.length}</small></button>}
          </nav><label className="settings-search"><Icon kind="search" /><input aria-label="搜索预设" placeholder="搜索流水线名称" value={query} onChange={event => setQuery(event.target.value)} /></label></div>
          {catalogError && <p className="settings-status error" role="alert">目录读取失败：{catalogError}。已保留上次列表，读取成功前暂停修改。</p>}
          {(workflow.catalogLoading || workflow.archivedLoading) && <p className="settings-status" role="status">正在读取共享目录…</p>}
          {catalogTab !== 'active' && <p className="settings-archive-hint">{catalogTab === 'builtin' ? '内置定义保留，可改名恢复到目录。' : '这里保留以前移出的自定义预设；本轮自定义“删除”会永久删除定义。'}恢复不会自动选择或启动流水线。</p>}
          <div className="settings-preset-layout"><section className="settings-catalog-list" aria-label="流水线列表">
            <div className="settings-list-heading"><span>{catalogTab === 'active' ? '可用流水线' : '可恢复的流水线'}</span><span>{filtered.length} 个预设</span></div>
            {filtered.map(preset => <article className={`settings-preset-row${selected?.id === preset.id ? ' selected' : ''}`} key={preset.id}>
              <button type="button" className="settings-preset-summary" aria-label={`查看 ${preset.label}`} aria-pressed={selected?.id === preset.id} onClick={() => setSelectedId(preset.id)}><span className="settings-preset-title"><strong>{preset.label}</strong><Icon kind="graph" /></span><span className="settings-preset-flow">{inputs(preset)} → {outputs(preset)}</span><span className="settings-preset-meta"><span className={`settings-chip${preset.builtin ? '' : ' custom'}`}>{preset.builtin ? '内置' : '自定义'}</span><span>{'graph' in preset ? `${preset.graph.nodes.length} 个节点` : '旧版流程'}</span><span>· 修订 {preset.revision}</span></span></button>
              <div className="settings-row-actions">{catalogTab === 'active' ? <><button className="settings-text-button" disabled={catalogBusy || !!catalogError} onClick={() => void openEditor(preset)}>{preset.builtin ? '另存编辑' : '编辑'}</button><button className="settings-text-button" disabled={catalogBusy || !!catalogError} onClick={() => openModal('copy', preset)}>复制</button></> : <button className="settings-text-button" disabled={catalogBusy || !!catalogError} onClick={() => openModal('restore', preset)}>恢复到目录</button>}{(catalogTab === 'active' || !preset.builtin) && <button className="settings-text-button danger" disabled={catalogBusy || !!catalogError} aria-label={`删除 ${preset.label}`} onClick={() => void deletePreset(preset)}>删除</button>}</div>
            </article>)}
            {!filtered.length && !workflow.catalogLoading && !workflow.archivedLoading && <div className="settings-empty"><Icon kind="folder" /><strong>{query ? '没有匹配的流水线' : catalogTab === 'active' ? '当前目录为空' : '没有可恢复的预设'}</strong><p>{catalogTab === 'active' ? '新建流水线，或恢复已有内置预设。' : '恢复后会回到当前目录，不会自动打开。'}</p></div>}
            <p className="settings-bottom-note">删除内置预设后可恢复；自定义预设删除后不可恢复。已有任务和产物不受影响。</p>
          </section>
          <aside className="settings-definition" aria-label="所选预设概览">{selected ? <>
            <p className="settings-definition-label">所选流水线</p><h3>{selected.label}</h3><p>{selected.description || '暂无说明'}</p>
            {'graph' in selected && <div className="settings-flow-preview"><div className="settings-flow-label"><span>流程概览</span><span>{selected.graph.nodes.length} 节点 · {selected.graph.input_slots.length} 输入</span></div><div className="settings-flow-slots">{selected.graph.input_slots.map(slot => <span key={slot.id}>{slot.label}</span>)}</div><div className="settings-flow-nodes">{selected.graph.nodes.map(node => <span className="settings-flow-node" key={node.id}><strong>{GRAPH_CATALOG[node.kind]?.label || node.kind}</strong><small>{node.id}</small></span>)}</div><p className="settings-flow-output">{outputs(selected)}</p></div>}
            <dl><div><dt>适用输入</dt><dd>{inputs(selected)}</dd></div><div><dt>交付内容</dt><dd>{outputs(selected)}</dd></div><div><dt>来源</dt><dd>{selected.builtin ? '内置 · 另存后编辑' : '自定义'} · 修订 {selected.revision}</dd></div></dl><div className="settings-definition-footer"><small>不绑定实际文件，不启动任务</small><button className="settings-text-button" disabled={catalogBusy || !!catalogError} onClick={() => catalogTab === 'active' ? void openEditor(selected) : openModal('restore', selected)}>{catalogTab === 'active' ? selected.builtin ? '另存并编辑 ↗' : '编辑流水线 ↗' : '恢复到目录'}</button></div>
          </> : <div className="settings-empty"><Icon kind="graph" /><strong>选择一个流水线</strong><p>查看输入、节点与交付内容。</p></div>}</aside></div>
        </> : <>
          {pathsLoading && <p className="settings-status" role="status">正在读取路径…</p>}
          {pathsLoadError && <p className="settings-status error" role="alert">{pathsLoadError}<button onClick={() => void loadPaths()} disabled={pathsLoading || busy}>重试</button></p>}
          {pathsMessage && <p className={`settings-status${pathsSaveError ? ' error' : ''}`} role={pathsSaveError ? 'alert' : 'status'}>{pathsMessage}</p>}
          {[0, 2].map(start => <section className="settings-path-section" key={start}><h3><Icon kind="folder" />{start === 0 ? '输出与字幕' : '模型与临时文件'}</h3>{PATH_FIELDS.slice(start, start + 2).map(field => <div className="settings-path-field" key={field.key}><div className="settings-field-label"><label htmlFor={`settings-${field.key}`}>{field.label}</label>{field.compatibility && <span>兼容</span>}</div><div className="settings-path-row"><input id={`settings-${field.key}`} value={paths[field.key]} disabled={!savedPaths || pathsSaving || !!pathsLoadError} placeholder={field.placeholder} autoComplete="off" spellCheck={false} onChange={event => changePath(field.key, event.target.value)} /><button className="settings-button" disabled={!savedPaths || busy || !!pathsLoadError} aria-label={`浏览${field.label}`} onClick={() => void browse(field.key)}><Icon kind="folder" />{browsing === field.key ? '选择中…' : '浏览'}</button></div><p>{field.hint}</p></div>)}</section>)}
          <p className="settings-paths-summary">模型安装和服务连接仍在“引擎与资源”管理。这里只配置目录，不移动或删除现有文件。</p>
        </>}
      </div>
      {category === 'paths' ? <footer className="settings-save-bar"><span className={dirty ? 'changed' : ''}>● {dirty ? '有未保存的修改' : savedPaths ? '使用已保存的路径' : '尚未读取路径'}</span><div><button className="settings-button quiet" disabled={!dirty || busy || pathsLoading} onClick={() => { if (savedPaths) { PATH_FIELDS.forEach(({ key }) => versions.current[key]++); setPaths({ ...savedPaths }); setPathsMessage('') } }}>放弃修改</button><button className="settings-button primary" disabled={!dirty || busy || pathsLoading || !!pathsLoadError} onClick={() => void savePaths()}>{pathsSaving ? '正在保存…' : '保存路径'}</button></div></footer> : <footer className="settings-footnote"><span>预设与工作台共用</span><span>节点、连线与参数在流水线编辑页维护</span></footer>}
    </main>
    {modal && <dialog ref={dialog} className="settings-dialog" aria-labelledby="settings-dialog-title" onCancel={event => { if (busy) event.preventDefault(); else setModal(null) }} onClose={() => { if (!busy) setModal(null) }}><form onSubmit={event => { event.preventDefault(); void submitModal() }}><header><h2 id="settings-dialog-title">{modal.kind === 'copy' ? '复制流水线' : '恢复到当前目录'}</h2><p>{modal.preset.label} · 修订 {modal.preset.revision}</p></header><div className="settings-dialog-body"><label htmlFor="settings-preset-name">{modal.kind === 'copy' ? '副本名称' : '恢复名称'}</label><input id="settings-preset-name" autoFocus maxLength={100} value={modal.label} disabled={busy} onChange={event => setModal(current => current ? { ...current, label: event.target.value } : null)} /><p>{modal.kind === 'copy' ? '复制已保存的结构。当前编辑草稿、素材与工作台参数保持不变。' : '恢复不会自动打开或执行。若名称冲突，请改名后重试，不会覆盖已有预设。'}</p>{actionError && <p className="settings-status error" role="alert">{actionError}</p>}</div><footer><button type="button" className="settings-button" disabled={busy} onClick={() => { dialog.current?.close(); setModal(null) }}>取消</button><button className="settings-button primary" disabled={catalogBusy || !modal.label.trim()}>{working ? '正在处理…' : modal.kind === 'copy' ? '保存副本' : '恢复到目录'}</button></footer></form></dialog>}
  </div>
}
